"""F3-D1: 4 SMALL_BINDING resolvers (P6, P7, P9, P19) - docs/f3-a-exit-check-registry-contract.
md's F3-D-PRE survey, ACCEPTED WITH REPAIR. Each predicate is newly designed here (no
pre-existing required_kind covers it), built only from real, already-declared fields.
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

import nogap_artifacts as na                                              # noqa: E402
import nogap_exit_registry as er                                          # noqa: E402
import nogap_methodology as nm                                            # noqa: E402
from test_methodology_build import build_p0_p11_chain                     # noqa: E402
from test_methodology_lifecycle import LifecycleFixture                   # noqa: E402


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


class RegistryScope(unittest.TestCase):
    def test_exactly_27_rows_implemented_23_unique_resolvers(self):
        registry = er.load_registry()
        implemented = {k for k, v in registry.items() if v.implementation_status == er.IMPLEMENTED}
        self.assertEqual(len(implemented), 27)
        self.assertEqual(len(er.RESOLVERS), 23)

    def test_four_rows_are_small_binding_implemented(self):
        registry = er.load_registry()
        for key in (
            ("P6", "requirements_have_stable_ids_req_prefix"),
            ("P7", "execution_authority_and_acceptance_authority_are_distinct_identities_or_roles"),
            ("P9", "governance_defines_acceptance_authority"),
            ("P19", "known_limitations_recorded"),
        ):
            entry = registry[key]
            self.assertEqual(entry.classification, er.SMALL_BINDING, key)
            self.assertEqual(entry.implementation_status, er.IMPLEMENTED, key)
            # F3-A/F3-D micro-repair: SMALL_BINDING rows never carry planned_resolver_id -
            # that field names a mechanism known at F3-A freeze, DC-only. A SB row's
            # resolver_id is a freshly-designed F3-D binding, never a "planned" precursor.
            self.assertIsNotNone(entry.resolver_id, key)
            self.assertIsNone(entry.planned_resolver_id, key)
            self.assertIsNone(entry.unimplemented_reason, key)
            self.assertIsNone(entry.blocked_by, key)

    def test_manifest_resolver_id_with_missing_symbol_fails_closed(self):
        # REPAIR: a MANIFEST resolver_id on a SMALL_BINDING row means F3-D declared that row
        # bound. If the resolver symbol is missing from RESOLVERS, load_registry() must raise -
        # never silently fall back to UNIMPLEMENTED/NOT_BOUND.
        bound_id = "artifact_field:P6_REQUIREMENT.requirement_id_prefix"
        real_resolver = er.RESOLVERS.pop(bound_id)
        try:
            with self.assertRaises(er.RegistryLoadError):
                er.load_registry()
        finally:
            er.RESOLVERS[bound_id] = real_resolver

    def test_other_nine_small_binding_rows_stay_unimplemented(self):
        registry = er.load_registry()
        still_pending = [
            ("P14", "execution_evidence_never_self_marked_authoritative"),
            ("P15", "verification_ladder_depth_matches_active_profile_risk_and_claim_strength"),
            ("P16", "required_commands_and_forbidden_paths_checked"),
            ("P17", "result_reproduced_independently_of_original_worktree"),
            ("P18", "reviewer_identity_distinct_from_executor_identity"),
            ("P20", "rollback_plan_exists"),
            ("P20", "deployment_decision_recorded"),
            ("P21", "incidents_preserve_evidence_before_repair"),
            ("P22", "improvement_proposal_cites_evidence"),
        ]
        for key in still_pending:
            entry = registry[key]
            self.assertEqual(entry.classification, er.SMALL_BINDING, key)
            self.assertEqual(entry.implementation_status, er.UNIMPLEMENTED, key)
            self.assertEqual(entry.unimplemented_reason, er.NOT_BOUND, key)
            self.assertIsNone(entry.resolver_id, key)


class P6StableIdPrefix(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)
        self.chain = build_p0_p11_chain(self.project)
        self.registry = er.load_registry()

    def _entry(self):
        return self.registry[("P6", "requirements_have_stable_ids_req_prefix")]

    def _ctx(self):
        return er.ResolverContext(project=self.project, phase_id="P6")

    def test_positive(self):
        outcome = er.resolve(self._entry(), self._ctx())
        self.assertEqual(outcome.status, er.PASS, outcome.detail)

    def test_determinism_and_purity(self):
        ctx = self._ctx()
        first = er.resolve(self._entry(), ctx)
        second = er.resolve(self._entry(), ctx)
        self.assertEqual(first, second)
        before = _project_hash(self.project)
        er.resolve(self._entry(), ctx)
        self.assertEqual(before, _project_hash(self.project))

    def test_bad_prefix_fails(self):
        artifact_id = self.chain["P6"]["artifact_id"]
        path = na.artifacts_dir(self.project) / f"{artifact_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["fields"]["requirement_id"] = "TASK-001"
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        outcome = er.resolve(self._entry(), self._ctx())
        self.assertEqual(outcome.status, er.FAIL)
        self.assertIn("TASK-001", outcome.detail)

    def test_no_requirement_recorded_fails(self):
        # A project that never created any P6_REQUIREMENT at all.
        project = _new_project(tempfile.mkdtemp())
        registry = er.load_registry()
        outcome = er.resolve(registry[("P6", "requirements_have_stable_ids_req_prefix")],
                             er.ResolverContext(project=project, phase_id="P6"))
        self.assertEqual(outcome.status, er.FAIL)
        self.assertIn("no valid", outcome.detail)


class P7AuthorityDisjointness(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)
        self.chain = build_p0_p11_chain(self.project)
        self.registry = er.load_registry()

    def _entry(self):
        return self.registry[("P7", "execution_authority_and_acceptance_authority_are_distinct_identities_or_roles")]

    def _ctx(self):
        return er.ResolverContext(project=self.project, phase_id="P7")

    def test_positive(self):
        outcome = er.resolve(self._entry(), self._ctx())
        self.assertEqual(outcome.status, er.PASS, outcome.detail)

    def test_determinism_and_purity(self):
        ctx = self._ctx()
        self.assertEqual(er.resolve(self._entry(), ctx), er.resolve(self._entry(), ctx))
        before = _project_hash(self.project)
        er.resolve(self._entry(), ctx)
        self.assertEqual(before, _project_hash(self.project))

    def test_overlapping_authorities_fail(self):
        artifact_id = self.chain["P7"]["artifact_id"]
        path = na.artifacts_dir(self.project) / f"{artifact_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["fields"]["execution_authorities"] = ["agent", "shared-role"]
        record["fields"]["acceptance_authorities"] = ["human", "shared-role"]
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        outcome = er.resolve(self._entry(), self._ctx())
        self.assertEqual(outcome.status, er.FAIL)
        self.assertIn("shared-role", outcome.detail)


class P9AcceptanceAuthority(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)
        self.chain = build_p0_p11_chain(self.project)
        self.registry = er.load_registry()

    def _entry(self):
        return self.registry[("P9", "governance_defines_acceptance_authority")]

    def _ctx(self):
        return er.ResolverContext(project=self.project, phase_id="P9")

    def test_positive(self):
        outcome = er.resolve(self._entry(), self._ctx())
        self.assertEqual(outcome.status, er.PASS, outcome.detail)

    def test_determinism_and_purity(self):
        ctx = self._ctx()
        self.assertEqual(er.resolve(self._entry(), ctx), er.resolve(self._entry(), ctx))
        before = _project_hash(self.project)
        er.resolve(self._entry(), ctx)
        self.assertEqual(before, _project_hash(self.project))

    def test_missing_acceptance_key_fails(self):
        artifact_id = self.chain["P9"]["artifact_id"]
        path = na.artifacts_dir(self.project) / f"{artifact_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["fields"]["authority_assignments"] = {"execution": "agent:codex"}
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        outcome = er.resolve(self._entry(), self._ctx())
        self.assertEqual(outcome.status, er.FAIL)

    def test_empty_acceptance_value_fails_not_just_key_presence(self):
        # The whole point of the F3-D-PRE ruling: presence of the key alone must not pass.
        artifact_id = self.chain["P9"]["artifact_id"]
        path = na.artifacts_dir(self.project) / f"{artifact_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["fields"]["authority_assignments"] = {"acceptance": "  "}
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        outcome = er.resolve(self._entry(), self._ctx())
        self.assertEqual(outcome.status, er.FAIL)
        self.assertIn("carries no 'acceptance'", outcome.detail)


class P19KnownLimitations(LifecycleFixture):
    def _entry(self):
        return er.load_registry()[("P19", "known_limitations_recorded")]

    def _ctx(self):
        return er.ResolverContext(project=self.project, phase_id="P19")

    def test_no_frozen_rc_yet_fails(self):
        outcome = er.resolve(self._entry(), self._ctx())
        self.assertEqual(outcome.status, er.FAIL)
        self.assertEqual(outcome.detail, "no FROZEN release candidate exists for this project")

    def test_positive_with_known_limitations(self):
        self.frozen_candidate(known_limitations=["minor polish deferred"])
        outcome = er.resolve(self._entry(), self._ctx())
        self.assertEqual(outcome.status, er.PASS, outcome.detail)
        self.assertIn("minor polish deferred", outcome.detail)

    def test_empty_known_limitations_fails_not_just_key_presence(self):
        self.frozen_candidate(known_limitations=[])
        outcome = er.resolve(self._entry(), self._ctx())
        self.assertEqual(outcome.status, er.FAIL)
        self.assertIn("no known_limitations", outcome.detail)

    def test_determinism_and_purity(self):
        self.frozen_candidate(known_limitations=["x"])
        ctx = self._ctx()
        entry = self._entry()
        self.assertEqual(er.resolve(entry, ctx), er.resolve(entry, ctx))
        before = _project_hash(self.project)
        er.resolve(entry, ctx)
        self.assertEqual(before, _project_hash(self.project))


if __name__ == "__main__":
    unittest.main()
