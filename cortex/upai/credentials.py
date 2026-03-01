"""
UPAI Verifiable Credentials — W3C-compliant credential issuance, verification, and storage.

Supports:
- Self-signed credentials (issuer == identity owner)
- External credential verification (caller provides issuer public key)
- In-memory + JSON persistence store
- Credential lifecycle: active → revoked | expired
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cortex.upai.identity import (
    UPAIIdentity,
    _base64url_decode,
    _base64url_encode,
)

# ---------------------------------------------------------------------------
# W3C VC context
# ---------------------------------------------------------------------------

W3C_CREDENTIALS_V1 = "https://www.w3.org/2018/credentials/v1"


# ---------------------------------------------------------------------------
# VerifiableCredential dataclass
# ---------------------------------------------------------------------------

@dataclass
class VerifiableCredential:
    """W3C Verifiable Credential data model."""

    credential_id: str            # uuid4
    context: list[str]            # ["https://www.w3.org/2018/credentials/v1"]
    credential_type: list[str]    # ["VerifiableCredential", "EmploymentCredential"]
    issuer_did: str               # DID of the issuer
    subject_did: str              # DID of the subject
    issuance_date: str            # ISO 8601
    expiration_date: str          # ISO 8601 (empty = no expiry)
    claims: dict                  # {"role": "Engineer", "company": "Acme"}
    proof: dict                   # {"type": "Ed25519Signature2020", ...}
    status: str                   # "active" | "revoked" | "expired"
    bound_node_id: str            # graph node this credential endorses (empty = unbound)

    def to_dict(self) -> dict:
        return {
            "@context": list(self.context),
            "id": self.credential_id,
            "type": list(self.credential_type),
            "issuer": self.issuer_did,
            "issuanceDate": self.issuance_date,
            "expirationDate": self.expiration_date,
            "credentialSubject": {
                "id": self.subject_did,
                **self.claims,
            },
            "proof": dict(self.proof),
            "status": self.status,
            "boundNodeId": self.bound_node_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> VerifiableCredential:
        subject = d.get("credentialSubject", {})
        subject_did = subject.get("id", "")
        claims = {k: v for k, v in subject.items() if k != "id"}
        return cls(
            credential_id=d.get("id", ""),
            context=list(d.get("@context", [W3C_CREDENTIALS_V1])),
            credential_type=list(d.get("type", ["VerifiableCredential"])),
            issuer_did=d.get("issuer", ""),
            subject_did=subject_did,
            issuance_date=d.get("issuanceDate", ""),
            expiration_date=d.get("expirationDate", ""),
            claims=claims,
            proof=dict(d.get("proof", {})),
            status=d.get("status", "active"),
            bound_node_id=d.get("boundNodeId", ""),
        )


# ---------------------------------------------------------------------------
# CredentialIssuer — self-sign credentials with an identity
# ---------------------------------------------------------------------------

class CredentialIssuer:
    """Issue W3C Verifiable Credentials signed by a UPAI identity."""

    def issue(
        self,
        identity: UPAIIdentity,
        subject_did: str,
        credential_type: list[str],
        claims: dict,
        ttl_days: int = 0,
        bound_node_id: str = "",
    ) -> VerifiableCredential:
        """Issue a self-signed credential.

        Args:
            identity: Issuer identity (must have private key).
            subject_did: DID of the credential subject.
            credential_type: List of types, must include "VerifiableCredential".
            claims: Claim key-value pairs.
            ttl_days: Days until expiry (0 = no expiry).
            bound_node_id: Optional graph node ID this credential endorses.

        Returns:
            Signed VerifiableCredential.
        """
        if identity._private_key is None:
            raise ValueError("Identity must have a private key to issue credentials")

        now = datetime.now(timezone.utc)
        credential_id = str(uuid.uuid4())

        # Ensure VerifiableCredential is in the type list
        types = list(credential_type)
        if "VerifiableCredential" not in types:
            types.insert(0, "VerifiableCredential")

        expiration = ""
        if ttl_days > 0:
            expiration = (now + timedelta(days=ttl_days)).isoformat()

        # Build credential without proof for signing
        credential_data = {
            "@context": [W3C_CREDENTIALS_V1],
            "id": credential_id,
            "type": types,
            "issuer": identity.did,
            "issuanceDate": now.isoformat(),
            "expirationDate": expiration,
            "credentialSubject": {
                "id": subject_did,
                **claims,
            },
            "boundNodeId": bound_node_id,
        }

        # Sign the canonical representation
        canonical = json.dumps(credential_data, sort_keys=True, ensure_ascii=False).encode("utf-8")
        signature = identity.sign(canonical)
        proof_value = _base64url_encode(
            __import__("base64").b64decode(signature)
        )

        alg = "Ed25519Signature2020" if identity._key_type == "ed25519" else "HmacSha256Signature2024"
        proof = {
            "type": alg,
            "created": now.isoformat(),
            "verificationMethod": f"{identity.did}#key-1",
            "proofPurpose": "assertionMethod",
            "proofValue": proof_value,
        }

        return VerifiableCredential(
            credential_id=credential_id,
            context=[W3C_CREDENTIALS_V1],
            credential_type=types,
            issuer_did=identity.did,
            subject_did=subject_did,
            issuance_date=now.isoformat(),
            expiration_date=expiration,
            claims=claims,
            proof=proof,
            status="active",
            bound_node_id=bound_node_id,
        )


# ---------------------------------------------------------------------------
# CredentialVerifier — verify credential signatures and status
# ---------------------------------------------------------------------------

class CredentialVerifier:
    """Verify W3C Verifiable Credentials."""

    def verify(
        self,
        credential_dict: dict,
        issuer_public_key_b64: str,
    ) -> tuple[bool, str]:
        """Verify a credential's signature and structure.

        Args:
            credential_dict: Credential as dict (from to_dict()).
            issuer_public_key_b64: Base64-encoded public key of the issuer.

        Returns:
            (success, error_message). error_message is empty on success.
        """
        # Check required fields
        for field_name in ("@context", "id", "type", "issuer", "issuanceDate", "proof"):
            if field_name not in credential_dict:
                return False, f"missing required field: {field_name}"

        proof = credential_dict.get("proof", {})
        if not proof.get("proofValue"):
            return False, "missing proofValue in proof"

        # Check expiry
        status = self.check_status_from_dict(credential_dict)
        if status == "expired":
            return False, "credential has expired"
        if status == "revoked":
            return False, "credential has been revoked"

        # Reconstruct signing input (credential without proof)
        credential_without_proof = {k: v for k, v in credential_dict.items()
                                     if k not in ("proof", "status")}
        canonical = json.dumps(credential_without_proof, sort_keys=True, ensure_ascii=False).encode("utf-8")

        # Decode signature
        proof_value = proof.get("proofValue", "")
        try:
            sig_bytes = _base64url_decode(proof_value)
        except Exception:
            return False, "invalid proofValue encoding"

        import base64
        sig_b64_standard = base64.b64encode(sig_bytes).decode("ascii")

        # Determine key type from proof type
        proof_type = proof.get("type", "")
        key_type = "ed25519" if "Ed25519" in proof_type else "sha256"

        if key_type == "sha256":
            import base64
            import hashlib
            import hmac

            sig_raw = base64.b64decode(sig_b64_standard)
            verify_key = base64.b64decode(issuer_public_key_b64)
            expected = hmac.new(verify_key, canonical, hashlib.sha256).digest()
            if not hmac.compare_digest(sig_raw, expected):
                return False, "invalid signature"
        else:
            if not UPAIIdentity.verify(canonical, sig_b64_standard, issuer_public_key_b64, key_type=key_type):
                return False, "invalid signature"

        return True, ""

    def check_status(self, credential: VerifiableCredential) -> str:
        """Check credential status: 'active', 'expired', or 'revoked'."""
        if credential.status == "revoked":
            return "revoked"
        if credential.expiration_date:
            try:
                exp = datetime.fromisoformat(credential.expiration_date)
                if datetime.now(timezone.utc) > exp:
                    return "expired"
            except (ValueError, TypeError):
                pass
        return "active"

    def check_status_from_dict(self, credential_dict: dict) -> str:
        """Check status from a credential dict."""
        if credential_dict.get("status") == "revoked":
            return "revoked"
        exp_str = credential_dict.get("expirationDate", "")
        if exp_str:
            try:
                exp = datetime.fromisoformat(exp_str)
                if datetime.now(timezone.utc) > exp:
                    return "expired"
            except (ValueError, TypeError):
                pass
        return "active"


# ---------------------------------------------------------------------------
# CredentialStore — in-memory + JSON persistence
# ---------------------------------------------------------------------------

class CredentialStore:
    """Thread-safe credential store with JSON persistence."""

    def __init__(self, store_path: str | None = None) -> None:
        self._credentials: dict[str, VerifiableCredential] = {}
        self._lock = threading.Lock()
        self._store_path = store_path
        if store_path:
            self._load()

    def _load(self) -> None:
        if self._store_path:
            p = Path(self._store_path)
            if p.exists():
                try:
                    data = json.loads(p.read_text())
                    for cred_dict in data.get("credentials", []):
                        cred = VerifiableCredential.from_dict(cred_dict)
                        self._credentials[cred.credential_id] = cred
                except (json.JSONDecodeError, KeyError):
                    pass

    def _save(self) -> None:
        if self._store_path:
            p = Path(self._store_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "credentials": [c.to_dict() for c in self._credentials.values()]
            }
            p.write_text(json.dumps(data, indent=2))

    def add(self, credential: VerifiableCredential) -> None:
        """Add a credential to the store."""
        with self._lock:
            self._credentials[credential.credential_id] = credential
            self._save()

    def get(self, credential_id: str) -> VerifiableCredential | None:
        """Get a credential by ID."""
        with self._lock:
            return self._credentials.get(credential_id)

    def list_all(self) -> list[VerifiableCredential]:
        """List all credentials."""
        with self._lock:
            return list(self._credentials.values())

    def list_by_node(self, node_id: str) -> list[VerifiableCredential]:
        """List credentials bound to a specific node."""
        with self._lock:
            return [c for c in self._credentials.values() if c.bound_node_id == node_id]

    def revoke(self, credential_id: str) -> bool:
        """Revoke a credential. Returns True if found and revoked."""
        with self._lock:
            cred = self._credentials.get(credential_id)
            if cred is None:
                return False
            cred.status = "revoked"
            self._save()
            return True

    def delete(self, credential_id: str) -> bool:
        """Delete a credential. Returns True if found and deleted."""
        with self._lock:
            if credential_id in self._credentials:
                del self._credentials[credential_id]
                self._save()
                return True
            return False

    @property
    def count(self) -> int:
        """Number of credentials in the store."""
        with self._lock:
            return len(self._credentials)
