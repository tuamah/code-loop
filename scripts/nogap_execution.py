#!/usr/bin/env python3
"""Isolated ExecutionBackend: runs one bounded command in a disposable git worktree.

This is the sandbox boundary from the Execution Plane. It never touches the real
working tree: it creates a detached worktree from the project's current HEAD, runs
one explicit argv command inside it under a hard timeout, captures whatever changed
as a patch, and always removes the worktree afterward, regardless of how the process
ended (exited, timed out, or was cancelled).

The command may be a fixed argv list, or a (worktree_path) -> argv builder for
callers (like an AgentRuntime adapter's build_exec_command) that need to know the
worktree path to construct their command. This module never declares success or
failure - it only reports facts (process outcome, returncode, patch). See
ExecutionResult's docstring for why, and nogap_effects.py for how a caller turns
those facts into a verdict.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


def _git(args: list[str], cwd: Path, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


@dataclass
class ExecutionResult:
    """Facts observed about one execution. Deliberately carries no success/failure verdict:

    a process exiting 0 is not proof that its task succeeded (a coding agent can exit clean
    while accomplishing nothing, e.g. because its own internal sandbox silently failed to
    write). process_outcome only ever describes *how the process ended* (exited, timed_out,
    cancelled); returncode is the raw exit code, unequal. Turning these facts into a verdict
    is the caller's job: nogap.py's classify_generic_execution() for arbitrary commands where
    returncode really is authoritative (e.g. a test runner), or nogap_effects.verify_effect()
    for AgentRuntime dispatch, which checks the patch (observed world state) against what was
    actually expected instead of trusting the process's own exit code or narrative.
    """

    execution_id: str
    command: list[str]
    returncode: int | None
    process_outcome: str
    stdout: str
    stderr: str
    duration_seconds: float
    patch: str
    base_commit: str
    cancelled: bool
    timed_out: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "command": self.command,
            "returncode": self.returncode,
            "process_outcome": self.process_outcome,
            "duration_seconds": round(self.duration_seconds, 3),
            "base_commit": self.base_commit,
            "cancelled": self.cancelled,
            "timed_out": self.timed_out,
        }


class ExecutionHandle:
    """Lets an in-process caller cancel a running execution while it is blocking."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self.cancelled = False

    def _attach(self, process: subprocess.Popen[str]) -> None:
        self._process = process

    def cancel(self) -> None:
        self.cancelled = True
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()


class GitWorktreeExecutionBackend:
    """ExecutionBackend that runs one bounded command inside a disposable git worktree."""

    id = "git-worktree"
    kind = "ExecutionBackend"

    def __init__(self, project_root: Path, sandbox_root: Path | None = None) -> None:
        self.project_root = project_root.resolve()
        self.sandbox_root = (sandbox_root or (self.project_root / ".nogap" / "worktrees")).resolve()

    def run(
        self,
        command: list[str] | Callable[[Path], list[str]],
        *,
        timeout: int = 300,
        handle: ExecutionHandle | None = None,
    ) -> ExecutionResult:
        if not callable(command) and not command:
            raise ValueError("command must be a non-empty argv list or a (worktree) -> argv builder")

        head = _git(["rev-parse", "HEAD"], cwd=self.project_root)
        if head.returncode != 0:
            raise RuntimeError(f"cannot resolve HEAD in {self.project_root}: {head.stderr.strip()}")
        base_commit = head.stdout.strip()

        execution_id = f"exec-{uuid.uuid4().hex[:12]}"
        worktree_path = self.sandbox_root / execution_id
        self.sandbox_root.mkdir(parents=True, exist_ok=True)

        add = _git(["worktree", "add", "--detach", str(worktree_path), base_commit], cwd=self.project_root, timeout=60)
        if add.returncode != 0:
            raise RuntimeError(f"failed to create isolated worktree: {add.stderr.strip()}")

        handle = handle or ExecutionHandle()
        stdout, stderr, returncode, timed_out = "", "", None, False
        resolved_command: list[str] = []
        started = time.monotonic()
        try:
            resolved_command = command(worktree_path) if callable(command) else command
            if not resolved_command:
                raise ValueError("command builder returned an empty argv list")
            if not handle.cancelled:
                process = subprocess.Popen(
                    resolved_command,
                    cwd=worktree_path,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                handle._attach(process)
                try:
                    stdout, stderr = process.communicate(timeout=timeout)
                    returncode = process.returncode
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate()
                    timed_out = True
                    returncode = process.returncode
        finally:
            duration = time.monotonic() - started
            # `git diff <base>` alone misses new untracked files, which is the common case for
            # agent-created files. Stage everything in the disposable worktree's index first so
            # the diff captures additions, modifications, and deletions.
            _git(["add", "-A"], cwd=worktree_path, timeout=60)
            diff = _git(["diff", "--cached", "--binary"], cwd=worktree_path, timeout=60)
            patch = diff.stdout if diff.returncode == 0 else ""
            remove = _git(["worktree", "remove", "--force", str(worktree_path)], cwd=self.project_root, timeout=60)
            if remove.returncode != 0:
                shutil.rmtree(worktree_path, ignore_errors=True)
                _git(["worktree", "prune"], cwd=self.project_root, timeout=30)

        if handle.cancelled:
            process_outcome = "cancelled"
        elif timed_out:
            process_outcome = "timed_out"
        else:
            process_outcome = "exited"

        return ExecutionResult(
            execution_id=execution_id,
            command=resolved_command,
            returncode=returncode,
            process_outcome=process_outcome,
            stdout=stdout[-8000:],
            stderr=stderr[-8000:],
            duration_seconds=duration,
            patch=patch,
            base_commit=base_commit,
            cancelled=handle.cancelled,
            timed_out=timed_out,
        )
