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

## Running with Docker

`docker compose up -d n8n` starts the n8n container, which serves the analysis workflow
(`n8n_workflows/sentinel_analysis.json`) that reads `test_corpus/sample_app_clean/` and writes
`n8n_workflows/output/findings.json`.

Once findings exist, run the Planning Agent in its own container:

```
docker compose run langgraph_service python planner.py
```

This builds the `langgraph_service` image (Python 3.12, `langgraph_service/Dockerfile`),
reads `n8n_workflows/output/findings.json`, and writes `langgraph_service/output/refactor_plan.json`
back to the host via the mounted `langgraph_service/output` volume. `env_file: .env` makes
`ANTHROPIC_API_KEY` available inside the container for the planner's LLM dependency pass.

The HITL refactor executor (`langgraph_service/graph.py`) is **not** meant to run in a
container: its `human_approval` step blocks on a real `input()` call in the terminal, and a
containerized process doesn't reliably have a TTY attached. Run it locally instead, in a venv
with `requirements.txt` installed:

```
python langgraph_service/graph.py
```
