#!/usr/bin/env python3
"""M6-D: Independent Verification Pipeline.

Two layers, each producing its own facts for the caller to turn into evidence
with authority="verification" - never authority="acceptance". A verifier never
issues ACCEPT; it only ever produces passed/failed/inconclusive evidence. The
Decision Engine (nogap.py's cmd_decide) alone collects evidence and decides.

Layer 1 - Deterministic Verification: applies the patch under review to a
FRESH isolated worktree (never the one that originally produced it) and runs
the frozen gate's required_commands against it, plus an effect/scope
re-check (does the patch touch what it should, and nothing it must not).
This is the strongest evidence: reproducible, no agent judgment involved.

Layer 2 - Independent Agent Review: dispatches a DIFFERENT ready AgentRuntime
than the one that produced the patch to review it - mirroring the identity-
separation principle already enforced for ACCEPT (an executor cannot also be
its own verifier). The reviewer is asked to write a structured verdict file
inside the worktree rather than narrate a judgment in prose, and that file is
extracted from the resulting patch text (observed world state), not parsed
out of stdout - keeping faith with M6-C's "observed world state over
narrative" rule even for a review task whose product is inherently an opinion.
An unparsable or missing verdict is "inconclusive", never trusted as a pass.
"""

from __future__ import annotations

import json
import re
import shlex
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nogap_effects import ExpectedEffect, classify_generic_execution, verify_effect
from nogap_execution import GitWorktreeExecutionBackend

REVIEW_VERDICT_FILENAME = ".nogap-review.json"
REVIEW_VERDICTS = {"pass", "fail", "inconclusive"}


@dataclass
class VerificationCheck:
    """One check's outcome: what the caller turns into one evidence record.

    Shaped like nogap_execution.ExecutionResult (same field names
    write_isolated_run_evidence reads) so both can go through the same evidence
    writer, whether or not a subprocess actually ran for this particular check.
    """

    check: str
    status: str
    execution_status: str
    reason: str
    command: list[str]
    process_outcome: str
    returncode: int | None
    patch: str
    stdout: str
    stderr: str
    base_commit: str
    execution_id: str = field(default_factory=lambda: f"verify-{uuid.uuid4().hex[:12]}")


def _check_from_result(check_name: str, result: Any, status: str, execution_status: str, reason: str) -> VerificationCheck:
    return VerificationCheck(
        check=check_name,
        status=status,
        execution_status=execution_status,
        reason=reason,
        command=result.command,
        process_outcome=result.process_outcome,
        returncode=result.returncode,
        patch=result.patch,
        stdout=result.stdout,
        stderr=result.stderr,
        base_commit=result.base_commit,
        execution_id=result.execution_id,
    )


def _strip_matching_quotes(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    return token


def required_commands_from_gate(gate: dict[str, Any]) -> list[list[str]]:
    """Turns gate.rules.required_commands (plain command strings) into argv lists.

    shlex's default POSIX mode treats backslash as an escape character, which
    corrupts Windows paths (e.g. C:\\Users\\...) if a required_command ever embeds
    one - so this splits with posix=False instead, then strips one layer of
    matching quotes itself (non-POSIX mode leaves them on each token, which would
    otherwise be passed to Popen as literal characters instead of being consumed
    as quoting).
    """
    rules = gate.get("rules", {}) if isinstance(gate, dict) else {}
    commands = rules.get("required_commands", [])
    if not isinstance(commands, list):
        return []
    return [
        [_strip_matching_quotes(token) for token in shlex.split(cmd, posix=False)]
        for cmd in commands if isinstance(cmd, str) and cmd.strip()
    ]


def expected_effect_from_gate(gate: dict[str, Any]) -> ExpectedEffect:
    """gate.rules.forbidden_paths becomes ExpectedEffect.forbidden_paths - the gate's
    own scope rule finally has teeth here instead of sitting unused in the schema."""
    rules = gate.get("rules", {}) if isinstance(gate, dict) else {}
    forbidden = rules.get("forbidden_paths", [])
    forbidden_paths = [path for path in forbidden if isinstance(path, str)] if isinstance(forbidden, list) else []
    return ExpectedEffect(change_type="ANY", forbidden_paths=forbidden_paths)


def run_deterministic_layer(
    project_root: Path,
    patch: str,
    gate: dict[str, Any],
    *,
    timeout: int = 300,
) -> list[VerificationCheck]:
    """Effect/scope re-check plus every gate.rules.required_commands, all run
    against a fresh worktree with `patch` applied - independent of whatever
    worktree originally produced it."""
    backend = GitWorktreeExecutionBackend(project_root)
    checks: list[VerificationCheck] = []

    expected = expected_effect_from_gate(gate)
    effect = verify_effect(patch, expected)
    checks.append(VerificationCheck(
        check="effect-scope",
        status="passed" if effect.outcome == "satisfied" else "failed",
        execution_status="EXPECTED_EFFECT_PRESENT" if effect.outcome == "satisfied" else "SCOPE_VIOLATION",
        reason=effect.reason,
        command=[],
        process_outcome="n/a",
        returncode=None,
        patch=patch,
        stdout="",
        stderr="",
        base_commit="",
    ))

    for command in required_commands_from_gate(gate):
        check_name = " ".join(command)
        try:
            result = backend.run(command, timeout=timeout, apply_patch=patch)
        except (RuntimeError, ValueError) as exc:
            checks.append(VerificationCheck(
                check=check_name, status="inconclusive", execution_status="VERIFICATION_RUN_ERROR",
                reason=str(exc), command=command, process_outcome="n/a", returncode=None,
                patch="", stdout="", stderr="", base_commit="",
            ))
            continue
        status, execution_status, reason = classify_generic_execution(result)
        checks.append(_check_from_result(check_name, result, status, execution_status, reason))

    return checks


def _extract_new_file_content(patch: str, path: str) -> str | None:
    """Pulls the added-lines content of one newly created file out of a unified diff.

    Used to read a structured review verdict the reviewer wrote inside its worktree:
    the file shows up as an addition in the resulting patch, so this reads it from
    observed diff content rather than trusting anything the reviewer said in stdout.
    """
    # [\s\S]*? (not `.` + re.DOTALL) spans the multi-line file-mode header only; the
    # capture group must NOT have . match newlines, or one "+"-prefixed line would
    # swallow the rest of the patch (including the next file's own "+++ b/..." header).
    pattern = re.compile(
        rf"^diff --git a/{re.escape(path)} b/{re.escape(path)}\n[\s\S]*?\n@@[^\n]*@@\n((?:\+.*\n?)*)",
        re.MULTILINE,
    )
    match = pattern.search(patch)
    if not match:
        return None
    lines = match.group(1).splitlines()
    return "\n".join(line[1:] for line in lines if line.startswith("+"))


def build_review_prompt(diff: str, objective: str) -> str:
    return (
        f"You are reviewing a code change made by a different AI agent toward this objective:\n"
        f"{objective}\n\n"
        f"Do not apply, re-run, or modify the change. Review the diff below for correctness, "
        f"whether it actually addresses the objective, and any obvious risk.\n\n"
        f"Write your verdict to a new file named {REVIEW_VERDICT_FILENAME} in the current "
        f"directory with exactly this JSON shape and nothing else in the file:\n"
        f'{{"verdict": "pass", "notes": "short reason"}}\n'
        f'verdict must be exactly one of "pass", "fail", or "inconclusive". '
        f"Do not create or modify any other file.\n\n"
        f"--- diff to review ---\n{diff}\n--- end diff ---"
    )


def run_independent_review_layer(
    project_root: Path,
    patch: str,
    objective: str,
    reviewer: Any,
    *,
    timeout: int = 300,
) -> VerificationCheck:
    """Dispatches `reviewer` (an AgentRuntime adapter, expected to be a DIFFERENT
    provider than whoever produced `patch`) to review it and write a structured
    verdict file. A missing or unparsable verdict is inconclusive, never a pass."""
    backend = GitWorktreeExecutionBackend(project_root)
    prompt = build_review_prompt(patch, objective)
    result = backend.run(
        lambda worktree: reviewer.build_exec_command(prompt, worktree),
        timeout=timeout,
        apply_patch=patch,
    )

    check_name = f"independent-review:{reviewer.id}"
    if result.cancelled:
        return _check_from_result(check_name, result, "blocked", "CANCELLED", "review was cancelled before completion")
    if result.timed_out:
        return _check_from_result(check_name, result, "inconclusive", "TIMED_OUT", "review exceeded its timeout")

    raw = _extract_new_file_content(result.patch, REVIEW_VERDICT_FILENAME)
    if raw is None:
        return _check_from_result(
            check_name, result, "inconclusive", "NO_VERDICT_PRODUCED",
            f"reviewer did not write {REVIEW_VERDICT_FILENAME}; no structured verdict to trust",
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return _check_from_result(
            check_name, result, "inconclusive", "VERDICT_UNPARSABLE",
            f"reviewer's {REVIEW_VERDICT_FILENAME} was not valid JSON",
        )
    verdict = parsed.get("verdict") if isinstance(parsed, dict) else None
    if verdict not in REVIEW_VERDICTS:
        return _check_from_result(
            check_name, result, "inconclusive", "VERDICT_UNPARSABLE",
            f"reviewer's verdict field was {verdict!r}, not one of {sorted(REVIEW_VERDICTS)}",
        )
    notes = str(parsed.get("notes", "")) if isinstance(parsed, dict) else ""
    status = {"pass": "passed", "fail": "failed", "inconclusive": "inconclusive"}[verdict]
    execution_status = {"pass": "REVIEW_PASS", "fail": "REVIEW_FAIL", "inconclusive": "REVIEW_INCONCLUSIVE"}[verdict]
    return _check_from_result(check_name, result, status, execution_status, notes or f"reviewer verdict: {verdict}")
