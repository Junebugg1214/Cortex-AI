#!/usr/bin/env python3
"""
Chatbot Memory Importer

Converts universal portable context (from chatbot-memory-extractor) into 
platform-specific memory formats.

Usage:
    python import_memory.py <context_file.json> [options]

Supported output formats:
    - claude-preferences: Text for Claude's Settings > Profile
    - claude-memories: Structured memory edits for Claude
    - system-prompt: Generic system prompt for any LLM
    - summary: Condensed human-readable summary
    - all: Generate all formats
"""

import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
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

CATEGORY_DISPLAY_NAMES = {
    "identity": "Identity",
    "professional_context": "Professional Context",
    "personal_context": "Personal Context",
    "communication_preferences": "Communication Preferences",
    "technical_expertise": "Technical Expertise",
    "recurring_workflows": "Recurring Workflows",
    "domain_knowledge": "Domain Knowledge",
    "active_priorities": "Active Priorities"
}

# Priority order for presenting facts (most important first)
CATEGORY_PRIORITY = [
    "identity",
    "professional_context",
    "active_priorities",
    "technical_expertise",
    "domain_knowledge",
    "communication_preferences",
    "recurring_workflows",
    "personal_context"
]

# ============================================================================
# TEXT CLEANING
# ============================================================================

def clean_fact_text(text: str, category: str) -> str | None:
    """Clean and validate fact text, return None if unusable"""
    text = text.strip()
    
    # Remove leading/trailing punctuation fragments
    text = text.strip('.,;:!?')
    
    # Skip very short facts
    if len(text) < 4:
        return None
    
    # Skip fragments that are just conjunctions or prepositions
    skip_starts = ['and ', 'or ', 'but ', 'the ', 'a ', 'an ', 'to ', 'for ', 'with ', 'on ', 'in ']
    lower = text.lower()
    for skip in skip_starts:
        if lower.startswith(skip) and len(text) < 15:
            return None
    
    # Skip incomplete phrases (ending with prepositions/conjunctions)
    skip_ends = [' and', ' or', ' the', ' a', ' to', ' for', ' with', ' on', ' in', ' is', ' are']
    for skip in skip_ends:
        if lower.endswith(skip):
            return None
    
    # Skip facts that are just verbs or verb phrases without objects
    verb_only = ['focused on', 'working on', 'looking at', 'thinking about']
    if lower in verb_only:
        return None
    
    # Skip facts with question marks (likely incomplete extractions)
    if '?' in text:
        return None
    
    # Clean up "I'm" / "I am" at the start (redundant in memory context)
    if lower.startswith("i'm ") or lower.startswith("i am "):
        text = text[4:].strip() if lower.startswith("i'm ") else text[5:].strip()
    
    # Capitalize first letter
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    
    return text if len(text) >= 4 else None


def is_meaningful_fact(fact: dict, category: str) -> bool:
    """Check if a fact is meaningful enough to import"""
    text = fact.get("text", "").strip().lower()
    
    # Must have reasonable length
    if len(text) < 4:
        return False
    
    # Skip very generic terms
    generic = ['user', 'thing', 'stuff', 'something', 'anything']
    if text in generic:
        return False
    
    return True


# ============================================================================
# FILTERING
# ============================================================================

def load_context(file_path: Path) -> dict:
    """Load and validate the universal context JSON"""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Validate schema
    if data.get("schema_version") != "1.0":
        print(f"⚠️  Warning: Unknown schema version {data.get('schema_version')}")
    
    if "categories" not in data:
        raise ValueError("Invalid context file: missing 'categories' field")
    
    return data


def filter_facts(context: dict, min_confidence: float, categories: list[str] | None) -> dict:
    """Filter facts by confidence threshold and category selection"""
    filtered = {}
    
    for category, data in context["categories"].items():
        # Skip if category not in selection (when selection is specified)
        if categories and category not in categories:
            continue
        
        # Filter facts by confidence
        filtered_facts = [
            f for f in data.get("facts", [])
            if f["confidence"]["score"] >= min_confidence
        ]
        
        if filtered_facts:
            filtered[category] = filtered_facts
    
    return filtered


def deduplicate_facts(facts: dict) -> dict:
    """Remove near-duplicate facts across categories"""
    seen_normalized = set()
    deduplicated = {}
    
    for category in CATEGORY_PRIORITY:
        if category not in facts:
            continue
        
        unique_facts = []
        for fact in facts[category]:
            normalized = fact.get("normalized", fact["text"].lower().strip())
            
            # Skip if we've seen something very similar
            if normalized in seen_normalized:
                continue
            
            # Check for substring matches (avoid "Python" and "Python is my go-to")
            is_substring = any(
                normalized in seen or seen in normalized
                for seen in seen_normalized
                if len(normalized) > 5 and len(seen) > 5
            )
            
            if not is_substring:
                seen_normalized.add(normalized)
                unique_facts.append(fact)
        
        if unique_facts:
            deduplicated[category] = unique_facts
    
    return deduplicated


# ============================================================================
# OUTPUT GENERATORS
# ============================================================================

def generate_claude_preferences(facts: dict) -> str:
    """
    Generate text for Claude's Settings > Profile (user preferences).
    Format: Natural language, concise, prioritized.
    """
    lines = []
    
    # Identity section - combine into natural sentences
    if "identity" in facts:
        identity_parts = []
        for f in facts["identity"][:5]:
            cleaned = clean_fact_text(f["text"], "identity")
            if cleaned and len(cleaned) > 3:
                identity_parts.append(cleaned)
        identity_parts = list(dict.fromkeys(identity_parts))[:3]
        if identity_parts:
            lines.append(f"I am {', '.join(identity_parts)}.")
    
    # Professional context
    if "professional_context" in facts:
        prof_parts = []
        for f in facts["professional_context"][:5]:
            cleaned = clean_fact_text(f["text"], "professional_context")
            if cleaned and len(cleaned) > 3:
                prof_parts.append(cleaned)
        prof_parts = list(dict.fromkeys(prof_parts))[:3]
        if prof_parts:
            lines.append(f"My work involves {'; '.join(prof_parts)}.")
    
    # Active priorities
    if "active_priorities" in facts:
        priorities = []
        for f in facts["active_priorities"][:5]:
            cleaned = clean_fact_text(f["text"], "active_priorities")
            if cleaned and len(cleaned) > 3:
                priorities.append(cleaned)
        priorities = list(dict.fromkeys(priorities))[:3]
        if priorities:
            lines.append(f"Currently focused on: {'; '.join(priorities)}.")
    
    # Technical expertise
    if "technical_expertise" in facts:
        tech = []
        for f in facts["technical_expertise"][:8]:
            cleaned = clean_fact_text(f["text"], "technical_expertise")
            if cleaned and len(cleaned) > 1:
                tech.append(cleaned)
        tech = list(dict.fromkeys(tech))[:5]
        if tech:
            lines.append(f"Technical skills: {', '.join(tech)}.")
    
    # Domain knowledge
    if "domain_knowledge" in facts:
        domains = []
        for f in facts["domain_knowledge"][:5]:
            cleaned = clean_fact_text(f["text"], "domain_knowledge")
            if cleaned and len(cleaned) > 2:
                domains.append(cleaned)
        domains = list(dict.fromkeys(domains))[:3]
        if domains:
            lines.append(f"Domain expertise: {', '.join(domains)}.")
    
    # Communication preferences
    if "communication_preferences" in facts:
        prefs = []
        for f in facts["communication_preferences"][:3]:
            cleaned = clean_fact_text(f["text"], "communication_preferences")
            if cleaned and len(cleaned) > 2:
                prefs.append(cleaned)
        prefs = list(dict.fromkeys(prefs))[:2]
        if prefs:
            lines.append(f"Communication preference: {'; '.join(prefs)}.")
    
    # Recurring workflows
    if "recurring_workflows" in facts:
        workflows = []
        for f in facts["recurring_workflows"][:3]:
            cleaned = clean_fact_text(f["text"], "recurring_workflows")
            if cleaned and len(cleaned) > 2:
                workflows.append(cleaned)
        workflows = list(dict.fromkeys(workflows))[:2]
        if workflows:
            lines.append(f"I frequently {'; '.join(workflows)}.")
    
    # Personal context (brief)
    if "personal_context" in facts:
        personal = []
        for f in facts["personal_context"][:3]:
            cleaned = clean_fact_text(f["text"], "personal_context")
            if cleaned and len(cleaned) > 2:
                personal.append(cleaned)
        personal = list(dict.fromkeys(personal))[:2]
        if personal:
            lines.append(f"Personal: {'; '.join(personal)}.")
    
    return "\n".join(lines)


def generate_claude_memories(facts: dict) -> list[str]:
    """
    Generate structured memory edits for Claude's memory system.
    Format: List of concise statements (max 200 chars each).
    """
    memories = []
    
    # Process in priority order
    for category in CATEGORY_PRIORITY:
        if category not in facts:
            continue
        
        for fact in facts[category][:5]:  # Max 5 per category
            # Clean the text first
            cleaned = clean_fact_text(fact["text"], category)
            
            # Skip if cleaning returned None (unusable text)
            if not cleaned or len(cleaned) < 4:
                continue
            
            # Construct memory statement based on category
            if category == "identity":
                if any(kw in cleaned.lower() for kw in ["cto", "ceo", "cmo", "coo", "founder", "director", "manager", "engineer", "developer", "physician", "doctor"]):
                    memory = f"User is {cleaned}"
                elif cleaned.lower().startswith(("the ", "a ")):
                    memory = f"User is {cleaned}"
                else:
                    memory = f"User: {cleaned}"
            elif category == "professional_context":
                memory = f"User's work involves {cleaned}"
            elif category == "technical_expertise":
                memory = f"User works with {cleaned}"
            elif category == "communication_preferences":
                memory = f"User prefers {cleaned}"
            elif category == "recurring_workflows":
                memory = f"User frequently {cleaned}"
            elif category == "domain_knowledge":
                memory = f"User has expertise in {cleaned}"
            elif category == "active_priorities":
                memory = f"User is focused on {cleaned}"
            elif category == "personal_context":
                memory = f"User: {cleaned}"
            else:
                memory = f"User: {cleaned}"
            
            # Truncate to max length
            if len(memory) > 200:
                memory = memory[:197] + "..."
            
            # Avoid duplicates
            if memory not in memories:
                memories.append(memory)
    
    # Limit total memories (Claude has a limit of 30)
    return memories[:30]


def generate_system_prompt(facts: dict, include_header: bool = True) -> str:
    """
    Generate a generic system prompt section for any LLM.
    Can be prepended to existing system prompts.
    """
    lines = []
    
    if include_header:
        lines.append("<user_context>")
        lines.append("The following information about the user was extracted from their conversation history:")
        lines.append("")
    
    for category in CATEGORY_PRIORITY:
        if category not in facts:
            continue
        
        display_name = CATEGORY_DISPLAY_NAMES.get(category, category)
        category_facts = []
        for f in facts[category][:5]:
            cleaned = clean_fact_text(f["text"], category)
            if cleaned and len(cleaned) > 2:
                category_facts.append(cleaned)
        category_facts = list(dict.fromkeys(category_facts))  # Dedupe
        
        if category_facts:
            lines.append(f"**{display_name}:** {'; '.join(category_facts)}")
    
    if include_header:
        lines.append("")
        lines.append("</user_context>")
    
    return "\n".join(lines)


def generate_summary(facts: dict, context: dict) -> str:
    """Generate a condensed human-readable summary"""
    lines = [
        "# Imported User Context",
        "",
        f"*Generated: {datetime.now(timezone.utc).isoformat()}*",
        f"*Source: {context.get('source', {}).get('source_file', 'Unknown')}*",
        "",
        "---",
        ""
    ]
    
    total_facts = sum(len(f) for f in facts.values())
    lines.append(f"**Total facts imported:** {total_facts}")
    lines.append(f"**Categories:** {len(facts)}")
    lines.append("")
    
    for category in CATEGORY_PRIORITY:
        if category not in facts:
            continue
        
        display_name = CATEGORY_DISPLAY_NAMES.get(category, category)
        lines.append(f"## {display_name}")
        lines.append("")
        
        for fact in facts[category][:5]:
            confidence = fact["confidence"]["level"]
            emoji = {"high": "🟢", "medium": "🟡", "low": "🟠", "very_low": "🔴"}.get(confidence, "⚪")
            lines.append(f"- {emoji} {fact['text']}")
        
        lines.append("")
    
    return "\n".join(lines)


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Import universal context into platform-specific formats"
    )
    parser.add_argument("context_file", help="Path to context JSON from chatbot-memory-extractor")
    parser.add_argument("--output-dir", "-o", default=".", help="Output directory")
    parser.add_argument(
        "--format", "-f", 
        choices=["claude-preferences", "claude-memories", "system-prompt", "summary", "all"],
        default="all",
        help="Output format"
    )
    parser.add_argument(
        "--confidence", "-c",
        choices=["high", "medium", "low", "all"],
        default="medium",
        help="Minimum confidence threshold (default: medium)"
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        choices=list(CATEGORY_DISPLAY_NAMES.keys()),
        help="Only include specific categories"
    )
    
    args = parser.parse_args()
    
    input_path = Path(args.context_file)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load context
    print(f"📂 Loading: {input_path}")
    context = load_context(input_path)
    
    # Get confidence threshold
    min_confidence = CONFIDENCE_THRESHOLDS[args.confidence]
    print(f"🎯 Confidence threshold: {args.confidence} (>= {min_confidence})")
    
    # Filter facts
    filtered = filter_facts(context, min_confidence, args.categories)
    filtered = deduplicate_facts(filtered)
    
    total_facts = sum(len(f) for f in filtered.values())
    print(f"✅ Filtered to {total_facts} facts across {len(filtered)} categories")
    
    if total_facts == 0:
        print("⚠️  No facts match the criteria. Try lowering the confidence threshold.")
        return
    
    # Generate outputs
    base_name = input_path.stem.replace("_context", "")
    formats_to_generate = (
        ["claude-preferences", "claude-memories", "system-prompt", "summary"]
        if args.format == "all"
        else [args.format]
    )
    
    for fmt in formats_to_generate:
        if fmt == "claude-preferences":
            content = generate_claude_preferences(filtered)
            out_path = output_dir / f"{base_name}_claude_preferences.txt"
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"📄 Claude preferences: {out_path}")
            
        elif fmt == "claude-memories":
            memories = generate_claude_memories(filtered)
            out_path = output_dir / f"{base_name}_claude_memories.json"
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump({"memories": memories, "count": len(memories)}, f, indent=2)
            print(f"🧠 Claude memories: {out_path} ({len(memories)} items)")
            
        elif fmt == "system-prompt":
            content = generate_system_prompt(filtered)
            out_path = output_dir / f"{base_name}_system_prompt.txt"
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"💬 System prompt: {out_path}")
            
        elif fmt == "summary":
            content = generate_summary(filtered, context)
            out_path = output_dir / f"{base_name}_import_summary.md"
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"📝 Summary: {out_path}")
    
    # Print quick preview
    print("\n" + "="*50)
    print("📋 QUICK PREVIEW (Claude Preferences)")
    print("="*50)
    preview = generate_claude_preferences(filtered)
    print(preview[:500] + ("..." if len(preview) > 500 else ""))


if __name__ == "__main__":
    main()
