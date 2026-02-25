"""Tests for cortex.caas.profile — Public Profile Page (Feature 2)."""

from __future__ import annotations

import html
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from cortex.graph import CortexGraph, Node, make_node_id_with_tag
from cortex.caas.profile import (
    DEFAULT_SECTIONS,
    RESERVED_HANDLES,
    ProfileConfig,
    ProfileStore,
    _slugify_handle,
    auto_populate_profile,
    render_profile_html,
    render_profile_jsonld,
    validate_handle,
)
from cortex.professional_timeline import (
    EducationHistoryEntry,
    WorkHistoryEntry,
    create_education_node,
    create_work_history_node,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _identity_node(name="Alice Smith"):
    nid = make_node_id_with_tag(name, "identity")
    return Node(id=nid, label=name, tags=["identity"], confidence=0.95,
                properties={"email": "alice@example.com"},
                brief="Software Engineer from NYC")


def _skill_node(name, confidence=0.85):
    nid = make_node_id_with_tag(name, "technical_expertise")
    return Node(id=nid, label=name, tags=["technical_expertise"],
                confidence=confidence)


def _project_node(name, desc=""):
    nid = make_node_id_with_tag(name, "active_priorities")
    return Node(id=nid, label=name, tags=["active_priorities"],
                confidence=0.8, brief=desc)


def _sample_graph():
    g = CortexGraph()
    g.add_node(_identity_node())
    g.add_node(create_work_history_node(
        WorkHistoryEntry(employer="Acme", role="SWE", start_date="2020-01-01",
                         description="Built systems", achievements=["Shipped v2"])))
    g.add_node(create_education_node(
        EducationHistoryEntry(institution="MIT", degree="B.S. CS",
                              start_date="2016-09-01", end_date="2020-05-15")))
    g.add_node(_skill_node("Python", 0.9))
    g.add_node(_skill_node("Rust", 0.7))
    g.add_node(_project_node("Cortex-AI", "Knowledge graph platform"))
    return g


def _default_config():
    return ProfileConfig(
        handle="alice",
        display_name="Alice Smith",
        headline="Software Engineer",
        bio="I build things.",
    )


# ---------------------------------------------------------------------------
# ProfileConfig
# ---------------------------------------------------------------------------

class TestProfileConfig(unittest.TestCase):

    def test_creation(self):
        config = _default_config()
        self.assertEqual(config.handle, "alice")
        self.assertEqual(config.display_name, "Alice Smith")
        self.assertEqual(config.policy, "professional")
        self.assertEqual(config.sections, DEFAULT_SECTIONS)

    def test_to_dict_roundtrip(self):
        config = _default_config()
        d = config.to_dict()
        restored = ProfileConfig.from_dict(d)
        self.assertEqual(restored.handle, "alice")
        self.assertEqual(restored.headline, "Software Engineer")
        self.assertEqual(restored.sections, DEFAULT_SECTIONS)

    def test_handle_validation_valid(self):
        self.assertEqual(validate_handle("alice"), [])
        self.assertEqual(validate_handle("alice-smith"), [])
        self.assertEqual(validate_handle("a12"), [])

    def test_handle_too_short(self):
        errors = validate_handle("ab")
        self.assertTrue(len(errors) > 0)

    def test_handle_invalid_chars(self):
        errors = validate_handle("Alice Smith")
        self.assertTrue(len(errors) > 0)

    def test_handle_reserved(self):
        for handle in ["admin", "api", "app", "dashboard"]:
            errors = validate_handle(handle)
            self.assertTrue(any("reserved" in e for e in errors), f"{handle} should be reserved")

    def test_handle_empty(self):
        errors = validate_handle("")
        self.assertTrue(len(errors) > 0)

    def test_handle_starts_with_hyphen(self):
        errors = validate_handle("-alice")
        self.assertTrue(len(errors) > 0)


# ---------------------------------------------------------------------------
# ProfileStore
# ---------------------------------------------------------------------------

class TestProfileStore(unittest.TestCase):

    def test_create_and_get(self):
        store = ProfileStore()
        config = _default_config()
        created = store.create(config)
        self.assertEqual(created.handle, "alice")
        self.assertTrue(created.created_at)

        retrieved = store.get("alice")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.display_name, "Alice Smith")

    def test_duplicate_handle_rejected(self):
        store = ProfileStore()
        store.create(_default_config())
        with self.assertRaises(ValueError):
            store.create(ProfileConfig(handle="alice"))

    def test_update(self):
        store = ProfileStore()
        store.create(_default_config())
        updated = store.update("alice", {"headline": "Senior Engineer"})
        self.assertIsNotNone(updated)
        self.assertEqual(updated.headline, "Senior Engineer")

    def test_delete(self):
        store = ProfileStore()
        store.create(_default_config())
        self.assertTrue(store.delete("alice"))
        self.assertIsNone(store.get("alice"))

    def test_delete_nonexistent(self):
        store = ProfileStore()
        self.assertFalse(store.delete("nonexistent"))

    def test_list_all(self):
        store = ProfileStore()
        store.create(_default_config())
        profiles = store.list_all()
        self.assertEqual(len(profiles), 1)

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "profiles.json"
            store1 = ProfileStore(path)
            store1.create(_default_config())

            # New store instance loads from disk
            store2 = ProfileStore(path)
            retrieved = store2.get("alice")
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved.display_name, "Alice Smith")

    def test_reserved_handle_rejected(self):
        store = ProfileStore()
        with self.assertRaises(ValueError):
            store.create(ProfileConfig(handle="admin"))


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

class TestRenderHTML(unittest.TestCase):

    def test_valid_html_output(self):
        graph = _sample_graph()
        config = _default_config()
        page = render_profile_html(graph, config)
        self.assertIn("<!DOCTYPE html>", page)
        self.assertIn("<html", page)
        self.assertIn("</html>", page)
        self.assertIn("Alice Smith", page)

    def test_sections_present(self):
        graph = _sample_graph()
        config = _default_config()
        page = render_profile_html(graph, config)
        self.assertIn("Experience", page)
        self.assertIn("Skills", page)
        self.assertIn("Education", page)
        self.assertIn("Projects", page)

    def test_meta_tags(self):
        graph = _sample_graph()
        config = _default_config()
        page = render_profile_html(graph, config)
        self.assertIn('og:title', page)
        self.assertIn('og:description', page)
        self.assertIn('og:type', page)

    def test_jsonld_in_html(self):
        graph = _sample_graph()
        config = _default_config()
        page = render_profile_html(graph, config)
        self.assertIn('application/ld+json', page)
        self.assertIn('schema.org', page)

    def test_empty_graph(self):
        graph = CortexGraph()
        config = _default_config()
        page = render_profile_html(graph, config)
        self.assertIn("<!DOCTYPE html>", page)
        self.assertIn("No public information available", page)

    def test_selective_sections(self):
        graph = _sample_graph()
        config = ProfileConfig(
            handle="alice",
            display_name="Alice",
            sections=["skills"],
        )
        page = render_profile_html(graph, config)
        self.assertIn("Skills", page)
        self.assertNotIn("<h2>Experience</h2>", page)
        self.assertNotIn("<h2>Education</h2>", page)


# ---------------------------------------------------------------------------
# JSON-LD
# ---------------------------------------------------------------------------

class TestJsonLD(unittest.TestCase):

    def test_basic_jsonld(self):
        graph = _sample_graph()
        config = _default_config()
        jsonld = render_profile_jsonld(graph, config)
        self.assertEqual(jsonld["@context"], "https://schema.org")
        self.assertEqual(jsonld["@type"], "Person")
        self.assertEqual(jsonld["name"], "Alice Smith")
        self.assertEqual(jsonld["jobTitle"], "Software Engineer")
        self.assertEqual(jsonld["description"], "I build things.")

    def test_email_from_graph(self):
        graph = _sample_graph()
        config = _default_config()
        jsonld = render_profile_jsonld(graph, config)
        self.assertEqual(jsonld.get("email"), "alice@example.com")


# ---------------------------------------------------------------------------
# Security: XSS prevention
# ---------------------------------------------------------------------------

class TestSecurity(unittest.TestCase):

    def test_xss_in_node_labels_escaped(self):
        graph = CortexGraph()
        malicious = '<script>alert("xss")</script>'
        nid = make_node_id_with_tag(malicious, "technical_expertise")
        graph.add_node(Node(id=nid, label=malicious,
                            tags=["technical_expertise"], confidence=0.9))
        config = ProfileConfig(handle="test-user", display_name="Test",
                               sections=["skills"])
        page = render_profile_html(graph, config)
        # The raw script tag should NOT appear in the output
        self.assertNotIn('<script>alert', page)
        # But the escaped version should
        self.assertIn(html.escape(malicious), page)

    def test_xss_in_display_name_escaped(self):
        graph = CortexGraph()
        config = ProfileConfig(
            handle="test-user",
            display_name='<img src=x onerror=alert(1)>',
            headline='<script>alert(2)</script>',
        )
        page = render_profile_html(graph, config)
        self.assertNotIn('<img src=x', page)
        self.assertNotIn('<script>alert(2)', page)

    def test_xss_in_work_history_escaped(self):
        graph = CortexGraph()
        entry = WorkHistoryEntry(
            employer='<b>Evil Corp</b>',
            role='<script>x</script>',
            start_date="2020-01-01",
        )
        graph.add_node(create_work_history_node(entry))
        config = ProfileConfig(handle="test-user", sections=["experience"])
        page = render_profile_html(graph, config)
        self.assertNotIn('<b>Evil Corp</b>', page)
        self.assertNotIn('<script>x</script>', page)


# ---------------------------------------------------------------------------
# Profile route (basic handler tests)
# ---------------------------------------------------------------------------

class TestProfileRoute(unittest.TestCase):

    def test_profile_page_returns_html(self):
        """Verify _serve_profile_page produces HTML."""
        import time as _time
        import io as _io
        from cortex.caas.server import CaaSHandler
        from cortex.caas.dashboard.auth import DashboardSessionManager
        from cortex.caas.profile import ProfileStore

        handler_class = CaaSHandler
        handler_class.graph = _sample_graph()
        handler_class.enable_webapp = True

        # Set up profile store with a profile
        store = ProfileStore()
        store.create(_default_config())
        handler_class.profile_store = store

        # Create handler
        handler = handler_class.__new__(handler_class)
        handler.client_address = ("127.0.0.1", 12345)
        handler._request_start_time = _time.monotonic()
        handler.path = "/p/alice"
        handler.command = "GET"

        response_data = {}

        def mock_respond(status, ct, data, **kw):
            response_data["status"] = status
            response_data["content_type"] = ct
            response_data["body"] = data

        handler._respond = mock_respond
        handler._init_request_id = lambda: None
        handler._metrics_inc_in_flight = lambda x: None
        handler._check_rate_limit = lambda: False

        handler._serve_profile_page("alice")
        self.assertEqual(response_data["status"], 200)
        self.assertEqual(response_data["content_type"], "text/html")
        self.assertIn(b"Alice Smith", response_data["body"])

    def test_unknown_handle_404(self):
        import time as _time
        from cortex.caas.server import CaaSHandler
        from cortex.caas.profile import ProfileStore

        handler_class = CaaSHandler
        handler_class.graph = _sample_graph()
        handler_class.enable_webapp = True
        handler_class.profile_store = ProfileStore()

        handler = handler_class.__new__(handler_class)
        handler.client_address = ("127.0.0.1", 12345)
        handler._request_start_time = _time.monotonic()
        handler.path = "/p/unknown"
        handler.command = "GET"

        response_data = {}

        def mock_respond(status, ct, data, **kw):
            response_data["status"] = status
            response_data["body"] = data

        handler._respond = mock_respond
        handler._init_request_id = lambda: None
        handler._metrics_inc_in_flight = lambda x: None
        handler._check_rate_limit = lambda: False

        handler._serve_profile_page("unknown")
        self.assertEqual(response_data["status"], 404)


# ---------------------------------------------------------------------------
# Auto-populate profile
# ---------------------------------------------------------------------------

class TestSlugifyHandle(unittest.TestCase):

    def test_simple_name(self):
        self.assertEqual(_slugify_handle("Alice Smith"), "alice-smith")

    def test_single_name(self):
        # "alice" is 5 chars, valid
        self.assertEqual(_slugify_handle("Alice"), "alice")

    def test_unicode_name(self):
        # Accented chars stripped to ASCII
        slug = _slugify_handle("José García")
        self.assertEqual(slug, "jose-garcia")

    def test_special_chars(self):
        slug = _slugify_handle("Dr. Jane O'Brien-Lee!")
        self.assertTrue(slug.startswith("dr-jane"))
        self.assertRegex(slug, r"^[a-z0-9][a-z0-9\-]+$")

    def test_minimum_length_padding(self):
        slug = _slugify_handle("AB")
        self.assertTrue(len(slug) >= 3)

    def test_empty_string(self):
        slug = _slugify_handle("")
        # Should still produce a valid handle (padded)
        self.assertTrue(len(slug) >= 3)


class TestAutoPopulateProfile(unittest.TestCase):

    def test_name_extraction(self):
        graph = _sample_graph()
        profile = auto_populate_profile(graph)
        self.assertEqual(profile.display_name, "Alice Smith")

    def test_handle_derivation(self):
        graph = _sample_graph()
        profile = auto_populate_profile(graph)
        self.assertEqual(profile.handle, "alice-smith")

    def test_bio_from_identity_brief(self):
        graph = _sample_graph()
        profile = auto_populate_profile(graph)
        self.assertEqual(profile.bio, "Software Engineer from NYC")

    def test_headline_from_professional_context(self):
        graph = CortexGraph()
        nid_i = make_node_id_with_tag("Alex", "identity")
        graph.add_node(Node(id=nid_i, label="Alex", tags=["identity"],
                            confidence=0.9))
        nid_p = make_node_id_with_tag("Backend Developer", "professional_context")
        graph.add_node(Node(id=nid_p, label="Backend Developer",
                            tags=["professional_context"], confidence=0.8,
                            brief="Current role"))
        profile = auto_populate_profile(graph)
        self.assertEqual(profile.headline, "Backend Developer")

    def test_empty_graph(self):
        graph = CortexGraph()
        profile = auto_populate_profile(graph)
        self.assertEqual(profile.display_name, "")
        self.assertEqual(profile.handle, "my-profile")
        self.assertEqual(profile.headline, "")
        self.assertEqual(profile.bio, "")

    def test_no_identity_nodes(self):
        graph = CortexGraph()
        nid = make_node_id_with_tag("CEO", "professional_context")
        graph.add_node(Node(id=nid, label="CEO",
                            tags=["professional_context"], confidence=0.85))
        profile = auto_populate_profile(graph)
        self.assertEqual(profile.display_name, "")
        self.assertEqual(profile.handle, "my-profile")
        self.assertEqual(profile.headline, "CEO")

    def test_reserved_handle_protection(self):
        graph = CortexGraph()
        nid = make_node_id_with_tag("Admin", "identity")
        graph.add_node(Node(id=nid, label="Admin", tags=["identity"],
                            confidence=0.9))
        profile = auto_populate_profile(graph)
        self.assertNotIn(profile.handle, RESERVED_HANDLES)
        self.assertEqual(profile.handle, "admin-profile")

    def test_default_policy_and_sections(self):
        graph = _sample_graph()
        profile = auto_populate_profile(graph)
        self.assertEqual(profile.policy, "professional")
        self.assertEqual(profile.sections, list(DEFAULT_SECTIONS))

    def test_avatar_url_from_properties(self):
        graph = CortexGraph()
        nid = make_node_id_with_tag("Jane", "identity")
        graph.add_node(Node(id=nid, label="Jane", tags=["identity"],
                            confidence=0.9,
                            properties={"avatar_url": "https://example.com/pic.jpg"}))
        profile = auto_populate_profile(graph)
        self.assertEqual(profile.avatar_url, "https://example.com/pic.jpg")

    def test_long_bio_fallback(self):
        """When identity has no brief, use long professional_context brief."""
        graph = CortexGraph()
        nid_i = make_node_id_with_tag("Bob", "identity")
        graph.add_node(Node(id=nid_i, label="Bob", tags=["identity"],
                            confidence=0.9, brief=""))
        long_text = "A" * 150
        nid_p = make_node_id_with_tag("Engineer", "professional_context")
        graph.add_node(Node(id=nid_p, label="Engineer",
                            tags=["professional_context"], confidence=0.8,
                            brief=long_text))
        profile = auto_populate_profile(graph)
        self.assertEqual(profile.bio, long_text[:500])

    def test_no_side_effects(self):
        """auto_populate_profile should not modify the graph."""
        graph = _sample_graph()
        nodes_before = len(graph.nodes)
        auto_populate_profile(graph)
        self.assertEqual(len(graph.nodes), nodes_before)


if __name__ == "__main__":
    unittest.main()
