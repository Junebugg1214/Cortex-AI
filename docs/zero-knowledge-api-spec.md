# Zero-Knowledge Memory API Spec (Draft v1)

This spec defines a local-first, zero-knowledge sync model for user-owned memory/identity data.

Goals:
- User device is the plaintext source of truth.
- Cloud relay stores ciphertext and metadata only.
- Creator/operator cannot read user memory.
- Scoped sharing via signed grants.

## 1. Components

1. `Vault Client` (local app/agent)
- Generates and manages user keys.
- Encrypts/decrypts all memory objects.
- Signs manifests and grants.

2. `Sync Relay` (cloud API)
- Stores encrypted objects and signed manifests.
- Never receives plaintext memory or unwrapped DEKs.

3. `Policy Gateway` (optional cloud or local)
- Verifies signed grants.
- Enforces policy scope (technical/professional/minimal/custom).

## 2. Crypto Profile

- Object encryption: `XChaCha20-Poly1305` (preferred) or `AES-256-GCM`.
- Signatures: `Ed25519`.
- Passphrase KDF (if used): `Argon2id`.
- All ciphertext payloads are AEAD-encrypted.

## 3. API Base and Auth

Base path:
- `/v1`

Transport:
- HTTPS required in production.

Auth models:
1. Owner session token (`Authorization: Bearer <owner_token>`)
- Used for writing objects/manifests and creating revocations.

2. Capability grant token (`Authorization: Bearer <grant_token>`)
- Used by connectors/agents for read access per policy.

## 4. Common Envelope Schemas

### 4.1 Error

```json
{
  "$id": "Error",
  "type": "object",
  "required": ["error"],
  "properties": {
    "error": {
      "type": "object",
      "required": ["code", "message"],
      "properties": {
        "code": { "type": "string" },
        "message": { "type": "string" },
        "hint": { "type": "string" }
      },
      "additionalProperties": false
    }
  },
  "additionalProperties": false
}
```

### 4.2 EncryptedObject

```json
{
  "$id": "EncryptedObject",
  "type": "object",
  "required": [
    "object_id",
    "owner_did",
    "stream",
    "version",
    "alg",
    "nonce",
    "ciphertext",
    "aad_hash",
    "ciphertext_hash",
    "created_at"
  ],
  "properties": {
    "object_id": { "type": "string", "pattern": "^[a-zA-Z0-9._:-]{1,128}$" },
    "owner_did": { "type": "string" },
    "stream": { "type": "string", "enum": ["memory", "profile", "connector"] },
    "version": { "type": "integer", "minimum": 1 },
    "alg": { "type": "string", "enum": ["xchacha20poly1305", "aes256gcm"] },
    "nonce": { "type": "string", "description": "base64url nonce" },
    "ciphertext": { "type": "string", "description": "base64url ciphertext+tag" },
    "aad_hash": { "type": "string", "description": "sha256 of canonical AAD JSON" },
    "ciphertext_hash": { "type": "string", "description": "sha256 of ciphertext bytes" },
    "dek_wrap": {
      "type": "object",
      "required": ["kid", "wrapped_key"],
      "properties": {
        "kid": { "type": "string" },
        "wrapped_key": { "type": "string", "description": "base64url wrapped DEK" }
      },
      "additionalProperties": false
    },
    "created_at": { "type": "string", "format": "date-time" },
    "metadata": { "type": "object" }
  },
  "additionalProperties": false
}
```

### 4.3 Manifest

```json
{
  "$id": "Manifest",
  "type": "object",
  "required": [
    "manifest_id",
    "owner_did",
    "stream",
    "sequence",
    "object_refs",
    "issued_at",
    "signature"
  ],
  "properties": {
    "manifest_id": { "type": "string" },
    "owner_did": { "type": "string" },
    "stream": { "type": "string", "enum": ["memory", "profile", "connector"] },
    "sequence": { "type": "integer", "minimum": 1 },
    "prev_manifest_id": { "type": "string" },
    "object_refs": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["object_id", "version", "ciphertext_hash"],
        "properties": {
          "object_id": { "type": "string" },
          "version": { "type": "integer", "minimum": 1 },
          "ciphertext_hash": { "type": "string" }
        },
        "additionalProperties": false
      }
    },
    "issued_at": { "type": "string", "format": "date-time" },
    "signature": { "type": "string", "description": "base64url Ed25519 signature over canonical manifest payload" }
  },
  "additionalProperties": false
}
```

### 4.4 GrantTokenClaims

```json
{
  "$id": "GrantTokenClaims",
  "type": "object",
  "required": ["grant_id", "sub", "aud", "policy", "scopes", "iat", "exp", "nonce"],
  "properties": {
    "grant_id": { "type": "string" },
    "sub": { "type": "string", "description": "owner DID" },
    "aud": { "type": "string", "description": "consumer app/connector id" },
    "policy": { "type": "string", "enum": ["minimal", "professional", "technical", "full", "custom"] },
    "custom_tags": { "type": "array", "items": { "type": "string" } },
    "scopes": { "type": "array", "items": { "type": "string" } },
    "iat": { "type": "integer" },
    "exp": { "type": "integer" },
    "nonce": { "type": "string" }
  },
  "additionalProperties": false
}
```

### 4.5 RevocationEntry

```json
{
  "$id": "RevocationEntry",
  "type": "object",
  "required": ["revocation_id", "owner_did", "target_type", "target_id", "created_at", "signature"],
  "properties": {
    "revocation_id": { "type": "string" },
    "owner_did": { "type": "string" },
    "target_type": { "type": "string", "enum": ["grant", "key", "object"] },
    "target_id": { "type": "string" },
    "reason": { "type": "string" },
    "created_at": { "type": "string", "format": "date-time" },
    "signature": { "type": "string" }
  },
  "additionalProperties": false
}
```

## 5. Endpoints

## 5.1 Objects

### `PUT /v1/objects/{object_id}/{version}`
Store one encrypted object version.

Request body:
- `EncryptedObject`

Response `201`:
```json
{
  "status": "stored",
  "object_id": "mem.node.user-123",
  "version": 7
}
```

### `GET /v1/objects/{object_id}/{version}`
Fetch exact encrypted object version.

Response `200`:
- `EncryptedObject`

### `HEAD /v1/objects/{object_id}/{version}`
Existence + hash check without body.

Response headers:
- `ETag: "<ciphertext_hash>"`
- `X-Cortex-Owner-Did`

## 5.2 Manifests

### `POST /v1/manifests`
Append signed manifest entry.

Request body:
- `Manifest`

Response `201`:
```json
{
  "status": "accepted",
  "manifest_id": "m_01JXYZ...",
  "sequence": 42
}
```

### `GET /v1/manifests/{stream}?cursor=<opaque>&limit=100`
List manifests for incremental sync.

Response `200`:
```json
{
  "items": [],
  "next_cursor": "opaque-or-null"
}
```

## 5.3 Grants

### `POST /v1/grants`
Create a signed capability grant.

Request body:
```json
{
  "aud": "connector.openai",
  "policy": "technical",
  "custom_tags": ["technical_expertise", "projects"],
  "scopes": ["memory:read"],
  "ttl_seconds": 3600
}
```

Response `201`:
```json
{
  "grant_id": "g_01JXYZ...",
  "token": "<signed_compact_token>",
  "expires_at": "2026-03-03T01:00:00Z"
}
```

### `POST /v1/grants/verify`
Verify token validity + effective policy (gateway/internal use).

Request:
```json
{ "token": "<signed_compact_token>" }
```

Response `200`:
```json
{
  "valid": true,
  "claims": {},
  "effective_policy": {
    "name": "technical",
    "include_tags": ["technical_expertise", "projects"],
    "exclude_tags": []
  }
}
```

## 5.4 Revocations

### `POST /v1/revocations`
Revoke grant/key/object access.

Request body:
- `RevocationEntry` without server-generated fields allowed as input.

Response `201`:
```json
{
  "status": "revoked",
  "revocation_id": "r_01JXYZ..."
}
```

### `GET /v1/revocations?since=<rfc3339>&limit=1000`
Incremental revocation feed for clients/gateways.

Response `200`:
```json
{
  "items": [],
  "next_since": "2026-03-03T00:00:00Z"
}
```

## 5.5 Policy-Filtered Read API

### `GET /v1/memory/context`
Returns disclosed memory view based on `grant_token` policy.

Query params:
- `format`: `json | compact | markdown`

Response `200`:
- Filtered content only (never raw full graph unless policy permits).

## 6. Status Codes

- `200` OK
- `201` Created
- `400` Invalid payload
- `401` Unauthorized/invalid token
- `403` Token valid but scope/policy denied
- `404` Not found
- `409` Version conflict or manifest sequence gap
- `422` Signature or hash mismatch
- `429` Rate limited
- `500` Server error

## 7. Validation Rules

1. `PUT /objects` rejects if:
- `ciphertext_hash` does not match payload.
- owner DID in token does not match object owner.
- duplicate version with different hash.

2. `POST /manifests` rejects if:
- bad signature.
- non-contiguous sequence.
- referenced objects missing.

3. `POST /grants` rejects if:
- unknown policy.
- `ttl_seconds` out of bounds.
- unsupported scopes requested.

4. `POST /revocations` rejects if:
- invalid owner signature.
- unknown target type.

## 8. Minimal OpenAPI Path Sketch

```yaml
paths:
  /v1/objects/{object_id}/{version}:
    put:
      summary: Store encrypted object
    get:
      summary: Get encrypted object
    head:
      summary: Check encrypted object
  /v1/manifests:
    post:
      summary: Append signed manifest
  /v1/manifests/{stream}:
    get:
      summary: List manifests by stream
  /v1/grants:
    post:
      summary: Create capability grant
  /v1/grants/verify:
    post:
      summary: Verify grant token
  /v1/revocations:
    post:
      summary: Create revocation
    get:
      summary: List revocations
  /v1/memory/context:
    get:
      summary: Read policy-filtered context
```

## 9. Rollout Plan (Incremental)

1. Add encrypted object store and manifest APIs in CaaS.
2. Keep existing `/context` endpoints; front them via `grant_token` policy checks.
3. Add relay mode feature flag: `zero_knowledge_mode=true`.
4. Add local vault client that performs encryption/signing.
5. Migrate existing plaintext graph to encrypted object format (one-time tool).

## 10. Mapping to Existing Cortex Endpoints

- Existing `/context*` remains the disclosed read surface.
- Existing `/api/keys` and grants can evolve into `/v1/grants`.
- Existing policies (`full`, `technical`, `professional`, `minimal`) are reused.
- Existing profile/API-key/session auth can back owner auth until dedicated auth is introduced.

