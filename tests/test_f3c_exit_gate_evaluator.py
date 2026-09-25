"""F3-C: the report-only evaluator (docs/f3-a-exit-check-registry-contract.md §7 item 2).

`evaluate_exit_gate(project, phase_id) -> ExitGateEvaluation` is read-only and never wired
into `_evaluate_transition` - these tests prove exactly that, plus the derived-field and
ordering guarantees §3 makes.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import nogap_exit_registry as er                                          # noqa: E402
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
    digest = hashlib.sha256()
    for path in sorted(project.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        digest.update(str(path.relative_to(project)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _declared_order(phase_id: str) -> list[str]:
    for path in sorted((ROOT / "methodology" / "phases").glob("p*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["id"] == phase_id:
            return list(data["exit_gate"]["checks"])
    raise AssertionError(phase_id)


class UnknownPhase(unittest.TestCase):
    def test_unknown_phase_id_raises(self):
        with self.assertRaises(ValueError):
            er.evaluate_exit_gate(Path("/tmp"), "P99")


class OrderingAndShape(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)

    def test_p1_results_match_declared_order_exactly(self):
        evaluation = er.evaluate_exit_gate(self.project, "P1")
        self.assertEqual([r.check_name for r in evaluation.results], _declared_order("P1"))
        self.assertEqual(evaluation.phase_id, "P1")
        self.assertEqual(evaluation.registry_version, "unversioned")

    def test_p0_results_match_declared_order_exactly(self):
        evaluation = er.evaluate_exit_gate(self.project, "P0")
        self.assertEqual([r.check_name for r in evaluation.results], _declared_order("P0"))

    def test_results_is_a_tuple_not_a_list(self):
        evaluation = er.evaluate_exit_gate(self.project, "P1")
        self.assertIsInstance(evaluation.results, tuple)


class DerivedFields(unittest.TestCase):
    """all_implemented/all_passed, computed exactly per §3, never independently settable."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)
        self.chain = build_p0_p11_chain(self.project)

    def test_valid_p1_is_all_implemented_and_all_passed(self):
        # P1's 4 checks are all DIRECT_COMPOSITION/IMPLEMENTED, and build_p0_p11_chain gives a
        # genuinely valid P1_SCOPE record.
        evaluation = er.evaluate_exit_gate(self.project, "P1")
        self.assertTrue(evaluation.all_implemented)
        self.assertTrue(evaluation.all_passed)
        self.assertTrue(all(r.status == er.PASS for r in evaluation.results))

    def test_p0_has_an_unimplemented_row_so_neither_all_implemented_nor_all_passed(self):
        # P0: intent_classified... is IMPLEMENTED/PASS, objective_stated... is NO_REPRESENTATION
        # (UNIMPLEMENTED).
        evaluation = er.evaluate_exit_gate(self.project, "P0")
        self.assertFalse(evaluation.all_implemented)
        self.assertFalse(evaluation.all_passed)
        statuses = {r.check_name: r.status for r in evaluation.results}
        self.assertEqual(statuses["intent_classified_as_research_production_or_experimental"], er.PASS)
        self.assertEqual(statuses["objective_stated_in_one_paragraph_or_less"], er.UNIMPLEMENTED_RESULT)

    def test_a_real_fail_keeps_all_implemented_true_but_all_passed_false(self):
        import nogap_artifacts as na
        artifact_id = self.chain["P1"]["artifact_id"]
        path = na.artifacts_dir(self.project) / f"{artifact_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["fields"]["constraints"] = []
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        evaluation = er.evaluate_exit_gate(self.project, "P1")
        self.assertTrue(evaluation.all_implemented)
        self.assertFalse(evaluation.all_passed)
        statuses = {r.check_name: r.status for r in evaluation.results}
        self.assertEqual(statuses["constraints_recorded"], er.FAIL)

    def test_p13_mixes_a_build_invariant_unimplemented_row_with_an_implemented_one(self):
        # P13: execution_ran_inside_isolated_worktree is BUILD_INVARIANT/SCOPE_MISMATCH,
        # blocked_by BUILD-INVARIANT-PRE (never touched by F3-B); patch_artifact_recorded is
        # IMPLEMENTED (F3-B2). No prior P13 attempt here, so the implemented one is FAIL.
        evaluation = er.evaluate_exit_gate(self.project, "P13")
        by_name = {r.check_name: r for r in evaluation.results}
        bi = by_name["execution_ran_inside_isolated_worktree"]
        self.assertEqual(bi.status, er.UNIMPLEMENTED_RESULT)
        self.assertIn("SCOPE_MISMATCH", bi.detail)
        self.assertIn("BUILD-INVARIANT-PRE", bi.detail)
        self.assertIsNone(bi.semantic_source)
        patch = by_name["patch_artifact_recorded"]
        self.assertEqual(patch.status, er.FAIL)
        self.assertFalse(evaluation.all_implemented)
        self.assertFalse(evaluation.all_passed)

    def test_p22_small_binding_row_has_no_blocked_by_in_detail(self):
        # improvement_proposal_cites_evidence (SMALL_BINDING/NOT_BOUND, still unimplemented -
        # F3-D2's own future scope) never carries blocked_by (§6 invariant 9) - detail must
        # not fabricate one. (P6/P7/P9/P19's SMALL_BINDING rows are IMPLEMENTED now - F3-D1 -
        # see tests/test_f3d1_small_binding_resolvers.py for their own coverage.)
        evaluation = er.evaluate_exit_gate(self.project, "P22")
        row = next(r for r in evaluation.results if r.check_name == "improvement_proposal_cites_evidence")
        self.assertEqual(row.status, er.UNIMPLEMENTED_RESULT)
        self.assertIn("NOT_BOUND", row.detail)
        self.assertNotIn("blocked_by", row.detail)


class ErrorPropagation(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)
        build_p0_p11_chain(self.project)

    def test_a_raising_resolver_surfaces_as_error_and_does_not_short_circuit_the_gate(self):
        # problem_statement_exists is P1's FIRST declared check - if evaluate_exit_gate
        # stopped at the first ERROR, the other three P1 checks would never appear in
        # `results` at all. Asserting they are present AND correctly PASS proves iteration
        # continues past an ERROR, not merely that ERROR itself is produced.
        original = er.RESOLVERS["required_kind:PROBLEM_STATEMENT"]

        def raiser(ctx, entry):
            raise RuntimeError("simulated fault")

        er.RESOLVERS["required_kind:PROBLEM_STATEMENT"] = raiser
        try:
            evaluation = er.evaluate_exit_gate(self.project, "P1")
        finally:
            er.RESOLVERS["required_kind:PROBLEM_STATEMENT"] = original

        self.assertEqual([r.check_name for r in evaluation.results], _declared_order("P1"))
        by_name = {r.check_name: r for r in evaluation.results}
        row = by_name["problem_statement_exists"]
        self.assertEqual(row.status, er.ERROR)
        self.assertIn("simulated fault", row.detail)
        # §3's own literal rule: all_implemented only excludes UNIMPLEMENTED, ERROR still
        # counts as "implemented" (a real adapter exists and ran) - only all_passed reflects it.
        self.assertTrue(evaluation.all_implemented)
        self.assertFalse(evaluation.all_passed)
        # the three OTHER P1 checks were still evaluated normally, not skipped.
        for name in ("in_scope_list_nonempty", "out_of_scope_list_exists", "constraints_recorded"):
            self.assertEqual(by_name[name].status, er.PASS, name)

    def test_semantic_source_mismatch_surfaces_as_error_and_does_not_short_circuit(self):
        original = er.RESOLVERS["required_kind:PROBLEM_STATEMENT"]

        def mismatched(ctx, entry):
            return er.ResolverOutcome(er.PASS, "fake", "required_kind:WRONG_KIND")

        er.RESOLVERS["required_kind:PROBLEM_STATEMENT"] = mismatched
        try:
            evaluation = er.evaluate_exit_gate(self.project, "P1")
        finally:
            er.RESOLVERS["required_kind:PROBLEM_STATEMENT"] = original

        by_name = {r.check_name: r for r in evaluation.results}
        row = by_name["problem_statement_exists"]
        self.assertEqual(row.status, er.ERROR)
        self.assertIn("semantic_source mismatch", row.detail)
        self.assertFalse(evaluation.all_passed)
        for name in ("in_scope_list_nonempty", "out_of_scope_list_exists", "constraints_recorded"):
            self.assertEqual(by_name[name].status, er.PASS, name)


class Purity(unittest.TestCase):
    """Never mutates project state; never wired into _evaluate_transition."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)
        build_p0_p11_chain(self.project)

    def test_evaluating_every_prebuild_phase_does_not_touch_the_project(self):
        before = _project_hash(self.project)
        for phase_id in ("P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11"):
            er.evaluate_exit_gate(self.project, phase_id)
        self.assertEqual(before, _project_hash(self.project))

    def test_determinism(self):
        first = er.evaluate_exit_gate(self.project, "P1")
        second = er.evaluate_exit_gate(self.project, "P1")
        self.assertEqual(first, second)

    def test_never_wired_into_evaluate_transition(self):
        import inspect

        source = inspect.getsource(nm._evaluate_transition)
        self.assertNotIn("evaluate_exit_gate", source)
        self.assertNotIn("nogap_exit_registry", source)


if __name__ == "__main__":
    unittest.main()
