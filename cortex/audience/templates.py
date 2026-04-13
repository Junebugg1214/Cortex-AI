"""Built-in audience policy templates shipped with Cortex."""

from __future__ import annotations

from cortex.audience.policy import AudiencePolicy

BUILTIN_AUDIENCE_TEMPLATES: dict[str, AudiencePolicy] = {
    "executive": AudiencePolicy(
        audience_id="executive",
        display_name="Executive",
        allowed_node_types=["project", "milestone", "decision", "active_priorities", "business_context"],
        blocked_node_types=["credential", "personal", "user_preferences", "communication_preferences"],
        allowed_claim_confidences=(0.6, 1.0),
        redact_fields=["properties", "source_quotes", "provenance", "snapshots"],
        output_format="brief",
        delivery="stdout",
        delivery_target=None,
        include_provenance=False,
        include_contested=False,
    ),
    "attorney": AudiencePolicy(
        audience_id="attorney",
        display_name="Attorney",
        allowed_node_types=[],
        blocked_node_types=["user_preferences", "communication_preferences"],
        allowed_claim_confidences=(0.0, 1.0),
        redact_fields=[],
        output_format="report",
        delivery="stdout",
        delivery_target=None,
        include_provenance=True,
        include_contested=True,
    ),
    "onboarding": AudiencePolicy(
        audience_id="onboarding",
        display_name="Onboarding",
        allowed_node_types=[],
        blocked_node_types=["history", "correction_history", "negations"],
        allowed_claim_confidences=(0.5, 1.0),
        redact_fields=["source_quotes", "provenance", "snapshots"],
        output_format="pack",
        delivery="stdout",
        delivery_target=None,
        include_provenance=False,
        include_contested=False,
    ),
    "audit": AudiencePolicy(
        audience_id="audit",
        display_name="Audit",
        allowed_node_types=[],
        blocked_node_types=[],
        allowed_claim_confidences=(0.0, 1.0),
        redact_fields=[],
        output_format="raw",
        delivery="stdout",
        delivery_target=None,
        include_provenance=True,
        include_contested=True,
    ),
}


__all__ = ["BUILTIN_AUDIENCE_TEMPLATES"]
