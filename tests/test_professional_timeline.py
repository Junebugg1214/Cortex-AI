"""Tests for cortex.professional_timeline — Professional Timeline Schema (Feature 1)."""

from __future__ import annotations

import io
import json
import csv
import zipfile
import unittest
from unittest.mock import patch

from cortex.graph import CortexGraph, Node, make_node_id_with_tag
from cortex.professional_timeline import (
    EMPLOYMENT_TYPES,
    EducationHistoryEntry,
    WorkHistoryEntry,
    create_education_node,
    create_work_history_node,
    get_timeline,
    validate_education_properties,
    validate_work_history_properties,
)


# ---------------------------------------------------------------------------
# WorkHistoryEntry
# ---------------------------------------------------------------------------

class TestWorkHistoryEntry(unittest.TestCase):

    def test_creation(self):
        e = WorkHistoryEntry(employer="Acme", role="Engineer", start_date="2020-01-15")
        self.assertEqual(e.employer, "Acme")
        self.assertEqual(e.role, "Engineer")
        self.assertEqual(e.start_date, "2020-01-15")
        self.assertEqual(e.end_date, "")
        self.assertTrue(e.current)

    def test_current_flag_false(self):
        e = WorkHistoryEntry(employer="Acme", role="Engineer",
                             start_date="2020-01-15", end_date="2022-06-30")
        self.assertFalse(e.current)

    def test_to_properties_roundtrip(self):
        e = WorkHistoryEntry(
            employer="Acme", role="Engineer", start_date="2020-01-15",
            end_date="2022-06-30", location="NYC", description="Built stuff",
            achievements=["Shipped v2"], employment_type="contract",
        )
        props = e.to_properties()
        restored = WorkHistoryEntry.from_properties(props)
        self.assertEqual(restored.employer, "Acme")
        self.assertEqual(restored.role, "Engineer")
        self.assertEqual(restored.end_date, "2022-06-30")
        self.assertEqual(restored.location, "NYC")
        self.assertEqual(restored.achievements, ["Shipped v2"])
        self.assertEqual(restored.employment_type, "contract")
        self.assertFalse(restored.current)

    def test_defaults(self):
        e = WorkHistoryEntry(employer="X", role="Y", start_date="2020-01-01")
        self.assertEqual(e.location, "")
        self.assertEqual(e.description, "")
        self.assertEqual(e.achievements, [])
        self.assertEqual(e.employment_type, "full-time")


# ---------------------------------------------------------------------------
# EducationHistoryEntry
# ---------------------------------------------------------------------------

class TestEducationHistoryEntry(unittest.TestCase):

    def test_creation(self):
        e = EducationHistoryEntry(institution="MIT", degree="B.S. CS")
        self.assertEqual(e.institution, "MIT")
        self.assertEqual(e.degree, "B.S. CS")
        self.assertTrue(e.current)

    def test_to_properties_roundtrip(self):
        e = EducationHistoryEntry(
            institution="MIT", degree="B.S.", field_of_study="CS",
            start_date="2016-09-01", end_date="2020-05-15",
            gpa="3.8", achievements=["Summa Cum Laude"], courses=["Algo 101"],
        )
        props = e.to_properties()
        restored = EducationHistoryEntry.from_properties(props)
        self.assertEqual(restored.institution, "MIT")
        self.assertEqual(restored.field_of_study, "CS")
        self.assertEqual(restored.gpa, "3.8")
        self.assertFalse(restored.current)
        self.assertEqual(restored.courses, ["Algo 101"])

    def test_defaults(self):
        e = EducationHistoryEntry(institution="X", degree="Y")
        self.assertEqual(e.field_of_study, "")
        self.assertEqual(e.gpa, "")
        self.assertEqual(e.achievements, [])
        self.assertEqual(e.courses, [])


# ---------------------------------------------------------------------------
# Node creation
# ---------------------------------------------------------------------------

class TestCreateNodes(unittest.TestCase):

    def test_work_history_node(self):
        entry = WorkHistoryEntry(employer="Acme", role="SWE",
                                 start_date="2020-01-15")
        node = create_work_history_node(entry)
        self.assertEqual(node.label, "SWE at Acme")
        self.assertIn("work_history", node.tags)
        self.assertEqual(node.properties["employer"], "Acme")
        self.assertEqual(node.properties["role"], "SWE")
        self.assertTrue(node.properties["current"])
        expected_id = make_node_id_with_tag("SWE at Acme", "work_history")
        self.assertEqual(node.id, expected_id)
        self.assertIn("present", node.brief)

    def test_education_node(self):
        entry = EducationHistoryEntry(institution="MIT", degree="B.S. CS",
                                      start_date="2016-09-01", end_date="2020-05-15")
        node = create_education_node(entry)
        self.assertEqual(node.label, "B.S. CS at MIT")
        self.assertIn("education_history", node.tags)
        self.assertEqual(node.properties["institution"], "MIT")
        self.assertFalse(node.properties["current"])
        expected_id = make_node_id_with_tag("B.S. CS at MIT", "education_history")
        self.assertEqual(node.id, expected_id)

    def test_deterministic_ids(self):
        e1 = WorkHistoryEntry(employer="Acme", role="SWE", start_date="2020-01-01")
        e2 = WorkHistoryEntry(employer="Acme", role="SWE", start_date="2020-01-01")
        self.assertEqual(create_work_history_node(e1).id, create_work_history_node(e2).id)

    def test_label_format(self):
        entry = WorkHistoryEntry(employer="Google", role="Staff Engineer",
                                 start_date="2020-01-01")
        node = create_work_history_node(entry)
        self.assertEqual(node.label, "Staff Engineer at Google")

    def test_confidence_is_high(self):
        entry = WorkHistoryEntry(employer="Acme", role="SWE", start_date="2020-01-01")
        node = create_work_history_node(entry)
        self.assertEqual(node.confidence, 0.95)


# ---------------------------------------------------------------------------
# get_timeline
# ---------------------------------------------------------------------------

class TestGetTimeline(unittest.TestCase):

    def test_chronological_sort(self):
        g = CortexGraph()
        e1 = WorkHistoryEntry(employer="A", role="R1", start_date="2018-01-01")
        e2 = WorkHistoryEntry(employer="B", role="R2", start_date="2022-01-01")
        g.add_node(create_work_history_node(e1))
        g.add_node(create_work_history_node(e2))

        timeline = get_timeline(g)
        self.assertEqual(len(timeline), 2)
        # Most recent first
        self.assertEqual(timeline[0].properties["employer"], "B")
        self.assertEqual(timeline[1].properties["employer"], "A")

    def test_mixed_work_education(self):
        g = CortexGraph()
        w = WorkHistoryEntry(employer="Acme", role="SWE", start_date="2021-01-01")
        e = EducationHistoryEntry(institution="MIT", degree="BS",
                                  start_date="2017-09-01", end_date="2021-05-15")
        g.add_node(create_work_history_node(w))
        g.add_node(create_education_node(e))

        timeline = get_timeline(g)
        self.assertEqual(len(timeline), 2)
        # Work (2021) comes first
        self.assertIn("work_history", timeline[0].tags)
        self.assertIn("education_history", timeline[1].tags)

    def test_empty_graph(self):
        g = CortexGraph()
        self.assertEqual(get_timeline(g), [])

    def test_ignores_non_timeline_nodes(self):
        g = CortexGraph()
        g.add_node(Node(id="x", label="Random", tags=["technical_expertise"]))
        w = WorkHistoryEntry(employer="Acme", role="SWE", start_date="2020-01-01")
        g.add_node(create_work_history_node(w))
        self.assertEqual(len(get_timeline(g)), 1)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation(unittest.TestCase):

    def test_valid_work_history(self):
        props = {"employer": "Acme", "role": "SWE", "start_date": "2020-01-15"}
        self.assertEqual(validate_work_history_properties(props), [])

    def test_missing_employer(self):
        props = {"role": "SWE", "start_date": "2020-01-15"}
        errors = validate_work_history_properties(props)
        self.assertTrue(any("employer" in e for e in errors))

    def test_missing_role(self):
        props = {"employer": "Acme", "start_date": "2020-01-15"}
        errors = validate_work_history_properties(props)
        self.assertTrue(any("role" in e for e in errors))

    def test_missing_start_date(self):
        props = {"employer": "Acme", "role": "SWE"}
        errors = validate_work_history_properties(props)
        self.assertTrue(any("start_date" in e for e in errors))

    def test_invalid_start_date_format(self):
        props = {"employer": "Acme", "role": "SWE", "start_date": "Jan 2020"}
        errors = validate_work_history_properties(props)
        self.assertTrue(any("start_date" in e for e in errors))

    def test_end_before_start(self):
        props = {"employer": "Acme", "role": "SWE",
                 "start_date": "2022-01-01", "end_date": "2020-01-01"}
        errors = validate_work_history_properties(props)
        self.assertTrue(any("end_date cannot be before" in e for e in errors))

    def test_invalid_employment_type(self):
        props = {"employer": "Acme", "role": "SWE", "start_date": "2020-01-01",
                 "employment_type": "wizard"}
        errors = validate_work_history_properties(props)
        self.assertTrue(any("employment_type" in e for e in errors))

    def test_valid_education(self):
        props = {"institution": "MIT", "degree": "B.S."}
        self.assertEqual(validate_education_properties(props), [])

    def test_education_missing_institution(self):
        props = {"degree": "B.S."}
        errors = validate_education_properties(props)
        self.assertTrue(any("institution" in e for e in errors))

    def test_education_missing_degree(self):
        props = {"institution": "MIT"}
        errors = validate_education_properties(props)
        self.assertTrue(any("degree" in e for e in errors))

    def test_education_invalid_dates(self):
        props = {"institution": "MIT", "degree": "B.S.",
                 "start_date": "not-a-date"}
        errors = validate_education_properties(props)
        self.assertTrue(any("start_date" in e for e in errors))

    def test_empty_string_fields(self):
        props = {"employer": "", "role": "", "start_date": ""}
        errors = validate_work_history_properties(props)
        self.assertGreaterEqual(len(errors), 3)

    def test_all_employment_types_valid(self):
        for emp_type in EMPLOYMENT_TYPES:
            props = {"employer": "X", "role": "Y", "start_date": "2020-01-01",
                     "employment_type": emp_type}
            self.assertEqual(validate_work_history_properties(props), [])


# ---------------------------------------------------------------------------
# LinkedIn import
# ---------------------------------------------------------------------------

class TestLinkedInImport(unittest.TestCase):

    def _make_zip(self, csvs: dict[str, list[dict]]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for filename, rows in csvs.items():
                if not rows:
                    zf.writestr(filename, "")
                    continue
                out = io.StringIO()
                writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
                zf.writestr(filename, out.getvalue())
        return buf.getvalue()

    def test_positions_create_work_history_nodes(self):
        from cortex.caas.importers import parse_linkedin_export
        data = self._make_zip({
            "Positions.csv": [{
                "Title": "Engineer",
                "Company Name": "Acme Corp",
                "Started On": "Jan 2020",
                "Finished On": "Dec 2022",
                "Description": "Built systems",
                "Location": "SF",
            }],
        })
        result = parse_linkedin_export(data)
        wh_nodes = [n for n in result["nodes"] if "work_history" in n.get("tags", [])]
        self.assertEqual(len(wh_nodes), 1)
        self.assertEqual(wh_nodes[0]["label"], "Engineer at Acme Corp")
        self.assertEqual(wh_nodes[0]["properties"]["start_date"], "2020-01-01")
        self.assertEqual(wh_nodes[0]["properties"]["end_date"], "2022-12-01")

    def test_education_creates_education_history_nodes(self):
        from cortex.caas.importers import parse_linkedin_export
        data = self._make_zip({
            "Education.csv": [{
                "School Name": "MIT",
                "Degree Name": "B.S. Computer Science",
                "Start Date": "2016",
                "End Date": "2020",
                "Notes": "CS",
            }],
        })
        result = parse_linkedin_export(data)
        eh_nodes = [n for n in result["nodes"] if "education_history" in n.get("tags", [])]
        self.assertEqual(len(eh_nodes), 1)
        self.assertEqual(eh_nodes[0]["properties"]["institution"], "MIT")
        self.assertEqual(eh_nodes[0]["properties"]["degree"], "B.S. Computer Science")

    def test_backward_compat_professional_context_still_created(self):
        from cortex.caas.importers import parse_linkedin_export
        data = self._make_zip({
            "Positions.csv": [{
                "Title": "Engineer",
                "Company Name": "Acme",
                "Started On": "",
                "Finished On": "",
                "Description": "",
                "Location": "",
            }],
        })
        result = parse_linkedin_export(data)
        pc_nodes = [n for n in result["nodes"] if "professional_context" in n.get("tags", [])]
        self.assertGreaterEqual(len(pc_nodes), 1)

    def test_backward_compat_education_nodes_still_created(self):
        from cortex.caas.importers import parse_linkedin_export
        data = self._make_zip({
            "Education.csv": [{
                "School Name": "MIT",
                "Degree Name": "B.S.",
                "Start Date": "",
                "End Date": "",
                "Notes": "",
            }],
        })
        result = parse_linkedin_export(data)
        edu_nodes = [n for n in result["nodes"] if "education" in n.get("tags", [])]
        self.assertGreaterEqual(len(edu_nodes), 1)


# ---------------------------------------------------------------------------
# Timeline API
# ---------------------------------------------------------------------------

class TestTimelineAPI(unittest.TestCase):
    """Test the timeline CRUD routes on the CaaS server."""

    @classmethod
    def setUpClass(cls):
        import time as _time
        from cortex.caas.server import CaaSHandler
        from cortex.caas.dashboard.auth import DashboardSessionManager
        # Minimal server setup for testing
        cls.handler_class = CaaSHandler
        cls.handler_class.graph = CortexGraph()
        cls.handler_class.enable_webapp = True
        sm = DashboardSessionManager.__new__(DashboardSessionManager)
        sm._sessions = {}
        sm._session_meta = {}
        sm._lock = __import__("threading").Lock()
        sm._session_ttl = 3600
        cls._token = "test-session-token"
        # Store expiry as float (time.monotonic() + ttl)
        sm._sessions[cls._token] = _time.monotonic() + 3600
        cls.handler_class.session_manager = sm

    def _make_handler(self, body=None):
        """Create a handler with mocked I/O and auth."""
        import io as _io
        import time as _time

        body_bytes = json.dumps(body).encode() if body else b""

        handler = self.handler_class.__new__(self.handler_class)
        handler.client_address = ("127.0.0.1", 12345)
        handler._request_start_time = _time.monotonic()
        handler.path = "/api/timeline"
        handler.command = "GET"

        response_data = {}

        def mock_respond(status, ct, data, **kw):
            response_data["status"] = status
            response_data["body"] = data
            response_data["content_type"] = ct

        handler._respond = mock_respond
        handler._init_request_id = lambda: None
        handler._metrics_inc_in_flight = lambda x: None
        handler._check_rate_limit = lambda: False

        token = self._token

        class MockHeaders:
            def get(self2, k, d=""):
                return {
                    "Cookie": f"cortex_app_session={token}",
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body_bytes)),
                    "If-None-Match": "",
                }.get(k, d)

        handler.headers = MockHeaders()
        handler.rfile = _io.BytesIO(body_bytes)

        return handler, response_data

    def test_get_timeline_empty(self):
        self.handler_class.graph = CortexGraph()
        handler, resp = self._make_handler()
        handler._handle_get_timeline()
        self.assertEqual(resp["status"], 200)
        data = json.loads(resp["body"])
        self.assertEqual(data["count"], 0)

    def test_create_work_history(self):
        self.handler_class.graph = CortexGraph()
        body = {
            "type": "work_history",
            "properties": {
                "employer": "Acme",
                "role": "Engineer",
                "start_date": "2020-01-15",
            },
        }
        handler, resp = self._make_handler(body)
        handler._handle_create_timeline_entry()
        self.assertEqual(resp["status"], 201)
        data = json.loads(resp["body"])
        self.assertEqual(data["node"]["label"], "Engineer at Acme")
        self.assertIn(data["id"], self.handler_class.graph.nodes)

    def test_create_education_history(self):
        self.handler_class.graph = CortexGraph()
        body = {
            "type": "education_history",
            "properties": {
                "institution": "MIT",
                "degree": "B.S. CS",
            },
        }
        handler, resp = self._make_handler(body)
        handler._handle_create_timeline_entry()
        self.assertEqual(resp["status"], 201)
        data = json.loads(resp["body"])
        self.assertIn("education_history", data["node"]["tags"])

    def test_create_invalid_type(self):
        self.handler_class.graph = CortexGraph()
        body = {"type": "invalid", "properties": {"employer": "X"}}
        handler, resp = self._make_handler(body)
        handler._handle_create_timeline_entry()
        self.assertIn(resp["status"], (400, 422))

    def test_create_missing_required_fields(self):
        self.handler_class.graph = CortexGraph()
        body = {"type": "work_history", "properties": {"employer": "Acme"}}
        handler, resp = self._make_handler(body)
        handler._handle_create_timeline_entry()
        self.assertIn(resp["status"], (400, 422))

    def test_delete_timeline_entry(self):
        self.handler_class.graph = CortexGraph()
        from cortex.professional_timeline import WorkHistoryEntry, create_work_history_node
        entry = WorkHistoryEntry(employer="Acme", role="SWE", start_date="2020-01-01")
        node = create_work_history_node(entry)
        self.handler_class.graph.add_node(node)

        handler, resp = self._make_handler()
        handler._handle_delete_timeline_entry(node.id)
        self.assertEqual(resp["status"], 200)
        self.assertNotIn(node.id, self.handler_class.graph.nodes)

    def test_delete_nonexistent(self):
        self.handler_class.graph = CortexGraph()
        handler, resp = self._make_handler()
        handler._handle_delete_timeline_entry("nonexistent")
        self.assertEqual(resp["status"], 404)


# ---------------------------------------------------------------------------
# CATEGORY_ORDER
# ---------------------------------------------------------------------------

class TestCategoryOrder(unittest.TestCase):

    def test_new_tags_in_category_order(self):
        from cortex.graph import CATEGORY_ORDER
        self.assertIn("work_history", CATEGORY_ORDER)
        self.assertIn("education_history", CATEGORY_ORDER)

    def test_new_tags_after_active_priorities(self):
        from cortex.graph import CATEGORY_ORDER
        ap_idx = CATEGORY_ORDER.index("active_priorities")
        wh_idx = CATEGORY_ORDER.index("work_history")
        eh_idx = CATEGORY_ORDER.index("education_history")
        self.assertGreater(wh_idx, ap_idx)
        self.assertGreater(eh_idx, ap_idx)


# ---------------------------------------------------------------------------
# Disclosure policy
# ---------------------------------------------------------------------------

class TestDisclosurePolicyUpdate(unittest.TestCase):

    def test_professional_policy_includes_timeline_tags(self):
        from cortex.upai.disclosure import BUILTIN_POLICIES
        prof = BUILTIN_POLICIES["professional"]
        self.assertIn("work_history", prof.include_tags)
        self.assertIn("education_history", prof.include_tags)

    def test_professional_api_key_policy_includes_timeline_tags(self):
        from cortex.caas.api_keys import POLICY_TAGS
        prof = POLICY_TAGS["professional"]
        self.assertIn("work_history", prof)
        self.assertIn("education_history", prof)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TestSchemas(unittest.TestCase):

    def test_schemas_registered(self):
        from cortex.upai.schemas import SCHEMAS
        self.assertIn("work_history_properties", SCHEMAS)
        self.assertIn("education_history_properties", SCHEMAS)

    def test_work_history_schema_validation(self):
        from cortex.upai.schemas import SCHEMAS, validate
        schema = SCHEMAS["work_history_properties"]
        valid = {"employer": "Acme", "role": "SWE", "start_date": "2020-01-15"}
        self.assertEqual(validate(valid, schema), [])

    def test_work_history_schema_missing_required(self):
        from cortex.upai.schemas import SCHEMAS, validate
        schema = SCHEMAS["work_history_properties"]
        invalid = {"employer": "Acme"}
        errors = validate(invalid, schema)
        self.assertTrue(len(errors) > 0)


if __name__ == "__main__":
    unittest.main()
