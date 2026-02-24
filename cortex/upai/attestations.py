"""
Peer Attestation Protocol — Let DID holders sign attestations for employment,
skills, or references, stored as VerifiableCredentials on the subject's graph.

Uses the existing CredentialIssuer/CredentialStore/CredentialVerifier infrastructure.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cortex.upai.credentials import CredentialStore, VerifiableCredential
    from cortex.upai.identity import UPAIIdentity


# ---------------------------------------------------------------------------
# Attestation type definitions
# ---------------------------------------------------------------------------

ATTESTATION_TYPES: dict[str, dict[str, Any]] = {
    "EmploymentAttestation": {
        "required_claims": ["subject_name", "employer", "role", "relationship"],
        "optional_claims": ["start_date", "end_date", "description"],
    },
    "SkillEndorsement": {
        "required_claims": ["subject_name", "skill", "proficiency_level"],
        "optional_claims": ["context", "years_experience"],
    },
    "ReferenceAttestation": {
        "required_claims": ["subject_name", "relationship", "reference_text"],
        "optional_claims": ["employer", "duration"],
    },
}


# ---------------------------------------------------------------------------
# AttestationRequest
# ---------------------------------------------------------------------------

@dataclass
class AttestationRequest:
    """A request for a peer to attest to claims about the subject."""

    request_id: str
    subject_did: str
    attestor_did: str
    attestation_type: str
    bound_node_id: str
    proposed_claims: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "subject_did": self.subject_did,
            "attestor_did": self.attestor_did,
            "attestation_type": self.attestation_type,
            "bound_node_id": self.bound_node_id,
            "proposed_claims": dict(self.proposed_claims),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AttestationRequest:
        return cls(
            request_id=d.get("request_id", ""),
            subject_did=d.get("subject_did", ""),
            attestor_did=d.get("attestor_did", ""),
            attestation_type=d.get("attestation_type", ""),
            bound_node_id=d.get("bound_node_id", ""),
            proposed_claims=dict(d.get("proposed_claims", {})),
            created_at=d.get("created_at", ""),
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_attestation_claims(
    attestation_type: str,
    claims: dict[str, Any],
) -> list[str]:
    """Validate claims against an attestation type schema.

    Returns a list of error strings (empty = valid).
    """
    errors: list[str] = []

    if attestation_type not in ATTESTATION_TYPES:
        errors.append(
            f"unknown attestation type: {attestation_type!r} "
            f"(valid: {', '.join(sorted(ATTESTATION_TYPES))})"
        )
        return errors

    type_def = ATTESTATION_TYPES[attestation_type]
    required = type_def["required_claims"]
    valid_keys = set(required) | set(type_def["optional_claims"])

    for req in required:
        val = claims.get(req, "")
        if not val or not str(val).strip():
            errors.append(f"missing required claim: {req}")

    # Warn about unknown claims
    for key in claims:
        if key not in valid_keys:
            errors.append(f"unknown claim: {key!r}")

    return errors


# ---------------------------------------------------------------------------
# Request creation
# ---------------------------------------------------------------------------

def create_attestation_request(
    identity: UPAIIdentity,
    attestor_did: str,
    attestation_type: str,
    proposed_claims: dict[str, Any],
    bound_node_id: str = "",
) -> tuple[AttestationRequest, Any]:
    """Create an attestation request wrapped in a SignedEnvelope.

    Returns ``(request, signed_envelope)``.
    """
    from cortex.upai.identity import SignedEnvelope

    request = AttestationRequest(
        request_id=str(uuid.uuid4()),
        subject_did=identity.did,
        attestor_did=attestor_did,
        attestation_type=attestation_type,
        bound_node_id=bound_node_id,
        proposed_claims=proposed_claims,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    envelope = SignedEnvelope.create(
        data=request.to_dict(),
        identity=identity,
        audience=attestor_did,
        ttl_seconds=86400,  # 24h
    )

    return request, envelope


# ---------------------------------------------------------------------------
# Attestation signing
# ---------------------------------------------------------------------------

def sign_attestation(
    attestor_identity: UPAIIdentity,
    request: AttestationRequest,
    claims: dict[str, Any],
    ttl_days: int = 365,
) -> Any:
    """Attestor signs an attestation, producing a VerifiableCredential.

    The attestor reviews the proposed claims, potentially modifies them,
    then signs with their identity as the issuer.
    """
    from cortex.upai.credentials import CredentialIssuer

    # Validate claims
    errors = validate_attestation_claims(request.attestation_type, claims)
    if errors:
        raise ValueError(f"Invalid attestation claims: {'; '.join(errors)}")

    issuer = CredentialIssuer()
    credential = issuer.issue(
        identity=attestor_identity,
        subject_did=request.subject_did,
        credential_type=["VerifiableCredential", request.attestation_type],
        claims=claims,
        ttl_days=ttl_days,
        bound_node_id=request.bound_node_id,
    )

    return credential


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_attestations_for_node(
    store: CredentialStore,
    node_id: str,
) -> list[VerifiableCredential]:
    """Get all attestation credentials bound to a specific node."""
    return store.list_by_node(node_id)


def get_attestation_summary(
    store: CredentialStore,
    node_id: str,
) -> dict[str, Any]:
    """Get a summary of attestations for a node."""
    creds = get_attestations_for_node(store, node_id)
    active = [c for c in creds if c.status == "active"]
    issuers = list({c.issuer_did for c in active})

    return {
        "node_id": node_id,
        "total": len(creds),
        "active": len(active),
        "issuer_dids": issuers,
        "types": list({t for c in active for t in c.credential_type
                       if t != "VerifiableCredential"}),
    }
