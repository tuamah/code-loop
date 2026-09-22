"""Closure item 2: `preflight` is fail-closed.

The rule under test, and nothing wider:

    missing / unresolved methodology state
      -> never permitted by default
      -> explicit trusted exception, or FAIL CLOSED

The fail-open had TWO layers, and closing either alone would have left it open:

  1. `preflight_build()` returned permitted=True when no state existed;
  2. `cmd_run` gated on `methodology_tracked and not permitted`, so it skipped the
     barrier entirely for exactly that case - a caller deciding for itself which
     statuses to enforce.

Both are tested here, separately, because a test that only covers the first would
pass against a runtime that still executes.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import nogap                                                                 # noqa: E402
import nogap_build                                                           # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@dataclass
class _ReadyExecutor:
    """A connected AgentRuntime that would happily run, so the barrier has something to stop."""

    id: str
    kind: str = "AgentRuntime"

    def health(self):
        return {"status": "connected", "trust_status": "READY"}

    def capabilities(self):
        return {"id": self.id, "kind": self.kind, "can_execute": False, "supported_operations": []}

    def build_exec_command(self, prompt, worktree):
        return [sys.executable, "-c", "open('target.txt','w').write('hi')"]


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
                        str(self.project), "--objective", "preflight"],
                       check=True, capture_output=True)



# -- the barrier itself ---------------------------------------------------------------------------

class MissingStateIsNotPermitted(Project):
    def test_no_state_is_refused(self):
        result = nogap_build.preflight_build(self.project)
        self.assertFalse(result["permitted"])
        self.assertEqual(result["status"], "METHODOLOGY_NOT_INITIALIZED")

    def test_no_state_is_never_reported_as_ready(self):
        self.assertNotEqual(nogap_build.preflight_build(self.project)["status"], "READY")

    def test_the_rejection_tells_the_user_what_to_do(self):
        reasons = " ".join(nogap_build.preflight_build(self.project)["reasons"])
        self.assertIn("not permitted", reasons)
        self.assertIn("nogap methodology init", reasons)


class UnresolvedStateIsNotPermitted(Project):
    """State that exists but will not load is a signal, not an absence."""

    def corrupt(self, text: str) -> None:
        from nogap_methodology import methodology_state_path
        path = methodology_state_path(self.project)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_unparsable_state_is_refused_not_raised(self):
        self.corrupt("{not json")
        result = nogap_build.preflight_build(self.project)
        self.assertFalse(result["permitted"])
        self.assertEqual(result["status"], "METHODOLOGY_UNRESOLVED")
        self.assertIn("will not load", result["reasons"][0])

    def test_structurally_invalid_state_is_refused(self):
        self.corrupt(json.dumps({"current_phase": "P11"}))  # missing required fields
        result = nogap_build.preflight_build(self.project)
        self.assertFalse(result["permitted"])
        self.assertEqual(result["status"], "METHODOLOGY_UNRESOLVED")

    def test_unresolved_state_counts_as_tracked(self):
        """Tracked, so no exemption path can reach it: see the exemption tests below."""
        self.corrupt("{not json")
        self.assertTrue(nogap_build.preflight_build(self.project)["tracked"])

    def test_nothing_written_into_the_workspace_rescues_unresolved_state(self):
        """Corruption is a signal. Nothing a workspace writer can do may discard it."""
        self.corrupt("{not json")
        for name in ("methodology-exemption.json", "exemption.json"):
            (self.project / ".code-loop" / name).write_text(
                json.dumps({"permitted": True}), encoding="utf-8")
        result = nogap_build.preflight_build(self.project)
        self.assertFalse(result["permitted"])
        self.assertEqual(result["status"], "METHODOLOGY_UNRESOLVED")


# -- there is no local exemption ------------------------------------------------------------------

class NoWorkspaceWritableBypassExists(Project):
    """The hole an earlier revision of this change opened, and the test that keeps it shut.

    That revision let a project grant itself an exception through an unsigned file in its own
    workspace. It replaced "no state permits" with "writing one local JSON permits" - the same
    hole with an extra step, because the executor this barrier exists to constrain has write
    access to that workspace. Whoever can write the workspace must not be able to authorize
    execution in it.
    """

    CANDIDATES = ("methodology-exemption.json", "exemption.json", "methodology-override.json",
                  ".methodology-exempt", "preflight-override.json", "bypass.json")

    def test_no_file_an_executor_could_write_grants_permission(self):
        """The property, stated as a property: writing into the workspace never permits."""
        record = {"reason": "r", "granted_by": "mallory", "expires_at": "2099-01-01T00:00:00Z",
                  "permitted": True, "status": "READY", "exempt": True}
        for name in self.CANDIDATES:
            for directory in (self.project, self.project / ".code-loop",
                              self.project / ".code-loop" / "runtime"):
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / name
                path.write_text(json.dumps(record), encoding="utf-8")
                result = nogap_build.preflight_build(self.project)
                self.assertFalse(result["permitted"], f"{path} granted permission")
                self.assertEqual(result["status"], "METHODOLOGY_NOT_INITIALIZED")
                path.unlink()

    def test_the_module_exposes_no_exemption_mechanism(self):
        """Parsed, not grepped: a docstring saying "no exemption" must not satisfy this."""
        import ast
        tree = ast.parse((ROOT / "scripts" / "nogap_build.py").read_text(encoding="utf-8"))
        names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        for banned in ("read_exemption", "exemption_path", "load_exemption", "check_exemption"):
            self.assertNotIn(banned, names)
        assigned = {t.id for n in tree.body if isinstance(n, ast.Assign)
                    for t in n.targets if isinstance(t, ast.Name)}
        for banned in ("MAX_EXEMPTION_DAYS", "EXEMPTION_FIELDS", "EXEMPTION_PATH"):
            self.assertNotIn(banned, assigned)

    def test_no_status_permits_without_methodology_state(self):
        """No reachable status is both ungoverned and permitted."""
        result = nogap_build.preflight_build(self.project)
        self.assertFalse(result["tracked"])
        self.assertFalse(result["permitted"])

    def test_the_rejection_names_the_reason_there_is_no_override(self):
        reasons = " ".join(nogap_build.preflight_build(self.project)["reasons"])
        self.assertIn("no local override", reasons)
        self.assertIn("authorize execution", reasons)


# -- the caller: the second layer -------------------------------------------------------------------

class CmdRunEnforcesTheBarrier(Project):
    """The layer above. `cmd_run` used to skip the barrier for exactly the refused case.

    A READY executor is installed for every test here, deliberately. Without one, cmd_run
    returns earlier at "no ready implementer AgentRuntime" and never reaches the barrier at
    all - so the test would pass while proving nothing about it. An earlier version of this
    class had exactly that defect: it passed locally, because another test in the same
    process had left a ready adapter in the global registry, and failed on CI where nothing
    had. Installing one here makes the assertion mean what it says: an executor is ready and
    willing, and the barrier refuses anyway.
    """

    def setUp(self):
        super().setUp()
        import nogap_adapters
        self._saved = dict(nogap_adapters.ADAPTERS)
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS["codex"] = _ReadyExecutor("codex")
        self.addCleanup(self._restore_adapters)

    def _restore_adapters(self):
        import nogap_adapters
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS.update(self._saved)

    def test_the_executor_is_actually_ready(self):
        """Guards the guard: if this stops being true, every test below stops testing."""
        import nogap_adapters
        self.assertTrue(nogap_adapters.ADAPTERS["codex"].health()["status"] == "connected")

    def run_execute(self) -> str:
        import io
        import contextlib
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            nogap.cmd_run(argparse.Namespace(
                path=str(self.project), actor="test", execute=True, execute_timeout=60))
        return buffer.getvalue()

    def evidence_files(self) -> list[Path]:
        return list((self.project / ".code-loop" / "runtime" / "evidence").glob("*.json"))

    def test_execute_is_blocked_when_state_is_missing(self):
        output = self.run_execute()
        self.assertIn("execution BLOCKED by methodology", output)
        self.assertIn("METHODOLOGY_NOT_INITIALIZED", output)

    def test_nothing_is_executed_when_the_barrier_refuses(self):
        """Blocked means no process ran, not that the result was discarded afterwards."""
        self.run_execute()
        self.assertEqual(self.evidence_files(), [])

    def test_the_block_is_recorded_as_an_event(self):
        self.run_execute()
        events = list((self.project / ".code-loop" / "runtime" / "events").glob("*.jsonl"))
        self.assertTrue(events)
        self.assertIn("METHODOLOGY_BLOCKED",
                      "".join(e.read_text(encoding="utf-8") for e in events))

    def test_execute_is_blocked_when_state_is_unresolved(self):
        from nogap_methodology import methodology_state_path
        path = methodology_state_path(self.project)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        output = self.run_execute()
        self.assertIn("execution BLOCKED by methodology", output)
        self.assertIn("METHODOLOGY_UNRESOLVED", output)

    def test_no_workspace_file_lets_execute_through(self):
        """End to end: the adversary writes into the workspace and still does not execute."""
        for name in ("methodology-exemption.json", "exemption.json", "bypass.json"):
            (self.project / ".code-loop" / name).write_text(json.dumps(
                {"reason": "r", "granted_by": "mallory", "expires_at": "2099-01-01T00:00:00Z",
                 "permitted": True}), encoding="utf-8")
        output = self.run_execute()
        self.assertIn("execution BLOCKED by methodology", output)
        self.assertEqual(self.evidence_files(), [])

    def test_a_blocked_project_creates_no_routing_state(self):
        """Authorization precedes routing, so a refused run leaves no routing history."""
        self.run_execute()
        runtime = self.project / ".code-loop" / "runtime"
        self.assertEqual(list((runtime / "routes").glob("*.json")), [])
        self.assertEqual(list((runtime / "dispatches").glob("*.json")), [])
        events = "".join(e.read_text(encoding="utf-8")
                         for e in (runtime / "events").glob("*.jsonl"))
        for never in ("ROUTE_SELECTED", "ROUTE_UNAVAILABLE",
                      "DISPATCH_INTENDED", "DISPATCH_FAILED"):
            self.assertNotIn(never, events)

    def test_there_is_still_no_bypass_flag(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "nogap.py"), "run", "--help"],
            capture_output=True, text=True)
        lowered = result.stdout.lower()
        for flag in ("--force", "--skip-methodology", "--bypass", "--no-preflight"):
            self.assertNotIn(flag, lowered)

    def test_the_caller_gates_on_permitted_alone(self):
        """The shape of the old hole: a caller that reads `status` to decide what to enforce.

        Asserted against the parsed source rather than the text, so a docstring mentioning
        the old expression cannot satisfy it.
        """
        import ast
        source = (ROOT / "scripts" / "nogap.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef) and n.name == "cmd_run")
        guards = [n.test for n in ast.walk(function) if isinstance(n, ast.If)]
        barrier = [g for g in guards
                   if isinstance(g, ast.UnaryOp) and isinstance(g.op, ast.Not)
                   and "permitted" in ast.dump(g)]
        self.assertTrue(barrier, "cmd_run has no `not preflight['permitted']` guard")
        for guard in barrier:
            self.assertNotIn("status", ast.dump(guard),
                             "the barrier consults `status`; it must gate on `permitted` alone")

    def test_tracked_is_read_not_derived_from_status(self):
        """`methodology_tracked = preflight["status"] != ...` is how the hole was built.

        With the barrier gating on `permitted`, re-deriving it from `status` is behaviourally
        equivalent TODAY, so no behavioural test can catch it - a mutation proved exactly that.
        It is still the wrong rule: it silently mis-derives the moment any status is both
        ungoverned and permitted, which is one added status away. Whether a project is TRACKED
        is a fact preflight reports, not something a caller reconstructs by comparing strings.
        """
        import ast
        source = (ROOT / "scripts" / "nogap.py").read_text(encoding="utf-8")
        function = next(n for n in ast.walk(ast.parse(source))
                        if isinstance(n, ast.FunctionDef) and n.name == "cmd_run")
        assignments = [n for n in ast.walk(function) if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == "methodology_tracked"
                               for t in n.targets)]
        self.assertTrue(assignments, "cmd_run never assigns methodology_tracked")
        for node in assignments:
            dumped = ast.dump(node.value)
            self.assertIn("'tracked'", dumped,
                          "methodology_tracked must be read from preflight['tracked']")
            self.assertNotIn("status", dumped,
                             "methodology_tracked is derived from `status`; read `tracked`")


class AuthorizationPrecedesAvailability(Project):
    """The ordering bug, and the property that pins it shut.

    The barrier used to sit AFTER route_implementer(). That made the methodology decision
    subordinate to whether an executor happened to be connected:

        permitted=False + executor ready       -> METHODOLOGY_BLOCKED
        permitted=False + executor unavailable -> DISPATCH_FAILED     <- wrong

    Both are refusals, so both "look safe" - and that is exactly why it survived. The second
    one refuses for the wrong reason: it reports a resource problem where there is an
    authorization problem, and it says the request would have proceeded if only an executor
    had been there. Unauthorized is not "try again when a runtime is free".

    These two tests are deliberately independent and assert the SAME verdict. Neither alone
    is sufficient: the first passes under the old ordering too.
    """

    def run_execute(self) -> str:
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            nogap.cmd_run(argparse.Namespace(
                path=str(self.project), actor="test", execute=True, execute_timeout=60))
        return buffer.getvalue()

    def set_adapters(self, ready: bool) -> None:
        import nogap_adapters
        saved = dict(nogap_adapters.ADAPTERS)
        self.addCleanup(lambda: (nogap_adapters.ADAPTERS.clear(),
                                 nogap_adapters.ADAPTERS.update(saved)))
        nogap_adapters.ADAPTERS.clear()
        if ready:
            nogap_adapters.ADAPTERS["codex"] = _ReadyExecutor("codex")

    def assert_blocked_by_methodology(self, output: str) -> None:
        self.assertIn("execution BLOCKED by methodology", output)
        self.assertIn("METHODOLOGY_NOT_INITIALIZED", output)
        # The refusal is an authorization refusal, never a resource refusal.
        self.assertNotIn("DISPATCH_FAILED", output)
        self.assertNotIn("no ready implementer", output)

    def test_A_blocked_with_an_executor_ready(self):
        self.set_adapters(ready=True)
        self.assert_blocked_by_methodology(self.run_execute())

    def test_B_blocked_with_no_executor_available(self):
        """The case the old ordering got wrong: no executor, and still METHODOLOGY_BLOCKED."""
        self.set_adapters(ready=False)
        self.assert_blocked_by_methodology(self.run_execute())

    def test_B_creates_no_routing_state_either(self):
        """With no executor the old code emitted ROUTE_UNAVAILABLE before deciding anything."""
        self.set_adapters(ready=False)
        self.run_execute()
        runtime = self.project / ".code-loop" / "runtime"
        events = "".join(e.read_text(encoding="utf-8")
                         for e in (runtime / "events").glob("*.jsonl"))
        for never in ("ROUTE_SELECTED", "ROUTE_UNAVAILABLE",
                      "DISPATCH_INTENDED", "DISPATCH_FAILED"):
            self.assertNotIn(never, events)
        self.assertIn("METHODOLOGY_BLOCKED", events)

    def test_both_cases_reach_the_identical_verdict(self):
        """Stated as one property: executor availability does not change the decision."""
        self.set_adapters(ready=True)
        with_executor = self.run_execute()
        self.setUp()
        self.set_adapters(ready=False)
        without_executor = self.run_execute()
        for output in (with_executor, without_executor):
            self.assertIn("execution BLOCKED by methodology: METHODOLOGY_NOT_INITIALIZED",
                          output)

    def test_planning_only_runs_still_route_normally(self):
        """The gate is scoped to --execute: planning may still inspect and report."""
        import contextlib
        import io
        self.set_adapters(ready=True)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            nogap.cmd_run(argparse.Namespace(
                path=str(self.project), actor="test", execute=False, execute_timeout=60))
        output = buffer.getvalue()
        self.assertIn("-> dispatch", output)
        self.assertNotIn("execution BLOCKED", output)


if __name__ == "__main__":
    unittest.main()
