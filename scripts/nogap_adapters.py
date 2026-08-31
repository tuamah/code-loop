#!/usr/bin/env python3
"""Read-only AgentRuntime/ModelProvider adapter interfaces.

These adapters expose identity, capability declarations, and sanitized health
probes only. None of them execute project changes: execution dispatch stays
NOT_IMPLEMENTED until the runtime has complete policy gates (frozen gates,
independent verification, and separated acceptance authority) wired end to
end. health() is safe to call repeatedly and never returns secret material;
capabilities() is a static declaration and never shells out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from nogap_connections import (
    claude_connection,
    codex_connection,
    default_secret_store,
    openrouter_connection,
)

_SECRET_KEYS = {"api_key", "token", "secret", "code_verifier", "credential_blob", "password"}


def _sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in _SECRET_KEYS}


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
            "can_execute": False,
            "supported_operations": [],
            "note": "execution dispatch is not implemented in this runtime milestone",
        }


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
            "can_execute": False,
            "supported_operations": [],
            "note": "execution dispatch is not implemented in this runtime milestone",
        }


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
