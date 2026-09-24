"""F2b D5: REVIEW_VERDICT resolver (Rev 2.1 section 2.6/2.6.1) and its three-way agreement.

Checked pre-freeze, at P18->P19 (freeze_release_candidate()'s own can_transition(P19) dry
run) - composite over the RC's candidate_bindings, exactly like D4's EVIDENCE_BUNDLE is
composite over its evidence set, but never requiring FROZEN/V3 (that would make freeze's own
dry run unsatisfiable before freeze ever runs).

Every RC/P18/evidence record here comes from the real pipeline. Where a state is unreachable
through the real API, the real on-disk record is edited in place, and the test says so.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import sys
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import nogap_artifacts as na                                              # noqa: E402
import nogap_lifecycle as nlc                                             # noqa: E402
import nogap_methodology as nm                                            # noqa: E402
import nogap_required_kinds as rk                                         # noqa: E402
from methodology_fixture_builder import real_candidate_bindings           # noqa: E402
from test_methodology_lifecycle import (                                  # noqa: E402
    LifecycleFixture, StandardProfileLifecycleFixture, make_task_contract,
)

UNATTESTED = hashlib.sha256(b"unattested-d5").hexdigest()


class D5AgreementGuard(unittest.TestCase):
    """T1: contract declaration <-> SEMANTIC_RESOLVERS <-> ENFORCED_KINDS, for P18/REVIEW_VERDICT."""

    def test_t1_real_three_way_agreement(self):
        m = nm.load_methodology()
        name = m.phases["P18"].semantic_resolvers["REVIEW_VERDICT"]
        self.assertEqual(rk.SEMANTIC_RESOLVERS[name].kind, "REVIEW_VERDICT")
        self.assertIsInstance(rk.ENFORCED_KINDS["REVIEW_VERDICT"], rk.ReviewVerdict)
        self.assertNotIn("REVIEW_VERDICT", rk.DEFERRED_KINDS)
        self.assertIsNone(rk.semantic_resolver_agreement_problem("REVIEW_VERDICT", name))

    def assert_load_rejected(self, fragment: str) -> None:
        with self.assertRaises(nm.MethodologyValidationError) as ctx:
            nm.load_methodology()
        self.assertIn(fragment, str(ctx.exception))

    def test_t1b_registered_for_wrong_kind_rejected(self):
        wrong = {"REVIEW_VERDICT_RESOLVER": rk.SemanticResolverSpec(kind="RELEASE_CANDIDATE")}
        with mock.patch.dict(rk.SEMANTIC_RESOLVERS, wrong):
            self.assert_load_rejected("is registered for kind 'RELEASE_CANDIDATE', not 'REVIEW_VERDICT'")

    def test_t1c_kind_not_enforced_rejected(self):
        with mock.patch.dict(rk.ENFORCED_KINDS):
            del rk.ENFORCED_KINDS["REVIEW_VERDICT"]
            self.assert_load_rejected("has no implementation in ENFORCED_KINDS")


class D5Structural(unittest.TestCase):
    """T-STRUCT: no dynamic import / getattr-by-string / reflection in the new code, and
    nogap_lifecycle.py never swallows MethodologyValidationError (the module-wide invariant
    test_23_no_transition_swallowing_pattern_remains already enforces on the whole module)."""

    BANNED = {"getattr", "__import__", "import_module", "importlib", "eval", "exec",
              "globals", "locals", "vars", "setattr", "hasattr"}

    def test_struct_no_dynamic_resolution(self):
        sources = [inspect.getsource(f) for f in (
            rk._check_review_verdict_kind, nlc.review_verdict_problem)]
        for src in sources:
            for node in ast.walk(ast.parse(textwrap.dedent(src))):
                self.assertNotIsInstance(node, ast.Import)
                if isinstance(node, ast.ImportFrom):
                    # review_verdict_problem lazily imports EVIDENCE_STATUS from plain
                    # "nogap" (the entrypoint module, not a nogap_* submodule) - the same
                    # lazy-import-to-break-circularity pattern every nogap_lifecycle.py
                    # function already uses for its other nogap_* dependencies.
                    self.assertTrue(node.module == "nogap" or node.module.startswith("nogap_"), node.module)
                if isinstance(node, ast.Name):
                    self.assertNotIn(node.id, self.BANNED)
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, self.BANNED)

    def test_struct_resolver_never_catches_methodology_validation_error(self):
        """The invariant is module-wide (test_methodology_lifecycle.py's
        NoSilentSwallowingTests already asserts it for all of nogap_lifecycle.py); this
        pins it specifically to the function this task added, so a future edit that
        re-introduces a catch here fails right where it was introduced."""
        src = inspect.getsource(nlc.review_verdict_problem)
        self.assertNotIn("except MethodologyValidationError", src)


class ReviewVerdictResolverLightProfile(LifecycleFixture):
    """LIGHT profile: independent review is not required, so the real P18 this fixture
    produces is independent_review_performed=False / SKIPPED_PER_PROFILE_POLICY - the
    baseline "review never attempted, and that is fine" case."""

    def check(self, rc_id: str) -> rk.Verdict:
        (verdict,) = rk.check_required_kinds(self.project, ["REVIEW_VERDICT"], [rc_id])
        return verdict

    def assert_rejected(self, verdict: rk.Verdict, *fragments: str) -> None:
        self.assertEqual(verdict.outcome, rk.REJECTED, str(verdict))
        for fragment in fragments:
            self.assertIn(fragment, verdict.detail)

    def edit_json(self, path: Path, fn) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        fn(data)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def edit_p18(self, fn) -> None:
        (p18,) = na.list_artifacts(self.project, artifact_type="P18_VERIFICATION_RESULT")
        self.edit_json(na.artifacts_dir(self.project) / f"{p18['artifact_id']}.json", fn)

    def edit_rc(self, rc_id: str, fn) -> None:
        self.edit_json(nlc._kind_dir(self.project, "release_candidates") / f"{rc_id}.json", fn)

    def complete_candidate(self, **overrides) -> dict:
        overrides.setdefault("candidate_bindings", real_candidate_bindings(self.project, [self.task_id]))
        return self.make_candidate(**overrides)

    # -- T2: skipped-per-profile-policy is a legitimate, PASSING verdict --
    def test_t2_skipped_per_profile_policy_validated(self):
        rc = self.complete_candidate()
        verdict = self.check(rc["release_candidate_id"])
        self.assertEqual(verdict.outcome, rk.VALIDATED, str(verdict))

    def test_t2b_no_rc_among_refs_rejected(self):
        (verdict,) = rk.check_required_kinds(self.project, ["REVIEW_VERDICT"], ["RC-999"])
        self.assert_rejected(verdict, "no resolvable release candidate")

    # -- T3: exact candidate_bindings coverage (pre-freeze, DRAFT RC, no FROZEN required) --
    def test_t3_incomplete_candidate_bindings_rejected(self):
        rc = self.make_candidate(candidate_bindings={})
        self.assert_rejected(self.check(rc["release_candidate_id"]), f"missing=[{self.task_id!r}]")

    def test_t3b_extra_candidate_bindings_rejected(self):
        # Unreachable via real creation (create_release_candidate validates bindings against
        # included_task_refs itself): the real record is edited in place, same convention as
        # EVIDENCE_BUNDLE's non-V3/incomplete-binding tests use for other unreachable states.
        other = make_task_contract(self.project, self.chain)["fields"]["task_id"]
        real_hash = na.list_artifacts(self.project, artifact_type="P18_VERIFICATION_RESULT")[0]["fields"]["candidate_hash"]
        rc = self.complete_candidate()
        self.edit_rc(rc["release_candidate_id"],
                     lambda r: r["candidate_bindings"].update({other: real_hash}))
        self.assert_rejected(self.check(rc["release_candidate_id"]), f"extra=[{other!r}]")

    # -- T4: unresolved binding pair --
    def test_t4_unresolved_binding_pair_rejected(self):
        rc = self.make_candidate(candidate_bindings={self.task_id: UNATTESTED})
        self.assert_rejected(self.check(rc["release_candidate_id"]),
                             "resolves to no P18_VERIFICATION_RESULT", repr(self.task_id), UNATTESTED)

    # -- T5: pre-freeze validates a DRAFT RC - the property the circular-dependency fix exists for --
    def test_t5_draft_rc_with_complete_bindings_validates_pre_freeze(self):
        rc = self.complete_candidate()  # DRAFT, explicit real candidate_bindings
        self.assertEqual(nlc.load_release_candidate(self.project, rc["release_candidate_id"])["status"], "DRAFT")
        self.assertEqual(self.check(rc["release_candidate_id"]).outcome, rk.VALIDATED)

    # -- T6: end to end - freeze itself succeeds and reaches FROZEN/V3 + P19 --
    def test_t6_freeze_succeeds_and_reaches_frozen_v3_and_p19(self):
        rc = self.frozen_candidate()
        self.assertEqual(rc["status"], "FROZEN")
        self.assertEqual(rc["candidate_fingerprint_version"], "3")
        from nogap_methodology import status as mstatus
        self.assertEqual(mstatus(self.project)["current_phase"], "P19")

    # -- T7: independent_review_performed=False forbids a ref --
    def test_t7_performed_false_with_ref_rejected(self):
        rc = self.complete_candidate()
        self.edit_p18(lambda r: r["fields"].update(review_evidence_ref="evidence-should-not-be-here"))
        self.assert_rejected(self.check(rc["release_candidate_id"]),
                             "independent_review_performed=False but carries review_evidence_ref")

    # -- T8: independent_review_performed=False with a non-not-attempted result is rejected --
    def test_t8_performed_false_wrong_result_rejected(self):
        rc = self.complete_candidate()
        self.edit_p18(lambda r: r["fields"].update(independent_review_result="passed"))
        self.assert_rejected(self.check(rc["release_candidate_id"]),
                             "independent_review_performed=False but independent_review_result='passed'")

    # -- T9: independent_review_performed missing/non-boolean fails closed --
    def test_t9_performed_not_boolean_rejected(self):
        rc = self.complete_candidate()
        self.edit_p18(lambda r: r["fields"].update(independent_review_performed=None))
        self.assert_rejected(self.check(rc["release_candidate_id"]),
                             "independent_review_performed is not a boolean")

    # -- T10: staleness (via verification_staleness()) fails closed --
    def test_t10_stale_p18_rejected(self):
        rc = self.complete_candidate()
        self.edit_p18(lambda r: r["fields"].update(patch_hash="sha256:" + "ee" * 32))
        self.assert_rejected(self.check(rc["release_candidate_id"]), "is stale", "patch hash changed")


class ReviewVerdictResolverStandardProfile(StandardProfileLifecycleFixture):
    """STANDARD profile with a REAL independent-review PASS: the genuine evidence-backed
    path, where independent_review_performed=True and review_evidence_ref is mandatory."""

    def check(self, rc_id: str) -> rk.Verdict:
        (verdict,) = rk.check_required_kinds(self.project, ["REVIEW_VERDICT"], [rc_id])
        return verdict

    def assert_rejected(self, verdict: rk.Verdict, *fragments: str) -> None:
        self.assertEqual(verdict.outcome, rk.REJECTED, str(verdict))
        for fragment in fragments:
            self.assertIn(fragment, verdict.detail)

    def edit_json(self, path: Path, fn) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        fn(data)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def edit_p18(self, fn) -> None:
        (p18,) = na.list_artifacts(self.project, artifact_type="P18_VERIFICATION_RESULT")
        self.edit_json(na.artifacts_dir(self.project) / f"{p18['artifact_id']}.json", fn)

    def edit_evidence(self, evidence_id: str, fn) -> None:
        path = (self.project / ".code-loop" / "runtime" / "evidence" / f"{evidence_id}.json")
        self.edit_json(path, fn)

    def review_evidence_id(self) -> str:
        (p18,) = na.list_artifacts(self.project, artifact_type="P18_VERIFICATION_RESULT")
        return p18["fields"]["review_evidence_ref"]

    def complete_candidate(self, **overrides) -> dict:
        overrides.setdefault("candidate_bindings", real_candidate_bindings(self.project, [self.task_id]))
        return self.make_candidate(**overrides)

    # -- T11: genuine evidence-backed PASS validates --
    def test_t11_evidence_backed_pass_validated(self):
        rc = self.complete_candidate()
        self.assertEqual(self.check(rc["release_candidate_id"]).outcome, rk.VALIDATED)

    # -- T12: performed=True but result not a real evidence outcome --
    def test_t12_performed_true_non_evidence_result_rejected(self):
        rc = self.complete_candidate()
        self.edit_p18(lambda r: r["fields"].update(independent_review_result="PENDING"))
        self.assert_rejected(self.check(rc["release_candidate_id"]),
                             "independent_review_performed=True but independent_review_result='PENDING'")

    # -- T13: performed=True but no ref --
    def test_t13_performed_true_no_ref_rejected(self):
        rc = self.complete_candidate()
        self.edit_p18(lambda r: r["fields"].pop("review_evidence_ref"))
        self.assert_rejected(self.check(rc["release_candidate_id"]),
                             "independent_review_performed=True but no review_evidence_ref")

    # -- T14: ref does not resolve in the ledger --
    def test_t14_unresolvable_ref_rejected(self):
        rc = self.complete_candidate()
        self.edit_p18(lambda r: r["fields"].update(review_evidence_ref="evidence-does-not-exist"))
        self.assert_rejected(self.check(rc["release_candidate_id"]), "does not resolve in the evidence ledger")

    # -- T15: wrong evidence_class --
    def test_t15_wrong_evidence_class_rejected(self):
        rc = self.complete_candidate()
        self.edit_evidence(self.review_evidence_id(), lambda e: e.update(evidence_class="deterministic"))
        self.assert_rejected(self.check(rc["release_candidate_id"]),
                             "evidence_class='deterministic', not 'independent_review'")

    # -- T16: wrong binding (task_id/candidate_hash mismatch) --
    def test_t16_wrong_binding_rejected(self):
        rc = self.complete_candidate()
        self.edit_evidence(self.review_evidence_id(), lambda e: e["provenance"].update(candidate_hash="sha256:" + "cc" * 32))
        self.assert_rejected(self.check(rc["release_candidate_id"]), "is not bound to this task/candidate")

    # -- T17: divergence - P18 result vs evidence.status --
    def test_t17_divergence_rejected(self):
        rc = self.complete_candidate()
        self.edit_p18(lambda r: r["fields"].update(independent_review_result="failed"))
        self.assert_rejected(self.check(rc["release_candidate_id"]),
                             "does not equal evidence.status")

    # -- T18: reviewer identity collision (never resolved by preferring either side) --
    def test_t18_identity_collision_rejected(self):
        rc = self.complete_candidate()
        self.edit_p18(lambda r: r["fields"].update(executor_actor_id="agent:claude"))
        self.assert_rejected(self.check(rc["release_candidate_id"]), "is not independent from executor identity")

    # -- T19: malformed evidence record (no provenance at all) --
    def test_t19_malformed_evidence_rejected(self):
        rc = self.complete_candidate()
        self.edit_evidence(self.review_evidence_id(), lambda e: e.update(provenance="nope"))
        self.assert_rejected(self.check(rc["release_candidate_id"]), "has no provenance")


if __name__ == "__main__":
    unittest.main()
