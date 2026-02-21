"""
UPAI JSON Schemas — Draft-07 schema dicts + stdlib-only validator.

Covers all UPAI data structures:
- Node, Edge, CortexGraph (v5/v6 export)
- Identity, DID Document
- Signed envelopes, grant tokens
- Disclosure policies, context versions
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Schema definitions (JSON Schema draft-07 style)
# ---------------------------------------------------------------------------

NODE_SCHEMA: dict = {
    "type": "object",
    "required": ["id", "label", "tags", "confidence"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "label": {"type": "string", "minLength": 1},
        "tags": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "properties": {"type": "object"},
        "brief": {"type": "string"},
        "full_description": {"type": "string"},
        "mention_count": {"type": "integer", "minimum": 0},
        "extraction_method": {"type": "string"},
        "metrics": {"type": "array", "items": {"type": "string"}},
        "timeline": {"type": "array", "items": {"type": "string"}},
        "source_quotes": {"type": "array", "items": {"type": "string"}},
        "first_seen": {"type": "string"},
        "last_seen": {"type": "string"},
        "relationship_type": {"type": "string"},
        "snapshots": {"type": "array", "items": {"type": "object"}},
    },
}

EDGE_SCHEMA: dict = {
    "type": "object",
    "required": ["id", "source_id", "target_id", "relation"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "source_id": {"type": "string", "minLength": 1},
        "target_id": {"type": "string", "minLength": 1},
        "relation": {"type": "string", "minLength": 1},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "properties": {"type": "object"},
        "first_seen": {"type": "string"},
        "last_seen": {"type": "string"},
    },
}

GRAPH_SCHEMA: dict = {
    "type": "object",
    "required": ["schema_version", "meta", "graph"],
    "properties": {
        "schema_version": {"type": "string", "pattern": r"^\d+\.\d+$"},
        "meta": {
            "type": "object",
            "properties": {
                "node_count": {"type": "integer", "minimum": 0},
                "edge_count": {"type": "integer", "minimum": 0},
                "generated_at": {"type": "string"},
            },
        },
        "graph": {
            "type": "object",
            "required": ["nodes", "edges"],
            "properties": {
                "nodes": {"type": "object"},
                "edges": {"type": "object"},
            },
        },
        "categories": {"type": "object"},
    },
}

IDENTITY_SCHEMA: dict = {
    "type": "object",
    "required": ["did", "name", "public_key_b64", "created_at"],
    "properties": {
        "did": {"type": "string", "pattern": r"^did:"},
        "name": {"type": "string", "minLength": 1},
        "public_key_b64": {"type": "string", "minLength": 1},
        "created_at": {"type": "string", "minLength": 1},
    },
}

ENVELOPE_SCHEMA: dict = {
    "type": "object",
    "required": ["header", "payload", "signature"],
    "properties": {
        "header": {
            "type": "object",
            "required": ["alg", "typ"],
            "properties": {
                "alg": {"type": "string", "enum": ["Ed25519", "HMAC-SHA256"]},
                "typ": {"type": "string", "enum": ["UPAI-Envelope"]},
            },
        },
        "payload": {
            "type": "object",
            "required": ["data", "nonce", "iat"],
            "properties": {
                "data": {},
                "nonce": {"type": "string", "minLength": 16},
                "iat": {"type": "string"},
                "exp": {"type": "string"},
                "aud": {"type": "string"},
            },
        },
        "signature": {"type": "string", "minLength": 1},
    },
}

GRANT_TOKEN_SCHEMA: dict = {
    "type": "object",
    "required": [
        "grant_id", "subject_did", "issuer_did",
        "audience", "policy", "scopes", "issued_at", "expires_at",
    ],
    "properties": {
        "grant_id": {"type": "string", "minLength": 1},
        "subject_did": {"type": "string", "pattern": r"^did:"},
        "issuer_did": {"type": "string", "pattern": r"^did:"},
        "audience": {"type": "string", "minLength": 1},
        "policy": {
            "type": "string",
            "enum": ["full", "professional", "technical", "minimal"],
        },
        "scopes": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "issued_at": {"type": "string", "minLength": 1},
        "expires_at": {"type": "string", "minLength": 1},
        "not_before": {"type": "string"},
    },
}

DISCLOSURE_POLICY_SCHEMA: dict = {
    "type": "object",
    "required": ["name", "include_tags", "exclude_tags", "min_confidence", "redact_properties"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "include_tags": {"type": "array", "items": {"type": "string"}},
        "exclude_tags": {"type": "array", "items": {"type": "string"}},
        "min_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "redact_properties": {"type": "array", "items": {"type": "string"}},
        "max_nodes": {"type": "integer", "minimum": 0},
    },
}

VERSION_SCHEMA: dict = {
    "type": "object",
    "required": [
        "version_id", "timestamp", "source", "message",
        "graph_hash", "node_count", "edge_count",
    ],
    "properties": {
        "version_id": {"type": "string", "minLength": 1},
        "parent_id": {"type": ["string", "null"]},
        "timestamp": {"type": "string", "minLength": 1},
        "source": {"type": "string", "minLength": 1},
        "message": {"type": "string"},
        "graph_hash": {"type": "string", "minLength": 64, "maxLength": 64},
        "node_count": {"type": "integer", "minimum": 0},
        "edge_count": {"type": "integer", "minimum": 0},
        "signature": {"type": ["string", "null"]},
    },
}

DID_DOCUMENT_SCHEMA: dict = {
    "type": "object",
    "required": ["@context", "id", "controller", "verificationMethod", "authentication"],
    "properties": {
        "@context": {
            "type": ["string", "array"],
        },
        "id": {"type": "string", "pattern": r"^did:"},
        "controller": {"type": "string", "pattern": r"^did:"},
        "created": {"type": "string"},
        "verificationMethod": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "type", "controller"],
                "properties": {
                    "id": {"type": "string"},
                    "type": {"type": "string"},
                    "controller": {"type": "string", "pattern": r"^did:"},
                    "publicKeyBase64": {"type": "string"},
                    "publicKeyMultibase": {"type": "string"},
                },
            },
        },
        "authentication": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
        },
        "alsoKnownAs": {
            "type": "array",
            "items": {"type": "string"},
        },
        "service": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "type", "serviceEndpoint"],
                "properties": {
                    "id": {"type": "string"},
                    "type": {"type": "string"},
                    "serviceEndpoint": {"type": "string"},
                },
            },
        },
    },
}

CREDENTIAL_PROOF_SCHEMA: dict = {
    "type": "object",
    "required": ["type", "created", "verificationMethod", "proofPurpose", "proofValue"],
    "properties": {
        "type": {"type": "string", "minLength": 1},
        "created": {"type": "string", "minLength": 1},
        "verificationMethod": {"type": "string", "minLength": 1},
        "proofPurpose": {"type": "string", "enum": ["assertionMethod", "authentication"]},
        "proofValue": {"type": "string", "minLength": 1},
    },
}

CREDENTIAL_SCHEMA: dict = {
    "type": "object",
    "required": ["@context", "id", "type", "issuer", "issuanceDate", "credentialSubject", "proof"],
    "properties": {
        "@context": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "id": {"type": "string", "minLength": 1},
        "type": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "issuer": {"type": "string", "pattern": r"^did:"},
        "issuanceDate": {"type": "string", "minLength": 1},
        "expirationDate": {"type": "string"},
        "credentialSubject": {
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "string", "pattern": r"^did:"},
            },
        },
        "proof": CREDENTIAL_PROOF_SCHEMA,
        "status": {"type": "string", "enum": ["active", "revoked", "expired"]},
        "boundNodeId": {"type": "string"},
    },
}


# Schema registry
SCHEMAS: dict[str, dict] = {
    "node": NODE_SCHEMA,
    "edge": EDGE_SCHEMA,
    "graph": GRAPH_SCHEMA,
    "identity": IDENTITY_SCHEMA,
    "envelope": ENVELOPE_SCHEMA,
    "grant_token": GRANT_TOKEN_SCHEMA,
    "disclosure_policy": DISCLOSURE_POLICY_SCHEMA,
    "version": VERSION_SCHEMA,
    "did_document": DID_DOCUMENT_SCHEMA,
    "credential": CREDENTIAL_SCHEMA,
    "credential_proof": CREDENTIAL_PROOF_SCHEMA,
}


# ---------------------------------------------------------------------------
# Stdlib-only validator
# ---------------------------------------------------------------------------

def validate(data: Any, schema: dict, path: str = "") -> list[str]:
    """Validate *data* against a JSON Schema dict. Returns list of error strings (empty = valid).

    Supports: type, required, properties, items, enum, pattern,
    minimum/maximum, minLength/maxLength, minItems/maxItems.
    """
    errors: list[str] = []
    prefix = f"{path}: " if path else ""

    # --- type ---
    schema_type = schema.get("type")
    if schema_type is not None:
        if not _check_type(data, schema_type):
            types = schema_type if isinstance(schema_type, list) else [schema_type]
            errors.append(f"{prefix}expected type {'/'.join(types)}, got {type(data).__name__}")
            return errors  # no point checking further

    # --- enum ---
    if "enum" in schema:
        if data not in schema["enum"]:
            errors.append(f"{prefix}value {data!r} not in enum {schema['enum']}")

    # --- pattern ---
    if "pattern" in schema and isinstance(data, str):
        if not re.search(schema["pattern"], data):
            errors.append(f"{prefix}string {data!r} does not match pattern {schema['pattern']!r}")

    # --- minimum / maximum ---
    if "minimum" in schema and isinstance(data, (int, float)):
        if data < schema["minimum"]:
            errors.append(f"{prefix}value {data} < minimum {schema['minimum']}")
    if "maximum" in schema and isinstance(data, (int, float)):
        if data > schema["maximum"]:
            errors.append(f"{prefix}value {data} > maximum {schema['maximum']}")

    # --- minLength / maxLength ---
    if "minLength" in schema and isinstance(data, str):
        if len(data) < schema["minLength"]:
            errors.append(f"{prefix}string length {len(data)} < minLength {schema['minLength']}")
    if "maxLength" in schema and isinstance(data, str):
        if len(data) > schema["maxLength"]:
            errors.append(f"{prefix}string length {len(data)} > maxLength {schema['maxLength']}")

    # --- minItems / maxItems ---
    if "minItems" in schema and isinstance(data, list):
        if len(data) < schema["minItems"]:
            errors.append(f"{prefix}array length {len(data)} < minItems {schema['minItems']}")
    if "maxItems" in schema and isinstance(data, list):
        if len(data) > schema["maxItems"]:
            errors.append(f"{prefix}array length {len(data)} > maxItems {schema['maxItems']}")

    # --- required ---
    if "required" in schema and isinstance(data, dict):
        for key in schema["required"]:
            if key not in data:
                errors.append(f"{prefix}missing required field '{key}'")

    # --- properties ---
    if "properties" in schema and isinstance(data, dict):
        for key, sub_schema in schema["properties"].items():
            if key in data and sub_schema:
                errors.extend(validate(data[key], sub_schema, path=f"{path}.{key}" if path else key))

    # --- items ---
    if "items" in schema and isinstance(data, list):
        item_schema = schema["items"]
        if item_schema:
            for i, item in enumerate(data):
                item_path = f"{path}[{i}]" if path else f"[{i}]"
                errors.extend(validate(item, item_schema, path=item_path))

    return errors


def is_valid(data: Any, schema: dict) -> bool:
    """Return True if *data* validates against *schema*."""
    return len(validate(data, schema)) == 0


def _check_type(data: Any, schema_type: str | list) -> bool:
    """Check if data matches the JSON Schema type(s)."""
    if isinstance(schema_type, list):
        return any(_check_type(data, t) for t in schema_type)

    type_map = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
        "null": type(None),
    }

    expected = type_map.get(schema_type)
    if expected is None:
        return True  # unknown type, skip

    if schema_type == "integer" and isinstance(data, bool):
        return False  # bool is subclass of int in Python
    if schema_type == "number" and isinstance(data, bool):
        return False

    return isinstance(data, expected)
