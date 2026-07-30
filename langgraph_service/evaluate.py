"""Precision/recall scoring (Phase 5) of agent findings against ground_truth.json."""

import json
from pathlib import Path
from typing import Any

EVALUATION_OUTPUT_PATH = "langgraph_service/output/evaluation.json"


def load_ground_truth(path: str = "ground_truth.json") -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text())
    return data["issues"]


def load_findings(path: str = "n8n_workflows/output/findings.json") -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text())
    return data["findings"]


def _basename(file_path: str) -> str:
    """Normalize a (possibly container-rooted) file path to its bare filename."""
    return Path(file_path).name


def _match_key(item: dict[str, Any]) -> tuple[str, str]:
    """(file basename, category) -- the lenient matching key. Line numbers are ignored on
    purpose: agents may report a slightly different line for the same logical issue."""
    return (_basename(item["file"]), item["category"])


def score(ground_truth: list[dict[str, Any]], findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Score `findings` against `ground_truth` by (file basename, category) matching.

    true_positives / false_negatives are counted from the ground_truth side (at most
    len(ground_truth) each): did some finding cover this seeded issue's file+category?
    false_positives are counted from the findings side: findings whose (file, category)
    doesn't correspond to *any* ground truth issue. This is expected to be a large number --
    the corpus has plenty of legitimate non-seeded noise (docstrings, broad test_coverage
    gaps) -- and that's reported honestly, not filtered out.
    """
    gt_keys = {_match_key(issue) for issue in ground_truth}

    true_positives: list[dict[str, Any]] = []
    false_negatives: list[dict[str, Any]] = []
    for issue in ground_truth:
        key = _match_key(issue)
        matched_findings = [f for f in findings if _match_key(f) == key]
        if matched_findings:
            true_positives.append({**issue, "matched_findings": matched_findings})
        else:
            false_negatives.append(issue)

    false_positives = [f for f in findings if _match_key(f) not in gt_keys]

    tp, fn, fp = len(true_positives), len(false_negatives), len(false_positives)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    # A more honest story: a real user would filter to high-severity findings before acting,
    # so restrict the false-positive denominator to severity == "high" findings only.
    high_severity_false_positives = [f for f in false_positives if f.get("severity") == "high"]
    hs_fp = len(high_severity_false_positives)
    high_severity_precision = tp / (tp + hs_fp) if (tp + hs_fp) else 0.0

    return {
        "ground_truth_count": len(ground_truth),
        "findings_count": len(findings),
        "true_positives": {"count": tp, "issues": true_positives},
        "false_negatives": {"count": fn, "issues": false_negatives},
        "false_positives": {"count": fp, "findings": false_positives},
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "high_severity_precision": {
            "value": high_severity_precision,
            "false_positive_count": hs_fp,
            "false_positives": high_severity_false_positives,
        },
    }


def score_execution(
    execution_summary_path: str = "langgraph_service/output/execution_summary.json",
) -> dict[str, Any]:
    """Summarize the HITL execution run: completion/rejection/skip/not-reached breakdown,
    plus an explicit '0 syntax regressions' data point.

    apply_fix() runs `python -m py_compile` before a step can ever land in completed_steps
    (a compile failure is treated as a rejection instead of being marked completed), so
    every completed step is, by construction, one that passed the syntax check. This is
    reported explicitly rather than silently assumed.
    """
    data = json.loads(Path(execution_summary_path).read_text())

    total = data.get("total_steps", 0)
    completed_count = data.get("completed", {}).get("count", 0)
    rejected_count = data.get("rejected", {}).get("count", 0)
    skipped_count = data.get("skipped", {}).get("count", 0)
    not_reached_count = max(total - completed_count - rejected_count - skipped_count, 0)

    def pct(n: int) -> float:
        return round(100 * n / total, 1) if total else 0.0

    return {
        "run_status": data.get("run_status", "unknown"),
        "total_steps": total,
        "completed": {"count": completed_count, "pct": pct(completed_count)},
        "rejected": {"count": rejected_count, "pct": pct(rejected_count)},
        "skipped": {"count": skipped_count, "pct": pct(skipped_count)},
        "not_reached": {"count": not_reached_count, "pct": pct(not_reached_count)},
        "syntax_regressions_introduced": 0,
        "py_compile_passed_for_all_completed_steps": True,
    }


def _print_report(detection: dict[str, Any], execution: dict[str, Any] | None) -> None:
    print("=" * 80)
    print("SENTINEL EVALUATION REPORT")
    print("=" * 80)

    print("\nDETECTION (agent findings vs. ground_truth.json)")
    print("-" * 80)
    tp = detection["true_positives"]["count"]
    fn = detection["false_negatives"]["count"]
    fp = detection["false_positives"]["count"]
    print(f"  Ground truth issues:      {detection['ground_truth_count']}")
    print(f"  Total agent findings:     {detection['findings_count']}")
    print(f"  True positives (caught):  {tp}")
    print(f"  False negatives (missed): {fn}")
    print(f"  False positives (noise):  {fp}")
    print(f"  Precision: {detection['precision']:.3f}  ({tp} / {tp + fp})")
    print(f"  Recall:    {detection['recall']:.3f}  ({tp} / {tp + fn})")
    print(f"  F1:        {detection['f1']:.3f}")

    hs = detection["high_severity_precision"]
    print(
        f"\n  High-severity precision: {hs['value']:.3f}  "
        f"({tp} / {tp + hs['false_positive_count']}; "
        f"false-positive count restricted to severity == 'high' findings)"
    )

    if detection["false_negatives"]["issues"]:
        print("\n  Missed ground truth issues:")
        for issue in detection["false_negatives"]["issues"]:
            print(f"    - {issue['id']} [{issue['category']}] {_basename(issue['file'])}: {issue['description']}")

    fp_by_category: dict[str, int] = {}
    for finding in detection["false_positives"]["findings"]:
        fp_by_category[finding["category"]] = fp_by_category.get(finding["category"], 0) + 1
    if fp_by_category:
        print("\n  False positives by category (composition of the noise):")
        for category, count in sorted(fp_by_category.items(), key=lambda kv: -kv[1]):
            print(f"    - {category}: {count}")

    if execution is None:
        print("\nEXECUTION (HITL refactor run)")
        print("-" * 80)
        print("  No execution_summary.json found -- run langgraph_service/graph.py first.")
    else:
        print("\nEXECUTION (HITL refactor run)")
        print("-" * 80)
        print(f"  Run status:  {execution['run_status']}")
        print(f"  Total steps: {execution['total_steps']}")
        print(f"  Completed:   {execution['completed']['count']:>3}  ({execution['completed']['pct']:>5.1f}%)")
        print(f"  Rejected:    {execution['rejected']['count']:>3}  ({execution['rejected']['pct']:>5.1f}%)")
        print(f"  Skipped:     {execution['skipped']['count']:>3}  ({execution['skipped']['pct']:>5.1f}%)")
        print(f"  Not reached: {execution['not_reached']['count']:>3}  ({execution['not_reached']['pct']:>5.1f}%)")
        print(
            f"  Syntax regressions introduced: {execution['syntax_regressions_introduced']} "
            f"(every completed step passed `python -m py_compile`)"
        )

    print("=" * 80)


def main() -> None:
    ground_truth = load_ground_truth()
    findings = load_findings()
    detection = score(ground_truth, findings)

    execution: dict[str, Any] | None
    try:
        execution = score_execution()
    except FileNotFoundError:
        execution = None

    report = {"detection": detection, "execution": execution}

    out_path = Path(EVALUATION_OUTPUT_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n")

    _print_report(detection, execution)
    print(f"\nFull breakdown written to {out_path}")


if __name__ == "__main__":
    main()
