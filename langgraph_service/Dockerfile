FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY langgraph_service/ ./langgraph_service/
COPY test_corpus/ ./test_corpus/

WORKDIR /app/langgraph_service

# graph.py is the interactive HITL orchestrator: human_approval() blocks on a real
# input() call in the terminal, which a container can't reliably provide (no TTY by
# default, and non-interactive `docker compose run` will just hang or fail to read
# stdin). planner.py is fully non-interactive end-to-end, so it's the sane default
# CMD -- run graph.py locally in a venv instead. See README.md's "Running with Docker"
# section.
CMD ["python", "planner.py"]
