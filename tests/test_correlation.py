"""
Tests for WP-5.6: Request Correlation & Enhanced Error Codes.

Covers:
- Request ID generation, parsing, and propagation
- New error codes (409, 410, 413, 415, 503)
- Error code registry completeness
- Request ID in error responses and success headers
"""

from __future__ import annotations

import json
import threading
import uuid

import pytest

from cortex.caas.correlation import (
    MAX_REQUEST_ID_LENGTH,
    RequestContext,
    generate_request_id,
    parse_request_id,
)
from cortex.upai.errors import (
    ERR_CONFLICT,
    ERR_GONE,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_PAYLOAD_TOO_LARGE,
    ERR_SERVICE_UNAVAILABLE,
    ERR_UNSUPPORTED_MEDIA_TYPE,
    ERROR_CODES,
)

# ── Request ID generation ────────────────────────────────────────────────


class TestGenerateRequestId:
    def test_returns_uuid(self):
        rid = generate_request_id()
        # Should be a valid UUID4
        parsed = uuid.UUID(rid, version=4)
        assert str(parsed) == rid

    def test_unique_per_call(self):
        ids = {generate_request_id() for _ in range(100)}
        assert len(ids) == 100


# ── Request ID parsing ───────────────────────────────────────────────────


class TestParseRequestId:
    def test_honors_valid_client_id(self):
        client_id = "my-request-123"
        assert parse_request_id(client_id) == client_id

    def test_honors_uuid_client_id(self):
        client_id = str(uuid.uuid4())
        assert parse_request_id(client_id) == client_id

    def test_generates_new_for_none(self):
        rid = parse_request_id(None)
        uuid.UUID(rid, version=4)  # valid UUID

    def test_generates_new_for_empty(self):
        rid = parse_request_id("")
        uuid.UUID(rid, version=4)

    def test_rejects_too_long(self):
        long_id = "x" * (MAX_REQUEST_ID_LENGTH + 1)
        rid = parse_request_id(long_id)
        assert rid != long_id
        uuid.UUID(rid, version=4)

    def test_accepts_max_length(self):
        max_id = "a" * MAX_REQUEST_ID_LENGTH
        assert parse_request_id(max_id) == max_id

    def test_rejects_non_ascii(self):
        rid = parse_request_id("req-\x00-id")
        assert rid != "req-\x00-id"
        uuid.UUID(rid, version=4)

    def test_rejects_control_characters(self):
        rid = parse_request_id("req\n-id")
        assert rid != "req\n-id"

    def test_accepts_printable_ascii(self):
        valid = "abc-123_XYZ.test@example"
        assert parse_request_id(valid) == valid


# ── RequestContext dataclass ─────────────────────────────────────────────


class TestRequestContext:
    def test_fields(self):
        ctx = RequestContext(
            request_id="rid-1",
            method="GET",
            path="/context",
            client_ip="127.0.0.1",
            start_time=1000.0,
        )
        assert ctx.request_id == "rid-1"
        assert ctx.method == "GET"
        assert ctx.path == "/context"
        assert ctx.client_ip == "127.0.0.1"
        assert ctx.start_time == 1000.0


# ── New error codes ──────────────────────────────────────────────────────


class TestNewErrorCodes:
    def test_conflict_409(self):
        err = ERR_CONFLICT("grant")
        assert err.http_status == 409
        assert err.code == "UPAI-4011"
        assert "grant" in err.message
        assert err.error_type == "conflict"

    def test_gone_410(self):
        err = ERR_GONE("key")
        assert err.http_status == 410
        assert err.code == "UPAI-4012"
        assert "key" in err.message
        assert err.error_type == "gone"

    def test_payload_too_large_413(self):
        err = ERR_PAYLOAD_TOO_LARGE()
        assert err.http_status == 413
        assert err.code == "UPAI-4013"
        assert err.error_type == "payload_too_large"

    def test_unsupported_media_type_415(self):
        err = ERR_UNSUPPORTED_MEDIA_TYPE()
        assert err.http_status == 415
        assert err.code == "UPAI-4014"
        assert err.error_type == "unsupported_media_type"

    def test_service_unavailable_503(self):
        err = ERR_SERVICE_UNAVAILABLE()
        assert err.http_status == 503
        assert err.code == "UPAI-5003"
        assert err.error_type == "service_unavailable"

    def test_custom_messages(self):
        err = ERR_PAYLOAD_TOO_LARGE("File too big")
        assert err.message == "File too big"

    def test_details_kwarg(self):
        err = ERR_CONFLICT("resource", max_size=1024)
        assert err.details["max_size"] == 1024


# ── Error code registry ──────────────────────────────────────────────────


class TestErrorCodeRegistry:
    def test_total_count(self):
        assert len(ERROR_CODES) == 17

    def test_all_client_errors_present(self):
        expected_client = [
            "UPAI-4001", "UPAI-4002", "UPAI-4003", "UPAI-4004", "UPAI-4005",
            "UPAI-4006", "UPAI-4007", "UPAI-4008", "UPAI-4009", "UPAI-4010",
            "UPAI-4011", "UPAI-4012", "UPAI-4013", "UPAI-4014",
        ]
        for code in expected_client:
            assert code in ERROR_CODES, f"Missing {code}"

    def test_all_server_errors_present(self):
        expected_server = ["UPAI-5001", "UPAI-5002", "UPAI-5003"]
        for code in expected_server:
            assert code in ERROR_CODES, f"Missing {code}"

    def test_values_are_string_types(self):
        for code, error_type in ERROR_CODES.items():
            assert isinstance(error_type, str)
            assert len(error_type) > 0


# ── request_id in error to_dict ──────────────────────────────────────────


class TestErrorRequestId:
    def test_request_id_in_error_dict(self):
        err = ERR_NOT_FOUND("thing")
        d = err.to_dict(request_id="req-abc")
        assert d["error"]["request_id"] == "req-abc"

    def test_no_request_id_when_empty(self):
        err = ERR_NOT_FOUND("thing")
        d = err.to_dict()
        assert "request_id" not in d["error"]

    def test_no_request_id_when_blank(self):
        err = ERR_NOT_FOUND("thing")
        d = err.to_dict(request_id="")
        assert "request_id" not in d["error"]

    def test_preserves_other_fields(self):
        err = ERR_INVALID_REQUEST("bad input", field="name")
        d = err.to_dict(request_id="req-123")
        assert d["error"]["code"] == "UPAI-4004"
        assert d["error"]["type"] == "invalid_request"
        assert d["error"]["message"] == "bad input"
        assert d["error"]["details"]["field"] == "name"
        assert d["error"]["request_id"] == "req-123"


# ── Integration: request ID in server responses ──────────────────────────


class TestServerRequestIdIntegration:
    """Test that server includes X-Request-ID in responses."""

    @pytest.fixture(autouse=True)
    def _setup_server(self):
        """Start a minimal CaaS server for testing."""
        from cortex.caas.server import CaaSHandler, ThreadingHTTPServer
        from cortex.graph import CortexGraph
        from cortex.upai.identity import UPAIIdentity

        identity = UPAIIdentity.generate(name="test-correlation")
        graph = CortexGraph()

        CaaSHandler.graph = graph
        CaaSHandler.identity = identity
        CaaSHandler.grant_store = __import__(
            "cortex.caas.server", fromlist=["JsonGrantStore"]
        ).JsonGrantStore()
        CaaSHandler.audit_log = None
        CaaSHandler.metrics_registry = None
        CaaSHandler.rate_limiter = None
        CaaSHandler.login_rate_limiter = None
        CaaSHandler.webhook_worker = None
        CaaSHandler.sse_manager = None
        CaaSHandler.session_manager = None
        CaaSHandler.oauth_manager = None
        CaaSHandler.credential_store = None
        CaaSHandler.keychain = None
        CaaSHandler._allowed_origins = {"http://127.0.0.1:0"}
        CaaSHandler.policy_registry = __import__(
            "cortex.upai.disclosure", fromlist=["PolicyRegistry"]
        ).PolicyRegistry()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), CaaSHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        yield
        self.server.shutdown()

    def _get(self, path: str, headers: dict | None = None) -> tuple:
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        return resp, body

    def test_auto_generates_request_id(self):
        resp, body = self._get("/health")
        rid = resp.getheader("X-Request-ID")
        assert rid is not None
        uuid.UUID(rid, version=4)  # valid UUID

    def test_honors_client_request_id(self):
        client_id = "my-custom-trace-id-42"
        resp, body = self._get("/health", headers={"X-Request-ID": client_id})
        rid = resp.getheader("X-Request-ID")
        assert rid == client_id

    def test_request_id_in_error_response(self):
        client_id = "trace-err-001"
        resp, body = self._get(
            "/nonexistent",
            headers={"X-Request-ID": client_id},
        )
        assert resp.status == 404
        data = json.loads(body)
        assert data["error"]["request_id"] == client_id
        assert resp.getheader("X-Request-ID") == client_id

    def test_invalid_request_id_replaced(self):
        bad_id = "x" * 200  # too long
        resp, body = self._get("/health", headers={"X-Request-ID": bad_id})
        rid = resp.getheader("X-Request-ID")
        assert rid != bad_id
        uuid.UUID(rid, version=4)

    def test_request_id_on_success_response(self):
        resp, body = self._get("/")
        rid = resp.getheader("X-Request-ID")
        assert rid is not None
        assert len(rid) > 0
