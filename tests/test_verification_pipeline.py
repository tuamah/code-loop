#!/usr/bin/env python3
"""Checks for the M6-D Independent Verification Pipeline.

Covers both layers of nogap_verification.py directly, and cmd_verify end to end
through the real CLI. A regression test reproduces the exact extraction bug found
live: re.DOTALL made `.` match newlines inside the content-line pattern, so one
"+"-prefixed line swallowed the rest of the patch, including the next file's own
"+++ b/..." header.
"""

from __future__ import annotations

import argparse
import contextlib
import io
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
from nogap_verification import (  # noqa: E402
    REVIEW_VERDICT_FILENAME,
    _extract_new_file_content,
    expected_effect_from_gate,
    required_commands_from_gate,
    run_deterministic_layer,
    run_independent_review_layer,
)


def verify_namespace(path: str, **overrides: Any) -> argparse.Namespace:
    defaults = {
        "path": path, "dispatch": None, "timeout": 60,
        "review": False, "review_timeout": 60, "actor": "test-verifier",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/nogap.py", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, capture_output=True)


def init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(["init", "-q"], path)
    git(["config", "user.email", "test@test.com"], path)
    git(["config", "user.name", "test"], path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    git(["add", "README.md"], path)
    git(["commit", "-q", "-m", "initial"], path)


MULTI_FILE_PATCH = (
    'diff --git a/.nogap-review.json b/.nogap-review.json\n'
    'new file mode 100644\n'
    'index 0000000..345eed8\n'
    '--- /dev/null\n'
    '+++ b/.nogap-review.json\n'
    '@@ -0,0 +1 @@\n'
    '+{"verdict": "pass", "notes": "hi"}\n'
    'diff --git a/smoke_target.txt b/smoke_target.txt\n'
    'new file mode 100644\n'
    'index 0000000..893a3d7\n'
    '--- /dev/null\n'
    '+++ b/smoke_target.txt\n'
    '@@ -0,0 +1 @@\n'
    '+verification smoke test\n'
)


class ExtractNewFileContentTests(unittest.TestCase):
    def test_regression_stops_at_next_files_diff_header(self) -> None:
        # This exact shape broke the extraction live: re.DOTALL made the content-line
        # pattern's `.` match newlines, so it swallowed everything including the next
        # file's own "+++ b/..." header (which itself starts with "+").
        content = _extract_new_file_content(MULTI_FILE_PATCH, ".nogap-review.json")
        self.assertEqual(content, '{"verdict": "pass", "notes": "hi"}')

    def test_missing_file_returns_none(self) -> None:
        self.assertIsNone(_extract_new_file_content(MULTI_FILE_PATCH, "nonexistent.json"))

    def test_extracts_second_files_content_correctly_too(self) -> None:
        content = _extract_new_file_content(MULTI_FILE_PATCH, "smoke_target.txt")
        self.assertEqual(content, "verification smoke test")


class GateHelperTests(unittest.TestCase):
    def test_required_commands_from_gate_splits_shell_style_strings(self) -> None:
        gate = {"rules": {"required_commands": ["python -m pytest -q", 'echo "hi there"']}}
        commands = required_commands_from_gate(gate)
        self.assertEqual(commands, [["python", "-m", "pytest", "-q"], ["echo", "hi there"]])

    def test_required_commands_from_gate_handles_missing_rules(self) -> None:
        self.assertEqual(required_commands_from_gate({}), [])

    def test_expected_effect_from_gate_uses_forbidden_paths(self) -> None:
        gate = {"rules": {"forbidden_paths": ["README.md", "secrets.env"]}}
        expected = expected_effect_from_gate(gate)
        self.assertEqual(expected.change_type, "ANY")
        self.assertEqual(expected.forbidden_paths, ["README.md", "secrets.env"])


class DeterministicLayerTests(unittest.TestCase):
    def test_effect_scope_check_passes_when_nothing_forbidden_touched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            patch = (
                "diff --git a/new_file.txt b/new_file.txt\n"
                "new file mode 100644\n--- /dev/null\n+++ b/new_file.txt\n"
                "@@ -0,0 +1 @@\n+hi\n"
            )
            gate = {"rules": {"forbidden_paths": ["README.md"], "required_commands": []}}
            checks = run_deterministic_layer(project, patch, gate)
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0].check, "effect-scope")
            self.assertEqual(checks[0].status, "passed")

    def test_effect_scope_check_fails_when_forbidden_path_touched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            patch = (
                "diff --git a/README.md b/README.md\n"
                "index cebddc4..e068484 100644\n--- a/README.md\n+++ b/README.md\n"
                "@@ -1 +1 @@\n-hello\n+goodbye\n"
            )
            gate = {"rules": {"forbidden_paths": ["README.md"], "required_commands": []}}
            checks = run_deterministic_layer(project, patch, gate)
            self.assertEqual(checks[0].status, "failed")
            self.assertEqual(checks[0].execution_status, "SCOPE_VIOLATION")

    def test_required_command_runs_against_the_patched_worktree_and_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            patch = (
                "diff --git a/target.txt b/target.txt\n"
                "new file mode 100644\n--- /dev/null\n+++ b/target.txt\n"
                "@@ -0,0 +1 @@\n+content\n"
            )
            gate = {"rules": {"forbidden_paths": [], "required_commands": [
                f'{sys.executable} -c "import pathlib,sys; sys.exit(0 if pathlib.Path(\'target.txt\').exists() else 1)"'
            ]}}
            checks = run_deterministic_layer(project, patch, gate)
            self.assertEqual(len(checks), 2)
            command_check = checks[1]
            self.assertEqual(command_check.status, "passed")

    def test_required_command_that_fails_is_reported_failed_not_silently_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            gate = {"rules": {"forbidden_paths": [], "required_commands": [f"{sys.executable} -c \"import sys; sys.exit(1)\""]}}
            checks = run_deterministic_layer(project, "", gate)
            command_check = checks[1]
            self.assertEqual(command_check.status, "failed")


@dataclass
class StubReviewer:
    id: str
    verdict_content: str
    kind: str = "AgentRuntime"

    def health(self) -> dict[str, Any]:
        return {"status": "connected", "trust_status": "READY"}

    def capabilities(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "can_execute": True, "allowed_exit_codes": [0]}

    def build_exec_command(self, prompt: str, worktree: Path) -> list[str]:
        literal = json.dumps(self.verdict_content)
        return [sys.executable, "-c", f"open({json.dumps(REVIEW_VERDICT_FILENAME)}, 'w').write({literal})"]


class IndependentReviewLayerTests(unittest.TestCase):
    def test_valid_pass_verdict_is_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            reviewer = StubReviewer("stub-reviewer", '{"verdict": "pass", "notes": "looks right"}')
            check = run_independent_review_layer(project, "", "objective", reviewer)
            self.assertEqual(check.status, "passed")
            self.assertEqual(check.execution_status, "REVIEW_PASS")
            self.assertEqual(check.reason, "looks right")

    def test_valid_fail_verdict_is_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            reviewer = StubReviewer("stub-reviewer", '{"verdict": "fail", "notes": "wrong file"}')
            check = run_independent_review_layer(project, "", "objective", reviewer)
            self.assertEqual(check.status, "failed")

    def test_missing_verdict_file_is_inconclusive_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)

            @dataclass
            class SilentReviewer(StubReviewer):
                def build_exec_command(self, prompt: str, worktree: Path) -> list[str]:
                    return [sys.executable, "-c", "pass"]

            check = run_independent_review_layer(project, "", "objective", SilentReviewer("silent", ""))
            self.assertEqual(check.status, "inconclusive")
            self.assertEqual(check.execution_status, "NO_VERDICT_PRODUCED")

    def test_invalid_json_verdict_is_inconclusive_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            reviewer = StubReviewer("bad-json-reviewer", "not valid json at all")
            check = run_independent_review_layer(project, "", "objective", reviewer)
            self.assertEqual(check.status, "inconclusive")
            self.assertEqual(check.execution_status, "VERDICT_UNPARSABLE")

    def test_unrecognized_verdict_value_is_inconclusive_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            reviewer = StubReviewer("weird-verdict-reviewer", '{"verdict": "definitely maybe", "notes": ""}')
            check = run_independent_review_layer(project, "", "objective", reviewer)
            self.assertEqual(check.status, "inconclusive")
            self.assertEqual(check.execution_status, "VERDICT_UNPARSABLE")


@dataclass
class StubExecutor:
    id: str
    kind: str = "AgentRuntime"

    def health(self) -> dict[str, Any]:
        return {"status": "connected", "trust_status": "READY"}

    def capabilities(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "can_execute": True, "allowed_exit_codes": [0]}

    def build_exec_command(self, prompt: str, worktree: Path) -> list[str]:
        return [sys.executable, "-c", "open('target.txt', 'w').write('done')"]


class CmdVerifyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_adapters = dict(nogap_adapters.ADAPTERS)

    def tearDown(self) -> None:
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS.update(self._original_adapters)

    def set_adapters(self, **adapters: Any) -> None:
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS.update(adapters)

    def setup_project_with_gate(self, tmp: str, required_commands=None, forbidden_paths=None) -> Path:
        project = Path(tmp)
        init_git_repo(project)
        result = run_script("init", str(project), "--objective", "verification pipeline test")
        self.assertEqual(result.returncode, 0, result.stderr)
        gate_path = project / ".code-loop" / "runtime" / "gates" / "gate-0001.json"
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        gate["rules"]["required_commands"] = required_commands or []
        gate["rules"]["forbidden_paths"] = forbidden_paths or []
        gate_path.write_text(json.dumps(gate), encoding="utf-8")
        freeze_result = run_script("freeze", str(project))
        self.assertEqual(freeze_result.returncode, 0, freeze_result.stderr)
        return project

    def dispatch_with_stub_executor(self, project: Path) -> str:
        self.set_adapters(executor=StubExecutor("executor"))
        nogap.cmd_run(argparse.Namespace(path=str(project), actor="test", execute=True, execute_timeout=60))
        runtime = project / ".code-loop" / "runtime"
        dispatch = json.loads(next((runtime / "dispatches").glob("*.json")).read_text(encoding="utf-8"))
        return dispatch["id"]

    def test_verify_requires_existing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_script("verify", tmp)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no runtime", result.stdout + result.stderr)

    def test_verify_requires_execution_evidence_for_a_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self.setup_project_with_gate(tmp)
            result = run_script("verify", str(project))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no dispatch records", result.stdout + result.stderr)

    def test_verify_writes_verification_authority_evidence_linked_to_dispatch_and_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self.setup_project_with_gate(
                tmp,
                required_commands=[f"{sys.executable} -c \"import pathlib,sys; sys.exit(0 if pathlib.Path('target.txt').exists() else 1)\""],
            )
            dispatch_id = self.dispatch_with_stub_executor(project)

            result = run_script("verify", str(project))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            runtime = project / ".code-loop" / "runtime"
            gate = json.loads((runtime / "gates" / "gate-0001.json").read_text(encoding="utf-8"))
            verification_evidence = [
                item for item in (json.loads(p.read_text(encoding="utf-8")) for p in (runtime / "evidence").glob("*.json"))
                if item["provenance"].get("authority") == "verification"
            ]
            self.assertEqual(len(verification_evidence), 2)  # effect-scope + the one required_command
            for item in verification_evidence:
                self.assertEqual(item["provenance"]["dispatch_id"], dispatch_id)
                self.assertEqual(item["provenance"]["gate_hash"], gate["hash"])
                self.assertEqual(item["status"], "passed")

            validated = run_script("validate", str(project))
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)

    def test_verify_never_writes_a_decision_only_evidence(self) -> None:
        """The core rule: a verifier issues evidence, never ACCEPT."""
        with tempfile.TemporaryDirectory() as tmp:
            project = self.setup_project_with_gate(tmp)
            self.dispatch_with_stub_executor(project)
            run_script("verify", str(project))
            runtime = project / ".code-loop" / "runtime"
            self.assertEqual(list((runtime / "decisions").glob("*.json")), [])

    def test_verify_review_uses_a_different_provider_with_provider_qualified_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self.setup_project_with_gate(tmp)
            self.set_adapters(
                executor=StubExecutor("executor"),
                reviewer=StubReviewer("reviewer", '{"verdict": "pass", "notes": "independent review ok"}'),
            )
            nogap.cmd_run(argparse.Namespace(path=str(project), actor="test", execute=True, execute_timeout=60))
            runtime = project / ".code-loop" / "runtime"
            dispatch = json.loads(next((runtime / "dispatches").glob("*.json")).read_text(encoding="utf-8"))

            # in-process, not run_script: a subprocess would not see the monkeypatched
            # nogap_adapters.ADAPTERS and would fall back to the real codex/claude.
            nogap.cmd_verify(verify_namespace(str(project), review=True))

            evidence_items = [json.loads(p.read_text(encoding="utf-8")) for p in (runtime / "evidence").glob("*.json")]
            execution_item = next(item for item in evidence_items if item["kind"] == "execution")
            review_items = [
                item for item in evidence_items
                if item["provenance"].get("authority") == "verification" and item["provenance"].get("provider") == "reviewer"
            ]
            self.assertEqual(len(review_items), 1)
            review_item = review_items[0]
            self.assertEqual(review_item["status"], "passed")
            self.assertEqual(review_item["provenance"]["dispatch_id"], dispatch["id"])
            # identity separation: the reviewer's actor_id must differ from the executor's
            self.assertNotEqual(review_item["provenance"]["actor_id"], execution_item["provenance"]["actor_id"])
            self.assertEqual(execution_item["provenance"]["actor_id"], "agent:executor")
            self.assertEqual(review_item["provenance"]["actor_id"], "agent:reviewer")

    def test_verify_review_skips_honestly_when_no_other_ready_adapter_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self.setup_project_with_gate(tmp)
            self.dispatch_with_stub_executor(project)  # only "executor" registered, no other adapter
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                nogap.cmd_verify(verify_namespace(str(project), review=True))
            self.assertIn("no other ready AgentRuntime", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
