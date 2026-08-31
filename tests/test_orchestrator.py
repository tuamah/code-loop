#!/usr/bin/env python3
"""Checks for the orchestration-only `nogap run` command.

`nogap run` only proposes a plan, selects a route from real (stubbed here) adapter
health, and records a dispatch *intent*. It must never fabricate a route or dispatch
for an adapter that is not actually ready, and it must never invoke an adapter.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nogap  # noqa: E402
import nogap_adapters  # noqa: E402


@dataclass
class StubAdapter:
    id: str
    ready: bool
    kind: str = "AgentRuntime"

    def health(self) -> dict[str, Any]:
        return {
            "status": "connected" if self.ready else "disconnected",
            "trust_status": "READY" if self.ready else "NOT_READY",
        }

    def capabilities(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "can_execute": False, "supported_operations": []}


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/nogap.py", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


class OrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_adapters = dict(nogap_adapters.ADAPTERS)

    def tearDown(self) -> None:
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS.update(self._original_adapters)

    def set_adapters(self, **ready_by_id: bool) -> None:
        nogap_adapters.ADAPTERS.clear()
        for adapter_id, ready in ready_by_id.items():
            nogap_adapters.ADAPTERS[adapter_id] = StubAdapter(adapter_id, ready=ready)

    def init_project(self, tmp: str, objective: str) -> Path:
        project = Path(tmp)
        result = run_script("init", str(project), "--objective", objective)
        self.assertEqual(result.returncode, 0, result.stderr)
        return project

    def test_run_requires_an_existing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                nogap.cmd_run(argparse.Namespace(path=tmp, actor="test"))

    def test_run_with_no_ready_adapter_writes_plan_but_no_route_or_dispatch(self) -> None:
        self.set_adapters(codex=False, claude=False)
        with tempfile.TemporaryDirectory() as tmp:
            project = self.init_project(tmp, "no ready adapter")
            nogap.cmd_run(argparse.Namespace(path=str(project), actor="test-orchestrator"))
            runtime = project / ".code-loop" / "runtime"
            self.assertEqual(len(list((runtime / "plans").glob("*.json"))), 1)
            self.assertEqual(list((runtime / "routes").glob("*.json")), [])
            self.assertEqual(list((runtime / "dispatches").glob("*.json")), [])

    def test_run_with_ready_adapter_creates_linked_plan_route_dispatch(self) -> None:
        self.set_adapters(codex=True, claude=False)
        with tempfile.TemporaryDirectory() as tmp:
            project = self.init_project(tmp, "ready adapter dispatch")
            nogap.cmd_run(argparse.Namespace(path=str(project), actor="test-orchestrator"))
            runtime = project / ".code-loop" / "runtime"

            plan_files = list((runtime / "plans").glob("*.json"))
            route_files = list((runtime / "routes").glob("*.json"))
            dispatch_files = list((runtime / "dispatches").glob("*.json"))
            self.assertEqual(len(plan_files), 1)
            self.assertEqual(len(route_files), 1)
            self.assertEqual(len(dispatch_files), 1)

            plan = json.loads(plan_files[0].read_text(encoding="utf-8"))
            route = json.loads(route_files[0].read_text(encoding="utf-8"))
            dispatch = json.loads(dispatch_files[0].read_text(encoding="utf-8"))

            self.assertEqual(route["selected"], {"provider": "codex", "runtime": "codex"})
            self.assertEqual(dispatch["plan_id"], plan["id"])
            self.assertEqual(dispatch["route_id"], route["id"])
            self.assertEqual(dispatch["status"], "intended")

            result = run_script("validate", str(project))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_run_never_selects_an_adapter_that_is_not_ready(self) -> None:
        self.set_adapters(codex=False, claude=True)
        with tempfile.TemporaryDirectory() as tmp:
            project = self.init_project(tmp, "only claude ready")
            nogap.cmd_run(argparse.Namespace(path=str(project), actor="test-orchestrator"))
            runtime = project / ".code-loop" / "runtime"
            route = json.loads(next((runtime / "routes").glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(route["selected"]["provider"], "claude")
            considered_ids = {item["provider"] for item in route["considered"]}
            self.assertEqual(considered_ids, {"codex", "claude"})

    def test_run_never_invokes_the_selected_adapter(self) -> None:
        invoked = {"called": False}

        class RecordingAdapter(StubAdapter):
            def health(self) -> dict[str, Any]:
                invoked["called"] = True
                return super().health()

        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS["codex"] = RecordingAdapter("codex", ready=True)
        with tempfile.TemporaryDirectory() as tmp:
            project = self.init_project(tmp, "no invocation, only health probe")
            nogap.cmd_run(argparse.Namespace(path=str(project), actor="test-orchestrator"))
            # health() (a status probe) is expected; nothing beyond that should touch the adapter.
            self.assertTrue(invoked["called"])
            runtime = project / ".code-loop" / "runtime"
            dispatch = json.loads(next((runtime / "dispatches").glob("*.json")).read_text(encoding="utf-8"))
            self.assertIn("not implemented", dispatch["reason"])


if __name__ == "__main__":
    unittest.main()
