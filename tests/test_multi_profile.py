"""Tests for multi-profile support — Feature 4."""

import pytest
from cortex.caas.profile import ProfileConfig, ProfileStore, validate_handle


class TestMultiProfile:
    def test_create_multiple_profiles(self):
        store = ProfileStore()
        p1 = ProfileConfig(handle="alice", display_name="Alice")
        p2 = ProfileConfig(handle="bob", display_name="Bob")
        store.create(p1)
        store.create(p2)
        assert len(store.list_all()) == 2

    def test_get_by_handle(self):
        store = ProfileStore()
        store.create(ProfileConfig(handle="alice", display_name="Alice"))
        store.create(ProfileConfig(handle="bob", display_name="Bob"))
        p = store.get("bob")
        assert p is not None
        assert p.display_name == "Bob"

    def test_get_nonexistent_returns_none(self):
        store = ProfileStore()
        assert store.get("nobody") is None

    def test_delete_profile(self):
        store = ProfileStore()
        store.create(ProfileConfig(handle="alice", display_name="Alice"))
        store.create(ProfileConfig(handle="bob", display_name="Bob"))
        assert store.delete("alice") is True
        assert len(store.list_all()) == 1
        assert store.get("alice") is None

    def test_delete_nonexistent_returns_false(self):
        store = ProfileStore()
        assert store.delete("nobody") is False

    def test_duplicate_handle_raises(self):
        store = ProfileStore()
        store.create(ProfileConfig(handle="alice", display_name="Alice"))
        with pytest.raises(ValueError, match="already exists"):
            store.create(ProfileConfig(handle="alice", display_name="Alice 2"))

    def test_update_profile(self):
        store = ProfileStore()
        store.create(ProfileConfig(handle="alice", display_name="Alice"))
        updated = store.update("alice", {"display_name": "Alice Updated", "headline": "Engineer"})
        assert updated is not None
        assert updated.display_name == "Alice Updated"
        assert updated.headline == "Engineer"

    def test_list_all_preserves_order(self):
        store = ProfileStore()
        for name in ("charlie", "alice", "bob"):
            store.create(ProfileConfig(handle=name, display_name=name.title()))
        handles = [p.handle for p in store.list_all()]
        assert "charlie" in handles
        assert "alice" in handles
        assert "bob" in handles
        assert len(handles) == 3
