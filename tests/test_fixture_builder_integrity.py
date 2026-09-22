"""The fixture builder must be honest, and here is where that is proven.

A builder that fakes the references under test cannot witness the rule it stands in for. So
the builder itself gets adversarial tests:

* its history is real - artifacts exist, the gate is genuinely frozen, the hash it binds to
  is the one the system reports;
* a FABRICATED gate hash is rejected as stale, which is what makes the real one meaningful;
* it never writes methodology state directly;
* it never invents artifact ids.

The last two are asserted against the parsed source, not by grepping prose, so a comment
promising good behaviour cannot satisfy them.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import methodology_fixture_builder as fbuilder                               # noqa: E402
import nogap_methodology as nm                                               # noqa: E402
import nogap_verify_binding as vb                                            # noqa: E402
from nogap_build import _frozen_gate                                         # noqa: E402


def new_project() -> Path:
    project = Path(tempfile.mkdtemp())
    for args in (["init", "-q"], ["config", "user.email", "t@t.com"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)
    (project / "R.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "R.md"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=project, check=True,
                   capture_output=True)
    nm.init_project(project, "research", "low", "low", actor="test")
    return project


class TheGateIsReal(unittest.TestCase):
    """The blocker that produced this work: a verification bound to a gate that was never
    frozen is stale, and the system was right to say so."""

    def setUp(self):
        self.project = new_project()
        self.builder = fbuilder.FixtureBuilder(self.project)

    def test_the_builder_freezes_an_actual_gate(self):
        self.builder.ensure_gate()
        gate = _frozen_gate(self.project)
        self.assertIsNotNone(gate, "no frozen gate exists")
        self.assertEqual(gate["status"], "frozen")
        self.assertTrue(gate["hash"])

    def test_the_builder_binds_to_the_hash_the_system_reports(self):
        """Not a hash it computed for itself: the one the frozen gate actually carries."""
        self.assertEqual(self.builder.ensure_gate(), _frozen_gate(self.project)["hash"])

    def test_a_real_gate_hash_is_accepted_and_a_fabricated_one_is_stale(self):
        """The pair that gives the real hash its meaning.

        With the true hash the verification is current; with any other value the same
        record is stale. If both passed, binding to the real gate would prove nothing.
        """
        self.builder.advance_to("P18")
        self.builder._artifact_for("P18")
        task_id = self.builder.artifacts["P12"]["fields"]["task_id"]
        record = self.builder.artifacts["P18"]

        real = _frozen_gate(self.project)["hash"]
        self.assertEqual(vb.verification_staleness(self.project, record, real), [],
                         "a verification bound to the real frozen gate reported stale")

        fabricated = "sha256:" + "ff" * 32
        reasons = vb.verification_staleness(self.project, record, fabricated)
        self.assertTrue(reasons, "a fabricated gate hash was accepted as current")
        self.assertTrue(any("gate" in r.lower() for r in reasons), reasons)

    def test_readiness_accepts_the_chain_the_builder_produces(self):
        """End to end: task -> evidence -> self-check -> binding -> frozen gate -> readiness.

        Every one of those links was invisible while a placeholder string satisfied the rule.
        """
        self.builder.advance_to("P21")
        self.assertEqual(nm.status(self.project)["current_phase"], "P21")


class BuilderIntegrity(unittest.TestCase):
    """Parsed, not grepped. A docstring promising these properties must not satisfy them."""

    def setUp(self):
        self.tree = ast.parse(
            (ROOT / "tests" / "methodology_fixture_builder.py").read_text(encoding="utf-8"))

    def test_the_builder_never_writes_methodology_state_directly(self):
        """Every phase change must be a transition the engine agreed to."""
        banned = {"_write_state", "methodology_state_path"}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute) and node.attr in banned:
                self.fail(f"the builder touches {node.attr}")
            if isinstance(node, ast.Name) and node.id in banned:
                self.fail(f"the builder touches {node.id}")
        source = (ROOT / "tests" / "methodology_fixture_builder.py").read_text(encoding="utf-8")
        self.assertNotIn('["current_phase"] =', source)
        self.assertNotIn("['current_phase'] =", source)

    def test_the_builder_never_invents_artifact_ids(self):
        """Every reference it passes came back from the API that created the thing.

        The literal strings below are the shapes the old fixtures used. Their absence is the
        property: an id the builder made up is an id nothing resolves.
        """
        # AST literals only, never the source text: the module's own docstring NAMES the old
        # placeholders in order to explain why they are gone, and a prose scan matched that
        # and failed. A guard that reads comments is the same defect it is guarding against.
        docstrings = {ast.get_docstring(n) for n in ast.walk(self.tree)
                      if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))}
        literals = {n.value for n in ast.walk(self.tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and n.value not in docstrings}
        # The property is "no invented REFERENCE ids", not "no short strings": "x" as a
        # problem_summary is field content the artifact contract asks for, and banning it
        # would be confusing a value with a reference.
        for invented in ("test-artifact", "artifact-placeholder", "intent-doc", "gap-doc",
                         "verdict-doc", "ev-placeholder", "revert-artifact",
                         "root-cause-doc", "proposal-doc", "review-doc"):
            self.assertNotIn(invented, literals, f"the builder invents {invented!r}")

    def test_the_builder_uses_production_apis_to_create_artifacts(self):
        """Positive counterpart: it does not hand-write artifact JSON either."""
        names = {n.func.id for n in ast.walk(self.tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("create_artifact", names,
                      "the builder does not create artifacts through the production API")


if __name__ == "__main__":
    unittest.main()


class TheRealPipelineIsReal(unittest.TestCase):
    """P21 is reached by doing the work, not by arranging the appearance of it.

    The success criterion is the CHAIN, not the phase:

        real execution -> independent authoritative verification -> ACCEPT decision
        -> release candidate -> readiness -> deployment -> P21

    Each link is asserted separately, because reaching P21 while any one of them was faked
    would be exactly the failure this fixture exists to make impossible.
    """

    @classmethod
    def setUpClass(cls):
        cls.project = new_project()
        cls.builder = fbuilder.advance_via_real_pipeline(cls.project)
        cls.runtime = cls.project / ".code-loop" / "runtime"

    def records(self, kind: str) -> list[dict]:
        return [json.loads(p.read_text(encoding="utf-8"))
                for p in (self.runtime / kind).glob("*.json")]

    def test_1_execution_really_happened(self):
        """A real command ran in a real isolated worktree and left an observable effect."""
        execution = [e for e in self.records("evidence")
                     if e.get("provenance", {}).get("authority") == "execution"]
        self.assertTrue(execution, "no execution evidence was produced")
        self.assertTrue(any(e.get("status") == "passed" for e in execution))

    def test_2_verification_is_independent_of_execution(self):
        """The property that makes the ACCEPT meaningful: different identities."""
        by_authority = {}
        for record in self.records("evidence"):
            provenance = record.get("provenance", {})
            by_authority.setdefault(provenance.get("authority"), set()).add(
                provenance.get("actor_id"))
        self.assertIn("verification", by_authority, "no verification evidence")
        executors = by_authority.get("execution", set())
        reviewers = {a for a in by_authority["verification"] if a and a.startswith("agent:")}
        self.assertTrue(reviewers, "no agent reviewed the candidate")
        self.assertFalse(executors & reviewers,
                         f"the reviewer IS the executor: {executors & reviewers}")

    def test_3_the_decision_engine_returned_accept(self):
        decisions = self.records("decisions")
        self.assertTrue(decisions, "no decision was recorded")
        self.assertEqual(decisions[-1]["decision"], "accept")

    def test_4_an_abstain_would_fail_the_fixture_loudly(self):
        """The guard that keeps this honest.

        If the pipeline ever stops producing independent verification, cmd_decide abstains -
        correctly - and the fixture must break rather than route around it. Asserted on the
        parsed source so the check cannot be softened to a warning unnoticed.
        """
        source = (ROOT / "tests" / "methodology_fixture_builder.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]
        accept_guards = [n for n in asserts if "accept" in ast.dump(n)]
        self.assertTrue(accept_guards,
                        "nothing asserts the decision was accept; an abstain would pass")

    def test_5_the_lifecycle_records_are_real_and_linked(self):
        import nogap_lifecycle as nlc

        rc = nlc.load_release_candidate(self.project, self.builder._lifecycle["rc"])
        self.assertIsNotNone(rc)
        self.assertEqual(rc["status"], "FROZEN")
        deployment = nlc.load_deployment(self.project, self.builder._lifecycle["deployment"])
        self.assertEqual(deployment["status"], "SUCCEEDED")
        self.assertEqual(deployment["release_candidate_id"], rc["release_candidate_id"])
        self.assertTrue(deployment["decision_refs"], "the deployment cites no decision")

    def test_6_and_only_then_is_the_project_at_p21(self):
        self.assertEqual(nm.status(self.project)["current_phase"], "P21")
