#!/usr/bin/env python3
"""Checks for the read-only AgentRuntime/ModelProvider adapter interfaces."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nogap_adapters  # noqa: E402
import nogap_connections  # noqa: E402


class AdapterTests(unittest.TestCase):
    def test_adapters_declare_stable_identity_and_kind(self) -> None:
        self.assertEqual((nogap_adapters.CodexAgentRuntime().id, nogap_adapters.CodexAgentRuntime().kind), ("codex", "AgentRuntime"))
        self.assertEqual((nogap_adapters.ClaudeAgentRuntime().id, nogap_adapters.ClaudeAgentRuntime().kind), ("claude", "AgentRuntime"))
        self.assertEqual(
            (nogap_adapters.OpenRouterModelProvider().id, nogap_adapters.OpenRouterModelProvider().kind),
            ("openrouter", "ModelProvider"),
        )

    def test_capabilities_never_claim_execution(self) -> None:
        for adapter in nogap_adapters.ADAPTERS.values():
            self.assertFalse(adapter.capabilities()["can_execute"])

    def test_health_never_returns_secret_fields(self) -> None:
        for adapter in nogap_adapters.ADAPTERS.values():
            health = adapter.health()
            raw = json.dumps(health)
            for key in nogap_adapters._SECRET_KEYS:
                self.assertNotIn(key, health)
            self.assertNotIn("api_key", raw)

    def test_missing_executable_reports_not_ready_not_connected(self) -> None:
        original = nogap_connections.configured_executable
        nogap_connections.configured_executable = lambda *args, **kwargs: None
        try:
            health = nogap_adapters.CodexAgentRuntime().health()
            self.assertEqual(health["trust_status"], "NOT_READY")
            self.assertNotEqual(health["status"], "connected")
        finally:
            nogap_connections.configured_executable = original

    def test_adapter_report_covers_every_adapter_and_stays_sanitized(self) -> None:
        report = nogap_adapters.adapter_report()
        self.assertEqual({item["id"] for item in report}, {"codex", "claude", "openrouter"})
        for item in report:
            self.assertIn("trust_status", item)
            self.assertFalse(item["can_execute"])
            self.assertNotIn("api_key", json.dumps(item))


if __name__ == "__main__":
    unittest.main()
