## Sentinel

Sentinel is a multi-agent code review and refactor pipeline built on n8n for workflow
orchestration and LangGraph for agentic reasoning: an intake stage fans a codebase out to
specialized review agents (security, performance, style, test coverage), a dependency-aware
Planning Agent consolidates their findings into an ordered remediation plan that respects
file- and function-level dependencies so fixes are proposed in a safe sequence, and a Refactor
Executor Agent applies changes behind a human-in-the-loop (HITL) approval gate before anything
is written back to the repo. `test_corpus/sample_app` is a small, intentionally flawed toy
Flask-style app used to evaluate the pipeline end-to-end: it seeds one known issue per category
(a SQL injection in `db.py`, a hardcoded secret in `api.py`, an N+1 query pattern in `db.py`, a
poorly named/undocumented function in `utils.py`, and a test file that only covers one of three
functions), with the expected findings recorded in `ground_truth.json` so precision/recall can
be scored automatically against what the agents actually detect.
