#!/usr/bin/env python3
"""Checks for the backend-backed NoGapCode dashboard."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("nogap_dashboard", ROOT / "scripts" / "nogap_dashboard.py")
assert SPEC and SPEC.loader
nogap_dashboard = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(ROOT / "scripts"))
SPEC.loader.exec_module(nogap_dashboard)

CONNECTIONS_SPEC = importlib.util.spec_from_file_location("nogap_connections", ROOT / "scripts" / "nogap_connections.py")
assert CONNECTIONS_SPEC and CONNECTIONS_SPEC.loader
nogap_connections = importlib.util.module_from_spec(CONNECTIONS_SPEC)
CONNECTIONS_SPEC.loader.exec_module(nogap_connections)


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


class MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, target: str) -> str | None:
        return self.values.get(target)

    def set(self, target: str, secret: str) -> None:
        self.values[target] = secret

    def delete(self, target: str) -> None:
        self.values.pop(target, None)

    def available(self) -> bool:
        return True


class DashboardBackendTests(unittest.TestCase):
    def test_payload_reports_missing_runtime_without_fake_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = nogap_dashboard.build_payload(Path(tmp))
            self.assertFalse(payload["project"]["runtime_exists"])
            self.assertEqual(payload["summary"]["projects"], 0)
            self.assertEqual(payload["system"]["runtime"], "no-runtime")

    def test_payload_uses_runtime_files_for_dashboard_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run_script("scripts/nogap.py", "init", str(project), "--objective", "real dashboard")
            run_script("scripts/nogap.py", "freeze", str(project))
            runtime = project / ".code-loop" / "runtime"
            gate = json.loads((runtime / "gates" / "gate-0001.json").read_text(encoding="utf-8"))
            gate_hash = gate["hash"]
            write_json(runtime / "claims" / "claim-0001.json", {
                "id": "claim-0001",
                "run_id": "run-0001",
                "text": "Dashboard reads real runtime files.",
                "status": "supported",
                "evidence": ["evidence-0001"],
            })
            write_json(runtime / "evidence" / "evidence-0001.json", {
                "id": "evidence-0001",
                "run_id": "run-0001",
                "kind": "test",
                "status": "passed",
                "claim_ids": ["claim-0001"],
                "provenance": {
                    "created_by": "verifier-1",
                    "actor_id": "verifier-1",
                    "authority": "verification",
                    "role": "verifier",
                    "created_at": "2026-08-31T00:00:00Z",
                    "gate_hash": gate_hash,
                },
            })
            run_script("scripts/nogap.py", "decide", str(project), "--actor-id", "acceptor-1")
            run_script("scripts/nogap.py", "learn", str(project), "--tag", "dashboard", "--text", "Dashboard reads runtime state.")
            payload = nogap_dashboard.build_payload(project)
            self.assertTrue(payload["project"]["runtime_exists"])
            self.assertEqual(payload["metrics"]["verifications"], 1)
            self.assertEqual(payload["metrics"]["decisions"], 1)
            self.assertEqual(payload["metrics"]["knowledge"], 1)
            self.assertEqual(payload["gates"][0]["passed"], 1)
            self.assertEqual(payload["decisions"][0]["status"], "ACCEPT")

    def test_nogap_cli_exposes_dashboard_command(self) -> None:
        result = run_script("scripts/nogap.py", "--help")
        self.assertIn("dashboard", result.stdout)

    def test_connections_payload_never_returns_openrouter_secret(self) -> None:
        store = MemorySecretStore()
        secret = "sk-or-1234567890abcdef"
        nogap_connections.store_openrouter_key(secret, store, verify=False)
        payload = nogap_connections.build_connections_payload(store)
        raw = json.dumps(payload)
        self.assertNotIn(secret, raw)
        openrouter = next(item for item in payload["providers"] if item["id"] == "openrouter")
        self.assertTrue(openrouter["credential_present"])
        self.assertEqual(openrouter["credential_ref"], nogap_connections.OPENROUTER_TARGET)
        self.assertTrue(openrouter["credential_hint"].startswith("sk-or-"))

    def test_openrouter_rejects_invalid_key_before_storage(self) -> None:
        store = MemorySecretStore()
        with self.assertRaises(ValueError):
            nogap_connections.store_openrouter_key("short", store)
        self.assertIsNone(store.get(nogap_connections.OPENROUTER_TARGET))

    def test_openrouter_pkce_login_keeps_verifier_server_side(self) -> None:
        store = MemorySecretStore()
        before = set(nogap_connections.OPENROUTER_PENDING_AUTH)
        payload = nogap_connections.start_openrouter_login(
            "http://127.0.0.1:8766/api/connections/openrouter/callback",
            store,
            open_browser=False,
        )
        after = set(nogap_connections.OPENROUTER_PENDING_AUTH)
        new_states = after - before
        self.assertEqual(payload["status"], "auth_pending")
        self.assertEqual(len(new_states), 1)
        self.assertIn("code_challenge=", payload["auth_url"])
        self.assertNotIn("code_verifier", payload["auth_url"])
        for state in new_states:
            nogap_connections.OPENROUTER_PENDING_AUTH.pop(state, None)

    def test_openrouter_callback_requires_known_state(self) -> None:
        store = MemorySecretStore()
        with self.assertRaises(ValueError):
            nogap_connections.complete_openrouter_login("code", "unknown-state", store)

    def test_cli_connection_probe_is_sanitized_when_missing(self) -> None:
        payload = nogap_connections.cli_connection("missing", "Missing CLI", "nogap-missing-cli-for-test")
        raw = json.dumps(payload)
        self.assertEqual(payload["status"], "disconnected")
        self.assertIn("runtime_executable", raw)
        self.assertNotIn("api_key", raw)

    def test_claude_missing_executable_is_not_treated_as_oauth(self) -> None:
        original = nogap_connections.configured_executable
        nogap_connections.configured_executable = lambda *args, **kwargs: None
        try:
            payload = nogap_connections.connect_cli("claude")
            self.assertEqual(payload["status"], "install_required")
            self.assertIn("install_url", payload)
            self.assertNotIn("auth_url", payload)
        finally:
            nogap_connections.configured_executable = original

    def test_project_registry_add_and_select_uses_existing_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "projects.json"
            project_a = Path(tmp) / "a"
            project_b = Path(tmp) / "b"
            project_a.mkdir()
            project_b.mkdir()
            original_registry = nogap_dashboard.REGISTRY_PATH
            original_project = nogap_dashboard.DashboardHandler.project
            nogap_dashboard.REGISTRY_PATH = registry
            nogap_dashboard.DashboardHandler.project = project_a
            try:
                added = nogap_dashboard.add_project(str(project_b), project_a, "Project B")
                self.assertEqual(added["selected_id"], nogap_dashboard.project_id(project_b))
                selected = nogap_dashboard.select_project(nogap_dashboard.project_id(project_a), project_b)
                self.assertEqual(selected["selected_id"], nogap_dashboard.project_id(project_a))
            finally:
                nogap_dashboard.REGISTRY_PATH = original_registry
                nogap_dashboard.DashboardHandler.project = original_project

    def test_project_registry_rejects_missing_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "projects.json"
            original_registry = nogap_dashboard.REGISTRY_PATH
            nogap_dashboard.REGISTRY_PATH = registry
            try:
                with self.assertRaises(ValueError):
                    nogap_dashboard.add_project(str(Path(tmp) / "missing"), Path(tmp))
            finally:
                nogap_dashboard.REGISTRY_PATH = original_registry

    def test_validate_runtime_returns_sanitized_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = nogap_dashboard.validate_runtime(Path(tmp))
            self.assertEqual(result["command"], "python scripts/nogap.py validate <project>")
            self.assertIn(result["status"], {"passed", "failed"})

    def test_dashboard_payload_exposes_record_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = nogap_dashboard.build_payload(Path(tmp))
            self.assertIn("records", payload)
            for name in ("claims", "evidence", "lessons", "literature", "events"):
                self.assertIn(name, payload["records"])


if __name__ == "__main__":
    unittest.main()
