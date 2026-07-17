from __future__ import annotations

import html
import re


_FENCED_CODE = re.compile(r"```[^\n]*\n.*?```|~~~[^\n]*\n.*?~~~", re.DOTALL)
_MARKDOWN_IMAGE = re.compile(r"!\[([^]]*)\]\([^)]+\)")
_MARKDOWN_LINK = re.compile(r"\[([^]]+)\]\([^)]+\)")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_RAW_URL = re.compile(r"\bhttps?://\S+")
_HTML_TAG = re.compile(r"<[^>]+>")
_TABLE_DIVIDER = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_LIST_PREFIX = re.compile(r"^\s*(?:#{1,6}\s+|>\s*|[-+*]\s+|\d+[.)]\s+)")
_HORIZONTAL_RULE = re.compile(r"^\s*(?:[-*_]\s*){3,}$")
_SPACE = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{3,}")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")


def clean_for_speech(markdown: str, *, max_characters: int = 12_000) -> str:
    """Turn a Codex Markdown answer into bounded, natural-ish spoken text."""
    text = html.unescape(markdown.replace("\r\n", "\n").replace("\r", "\n"))
    text = _FENCED_CODE.sub("\nCode block omitted.\n", text)
    text = _MARKDOWN_IMAGE.sub(lambda match: match.group(1) or "image", text)
    text = _MARKDOWN_LINK.sub(lambda match: match.group(1), text)
    text = _INLINE_CODE.sub(lambda match: match.group(1), text)
    text = _RAW_URL.sub("link", text)
    text = _HTML_TAG.sub(" ", text)

    lines: list[str] = []
    for raw_line in text.splitlines():
        if _TABLE_DIVIDER.match(raw_line) or _HORIZONTAL_RULE.match(raw_line):
            continue
        line = _LIST_PREFIX.sub("", raw_line)
        if "|" in line:
            line = ", ".join(part.strip() for part in line.strip(" | ").split("|") if part.strip())
        line = _SPACE.sub(" ", line).strip()
        lines.append(line)

    text = _BLANKS.sub("\n\n", "\n".join(lines)).strip()
    text = re.sub(r"[*_~]", "", text)
    text = _SPACE.sub(" ", text)
    if len(text) > max_characters:
        clipped = text[:max_characters].rsplit(" ", 1)[0].rstrip(" ,;:")
        text = clipped + ". The rest of this response was omitted."
    return text.strip()


def _split_words(text: str, max_characters: int) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for word in words:
        if len(word) > max_characters:
            if current:
                chunks.append(" ".join(current))
                current = []
                length = 0
            chunks.extend(
                word[index : index + max_characters]
                for index in range(0, len(word), max_characters)
            )
            continue
        added = len(word) + (1 if current else 0)
        if current and length + added > max_characters:
            chunks.append(" ".join(current))
            current = [word]
            length = len(word)
        else:
            current.append(word)
            length += added
    if current:
        chunks.append(" ".join(current))
    return chunks


def _split_long_segment(text: str, max_characters: int) -> list[str]:
    if len(text) <= max_characters:
        return [text]
    clauses = re.split(r"(?<=[;:,])\s+", text)
    result: list[str] = []
    current = ""
    for clause in clauses:
        if len(clause) > max_characters:
            if current:
                result.append(current)
                current = ""
            result.extend(_split_words(clause, max_characters))
        elif current and len(current) + 1 + len(clause) > max_characters:
            result.append(current)
            current = clause
        else:
            current = f"{current} {clause}".strip()
    if current:
        result.append(current)
    return result


def chunk_for_kokoro(
    text: str,
    *,
    target_characters: int = 160,
    max_characters: int = 220,
) -> list[str]:
    """Split at prose boundaries so Kokoro starts quickly and stays natural."""
    if not text.strip():
        return []
    segments: list[str] = []
    for segment in _SENTENCE_BOUNDARY.split(text.strip()):
        segment = segment.strip()
        if segment:
            segments.extend(_split_long_segment(segment, max_characters))

    chunks: list[str] = []
    current = ""
    for segment in segments:
        proposed = f"{current} {segment}".strip()
        if current and len(proposed) > target_characters:
            chunks.append(current)
            current = segment
        else:
            current = proposed
    if current:
        if chunks and len(current) < 40 and len(chunks[-1]) + 1 + len(current) <= max_characters:
            chunks[-1] = f"{chunks[-1]} {current}"
        else:
            chunks.append(current)
    return chunks
