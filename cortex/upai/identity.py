"""
UPAI Identity — DID generation, keypair management, signing/verification.

Two modes:
- Crypto mode (Ed25519 via PyNaCl): real signatures, DID = did:upai:ed25519:<fingerprint>
- Stdlib mode (HMAC-SHA256): local-only integrity, DID = did:upai:sha256:<key_hash>
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional crypto dependency
# ---------------------------------------------------------------------------

try:
    import nacl.signing
    import nacl.encoding
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False


def has_crypto() -> bool:
    """Check if PyNaCl is available for Ed25519 signatures."""
    return _HAS_CRYPTO


# ---------------------------------------------------------------------------
# Keypair generation helpers
# ---------------------------------------------------------------------------

def _generate_ed25519_keypair() -> tuple[bytes, bytes]:
    """Generate Ed25519 keypair via PyNaCl. Returns (private_key, public_key)."""
    signing_key = nacl.signing.SigningKey.generate()
    private_bytes = bytes(signing_key)
    public_bytes = bytes(signing_key.verify_key)
    return private_bytes, public_bytes


def _generate_hmac_identity(name: str) -> tuple[str, bytes]:
    """Stdlib fallback: HMAC-SHA256 with random secret.

    Returns (did, secret_key).
    """
    secret = secrets.token_bytes(32)
    key_hash = hashlib.sha256(secret).hexdigest()[:32]
    did = f"did:upai:sha256:{key_hash}"
    return did, secret


# ---------------------------------------------------------------------------
# UPAIIdentity
# ---------------------------------------------------------------------------

@dataclass
class UPAIIdentity:
    did: str                      # "did:upai:ed25519:<fingerprint>" or "did:upai:sha256:<fingerprint>"
    name: str                     # Human-readable name
    public_key_b64: str           # Base64-encoded public key (Ed25519) or HMAC key hash
    created_at: str               # ISO-8601
    _private_key: bytes | None = field(default=None, repr=False)  # Never serialized; excluded from repr

    def __repr__(self) -> str:
        """Custom repr that never exposes private key material."""
        return (
            f"UPAIIdentity(did={self.did!r}, name={self.name!r}, "
            f"created_at={self.created_at!r}, has_private_key={self._private_key is not None})"
        )

    @classmethod
    def generate(cls, name: str) -> UPAIIdentity:
        """Generate new identity. Uses Ed25519 if available, HMAC fallback."""
        created_at = datetime.now(timezone.utc).isoformat()

        if _HAS_CRYPTO:
            private_bytes, public_bytes = _generate_ed25519_keypair()
            fingerprint = hashlib.sha256(public_bytes).hexdigest()[:32]
            did = f"did:upai:ed25519:{fingerprint}"
            public_key_b64 = base64.b64encode(public_bytes).decode("ascii")
            return cls(
                did=did,
                name=name,
                public_key_b64=public_key_b64,
                created_at=created_at,
                _private_key=private_bytes,
            )
        else:
            did, secret = _generate_hmac_identity(name)
            # For HMAC mode, public_key_b64 stores the hash of the secret
            # (the secret itself stays in _private_key)
            key_hash_b64 = base64.b64encode(
                hashlib.sha256(secret).digest()
            ).decode("ascii")
            return cls(
                did=did,
                name=name,
                public_key_b64=key_hash_b64,
                created_at=created_at,
                _private_key=secret,
            )

    def save(self, store_dir: Path) -> None:
        """Save identity.json (public) + identity.key (private) to store_dir."""
        store_dir.mkdir(parents=True, exist_ok=True)

        # Restrict store directory permissions
        try:
            os.chmod(store_dir, 0o700)
        except OSError:
            print(
                f"WARNING: Could not set permissions on {store_dir}. "
                "Private key may be accessible to other users.",
                file=sys.stderr,
            )

        # Public identity
        public_path = store_dir / "identity.json"
        public_path.write_text(json.dumps(self.to_public_dict(), indent=2))

        # Write .gitignore to protect key from accidental commits
        gitignore_path = store_dir / ".gitignore"
        if not gitignore_path.exists():
            gitignore_path.write_text("identity.key\n")

        # Private key — restrict file permissions
        if self._private_key is not None:
            key_path = store_dir / "identity.key"
            key_data = {
                "private_key_b64": base64.b64encode(self._private_key).decode("ascii"),
            }
            key_path.write_text(json.dumps(key_data, indent=2))
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                print(
                    f"WARNING: Could not restrict permissions on {key_path.name}. "
                    "Private key file may be readable by other users.",
                    file=sys.stderr,
                )

    @classmethod
    def load(cls, store_dir: Path) -> UPAIIdentity:
        """Load identity from store_dir."""
        public_path = store_dir / "identity.json"
        pub = json.loads(public_path.read_text())

        private_key = None
        key_path = store_dir / "identity.key"
        if key_path.exists():
            key_data = json.loads(key_path.read_text())
            private_key = base64.b64decode(key_data["private_key_b64"])

        return cls(
            did=pub["did"],
            name=pub["name"],
            public_key_b64=pub["public_key_b64"],
            created_at=pub["created_at"],
            _private_key=private_key,
        )

    def sign(self, data: bytes) -> str:
        """Sign data, return base64-encoded signature."""
        if self._private_key is None:
            raise ValueError("No private key available for signing")

        if self.did.startswith("did:upai:ed25519:"):
            signing_key = nacl.signing.SigningKey(self._private_key)
            signed = signing_key.sign(data)
            return base64.b64encode(signed.signature).decode("ascii")
        else:
            # HMAC-SHA256 fallback
            sig = hmac.new(self._private_key, data, hashlib.sha256).digest()
            return base64.b64encode(sig).decode("ascii")

    @classmethod
    def verify(cls, data: bytes, signature_b64: str, public_key_b64: str, *, key_type: str = "ed25519") -> bool:
        """Verify a signature against public key.

        For Ed25519: true cryptographic verification.
        For HMAC: always returns False (HMAC verification requires the secret).
        key_type should be "ed25519" or "sha256" to disambiguate key format.
        """
        if key_type != "ed25519":
            # HMAC mode: cannot verify without the secret key
            return False

        sig_bytes = base64.b64decode(signature_b64)
        pub_bytes = base64.b64decode(public_key_b64)

        if _HAS_CRYPTO:
            try:
                verify_key = nacl.signing.VerifyKey(pub_bytes)
                verify_key.verify(data, sig_bytes)
                return True
            except Exception:
                return False

        # No crypto library available
        return False

    def verify_own(self, data: bytes, signature_b64: str) -> bool:
        """Verify a signature using this identity's private key (HMAC mode support)."""
        if self._private_key is None:
            raise ValueError("No private key available for verification")

        if self.did.startswith("did:upai:ed25519:"):
            return self.verify(data, signature_b64, self.public_key_b64)
        else:
            # HMAC: recompute and compare
            sig_bytes = base64.b64decode(signature_b64)
            expected = hmac.new(self._private_key, data, hashlib.sha256).digest()
            return hmac.compare_digest(sig_bytes, expected)

    def integrity_hash(self, data: bytes) -> str:
        """SHA-256 integrity hash (always available, stdlib)."""
        return hashlib.sha256(data).hexdigest()

    def to_did_document(self) -> dict:
        """W3C-aligned DID document structure."""
        method = "ed25519" if self.did.startswith("did:upai:ed25519:") else "sha256"
        doc: dict = {
            "@context": "https://www.w3.org/ns/did/v1",
            "id": self.did,
            "controller": self.did,
            "created": self.created_at,
            "verificationMethod": [
                {
                    "id": f"{self.did}#key-1",
                    "type": f"{'Ed25519VerificationKey2020' if method == 'ed25519' else 'Sha256HmacKey2024'}",
                    "controller": self.did,
                    "publicKeyBase64": self.public_key_b64,
                }
            ],
            "authentication": [f"{self.did}#key-1"],
        }
        return doc

    def to_public_dict(self) -> dict:
        """Public identity info (no private key)."""
        return {
            "did": self.did,
            "name": self.name,
            "public_key_b64": self.public_key_b64,
            "created_at": self.created_at,
        }
