#!/usr/bin/env python3
"""
Tests for the 4 medium-priority features:
1. Typed Relationships
2. Conflict Detection
3. Incremental Merge
4. Bidirectional Sync (Claude Memory Import)
"""

import json
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "chatbot-memory-extractor" / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "chatbot-memory-importer" / "scripts"))

from extract_memory import (
    AggressiveExtractor, ExtractionContext, ExtractedTopic,
    are_similar, normalize_text, merge_contexts, parse_timestamp,
    RELATIONSHIP_TYPE_PATTERNS
)
from import_memory import NormalizedContext, TopicDetail


class TestTypedRelationships:
    """Tests for Feature 1: Typed Relationships"""

    def test_relationship_type_patterns_exist(self):
        """Verify all expected relationship types have patterns"""
        expected_types = {"partner", "mentor", "advisor", "investor", "client", "competitor"}
        assert set(RELATIONSHIP_TYPE_PATTERNS.keys()) == expected_types

    def test_partner_extraction(self):
        """Test partner relationship detection"""
        extractor = AggressiveExtractor()
        extractor.extract_from_text("We partner with Mayo Clinic on research.")
        extractor.post_process()

        relationships = extractor.context.topics.get("relationships", {})
        partner_found = any(
            t.relationship_type == "partner"
            for t in relationships.values()
        )
        assert partner_found, "Should detect partner relationship"

    def test_mentor_extraction(self):
        """Test mentor relationship detection"""
        extractor = AggressiveExtractor()
        extractor.extract_from_text("Dr. Smith is my mentor.")
        extractor.post_process()

        relationships = extractor.context.topics.get("relationships", {})
        mentor_found = any(
            t.relationship_type == "mentor"
            for t in relationships.values()
        )
        assert mentor_found, "Should detect mentor relationship"

    def test_client_extraction(self):
        """Test client relationship detection"""
        extractor = AggressiveExtractor()
        extractor.extract_from_text("Our clients include Microsoft and Google.")
        extractor.post_process()

        relationships = extractor.context.topics.get("relationships", {})
        client_found = any(
            t.relationship_type == "client"
            for t in relationships.values()
        )
        assert client_found, "Should detect client relationship"

    def test_investor_extraction(self):
        """Test investor relationship detection"""
        extractor = AggressiveExtractor()
        extractor.extract_from_text("Sequoia invested in our company.")
        extractor.post_process()

        relationships = extractor.context.topics.get("relationships", {})
        investor_found = any(
            t.relationship_type == "investor"
            for t in relationships.values()
        )
        assert investor_found, "Should detect investor relationship"

    def test_relationship_type_in_export(self):
        """Test that relationship_type appears in exported JSON"""
        extractor = AggressiveExtractor()
        extractor.extract_from_text("We collaborate with Acme Corp on projects.")
        extractor.post_process()

        result = extractor.context.export()
        relationships = result.get("categories", {}).get("relationships", [])

        has_type_field = any(
            "relationship_type" in r
            for r in relationships
        )
        assert has_type_field, "Export should include relationship_type field"


class TestConflictDetection:
    """Tests for Feature 2: Conflict Detection"""

    def test_conflict_detection_finds_match(self):
        """Test that conflicts are detected between positive and negation categories"""
        ctx = ExtractionContext()

        # Add to values
        ctx.topics["values"]["python"] = ExtractedTopic(
            topic="Python", category="values", brief="Likes Python",
            confidence=0.8, last_seen=datetime(2025, 1, 1, tzinfo=timezone.utc)
        )

        # Add conflicting negation
        ctx.topics["negations"]["python"] = ExtractedTopic(
            topic="Python", category="negations", brief="Avoids Python",
            confidence=0.85, last_seen=datetime(2025, 6, 1, tzinfo=timezone.utc)
        )

        conflicts = ctx.detect_conflicts()
        assert len(conflicts) == 1, "Should detect 1 conflict"
        assert conflicts[0]["type"] == "negation_conflict"
        assert conflicts[0]["positive_topic"] == "Python"
        assert conflicts[0]["negative_topic"] == "Python"

    def test_conflict_resolution_prefers_newer(self):
        """Test that resolution prefers more recent statement"""
        ctx = ExtractionContext()

        # Older positive
        ctx.topics["technical_expertise"]["java"] = ExtractedTopic(
            topic="Java", category="technical_expertise", confidence=0.8,
            last_seen=datetime(2024, 1, 1, tzinfo=timezone.utc)
        )

        # Newer negation
        ctx.topics["negations"]["java"] = ExtractedTopic(
            topic="Java", category="negations", confidence=0.85,
            last_seen=datetime(2025, 6, 1, tzinfo=timezone.utc)
        )

        conflicts = ctx.detect_conflicts()
        assert conflicts[0]["resolution"] == "prefer_negation"

    def test_no_conflict_when_no_negations(self):
        """Test no conflicts when negations category is empty"""
        ctx = ExtractionContext()
        ctx.topics["values"]["python"] = ExtractedTopic(
            topic="Python", category="values", confidence=0.8
        )

        conflicts = ctx.detect_conflicts()
        assert len(conflicts) == 0

    def test_conflicts_in_export(self):
        """Test that conflicts appear in exported JSON"""
        ctx = ExtractionContext()
        ctx.topics["values"]["test"] = ExtractedTopic(
            topic="Test", category="values", confidence=0.8
        )
        ctx.topics["negations"]["test"] = ExtractedTopic(
            topic="Test", category="negations", confidence=0.85
        )
        ctx.conflicts = ctx.detect_conflicts()

        result = ctx.export()
        assert "conflicts" in result
        assert len(result["conflicts"]) == 1


class TestIncrementalMerge:
    """Tests for Feature 3: Incremental Merge"""

    def test_merge_preserves_existing_topics(self):
        """Test that merge preserves topics from existing context"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "schema_version": "4.0",
                "categories": {
                    "technical_expertise": [
                        {"topic": "Python", "confidence": 0.9, "mention_count": 10}
                    ]
                }
            }, f)
            existing_path = Path(f.name)

        try:
            extractor = AggressiveExtractor()
            extractor.extract_from_text("I use JavaScript and React.")

            merged = merge_contexts(existing_path, extractor)
            merged.post_process()

            tech = merged.context.topics.get("technical_expertise", {})
            topics = [t.topic.lower() for t in tech.values()]

            assert "python" in topics, "Should preserve Python from existing"
            assert "javascript" in topics or "react" in topics, "Should include new topics"
        finally:
            existing_path.unlink()

    def test_merge_deduplicates(self):
        """Test that merge deduplicates similar topics"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "schema_version": "4.0",
                "categories": {
                    "technical_expertise": [
                        {"topic": "Python", "confidence": 0.7, "mention_count": 3}
                    ]
                }
            }, f)
            existing_path = Path(f.name)

        try:
            extractor = AggressiveExtractor()
            extractor.extract_from_text("I use Python for data science.")

            merged = merge_contexts(existing_path, extractor)
            merged.post_process()

            tech = merged.context.topics.get("technical_expertise", {})
            python_topics = [t for t in tech.values() if "python" in t.topic.lower()]

            # Should be merged into one
            assert len(python_topics) <= 1, "Python should be deduplicated"
        finally:
            existing_path.unlink()

    def test_merge_preserves_relationship_type(self):
        """Test that merge preserves relationship_type from existing"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                "schema_version": "4.0",
                "categories": {
                    "relationships": [
                        {"topic": "Acme Corp", "confidence": 0.9, "relationship_type": "partner"}
                    ]
                }
            }, f)
            existing_path = Path(f.name)

        try:
            extractor = AggressiveExtractor()
            merged = merge_contexts(existing_path, extractor)
            merged.post_process()

            rels = merged.context.topics.get("relationships", {})
            acme = next((t for t in rels.values() if "acme" in t.topic.lower()), None)

            assert acme is not None, "Should preserve Acme Corp"
            assert acme.relationship_type == "partner", "Should preserve relationship_type"
        finally:
            existing_path.unlink()


class TestBidirectionalSync:
    """Tests for Feature 4: Bidirectional Sync (Claude Memory Import)"""

    def test_detect_claude_memory_format(self):
        """Test that Claude memory format is detected correctly"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump([
                {"text": "User is John Doe", "confidence": 0.9, "category": "identity"}
            ], f)
            path = Path(f.name)

        try:
            ctx = NormalizedContext.load(path)
            assert ctx.meta.get("source") == "claude_memories"
        finally:
            path.unlink()

    def test_parse_identity_memory(self):
        """Test parsing identity from Claude memory format"""
        data = [{"text": "User is John Doe", "confidence": 0.9, "category": "identity"}]
        ctx = NormalizedContext.from_claude_memories(data)

        assert "identity" in ctx.categories
        assert len(ctx.categories["identity"]) == 1
        assert ctx.categories["identity"][0].topic == "John Doe"

    def test_parse_technical_memory(self):
        """Test parsing technical expertise from Claude memory"""
        data = [{"text": "User tech: Python, JavaScript", "confidence": 0.8, "category": "technical_expertise"}]
        ctx = NormalizedContext.from_claude_memories(data)

        assert "technical_expertise" in ctx.categories
        assert ctx.categories["technical_expertise"][0].topic == "Python, JavaScript"

    def test_parse_negation_memory(self):
        """Test parsing negations from Claude memory"""
        data = [{"text": "User avoids: Java", "confidence": 0.75, "category": "negations"}]
        ctx = NormalizedContext.from_claude_memories(data)

        assert "negations" in ctx.categories
        assert ctx.categories["negations"][0].topic == "Java"

    def test_fallback_to_mentions(self):
        """Test that unrecognized format falls back to mentions"""
        data = [{"text": "Some random text that doesn't match patterns", "confidence": 0.5}]
        ctx = NormalizedContext.from_claude_memories(data)

        assert "mentions" in ctx.categories
        assert len(ctx.categories["mentions"]) == 1

    def test_topic_detail_has_relationship_type(self):
        """Test that TopicDetail dataclass has relationship_type field"""
        topic = TopicDetail(
            topic="Acme Corp",
            category="relationships",
            relationship_type="partner"
        )
        assert topic.relationship_type == "partner"

    def test_from_dict_preserves_relationship_type(self):
        """Test that from_dict preserves relationship_type"""
        data = {
            "topic": "Acme Corp",
            "confidence": 0.9,
            "relationship_type": "investor"
        }
        topic = TopicDetail.from_dict(data, "relationships")
        assert topic.relationship_type == "investor"


class TestIntegration:
    """Integration tests combining multiple features"""

    def test_full_extraction_pipeline(self):
        """Test complete extraction with all features"""
        extractor = AggressiveExtractor()

        # Add text with various features
        extractor.extract_from_text("My name is Alex and I'm a CTO.")
        extractor.extract_from_text("We partner with Mayo Clinic. Dr. Smith is my mentor.")
        extractor.extract_from_text("I use Python but I avoid Java.")

        extractor.post_process()
        result = extractor.context.export()

        # Check schema version
        assert result["schema_version"] == "4.0"

        # Check features listed
        assert "typed_relationships" in result["meta"]["features"]
        assert "conflict_detection" in result["meta"]["features"]

        # Check categories exist
        assert "identity" in result["categories"] or "professional_context" in result["categories"]

    def test_roundtrip_claude_memories(self):
        """Test export to Claude memories and reimport"""
        # First extract
        extractor = AggressiveExtractor()
        extractor.extract_from_text("I'm a software engineer who uses Python.")
        extractor.post_process()

        # Export to v4 format
        result = extractor.context.export()

        # Simulate Claude memory format
        memories = []
        for cat, topics in result["categories"].items():
            for t in topics:
                if cat == "identity":
                    text = f"User is {t['topic']}"
                elif cat == "technical_expertise":
                    text = f"User tech: {t['topic']}"
                else:
                    text = f"Mentioned: {t['topic']}"
                memories.append({"text": text, "confidence": t["confidence"], "category": cat})

        # Reimport
        ctx = NormalizedContext.from_claude_memories(memories)

        # Should have preserved data
        assert len(ctx.categories) > 0


def run_tests():
    """Run all tests and report results"""
    import traceback

    test_classes = [
        TestTypedRelationships,
        TestConflictDetection,
        TestIncrementalMerge,
        TestBidirectionalSync,
        TestIntegration,
    ]

    total = 0
    passed = 0
    failed = []

    for test_class in test_classes:
        print(f"\n{'='*60}")
        print(f"Running {test_class.__name__}")
        print('='*60)

        instance = test_class()
        methods = [m for m in dir(instance) if m.startswith("test_")]

        for method_name in methods:
            total += 1
            method = getattr(instance, method_name)
            try:
                method()
                print(f"  ✅ {method_name}")
                passed += 1
            except AssertionError as e:
                print(f"  ❌ {method_name}: {e}")
                failed.append((test_class.__name__, method_name, str(e)))
            except Exception as e:
                print(f"  ❌ {method_name}: {type(e).__name__}: {e}")
                failed.append((test_class.__name__, method_name, traceback.format_exc()))

    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed")
    print('='*60)

    if failed:
        print("\nFailed tests:")
        for cls, method, error in failed:
            print(f"  - {cls}.{method}")
            if len(error) > 200:
                print(f"    {error[:200]}...")
            else:
                print(f"    {error}")
        return 1

    print("\n✅ All tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(run_tests())
