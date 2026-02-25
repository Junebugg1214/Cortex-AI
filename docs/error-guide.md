# Error Reference

Complete reference for all 17 UPAI error codes. Every error response from the Cortex CaaS API follows the same JSON structure:

```json
{
  "error": {
    "code": "UPAI-4001",
    "type": "invalid_token",
    "message": "Token is malformed, expired, or has invalid signature",
    "details": {},
    "hint": "Check that the token is not expired, the signature matches the server's DID, and the token includes a valid nonce.",
    "request_id": "req_a1b2c3d4"
  }
}
```

The `hint` field provides actionable suggestions (powered by fuzzy-matching when applicable). The `request_id` field appears when request correlation is enabled.

---

## Client Errors (4xx)

### UPAI-4001 — `invalid_token`

| | |
|---|---|
| **HTTP Status** | 401 Unauthorized |
| **Message** | Token is malformed, expired, or has invalid signature |

**Common causes:**
- The grant token has expired (check the `exp` claim)
- The token was signed by a different identity than the server
- The token string is truncated or corrupted
- Missing `Authorization: Bearer <token>` header

**How to fix:**
1. Create a new grant: `cortex grant --create --audience "..." --policy professional`
2. Verify the token hasn't expired: check the grant's `expires_at` field
3. Ensure you're connecting to the same server that issued the token

---

### UPAI-4002 — `insufficient_scope`

| | |
|---|---|
| **HTTP Status** | 403 Forbidden |
| **Message** | Token lacks required scope: `{required}` |

**Common causes:**
- The grant was created with limited scopes (e.g., `context:read` only) but the request needs a different scope
- Attempting a write operation with a read-only token

**How to fix:**
1. Create a new grant with the needed scopes: `cortex grant --create --audience "..." --scopes context:read,versions:read,grants:manage`
2. Check valid scopes: `context:read`, `context:write`, `versions:read`, `identity:read`, `credentials:*`, `webhooks:manage`, `policies:manage`, `grants:manage`, `devices:manage`

---

### UPAI-4003 — `not_found`

| | |
|---|---|
| **HTTP Status** | 404 Not Found |
| **Message** | `{resource}` not found |

**Common causes:**
- The resource ID is incorrect or has a typo
- The resource was deleted or revoked
- Using a node/version/grant ID from a different server instance

**How to fix:**
1. Verify the resource ID is correct
2. List available resources: `GET /context/nodes`, `GET /grants`, `GET /versions`
3. Check if the resource was deleted (it may return 410 Gone instead)

---

### UPAI-4004 — `invalid_request`

| | |
|---|---|
| **HTTP Status** | 400 Bad Request |
| **Message** | Request body is malformed |

**Common causes:**
- Invalid JSON in the request body
- Missing required fields (e.g., `audience` when creating a grant)
- Wrong data types (e.g., string where number expected)

**How to fix:**
1. Validate your JSON: `echo '{"audience":"test"}' | python3 -m json.tool`
2. Check the API docs at `/docs` (Swagger UI) for required fields
3. Ensure `Content-Type: application/json` header is set

---

### UPAI-4005 — `invalid_policy`

| | |
|---|---|
| **HTTP Status** | 400 Bad Request |
| **Message** | Unknown disclosure policy: `{policy}` |

**Common causes:**
- Typo in the policy name
- Using a custom policy name that hasn't been created yet

**How to fix:**
1. Check the hint — it uses fuzzy matching to suggest the closest valid policy
2. Built-in policies: `full`, `professional`, `technical`, `minimal`
3. List all policies: `GET /policies` or `cortex policy --list`
4. Create a custom policy: `POST /policies`

---

### UPAI-4006 — `schema_validation`

| | |
|---|---|
| **HTTP Status** | 400 Bad Request |
| **Message** | Data fails schema validation |

**Common causes:**
- Webhook URL is not a valid HTTPS URL
- Grant `ttl_hours` is not a positive integer
- Node data doesn't conform to the graph schema

**How to fix:**
1. Check `details.validation_errors` in the response for specific field errors
2. Review the OpenAPI spec at `spec/openapi.json` for field constraints
3. Ensure URLs use HTTPS (not HTTP) for webhook registrations

---

### UPAI-4007 — `revoked_key`

| | |
|---|---|
| **HTTP Status** | 401 Unauthorized |
| **Message** | Signing key `{did}` has been revoked |

**Common causes:**
- The server's signing key was rotated and the old key is revoked
- The token was signed with a key that has since been revoked

**How to fix:**
1. Create a new grant token (it will be signed with the current active key)
2. Check the server's DID document: `GET /identity`

---

### UPAI-4008 — `replay_detected`

| | |
|---|---|
| **HTTP Status** | 400 Bad Request |
| **Message** | Nonce has already been used |

**Common causes:**
- Replaying a previously used request (nonce replay protection)
- Clock skew causing nonce collisions

**How to fix:**
1. Generate a fresh nonce for each request
2. Nonces expire after 5 minutes — ensure your clock is synchronized
3. Each nonce can only be used once within the TTL window

---

### UPAI-4009 — `rate_limited`

| | |
|---|---|
| **HTTP Status** | 429 Too Many Requests |
| **Message** | Too many requests |

**Common causes:**
- Exceeding the per-IP rate limit (default: 60 requests per 60 seconds)
- Automated scripts making requests too quickly

**How to fix:**
1. Back off and retry after the `Retry-After` header value (if present)
2. Use exponential backoff: wait 1s, 2s, 4s, 8s between retries
3. Cache responses where possible (the API supports ETags — use `If-None-Match`)
4. For bulk operations, use pagination instead of many parallel requests

---

### UPAI-4010 — `policy_immutable`

| | |
|---|---|
| **HTTP Status** | 403 Forbidden |
| **Message** | Cannot modify built-in policy: `{policy}` |

**Common causes:**
- Attempting to update or delete a built-in policy (`full`, `professional`, `technical`, `minimal`)

**How to fix:**
1. Built-in policies cannot be modified or deleted
2. Create a custom policy instead: `POST /policies` with your desired configuration
3. Custom policies can use any name that doesn't conflict with built-ins

---

### UPAI-4011 — `conflict`

| | |
|---|---|
| **HTTP Status** | 409 Conflict |
| **Message** | `{resource}` already exists |

**Common causes:**
- Creating a policy with a name that already exists
- Registering a webhook with a URL that's already registered

**How to fix:**
1. Use a different name/identifier
2. Update the existing resource instead of creating a new one
3. Delete the existing resource first if you want to replace it

---

### UPAI-4012 — `gone`

| | |
|---|---|
| **HTTP Status** | 410 Gone |
| **Message** | `{resource}` has been permanently removed |

**Common causes:**
- Accessing a resource that was explicitly deleted (not just revoked)
- The resource existed at one point but has been permanently removed

**How to fix:**
1. This is permanent — the resource cannot be recovered
2. Create a new resource if needed

---

### UPAI-4013 — `payload_too_large`

| | |
|---|---|
| **HTTP Status** | 413 Payload Too Large |
| **Message** | Request payload exceeds size limit |

**Common causes:**
- Request body exceeds the 1 MB limit

**How to fix:**
1. Reduce the request body size
2. For large imports, use the file upload endpoint (`POST /api/upload`) instead
3. Split large operations into smaller batches

---

### UPAI-4014 — `unsupported_media_type`

| | |
|---|---|
| **HTTP Status** | 415 Unsupported Media Type |
| **Message** | Unsupported content type |

**Common causes:**
- Missing or incorrect `Content-Type` header
- Sending form-encoded data instead of JSON

**How to fix:**
1. Set `Content-Type: application/json` for all API requests
2. Ensure the request body is valid JSON (not form data or XML)

---

## Server Errors (5xx)

### UPAI-5001 — `internal_error`

| | |
|---|---|
| **HTTP Status** | 500 Internal Server Error |
| **Message** | Unexpected server error |

**Common causes:**
- Bug in the server code
- Corrupted graph data
- File system or database error

**How to fix:**
1. Check the server logs for the full stack trace
2. If reproducible, file an issue at [github.com/Junebugg1214/Cortex-AI/issues](https://github.com/Junebugg1214/Cortex-AI/issues)
3. Include the `request_id` from the error response when reporting

---

### UPAI-5002 — `not_configured`

| | |
|---|---|
| **HTTP Status** | 503 Service Unavailable |
| **Message** | Server not fully configured |

**Common causes:**
- The server started without a context graph file
- Identity has not been initialized (`cortex identity --init`)
- Required storage backend is not available

**How to fix:**
1. Ensure a context file is provided: `cortex serve context.json`
2. Initialize identity if needed: `cortex identity --init --name "Your Name"`
3. For PostgreSQL: verify the database is running and the connection URL is correct

---

### UPAI-5003 — `service_unavailable`

| | |
|---|---|
| **HTTP Status** | 503 Service Unavailable |
| **Message** | Service temporarily unavailable |

**Common causes:**
- Server is starting up or shutting down
- Database connection pool exhausted
- Temporary resource constraint

**How to fix:**
1. Wait a moment and retry
2. Check `GET /health` to see if the server is healthy
3. If using PostgreSQL, check the database connection and pool settings

---

## Error Handling in SDKs

### Python

```python
from cortex_sdk.exceptions import (
    CortexSDKError,       # Base class for all errors
    AuthenticationError,  # 401
    ForbiddenError,       # 403
    NotFoundError,        # 404
    ValidationError,      # 400
    RateLimitError,       # 429
    ServerError,          # 5xx
)

try:
    client.context()
except RateLimitError:
    time.sleep(5)
    client.context()  # retry
except AuthenticationError:
    # Token expired — create a new grant
    pass
```

### TypeScript

```typescript
import {
  CortexSDKError,       // Base class for all errors
  AuthenticationError,  // 401
  ForbiddenError,       // 403
  NotFoundError,        // 404
  ValidationError,      // 400
  RateLimitError,       // 429
  ServerError,          // 5xx
} from '@cortex_ai/sdk';

try {
  await client.context();
} catch (err) {
  if (err instanceof RateLimitError) {
    await new Promise(r => setTimeout(r, 5000));
    await client.context(); // retry
  }
}
```

### curl

```bash
# Check for errors in JSON responses
curl -s http://localhost:8421/context \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Check HTTP status code
curl -s -o /dev/null -w "%{http_code}" http://localhost:8421/context \
  -H "Authorization: Bearer $TOKEN"
```

## Next Steps

- [Python SDK Quickstart](quickstart-python.md) — get started with Python
- [TypeScript SDK Quickstart](quickstart-typescript.md) — get started with TypeScript
- [CLI Walkthrough](cli-walkthrough.md) — explore all CLI commands
- [Interactive API Docs](http://localhost:8421/docs) — Swagger UI (start server first)
