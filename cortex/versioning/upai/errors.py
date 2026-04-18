"""
UPAI Error Code Registry — Structured error responses for local CLI and library workflows.

Error codes follow the pattern:
- UPAI-4xxx: Client errors
- UPAI-5xxx: Server errors
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UPAIError:
    """Structured UPAI error response."""

    code: str  # "UPAI-4001"
    error_type: str  # "invalid_token"
    message: str
    details: dict = field(default_factory=dict)
    http_status: int = 400
    hint: str = ""

    def to_dict(self, request_id: str = "") -> dict:
        d: dict = {
            "error": {
                "code": self.code,
                "type": self.error_type,
                "message": self.message,
                "details": self.details,
            }
        }
        if self.hint:
            d["error"]["hint"] = self.hint
        if request_id:
            d["error"]["request_id"] = request_id
        return d


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def ERR_INVALID_TOKEN(
    message: str = "Token is malformed, expired, or has invalid signature", **details: object
) -> UPAIError:
    return UPAIError(
        code="UPAI-4001", error_type="invalid_token", message=message, details=dict(details), http_status=401
    )


def ERR_INSUFFICIENT_SCOPE(required: str = "", **details: object) -> UPAIError:
    msg = f"Token lacks required scope: {required}" if required else "Token lacks required scope"
    return UPAIError(
        code="UPAI-4002", error_type="insufficient_scope", message=msg, details=dict(details), http_status=403
    )


def ERR_NOT_FOUND(resource: str = "resource", **details: object) -> UPAIError:
    return UPAIError(
        code="UPAI-4003",
        error_type="not_found",
        message=f"{resource} not found",
        details=dict(details),
        http_status=404,
    )


def ERR_INVALID_REQUEST(message: str = "Request body is malformed", **details: object) -> UPAIError:
    return UPAIError(
        code="UPAI-4004", error_type="invalid_request", message=message, details=dict(details), http_status=400
    )


def ERR_INVALID_POLICY(policy: str = "", **details: object) -> UPAIError:
    msg = f"Unknown disclosure policy: {policy}" if policy else "Unknown disclosure policy"
    return UPAIError(code="UPAI-4005", error_type="invalid_policy", message=msg, details=dict(details), http_status=400)


def ERR_SCHEMA_VALIDATION(errors: list[str] | None = None, **details: object) -> UPAIError:
    d = dict(details)
    if errors:
        d["validation_errors"] = errors
    return UPAIError(
        code="UPAI-4006",
        error_type="schema_validation",
        message="Data fails schema validation",
        details=d,
        http_status=400,
    )


def ERR_REVOKED_KEY(did: str = "", **details: object) -> UPAIError:
    msg = f"Signing key {did} has been revoked" if did else "Signing key has been revoked"
    return UPAIError(code="UPAI-4007", error_type="revoked_key", message=msg, details=dict(details), http_status=401)


def ERR_REPLAY_DETECTED(**details: object) -> UPAIError:
    return UPAIError(
        code="UPAI-4008",
        error_type="replay_detected",
        message="Nonce has already been used",
        details=dict(details),
        http_status=400,
    )


def ERR_RATE_LIMITED(message: str = "Too many requests", **details: object) -> UPAIError:
    return UPAIError(
        code="UPAI-4009", error_type="rate_limited", message=message, details=dict(details), http_status=429
    )


def ERR_POLICY_IMMUTABLE(policy: str = "", **details: object) -> UPAIError:
    msg = f"Cannot modify built-in policy: {policy}" if policy else "Cannot modify built-in policy"
    return UPAIError(
        code="UPAI-4010", error_type="policy_immutable", message=msg, details=dict(details), http_status=403
    )


def ERR_CONFLICT(resource: str = "resource", **details: object) -> UPAIError:
    return UPAIError(
        code="UPAI-4011",
        error_type="conflict",
        message=f"{resource} already exists",
        details=dict(details),
        http_status=409,
    )


def ERR_GONE(resource: str = "resource", **details: object) -> UPAIError:
    return UPAIError(
        code="UPAI-4012",
        error_type="gone",
        message=f"{resource} has been permanently removed",
        details=dict(details),
        http_status=410,
    )


def ERR_PAYLOAD_TOO_LARGE(message: str = "Request payload exceeds size limit", **details: object) -> UPAIError:
    return UPAIError(
        code="UPAI-4013", error_type="payload_too_large", message=message, details=dict(details), http_status=413
    )


def ERR_UNSUPPORTED_MEDIA_TYPE(message: str = "Unsupported content type", **details: object) -> UPAIError:
    return UPAIError(
        code="UPAI-4014", error_type="unsupported_media_type", message=message, details=dict(details), http_status=415
    )


def ERR_INTERNAL(message: str = "Unexpected server error", **details: object) -> UPAIError:
    return UPAIError(
        code="UPAI-5001", error_type="internal_error", message=message, details=dict(details), http_status=500
    )


def ERR_NOT_CONFIGURED(message: str = "Server not fully configured", **details: object) -> UPAIError:
    return UPAIError(
        code="UPAI-5002", error_type="not_configured", message=message, details=dict(details), http_status=503
    )


def ERR_SERVICE_UNAVAILABLE(message: str = "Service temporarily unavailable", **details: object) -> UPAIError:
    return UPAIError(
        code="UPAI-5003", error_type="service_unavailable", message=message, details=dict(details), http_status=503
    )


# ---------------------------------------------------------------------------
# Error code → factory mapping
# ---------------------------------------------------------------------------

ERROR_CODES: dict[str, str] = {
    "UPAI-4001": "invalid_token",
    "UPAI-4002": "insufficient_scope",
    "UPAI-4003": "not_found",
    "UPAI-4004": "invalid_request",
    "UPAI-4005": "invalid_policy",
    "UPAI-4006": "schema_validation",
    "UPAI-4007": "revoked_key",
    "UPAI-4008": "replay_detected",
    "UPAI-4009": "rate_limited",
    "UPAI-4010": "policy_immutable",
    "UPAI-4011": "conflict",
    "UPAI-4012": "gone",
    "UPAI-4013": "payload_too_large",
    "UPAI-4014": "unsupported_media_type",
    "UPAI-5001": "internal_error",
    "UPAI-5002": "not_configured",
    "UPAI-5003": "service_unavailable",
}
