"""
Tests for did:key support and base58btc encoding.

Covers:
- Base58btc encode/decode round-trip
- did:key ↔ public key round-trip
- Legacy identity loading still works
- DID Document compliance for did:key
- migrate_did() from legacy format
- alsoKnownAs in DID Document
"""

import base64
import tempfile
from pathlib import Path

from cortex.upai.identity import (
    UPAIIdentity, has_crypto,
    _base58btc_encode, _base58btc_decode,
    _base64url_encode, _base64url_decode,
    _public_key_to_did_key, _did_key_to_public_key,
    _ED25519_MULTICODEC_PREFIX, _HAS_CRYPTO,
)


# ============================================================================
# Base58btc
# ============================================================================

class TestBase58btc:

    def test_encode_decode_roundtrip(self):
        data = b"Hello, World!"
        encoded = _base58btc_encode(data)
        decoded = _base58btc_decode(encoded)
        assert decoded == data

    def test_encode_empty(self):
        assert _base58btc_encode(b"") == ""

    def test_decode_empty(self):
        assert _base58btc_decode("") == b""

    def test_leading_zeros_preserved(self):
        data = b"\x00\x00\x01\x02"
        encoded = _base58btc_encode(data)
        assert encoded.startswith("11")  # two leading '1's for two zero bytes
        decoded = _base58btc_decode(encoded)
        assert decoded == data

    def test_known_vector(self):
        # Bitcoin's base58 encoding of "Hello World" is well-known
        data = b"Hello World"
        encoded = _base58btc_encode(data)
        decoded = _base58btc_decode(encoded)
        assert decoded == data
        # Verify it only contains valid base58 chars
        valid = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        assert all(c in valid for c in encoded)

    def test_single_byte(self):
        for i in range(256):
            data = bytes([i])
            encoded = _base58btc_encode(data)
            decoded = _base58btc_decode(encoded)
            assert decoded == data

    def test_32_byte_key(self):
        """Ed25519 public keys are 32 bytes."""
        import os
        data = os.urandom(32)
        encoded = _base58btc_encode(data)
        decoded = _base58btc_decode(encoded)
        assert decoded == data


# ============================================================================
# Base64url
# ============================================================================

class TestBase64url:

    def test_encode_decode_roundtrip(self):
        data = b"test data with + and / chars"
        encoded = _base64url_encode(data)
        decoded = _base64url_decode(encoded)
        assert decoded == data

    def test_no_padding(self):
        encoded = _base64url_encode(b"test")
        assert "=" not in encoded

    def test_url_safe_chars(self):
        """Should use - and _ instead of + and /."""
        data = b"\xff\xfe\xfd"  # bytes that produce +/ in standard base64
        encoded = _base64url_encode(data)
        assert "+" not in encoded
        assert "/" not in encoded


# ============================================================================
# DID:key
# ============================================================================

class TestDidKey:

    def test_public_key_to_did_key_format(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        assert identity.did.startswith("did:key:z6Mk")

    def test_did_key_roundtrip(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        pub_bytes = base64.b64decode(identity.public_key_b64)
        did = _public_key_to_did_key(pub_bytes)
        recovered = _did_key_to_public_key(did)
        assert recovered == pub_bytes

    def test_multicodec_prefix_present(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        pub_bytes = base64.b64decode(identity.public_key_b64)
        did = _public_key_to_did_key(pub_bytes)
        # Decode back and check prefix
        multibase_value = did[len("did:key:z"):]
        decoded = _base58btc_decode(multibase_value)
        assert decoded[:2] == _ED25519_MULTICODEC_PREFIX

    def test_did_key_to_public_key_wrong_prefix(self):
        import pytest
        with pytest.raises(ValueError, match="Not a did:key"):
            _did_key_to_public_key("did:upai:ed25519:abc")

    def test_did_key_to_public_key_wrong_multicodec(self):
        import pytest
        # Encode with wrong multicodec prefix
        fake = b"\x00\x01" + b"\x00" * 32
        fake_did = "did:key:z" + _base58btc_encode(fake)
        with pytest.raises(ValueError, match="wrong multicodec"):
            _did_key_to_public_key(fake_did)

    def test_key_type_property(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        assert identity._key_type == "ed25519"

    def test_key_type_hmac(self):
        import cortex.upai.identity as id_mod
        orig = id_mod._HAS_CRYPTO
        id_mod._HAS_CRYPTO = False
        try:
            identity = UPAIIdentity.generate("Test")
            assert identity._key_type == "sha256"
        finally:
            id_mod._HAS_CRYPTO = orig

    def test_key_type_legacy_ed25519(self):
        """Legacy did:upai:ed25519:... should still be recognized as ed25519."""
        identity = UPAIIdentity(
            did="did:upai:ed25519:abcdef1234567890",
            name="Legacy",
            public_key_b64="dGVzdA==",
            created_at="2024-01-01T00:00:00+00:00",
        )
        assert identity._key_type == "ed25519"


# ============================================================================
# Legacy identity loading
# ============================================================================

class TestLegacyIdentity:

    def test_load_legacy_did_format(self):
        """Identities saved with old did:upai:ed25519:... format should load fine."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store_dir = Path(tmpdir) / ".cortex"
            store_dir.mkdir(parents=True)

            import json
            pub = {
                "did": "did:upai:ed25519:abcdef1234567890abcdef1234567890",
                "name": "Legacy User",
                "public_key_b64": "dGVzdHB1YmtleQ==",
                "created_at": "2024-01-01T00:00:00+00:00",
            }
            (store_dir / "identity.json").write_text(json.dumps(pub))

            loaded = UPAIIdentity.load(store_dir)
            assert loaded.did == pub["did"]
            assert loaded.name == pub["name"]
            assert loaded._key_type == "ed25519"


# ============================================================================
# DID Document compliance
# ============================================================================

class TestDidDocumentCompliance:

    def test_did_key_uses_multibase(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        doc = identity.to_did_document()
        vm = doc["verificationMethod"][0]
        assert "publicKeyMultibase" in vm
        assert vm["publicKeyMultibase"].startswith("z")
        assert "publicKeyBase64" not in vm

    def test_legacy_uses_base64(self):
        identity = UPAIIdentity(
            did="did:upai:ed25519:abcdef1234567890",
            name="Legacy",
            public_key_b64="dGVzdA==",
            created_at="2024-01-01T00:00:00+00:00",
        )
        doc = identity.to_did_document()
        vm = doc["verificationMethod"][0]
        assert "publicKeyBase64" in vm
        assert "publicKeyMultibase" not in vm

    def test_also_known_as_present(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        doc = identity.to_did_document()
        assert "alsoKnownAs" in doc
        assert len(doc["alsoKnownAs"]) == 1
        assert doc["alsoKnownAs"][0].startswith("did:upai:ed25519:")

    def test_service_endpoints(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        services = [
            {"id": f"{identity.did}#caas", "type": "ContextService", "serviceEndpoint": "http://localhost:8421"}
        ]
        doc = identity.to_did_document(service_endpoints=services)
        assert "service" in doc
        assert len(doc["service"]) == 1
        assert doc["service"][0]["type"] == "ContextService"

    def test_no_service_by_default(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        doc = identity.to_did_document()
        assert "service" not in doc

    def test_w3c_required_fields(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        doc = identity.to_did_document()
        assert "@context" in doc
        assert doc["@context"] == "https://www.w3.org/ns/did/v1"
        assert "id" in doc
        assert "controller" in doc
        assert "verificationMethod" in doc
        assert "authentication" in doc


# ============================================================================
# migrate_did
# ============================================================================

class TestMigrateDid:

    def test_migrate_produces_did_key(self):
        if not has_crypto():
            return
        identity = UPAIIdentity.generate("Test")
        # Create a "legacy" identity with same key material
        import hashlib
        pub_bytes = base64.b64decode(identity.public_key_b64)
        fingerprint = hashlib.sha256(pub_bytes).hexdigest()[:32]
        legacy = UPAIIdentity(
            did=f"did:upai:ed25519:{fingerprint}",
            name="Legacy",
            public_key_b64=identity.public_key_b64,
            created_at=identity.created_at,
            _private_key=identity._private_key,
        )
        new_did = legacy.migrate_did()
        assert new_did.startswith("did:key:z6Mk")
        assert new_did == identity.did

    def test_migrate_hmac_raises(self):
        import cortex.upai.identity as id_mod
        import pytest
        orig = id_mod._HAS_CRYPTO
        id_mod._HAS_CRYPTO = False
        try:
            identity = UPAIIdentity.generate("HMAC")
            with pytest.raises(ValueError, match="Cannot migrate"):
                identity.migrate_did()
        finally:
            id_mod._HAS_CRYPTO = orig
