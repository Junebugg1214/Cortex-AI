"""Tests for cortex.caas.encryption — Field encryption at rest."""

from __future__ import annotations

import hashlib
import hmac as _hmac
import os

import pytest

from cortex.caas.encryption import (
    FieldEncryptor,
    _PREFIX,
    _PREFIX_V1,
    _PREFIX_V2,
    _ITERATIONS_V1,
    _generate_keystream_v1,
    _xor_bytes,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_encryptor() -> FieldEncryptor:
    return FieldEncryptor(master_key=os.urandom(32))


def _encrypt_v1(master_key: bytes, plaintext: str) -> str:
    """Produce a v1-format encrypted token (for backward compat tests)."""
    salt = os.urandom(16)
    field_key = hashlib.pbkdf2_hmac("sha256", master_key, salt, _ITERATIONS_V1)
    plaintext_bytes = plaintext.encode("utf-8")
    keystream = _generate_keystream_v1(field_key, len(plaintext_bytes))
    ciphertext = _xor_bytes(plaintext_bytes, keystream)
    mac = _hmac.new(field_key, ciphertext, hashlib.sha256).digest()
    return f"{_PREFIX_V1}{salt.hex()}:{ciphertext.hex()}:{mac.hex()}"


# ---------------------------------------------------------------------------
# TestFieldEncryptor — v2 (current)
# ---------------------------------------------------------------------------

class TestFieldEncryptor:
    def test_encrypt_decrypt_roundtrip(self):
        enc = _make_encryptor()
        plaintext = "super-secret-token-string"
        encrypted = enc.encrypt(plaintext)
        decrypted = enc.decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_produces_v2_prefix(self):
        enc = _make_encryptor()
        encrypted = enc.encrypt("hello")
        assert encrypted.startswith(_PREFIX_V2)

    def test_encrypted_v2_format(self):
        enc = _make_encryptor()
        encrypted = enc.encrypt("test")
        parts = encrypted[len(_PREFIX_V2):].split(":")
        assert len(parts) == 4  # salt:iterations:ciphertext:mac
        bytes.fromhex(parts[0])  # salt is hex
        int(parts[1])            # iterations is int
        bytes.fromhex(parts[2])  # ciphertext is hex
        bytes.fromhex(parts[3])  # mac is hex

    def test_is_encrypted(self):
        enc = _make_encryptor()
        assert enc.is_encrypted("enc:v2:aabb:600000:ccdd:eeff")
        assert enc.is_encrypted("enc:v1:aabb:ccdd:eeff")
        assert not enc.is_encrypted("plain-text")
        assert not enc.is_encrypted("")

    def test_different_encryptions_produce_different_output(self):
        enc = _make_encryptor()
        e1 = enc.encrypt("same-input")
        e2 = enc.encrypt("same-input")
        # Different random salts → different ciphertexts
        assert e1 != e2
        # But both decrypt to the same value
        assert enc.decrypt(e1) == "same-input"
        assert enc.decrypt(e2) == "same-input"

    def test_tampered_ciphertext_rejected(self):
        enc = _make_encryptor()
        encrypted = enc.encrypt("secret")
        parts = encrypted[len(_PREFIX_V2):].split(":")
        # Tamper with ciphertext (index 2)
        tampered_ct = "ff" * (len(parts[2]) // 2)
        tampered = f"{_PREFIX_V2}{parts[0]}:{parts[1]}:{tampered_ct}:{parts[3]}"
        with pytest.raises(ValueError, match="HMAC mismatch"):
            enc.decrypt(tampered)

    def test_tampered_mac_rejected(self):
        enc = _make_encryptor()
        encrypted = enc.encrypt("secret")
        parts = encrypted[len(_PREFIX_V2):].split(":")
        tampered = f"{_PREFIX_V2}{parts[0]}:{parts[1]}:{parts[2]}:{'00' * 32}"
        with pytest.raises(ValueError, match="HMAC mismatch"):
            enc.decrypt(tampered)

    def test_tampered_salt_rejected(self):
        enc = _make_encryptor()
        encrypted = enc.encrypt("secret")
        parts = encrypted[len(_PREFIX_V2):].split(":")
        tampered = f"{_PREFIX_V2}{'00' * 16}:{parts[1]}:{parts[2]}:{parts[3]}"
        with pytest.raises(ValueError, match="HMAC mismatch"):
            enc.decrypt(tampered)

    def test_wrong_key_rejected(self):
        enc1 = FieldEncryptor(master_key=os.urandom(32))
        enc2 = FieldEncryptor(master_key=os.urandom(32))
        encrypted = enc1.encrypt("secret")
        with pytest.raises(ValueError, match="HMAC mismatch"):
            enc2.decrypt(encrypted)

    def test_non_encrypted_raises(self):
        enc = _make_encryptor()
        with pytest.raises(ValueError, match="Not an encrypted"):
            enc.decrypt("plain-text")

    def test_malformed_token_raises(self):
        enc = _make_encryptor()
        with pytest.raises(ValueError):
            enc.decrypt("enc:v2:only-one-part")

    def test_empty_plaintext(self):
        enc = _make_encryptor()
        encrypted = enc.encrypt("")
        assert enc.decrypt(encrypted) == ""

    def test_long_plaintext(self):
        enc = _make_encryptor()
        plaintext = "x" * 10000
        encrypted = enc.encrypt(plaintext)
        assert enc.decrypt(encrypted) == plaintext

    def test_unicode_plaintext(self):
        enc = _make_encryptor()
        plaintext = "Hello, 世界! 🌍"
        encrypted = enc.encrypt(plaintext)
        assert enc.decrypt(encrypted) == plaintext

    def test_short_master_key_rejected(self):
        with pytest.raises(ValueError, match="at least 16 bytes"):
            FieldEncryptor(master_key=b"short")


# ---------------------------------------------------------------------------
# TestV1BackwardCompat
# ---------------------------------------------------------------------------

class TestV1BackwardCompat:
    """Verify that v1-encrypted data can still be decrypted."""

    def test_decrypt_v1_token(self):
        key = os.urandom(32)
        enc = FieldEncryptor(master_key=key)
        v1_token = _encrypt_v1(key, "legacy-secret")
        assert v1_token.startswith(_PREFIX_V1)
        decrypted = enc.decrypt(v1_token)
        assert decrypted == "legacy-secret"

    def test_v1_unicode(self):
        key = os.urandom(32)
        enc = FieldEncryptor(master_key=key)
        v1_token = _encrypt_v1(key, "Hello, 世界!")
        assert enc.decrypt(v1_token) == "Hello, 世界!"

    def test_v1_tampered_rejected(self):
        key = os.urandom(32)
        enc = FieldEncryptor(master_key=key)
        v1_token = _encrypt_v1(key, "secret")
        parts = v1_token[len(_PREFIX_V1):].split(":")
        tampered = f"{_PREFIX_V1}{parts[0]}:{'ff' * (len(parts[1]) // 2)}:{parts[2]}"
        with pytest.raises(ValueError, match="HMAC mismatch"):
            enc.decrypt(tampered)

    def test_cross_version_not_interchangeable(self):
        """v1 and v2 use different keystreams — same key produces different ciphertexts."""
        key = os.urandom(32)
        enc = FieldEncryptor(master_key=key)
        v1_token = _encrypt_v1(key, "test")
        v2_token = enc.encrypt("test")
        assert v1_token.startswith(_PREFIX_V1)
        assert v2_token.startswith(_PREFIX_V2)
        # Both should decrypt correctly
        assert enc.decrypt(v1_token) == "test"
        assert enc.decrypt(v2_token) == "test"


# ---------------------------------------------------------------------------
# TestFromIdentityKey
# ---------------------------------------------------------------------------

class TestFromIdentityKey:
    def test_from_identity_key(self):
        pk = os.urandom(32)
        enc = FieldEncryptor.from_identity_key(pk)
        encrypted = enc.encrypt("test")
        assert enc.decrypt(encrypted) == "test"

    def test_deterministic_derivation(self):
        pk = os.urandom(32)
        enc1 = FieldEncryptor.from_identity_key(pk)
        enc2 = FieldEncryptor.from_identity_key(pk)
        # Same key should decrypt each other's output
        encrypted = enc1.encrypt("hello")
        assert enc2.decrypt(encrypted) == "hello"

    def test_different_keys_incompatible(self):
        enc1 = FieldEncryptor.from_identity_key(os.urandom(32))
        enc2 = FieldEncryptor.from_identity_key(os.urandom(32))
        encrypted = enc1.encrypt("hello")
        with pytest.raises(ValueError):
            enc2.decrypt(encrypted)


# ---------------------------------------------------------------------------
# TestSqliteStoreIntegration
# ---------------------------------------------------------------------------

class TestSqliteStoreIntegration:
    def test_encrypted_grant_storage(self, tmp_path):
        from cortex.caas.sqlite_store import SqliteGrantStore
        pk = os.urandom(32)
        enc = FieldEncryptor.from_identity_key(pk)
        store = SqliteGrantStore(str(tmp_path / "test.db"), encryptor=enc)

        token_str = "eyJhbGciOiJFZDI1NTE5In0.payload.signature"
        store.add("grant-001", token_str, {
            "audience": "test",
            "policy": "professional",
            "issued_at": "2026-01-01T00:00:00Z",
        })

        # Verify raw value in DB is encrypted
        row = store._conn.execute(
            "SELECT token_str FROM grants WHERE grant_id = 'grant-001'"
        ).fetchone()
        raw = row["token_str"]
        assert raw.startswith(_PREFIX_V2)
        assert raw != token_str

        # Verify retrieval decrypts
        result = store.get("grant-001")
        assert result["token_str"] == token_str
        store.close()

    def test_backward_compat_plaintext_read(self, tmp_path):
        """Pre-encryption data (without prefix) is returned as-is."""
        from cortex.caas.sqlite_store import SqliteGrantStore
        pk = os.urandom(32)
        enc = FieldEncryptor.from_identity_key(pk)

        # Create store WITHOUT encryption, add a grant
        store1 = SqliteGrantStore(str(tmp_path / "test.db"))
        store1.add("grant-plain", "plaintext-token", {"audience": "x", "policy": "y", "issued_at": ""})
        store1.close()

        # Open with encryption — should still read plaintext grant
        store2 = SqliteGrantStore(str(tmp_path / "test.db"), encryptor=enc)
        result = store2.get("grant-plain")
        assert result["token_str"] == "plaintext-token"
        store2.close()

    def test_no_encryptor_stores_plaintext(self, tmp_path):
        from cortex.caas.sqlite_store import SqliteGrantStore
        store = SqliteGrantStore(str(tmp_path / "test.db"))
        store.add("grant-002", "my-token", {"audience": "a", "policy": "b", "issued_at": ""})
        row = store._conn.execute(
            "SELECT token_str FROM grants WHERE grant_id = 'grant-002'"
        ).fetchone()
        assert row["token_str"] == "my-token"
        store.close()
