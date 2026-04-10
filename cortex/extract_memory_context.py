from __future__ import annotations

import difflib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

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


def build_eval_compat_view(v4_output: dict) -> dict[str, list[dict]]:
    """Provide flat node and contradiction aliases for downstream compatibility."""
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
    relationship_type: str = ""

    def apply_boosts(self, reference_time: datetime | None = None):
        mention_boost = 0.0
        for threshold, boost in sorted(MENTION_COUNT_BOOST.items()):
            if self.mention_count >= threshold:
                mention_boost = boost
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
            if relationship_type and not existing.relationship_type:
                existing.relationship_type = relationship_type
            return

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
            for index, key1 in enumerate(keys):
                if key1 in merged:
                    continue
                for key2 in keys[index + 1 :]:
                    if key2 in merged:
                        continue
                    topic1 = self.topics[category][key1]
                    topic2 = self.topics[category][key2]
                    if not are_similar(topic1.topic, topic2.topic, threshold=0.8):
                        continue
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
        """Detect contradictory statements across categories."""
        conflicts = []

        if "negations" not in self.topics:
            return conflicts

        positive_categories = ["technical_expertise", "domain_knowledge", "values", "user_preferences"]

        for pos_category in positive_categories:
            if pos_category not in self.topics:
                continue
            for pos_topic in self.topics[pos_category].values():
                for neg_topic in self.topics["negations"].values():
                    if not are_similar(pos_topic.topic, neg_topic.topic, threshold=0.7):
                        continue

                    pos_time = pos_topic.last_seen
                    neg_time = neg_topic.last_seen
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
                output["categories"][category] = [topic.to_dict() for topic in sorted_topics]
        if self.conflicts:
            output["conflicts"] = self.conflicts
        if self.redaction_summary is not None:
            output["redaction_summary"] = self.redaction_summary
        output.update(build_eval_compat_view(output))
        return output

    def stats(self) -> dict:
        total = sum(len(topics) for topics in self.topics.values())
        by_category = {category: len(topics) for category, topics in self.topics.items()}
        high = sum(1 for topics in self.topics.values() for topic in topics.values() if topic.confidence >= 0.8)
        medium = sum(1 for topics in self.topics.values() for topic in topics.values() if 0.6 <= topic.confidence < 0.8)
        low = sum(1 for topics in self.topics.values() for topic in topics.values() if topic.confidence < 0.6)
        return {
            "total": total,
            "by_category": by_category,
            "by_confidence": {"high": high, "medium": medium, "low": low},
        }

    def to_graph(self):
        """Convert extraction results to a CortexGraph (v5)."""
        from cortex.compat import upgrade_v4_to_v5

        return upgrade_v4_to_v5(self.export())


__all__ = [
    "BASE_CONFIDENCE",
    "ExtractionContext",
    "ExtractedTopic",
    "MENTION_COUNT_BOOST",
    "MERGEABLE_CATEGORIES",
    "SIMILARITY_THRESHOLD",
    "TIME_DECAY",
    "are_similar",
    "build_eval_compat_view",
    "find_best_match",
    "get_similarity",
    "get_time_decay_multiplier",
    "get_word_overlap",
    "normalize_text",
]
