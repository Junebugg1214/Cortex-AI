"""
UPAI Discovery — DID resolution and .well-known configuration.

Supports:
- did:key resolution (offline, pure computation from multibase)
- did:web resolution (network, fetches .well-known/did.json)
- Local identity resolution (from UPAIIdentity instance)
- UPAI Configuration for service discovery
"""

from __future__ import annotations

import base64
import json
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from cortex.upai.identity import (
    UPAIIdentity,
    _base58btc_decode,
    _base58btc_encode,
    _base64url_encode,
    _base64url_decode,
    _ED25519_MULTICODEC_PREFIX,
    _public_key_to_did_key,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# DID Resolver
# ---------------------------------------------------------------------------

class DIDResolver:
    """Resolve DIDs to DID Documents."""

    def resolve(self, did: str, **kwargs: Any) -> dict | None:
        """Resolve a DID to a DID Document.

        Dispatches to method-specific resolver based on DID prefix.
        If an identity is provided and its DID matches, use the local
        resolver (which supports service_endpoints).
        Returns None if the DID method is unknown or resolution fails.
        """
        # If caller provides a matching identity, prefer local resolution
        identity = kwargs.get("identity")
        if identity and identity.did == did:
            service_endpoints = kwargs.get("service_endpoints")
            return self.resolve_local(identity, service_endpoints=service_endpoints)

        if did.startswith("did:key:"):
            return self.resolve_did_key(did)
        elif did.startswith("did:web:"):
            return self.resolve_did_web(did)
        return None

    def resolve_local(
        self,
        identity: UPAIIdentity,
        service_endpoints: list[dict] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Resolve a local UPAI identity to its DID Document."""
        return identity.to_did_document(service_endpoints=service_endpoints)

    def resolve_did_key(self, did: str) -> dict | None:
        """Resolve a did:key to a DID Document.

        did:key encodes the public key in the DID itself (multibase + multicodec).
        No network calls needed.
        """
        if not did.startswith("did:key:z"):
            return None

        try:
            multibase_value = did[len("did:key:z"):]
            decoded = _base58btc_decode(multibase_value)

            if not decoded.startswith(_ED25519_MULTICODEC_PREFIX):
                return None

            pub_bytes = decoded[len(_ED25519_MULTICODEC_PREFIX):]
            if len(pub_bytes) != 32:
                return None

            public_key_b64 = base64.b64encode(pub_bytes).decode("ascii")

            # Reconstruct multibase for the document
            multibase = "z" + _base58btc_encode(_ED25519_MULTICODEC_PREFIX + pub_bytes)

            return {
                "@context": "https://www.w3.org/ns/did/v1",
                "id": did,
                "controller": did,
                "verificationMethod": [
                    {
                        "id": f"{did}#key-1",
                        "type": "Ed25519VerificationKey2020",
                        "controller": did,
                        "publicKeyMultibase": multibase,
                    }
                ],
                "authentication": [f"{did}#key-1"],
            }
        except (ValueError, IndexError):
            return None

    def resolve_did_web(self, did: str) -> dict | None:
        """Resolve a did:web to a DID Document via HTTPS.

        did:web:example.com → https://example.com/.well-known/did.json
        did:web:example.com:path:to → https://example.com/path/to/did.json
        """
        if not did.startswith("did:web:"):
            return None

        # Parse the DID
        method_specific = did[len("did:web:"):]
        parts = method_specific.split(":")

        if not parts:
            return None

        domain = parts[0]
        # URL-decode domain (colons become /)
        path_parts = parts[1:] if len(parts) > 1 else []

        if path_parts:
            url = f"https://{domain}/{'/'.join(path_parts)}/did.json"
        else:
            url = f"https://{domain}/.well-known/did.json"

        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                # Basic validation
                if isinstance(data, dict) and data.get("id") == did:
                    return data
                return None
        except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
            return None


# ---------------------------------------------------------------------------
# UPAI Configuration
# ---------------------------------------------------------------------------

@dataclass
class UPAIConfiguration:
    """UPAI service configuration for .well-known discovery."""

    server_url: str
    did: str
    supported_policies: list[str]
    supported_scopes: list[str]
    version: str = "1.0"

    def to_dict(self) -> dict:
        return {
            "server_url": self.server_url,
            "did": self.did,
            "supported_policies": list(self.supported_policies),
            "supported_scopes": list(self.supported_scopes),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> UPAIConfiguration:
        return cls(
            server_url=d["server_url"],
            did=d["did"],
            supported_policies=list(d.get("supported_policies", [])),
            supported_scopes=list(d.get("supported_scopes", [])),
            version=d.get("version", "1.0"),
        )
