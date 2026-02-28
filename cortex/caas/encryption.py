"""
CaaS Field Encryption — Encrypt sensitive fields at rest.

Reuses the keystream cipher pattern from cortex.upai.backup:
- PBKDF2-HMAC-SHA256 for key derivation
- HMAC-SHA256 counter-mode keystream XOR for encryption (v2)
- HMAC-SHA256 for integrity

Format v2: ``enc:v2:<salt_hex>:<iterations>:<ciphertext_hex>:<mac_hex>``
Format v1 (legacy): ``enc:v1:<salt_hex>:<ciphertext_hex>:<mac_hex>``
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import os

# ---------------------------------------------------------------------------
# Keystream ciphers
# ---------------------------------------------------------------------------

def _generate_keystream_v1(key: bytes, length: int) -> bytes:
    """Legacy v1: deterministic keystream by repeated SHA-256 hashing."""
    stream = bytearray()
    block = key
    while len(stream) < length:
        block = hashlib.sha256(block).digest()
        stream.extend(block)
    return bytes(stream[:length])


def _generate_keystream(key: bytes, length: int) -> bytes:
    """HMAC-SHA256 counter-mode keystream (v2)."""
    stream = bytearray()
    counter = 0
    while len(stream) < length:
        block = _hmac.new(key, counter.to_bytes(4, "big"), hashlib.sha256).digest()
        stream.extend(block)
        counter += 1
    return bytes(stream[:length])


def _xor_bytes(data: bytes, keystream: bytes) -> bytes:
    """XOR data with keystream."""
    return bytes(a ^ b for a, b in zip(data, keystream))


# ---------------------------------------------------------------------------
# FieldEncryptor
# ---------------------------------------------------------------------------

_PREFIX_V1 = "enc:v1:"
_PREFIX_V2 = "enc:v2:"
_PREFIX = _PREFIX_V2  # current version for new encryptions
_ITERATIONS_V1 = 10_000
_ITERATIONS = 600_000
_SALT_SIZE = 16
# Safe bounds for iteration count to prevent DoS via CPU exhaustion
_MIN_ITERATIONS = 10_000
_MAX_ITERATIONS = 10_000_000


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
        """Encrypt a plaintext string. Returns ``enc:v2:<salt>:<iterations>:<ct>:<mac>``."""
        salt = os.urandom(_SALT_SIZE)
        field_key = hashlib.pbkdf2_hmac(
            "sha256", self._master_key, salt, _ITERATIONS
        )
        plaintext_bytes = plaintext.encode("utf-8")
        keystream = _generate_keystream(field_key, len(plaintext_bytes))
        ciphertext = _xor_bytes(plaintext_bytes, keystream)
        mac = _hmac.new(field_key, ciphertext, hashlib.sha256).digest()
        return f"{_PREFIX_V2}{salt.hex()}:{_ITERATIONS}:{ciphertext.hex()}:{mac.hex()}"

    def decrypt(self, token: str) -> str:
        """Decrypt an encrypted token. Raises ValueError on integrity failure."""
        if token.startswith(_PREFIX_V2):
            return self._decrypt_v2(token)
        if token.startswith(_PREFIX_V1):
            return self._decrypt_v1(token)
        raise ValueError("Not an encrypted token")

    def _decrypt_v2(self, token: str) -> str:
        """Decrypt v2 format: enc:v2:<salt>:<iterations>:<ct>:<mac>."""
        rest = token[len(_PREFIX_V2):]
        parts = rest.split(":")
        if len(parts) != 4:
            raise ValueError("Malformed encrypted token (v2)")
        salt_hex, iter_str, ct_hex, mac_hex = parts
        try:
            salt = bytes.fromhex(salt_hex)
            iterations = int(iter_str)
            # Reject iteration counts outside safe bounds to prevent DoS
            if iterations < _MIN_ITERATIONS or iterations > _MAX_ITERATIONS:
                raise ValueError("Iteration count out of safe bounds")
            ciphertext = bytes.fromhex(ct_hex)
            stored_mac = bytes.fromhex(mac_hex)
        except ValueError:
            raise ValueError("Malformed hex/int in encrypted token")
        field_key = hashlib.pbkdf2_hmac(
            "sha256", self._master_key, salt, iterations
        )
        computed_mac = _hmac.new(field_key, ciphertext, hashlib.sha256).digest()
        if not _hmac.compare_digest(stored_mac, computed_mac):
            raise ValueError("Integrity check failed: HMAC mismatch")
        keystream = _generate_keystream(field_key, len(ciphertext))
        plaintext_bytes = _xor_bytes(ciphertext, keystream)
        return plaintext_bytes.decode("utf-8")

    def _decrypt_v1(self, token: str) -> str:
        """Decrypt legacy v1 format: enc:v1:<salt>:<ct>:<mac>."""
        rest = token[len(_PREFIX_V1):]
        parts = rest.split(":")
        if len(parts) != 3:
            raise ValueError("Malformed encrypted token (v1)")
        salt_hex, ct_hex, mac_hex = parts
        try:
            salt = bytes.fromhex(salt_hex)
            ciphertext = bytes.fromhex(ct_hex)
            stored_mac = bytes.fromhex(mac_hex)
        except ValueError:
            raise ValueError("Malformed hex in encrypted token")
        field_key = hashlib.pbkdf2_hmac(
            "sha256", self._master_key, salt, _ITERATIONS_V1
        )
        computed_mac = _hmac.new(field_key, ciphertext, hashlib.sha256).digest()
        if not _hmac.compare_digest(stored_mac, computed_mac):
            raise ValueError("Integrity check failed: HMAC mismatch")
        keystream = _generate_keystream_v1(field_key, len(ciphertext))
        plaintext_bytes = _xor_bytes(ciphertext, keystream)
        return plaintext_bytes.decode("utf-8")

    @staticmethod
    def is_encrypted(value: str) -> bool:
        """Check if a value has an encrypted prefix."""
        return value.startswith(_PREFIX_V1) or value.startswith(_PREFIX_V2)
