"""Tests for cortex.upai.backup — Key backup and recovery."""

import json
import unittest

from cortex.upai.backup import (
    KeyBackup,
    RecoveryCodeGenerator,
    _generate_keystream,
    _xor_bytes,
)
from cortex.upai.identity import UPAIIdentity, has_crypto


@unittest.skipUnless(has_crypto(), "Ed25519 (PyNaCl) not available")
class TestKeyBackup(unittest.TestCase):
    """Test encrypted key backup and restore."""

    def setUp(self):
        self.identity = UPAIIdentity.generate("Backup Test")
        self.backup = KeyBackup()

    def test_backup_restore_roundtrip(self):
        passphrase = "test-passphrase-123"
        blob = self.backup.backup(self.identity, passphrase)
        restored = self.backup.restore(blob, passphrase)

        self.assertEqual(restored.did, self.identity.did)
        self.assertEqual(restored.name, self.identity.name)
        self.assertEqual(restored.public_key_b64, self.identity.public_key_b64)
        self.assertEqual(restored._private_key, self.identity._private_key)

    def test_wrong_passphrase(self):
        blob = self.backup.backup(self.identity, "correct-passphrase")
        with self.assertRaises(ValueError) as ctx:
            self.backup.restore(blob, "wrong-passphrase")
        self.assertIn("HMAC", str(ctx.exception))

    def test_backup_format_is_json(self):
        blob = self.backup.backup(self.identity, "test123test")
        data = json.loads(blob)
        self.assertEqual(data["version"], 1)
        self.assertIn("salt", data)
        self.assertIn("iterations", data)
        self.assertIn("ciphertext", data)
        self.assertIn("hmac", data)
        self.assertIn("did", data)
        self.assertIn("name", data)
        self.assertIn("public_key_b64", data)

    def test_different_passphrases_different_ciphertexts(self):
        blob1 = self.backup.backup(self.identity, "passphrase-one")
        blob2 = self.backup.backup(self.identity, "passphrase-two")
        data1 = json.loads(blob1)
        data2 = json.loads(blob2)
        # Different salts → different ciphertexts
        self.assertNotEqual(data1["ciphertext"], data2["ciphertext"])

    def test_restored_identity_can_sign_verify(self):
        blob = self.backup.backup(self.identity, "test-sign-verify")
        restored = self.backup.restore(blob, "test-sign-verify")

        # Sign with restored identity
        message = b"test message"
        sig = restored.sign(message)

        # Verify with original public key
        valid = UPAIIdentity.verify(message, sig, self.identity.public_key_b64)
        self.assertTrue(valid)

    def test_backup_no_private_key_raises(self):
        pub_only = UPAIIdentity(
            did="did:key:z6MkTest",
            name="No Key",
            public_key_b64="AAAA",
            created_at="2026-01-01",
            _private_key=None,
        )
        with self.assertRaises(ValueError):
            self.backup.backup(pub_only, "test")

    def test_invalid_json_raises(self):
        with self.assertRaises(ValueError):
            self.backup.restore(b"not json", "test")

    def test_wrong_version_raises(self):
        blob = self.backup.backup(self.identity, "test12345678")
        data = json.loads(blob)
        data["version"] = 99
        with self.assertRaises(ValueError) as ctx:
            self.backup.restore(json.dumps(data).encode(), "test12345678")
        self.assertIn("version", str(ctx.exception))


class TestRecoveryCodeGenerator(unittest.TestCase):
    """Test recovery phrase generation."""

    def setUp(self):
        self.gen = RecoveryCodeGenerator()

    def test_generates_12_words(self):
        phrase = self.gen.generate_recovery_phrase()
        words = phrase.split()
        self.assertEqual(len(words), 12)

    def test_words_from_wordlist(self):
        from cortex.upai.backup import _WORDLIST
        phrase = self.gen.generate_recovery_phrase()
        for word in phrase.split():
            self.assertIn(word, _WORDLIST, f"Word {word!r} not in wordlist")

    def test_phrase_to_bytes_roundtrip(self):
        phrase = self.gen.generate_recovery_phrase()
        result = self.gen.phrase_to_bytes(phrase)
        self.assertEqual(len(result), 12)

    def test_different_phrases(self):
        phrases = {self.gen.generate_recovery_phrase() for _ in range(10)}
        # Extremely unlikely to generate duplicates
        self.assertGreater(len(phrases), 1)

    def test_phrase_to_bytes_unknown_word(self):
        with self.assertRaises(ValueError):
            self.gen.phrase_to_bytes("xyzzy foobar baz")

    @unittest.skipUnless(has_crypto(), "Ed25519 not available")
    def test_recovery_phrase_as_backup_passphrase(self):
        """Recovery phrase can be used as passphrase for backup."""
        identity = UPAIIdentity.generate("Recovery Test")
        phrase = self.gen.generate_recovery_phrase()

        backup = KeyBackup()
        blob = backup.backup(identity, phrase)
        restored = backup.restore(blob, phrase)
        self.assertEqual(restored.did, identity.did)


class TestXORKeystream(unittest.TestCase):
    """Test XOR keystream cipher internals."""

    def test_deterministic_keystream(self):
        key = b"test-key-material-32-bytes-long!"
        ks1 = _generate_keystream(key, 64)
        ks2 = _generate_keystream(key, 64)
        self.assertEqual(ks1, ks2)

    def test_different_keys_different_streams(self):
        ks1 = _generate_keystream(b"key-a-32-bytes-long-padding!!!!", 64)
        ks2 = _generate_keystream(b"key-b-32-bytes-long-padding!!!!", 64)
        self.assertNotEqual(ks1, ks2)

    def test_xor_roundtrip(self):
        data = b"hello world test data"
        keystream = _generate_keystream(b"my-secret-key-for-testing-32b!!", len(data))
        encrypted = _xor_bytes(data, keystream)
        decrypted = _xor_bytes(encrypted, keystream)
        self.assertEqual(decrypted, data)

    def test_keystream_length(self):
        ks = _generate_keystream(b"key", 100)
        self.assertEqual(len(ks), 100)


if __name__ == "__main__":
    unittest.main()
