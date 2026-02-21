#!/usr/bin/env python3
"""
Multi-Agent Context Sharing — two agents sharing context via grants.

Demonstrates:
1. Creating a UPAI identity
2. Issuing scoped grants to different agents
3. Verifying grant tokens

Prerequisites:
    pip install cortex-ai

Usage:
    python examples/multi-agent/main.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path


def main():
    from cortex.upai.identity import UPAIIdentity
    from cortex.upai.tokens import GrantToken

    # Step 1: Create an identity (simulates a CaaS server owner)
    store_dir = Path(tempfile.mkdtemp()) / ".cortex"
    store_dir.mkdir()
    identity = UPAIIdentity.create(store_dir)
    print(f"1. Created identity: {identity.did}")

    # Step 2: Issue a read-only grant for Agent A
    agent_a_grant = GrantToken.create(
        identity=identity,
        audience="agent-a",
        scopes=["context:read", "identity:read"],
        ttl_hours=24,
    )
    print(f"2. Agent A grant (read-only): {agent_a_grant.grant_id}")
    print(f"   Scopes: {agent_a_grant.scopes}")

    # Step 3: Issue a read-write grant for Agent B
    agent_b_grant = GrantToken.create(
        identity=identity,
        audience="agent-b",
        scopes=["context:read", "context:write", "identity:read"],
        ttl_hours=8,
    )
    print(f"3. Agent B grant (read-write): {agent_b_grant.grant_id}")
    print(f"   Scopes: {agent_b_grant.scopes}")

    # Step 4: Verify tokens
    verified_a = GrantToken.verify(agent_a_grant.to_token_string(), identity)
    print(f"4. Agent A token verified: {verified_a is not None}")
    print(f"   Has context:read? {verified_a.has_scope('context:read')}")
    print(f"   Has context:write? {verified_a.has_scope('context:write')}")

    verified_b = GrantToken.verify(agent_b_grant.to_token_string(), identity)
    print(f"5. Agent B token verified: {verified_b is not None}")
    print(f"   Has context:write? {verified_b.has_scope('context:write')}")

    print("\nDone! In production, agents would use these tokens with:")
    print(f"  Authorization: Bearer <token>")
    print(f"  against the CaaS API at http://127.0.0.1:8421")


if __name__ == "__main__":
    main()
