from __future__ import annotations

import re
from datetime import datetime

from cortex.extract_memory_context import are_similar, find_best_match, normalize_text
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
)
from cortex.extract_memory_text import clean_extracted_text as _clean_extracted_text
from cortex.extract_memory_text import clean_role_phrase as _clean_role_phrase
from cortex.extract_memory_text import extract_entities as _extract_entities
from cortex.extract_memory_text import extract_match_context as _extract_match_context
from cortex.extract_memory_text import extract_numbers as _extract_numbers
from cortex.extract_memory_text import extract_with_context as _extract_with_context
from cortex.extract_memory_text import keyword_search as _keyword_search
from cortex.extract_memory_text import looks_like_project_phrase as _looks_like_project_phrase
from cortex.extract_memory_text import looks_like_role_phrase as _looks_like_role_phrase

_KEYWORD_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


def _clean_text(text: str) -> str:
    return _clean_extracted_text(text, strip_prefixes=STRIP_PREFIXES)


def _search_keyword(text: str, keyword: str) -> re.Match[str] | None:
    return _keyword_search(text, keyword, cache=_KEYWORD_PATTERN_CACHE)


def _match_context(text: str, start: int, end: int, window: int = 50) -> str:
    return _extract_match_context(text, start, end, window)


def _clean_role(text: str) -> str:
    return _clean_role_phrase(text, clean_extracted_text_fn=_clean_text)


def _looks_like_role(text: str) -> bool:
    return _looks_like_role_phrase(
        text,
        normalize_text=normalize_text,
        role_guard_words=ROLE_GUARD_WORDS,
        role_hint_words=ROLE_HINT_WORDS,
    )


def _looks_like_project(text: str) -> bool:
    return _looks_like_project_phrase(
        text,
        normalize_text=normalize_text,
        noise_words=NOISE_WORDS,
        skip_words=SKIP_WORDS,
        project_hint_words=PROJECT_HINT_WORDS,
        priority_action_hint_words=PRIORITY_ACTION_HINT_WORDS,
        all_tech_keywords=ALL_TECH_KEYWORDS,
    )


def _numbers(text: str) -> list[str]:
    return _extract_numbers(text)


def _with_context(text: str, keyword: str, window: int = 50) -> str:
    return _extract_with_context(text, keyword, window)


def _entities(text: str) -> list[tuple[str, str]]:
    return _extract_entities(text, skip_words=SKIP_WORDS)


class AggressiveExtractionTopicMixin:
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
                role = _clean_role(match.group(1))
                if 3 < len(role) < 100 and _looks_like_role(role):
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
            role = _clean_role(f"{match.group(1)} {match.group(2)}".strip())
            if _looks_like_role(role):
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
                        full_description=_with_context(text, company, 100),
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
                project = _clean_text(match.group(1).strip()) if match.lastindex >= 1 else ""
                if 3 < len(project) < 200 and _looks_like_project(project):
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
                focus = _clean_text(match.group(1))
                if 5 < len(focus) < 200 and _looks_like_project(focus):
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
                match = _search_keyword(lower, keyword)
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
                    source_quote=_match_context(text, match.start(), match.end(), 30),
                    timestamp=timestamp,
                )

    def _extract_domains(self, text: str, timestamp: datetime | None = None):
        lower = text.lower()
        for domain, keywords in DOMAIN_KEYWORDS.items():
            matches = [(kw, _search_keyword(lower, kw)) for kw in keywords]
            matches = [(kw, match) for kw, match in matches if match]
            if matches:
                for kw, match in matches:
                    self.context.add_topic(
                        "domain_knowledge",
                        kw.title(),
                        brief=f"{domain}: {kw}",
                        extraction_method="contextual",
                        source_quote=_match_context(text, match.start(), match.end(), 50),
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
        extracted = {}

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
                                full_description=_with_context(text, entity, 100),
                                extraction_method="explicit_statement",
                                source_quote=match.group(0),
                                timestamp=timestamp,
                                relationship_type=rel_type,
                            )

        for pattern in RELATIONSHIP_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                entity = match.group(1).strip()
                key = normalize_text(entity)
                if 2 < len(entity) < 100 and key not in extracted:
                    extracted[key] = ""
                    self.context.add_topic(
                        "relationships",
                        entity,
                        full_description=_with_context(text, entity, 100),
                        extraction_method="explicit_statement",
                        source_quote=match.group(0),
                        timestamp=timestamp,
                        relationship_type="",
                    )

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
                            brief=_with_context(text, org, 50)[:100],
                            extraction_method="contextual",
                            source_quote=match.group(0),
                            timestamp=timestamp,
                        )

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
                value = _clean_text(match.group(1))
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
                lambda m: _clean_text(m.group(1)),
            ),
            (
                r"\b([A-Za-z][A-Za-z0-9'/-]*(?:\s+[A-Za-z][A-Za-z0-9'/-]*){0,12}\s+is non-negotiable(?:\s+for\s+[^.,]+)?)",
                lambda m: _clean_text(m.group(1)),
            ),
            (
                r"i(?:'d| would)\s+rather\s+([^.,]+?)\s+than\s+([^.,]+)",
                lambda m: _clean_text(f"{m.group(1)} over {m.group(2)}"),
            ),
            (
                r"i(?:\s+also)?\s+document everything",
                lambda _m: "Document everything",
            ),
            (
                r"\b([A-Z]{2,}\s+license(?:\s+always)?)\b",
                lambda m: _clean_text(m.group(1)),
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
                pref = _clean_text(match.group(1))
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
        for num in _numbers(text):
            context_text = _with_context(text, num, 50)
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
        for entity, entity_type in _entities(text):
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
                    brief=_with_context(text, entity, 30)[:100] or entity,
                    extraction_method="mentioned",
                    source_quote=_with_context(text, entity, 30),
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
        lower = text.lower()
        has_negation_context = any(kw in lower for kw in NEGATION_KEYWORDS)
        if not has_negation_context:
            return

        for pattern in NEGATION_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                negated_item = _clean_text(match.group(1))
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
                    self._negated_items.add(normalize_text(negated_item))
                    for word in negated_item.lower().split():
                        if len(word) > 2 and word not in SKIP_WORDS:
                            self._negated_items.add(word)

    def _extract_preferences(self, text: str, timestamp: datetime | None = None):
        lower = text.lower()

        for pattern in PREFERENCES_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                pref = _clean_text(match.group(1))
                if 3 < len(pref) < 150:
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

        comm_patterns = [
            r"(?:please|always)\s+(be\s+(?:concise|detailed|thorough|brief|specific))",
            r"(?:i|we)\s+(?:like|prefer|want)\s+((?:detailed|concise|brief|thorough)\s+(?:explanations?|responses?|answers?))",
            r"(?:give me|provide)\s+((?:more|less)\s+(?:detail|context|examples?))",
        ]
        for pattern in comm_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                pref = _clean_text(match.group(1))
                if len(pref) > 3:
                    self.context.add_topic(
                        category="communication_preferences",
                        topic=pref,
                        brief=f"Communication: {pref}",
                        extraction_method="explicit_statement",
                        source_quote=match.group(0)[:200],
                        timestamp=timestamp,
                    )

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
        for pattern in CONSTRAINTS_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                constraint = match.group(1).strip() if match.lastindex >= 1 else match.group(0).strip()
                if len(constraint) < 2:
                    continue

                constraint_type = self._classify_constraint(match.group(0).lower())
                metrics = _numbers(match.group(0))

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
        for ctype, keywords in CONSTRAINT_TYPES.items():
            if any(kw in text for kw in keywords):
                return ctype
        return "general"

    def _extract_corrections(self, text: str, timestamp: datetime | None = None):
        lower = text.lower()
        has_correction_context = any(kw in lower for kw in CORRECTION_KEYWORDS)
        if not has_correction_context:
            return

        for pat_idx, pattern in enumerate(CORRECTIONS_PATTERNS):
            for match in re.finditer(pattern, text, re.IGNORECASE):
                if match.lastindex >= 2:
                    matched_text = match.group(0).lower()
                    if pat_idx == 0:
                        correct_item = match.group(1).strip()
                        wrong_item = match.group(2).strip()
                    elif matched_text.startswith(("not ", "no ")) or matched_text.startswith("no,"):
                        wrong_item = match.group(1).strip()
                        correct_item = match.group(2).strip()
                    else:
                        wrong_item = match.group(1).strip()
                        correct_item = match.group(2).strip()
                    correction_text = f"Corrected '{wrong_item}' to '{correct_item}'"
                    topic_name = correct_item
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

        if self._negated_items:
            categories_to_filter = ["technical_expertise", "domain_knowledge", "values", "user_preferences"]
            for category in categories_to_filter:
                if category in self.context.topics:
                    to_remove = set()
                    for key in list(self.context.topics[category].keys()):
                        if any(are_similar(key, neg, threshold=0.8) for neg in self._negated_items):
                            to_remove.add(key)
                    for key in to_remove:
                        del self.context.topics[category][key]

        self.context.merge_similar_topics()
        self.context.apply_time_decay()
        self.context.conflicts = self.context.detect_conflicts()

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
