"""
Tests for PostgreSQL storage backends — auto-skipped if psycopg is not
installed or the ``cortex_test`` database is not available.

Each test class truncates its tables in setUp/tearDown to ensure isolation.
"""

import os
import unittest

# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

_SKIP_REASON = ""
_HAS_PSYCOPG = False
_PG_CONNINFO = os.environ.get("CORTEX_TEST_PG_URL", "dbname=cortex_test")

try:
    import psycopg  # noqa: F401
    _HAS_PSYCOPG = True
except ImportError:
    _SKIP_REASON = "psycopg not installed"

if _HAS_PSYCOPG and not _SKIP_REASON:
    try:
        _test_conn = psycopg.connect(_PG_CONNINFO, autocommit=True)
        _test_conn.close()
    except Exception as exc:
        _SKIP_REASON = f"Cannot connect to PostgreSQL ({_PG_CONNINFO}): {exc}"

_skip = unittest.skipIf(bool(_SKIP_REASON), _SKIP_REASON)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_token_data(audience="TestAudience", policy="professional"):
    return {
        "audience": audience,
        "policy": policy,
        "issued_at": "2026-01-01T00:00:00Z",
        "scopes": ["context:read"],
    }


def _truncate_tables(conninfo: str, tables: list[str]) -> None:
    """Truncate the given tables (for test isolation)."""
    conn = psycopg.connect(conninfo, autocommit=True)
    try:
        for table in tables:
            conn.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
    except Exception:
        # Table may not exist yet — that's OK
        pass
    finally:
        conn.close()


# ===================================================================
# Grant Store
# ===================================================================

@_skip
class TestPostgresGrantStore(unittest.TestCase):

    def setUp(self):
        from cortex.caas.postgres_store import PostgresGrantStore
        _truncate_tables(_PG_CONNINFO, ["grants"])
        self.store = PostgresGrantStore(_PG_CONNINFO)

    def tearDown(self):
        self.store.close()

    def test_add_and_get(self):
        td = _make_token_data()
        self.store.add("g-001", "tok-abc", td)
        result = self.store.get("g-001")
        self.assertIsNotNone(result)
        self.assertEqual(result["token_str"], "tok-abc")
        self.assertEqual(result["token_data"]["audience"], "TestAudience")
        self.assertFalse(result["revoked"])

    def test_get_missing(self):
        self.assertIsNone(self.store.get("nonexistent"))

    def test_list_all(self):
        self.store.add("g-001", "tok-a", _make_token_data("A"))
        self.store.add("g-002", "tok-b", _make_token_data("B"))
        grants = self.store.list_all()
        self.assertEqual(len(grants), 2)
        ids = {g["grant_id"] for g in grants}
        self.assertEqual(ids, {"g-001", "g-002"})

    def test_revoke(self):
        self.store.add("g-001", "tok-a", _make_token_data())
        self.assertTrue(self.store.revoke("g-001"))
        result = self.store.get("g-001")
        self.assertTrue(result["revoked"])

    def test_revoke_nonexistent(self):
        self.assertFalse(self.store.revoke("nope"))

    def test_revoke_idempotent(self):
        self.store.add("g-001", "tok-a", _make_token_data())
        self.assertTrue(self.store.revoke("g-001"))
        # Second revoke still returns True (row exists, already revoked)
        self.assertTrue(self.store.revoke("g-001"))

    def test_encryption_roundtrip(self):
        """Grant store with encryptor encrypts/decrypts token_str."""
        try:
            from cortex.caas.encryption import FieldEncryptor
        except ImportError:
            self.skipTest("FieldEncryptor not available")
        enc = FieldEncryptor.from_identity_key(b"test-key-32-bytes-long-00000000")
        _truncate_tables(_PG_CONNINFO, ["grants"])
        store = PostgresGrantStore(_PG_CONNINFO, encryptor=enc)
        try:
            store.add("g-enc", "secret-token", _make_token_data())
            result = store.get("g-enc")
            self.assertEqual(result["token_str"], "secret-token")
        finally:
            store.close()


# ===================================================================
# Webhook Store
# ===================================================================

@_skip
class TestPostgresWebhookStore(unittest.TestCase):

    def setUp(self):
        from cortex.caas.postgres_store import PostgresWebhookStore
        _truncate_tables(_PG_CONNINFO, ["webhooks"])
        self.store = PostgresWebhookStore(_PG_CONNINFO)

    def tearDown(self):
        self.store.close()

    def _make_reg(self, wid="wh-001", url="https://example.com/hook",
                  events=None, active=True):
        from cortex.upai.webhooks import WebhookRegistration
        return WebhookRegistration(
            webhook_id=wid, url=url,
            events=events or ["grant.created"],
            secret="s3cret", created_at="2026-01-01T00:00:00Z",
            active=active,
        )

    def test_add_and_get(self):
        reg = self._make_reg()
        self.store.add(reg)
        result = self.store.get("wh-001")
        self.assertIsNotNone(result)
        self.assertEqual(result.url, "https://example.com/hook")
        self.assertTrue(result.active)

    def test_get_missing(self):
        self.assertIsNone(self.store.get("nonexistent"))

    def test_list_all(self):
        self.store.add(self._make_reg("wh-001"))
        self.store.add(self._make_reg("wh-002"))
        all_wh = self.store.list_all()
        self.assertEqual(len(all_wh), 2)

    def test_delete(self):
        self.store.add(self._make_reg())
        self.assertTrue(self.store.delete("wh-001"))
        self.assertIsNone(self.store.get("wh-001"))

    def test_delete_missing(self):
        self.assertFalse(self.store.delete("nonexistent"))

    def test_get_for_event(self):
        self.store.add(self._make_reg("wh-a", events=["grant.created"]))
        self.store.add(self._make_reg("wh-b", events=["grant.revoked"]))
        self.store.add(self._make_reg("wh-c", events=["grant.created"], active=False))
        matching = self.store.get_for_event("grant.created")
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].webhook_id, "wh-a")


# ===================================================================
# Audit Log
# ===================================================================

@_skip
class TestPostgresAuditLog(unittest.TestCase):

    def setUp(self):
        from cortex.caas.postgres_store import PostgresAuditLog
        _truncate_tables(_PG_CONNINFO, ["audit_log"])
        self.log = PostgresAuditLog(_PG_CONNINFO)

    def tearDown(self):
        self.log.close()

    def test_log_and_query(self):
        self.log.log("grant.created", {"grant_id": "g-001"})
        entries = self.log.query()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["event_type"], "grant.created")

    def test_query_all(self):
        self.log.log("a")
        self.log.log("b")
        self.log.log("c")
        entries = self.log.query()
        self.assertEqual(len(entries), 3)

    def test_query_by_type(self):
        self.log.log("grant.created")
        self.log.log("grant.revoked")
        self.log.log("grant.created")
        entries = self.log.query(event_type="grant.created")
        self.assertEqual(len(entries), 2)

    def test_query_limit(self):
        for i in range(10):
            self.log.log(f"event-{i}")
        entries = self.log.query(limit=3)
        self.assertEqual(len(entries), 3)


# ===================================================================
# Delivery Log
# ===================================================================

@_skip
class TestPostgresDeliveryLog(unittest.TestCase):

    def setUp(self):
        from cortex.caas.postgres_store import PostgresDeliveryLog
        _truncate_tables(_PG_CONNINFO, ["webhook_deliveries"])
        self.log = PostgresDeliveryLog(_PG_CONNINFO)

    def tearDown(self):
        self.log.close()

    def test_record_and_query(self):
        self.log.record("d-001", "wh-001", "grant.created", 200, True)
        entries = self.log.query()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["delivery_id"], "d-001")
        self.assertTrue(entries[0]["success"])

    def test_query_by_webhook(self):
        self.log.record("d-001", "wh-001", "grant.created", 200, True)
        self.log.record("d-002", "wh-002", "grant.revoked", 500, False, error="timeout")
        entries = self.log.query(webhook_id="wh-001")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["webhook_id"], "wh-001")

    def test_query_by_event(self):
        self.log.record("d-001", "wh-001", "grant.created", 200, True)
        self.log.record("d-002", "wh-001", "grant.revoked", 200, True)
        # query is by webhook_id only (no event filter in query method)
        entries = self.log.query(webhook_id="wh-001")
        self.assertEqual(len(entries), 2)

    def test_recent(self):
        for i in range(5):
            self.log.record(f"d-{i:03d}", "wh-001", "test", 200, True)
        entries = self.log.query(limit=3)
        self.assertEqual(len(entries), 3)


# ===================================================================
# Policy Store
# ===================================================================

@_skip
class TestPostgresPolicyStore(unittest.TestCase):

    def setUp(self):
        from cortex.caas.postgres_store import PostgresPolicyStore
        _truncate_tables(_PG_CONNINFO, ["policies"])
        self.store = PostgresPolicyStore(_PG_CONNINFO)

    def tearDown(self):
        self.store.close()

    def _make_policy(self, name="test-policy"):
        from cortex.upai.disclosure import DisclosurePolicy
        return DisclosurePolicy(
            name=name,
            include_tags=["technical"],
            exclude_tags=["personal"],
            min_confidence=0.5,
            redact_properties=["email"],
            max_nodes=100,
        )

    def test_add_and_get(self):
        policy = self._make_policy()
        self.store.add(policy)
        result = self.store.get("test-policy")
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "test-policy")
        self.assertEqual(result.include_tags, ["technical"])
        self.assertAlmostEqual(result.min_confidence, 0.5)

    def test_get_missing(self):
        self.assertIsNone(self.store.get("nonexistent"))

    def test_list_all(self):
        self.store.add(self._make_policy("p1"))
        self.store.add(self._make_policy("p2"))
        policies = self.store.list_all()
        self.assertEqual(len(policies), 2)

    def test_update(self):
        self.store.add(self._make_policy("original"))
        from cortex.upai.disclosure import DisclosurePolicy
        updated = DisclosurePolicy(
            name="original",
            include_tags=["all"],
            exclude_tags=[],
            min_confidence=0.0,
            redact_properties=[],
            max_nodes=0,
        )
        self.assertTrue(self.store.update("original", updated))
        result = self.store.get("original")
        self.assertEqual(result.include_tags, ["all"])

    def test_delete(self):
        self.store.add(self._make_policy())
        self.assertTrue(self.store.delete("test-policy"))
        self.assertIsNone(self.store.get("test-policy"))

    def test_delete_missing(self):
        self.assertFalse(self.store.delete("nonexistent"))


# ===================================================================
# Audit Ledger (hash-chained)
# ===================================================================

@_skip
class TestPostgresAuditLedger(unittest.TestCase):

    def setUp(self):
        from cortex.caas.postgres_audit_ledger import PostgresAuditLedger
        _truncate_tables(_PG_CONNINFO, ["audit_ledger"])
        self.ledger = PostgresAuditLedger(_PG_CONNINFO)

    def tearDown(self):
        self.ledger.close()

    def test_append(self):
        entry = self.ledger.append("grant.created", actor="user:alice")
        self.assertEqual(entry.event_type, "grant.created")
        self.assertEqual(entry.actor, "user:alice")
        self.assertTrue(entry.entry_hash)

    def test_query(self):
        self.ledger.append("a")
        self.ledger.append("b")
        self.ledger.append("a")
        entries = self.ledger.query(event_type="a")
        self.assertEqual(len(entries), 2)

    def test_count(self):
        self.assertEqual(self.ledger.count(), 0)
        self.ledger.append("x")
        self.ledger.append("y")
        self.assertEqual(self.ledger.count(), 2)

    def test_verify_valid_chain(self):
        self.ledger.append("a")
        self.ledger.append("b")
        self.ledger.append("c")
        valid, checked, err = self.ledger.verify()
        self.assertTrue(valid)
        self.assertEqual(checked, 3)
        self.assertEqual(err, "")

    def test_tamper_detection(self):
        self.ledger.append("a")
        self.ledger.append("b")
        # Tamper with the database directly
        conn = psycopg.connect(_PG_CONNINFO, autocommit=True)
        try:
            conn.execute(
                "UPDATE audit_ledger SET details = %s WHERE sequence_id = 0",
                ('{"tampered": true}',),
            )
        finally:
            conn.close()
        valid, checked, err = self.ledger.verify()
        self.assertFalse(valid)
        self.assertIn("hash mismatch", err)

    def test_query_by_actor(self):
        self.ledger.append("x", actor="alice")
        self.ledger.append("x", actor="bob")
        self.ledger.append("x", actor="alice")
        entries = self.ledger.query(actor="alice")
        self.assertEqual(len(entries), 2)


# ===================================================================
# Integration: CLI + Config
# ===================================================================

class TestPostgresIntegration(unittest.TestCase):
    """Integration tests that do NOT require a running PostgreSQL instance."""

    def test_cli_storage_choices(self):
        """--storage accepts 'postgres' as a valid choice."""
        from cortex.cli import build_parser
        parser = build_parser()
        args = parser.parse_args([
            "serve", "dummy.json", "--storage", "postgres",
            "--db-url", "dbname=cortex_test",
        ])
        self.assertEqual(args.storage, "postgres")
        self.assertEqual(args.db_url, "dbname=cortex_test")

    def test_cli_grant_storage_choices(self):
        """grant --storage accepts 'postgres'."""
        from cortex.cli import build_parser
        parser = build_parser()
        args = parser.parse_args([
            "grant", "--list", "--storage", "postgres",
            "--db-url", "dbname=cortex_test",
        ])
        self.assertEqual(args.storage, "postgres")

    def test_config_db_url_default(self):
        """Config defaults include db_url key."""
        from cortex.caas.config import CortexConfig
        config = CortexConfig.defaults()
        self.assertEqual(config.get("storage", "db_url"), "")

    def test_module_importable(self):
        """postgres_store module can be imported (psycopg imported lazily at init)."""
        from cortex.caas import postgres_store
        self.assertTrue(hasattr(postgres_store, "PostgresGrantStore"))
        self.assertTrue(hasattr(postgres_store, "PostgresWebhookStore"))
        self.assertTrue(hasattr(postgres_store, "PostgresAuditLog"))
        self.assertTrue(hasattr(postgres_store, "PostgresDeliveryLog"))
        self.assertTrue(hasattr(postgres_store, "PostgresPolicyStore"))


# ===================================================================
# Cleanup / Table Creation
# ===================================================================

@_skip
class TestPostgresCleanup(unittest.TestCase):

    def test_tables_created_on_init(self):
        """Verify that store classes create their tables on init."""
        from cortex.caas.postgres_store import PostgresGrantStore
        conn = psycopg.connect(_PG_CONNINFO, autocommit=True)
        try:
            # Drop and recreate to prove auto-creation works
            conn.execute("DROP TABLE IF EXISTS grants CASCADE")
        finally:
            conn.close()
        store = PostgresGrantStore(_PG_CONNINFO)
        try:
            # Should not raise — table was auto-created
            store.add("g-init", "tok", _make_token_data())
            result = store.get("g-init")
            self.assertIsNotNone(result)
        finally:
            store.close()

    def test_connection_cleanup(self):
        """close() makes subsequent operations fail."""
        from cortex.caas.postgres_store import PostgresGrantStore
        store = PostgresGrantStore(_PG_CONNINFO)
        store.close()
        with self.assertRaises(Exception):
            store.add("g-fail", "tok", _make_token_data())


if __name__ == "__main__":
    unittest.main()
