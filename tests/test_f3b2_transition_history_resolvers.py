"""F3-B2: the shared `lifecycle:transition_history` resolver for P13 `patch_artifact_recorded`
and P14 `execution_evidence_authority_is_execution` (docs/f3-a-exit-check-registry-contract.md
§4.4.1's frozen lineage rule).

Every transition_history entry here is produced through the REAL `nogap_methodology.transition`
function (via `nogap_build`'s own P12->P13->P14/P13->P12/P14->P13 helpers, or `transition()`
directly for a repair return) - never hand-written into state.json. The resolver itself is
never given a scenario the real engine could not produce.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import nogap_artifacts as na                                              # noqa: E402
import nogap_build as nb                                                  # noqa: E402
import nogap_exit_registry as er                                          # noqa: E402
import nogap_methodology as nm                                            # noqa: E402
from methodology_fixture_builder import freeze_gate_before_build          # noqa: E402
from test_methodology_build import build_p0_p11_chain                     # noqa: E402
from test_methodology_lifecycle import LifecycleFixture, make_task_contract  # noqa: E402


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


def _write_execution_evidence(project: Path, run_id: str, actor: str = "executor",
                              authority: str = "execution", status: str = "passed") -> str:
    """A minimal, real execution-ledger evidence record - the same shape
    write_isolated_run_evidence (nogap.py) writes, trimmed to what `_check_evidence_kind`
    actually inspects (kind, provenance.authority, run_id, provenance.actor_id, status)."""
    evidence_dir = project.resolve() / ".code-loop" / "runtime" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_id = f"evidence-exec-{uuid.uuid4().hex[:12]}"
    evidence = {
        "id": evidence_id,
        "run_id": run_id,
        "kind": "execution",
        "status": status,
        "provenance": {"created_by": actor, "actor_id": actor, "authority": authority},
        "summary": "fixture execution evidence",
    }
    (evidence_dir / f"{evidence_id}.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence_id


def _write_patch(project: Path, name: str | None = None) -> str:
    name = name or f"{uuid.uuid4().hex[:12]}.patch"
    path = project / "artifacts_fixture" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("diff --git a/x b/x\n", encoding="utf-8")
    return str(path.relative_to(project))


def _reach_p13(project: Path, actor: str = "team") -> tuple[dict, str]:
    """P0-P11 chain, then a real P11->P12->P13 drive. Returns (task_contract, plan_evidence_id)."""
    chain = build_p0_p11_chain(project, actor=actor)
    freeze_gate_before_build(project)
    nb.enter_build_phase(project, actor, "P11 obligations satisfied")
    contract = make_task_contract(project, chain, actor=actor)
    plan_evidence_id = nb.record_plan_evidence(project, "run-0001", contract, actor)
    nb.enter_execution_phase(project, actor, "entering isolated execution", contract, plan_evidence_id)
    return contract, plan_evidence_id


def _close_p13(project: Path, actor: str = "team") -> tuple[str, str]:
    """From a real P13 (via _reach_p13), closes it with a real execution evidence id and patch
    ref, exactly as nogap_build.enter_self_check_phase does. Returns (evidence_id, patch_ref)."""
    evidence_id = _write_execution_evidence(project, "run-0001", actor=actor)
    patch_ref = _write_patch(project)
    nb.enter_self_check_phase(project, actor, "execution succeeded", evidence_id, patch_ref)
    return evidence_id, patch_ref


class NoPriorBinding(unittest.TestCase):
    """A project that never reached P13 at all: no P13-attempt binding exists."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)
        build_p0_p11_chain(self.project)  # stops at P11
        self.registry = er.load_registry()

    def test_p13_and_p14_are_missing(self):
        for phase, check in (("P13", "patch_artifact_recorded"),
                             ("P14", "execution_evidence_authority_is_execution")):
            entry = self.registry[(phase, check)]
            outcome = er.resolve(entry, er.ResolverContext(project=self.project, phase_id=phase))
            self.assertEqual(outcome.status, er.FAIL, outcome.detail)
            self.assertIn("no current P13-attempt binding", outcome.detail)


class HappyPath(unittest.TestCase):
    """A real, successful P13->P14 close."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)
        _reach_p13(self.project)
        self.evidence_id, self.patch_ref = _close_p13(self.project)
        self.registry = er.load_registry()

    def test_p13_passes(self):
        entry = self.registry[("P13", "patch_artifact_recorded")]
        outcome = er.resolve(entry, er.ResolverContext(project=self.project, phase_id="P13"))
        self.assertEqual(outcome.status, er.PASS, outcome.detail)
        self.assertIn(self.patch_ref, outcome.detail)

    def test_p14_passes(self):
        entry = self.registry[("P14", "execution_evidence_authority_is_execution")]
        outcome = er.resolve(entry, er.ResolverContext(project=self.project, phase_id="P14"))
        self.assertEqual(outcome.status, er.PASS, outcome.detail)
        self.assertIn(self.evidence_id, outcome.detail)

    def test_determinism_and_purity(self):
        entry = self.registry[("P13", "patch_artifact_recorded")]
        ctx = er.ResolverContext(project=self.project, phase_id="P13")
        first = er.resolve(entry, ctx)
        second = er.resolve(entry, ctx)
        self.assertEqual(first, second)
        before = _project_hash(self.project)
        er.resolve(entry, ctx)
        self.assertEqual(before, _project_hash(self.project))


class FailureNeverCloses(unittest.TestCase):
    """P13 -> P12 (record_build_failure): the failure edge must satisfy neither check."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)
        _reach_p13(self.project)
        evidence_id = _write_execution_evidence(self.project, "run-0001")
        patch_ref = _write_patch(self.project)
        nb.record_build_failure(self.project, "team", "execution failed", evidence_id, patch_ref)
        self.registry = er.load_registry()

    def test_neither_check_satisfied(self):
        for phase, check in (("P13", "patch_artifact_recorded"),
                             ("P14", "execution_evidence_authority_is_execution")):
            entry = self.registry[(phase, check)]
            outcome = er.resolve(entry, er.ResolverContext(project=self.project, phase_id=phase))
            self.assertEqual(outcome.status, er.FAIL, outcome.detail)
            self.assertIn("no current P13-attempt binding", outcome.detail)


class ReEntryInvalidatesStaleBinding(unittest.TestCase):
    """The scenario the whole lineage rule exists to prevent: a valid close, then a repair
    return to P13 with no fresh close since. Must NOT report the old PASS."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)
        _reach_p13(self.project)
        self.old_evidence_id, self.old_patch_ref = _close_p13(self.project)
        self.registry = er.load_registry()
        # sanity: the old close really does PASS before the repair return
        entry = self.registry[("P13", "patch_artifact_recorded")]
        self.assertEqual(
            er.resolve(entry, er.ResolverContext(project=self.project, phase_id="P13")).status, er.PASS)

    def _return_to_p13(self) -> None:
        # P14's failure_transition is P13 directly (methodology/phases/p14.json) - a real,
        # legal edge, no REPAIR_LOOP pseudo-phase needed first.
        evidence_id = _write_execution_evidence(self.project, "run-0002")
        nm.transition(self.project, "P13", "team", "repair: redo execution",
                      evidence_refs=[evidence_id], authority_class="tool")

    def test_stale_pass_is_killed(self):
        self._return_to_p13()
        for phase, check in (("P13", "patch_artifact_recorded"),
                             ("P14", "execution_evidence_authority_is_execution")):
            entry = self.registry[(phase, check)]
            outcome = er.resolve(entry, er.ResolverContext(project=self.project, phase_id=phase))
            self.assertEqual(outcome.status, er.FAIL, outcome.detail)
            self.assertIn("no current P13-attempt binding", outcome.detail)

    def test_fresh_close_after_reentry_binds_to_new_refs_not_old(self):
        self._return_to_p13()
        new_evidence_id, new_patch_ref = _close_p13(self.project)
        self.assertNotEqual(new_evidence_id, self.old_evidence_id)
        self.assertNotEqual(new_patch_ref, self.old_patch_ref)

        p13_entry = self.registry[("P13", "patch_artifact_recorded")]
        p13_outcome = er.resolve(p13_entry, er.ResolverContext(project=self.project, phase_id="P13"))
        self.assertEqual(p13_outcome.status, er.PASS, p13_outcome.detail)
        self.assertIn(new_patch_ref, p13_outcome.detail)
        self.assertNotIn(self.old_patch_ref, p13_outcome.detail)

        p14_entry = self.registry[("P14", "execution_evidence_authority_is_execution")]
        p14_outcome = er.resolve(p14_entry, er.ResolverContext(project=self.project, phase_id="P14"))
        self.assertEqual(p14_outcome.status, er.PASS, p14_outcome.detail)
        self.assertIn(new_evidence_id, p14_outcome.detail)
        self.assertNotIn(self.old_evidence_id, p14_outcome.detail)


class MalformedReferences(unittest.TestCase):
    """The transition record's own refs point to something that does not (or no longer)
    resolve - the resolver must relay the authoritative check's own verdict, never invent one."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)
        _reach_p13(self.project)
        self.registry = er.load_registry()

    def test_patch_file_deleted_after_close_fails_via_authoritative_check(self):
        evidence_id, patch_ref = _close_p13(self.project)
        (self.project / patch_ref).unlink()
        entry = self.registry[("P13", "patch_artifact_recorded")]
        outcome = er.resolve(entry, er.ResolverContext(project=self.project, phase_id="P13"))
        self.assertEqual(outcome.status, er.FAIL)
        self.assertEqual(outcome.semantic_source, "lifecycle:transition_history")

    def test_evidence_wrong_authority_fails_via_authoritative_check(self):
        wrong_evidence_id = _write_execution_evidence(self.project, "run-0001", authority="verification")
        patch_ref = _write_patch(self.project)
        nb.enter_self_check_phase(self.project, "team", "execution succeeded", wrong_evidence_id, patch_ref)
        entry = self.registry[("P14", "execution_evidence_authority_is_execution")]
        outcome = er.resolve(entry, er.ResolverContext(project=self.project, phase_id="P14"))
        self.assertEqual(outcome.status, er.FAIL)
        self.assertIn("authority", outcome.detail)


class RealPipelinePositive(LifecycleFixture):
    """The full real cmd_run/cmd_verify pipeline (not the hand-driven nogap_build calls
    above) also produces a satisfying binding - proves the resolver works against genuine
    production evidence, not just fixture-shaped evidence."""

    def test_real_pipeline_p13_and_p14_pass(self):
        registry = er.load_registry()
        p13 = registry[("P13", "patch_artifact_recorded")]
        p14 = registry[("P14", "execution_evidence_authority_is_execution")]
        p13_outcome = er.resolve(p13, er.ResolverContext(project=self.project, phase_id="P13"))
        p14_outcome = er.resolve(p14, er.ResolverContext(project=self.project, phase_id="P14"))
        self.assertEqual(p13_outcome.status, er.PASS, p13_outcome.detail)
        self.assertEqual(p14_outcome.status, er.PASS, p14_outcome.detail)
        self.assertIn(self.exec_evidence_id, p14_outcome.detail)


class ErrorHandling(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = _new_project(self.tmp.name)
        _reach_p13(self.project)
        _close_p13(self.project)
        self.registry = er.load_registry()

    def test_resolver_exception_becomes_error(self):
        entry = self.registry[("P13", "patch_artifact_recorded")]
        original = er.RESOLVERS["lifecycle:transition_history"]

        def raiser(ctx, e):
            raise RuntimeError("simulated fault")

        er.RESOLVERS["lifecycle:transition_history"] = raiser
        try:
            outcome = er.resolve(entry, er.ResolverContext(project=self.project, phase_id="P13"))
        finally:
            er.RESOLVERS["lifecycle:transition_history"] = original
        self.assertEqual(outcome.status, er.ERROR)
        self.assertIn("simulated fault", outcome.detail)


if __name__ == "__main__":
    unittest.main()
