"""
CaaS Field Encryption — Encrypt sensitive fields at rest.

Reuses the keystream cipher pattern from cortex.upai.backup:
- PBKDF2-HMAC-SHA256 for key derivation
- SHA-256 keystream XOR for encryption
- HMAC-SHA256 for integrity

Format: ``enc:v1:<salt_hex>:<ciphertext_hex>:<mac_hex>``
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import os


# ---------------------------------------------------------------------------
# Keystream cipher (same as backup.py)
# ---------------------------------------------------------------------------

def _generate_keystream(key: bytes, length: int) -> bytes:
    """Generate a deterministic keystream by repeated SHA-256 hashing."""
    stream = bytearray()
    block = key
    while len(stream) < length:
        block = hashlib.sha256(block).digest()
        stream.extend(block)
    return bytes(stream[:length])


def _xor_bytes(data: bytes, keystream: bytes) -> bytes:
    """XOR data with keystream."""
    return bytes(a ^ b for a, b in zip(data, keystream))


# ---------------------------------------------------------------------------
# FieldEncryptor
# ---------------------------------------------------------------------------

_PREFIX = "enc:v1:"
_ITERATIONS = 10_000
_SALT_SIZE = 16


class FieldEncryptor:
    """Encrypts and decrypts individual field values using a master key.

    The master key is derived from the identity private key:
        master_key = HMAC-SHA256(private_key, b"cortex-field-encryption")

    Each encrypted value uses a random salt for per-field key derivation.
    """

    def __init__(self, master_key: bytes) -> None:
        if len(master_key) < 16:
            raise ValueError("Master key must be at least 16 bytes")
        self._master_key = master_key

    @classmethod
    def from_identity_key(cls, private_key: bytes) -> FieldEncryptor:
        """Derive a FieldEncryptor from an identity private key."""
        master = _hmac.new(private_key, b"cortex-field-encryption", hashlib.sha256).digest()
        return cls(master)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string. Returns ``enc:v1:<salt>:<ct>:<mac>``."""
        salt = os.urandom(_SALT_SIZE)
        field_key = hashlib.pbkdf2_hmac(
            "sha256", self._master_key, salt, _ITERATIONS
        )
        plaintext_bytes = plaintext.encode("utf-8")
        keystream = _generate_keystream(field_key, len(plaintext_bytes))
        ciphertext = _xor_bytes(plaintext_bytes, keystream)
        mac = _hmac.new(field_key, ciphertext, hashlib.sha256).digest()
        return f"{_PREFIX}{salt.hex()}:{ciphertext.hex()}:{mac.hex()}"

    def decrypt(self, token: str) -> str:
        """Decrypt an encrypted token. Raises ValueError on integrity failure."""
        if not self.is_encrypted(token):
            raise ValueError("Not an encrypted token")
        rest = token[len(_PREFIX):]
        parts = rest.split(":")
        if len(parts) != 3:
            raise ValueError("Malformed encrypted token")
        salt_hex, ct_hex, mac_hex = parts
        try:
            salt = bytes.fromhex(salt_hex)
            ciphertext = bytes.fromhex(ct_hex)
            stored_mac = bytes.fromhex(mac_hex)
        except ValueError:
            raise ValueError("Malformed hex in encrypted token")
        field_key = hashlib.pbkdf2_hmac(
            "sha256", self._master_key, salt, _ITERATIONS
        )
        # Verify integrity
        computed_mac = _hmac.new(field_key, ciphertext, hashlib.sha256).digest()
        if not _hmac.compare_digest(stored_mac, computed_mac):
            raise ValueError("Integrity check failed: HMAC mismatch")
        keystream = _generate_keystream(field_key, len(ciphertext))
        plaintext_bytes = _xor_bytes(ciphertext, keystream)
        return plaintext_bytes.decode("utf-8")

    @staticmethod
    def is_encrypted(value: str) -> bool:
        """Check if a value has the encrypted prefix."""
        return value.startswith(_PREFIX)
