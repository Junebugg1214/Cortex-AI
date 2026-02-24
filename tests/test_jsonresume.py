"""Tests for cortex.caas.jsonresume — JSON Resume Export (Feature 4)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from cortex.graph import CortexGraph, Node, make_node_id_with_tag
from cortex.caas.jsonresume import (
    _confidence_to_level,
    _map_basics,
    _map_certificates,
    _map_education,
    _map_languages,
    _map_projects,
    _map_references,
    _map_skills,
    _map_work,
    graph_to_jsonresume,
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

def _identity_node(name="Alice Smith", email="alice@example.com"):
    nid = make_node_id_with_tag(name, "identity")
    return Node(id=nid, label=name, tags=["identity"], confidence=0.95,
                properties={"email": email})


def _skill_node(name, confidence=0.85):
    nid = make_node_id_with_tag(name, "technical_expertise")
    return Node(id=nid, label=name, tags=["technical_expertise"],
                confidence=confidence)


def _language_node(name, confidence=0.9):
    nid = make_node_id_with_tag(name, "communication_preferences")
    return Node(id=nid, label=name, tags=["communication_preferences"],
                confidence=confidence, brief="Spoken language")


def _cert_node(name):
    nid = make_node_id_with_tag(name, "professional_context")
    return Node(id=nid, label=name, tags=["professional_context"],
                confidence=0.85, brief="Certification")


def _project_node(name, description=""):
    nid = make_node_id_with_tag(name, "active_priorities")
    return Node(id=nid, label=name, tags=["active_priorities"],
                confidence=0.8, brief=description)


# ---------------------------------------------------------------------------
# Basics mapping
# ---------------------------------------------------------------------------

class TestBasicsMapping(unittest.TestCase):

    def test_identity_to_basics(self):
        g = CortexGraph()
        g.add_node(_identity_node())
        basics = _map_basics(g)
        self.assertEqual(basics["name"], "Alice Smith")
        self.assertEqual(basics["email"], "alice@example.com")

    def test_missing_email(self):
        g = CortexGraph()
        nid = make_node_id_with_tag("Bob", "identity")
        g.add_node(Node(id=nid, label="Bob", tags=["identity"], confidence=0.9))
        basics = _map_basics(g)
        self.assertEqual(basics.get("name"), "Bob")
        self.assertNotIn("email", basics)

    def test_headline_from_professional_context(self):
        g = CortexGraph()
        g.add_node(_identity_node())
        nid = make_node_id_with_tag("headline", "professional_context")
        g.add_node(Node(id=nid, label="Full-Stack Engineer",
                        tags=["professional_context"], confidence=0.9,
                        brief="LinkedIn headline"))
        basics = _map_basics(g)
        self.assertEqual(basics.get("summary"), "LinkedIn headline")

    def test_empty_graph(self):
        g = CortexGraph()
        basics = _map_basics(g)
        self.assertEqual(basics, {})


# ---------------------------------------------------------------------------
# Work mapping
# ---------------------------------------------------------------------------

class TestWorkMapping(unittest.TestCase):

    def test_work_history_to_work(self):
        g = CortexGraph()
        entry = WorkHistoryEntry(
            employer="Acme", role="SWE", start_date="2020-01-15",
            end_date="2022-06-30", description="Built systems",
            achievements=["Shipped v2"],
        )
        g.add_node(create_work_history_node(entry))
        work = _map_work(g)
        self.assertEqual(len(work), 1)
        self.assertEqual(work[0]["name"], "Acme")
        self.assertEqual(work[0]["position"], "SWE")
        self.assertEqual(work[0]["startDate"], "2020-01-15")
        self.assertEqual(work[0]["endDate"], "2022-06-30")
        self.assertEqual(work[0]["highlights"], ["Shipped v2"])

    def test_date_sort_descending(self):
        g = CortexGraph()
        e1 = WorkHistoryEntry(employer="Old", role="R1", start_date="2015-01-01")
        e2 = WorkHistoryEntry(employer="New", role="R2", start_date="2022-01-01")
        g.add_node(create_work_history_node(e1))
        g.add_node(create_work_history_node(e2))
        work = _map_work(g)
        self.assertEqual(work[0]["name"], "New")
        self.assertEqual(work[1]["name"], "Old")

    def test_current_position_no_end_date(self):
        g = CortexGraph()
        entry = WorkHistoryEntry(employer="Acme", role="SWE", start_date="2023-01-01")
        g.add_node(create_work_history_node(entry))
        work = _map_work(g)
        self.assertNotIn("endDate", work[0])


# ---------------------------------------------------------------------------
# Education mapping
# ---------------------------------------------------------------------------

class TestEducationMapping(unittest.TestCase):

    def test_education_history_to_education(self):
        g = CortexGraph()
        entry = EducationHistoryEntry(
            institution="MIT", degree="B.S.", field_of_study="CS",
            start_date="2016-09-01", end_date="2020-05-15",
            gpa="3.8", courses=["Algorithms"],
        )
        g.add_node(create_education_node(entry))
        edu = _map_education(g)
        self.assertEqual(len(edu), 1)
        self.assertEqual(edu[0]["institution"], "MIT")
        self.assertEqual(edu[0]["studyType"], "B.S.")
        self.assertEqual(edu[0]["area"], "CS")
        self.assertEqual(edu[0]["score"], "3.8")
        self.assertEqual(edu[0]["courses"], ["Algorithms"])

    def test_education_no_gpa(self):
        g = CortexGraph()
        entry = EducationHistoryEntry(institution="MIT", degree="B.S.")
        g.add_node(create_education_node(entry))
        edu = _map_education(g)
        self.assertNotIn("score", edu[0])


# ---------------------------------------------------------------------------
# Skills mapping
# ---------------------------------------------------------------------------

class TestSkillsMapping(unittest.TestCase):

    def test_skills_mapping(self):
        g = CortexGraph()
        g.add_node(_skill_node("Python", 0.9))
        g.add_node(_skill_node("Rust", 0.5))
        skills = _map_skills(g)
        self.assertEqual(len(skills), 2)
        # Sorted by level desc
        self.assertEqual(skills[0]["name"], "Python")
        self.assertEqual(skills[0]["level"], "Expert")
        self.assertEqual(skills[1]["level"], "Intermediate")

    def test_confidence_boundaries(self):
        self.assertEqual(_confidence_to_level(0.0), "Beginner")
        self.assertEqual(_confidence_to_level(0.39), "Beginner")
        self.assertEqual(_confidence_to_level(0.4), "Intermediate")
        self.assertEqual(_confidence_to_level(0.59), "Intermediate")
        self.assertEqual(_confidence_to_level(0.6), "Advanced")
        self.assertEqual(_confidence_to_level(0.79), "Advanced")
        self.assertEqual(_confidence_to_level(0.8), "Expert")
        self.assertEqual(_confidence_to_level(1.0), "Expert")


# ---------------------------------------------------------------------------
# Languages
# ---------------------------------------------------------------------------

class TestLanguagesMapping(unittest.TestCase):

    def test_spoken_language(self):
        g = CortexGraph()
        g.add_node(_language_node("English"))
        langs = _map_languages(g)
        self.assertEqual(len(langs), 1)
        self.assertEqual(langs[0]["language"], "English")
        self.assertEqual(langs[0]["fluency"], "Native speaker")

    def test_non_spoken_language_excluded(self):
        g = CortexGraph()
        nid = make_node_id_with_tag("JSON", "communication_preferences")
        g.add_node(Node(id=nid, label="JSON", tags=["communication_preferences"],
                        confidence=0.8, brief="Preferred data format"))
        langs = _map_languages(g)
        self.assertEqual(len(langs), 0)


# ---------------------------------------------------------------------------
# Certificates
# ---------------------------------------------------------------------------

class TestCertificatesMapping(unittest.TestCase):

    def test_certification_detected(self):
        g = CortexGraph()
        g.add_node(_cert_node("AWS Solutions Architect"))
        certs = _map_certificates(g)
        self.assertEqual(len(certs), 1)
        self.assertEqual(certs[0]["name"], "AWS Solutions Architect")

    def test_non_cert_excluded(self):
        g = CortexGraph()
        nid = make_node_id_with_tag("CEO", "professional_context")
        g.add_node(Node(id=nid, label="CEO", tags=["professional_context"],
                        confidence=0.9, brief="Current role"))
        certs = _map_certificates(g)
        self.assertEqual(len(certs), 0)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class TestProjectsMapping(unittest.TestCase):

    def test_projects(self):
        g = CortexGraph()
        g.add_node(_project_node("Cortex-AI", "Knowledge graph platform"))
        projs = _map_projects(g)
        self.assertEqual(len(projs), 1)
        self.assertEqual(projs[0]["name"], "Cortex-AI")
        self.assertEqual(projs[0]["description"], "Knowledge graph platform")


# ---------------------------------------------------------------------------
# Sparse graph
# ---------------------------------------------------------------------------

class TestSparseGraph(unittest.TestCase):

    def test_empty_graph_returns_empty_resume(self):
        g = CortexGraph()
        resume = graph_to_jsonresume(g)
        self.assertEqual(resume, {})

    def test_partial_data_no_crash(self):
        g = CortexGraph()
        g.add_node(_skill_node("Python", 0.9))
        resume = graph_to_jsonresume(g)
        self.assertIn("skills", resume)
        self.assertNotIn("work", resume)
        self.assertNotIn("education", resume)

    def test_resume_is_valid_json(self):
        g = CortexGraph()
        g.add_node(_identity_node())
        g.add_node(_skill_node("Python", 0.9))
        resume = graph_to_jsonresume(g)
        # Should be JSON-serializable
        serialized = json.dumps(resume)
        self.assertIsInstance(json.loads(serialized), dict)


# ---------------------------------------------------------------------------
# render_memory format
# ---------------------------------------------------------------------------

class TestRenderMemoryFormat(unittest.TestCase):

    def test_jsonresume_format(self):
        from cortex.caas.api_keys import render_memory
        g = CortexGraph()
        g.add_node(_identity_node())
        content, ct = render_memory(g, "full", None, "jsonresume")
        self.assertEqual(ct, "application/json")
        data = json.loads(content)
        self.assertIn("basics", data)
        self.assertEqual(data["basics"]["name"], "Alice Smith")


# ---------------------------------------------------------------------------
# References (with mock credential store)
# ---------------------------------------------------------------------------

class TestReferencesMapping(unittest.TestCase):

    def test_references_from_credential_store(self):
        mock_cred = MagicMock()
        mock_cred.credential_type = ["VerifiableCredential", "ReferenceAttestation"]
        mock_cred.status = "active"
        mock_cred.claims = {
            "attestor_name": "Bob",
            "reference_text": "Alice is amazing",
        }
        mock_cred.issuer_did = "did:key:z123"

        mock_store = MagicMock()
        mock_store.list_all.return_value = [mock_cred]

        refs = _map_references(mock_store)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["name"], "Bob")
        self.assertEqual(refs[0]["reference"], "Alice is amazing")

    def test_no_credential_store(self):
        refs = _map_references(None)
        self.assertEqual(refs, [])

    def test_revoked_credential_excluded(self):
        mock_cred = MagicMock()
        mock_cred.credential_type = ["VerifiableCredential", "ReferenceAttestation"]
        mock_cred.status = "revoked"
        mock_cred.claims = {"reference_text": "Revoked reference"}

        mock_store = MagicMock()
        mock_store.list_all.return_value = [mock_cred]

        refs = _map_references(mock_store)
        self.assertEqual(len(refs), 0)


# ---------------------------------------------------------------------------
# Full integration
# ---------------------------------------------------------------------------

class TestFullResume(unittest.TestCase):

    def test_complete_resume(self):
        g = CortexGraph()
        g.add_node(_identity_node())
        g.add_node(create_work_history_node(
            WorkHistoryEntry(employer="Acme", role="SWE", start_date="2020-01-01",
                             description="Full stack", achievements=["Shipped v2"])))
        g.add_node(create_education_node(
            EducationHistoryEntry(institution="MIT", degree="B.S.", field_of_study="CS",
                                  start_date="2016-09-01", end_date="2020-05-15")))
        g.add_node(_skill_node("Python", 0.9))
        g.add_node(_language_node("English"))
        g.add_node(_cert_node("AWS SAA"))
        g.add_node(_project_node("Cortex-AI", "Knowledge graph"))

        resume = graph_to_jsonresume(g)
        self.assertIn("basics", resume)
        self.assertIn("work", resume)
        self.assertIn("education", resume)
        self.assertIn("skills", resume)
        self.assertIn("languages", resume)
        self.assertIn("certificates", resume)
        self.assertIn("projects", resume)


if __name__ == "__main__":
    unittest.main()
