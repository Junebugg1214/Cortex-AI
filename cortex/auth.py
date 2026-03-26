from __future__ import annotations

from dataclasses import dataclass

from cortex.config import APIKeyConfig


@dataclass(slots=True)
class AuthDecision:
    allowed: bool
    status_code: int = 200
    error: str = ""
    key_name: str = ""
    namespace: str | None = None


def extract_api_token(headers: dict[str, str]) -> str:
    normalized = {key.lower(): value for key, value in headers.items()}
    header_key = normalized.get("x-api-key", "").strip()
    if header_key:
        return header_key
    auth_header = normalized.get("authorization", "").strip()
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer ") :].strip()
    return ""


def authorize_api_key(
    *,
    keys: tuple[APIKeyConfig, ...],
    headers: dict[str, str],
    required_scope: str,
    namespace: str | None,
    namespace_required: bool,
) -> AuthDecision:
    if not keys:
        return AuthDecision(allowed=True, namespace=namespace)

    token = extract_api_token(headers)
    if not token:
        return AuthDecision(
            allowed=False,
            status_code=401,
            error="Unauthorized: missing API key. Configure Authorization: Bearer <token> or X-API-Key.",
        )

    key = next((item for item in keys if item.token == token), None)
    if key is None:
        return AuthDecision(allowed=False, status_code=401, error="Unauthorized: invalid API key.")
    if required_scope and not key.allows_scope(required_scope):
        return AuthDecision(
            allowed=False,
            status_code=403,
            error=f"Forbidden: API key '{key.name}' does not allow scope '{required_scope}'.",
        )

    effective_namespace = namespace
    namespace_prefixes = [item for item in key.namespaces if item != "*"]
    if namespace_prefixes:
        if namespace:
            if not key.allows_namespace(namespace):
                return AuthDecision(
                    allowed=False,
                    status_code=403,
                    error=(
                        f"Forbidden: namespace '{namespace}' is outside API key '{key.name}' namespace scope "
                        f"{list(key.namespaces)}."
                    ),
                )
        elif namespace_required:
            default_namespace = key.single_namespace()
            if default_namespace is None:
                return AuthDecision(
                    allowed=False,
                    status_code=403,
                    error=(
                        f"Forbidden: API key '{key.name}' spans multiple namespaces; "
                        "send X-Cortex-Namespace or include namespace in the request."
                    ),
                )
            effective_namespace = default_namespace

    return AuthDecision(
        allowed=True,
        key_name=key.name,
        namespace=effective_namespace,
    )


__all__ = ["AuthDecision", "authorize_api_key", "extract_api_token"]
