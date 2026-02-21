"""
Federation — cross-instance context sharing for Cortex-AI.

Enables secure export/import of graph subsets between Cortex instances
using Ed25519-signed bundles with replay protection.

Flow::

    Instance A: export → sign bundle → send to Instance B
    Instance B: verify signature → check trusted DIDs → merge into local graph

Usage::

    from cortex.federation import FederationManager

    mgr = FederationManager(identity=my_identity, trusted_dids=["did:key:z6Mk..."])
    bundle = mgr.export_bundle(graph, policy="full")
    # ... transfer bundle to peer ...
    result = mgr.import_bundle(graph, bundle)
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cortex.graph import CortexGraph
    from cortex.upai.identity import UPAIIdentity


# ---------------------------------------------------------------------------
# Bundle data types
# ---------------------------------------------------------------------------

@dataclass
class FederationBundle:
    """A signed graph export for cross-instance sharing."""

    version: str                     # "1.0"
    exporter_did: str                # DID of the exporting instance
    exporter_public_key_b64: str     # Public key for signature verification
    nonce: str                       # Replay protection nonce
    created_at: str                  # ISO-8601 timestamp
    expires_at: str                  # ISO-8601 timestamp
    policy: str                      # Export policy name ("full", "summary", "minimal")
    graph_data: dict                 # Exported nodes/edges
    node_count: int
    edge_count: int
    content_hash: str                # SHA-256 of canonical graph_data
    signature: str                   # Base64-encoded Ed25519 signature (or "")
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        return {
            "version": self.version,
            "exporter_did": self.exporter_did,
            "exporter_public_key_b64": self.exporter_public_key_b64,
            "nonce": self.nonce,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "policy": self.policy,
            "graph_data": self.graph_data,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "content_hash": self.content_hash,
            "signature": self.signature,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FederationBundle:
        """Deserialize from a plain dict."""
        return cls(
            version=d.get("version", "1.0"),
            exporter_did=d["exporter_did"],
            exporter_public_key_b64=d.get("exporter_public_key_b64", ""),
            nonce=d.get("nonce", ""),
            created_at=d.get("created_at", ""),
            expires_at=d.get("expires_at", ""),
            policy=d.get("policy", "full"),
            graph_data=d.get("graph_data", {}),
            node_count=d.get("node_count", 0),
            edge_count=d.get("edge_count", 0),
            content_hash=d.get("content_hash", ""),
            signature=d.get("signature", ""),
            metadata=d.get("metadata", {}),
        )


@dataclass
class ImportResult:
    """Result of importing a federation bundle."""

    success: bool
    nodes_added: int = 0
    nodes_updated: int = 0
    edges_added: int = 0
    edges_updated: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "nodes_added": self.nodes_added,
            "nodes_updated": self.nodes_updated,
            "edges_added": self.edges_added,
            "edges_updated": self.edges_updated,
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# Export policies
# ---------------------------------------------------------------------------

EXPORT_POLICIES = {
    "full": {
        "include_properties": True,
        "include_descriptions": True,
        "include_confidence": True,
        "include_timeline": True,
    },
    "summary": {
        "include_properties": False,
        "include_descriptions": True,
        "include_confidence": True,
        "include_timeline": False,
    },
    "minimal": {
        "include_properties": False,
        "include_descriptions": False,
        "include_confidence": False,
        "include_timeline": False,
    },
}


def _apply_policy(node_dict: dict, policy_name: str) -> dict:
    """Filter a node dict according to the export policy."""
    policy = EXPORT_POLICIES.get(policy_name, EXPORT_POLICIES["full"])
    result = {
        "id": node_dict["id"],
        "label": node_dict["label"],
        "tags": node_dict.get("tags", []),
    }
    if policy["include_confidence"]:
        result["confidence"] = node_dict.get("confidence", 0.0)
    if policy["include_descriptions"]:
        result["brief"] = node_dict.get("brief", "")
        result["full_description"] = node_dict.get("full_description", "")
    if policy["include_properties"]:
        result["properties"] = node_dict.get("properties", {})
    if policy["include_timeline"]:
        result["timeline"] = node_dict.get("timeline", [])
        result["first_seen"] = node_dict.get("first_seen", "")
        result["last_seen"] = node_dict.get("last_seen", "")
    return result


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------

def _compute_content_hash(graph_data: dict) -> str:
    """SHA-256 hash of canonical JSON representation."""
    canonical = json.dumps(graph_data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Signing helpers
# ---------------------------------------------------------------------------

def _compute_signing_input(bundle_dict: dict) -> bytes:
    """Compute the canonical bytes to be signed.

    Signs over: version + exporter_did + nonce + created_at + content_hash.
    """
    parts = [
        bundle_dict.get("version", ""),
        bundle_dict.get("exporter_did", ""),
        bundle_dict.get("nonce", ""),
        bundle_dict.get("created_at", ""),
        bundle_dict.get("content_hash", ""),
    ]
    canonical = "|".join(parts)
    return canonical.encode("utf-8")


# ---------------------------------------------------------------------------
# FederationManager
# ---------------------------------------------------------------------------

class FederationManager:
    """Manages federation export/import between Cortex instances."""

    def __init__(
        self,
        identity: UPAIIdentity,
        trusted_dids: list[str] | None = None,
        sign_exports: bool = True,
        bundle_ttl_seconds: int = 3600,
    ) -> None:
        self.identity = identity
        self.trusted_dids: set[str] = set(trusted_dids or [])
        self.sign_exports = sign_exports
        self.bundle_ttl_seconds = bundle_ttl_seconds
        self._seen_nonces: set[str] = set()

    # ── Export ────────────────────────────────────────────────────────

    def export_bundle(
        self,
        graph: CortexGraph,
        policy: str = "full",
        tag_filter: str | None = None,
        metadata: dict | None = None,
    ) -> FederationBundle:
        """Export graph data as a signed federation bundle.

        Args:
            graph: The source graph.
            policy: Export policy name ("full", "summary", "minimal").
            tag_filter: Optional tag to filter nodes by.
            metadata: Optional metadata dict to include.

        Returns:
            A signed FederationBundle ready for transmission.
        """
        if policy not in EXPORT_POLICIES:
            raise ValueError(f"Unknown export policy: {policy!r}. "
                             f"Valid: {', '.join(EXPORT_POLICIES)}")

        # Build graph_data with policy filtering
        nodes = {}
        for nid, node in graph.nodes.items():
            nd = node.to_dict()
            if tag_filter and tag_filter not in nd.get("tags", []):
                continue
            nodes[nid] = _apply_policy(nd, policy)

        # Include edges where both endpoints are in the exported set
        edges = {}
        for eid, edge in graph.edges.items():
            if edge.source_id in nodes and edge.target_id in nodes:
                edges[eid] = edge.to_dict()

        graph_data = {"nodes": nodes, "edges": edges}
        content_hash = _compute_content_hash(graph_data)
        now = datetime.now(timezone.utc)

        bundle = FederationBundle(
            version="1.0",
            exporter_did=self.identity.did,
            exporter_public_key_b64=self.identity.public_key_b64,
            nonce=secrets.token_hex(16),
            created_at=now.isoformat(),
            expires_at=datetime.fromtimestamp(
                now.timestamp() + self.bundle_ttl_seconds, tz=timezone.utc
            ).isoformat(),
            policy=policy,
            graph_data=graph_data,
            node_count=len(nodes),
            edge_count=len(edges),
            content_hash=content_hash,
            signature="",
            metadata=metadata or {},
        )

        # Sign if Ed25519 is available
        if self.sign_exports:
            signing_input = _compute_signing_input(bundle.to_dict())
            try:
                bundle.signature = self.identity.sign(signing_input)
            except (ValueError, AttributeError):
                pass  # No private key or crypto unavailable

        return bundle

    # ── Import ────────────────────────────────────────────────────────

    def import_bundle(
        self,
        graph: CortexGraph,
        bundle: FederationBundle,
        *,
        verify_signature: bool = True,
        check_trust: bool = True,
        check_expiry: bool = True,
    ) -> ImportResult:
        """Import a federation bundle into the local graph.

        Args:
            graph: The target graph to merge into.
            bundle: The federation bundle to import.
            verify_signature: Whether to verify the cryptographic signature.
            check_trust: Whether to check if the exporter DID is trusted.
            check_expiry: Whether to check bundle expiry.

        Returns:
            ImportResult with counts and any errors.
        """
        errors: list[str] = []

        # 1. Trust check
        if check_trust and bundle.exporter_did not in self.trusted_dids:
            return ImportResult(
                success=False,
                errors=[f"Untrusted exporter: {bundle.exporter_did}"],
            )

        # 2. Replay check (nonce)
        if bundle.nonce in self._seen_nonces:
            return ImportResult(
                success=False,
                errors=[f"Replay detected: nonce {bundle.nonce} already seen"],
            )

        # 3. Expiry check
        if check_expiry and bundle.expires_at:
            try:
                exp = datetime.fromisoformat(bundle.expires_at)
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                if now > exp:
                    return ImportResult(
                        success=False,
                        errors=[f"Bundle expired at {bundle.expires_at}"],
                    )
            except (ValueError, TypeError):
                errors.append("Could not parse expires_at; skipping expiry check")

        # 4. Content hash verification
        expected_hash = _compute_content_hash(bundle.graph_data)
        if bundle.content_hash and bundle.content_hash != expected_hash:
            return ImportResult(
                success=False,
                errors=["Content hash mismatch — bundle may be tampered"],
            )

        # 5. Signature verification
        if verify_signature and bundle.signature and bundle.exporter_public_key_b64:
            from cortex.upai.identity import UPAIIdentity as _Identity

            signing_input = _compute_signing_input(bundle.to_dict())
            if not _Identity.verify(
                signing_input,
                bundle.signature,
                bundle.exporter_public_key_b64,
            ):
                return ImportResult(
                    success=False,
                    errors=["Invalid signature"],
                )

        # Record nonce
        self._seen_nonces.add(bundle.nonce)

        # 6. Merge nodes and edges
        from cortex.graph import Edge, Node

        nodes_added = 0
        nodes_updated = 0
        edges_added = 0
        edges_updated = 0

        for nid, nd in bundle.graph_data.get("nodes", {}).items():
            try:
                node = Node.from_dict(nd)
                if nid in graph.nodes:
                    # Update existing: merge tags, take higher confidence
                    existing = graph.nodes[nid]
                    merged_tags = list(set(existing.tags) | set(node.tags))
                    existing.tags = merged_tags
                    if node.confidence > existing.confidence:
                        existing.confidence = node.confidence
                    if node.brief and not existing.brief:
                        existing.brief = node.brief
                    nodes_updated += 1
                else:
                    graph.add_node(node)
                    nodes_added += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Failed to import node {nid}: {exc}")

        for eid, ed in bundle.graph_data.get("edges", {}).items():
            try:
                edge = Edge.from_dict(ed)
                # Only add if both endpoints exist in graph
                if edge.source_id in graph.nodes and edge.target_id in graph.nodes:
                    if eid in graph.edges:
                        existing_edge = graph.edges[eid]
                        if edge.confidence > existing_edge.confidence:
                            existing_edge.confidence = edge.confidence
                        edges_updated += 1
                    else:
                        graph.add_edge(edge)
                        edges_added += 1
                else:
                    errors.append(f"Skipped edge {eid}: endpoint(s) not in graph")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Failed to import edge {eid}: {exc}")

        return ImportResult(
            success=True,
            nodes_added=nodes_added,
            nodes_updated=nodes_updated,
            edges_added=edges_added,
            edges_updated=edges_updated,
            errors=errors,
        )

    # ── Peer management ───────────────────────────────────────────────

    def add_trusted_did(self, did: str) -> None:
        """Add a DID to the trusted set."""
        self.trusted_dids.add(did)

    def remove_trusted_did(self, did: str) -> bool:
        """Remove a DID from the trusted set. Returns True if it was present."""
        if did in self.trusted_dids:
            self.trusted_dids.discard(did)
            return True
        return False

    def list_trusted_dids(self) -> list[str]:
        """Return sorted list of trusted DIDs."""
        return sorted(self.trusted_dids)

    def get_peer_info(self) -> dict:
        """Return this instance's federation info for peering."""
        return {
            "did": self.identity.did,
            "public_key_b64": self.identity.public_key_b64,
            "federation_version": "1.0",
        }
