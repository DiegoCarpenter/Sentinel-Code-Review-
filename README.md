# Sentinel — Multi-Agent Code Review & Refactor Pipeline

A pipeline that reviews a codebase with parallel specialist agents, builds a dependency-aware refactor plan, and executes fixes behind a human-in-the-loop approval gate — combining n8n for workflow orchestration with LangGraph for agentic reasoning.

[Demo video](https://youtu.be/K2aosXVTXQA)

## Architecture

Codebase
│
▼
n8n: 3 parallel specialist agents (Security / Performance / Style+Test Coverage)
│
▼ findings.json
LangGraph Planning Agent
├─ filter & prioritize by severity
├─ build a dependency graph (NetworkX) — rule-based edges + an LLM pass for
│ cross-cutting dependencies rule-based logic can't see
└─ topological sort → ordered refactor plan (cycles broken automatically)
│
▼ refactor_plan.json
LangGraph Orchestrator (HITL)
├─ generate a proposed fix + unified diff per step
├─ interrupt() — pause for human approve/reject/skip
└─ apply_fix() — writes the change, gated by a py_compile check
│
▼ execution_summary.json
Evaluation — precision/recall/F1 vs. ground_truth.json

## Why this design

- **Three specialist agents in parallel, not one generalist.** Security, performance, and style/test-coverage review are different skills with different failure modes; running them as separate LLM calls against the same corpus avoids one agent's blind spots masking another's, and lets each be evaluated independently.
- **Dependency-aware ordering, not just severity ordering.** A pure severity sort would happily apply a style fix before the security fix it's co-located with, or apply a test-coverage fix before the vulnerability it's meant to test is even patched. The Planning Agent builds a real dependency graph — same-function security-before-performance-before-tests, style always last — and augments it with an LLM pass that reads the actual source to catch cross-function dependencies the rules can't see (e.g. one flagged function calling another flagged function). Cycles are broken automatically by dropping the lowest-severity edge involved, rather than crashing the run.
- **Human-in-the-loop is a real gate, not a formality.** Each step shows the actual unified diff before asking for approval, and the graph genuinely pauses via LangGraph's `interrupt()`/`Command(resume=...)` — a rejected or skipped step doesn't get silently retried or forced through.
- **Syntactic safety is enforced at the write boundary.** `apply_fix()` runs `python -m py_compile` before any step can be marked completed; a compile failure is treated as a rejection rather than a silent success. This guarantees zero syntax regressions across every run — but it's a syntactic check, not a semantic one, and that distinction is reported explicitly rather than assumed (see Evaluation below).

## Evaluation results

Run against a seeded 5-issue test corpus (`test_corpus/sample_app`) — one issue per category: a SQL injection, a hardcoded secret, an N+1 query pattern, a poorly-named/undocumented function, and a test-coverage gap.

**Detection (agent findings vs. ground truth):**

| Metric | Value |
|---|---|
| Precision | 0.20 |
| Recall | 0.80 |
| F1 | 0.32 |
| High-severity precision | 0.33 |

4 of 5 seeded issues were caught (recall 0.80); the missed one was the test-coverage gap. Precision looks low at 0.20, but that's mostly a labeling artifact of a strict corpus, not weak detection: 24 total findings were generated against only 5 seeded issues, and the majority of the 16 "false positives" are legitimate, real code-quality findings (missing docstrings, genuinely untested functions) that simply weren't part of the 5 issues deliberately seeded into the corpus — reported honestly rather than filtered out to inflate the score.

**Execution (HITL refactor run):**

| Metric | Value |
|---|---|
| Total steps | 14 |
| Completed | 4 (28.6%) |
| Rejected | 1 (7.1%) |
| Skipped | 1 (7.1%) |
| Syntax regressions introduced | 0 |

Every completed step passed `py_compile` by construction — but that only verifies the fix doesn't break the syntax, not that it correctly resolves what the finding actually flagged. That gap between syntactic validity and semantic correctness is a known limitation of automated fix verification, not something the pipeline currently closes.

## Tech stack

`n8n` · `LangGraph` · `LangChain` · `NetworkX` · `Claude Sonnet` (Anthropic API) · `Docker` · `Python 3.12`

## Running it

```bash
# Phase 1-2: run the n8n analysis workflow
docker compose up -d n8n
# → reads test_corpus/sample_app_clean/, writes n8n_workflows/output/findings.json

# Phase 3: build the dependency-aware refactor plan
docker compose run langgraph_service python planner.py
# → writes langgraph_service/output/refactor_plan.json

# Phase 4: run the HITL refactor executor (needs a real terminal — not containerized,
# since human_approval() blocks on input())
python langgraph_service/graph.py

# Phase 5: score results against ground truth
python langgraph_service/evaluate.py
```

---
UCLA Extension — Agentic AI Course, Capstone Project
