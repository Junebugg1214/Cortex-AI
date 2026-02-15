"""
UPAI Webhooks — Registration, HMAC-SHA256 payload signing, and delivery.

Webhook payloads are signed with a shared secret using HMAC-SHA256.
Headers sent with each delivery:
- X-UPAI-Event: event type
- X-UPAI-Signature: sha256=<hex>
- X-UPAI-Delivery: unique delivery ID
- X-UPAI-Timestamp: ISO-8601 timestamp
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError


VALID_EVENTS: set[str] = {
    "context.updated",
    "version.created",
    "grant.created",
    "grant.revoked",
    "key.rotated",
}


@dataclass
class WebhookRegistration:
    """A registered webhook endpoint."""

    webhook_id: str
    url: str
    events: list[str]
    secret: str           # HMAC-SHA256 shared secret
    created_at: str
    active: bool = True

    def to_dict(self) -> dict:
        return {
            "webhook_id": self.webhook_id,
            "url": self.url,
            "events": list(self.events),
            "secret": self.secret,
            "created_at": self.created_at,
            "active": self.active,
        }

    @classmethod
    def from_dict(cls, d: dict) -> WebhookRegistration:
        return cls(
            webhook_id=d["webhook_id"],
            url=d["url"],
            events=list(d["events"]),
            secret=d["secret"],
            created_at=d["created_at"],
            active=d.get("active", True),
        )


def create_webhook(url: str, events: list[str]) -> WebhookRegistration:
    """Create a new webhook registration with a generated shared secret."""
    return WebhookRegistration(
        webhook_id=str(uuid.uuid4()),
        url=url,
        events=list(events),
        secret=secrets.token_hex(32),
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def sign_payload(payload: bytes, secret: str) -> str:
    """Sign a payload with HMAC-SHA256. Returns 'sha256=<hex>'."""
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def verify_webhook_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    """Verify a webhook signature header against payload and secret."""
    if not sig_header.startswith("sha256="):
        return False
    expected = sign_payload(payload, secret)
    return hmac.compare_digest(sig_header, expected)


def deliver_webhook(
    registration: WebhookRegistration,
    event: str,
    data: dict,
    timeout: float = 5.0,
) -> tuple[bool, int]:
    """Deliver a webhook payload to the registered URL.

    Returns (success, http_status_code). Status is 0 on connection error.
    """
    payload = json.dumps({
        "event": event,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }).encode("utf-8")

    signature = sign_payload(payload, registration.secret)
    delivery_id = str(uuid.uuid4())

    req = Request(registration.url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-UPAI-Event", event)
    req.add_header("X-UPAI-Signature", signature)
    req.add_header("X-UPAI-Delivery", delivery_id)
    req.add_header("X-UPAI-Timestamp", datetime.now(timezone.utc).isoformat())

    try:
        resp = urlopen(req, timeout=timeout)
        return True, resp.status
    except URLError:
        return False, 0
    except Exception:
        return False, 0
