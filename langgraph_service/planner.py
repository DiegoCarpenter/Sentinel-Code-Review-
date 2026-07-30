"""Planning Agent (Phase 3): turns raw findings into a dependency-aware remediation plan.

Pipeline: load_findings -> filter_and_prioritize -> build_dependency_graph -> topological_plan.
"""

import ast
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import networkx as nx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

SEVERITY_ORDER: dict[str, int] = {"high": 0, "medium": 1, "low": 2}
ANTHROPIC_MODEL = "claude-sonnet-4-6"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FINDINGS_PATH = REPO_ROOT / "n8n_workflows" / "output" / "findings.json"
DEFAULT_CORPUS_DIR = REPO_ROOT / "test_corpus" / "sample_app_clean"
DEFAULT_PLAN_PATH = REPO_ROOT / "langgraph_service" / "output" / "refactor_plan.json"


def load_findings(path: str) -> list[dict[str, Any]]:
    """Load the findings array from an n8n analysis output file."""
    data = json.loads(Path(path).read_text())
    return data["findings"]


def _basename(file_path: str) -> str:
    """Normalize a (possibly container-rooted, e.g. /data/...) file path to its bare filename."""
    return Path(file_path).name


def finding_id(finding: dict[str, Any]) -> str:
    """Build a stable node id for a finding: '<file>:<line>:<category>'."""
    return f"{_basename(finding['file'])}:{finding.get('line')}:{finding['category']}"


def filter_and_prioritize(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep high-severity findings always; keep medium findings only for security/performance
    (dropping medium/low style and test_coverage noise); sort by severity (high > medium > low).

    Findings that share a (file, line) with a different category are kept as separate items —
    never silently merged — and each gets a `co_located_categories` field noting the other
    categories present at that same location.
    """
    kept = [
        dict(finding)
        for finding in findings
        if finding["severity"] == "high"
        or (finding["severity"] == "medium" and finding["category"] in ("security", "performance"))
    ]

    for finding in kept:
        finding["id"] = finding_id(finding)

    by_location: dict[tuple[str, Any], list[str]] = {}
    for finding in kept:
        by_location.setdefault((finding["file"], finding.get("line")), []).append(finding["category"])

    for finding in kept:
        categories_here = by_location[(finding["file"], finding.get("line"))]
        co_located = sorted({c for c in categories_here if c != finding["category"]})
        if co_located:
            finding["co_located_categories"] = co_located

    kept.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 99))
    return kept


def _load_corpus_sources(corpus_dir: str | Path) -> dict[str, str]:
    """Map bare filename -> source text for every .py file under corpus_dir."""
    return {path.name: path.read_text() for path in Path(corpus_dir).rglob("*.py")}


def _function_for_line(source: str, line: int | None) -> str | None:
    """Return the name of the innermost function definition enclosing `line`, if any."""
    if line is None:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    best_name: str | None = None
    best_span: int | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end_line = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= line <= end_line:
                span = end_line - node.lineno
                if best_span is None or span < best_span:
                    best_name, best_span = node.name, span
    return best_name


def _strip_code_fences(text: str) -> str:
    """Strip a leading ```json/``` and trailing ``` (with surrounding whitespace) before parsing."""
    result = text.strip()
    result = re.sub(r"^```(?:json)?[ \t]*\r?\n?", "", result)
    result = re.sub(r"```[ \t]*$", "", result)
    return result.strip()


def _llm_cross_cutting_edges(
    findings: list[dict[str, Any]],
    file_contents: dict[str, str],
) -> list[dict[str, str]]:
    """Ask Claude to spot ordering dependencies that same-file/same-function rules would miss
    (e.g. one function calling another that also has a finding).

    Returns [] on any failure -- missing API key, network error, unparseable response -- so a
    broken LLM call degrades the plan to rule-based edges only instead of crashing the run.
    """
    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError:
        logger.warning("langchain-anthropic not installed; skipping LLM dependency pass.")
        return []

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.warning("ANTHROPIC_API_KEY not set; skipping LLM dependency pass.")
        return []

    findings_payload = [
        {
            "id": finding["id"],
            "file": _basename(finding["file"]),
            "line": finding.get("line"),
            "category": finding["category"],
            "severity": finding["severity"],
            "description": finding["description"],
        }
        for finding in findings
    ]
    source_blob = "\n\n".join(
        f"=== {name} ===\n{content}" for name, content in sorted(file_contents.items())
    )

    system_prompt = (
        "You are a refactor-planning assistant. Given a list of code review findings (each "
        "with a stable id) and the full source of the files they belong to, identify "
        "cross-cutting ordering dependencies that simple same-file/same-function rules would "
        "miss -- for example, one function calling another that also has a finding, or a "
        "shared helper touched by multiple findings. Respond with ONLY a JSON array, no prose, "
        "no markdown fences. Each element: "
        '{"from_id": "<id>", "to_id": "<id>", "reason": "<one sentence>"} '
        "meaning from_id must be fixed before to_id. Only include edges backed by something "
        "visible in the source -- do not invent dependencies. If there are none, respond with []."
    )
    human_prompt = (
        f"Findings:\n{json.dumps(findings_payload, indent=2)}\n\n"
        f"Source files:\n{source_blob}"
    )

    llm = ChatAnthropic(model=ANTHROPIC_MODEL, temperature=0, max_tokens=2048)
    try:
        response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)])
        edges = json.loads(_strip_code_fences(str(response.content)))
        return edges if isinstance(edges, list) else []
    except Exception:
        logger.warning("LLM dependency pass failed; continuing with rule-based edges only.", exc_info=True)
        return []


def build_dependency_graph(
    findings: list[dict[str, Any]],
    corpus_dir: str | Path = DEFAULT_CORPUS_DIR,
) -> nx.DiGraph:
    """Build a directed graph of refactor-ordering constraints between findings.

    Rule-based edges (within the same file):
      - security -> performance, when both touch the same function (fix the vulnerability
        before optimizing the vulnerable version).
      - security|performance -> test_coverage, when both touch the same function (write the
        fix first, then the test that covers it).
      - every non-style finding -> every style finding in that file (style is safe to apply
        last, regardless of what else changed).

    On top of those, an LLM call inspects the findings plus raw source for cross-cutting
    dependencies the rules can't see (e.g. one flagged function calling another).
    """
    graph = nx.DiGraph()
    for finding in findings:
        graph.add_node(finding["id"], finding=finding)

    file_contents = _load_corpus_sources(corpus_dir)

    findings_by_file: dict[str, list[dict[str, Any]]] = {}
    for finding in findings:
        findings_by_file.setdefault(_basename(finding["file"]), []).append(finding)

    for file_name, file_findings in findings_by_file.items():
        source = file_contents.get(file_name, "")
        for finding in file_findings:
            finding["_function"] = _function_for_line(source, finding.get("line"))

        security = [f for f in file_findings if f["category"] == "security"]
        performance = [f for f in file_findings if f["category"] == "performance"]
        test_coverage = [f for f in file_findings if f["category"] == "test_coverage"]
        style = [f for f in file_findings if f["category"] == "style"]
        non_style = [f for f in file_findings if f["category"] != "style"]

        for sec in security:
            for perf in performance:
                if sec["_function"] and sec["_function"] == perf["_function"]:
                    graph.add_edge(
                        sec["id"],
                        perf["id"],
                        reason=f"must follow fix to {sec['id']} (shared function {sec['_function']})",
                    )

        for fixer in security + performance:
            for test in test_coverage:
                if fixer["_function"] and fixer["_function"] == test["_function"]:
                    graph.add_edge(
                        fixer["id"],
                        test["id"],
                        reason=f"must follow fix to {fixer['id']} (shared function {fixer['_function']})",
                    )

        for fixer in non_style:
            for style_finding in style:
                graph.add_edge(
                    fixer["id"],
                    style_finding["id"],
                    reason=f"style fixes are applied last for {file_name}, after {fixer['id']}",
                )

    for finding in findings:
        finding.pop("_function", None)

    for edge in _llm_cross_cutting_edges(findings, file_contents):
        from_id, to_id = edge.get("from_id"), edge.get("to_id")
        if from_id in graph.nodes and to_id in graph.nodes and from_id != to_id:
            graph.add_edge(from_id, to_id, reason=edge.get("reason", f"depends on {from_id}"))
        else:
            logger.warning("Skipping LLM edge with unknown node id(s): %s", edge)

    return graph


def _severity_rank(graph: nx.DiGraph, node_id: str) -> int:
    return SEVERITY_ORDER.get(graph.nodes[node_id]["finding"]["severity"], 99)


def _lowest_severity_edge(graph: nx.DiGraph, cycle: list[tuple[Any, ...]]) -> tuple[str, str]:
    """Pick the cycle edge to drop: the one whose least-severe endpoint is least severe overall."""
    return max(
        ((u, v) for u, v, *_ in cycle),
        key=lambda uv: max(_severity_rank(graph, uv[0]), _severity_rank(graph, uv[1])),
    )


def topological_plan(graph: nx.DiGraph) -> list[dict[str, Any]]:
    """Produce an ordered refactor plan from the dependency graph via topological sort.

    Cycles (conflicting dependencies) are broken by repeatedly dropping the lowest-severity
    edge involved rather than raising, since a demo/CI run should degrade, not crash.
    """
    graph = graph.copy()
    while True:
        try:
            cycle = nx.find_cycle(graph)
        except nx.NetworkXNoCycle:
            break
        logger.warning("Dependency cycle detected: %s", cycle)
        u, v = _lowest_severity_edge(graph, cycle)
        logger.warning("Breaking cycle by dropping lowest-severity edge %s -> %s", u, v)
        graph.remove_edge(u, v)

    plan: list[dict[str, Any]] = []
    for step_number, node_id in enumerate(nx.topological_sort(graph), start=1):
        predecessors = list(graph.predecessors(node_id))
        if not predecessors:
            reason = "no dependencies"
        else:
            reason = "; ".join(
                graph.edges[predecessor, node_id].get("reason", f"must follow fix to {predecessor}")
                for predecessor in predecessors
            )
        plan.append(
            {
                "step_number": step_number,
                "finding": graph.nodes[node_id]["finding"],
                "dependency_reason": reason,
            }
        )
    return plan


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    load_dotenv()

    findings = load_findings(str(DEFAULT_FINDINGS_PATH))
    prioritized = filter_and_prioritize(findings)
    graph = build_dependency_graph(prioritized, DEFAULT_CORPUS_DIR)
    plan = topological_plan(graph)

    DEFAULT_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_PLAN_PATH.write_text(json.dumps(plan, indent=2) + "\n")

    print(f"Refactor plan ({len(plan)} steps) written to {DEFAULT_PLAN_PATH}\n")
    for item in plan:
        finding = item["finding"]
        print(
            f"{item['step_number']:>2}. [{finding['severity'].upper():<6} {finding['category']:<13}] "
            f"{_basename(finding['file'])}:{finding.get('line')} - {finding['description']} "
            f"({item['dependency_reason']})"
        )


if __name__ == "__main__":
    main()
