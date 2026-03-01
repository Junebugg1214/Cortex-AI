"""Regression tests for stdlib/HMAC auth behavior in CaaS server."""

from __future__ import annotations

import http.client
import json
import threading
from datetime import datetime, timedelta, timezone

from cortex.graph import CortexGraph
from cortex.upai.identity import UPAIIdentity
from cortex.upai.tokens import GrantToken


def _generate_hmac_identity(name: str) -> UPAIIdentity:
    import cortex.upai.identity as id_mod

    orig = id_mod._HAS_CRYPTO
    id_mod._HAS_CRYPTO = False
    try:
        return UPAIIdentity.generate(name)
    finally:
        id_mod._HAS_CRYPTO = orig


def _start_server(identity: UPAIIdentity):
    from cortex.caas.server import start_caas_server

    graph = CortexGraph()
    server = start_caas_server(graph=graph, identity=identity, port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def test_hmac_token_with_future_not_before_is_rejected():
    identity = _generate_hmac_identity("hmac-server")
    server, port = _start_server(identity)
    try:
        token = GrantToken.create(identity, audience="test", scopes=["context:read"])
        token.not_before = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        token_str = token.sign(identity)

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/context", headers={"Authorization": f"Bearer {token_str}"})
        resp = conn.getresponse()
        body = json.loads(resp.read() or b"{}")

        assert resp.status == 401
        assert body["error"]["type"] == "invalid_token"
        assert "not yet valid" in body["error"]["message"]
    finally:
        server.shutdown()


def test_hmac_token_with_malformed_signature_is_rejected_cleanly():
    identity = _generate_hmac_identity("hmac-server")
    server, port = _start_server(identity)
    try:
        token = GrantToken.create(identity, audience="test", scopes=["context:read"])
        token_str = token.sign(identity)
        parts = token_str.split(".")
        malformed = f"{parts[0]}.{parts[1]}.@@@"  # invalid base64url signature part

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/context", headers={"Authorization": f"Bearer {malformed}"})
        resp = conn.getresponse()
        body = json.loads(resp.read() or b"{}")

        assert resp.status == 401
        assert body["error"]["type"] == "invalid_token"
        assert body["error"]["message"] in {"malformed token signature", "invalid signature"}
    finally:
        server.shutdown()
