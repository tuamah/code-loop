"""F2b D4: EVIDENCE_BUNDLE resolver (Rev 2.1 section 2.11) and the three-way resolver agreement guard.

Every RC, P11, P15, P18 and evidence record here comes from the real pipeline (LifecycleFixture).
Where a state is unreachable through the real API (non-V3 frozen RC, incomplete bindings on a
frozen RC) or an existing real record needs a different field value (failed status, removed
evidence_class, unbound provenance), the real on-disk record is edited in place, and the test
says so.
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
from test_methodology_lifecycle import LifecycleFixture, make_task_contract  # noqa: E402

UNATTESTED = hashlib.sha256(b"unattested").hexdigest()


class AgreementGuard(unittest.TestCase):
    """T1: contract declaration <-> SEMANTIC_RESOLVERS <-> ENFORCED_KINDS."""

    def test_t1_real_three_way_agreement(self):
        m = nm.load_methodology()
        name = m.phases["P19"].semantic_resolvers["EVIDENCE_BUNDLE"]
        self.assertEqual(rk.SEMANTIC_RESOLVERS[name].kind, "EVIDENCE_BUNDLE")
        self.assertIsInstance(rk.ENFORCED_KINDS["EVIDENCE_BUNDLE"], rk.EvidenceBundle)
        self.assertNotIn("EVIDENCE_BUNDLE", rk.DEFERRED_KINDS)
        self.assertIsNone(rk.semantic_resolver_agreement_problem("EVIDENCE_BUNDLE", name))

    def assert_load_rejected(self, fragment: str) -> None:
        with self.assertRaises(nm.MethodologyValidationError) as ctx:
            nm.load_methodology()
        self.assertIn(fragment, str(ctx.exception))

    def test_t1a_unregistered_name_rejected(self):
        # Clearing the whole registry makes every phase's declared resolver unregistered at
        # once (D5 added P18's REVIEW_VERDICT_RESOLVER beside P19's own) - load-time
        # validation fails on whichever phase it reaches first, so the assertion is on the
        # generic rejection shape, not a specific phase's resolver name.
        with mock.patch.dict(rk.SEMANTIC_RESOLVERS, clear=True):
            self.assert_load_rejected("references unknown resolver")
            self.assertIn("unknown resolver",
                          rk.semantic_resolver_agreement_problem("EVIDENCE_BUNDLE", "EVIDENCE_BUNDLE_RESOLVER"))

    def test_t1b_registered_for_wrong_kind_rejected(self):
        wrong = {"EVIDENCE_BUNDLE_RESOLVER": rk.SemanticResolverSpec(kind="RELEASE_CANDIDATE")}
        with mock.patch.dict(rk.SEMANTIC_RESOLVERS, wrong):
            self.assert_load_rejected("is registered for kind 'RELEASE_CANDIDATE', not 'EVIDENCE_BUNDLE'")

    def test_t1c_kind_not_enforced_rejected(self):
        with mock.patch.dict(rk.ENFORCED_KINDS):
            del rk.ENFORCED_KINDS["EVIDENCE_BUNDLE"]
            self.assert_load_rejected("has no implementation in ENFORCED_KINDS")


class Structural(unittest.TestCase):
    """T-STRUCT: no dynamic import / getattr-by-string / reflection in the new code."""

    BANNED = {"getattr", "__import__", "import_module", "importlib", "eval", "exec",
              "globals", "locals", "vars", "setattr", "hasattr"}

    def test_struct_no_dynamic_resolution(self):
        sources = [inspect.getsource(f) for f in (
            rk._check_evidence_bundle_kind, rk.semantic_resolver_agreement_problem,
            rk.check_required_kinds, nm._validate_semantic_resolvers)]
        tree = ast.parse((ROOT / "scripts" / "nogap_required_kinds.py").read_text(encoding="utf-8"))
        registry = [n for n in tree.body if isinstance(n, ast.AnnAssign)
                    and getattr(n.target, "id", None) == "SEMANTIC_RESOLVERS"]
        self.assertEqual(len(registry), 1)
        literal = registry[0].value
        self.assertIsInstance(literal, ast.Dict)
        for key, value in zip(literal.keys, literal.values):
            self.assertIsInstance(key, ast.Constant)
            self.assertIsInstance(value, ast.Call)
            self.assertEqual(value.func.id, "SemanticResolverSpec")
            self.assertTrue(all(isinstance(k.value, ast.Constant) for k in value.keywords))
        sources.append(ast.unparse(registry[0]))
        for src in sources:
            for node in ast.walk(ast.parse(textwrap.dedent(src))):
                self.assertNotIsInstance(node, ast.Import)
                if isinstance(node, ast.ImportFrom):
                    self.assertTrue(node.module.startswith("nogap_"), node.module)
                if isinstance(node, ast.Name):
                    self.assertNotIn(node.id, self.BANNED)
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, self.BANNED)


class EvidenceBundleResolver(LifecycleFixture):
    """T2-T13 on the real pipeline: P11 requires {execution}, P15 (via P18) requires {effect_scope}."""

    def setUp(self) -> None:
        super().setUp()
        evidence_dir = self.project / ".code-loop" / "runtime" / "evidence"
        (self.verify_id,) = [p.stem for p in evidence_dir.glob("evidence-verify-*.json")]
        self.evidence_dir = evidence_dir

    # -- helpers --
    def check(self, rc_id: str) -> rk.Verdict:
        (verdict,) = rk.check_required_kinds(self.project, ["EVIDENCE_BUNDLE"], [rc_id])
        return verdict

    def complete_rc(self, **overrides) -> str:
        overrides.setdefault("evidence_refs", [self.exec_evidence_id, self.verify_id])
        return self.frozen_candidate(**overrides)["release_candidate_id"]

    def edit_json(self, path: Path, fn) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        fn(data)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def edit_rc(self, rc_id: str, fn) -> None:
        self.edit_json(nlc._kind_dir(self.project, "release_candidates") / f"{rc_id}.json", fn)

    def edit_evidence(self, evidence_id: str, fn) -> None:
        self.edit_json(self.evidence_dir / f"{evidence_id}.json", fn)

    def assert_rejected(self, verdict: rk.Verdict, *fragments: str) -> None:
        self.assertEqual(verdict.outcome, rk.REJECTED, str(verdict))
        for fragment in fragments:
            self.assertIn(fragment, verdict.detail)

    # -- tests --
    def test_t2_complete_frozen_v3_validated(self):
        verdict = self.check(self.complete_rc())
        self.assertEqual(verdict.outcome, rk.VALIDATED, str(verdict))

    def test_t2b_no_rc_among_refs_rejected(self):
        (verdict,) = rk.check_required_kinds(self.project, ["EVIDENCE_BUNDLE"], ["RC-999"])
        self.assert_rejected(verdict, "no resolvable release candidate")

    def test_t3_draft_rc_rejected(self):
        rc = self.make_candidate(evidence_refs=[self.exec_evidence_id, self.verify_id],
                                 candidate_bindings={self.task_id: self.real_hash()})
        self.assert_rejected(self.check(rc["release_candidate_id"]), "is not FROZEN", "'DRAFT'")

    def test_t4_non_v3_frozen_rejected(self):
        # Unreachable via real freeze (freeze always emits V3): the real frozen record is edited.
        rc_id = self.complete_rc()
        for version in ("1", "2"):
            with self.subTest(version=version):
                self.edit_rc(rc_id, lambda r: r.update(candidate_fingerprint_version=version))
                self.assert_rejected(self.check(rc_id), f"candidate_fingerprint_version={version!r}")

    def test_t5_incomplete_candidate_bindings_rejected(self):
        # Unreachable via real freeze (freeze enforces exact coverage): real record edited.
        rc_id = self.complete_rc()
        self.edit_rc(rc_id, lambda r: r.update(candidate_bindings={}))
        self.assert_rejected(self.check(rc_id), f"missing=[{self.task_id!r}]")
        other = make_task_contract(self.project, self.chain)["fields"]["task_id"]
        self.edit_rc(rc_id, lambda r: r.update(
            candidate_bindings={self.task_id: self.real_hash(), other: self.real_hash()}))
        self.assert_rejected(self.check(rc_id), f"extra=[{other!r}]")

    def test_t6_unresolved_binding_pair_rejected(self):
        rc_id = self.complete_rc()
        self.edit_rc(rc_id, lambda r: r.update(candidate_bindings={self.task_id: UNATTESTED}))
        self.assert_rejected(self.check(rc_id), "resolves to no P18_VERIFICATION_RESULT",
                             repr(self.task_id), UNATTESTED)

    def test_t7_legacy_record_covers_nothing(self):
        rc_id = self.complete_rc()
        self.edit_evidence(self.verify_id, lambda e: e.pop("evidence_class"))
        self.assert_rejected(self.check(rc_id), "uncovered", "['effect_scope']")

    def test_t8_duplicate_refs_add_no_coverage(self):
        rc_id = self.complete_rc(evidence_refs=[self.exec_evidence_id, self.exec_evidence_id])
        self.assert_rejected(self.check(rc_id), "['effect_scope']")
        rc_id = self.complete_rc(candidate_ref="rc-dup2", evidence_refs=[self.verify_id, self.verify_id])
        self.assert_rejected(self.check(rc_id), "['execution']")

    def test_t9_zero_valid_p11_fails_closed(self):
        rc_id = self.complete_rc()
        for plan in na.list_artifacts(self.project, artifact_type="P11_GATE_PLAN"):
            (na.artifacts_dir(self.project) / f"{plan['artifact_id']}.json").unlink()
        self.assert_rejected(self.check(rc_id), "no valid P11_GATE_PLAN")

    def test_t10_non_terminal_p18_still_resolves(self):
        rc_id = self.complete_rc()
        self._set_real_p18_status("VERIFICATION_FAILED")
        (p18,) = na.list_artifacts(self.project, artifact_type="P18_VERIFICATION_RESULT")
        self.assertEqual(p18["status"], "VERIFICATION_FAILED")
        self.assertEqual(self.check(rc_id).outcome, rk.VALIDATED)

    def test_t11_failed_evidence_status_still_covers(self):
        rc_id = self.complete_rc()
        self.edit_evidence(self.exec_evidence_id, lambda e: e.update(status="failed"))
        self.edit_evidence(self.verify_id, lambda e: e.update(status="blocked"))
        self.assertEqual(self.check(rc_id).outcome, rk.VALIDATED)

    def test_t12_unbound_evidence_covers_nothing(self):
        other = make_task_contract(self.project, self.chain)["fields"]["task_id"]
        cases = {
            "other_task": lambda e: e["provenance"].update(task_id=other),
            "no_candidate_hash": lambda e: e["provenance"].pop("candidate_hash"),
        }
        for name, edit in cases.items():
            with self.subTest(case=name):
                rc_id = self.complete_rc(candidate_ref=f"rc-{name}")
                original = (self.evidence_dir / f"{self.verify_id}.json").read_text(encoding="utf-8")
                self.edit_evidence(self.verify_id, edit)
                try:
                    self.assert_rejected(self.check(rc_id), "['effect_scope']")
                finally:
                    (self.evidence_dir / f"{self.verify_id}.json").write_text(original, encoding="utf-8")

    def test_t13_unresolvable_or_malformed_frozen_ref_rejected(self):
        rc_id = self.complete_rc()
        self.edit_evidence(self.verify_id, lambda e: e.update(provenance="nope"))
        self.assert_rejected(self.check(rc_id), f"{self.verify_id!r} is a malformed evidence record")
        (self.evidence_dir / f"{self.verify_id}.json").unlink()
        self.assert_rejected(self.check(rc_id), f"{self.verify_id!r} does not resolve")

    def test_frozen_snapshot_not_live_refs(self):
        rc_id = self.complete_rc()
        self.edit_rc(rc_id, lambda r: r.update(evidence_refs=[]))
        self.assertEqual(self.check(rc_id).outcome, rk.VALIDATED)
        self.edit_rc(rc_id, lambda r: r["freeze_record"].update(evidence_refs=[self.exec_evidence_id]))
        self.assert_rejected(self.check(rc_id), "['effect_scope']")

    def real_hash(self) -> str:
        (p18,) = na.list_artifacts(self.project, artifact_type="P18_VERIFICATION_RESULT")
        return p18["fields"]["candidate_hash"]


if __name__ == "__main__":
    unittest.main()
