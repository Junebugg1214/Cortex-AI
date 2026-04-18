from __future__ import annotations

import re
from dataclasses import replace
from time import perf_counter

from .state import DocumentChunk, PipelineState

_CHAT_TURN_RE = re.compile(
    r"(?ims)^\s*(?P<speaker>user|assistant|system|human|ai|developer|tool|[A-Z][\w .-]{0,32})\s*:\s+"
)
_DOC_HEADING_RE = re.compile(r"(?m)^(?P<heading>#{1,6}\s+.+?)\s*$")
_CODE_SYMBOL_RE = re.compile(
    r"(?m)^\s*(?:async\s+def|def|class|function|export\s+function|export\s+class|const|let|var)\s+[\w$]+"
)
_TRANSCRIPT_UTTERANCE_RE = re.compile(r"(?m)^\s*(?:\[[0-9:.]+\]|\([0-9:.]+\)|[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)\s*")


def _line_span(start: int, text: str) -> str:
    line = text.count("\n", 0, start) + 1
    return f"line:{line}"


def _chunk(chunk_id: str, text: str, source_type: str, *, span: str, **metadata: object) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        text=text.strip(),
        source_type=source_type,
        source_span=span,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _split_by_matches(
    content: str,
    matches: list[re.Match[str]],
    *,
    source_type: str,
    prefix: str,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        text = content[match.start() : end].strip()
        if text:
            chunks.append(
                _chunk(
                    f"{prefix}-{index + 1}",
                    text,
                    source_type,
                    span=_line_span(match.start(), content),
                )
            )
    return chunks


def _split_chat(content: str) -> list[DocumentChunk]:
    matches = list(_CHAT_TURN_RE.finditer(content))
    if len(matches) < 2 and (not matches or matches[0].start() != 0):
        return []
    return _split_by_matches(content, matches, source_type="chat", prefix="turn")


def _split_doc(content: str) -> list[DocumentChunk]:
    matches = list(_DOC_HEADING_RE.finditer(content))
    if not matches:
        return []
    chunks: list[DocumentChunk] = []
    if matches[0].start() > 0 and content[: matches[0].start()].strip():
        chunks.append(_chunk("section-0", content[: matches[0].start()], "doc", span="line:1"))
    chunks.extend(_split_by_matches(content, matches, source_type="doc", prefix="section"))
    return chunks


def _split_code(content: str) -> list[DocumentChunk]:
    matches = list(_CODE_SYMBOL_RE.finditer(content))
    if not matches:
        return []
    chunks: list[DocumentChunk] = []
    if matches[0].start() > 0 and content[: matches[0].start()].strip():
        chunks.append(_chunk("module-0", content[: matches[0].start()], "code", span="line:1"))
    chunks.extend(_split_by_matches(content, matches, source_type="code", prefix="symbol"))
    return chunks


def _split_transcript(content: str) -> list[DocumentChunk]:
    matches = list(_TRANSCRIPT_UTTERANCE_RE.finditer(content))
    if not matches:
        return []
    return _split_by_matches(content, matches, source_type="transcript", prefix="utterance")


def _split_paragraphs(content: str, *, source_type: str, max_chars: int) -> list[DocumentChunk]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", content) if block.strip()]
    if not blocks:
        return []

    chunks: list[DocumentChunk] = []
    current: list[str] = []
    current_len = 0
    chunk_index = 1
    for block in blocks:
        next_len = current_len + len(block) + (2 if current else 0)
        if current and next_len > max_chars:
            text = "\n\n".join(current)
            chunks.append(_chunk(f"chunk-{chunk_index}", text, source_type, span=""))
            chunk_index += 1
            current = [block]
            current_len = len(block)
            continue
        current.append(block)
        current_len = next_len
    if current:
        chunks.append(_chunk(f"chunk-{chunk_index}", "\n\n".join(current), source_type, span=""))
    return chunks


def split_document(state: PipelineState, *, max_chars: int = 4_000) -> PipelineState:
    """Split a document into source-type-aware chunks."""

    started = perf_counter()
    content = state.document.content.strip()
    chunks: list[DocumentChunk] = []
    if content:
        if state.document.source_type == "chat":
            chunks = _split_chat(content)
        elif state.document.source_type == "doc":
            chunks = _split_doc(content)
        elif state.document.source_type == "code":
            chunks = _split_code(content)
        elif state.document.source_type == "transcript":
            chunks = _split_transcript(content)
        if not chunks:
            chunks = _split_paragraphs(content, source_type=state.document.source_type, max_chars=max_chars)
        if not chunks:
            chunks = [_chunk("chunk-1", content, state.document.source_type, span="")]

    diagnostics = replace(state.diagnostics, tokens_in=len(content.split()))
    next_state = replace(state, chunks=tuple(chunks), diagnostics=diagnostics)
    return next_state.with_timing("split_document", (perf_counter() - started) * 1000.0)
