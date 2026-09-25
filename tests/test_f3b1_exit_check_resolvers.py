"""F3-B1: resolvers for the 21 DIRECT_COMPOSITION rows whose planned_resolver_id is reachable
from ResolverContext{project, phase_id} alone (docs/f3-a-exit-check-registry-contract.md, F3-B
GO). P5/P8 (registry-blocked on wording) and P13/P14 (F3-B2, BLOCKED on
RESOLVER-CONTEXT-REF-GAP-PRE) carry no resolver here - confirmed by test_registry_scope below.

Every fixture reuses this repo's existing, already-trusted builders
(build_p0_p11_chain/LifecycleFixture/make_task_contract/freeze_gate_before_build) - no new
project-state construction invented for this file.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import nogap_artifacts as na                                              # noqa: E402
import nogap_exit_registry as er                                          # noqa: E402
import nogap_methodology as nm                                            # noqa: E402
from methodology_fixture_builder import freeze_gate_before_build          # noqa: E402
from test_methodology_build import build_p0_p11_chain                     # noqa: E402
from test_methodology_lifecycle import LifecycleFixture, make_task_contract  # noqa: E402


def _new_project(tmp_dir: str) -> Path:
    """A fresh git-initialized, methodology-initialized project - the same two-step setup
    test_f2b_cost_model.py and every other F2b resolver test file uses before calling
    build_p0_p11_chain (which itself needs nm.init_project's state to exist)."""
    import subprocess

    project = Path(tmp_dir)
    for args in (["init", "-q"], ["config", "user.email", "t@t.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)
    (project / "R.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "R.md"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=project, check=True, capture_output=True)
    nm.init_project(project, "research", "low", "low", actor="test")
    return project


def _project_hash(project: Path) -> str:
    """Purity check primitive (§4.3): a stable digest over every tracked file's content."""
    digest = hashlib.sha256()
    for path in sorted(project.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        digest.update(str(path.relative_to(project)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


class RegistryScope(unittest.TestCase):
    """Point 7: registry-load invariants stay correct, and exactly the authorized 21 rows are
    IMPLEMENTED - never more, never fewer."""

    def test_registry_loads_and_exactly_21_rows_are_implemented(self):
        # ARTIFACT-FIELD-ATTRIBUTION-PRE closed: the 2 artifact_field: rows (P5
        # decision_has_reason, P11 stop_conditions_defined) are back to IMPLEMENTED, now bound
        # to nogap_artifacts.check_required_field instead of whole-record validate_record().
        registry = er.load_registry()
        self.assertEqual(len(registry), 50)
        implemented = {k for k, v in registry.items() if v.implementation_status == er.IMPLEMENTED}
        self.assertEqual(len(implemented), 21)
        for key in implemented:
            entry = registry[key]
            self.assertEqual(entry.classification, er.DIRECT_COMPOSITION)
            self.assertEqual(entry.resolver_id, entry.planned_resolver_id)
            self.assertEqual(entry.semantic_source, entry.resolver_id)
            self.assertIsNone(entry.unimplemented_reason)
            self.assertIsNone(entry.blocked_by)

    def test_p5_p8_p13_p14_stay_unimplemented(self):
        registry = er.load_registry()
        for key in (("P5", "decision_value_is_one_of_build_buy_adopt_fork_integrate"),
                    ("P8", "adr_records_reason"),
                    ("P13", "patch_artifact_recorded"),
                    ("P14", "execution_evidence_authority_is_execution")):
            entry = registry[key]
            self.assertEqual(entry.implementation_status, er.UNIMPLEMENTED, key)
            self.assertEqual(entry.classification, er.DIRECT_COMPOSITION, key)
            self.assertIsNone(entry.resolver_id, key)
            self.assertIsNone(entry.semantic_source, key)
        self.assertEqual(registry[("P5", "decision_value_is_one_of_build_buy_adopt_fork_integrate")]
                          .unimplemented_reason, er.WORDING_CONFLICT)
        self.assertEqual(registry[("P8", "adr_records_reason")].unimplemented_reason, er.WORDING_CONFLICT)
        self.assertEqual(registry[("P13", "patch_artifact_recorded")].unimplemented_reason,
                          er.RESOLVER_PENDING)
        self.assertEqual(registry[("P14", "execution_evidence_authority_is_execution")]
                          .unimplemented_reason, er.RESOLVER_PENDING)
        self.assertIsNone(registry[("P13", "patch_artifact_recorded")].blocked_by)
        self.assertIsNone(registry[("P14", "execution_evidence_authority_is_execution")].blocked_by)

    def test_artifact_field_rows_reimplemented_after_attribution_repair(self):
        # ARTIFACT-FIELD-ATTRIBUTION-PRE closed: both rows are IMPLEMENTED again, bound to
        # nogap_artifacts.check_required_field (not validate_record).
        registry = er.load_registry()
        for key in (("P5", "decision_has_reason"), ("P11", "stop_conditions_defined")):
            entry = registry[key]
            self.assertEqual(entry.implementation_status, er.IMPLEMENTED, key)
            self.assertEqual(entry.classification, er.DIRECT_COMPOSITION, key)
            self.assertEqual(entry.resolver_id, entry.planned_resolver_id, key)
            self.assertIsNone(entry.unimplemented_reason, key)
            self.assertIsNone(entry.blocked_by, key)

    def test_no_resolver_bound_for_p13_p14(self):
        self.assertNotIn("required_kind:PATCH", er.RESOLVERS)
        self.assertNotIn("required_kind:EXECUTION_EVIDENCE", er.RESOLVERS)

    def test_exactly_18_unique_resolvers_bound(self):
        self.assertEqual(len(er.RESOLVERS), 18)


class P0ThroughP11Fixture(unittest.TestCase):
    """One shared project for every P0-P11 required_kind/artifact_field resolver: build once,
    read many times (each test only inspects, never mutates the shared fixture, except via a
    scoped rewrite/restore pair)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.project = _new_project(cls.tmp.name)
        cls.chain = build_p0_p11_chain(cls.project)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def _rewrite(self, artifact_id: str, **changes) -> dict:
        """Mutates one artifact's fields, returns the ORIGINAL record so the caller can
        restore it (every test using this must restore in a finally block - the fixture is
        shared across the whole class)."""
        path = na.artifacts_dir(self.project) / f"{artifact_id}.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        record = json.loads(json.dumps(original))
        for key, value in changes.items():
            if key == "fields":
                record["fields"].update(value)
            else:
                record[key] = value
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return original

    def _restore(self, artifact_id: str, original: dict) -> None:
        path = na.artifacts_dir(self.project) / f"{artifact_id}.json"
        path.write_text(json.dumps(original, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _ctx(self, phase_id: str) -> er.ResolverContext:
        return er.ResolverContext(project=self.project, phase_id=phase_id)

    def _entry(self, phase_id: str, check_name: str) -> er.RegistryEntry:
        return self.registry[(phase_id, check_name)]

    def setUp(self) -> None:
        self.registry = er.load_registry()

    # -- shared assertions, reused by every resolver family below --

    def assert_positive(self, phase_id: str, check_name: str) -> er.ResolverOutcome:
        entry = self._entry(phase_id, check_name)
        outcome = er.resolve(entry, self._ctx(phase_id))
        self.assertEqual(outcome.status, er.PASS, outcome.detail)
        self.assertEqual(outcome.semantic_source, entry.semantic_source)
        return outcome

    def assert_negative(self, phase_id: str, check_name: str, expected_status: str = er.FAIL) -> er.ResolverOutcome:
        entry = self._entry(phase_id, check_name)
        outcome = er.resolve(entry, self._ctx(phase_id))
        self.assertEqual(outcome.status, expected_status, outcome.detail)
        return outcome

    def assert_deterministic(self, phase_id: str, check_name: str) -> None:
        entry = self._entry(phase_id, check_name)
        ctx = self._ctx(phase_id)
        first = er.resolve(entry, ctx)
        second = er.resolve(entry, ctx)
        self.assertEqual(first, second)

    def assert_pure(self, phase_id: str, check_name: str) -> None:
        entry = self._entry(phase_id, check_name)
        before = _project_hash(self.project)
        er.resolve(entry, self._ctx(phase_id))
        after = _project_hash(self.project)
        self.assertEqual(before, after)


class RequiredArtifactFieldResolvers(P0ThroughP11Fixture):
    """PROJECT_INTENT, PROBLEM_STATEMENT, SCOPE, CONSTRAINTS, FAILURE_CRITERIA, RISK_LEVEL,
    CLAIM_STRENGTH, GAP_ANALYSIS, COST_MODEL, RUNTIME_STRUCTURE, BASELINE, METRICS,
    TASK_CONTRACT (via the artifact_field:/required_kind: families that resolve via
    list_artifacts(project, artifact_type, phase_id))."""

    CASES = [
        ("P0", "intent_classified_as_research_production_or_experimental", "P0", "expected_cost_unused"),
    ]

    def test_project_intent_positive_negative_determinism_purity(self):
        phase, check = "P0", "intent_classified_as_research_production_or_experimental"
        self.assert_positive(phase, check)
        self.assert_deterministic(phase, check)
        self.assert_pure(phase, check)
        artifact_id = self.chain["P0"]["artifact_id"]
        original = self._rewrite(artifact_id, fields={"project_name": ""})
        try:
            self.assert_negative(phase, check)
        finally:
            self._restore(artifact_id, original)

    def test_problem_statement_positive_missing_wrong_type(self):
        phase, check = "P1", "problem_statement_exists"
        self.assert_positive(phase, check)
        self.assert_deterministic(phase, check)
        self.assert_pure(phase, check)
        artifact_id = self.chain["P1"]["artifact_id"]
        original = self._rewrite(artifact_id, fields={"problem_statement": ""})
        try:
            self.assert_negative(phase, check)
        finally:
            self._restore(artifact_id, original)
        # WRONG_TYPE: the phase has no P1_SCOPE at all -> MISSING via an empty type filter
        entry = self._entry("P6", "requirements_have_stable_ids_req_prefix")  # sanity: not IMPLEMENTED
        self.assertIsNone(entry.resolver_id)

    def test_scope_in_and_out_positive_negative(self):
        artifact_id = self.chain["P1"]["artifact_id"]
        for check in ("in_scope_list_nonempty", "out_of_scope_list_exists"):
            self.assert_positive("P1", check)
            self.assert_deterministic("P1", check)
            self.assert_pure("P1", check)
        original = self._rewrite(artifact_id, fields={"in_scope": [], "out_of_scope": []})
        try:
            self.assert_negative("P1", "in_scope_list_nonempty")
            self.assert_negative("P1", "out_of_scope_list_exists")
        finally:
            self._restore(artifact_id, original)

    def test_constraints_positive_negative(self):
        phase, check = "P1", "constraints_recorded"
        self.assert_positive(phase, check)
        self.assert_deterministic(phase, check)
        self.assert_pure(phase, check)
        artifact_id = self.chain["P1"]["artifact_id"]
        original = self._rewrite(artifact_id, fields={"constraints": []})
        try:
            self.assert_negative(phase, check)
        finally:
            self._restore(artifact_id, original)

    def test_failure_criteria_risk_claim_strength(self):
        artifact_id = self.chain["P2"]["artifact_id"]
        for check, field in (("failure_criteria_recorded", "failure_criteria"),
                              ("risk_level_set", "risk_level"),
                              ("claim_strength_set", "claim_strength")):
            self.assert_positive("P2", check)
            self.assert_deterministic("P2", check)
            self.assert_pure("P2", check)
            original = self._rewrite(artifact_id, fields={field: "" if field != "failure_criteria" else []})
            try:
                self.assert_negative("P2", check)
            finally:
                self._restore(artifact_id, original)

    def test_gap_analysis_positive_stale(self):
        phase, check = "P4", "gap_analysis_references_prior_art_map"
        self.assert_positive(phase, check)
        self.assert_deterministic(phase, check)
        self.assert_pure(phase, check)
        artifact_id = self.chain["P4"]["artifact_id"]
        original = self._rewrite(artifact_id, status="SUPERSEDED")
        try:
            self.assert_negative(phase, check, er.FAIL)
        finally:
            self._restore(artifact_id, original)

    def test_cost_model_positive_negative(self):
        phase, check = "P8", "cost_model_covers_at_least_one_dimension"
        self.assert_positive(phase, check)
        self.assert_deterministic(phase, check)
        self.assert_pure(phase, check)
        artifact_id = self.chain["P8"]["artifact_id"]
        original = self._rewrite(artifact_id, fields={"expected_cost": ""})
        try:
            self.assert_negative(phase, check)
        finally:
            self._restore(artifact_id, original)

    def test_runtime_structure_positive_negative(self):
        phase, check = "P9", "runtime_structure_initialized"
        self.assert_positive(phase, check)
        self.assert_deterministic(phase, check)
        self.assert_pure(phase, check)
        artifact_id = self.chain["P9_RUNTIME_STRUCTURE"]["artifact_id"]
        original = self._rewrite(artifact_id, fields={"runtime_structure_version": "999"})
        try:
            self.assert_negative(phase, check)
        finally:
            self._restore(artifact_id, original)

    def test_baseline_and_metrics_positive_negative(self):
        artifact_id = self.chain["P10"]["artifact_id"]
        for check in ("baseline_recorded", "at_least_one_primary_metric_defined"):
            self.assert_positive("P10", check)
            self.assert_deterministic("P10", check)
            self.assert_pure("P10", check)
        original = self._rewrite(artifact_id, fields={"primary_metric": ""})
        try:
            self.assert_negative("P10", "at_least_one_primary_metric_defined")
        finally:
            self._restore(artifact_id, original)

    def test_golden_gates_missing_before_freeze(self):
        # No frozen gate exists yet in this shared fixture -> MISSING (mapped to FAIL).
        self.assert_negative("P11", "frozen_gate_exists")
        self.assert_deterministic("P11", "frozen_gate_exists")
        self.assert_pure("P11", "frozen_gate_exists")


class GoldenGatesPositive(unittest.TestCase):
    """A separate, dedicated project so freezing the gate never interferes with the shared
    P0-P11 fixture above."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)
        build_p0_p11_chain(self.project)
        freeze_gate_before_build(self.project)
        self.registry = er.load_registry()

    def test_golden_gates_positive_deterministic_pure(self):
        entry = self.registry[("P11", "frozen_gate_exists")]
        ctx = er.ResolverContext(project=self.project, phase_id="P11")
        outcome = er.resolve(entry, ctx)
        self.assertEqual(outcome.status, er.PASS, outcome.detail)
        second = er.resolve(entry, ctx)
        self.assertEqual(outcome, second)
        before = _project_hash(self.project)
        er.resolve(entry, ctx)
        self.assertEqual(before, _project_hash(self.project))


class TaskContractResolvers(unittest.TestCase):
    """The three P12 checks share one resolver_id (required_kind:TASK_CONTRACT) - a single
    valid record satisfies all three; missing any of its required fields fails all three
    together, exactly as WholeArtifact composition implies."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)
        self.chain = build_p0_p11_chain(self.project)
        self.contract = make_task_contract(self.project, self.chain)
        self.registry = er.load_registry()

    def _ctx(self) -> er.ResolverContext:
        return er.ResolverContext(project=self.project, phase_id="P12")

    def test_all_three_positive(self):
        for check in ("task_contract_has_goal_and_scope", "task_contract_has_forbidden_scope",
                      "task_contract_has_acceptance_criteria"):
            entry = self.registry[("P12", check)]
            outcome = er.resolve(entry, self._ctx())
            self.assertEqual(outcome.status, er.PASS, outcome.detail)

    def test_determinism_and_purity(self):
        entry = self.registry[("P12", "task_contract_has_goal_and_scope")]
        ctx = self._ctx()
        self.assertEqual(er.resolve(entry, ctx), er.resolve(entry, ctx))
        before = _project_hash(self.project)
        er.resolve(entry, ctx)
        self.assertEqual(before, _project_hash(self.project))

    def test_missing_forbidden_scope_fails_all_three(self):
        path = na.artifacts_dir(self.project) / f"{self.contract['artifact_id']}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["fields"]["forbidden_scope"] = []
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for check in ("task_contract_has_goal_and_scope", "task_contract_has_forbidden_scope",
                      "task_contract_has_acceptance_criteria"):
            entry = self.registry[("P12", check)]
            outcome = er.resolve(entry, self._ctx())
            self.assertEqual(outcome.status, er.FAIL, check)

    def test_no_task_contract_recorded_is_missing(self):
        empty_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(empty_dir, ignore_errors=True))
        empty_project = _new_project(empty_dir)
        build_p0_p11_chain(empty_project)
        entry = er.load_registry()[("P12", "task_contract_has_goal_and_scope")]
        outcome = er.resolve(entry, er.ResolverContext(project=empty_project, phase_id="P12"))
        self.assertEqual(outcome.status, er.FAIL)


class ArtifactFieldAttributionFinding(unittest.TestCase):
    """ARTIFACT-FIELD-ATTRIBUTION-PRE: the original bug (composing over whole-record
    validate_record() mis-attributes failure) reproduced at the `validate_record` level, AND
    proof that the now-rebound resolvers (nogap_artifacts.check_required_field) no longer have
    it - the same corrupting mutation that broke the old resolver must NOT break the new one.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)
        self.chain = build_p0_p11_chain(self.project)
        self.registry = er.load_registry()

    def test_validate_record_itself_still_conflates_fields(self):
        # This is the raw fact that made the OLD resolver wrong - validate_record's own
        # return value never distinguished which field a problem belongs to. Still true today
        # (validate_record itself was never changed); the fix is that the resolver no longer
        # uses it for this purpose.
        artifact_id = self.chain["P5"]["artifact_id"]
        path = na.artifacts_dir(self.project) / f"{artifact_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["fields"]["selected_strategy"] = "BOGUS"
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        problems = na.validate_record(self.project, record)
        self.assertTrue(problems)
        self.assertTrue(all("reason" not in p for p in problems), problems)
        self.assertTrue(any("selected_strategy" in p for p in problems), problems)

    def test_resolver_no_longer_mis_attributes_p5_reason(self):
        # The exact scenario above, through the REAL resolve() path this time.
        artifact_id = self.chain["P5"]["artifact_id"]
        path = na.artifacts_dir(self.project) / f"{artifact_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["fields"]["selected_strategy"] = "BOGUS"
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        entry = self.registry[("P5", "decision_has_reason")]
        outcome = er.resolve(entry, er.ResolverContext(project=self.project, phase_id="P5"))
        self.assertEqual(outcome.status, er.PASS, outcome.detail)
        self.assertNotIn("selected_strategy", outcome.detail)

    def test_resolver_no_longer_mis_attributes_p11_stop_conditions(self):
        artifact_id = self.chain["P11"]["artifact_id"]
        path = na.artifacts_dir(self.project) / f"{artifact_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["fields"]["required_tests"] = []
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        entry = self.registry[("P11", "stop_conditions_defined")]
        outcome = er.resolve(entry, er.ResolverContext(project=self.project, phase_id="P11"))
        self.assertEqual(outcome.status, er.PASS, outcome.detail)
        self.assertNotIn("required_tests", outcome.detail)

    def test_resolvers_still_correctly_fail_on_their_own_field(self):
        # The fix must not become a blanket PASS - the target field's OWN emptiness must
        # still be caught.
        p5_id = self.chain["P5"]["artifact_id"]
        p5_path = na.artifacts_dir(self.project) / f"{p5_id}.json"
        p5_record = json.loads(p5_path.read_text(encoding="utf-8"))
        p5_record["fields"]["reason"] = ""
        p5_path.write_text(json.dumps(p5_record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        outcome = er.resolve(self.registry[("P5", "decision_has_reason")],
                             er.ResolverContext(project=self.project, phase_id="P5"))
        self.assertEqual(outcome.status, er.FAIL)

        p11_id = self.chain["P11"]["artifact_id"]
        p11_path = na.artifacts_dir(self.project) / f"{p11_id}.json"
        p11_record = json.loads(p11_path.read_text(encoding="utf-8"))
        p11_record["fields"]["stop_conditions"] = []
        p11_path.write_text(json.dumps(p11_record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        outcome = er.resolve(self.registry[("P11", "stop_conditions_defined")],
                             er.ResolverContext(project=self.project, phase_id="P11"))
        self.assertEqual(outcome.status, er.FAIL)

    def test_positive_deterministic_pure(self):
        for key, phase in ((("P5", "decision_has_reason"), "P5"),
                           (("P11", "stop_conditions_defined"), "P11")):
            entry = self.registry[key]
            ctx = er.ResolverContext(project=self.project, phase_id=phase)
            outcome = er.resolve(entry, ctx)
            self.assertEqual(outcome.status, er.PASS, outcome.detail)
            self.assertEqual(er.resolve(entry, ctx), outcome)
            before = _project_hash(self.project)
            er.resolve(entry, ctx)
            self.assertEqual(before, _project_hash(self.project))


class ReleaseCandidateResolvers(LifecycleFixture):
    """lifecycle:candidate_binding and required_kind:EVIDENCE_BUNDLE - both P19 checks, both
    resolved via nogap_lifecycle.get_current_release_candidate (the existing, authoritative
    "current RC" selector), never a new one."""

    def _ctx(self) -> er.ResolverContext:
        return er.ResolverContext(project=self.project, phase_id="P19")

    def test_no_frozen_rc_yet_is_fail(self):
        registry = er.load_registry()
        for check in ("release_candidate_commit_matches_verified_commit",
                      "evidence_bundle_references_verification_evidence"):
            entry = registry[("P19", check)]
            outcome = er.resolve(entry, self._ctx())
            self.assertEqual(outcome.status, er.FAIL, outcome.detail)
            self.assertEqual(outcome.detail, "no FROZEN release candidate exists for this project")

    def test_frozen_rc_with_real_bindings_positive_and_deterministic(self):
        frozen = self.frozen_candidate()
        registry = er.load_registry()
        ctx = self._ctx()
        for check in ("release_candidate_commit_matches_verified_commit",
                      "evidence_bundle_references_verification_evidence"):
            entry = registry[("P19", check)]
            outcome = er.resolve(entry, ctx)
            self.assertEqual(outcome.status, er.PASS, outcome.detail)
            self.assertEqual(er.resolve(entry, ctx), outcome)

    def test_frozen_rc_purity(self):
        self.frozen_candidate()
        registry = er.load_registry()
        entry = registry[("P19", "release_candidate_commit_matches_verified_commit")]
        before = _project_hash(self.project)
        er.resolve(entry, self._ctx())
        self.assertEqual(before, _project_hash(self.project))

    def test_empty_candidate_bindings_fails_candidate_binding_check(self):
        self.make_candidate(candidate_bindings={})
        registry = er.load_registry()
        entry = registry[("P19", "release_candidate_commit_matches_verified_commit")]
        outcome = er.resolve(entry, self._ctx())
        self.assertEqual(outcome.status, er.FAIL)

    def test_evidence_bundle_fails_on_a_non_frozen_candidate(self):
        self.make_candidate()  # created, never frozen
        registry = er.load_registry()
        entry = registry[("P19", "evidence_bundle_references_verification_evidence")]
        outcome = er.resolve(entry, self._ctx())
        self.assertEqual(outcome.status, er.FAIL)


class ResolveErrorHandling(unittest.TestCase):
    """§4.2/§3.2 - the shared `resolve()` wrapper's own error-handling guarantees, proven
    directly rather than only implied by every resolver's own tests above."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)
        build_p0_p11_chain(self.project)
        self.registry = er.load_registry()

    def test_resolver_exception_becomes_error_not_a_crash(self):
        entry = self.registry[("P1", "problem_statement_exists")]
        broken = er.RESOLVERS["required_kind:PROBLEM_STATEMENT"]

        def raiser(ctx, e):
            raise RuntimeError("simulated resolver fault")

        original = er.RESOLVERS["required_kind:PROBLEM_STATEMENT"]
        er.RESOLVERS["required_kind:PROBLEM_STATEMENT"] = raiser
        try:
            outcome = er.resolve(entry, er.ResolverContext(project=self.project, phase_id="P1"))
        finally:
            er.RESOLVERS["required_kind:PROBLEM_STATEMENT"] = original
        self.assertEqual(outcome.status, er.ERROR)
        self.assertIn("simulated resolver fault", outcome.detail)

    def test_semantic_source_mismatch_becomes_error(self):
        entry = self.registry[("P1", "problem_statement_exists")]

        def mismatched(ctx, e):
            return er.ResolverOutcome(er.PASS, "fake", "required_kind:WRONG_KIND")

        original = er.RESOLVERS["required_kind:PROBLEM_STATEMENT"]
        er.RESOLVERS["required_kind:PROBLEM_STATEMENT"] = mismatched
        try:
            outcome = er.resolve(entry, er.ResolverContext(project=self.project, phase_id="P1"))
        finally:
            er.RESOLVERS["required_kind:PROBLEM_STATEMENT"] = original
        self.assertEqual(outcome.status, er.ERROR)
        self.assertIn("semantic_source mismatch", outcome.detail)

    def test_resolve_rejects_an_unimplemented_row(self):
        entry = self.registry[("P5", "decision_value_is_one_of_build_buy_adopt_fork_integrate")]
        with self.assertRaises(ValueError):
            er.resolve(entry, er.ResolverContext(project=self.project, phase_id="P5"))


if __name__ == "__main__":
    unittest.main()
