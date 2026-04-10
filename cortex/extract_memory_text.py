from __future__ import annotations

import re
from typing import Callable


def clean_extracted_text(text: str, *, strip_prefixes: list[str]) -> str:
    text = text.strip()
    lower = text.lower()
    for prefix in strip_prefixes:
        if lower.startswith(prefix):
            text = text[len(prefix) :]
            break
    text = text.rstrip(".,;:!?")
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text.strip()


def keyword_pattern(keyword: str, *, cache: dict[str, re.Pattern[str]]) -> re.Pattern[str]:
    cached = cache.get(keyword)
    if cached is not None:
        return cached
    pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(keyword) + r"(?![A-Za-z0-9])", re.IGNORECASE)
    cache[keyword] = pattern
    return pattern


def keyword_search(text: str, keyword: str, *, cache: dict[str, re.Pattern[str]]) -> re.Match[str] | None:
    return keyword_pattern(keyword, cache=cache).search(text)


def extract_match_context(text: str, start: int, end: int, window: int = 50) -> str:
    start = max(0, start - window)
    end = min(len(text), end + window)
    while start > 0 and text[start] not in " \n\t":
        start -= 1
    while end < len(text) and text[end] not in " \n\t":
        end += 1
    return text[start:end].strip()


def looks_like_role_phrase(
    text: str,
    *,
    normalize_text: Callable[[str], str],
    role_guard_words: set[str],
    role_hint_words: set[str],
) -> bool:
    normalized = normalize_text(text)
    tokens = normalized.split()
    if not tokens or len(tokens) > 8:
        return False
    if tokens[0] in role_guard_words:
        return False
    if tokens[0] in {"of", "for", "with"}:
        return False
    if " of " in normalized and tokens[0] not in role_hint_words:
        return False
    return any(token in role_hint_words for token in tokens)


def clean_role_phrase(text: str, *, clean_extracted_text_fn: Callable[[str], str]) -> str:
    text = clean_extracted_text_fn(text)
    segments = re.split(r"\s+(?:on|at|for|with)\s+", text, maxsplit=1, flags=re.IGNORECASE)
    candidate = segments[0].strip() if segments else text
    return candidate or text


def looks_like_project_phrase(
    text: str,
    *,
    normalize_text: Callable[[str], str],
    noise_words: set[str],
    skip_words: set[str],
    project_hint_words: set[str],
    priority_action_hint_words: set[str],
    all_tech_keywords: set[str],
) -> bool:
    normalized = normalize_text(text)
    tokens = normalized.split()
    if len(tokens) < 2 or len(tokens) > 14:
        return False
    if tokens[0] in noise_words | skip_words:
        return False
    if any(phrase in normalized for phrase in {" with the team", " with my team", " with the people"}):
        return False
    if any(token in project_hint_words for token in tokens):
        return True
    if any(token in priority_action_hint_words for token in tokens):
        return True
    if any(token in all_tech_keywords for token in tokens):
        return True
    if any(ch.isdigit() for ch in text) or any(sym in text for sym in "-_/"):
        return True
    if any(token[:1].isupper() for token in text.split() if token):
        return True
    return False


def extract_numbers(text: str) -> list[str]:
    patterns = [
        r"\$[\d,]+(?:\.\d+)?(?:\s*(?:million|billion|M|B|k|K))?",
        r"[\d,]+(?:\.\d+)?%",
        r"[\d,]+(?:\.\d+)?\s*(?:million|billion|M|B|k|K)\b",
        r"\b\d{4}\b(?!\d)",
        r"(?:≥|>=|≤|<=|>|<)\s*[\d.]+",
        r"\b\d+(?:\.\d+)?\s*(?:years?|months?|weeks?|days?|hours?)\b",
        r"\b\d+\s*(?:users?|customers?|clients?|employees?|people)\b",
    ]
    results = []
    for pattern in patterns:
        results.extend(re.findall(pattern, text, re.IGNORECASE))
    return list(set(results))


def extract_with_context(text: str, keyword: str, window: int = 50) -> str:
    pos = text.lower().find(keyword.lower())
    if pos == -1:
        return ""
    start, end = max(0, pos - window), min(len(text), pos + len(keyword) + window)
    while start > 0 and text[start] not in " \n\t":
        start -= 1
    while end < len(text) and text[end] not in " \n\t":
        end += 1
    return text[start:end].strip()


def extract_entities(text: str, *, skip_words: set[str]) -> list[tuple[str, str]]:
    entities = []
    for match in re.finditer(r"\b([A-Z][a-z]+(?:[-\'][A-Z]?[a-z]+)*(?:\s+[A-Z][a-z]+(?:[-\'][A-Z]?[a-z]+)*)*)\b", text):
        entity = match.group(1)
        if len(entity) > 2 and entity.lower() not in skip_words:
            entities.append((entity, "entity"))
    for match in re.finditer(r"\b([A-Z][a-z]+[A-Z][A-Za-z]*|[A-Z]{2,})\b", text):
        entities.append((match.group(1), "tech_entity"))
    return entities


__all__ = [
    "clean_extracted_text",
    "clean_role_phrase",
    "extract_entities",
    "extract_match_context",
    "extract_numbers",
    "extract_with_context",
    "keyword_pattern",
    "keyword_search",
    "looks_like_project_phrase",
    "looks_like_role_phrase",
]
