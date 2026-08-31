#!/usr/bin/env python3
"""Checks for the isolated GitWorktreeExecutionBackend and `nogap execute`.

The backend must never touch the real working tree, must always clean up its
disposable worktree (pass, fail, timeout, or cancel), must capture untracked
new files in its patch, and its evidence must never be treated as authoritative
on its own (only verification/human authority is authoritative for ACCEPT).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from nogap_execution import ExecutionHandle, GitWorktreeExecutionBackend  # noqa: E402


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


class ExecutionBackendUnitTests(unittest.TestCase):
    def test_new_untracked_files_are_captured_in_the_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            backend = GitWorktreeExecutionBackend(project)
            result = backend.run([sys.executable, "-c", "open('new_file.txt','w').write('hi')"])
            self.assertEqual(result.status, "passed")
            self.assertIn("new_file.txt", result.patch)
            self.assertIn("+hi", result.patch)

    def test_real_working_tree_is_never_modified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            before = sorted(p.name for p in project.iterdir() if p.name != ".git")
            backend = GitWorktreeExecutionBackend(project)
            backend.run([sys.executable, "-c", "open('should_not_leak.txt','w').write('x')"])
            after = sorted(p.name for p in project.iterdir() if p.name != ".git" and p.name != ".nogap")
            self.assertEqual(before, after)

    def test_worktree_is_removed_after_a_normal_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            backend = GitWorktreeExecutionBackend(project)
            backend.run([sys.executable, "-c", "pass"])
            listing = git(["worktree", "list"], project).stdout
            self.assertEqual(listing.count("\n"), 1)  # only the main worktree remains

    def test_worktree_is_removed_after_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            backend = GitWorktreeExecutionBackend(project)
            result = backend.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)
            self.assertEqual(result.status, "inconclusive")
            self.assertTrue(result.timed_out)
            listing = git(["worktree", "list"], project).stdout
            self.assertEqual(listing.count("\n"), 1)

    def test_failing_command_reports_failed_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            backend = GitWorktreeExecutionBackend(project)
            result = backend.run([sys.executable, "-c", "import sys; sys.exit(1)"])
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.returncode, 1)

    def test_cancel_from_another_thread_reports_blocked_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            backend = GitWorktreeExecutionBackend(project)
            handle = ExecutionHandle()

            def cancel_soon() -> None:
                import time
                time.sleep(0.5)
                handle.cancel()

            threading.Thread(target=cancel_soon, daemon=True).start()
            result = backend.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=60, handle=handle)
            self.assertEqual(result.status, "blocked")
            self.assertTrue(result.cancelled)
            listing = git(["worktree", "list"], project).stdout
            self.assertEqual(listing.count("\n"), 1)


class ExecuteCommandTests(unittest.TestCase):
    def test_execute_requires_a_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            run_script("init", str(project), "--objective", "no command")
            result = run_script("execute", str(project))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires a command", result.stdout + result.stderr)

    def test_execute_writes_non_authoritative_execution_evidence_and_patch_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            run_script("init", str(project), "--objective", "execute writes evidence")
            result = run_script("execute", str(project), "--", sys.executable, "-c", "open('out.txt','w').write('x')")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            runtime = project / ".code-loop" / "runtime"
            evidence_files = list((runtime / "evidence").glob("*.json"))
            artifact_files = list((runtime / "artifacts").glob("*.patch"))
            self.assertEqual(len(evidence_files), 1)
            self.assertEqual(len(artifact_files), 1)

            evidence = json.loads(evidence_files[0].read_text(encoding="utf-8"))
            self.assertEqual(evidence["kind"], "execution")
            self.assertEqual(evidence["status"], "passed")
            self.assertEqual(evidence["provenance"]["authority"], "execution")
            self.assertIn("out.txt", artifact_files[0].read_text(encoding="utf-8"))

            validated = run_script("validate", str(project))
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)

    def test_timeout_flag_is_parsed_correctly_and_does_not_leak_into_the_command(self) -> None:
        # Regression test: --timeout previously collided with argparse.REMAINDER's dest
        # (which shadowed the top-level subparsers dest="command") and could be swallowed
        # into the worktree command itself, crashing Popen with FileNotFoundError.
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            run_script("init", str(project), "--objective", "timeout flag regression")
            result = run_script(
                "execute", str(project), "--timeout", "2", "--",
                sys.executable, "-c", "import time; time.sleep(30)",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("inconclusive", result.stdout)

    def test_execute_rejects_missing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            init_git_repo(project)
            result = run_script("execute", str(project), "--", sys.executable, "-c", "pass")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no runtime", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
