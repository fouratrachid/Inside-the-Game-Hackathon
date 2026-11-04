import asyncio
import json
from pathlib import Path

import pytest
from conftest import ScriptedModel, final, synthetic_session, tool_call, tool_results
from fastapi import HTTPException

from app.agent.service import MatchAgent
from app.config import Settings
from app.rag.chunking import approx_tokens, chunk_markdown, load_corpus
from app.rag.embeddings import HashEmbedder
from app.rag.ingest import ingest
from app.rag.knowledge import KnowledgeBase
from app.rag.store import ChromaStore

KNOWLEDGE = Path(__file__).resolve().parents[1] / "knowledge"


@pytest.fixture(scope="module")
def kb(tmp_path_factory):
    store = ChromaStore(tmp_path_factory.mktemp("chroma"), "test")
    ingest(store, HashEmbedder(), KNOWLEDGE)
    return KnowledgeBase(store, HashEmbedder(), top_k=3)


def test_chunks_follow_headings_and_size_limits():
    text = "# Title\nintro\n## Part A\n" + "word " * 900 + "\n## Part B\nshort"
    chunks = chunk_markdown(text, "knowledge/x.md", max_tokens=450, overlap_tokens=60)
    headings = [c.heading for c in chunks]
    assert headings[0] == "Title" and headings[-1] == "Title › Part B"
    part_a = [c for c in chunks if c.heading == "Title › Part A"]
    assert len(part_a) >= 3 and all(approx_tokens(c.text) <= 470 for c in part_a)
    corpus = load_corpus(KNOWLEDGE)
    assert {c.source for c in corpus} >= {"knowledge/xt.md", "knowledge/field-tilt.md"}
    assert all(c.source != "knowledge/README.md" for c in corpus)


def test_ingestion_is_idempotent_and_removes_stale_chunks(tmp_path):
    folder = tmp_path / "knowledge"
    folder.mkdir()
    (folder / "a.md").write_text("# A\n## One\nalpha beta\n## Two\ngamma delta")
    store = ChromaStore(tmp_path / "db", "idem")
    first = ingest(store, HashEmbedder(), folder)
    second = ingest(store, HashEmbedder(), folder)
    assert first["total"] == second["total"] == 2 and second["removed"] == 0
    (folder / "a.md").write_text("# A\n## One\nalpha beta")
    third = ingest(store, HashEmbedder(), folder)
    assert third["total"] == 1 and third["removed"] == 1


def test_field_tilt_query_retrieves_the_field_tilt_definition(kb):
    hits = kb.search("what is field tilt")
    assert hits[0]["source"] == "knowledge/field-tilt.md"
    assert "attacking third" in " ".join(h["text"] for h in hits)
    assert kb.search("expected threat grid")[0]["source"] == "knowledge/xt.md"


def ask(kb, *script, question="What does field tilt mean?"):
    session, _ = synthetic_session(limit=120)
    model = ScriptedModel(script=list(script))
    agent = MatchAgent(Settings(gemini_api_key="k"), model, knowledge=kb)
    return asyncio.run(agent.ask(question, "simple", session)), model


def test_definition_questions_use_lookup_and_cite_sources(kb):
    def answer(messages):
        chunks = tool_results(messages, "lookup_definition")[0]["chunks"]
        source = chunks[0]["source"]
        return final(f"Field tilt is the share of attacking-third passes ({source}).", minute=0)

    def with_source(messages):
        message = answer(messages)
        data = json.loads(message.content)
        data["cited_sources"] = ["knowledge/field-tilt.md"]
        message.content = json.dumps(data)
        return message

    result, model = ask(
        kb, tool_call(("lookup_definition", {"query": "field tilt"})), answer, with_source
    )
    assert "lookup_definition" in model.bound_tools
    assert result["tools_used"][0]["tool"] == "lookup_definition"
    assert result["cited_sources"] == ["knowledge/field-tilt.md"]
    assert "cite the source files" in model.calls[2][-2].content  # First try lacked sources.


def test_invented_sources_are_rejected(kb):
    bad = final("Field tilt is made up.")
    bad.content = bad.content[:-1] + ', "cited_sources": ["knowledge/secret.md"]}'
    again = final("Still made up.")
    again.content = again.content[:-1] + ', "cited_sources": ["knowledge/secret.md"]}'
    with pytest.raises(HTTPException) as error:
        ask(kb, tool_call(("lookup_definition", {"query": "field tilt"})), bad, again)
    assert error.value.status_code == 502


def test_prompt_restricts_sources_to_retrieved_paths():
    from app.agent.graph import SYSTEM_PROMPT

    assert "ONLY exact paths that lookup_definition returned" in SYSTEM_PROMPT
    assert "cited_sources is []" in SYSTEM_PROMPT
    assert "knowledge/<file>.md" not in SYSTEM_PROMPT  # The template invited invented names.


def test_retrieved_paths_are_shown_before_the_answer(kb):
    def answer(messages):
        note = messages[-1].content
        assert note.startswith("Allowed cited_sources (exact paths")
        allowed = json.loads(note.split(": ", 1)[1].rsplit(". Cite", 1)[0])
        assert "knowledge/field-tilt.md" in allowed
        message = final("Field tilt is the share of attacking-third passes.")
        data = json.loads(message.content)
        data["cited_sources"] = allowed[:1]
        message.content = json.dumps(data)
        return message

    result, _ = ask(kb, tool_call(("lookup_definition", {"query": "field tilt"})), answer)
    assert result["cited_sources"]


def test_without_lookup_the_model_is_told_sources_must_be_empty(kb):
    def answer(messages):
        assert "Allowed cited_sources: none" in messages[-1].content
        return final("It is level.")

    ask(kb, tool_call(("get_match_stats", {})), answer, question="What is the score?")


def test_retry_message_names_the_allowed_sources(kb):
    bad = final("Field tilt.")
    bad.content = bad.content[:-1] + ', "cited_sources": ["knowledge/get_match_stats.md"]}'

    def fixed(messages):
        retry = messages[-2].content  # [-1] is the per-turn sources note.
        assert "['knowledge/get_match_stats.md'] were not retrieved" in retry
        assert "knowledge/field-tilt.md" in retry and "Cite only paths from this list" in retry
        message = final("Field tilt.")
        data = json.loads(message.content)
        data["cited_sources"] = ["knowledge/field-tilt.md"]
        message.content = json.dumps(data)
        return message

    result, _ = ask(kb, tool_call(("lookup_definition", {"query": "field tilt"})), bad, fixed)
    assert result["cited_sources"] == ["knowledge/field-tilt.md"]


def test_definition_question_cannot_be_answered_from_memory(kb):
    from app.agent.graph import DEFINITION_UNAVAILABLE

    memory = final("Field tilt is the share of possession in the opponent's half.")

    def admits(messages):
        assert "definition question" in messages[-2].content
        return final(DEFINITION_UNAVAILABLE)

    empty = type("Empty", (), {"search": lambda self, query, k=None: []})()
    result, _ = ask(
        empty, tool_call(("lookup_definition", {"query": "field tilt"})), memory, admits
    )
    assert result["text"] == DEFINITION_UNAVAILABLE and result["cited_sources"] == []


def test_definition_question_from_memory_fails_after_retry_when_lookup_errors():
    class Broken:
        def search(self, query, k=None):
            raise ValueError("The definitions index is empty.")

    wrong = final("Field tilt is possession share.")
    with pytest.raises(HTTPException):
        ask(Broken(), tool_call(("lookup_definition", {"query": "x"})), wrong, wrong)


def test_definition_detector():
    from app.agent.graph import is_definition_question

    assert is_definition_question("What does field tilt mean?")
    assert is_definition_question("How is xG calculated?")
    assert not is_definition_question("Who has more xG?")


def test_empty_index_is_built_automatically(tmp_path, caplog):
    from app.rag.knowledge import LazyKnowledgeBase

    settings = Settings(rag_path=str(tmp_path / "db"), rag_embedder="hash")
    with caplog.at_level("WARNING"):
        hits = LazyKnowledgeBase(settings).search("what is field tilt")
    assert hits and "is empty; building it" in caplog.text
    assert LazyKnowledgeBase(settings).search("field tilt")  # Second open reuses it.


def test_failed_index_build_logs_the_fix(tmp_path, caplog, monkeypatch):
    from app.rag import ingest as ingest_module
    from app.rag.knowledge import LazyKnowledgeBase

    def broken(*args, **kwargs):
        raise OSError("no files")

    monkeypatch.setattr(ingest_module, "ingest", broken)
    settings = Settings(rag_path=str(tmp_path / "db"), rag_embedder="hash")
    with caplog.at_level("WARNING"), pytest.raises(ValueError):
        LazyKnowledgeBase(settings).search("xg")
    assert "python -m app.rag.ingest" in caplog.text


def test_app_startup_builds_the_index(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setenv("GAME_RAG_PATH", str(tmp_path / "db"))
    monkeypatch.setenv("GAME_RAG_BUILD_ON_STARTUP", "true")
    app = create_app()
    with TestClient(app):
        assert app.state.agent.knowledge._kb.store.count() > 0
