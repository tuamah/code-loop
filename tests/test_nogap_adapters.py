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

    def test_only_agent_runtimes_declare_execute_capability(self) -> None:
        # AgentRuntime adapters (codex, claude) can build a sandboxed exec command;
        # the ModelProvider (openrouter) never executes anything.
        self.assertTrue(nogap_adapters.CodexAgentRuntime().capabilities()["can_execute"])
        self.assertTrue(nogap_adapters.ClaudeAgentRuntime().capabilities()["can_execute"])
        self.assertFalse(nogap_adapters.OpenRouterModelProvider().capabilities()["can_execute"])

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
        by_id = {item["id"]: item for item in report}
        self.assertTrue(by_id["codex"]["can_execute"])
        self.assertTrue(by_id["claude"]["can_execute"])
        self.assertFalse(by_id["openrouter"]["can_execute"])
        for item in report:
            self.assertIn("trust_status", item)
            self.assertNotIn("api_key", json.dumps(item))


class ExecCommandBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original = nogap_adapters.configured_executable

    def tearDown(self) -> None:
        nogap_adapters.configured_executable = self._original

    def test_codex_exec_command_is_sandboxed_and_scoped_to_the_worktree(self) -> None:
        nogap_adapters.configured_executable = lambda *args, **kwargs: r"C:\fake\codex.exe"
        worktree = Path("C:/fake/worktree")
        command = nogap_adapters.CodexAgentRuntime().build_exec_command("do the thing", worktree)
        self.assertEqual(command[0], r"C:\fake\codex.exe")
        self.assertIn("exec", command)
        self.assertIn("--sandbox", command)
        self.assertIn("workspace-write", command)
        self.assertIn(str(worktree), command)
        self.assertEqual(command[-1], "do the thing")
        # never bypasses sandboxing or approvals
        joined = " ".join(command)
        self.assertNotIn("dangerously-bypass", joined)

    def test_claude_exec_command_is_restricted_and_non_interactive(self) -> None:
        nogap_adapters.configured_executable = lambda *args, **kwargs: r"C:\fake\claude.exe"
        worktree = Path("C:/fake/worktree")
        command = nogap_adapters.ClaudeAgentRuntime().build_exec_command("do the thing", worktree)
        self.assertEqual(command[0], r"C:\fake\claude.exe")
        self.assertIn("-p", command)
        self.assertIn("do the thing", command)
        self.assertIn("--restricted", command)
        self.assertIn("--permission-mode", command)
        self.assertIn("acceptEdits", command)
        joined = " ".join(command)
        self.assertNotIn("bypassPermissions", joined)
        self.assertNotIn("dangerously-skip-permissions", joined)

    def test_missing_executable_raises_executor_not_ready(self) -> None:
        nogap_adapters.configured_executable = lambda *args, **kwargs: None
        with self.assertRaises(nogap_adapters.ExecutorNotReady):
            nogap_adapters.CodexAgentRuntime().build_exec_command("x", Path("."))
        with self.assertRaises(nogap_adapters.ExecutorNotReady):
            nogap_adapters.ClaudeAgentRuntime().build_exec_command("x", Path("."))


if __name__ == "__main__":
    unittest.main()
