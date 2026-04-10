#!/usr/bin/env python3
# ruff: noqa: E402
from __future__ import annotations

"""
Chatbot Memory Extractor v4.0

IMPROVEMENTS OVER v3:
- Semantic deduplication (fuzzy matching, not just exact)
- Better hyphenated/compound name handling (O'Brien, Saint-Jour, etc.)
- Time decay (older mentions = reduced confidence boost)
- Topic merging heuristics (combine related topics)
- Improved entity extraction

Usage:
    python extract_memory_v4.py <export_file> [options]
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import cortex.extract_memory_context as _extract_memory_context
from cortex.extract_memory_context import (
    ExtractionContext,
    are_similar,
    find_best_match,
    normalize_text,
)
from cortex.extract_memory_loaders import load_file
from cortex.extract_memory_patterns import (
    ALL_TECH_KEYWORDS,
    COMPANY_PATTERNS,
    CONSTRAINT_TYPES,
    CONSTRAINTS_PATTERNS,
    CORRECTION_KEYWORDS,
    CORRECTIONS_PATTERNS,
    CURRENT_INDICATORS,
    DOMAIN_KEYWORDS,
    FUTURE_INDICATORS,
    IDENTITY_PATTERNS,
    NEGATION_KEYWORDS,
    NEGATION_PATTERNS,
    NOISE_WORDS,
    PAST_INDICATORS,
    PREFERENCES_PATTERNS,
    PRIORITY_ACTION_HINT_WORDS,
    PROJECT_HINT_WORDS,
    PROJECT_PATTERNS,
    RELATIONSHIP_PATTERNS,
    RELATIONSHIP_TYPE_PATTERNS,
    ROLE_GUARD_WORDS,
    ROLE_HINT_WORDS,
    ROLE_PATTERNS,
    SKIP_WORDS,
    STRIP_PREFIXES,
    TECH_FALSE_POSITIVES,
    TECH_KEYWORDS,
    VALUE_PATTERNS,
    PIIRedactor,
)
from cortex.extract_memory_streams import (
    extract_message_stream,
    first_text_from_paths,
    get_message_text,
    is_user_message,
    message_collection,
    parse_timestamp,
)
from cortex.extract_memory_text import (
    clean_extracted_text as _clean_extracted_text,
)
from cortex.extract_memory_text import (
    clean_role_phrase as _clean_role_phrase,
)
from cortex.extract_memory_text import (
    extract_entities as _extract_entities,
)
from cortex.extract_memory_text import (
    extract_match_context as _extract_match_context,
)
from cortex.extract_memory_text import (
    extract_numbers as _extract_numbers,
)
from cortex.extract_memory_text import (
    extract_with_context as _extract_with_context,
)
from cortex.extract_memory_text import (
    keyword_pattern as _keyword_pattern,
)
from cortex.extract_memory_text import (
    keyword_search as _keyword_search,
)
from cortex.extract_memory_text import (
    looks_like_project_phrase as _looks_like_project_phrase,
)
from cortex.extract_memory_text import (
    looks_like_role_phrase as _looks_like_role_phrase,
)

ExtractedTopic = _extract_memory_context.ExtractedTopic
build_eval_compat_view = _extract_memory_context.build_eval_compat_view

_KEYWORD_PATTERN_CACHE: dict[str, re.Pattern] = {}


# ============================================================================
# TEXT UTILITIES
# ============================================================================


def clean_extracted_text(text: str) -> str:
    return _clean_extracted_text(text, strip_prefixes=STRIP_PREFIXES)


def keyword_pattern(keyword: str) -> re.Pattern:
    return _keyword_pattern(keyword, cache=_KEYWORD_PATTERN_CACHE)


def keyword_search(text: str, keyword: str) -> re.Match | None:
    return _keyword_search(text, keyword, cache=_KEYWORD_PATTERN_CACHE)


def extract_match_context(text: str, start: int, end: int, window: int = 50) -> str:
    return _extract_match_context(text, start, end, window)


def looks_like_role_phrase(text: str) -> bool:
    return _looks_like_role_phrase(
        text,
        normalize_text=normalize_text,
        role_guard_words=ROLE_GUARD_WORDS,
        role_hint_words=ROLE_HINT_WORDS,
    )


def clean_role_phrase(text: str) -> str:
    return _clean_role_phrase(text, clean_extracted_text_fn=clean_extracted_text)


def looks_like_project_phrase(text: str) -> bool:
    return _looks_like_project_phrase(
        text,
        normalize_text=normalize_text,
        noise_words=NOISE_WORDS,
        skip_words=SKIP_WORDS,
        project_hint_words=PROJECT_HINT_WORDS,
        priority_action_hint_words=PRIORITY_ACTION_HINT_WORDS,
        all_tech_keywords=ALL_TECH_KEYWORDS,
    )


def extract_numbers(text: str) -> list[str]:
    return _extract_numbers(text)


def extract_with_context(text: str, keyword: str, window: int = 50) -> str:
    return _extract_with_context(text, keyword, window)


def extract_entities(text: str) -> list[tuple[str, str]]:
    return _extract_entities(text, skip_words=SKIP_WORDS)


# ============================================================================
# EXTRACTOR
# ============================================================================


class AggressiveExtractor:
    def __init__(self, redactor: PIIRedactor | None = None):
        self.context = ExtractionContext()
        self.all_user_text = []
        self._negated_items = set()  # Track negated items for cross-category filtering
        self._redactor = redactor

    def extract_from_text(self, text: str, timestamp: datetime | None = None):
        if not text or len(text.strip()) < 10:
            return
        if self._redactor:
            text = self._redactor.redact(text)
        self.all_user_text.append(text)
        self._extract_identity(text, timestamp)
        self._extract_roles(text, timestamp)
        self._extract_companies(text, timestamp)
        self._extract_projects(text, timestamp)
        self._extract_technical(text, timestamp)
        self._extract_domains(text, timestamp)
        self._extract_relationships(text, timestamp)
        self._extract_values(text, timestamp)
        self._extract_priorities(text, timestamp)
        self._extract_metrics(text, timestamp)
        self._extract_negations(text, timestamp)
        self._extract_preferences(text, timestamp)
        self._extract_constraints(text, timestamp)
        self._extract_corrections(text, timestamp)
        self._extract_entities_generic(text, timestamp)
        self._extract_temporal(text, timestamp)

    def _extract_identity(self, text: str, timestamp: datetime | None = None):
        for pattern in IDENTITY_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                name = match.group(1).strip()
                if name.lower() not in SKIP_WORDS:
                    self.context.add_topic(
                        "identity",
                        name,
                        brief=name,
                        extraction_method="explicit_statement",
                        source_quote=match.group(0),
                        timestamp=timestamp,
                    )
        for pattern in [r"\b(MD|PhD|JD|MBA|CPA|RN|DO|DDS|DVM|PE|PMP|FACS|FACP)\b"]:
            for match in re.finditer(pattern, text):
                self.context.add_topic(
                    "identity",
                    match.group(1),
                    extraction_method="explicit_statement",
                    source_quote=match.group(0),
                    timestamp=timestamp,
                )

    def _extract_roles(self, text: str, timestamp: datetime | None = None):
        for pattern in ROLE_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                role = clean_role_phrase(match.group(1))
                if 3 < len(role) < 100 and looks_like_role_phrase(role):
                    self.context.add_topic(
                        "professional_context",
                        role,
                        brief=role,
                        extraction_method="explicit_statement",
                        source_quote=match.group(0),
                        timestamp=timestamp,
                    )
        for match in re.finditer(
            r"\b(CEO|CTO|CFO|COO|CMO|CIO|CISO|VP|SVP|EVP|Director|Manager|Lead|Head|Chief|Principal|Senior|Junior|Staff)\s+(?:of\s+)?([A-Za-z\s]+?)(?:\s+at|\s+for|,|\.|$)",
            text,
            re.IGNORECASE,
        ):
            role = clean_role_phrase(f"{match.group(1)} {match.group(2)}".strip())
            if looks_like_role_phrase(role):
                self.context.add_topic(
                    "professional_context",
                    role,
                    extraction_method="explicit_statement",
                    source_quote=match.group(0),
                    timestamp=timestamp,
                )

    def _extract_companies(self, text: str, timestamp: datetime | None = None):
        for pattern in COMPANY_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                company = match.group(1).strip()
                if 1 < len(company) < 50:
                    self.context.add_topic(
                        "business_context",
                        company,
                        brief=company,
                        full_description=extract_with_context(text, company, 100),
                        extraction_method="self_reference",
                        source_quote=match.group(0),
                        timestamp=timestamp,
                    )
        for match in re.finditer(
            r"(?:my|our)\s+(company|startup|business|organization|team|product|platform|app|service|tool)\s+([^.,]+)",
            text,
            re.IGNORECASE,
        ):
            thing = match.group(2).strip()
            cat = (
                "business_context"
                if match.group(1) in ["company", "startup", "business", "organization"]
                else "active_priorities"
            )
            self.context.add_topic(
                cat, thing, extraction_method="self_reference", source_quote=match.group(0), timestamp=timestamp
            )

    def _extract_projects(self, text: str, timestamp: datetime | None = None):
        for pattern in PROJECT_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                project = clean_extracted_text(match.group(1).strip()) if match.lastindex >= 1 else ""
                if 3 < len(project) < 200 and looks_like_project_phrase(project):
                    self.context.add_topic(
                        "active_priorities",
                        project,
                        extraction_method="direct_description",
                        source_quote=match.group(0),
                        timestamp=timestamp,
                    )
        for pattern in [
            r"(?:focused on|working on|building|developing|researching|exploring)\s+([^.,]+)",
            r"(?:my|our)\s+(?:current|main|primary|key)\s+(?:focus|priority|project|work)\s+(?:is\s+)?([^.,]+)",
        ]:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                focus = clean_extracted_text(match.group(1))
                if 5 < len(focus) < 200 and looks_like_project_phrase(focus):
                    self.context.add_topic(
                        "active_priorities",
                        focus,
                        extraction_method="direct_description",
                        source_quote=match.group(0),
                        timestamp=timestamp,
                    )

    def _extract_technical(self, text: str, timestamp: datetime | None = None):
        lower = text.lower()
        for category, keywords in TECH_KEYWORDS.items():
            for keyword in keywords:
                match = keyword_search(lower, keyword)
                if len(keyword) <= 3:
                    if not match:
                        continue
                    if keyword in TECH_FALSE_POSITIVES and not any(
                        tc in lower for tc in ["language", "programming", "code", "develop", "stack", "use", "prefer"]
                    ):
                        continue
                elif not match:
                    continue
                method = (
                    "self_reference"
                    if any(
                        p in lower for p in ["i use", "i prefer", "we use", "our stack", "i work with", "tech stack"]
                    )
                    else "mentioned"
                )
                self.context.add_topic(
                    "technical_expertise",
                    keyword.title() if len(keyword) > 3 else keyword.upper(),
                    brief=f"{category}: {keyword}",
                    extraction_method=method,
                    source_quote=extract_match_context(text, match.start(), match.end(), 30),
                    timestamp=timestamp,
                )

    def _extract_domains(self, text: str, timestamp: datetime | None = None):
        lower = text.lower()
        for domain, keywords in DOMAIN_KEYWORDS.items():
            matches = [(kw, keyword_search(lower, kw)) for kw in keywords]
            matches = [(kw, match) for kw, match in matches if match]
            if matches:
                for kw, match in matches:
                    self.context.add_topic(
                        "domain_knowledge",
                        kw.title(),
                        brief=f"{domain}: {kw}",
                        extraction_method="contextual",
                        source_quote=extract_match_context(text, match.start(), match.end(), 50),
                        timestamp=timestamp,
                    )
                if len(matches) >= 2:
                    self.context.add_topic(
                        "domain_knowledge",
                        domain.replace("_", " ").title(),
                        extraction_method="inferred",
                        timestamp=timestamp,
                    )

    def _extract_relationships(self, text: str, timestamp: datetime | None = None):
        """Extract relationships with type classification"""
        extracted = {}  # Track what we've extracted to avoid duplicates

        # First pass: typed patterns (partner, mentor, advisor, investor, client, competitor)
        for rel_type, patterns in RELATIONSHIP_TYPE_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    entity = match.group(1).strip()
                    if 2 < len(entity) < 100:
                        key = normalize_text(entity)
                        if key not in extracted:
                            extracted[key] = rel_type
                            self.context.add_topic(
                                "relationships",
                                entity,
                                brief=f"{rel_type.title()}: {entity}",
                                full_description=extract_with_context(text, entity, 100),
                                extraction_method="explicit_statement",
                                source_quote=match.group(0),
                                timestamp=timestamp,
                                relationship_type=rel_type,
                            )

        # Second pass: generic relationship patterns (untyped)
        for pattern in RELATIONSHIP_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                entity = match.group(1).strip()
                key = normalize_text(entity)
                if 2 < len(entity) < 100 and key not in extracted:
                    extracted[key] = ""
                    self.context.add_topic(
                        "relationships",
                        entity,
                        full_description=extract_with_context(text, entity, 100),
                        extraction_method="explicit_statement",
                        source_quote=match.group(0),
                        timestamp=timestamp,
                        relationship_type="",
                    )

        # Additional contextual patterns
        for match in re.finditer(
            r"(?:working|partnering|collaborating|meeting)\s+with\s+([A-Z][A-Za-z\s-]+?)(?:\s+(?:on|to|for|about)|\.|,|$)",
            text,
        ):
            entity = match.group(1).strip()
            key = normalize_text(entity)
            if len(entity) > 2 and key not in extracted:
                extracted[key] = ""
                self.context.add_topic(
                    "relationships",
                    entity,
                    extraction_method="contextual",
                    source_quote=match.group(0),
                    timestamp=timestamp,
                )

        for pattern in [
            r"(?:validation|study|partnership|collaboration)\s+(?:with|from|at)\s+([A-Z][A-Za-z\s-]+?)(?:\.|,|$|\s+(?:for|to|which))",
            r"([A-Z][A-Za-z]+(?:\s+(?:Clinic|Hospital|Medical|Health|University|Institute|Platform|Labs?))?)\s+(?:validation|partnership|study)",
            r"(?:advisors?|network)\s+(?:from|includes?|at)\s+([A-Z][A-Za-z,\s-]+?)(?:\.|$)",
        ]:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                orgs = match.group(1).strip()
                for org in re.split(r",\s*|\s+and\s+", orgs):
                    org = org.strip()
                    key = normalize_text(org)
                    if len(org) > 3 and org[0].isupper() and key not in extracted:
                        extracted[key] = ""
                        self.context.add_topic(
                            "relationships",
                            org,
                            brief=extract_with_context(text, org, 50)[:100],
                            extraction_method="contextual",
                            source_quote=match.group(0),
                            timestamp=timestamp,
                        )

        # Competitor detection (goes to market_context)
        for pattern in [
            r"(?:looked at|compared to|competitor|like)\s+(?:what\s+)?([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)\s+(?:is doing|does|offers)?",
            r"([A-Z][A-Za-z]+(?:\s+Health)?)\s+(?:in this space|as a competitor|for comparison)",
        ]:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                competitor = match.group(1).strip()
                if len(competitor) > 3:
                    self.context.add_topic(
                        "market_context",
                        competitor,
                        brief=f"Competitor/reference: {competitor}",
                        extraction_method="mentioned",
                        source_quote=match.group(0),
                        timestamp=timestamp,
                    )

    def _extract_values(self, text: str, timestamp: datetime | None = None):
        for pattern in VALUE_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                value = clean_extracted_text(match.group(1))
                if 5 < len(value) < 200:
                    self.context.add_topic(
                        "values",
                        value,
                        full_description=match.group(0)[:200],
                        extraction_method="explicit_statement",
                        source_quote=match.group(0),
                        timestamp=timestamp,
                    )
        for pattern, value_builder in [
            (
                r"i\s+care(?:\s+\w+){0,3}\s+about\s+([^.,]+)",
                lambda m: clean_extracted_text(m.group(1)),
            ),
            (
                r"\b([A-Za-z][A-Za-z0-9'/-]*(?:\s+[A-Za-z][A-Za-z0-9'/-]*){0,12}\s+is non-negotiable(?:\s+for\s+[^.,]+)?)",
                lambda m: clean_extracted_text(m.group(1)),
            ),
            (
                r"i(?:'d| would)\s+rather\s+([^.,]+?)\s+than\s+([^.,]+)",
                lambda m: clean_extracted_text(f"{m.group(1)} over {m.group(2)}"),
            ),
            (
                r"i(?:\s+also)?\s+document everything",
                lambda _m: "Document everything",
            ),
            (
                r"\b([A-Z]{2,}\s+license(?:\s+always)?)\b",
                lambda m: clean_extracted_text(m.group(1)),
            ),
            (
                r"if it(?:'s| is) not written down it did(?:n't| not) happen",
                lambda _m: "Document everything",
            ),
        ]:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                value = value_builder(match)
                if 5 < len(value) < 200:
                    self.context.add_topic(
                        "values",
                        value,
                        full_description=match.group(0)[:200],
                        extraction_method="explicit_statement",
                        source_quote=match.group(0),
                        timestamp=timestamp,
                    )
        for pattern in [r"i (?:prefer|like|want|need)\s+([^.,]+)", r"(?:please|always|never)\s+([^.,]+)"]:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                pref = clean_extracted_text(match.group(1))
                if 5 < len(pref) < 100:
                    self.context.add_topic(
                        "communication_preferences",
                        pref,
                        extraction_method="explicit_statement",
                        source_quote=match.group(0),
                        timestamp=timestamp,
                    )

    def _extract_priorities(self, text: str, timestamp: datetime | None = None):
        for pattern in [
            r"(?:my|our)\s+(?:goal|target|objective|priority|plan)\s+(?:is\s+)?(?:to\s+)?([^.,]+)",
            r"(?:trying to|aiming to|planning to|hoping to|want to|need to)\s+([^.,]+)",
            r"(?:preparing for|getting ready for|working towards)\s+([^.,]+)",
        ]:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                priority = match.group(1).strip()
                if 5 < len(priority) < 200:
                    self.context.add_topic(
                        "active_priorities",
                        priority,
                        extraction_method="direct_description",
                        source_quote=match.group(0),
                        timestamp=timestamp,
                    )

    def _extract_metrics(self, text: str, timestamp: datetime | None = None):
        for num in extract_numbers(text):
            context_text = extract_with_context(text, num, 50)
            cat = (
                "business_context"
                if any(
                    kw in context_text.lower()
                    for kw in ["funding", "raise", "revenue", "cost", "price", "budget", "investment"]
                )
                else "metrics"
            )
            self.context.add_topic(
                cat,
                num,
                brief=context_text[:100],
                extraction_method="contextual",
                source_quote=context_text,
                timestamp=timestamp,
            )

    def _extract_entities_generic(self, text: str, timestamp: datetime | None = None):
        for entity, entity_type in extract_entities(text):
            if entity.lower() in SKIP_WORDS | NOISE_WORDS or len(entity) < 3:
                continue
            if not any(
                find_best_match(normalize_text(entity), topics, threshold=0.8)
                for cat, topics in self.context.topics.items()
                if cat != "mentions"
            ):
                self.context.add_topic(
                    "mentions",
                    entity,
                    brief=extract_with_context(text, entity, 30)[:100] or entity,
                    extraction_method="mentioned",
                    source_quote=extract_with_context(text, entity, 30),
                    timestamp=timestamp,
                )

    def _extract_temporal(self, text: str, timestamp: datetime | None = None):
        lower = text.lower()
        is_current = any(ind in lower for ind in CURRENT_INDICATORS)
        is_past = any(ind in lower for ind in PAST_INDICATORS)
        is_future = any(ind in lower for ind in FUTURE_INDICATORS)
        for topics in self.context.topics.values():
            for key, topic in topics.items():
                if key in lower or normalize_text(topic.topic) in normalize_text(text):
                    if is_current and "current" not in topic.timeline:
                        topic.timeline.append("current")
                    if is_past and "past" not in topic.timeline:
                        topic.timeline.append("past")
                    if is_future and "planned" not in topic.timeline:
                        topic.timeline.append("planned")

    def _extract_negations(self, text: str, timestamp: datetime | None = None):
        """Extract items the user explicitly rejects or avoids."""
        lower = text.lower()

        # Only process if negation context exists
        has_negation_context = any(kw in lower for kw in NEGATION_KEYWORDS)
        if not has_negation_context:
            return

        for pattern in NEGATION_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                negated_item = clean_extracted_text(match.group(1))
                if 2 < len(negated_item) < 100:
                    self.context.add_topic(
                        category="negations",
                        topic=negated_item,
                        brief=f"User avoids: {negated_item}",
                        full_description=match.group(0)[:200],
                        extraction_method="explicit_statement",
                        source_quote=match.group(0)[:200],
                        timestamp=timestamp,
                    )
                    # Store normalized form for filtering other categories
                    self._negated_items.add(normalize_text(negated_item))
                    # Also add individual words from the negated item for broader matching
                    for word in negated_item.lower().split():
                        if len(word) > 2 and word not in SKIP_WORDS:
                            self._negated_items.add(word)

    def _extract_preferences(self, text: str, timestamp: datetime | None = None):
        """Extract user preferences and style choices."""
        lower = text.lower()

        for pattern in PREFERENCES_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                pref = clean_extracted_text(match.group(1))
                if 3 < len(pref) < 150:
                    # Determine extraction strength
                    has_strong_indicator = any(ind in lower for ind in {"prefer", "always", "favorite", "love"})
                    method = "explicit_statement" if has_strong_indicator else "self_reference"

                    self.context.add_topic(
                        category="user_preferences",
                        topic=pref,
                        brief=f"Prefers: {pref}",
                        extraction_method=method,
                        source_quote=match.group(0)[:200],
                        timestamp=timestamp,
                    )

        # Extract communication style preferences specifically
        comm_patterns = [
            r"(?:please|always)\s+(be\s+(?:concise|detailed|thorough|brief|specific))",
            r"(?:i|we)\s+(?:like|prefer|want)\s+((?:detailed|concise|brief|thorough)\s+(?:explanations?|responses?|answers?))",
            r"(?:give me|provide)\s+((?:more|less)\s+(?:detail|context|examples?))",
        ]
        for pattern in comm_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                pref = clean_extracted_text(match.group(1))
                if len(pref) > 3:
                    self.context.add_topic(
                        category="communication_preferences",
                        topic=pref,
                        brief=f"Communication: {pref}",
                        extraction_method="explicit_statement",
                        source_quote=match.group(0)[:200],
                        timestamp=timestamp,
                    )
        # Directive-style communication preferences
        directive_prefs = [
            (r"\bplease be concise\b", "concise responses", "communication_preferences"),
            (r"\bskip the disclaimers\b", "no disclaimers", "communication_preferences"),
            (
                r"\bdon'?t use bullet points(?: for everything)?\b",
                "prose over bullet points when appropriate",
                "communication_preferences",
            ),
            (
                r"\bwrite in prose(?: when it makes sense)?\b",
                "prose over bullet points when appropriate",
                "communication_preferences",
            ),
            (r"\bno filler phrases\b", "no filler phrases", "communication_preferences"),
            (r"\bjust answer\b", "direct answers", "communication_preferences"),
            (r"\bi dislike long explanations\b", "dislikes long explanations", "user_preferences"),
        ]

        for pattern, topic, category in directive_prefs:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            self.context.add_topic(
                category=category,
                topic=topic,
                brief=f"Communication: {topic}" if category == "communication_preferences" else f"Prefers: {topic}",
                extraction_method="explicit_statement",
                source_quote=match.group(0)[:200],
                timestamp=timestamp,
            )

        def add_preference_with_override(
            topic: str,
            source_quote: str,
            categories: tuple[str, ...],
            opposite_topics: tuple[str, ...] = (),
        ):
            def matches_override(existing_topic: str, target: str) -> bool:
                existing_norm = normalize_text(existing_topic)
                target_norm = normalize_text(target)
                if not existing_norm or not target_norm:
                    return False
                return (
                    existing_norm == target_norm
                    or existing_norm.startswith(target_norm + " ")
                    or existing_norm.endswith(" " + target_norm)
                    or target_norm in existing_norm.split()
                )

            for category in categories:
                self.context.add_topic(
                    category=category,
                    topic=topic,
                    brief=f"Communication: {topic}" if category == "communication_preferences" else f"Prefers: {topic}",
                    extraction_method="explicit_statement",
                    source_quote=source_quote[:200],
                    timestamp=timestamp,
                )

            if not opposite_topics:
                return

            for category in ("user_preferences", "communication_preferences"):
                for existing in list(self.context.topics.get(category, {}).values()):
                    if are_similar(existing.topic, topic, threshold=0.8):
                        continue
                    if timestamp and existing.last_seen and existing.last_seen >= timestamp:
                        continue
                    if not any(matches_override(existing.topic, opposite) for opposite in opposite_topics):
                        continue
                    self.context.add_topic(
                        category="negations",
                        topic=existing.topic,
                        brief=f"Superseded preference: {existing.topic}",
                        full_description=f"Later preference override: {topic}",
                        extraction_method="explicit_statement",
                        source_quote=source_quote[:200],
                        timestamp=timestamp,
                    )

        evolving_preference_patterns = [
            (
                r"\b(?:i want|please|just|you can|can you|be|keep it|make it)\b[^.]{0,80}\b(concise|brief)\b",
                "concise responses",
                ("communication_preferences", "user_preferences"),
                ("verbose", "verbose explanations", "detailed explanations", "thorough explanations"),
            ),
            (
                r"\b(?:i want|please|just|you can|can you|be|keep it|make it)\b[^.]{0,80}\b(verbose|detailed|thorough)\b",
                "verbose explanations",
                ("communication_preferences", "user_preferences"),
                ("concise", "concise responses", "brief responses"),
            ),
            (
                r"\btreat me like an expert\b",
                "expert-level explanations",
                ("communication_preferences", "user_preferences"),
                ("basic explanations", "beginner-level explanations", "skip the basics"),
            ),
            (
                r"\bskip the basics\b",
                "expert-level explanations",
                ("communication_preferences", "user_preferences"),
                ("basic explanations", "beginner-level explanations"),
            ),
        ]

        for pattern, topic, categories, opposite_topics in evolving_preference_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                add_preference_with_override(topic, match.group(0), categories, opposite_topics)

        indentation_patterns = [
            r"\bi(?:\s+always)?\s+use\s+(tabs|spaces)\b(?:[^.]{0,40}\bindentation\b)?",
            r"\b(tabs|spaces)\s+for\s+indentation\b",
            r"\b(tabs|spaces)\s+everywhere\b",
            r"\bfor\s+[a-z0-9+#.]+\b[^.]{0,40}\b(tabs|spaces)\b",
        ]
        for pattern in indentation_patterns:
            for match in re.finditer(pattern, lower):
                style = match.group(1).lower()
                topic = f"Use {style}"
                opposite = "spaces" if style == "tabs" else "tabs"
                add_preference_with_override(
                    topic,
                    match.group(0),
                    ("user_preferences",),
                    (f"Use {opposite}", opposite, f"{opposite} for indentation"),
                )

    def _extract_constraints(self, text: str, timestamp: datetime | None = None):
        """Extract constraints (budget, timeline, team size, requirements)."""

        for pattern in CONSTRAINTS_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                constraint = match.group(1).strip() if match.lastindex >= 1 else match.group(0).strip()
                if len(constraint) < 2:
                    continue

                # Classify constraint type
                constraint_type = self._classify_constraint(match.group(0).lower())

                # Extract associated metrics
                metrics = extract_numbers(match.group(0))

                self.context.add_topic(
                    category="constraints",
                    topic=constraint,
                    brief=f"{constraint_type.title()}: {constraint}",
                    full_description=match.group(0)[:200],
                    extraction_method="explicit_statement",
                    metrics=metrics,
                    source_quote=match.group(0)[:200],
                    timestamp=timestamp,
                )

    def _classify_constraint(self, text: str) -> str:
        """Classify constraint into type."""
        for ctype, keywords in CONSTRAINT_TYPES.items():
            if any(kw in text for kw in keywords):
                return ctype
        return "general"

    def _extract_corrections(self, text: str, timestamp: datetime | None = None):
        """Extract user corrections and clarifications."""
        lower = text.lower()

        # Only process if correction context exists
        has_correction_context = any(kw in lower for kw in CORRECTION_KEYWORDS)
        if not has_correction_context:
            return

        for pat_idx, pattern in enumerate(CORRECTIONS_PATTERNS):
            for match in re.finditer(pattern, text, re.IGNORECASE):
                # Handle both single-group and two-group patterns
                if match.lastindex >= 2:
                    # Determine which group is correct vs wrong based on pattern
                    matched_text = match.group(0).lower()
                    if pat_idx == 0:
                        # "I meant X not Y" — group(1) is correct, group(2) is wrong
                        correct_item = match.group(1).strip()
                        wrong_item = match.group(2).strip()
                    elif matched_text.startswith(("not ", "no ")) or matched_text.startswith("no,"):
                        # "not X but Y" — group(1) is wrong, group(2) is correct
                        wrong_item = match.group(1).strip()
                        correct_item = match.group(2).strip()
                    else:
                        # Standard pattern: group 1 is wrong, group 2 is correct
                        wrong_item = match.group(1).strip()
                        correct_item = match.group(2).strip()
                    correction_text = f"Corrected '{wrong_item}' to '{correct_item}'"
                    topic_name = correct_item
                    # Add the wrong item to negated items for filtering
                    if len(wrong_item) > 2:
                        self._negated_items.add(normalize_text(wrong_item))
                        for word in wrong_item.lower().split():
                            if len(word) > 2 and word not in SKIP_WORDS:
                                self._negated_items.add(word)
                else:
                    correct_item = match.group(1).strip()
                    correction_text = f"Clarified: {correct_item}"
                    topic_name = correct_item

                if 2 < len(topic_name) < 150:
                    self.context.add_topic(
                        category="correction_history",
                        topic=topic_name,
                        brief=correction_text,
                        full_description=match.group(0)[:200],
                        extraction_method="explicit_statement",
                        source_quote=match.group(0)[:200],
                        timestamp=timestamp,
                    )

    def post_process(self):
        for cat in ["relationships", "market_context", "mentions"]:
            if cat in self.context.topics:
                to_remove = {
                    key
                    for key, topic in list(self.context.topics[cat].items())
                    if key in NOISE_WORDS
                    or topic.topic.lower() in NOISE_WORDS
                    or (len(topic.topic.split()) == 1 and len(topic.topic) < 6 and topic.confidence < 0.6)
                }
                for key in to_remove:
                    if key in self.context.topics[cat]:
                        del self.context.topics[cat][key]

        # Filter negated items from positive categories
        if self._negated_items:
            categories_to_filter = ["technical_expertise", "domain_knowledge", "values", "user_preferences"]
            for category in categories_to_filter:
                if category in self.context.topics:
                    to_remove = set()
                    for key in list(self.context.topics[category].keys()):
                        # Check if this item was negated (fuzzy match)
                        if any(are_similar(key, neg, threshold=0.8) for neg in self._negated_items):
                            to_remove.add(key)
                    for key in to_remove:
                        del self.context.topics[category][key]

        self.context.merge_similar_topics()
        self.context.apply_time_decay()

        # Detect conflicts between positive categories and negations
        self.context.conflicts = self.context.detect_conflicts()

        # Inject redaction summary if redactor was used
        if self._redactor:
            self.context.redaction_summary = self._redactor.get_summary()

        if "mentions" in self.context.topics:
            better_topics = {key for cat, topics in self.context.topics.items() for key in topics if cat != "mentions"}
            to_remove = {
                key
                for key in list(self.context.topics["mentions"].keys())
                if any(are_similar(key, better, threshold=0.7) for better in better_topics)
            }
            for key in to_remove:
                if key in self.context.topics["mentions"]:
                    del self.context.topics["mentions"][key]

    def process_openai_export(self, data: list | dict) -> dict:
        if isinstance(data, list):
            conversations = data
        elif isinstance(data, dict) and "mapping" in data:
            conversations = [data]
        else:
            conversations = data.get("conversations", data.get("items", []))
        for conv in conversations:
            for node in conv.get("mapping", {}).values():
                if not isinstance(node, dict):
                    continue
                message = node.get("message")
                if message and is_user_message(message):
                    self.extract_from_text(get_message_text(message), parse_timestamp(message.get("create_time")))
        self.post_process()
        return self.context.export()

    def process_messages_list(self, messages: list) -> dict:
        for message in messages:
            if is_user_message(message):
                self.extract_from_text(
                    get_message_text(message), parse_timestamp(message.get("timestamp", message.get("created_at")))
                )
        self.post_process()
        return self.context.export()

    def process_plain_text(self, text: str) -> dict:
        for chunk in text.split("\n\n"):
            if len(chunk.strip()) > 20:
                self.extract_from_text(chunk)
        self.post_process()
        return self.context.export()

    def process_gemini_export(self, data: dict) -> dict:
        """Process Gemini/Google AI Studio exports."""
        conversations = data.get("conversations", [])

        for conv in conversations:
            # Handle "turns" format
            if "turns" in conv:
                for turn in conv["turns"]:
                    if turn.get("role") == "user":
                        self.extract_from_text(
                            turn.get("text", ""), parse_timestamp(turn.get("timestamp", turn.get("create_time")))
                        )
            # Handle "messages" format
            elif "messages" in conv:
                for msg in conv["messages"]:
                    author = msg.get("author", msg.get("role", ""))
                    if author in ["user", "human"]:
                        content = msg.get("content", msg.get("text", ""))
                        if isinstance(content, list):
                            content = " ".join(
                                p.get("text", str(p)) if isinstance(p, dict) else str(p) for p in content
                            )
                        self.extract_from_text(content, parse_timestamp(msg.get("timestamp", msg.get("create_time"))))

        self.post_process()
        return self.context.export()

    def process_perplexity_export(self, data: dict) -> dict:
        """Process Perplexity exports."""
        threads = data.get("threads", [])

        for thread in threads:
            for msg in thread.get("messages", []):
                if msg.get("role") == "user":
                    self.extract_from_text(msg.get("content", ""), parse_timestamp(msg.get("created_at")))

        self.post_process()
        return self.context.export()

    def process_grok_export(self, data: list | dict) -> dict:
        """Process Grok exports."""
        conversations = data if isinstance(data, list) else data.get("conversations", data.get("chats", [data]))
        for conv in conversations:
            messages = message_collection(conv, "messages", "items", "entries", "turns")
            extract_message_stream(
                self,
                messages,
                role_keys=("role", "sender", "author", "speaker", "type"),
                user_values=("user", "human", "prompt"),
                content_paths=(
                    ("content",),
                    ("text",),
                    ("body",),
                    ("message",),
                    ("prompt",),
                    ("query",),
                ),
                timestamp_keys=("timestamp", "created_at", "createdAt", "time"),
            )

        self.post_process()
        return self.context.export()

    def process_cursor_export(self, data: list | dict) -> dict:
        """Process Cursor chat/composer exports."""
        conversations = data if isinstance(data, list) else data.get("conversations", data.get("sessions", [data]))
        for conv in conversations:
            messages = message_collection(conv, "bubbles", "messages", "items", "conversation", "chat")
            extract_message_stream(
                self,
                messages,
                role_keys=("type", "role", "speaker", "kind", "author"),
                user_values=("user", "human", "prompt"),
                content_paths=(
                    ("text",),
                    ("content",),
                    ("message",),
                    ("prompt",),
                    ("markdown",),
                    ("body",),
                ),
                timestamp_keys=("timestamp", "created_at", "createdAt", "updatedAt"),
            )

        self.post_process()
        return self.context.export()

    def process_windsurf_export(self, data: list | dict) -> dict:
        """Process Windsurf session exports."""
        conversations = data if isinstance(data, list) else data.get("conversations", data.get("sessions", [data]))
        for conv in conversations:
            messages = message_collection(conv, "timeline", "messages", "entries", "items", "conversation")
            extract_message_stream(
                self,
                messages,
                role_keys=("role", "speaker", "type", "author"),
                user_values=("user", "human", "prompt"),
                content_paths=(
                    ("text",),
                    ("content",),
                    ("message",),
                    ("body",),
                    ("prompt",),
                    ("input",),
                ),
                timestamp_keys=("timestamp", "created_at", "createdAt", "updatedAt"),
            )

        self.post_process()
        return self.context.export()

    def process_copilot_export(self, data: list | dict) -> dict:
        """Process Copilot chat/export formats."""
        if isinstance(data, list):
            interactions = data
        else:
            interactions = data.get("interactions")
            if interactions is None:
                interactions = data.get("history")
            if interactions is None:
                interactions = data.get("sessions")
            if interactions is None:
                interactions = [data]

        for interaction in interactions:
            if not isinstance(interaction, dict):
                continue
            if "request" in interaction or "prompt" in interaction:
                pseudo_message = {
                    "role": "user",
                    "content": first_text_from_paths(
                        interaction,
                        ("request", "message"),
                        ("request", "content"),
                        ("request", "prompt"),
                        ("prompt",),
                        ("message",),
                        ("content",),
                    ),
                    "created_at": interaction.get(
                        "createdAt", interaction.get("timestamp", interaction.get("created_at"))
                    ),
                }
                extract_message_stream(
                    self,
                    [pseudo_message],
                    role_keys=("role",),
                    user_values=("user",),
                    content_paths=(("content",),),
                    timestamp_keys=("created_at",),
                )
                continue

            messages = message_collection(interaction, "messages", "entries", "items")
            normalized_messages: list[dict[str, Any]] = []
            for message in messages:
                if not isinstance(message, dict):
                    continue
                if "request" in message or "prompt" in message:
                    normalized_messages.append(
                        {
                            "role": "user",
                            "content": first_text_from_paths(
                                message,
                                ("request", "message"),
                                ("request", "content"),
                                ("request", "prompt"),
                                ("prompt",),
                                ("message",),
                                ("content",),
                            ),
                            "created_at": message.get("createdAt", message.get("timestamp", message.get("created_at"))),
                        }
                    )
                    continue
                normalized_messages.append(message)
            extract_message_stream(
                self,
                normalized_messages,
                role_keys=("role", "author", "speaker", "type"),
                user_values=("user", "human", "prompt"),
                content_paths=(
                    ("content",),
                    ("text",),
                    ("message",),
                    ("prompt",),
                    ("body",),
                ),
                timestamp_keys=("timestamp", "created_at", "createdAt"),
            )

        self.post_process()
        return self.context.export()

    def process_jsonl_messages(self, messages: list) -> dict:
        """Process JSONL message list."""
        for msg in messages:
            if is_user_message(msg):
                self.extract_from_text(
                    get_message_text(msg), parse_timestamp(msg.get("timestamp", msg.get("created_at")))
                )

        self.post_process()
        return self.context.export()

    def process_api_logs(self, data: dict) -> dict:
        """Process OpenAI/Anthropic API request logs."""
        requests = data.get("requests", [])

        for req in requests:
            messages = req.get("messages", [])
            for msg in messages:
                if msg.get("role") in ["user", "human"]:
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        # Handle Anthropic content blocks
                        content = " ".join(
                            block.get("text", "")
                            for block in content
                            if isinstance(block, dict) and block.get("type") == "text"
                        )
                    self.extract_from_text(content, parse_timestamp(req.get("timestamp", req.get("created_at"))))

        self.post_process()
        return self.context.export()


# ============================================================================
# FILE HANDLERS
# ============================================================================


def merge_contexts(existing_path: Path, extractor: "AggressiveExtractor") -> "AggressiveExtractor":
    """Merge new extraction with existing v4 context file.

    Loads topics from existing context file and adds them to the new extraction.
    Uses add_topic() which handles deduplication via find_best_match.
    """
    try:
        with open(existing_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        import sys

        print(f"[cortex] Warning: could not load merge file {existing_path.name}: {exc}", file=sys.stderr)
        return extractor

    # Load existing topics into the new context
    for category, topics in existing.get("categories", {}).items():
        for topic_data in topics:
            extractor.context.add_topic(
                category=category,
                topic=topic_data.get("topic", ""),
                brief=topic_data.get("brief", ""),
                full_description=topic_data.get("full_description", ""),
                confidence=topic_data.get("confidence", 0.5),
                extraction_method=topic_data.get("extraction_method", "mentioned"),
                metrics=topic_data.get("metrics", []),
                relationships=topic_data.get("relationships", []),
                timeline=topic_data.get("timeline", []),
                source_quote=topic_data.get("source_quotes", [""])[0] if topic_data.get("source_quotes") else "",
                timestamp=parse_timestamp(topic_data.get("last_seen")),
                relationship_type=topic_data.get("relationship_type", ""),
            )

    # Re-run merge for deduplication
    extractor.context.merge_similar_topics()

    return extractor


def main():
    parser = argparse.ArgumentParser(description="Aggressive memory extraction v4")
    parser.add_argument("input_file", help="Path to export file")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument(
        "--format",
        "-f",
        choices=[
            "auto",
            "openai",
            "gemini",
            "perplexity",
            "grok",
            "cursor",
            "windsurf",
            "copilot",
            "jsonl",
            "api_logs",
            "messages",
            "text",
            "generic",
        ],
        default="auto",
    )
    parser.add_argument("--merge", "-m", help="Existing context file to merge with (incremental extraction)")
    parser.add_argument("--redact", action="store_true", help="Enable PII redaction (emails, phones, SSNs, etc.)")
    parser.add_argument("--redact-patterns", help='Path to JSON file with custom redaction patterns {"LABEL": "regex"}')
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    input_path = Path(args.input_file)

    if not input_path.exists():
        print(f"File not found: {input_path}")
        return 1

    print(f"Loading: {input_path}")
    try:
        data, detected_format = load_file(input_path)
    except Exception as e:
        print(f"Error: {e}")
        return 1

    fmt = args.format if args.format != "auto" else detected_format
    print(f"Format: {fmt}")

    # Build optional PII redactor
    redactor = None
    if args.redact:
        custom_patterns = None
        if args.redact_patterns:
            patterns_path = Path(args.redact_patterns)
            if patterns_path.exists():
                with open(patterns_path, "r", encoding="utf-8") as f:
                    custom_patterns = json.load(f)
                print(f"🔒 Loaded {len(custom_patterns)} custom redaction patterns from {patterns_path}")
            else:
                print(f"⚠️  Redaction patterns file not found: {patterns_path}")
                return 1
        redactor = PIIRedactor(custom_patterns)
        print("🔒 PII redaction enabled")

    extractor = AggressiveExtractor(redactor=redactor)

    # Handle merge with existing context file
    if args.merge:
        merge_path = Path(args.merge)
        if merge_path.exists():
            print(f"📎 Merging with existing context: {merge_path}")
            extractor = merge_contexts(merge_path, extractor)
        else:
            print(f"⚠️  Merge file not found: {merge_path} (proceeding without merge)")

    print("Extracting (semantic dedup, time decay, topic merging, conflict detection, typed relationships)...")

    if fmt == "openai":
        result = extractor.process_openai_export(data)
    elif fmt == "gemini":
        result = extractor.process_gemini_export(data)
    elif fmt == "perplexity":
        result = extractor.process_perplexity_export(data)
    elif fmt == "grok":
        result = extractor.process_grok_export(data)
    elif fmt == "cursor":
        result = extractor.process_cursor_export(data)
    elif fmt == "windsurf":
        result = extractor.process_windsurf_export(data)
    elif fmt == "copilot":
        result = extractor.process_copilot_export(data)
    elif fmt in ("jsonl", "claude_code"):
        result = extractor.process_jsonl_messages(data)
    elif fmt == "api_logs":
        result = extractor.process_api_logs(data)
    elif fmt == "messages":
        result = extractor.process_messages_list(data)
    elif fmt == "text":
        result = extractor.process_plain_text(data)
    else:
        if isinstance(data, list):
            result = extractor.process_messages_list(data)
        elif isinstance(data, dict) and "messages" in data:
            result = extractor.process_messages_list(data["messages"])
        else:
            result = extractor.process_plain_text(json.dumps(data))

    stats = extractor.context.stats()
    print(f"✅ Extracted {stats['total']} topics across {len(stats['by_category'])} categories")
    print(
        f"   By confidence: {stats['by_confidence']['high']} high, {stats['by_confidence']['medium']} medium, {stats['by_confidence']['low']} low"
    )

    if args.stats or args.verbose:
        print("\n📊 By category:")
        for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
            print(f"   {cat}: {count}")

    if args.verbose:
        print("\n🔎 Sample extractions:")
        for cat, topics in list(result["categories"].items())[:5]:
            print(f"\n  [{cat}]")
            for topic in topics[:3]:
                rel_type = topic.get("relationship_type", "")
                rel_str = f", type: {rel_type}" if rel_type else ""
                print(
                    f"    • {topic['topic']} (conf: {topic['confidence']}, mentions: {topic['mention_count']}{rel_str})"
                )

        # Show conflicts if any
        if result.get("conflicts"):
            print(f"\n⚠️  Detected {len(result['conflicts'])} conflicts:")
            for conflict in result["conflicts"][:5]:
                print(
                    f"    • {conflict['positive_category']}: '{conflict['positive_topic']}' vs negation '{conflict['negative_topic']}' → {conflict['resolution']}"
                )

    # Show redaction summary
    if result.get("redaction_summary"):
        summary = result["redaction_summary"]
        print(f"\n🔒 Redaction: {summary['total_redactions']} items redacted")
        if args.verbose and summary["by_type"]:
            for pii_type, count in sorted(summary["by_type"].items()):
                print(f"   {pii_type}: {count}")

    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_context.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"\n💾 Saved to: {output_path}")
    return 0


if __name__ == "__main__":
    exit(main())
