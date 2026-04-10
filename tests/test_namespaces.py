import pytest

from cortex.namespaces import (
    WILDCARD_NAMESPACE,
    acl_allows_namespace,
    acl_single_namespace,
    describe_resource_namespace,
    normalize_acl_namespaces,
    normalize_resource_namespace,
    resource_namespace_matches,
)


def test_resource_namespaces_normalize_to_none_when_unscoped():
    assert normalize_resource_namespace(None) is None
    assert normalize_resource_namespace("") is None
    assert normalize_resource_namespace(" /team/atlas/ ") == "team/atlas"


def test_resource_namespaces_reject_acl_wildcards():
    with pytest.raises(ValueError, match="must not contain spaces or '\\*'"):
        normalize_resource_namespace("*")


def test_acl_namespaces_keep_wildcards_separate_from_resource_namespaces():
    namespaces = normalize_acl_namespaces(["team", "*", "team"])

    assert namespaces == ("team", WILDCARD_NAMESPACE)
    assert acl_allows_namespace(("team",), "team/atlas")
    assert not acl_allows_namespace(("team",), None)
    assert acl_single_namespace(("team",)) == "team"
    assert acl_single_namespace(("team", "team-b")) is None


def test_resource_namespace_matching_and_labels_share_one_contract():
    assert resource_namespace_matches("team/atlas", "team")
    assert resource_namespace_matches(None, None)
    assert not resource_namespace_matches(None, "team")
    assert describe_resource_namespace(None) == "(unscoped)"
    assert describe_resource_namespace("team") == "team"
