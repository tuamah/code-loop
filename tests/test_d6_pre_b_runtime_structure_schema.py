"""D6-PRE-B: schema/validation primitives for P9_RUNTIME_STRUCTURE (Rev 3 contract,
docs/d6-runtime-structure-contract.md). Schema-level only - no RUNTIME_STRUCTURE required_kinds
resolver exists yet; the kind stays in DEFERRED_KINDS. These tests exercise nogap_artifacts.
validate_record/create_artifact directly, the same path every other artifact type uses.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import nogap_artifact_types as nat                                          # noqa: E402
import nogap_methodology as nm                                              # noqa: E402
import nogap_required_kinds as rk                                           # noqa: E402
from nogap_artifacts import create_artifact, validate_record                # noqa: E402

PLANES = ("CONTROL_DECISION", "EXECUTION", "TOOL_CAPABILITY",
          "VERIFICATION_EVIDENCE", "STATE_EVENT", "OBSERVABILITY")


def _all_documented_only() -> dict:
    return {p: "DOCUMENTED_ONLY" for p in PLANES}


def minimal_fields(**overrides) -> dict:
    fields = {
        "components": [], "boundaries": [],
        "plane_status": _all_documented_only(),
        "runtime_structure_version": "1",
    }
    fields.update(overrides)
    return fields


class RuntimeStructureFixtureBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.project = Path(self.dir.name)
        import subprocess
        for args in (["init", "-q"], ["config", "user.email", "t@t.com"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git", *args], cwd=self.project, check=True, capture_output=True)
        (self.project / "R.md").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "add", "R.md"], cwd=self.project, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=self.project, check=True,
                       capture_output=True)
        nm.init_project(self.project, "research", "low", "low", actor="test")

    def record_for(self, fields: dict) -> dict:
        definition = nm.load_methodology()
        return {
            "artifact_type": "P9_RUNTIME_STRUCTURE",
            "phase_id": "P9",
            "methodology_version": definition.version,
            "fields": fields,
        }

    def problems_for(self, fields: dict) -> list[str]:
        return validate_record(self.project, self.record_for(fields))


class OwnershipAndMapping(RuntimeStructureFixtureBase):
    def test_p9_runtime_structure_registered_under_p9(self):
        self.assertEqual(nat.ARTIFACT_TYPES["P9_RUNTIME_STRUCTURE"]["phase_id"], "P9")
        self.assertEqual(
            nat.PHASE_TO_ARTIFACT_TYPES["P9"], ("P9_GOVERNANCE", "P9_RUNTIME_STRUCTURE"))
        self.assertNotIn("P9", nat.PHASE_TO_ARTIFACT_TYPE)  # now genuinely multi-owner

    def test_runtime_structure_still_deferred(self):
        self.assertIn("RUNTIME_STRUCTURE", rk.DEFERRED_KINDS)
        self.assertNotIn("RUNTIME_STRUCTURE", rk.ENFORCED_KINDS)

    def test_partition_guard_unaffected(self):
        declared = rk.declared_required_kinds()
        enforced = set(rk.ENFORCED_KINDS)
        deferred = set(rk.DEFERRED_KINDS)
        self.assertEqual(declared - (enforced | deferred), set())
        self.assertEqual((enforced | deferred) - declared, set())
        self.assertEqual(len(enforced), 34)
        self.assertEqual(len(deferred), 3)


class MinimalValidRecord(RuntimeStructureFixtureBase):
    def test_minimal_record_is_valid(self):
        self.assertEqual(self.problems_for(minimal_fields()), [])

    def test_minimal_record_creatable_through_create_artifact(self):
        record = create_artifact(self.project, "P9_RUNTIME_STRUCTURE", minimal_fields(),
                                 actor="test")
        self.assertEqual(record["artifact_type"], "P9_RUNTIME_STRUCTURE")


class TopLevelShape(RuntimeStructureFixtureBase):
    def test_missing_components_field_invalid(self):
        fields = minimal_fields()
        del fields["components"]
        self.assertTrue(self.problems_for(fields))

    def test_missing_boundaries_field_invalid(self):
        fields = minimal_fields()
        del fields["boundaries"]
        self.assertTrue(self.problems_for(fields))

    def test_missing_plane_status_field_invalid(self):
        fields = minimal_fields()
        del fields["plane_status"]
        self.assertTrue(self.problems_for(fields))

    def test_missing_version_field_invalid(self):
        fields = minimal_fields()
        del fields["runtime_structure_version"]
        self.assertTrue(self.problems_for(fields))

    def test_version_outside_closed_set_invalid(self):
        problems = self.problems_for(minimal_fields(runtime_structure_version="2"))
        self.assertTrue(any("runtime_structure_version" in p for p in problems))

    def test_components_not_a_list_invalid(self):
        problems = self.problems_for(minimal_fields(components={"not": "a list"}))
        self.assertTrue(any("components must be a list" in p for p in problems))

    def test_plane_status_not_a_dict_invalid(self):
        problems = self.problems_for(minimal_fields(plane_status=["not", "a", "dict"]))
        self.assertTrue(any("plane_status must be an object" in p for p in problems))

    def test_plane_status_missing_a_plane_invalid(self):
        bad = _all_documented_only()
        del bad["OBSERVABILITY"]
        problems = self.problems_for(minimal_fields(plane_status=bad))
        self.assertTrue(any("plane_status keys must be exactly" in p for p in problems))

    def test_plane_status_extra_key_invalid(self):
        bad = {**_all_documented_only(), "NOT_A_PLANE": "DOCUMENTED_ONLY"}
        problems = self.problems_for(minimal_fields(plane_status=bad))
        self.assertTrue(any("plane_status keys must be exactly" in p for p in problems))

    def test_plane_status_bad_value_invalid(self):
        bad = {**_all_documented_only(), "OBSERVABILITY": "SORT_OF"}
        problems = self.problems_for(minimal_fields(plane_status=bad))
        self.assertTrue(any("plane_status values must be one of" in p for p in problems))


class ComponentValidation(RuntimeStructureFixtureBase):
    def _component(self, **overrides) -> dict:
        c = {
            "component_id": "c1", "plane": "EXECUTION",
            "implementation_ref": "nogap_execution", "authority_roles": ["execution"],
        }
        c.update(overrides)
        return c

    def test_valid_component_backing_enforced_plane(self):
        plane_status = {**_all_documented_only(), "EXECUTION": "ENFORCED"}
        problems = self.problems_for(minimal_fields(
            components=[self._component()], plane_status=plane_status))
        self.assertEqual(problems, [])

    def test_duplicate_component_id_invalid(self):
        plane_status = {**_all_documented_only(), "EXECUTION": "ENFORCED"}
        problems = self.problems_for(minimal_fields(
            components=[self._component(), self._component(component_id="c1")],
            plane_status=plane_status))
        self.assertTrue(any("duplicate component_id" in p for p in problems))

    def test_unresolvable_implementation_ref_invalid(self):
        problems = self.problems_for(minimal_fields(
            components=[self._component(implementation_ref="not_a_real_module_xyz")],
            plane_status={**_all_documented_only(), "EXECUTION": "ENFORCED"}))
        self.assertTrue(any("implementation_ref does not resolve" in p for p in problems))

    def test_path_traversal_implementation_ref_rejected(self):
        problems = self.problems_for(minimal_fields(
            components=[self._component(implementation_ref="../../etc/passwd")],
            plane_status={**_all_documented_only(), "EXECUTION": "ENFORCED"}))
        self.assertTrue(any("implementation_ref does not resolve" in p for p in problems))

    def test_absolute_path_implementation_ref_rejected(self):
        problems = self.problems_for(minimal_fields(
            components=[self._component(implementation_ref="/etc/passwd")],
            plane_status={**_all_documented_only(), "EXECUTION": "ENFORCED"}))
        self.assertTrue(any("implementation_ref does not resolve" in p for p in problems))

    def test_repo_relative_path_form_resolves(self):
        problems = self.problems_for(minimal_fields(
            components=[self._component(implementation_ref="scripts/nogap_execution.py")],
            plane_status={**_all_documented_only(), "EXECUTION": "ENFORCED"}))
        self.assertEqual(problems, [])

    def test_unknown_plane_invalid(self):
        problems = self.problems_for(minimal_fields(
            components=[self._component(plane="NOT_A_PLANE")]))
        self.assertTrue(any("plane must be one of" in p for p in problems))

    def test_empty_authority_roles_invalid(self):
        problems = self.problems_for(minimal_fields(
            components=[self._component(authority_roles=[])]))
        self.assertTrue(any("authority_roles must be a non-empty list" in p for p in problems))

    def test_unknown_authority_role_invalid(self):
        problems = self.problems_for(minimal_fields(
            components=[self._component(authority_roles=["overlord"])]))
        self.assertTrue(any("unknown role" in p for p in problems))

    def test_execution_and_acceptance_conflict_invalid(self):
        problems = self.problems_for(minimal_fields(
            components=[self._component(authority_roles=["execution", "acceptance"])]))
        self.assertTrue(any("must not contain both execution and acceptance" in p for p in problems))


class BoundaryValidation(RuntimeStructureFixtureBase):
    def _components(self) -> list[dict]:
        return [
            {"component_id": "c1", "plane": "EXECUTION",
             "implementation_ref": "nogap_execution", "authority_roles": ["execution"]},
            {"component_id": "c2", "plane": "STATE_EVENT",
             "implementation_ref": "nogap_artifacts", "authority_roles": ["tool"]},
        ]

    def _boundary(self, **overrides) -> dict:
        b = {
            "boundary_id": "b1", "source_component_id": "c1", "target_component_id": "c2",
            "boundary_type": "state", "permitted_flows": ["claims_only"],
            "enforcement_status": "DOCUMENTED_ONLY", "enforcement_ref": None,
        }
        b.update(overrides)
        return b

    def _plane_status(self) -> dict:
        return {**_all_documented_only(), "EXECUTION": "ENFORCED", "STATE_EVENT": "ENFORCED"}

    def test_valid_documented_only_boundary(self):
        problems = self.problems_for(minimal_fields(
            components=self._components(), boundaries=[self._boundary()],
            plane_status=self._plane_status()))
        self.assertEqual(problems, [])

    def test_valid_enforced_boundary_with_resolvable_ref(self):
        problems = self.problems_for(minimal_fields(
            components=self._components(),
            boundaries=[self._boundary(enforcement_status="ENFORCED",
                                       enforcement_ref="nogap_verification")],
            plane_status=self._plane_status()))
        self.assertEqual(problems, [])

    def test_enforced_boundary_without_resolvable_ref_invalid(self):
        problems = self.problems_for(minimal_fields(
            components=self._components(),
            boundaries=[self._boundary(enforcement_status="ENFORCED", enforcement_ref=None)],
            plane_status=self._plane_status()))
        self.assertTrue(any("ENFORCED but enforcement_ref does not resolve" in p for p in problems))

    def test_documented_only_boundary_with_non_null_ref_invalid(self):
        problems = self.problems_for(minimal_fields(
            components=self._components(),
            boundaries=[self._boundary(enforcement_status="DOCUMENTED_ONLY",
                                       enforcement_ref="nogap_verification")],
            plane_status=self._plane_status()))
        self.assertTrue(any("DOCUMENTED_ONLY but declares a non-null enforcement_ref" in p for p in problems))

    def test_dangling_source_endpoint_invalid(self):
        problems = self.problems_for(minimal_fields(
            components=self._components(),
            boundaries=[self._boundary(source_component_id="no-such-component")],
            plane_status=self._plane_status()))
        self.assertTrue(any("source_component_id" in p and "does not resolve" in p for p in problems))

    def test_dangling_target_endpoint_invalid(self):
        problems = self.problems_for(minimal_fields(
            components=self._components(),
            boundaries=[self._boundary(target_component_id="no-such-component")],
            plane_status=self._plane_status()))
        self.assertTrue(any("target_component_id" in p and "does not resolve" in p for p in problems))

    def test_duplicate_boundary_id_invalid(self):
        problems = self.problems_for(minimal_fields(
            components=self._components(),
            boundaries=[self._boundary(), self._boundary()],
            plane_status=self._plane_status()))
        self.assertTrue(any("duplicate boundary_id" in p for p in problems))

    def test_unknown_boundary_type_invalid(self):
        problems = self.problems_for(minimal_fields(
            components=self._components(),
            boundaries=[self._boundary(boundary_type="not_a_type")],
            plane_status=self._plane_status()))
        self.assertTrue(any("boundary_type must be one of" in p for p in problems))

    def test_empty_permitted_flows_invalid(self):
        problems = self.problems_for(minimal_fields(
            components=self._components(),
            boundaries=[self._boundary(permitted_flows=[])],
            plane_status=self._plane_status()))
        self.assertTrue(any("permitted_flows must be a non-empty list" in p for p in problems))

    def test_no_boundary_plane_field_accepted(self):
        # Rev 2 REPAIR (kept in Rev 3): boundaries carry no `plane` field at all - a boundary
        # entry with one present is simply ignored (not itself a schema violation - it isn't
        # a declared field the schema reads), proving nothing derives Plane from it.
        problems = self.problems_for(minimal_fields(
            components=self._components(),
            boundaries=[{**self._boundary(), "plane": "OBSERVABILITY"}],
            plane_status=self._plane_status()))
        self.assertEqual(problems, [])


class PlaneCoverageBiconditional(RuntimeStructureFixtureBase):
    def test_enforced_plane_without_backing_component_invalid(self):
        plane_status = {**_all_documented_only(), "EXECUTION": "ENFORCED"}
        problems = self.problems_for(minimal_fields(plane_status=plane_status))
        self.assertTrue(any("ENFORCED but no component declares that plane" in p for p in problems))

    def test_real_component_under_documented_only_plane_invalid(self):
        # Rev 3's new direction: a real, resolvable component contradicts a DOCUMENTED_ONLY
        # declaration for its own Plane.
        component = {"component_id": "c1", "plane": "EXECUTION",
                     "implementation_ref": "nogap_execution", "authority_roles": ["execution"]}
        problems = self.problems_for(minimal_fields(
            components=[component], plane_status=_all_documented_only()))
        self.assertTrue(any("DOCUMENTED_ONLY but a real, resolvable component" in p for p in problems))

    def test_enforced_plane_with_unresolvable_component_still_invalid(self):
        # A component declaring the plane but with a dead implementation_ref does not count as
        # "backing" - both directions of the biconditional key off resolvability, not presence.
        component = {"component_id": "c1", "plane": "EXECUTION",
                     "implementation_ref": "not_a_real_module", "authority_roles": ["execution"]}
        plane_status = {**_all_documented_only(), "EXECUTION": "ENFORCED"}
        problems = self.problems_for(minimal_fields(components=[component], plane_status=plane_status))
        self.assertTrue(any("ENFORCED but no component declares that plane" in p for p in problems))
        self.assertTrue(any("implementation_ref does not resolve" in p for p in problems))


class VerifierIndependenceConditional(RuntimeStructureFixtureBase):
    def _verifier_component(self, **overrides) -> dict:
        c = {"component_id": "verifier", "plane": "VERIFICATION_EVIDENCE",
             "implementation_ref": "nogap_verification", "authority_roles": ["verification"]}
        c.update(overrides)
        return c

    def test_documented_only_verification_evidence_requires_nothing(self):
        # The exact minimal-record case: no verifier component, no violation, because the
        # Plane itself is declared DOCUMENTED_ONLY.
        self.assertEqual(self.problems_for(minimal_fields()), [])

    def test_enforced_verification_evidence_without_verifier_invalid(self):
        plane_status = {**_all_documented_only(), "VERIFICATION_EVIDENCE": "ENFORCED"}
        problems = self.problems_for(minimal_fields(plane_status=plane_status))
        self.assertTrue(any("no component with plane == VERIFICATION_EVIDENCE holds the "
                            "verification authority role" in p for p in problems))

    def test_enforced_verification_evidence_with_valid_verifier_passes(self):
        plane_status = {**_all_documented_only(), "VERIFICATION_EVIDENCE": "ENFORCED"}
        problems = self.problems_for(minimal_fields(
            components=[self._verifier_component()], plane_status=plane_status))
        self.assertEqual(problems, [])

    def test_verifier_with_execution_role_not_independent(self):
        plane_status = {**_all_documented_only(), "VERIFICATION_EVIDENCE": "ENFORCED"}
        problems = self.problems_for(minimal_fields(
            components=[self._verifier_component(authority_roles=["verification", "execution"])],
            plane_status=plane_status))
        self.assertTrue(any("holds both verification and execution" in p for p in problems))

    def test_verifier_with_acceptance_and_no_human_not_independent(self):
        plane_status = {**_all_documented_only(), "VERIFICATION_EVIDENCE": "ENFORCED"}
        problems = self.problems_for(minimal_fields(
            components=[self._verifier_component(authority_roles=["verification", "acceptance"])],
            plane_status=plane_status))
        self.assertTrue(any("collapses independent verification into self-acceptance" in p for p in problems))

    def test_verifier_with_acceptance_and_human_is_allowed(self):
        plane_status = {**_all_documented_only(), "VERIFICATION_EVIDENCE": "ENFORCED"}
        problems = self.problems_for(minimal_fields(
            components=[self._verifier_component(
                authority_roles=["verification", "acceptance", "human"])],
            plane_status=plane_status))
        self.assertEqual(problems, [])


class FixtureBuilderIntegration(RuntimeStructureFixtureBase):
    def test_real_p0_p11_chain_does_not_auto_create_runtime_structure(self):
        # REPAIR (post-D6-PRE-B): ownership != obligation. The real P0-P11 chain builder
        # (test_methodology_build.build_p0_p11_chain) creates P9_GOVERNANCE only - it was
        # never required to create P9_RUNTIME_STRUCTURE, and no longer does (that addition
        # was reverted). P9_RUNTIME_STRUCTURE can still be created and validated directly
        # (proven throughout this file) - it is simply not part of the default chain while
        # RUNTIME_STRUCTURE stays DEFERRED.
        import test_methodology_build as chain
        from nogap_artifacts import list_artifacts

        chain.build_p0_p11_chain(self.project)
        self.assertEqual(list_artifacts(self.project, artifact_type="P9_RUNTIME_STRUCTURE"), [])
        governance = list_artifacts(self.project, artifact_type="P9_GOVERNANCE")
        self.assertEqual(len(governance), 1)

    def test_prebuild_readiness_unaffected_by_runtime_structure_absence(self):
        # The causal test the REPAIR requires: P9 genuinely owns both artifact types, one
        # exists (P9_GOVERNANCE), the other is absent (P9_RUNTIME_STRUCTURE), and
        # RUNTIME_STRUCTURE is still DEFERRED => prebuild_readiness must behave exactly as it
        # did before D6-PRE-B ever existed - no mention of P9_RUNTIME_STRUCTURE anywhere in
        # its reasons, missing or otherwise.
        import test_methodology_build as chain
        from nogap_artifacts import list_artifacts, prebuild_readiness

        chain.build_p0_p11_chain(self.project)
        self.assertEqual(list_artifacts(self.project, artifact_type="P9_RUNTIME_STRUCTURE"), [])
        self.assertIn("RUNTIME_STRUCTURE", rk.DEFERRED_KINDS)

        result = prebuild_readiness(self.project)
        self.assertFalse(any("P9_RUNTIME_STRUCTURE" in reason for reason in result["missing"]),
                         result["missing"])
        # P9_GOVERNANCE, the one enforced-kind-backed type P9 owns, is still required exactly
        # as before - the fix narrows requiredness, it does not remove it.
        self.assertFalse(any("P9 (P9_GOVERNANCE)" in reason for reason in result["missing"]),
                         result["missing"])

    def test_enforced_artifact_types_excludes_deferred_runtime_structure(self):
        from nogap_artifacts import _enforced_artifact_types

        enforced_types = _enforced_artifact_types()
        self.assertIn("P9_GOVERNANCE", enforced_types)
        self.assertNotIn("P9_RUNTIME_STRUCTURE", enforced_types)

    def test_artifact_for_now_raises_on_real_p9(self):
        # No longer simulated (D6-PRE-A's test used a monkeypatch) - P9 is now genuinely
        # multi-owner, so the guard fires on real data.
        from methodology_fixture_builder import FixtureBuilder

        builder = FixtureBuilder(self.project)
        with self.assertRaises(ValueError):
            builder._artifact_for("P9")


if __name__ == "__main__":
    unittest.main()
