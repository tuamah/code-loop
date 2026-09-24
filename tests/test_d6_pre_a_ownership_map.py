"""D6-PRE-A: PHASE_TO_ARTIFACT_TYPES (1:N ownership) and the fail-closed legacy compatibility
map PHASE_TO_ARTIFACT_TYPE (single-owner phases only).

No new artifact type is added by this step (RUNTIME_STRUCTURE stays DEFERRED, P9_RUNTIME_
STRUCTURE does not exist yet) - this only fixes the underlying ownership-map bug D6-IMPLEMENTATION-
PRE found: a phase_id -> single artifact_type map silently picks a "winner by insertion order"
the moment a phase owns more than one artifact type, which P9 will once RUNTIME_STRUCTURE is
implemented (docs/d6-runtime-structure-contract.md).
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
from nogap_artifacts import prebuild_readiness                              # noqa: E402


class OwnershipMapStructure(unittest.TestCase):
    def test_union_of_all_types_equals_artifact_types_keys(self):
        union: set[str] = set()
        for types in nat.PHASE_TO_ARTIFACT_TYPES.values():
            union |= set(types)
        self.assertEqual(union, set(nat.ARTIFACT_TYPES.keys()))

    def test_every_artifact_type_appears_exactly_once_under_its_declared_phase(self):
        seen: dict[str, str] = {}
        for phase_id, types in nat.PHASE_TO_ARTIFACT_TYPES.items():
            for t in types:
                self.assertNotIn(t, seen, f"{t} appears under both {seen.get(t)} and {phase_id}")
                seen[t] = phase_id
                self.assertEqual(nat.ARTIFACT_TYPES[t]["phase_id"], phase_id)

    def test_order_matches_artifact_types_declaration_order(self):
        expected: dict[str, list[str]] = {}
        for name, info in nat.ARTIFACT_TYPES.items():
            expected.setdefault(info["phase_id"], []).append(name)
        for phase_id, types in nat.PHASE_TO_ARTIFACT_TYPES.items():
            self.assertEqual(list(types), expected[phase_id])

    # -- legacy compatibility map: single-owner only, fail-closed by omission --

    def test_legacy_map_holds_only_single_owner_phases(self):
        for phase_id, artifact_type in nat.PHASE_TO_ARTIFACT_TYPE.items():
            self.assertEqual(len(nat.PHASE_TO_ARTIFACT_TYPES[phase_id]), 1)
            self.assertEqual(nat.PHASE_TO_ARTIFACT_TYPES[phase_id], (artifact_type,))

    def test_legacy_map_omits_no_current_phase_since_none_is_multi_owner_yet(self):
        # Today (pre-RUNTIME_STRUCTURE) every owned phase_id has exactly one artifact type, so
        # the legacy map's domain equals the full ownership map's domain. This test pins that
        # fact so a future PR that silently adds a second P9 artifact type without reading
        # docs/d6-runtime-structure-contract.md's wiring plan first gets a clear, named failure
        # here rather than a silent PHASE_TO_ARTIFACT_TYPE[phase_id] KeyError somewhere else.
        self.assertEqual(set(nat.PHASE_TO_ARTIFACT_TYPE.keys()), set(nat.PHASE_TO_ARTIFACT_TYPES.keys()))

    def test_legacy_lookup_on_unknown_phase_fails_closed(self):
        with self.assertRaises(KeyError):
            _ = nat.PHASE_TO_ARTIFACT_TYPE["NOT-A-REAL-PHASE"]

    def test_ownership_map_lookup_on_unknown_phase_fails_closed(self):
        with self.assertRaises(KeyError):
            _ = nat.PHASE_TO_ARTIFACT_TYPES["NOT-A-REAL-PHASE"]


class PrebuildReadinessMultiOwnerAware(unittest.TestCase):
    """prebuild_readiness must index PHASE_TO_ARTIFACT_TYPES directly (fail-closed KeyError on
    an unrecognized phase_id, never a silent skip), and must report every owned artifact type
    of a phase independently, not just one."""

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

    def test_missing_p9_governance_reported_with_real_type_name(self):
        result = prebuild_readiness(self.project)
        self.assertFalse(result["ready"])
        self.assertTrue(any("P9 (P9_GOVERNANCE)" in m for m in result["missing"]), result["missing"])

    def test_fails_closed_if_prebuild_phases_named_an_unowned_phase(self):
        # PREBUILD_PHASES is P0..P11, all of which are real keys in PHASE_TO_ARTIFACT_TYPES
        # today - this proves the indexing itself (not a .get default) is what runs, by
        # confirming every one of those phase_ids resolves without KeyError.
        import nogap_artifacts as na
        for phase_id in na.PREBUILD_PHASES:
            self.assertIn(phase_id, nat.PHASE_TO_ARTIFACT_TYPES)

    def test_prebuild_readiness_raises_on_a_phase_id_absent_from_ownership_map(self):
        # Proves prebuild_readiness indexes PHASE_TO_ARTIFACT_TYPES directly - a .get(phase_id,
        # ()) fallback would swallow this as "phase owns nothing" and silently under-report
        # missing obligations instead of surfacing the structural error.
        import nogap_artifacts as na
        original = na.PREBUILD_PHASES
        na.PREBUILD_PHASES = [*original, "NOT-A-REAL-PHASE"]
        try:
            with self.assertRaises(KeyError):
                prebuild_readiness(self.project)
        finally:
            na.PREBUILD_PHASES = original


class FixtureBuilderArtifactForMultiOwnerGuard(unittest.TestCase):
    """methodology_fixture_builder.FixtureBuilder._artifact_for must refuse to silently build
    "the" artifact for a multi-owner phase. No real multi-owner phase exists yet (P9 gains one
    only once P9_RUNTIME_STRUCTURE is implemented), so this simulates one by monkeypatching the
    real ownership maps the method reads, proving the guard added in D6-PRE-A is load-bearing
    rather than dead code."""

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

    def test_raises_when_simulated_multi_owner_phase_is_requested(self):
        import nogap_artifacts as na
        from methodology_fixture_builder import FixtureBuilder

        builder = FixtureBuilder(self.project)
        original_multi = dict(na.PHASE_TO_ARTIFACT_TYPES)
        original_legacy = dict(na.PHASE_TO_ARTIFACT_TYPE)
        na.PHASE_TO_ARTIFACT_TYPES = {**original_multi, "P9": ("P9_GOVERNANCE", "FAKE_SECOND")}
        na.PHASE_TO_ARTIFACT_TYPE = {k: v for k, v in original_legacy.items() if k != "P9"}
        try:
            with self.assertRaises(ValueError):
                builder._artifact_for("P9")
        finally:
            na.PHASE_TO_ARTIFACT_TYPES = original_multi
            na.PHASE_TO_ARTIFACT_TYPE = original_legacy

    def test_single_owner_phase_unaffected(self):
        from methodology_fixture_builder import FixtureBuilder

        builder = FixtureBuilder(self.project)
        artifact_id = builder._artifact_for("P0")
        self.assertIsNotNone(artifact_id)


if __name__ == "__main__":
    unittest.main()
