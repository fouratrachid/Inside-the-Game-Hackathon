"""Split Markdown by headings into ~300–500-token chunks with overlap."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Chunk:
    id: str
    source: str
    heading: str
    text: str


def approx_tokens(text: str) -> int:
    """Cheap token estimate (≈1.3 tokens per word) so chunking needs no tokenizer."""
    return round(len(text.split()) * 1.3)


def _sections(markdown: str):
    title, heading, lines = "", "", []
    for line in markdown.splitlines():
        match = re.match(r"^(#{1,3})\s+(.*)", line)
        if match:
            if lines and "".join(lines).strip():
                yield heading or title, "\n".join(lines).strip()
            if len(match.group(1)) == 1:
                title = match.group(2).strip()
            heading = f"{title} › {match.group(2).strip()}" if len(match.group(1)) > 1 else title
            lines = []
        else:
            lines.append(line)
    if lines and "".join(lines).strip():
        yield heading or title, "\n".join(lines).strip()


def chunk_markdown(
    markdown: str, source: str, max_tokens: int = 450, overlap_tokens: int = 60
) -> list[Chunk]:
    """Heading-aware chunks; long sections are windowed by words with overlap."""
    chunks = []
    max_words = max(20, int(max_tokens / 1.3))
    overlap_words = int(overlap_tokens / 1.3)
    for heading, body in _sections(markdown):
        words = body.split()
        start = 0
        while start < len(words):
            piece = " ".join(words[start : start + max_words])
            digest = hashlib.sha256(f"{source}|{heading}|{start}|{piece}".encode()).hexdigest()
            chunks.append(Chunk(digest[:24], source, heading, f"{heading}\n{piece}"))
            if start + max_words >= len(words):
                break
            start += max_words - overlap_words
    return chunks


def load_corpus(folder: Path) -> list[Chunk]:
    chunks = []
    for path in sorted(folder.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        chunks.extend(chunk_markdown(path.read_text(encoding="utf-8"), f"knowledge/{path.name}"))
    return chunks
