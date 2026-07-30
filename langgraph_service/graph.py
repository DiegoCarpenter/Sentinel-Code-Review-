"""Orchestrator graph (Phase 4): wires planner + executor with a human-in-the-loop gate."""

import difflib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from langgraph_service.executor import apply_fix, generate_fix, resolve_target_path
from langgraph_service.state import OrchestratorState

SOURCE_CORPUS_DIR = REPO_ROOT / "test_corpus" / "sample_app_clean"
WORKING_COPY_DIR = REPO_ROOT / "langgraph_service" / "working_copy"
PLAN_PATH = REPO_ROOT / "langgraph_service" / "output" / "refactor_plan.json"
SUMMARY_PATH = REPO_ROOT / "langgraph_service" / "output" / "execution_summary.json"


def setup_working_copy(state: OrchestratorState) -> dict[str, Any]:
    """Copy the clean corpus into a fresh, disposable working directory. Refactors are
    applied there and never touch test_corpus/sample_app_clean/ itself."""
    if WORKING_COPY_DIR.exists():
        shutil.rmtree(WORKING_COPY_DIR)
    shutil.copytree(SOURCE_CORPUS_DIR, WORKING_COPY_DIR)
    print(f"[setup_working_copy] {SOURCE_CORPUS_DIR} -> {WORKING_COPY_DIR}")
    return {"working_dir": str(WORKING_COPY_DIR)}


def load_plan(state: OrchestratorState) -> dict[str, Any]:
    """Load the Phase 3 refactor plan and reset step-tracking state."""
    plan = json.loads(PLAN_PATH.read_text())
    print(f"[load_plan] loaded {len(plan)} step(s) from {PLAN_PATH}")
    return {"plan": plan, "current_step_index": 0, "completed_steps": [], "rejected_steps": []}


def present_step(state: OrchestratorState) -> dict[str, Any]:
    """Print the current step's finding, generate a proposed fix, and show a unified diff
    of what would change so a human reviewer can actually evaluate it."""
    step = state["plan"][state["current_step_index"]]
    finding = step["finding"]
    filename = Path(finding["file"]).name

    print("\n" + "=" * 72)
    print(f"STEP {step['step_number']} / {len(state['plan'])}")
    print(f"  file:              {filename}")
    print(f"  category:          {finding['category']}")
    print(f"  severity:          {finding['severity']}")
    print(f"  description:       {finding['description']}")
    print(f"  dependency_reason: {step['dependency_reason']}")
    print("=" * 72)

    target_path = resolve_target_path(state["working_dir"], filename)
    file_content = target_path.read_text()

    fix = generate_fix(finding, file_content)
    fix["file"] = filename  # normalize -- don't trust whatever path shape the LLM echoed back

    if fix["original_snippet"] not in file_content:
        print(
            "[present_step] WARNING: proposed original_snippet was not found verbatim in the "
            "current file; apply_step will reject this fix if it's approved."
        )

    fixed_content = file_content.replace(fix["original_snippet"], fix["fixed_snippet"], 1)
    diff = difflib.unified_diff(
        file_content.splitlines(keepends=True),
        fixed_content.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )

    print(f"\nProposed fix: {fix['explanation']}\n")
    diff_text = "".join(diff)
    print(diff_text or "(no textual diff -- snippet not found or fix is a no-op)")

    return {"pending_fix": fix}


def human_approval(state: OrchestratorState) -> dict[str, Any]:
    """HITL gate. Pauses via interrupt() and surfaces the pending fix; resumes with one of
    'approve' / 'reject' / 'skip'."""
    step = state["plan"][state["current_step_index"]]
    fix = state["pending_fix"]

    raw_decision = interrupt(
        {
            "step_number": step["step_number"],
            "file": fix["file"],
            "explanation": fix["explanation"],
            "prompt": "Respond 'approve', 'reject', or 'skip'.",
        }
    )
    decision = str(raw_decision).strip().lower()
    if decision not in ("approve", "reject", "skip"):
        print(f"[human_approval] unrecognized response {decision!r}; treating as 'skip'.")
        decision = "skip"

    if decision == "approve":
        return {"human_decision": decision}

    print(f"[human_approval] step {step['step_number']} {decision}.")
    return {
        "human_decision": decision,
        "rejected_steps": state["rejected_steps"] + [{**step, "status": decision}],
    }


def apply_step(state: OrchestratorState) -> dict[str, Any]:
    """Apply the approved fix. On failure (bad snippet or a py_compile break), don't crash
    the run -- log it and treat the step like a rejection."""
    step = state["plan"][state["current_step_index"]]
    fix = state["pending_fix"]

    try:
        success = apply_fix(fix, state["working_dir"])
    except (ValueError, FileNotFoundError) as exc:
        print(f"[apply_step] FAILED: {exc}")
        success = False

    if success:
        print(f"[apply_step] applied fix for step {step['step_number']} ({fix['file']}).")
        return {"completed_steps": state["completed_steps"] + [{**step, "status": "completed"}]}

    print(f"[apply_step] fix for step {step['step_number']} did not apply cleanly; treating as rejected.")
    return {"rejected_steps": state["rejected_steps"] + [{**step, "status": "failed"}]}


def advance_or_finish(state: OrchestratorState) -> dict[str, Any]:
    return {"current_step_index": state["current_step_index"] + 1}


def _build_and_write_summary(state: OrchestratorState, run_status: str) -> dict[str, Any]:
    """Shared summary logic: bucket completed/rejected/skipped steps, write
    execution_summary.json (tagged with run_status), and print a human-readable recap.

    Reads via .get() with defaults rather than direct indexing so it's also safe to call
    with a partial state (e.g. the run was interrupted before load_plan ever ran).
    """
    completed = state.get("completed_steps", [])
    # rejected_steps holds both actively-rejected and skipped entries, distinguished by
    # their "status" tag; split them back out for the report.
    rejected_steps = state.get("rejected_steps", [])
    rejected = [s for s in rejected_steps if s.get("status") != "skip"]
    skipped = [s for s in rejected_steps if s.get("status") == "skip"]

    summary = {
        "run_status": run_status,
        "total_steps": len(state.get("plan", [])),
        "completed": {"count": len(completed), "steps": completed},
        "rejected": {"count": len(rejected), "steps": rejected},
        "skipped": {"count": len(skipped), "steps": skipped},
    }

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n")

    print("\n" + "=" * 72)
    print("EXECUTION SUMMARY")
    print("=" * 72)
    print(f"  total steps: {summary['total_steps']}")
    print(f"  completed:   {summary['completed']['count']}")
    print(f"  rejected:    {summary['rejected']['count']}")
    print(f"  skipped:     {summary['skipped']['count']}")
    print(f"  written to:  {SUMMARY_PATH}")
    print("=" * 72)

    return summary


def write_summary(state: OrchestratorState) -> dict[str, Any]:
    """Write execution_summary.json and print a human-readable recap for a normal finish."""
    _build_and_write_summary(state, run_status="completed")
    return {}


def _route_after_load(state: OrchestratorState) -> str:
    return "present_step" if state["plan"] else "write_summary"


def _route_after_approval(state: OrchestratorState) -> str:
    return "apply_step" if state["human_decision"] == "approve" else "advance_or_finish"


def _route_after_advance(state: OrchestratorState) -> str:
    return "present_step" if state["current_step_index"] < len(state["plan"]) else "write_summary"


def build_graph() -> Any:
    builder = StateGraph(OrchestratorState)

    builder.add_node("setup_working_copy", setup_working_copy)
    builder.add_node("load_plan", load_plan)
    builder.add_node("present_step", present_step)
    builder.add_node("human_approval", human_approval)
    builder.add_node("apply_step", apply_step)
    builder.add_node("advance_or_finish", advance_or_finish)
    builder.add_node("write_summary", write_summary)

    builder.add_edge(START, "setup_working_copy")
    builder.add_edge("setup_working_copy", "load_plan")
    builder.add_conditional_edges(
        "load_plan", _route_after_load, {"present_step": "present_step", "write_summary": "write_summary"}
    )
    builder.add_edge("present_step", "human_approval")
    builder.add_conditional_edges(
        "human_approval",
        _route_after_approval,
        {"apply_step": "apply_step", "advance_or_finish": "advance_or_finish"},
    )
    builder.add_edge("apply_step", "advance_or_finish")
    builder.add_conditional_edges(
        "advance_or_finish",
        _route_after_advance,
        {"present_step": "present_step", "write_summary": "write_summary"},
    )
    builder.add_edge("write_summary", END)

    return builder.compile(checkpointer=MemorySaver())


if __name__ == "__main__":
    load_dotenv()
    app = build_graph()
    config = {"configurable": {"thread_id": "sentinel-refactor-run"}}

    initial_state: OrchestratorState = {
        "plan": [],
        "current_step_index": 0,
        "completed_steps": [],
        "rejected_steps": [],
        "working_dir": "",
    }

    print("Starting Sentinel refactor executor...\n")

    try:
        result = app.invoke(initial_state, config)

        while "__interrupt__" in result:
            payload = result["__interrupt__"][0].value
            print(f"\n--- Human approval needed: step {payload['step_number']} ({payload['file']}) ---")
            print(f"    {payload['explanation']}")
            raw = input("Approve, reject, or skip this fix? [a/r/s]: ").strip().lower()
            decision = {"a": "approve", "r": "reject", "s": "skip"}.get(raw, raw)
            if decision not in ("approve", "reject", "skip"):
                print(f"Unrecognized input {raw!r}; treating as 'skip'.")
                decision = "skip"
            result = app.invoke(Command(resume=decision), config)

        print("\nRun complete.")
    except KeyboardInterrupt:
        print("\n\nRun interrupted by user.")
        try:
            state_so_far = app.get_state(config).values
        except Exception:
            state_so_far = {}
        _build_and_write_summary(state_so_far, run_status="interrupted_by_user")
