# Universal Personal AI (UPAI) Protocol Specification

**Version:** 1.0.0
**Status:** Draft
**Date:** 2026-02-15
**Authors:** Cortex-AI Contributors

---

## 1. Abstract

The Universal Personal AI (UPAI) protocol defines a portable, privacy-preserving
data model and interaction layer for personal AI systems. It specifies how
identity graphs, signed envelopes, disclosure policies, and context APIs
interoperate so that an individual's structured knowledge can move between
conforming implementations without loss of fidelity or trust.

This specification draws on W3C Decentralized Identifiers, RFC 8037 (Ed25519),
and established envelope patterns to produce a minimal yet complete protocol
for personal AI interoperability.

### 1.1 Status of This Document

This document is a **Draft** specification. It is subject to change without
notice. Implementers should treat all interfaces as unstable until the
specification reaches Candidate Recommendation status.

---

## 2. Terminology

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD",
"SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be
interpreted as described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

Additional terms used throughout this specification:

- **Node**: A discrete unit of personal knowledge (skill, experience, belief, preference).
- **Edge**: A typed, weighted relationship between two Nodes.
- **CortexGraph**: The complete directed graph of Nodes and Edges belonging to a single identity.
- **Envelope**: A signed, serialized container for transmitting graph data.
- **Disclosure Policy**: A named rule set governing which fields are revealed in a given context.
- **Controller**: The entity (person) who owns and controls a CortexGraph.
- **Consumer**: Any system or agent that reads graph data with the Controller's consent.

---

## 3. Data Model

### 3.1 Node

A Node represents a single piece of structured personal knowledge. Every Node
MUST contain exactly the following 17 fields:

| # | Field | Type | Required | Description |
|---|-------|------|----------|-------------|
| 1 | `id` | string | MUST | Deterministic identifier (see 3.4) |
| 2 | `type` | string | MUST | One of the 17 standard tags (see 3.5) |
| 3 | `label` | string | MUST | Human-readable short name |
| 4 | `description` | string | MUST | Detailed prose description |
| 5 | `source` | string | MUST | Origin system or method of capture |
| 6 | `confidence` | float | MUST | Range [0.0, 1.0] indicating certainty |
| 7 | `weight` | float | MUST | Relative importance, range [0.0, 1.0] |
| 8 | `tags` | string[] | MUST | Array of category tags |
| 9 | `created_at` | string | MUST | ISO 8601 timestamp of creation |
| 10 | `updated_at` | string | MUST | ISO 8601 timestamp of last modification |
| 11 | `version` | integer | MUST | Monotonically increasing version counter |
| 12 | `visibility` | string | MUST | One of: `public`, `protected`, `private` |
| 13 | `context` | string | SHOULD | Situational context for this knowledge |
| 14 | `evidence` | string[] | SHOULD | Supporting references or citations |
| 15 | `expires_at` | string | MAY | ISO 8601 expiration timestamp |
| 16 | `schema_version` | string | MUST | Protocol version that produced this node |
| 17 | `metadata` | object | MAY | Arbitrary key-value extension data |

Example Node:

```json
{
  "id": "a1b2c3d4e5f6g7h8",
  "type": "skill",
  "label": "Distributed Systems Design",
  "description": "Experience designing horizontally scalable microservice architectures with event-driven communication patterns.",
  "source": "linkedin_import",
  "confidence": 0.92,
  "weight": 0.85,
  "tags": ["skill", "engineering", "architecture"],
  "created_at": "2025-06-15T10:30:00Z",
  "updated_at": "2026-01-20T14:22:00Z",
  "version": 3,
  "visibility": "public",
  "context": "professional",
  "evidence": ["https://github.com/user/distributed-project"],
  "expires_at": null,
  "schema_version": "1.0.0",
  "metadata": {
    "years_experience": 7,
    "last_used": "2026-01"
  }
}
```

### 3.2 Edge

An Edge represents a directed, typed relationship between two Nodes. Every Edge
MUST contain exactly the following 8 fields:

| # | Field | Type | Required | Description |
|---|-------|------|----------|-------------|
| 1 | `id` | string | MUST | Deterministic identifier (see 3.4) |
| 2 | `source_id` | string | MUST | ID of the origin Node |
| 3 | `target_id` | string | MUST | ID of the destination Node |
| 4 | `relation` | string | MUST | Relationship type (e.g., `requires`, `enhances`, `contradicts`) |
| 5 | `weight` | float | MUST | Strength of relationship, range [0.0, 1.0] |
| 6 | `context` | string | SHOULD | Situational context for this relationship |
| 7 | `created_at` | string | MUST | ISO 8601 timestamp |
| 8 | `metadata` | object | MAY | Arbitrary extension data |

Example Edge:

```json
{
  "id": "e9f0a1b2c3d4e5f6",
  "source_id": "a1b2c3d4e5f6g7h8",
  "target_id": "b2c3d4e5f6g7h8i9",
  "relation": "requires",
  "weight": 0.75,
  "context": "professional",
  "created_at": "2025-06-15T10:35:00Z",
  "metadata": {}
}
```

### 3.3 CortexGraph

A CortexGraph is the top-level container. It MUST include:

```json
{
  "graph_id": "string (deterministic, see 3.4)",
  "controller": "did:key:z6Mkf5... (see Section 4)",
  "schema_version": "1.0.0",
  "created_at": "ISO 8601",
  "updated_at": "ISO 8601",
  "nodes": [],
  "edges": [],
  "commit_head": "string (see Section 7)"
}
```

### 3.4 Deterministic Identifiers

All `id` fields MUST be computed deterministically using SHA-256 truncated to
16 hex characters. The input to the hash function is the canonical JSON
serialization (RFC 8785) of the object's identity-bearing fields.

For Nodes, the identity-bearing fields are: `type`, `label`, `source`, `created_at`.
For Edges, the identity-bearing fields are: `source_id`, `target_id`, `relation`, `created_at`.

Algorithm:

```
id = SHA-256(canonical_json(identity_fields))[:16]
```

Where `[:16]` denotes the first 16 characters of the lowercase hex digest.

Implementations MUST use RFC 8785 JSON Canonicalization Scheme to ensure
deterministic serialization across platforms.

### 3.5 Standard Tags

Conforming implementations MUST recognize the following 17 standard tags.
Additional tags MAY be used but MUST NOT conflict with these names.

| # | Tag | Description |
|---|-----|-------------|
| 1 | `skill` | Technical or professional capability |
| 2 | `experience` | Work history or life event |
| 3 | `belief` | Core value or conviction |
| 4 | `preference` | Personal taste or favored approach |
| 5 | `goal` | Aspiration or target outcome |
| 6 | `education` | Formal learning or certification |
| 7 | `relationship` | Interpersonal connection |
| 8 | `health` | Physical or mental health data |
| 9 | `financial` | Financial information or preference |
| 10 | `location` | Geographic association |
| 11 | `project` | A body of work or initiative |
| 12 | `interest` | Hobby or area of curiosity |
| 13 | `achievement` | Award, milestone, or accomplishment |
| 14 | `communication` | Communication style or preference |
| 15 | `personality` | Trait, tendency, or behavioral pattern |
| 16 | `constraint` | Limitation, restriction, or boundary |
| 17 | `context` | Situational or environmental factor |

---

## 4. Identity

### 4.1 DID Method: `did:key`

UPAI uses the `did:key` method for decentralized identity. Controllers MUST
generate an Ed25519 keypair and encode the public key using the multicodec
prefix `0xed01` followed by base58btc encoding with the `z` prefix.

Format:

```
did:key:z6Mk<base58btc-encoded-ed25519-public-key>
```

Example:

```
did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK
```

### 4.2 DID Document

The DID Document MUST conform to W3C DID Core v1.0. A minimal conforming
document:

```json
{
  "@context": [
    "https://www.w3.org/ns/did/v1",
    "https://w3id.org/security/suites/ed25519-2020/v1"
  ],
  "id": "did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK",
  "authentication": [
    {
      "id": "did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK#keys-1",
      "type": "Ed25519VerificationKey2020",
      "controller": "did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK",
      "publicKeyMultibase": "z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK"
    }
  ],
  "service": [
    {
      "id": "did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK#upai",
      "type": "UPAIContextService",
      "serviceEndpoint": "https://example.com/.well-known/upai-configuration"
    }
  ]
}
```

### 4.3 Key Lifecycle

Controllers SHOULD implement key rotation by publishing a new DID Document
with the updated key material. The previous key MUST be moved to a
`revoked_keys` list within the Controller's local configuration.

Key states:

- **active**: Current signing key. Exactly one key MUST be active at any time.
- **rotated**: Previous key replaced by a newer one. MUST NOT be used for signing.
- **revoked**: Key compromised or decommissioned. MUST be rejected on verification.

### 4.4 HMAC Fallback

In environments where Ed25519 is unavailable (e.g., constrained runtimes),
implementations MAY use HMAC-SHA256 for envelope integrity. When HMAC is used:

- The `alg` header field MUST be set to `"HS256"`.
- The shared secret MUST be at least 256 bits.
- The implementation MUST clearly document that authenticity is limited to
  parties sharing the secret.
- HMAC envelopes MUST NOT be used for inter-party disclosure; they are
  valid only for local integrity checking.

---

## 5. Signed Envelopes

### 5.1 Structure

A signed envelope is a three-part base64url-encoded string:

```
<header>.<payload>.<signature>
```

Each part is independently base64url-encoded (RFC 4648 Section 5, no padding).

### 5.2 Header

The header MUST contain:

```json
{
  "alg": "EdDSA",
  "typ": "upai-envelope+json",
  "kid": "did:key:z6Mk...#keys-1"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `alg` | string | MUST | `"EdDSA"` for Ed25519, `"HS256"` for HMAC fallback |
| `typ` | string | MUST | `"upai-envelope+json"` |
| `kid` | string | MUST | Key ID referencing the DID Document verification method |

### 5.3 Payload

The payload MUST contain:

```json
{
  "data": { },
  "nonce": "unique-random-string",
  "iat": 1708000000,
  "exp": 1708003600,
  "aud": "did:key:z6Mk..."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `data` | object | MUST | The CortexGraph, Node, Edge, or partial projection |
| `nonce` | string | MUST | Cryptographically random, minimum 128 bits entropy |
| `iat` | integer | MUST | Issued-at Unix timestamp (seconds) |
| `exp` | integer | MUST | Expiration Unix timestamp (seconds) |
| `aud` | string | SHOULD | Intended recipient DID |

### 5.4 Signature

The signature is computed over `base64url(header) + "." + base64url(payload)`
using the algorithm specified in the header.

### 5.5 Replay Protection

Consumers MUST maintain a nonce cache and reject any envelope whose `nonce`
has been previously seen within the envelope's validity window (`iat` to `exp`).

The nonce cache MUST retain entries for at least `max_envelope_lifetime`
seconds (default: 3600). Implementations SHOULD use a time-bounded set or
bloom filter for efficient lookup.

An envelope MUST be rejected if:

1. `exp` is in the past (clock skew tolerance: 30 seconds).
2. `iat` is more than 60 seconds in the future.
3. `exp - iat` exceeds `max_envelope_lifetime`.
4. The `nonce` has been seen before within the validity window.

---

## 6. Disclosure

### 6.1 DisclosurePolicy Schema

A DisclosurePolicy defines which Node fields and Edge data are included when
the CortexGraph is projected for a specific audience.

```json
{
  "policy_id": "string",
  "name": "string",
  "description": "string",
  "version": "1.0.0",
  "node_fields": ["list of included Node field names"],
  "edge_included": true,
  "visibility_filter": ["public"],
  "tag_filter": ["list of allowed tags or '*' for all"],
  "confidence_min": 0.0,
  "weight_min": 0.0,
  "max_nodes": null,
  "strip_metadata_keys": []
}
```

### 6.2 Built-in Policies

Conforming implementations MUST support the following 4 built-in policies:

#### 6.2.1 `full`

All fields, all visibility levels, all tags, no filtering. Intended for
Controller-only access and full backups.

```json
{
  "policy_id": "full",
  "name": "Full Disclosure",
  "node_fields": ["*"],
  "edge_included": true,
  "visibility_filter": ["public", "protected", "private"],
  "tag_filter": ["*"],
  "confidence_min": 0.0,
  "weight_min": 0.0,
  "max_nodes": null,
  "strip_metadata_keys": []
}
```

#### 6.2.2 `professional`

Public and protected fields relevant to professional contexts. Excludes
health, financial, and private relationship data.

```json
{
  "policy_id": "professional",
  "name": "Professional Disclosure",
  "node_fields": ["id", "type", "label", "description", "source", "confidence", "weight", "tags", "created_at", "updated_at", "version", "visibility", "context", "evidence", "schema_version"],
  "edge_included": true,
  "visibility_filter": ["public", "protected"],
  "tag_filter": ["skill", "experience", "education", "project", "achievement", "interest", "communication", "personality", "goal"],
  "confidence_min": 0.5,
  "weight_min": 0.0,
  "max_nodes": null,
  "strip_metadata_keys": []
}
```

#### 6.2.3 `technical`

Focused on skills, projects, and technical competencies. Minimal personal data.

```json
{
  "policy_id": "technical",
  "name": "Technical Disclosure",
  "node_fields": ["id", "type", "label", "description", "confidence", "weight", "tags", "version", "schema_version", "metadata"],
  "edge_included": true,
  "visibility_filter": ["public"],
  "tag_filter": ["skill", "project", "education", "achievement"],
  "confidence_min": 0.6,
  "weight_min": 0.3,
  "max_nodes": 100,
  "strip_metadata_keys": ["personal_notes"]
}
```

#### 6.2.4 `minimal`

Only public labels and types. No descriptions, evidence, or metadata.

```json
{
  "policy_id": "minimal",
  "name": "Minimal Disclosure",
  "node_fields": ["id", "type", "label", "tags", "schema_version"],
  "edge_included": false,
  "visibility_filter": ["public"],
  "tag_filter": ["skill", "experience", "education", "project"],
  "confidence_min": 0.7,
  "weight_min": 0.5,
  "max_nodes": 25,
  "strip_metadata_keys": ["*"]
}
```

### 6.3 Filtering Algorithm

The disclosure filtering algorithm MUST execute the following 12 steps in order:

1. **Clone**: Deep-copy the full CortexGraph to avoid mutating the source.
2. **Visibility filter**: Remove all Nodes whose `visibility` is not in `visibility_filter`.
3. **Tag filter**: If `tag_filter` is not `["*"]`, remove Nodes whose `type` is not in `tag_filter`.
4. **Confidence threshold**: Remove Nodes with `confidence` below `confidence_min`.
5. **Weight threshold**: Remove Nodes with `weight` below `weight_min`.
6. **Expiration check**: Remove Nodes whose `expires_at` is non-null and in the past.
7. **Edge pruning**: Remove Edges where `source_id` or `target_id` references a removed Node.
8. **Edge inclusion**: If `edge_included` is `false`, remove all Edges.
9. **Field projection**: For each remaining Node, retain only fields listed in `node_fields` (or all if `["*"]`).
10. **Metadata stripping**: Remove keys in `strip_metadata_keys` from each Node's `metadata` (or all keys if `["*"]`).
11. **Node cap**: If `max_nodes` is non-null and the count exceeds it, sort by `weight` descending, then `confidence` descending, and truncate.
12. **Seal**: Wrap the projected graph in a signed envelope (Section 5) bound to the requesting Consumer's DID.

---

## 7. Version Control

UPAI provides a lightweight, Git-inspired version control system for CortexGraph
mutations. Implementations at the Signed conformance level (Section 11) SHOULD
support these operations.

### 7.1 Commit

A commit captures a snapshot of the graph state.

```json
{
  "commit_id": "SHA-256[:16] of commit content",
  "parent_id": "previous commit_id or null for initial",
  "timestamp": "ISO 8601",
  "author": "did:key:z6Mk...",
  "message": "string describing the change",
  "operations": [
    {
      "op": "add_node",
      "node": { }
    },
    {
      "op": "update_node",
      "node_id": "string",
      "fields": { "key": "new_value" }
    },
    {
      "op": "delete_node",
      "node_id": "string"
    },
    {
      "op": "add_edge",
      "edge": { }
    },
    {
      "op": "delete_edge",
      "edge_id": "string"
    }
  ]
}
```

Valid operations: `add_node`, `update_node`, `delete_node`, `add_edge`,
`update_edge`, `delete_edge`.

### 7.2 Log

Returns the commit history as an ordered array from most recent to oldest.

```
GET /api/v1/graph/log?limit=50&offset=0
```

Response:

```json
{
  "commits": [
    {
      "commit_id": "a1b2c3d4e5f6g7h8",
      "parent_id": "z9y8x7w6v5u4t3s2",
      "timestamp": "2026-02-15T10:00:00Z",
      "author": "did:key:z6Mk...",
      "message": "Add distributed systems skill node"
    }
  ],
  "total": 142,
  "has_more": true
}
```

### 7.3 Diff

Computes the difference between two commits.

```
GET /api/v1/graph/diff?from={commit_id}&to={commit_id}
```

Response:

```json
{
  "from_commit": "z9y8x7w6v5u4t3s2",
  "to_commit": "a1b2c3d4e5f6g7h8",
  "operations": [
    {
      "op": "add_node",
      "node": { }
    }
  ],
  "stats": {
    "nodes_added": 1,
    "nodes_updated": 0,
    "nodes_deleted": 0,
    "edges_added": 2,
    "edges_updated": 0,
    "edges_deleted": 0
  }
}
```

### 7.4 Checkout

Restores the graph to the state at a specific commit. This creates a new commit
recording the restoration.

```
POST /api/v1/graph/checkout
```

```json
{
  "commit_id": "z9y8x7w6v5u4t3s2",
  "message": "Revert to pre-migration state"
}
```

---

## 8. Context-as-a-Service API

### 8.1 Base URL

All API endpoints are relative to the base URL discovered via the
`.well-known/upai-configuration` document (Section 9).

```
https://api.example.com/api/v1
```

### 8.2 Authentication Model

All API requests MUST include a signed envelope as a Bearer token:

```
Authorization: Bearer <signed-envelope>
```

The envelope's `aud` field MUST match the server's DID. The server MUST
validate the envelope signature, expiration, and nonce before processing.

Token scopes:

| Scope | Description |
|-------|-------------|
| `graph:read` | Read graph data with disclosure policy |
| `graph:write` | Mutate graph data (add, update, delete) |
| `graph:admin` | Full access including version control and policy management |
| `disclosure:read` | Read available disclosure policies |
| `disclosure:write` | Create or modify disclosure policies |

### 8.3 Endpoints

#### 8.3.1 Graph Operations

**Get Graph (with disclosure)**

```
GET /api/v1/graph?policy={policy_id}
```

Scope: `graph:read`

Returns the CortexGraph filtered through the specified disclosure policy.
If no policy is specified, the server MUST use the `minimal` policy for
external consumers and `full` for the Controller.

**Update Graph (batch)**

```
POST /api/v1/graph/commit
```

Scope: `graph:write`

Request body: A commit object (Section 7.1).

#### 8.3.2 Node Operations

**List Nodes**

```
GET /api/v1/nodes?type={tag}&limit=50&offset=0
```

Scope: `graph:read`

**Get Node**

```
GET /api/v1/nodes/{node_id}
```

Scope: `graph:read`

**Create Node**

```
POST /api/v1/nodes
```

Scope: `graph:write`

**Update Node**

```
PATCH /api/v1/nodes/{node_id}
```

Scope: `graph:write`

**Delete Node**

```
DELETE /api/v1/nodes/{node_id}
```

Scope: `graph:write`

#### 8.3.3 Edge Operations

**List Edges**

```
GET /api/v1/edges?source_id={id}&target_id={id}&limit=50&offset=0
```

Scope: `graph:read`

**Create Edge**

```
POST /api/v1/edges
```

Scope: `graph:write`

**Delete Edge**

```
DELETE /api/v1/edges/{edge_id}
```

Scope: `graph:write`

#### 8.3.4 Disclosure Operations

**List Policies**

```
GET /api/v1/policies
```

Scope: `disclosure:read`

**Get Policy**

```
GET /api/v1/policies/{policy_id}
```

Scope: `disclosure:read`

**Create Policy**

```
POST /api/v1/policies
```

Scope: `disclosure:write`

#### 8.3.5 Version Control Operations

**Get Log**

```
GET /api/v1/graph/log?limit=50&offset=0
```

Scope: `graph:read`

**Get Diff**

```
GET /api/v1/graph/diff?from={commit_id}&to={commit_id}
```

Scope: `graph:read`

**Checkout**

```
POST /api/v1/graph/checkout
```

Scope: `graph:admin`

#### 8.3.6 Identity Operations

**Get DID Document**

```
GET /api/v1/identity/did
```

Scope: none (public)

**Rotate Key**

```
POST /api/v1/identity/rotate
```

Scope: `graph:admin`

### 8.4 Pagination

All list endpoints MUST support cursor-based or offset-based pagination:

```json
{
  "data": [],
  "pagination": {
    "total": 142,
    "limit": 50,
    "offset": 0,
    "has_more": true
  }
}
```

The `limit` parameter MUST NOT exceed 200. The default MUST be 50.

### 8.5 Error Codes

All errors MUST be returned as JSON with the following structure:

```json
{
  "error": {
    "code": "UPAI-4001",
    "type": "invalid_token",
    "message": "Human-readable description",
    "details": {}
  }
}
```

The complete error code table:

| Code | Type | HTTP | Description |
|------|------|------|-------------|
| UPAI-4001 | `invalid_token` | 401 | Token malformed, expired, or invalid signature |
| UPAI-4002 | `insufficient_scope` | 403 | Token lacks required scope for this operation |
| UPAI-4003 | `not_found` | 404 | Requested resource does not exist |
| UPAI-4004 | `invalid_request` | 400 | Malformed request body or parameters |
| UPAI-4005 | `invalid_policy` | 400 | Unknown or invalid disclosure policy referenced |
| UPAI-4006 | `schema_validation` | 400 | Request data fails JSON Schema validation |
| UPAI-4007 | `revoked_key` | 401 | The signing key has been revoked |
| UPAI-4008 | `replay_detected` | 400 | The envelope nonce has already been consumed |
| UPAI-5001 | `internal_error` | 500 | Unexpected server error |
| UPAI-5002 | `not_configured` | 503 | Server is not fully configured or initialized |

Error responses MUST include the appropriate HTTP status code and the
`Content-Type: application/json` header.

---

## 9. Discovery

### 9.1 Well-Known Configuration

Conforming servers MUST serve a JSON document at:

```
GET /.well-known/upai-configuration
```

The document MUST contain:

```json
{
  "issuer": "did:key:z6Mk...",
  "api_base": "https://api.example.com/api/v1",
  "schema_version": "1.0.0",
  "supported_policies": ["full", "professional", "technical", "minimal"],
  "supported_scopes": ["graph:read", "graph:write", "graph:admin", "disclosure:read", "disclosure:write"],
  "signing_algorithms": ["EdDSA"],
  "max_envelope_lifetime": 3600,
  "did_document_url": "https://api.example.com/api/v1/identity/did",
  "endpoints": {
    "graph": "/api/v1/graph",
    "nodes": "/api/v1/nodes",
    "edges": "/api/v1/edges",
    "policies": "/api/v1/policies",
    "log": "/api/v1/graph/log",
    "diff": "/api/v1/graph/diff",
    "checkout": "/api/v1/graph/checkout"
  }
}
```

### 9.2 DID Document Service Endpoints

Controllers SHOULD include a service endpoint in their DID Document pointing
to their UPAI configuration:

```json
{
  "id": "did:key:z6Mk...#upai-service",
  "type": "UPAIContextService",
  "serviceEndpoint": "https://example.com/.well-known/upai-configuration"
}
```

This enables any party with the Controller's DID to discover their UPAI
service automatically.

---

## 10. Security Considerations

### 10.1 Transport Security

All UPAI communications MUST use TLS 1.2 or later. TLS 1.3 is RECOMMENDED.
Implementations MUST reject connections using TLS versions below 1.2.

Cipher suite requirements:
- MUST support `TLS_AES_128_GCM_SHA256`.
- SHOULD support `TLS_AES_256_GCM_SHA384`.
- MUST NOT use cipher suites with known vulnerabilities (RC4, DES, export ciphers).

### 10.2 Nonce Cache

The nonce cache is critical for replay protection. Implementations:

- MUST store nonces for at least `max_envelope_lifetime` seconds.
- SHOULD use a time-partitioned data structure for efficient expiration.
- MUST be resilient to restart (persist to disk or accept a brief replay
  window on cold start, documented as a known limitation).
- SHOULD monitor cache size and alert if growth is anomalous (potential
  denial-of-service via nonce flooding).

### 10.3 Key Storage

Private keys MUST be stored securely:

- On servers: Use HSM, KMS, or encrypted-at-rest key stores.
- On clients: Use OS keychain (macOS Keychain, Windows DPAPI, Linux
  Secret Service) or hardware security keys.
- Private keys MUST NOT be logged, transmitted, or stored in plaintext.
- Private keys MUST NOT appear in environment variables in production.

### 10.4 Grant Lifetime

Envelope expiration (`exp - iat`) MUST NOT exceed the server's
`max_envelope_lifetime` (default: 3600 seconds). Implementations:

- SHOULD use short-lived envelopes (300 seconds) for routine operations.
- MAY use longer lifetimes (up to 3600 seconds) for batch operations.
- MUST reject envelopes with lifetimes exceeding the configured maximum.

### 10.5 Webhook Verification

If implementations support webhooks for graph change notifications:

- Webhook payloads MUST be delivered as signed envelopes.
- Recipients MUST verify the envelope signature before processing.
- Recipients SHOULD verify the `aud` field matches their own DID.
- Webhook endpoints MUST use HTTPS.
- Implementations SHOULD implement exponential backoff for delivery retries.

### 10.6 Rate Limiting

Servers SHOULD implement rate limiting to prevent abuse:

- Per-DID rate limits for authenticated requests.
- Global rate limits for unauthenticated endpoints (discovery, DID Document).
- Rate limit headers (`X-RateLimit-Limit`, `X-RateLimit-Remaining`,
  `X-RateLimit-Reset`) SHOULD be included in responses.

---

## 11. Conformance

UPAI defines three conformance levels. Each level builds on the previous.

### 11.1 Level 1: Core (MUST)

A Core-conformant implementation MUST:

- Implement the full Node schema (17 fields) and Edge schema (8 fields).
- Generate deterministic IDs via SHA-256[:16] using RFC 8785 canonicalization.
- Recognize all 17 standard tags.
- Support the CortexGraph container structure.
- Implement all 4 built-in disclosure policies.
- Execute the 12-step filtering algorithm correctly.
- Validate inputs against the JSON Schemas defined in Appendix A.
- Return errors using the UPAI error code format.

### 11.2 Level 2: Signed (SHOULD)

A Signed-conformant implementation MUST satisfy Level 1 and additionally SHOULD:

- Generate and verify `did:key` identities with Ed25519.
- Produce and consume signed envelopes (three-part base64url).
- Implement replay protection with nonce caching.
- Support envelope expiration validation.
- Implement the version control operations (commit, log, diff, checkout).
- Serve a DID Document conforming to W3C DID Core.

### 11.3 Level 3: Networked (MAY)

A Networked-conformant implementation MUST satisfy Level 2 and MAY additionally:

- Serve the Context-as-a-Service API (Section 8) over HTTPS.
- Publish `.well-known/upai-configuration` for discovery.
- Implement webhook notifications for graph mutations.
- Support multi-Consumer access with scoped tokens.
- Implement key rotation via the identity API.
- Support federated graph queries across multiple UPAI servers.

---

## 12. Appendix

### Appendix A: JSON Schema Definitions (Normative)

The following JSON Schema definitions are normative. Conforming implementations
MUST validate data against these schemas.

#### A.1 Node Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://upai.dev/schemas/v1/node.json",
  "title": "UPAI Node",
  "type": "object",
  "required": [
    "id", "type", "label", "description", "source", "confidence",
    "weight", "tags", "created_at", "updated_at", "version",
    "visibility", "schema_version"
  ],
  "properties": {
    "id": { "type": "string", "pattern": "^[a-f0-9]{16}$" },
    "type": { "type": "string", "enum": [
      "skill", "experience", "belief", "preference", "goal",
      "education", "relationship", "health", "financial", "location",
      "project", "interest", "achievement", "communication",
      "personality", "constraint", "context"
    ]},
    "label": { "type": "string", "minLength": 1, "maxLength": 256 },
    "description": { "type": "string", "maxLength": 4096 },
    "source": { "type": "string", "minLength": 1 },
    "confidence": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
    "weight": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
    "tags": { "type": "array", "items": { "type": "string" } },
    "created_at": { "type": "string", "format": "date-time" },
    "updated_at": { "type": "string", "format": "date-time" },
    "version": { "type": "integer", "minimum": 1 },
    "visibility": { "type": "string", "enum": ["public", "protected", "private"] },
    "context": { "type": "string" },
    "evidence": { "type": "array", "items": { "type": "string", "format": "uri" } },
    "expires_at": { "type": ["string", "null"], "format": "date-time" },
    "schema_version": { "type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$" },
    "metadata": { "type": "object" }
  },
  "additionalProperties": false
}
```

#### A.2 Edge Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://upai.dev/schemas/v1/edge.json",
  "title": "UPAI Edge",
  "type": "object",
  "required": ["id", "source_id", "target_id", "relation", "weight", "created_at"],
  "properties": {
    "id": { "type": "string", "pattern": "^[a-f0-9]{16}$" },
    "source_id": { "type": "string", "pattern": "^[a-f0-9]{16}$" },
    "target_id": { "type": "string", "pattern": "^[a-f0-9]{16}$" },
    "relation": { "type": "string", "minLength": 1 },
    "weight": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
    "context": { "type": "string" },
    "created_at": { "type": "string", "format": "date-time" },
    "metadata": { "type": "object" }
  },
  "additionalProperties": false
}
```

#### A.3 DisclosurePolicy Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://upai.dev/schemas/v1/disclosure-policy.json",
  "title": "UPAI Disclosure Policy",
  "type": "object",
  "required": ["policy_id", "name", "node_fields", "edge_included", "visibility_filter", "tag_filter"],
  "properties": {
    "policy_id": { "type": "string", "pattern": "^[a-z][a-z0-9_-]*$" },
    "name": { "type": "string" },
    "description": { "type": "string" },
    "version": { "type": "string" },
    "node_fields": { "type": "array", "items": { "type": "string" } },
    "edge_included": { "type": "boolean" },
    "visibility_filter": {
      "type": "array",
      "items": { "type": "string", "enum": ["public", "protected", "private"] }
    },
    "tag_filter": { "type": "array", "items": { "type": "string" } },
    "confidence_min": { "type": "number", "minimum": 0.0, "maximum": 1.0, "default": 0.0 },
    "weight_min": { "type": "number", "minimum": 0.0, "maximum": 1.0, "default": 0.0 },
    "max_nodes": { "type": ["integer", "null"], "minimum": 1 },
    "strip_metadata_keys": { "type": "array", "items": { "type": "string" }, "default": [] }
  },
  "additionalProperties": false
}
```

### Appendix B: Example Flows (Informative)

#### B.1 Consumer Discovers and Queries a Controller's Graph

1. Consumer resolves Controller's DID to obtain DID Document.
2. Consumer extracts the `UPAIContextService` endpoint from `service`.
3. Consumer fetches `/.well-known/upai-configuration` to learn API base and supported policies.
4. Consumer creates a signed envelope with `aud` set to Controller's DID and scope `graph:read`.
5. Consumer sends `GET /api/v1/graph?policy=professional` with the envelope as Bearer token.
6. Server validates envelope (signature, nonce, expiration, scope).
7. Server applies the `professional` disclosure policy (12-step algorithm).
8. Server wraps the filtered graph in a response envelope signed by the server's DID.
9. Consumer verifies the response envelope and processes the projected graph.

#### B.2 Controller Commits a New Skill Node

1. Controller creates a Node object with all 17 required fields.
2. Controller computes the deterministic `id` via SHA-256[:16].
3. Controller constructs a commit with `op: "add_node"`.
4. Controller wraps the commit in a signed envelope with scope `graph:write`.
5. Controller sends `POST /api/v1/graph/commit`.
6. Server validates, applies the commit, updates `commit_head`.
7. Server returns the new commit ID and updated graph metadata.

#### B.3 Key Rotation

1. Controller generates a new Ed25519 keypair.
2. Controller constructs a key rotation request signed with the **current** key.
3. Controller sends `POST /api/v1/identity/rotate` with the new public key.
4. Server verifies the request using the current key.
5. Server updates the DID Document: new key becomes `active`, old key becomes `rotated`.
6. Server returns the updated DID Document.
7. All subsequent envelopes MUST be signed with the new key.

---

## References

- [RFC 2119] Bradner, S., "Key words for use in RFCs to Indicate Requirement Levels", BCP 14, RFC 2119, March 1997.
- [RFC 4648] Josefsson, S., "The Base16, Base32, and Base64 Data Encodings", RFC 4648, October 2006.
- [RFC 8037] Liusvaara, I., "CFRG Elliptic Curve Diffie-Hellman (ECDH) and Signatures in JSON Object Signing and Encryption (JOSE)", RFC 8037, January 2017.
- [RFC 8785] Rundgren, A., Jordan, B., Erdtman, S., "JSON Canonicalization Scheme (JCS)", RFC 8785, June 2020.
- [W3C DID Core] Sporny, M., et al., "Decentralized Identifiers (DIDs) v1.0", W3C Recommendation, July 2022.
- [did:key Method] Multiformats, "did:key Method Specification", https://w3c-ccg.github.io/did-method-key/.

---

*End of specification.*
