"""
UPAI Identity — DID generation, keypair management, signing/verification.

Two modes:
- Crypto mode (Ed25519 via PyNaCl): real signatures, DID = did:key:z6Mk...
- Stdlib mode (HMAC-SHA256): local-only integrity, DID = did:upai:sha256:<key_hash>

Supports loading legacy did:upai:ed25519:* identities for backward compatibility.
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
    import nacl.encoding
    import nacl.signing
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False


def has_crypto() -> bool:
    """Check if PyNaCl is available for Ed25519 signatures."""
    return _HAS_CRYPTO


# ---------------------------------------------------------------------------
# Base58btc encoding (Bitcoin alphabet)
# ---------------------------------------------------------------------------

_B58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_BASE = len(_B58_ALPHABET)  # 58


def _base58btc_encode(data: bytes) -> str:
    """Encode bytes to base58btc (Bitcoin alphabet)."""
    # Count leading zero bytes
    n_leading = 0
    for b in data:
        if b == 0:
            n_leading += 1
        else:
            break

    # Convert to integer
    num = int.from_bytes(data, "big")

    # Encode
    result = bytearray()
    while num > 0:
        num, remainder = divmod(num, _B58_BASE)
        result.append(_B58_ALPHABET[remainder])
    result.reverse()

    # Prepend '1' for each leading zero byte
    return ("1" * n_leading) + result.decode("ascii")


def _base58btc_decode(encoded: str) -> bytes:
    """Decode base58btc string to bytes."""
    # Count leading '1' chars (represent leading zero bytes)
    n_leading = 0
    for ch in encoded:
        if ch == "1":
            n_leading += 1
        else:
            break

    # Convert from base58 to integer
    num = 0
    for ch in encoded:
        idx = _B58_ALPHABET.index(ch.encode("ascii"))
        num = num * _B58_BASE + idx

    # Convert to bytes
    if num == 0:
        result = b""
    else:
        result = num.to_bytes((num.bit_length() + 7) // 8, "big")

    return b"\x00" * n_leading + result


# ---------------------------------------------------------------------------
# Base64url encoding (URL-safe, no padding)
# ---------------------------------------------------------------------------

def _base64url_encode(data: bytes) -> str:
    """URL-safe base64 encoding without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(encoded: str) -> bytes:
    """URL-safe base64 decoding with padding restoration."""
    # Add padding only if needed: (4 - len % 4) % 4 gives 0,3,2,1 for len%4 = 0,1,2,3
    padded = encoded + "=" * ((4 - len(encoded) % 4) % 4)
    return base64.urlsafe_b64decode(padded)


# ---------------------------------------------------------------------------
# DID:key helpers
# ---------------------------------------------------------------------------

_ED25519_MULTICODEC_PREFIX = b"\xed\x01"


def _public_key_to_did_key(pub_bytes: bytes) -> str:
    """Convert Ed25519 public key bytes to did:key:z6Mk... format."""
    multicodec = _ED25519_MULTICODEC_PREFIX + pub_bytes
    return "did:key:z" + _base58btc_encode(multicodec)


def _did_key_to_public_key(did: str) -> bytes:
    """Extract Ed25519 public key bytes from did:key:z6Mk... format."""
    if not did.startswith("did:key:z"):
        raise ValueError(f"Not a did:key: {did}")
    multibase_value = did[len("did:key:z"):]
    decoded = _base58btc_decode(multibase_value)
    if not decoded.startswith(_ED25519_MULTICODEC_PREFIX):
        raise ValueError("Not an Ed25519 did:key (wrong multicodec prefix)")
    return decoded[len(_ED25519_MULTICODEC_PREFIX):]


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
    did: str                      # "did:key:z6Mk..." or "did:upai:sha256:<fingerprint>" or legacy "did:upai:ed25519:<fingerprint>"
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

    @property
    def _key_type(self) -> str:
        """Return 'ed25519' if this identity uses Ed25519, 'sha256' for HMAC."""
        if self.did.startswith("did:key:"):
            return "ed25519"
        if self.did.startswith("did:upai:ed25519:"):
            return "ed25519"
        return "sha256"

    @classmethod
    def generate(cls, name: str) -> UPAIIdentity:
        """Generate new identity. Uses Ed25519 if available, HMAC fallback."""
        created_at = datetime.now(timezone.utc).isoformat()

        if _HAS_CRYPTO:
            private_bytes, public_bytes = _generate_ed25519_keypair()
            did = _public_key_to_did_key(public_bytes)
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
        """Load identity from store_dir. Works with both did:key and legacy did:upai formats."""
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

    def migrate_did(self) -> str:
        """Compute the did:key for this identity from stored public key (opt-in migration).

        Returns the new did:key string. Does NOT modify self — caller decides whether to update.
        """
        if self._key_type != "ed25519":
            raise ValueError("Cannot migrate HMAC identity to did:key")
        pub_bytes = base64.b64decode(self.public_key_b64)
        return _public_key_to_did_key(pub_bytes)

    def sign(self, data: bytes) -> str:
        """Sign data, return base64-encoded signature."""
        if self._private_key is None:
            raise ValueError("No private key available for signing")

        if self._key_type == "ed25519":
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

        if self._key_type == "ed25519":
            return self.verify(data, signature_b64, self.public_key_b64)
        else:
            # HMAC: recompute and compare
            sig_bytes = base64.b64decode(signature_b64)
            expected = hmac.new(self._private_key, data, hashlib.sha256).digest()
            return hmac.compare_digest(sig_bytes, expected)

    def integrity_hash(self, data: bytes) -> str:
        """SHA-256 integrity hash (always available, stdlib)."""
        return hashlib.sha256(data).hexdigest()

    def to_did_document(self, service_endpoints: list[dict] | None = None) -> dict:
        """W3C DID Core compliant document structure.

        For did:key identities, uses publicKeyMultibase.
        For legacy identities, uses publicKeyBase64.
        Optionally includes service endpoints.
        """
        is_did_key = self.did.startswith("did:key:")
        is_ed25519 = self._key_type == "ed25519"

        vm: dict = {
            "id": f"{self.did}#key-1",
            "type": "Ed25519VerificationKey2020" if is_ed25519 else "Sha256HmacKey2024",
            "controller": self.did,
        }

        if is_did_key:
            # Use publicKeyMultibase for did:key (W3C DID Core compliant)
            pub_bytes = base64.b64decode(self.public_key_b64)
            multicodec = _ED25519_MULTICODEC_PREFIX + pub_bytes
            vm["publicKeyMultibase"] = "z" + _base58btc_encode(multicodec)
        else:
            vm["publicKeyBase64"] = self.public_key_b64

        doc: dict = {
            "@context": "https://www.w3.org/ns/did/v1",
            "id": self.did,
            "controller": self.did,
            "created": self.created_at,
            "verificationMethod": [vm],
            "authentication": [f"{self.did}#key-1"],
        }

        # alsoKnownAs for backward compat with legacy DID
        if is_did_key and is_ed25519:
            pub_bytes = base64.b64decode(self.public_key_b64)
            fingerprint = hashlib.sha256(pub_bytes).hexdigest()[:32]
            legacy_did = f"did:upai:ed25519:{fingerprint}"
            doc["alsoKnownAs"] = [legacy_did]

        if service_endpoints:
            doc["service"] = service_endpoints

        return doc

    def to_public_dict(self) -> dict:
        """Public identity info (no private key)."""
        return {
            "did": self.did,
            "name": self.name,
            "public_key_b64": self.public_key_b64,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# SignedEnvelope — replay-protected signed data container
# ---------------------------------------------------------------------------

@dataclass
class SignedEnvelope:
    """Signed envelope with replay protection (nonce, iat, exp, aud)."""

    header: dict       # {"alg": "Ed25519"|"HMAC-SHA256", "typ": "UPAI-Envelope"}
    payload: dict      # data + nonce + iat + exp + aud
    signature: str     # base64url signature

    @classmethod
    def create(
        cls,
        data: dict | list,
        identity: UPAIIdentity,
        audience: str = "",
        ttl_seconds: int = 300,
    ) -> SignedEnvelope:
        """Create a signed envelope wrapping data with replay protection."""
        now = datetime.now(timezone.utc)

        alg = "Ed25519" if identity._key_type == "ed25519" else "HMAC-SHA256"
        header = {"alg": alg, "typ": "UPAI-Envelope"}

        payload = {
            "data": data,
            "nonce": secrets.token_hex(16),
            "iat": now.isoformat(),
            "exp": datetime.fromtimestamp(
                now.timestamp() + ttl_seconds, tz=timezone.utc
            ).isoformat(),
            "aud": audience,
        }

        # Sign over header.payload
        header_b64 = _base64url_encode(
            json.dumps(header, sort_keys=True, ensure_ascii=False).encode("utf-8")
        )
        payload_b64 = _base64url_encode(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        )
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        sig = identity.sign(signing_input)
        sig_b64url = _base64url_encode(base64.b64decode(sig))

        return cls(header=header, payload=payload, signature=sig_b64url)

    def serialize(self) -> str:
        """Serialize to three-part base64url format: header.payload.signature."""
        header_b64 = _base64url_encode(
            json.dumps(self.header, sort_keys=True, ensure_ascii=False).encode("utf-8")
        )
        payload_b64 = _base64url_encode(
            json.dumps(self.payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        )
        return f"{header_b64}.{payload_b64}.{self.signature}"

    @classmethod
    def deserialize(cls, token: str) -> SignedEnvelope:
        """Parse a three-part base64url string back into a SignedEnvelope."""
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError(f"Expected 3 parts, got {len(parts)}")

        header = json.loads(_base64url_decode(parts[0]))
        payload = json.loads(_base64url_decode(parts[1]))
        signature = parts[2]

        return cls(header=header, payload=payload, signature=signature)

    def verify(
        self,
        public_key_b64: str,
        expected_audience: str = "",
        clock_skew: int = 60,
    ) -> tuple[bool, str]:
        """Verify signature, expiry, and audience.

        Returns (success, error_message). error_message is empty on success.
        """
        # Reconstruct signing input
        header_b64 = _base64url_encode(
            json.dumps(self.header, sort_keys=True, ensure_ascii=False).encode("utf-8")
        )
        payload_b64 = _base64url_encode(
            json.dumps(self.payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        )
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

        # Verify signature
        sig_bytes = _base64url_decode(self.signature)
        sig_b64_standard = base64.b64encode(sig_bytes).decode("ascii")

        alg = self.header.get("alg", "Ed25519")
        key_type = "ed25519" if alg == "Ed25519" else "sha256"

        if not UPAIIdentity.verify(
            signing_input, sig_b64_standard, public_key_b64, key_type=key_type
        ):
            return False, "invalid signature"

        # Check expiry
        now = datetime.now(timezone.utc)
        exp_str = self.payload.get("exp", "")
        if exp_str:
            exp = datetime.fromisoformat(exp_str)
            if now.timestamp() > exp.timestamp() + clock_skew:
                return False, "envelope expired"

        # Check iat (not in the future)
        iat_str = self.payload.get("iat", "")
        if iat_str:
            iat = datetime.fromisoformat(iat_str)
            if iat.timestamp() > now.timestamp() + clock_skew:
                return False, "iat is in the future"

        # Check audience
        if expected_audience:
            aud = self.payload.get("aud", "")
            if aud != expected_audience:
                return False, f"audience mismatch: expected {expected_audience!r}, got {aud!r}"

        return True, ""

    def to_dict(self) -> dict:
        return {
            "header": self.header,
            "payload": self.payload,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SignedEnvelope:
        return cls(
            header=d["header"],
            payload=d["payload"],
            signature=d["signature"],
        )
