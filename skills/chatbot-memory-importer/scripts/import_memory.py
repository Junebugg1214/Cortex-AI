#!/usr/bin/env python3
"""
Chatbot Memory Importer v4.0

EXPORTS TO:
- Claude Preferences (Settings > Profile)
- Claude Memories (JSON for memory_user_edits)
- System Prompts (XML for any LLM API)
- Notion (Markdown for Notion pages/databases)
- Google Docs (HTML for Google Docs import)
- Summary (Markdown with confidence indicators)
- Full JSON (lossless v4 schema)

Usage:
    python import_memory_v4.py <context_file> [options]
    
    # All formats
    python import_memory_v4.py context.json -f all -o ./output
    
    # Just Notion export
    python import_memory_v4.py context.json -f notion -c medium
    
    # Google Docs with high confidence only
    python import_memory_v4.py context.json -f gdocs -c high
"""

import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any


# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIDENCE_THRESHOLDS = {
    "high": 0.8,
    "medium": 0.6,
    "low": 0.4,
    "all": 0.0
}

CATEGORY_LABELS = {
    "identity": "Identity",
    "professional_context": "Professional Role",
    "business_context": "Business/Company",
    "active_priorities": "Current Focus",
    "relationships": "Relationships & Partners",
    "technical_expertise": "Technical Skills",
    "domain_knowledge": "Domain Expertise",
    "market_context": "Market Context",
    "metrics": "Key Metrics",
    "constraints": "Constraints & Limitations",
    "values": "Values & Principles",
    "negations": "Dislikes & Avoidances",
    "user_preferences": "User Preferences",
    "communication_preferences": "Communication Style",
    "correction_history": "Corrections & Clarifications",
    "history": "History",
    "mentions": "Other Mentions"
}

CATEGORY_ORDER = [
    "identity", "professional_context", "business_context", "active_priorities",
    "relationships", "technical_expertise", "domain_knowledge", "market_context",
    "metrics", "constraints", "values", "negations", "user_preferences",
    "communication_preferences", "correction_history", "history", "mentions"
]

# Notion colors for different confidence levels
NOTION_COLORS = {
    "high": "green",
    "medium": "yellow", 
    "low": "gray"
}


# ============================================================================
# DATA LOADING
# ============================================================================

@dataclass
class TopicDetail:
    topic: str
    category: str
    brief: str = ""
    full_description: str = ""
    confidence: float = 0.5
    mention_count: int = 1
    metrics: list[str] = field(default_factory=list)
    relationships: list[str] = field(default_factory=list)
    timeline: list[str] = field(default_factory=list)
    source_quotes: list[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    
    @classmethod
    def from_dict(cls, data: dict, category: str) -> 'TopicDetail':
        return cls(
            topic=data.get("topic", ""),
            category=category,
            brief=data.get("brief", data.get("topic", "")),
            full_description=data.get("full_description", ""),
            confidence=data.get("confidence", 0.5),
            mention_count=data.get("mention_count", 1),
            metrics=data.get("metrics", []),
            relationships=data.get("relationships", []),
            timeline=data.get("timeline", []),
            source_quotes=data.get("source_quotes", []),
            first_seen=data.get("first_seen", ""),
            last_seen=data.get("last_seen", "")
        )
    
    def get_detail_level(self) -> str:
        if self.confidence >= 0.8:
            return "full"
        elif self.confidence >= 0.6:
            return "moderate"
        else:
            return "minimal"
    
    def format_full(self) -> str:
        parts = [self.full_description or self.brief or self.topic]
        if self.metrics:
            parts.append(f"Metrics: {', '.join(self.metrics[:3])}")
        if self.relationships:
            parts.append(f"Related: {', '.join(self.relationships[:3])}")
        if self.timeline:
            parts.append(f"Timeline: {', '.join(self.timeline)}")
        return " | ".join(parts)
    
    def format_moderate(self) -> str:
        return self.brief or self.topic
    
    def format_minimal(self) -> str:
        return f"Mentioned: {self.topic}"
    
    def format_by_confidence(self, min_threshold: float = 0.4) -> str:
        if self.confidence < min_threshold:
            return ""
        level = self.get_detail_level()
        if level == "full":
            return self.format_full()
        elif level == "moderate":
            return self.format_moderate()
        else:
            return self.format_minimal()


@dataclass
class NormalizedContext:
    categories: dict[str, list[TopicDetail]] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    
    @classmethod
    def from_v4(cls, data: dict) -> 'NormalizedContext':
        ctx = cls()
        ctx.meta = data.get("meta", {})
        for category, topics in data.get("categories", {}).items():
            ctx.categories[category] = [TopicDetail.from_dict(t, category) for t in topics]
        return ctx
    
    @classmethod
    def from_v3(cls, data: dict) -> 'NormalizedContext':
        return cls.from_v4(data)  # Same structure
    
    @classmethod
    def from_openai(cls, data: dict) -> 'NormalizedContext':
        """Parse OpenAI context export format"""
        ctx = cls()
        ctx.meta = {"source": "openai", "generated_at": datetime.now(timezone.utc).isoformat()}
        
        mappings = {
            "identity": ["identity", "name", "who_i_am"],
            "professional_context": ["professional_roles", "job", "occupation", "role"],
            "business_context": ["company", "organization", "business", "startup"],
            "active_priorities": ["active_projects", "current_focus", "goals", "priorities"],
            "technical_expertise": ["technical_skills", "technologies", "tools", "languages", "frameworks"],
            "domain_knowledge": ["domains_of_expertise", "expertise", "knowledge_areas", "specializations"],
            "values": ["values", "principles", "beliefs", "values_and_constraints"],
            "communication_preferences": ["preferences", "communication_style", "style"],
            "relationships": ["relationships", "partnerships", "collaborations"],
            "market_context": ["market", "competitors", "industry"],
        }
        
        for target_cat, source_keys in mappings.items():
            topics = []
            for key in source_keys:
                if key in data:
                    value = data[key]
                    if isinstance(value, str):
                        topics.append(TopicDetail(topic=value, category=target_cat, brief=value, confidence=0.8))
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, str):
                                topics.append(TopicDetail(topic=item, category=target_cat, brief=item, confidence=0.7))
                            elif isinstance(item, dict):
                                topics.append(TopicDetail(
                                    topic=item.get("name", item.get("topic", str(item))),
                                    category=target_cat,
                                    brief=item.get("description", item.get("brief", "")),
                                    full_description=item.get("details", item.get("full_description", "")),
                                    confidence=item.get("confidence", 0.7)
                                ))
            if topics:
                ctx.categories[target_cat] = topics
        
        return ctx
    
    @classmethod
    def load(cls, file_path: Path) -> 'NormalizedContext':
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        version = data.get("schema_version", "")
        if version.startswith("4"):
            return cls.from_v4(data)
        elif version.startswith("3"):
            return cls.from_v3(data)
        elif "categories" in data:
            return cls.from_v4(data)
        else:
            return cls.from_openai(data)
    
    def get_topics_by_confidence(self, min_confidence: float = 0.4) -> dict[str, list[TopicDetail]]:
        result = {}
        for cat in CATEGORY_ORDER:
            if cat in self.categories:
                filtered = [t for t in self.categories[cat] if t.confidence >= min_confidence]
                if filtered:
                    result[cat] = sorted(filtered, key=lambda t: -t.confidence)
        return result
    
    def stats(self, min_confidence: float = 0.0) -> dict:
        topics = self.get_topics_by_confidence(min_confidence)
        total = sum(len(t) for t in topics.values())
        high = sum(1 for ts in topics.values() for t in ts if t.confidence >= 0.8)
        med = sum(1 for ts in topics.values() for t in ts if 0.6 <= t.confidence < 0.8)
        low = sum(1 for ts in topics.values() for t in ts if t.confidence < 0.6)
        return {
            "total": total,
            "by_category": {cat: len(ts) for cat, ts in topics.items()},
            "by_confidence": {"high": high, "medium": med, "low": low}
        }


# ============================================================================
# EXPORT FORMATS
# ============================================================================

def export_claude_preferences(ctx: NormalizedContext, min_confidence: float = 0.6) -> str:
    """Generate natural language for Claude Settings > Profile"""
    lines = []
    topics = ctx.get_topics_by_confidence(min_confidence)
    
    # Identity
    if "identity" in topics:
        names = [t.topic for t in topics["identity"]]
        lines.append(f"I am {'; '.join(names)}.")
    
    # Professional
    if "professional_context" in topics:
        roles = [t.format_by_confidence(min_confidence) for t in topics["professional_context"]]
        lines.append(f"Role: {'; '.join(filter(None, roles))}")
    
    # Business
    if "business_context" in topics:
        biz = [t.format_by_confidence(min_confidence) for t in topics["business_context"]]
        lines.append(f"Business: {'; '.join(filter(None, biz))}")
    
    # Focus
    if "active_priorities" in topics:
        focus = [t.format_by_confidence(min_confidence) for t in topics["active_priorities"][:5]]
        lines.append(f"Currently focused on: {'; '.join(filter(None, focus))}")
    
    # Technical
    if "technical_expertise" in topics:
        tech = [t.brief for t in topics["technical_expertise"]]
        lines.append(f"Technical: {'; '.join(tech[:10])}")
    
    # Domain
    if "domain_knowledge" in topics:
        domains = [t.brief for t in topics["domain_knowledge"]]
        lines.append(f"Domain expertise: {'; '.join(domains[:10])}")
    
    # Values
    if "values" in topics:
        vals = [t.topic for t in topics["values"]]
        lines.append(f"Values: {'; '.join(vals)}")
    
    # Communication
    if "communication_preferences" in topics:
        prefs = [t.topic for t in topics["communication_preferences"]]
        lines.append(f"Communication: {'; '.join(prefs)}")
    
    # Relationships
    if "relationships" in topics:
        rels = [t.format_by_confidence(min_confidence) for t in topics["relationships"][:5]]
        lines.append(f"Key relationships: {'; '.join(filter(None, rels))}")
    
    # Market
    if "market_context" in topics:
        market = [t.brief for t in topics["market_context"]]
        lines.append(f"Market context: {'; '.join(market)}")
    
    # Metrics
    if "metrics" in topics:
        metrics = [t.brief for t in topics["metrics"][:5]]
        lines.append(f"Key metrics: {'; '.join(metrics)}")

    # Constraints
    if "constraints" in topics:
        constraints = [t.brief for t in topics["constraints"]]
        lines.append(f"Constraints: {'; '.join(constraints)}")

    # Negations
    if "negations" in topics:
        negations = [t.topic for t in topics["negations"]]
        lines.append(f"Avoids/dislikes: {'; '.join(negations)}")

    # User Preferences
    if "user_preferences" in topics:
        prefs = [t.topic for t in topics["user_preferences"]]
        lines.append(f"Preferences: {'; '.join(prefs)}")

    # Correction History
    if "correction_history" in topics:
        corrections = [t.brief for t in topics["correction_history"][:3]]
        lines.append(f"Recent clarifications: {'; '.join(corrections)}")

    return "\n".join(lines)


def export_claude_memories(ctx: NormalizedContext, min_confidence: float = 0.6, max_items: int = 30) -> list[dict]:
    """Generate memories for Claude memory_user_edits tool"""
    memories = []
    topics = ctx.get_topics_by_confidence(min_confidence)
    
    priority_order = ["identity", "business_context", "professional_context", "active_priorities",
                      "relationships", "technical_expertise", "domain_knowledge", "market_context",
                      "metrics", "constraints", "values", "negations", "user_preferences",
                      "communication_preferences", "correction_history", "mentions"]
    
    for category in priority_order:
        if category not in topics:
            continue
        
        for topic in topics[category]:
            if len(memories) >= max_items:
                break
            
            level = topic.get_detail_level()
            
            if category == "identity":
                text = f"User is {topic.topic}"
            elif category == "business_context":
                text = f"User's business: {topic.format_by_confidence(min_confidence)}"
            elif category == "professional_context":
                text = f"User role: {topic.format_by_confidence(min_confidence)}"
            elif category == "active_priorities":
                text = f"User focus: {topic.format_by_confidence(min_confidence)}"
            elif category == "relationships":
                text = f"User relationship: {topic.format_by_confidence(min_confidence)}"
            elif category == "technical_expertise":
                text = f"User tech: {topic.brief}"
            elif category == "domain_knowledge":
                text = f"User domain: {topic.brief}"
            elif category == "market_context":
                text = f"Market context: {topic.brief}"
            elif category == "metrics":
                text = f"Key metric: {topic.brief}"
            elif category == "values":
                text = f"User values {topic.topic}"
            elif category == "communication_preferences":
                text = f"User prefers {topic.topic}"
            elif category == "constraints":
                text = f"Constraint: {topic.brief}"
            elif category == "negations":
                text = f"User avoids: {topic.topic}"
            elif category == "user_preferences":
                text = f"User prefers: {topic.topic}"
            elif category == "correction_history":
                text = f"User clarified: {topic.brief}"
            else:
                text = f"Mentioned: {topic.brief}"
            
            # Truncate to fit Claude memory limits
            if len(text) > 200:
                text = text[:197] + "..."
            
            memories.append({
                "text": text,
                "confidence": topic.confidence,
                "category": category
            })
        
        if len(memories) >= max_items:
            break
    
    return memories


def export_system_prompt(ctx: NormalizedContext, min_confidence: float = 0.6) -> str:
    """Generate XML context block for system prompts"""
    lines = ["<user_context>"]
    topics = ctx.get_topics_by_confidence(min_confidence)

    for category in CATEGORY_ORDER:
        if category not in topics:
            continue

        label = CATEGORY_LABELS.get(category, category)

        # Special treatment for constraints
        if category == "constraints":
            lines.append(f"  <{category}>")
            lines.append("    <!-- IMPORTANT: These are hard constraints that must be respected -->")
            for topic in topics[category]:
                lines.append(f"    - {topic.brief}")
            lines.append(f"  </{category}>")
            continue

        # Special treatment for negations
        if category == "negations":
            lines.append(f"  <{category}>")
            lines.append("    <!-- User explicitly avoids these -->")
            for topic in topics[category]:
                lines.append(f"    - {topic.topic}")
            lines.append(f"  </{category}>")
            continue

        # Special treatment for correction history
        if category == "correction_history":
            lines.append(f"  <{category}>")
            lines.append("    <!-- Patterns where user has corrected themselves before -->")
            for topic in topics[category]:
                lines.append(f"    - {topic.brief}")
            lines.append(f"  </{category}>")
            continue

        lines.append(f"  <{category}>")

        for topic in topics[category]:
            level = topic.get_detail_level()
            formatted = topic.format_by_confidence(min_confidence)
            if formatted:
                if level == "minimal":
                    lines.append(f"    [{formatted}]")
                else:
                    lines.append(f"    - {formatted}")

        lines.append(f"  </{category}>")

    lines.append("</user_context>")
    return "\n".join(lines)


def export_notion(ctx: NormalizedContext, min_confidence: float = 0.6) -> str:
    """Generate Notion-flavored Markdown for import"""
    lines = ["# User Context Profile", ""]
    lines.append(f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> Confidence threshold: {min_confidence}")
    lines.append("")
    
    topics = ctx.get_topics_by_confidence(min_confidence)
    
    # Summary callout
    stats = ctx.stats(min_confidence)
    lines.append("## 📊 Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total Topics | {stats['total']} |")
    lines.append(f"| High Confidence | {stats['by_confidence']['high']} |")
    lines.append(f"| Medium Confidence | {stats['by_confidence']['medium']} |")
    lines.append(f"| Low Confidence | {stats['by_confidence']['low']} |")
    lines.append("")
    
    # Categories
    for category in CATEGORY_ORDER:
        if category not in topics:
            continue
        
        label = CATEGORY_LABELS.get(category, category)
        emoji = {
            "identity": "👤", "professional_context": "💼", "business_context": "🏢",
            "active_priorities": "🎯", "relationships": "🤝", "technical_expertise": "💻",
            "domain_knowledge": "📚", "market_context": "📈", "metrics": "📊",
            "constraints": "🚧", "values": "💡", "negations": "🚫",
            "user_preferences": "⚙️", "communication_preferences": "💬",
            "correction_history": "✏️", "mentions": "📌"
        }.get(category, "•")
        
        lines.append(f"## {emoji} {label}")
        lines.append("")
        
        for topic in topics[category]:
            level = topic.get_detail_level()
            conf_badge = {"full": "🟢", "moderate": "🟡", "minimal": "🟠"}.get(level, "⚪")
            
            if level == "full":
                lines.append(f"### {conf_badge} {topic.topic}")
                if topic.full_description:
                    lines.append(f"{topic.full_description}")
                elif topic.brief and topic.brief != topic.topic:
                    lines.append(f"{topic.brief}")
                if topic.metrics:
                    lines.append(f"- **Metrics:** {', '.join(topic.metrics[:3])}")
                if topic.relationships:
                    lines.append(f"- **Related:** {', '.join(topic.relationships[:3])}")
                if topic.timeline:
                    lines.append(f"- **Timeline:** {', '.join(topic.timeline)}")
                lines.append("")
            elif level == "moderate":
                lines.append(f"- {conf_badge} **{topic.topic}**: {topic.brief}")
            else:
                lines.append(f"- {conf_badge} {topic.topic}")
        
        lines.append("")
    
    # Database template
    lines.append("---")
    lines.append("## 📋 Database Template")
    lines.append("")
    lines.append("To create a Notion database from this data, use these properties:")
    lines.append("")
    lines.append("| Property | Type | Description |")
    lines.append("|----------|------|-------------|")
    lines.append("| Topic | Title | The main topic name |")
    lines.append("| Category | Select | Category classification |")
    lines.append("| Confidence | Number | 0.0-1.0 confidence score |")
    lines.append("| Detail Level | Select | full/moderate/minimal |")
    lines.append("| Brief | Text | Short description |")
    lines.append("| Metrics | Multi-select | Associated metrics |")
    lines.append("")
    
    return "\n".join(lines)


def export_notion_database_json(ctx: NormalizedContext, min_confidence: float = 0.6) -> list[dict]:
    """Generate JSON for Notion database import"""
    rows = []
    topics = ctx.get_topics_by_confidence(min_confidence)
    
    for category in CATEGORY_ORDER:
        if category not in topics:
            continue
        
        for topic in topics[category]:
            rows.append({
                "Topic": topic.topic,
                "Category": CATEGORY_LABELS.get(category, category),
                "Confidence": topic.confidence,
                "Detail Level": topic.get_detail_level(),
                "Brief": topic.brief,
                "Full Description": topic.full_description,
                "Metrics": topic.metrics[:5],
                "Relationships": topic.relationships[:5],
                "Timeline": ", ".join(topic.timeline) if topic.timeline else "",
                "Mention Count": topic.mention_count
            })
    
    return rows


def export_google_docs(ctx: NormalizedContext, min_confidence: float = 0.6) -> str:
    """Generate HTML for Google Docs import"""
    lines = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        "<meta charset='UTF-8'>",
        "<title>User Context Profile</title>",
        "<style>",
        "body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }",
        "h1 { color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px; }",
        "h2 { color: #34a853; margin-top: 30px; }",
        "h3 { color: #333; }",
        ".high { color: #34a853; }",
        ".medium { color: #fbbc04; }",
        ".low { color: #9aa0a6; }",
        ".badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-left: 8px; }",
        ".badge-high { background: #e6f4ea; color: #34a853; }",
        ".badge-medium { background: #fef7e0; color: #f9ab00; }",
        ".badge-low { background: #f1f3f4; color: #5f6368; }",
        "table { border-collapse: collapse; width: 100%; margin: 20px 0; }",
        "th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }",
        "th { background: #f1f3f4; }",
        ".metric { background: #e8f0fe; padding: 4px 8px; border-radius: 4px; margin: 2px; display: inline-block; }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>User Context Profile</h1>",
        f"<p><em>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</em></p>",
    ]
    
    topics = ctx.get_topics_by_confidence(min_confidence)
    stats = ctx.stats(min_confidence)
    
    # Summary table
    lines.append("<h2>Summary</h2>")
    lines.append("<table>")
    lines.append("<tr><th>Metric</th><th>Value</th></tr>")
    lines.append(f"<tr><td>Total Topics</td><td>{stats['total']}</td></tr>")
    lines.append(f"<tr><td>High Confidence</td><td class='high'>{stats['by_confidence']['high']}</td></tr>")
    lines.append(f"<tr><td>Medium Confidence</td><td class='medium'>{stats['by_confidence']['medium']}</td></tr>")
    lines.append(f"<tr><td>Low Confidence</td><td class='low'>{stats['by_confidence']['low']}</td></tr>")
    lines.append("</table>")
    
    # Categories
    for category in CATEGORY_ORDER:
        if category not in topics:
            continue
        
        label = CATEGORY_LABELS.get(category, category)
        lines.append(f"<h2>{label}</h2>")
        
        for topic in topics[category]:
            level = topic.get_detail_level()
            badge_class = f"badge-{level}"
            
            if level == "full":
                lines.append(f"<h3>{topic.topic} <span class='badge {badge_class}'>High</span></h3>")
                if topic.full_description:
                    lines.append(f"<p>{topic.full_description}</p>")
                elif topic.brief and topic.brief != topic.topic:
                    lines.append(f"<p>{topic.brief}</p>")
                if topic.metrics:
                    lines.append("<p><strong>Metrics:</strong> ")
                    for m in topic.metrics[:3]:
                        lines.append(f"<span class='metric'>{m}</span> ")
                    lines.append("</p>")
                if topic.relationships:
                    lines.append(f"<p><strong>Related:</strong> {', '.join(topic.relationships[:3])}</p>")
                if topic.timeline:
                    lines.append(f"<p><strong>Timeline:</strong> {', '.join(topic.timeline)}</p>")
            elif level == "moderate":
                lines.append(f"<p><strong>{topic.topic}</strong> <span class='badge {badge_class}'>Medium</span>: {topic.brief}</p>")
            else:
                lines.append(f"<p class='low'>{topic.topic} <span class='badge {badge_class}'>Low</span></p>")
    
    lines.append("</body>")
    lines.append("</html>")
    
    return "\n".join(lines)


def export_summary(ctx: NormalizedContext, min_confidence: float = 0.4) -> str:
    """Generate markdown summary with confidence indicators"""
    lines = ["# User Context Summary", ""]
    
    topics = ctx.get_topics_by_confidence(min_confidence)
    stats = ctx.stats(min_confidence)
    
    lines.append(f"**Total:** {stats['total']} topics")
    lines.append(f"- 🟢 High confidence: {stats['by_confidence']['high']}")
    lines.append(f"- 🟡 Medium confidence: {stats['by_confidence']['medium']}")
    lines.append(f"- 🟠 Low confidence: {stats['by_confidence']['low']}")
    lines.append("")
    
    for category in CATEGORY_ORDER:
        if category not in topics:
            continue
        
        label = CATEGORY_LABELS.get(category, category)
        lines.append(f"## {label}")
        lines.append("")
        
        # Group by detail level
        full_items = [t for t in topics[category] if t.get_detail_level() == "full"]
        mod_items = [t for t in topics[category] if t.get_detail_level() == "moderate"]
        min_items = [t for t in topics[category] if t.get_detail_level() == "minimal"]
        
        for item in full_items:
            lines.append(f"- 🟢 **{item.topic}**: {item.format_full()}")
        for item in mod_items:
            lines.append(f"- 🟡 {item.topic}: {item.brief}")
        for item in min_items:
            lines.append(f"- 🟠 {item.topic}")
        
        lines.append("")
    
    return "\n".join(lines)


def export_full_json(ctx: NormalizedContext, min_confidence: float = 0.0) -> dict:
    """Export full lossless JSON"""
    topics = ctx.get_topics_by_confidence(min_confidence)
    
    return {
        "schema_version": "4.0",
        "meta": {
            **ctx.meta,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "confidence_threshold": min_confidence
        },
        "categories": {
            cat: [
                {
                    "topic": t.topic,
                    "brief": t.brief,
                    "full_description": t.full_description,
                    "confidence": t.confidence,
                    "mention_count": t.mention_count,
                    "detail_level": t.get_detail_level(),
                    "metrics": t.metrics,
                    "relationships": t.relationships,
                    "timeline": t.timeline
                }
                for t in topics_list
            ]
            for cat, topics_list in topics.items()
        }
    }


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Import context to various formats (v4)")
    parser.add_argument("input_file", help="Path to context JSON file")
    parser.add_argument("--output", "-o", help="Output directory", default=".")
    parser.add_argument(
        "--format", "-f",
        choices=["all", "claude-preferences", "claude-memories", "system-prompt", "notion", "notion-db", "gdocs", "summary", "full"],
        default="all",
        help="Output format(s)"
    )
    parser.add_argument(
        "--confidence", "-c",
        choices=["high", "medium", "low", "all"],
        default="medium",
        help="Minimum confidence level"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    
    args = parser.parse_args()
    input_path = Path(args.input_file)
    output_dir = Path(args.output)
    
    if not input_path.exists():
        print(f"❌ File not found: {input_path}")
        return 1
    
    print(f"📂 Loading: {input_path}")
    ctx = NormalizedContext.load(input_path)
    
    min_conf = CONFIDENCE_THRESHOLDS[args.confidence]
    stats = ctx.stats(min_conf)
    
    print(f"📊 Loaded {stats['total']} topics across {len(stats['by_category'])} categories")
    print(f"   By confidence: {stats['by_confidence']['high']} high, {stats['by_confidence']['medium']} medium, {stats['by_confidence']['low']} low")
    print(f"✅ Exporting {stats['total']} items (confidence >= {min_conf})")
    
    formats_to_export = []
    if args.format == "all":
        formats_to_export = ["claude-preferences", "claude-memories", "system-prompt", "notion", "notion-db", "gdocs", "summary", "full"]
    else:
        formats_to_export = [args.format]
    
    if args.dry_run:
        print("\n" + "=" * 60)
        print("🔍 DRY RUN PREVIEW")
        print("=" * 60)
        
        if "claude-preferences" in formats_to_export:
            print("\n--- Claude Preferences ---")
            print(export_claude_preferences(ctx, min_conf))
        
        if "claude-memories" in formats_to_export:
            print("\n--- Claude Memories (first 10) ---")
            memories = export_claude_memories(ctx, min_conf)
            for i, m in enumerate(memories[:10], 1):
                print(f"  {i}. {m['text']}")
            if len(memories) > 10:
                print(f"  ... and {len(memories) - 10} more")
        
        if "summary" in formats_to_export:
            print("\n--- Summary ---")
            summary = export_summary(ctx, min_conf)
            # Show first 50 lines
            for line in summary.split('\n')[:50]:
                print(line)
        
        return 0
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    outputs = []
    
    if "claude-preferences" in formats_to_export:
        path = output_dir / "claude_preferences.txt"
        path.write_text(export_claude_preferences(ctx, min_conf))
        outputs.append(("Claude Preferences", path))
    
    if "claude-memories" in formats_to_export:
        path = output_dir / "claude_memories.json"
        memories = export_claude_memories(ctx, min_conf)
        path.write_text(json.dumps(memories, indent=2))
        outputs.append((f"Claude Memories ({len(memories)} items)", path))
    
    if "system-prompt" in formats_to_export:
        path = output_dir / "system_prompt.txt"
        path.write_text(export_system_prompt(ctx, min_conf))
        outputs.append(("System Prompt", path))
    
    if "notion" in formats_to_export:
        path = output_dir / "notion_page.md"
        path.write_text(export_notion(ctx, min_conf))
        outputs.append(("Notion Page (Markdown)", path))
    
    if "notion-db" in formats_to_export:
        path = output_dir / "notion_database.json"
        rows = export_notion_database_json(ctx, min_conf)
        path.write_text(json.dumps(rows, indent=2))
        outputs.append((f"Notion Database ({len(rows)} rows)", path))
    
    if "gdocs" in formats_to_export:
        path = output_dir / "google_docs.html"
        path.write_text(export_google_docs(ctx, min_conf))
        outputs.append(("Google Docs (HTML)", path))
    
    if "summary" in formats_to_export:
        path = output_dir / "summary.md"
        path.write_text(export_summary(ctx, min_conf))
        outputs.append(("Summary", path))
    
    if "full" in formats_to_export:
        path = output_dir / "full_export.json"
        path.write_text(json.dumps(export_full_json(ctx, min_conf), indent=2))
        outputs.append(("Full JSON", path))
    
    print(f"\n💾 Exported {len(outputs)} files to {output_dir}/:")
    for name, path in outputs:
        print(f"   ✓ {name}: {path.name}")
    
    return 0


if __name__ == "__main__":
    exit(main())
