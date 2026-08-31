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
SPEC.loader.exec_module(nogap_dashboard)


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


if __name__ == "__main__":
    unittest.main()
