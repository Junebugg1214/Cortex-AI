#!/usr/bin/env python3
"""
Cortex Autoresearch — Synthetic Corpus Generator
Generates labeled conversation exports with deterministic ground truth.
Run: python generate_corpus.py
Output: corpus/ directory with test cases + manifest.json
"""

import json
import random
from pathlib import Path
from datetime import datetime, timedelta

CORPUS_DIR = Path("corpus")
CORPUS_DIR.mkdir(exist_ok=True)

# Seed for reproducibility — do not change once corpus is generated
random.seed(42)


# ─── Conversation Templates ────────────────────────────────────────────────────

CONVERSATIONS = [

    # ── Test 01: Clear technical preferences, single platform ─────────────────
    {
        "name": "test_01_technical_preferences",
        "description": "Explicit technical stack preferences stated across multiple turns",
        "has_seeded_contradictions": False,
        "platform": "chatgpt",
        "messages": [
            {"role": "user",  "content": "I work primarily in Python and TypeScript. Can you help me build a CLI tool?"},
            {"role": "assistant", "content": "Of course. What should the CLI do?"},
            {"role": "user",  "content": "It needs to parse JSON exports and build a graph. I prefer simple code over clever abstractions."},
            {"role": "assistant", "content": "Understood. I'll keep the implementation straightforward."},
            {"role": "user",  "content": "Also, I use pytest for testing and ruff for linting. Don't suggest other tools."},
            {"role": "assistant", "content": "Noted — pytest and ruff only."},
            {"role": "user",  "content": "One more thing: I deploy on Linux, always. Never Windows."},
        ],
        "ground_truth": {
            "technical_expertise": ["Python", "TypeScript", "pytest", "ruff"],
            "communication_preferences": ["simple code over clever abstractions"],
            "environment": ["Linux"],
            "active_projects": ["CLI tool for JSON export parsing and graph building"],
            "preferences": ["prefers simple code", "avoids Windows"],
        }
    },

    # ── Test 02: Communication style preferences ───────────────────────────────
    {
        "name": "test_02_communication_style",
        "description": "Communication and response style stated explicitly and implicitly",
        "has_seeded_contradictions": False,
        "platform": "chatgpt",
        "messages": [
            {"role": "user",  "content": "Please be concise. I dislike long explanations."},
            {"role": "assistant", "content": "Got it."},
            {"role": "user",  "content": "Also skip the disclaimers. I'm a professional, I know the caveats."},
            {"role": "assistant", "content": "Understood."},
            {"role": "user",  "content": "And don't use bullet points for everything. Write in prose when it makes sense."},
            {"role": "assistant", "content": "Will do."},
            {"role": "user",  "content": "No filler phrases like 'great question' or 'certainly'. Just answer."},
        ],
        "ground_truth": {
            "communication_preferences": [
                "concise responses",
                "no disclaimers",
                "prose over bullet points when appropriate",
                "no filler phrases",
            ],
            "preferences": [
                "dislikes long explanations",
                "prefers direct answers",
            ],
        }
    },

    # ── Test 03: Active projects and domain expertise ─────────────────────────
    {
        "name": "test_03_projects_and_domain",
        "description": "Multiple active projects with domain context",
        "has_seeded_contradictions": False,
        "platform": "claude",
        "messages": [
            {"role": "user",  "content": "I'm building an open source memory portability tool called Cortex. It's a Python CLI."},
            {"role": "assistant", "content": "What's the core use case?"},
            {"role": "user",  "content": "Users export their ChatGPT history and Cortex turns it into a local knowledge graph they can query."},
            {"role": "assistant", "content": "Interesting. What's the target audience?"},
            {"role": "user",  "content": "Developers who want to own their AI context. Privacy-focused users who don't want it on a server."},
            {"role": "assistant", "content": "That's a strong positioning angle."},
            {"role": "user",  "content": "I also run an oncology AI startup on the side. Very different space — regulatory, clinical stuff."},
            {"role": "assistant", "content": "Two very different domains. How do you split your time?"},
            {"role": "user",  "content": "Cortex is nights and weekends. The oncology work is my main focus right now."},
        ],
        "ground_truth": {
            "active_projects": [
                "Cortex — open source memory portability CLI",
                "oncology AI startup",
            ],
            "technical_expertise": ["Python", "knowledge graphs", "CLI tools"],
            "domain_knowledge": ["AI memory portability", "oncology AI", "regulatory clinical AI"],
            "values": ["privacy", "local-first tools", "user data ownership"],
        }
    },

    # ── Test 04: Seeded contradictions ────────────────────────────────────────
    {
        "name": "test_04_contradictions",
        "description": "Conversation with intentional contradictions about preferences",
        "has_seeded_contradictions": True,
        "platform": "chatgpt",
        "messages": [
            {"role": "user",  "content": "I always use tabs for indentation. It's non-negotiable."},
            {"role": "assistant", "content": "Noted, tabs it is."},
            {"role": "user",  "content": "Help me set up a Python project."},
            {"role": "assistant", "content": "Here's a basic pyproject.toml using spaces as per PEP 8..."},
            {"role": "user",  "content": "Actually, for Python I use spaces. The PEP 8 standard makes sense there."},
            {"role": "assistant", "content": "Understood, spaces for Python then."},
            {"role": "user",  "content": "For JavaScript though, tabs. Always."},
            {"role": "assistant", "content": "Got it — tabs for JS, spaces for Python."},
            {"role": "user",  "content": "Wait, I changed my mind. Spaces everywhere. Consistency matters more."},
        ],
        "ground_truth": {
            "technical_expertise": ["Python", "JavaScript"],
            "preferences": ["spaces for indentation (final preference, overrides earlier tab preference)"],
            "contradictions": [
                "Initially stated tabs always, later switched to spaces for Python, then spaces everywhere"
            ],
        }
    },

    # ── Test 05: Implicit preferences (not stated directly) ───────────────────
    {
        "name": "test_05_implicit_preferences",
        "description": "Preferences inferable from behavior, not stated explicitly",
        "has_seeded_contradictions": False,
        "platform": "chatgpt",
        "messages": [
            {"role": "user",  "content": "Here's my code. What's wrong with it?\n```python\ndef process(data):\n    for item in data:\n        result = transform(item)\n        if result: yield result\n```"},
            {"role": "assistant", "content": "The generator looks correct. One suggestion: add a type hint."},
            {"role": "user",  "content": "I don't use type hints. They clutter my code."},
            {"role": "assistant", "content": "Fair enough."},
            {"role": "user",  "content": "Also don't suggest docstrings. The code should speak for itself."},
            {"role": "assistant", "content": "Understood."},
            {"role": "user",  "content": "Can you make this faster? I process millions of records."},
            {"role": "assistant", "content": "For that volume, consider numpy vectorization or multiprocessing."},
            {"role": "user",  "content": "No external libraries. I keep dependencies minimal."},
        ],
        "ground_truth": {
            "technical_expertise": ["Python", "generators", "performance optimization"],
            "preferences": [
                "no type hints",
                "no docstrings",
                "minimal external dependencies",
                "self-documenting code style",
            ],
            "communication_preferences": ["direct feedback without suggestions they haven't asked for"],
        }
    },

    # ── Test 06: Near-duplicate entity challenge ──────────────────────────────
    {
        "name": "test_06_near_duplicates",
        "description": "Same entities expressed in multiple surface forms — tests deduplication",
        "has_seeded_contradictions": False,
        "platform": "claude",
        "messages": [
            {"role": "user",  "content": "I use python3 for all my scripts."},
            {"role": "assistant", "content": "Good choice. Any specific version?"},
            {"role": "user",  "content": "Python 3.11 mostly. Sometimes 3.10 for compatibility."},
            {"role": "assistant", "content": "Understood."},
            {"role": "user",  "content": "My main language is Python. I've used it for 8 years."},
            {"role": "assistant", "content": "You're experienced then."},
            {"role": "user",  "content": "Yeah, Python/Django was my first serious stack. Still love the language."},
            {"role": "assistant", "content": "Django experience is useful."},
            {"role": "user",  "content": "I also know Django REST Framework and have used py for data work too."},
        ],
        "ground_truth": {
            "technical_expertise": ["Python", "Django", "Django REST Framework"],
            "deduplication_challenge": [
                "python3", "Python", "Python 3.11", "Python 3.10", "py",
                "Python/Django", "Django", "Django REST Framework"
            ],
            "notes": "Should deduplicate to: Python (primary), Django, Django REST Framework — not 5+ separate nodes"
        }
    },

    # ── Test 07: Professional background and identity ─────────────────────────
    {
        "name": "test_07_professional_identity",
        "description": "Professional role, background, and organizational context",
        "has_seeded_contradictions": False,
        "platform": "chatgpt",
        "messages": [
            {"role": "user",  "content": "I'm a physician — internal medicine, hospitalist. 12 years at a community hospital."},
            {"role": "assistant", "content": "That's a demanding specialty. What brings you to AI tooling?"},
            {"role": "user",  "content": "I co-founded an AI startup focused on oncology adverse event grading."},
            {"role": "assistant", "content": "Interesting intersection of clinical medicine and AI."},
            {"role": "user",  "content": "It is. I'm the CMO — or was. Left in March 2026 due to a co-founder conflict."},
            {"role": "assistant", "content": "Sorry to hear that. What are you focused on now?"},
            {"role": "user",  "content": "Open source AI tooling and figuring out what's next. Cortex is part of that."},
        ],
        "ground_truth": {
            "professional_background": [
                "Internal medicine physician",
                "Hospitalist with 12 years experience",
                "Co-founder and former CMO of oncology AI startup",
            ],
            "domain_knowledge": ["clinical medicine", "oncology", "adverse event grading", "healthcare AI"],
            "active_projects": ["Cortex open source AI tooling"],
            "career_context": ["departed AI startup March 2026", "exploring next steps"],
        }
    },

    # ── Test 08: Values and working style ─────────────────────────────────────
    {
        "name": "test_08_values_working_style",
        "description": "Values and working style expressed through decisions and opinions",
        "has_seeded_contradictions": False,
        "platform": "claude",
        "messages": [
            {"role": "user",  "content": "I care a lot about auditability in AI systems. Black box outputs worry me."},
            {"role": "assistant", "content": "That's a reasonable concern, especially in regulated domains."},
            {"role": "user",  "content": "Clinician-in-the-loop is non-negotiable for anything clinical. The AI assists, doesn't decide."},
            {"role": "assistant", "content": "A governance-first approach."},
            {"role": "user",  "content": "Exactly. I'd rather ship slower and ship right than move fast and cause harm."},
            {"role": "assistant", "content": "That's a deliberate tradeoff."},
            {"role": "user",  "content": "I also document everything. If it's not written down it didn't happen."},
            {"role": "assistant", "content": "Good habit for regulated environments."},
            {"role": "user",  "content": "And for open source — MIT license always. No copyleft drama."},
        ],
        "ground_truth": {
            "values": [
                "auditability in AI systems",
                "clinician-in-the-loop for clinical AI",
                "safety over speed",
                "documentation discipline",
                "open source MIT licensing",
            ],
            "preferences": [
                "prefers MIT license over copyleft",
                "governance-first approach to AI",
            ],
        }
    },

    # ── Test 09: Mixed signal conversation — filler vs. real preference ────────
    {
        "name": "test_09_filler_vs_signal",
        "description": "Conversational filler mixed with real preferences — tests false positive rate",
        "has_seeded_contradictions": False,
        "platform": "chatgpt",
        "messages": [
            {"role": "user",  "content": "I feel like I should probably try Rust at some point."},
            {"role": "assistant", "content": "It's worth exploring if you work on systems-level code."},
            {"role": "user",  "content": "Maybe. I've heard it's hard. Anyway, my real stack is Python."},
            {"role": "assistant", "content": "Python is well-suited for what you're describing."},
            {"role": "user",  "content": "I guess Go is interesting too. Not sure if I'd use it though."},
            {"role": "assistant", "content": "Go is strong for CLI tools and concurrent workloads."},
            {"role": "user",  "content": "True. OK let's focus. I'm building this in Python, that's decided."},
            {"role": "assistant", "content": "Python it is."},
        ],
        "ground_truth": {
            "technical_expertise": ["Python"],
            "filler_not_preferences": ["Rust (mentioned speculatively)", "Go (mentioned speculatively)"],
            "notes": "Rust and Go should NOT be extracted as technical_expertise — they are speculative mentions, not stated expertise or preference. Python is the only confirmed choice.",
        }
    },

    # ── Test 10: Long conversation with drift ─────────────────────────────────
    {
        "name": "test_10_preference_drift",
        "description": "Preferences that evolve over a long conversation — tests recency weighting",
        "has_seeded_contradictions": True,
        "platform": "chatgpt",
        "messages": [
            {"role": "user",  "content": "I want verbose, detailed explanations. I'm learning this topic."},
            {"role": "assistant", "content": "I'll make sure to cover each concept thoroughly."},
            {"role": "user",  "content": "Great. What is a knowledge graph?"},
            {"role": "assistant", "content": "[Long detailed explanation of knowledge graphs with examples...]"},
            {"role": "user",  "content": "OK I get it now. You can be a bit more concise going forward."},
            {"role": "assistant", "content": "Sure, I'll keep it tighter."},
            {"role": "user",  "content": "Actually, just be very concise. I'm past the learning curve now."},
            {"role": "assistant", "content": "Understood."},
            {"role": "user",  "content": "Treat me like an expert from here on. Skip the basics."},
        ],
        "ground_truth": {
            "communication_preferences": [
                "concise responses (evolved preference — started verbose, ended concise)",
                "expert-level explanations (final stated preference)",
            ],
            "contradictions": [
                "Initially requested verbose detail, progressively shifted to requesting conciseness"
            ],
            "notes": "Recency should dominate — final preference is concise and expert-level, not verbose"
        }
    },
]


# ─── Corpus Writer ─────────────────────────────────────────────────────────────

def write_corpus():
    manifest_entries = []
    base_time = datetime(2025, 10, 1, 9, 0, 0)

    for i, conv in enumerate(CONVERSATIONS):
        # Build platform-specific export format
        if conv["platform"] == "chatgpt":
            export = build_chatgpt_format(conv, base_time + timedelta(days=i * 7))
        else:
            export = build_claude_format(conv, base_time + timedelta(days=i * 7))

        # Write the export file
        input_filename = f"{conv['name']}.json"
        input_path = CORPUS_DIR / input_filename
        input_path.write_text(json.dumps(export, indent=2))

        # Write the ground truth file
        gt_filename = f"{conv['name']}_ground_truth.json"
        gt_path = CORPUS_DIR / gt_filename
        gt_path.write_text(json.dumps(conv["ground_truth"], indent=2))

        # Add to manifest
        manifest_entries.append({
            "name": conv["name"],
            "description": conv["description"],
            "input_file": input_filename,
            "ground_truth_file": gt_filename,
            "has_seeded_contradictions": conv["has_seeded_contradictions"],
            "platform": conv["platform"],
            "weights": {
                "recall": 0.50,
                "dedup": 0.25,
                "contradiction_detection": 0.25,
            }
        })

        print(f"  Written: {input_filename}")

    manifest = {
        "version": "1.0.0",
        "generated_at": datetime.utcnow().isoformat(),
        "description": "Cortex autoresearch labeled evaluation corpus",
        "total_tests": len(manifest_entries),
        "scoring": {
            "metric": "extraction_score",
            "range": "0.0 to 1.0",
            "direction": "higher is better",
            "target": 0.92,
        },
        "tests": manifest_entries,
    }

    manifest_path = CORPUS_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\n  Manifest: {manifest_path}")
    print(f"  Total test cases: {len(manifest_entries)}")


def build_chatgpt_format(conv: dict, timestamp: datetime) -> dict:
    """Mimics ChatGPT conversation export structure."""
    mapping = {}
    for i, msg in enumerate(conv["messages"]):
        node_id = f"msg_{i:04d}"
        mapping[node_id] = {
            "id": node_id,
            "message": {
                "id": node_id,
                "author": {"role": msg["role"]},
                "content": {"content_type": "text", "parts": [msg["content"]]},
                "create_time": (timestamp + timedelta(minutes=i * 2)).timestamp(),
            },
            "parent": f"msg_{i-1:04d}" if i > 0 else None,
            "children": [f"msg_{i+1:04d}"] if i < len(conv["messages"]) - 1 else [],
        }

    return {
        "title": conv["description"],
        "create_time": timestamp.timestamp(),
        "update_time": (timestamp + timedelta(hours=1)).timestamp(),
        "mapping": mapping,
        "conversation_id": f"conv_{conv['name']}",
    }


def build_claude_format(conv: dict, timestamp: datetime) -> dict:
    """Mimics Claude conversation export structure."""
    return {
        "uuid": f"uuid_{conv['name']}",
        "name": conv["description"],
        "created_at": timestamp.isoformat(),
        "updated_at": (timestamp + timedelta(hours=1)).isoformat(),
        "chat_messages": [
            {
                "uuid": f"msg_{i}_{conv['name']}",
                "sender": msg["role"],
                "text": msg["content"],
                "created_at": (timestamp + timedelta(minutes=i * 2)).isoformat(),
            }
            for i, msg in enumerate(conv["messages"])
        ],
    }


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Cortex Autoresearch — Generating labeled corpus...\n")
    write_corpus()
    print("\nDone. Run `python eval.py` to establish your baseline score.")
