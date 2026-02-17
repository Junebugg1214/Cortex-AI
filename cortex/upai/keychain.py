"""
UPAI Keychain — Key rotation, revocation, and history chain.

Manages the lifecycle of Ed25519 identity keys:
- Rotate: generate new key, mark old as revoked with successor link
- Revoke: mark key as compromised/revoked
- History: chain of all keys with rotation proofs
- Persist: JSON file at .cortex/keychain.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from cortex.upai.identity import UPAIIdentity

if TYPE_CHECKING:
    pass


@dataclass
class KeyRecord:
    """A record of a key in the keychain."""

    did: str
    public_key_b64: str
    created_at: str
    revoked_at: str = ""
    revocation_reason: str = ""    # "compromised" | "rotated" | "expired"
    successor_did: str = ""

    def to_dict(self) -> dict:
        return {
            "did": self.did,
            "public_key_b64": self.public_key_b64,
            "created_at": self.created_at,
            "revoked_at": self.revoked_at,
            "revocation_reason": self.revocation_reason,
            "successor_did": self.successor_did,
        }

    @classmethod
    def from_dict(cls, d: dict) -> KeyRecord:
        return cls(
            did=d["did"],
            public_key_b64=d["public_key_b64"],
            created_at=d["created_at"],
            revoked_at=d.get("revoked_at", ""),
            revocation_reason=d.get("revocation_reason", ""),
            successor_did=d.get("successor_did", ""),
        )


class Keychain:
    """Manages key rotation, revocation, and history."""

    def __init__(self, store_dir: Path) -> None:
        self.store_dir = store_dir
        self.keychain_path = store_dir / "keychain.json"
        self._records: list[KeyRecord] = []
        self._load()

    def _load(self) -> None:
        """Load keychain from disk."""
        if self.keychain_path.exists():
            data = json.loads(self.keychain_path.read_text())
            self._records = [KeyRecord.from_dict(r) for r in data.get("keys", [])]
        else:
            self._records = []

    def _save(self) -> None:
        """Persist keychain to disk."""
        self.store_dir.mkdir(parents=True, exist_ok=True)
        data = {"keys": [r.to_dict() for r in self._records]}
        self.keychain_path.write_text(json.dumps(data, indent=2))

    def _ensure_registered(self, identity: UPAIIdentity) -> None:
        """Ensure the current identity is registered in the keychain."""
        if not any(r.did == identity.did for r in self._records):
            self._records.append(KeyRecord(
                did=identity.did,
                public_key_b64=identity.public_key_b64,
                created_at=identity.created_at,
            ))
            self._save()

    def rotate(self, current_identity: UPAIIdentity, reason: str = "rotated") -> tuple[UPAIIdentity, str]:
        """Rotate to a new key. Returns (new_identity, revocation_proof).

        The revocation_proof is a signature by the OLD key over the revocation record,
        proving the key holder authorized the rotation.
        """
        self._ensure_registered(current_identity)

        # Generate new identity
        new_identity = UPAIIdentity.generate(current_identity.name)

        # Mark old key as revoked
        now = datetime.now(timezone.utc).isoformat()
        for record in self._records:
            if record.did == current_identity.did and not record.revoked_at:
                record.revoked_at = now
                record.revocation_reason = reason
                record.successor_did = new_identity.did
                break

        # Add new key record
        self._records.append(KeyRecord(
            did=new_identity.did,
            public_key_b64=new_identity.public_key_b64,
            created_at=new_identity.created_at,
        ))

        # Create revocation proof: old key signs the rotation event
        proof_data = json.dumps({
            "action": "rotate",
            "old_did": current_identity.did,
            "new_did": new_identity.did,
            "timestamp": now,
        }, sort_keys=True).encode("utf-8")

        revocation_proof = ""
        if current_identity._private_key is not None:
            revocation_proof = current_identity.sign(proof_data)

        self._save()

        # Save new identity to disk
        new_identity.save(self.store_dir)

        return new_identity, revocation_proof

    def revoke(self, identity: UPAIIdentity, reason: str = "compromised") -> str:
        """Revoke a key. Returns revocation proof."""
        self._ensure_registered(identity)

        now = datetime.now(timezone.utc).isoformat()
        for record in self._records:
            if record.did == identity.did and not record.revoked_at:
                record.revoked_at = now
                record.revocation_reason = reason
                break

        # Create revocation proof
        proof_data = json.dumps({
            "action": "revoke",
            "did": identity.did,
            "reason": reason,
            "timestamp": now,
        }, sort_keys=True).encode("utf-8")

        revocation_proof = ""
        if identity._private_key is not None:
            revocation_proof = identity.sign(proof_data)

        self._save()
        return revocation_proof

    def is_revoked(self, did: str) -> bool:
        """Check if a DID has been revoked."""
        for record in self._records:
            if record.did == did:
                return bool(record.revoked_at)
        return False

    def get_active_did(self) -> str | None:
        """Return the currently active (non-revoked) DID, or None."""
        for record in reversed(self._records):
            if not record.revoked_at:
                return record.did
        return None

    def get_history(self) -> list[KeyRecord]:
        """Return all key records in order."""
        return list(self._records)

    def verify_rotation_chain(self) -> list[str]:
        """Verify the rotation chain is valid. Returns list of error strings (empty = valid)."""
        errors: list[str] = []

        for i, record in enumerate(self._records):
            if record.revocation_reason == "rotated" and record.successor_did:
                # Check successor exists
                successor = next(
                    (r for r in self._records if r.did == record.successor_did), None
                )
                if successor is None:
                    errors.append(
                        f"Key {record.did} was rotated to {record.successor_did} but successor not found"
                    )

        # Check exactly one active key
        active = [r for r in self._records if not r.revoked_at]
        if len(active) > 1:
            errors.append(f"Multiple active keys found: {[r.did for r in active]}")
        elif len(active) == 0 and self._records:
            errors.append("No active key found (all revoked)")

        return errors
