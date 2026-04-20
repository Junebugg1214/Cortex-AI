import cortex.service.auth as auth_module
from cortex.config import APIKeyConfig
from cortex.service.auth import authorize_api_key


def test_authorize_api_key_uses_constant_time_compare(monkeypatch):
    calls: list[tuple[str, str]] = []
    original_compare_digest = auth_module.secrets.compare_digest

    def counted_compare_digest(left, right):
        calls.append((left, right))
        return original_compare_digest(left, right)

    monkeypatch.setattr(auth_module.secrets, "compare_digest", counted_compare_digest)

    decision = authorize_api_key(
        keys=(
            APIKeyConfig(name="reader", token="reader-token", scopes=("read",), namespaces=("*",)),
            APIKeyConfig(name="writer", token="writer-token", scopes=("write",), namespaces=("*",)),
        ),
        headers={"X-API-Key": "writer-token"},
        required_scope="write",
        namespace=None,
        namespace_required=False,
    )

    assert decision.allowed is True
    assert calls == [("reader-token", "writer-token"), ("writer-token", "writer-token")]
