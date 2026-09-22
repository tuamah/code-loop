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
        gate = _frozen_gate(self.project)
        self.assertIsNotNone(gate, "no frozen gate exists")
        self.assertEqual(gate["status"], "frozen")
        self.assertTrue(gate["hash"])

    def test_the_builder_binds_to_the_hash_the_system_reports(self):
        """Not a hash it computed for itself: the one the frozen gate actually carries."""
        self.assertEqual(self.builder.gate_hash, _frozen_gate(self.project)["hash"])

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
