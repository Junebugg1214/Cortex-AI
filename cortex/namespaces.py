from __future__ import annotations

import re

RESOURCE_NAMESPACE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}")
WILDCARD_NAMESPACE = "*"


def normalize_resource_namespace(value: str | None) -> str | None:
    cleaned = str(value or "").strip().strip("/")
    if not cleaned:
        return None
    if cleaned == WILDCARD_NAMESPACE or " " in cleaned or not RESOURCE_NAMESPACE_PATTERN.fullmatch(cleaned):
        raise ValueError(
            "Namespaces must use letters, numbers, '.', '-', '_', or '/' and must not contain spaces or '*'."
        )
    return cleaned


def normalize_acl_namespace(value: str | None) -> str:
    cleaned = str(value or "").strip().strip("/")
    if not cleaned:
        return WILDCARD_NAMESPACE
    if cleaned == WILDCARD_NAMESPACE:
        return WILDCARD_NAMESPACE
    normalized = normalize_resource_namespace(cleaned)
    return normalized or WILDCARD_NAMESPACE


def normalize_acl_namespaces(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    raw_values = list(values or [])
    if not raw_values:
        return (WILDCARD_NAMESPACE,)
    normalized = tuple(dict.fromkeys(normalize_acl_namespace(item) for item in raw_values if str(item).strip()))
    return normalized or (WILDCARD_NAMESPACE,)


def acl_allows_namespace(allowed_namespaces: tuple[str, ...], namespace: str | None) -> bool:
    if WILDCARD_NAMESPACE in allowed_namespaces:
        return True
    normalized = normalize_resource_namespace(namespace)
    if normalized is None:
        return False
    return any(
        normalized == allowed or normalized.startswith(f"{allowed}/")
        for allowed in allowed_namespaces
        if allowed != WILDCARD_NAMESPACE
    )


def acl_single_namespace(allowed_namespaces: tuple[str, ...]) -> str | None:
    explicit_namespaces = [namespace for namespace in allowed_namespaces if namespace != WILDCARD_NAMESPACE]
    if len(explicit_namespaces) == 1:
        return explicit_namespaces[0]
    return None


def resource_namespace_matches(item_namespace: str | None, requested_namespace: str | None) -> bool:
    normalized_requested = normalize_resource_namespace(requested_namespace)
    if normalized_requested is None:
        return True
    normalized_item = normalize_resource_namespace(item_namespace)
    return normalized_item is not None and (
        normalized_item == normalized_requested or normalized_item.startswith(f"{normalized_requested}/")
    )


def describe_resource_namespace(namespace: str | None) -> str:
    return normalize_resource_namespace(namespace) or "(unscoped)"


__all__ = [
    "WILDCARD_NAMESPACE",
    "acl_allows_namespace",
    "acl_single_namespace",
    "describe_resource_namespace",
    "normalize_acl_namespace",
    "normalize_acl_namespaces",
    "normalize_resource_namespace",
    "resource_namespace_matches",
]
