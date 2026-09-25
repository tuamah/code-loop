"""ARTIFACT-FIELD-ATTRIBUTION-PRE: `nogap_artifacts.check_required_field` - the public,
field-scoped surface for the "required and non-empty" rule, factored out of `_check_fields`
via the shared `_field_requirement_problem` predicate (no duplicated logic, no new semantic
rule). Built because mutation testing on F3-B1's `artifact_field:*` resolvers proved that
composing over WHOLE-RECORD `validate_record()` mis-attributes failure: a corrupted UNRELATED
field made `decision_has_reason`/`stop_conditions_defined` report FAIL while blaming a field
they never inspected (see tests/test_f3b1_exit_check_resolvers.py's
ArtifactFieldAttributionFinding, which reproduces the original bug directly).
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

import nogap_artifacts as na                                              # noqa: E402
import nogap_methodology as nm                                            # noqa: E402
from test_methodology_build import build_p0_p11_chain                     # noqa: E402


def _new_project(tmp_dir: str) -> Path:
    project = Path(tmp_dir)
    for args in (["init", "-q"], ["config", "user.email", "t@t.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)
    (project / "R.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "R.md"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=project, check=True, capture_output=True)
    nm.init_project(project, "research", "low", "low", actor="test")
    return project


def _project_hash(project: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    for path in sorted(project.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        digest.update(str(path.relative_to(project)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


class CheckRequiredField(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)
        self.chain = build_p0_p11_chain(self.project)

    def _record(self, artifact_id: str) -> dict:
        path = na.artifacts_dir(self.project) / f"{artifact_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_valid_field_satisfied(self):
        record = self._record(self.chain["P5"]["artifact_id"])
        verdict = na.check_required_field(self.project, "P5_STRATEGY_DECISION", "reason", record["fields"])
        self.assertTrue(verdict.satisfied, verdict.detail)
        self.assertEqual(verdict.field, "reason")

    def test_missing_field_fails(self):
        record = self._record(self.chain["P5"]["artifact_id"])
        del record["fields"]["reason"]
        verdict = na.check_required_field(self.project, "P5_STRATEGY_DECISION", "reason", record["fields"])
        self.assertFalse(verdict.satisfied)
        self.assertIn("reason", verdict.detail)

    def test_empty_field_fails(self):
        record = self._record(self.chain["P11"]["artifact_id"])
        record["fields"]["stop_conditions"] = []
        verdict = na.check_required_field(self.project, "P11_GATE_PLAN", "stop_conditions", record["fields"])
        self.assertFalse(verdict.satisfied)
        self.assertIn("stop_conditions", verdict.detail)

    def test_unrelated_field_corruption_does_not_affect_target_field_verdict(self):
        # The exact scenario that broke whole-record composition: reason stays valid,
        # selected_strategy (an independently-validated field, enum-checked elsewhere in
        # validate_record) is corrupted. check_required_field must not even look at it.
        record = self._record(self.chain["P5"]["artifact_id"])
        record["fields"]["selected_strategy"] = "BOGUS"
        verdict = na.check_required_field(self.project, "P5_STRATEGY_DECISION", "reason", record["fields"])
        self.assertTrue(verdict.satisfied, verdict.detail)
        self.assertNotIn("selected_strategy", verdict.detail)

    def test_unrelated_required_field_corruption_does_not_affect_stop_conditions(self):
        record = self._record(self.chain["P11"]["artifact_id"])
        record["fields"]["required_tests"] = []
        verdict = na.check_required_field(self.project, "P11_GATE_PLAN", "stop_conditions", record["fields"])
        self.assertTrue(verdict.satisfied, verdict.detail)
        self.assertNotIn("required_tests", verdict.detail)

    def test_allow_empty_fields_exception_preserved(self):
        # P1_SCOPE.dependencies/known_assumptions are NOT allow_empty; find a real
        # allow_empty_fields entry to prove the exception path still holds. P7_ARCHITECTURE's
        # STANDARD-profile fields aren't allow_empty either - use the real ARTIFACT_TYPES data
        # directly rather than assuming one, per the "no invented semantics" rule.
        import nogap_artifact_types as nat

        allow_empty_type = next(
            (t, info) for t, info in nat.ARTIFACT_TYPES.items() if info.get("allow_empty_fields"))
        artifact_type, info = allow_empty_type
        field = next(iter(info["allow_empty_fields"]))
        fields = {k: (0 if k == field else "x") for k in info["required_fields"]}
        fields[field] = []
        record = self._record(self.chain["P5"]["artifact_id"])  # any valid state suffices
        verdict = na.check_required_field(self.project, artifact_type, field, fields)
        self.assertTrue(verdict.satisfied, verdict.detail)

    def test_field_not_in_required_fields_fails_closed(self):
        record = self._record(self.chain["P5"]["artifact_id"])
        verdict = na.check_required_field(self.project, "P5_STRATEGY_DECISION", "not_a_real_field",
                                          record["fields"])
        self.assertFalse(verdict.satisfied)

    def test_determinism(self):
        record = self._record(self.chain["P5"]["artifact_id"])
        first = na.check_required_field(self.project, "P5_STRATEGY_DECISION", "reason", record["fields"])
        second = na.check_required_field(self.project, "P5_STRATEGY_DECISION", "reason", record["fields"])
        self.assertEqual(first, second)

    def test_purity(self):
        record = self._record(self.chain["P5"]["artifact_id"])
        before = _project_hash(self.project)
        na.check_required_field(self.project, "P5_STRATEGY_DECISION", "reason", record["fields"])
        self.assertEqual(before, _project_hash(self.project))

    def test_check_fields_unchanged_behavior(self):
        # _check_fields (validate_record's own whole-record path) must behave exactly as
        # before the refactor - same problems, same messages, for a record with two broken
        # required fields.
        record = self._record(self.chain["P5"]["artifact_id"])
        record["fields"]["reason"] = ""
        problems = na.validate_record(self.project, record)
        self.assertTrue(any("reason" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
