"""F2a semantic clarification: required_artifacts are COMPLETION obligations.

They bind when an edge means "this phase is finished, leave it forward", and not when it
means "this phase could not be finished, recover out of it".

Demanding a completion artifact on a recovery edge makes recovery impossible by
construction: you go back from P20 precisely because RELEASE_READINESS_CHECKLIST could not
be produced, so requiring it in order to leave traps the run in a phase it can neither
finish nor exit. Before F2a nobody noticed the rule applied to backward edges at all,
because any non-empty list satisfied it.

**The decision is made from the edge's declared SOURCE, never from transition_type's name.**
`_classify_edge` labels an edge LOOP_ENTRY whenever its target belongs to a loop - including
edges that are in `allowed_next`. Excluding LOOP_ENTRY by name would therefore let a
completed phase enter the next loop owing artifacts it never produced. That bypass has its
own test and its own mutation below.

This is a clarification of WHEN a declared obligation binds, not a new meaning for any
artifact kind. No mapping is invented here; F2b remains untouched.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import nogap_methodology as nm                                               # noqa: E402
from nogap_methodology import MethodologyValidationError, can_transition     # noqa: E402


class EdgeProvenance(unittest.TestCase):
    """The rule, tested against the real phase contracts rather than a mock."""

    def setUp(self):
        self.definition = nm.load_methodology()

    def mode(self, current_id: str, to: str) -> str:
        """Mirror of the production decision, so the contracts themselves are asserted."""
        current = self.definition.get_phase(current_id)
        return "COMPLETION" if to in current.allowed_next else "RECOVERY"

    def test_forward_edges_are_completion_exits(self):
        for current_id in ("P19", "P20", "P21", "P22"):
            phase = self.definition.get_phase(current_id)
            for nxt in phase.allowed_next:
                self.assertEqual(self.mode(current_id, nxt), "COMPLETION",
                                 f"{current_id}->{nxt}")

    def test_backward_edges_are_recovery_exits(self):
        found = 0
        for current_id, phase in self.definition.phases.items():
            for back in phase.allowed_back_transitions:
                if back in phase.allowed_next:
                    continue  # an edge that is BOTH is a completion edge; see below
                found += 1
                self.assertEqual(self.mode(current_id, back), "RECOVERY",
                                 f"{current_id}->{back}")
        self.assertGreater(found, 0, "no backward edges found - the rule would be vacuous")

    def test_failure_transitions_are_recovery_exits(self):
        found = 0
        for current_id, phase in self.definition.phases.items():
            target = phase.failure_transition
            if not target or target == "REPAIR_LOOP" or target in phase.allowed_next:
                continue
            found += 1
            self.assertEqual(self.mode(current_id, target), "RECOVERY",
                             f"{current_id}->{target}")
        self.assertGreater(found, 0, "no failure transitions found - the rule would be vacuous")

    def test_an_allowed_next_edge_into_a_loop_is_still_a_completion_exit(self):
        """The bypass the naive rule would have opened.

        `_classify_edge` calls this LOOP_ENTRY because the target belongs to a loop. Keying
        off that name would let a completed phase enter the next loop without the artifacts
        it owes. Provenance says otherwise: the edge is in allowed_next, so it completes.
        """
        entries = [(pid, nxt) for pid, phase in self.definition.phases.items()
                   for nxt in phase.allowed_next
                   if self.definition.get_phase(nxt).loop]
        self.assertTrue(entries, "no allowed_next edge targets a loop phase")
        for current_id, nxt in entries:
            self.assertEqual(self.mode(current_id, nxt), "COMPLETION", f"{current_id}->{nxt}")

    def test_the_rule_does_not_consult_transition_type(self):
        """Parsed, not grepped: the production decision must not key off the type NAME."""
        import ast
        source = (ROOT / "scripts" / "nogap_methodology.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef) and n.name == "_evaluate_transition")
        assigns = [n for n in ast.walk(function) if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "obligation_mode"
                           for t in n.targets)]
        self.assertTrue(assigns, "_evaluate_transition never decides obligation_mode")
        dumped = ast.dump(assigns[0].value)
        self.assertIn("allowed_next", dumped,
                      "obligation_mode must be decided from the edge's declared source")
        for name in ("LOOP_ENTRY", "BACKWARD", "LOOP_RETURN", "FORWARD"):
            self.assertNotIn(name, dumped,
                             f"obligation_mode keys off the transition_type name {name!r}")


class LiveProject(unittest.TestCase):
    """End to end against a real project, so the rule is observed and not only computed."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.project = Path(self.dir.name)
        for args in (["init", "-q"], ["config", "user.email", "t@t.com"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git", *args], cwd=self.project, check=True, capture_output=True)
        (self.project / "R.md").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "add", "R.md"], cwd=self.project, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=self.project, check=True,
                       capture_output=True)
        nm.init_project(self.project, "research", "low", "low", actor="test")
        import test_methodology_build as chain
        chain.build_p0_p11_chain(self.project)

    def at(self, phase_id: str) -> None:
        state = json.loads(nm.methodology_state_path(self.project).read_text(encoding="utf-8"))
        state["current_phase"] = phase_id
        nm.methodology_state_path(self.project).write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_forward_without_the_artifact_is_blocked(self):
        """P11 -> P12 is a completion edge; P11 owes GOLDEN_GATES/TEST_PLAN."""
        self.at("P11")
        result = can_transition(self.project, "P12", artifact_refs=[])
        self.assertFalse(result["allowed"])
        self.assertTrue(any("requires artifacts" in r for r in result["blocked_reasons"]))

    def test_backward_without_the_artifact_is_allowed(self):
        """The case that made recovery impossible: leaving a phase you could not finish."""
        self.at("P11")
        phase = nm.load_methodology().get_phase("P11")
        back = next((b for b in phase.allowed_back_transitions
                     if b not in phase.allowed_next), None)
        self.assertIsNotNone(back, "P11 declares no purely-backward edge")
        result = can_transition(self.project, back, artifact_refs=[])
        self.assertTrue(
            all("requires artifacts" not in r and "required artifact" not in r
                for r in result["blocked_reasons"]),
            f"a recovery exit demanded a completion artifact: {result['blocked_reasons']}")

    def test_required_evidence_is_untouched_by_this_change(self):
        """The ruling moved required_ARTIFACTS only.

        A mutation that dropped required_evidence alongside them survived the first run of
        this suite, which means nothing here was pinning evidence behaviour at all. Whether
        evidence is also a completion-only obligation is a separate question the contract
        does not answer, and it must not be decided by accident as a side effect of this one.
        """
        definition = nm.load_methodology()
        phase_id = next((pid for pid, ph in definition.phases.items()
                         if ph.required_evidence and ph.allowed_next), None)
        self.assertIsNotNone(phase_id, "no phase declares required_evidence")
        self.at(phase_id)
        phase = definition.get_phase(phase_id)

        forward = can_transition(self.project, phase.allowed_next[0], evidence_refs=[])
        self.assertTrue(any("requires evidence" in r for r in forward["blocked_reasons"]),
                        "required_evidence is no longer enforced on a completion edge")

        back = next((b for b in phase.allowed_back_transitions
                     if b not in phase.allowed_next), None)
        if back is not None:
            recovery = can_transition(self.project, back, evidence_refs=[])
            self.assertTrue(
                any("requires evidence" in r for r in recovery["blocked_reasons"]),
                "required_evidence changed on recovery edges; this ruling did not move it")

    def test_recovery_still_enforces_everything_else(self):
        """Not a free pass: a recovery edge that is simply illegal stays illegal."""
        self.at("P11")
        result = can_transition(self.project, "P0", artifact_refs=[])
        self.assertFalse(result["allowed"])


if __name__ == "__main__":
    unittest.main()
