"""Refactor Executor Agent (Phase 4): applies planned fixes behind HITL approval."""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ANTHROPIC_MODEL = "claude-sonnet-4-6"


def _strip_code_fences(text: str) -> str:
    """Strip a leading ```json/``` and trailing ``` (with surrounding whitespace) before parsing."""
    result = text.strip()
    result = re.sub(r"^```(?:json)?[ \t]*\r?\n?", "", result)
    result = re.sub(r"```[ \t]*$", "", result)
    return result.strip()


def generate_fix(finding: dict[str, Any], file_content: str) -> dict[str, Any]:
    """Ask Claude to propose a fix for `finding` as an exact substring replacement.

    Returns {"file": str, "original_snippet": str, "fixed_snippet": str, "explanation": str}.
    original_snippet must be an exact substring of file_content -- apply_fix locates it with
    a plain string search, not a fuzzy match.
    """
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import HumanMessage, SystemMessage

    system_prompt = (
        "You are a careful refactoring assistant. Given a code review finding and the full "
        "current contents of the file it applies to, propose a minimal, exact fix. "
        "Respond with ONLY a JSON object, no prose, no markdown fences: "
        '{"file": "<filename>", "original_snippet": "<exact substring of the file content to '
        'replace>", "fixed_snippet": "<its replacement>", "explanation": "<one sentence>"}. '
        "original_snippet MUST be an exact, verbatim substring of the provided file content -- "
        "copy it character-for-character, including original indentation and line breaks -- so "
        "it can be located with a plain string search. Keep the change minimal and scoped to "
        "this one finding; do not rewrite unrelated code."
    )
    human_prompt = (
        "Finding:\n"
        f"  file: {finding.get('file')}\n"
        f"  category: {finding.get('category')}\n"
        f"  severity: {finding.get('severity')}\n"
        f"  description: {finding.get('description')}\n"
        f"  rationale: {finding.get('rationale')}\n\n"
        f"Current file content:\n{file_content}"
    )

    llm = ChatAnthropic(model=ANTHROPIC_MODEL, temperature=0, max_tokens=4096)
    response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)])
    return json.loads(_strip_code_fences(str(response.content)))


def resolve_target_path(working_dir: str, filename: str) -> Path:
    """Locate `filename` (a bare basename) anywhere under working_dir."""
    matches = list(Path(working_dir).rglob(filename))
    if not matches:
        raise FileNotFoundError(f"{filename!r} not found under {working_dir!r}")
    return matches[0]


def apply_fix(fix: dict[str, Any], working_dir: str) -> bool:
    """Apply `fix` to its target file inside working_dir via exact string replacement.

    Raises ValueError (fails loudly, never silently no-ops) if original_snippet isn't found
    verbatim in the current file. After writing, runs `python -m py_compile` as a syntax
    sanity check; if that fails, the file is reverted to its pre-fix content and this
    returns False. Returns True only once the fix has been written and the file still
    compiles.
    """
    target_path = resolve_target_path(working_dir, Path(fix["file"]).name)
    original_snippet = fix["original_snippet"]
    fixed_snippet = fix["fixed_snippet"]

    pre_fix_content = target_path.read_text()
    if original_snippet not in pre_fix_content:
        raise ValueError(
            f"apply_fix: original_snippet not found verbatim in {target_path}. "
            f"Refusing to silently no-op.\n--- expected snippet ---\n{original_snippet}"
        )

    new_content = pre_fix_content.replace(original_snippet, fixed_snippet, 1)
    target_path.write_text(new_content)

    check = subprocess.run(
        [sys.executable, "-m", "py_compile", str(target_path)],
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        target_path.write_text(pre_fix_content)
        print(f"apply_fix: py_compile failed for {target_path}, reverted.\n{check.stderr}")
        return False

    return True
