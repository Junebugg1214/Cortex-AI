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
import difflib
import json
import os
import re
import unicodedata
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ============================================================================
# CONFIGURATION
# ============================================================================

MENTION_COUNT_BOOST = {1: 0.0, 2: 0.1, 3: 0.15, 5: 0.2, 10: 0.25, 20: 0.3}

TIME_DECAY = {
    7: 1.0,  # Within a week
    30: 0.9,  # Within a month
    90: 0.7,  # Within 3 months
    180: 0.5,  # Within 6 months
    365: 0.3,  # Within a year
    float("inf"): 0.1,
}

BASE_CONFIDENCE = {
    "explicit_statement": 0.85,
    "self_reference": 0.8,
    "direct_description": 0.75,
    "contextual": 0.6,
    "mentioned": 0.4,
    "inferred": 0.3,
}

SIMILARITY_THRESHOLD = 0.85
MERGEABLE_CATEGORIES = {
    "technical_expertise",
    "domain_knowledge",
    "active_priorities",
    "business_context",
    "relationships",
}

# Patterns for hyphenated/compound names
IDENTITY_PATTERNS = [
    r"(?:my name is|i'?m|i am|call me)\s+([A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*(?:\s+[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*)*)",
    r"(?:this is)\s+(?:Dr\.?\s+)?([A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*(?:\s+[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*)*)",
    r"(?:i'?m|i am)\s+([A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*(?:\s+[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*)*),?\s*(?:MD|PhD|JD|MBA|DO|DDS|RN|PE|CPA)",
    r"(?:Dr\.?|Doctor)\s+([A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*)",
]

ROLE_PATTERNS = [
    r"i(?:'m| am) (?:a |an |the )?([a-z]+(?:\s+[a-z]+)?(?:ist|er|or|ant|ent|ian|ive|manager|director|officer|founder|engineer|developer|designer|analyst|scientist|physician|doctor|nurse|lawyer|consultant))",
    r"(?:work(?:ing)? as|my (?:job|role|position|title) is)(?: a| an| the)?\s+([^.,]+)",
    r"i (?:lead|manage|run|head|oversee)\s+([^.,]+)",
]

COMPANY_PATTERNS = [
    r"(?:my |our )(?:company|startup|business|firm|organization|org)(?: is)?\s+(?:called\s+)?([A-Z][A-Za-z0-9]+(?:[-\s][A-Z]?[A-Za-z0-9]+)*)",
    r"(?:i |we )(?:founded|started|co-?founded|built|created|launched)\s+([A-Z][A-Za-z0-9]+(?:[-\s][A-Z]?[A-Za-z0-9]+)*)",
    r"(?:co-?founder|founder|CEO|CTO|CMO|COO|CIO)\s+(?:of|at)\s+([A-Z][A-Za-z0-9]+(?:[-\s][A-Z]?[A-Za-z0-9]+)*)",
    r"(?:of|at)\s+([A-Z][A-Za-z0-9]+(?:[-\s][A-Z]?[A-Za-z0-9]+)*)\.\s+(?:We|I|Our)",
]

PROJECT_PATTERNS = [
    r"(?:working on|building|developing|creating)\s+(?:a |an |the )?([^.,]+?)(?:\s+(?:which|that|to|for)|\.|,|$)",
    r"(?:my |our )(?:project|product|platform|app|tool|system|solution)\s+(?:is\s+)?(?:called\s+)?([A-Z][A-Za-z0-9]+(?:[-\s][A-Z]?[A-Za-z0-9]+)*)?",
]

TECH_KEYWORDS = {
    "languages": [
        "python",
        "javascript",
        "typescript",
        "java",
        "c++",
        "c#",
        "ruby",
        "rust",
        "swift",
        "kotlin",
        "php",
        "scala",
        "matlab",
        "sql",
        "html",
        "css",
        "golang",
    ],
    "frameworks": [
        "react",
        "angular",
        "vue",
        "django",
        "flask",
        "fastapi",
        "express",
        "next.js",
        "nextjs",
        "nuxt",
        "rails",
        "spring",
        "laravel",
        ".net",
        "tensorflow",
        "pytorch",
        "keras",
        "langchain",
    ],
    "platforms": [
        "aws",
        "gcp",
        "azure",
        "vercel",
        "netlify",
        "heroku",
        "docker",
        "kubernetes",
        "linux",
        "ubuntu",
        "windows",
        "macos",
        "ec2",
        "lambda",
        "cloudflare",
    ],
    "databases": [
        "postgresql",
        "postgres",
        "mysql",
        "mongodb",
        "redis",
        "elasticsearch",
        "dynamodb",
        "firebase",
        "supabase",
        "convex",
        "planetscale",
        "pinecone",
    ],
    "tools": [
        "git",
        "github",
        "gitlab",
        "jira",
        "confluence",
        "slack",
        "notion",
        "figma",
        "vscode",
        "vim",
        "cursor",
        "copilot",
        "pytest",
        "ruff",
    ],
}

TECH_FALSE_POSITIVES = {"go", "r", "c", "rust", "swift", "ruby"}

DOMAIN_KEYWORDS = {
    "healthcare": [
        "clinical",
        "medical",
        "health",
        "patient",
        "hospital",
        "physician",
        "doctor",
        "nurse",
        "diagnosis",
        "treatment",
        "fda",
        "hipaa",
        "ehr",
        "emr",
        "ctcae",
        "oncology",
        "cancer",
        "therapy",
        "pharmaceutical",
        "drug",
        "trial",
    ],
    "finance": [
        "financial",
        "banking",
        "investment",
        "trading",
        "portfolio",
        "stock",
        "bond",
        "crypto",
        "blockchain",
        "fintech",
        "payment",
        "lending",
        "insurance",
    ],
    "ai_ml": [
        "machine learning",
        "deep learning",
        "neural network",
        "nlp",
        "computer vision",
        "ai",
        "artificial intelligence",
        "model",
        "training",
        "inference",
        "llm",
        "gpt",
        "transformer",
        "rag",
        "embedding",
    ],
    "legal": [
        "legal",
        "law",
        "attorney",
        "lawyer",
        "contract",
        "compliance",
        "regulatory",
        "litigation",
        "intellectual property",
        "patent",
        "trademark",
    ],
    "education": [
        "education",
        "learning",
        "teaching",
        "student",
        "course",
        "curriculum",
        "school",
        "university",
        "academic",
        "research",
    ],
}

RELATIONSHIP_PATTERNS = [
    r"(?:partner(?:ship|ed|ing)?|collaborat(?:e|ion|ing)|work(?:ing)? with)\s+([A-Z][A-Za-z0-9\s-]+?)(?:\s+(?:on|to|for)|\.|,|$)",
    r"(?:advisor|mentor|investor|client|customer)\s+(?:from|at|is)\s+([A-Z][A-Za-z0-9\s-]+)",
    r"([A-Z][A-Za-z0-9\s-]+?)\s+(?:is our|are our)\s+(?:partner|client|investor|advisor)",
]

RELATIONSHIP_TYPE_PATTERNS = {
    "partner": [
        r"(?:partner(?:ship|ing)?|collaborat(?:e|ing|ion))\s+(?:with|and)\s+([A-Z][A-Za-z0-9\s-]+?)(?:\s+(?:on|to|for)|\.|,|$)",
        r"([A-Z][A-Za-z0-9\s-]+?)\s+(?:is our|are our)\s+(?:partner|collaborator)",
    ],
    "mentor": [
        r"(?:mentor(?:ed)?|mentoring)\s+(?:by|from|is)\s+([A-Z][A-Za-z0-9\s-]+)",
        r"([A-Z][A-Za-z0-9\s-]+?)\s+(?:is my|as my)\s+mentor",
    ],
    "advisor": [
        r"(?:advisor|advised)\s+(?:by|from|is)\s+([A-Z][A-Za-z0-9\s-]+)",
        r"([A-Z][A-Za-z0-9\s-]+?)\s+(?:is an?|as an?)\s+advisor",
    ],
    "investor": [
        r"(?:investor|invested|backed|funded)\s+(?:by|from|is)\s+([A-Z][A-Za-z0-9\s-]+)",
        r"([A-Z][A-Za-z0-9\s-]+?)\s+(?:invested|is an investor)",
    ],
    "client": [
        r"(?:client|customer)s?\s+(?:include|is|are)\s+([A-Z][A-Za-z0-9\s-]+)",
        r"([A-Z][A-Za-z0-9\s-]+?)\s+(?:is a|as a)\s+(?:client|customer)",
    ],
    "competitor": [
        r"(?:competitor|competing)\s+(?:with|is|like)\s+([A-Z][A-Za-z0-9\s-]+)",
        r"(?:vs|versus|compared to)\s+([A-Z][A-Za-z0-9\s-]+)",
    ],
}

VALUE_PATTERNS = [
    r"i (?:believe|think|value|prioritize|care about)\s+([^.,]+)",
    r"(?:important to me|matters to me|i always)\s+([^.,]+)",
    r"(?:my |our )(?:principle|value|philosophy|approach) is\s+([^.,]+)",
]

CURRENT_INDICATORS = [
    "currently",
    "now",
    "right now",
    "at the moment",
    "these days",
    "lately",
    "recently",
    "this week",
    "this month",
    "this year",
    "2024",
    "2025",
    "2026",
]
PAST_INDICATORS = ["used to", "previously", "formerly", "back when", "in the past", "years ago", "last year", "before"]
FUTURE_INDICATORS = ["planning to", "going to", "will", "want to", "hope to", "aiming to", "targeting", "goal is"]

# Negation patterns for detecting what users explicitly reject/avoid
NEGATION_PATTERNS = [
    r"(?:i|we)\s+(?:don'?t|do not|never|won'?t|will not|refuse to|stopped)\s+(?:use|like|want|prefer|work with|recommend|trust|support)\s+([^.,]+)",
    r"(?:i|we)\s+(?:avoid|stay away from|steer clear of|moved away from|dropped|ditched|abandoned)\s+([^.,]+)",
    r"(?:i|we)\s+(?:hate|dislike|can'?t stand|am not a fan of|am against)\s+([^.,]+)",
    r"(?:not|no longer)\s+(?:using|a fan of|interested in|working with)\s+([^.,]+)",
    r"(?:switched|migrated|moved)\s+(?:from|away from)\s+([A-Za-z0-9]+)\s+(?:to|over to)",
    r"(?:i|we)\s+(?:quit|stopped|gave up on|abandoned)\s+([^.,]+)",
]
NEGATION_KEYWORDS = {
    "never",
    "don't",
    "dont",
    "won't",
    "wont",
    "avoid",
    "hate",
    "dislike",
    "stopped",
    "quit",
    "abandoned",
    "dropped",
    "switched from",
    "no longer",
    "not anymore",
    "refuse",
    "against",
}

# Preference patterns for detecting user style/tool preferences
PREFERENCES_PATTERNS = [
    r"(?:i|we)\s+(?:prefer|like|love|enjoy|favor)\s+([^.,]+?)(?:\s+(?:over|to|rather than|instead of)|[.,]|$)",
    r"(?:my|our)\s+(?:preferred|favorite|go-to|default)\s+(?:tool|approach|method|style|way|stack)\s+(?:is|for)\s+([^.,]+)",
    r"(?:i|we)\s+(?:always|usually|typically|generally|tend to)\s+([^.,]+?)(?:\s+(?:when|for|because)|[.,]|$)",
    r"i(?:'m| am)\s+(?:a|an)\s+([A-Za-z-]+)\s+(?:person|type|kind of (?:person|developer|engineer))",
    r"(?:my|our)\s+(?:style|approach|way)\s+(?:is|involves?)\s+([^.,]+)",
]
PREFERENCE_INDICATORS = {
    "prefer",
    "like",
    "love",
    "favor",
    "enjoy",
    "always",
    "usually",
    "typically",
    "my style",
    "my approach",
    "go-to",
    "favorite",
}

# Constraint patterns for budget/timeline/team/technical requirements
CONSTRAINTS_PATTERNS = [
    r"(?:budget|funding|spend|cost)\s+(?:is|of|around|about|under|limit(?:ed to)?)\s*\$?([\d,]+(?:\.\d+)?(?:\s*(?:k|K|M|million|billion))?)",
    r"\$?([\d,]+(?:\.\d+)?(?:\s*(?:k|K|M|million|billion))?)\s+(?:budget|funding|to spend)",
    r"(?:can(?:'t| not)?|cannot)\s+(?:spend|afford)\s+(?:more than|over)\s*\$?([\d,]+)",
    r"(?:deadline|timeline|timeframe|due|launch|go-live)\s+(?:is|in|by|within)\s+([^.,]+)",
    r"(?:need|must|have to)\s+(?:finish|complete|deliver|launch|ship)\s+(?:by|in|within)\s+([^.,]+)",
    r"([0-9]+)\s*(?:weeks?|months?|days?|years?)\s+(?:timeline|deadline|to (?:launch|complete|finish))",
    r"(?:team|staff|engineers?|developers?)\s+(?:of|is|are)\s+([0-9]+(?:\s+(?:people|engineers?|developers?))?)",
    r"([0-9]+)\s+(?:person|people|engineer|developer)s?\s+(?:team|working on)",
    r"(?:only|just)\s+([0-9]+)\s+(?:of us|people|engineers?)",
    r"(?:must|have to|need to|required to)\s+(?:use|support|integrate with|be compatible with)\s+([^.,]+)",
    r"(?:limited|restricted|constrained)\s+(?:to|by)\s+([^.,]+)",
    r"(?:must|need to)\s+(?:comply with|meet|follow|adhere to)\s+([A-Z]{2,}(?:\s+[A-Za-z]+)*)",
    r"([A-Z]{2,})\s+(?:compliant|compliance|certified|requirements?)",
]
CONSTRAINT_TYPES = {
    "budget": ["budget", "funding", "cost", "spend", "afford", "$", "k", "million"],
    "timeline": ["deadline", "timeline", "weeks", "months", "days", "by", "due", "launch"],
    "team": ["team", "people", "engineers", "developers", "staff", "headcount"],
    "technical": ["must use", "limited to", "compatible", "integrate", "support"],
    "regulatory": ["comply", "hipaa", "gdpr", "pci", "sox", "fda", "regulation"],
}

# Correction patterns for tracking user self-corrections
CORRECTIONS_PATTERNS = [
    # "I meant X not Y" pattern - group(1) is correct (X), group(2) is wrong (Y)
    r"(?:i meant|actually)\s+([A-Za-z0-9]+)\s+not\s+([A-Za-z0-9]+)",
    # General correction patterns
    r"(?:actually|sorry|correction|to clarify|let me correct|i misspoke),?\s+(?:i meant|it(?:'s| is)|that(?:'s| is)|it should be|i mean)\s+([^.,]+)",
    r"(?:not|no,?)\s+([A-Za-z0-9\s]+),?\s+(?:but|rather|i meant?|it(?:'s| is))\s+([A-Za-z0-9\s]+)",
    r"(?:i said|when i said)\s+([^,]+),?\s+(?:i meant|but i meant|i actually meant)\s+([^.,]+)",
    r"(?:that(?:'s| is)|i was)\s+wrong,?\s+(?:it(?:'s| is)|it should be|the correct (?:answer|thing) is)\s+([^.,]+)",
    r"(?:typo|error|mistake),?\s+(?:i meant|should be|it(?:'s| is))\s+([^.,]+)",
    r"(?:wait|hold on|no wait),?\s+(?:i meant?|it(?:'s| is)|that(?:'s| is))\s+([^.,]+)",
    r"(?:let me (?:rephrase|restate|clarify)|to be (?:clear|more precise)),?\s+([^.,]+)",
]
CORRECTION_KEYWORDS = {
    "actually",
    "correction",
    "sorry",
    "i meant",
    "typo",
    "mistake",
    "wrong",
    "error",
    "let me correct",
    "to clarify",
    "i misspoke",
    "wait",
    "hold on",
}

STRIP_PREFIXES = ["in ", "that ", "the ", "a ", "an ", "to ", "for ", "with ", "about "]
NOISE_WORDS = {
    "strategies",
    "doing",
    "things",
    "stuff",
    "something",
    "anything",
    "working",
    "building",
    "creating",
    "developing",
    "using",
    "good",
    "great",
    "best",
    "better",
    "important",
    "new",
    "old",
    "first",
    "last",
    "next",
    "other",
}
SKIP_WORDS = {
    "the",
    "this",
    "that",
    "what",
    "when",
    "where",
    "which",
    "who",
    "how",
    "why",
    "our",
    "my",
    "your",
    "their",
    "his",
    "her",
    "its",
    "we",
    "they",
    "he",
    "she",
    "it",
    "you",
    "i",
    "also",
    "just",
    "now",
    "then",
    "here",
    "there",
    "please",
    "thanks",
    "thank",
    "hello",
    "hi",
    "hey",
    "currently",
    "recently",
    "basically",
    "actually",
}

# Order matters: longer/more specific patterns must come before PHONE to avoid
# partial matches (e.g., PHONE matching trailing digits of a credit card number).
PII_PATTERNS = [
    ("EMAIL", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    ("SSN", r"\b\d{3}-\d{2}-\d{4}\b"),
    (
        "CREDIT_CARD",
        r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|6(?:011|5[0-9]{2})[0-9]{12})\b",
    ),
    ("PRIVATE_KEY", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    ("AWS_KEY", r"\bAKIA[0-9A-Z]{16}\b"),
    ("GITHUB_TOKEN", r"\bgh[ps]_[A-Za-z0-9_]{36,}\b"),
    ("API_KEY", r"(?:sk_live_[A-Za-z0-9]{24,}|sk-(?:ant-)?[A-Za-z0-9]{32,}|api[_-]?key[=:\s]+[A-Za-z0-9_\-]{20,})"),
    ("BEARER_TOKEN", r"\bBearer\s+[A-Za-z0-9._\-]{20,}\b"),
    ("DATABASE_URL", r"(?:postgres|mysql|mongodb|redis)://[^\s]+@[^\s]+"),
    ("IP_ADDRESS", r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"),
    ("STREET_ADDRESS", r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}(?:St|Ave|Blvd|Dr|Rd|Ln|Ct|Way|Pl|Cir|Ter|Pkwy)\.?\b"),
    ("PHONE", r"(?:\+?1[-.\s]?)?(?:\(?[0-9]{3}\)?[-.\s]?)[0-9]{3}[-.\s]?[0-9]{4}\b"),
]


class PIIRedactor:
    """Replaces PII in text with typed placeholders like [EMAIL], [PHONE], etc."""

    def __init__(self, custom_patterns: dict[str, str] | None = None):
        self._patterns: list[tuple[str, re.Pattern]] = []
        for label, pattern in PII_PATTERNS:
            self._patterns.append((label, re.compile(pattern)))
        if custom_patterns:
            for label, pattern in custom_patterns.items():
                self._patterns.append((label, re.compile(pattern)))
        self._counts: dict[str, int] = defaultdict(int)
        self._total: int = 0

    def redact(self, text: str) -> str:
        """Replace all PII matches with [TYPE] placeholders."""
        for label, compiled in self._patterns:

            def _replacer(match, _label=label):
                self._counts[_label] += 1
                self._total += 1
                return f"[{_label}]"

            text = compiled.sub(_replacer, text)
        return text

    def get_summary(self) -> dict:
        """Return redaction statistics. Never includes original PII values."""
        return {
            "redaction_applied": True,
            "total_redactions": self._total,
            "by_type": dict(self._counts),
        }


# ============================================================================
# SIMILARITY UTILITIES
# ============================================================================


def normalize_text(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("ASCII")
    text = re.sub(r"[^\w\s-]", "", text)
    return " ".join(text.split())


def get_similarity(s1: str, s2: str) -> float:
    n1, n2 = normalize_text(s1), normalize_text(s2)
    if n1 == n2:
        return 1.0
    if n1 in n2 or n2 in n1:
        return min(len(n1), len(n2)) / max(len(n1), len(n2)) if max(len(n1), len(n2)) > 0 else 0
    return difflib.SequenceMatcher(None, n1, n2).ratio()


def get_word_overlap(s1: str, s2: str) -> float:
    w1, w2 = set(normalize_text(s1).split()), set(normalize_text(s2).split())
    if not w1 or not w2:
        return 0.0
    return len(w1 & w2) / len(w1 | w2)


def are_similar(s1: str, s2: str, threshold: float = SIMILARITY_THRESHOLD) -> bool:
    return max(get_similarity(s1, s2), get_word_overlap(s1, s2)) >= threshold


def find_best_match(topic: str, existing: dict, threshold: float = SIMILARITY_THRESHOLD) -> str | None:
    best_key, best_score = None, threshold
    for key in existing:
        score = max(get_similarity(topic, key), get_word_overlap(topic, key))
        if score > best_score:
            best_score, best_key = score, key
    return best_key


# ============================================================================
# TIME UTILITIES
# ============================================================================


def parse_timestamp(ts: Any) -> datetime | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, TypeError, OSError, OverflowError):
            return None
    if isinstance(ts, str):
        for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
            try:
                return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
    return None


def get_time_decay_multiplier(last_seen: datetime | None, reference: datetime | None = None) -> float:
    if last_seen is None:
        return 0.5
    if reference is None:
        reference = datetime.now(timezone.utc)
    days_ago = (reference - last_seen).days
    for threshold, multiplier in sorted(TIME_DECAY.items()):
        if days_ago <= threshold:
            return multiplier
    return 0.1


# ============================================================================
# TEXT UTILITIES
# ============================================================================


def clean_extracted_text(text: str) -> str:
    text = text.strip()
    lower = text.lower()
    for prefix in STRIP_PREFIXES:
        if lower.startswith(prefix):
            text = text[len(prefix) :]
            break
    text = text.rstrip(".,;:!?")
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text.strip()


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


def extract_entities(text: str) -> list[tuple[str, str]]:
    entities = []
    # Hyphenated/apostrophe names
    for match in re.finditer(r"\b([A-Z][a-z]+(?:[-\'][A-Z]?[a-z]+)*(?:\s+[A-Z][a-z]+(?:[-\'][A-Z]?[a-z]+)*)*)\b", text):
        entity = match.group(1)
        if len(entity) > 2 and entity.lower() not in SKIP_WORDS:
            entities.append((entity, "entity"))
    # Acronyms/CamelCase
    for match in re.finditer(r"\b([A-Z][a-z]+[A-Z][A-Za-z]*|[A-Z]{2,})\b", text):
        entities.append((match.group(1), "tech_entity"))
    return entities


def is_user_message(message: dict) -> bool:
    role = message.get("role", message.get("author", {}).get("role", ""))
    return role in ["user", "human"]


def get_message_text(message: dict) -> str:
    if "content" in message:
        content = message["content"]
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            # ChatGPT format: {"content_type": "text", "parts": ["..."]}
            parts = content.get("parts", [])
            return " ".join(str(p) for p in parts if isinstance(p, str))
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict) and "text" in part:
                    parts.append(part["text"])
            return " ".join(parts)
    if "text" in message:
        return message["text"]
    if "message" in message:
        return get_message_text({"content": message["message"]})
    return ""


def build_eval_compat_view(v4_output: dict) -> dict[str, list[dict]]:
    """Provide the node/contradiction aliases expected by the autoresearch eval harness."""
    from cortex.compat import upgrade_v4_to_v5

    graph = upgrade_v4_to_v5(v4_output)
    nodes = []
    for node in graph.nodes.values():
        nodes.append(
            {
                "id": node.id,
                "label": node.label,
                "value": node.full_description or node.brief or node.label,
                "category": node.tags[0] if node.tags else "mentions",
                "tags": list(node.tags),
                "confidence": round(node.confidence, 2),
                "mention_count": node.mention_count,
            }
        )
    nodes.sort(key=lambda node: (-node["confidence"], node["label"].lower()))
    return {
        "nodes": nodes,
        "contradictions": list(v4_output.get("conflicts", [])),
    }


# ============================================================================
# DATA STRUCTURES
# ============================================================================


@dataclass
class ExtractedTopic:
    topic: str
    category: str
    brief: str = ""
    full_description: str = ""
    confidence: float = 0.5
    extraction_method: str = "mentioned"
    mention_count: int = 1
    metrics: list[str] = field(default_factory=list)
    relationships: list[str] = field(default_factory=list)
    timeline: list[str] = field(default_factory=list)
    source_quotes: list[str] = field(default_factory=list)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    mention_timestamps: list[datetime] = field(default_factory=list)
    relationship_type: str = ""  # partner, mentor, advisor, investor, client, competitor

    def apply_boosts(self, reference_time: datetime | None = None):
        mention_boost = 0.0
        for threshold, b in sorted(MENTION_COUNT_BOOST.items()):
            if self.mention_count >= threshold:
                mention_boost = b
        decay = get_time_decay_multiplier(self.last_seen, reference_time)
        self.confidence = min(0.95, self.confidence + (mention_boost * decay))

    def merge_with(self, other: "ExtractedTopic"):
        self.mention_count += other.mention_count
        self.confidence = max(self.confidence, other.confidence)
        if len(other.brief) > len(self.brief):
            self.brief = other.brief
        if len(other.full_description) > len(self.full_description):
            self.full_description = other.full_description
        self.metrics = list(set(self.metrics + other.metrics))
        self.relationships = list(set(self.relationships + other.relationships))
        self.timeline = list(set(self.timeline + other.timeline))
        self.source_quotes = list(set(self.source_quotes + other.source_quotes))[:5]
        self.mention_timestamps.extend(other.mention_timestamps)
        if other.first_seen and (self.first_seen is None or other.first_seen < self.first_seen):
            self.first_seen = other.first_seen
        if other.last_seen and (self.last_seen is None or other.last_seen > self.last_seen):
            self.last_seen = other.last_seen

    def to_dict(self) -> dict:
        result = {
            "topic": self.topic,
            "brief": self.brief or self.topic,
            "full_description": self.full_description,
            "confidence": round(self.confidence, 2),
            "mention_count": self.mention_count,
            "metrics": self.metrics[:10],
            "relationships": self.relationships[:10],
            "timeline": self.timeline[:5],
            "extraction_method": self.extraction_method,
            "source_quotes": self.source_quotes[:3],
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
        }
        if self.relationship_type:
            result["relationship_type"] = self.relationship_type
        return result


@dataclass
class ExtractionContext:
    topics: dict[str, dict[str, ExtractedTopic]] = field(default_factory=lambda: defaultdict(dict))
    extraction_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    conflicts: list[dict] = field(default_factory=list)
    redaction_summary: dict | None = field(default=None)

    def add_topic(
        self,
        category: str,
        topic: str,
        brief: str = "",
        full_description: str = "",
        confidence: float = None,
        extraction_method: str = "mentioned",
        metrics: list[str] = None,
        relationships: list[str] = None,
        timeline: list[str] = None,
        source_quote: str = "",
        timestamp: datetime | None = None,
        relationship_type: str = "",
    ):
        if not topic or len(topic.strip()) < 2:
            return
        topic = topic.strip()
        key = normalize_text(topic)
        if confidence is None:
            confidence = BASE_CONFIDENCE.get(extraction_method, 0.4)

        existing_key = find_best_match(key, self.topics[category])
        if existing_key:
            existing = self.topics[category][existing_key]
            existing.mention_count += 1
            existing.confidence = max(existing.confidence, confidence)
            if brief and len(brief) > len(existing.brief):
                existing.brief = brief
            if full_description and len(full_description) > len(existing.full_description):
                existing.full_description = full_description
            if metrics:
                existing.metrics = list(set(existing.metrics + metrics))
            if relationships:
                existing.relationships = list(set(existing.relationships + relationships))
            if timeline:
                existing.timeline = list(set(existing.timeline + timeline))
            if source_quote and source_quote not in existing.source_quotes:
                existing.source_quotes.append(source_quote[:200])
            if timestamp:
                existing.mention_timestamps.append(timestamp)
                if existing.last_seen is None or timestamp > existing.last_seen:
                    existing.last_seen = timestamp
            # Update relationship_type if provided and not already set
            if relationship_type and not existing.relationship_type:
                existing.relationship_type = relationship_type
        else:
            self.topics[category][key] = ExtractedTopic(
                topic=topic,
                category=category,
                brief=brief or topic,
                full_description=full_description,
                confidence=confidence,
                extraction_method=extraction_method,
                metrics=metrics or [],
                relationships=relationships or [],
                timeline=timeline or [],
                source_quotes=[source_quote[:200]] if source_quote else [],
                first_seen=timestamp,
                last_seen=timestamp,
                mention_timestamps=[timestamp] if timestamp else [],
                relationship_type=relationship_type,
            )

    def merge_similar_topics(self):
        for category in MERGEABLE_CATEGORIES:
            if category not in self.topics:
                continue
            keys = list(self.topics[category].keys())
            merged = set()
            for i, key1 in enumerate(keys):
                if key1 in merged:
                    continue
                for key2 in keys[i + 1 :]:
                    if key2 in merged:
                        continue
                    topic1, topic2 = self.topics[category][key1], self.topics[category][key2]
                    if are_similar(topic1.topic, topic2.topic, threshold=0.8):
                        if topic1.confidence >= topic2.confidence:
                            topic1.merge_with(topic2)
                            merged.add(key2)
                        else:
                            topic2.merge_with(topic1)
                            merged.add(key1)
                            break
            for key in merged:
                if key in self.topics[category]:
                    del self.topics[category][key]

    def apply_time_decay(self):
        for topics in self.topics.values():
            for topic in topics.values():
                topic.apply_boosts(self.extraction_time)

    def detect_conflicts(self) -> list[dict]:
        """Detect contradictory statements across categories.

        Looks for items that appear in both positive categories (like technical_expertise)
        AND negations category. For example, "I use Python" vs "I don't use Python".
        """
        conflicts = []

        if "negations" not in self.topics:
            return conflicts

        # Check for items in both positive categories AND negations
        positive_categories = ["technical_expertise", "domain_knowledge", "values", "user_preferences"]

        for pos_category in positive_categories:
            if pos_category not in self.topics:
                continue

            for pos_key, pos_topic in self.topics[pos_category].items():
                for neg_key, neg_topic in self.topics["negations"].items():
                    if are_similar(pos_topic.topic, neg_topic.topic, threshold=0.7):
                        # Determine which is more recent
                        pos_time = pos_topic.last_seen
                        neg_time = neg_topic.last_seen

                        # Determine resolution strategy
                        if neg_time and pos_time and neg_time > pos_time:
                            resolution = "prefer_negation"
                        elif pos_time and neg_time and pos_time > neg_time:
                            resolution = "prefer_positive"
                        else:
                            resolution = "needs_review"

                        conflicts.append(
                            {
                                "type": "negation_conflict",
                                "positive_category": pos_category,
                                "positive_topic": pos_topic.topic,
                                "positive_confidence": round(pos_topic.confidence, 2),
                                "positive_last_seen": pos_time.isoformat() if pos_time else None,
                                "negative_topic": neg_topic.topic,
                                "negative_confidence": round(neg_topic.confidence, 2),
                                "negative_last_seen": neg_time.isoformat() if neg_time else None,
                                "resolution": resolution,
                            }
                        )

        return conflicts

    def export(self) -> dict:
        output = {
            "schema_version": "4.0",
            "meta": {
                "generated_at": self.extraction_time.isoformat(),
                "method": "aggressive_extraction_v4",
                "features": [
                    "semantic_dedup",
                    "time_decay",
                    "topic_merging",
                    "conflict_detection",
                    "typed_relationships",
                ],
            },
            "categories": {},
        }
        for category, topics in self.topics.items():
            if topics:
                sorted_topics = sorted(topics.values(), key=lambda t: (t.confidence, t.mention_count), reverse=True)
                output["categories"][category] = [t.to_dict() for t in sorted_topics]
        if self.conflicts:
            output["conflicts"] = self.conflicts
        if self.redaction_summary is not None:
            output["redaction_summary"] = self.redaction_summary
        output.update(build_eval_compat_view(output))
        return output

    def stats(self) -> dict:
        total = sum(len(t) for t in self.topics.values())
        by_category = {cat: len(topics) for cat, topics in self.topics.items()}
        high = sum(1 for topics in self.topics.values() for t in topics.values() if t.confidence >= 0.8)
        med = sum(1 for topics in self.topics.values() for t in topics.values() if 0.6 <= t.confidence < 0.8)
        low = sum(1 for topics in self.topics.values() for t in topics.values() if t.confidence < 0.6)
        return {"total": total, "by_category": by_category, "by_confidence": {"high": high, "medium": med, "low": low}}

    def to_graph(self):
        """Convert extraction results to a CortexGraph (v5).

        Builds a v4 dict via export(), then upgrades via compat layer.
        This avoids duplicating conversion logic.
        """
        from cortex.compat import upgrade_v4_to_v5

        return upgrade_v4_to_v5(self.export())


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
            for match in re.finditer(pattern, text):
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
                role = match.group(1).strip()
                if 3 < len(role) < 100:
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
            self.context.add_topic(
                "professional_context",
                f"{match.group(1)} {match.group(2)}".strip(),
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
                project = match.group(1).strip() if match.lastindex >= 1 else ""
                if 3 < len(project) < 200:
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
                focus = match.group(1).strip()
                if 5 < len(focus) < 200:
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
                if len(keyword) <= 3:
                    if not re.search(r"\b" + re.escape(keyword) + r"\b", lower):
                        continue
                    if keyword in TECH_FALSE_POSITIVES and not any(
                        tc in lower for tc in ["language", "programming", "code", "develop", "stack", "use", "prefer"]
                    ):
                        continue
                elif keyword not in lower:
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
                    source_quote=extract_with_context(text, keyword, 30),
                    timestamp=timestamp,
                )

    def _extract_domains(self, text: str, timestamp: datetime | None = None):
        lower = text.lower()
        for domain, keywords in DOMAIN_KEYWORDS.items():
            matches = [kw for kw in keywords if kw in lower]
            if matches:
                for kw in matches:
                    self.context.add_topic(
                        "domain_knowledge",
                        kw.title(),
                        brief=f"{domain}: {kw}",
                        extraction_method="contextual",
                        source_quote=extract_with_context(text, kw, 50),
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
            (r"\bdon'?t use bullet points(?: for everything)?\b", "prose over bullet points when appropriate", "communication_preferences"),
            (r"\bwrite in prose(?: when it makes sense)?\b", "prose over bullet points when appropriate", "communication_preferences"),
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


def load_file(file_path: Path) -> tuple[Any, str]:
    if file_path.suffix == ".zip":
        _MAX_ZIP_ENTRY_SIZE = 100 * 1024 * 1024  # 100 MB limit (#26)
        with zipfile.ZipFile(file_path, "r") as zf:
            # Single-pass: categorize safe entries by priority
            conversations_entry: str | None = None
            json_entry: str | None = None
            txt_entry: str | None = None
            for name in zf.namelist():
                # Skip path traversal entries (#11)
                if ".." in name or os.path.isabs(name):
                    continue
                info = zf.getinfo(name)
                if info.file_size > _MAX_ZIP_ENTRY_SIZE:
                    continue
                if conversations_entry is None and "conversations.json" in name:
                    conversations_entry = name
                elif json_entry is None and name.endswith(".json"):
                    json_entry = name
                elif txt_entry is None and name.endswith(".txt"):
                    txt_entry = name

            # Load by priority: conversations.json > any .json > any .txt
            if conversations_entry is not None:
                with zf.open(conversations_entry) as f:
                    return json.load(f), "openai"
            if json_entry is not None:
                with zf.open(json_entry) as f:
                    return json.load(f), "generic"
            if txt_entry is not None:
                with zf.open(txt_entry) as f:
                    return f.read().decode("utf-8"), "text"
        raise ValueError("No supported files in zip")

    # JSONL format: one JSON object per line
    if file_path.suffix == ".jsonl":
        messages = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        # Check if this is Claude Code session JSONL
        if messages and len(messages) >= 2:
            first_real = next(
                (r for r in messages if isinstance(r, dict) and r.get("type") in ("user", "assistant", "system")),
                None,
            )
            if first_real is not None and "sessionId" in first_real and "cwd" in first_real:
                return messages, "claude_code"
        return messages, "jsonl"

    if file_path.suffix == ".json":
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Detection order: most specific to most generic

        # 1. OpenAI export (has "mapping" structure)
        if isinstance(data, list) and data and "mapping" in data[0]:
            return data, "openai"
        if isinstance(data, dict) and ("conversations" in data or "mapping" in data):
            if "mapping" in data:
                return data, "openai"
            convs = data.get("conversations", [])
            if convs and isinstance(convs, list) and convs[0] and "mapping" in convs[0]:
                return data, "openai"

        # 2. Perplexity (has "threads" key with specific structure)
        if isinstance(data, dict) and "threads" in data:
            threads = data["threads"]
            if threads and isinstance(threads[0], dict) and "messages" in threads[0]:
                return data, "perplexity"

        # 3. Gemini (has "conversations" with "turns" or "model" author format)
        if isinstance(data, dict) and "conversations" in data:
            convs = data["conversations"]
            if convs and isinstance(convs[0], dict):
                first_conv = convs[0]
                # Check for Gemini "turns" structure
                if "turns" in first_conv:
                    return data, "gemini"
                # Check for Gemini author format
                if "messages" in first_conv:
                    msgs = first_conv["messages"]
                    if msgs and isinstance(msgs[0], dict) and msgs[0].get("author") in ["user", "model"]:
                        return data, "gemini"

        # 4. API logs (has "requests" with messages arrays)
        if isinstance(data, dict) and "requests" in data:
            return data, "api_logs"
        if isinstance(data, list) and data and "messages" in data[0] and "model" in data[0]:
            return {"requests": data}, "api_logs"

        # 5. Generic messages list
        if isinstance(data, dict) and "messages" in data:
            return data.get("messages", []), "messages"

        # 6. Plain messages array
        if isinstance(data, list) and data and isinstance(data[0], dict):
            if "role" in data[0] or "author" in data[0]:
                return data, "messages"

        return data, "generic"

    if file_path.suffix in [".txt", ".md"]:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read(), "text"
    raise ValueError(f"Unsupported format: {file_path.suffix}")


def main():
    parser = argparse.ArgumentParser(description="Aggressive memory extraction v4")
    parser.add_argument("input_file", help="Path to export file")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument(
        "--format",
        "-f",
        choices=["auto", "openai", "gemini", "perplexity", "jsonl", "api_logs", "messages", "text", "generic"],
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
