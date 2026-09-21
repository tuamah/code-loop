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

    def build_exec_command(self, prompt: str, worktree: Path) -> list[str]:
        return [sys.executable, "-c", f"open('stub_agent_output.txt', 'w').write({prompt!r})"]


def init_git_repo(path: Path) -> None:
    def git(args: list[str]) -> None:
        subprocess.run(["git", *args], cwd=path, check=True, text=True, capture_output=True)

    path.mkdir(parents=True, exist_ok=True)
    git(["init", "-q"])
    git(["config", "user.email", "test@test.com"])
    git(["config", "user.name", "test"])
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    git(["add", "README.md"])
    git(["commit", "-q", "-m", "initial"])


def run_namespace(path: str, actor: str = "test-orchestrator", **overrides: Any) -> argparse.Namespace:
    defaults = {"path": path, "actor": actor, "execute": False, "execute_timeout": 600}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


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
                nogap.cmd_run(run_namespace(tmp, actor="test"))

    def test_run_with_no_ready_adapter_writes_plan_but_no_route_or_dispatch(self) -> None:
        self.set_adapters(codex=False, claude=False)
        with tempfile.TemporaryDirectory() as tmp:
            project = self.init_project(tmp, "no ready adapter")
            nogap.cmd_run(run_namespace(str(project)))
            runtime = project / ".code-loop" / "runtime"
            self.assertEqual(len(list((runtime / "plans").glob("*.json"))), 1)
            self.assertEqual(list((runtime / "routes").glob("*.json")), [])
            self.assertEqual(list((runtime / "dispatches").glob("*.json")), [])

    def test_run_with_ready_adapter_creates_linked_plan_route_dispatch(self) -> None:
        self.set_adapters(codex=True, claude=False)
        with tempfile.TemporaryDirectory() as tmp:
            project = self.init_project(tmp, "ready adapter dispatch")
            nogap.cmd_run(run_namespace(str(project)))
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
            nogap.cmd_run(run_namespace(str(project)))
            runtime = project / ".code-loop" / "runtime"
            route = json.loads(next((runtime / "routes").glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(route["selected"]["provider"], "claude")
            considered_ids = {item["provider"] for item in route["considered"]}
            self.assertEqual(considered_ids, {"codex", "claude"})

    def test_execute_flag_runs_selected_adapter_and_records_non_authoritative_evidence(self) -> None:
        self.set_adapters(codex=True, claude=False)
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            result = run_script("init", str(project), "--objective", "execute flag smoke")
            self.assertEqual(result.returncode, 0, result.stderr)

            nogap.cmd_run(run_namespace(str(project), execute=True))

            runtime = project / ".code-loop" / "runtime"
            dispatch = json.loads(next((runtime / "dispatches").glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(dispatch["status"], "intended")  # still never "executed"/"completed"

            evidence_files = list((runtime / "evidence").glob("*.json"))
            self.assertEqual(len(evidence_files), 1)
            evidence = json.loads(evidence_files[0].read_text(encoding="utf-8"))
            self.assertEqual(evidence["kind"], "execution")
            self.assertEqual(evidence["status"], "passed")
            self.assertEqual(evidence["provenance"]["authority"], "execution")
            self.assertEqual(evidence["provenance"]["dispatch_id"], dispatch["id"])
            self.assertEqual(evidence["provenance"]["provider"], "codex")

            artifact_files = list((runtime / "artifacts").glob("*.patch"))
            self.assertEqual(len(artifact_files), 1)
            self.assertIn("stub_agent_output.txt", artifact_files[0].read_text(encoding="utf-8"))

            validated = run_script("validate", str(project))
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)

    def test_golden_regression_clean_exit_with_zero_effect_is_never_passed(self) -> None:
        """F-EXEC-SEMANTIC golden regression.

        Observed live against the real Codex CLI on Windows: its internal sandbox failed
        to write anything (CreateProcessWithLogonW error) while the process itself still
        exited 0. A naive `returncode == 0 -> passed` mapping recorded a false success.
        This reproduces that exact shape deterministically (stub adapter, exit 0, empty
        patch) and asserts the runtime never calls it "passed" again.
        """

        class SilentlySucceedingAdapter(StubAdapter):
            def build_exec_command(self, prompt: str, worktree: Path) -> list[str]:
                # Exits 0 and touches nothing - exactly what a sandbox-blocked agent CLI did.
                return [sys.executable, "-c", "pass"]

        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS["codex"] = SilentlySucceedingAdapter("codex", ready=True)
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            run_script("init", str(project), "--objective", "golden regression: clean exit, zero effect")

            nogap.cmd_run(run_namespace(str(project), execute=True))

            runtime = project / ".code-loop" / "runtime"
            evidence = json.loads(next((runtime / "evidence").glob("*.json")).read_text(encoding="utf-8"))
            self.assertNotEqual(evidence["status"], "passed")
            self.assertEqual(evidence["status"], "failed")
            self.assertIn("NO_EXPECTED_EFFECT", evidence["summary"])

    def test_golden_regression_crashed_process_with_partial_effect_is_never_passed(self) -> None:
        """F-EXEC-SEMANTIC golden regression, symmetric case.

        The inverse of the RC=0 bug: an agent that writes the expected file and then
        crashes (nonzero exit) must not be trusted as complete just because the patch
        happens to contain the right change. Effect satisfaction alone is not success.
        """

        class CrashesAfterPartialEffectAdapter(StubAdapter):
            def build_exec_command(self, prompt: str, worktree: Path) -> list[str]:
                return [
                    sys.executable, "-c",
                    "open('stub_agent_output.txt', 'w').write('partial'); import sys; sys.exit(1)",
                ]

        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS["codex"] = CrashesAfterPartialEffectAdapter("codex", ready=True)
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            run_script("init", str(project), "--objective", "golden regression: partial effect then crash")

            nogap.cmd_run(run_namespace(str(project), execute=True))

            runtime = project / ".code-loop" / "runtime"
            evidence = json.loads(next((runtime / "evidence").glob("*.json")).read_text(encoding="utf-8"))
            # the effect really is present in the patch - that alone must still not be "passed"
            self.assertIn("stub_agent_output.txt", next((runtime / "artifacts").glob("*.patch")).read_text(encoding="utf-8"))
            self.assertNotEqual(evidence["status"], "passed")
            self.assertEqual(evidence["status"], "failed")
            self.assertIn("EFFECT_PRESENT_BUT_PROCESS_ABNORMAL", evidence["summary"])

    def test_without_execute_flag_no_evidence_or_artifact_is_written(self) -> None:
        self.set_adapters(codex=True, claude=False)
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            run_script("init", str(project), "--objective", "no execute by default")
            nogap.cmd_run(run_namespace(str(project)))  # execute=False (default)
            runtime = project / ".code-loop" / "runtime"
            self.assertEqual(list((runtime / "evidence").glob("*.json")), [])
            self.assertEqual(list((runtime / "artifacts").glob("*.patch")), [])

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
            nogap.cmd_run(run_namespace(str(project)))
            # health() (a status probe) is expected; nothing beyond that should touch the adapter.
            self.assertTrue(invoked["called"])
            runtime = project / ".code-loop" / "runtime"
            dispatch = json.loads(next((runtime / "dispatches").glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(dispatch["status"], "intended")
            self.assertEqual(list((runtime / "evidence").glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
