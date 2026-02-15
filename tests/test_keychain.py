"""
Tests for UPAI Keychain — key rotation and revocation.

Covers:
- Rotate produces new DID
- Old key marked revoked after rotation
- Revocation proof is valid
- Chain verification
- File persistence
- Multiple rotations
"""

import json
import tempfile
from pathlib import Path

from cortex.upai.identity import UPAIIdentity, has_crypto
from cortex.upai.keychain import Keychain, KeyRecord


# ============================================================================
# Basic operations
# ============================================================================

class TestKeychainBasic:

    def test_rotate_produces_new_did(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / ".cortex"
            identity = UPAIIdentity.generate("Test")
            identity.save(store)

            kc = Keychain(store)
            new_identity, proof = kc.rotate(identity)

            assert new_identity.did != identity.did
            assert new_identity.did.startswith("did:key:z6Mk")
            assert new_identity.name == identity.name

    def test_old_key_revoked_after_rotate(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / ".cortex"
            identity = UPAIIdentity.generate("Test")
            identity.save(store)

            kc = Keychain(store)
            kc.rotate(identity)

            assert kc.is_revoked(identity.did)

    def test_new_key_active_after_rotate(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / ".cortex"
            identity = UPAIIdentity.generate("Test")
            identity.save(store)

            kc = Keychain(store)
            new_identity, _ = kc.rotate(identity)

            assert not kc.is_revoked(new_identity.did)
            assert kc.get_active_did() == new_identity.did

    def test_revocation_proof_nonempty(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / ".cortex"
            identity = UPAIIdentity.generate("Test")
            identity.save(store)

            kc = Keychain(store)
            _, proof = kc.rotate(identity)
            assert proof  # non-empty string

    def test_revoke_key(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / ".cortex"
            identity = UPAIIdentity.generate("Test")
            identity.save(store)

            kc = Keychain(store)
            proof = kc.revoke(identity, reason="compromised")

            assert kc.is_revoked(identity.did)
            assert proof  # non-empty


# ============================================================================
# History and chain
# ============================================================================

class TestKeychainHistory:

    def test_history_grows(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / ".cortex"
            identity = UPAIIdentity.generate("Test")
            identity.save(store)

            kc = Keychain(store)
            kc.rotate(identity)

            history = kc.get_history()
            assert len(history) == 2  # old + new

    def test_multiple_rotations(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / ".cortex"
            current = UPAIIdentity.generate("Test")
            current.save(store)

            kc = Keychain(store)
            for _ in range(3):
                current, _ = kc.rotate(current)

            history = kc.get_history()
            assert len(history) == 4  # original + 3 rotations

            # Only the last one should be active
            active = [r for r in history if not r.revoked_at]
            assert len(active) == 1
            assert active[0].did == current.did

    def test_chain_verification_valid(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / ".cortex"
            current = UPAIIdentity.generate("Test")
            current.save(store)

            kc = Keychain(store)
            current, _ = kc.rotate(current)
            current, _ = kc.rotate(current)

            errors = kc.verify_rotation_chain()
            assert errors == []

    def test_successor_recorded(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / ".cortex"
            identity = UPAIIdentity.generate("Test")
            identity.save(store)

            kc = Keychain(store)
            new_identity, _ = kc.rotate(identity)

            history = kc.get_history()
            old_record = next(r for r in history if r.did == identity.did)
            assert old_record.successor_did == new_identity.did
            assert old_record.revocation_reason == "rotated"


# ============================================================================
# Persistence
# ============================================================================

class TestKeychainPersistence:

    def test_persists_to_file(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / ".cortex"
            identity = UPAIIdentity.generate("Test")
            identity.save(store)

            kc = Keychain(store)
            kc.rotate(identity)

            # Reload from disk
            kc2 = Keychain(store)
            assert len(kc2.get_history()) == 2

    def test_keychain_file_format(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / ".cortex"
            identity = UPAIIdentity.generate("Test")
            identity.save(store)

            kc = Keychain(store)
            kc.rotate(identity)

            data = json.loads((store / "keychain.json").read_text())
            assert "keys" in data
            assert len(data["keys"]) == 2

    def test_empty_keychain(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / ".cortex"
            store.mkdir(parents=True)
            kc = Keychain(store)
            assert kc.get_history() == []
            assert kc.get_active_did() is None


# ============================================================================
# KeyRecord
# ============================================================================

class TestKeyRecord:

    def test_to_dict_from_dict_roundtrip(self):
        record = KeyRecord(
            did="did:key:z6MkTest",
            public_key_b64="dGVzdA==",
            created_at="2024-01-01T00:00:00+00:00",
            revoked_at="2024-06-01T00:00:00+00:00",
            revocation_reason="rotated",
            successor_did="did:key:z6MkNew",
        )
        d = record.to_dict()
        restored = KeyRecord.from_dict(d)
        assert restored.did == record.did
        assert restored.revoked_at == record.revoked_at
        assert restored.successor_did == record.successor_did

    def test_is_revoked_check(self):
        if not has_crypto():
            return
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Path(tmpdir) / ".cortex"
            identity = UPAIIdentity.generate("Test")
            identity.save(store)

            kc = Keychain(store)
            assert not kc.is_revoked(identity.did)
            # Unknown DID
            assert not kc.is_revoked("did:key:z6MkUnknown")
