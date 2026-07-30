"""Shared graph state schema for the Sentinel orchestrator."""

from typing import Any, NotRequired, TypedDict


class OrchestratorState(TypedDict):
    plan: list[dict[str, Any]]
    current_step_index: int
    completed_steps: list[dict[str, Any]]
    rejected_steps: list[dict[str, Any]]
    working_dir: str

    # Implementation-internal fields, not part of the Phase 4 spec's five fields, but needed
    # to carry the fix proposed in `present_step` through to `human_approval` / `apply_step`
    # without recomputing it.
    pending_fix: NotRequired[dict[str, Any] | None]
    human_decision: NotRequired[str | None]
