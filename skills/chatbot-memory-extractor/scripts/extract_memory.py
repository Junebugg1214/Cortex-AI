#!/usr/bin/env python3
"""
Chatbot Memory Extractor

Extracts user context from any chatbot export (JSON, text) using structure-agnostic parsing.
Outputs a universal portable context format (JSON + Markdown).

Usage:
    python extract_memory.py <input_file> [--output-dir <dir>] [--format json|markdown|both]
"""

import json
import re
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from typing import Any

# ============================================================================
# CONFIGURATION
# ============================================================================

CATEGORIES = [
    "identity",
    "professional_context", 
    "personal_context",
    "communication_preferences",
    "technical_expertise",
    "recurring_workflows",
    "domain_knowledge",
    "active_priorities"
]

# Patterns for extracting information (category -> list of regex patterns)
EXTRACTION_PATTERNS = {
    "identity": [
        r"(?:my name is|i'm|i am|call me)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        r"(?:i work as|i'm a|i am a|my role is|my title is)\s+([^,.]+)",
        r"(?:i live in|i'm based in|located in|i'm from)\s+([^,.]+)",
        r"(?:i'm the|i am the)\s+(CEO|CTO|CMO|COO|founder|co-founder|director|manager|engineer|developer|physician|doctor|nurse|analyst|consultant|designer)[^,.]*",
    ],
    "professional_context": [
        r"(?:my company|our company|i work at|i work for|my startup|our startup)\s+(?:is\s+)?([^,.]+)",
        r"(?:we're building|i'm building|working on|my project|our project)\s+([^,.]+)",
        r"(?:my team|our team)\s+([^,.]+)",
        r"(?:my industry|our industry|i work in)\s+([^,.]+)",
        r"(?:my clients|our clients|my customers|our customers)\s+([^,.]+)",
    ],
    "personal_context": [
        r"(?:my wife|my husband|my partner|my spouse)\s+([^,.]+)",
        r"(?:my kids|my children|my son|my daughter)\s+([^,.]+)",
        r"(?:my hobby|my hobbies|i enjoy|i like to|in my free time)\s+([^,.]+)",
        r"(?:i'm interested in|my interest|my interests)\s+([^,.]+)",
    ],
    "communication_preferences": [
        r"(?:i prefer|i like|please use|don't use|avoid)\s+([^,.]+(?:format|style|tone|bullets|lists|markdown|code)[^,.]*)",
        r"(?:keep it|make it|be)\s+(brief|concise|detailed|thorough|simple|direct)[^,.]*",
        r"(?:i'm a)\s+(visual learner|hands-on|technical|non-technical)[^,.]*",
    ],
    "technical_expertise": [
        r"(?:i use|i know|i'm familiar with|experience with|skilled in|proficient in)\s+([^,.]+)",
        r"(?:my stack|our stack|tech stack|using)\s+([^,.]+)",
        r"(?:programming in|coding in|develop in|write)\s+([^,.]+)",
        r"(?:python|javascript|typescript|react|node|aws|gcp|azure|docker|kubernetes|sql|mongodb|postgresql)[^,.]*",
    ],
    "recurring_workflows": [
        r"(?:i often|i usually|i always|i regularly|every week|every day|frequently)\s+([^,.]+)",
        r"(?:help me|can you|i need to)\s+(write|create|build|analyze|review|edit|format|convert|generate)[^,.]+",
    ],
    "domain_knowledge": [
        r"(?:in my field|in my industry|in my domain|specialized in|expert in|my expertise)\s+([^,.]+)",
        r"(?:clinical|medical|legal|financial|engineering|scientific|academic|research)[^,.]+(?:knowledge|expertise|background)",
    ],
    "active_priorities": [
        r"(?:right now|currently|this week|this month|my priority|my focus|working on|preparing for)\s+([^,.]+)",
        r"(?:deadline|due date|launch|release|presentation|meeting|milestone)\s+([^,.]+)",
        r"(?:i need to|i have to|i must|urgent|asap|important)\s+([^,.]+)",
    ],
}

# ============================================================================
# STRUCTURE-AGNOSTIC PARSING
# ============================================================================

def detect_and_parse_conversations(data: Any) -> list[dict]:
    """
    Detect the structure of the input and extract conversations.
    Returns a list of messages with: role, content, timestamp (if available)
    """
    messages = []
    
    if isinstance(data, dict):
        # Try common structures
        messages = (
            parse_chatgpt_format(data) or
            parse_claude_format(data) or
            parse_generic_dict(data) or
            []
        )
    elif isinstance(data, list):
        messages = parse_list_format(data)
    
    return messages


def parse_chatgpt_format(data: dict) -> list[dict] | None:
    """Parse ChatGPT export format"""
    if "conversations" not in data and "mapping" not in data:
        # Check if it's a single conversation file
        if "mapping" in data:
            return extract_chatgpt_messages(data)
        return None
    
    messages = []
    conversations = data.get("conversations", [data])
    
    for conv in conversations:
        messages.extend(extract_chatgpt_messages(conv))
    
    return messages if messages else None


def extract_chatgpt_messages(conv: dict) -> list[dict]:
    """Extract messages from a single ChatGPT conversation"""
    messages = []
    mapping = conv.get("mapping", {})
    
    for node_id, node in mapping.items():
        msg = node.get("message")
        if not msg:
            continue
        
        role = msg.get("author", {}).get("role", "")
        content = msg.get("content", {})
        
        # Handle different content structures
        if isinstance(content, dict):
            parts = content.get("parts", [])
            text = " ".join(str(p) for p in parts if p)
        elif isinstance(content, str):
            text = content
        else:
            continue
        
        if not text or role not in ("user", "assistant", "system"):
            continue
        
        timestamp = msg.get("create_time")
        
        messages.append({
            "role": role,
            "content": text,
            "timestamp": timestamp
        })
    
    return messages


def parse_claude_format(data: dict) -> list[dict] | None:
    """Parse Claude export format (if available)"""
    # Claude conversations typically have a different structure
    # This handles potential Claude export formats
    
    if "chat_messages" in data:
        messages = []
        for msg in data["chat_messages"]:
            messages.append({
                "role": msg.get("sender", "user"),
                "content": msg.get("text", ""),
                "timestamp": msg.get("created_at")
            })
        return messages if messages else None
    
    return None


def parse_generic_dict(data: dict) -> list[dict] | None:
    """Parse generic dictionary formats by looking for message-like structures"""
    messages = []
    
    # Look for common keys that might contain messages
    for key in ["messages", "conversation", "chat", "history", "turns", "dialogue"]:
        if key in data:
            result = parse_list_format(data[key])
            if result:
                return result
    
    # Recursively search for message arrays
    for value in data.values():
        if isinstance(value, list):
            result = parse_list_format(value)
            if result:
                messages.extend(result)
        elif isinstance(value, dict):
            result = parse_generic_dict(value)
            if result:
                messages.extend(result)
    
    return messages if messages else None


def parse_list_format(data: list) -> list[dict] | None:
    """Parse list of messages in various formats"""
    messages = []
    
    for item in data:
        if not isinstance(item, dict):
            continue
        
        # Try to extract role and content
        role = (
            item.get("role") or 
            item.get("author") or 
            item.get("sender") or 
            item.get("from") or
            ""
        )
        
        if isinstance(role, dict):
            role = role.get("role", "")
        
        content = (
            item.get("content") or 
            item.get("text") or 
            item.get("message") or 
            item.get("body") or
            ""
        )
        
        if isinstance(content, dict):
            content = content.get("text", "") or content.get("parts", [""])[0]
        if isinstance(content, list):
            content = " ".join(str(c) for c in content)
        
        # Normalize role names
        role = str(role).lower()
        if role in ("human", "user", "customer", "person"):
            role = "user"
        elif role in ("assistant", "ai", "bot", "claude", "chatgpt", "gpt"):
            role = "assistant"
        
        if role in ("user", "assistant") and content:
            timestamp = (
                item.get("timestamp") or 
                item.get("created_at") or 
                item.get("create_time") or
                item.get("time") or
                item.get("date")
            )
            
            messages.append({
                "role": role,
                "content": str(content),
                "timestamp": timestamp
            })
    
    return messages if messages else None


def parse_text_transcript(text: str) -> list[dict]:
    """Parse plain text conversation transcript"""
    messages = []
    
    # Common patterns for conversation turns
    patterns = [
        r"(?:^|\n)(User|Human|Me|You):\s*(.+?)(?=\n(?:User|Human|Me|You|Assistant|AI|Bot|Claude|ChatGPT):|$)",
        r"(?:^|\n)(Assistant|AI|Bot|Claude|ChatGPT):\s*(.+?)(?=\n(?:User|Human|Me|You|Assistant|AI|Bot|Claude|ChatGPT):|$)",
    ]
    
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            role = match.group(1).lower()
            content = match.group(2).strip()
            
            if role in ("user", "human", "me", "you"):
                role = "user"
            else:
                role = "assistant"
            
            messages.append({
                "role": role,
                "content": content,
                "timestamp": None
            })
    
    return messages


# ============================================================================
# INFORMATION EXTRACTION
# ============================================================================

def extract_facts(messages: list[dict]) -> dict[str, list[dict]]:
    """
    Extract facts from messages using pattern matching and heuristics.
    Returns facts organized by category with metadata.
    """
    facts = defaultdict(list)
    user_messages = [m for m in messages if m["role"] == "user"]
    
    for i, msg in enumerate(user_messages):
        content = msg["content"]
        timestamp = msg.get("timestamp")
        position = i / max(len(user_messages), 1)  # 0 = oldest, 1 = newest
        
        # Extract facts using patterns
        for category, patterns in EXTRACTION_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, content, re.IGNORECASE):
                    fact_text = match.group(1) if match.groups() else match.group(0)
                    fact_text = fact_text.strip()
                    
                    if len(fact_text) < 2 or len(fact_text) > 200:
                        continue
                    
                    facts[category].append({
                        "text": fact_text,
                        "source": content[:100] + "..." if len(content) > 100 else content,
                        "timestamp": timestamp,
                        "position": position,
                        "extraction_type": "pattern"
                    })
        
        # Extract topics and entities from user messages (frequency analysis)
        extract_topics_and_entities(content, timestamp, position, facts)
    
    return facts


def extract_topics_and_entities(content: str, timestamp: Any, position: float, facts: dict):
    """Extract topics and named entities from content"""
    
    # Technical terms and tools
    tech_patterns = [
        r"\b(Python|JavaScript|TypeScript|React|Node\.js|AWS|GCP|Azure|Docker|Kubernetes|SQL|MongoDB|PostgreSQL|Redis|GraphQL|REST|API|Git|GitHub|VS Code|Linux|macOS|Windows)\b",
        r"\b(machine learning|deep learning|neural network|NLP|computer vision|data science|AI|ML|LLM)\b",
        r"\b(Vercel|Netlify|Heroku|Firebase|Supabase|Convex|Prisma|Next\.js|Vue|Angular|Svelte)\b",
    ]
    
    for pattern in tech_patterns:
        for match in re.finditer(pattern, content, re.IGNORECASE):
            facts["technical_expertise"].append({
                "text": match.group(0),
                "timestamp": timestamp,
                "position": position,
                "extraction_type": "entity"
            })
    
    # Domain-specific terms
    domain_patterns = [
        r"\b(clinical trial|FDA|HIPAA|EHR|EMR|healthcare|medical|patient|diagnosis|treatment|oncology|cardiology|neurology)\b",
        r"\b(CTCAE|adverse event|CDI|documentation|ICD-10|CPT|revenue cycle|billing)\b",
        r"\b(investment|funding|seed|Series [A-Z]|venture|valuation|pitch deck|investor|startup|founder)\b",
        r"\b(contract|legal|compliance|regulatory|policy|governance|audit)\b",
    ]
    
    for pattern in domain_patterns:
        for match in re.finditer(pattern, content, re.IGNORECASE):
            facts["domain_knowledge"].append({
                "text": match.group(0),
                "timestamp": timestamp,
                "position": position,
                "extraction_type": "entity"
            })


# ============================================================================
# WEIGHTING AND SCORING
# ============================================================================

def calculate_weights(facts: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """
    Apply recency and frequency weighting to facts.
    More recent + more frequent = higher importance.
    """
    weighted_facts = {}
    
    for category, fact_list in facts.items():
        # Group by normalized text
        grouped = defaultdict(list)
        for fact in fact_list:
            normalized = normalize_text(fact["text"])
            grouped[normalized].append(fact)
        
        # Calculate weighted scores
        scored_facts = []
        for normalized, occurrences in grouped.items():
            # Frequency score (log scale to prevent outliers from dominating)
            frequency = len(occurrences)
            frequency_score = min(1.0, (frequency / 10) ** 0.5)
            
            # Recency score (average position, weighted toward most recent)
            positions = [f["position"] for f in occurrences]
            recency_score = max(positions)  # Use most recent occurrence
            
            # Combined score (recency weighted slightly higher)
            combined_score = (recency_score * 0.6) + (frequency_score * 0.4)
            
            # Confidence based on extraction quality and frequency
            confidence = calculate_confidence(occurrences, frequency)
            
            # Use the most recent/best occurrence as representative
            best_occurrence = max(occurrences, key=lambda x: x["position"])
            
            scored_facts.append({
                "text": best_occurrence["text"],
                "normalized": normalized,
                "frequency": frequency,
                "recency_score": round(recency_score, 3),
                "frequency_score": round(frequency_score, 3),
                "combined_score": round(combined_score, 3),
                "confidence": confidence,
                "occurrences": frequency,
                "extraction_type": best_occurrence.get("extraction_type", "unknown")
            })
        
        # Sort by combined score (highest first)
        scored_facts.sort(key=lambda x: x["combined_score"], reverse=True)
        weighted_facts[category] = scored_facts
    
    return weighted_facts


def calculate_confidence(occurrences: list[dict], frequency: int) -> dict:
    """Calculate confidence score for a fact"""
    
    # Base confidence from extraction type
    extraction_types = [o.get("extraction_type", "unknown") for o in occurrences]
    has_pattern_match = "pattern" in extraction_types
    
    # Scoring factors
    if frequency >= 5 and has_pattern_match:
        level = "high"
        score = 0.9
    elif frequency >= 3 or has_pattern_match:
        level = "medium"
        score = 0.7
    elif frequency >= 2:
        level = "low"
        score = 0.5
    else:
        level = "very_low"
        score = 0.3
    
    # Boost for explicit statements (pattern matches)
    if has_pattern_match:
        score = min(1.0, score + 0.1)
    
    return {
        "level": level,
        "score": round(score, 2),
        "factors": {
            "frequency": frequency,
            "has_explicit_statement": has_pattern_match
        }
    }


def normalize_text(text: str) -> str:
    """Normalize text for comparison"""
    return re.sub(r'\s+', ' ', text.lower().strip())


# ============================================================================
# OUTPUT GENERATION
# ============================================================================

def generate_universal_context(weighted_facts: dict, metadata: dict) -> dict:
    """Generate the universal portable context format (JSON)"""
    
    context = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": metadata,
        "categories": {},
        "summary": {}
    }
    
    for category in CATEGORIES:
        facts = weighted_facts.get(category, [])
        
        # Filter to meaningful facts (confidence > very_low or high combined score)
        meaningful = [
            f for f in facts 
            if f["confidence"]["score"] >= 0.3 or f["combined_score"] >= 0.5
        ]
        
        context["categories"][category] = {
            "facts": meaningful[:20],  # Top 20 per category
            "total_extracted": len(facts)
        }
    
    # Generate summary statistics
    context["summary"] = {
        "total_facts": sum(len(c["facts"]) for c in context["categories"].values()),
        "high_confidence_facts": sum(
            1 for cat in context["categories"].values() 
            for f in cat["facts"] 
            if f["confidence"]["level"] == "high"
        ),
        "categories_with_data": sum(
            1 for cat in context["categories"].values() 
            if cat["facts"]
        )
    }
    
    return context


def generate_markdown(context: dict) -> str:
    """Generate human-readable Markdown from the universal context"""
    
    lines = [
        "# User Context Profile",
        "",
        f"*Generated: {context['generated_at']}*",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"- **Total facts extracted:** {context['summary']['total_facts']}",
        f"- **High confidence facts:** {context['summary']['high_confidence_facts']}",
        f"- **Categories with data:** {context['summary']['categories_with_data']}/{len(CATEGORIES)}",
        "",
    ]
    
    # Category display names
    category_names = {
        "identity": "Identity",
        "professional_context": "Professional Context",
        "personal_context": "Personal Context", 
        "communication_preferences": "Communication Preferences",
        "technical_expertise": "Technical Expertise",
        "recurring_workflows": "Recurring Workflows",
        "domain_knowledge": "Domain Knowledge",
        "active_priorities": "Active Priorities"
    }
    
    for category, display_name in category_names.items():
        cat_data = context["categories"].get(category, {"facts": []})
        facts = cat_data["facts"]
        
        lines.append(f"## {display_name}")
        lines.append("")
        
        if not facts:
            lines.append("*No data extracted*")
            lines.append("")
            continue
        
        for fact in facts[:10]:  # Top 10 for readability
            confidence = fact["confidence"]["level"]
            confidence_emoji = {
                "high": "🟢",
                "medium": "🟡", 
                "low": "🟠",
                "very_low": "🔴"
            }.get(confidence, "⚪")
            
            lines.append(f"- {confidence_emoji} **{fact['text']}**")
            lines.append(f"  - Confidence: {confidence} ({fact['confidence']['score']})")
            lines.append(f"  - Mentioned {fact['occurrences']}x | Importance: {fact['combined_score']}")
        
        lines.append("")
    
    lines.extend([
        "---",
        "",
        "## Confidence Legend",
        "",
        "- 🟢 High: Multiple explicit mentions, reliable",
        "- 🟡 Medium: Clear references, likely accurate", 
        "- 🟠 Low: Inferred or few mentions",
        "- 🔴 Very Low: Single mention, use with caution",
        "",
        "---",
        "",
        "*This profile was automatically extracted. Review for accuracy before importing.*"
    ])
    
    return "\n".join(lines)


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Extract user context from chatbot exports"
    )
    parser.add_argument("input_file", help="Path to chatbot export file (JSON or text)")
    parser.add_argument("--output-dir", "-o", default=".", help="Output directory")
    parser.add_argument("--format", "-f", choices=["json", "markdown", "both"], 
                        default="both", help="Output format")
    
    args = parser.parse_args()
    
    input_path = Path(args.input_file)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Read input file
    print(f"📂 Reading: {input_path}")
    
    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Try to parse as JSON first
    try:
        data = json.loads(content)
        messages = detect_and_parse_conversations(data)
        source_type = "json"
    except json.JSONDecodeError:
        # Fall back to text parsing
        messages = parse_text_transcript(content)
        source_type = "text"
    
    if not messages:
        print("❌ Could not extract any messages from the input file.")
        print("   Supported formats: ChatGPT export, Claude export, generic JSON, text transcript")
        sys.exit(1)
    
    print(f"✅ Parsed {len(messages)} messages ({source_type} format)")
    
    user_messages = [m for m in messages if m["role"] == "user"]
    print(f"   - User messages: {len(user_messages)}")
    print(f"   - Assistant messages: {len(messages) - len(user_messages)}")
    
    # Extract facts
    print("🔍 Extracting facts...")
    facts = extract_facts(messages)
    
    # Apply weighting
    print("⚖️  Applying recency/frequency weighting...")
    weighted_facts = calculate_weights(facts)
    
    # Generate metadata
    metadata = {
        "source_file": input_path.name,
        "source_type": source_type,
        "total_messages": len(messages),
        "user_messages": len(user_messages),
        "extraction_date": datetime.now(timezone.utc).isoformat()
    }
    
    # Generate outputs
    context = generate_universal_context(weighted_facts, metadata)
    
    base_name = input_path.stem + "_context"
    
    if args.format in ("json", "both"):
        json_path = output_dir / f"{base_name}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(context, f, indent=2, ensure_ascii=False)
        print(f"📄 JSON output: {json_path}")
    
    if args.format in ("markdown", "both"):
        md_path = output_dir / f"{base_name}.md"
        markdown = generate_markdown(context)
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(markdown)
        print(f"📝 Markdown output: {md_path}")
    
    # Print summary
    print("\n" + "="*50)
    print("📊 EXTRACTION SUMMARY")
    print("="*50)
    print(f"Total facts: {context['summary']['total_facts']}")
    print(f"High confidence: {context['summary']['high_confidence_facts']}")
    print(f"Categories with data: {context['summary']['categories_with_data']}/{len(CATEGORIES)}")
    print()
    
    for category, data in context["categories"].items():
        if data["facts"]:
            top_fact = data["facts"][0]["text"][:50]
            print(f"  {category}: {len(data['facts'])} facts (top: \"{top_fact}...\")")


if __name__ == "__main__":
    main()
