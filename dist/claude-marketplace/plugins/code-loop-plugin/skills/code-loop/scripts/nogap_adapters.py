#!/usr/bin/env python3
"""AgentRuntime/ModelProvider adapter interfaces.

health() and capabilities() are read-only and safe to call repeatedly: health()
probes the existing connection manager (sanitized, never returns secrets) and
capabilities() is a static declaration that never shells out.

build_exec_command() is different: it returns the argv for a real, non-interactive,
sandboxed CLI invocation of the AgentRuntime. It never runs anything itself -
scripts/nogap_execution.py's GitWorktreeExecutionBackend is the only thing that
executes it, and only inside a disposable, isolated git worktree. This adapter
layer grants no acceptance authority: execution evidence produced this way is
always authority=execution, never authoritative for ACCEPT on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from nogap_connections import (
    claude_connection,
    codex_connection,
    configured_executable,
    default_secret_store,
    openrouter_connection,
)

_SECRET_KEYS = {"api_key", "token", "secret", "code_verifier", "credential_blob", "password"}


def _sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in _SECRET_KEYS}


class ExecutorNotReady(RuntimeError):
    """Raised when an AgentRuntime adapter cannot build an execution command right now."""


class Adapter(Protocol):
    id: str
    kind: str

    def health(self) -> dict[str, Any]: ...

    def capabilities(self) -> dict[str, Any]: ...


@dataclass
class CodexAgentRuntime:
    id: str = "codex"
    kind: str = "AgentRuntime"

    def health(self) -> dict[str, Any]:
        return _sanitize(codex_connection())

    def capabilities(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "can_execute": True,
            "supported_operations": ["headless_exec"],
            "allowed_exit_codes": [0],
            "note": "runs only inside an isolated git worktree; never granted acceptance authority",
        }

    def build_exec_command(self, prompt: str, worktree: Path) -> list[str]:
        path = configured_executable("codex", "CODEX_CLI_PATH")
        if not path:
            raise ExecutorNotReady("codex executable not found")
        return [path, "exec", "--sandbox", "workspace-write", "-C", str(worktree), prompt]


@dataclass
class ClaudeAgentRuntime:
    id: str = "claude"
    kind: str = "AgentRuntime"

    def health(self) -> dict[str, Any]:
        return _sanitize(claude_connection())

    def capabilities(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "can_execute": True,
            "supported_operations": ["headless_exec"],
            "allowed_exit_codes": [0],
            "note": "runs only inside an isolated git worktree; never granted acceptance authority",
        }

    def build_exec_command(self, prompt: str, worktree: Path) -> list[str]:
        path = configured_executable("claude", "CLAUDE_CODE_PATH", [
            r"%USERPROFILE%\.local\bin\claude.exe",
            r"%APPDATA%\npm\claude.cmd",
            r"%APPDATA%\npm\claude.ps1",
            r"%LOCALAPPDATA%\Programs\Claude\claude.exe",
            r"%LOCALAPPDATA%\Programs\Claude Code\claude.exe",
        ])
        if not path:
            raise ExecutorNotReady("claude executable not found")
        # --restricted strips Bash/PowerShell/REPL tools entirely: file edits only,
        # no shell, on top of the git-worktree isolation itself.
        return [path, "-p", prompt, "--restricted", "--permission-mode", "acceptEdits"]


@dataclass
class OpenRouterModelProvider:
    id: str = "openrouter"
    kind: str = "ModelProvider"

    def health(self) -> dict[str, Any]:
        return _sanitize(openrouter_connection(default_secret_store(), test=False))

    def capabilities(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "can_execute": False,
            "supported_operations": ["model_discovery"],
            "note": "execution dispatch is not implemented in this runtime milestone",
        }


ADAPTERS: dict[str, Adapter] = {
    "codex": CodexAgentRuntime(),
    "claude": ClaudeAgentRuntime(),
    "openrouter": OpenRouterModelProvider(),
}


def adapter_report() -> list[dict[str, Any]]:
    report: list[dict[str, Any]] = []
    for adapter in ADAPTERS.values():
        health = adapter.health()
        capabilities = adapter.capabilities()
        report.append({
            **capabilities,
            "status": health.get("status", "unknown"),
            "trust_status": health.get("trust_status", "NOT_READY"),
        })
    return report
