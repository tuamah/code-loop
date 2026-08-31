#!/usr/bin/env python3
"""Execution semantics: turns raw process facts + observed effect into a verdict.

Two false-success shapes are both closed here, deliberately kept as separate
concerns:

1. RC=0, no effect (observed live: Codex's Windows sandbox silently failed to
   write while the CLI still exited 0). Fixed by never trusting returncode as
   proof of task completion - verify_effect() judges the patch alone.

2. Effect present, but the process then crashed (e.g. an agent writes half the
   expected change, then exits 1). Fixed by NOT letting effect satisfaction
   alone imply success either - classify_agent_execution() requires BOTH a
   normal process exit AND a satisfied effect:

       execution success = normal process completion AND verified expected effect

   never just RC==0, and never just "effect exists regardless of crash".

verify_effect() knows nothing about returncode, timeouts, or cancellation - it
only reads the patch (observed world state) against an ExpectedEffect. Process
facts (ProcessOutcome, allowed_exit_codes) are combined with the effect verdict
one layer up, in classify_agent_execution(). Neither function lives in
GitWorktreeExecutionBackend: the backend only ever reports facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nogap_execution import ExecutionResult

_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$", re.MULTILINE)

CHANGE_TYPES = {"CREATE", "MODIFY", "DELETE", "NO_CHANGE_ALLOWED", "ANY"}
DEFAULT_ALLOWED_EXIT_CODES = (0,)


def touched_paths(patch: str) -> set[str]:
    """Paths git actually recorded as changed, parsed from the unified diff itself."""
    return {match.group(2) for match in _DIFF_HEADER_RE.finditer(patch)}


@dataclass
class ExpectedEffect:
    change_type: str = "ANY"
    required_paths: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    content_contains: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.change_type not in CHANGE_TYPES:
            raise ValueError(f"change_type must be one of {sorted(CHANGE_TYPES)}, got {self.change_type!r}")


@dataclass
class EffectVerdict:
    """A pure judgment about the patch. Never sees returncode/timeout/cancel."""

    outcome: str  # "satisfied" | "unsatisfied"
    reason: str
    observed_paths: list[str]


def verify_effect(patch: str, expected: ExpectedEffect) -> EffectVerdict:
    observed = sorted(touched_paths(patch))

    if expected.change_type == "NO_CHANGE_ALLOWED":
        if observed:
            return EffectVerdict("unsatisfied", f"no changes were expected; observed: {observed}", observed)
        return EffectVerdict("satisfied", "no changes observed, as required", observed)

    forbidden_hit = sorted(set(observed) & set(expected.forbidden_paths))
    if forbidden_hit:
        return EffectVerdict("unsatisfied", f"forbidden paths were modified: {forbidden_hit}", observed)

    if expected.change_type == "ANY" and not expected.required_paths:
        if observed:
            return EffectVerdict("satisfied", f"observed changes: {observed}", observed)
        return EffectVerdict("unsatisfied", "no changes were observed in the patch", observed)

    missing = [path for path in expected.required_paths if path not in observed]
    if missing:
        return EffectVerdict("unsatisfied", f"required paths were not touched: {missing}", observed)

    for path, needle in expected.content_contains.items():
        if needle not in patch:
            return EffectVerdict("unsatisfied", f"expected content {needle!r} not found for {path}", observed)

    return EffectVerdict("satisfied", "all required paths and content matched", observed)


def classify_generic_execution(result: "ExecutionResult") -> tuple[str, str, str]:
    """Maps raw process facts to a status for `nogap execute`'s arbitrary-command case.

    Unlike AgentRuntime dispatch, an arbitrary command's returncode (a test runner, a
    linter) really is the authoritative signal here - that is what exit codes are for.
    """
    if result.cancelled:
        return "blocked", "CANCELLED", "execution was cancelled before completion"
    if result.timed_out:
        return "inconclusive", "TIMED_OUT", "execution exceeded its timeout"
    if result.returncode == 0:
        return "passed", "PROCESS_EXIT_OK", "process exited with code 0"
    return "failed", "PROCESS_EXIT_ERROR", f"process exited with code {result.returncode}"


def classify_agent_execution(
    process_outcome: str,
    returncode: int | None,
    effect: EffectVerdict,
    allowed_exit_codes: "list[int] | tuple[int, ...]" = DEFAULT_ALLOWED_EXIT_CODES,
) -> tuple[str, str, str]:
    """Combines ProcessOutcome + EffectVerdict into (status, execution_status, reason).

    status is the runtime-wide EVIDENCE_STATUS vocabulary (passed/failed/blocked/
    inconclusive). Process outcome short-circuits first: a timed-out or cancelled
    run is inconclusive/blocked regardless of what the (possibly incomplete) patch
    shows - the effect verdict is only meaningful once the process actually ran to
    a real conclusion.
    """
    if process_outcome == "cancelled":
        return "blocked", "CANCELLED", "execution was cancelled before completion"
    if process_outcome == "timed_out":
        return "inconclusive", "TIMED_OUT", "execution exceeded its timeout"

    process_ok = returncode in allowed_exit_codes

    if process_ok and effect.outcome == "satisfied":
        return "passed", "EXPECTED_EFFECT_PRESENT", effect.reason

    if process_ok:  # effect unsatisfied
        return "failed", "NO_EXPECTED_EFFECT", effect.reason

    if effect.outcome == "satisfied":
        return (
            "failed",
            "EFFECT_PRESENT_BUT_PROCESS_ABNORMAL",
            f"the expected effect appears present, but the process exited abnormally "
            f"(returncode={returncode}); a crashed run cannot be trusted as complete. "
            f"effect detail: {effect.reason}",
        )

    return (
        "failed",
        "PROCESS_ABNORMAL_NO_EFFECT",
        f"process exited abnormally (returncode={returncode}) and no expected effect was observed",
    )
