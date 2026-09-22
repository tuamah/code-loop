"""Closure item 3: `nogap execute` cannot bypass the prebuild barrier.

`nogap execute` is a DIRECT execution path - it creates a worktree and runs a command
without going near the orchestrator. It used to do that with no methodology check at all,
so a project refused through `nogap run --execute` could run the identical command through
`nogap execute` and produce identical execution evidence.

Closing a barrier on one path and not the other closes nothing: the adversary picks the
other path. The property under test is therefore not "cmd_execute has a check" but
"every execution path reaches the same decision".
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nogap                                                                 # noqa: E402
import nogap_build                                                           # noqa: E402


def git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Project(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.project = Path(self.dir.name)
        git(["init", "-q"], self.project)
        git(["config", "user.email", "t@t.com"], self.project)
        git(["config", "user.name", "t"], self.project)
        (self.project / "README.md").write_text("hello\n", encoding="utf-8")
        git(["add", "README.md"], self.project)
        git(["commit", "-q", "-m", "initial"], self.project)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "nogap.py"), "init",
                        str(self.project), "--objective", "execute"],
                       check=True, capture_output=True)

    def execute_args(self, command=None) -> argparse.Namespace:
        return argparse.Namespace(
            path=str(self.project), actor="test", timeout=60,
            worktree_command=command or [sys.executable, "-c",
                                         "open('pwned.txt','w').write('x')"])

    def run_execute(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            try:
                nogap.cmd_execute(self.execute_args())
            except SystemExit as exc:
                return buffer.getvalue(), exc
        return buffer.getvalue(), None

    def evidence(self) -> list[Path]:
        return list((self.project / ".code-loop" / "runtime" / "evidence").glob("*.json"))

    def events(self) -> str:
        return "".join(e.read_text(encoding="utf-8")
                       for e in (self.project / ".code-loop" / "runtime" / "events").glob("*.jsonl"))


class DirectExecutionIsRefused(Project):
    """An ungoverned project. The orchestrated path refuses; so must this one."""

    def test_execute_is_blocked_without_methodology_state(self):
        output, exit_exc = self.run_execute()
        self.assertIsNotNone(exit_exc, "cmd_execute did not refuse")
        self.assertIn("BLOCKED by methodology", str(exit_exc))
        self.assertIn("METHODOLOGY_NOT_INITIALIZED", str(exit_exc))

    def test_no_process_runs_when_refused(self):
        """The decisive assertion: refused means nothing executed, not cleaned up after."""
        self.run_execute()
        self.assertEqual(self.evidence(), [])
        # The worktree sandbox is never even created.
        self.assertFalse((self.project / ".nogap" / "worktrees").exists())

    def test_the_command_has_no_observable_effect(self):
        """The command writes a file. If it ran anywhere, the worktree would exist."""
        self.run_execute()
        self.assertEqual(list(self.project.rglob("pwned.txt")), [])

    def test_the_refusal_is_recorded(self):
        self.run_execute()
        self.assertIn("METHODOLOGY_BLOCKED", self.events())
        self.assertIn("cmd_execute", self.events())

    def test_execute_is_blocked_when_state_is_unresolved(self):
        from nogap_methodology import methodology_state_path
        path = methodology_state_path(self.project)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        _, exit_exc = self.run_execute()
        self.assertIsNotNone(exit_exc)
        self.assertIn("METHODOLOGY_UNRESOLVED", str(exit_exc))

    def test_no_workspace_file_unlocks_the_direct_path(self):
        """The bypass removed in item 2 must not reappear through this door either."""
        for name in ("methodology-exemption.json", "exemption.json", "bypass.json"):
            (self.project / ".code-loop" / name).write_text(
                json.dumps({"permitted": True, "granted_by": "mallory"}), encoding="utf-8")
        _, exit_exc = self.run_execute()
        self.assertIsNotNone(exit_exc)
        self.assertEqual(self.evidence(), [])


class BothPathsReachTheSameDecision(Project):
    """The property that matters: not "each path has a check", but "one decision"."""

    def orchestrated(self) -> str:
        import nogap_adapters
        saved = dict(nogap_adapters.ADAPTERS)
        self.addCleanup(lambda: (nogap_adapters.ADAPTERS.clear(),
                                 nogap_adapters.ADAPTERS.update(saved)))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            nogap.cmd_run(argparse.Namespace(
                path=str(self.project), actor="test", execute=True, execute_timeout=60))
        return buffer.getvalue()

    def test_both_paths_refuse_the_same_ungoverned_project(self):
        orchestrated = self.orchestrated()
        direct, exit_exc = self.run_execute()
        self.assertIn("BLOCKED by methodology", orchestrated)
        self.assertIn("BLOCKED by methodology", str(exit_exc))
        for text in (orchestrated, direct):
            self.assertIn("METHODOLOGY_NOT_INITIALIZED", text)

    def test_neither_path_produces_execution_evidence(self):
        self.orchestrated()
        self.run_execute()
        self.assertEqual(self.evidence(), [])

    def test_both_paths_call_the_same_decision_function(self):
        """Parsed, not grepped. Two checks that agree today can drift tomorrow.

        Only one decision function may exist, consulted on the same field, or the paths are
        free to diverge - and the one that diverges is the one the adversary uses.
        """
        tree = ast.parse((ROOT / "scripts" / "nogap.py").read_text(encoding="utf-8"))
        functions = {n.name: n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef)}
        for name in ("cmd_run", "cmd_execute"):
            body = ast.dump(functions[name])
            self.assertIn("preflight_build", body,
                          f"{name} does not consult preflight_build")
            self.assertIn("'permitted'", body,
                          f"{name} does not gate on the permitted field")


class NoUngatedExecutionPathExists(unittest.TestCase):
    """Guards against the NEXT bypass, not just this one.

    Item 3 closed `cmd_execute`. A third path added later, calling the backend directly
    with no authorization, would be the same defect wearing a new name - and nothing here
    would have noticed. So the rule is asserted over the module: in nogap.py, any function
    that starts a process through the execution backend must consult preflight_build.
    """

    ALLOWED_WITHOUT_PREFLIGHT: set[str] = set()

    def test_every_backend_caller_in_nogap_consults_preflight(self):
        tree = ast.parse((ROOT / "scripts" / "nogap.py").read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            body = ast.dump(node)
            starts_process = "GitWorktreeExecutionBackend" in body
            if starts_process and node.name not in self.ALLOWED_WITHOUT_PREFLIGHT:
                if "preflight_build" not in body:
                    offenders.append(node.name)
        self.assertEqual(offenders, [],
                         "these start a process without consulting preflight_build")

    def test_the_rule_finds_the_functions_it_claims_to_check(self):
        """Guards the guard: a rule that matches nothing passes vacuously forever."""
        tree = ast.parse((ROOT / "scripts" / "nogap.py").read_text(encoding="utf-8"))
        checked = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                   and "GitWorktreeExecutionBackend" in ast.dump(n)]
        self.assertIn("cmd_execute", checked)
        self.assertIn("cmd_run", checked)


if __name__ == "__main__":
    unittest.main()
