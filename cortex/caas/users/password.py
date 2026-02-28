"""
Password hashing using Argon2 (preferred) with bcrypt fallback.

Argon2id is memory-hard and resistant to GPU/ASIC attacks.
Falls back to bcrypt if argon2-cffi is not installed.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Protocol

# Try to import argon2, fall back to bcrypt, then to PBKDF2
_HASHER: str = "none"

try:
    from argon2 import PasswordHasher as Argon2Hasher
    from argon2.exceptions import VerifyMismatchError as Argon2MismatchError
    _HASHER = "argon2"
except ImportError:
    try:
        import bcrypt
        _HASHER = "bcrypt"
    except ImportError:
        _HASHER = "pbkdf2"


class PasswordHasher(Protocol):
    """Protocol for password hashers."""

    def hash(self, password: str) -> str:
        """Hash a password, returning a string suitable for storage."""
        ...

    def verify(self, password: str, hash_str: str) -> bool:
        """Verify a password against a stored hash."""
        ...


class Argon2PasswordHasher:
    """Argon2id password hasher (recommended)."""

    def __init__(self) -> None:
        # Use Argon2id with recommended parameters
        # time_cost=3, memory_cost=64MB, parallelism=4
        self._hasher = Argon2Hasher(
            time_cost=3,
            memory_cost=65536,  # 64MB
            parallelism=4,
            hash_len=32,
            salt_len=16,
        )

    def hash(self, password: str) -> str:
        """Hash password using Argon2id."""
        return self._hasher.hash(password)

    def verify(self, password: str, hash_str: str) -> bool:
        """Verify password against Argon2 hash."""
        try:
            self._hasher.verify(hash_str, password)
            return True
        except Argon2MismatchError:
            return False
        except Exception:
            return False

    def needs_rehash(self, hash_str: str) -> bool:
        """Check if hash should be upgraded to current parameters."""
        return self._hasher.check_needs_rehash(hash_str)


class BcryptPasswordHasher:
    """Bcrypt password hasher (fallback)."""

    def __init__(self, rounds: int = 12) -> None:
        import bcrypt
        self._bcrypt = bcrypt
        self._rounds = rounds

    def hash(self, password: str) -> str:
        """Hash password using bcrypt."""
        salt = self._bcrypt.gensalt(rounds=self._rounds)
        return self._bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    def verify(self, password: str, hash_str: str) -> bool:
        """Verify password against bcrypt hash."""
        try:
            return self._bcrypt.checkpw(
                password.encode("utf-8"),
                hash_str.encode("utf-8")
            )
        except Exception:
            return False


class PBKDF2PasswordHasher:
    """PBKDF2-SHA256 password hasher (stdlib fallback)."""

    def __init__(self, iterations: int = 600_000) -> None:
        self._iterations = iterations

    def hash(self, password: str) -> str:
        """Hash password using PBKDF2-SHA256."""
        salt = secrets.token_bytes(16)
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            self._iterations,
            dklen=32
        )
        # Format: pbkdf2:iterations:salt_hex:hash_hex
        return f"pbkdf2:{self._iterations}:{salt.hex()}:{dk.hex()}"

    # Safe bounds for iteration count to prevent DoS
    MIN_ITERATIONS = 10_000
    MAX_ITERATIONS = 10_000_000

    def verify(self, password: str, hash_str: str) -> bool:
        """Verify password against PBKDF2 hash."""
        try:
            parts = hash_str.split(":")
            if len(parts) != 4 or parts[0] != "pbkdf2":
                return False
            iterations = int(parts[1])
            # Reject iteration counts outside safe bounds to prevent DoS
            if iterations < self.MIN_ITERATIONS or iterations > self.MAX_ITERATIONS:
                return False
            salt = bytes.fromhex(parts[2])
            stored_hash = bytes.fromhex(parts[3])
            dk = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt,
                iterations,
                dklen=32
            )
            return hmac.compare_digest(dk, stored_hash)
        except Exception:
            return False


def get_password_hasher() -> PasswordHasher:
    """Get the best available password hasher."""
    if _HASHER == "argon2":
        return Argon2PasswordHasher()
    elif _HASHER == "bcrypt":
        return BcryptPasswordHasher()
    else:
        return PBKDF2PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password using the best available hasher."""
    return get_password_hasher().hash(password)


def verify_password(password: str, hash_str: str) -> bool:
    """Verify a password against any supported hash format."""
    # Detect hash format and use appropriate verifier
    if hash_str.startswith("$argon2"):
        if _HASHER == "argon2":
            return Argon2PasswordHasher().verify(password, hash_str)
        return False  # Can't verify argon2 without the library
    elif hash_str.startswith("$2"):  # bcrypt
        if _HASHER in ("argon2", "bcrypt"):
            try:
                return BcryptPasswordHasher().verify(password, hash_str)
            except ImportError:
                return False
        return False
    elif hash_str.startswith("pbkdf2:"):
        return PBKDF2PasswordHasher().verify(password, hash_str)
    else:
        # Unknown format
        return False


def get_hasher_info() -> dict:
    """Return information about the active password hasher."""
    return {
        "hasher": _HASHER,
        "available": _HASHER != "none",
        "recommended": _HASHER == "argon2",
    }
