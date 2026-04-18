#!/usr/bin/env python3
"""
Tests for the 4 medium-priority features:
1. Typed Relationships
2. Conflict Detection
3. Incremental Merge
4. Bidirectional Sync (Claude Memory Import)
"""

# CONTRACT TESTS: HeuristicBackend output contract.
# These tests define the required behavior of HeuristicBackend.
# They must pass unchanged for the lifetime of that backend.
# They are NOT tests of ModelBackend or EmbeddingBackend output.

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cortex.extract_memory import (
    RELATIONSHIP_TYPE_PATTERNS,
    AggressiveExtractor,
    ExtractedTopic,
    ExtractionContext,
    PIIRedactor,
    merge_contexts,
)
from cortex.import_memory import NormalizedContext, TopicDetail


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
        partner_found = any(t.relationship_type == "partner" for t in relationships.values())
        assert partner_found, "Should detect partner relationship"

    def test_mentor_extraction(self):
        """Test mentor relationship detection"""
        extractor = AggressiveExtractor()
        extractor.extract_from_text("Dr. Smith is my mentor.")
        extractor.post_process()

        relationships = extractor.context.topics.get("relationships", {})
        mentor_found = any(t.relationship_type == "mentor" for t in relationships.values())
        assert mentor_found, "Should detect mentor relationship"

    def test_client_extraction(self):
        """Test client relationship detection"""
        extractor = AggressiveExtractor()
        extractor.extract_from_text("Our clients include Microsoft and Google.")
        extractor.post_process()

        relationships = extractor.context.topics.get("relationships", {})
        client_found = any(t.relationship_type == "client" for t in relationships.values())
        assert client_found, "Should detect client relationship"

    def test_investor_extraction(self):
        """Test investor relationship detection"""
        extractor = AggressiveExtractor()
        extractor.extract_from_text("Sequoia invested in our company.")
        extractor.post_process()

        relationships = extractor.context.topics.get("relationships", {})
        investor_found = any(t.relationship_type == "investor" for t in relationships.values())
        assert investor_found, "Should detect investor relationship"

    def test_relationship_type_in_export(self):
        """Test that relationship_type appears in exported JSON"""
        extractor = AggressiveExtractor()
        extractor.extract_from_text("We collaborate with Acme Corp on projects.")
        extractor.post_process()

        result = extractor.context.export()
        relationships = result.get("categories", {}).get("relationships", [])

        has_type_field = any("relationship_type" in r for r in relationships)
        assert has_type_field, "Export should include relationship_type field"


class TestConflictDetection:
    """Tests for Feature 2: Conflict Detection"""

    def test_conflict_detection_finds_match(self):
        """Test that conflicts are detected between positive and negation categories"""
        ctx = ExtractionContext()

        # Add to values
        ctx.topics["values"]["python"] = ExtractedTopic(
            topic="Python",
            category="values",
            brief="Likes Python",
            confidence=0.8,
            last_seen=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )

        # Add conflicting negation
        ctx.topics["negations"]["python"] = ExtractedTopic(
            topic="Python",
            category="negations",
            brief="Avoids Python",
            confidence=0.85,
            last_seen=datetime(2025, 6, 1, tzinfo=timezone.utc),
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
            topic="Java",
            category="technical_expertise",
            confidence=0.8,
            last_seen=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        # Newer negation
        ctx.topics["negations"]["java"] = ExtractedTopic(
            topic="Java", category="negations", confidence=0.85, last_seen=datetime(2025, 6, 1, tzinfo=timezone.utc)
        )

        conflicts = ctx.detect_conflicts()
        assert conflicts[0]["resolution"] == "prefer_negation"

    def test_no_conflict_when_no_negations(self):
        """Test no conflicts when negations category is empty"""
        ctx = ExtractionContext()
        ctx.topics["values"]["python"] = ExtractedTopic(topic="Python", category="values", confidence=0.8)

        conflicts = ctx.detect_conflicts()
        assert len(conflicts) == 0

    def test_conflicts_in_export(self):
        """Test that conflicts appear in exported JSON"""
        ctx = ExtractionContext()
        ctx.topics["values"]["test"] = ExtractedTopic(topic="Test", category="values", confidence=0.8)
        ctx.topics["negations"]["test"] = ExtractedTopic(topic="Test", category="negations", confidence=0.85)
        ctx.conflicts = ctx.detect_conflicts()

        result = ctx.export()
        assert "conflicts" in result
        assert len(result["conflicts"]) == 1

    def test_export_includes_eval_compat_aliases(self):
        """Export should expose eval-compatible node and contradiction fields."""
        ctx = ExtractionContext()
        ctx.add_topic("technical_expertise", "Python", confidence=0.9)
        ctx.add_topic("domain_knowledge", "Python", confidence=0.8)
        ctx.add_topic("negations", "Python", confidence=0.85)
        ctx.conflicts = ctx.detect_conflicts()

        result = ctx.export()

        python_nodes = [node for node in result["nodes"] if node["label"] == "Python"]
        assert len(python_nodes) == 1
        assert python_nodes[0]["category"] == "technical_expertise"
        assert "domain_knowledge" in python_nodes[0]["tags"]
        assert result["contradictions"] == result["conflicts"]


class TestIncrementalMerge:
    """Tests for Feature 3: Incremental Merge"""

    def test_merge_preserves_existing_topics(self):
        """Test that merge preserves topics from existing context"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "schema_version": "4.0",
                    "categories": {
                        "technical_expertise": [{"topic": "Python", "confidence": 0.9, "mention_count": 10}]
                    },
                },
                f,
            )
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
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "schema_version": "4.0",
                    "categories": {"technical_expertise": [{"topic": "Python", "confidence": 0.7, "mention_count": 3}]},
                },
                f,
            )
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
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "schema_version": "4.0",
                    "categories": {
                        "relationships": [{"topic": "Acme Corp", "confidence": 0.9, "relationship_type": "partner"}]
                    },
                },
                f,
            )
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
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([{"text": "User is John Doe", "confidence": 0.9, "category": "identity"}], f)
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
        topic = TopicDetail(topic="Acme Corp", category="relationships", relationship_type="partner")
        assert topic.relationship_type == "partner"

    def test_from_dict_preserves_relationship_type(self):
        """Test that from_dict preserves relationship_type"""
        data = {"topic": "Acme Corp", "confidence": 0.9, "relationship_type": "investor"}
        topic = TopicDetail.from_dict(data, "relationships")
        assert topic.relationship_type == "investor"


class TestPIIRedaction:
    """Tests for PII Redaction feature"""

    def test_redaction_disabled_by_default(self):
        """PII should be preserved when no redactor is provided"""
        extractor = AggressiveExtractor()
        extractor.extract_from_text("Contact me at john@example.com for details.")
        extractor.post_process()
        result = extractor.context.export()
        assert "redaction_summary" not in result

    def test_email_redaction(self):
        """Emails should be replaced with [EMAIL]"""
        redactor = PIIRedactor()
        result = redactor.redact("Email me at john@example.com please.")
        assert "[EMAIL]" in result
        assert "john@example.com" not in result

    def test_phone_redaction(self):
        """Phone numbers should be replaced with [PHONE]"""
        redactor = PIIRedactor()
        result = redactor.redact("Call me at (555) 123-4567.")
        assert "[PHONE]" in result
        assert "123-4567" not in result

    def test_ssn_redaction(self):
        """SSNs should be replaced with [SSN]"""
        redactor = PIIRedactor()
        result = redactor.redact("My SSN is 123-45-6789.")
        assert "[SSN]" in result
        assert "123-45-6789" not in result

    def test_credit_card_redaction(self):
        """Credit card numbers should be replaced with [CREDIT_CARD]"""
        redactor = PIIRedactor()
        result = redactor.redact("Card number 4111111111111111 on file.")
        assert "[CREDIT_CARD]" in result
        assert "4111111111111111" not in result

    def test_api_key_redaction(self):
        """API keys should be replaced with [API_KEY]"""
        redactor = PIIRedactor()
        result = redactor.redact("Use sk-abcdefghijklmnopqrstuvwxyz0123456789 for auth.")
        assert "[API_KEY]" in result
        assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in result

    def test_ip_address_redaction(self):
        """IP addresses should be replaced with [IP_ADDRESS]"""
        redactor = PIIRedactor()
        result = redactor.redact("Server at 192.168.1.100 is down.")
        assert "[IP_ADDRESS]" in result
        assert "192.168.1.100" not in result

    def test_street_address_redaction(self):
        """Street addresses should be replaced with [STREET_ADDRESS]"""
        redactor = PIIRedactor()
        result = redactor.redact("I live at 123 Main St.")
        assert "[STREET_ADDRESS]" in result
        assert "123 Main St" not in result

    def test_names_not_redacted(self):
        """Names should NOT be redacted"""
        redactor = PIIRedactor()
        result = redactor.redact("My name is John Smith and I'm a developer.")
        assert "John Smith" in result

    def test_technical_terms_not_redacted(self):
        """Technical terms and company names should NOT be redacted"""
        redactor = PIIRedactor()
        result = redactor.redact("I use Python and React at Google.")
        assert "Python" in result
        assert "React" in result
        assert "Google" in result

    def test_summary_counts_accurate(self):
        """Redaction summary should accurately count replacements"""
        redactor = PIIRedactor()
        redactor.redact("Email john@example.com and jane@test.com. Call (555) 123-4567.")
        summary = redactor.get_summary()
        assert summary["redaction_applied"] is True
        assert summary["total_redactions"] == 3
        assert summary["by_type"]["EMAIL"] == 2
        assert summary["by_type"]["PHONE"] == 1

    def test_custom_patterns_work(self):
        """Custom patterns should extend built-in patterns"""
        custom = {"EMPLOYEE_ID": r"\bEMP-\d{6}\b"}
        redactor = PIIRedactor(custom_patterns=custom)
        result = redactor.redact("Employee EMP-123456 reported an issue.")
        assert "[EMPLOYEE_ID]" in result
        assert "EMP-123456" not in result

    def test_custom_patterns_extend_builtins(self):
        """Custom patterns should work alongside built-in patterns"""
        custom = {"INTERNAL_CODE": r"\bINT-[A-Z]{3}-\d{4}\b"}
        redactor = PIIRedactor(custom_patterns=custom)
        result = redactor.redact("Code INT-ABC-1234, email john@test.com.")
        assert "[INTERNAL_CODE]" in result
        assert "[EMAIL]" in result

    def test_redacted_text_flows_into_extraction(self):
        """PII should never enter extraction context when redactor is active"""
        redactor = PIIRedactor()
        extractor = AggressiveExtractor(redactor=redactor)
        extractor.extract_from_text("I'm a developer, email me at secret@company.com for the project details.")
        extractor.post_process()

        # Check no email address leaked into any extracted topic
        export = extractor.context.export()
        export_str = json.dumps(export)
        assert "secret@company.com" not in export_str

    def test_redaction_summary_in_export(self):
        """Redaction summary should appear in exported JSON when enabled"""
        redactor = PIIRedactor()
        extractor = AggressiveExtractor(redactor=redactor)
        extractor.extract_from_text("Contact john@example.com for more information about our project.")
        extractor.post_process()

        result = extractor.context.export()
        assert "redaction_summary" in result
        assert result["redaction_summary"]["redaction_applied"] is True
        assert result["redaction_summary"]["total_redactions"] >= 1

    def test_no_redaction_summary_when_disabled(self):
        """No redaction_summary key when redaction is not enabled"""
        extractor = AggressiveExtractor()
        extractor.extract_from_text("Contact john@example.com for details about the project.")
        extractor.post_process()

        result = extractor.context.export()
        assert "redaction_summary" not in result

    def test_multiple_pii_types_in_one_text(self):
        """Multiple PII types in a single text block should all be redacted"""
        redactor = PIIRedactor()
        text = "Email john@test.com, call (555) 123-4567, SSN 123-45-6789, server 10.0.0.1."
        result = redactor.redact(text)
        assert "[EMAIL]" in result
        assert "[PHONE]" in result
        assert "[SSN]" in result
        assert "[IP_ADDRESS]" in result
        summary = redactor.get_summary()
        assert summary["total_redactions"] == 4
        assert len(summary["by_type"]) == 4

    def test_empty_redaction_when_no_pii_found(self):
        """Summary should show zero redactions when text has no PII"""
        redactor = PIIRedactor()
        redactor.redact("I am a software engineer who uses Python.")
        summary = redactor.get_summary()
        assert summary["redaction_applied"] is True
        assert summary["total_redactions"] == 0
        assert summary["by_type"] == {}


class TestMigratePipeline:
    """Tests for the unified migrate.py pipeline"""

    def _import_migrate(self):
        """Import cortex.cli (the canonical CLI module)."""
        import cortex.cli

        return cortex.cli

    # 1
    def test_platform_formats_mapping(self):
        """All shortcuts exist and 'all' has 8 formats"""
        mod = self._import_migrate()
        expected_keys = {"claude", "notion", "gdocs", "system-prompt", "summary", "full", "all"}
        assert expected_keys == set(mod.PLATFORM_FORMATS.keys())
        assert len(mod.PLATFORM_FORMATS["all"]) == 8

    # 2
    def test_argv_routing_default_to_migrate(self):
        """A file path as first arg routes to the migrate subcommand"""
        mod = self._import_migrate()
        parser = mod.build_parser()
        # Simulate default-subcommand insertion
        argv = ["somefile.zip", "--to", "claude"]
        if argv[0] not in ("extract", "import", "migrate"):
            argv = ["migrate"] + argv
        argv, _ = mod._route_cli_v2_argv(argv)
        args = parser.parse_args(argv)
        assert args.subcommand == "__cli_v2_migrate"

    # 3
    def test_argv_routing_extract_subcommand(self):
        """'extract' is recognized as a subcommand"""
        mod = self._import_migrate()
        parser = mod.build_parser()
        argv, _ = mod._route_cli_v2_argv(["extract", "somefile.zip"])
        args = parser.parse_args(argv)
        assert args.subcommand == "__cli_v2_extract"

    # 4
    def test_argv_routing_import_subcommand(self):
        """'import' is recognized as a subcommand"""
        mod = self._import_migrate()
        parser = mod.build_parser()
        argv, _ = mod._route_cli_v2_argv(["import", "somefile.json", "--to", "claude"])
        args = parser.parse_args(argv)
        assert args.subcommand == "__cli_v2_import"

    # 5
    def test_run_extraction_routes_correctly(self):
        """_run_extraction produces valid v4 output"""
        mod = self._import_migrate()
        extractor = AggressiveExtractor()
        text = "My name is Alex and I use Python."
        result = mod._run_extraction(extractor, text, "text")
        assert "schema_version" in result
        assert "categories" in result

    # 6
    def test_full_pipeline_end_to_end(self):
        """Full pipeline: temp JSON input -> extract -> import -> output files exist"""
        mod = self._import_migrate()
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal input file
            input_file = Path(tmpdir) / "input.json"
            input_file.write_text(
                json.dumps(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": "My name is Alice and I'm a software engineer who uses Python and React.",
                            }
                        ]
                    }
                )
            )
            out_dir = Path(tmpdir) / "out"
            rc = mod.main(["migrate", str(input_file), "--to", "all", "-o", str(out_dir)])
            assert rc == 0
            assert (out_dir / "context.json").exists()
            # At least some format files should exist
            format_files = list(out_dir.glob("*"))
            assert len(format_files) >= 2, f"Expected output files, got {format_files}"

    # 7
    def test_pipeline_saves_intermediate_context(self):
        """Migrate mode saves context.json in output dir"""
        mod = self._import_migrate()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = Path(tmpdir) / "input.json"
            input_file.write_text(
                json.dumps({"messages": [{"role": "user", "content": "I work at Acme Corp as a CTO."}]})
            )
            out_dir = Path(tmpdir) / "out"
            mod.main(["migrate", str(input_file), "--to", "claude", "-o", str(out_dir)])
            ctx_path = out_dir / "context.json"
            assert ctx_path.exists(), "context.json should be saved"
            data = json.loads(ctx_path.read_text())
            assert "schema_version" in data
            assert data["schema_version"] != "4.0"
            assert "graph" in data
            assert "nodes" in data["graph"]

    def test_pipeline_v4_schema_is_explicit_and_deprecated(self, capsys):
        """Legacy v4 output still works only when requested explicitly."""
        mod = self._import_migrate()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = Path(tmpdir) / "input.json"
            input_file.write_text(
                json.dumps({"messages": [{"role": "user", "content": "I work on Cortex and use Python."}]})
            )
            out_dir = Path(tmpdir) / "out"
            rc = mod.main(["migrate", str(input_file), "--to", "claude", "-o", str(out_dir), "--schema", "v4"])
            captured = capsys.readouterr()

            assert rc == 0
            data = json.loads((out_dir / "context.json").read_text())
            assert data["schema_version"] == "4.0"
            assert "deprecated" in captured.err.lower()

    # 8
    def test_pipeline_claude_shortcut(self):
        """--to claude produces 2 format files + context.json"""
        mod = self._import_migrate()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = Path(tmpdir) / "input.json"
            input_file.write_text(
                json.dumps({"messages": [{"role": "user", "content": "I'm a developer who uses TypeScript."}]})
            )
            out_dir = Path(tmpdir) / "out"
            mod.main(["migrate", str(input_file), "--to", "claude", "-o", str(out_dir)])
            assert (out_dir / "context.json").exists()
            assert (out_dir / "claude_preferences.txt").exists()
            assert (out_dir / "claude_memories.json").exists()
            # Should NOT have notion or gdocs files
            assert not (out_dir / "notion_page.md").exists()

    # 9
    def test_pipeline_notion_shortcut(self):
        """--to notion produces 2 format files + context.json"""
        mod = self._import_migrate()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = Path(tmpdir) / "input.json"
            input_file.write_text(
                json.dumps({"messages": [{"role": "user", "content": "I'm a designer who uses Figma."}]})
            )
            out_dir = Path(tmpdir) / "out"
            mod.main(["migrate", str(input_file), "--to", "notion", "-o", str(out_dir)])
            assert (out_dir / "context.json").exists()
            assert (out_dir / "notion_page.md").exists()
            assert (out_dir / "notion_database.json").exists()
            assert not (out_dir / "claude_preferences.txt").exists()

    # 10
    def test_extract_only_mode(self):
        """Extract subcommand produces only JSON, no format files"""
        mod = self._import_migrate()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = Path(tmpdir) / "input.json"
            input_file.write_text(
                json.dumps({"messages": [{"role": "user", "content": "I use Go for backend development."}]})
            )
            out_path = Path(tmpdir) / "ctx.json"
            rc = mod.main(["extract", str(input_file), "-o", str(out_path)])
            assert rc == 0
            assert out_path.exists()
            data = json.loads(out_path.read_text())
            assert "schema_version" in data
            # No format files alongside
            siblings = (
                list(Path(tmpdir).glob("*.txt")) + list(Path(tmpdir).glob("*.md")) + list(Path(tmpdir).glob("*.html"))
            )
            assert len(siblings) == 0

    def test_extract_global_json_outputs_machine_readable_summary(self, capsys):
        mod = self._import_migrate()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = Path(tmpdir) / "input.json"
            out_path = Path(tmpdir) / "ctx.json"
            input_file.write_text(json.dumps({"messages": [{"role": "user", "content": "I use Python."}]}))

            rc = mod.main(["--json", "extract", str(input_file), "-o", str(out_path)])
            payload = json.loads(capsys.readouterr().out)

            assert rc == 0
            assert payload["status"] == "ok"
            assert payload["output_file"] == str(out_path)
            assert out_path.exists()

    # 11
    def test_import_only_mode(self):
        """Import subcommand produces format files from existing context"""
        mod = self._import_migrate()
        with tempfile.TemporaryDirectory() as tmpdir:
            # First create a context file via extraction
            input_file = Path(tmpdir) / "input.json"
            input_file.write_text(
                json.dumps({"messages": [{"role": "user", "content": "I'm a data scientist who uses Python and R."}]})
            )
            ctx_path = Path(tmpdir) / "ctx.json"
            mod.main(["extract", str(input_file), "-o", str(ctx_path)])

            # Now import
            out_dir = Path(tmpdir) / "imported"
            rc = mod.main(["import", str(ctx_path), "--to", "summary", "-o", str(out_dir)])
            assert rc == 0
            assert (out_dir / "summary.md").exists()

    # 12
    def test_missing_input_file_returns_error(self):
        """Returns 1 for nonexistent input file"""
        mod = self._import_migrate()
        rc = mod.main(["migrate", "/nonexistent/path/to/file.json", "--to", "claude"])
        assert rc == 1


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

    def test_openai_root_mapping_single_conversation_extracts_topics(self):
        """Single-conversation ChatGPT exports with a root mapping should be processed."""
        data = {
            "title": "Synthetic conversation",
            "mapping": {
                "msg_0000": {
                    "id": "msg_0000",
                    "message": {
                        "id": "msg_0000",
                        "author": {"role": "user"},
                        "content": {"content_type": "text", "parts": ["I use Python and pytest on Linux."]},
                        "create_time": 1759323600.0,
                    },
                    "parent": None,
                    "children": [],
                }
            },
        }

        extractor = AggressiveExtractor()
        result = extractor.process_openai_export(data)

        tech_topics = {topic["topic"] for topic in result["categories"].get("technical_expertise", [])}
        assert "Python" in tech_topics
        assert "Pytest" in tech_topics
        assert any(node["label"] == "Python" for node in result["nodes"])


def run_tests():
    """Run all tests and report results"""
    import traceback

    test_classes = [
        TestTypedRelationships,
        TestConflictDetection,
        TestIncrementalMerge,
        TestBidirectionalSync,
        TestPIIRedaction,
        TestMigratePipeline,
        TestIntegration,
    ]

    total = 0
    passed = 0
    failed = []

    for test_class in test_classes:
        print(f"\n{'=' * 60}")
        print(f"Running {test_class.__name__}")
        print("=" * 60)

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

    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} passed")
    print("=" * 60)

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
