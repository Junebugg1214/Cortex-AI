/**
 * SDK exception hierarchy for CortexClient.
 *
 * Maps HTTP status codes to specific error types, mirroring
 * the Python SDK (cortex/sdk/exceptions.py).
 */

export class CortexSDKError extends Error {
  readonly statusCode: number;
  readonly body: Record<string, unknown>;

  constructor(
    message: string,
    statusCode: number = 0,
    body: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "CortexSDKError";
    this.statusCode = statusCode;
    this.body = body;
  }
}

/** 401 Unauthorized — missing or invalid token. */
export class AuthenticationError extends CortexSDKError {
  constructor(message: string, statusCode = 401, body: Record<string, unknown> = {}) {
    super(message, statusCode, body);
    this.name = "AuthenticationError";
  }
}

/** 403 Forbidden — insufficient scope or immutable resource. */
export class ForbiddenError extends CortexSDKError {
  constructor(message: string, statusCode = 403, body: Record<string, unknown> = {}) {
    super(message, statusCode, body);
    this.name = "ForbiddenError";
  }
}

/** 404 Not Found — resource does not exist. */
export class NotFoundError extends CortexSDKError {
  constructor(message: string, statusCode = 404, body: Record<string, unknown> = {}) {
    super(message, statusCode, body);
    this.name = "NotFoundError";
  }
}

/** 400 Bad Request — invalid request data. */
export class ValidationError extends CortexSDKError {
  constructor(message: string, statusCode = 400, body: Record<string, unknown> = {}) {
    super(message, statusCode, body);
    this.name = "ValidationError";
  }
}

/** 429 Too Many Requests — rate limited. */
export class RateLimitError extends CortexSDKError {
  constructor(message: string, statusCode = 429, body: Record<string, unknown> = {}) {
    super(message, statusCode, body);
    this.name = "RateLimitError";
  }
}

/** 5xx Server Error — unexpected server failure. */
export class ServerError extends CortexSDKError {
  constructor(message: string, statusCode = 500, body: Record<string, unknown> = {}) {
    super(message, statusCode, body);
    this.name = "ServerError";
  }
}
