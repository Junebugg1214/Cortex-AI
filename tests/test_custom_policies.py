"""
Tests for custom disclosure policies — PolicyRegistry, JsonPolicyStore, SqlitePolicyStore.
"""

import os
import tempfile
import threading

import pytest

from cortex.caas.storage import JsonPolicyStore
from cortex.upai.disclosure import BUILTIN_POLICIES, DisclosurePolicy, PolicyRegistry

# ---------------------------------------------------------------------------
# PolicyRegistry unit tests
# ---------------------------------------------------------------------------

class TestPolicyRegistry:
    def test_builtin_policies_accessible(self):
        reg = PolicyRegistry()
        for name in BUILTIN_POLICIES:
            assert reg.get(name) is not None
            assert reg.is_builtin(name)

    def test_list_all_includes_builtins(self):
        reg = PolicyRegistry()
        all_policies = reg.list_all()
        names = {p.name for p in all_policies}
        for name in BUILTIN_POLICIES:
            assert name in names

    def test_register_custom_policy(self):
        reg = PolicyRegistry()
        p = DisclosurePolicy(
            name="test-custom",
            include_tags=["identity"],
            exclude_tags=[],
            min_confidence=0.5,
            redact_properties=[],
        )
        reg.register(p)
        assert reg.get("test-custom") is not None
        assert reg.get("test-custom").min_confidence == 0.5
        assert not reg.is_builtin("test-custom")

    def test_register_updates_list_all(self):
        reg = PolicyRegistry()
        initial_count = len(reg.list_all())
        p = DisclosurePolicy(
            name="extra-policy",
            include_tags=[],
            exclude_tags=[],
            min_confidence=0.0,
            redact_properties=[],
        )
        reg.register(p)
        assert len(reg.list_all()) == initial_count + 1

    def test_cannot_override_builtin(self):
        reg = PolicyRegistry()
        p = DisclosurePolicy(
            name="full",
            include_tags=["hacked"],
            exclude_tags=[],
            min_confidence=0.0,
            redact_properties=[],
        )
        with pytest.raises(ValueError, match="built-in"):
            reg.register(p)

    def test_update_custom_policy(self):
        reg = PolicyRegistry()
        p1 = DisclosurePolicy(
            name="updatable",
            include_tags=["a"],
            exclude_tags=[],
            min_confidence=0.3,
            redact_properties=[],
        )
        reg.register(p1)
        p2 = DisclosurePolicy(
            name="updatable",
            include_tags=["a", "b"],
            exclude_tags=[],
            min_confidence=0.7,
            redact_properties=[],
        )
        assert reg.update("updatable", p2)
        assert reg.get("updatable").min_confidence == 0.7
        assert reg.get("updatable").include_tags == ["a", "b"]

    def test_update_nonexistent_returns_false(self):
        reg = PolicyRegistry()
        p = DisclosurePolicy(
            name="ghost",
            include_tags=[],
            exclude_tags=[],
            min_confidence=0.0,
            redact_properties=[],
        )
        assert not reg.update("ghost", p)

    def test_update_builtin_raises(self):
        reg = PolicyRegistry()
        p = DisclosurePolicy(
            name="full",
            include_tags=[],
            exclude_tags=[],
            min_confidence=0.0,
            redact_properties=[],
        )
        with pytest.raises(ValueError, match="built-in"):
            reg.update("full", p)

    def test_delete_custom_policy(self):
        reg = PolicyRegistry()
        p = DisclosurePolicy(
            name="deletable",
            include_tags=[],
            exclude_tags=[],
            min_confidence=0.0,
            redact_properties=[],
        )
        reg.register(p)
        assert reg.delete("deletable")
        assert reg.get("deletable") is None

    def test_delete_nonexistent_returns_false(self):
        reg = PolicyRegistry()
        assert not reg.delete("no-such-policy")

    def test_delete_builtin_raises(self):
        reg = PolicyRegistry()
        with pytest.raises(ValueError, match="built-in"):
            reg.delete("professional")

    def test_invalid_name_rejected(self):
        reg = PolicyRegistry()
        p = DisclosurePolicy(
            name="",
            include_tags=[],
            exclude_tags=[],
            min_confidence=0.0,
            redact_properties=[],
        )
        with pytest.raises(ValueError, match="Invalid policy name"):
            reg.register(p)

    def test_invalid_name_special_chars(self):
        reg = PolicyRegistry()
        p = DisclosurePolicy(
            name="bad name!",
            include_tags=[],
            exclude_tags=[],
            min_confidence=0.0,
            redact_properties=[],
        )
        with pytest.raises(ValueError, match="Invalid policy name"):
            reg.register(p)

    def test_name_too_long(self):
        reg = PolicyRegistry()
        p = DisclosurePolicy(
            name="a" * 65,
            include_tags=[],
            exclude_tags=[],
            min_confidence=0.0,
            redact_properties=[],
        )
        with pytest.raises(ValueError, match="Invalid policy name"):
            reg.register(p)

    def test_valid_names(self):
        reg = PolicyRegistry()
        for name in ["a", "my-policy", "POLICY-123", "x" * 64]:
            p = DisclosurePolicy(
                name=name,
                include_tags=[],
                exclude_tags=[],
                min_confidence=0.0,
                redact_properties=[],
            )
            reg.register(p)
            assert reg.get(name) is not None
            reg.delete(name)

    def test_thread_safety(self):
        reg = PolicyRegistry()
        errors = []

        def register_many(prefix, count):
            try:
                for i in range(count):
                    p = DisclosurePolicy(
                        name=f"{prefix}-{i}",
                        include_tags=[],
                        exclude_tags=[],
                        min_confidence=0.0,
                        redact_properties=[],
                    )
                    reg.register(p)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=register_many, args=(f"t{t}", 20))
            for t in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        custom_count = len(reg.list_all()) - len(BUILTIN_POLICIES)
        assert custom_count == 100  # 5 threads * 20 policies


# ---------------------------------------------------------------------------
# JsonPolicyStore tests
# ---------------------------------------------------------------------------

class TestJsonPolicyStore:
    def test_add_and_get(self):
        store = JsonPolicyStore()
        p = DisclosurePolicy(
            name="test",
            include_tags=["a"],
            exclude_tags=[],
            min_confidence=0.5,
            redact_properties=[],
        )
        store.add(p)
        result = store.get("test")
        assert result is not None
        assert result.name == "test"
        assert result.min_confidence == 0.5

    def test_list_all(self):
        store = JsonPolicyStore()
        assert store.list_all() == []
        p = DisclosurePolicy(
            name="test",
            include_tags=[],
            exclude_tags=[],
            min_confidence=0.0,
            redact_properties=[],
        )
        store.add(p)
        assert len(store.list_all()) == 1

    def test_update(self):
        store = JsonPolicyStore()
        p1 = DisclosurePolicy(
            name="test",
            include_tags=["a"],
            exclude_tags=[],
            min_confidence=0.3,
            redact_properties=[],
        )
        store.add(p1)
        p2 = DisclosurePolicy(
            name="test",
            include_tags=["a", "b"],
            exclude_tags=[],
            min_confidence=0.8,
            redact_properties=[],
        )
        assert store.update("test", p2)
        assert store.get("test").min_confidence == 0.8

    def test_update_nonexistent(self):
        store = JsonPolicyStore()
        p = DisclosurePolicy(
            name="ghost",
            include_tags=[],
            exclude_tags=[],
            min_confidence=0.0,
            redact_properties=[],
        )
        assert not store.update("ghost", p)

    def test_delete(self):
        store = JsonPolicyStore()
        p = DisclosurePolicy(
            name="test",
            include_tags=[],
            exclude_tags=[],
            min_confidence=0.0,
            redact_properties=[],
        )
        store.add(p)
        assert store.delete("test")
        assert store.get("test") is None

    def test_delete_nonexistent(self):
        store = JsonPolicyStore()
        assert not store.delete("nope")

    def test_registry_with_store(self):
        store = JsonPolicyStore()
        p = DisclosurePolicy(
            name="pre-loaded",
            include_tags=["x"],
            exclude_tags=[],
            min_confidence=0.5,
            redact_properties=[],
        )
        store.add(p)
        reg = PolicyRegistry(store=store)
        # Pre-loaded policy should be accessible
        assert reg.get("pre-loaded") is not None
        assert reg.get("pre-loaded").min_confidence == 0.5


# ---------------------------------------------------------------------------
# SqlitePolicyStore tests
# ---------------------------------------------------------------------------

class TestSqlitePolicyStore:
    def test_add_and_get(self):
        from cortex.caas.sqlite_store import SqlitePolicyStore
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            store = SqlitePolicyStore(db_path)
            p = DisclosurePolicy(
                name="sqlite-test",
                include_tags=["a", "b"],
                exclude_tags=["c"],
                min_confidence=0.6,
                redact_properties=["secret"],
                max_nodes=50,
            )
            store.add(p)
            result = store.get("sqlite-test")
            assert result is not None
            assert result.name == "sqlite-test"
            assert result.include_tags == ["a", "b"]
            assert result.exclude_tags == ["c"]
            assert result.min_confidence == 0.6
            assert result.redact_properties == ["secret"]
            assert result.max_nodes == 50
            store.close()
        finally:
            os.unlink(db_path)

    def test_persistence(self):
        from cortex.caas.sqlite_store import SqlitePolicyStore
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            store1 = SqlitePolicyStore(db_path)
            p = DisclosurePolicy(
                name="persist-test",
                include_tags=["x"],
                exclude_tags=[],
                min_confidence=0.7,
                redact_properties=[],
            )
            store1.add(p)
            store1.close()

            store2 = SqlitePolicyStore(db_path)
            result = store2.get("persist-test")
            assert result is not None
            assert result.min_confidence == 0.7
            store2.close()
        finally:
            os.unlink(db_path)

    def test_list_all(self):
        from cortex.caas.sqlite_store import SqlitePolicyStore
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            store = SqlitePolicyStore(db_path)
            for i in range(3):
                store.add(DisclosurePolicy(
                    name=f"policy-{i}",
                    include_tags=[],
                    exclude_tags=[],
                    min_confidence=0.0,
                    redact_properties=[],
                ))
            assert len(store.list_all()) == 3
            store.close()
        finally:
            os.unlink(db_path)

    def test_update(self):
        from cortex.caas.sqlite_store import SqlitePolicyStore
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            store = SqlitePolicyStore(db_path)
            store.add(DisclosurePolicy(
                name="up",
                include_tags=["old"],
                exclude_tags=[],
                min_confidence=0.1,
                redact_properties=[],
            ))
            updated = DisclosurePolicy(
                name="up",
                include_tags=["new"],
                exclude_tags=[],
                min_confidence=0.9,
                redact_properties=[],
            )
            assert store.update("up", updated)
            result = store.get("up")
            assert result.include_tags == ["new"]
            assert result.min_confidence == 0.9
            store.close()
        finally:
            os.unlink(db_path)

    def test_delete(self):
        from cortex.caas.sqlite_store import SqlitePolicyStore
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            store = SqlitePolicyStore(db_path)
            store.add(DisclosurePolicy(
                name="del-me",
                include_tags=[],
                exclude_tags=[],
                min_confidence=0.0,
                redact_properties=[],
            ))
            assert store.delete("del-me")
            assert store.get("del-me") is None
            assert not store.delete("del-me")
            store.close()
        finally:
            os.unlink(db_path)

    def test_registry_with_sqlite_store(self):
        from cortex.caas.sqlite_store import SqlitePolicyStore
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            store = SqlitePolicyStore(db_path)
            store.add(DisclosurePolicy(
                name="sqlite-reg",
                include_tags=["t"],
                exclude_tags=[],
                min_confidence=0.4,
                redact_properties=[],
            ))

            reg = PolicyRegistry(store=store)
            assert reg.get("sqlite-reg") is not None

            # Register through registry persists to store
            reg.register(DisclosurePolicy(
                name="via-reg",
                include_tags=[],
                exclude_tags=[],
                min_confidence=0.0,
                redact_properties=[],
            ))
            assert store.get("via-reg") is not None

            # Delete through registry removes from store
            reg.delete("via-reg")
            assert store.get("via-reg") is None
            store.close()
        finally:
            os.unlink(db_path)
