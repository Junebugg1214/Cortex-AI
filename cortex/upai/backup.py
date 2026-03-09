"""
UPAI Key Backup — Encrypted backup and recovery of identity keys.

Encryption scheme (stdlib-only):
1. Key derivation: PBKDF2-HMAC-SHA256(passphrase, salt, 600k iterations) -> 32-byte key
2. Encryption: XOR with HMAC-SHA256 counter-mode keystream (v2)
3. Integrity: HMAC-SHA256(derived_key, ciphertext)

Also provides recovery phrase generation using a deterministic wordlist.
"""

from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import json
import os
import secrets

from cortex.upai.identity import UPAIIdentity

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
# KeyBackup — encrypted backup and restore
# ---------------------------------------------------------------------------


class KeyBackup:
    """Encrypted identity key backup using PBKDF2 + HMAC-CTR stream cipher + HMAC."""

    DEFAULT_ITERATIONS = 600_000
    _ITERATIONS_V1 = 100_000

    def backup(self, identity: UPAIIdentity, passphrase: str) -> bytes:
        """Encrypt identity private key and return JSON backup blob.

        Args:
            identity: Identity to back up (must have private key).
            passphrase: Passphrase for encryption.

        Returns:
            JSON bytes containing the encrypted backup.
        """
        if identity._private_key is None:
            raise ValueError("Identity must have a private key to back up")

        salt = os.urandom(32)
        iterations = self.DEFAULT_ITERATIONS

        # Derive key
        derived_key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iterations)

        # Encrypt private key
        plaintext = identity._private_key
        keystream = _generate_keystream(derived_key, len(plaintext))
        ciphertext = _xor_bytes(plaintext, keystream)

        # HMAC for integrity
        mac = _hmac.new(derived_key, ciphertext, hashlib.sha256).digest()

        backup_data = {
            "version": 2,
            "salt": base64.b64encode(salt).decode("ascii"),
            "iterations": iterations,
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "hmac": base64.b64encode(mac).decode("ascii"),
            "did": identity.did,
            "name": identity.name,
            "public_key_b64": identity.public_key_b64,
        }

        return json.dumps(backup_data, indent=2).encode("utf-8")

    def restore(self, backup_bytes: bytes, passphrase: str) -> UPAIIdentity:
        """Decrypt backup and restore identity.

        Args:
            backup_bytes: JSON backup blob from backup().
            passphrase: Passphrase used during backup.

        Returns:
            Restored UPAIIdentity.

        Raises:
            ValueError: If passphrase is wrong (HMAC mismatch) or backup is invalid.
        """
        try:
            data = json.loads(backup_bytes)
        except json.JSONDecodeError:
            raise ValueError("Invalid backup format: not valid JSON")

        version = data.get("version", 0)
        if version not in (1, 2):
            raise ValueError(f"Unsupported backup version: {version}")

        # Validate required keys
        required_keys = ["salt", "iterations", "ciphertext", "hmac", "did", "name", "public_key_b64"]
        missing = [k for k in required_keys if k not in data]
        if missing:
            raise ValueError(f"Invalid backup: missing required fields: {', '.join(missing)}")

        try:
            salt = base64.b64decode(data["salt"])
            ciphertext = base64.b64decode(data["ciphertext"])
            stored_mac = base64.b64decode(data["hmac"])
        except Exception as e:
            raise ValueError(f"Invalid backup: malformed base64 data: {e}") from e

        iterations = data["iterations"]
        if not isinstance(iterations, int) or iterations <= 0:
            raise ValueError("Invalid backup: iterations must be a positive integer")

        # Derive key
        derived_key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iterations)

        # Verify HMAC
        computed_mac = _hmac.new(derived_key, ciphertext, hashlib.sha256).digest()
        if not _hmac.compare_digest(stored_mac, computed_mac):
            raise ValueError("Wrong passphrase (HMAC verification failed)")

        # Decrypt — select keystream based on version
        if version == 1:
            keystream = _generate_keystream_v1(derived_key, len(ciphertext))
        else:
            keystream = _generate_keystream(derived_key, len(ciphertext))
        private_key = _xor_bytes(ciphertext, keystream)

        return UPAIIdentity(
            did=data["did"],
            name=data["name"],
            public_key_b64=data["public_key_b64"],
            created_at="",  # Not stored in backup; restored identity is usable
            _private_key=private_key,
        )


# ---------------------------------------------------------------------------
# Recovery phrase generation
# ---------------------------------------------------------------------------

# Deterministic wordlist: 256 common English words derived from categories.
# Each word is unique and easily distinguishable.
_WORDLIST = [
    "abandon",
    "ability",
    "able",
    "about",
    "above",
    "absent",
    "absorb",
    "abstract",
    "absurd",
    "abuse",
    "access",
    "acid",
    "acoustic",
    "acquire",
    "across",
    "act",
    "action",
    "actor",
    "actual",
    "adapt",
    "add",
    "addict",
    "address",
    "adjust",
    "admit",
    "adult",
    "advance",
    "advice",
    "aerobic",
    "affair",
    "afford",
    "afraid",
    "again",
    "age",
    "agent",
    "agree",
    "ahead",
    "aim",
    "air",
    "airport",
    "aisle",
    "alarm",
    "album",
    "alert",
    "alien",
    "all",
    "alley",
    "allow",
    "almost",
    "alone",
    "alpha",
    "already",
    "also",
    "alter",
    "always",
    "amateur",
    "amazing",
    "among",
    "amount",
    "amused",
    "analyst",
    "anchor",
    "ancient",
    "anger",
    "angle",
    "angry",
    "animal",
    "ankle",
    "announce",
    "annual",
    "another",
    "answer",
    "antenna",
    "antique",
    "anxiety",
    "any",
    "apart",
    "apology",
    "appear",
    "apple",
    "approve",
    "april",
    "arch",
    "arctic",
    "area",
    "arena",
    "argue",
    "arm",
    "armor",
    "army",
    "arrange",
    "arrest",
    "arrive",
    "arrow",
    "art",
    "artefact",
    "artist",
    "artwork",
    "ask",
    "aspect",
    "assault",
    "asset",
    "assist",
    "assume",
    "asthma",
    "athlete",
    "atom",
    "attack",
    "attend",
    "attitude",
    "attract",
    "auction",
    "audit",
    "august",
    "aunt",
    "author",
    "auto",
    "autumn",
    "average",
    "avocado",
    "avoid",
    "awake",
    "aware",
    "awesome",
    "awful",
    "awkward",
    "axis",
    "baby",
    "bachelor",
    "bacon",
    "badge",
    "bag",
    "balance",
    "balcony",
    "ball",
    "bamboo",
    "banana",
    "banner",
    "bar",
    "barely",
    "bargain",
    "barrel",
    "base",
    "basic",
    "basket",
    "battle",
    "beach",
    "bean",
    "beauty",
    "become",
    "beef",
    "before",
    "begin",
    "behave",
    "behind",
    "believe",
    "below",
    "belt",
    "bench",
    "benefit",
    "best",
    "betray",
    "better",
    "between",
    "beyond",
    "bicycle",
    "bid",
    "bike",
    "bind",
    "biology",
    "bird",
    "birth",
    "bitter",
    "black",
    "blade",
    "blame",
    "blanket",
    "blast",
    "bleak",
    "bless",
    "blind",
    "blood",
    "blossom",
    "blow",
    "blue",
    "blur",
    "blush",
    "board",
    "boat",
    "body",
    "boil",
    "bomb",
    "bone",
    "bonus",
    "book",
    "boost",
    "border",
    "boring",
    "borrow",
    "boss",
    "bottom",
    "bounce",
    "box",
    "boy",
    "bracket",
    "brain",
    "brand",
    "brave",
    "bread",
    "breeze",
    "brick",
    "bridge",
    "brief",
    "bright",
    "bring",
    "brisk",
    "broad",
    "broken",
    "bronze",
    "broom",
    "brother",
    "brown",
    "brush",
    "bubble",
    "buddy",
    "budget",
    "buffalo",
    "build",
    "bulb",
    "bulk",
    "bullet",
    "bundle",
    "burden",
    "burger",
    "burst",
    "bus",
    "business",
    "busy",
    "butter",
    "buyer",
    "cabin",
    "cable",
    "cactus",
    "cage",
    "cake",
    "call",
    "calm",
    "camera",
    "camp",
    "canal",
    "cancel",
    "candy",
    "cannon",
    "canoe",
    "canvas",
    "canyon",
]

_WORDLIST_SIZE = len(_WORDLIST)  # 256


class RecoveryCodeGenerator:
    """Generate and decode mnemonic recovery phrases."""

    def generate_recovery_phrase(self, entropy_bytes: int = 16) -> str:
        """Generate a 12-word recovery phrase from random entropy.

        Each word encodes 8 bits of entropy from our 256-word list,
        so 12 words = 96 bits of entropy (sufficient for passphrase use).
        With entropy_bytes=16 we use the first 12 bytes.
        """
        entropy = secrets.token_bytes(max(entropy_bytes, 12))
        words = []
        for i in range(12):
            idx = entropy[i] % _WORDLIST_SIZE
            words.append(_WORDLIST[idx])
        return " ".join(words)

    def phrase_to_bytes(self, phrase: str) -> bytes:
        """Convert a recovery phrase back to entropy bytes."""
        words = phrase.strip().split()
        result = bytearray()
        for word in words:
            if word not in _WORDLIST:
                raise ValueError(f"Unknown word in recovery phrase: {word!r}")
            idx = _WORDLIST.index(word)
            result.append(idx)
        return bytes(result)
