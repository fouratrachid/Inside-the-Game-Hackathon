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
    assert "cite the source files" in model.calls[2][-1].content  # First try lacked sources.


def test_invented_sources_are_rejected(kb):
    bad = final("Field tilt is made up.")
    bad.content = bad.content[:-1] + ', "cited_sources": ["knowledge/secret.md"]}'
    again = final("Still made up.")
    again.content = again.content[:-1] + ', "cited_sources": ["knowledge/secret.md"]}'
    with pytest.raises(HTTPException) as error:
        ask(kb, tool_call(("lookup_definition", {"query": "field tilt"})), bad, again)
    assert error.value.status_code == 502
