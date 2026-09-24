"""D5-PRE: `independent_review_performed` is a structural fact, not inferred from anything.

T1-T4 (creation default / skipped / genuinely-ran / required-but-unavailable) live as added
assertions inside the existing scenario tests in test_methodology_verify.py, since those
scenarios already exist there through the real pipeline. This file covers what doesn't fit
that shape: fail-closed schema enforcement (T6) and current behaviour on a pre-existing
legacy record that predates the field (T7).
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from nogap_artifacts import create_artifact, list_artifacts  # noqa: E402
from nogap_errors import MethodologyValidationError  # noqa: E402
from nogap_methodology import init_project  # noqa: E402


def _new_project() -> Path:
    import subprocess

    project = Path(tempfile.mkdtemp())
    for args in (["init", "-q"], ["config", "user.email", "t@t.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)
    (project / "R.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "R.md"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=project, check=True, capture_output=True)
    init_project(project, "research", "low", "low", actor="test")
    return project


class T6FailClosedSchema(unittest.TestCase):
    """A P18 record missing the new field is rejected - the same required_fields machinery
    every other P18 field already goes through, not a special case for this one."""

    def test_creating_p18_without_the_field_is_rejected(self) -> None:
        project = _new_project()
        fields = {
            "verification_plan_id": "plan-x", "task_id": "task-x", "candidate_hash": "sha256:" + "aa" * 32,
            "patch_hash": "sha256:" + "bb" * 32, "gate_hash": "sha256:" + "cc" * 32,
            "methodology_version_at_verification": "v1", "profile_at_verification": "LIGHT",
            "task_snapshot_hash": "sha256:" + "dd" * 32, "executor_actor_id": "agent:fixture",
            "levels_attempted": ["STATIC_CHECKS"], "deterministic_result": "passed",
            "reproducibility_result": "SKIPPED_PER_PROFILE_POLICY",
            "independent_review_result": "SKIPPED_PER_PROFILE_POLICY",
            # independent_review_performed deliberately omitted
        }
        with self.assertRaises(MethodologyValidationError) as ctx:
            create_artifact(project, "P18_VERIFICATION_RESULT", fields, actor="test")
        self.assertIn("independent_review_performed", str(ctx.exception))


class T7LegacyRecordIsNotBackfilled(unittest.TestCase):
    """Documentation of current state, not a resolver test: a legacy P18 on disk (written
    before this field existed) is left exactly as it is. General read paths must not crash
    on its absence, and nothing here guesses a value for it. Eligibility for D5 resolution
    is a separate, not-yet-built concern."""

    def test_a_legacy_shaped_record_on_disk_reads_back_without_crashing(self) -> None:
        project = _new_project()
        runtime_dir = project / ".code-loop" / "methodology" / "artifacts"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        legacy = {
            "artifact_id": "P18_VERIFICATION_RESULT-legacy0001",
            "artifact_type": "P18_VERIFICATION_RESULT",
            "status": "VERIFICATION_COMPLETE_AWAITING_DECISION",
            "fields": {
                "verification_plan_id": "plan-legacy", "task_id": "task-legacy",
                "candidate_hash": "sha256:" + "11" * 32, "patch_hash": "sha256:" + "22" * 32,
                "gate_hash": "sha256:" + "33" * 32, "methodology_version_at_verification": "v0",
                "profile_at_verification": "LIGHT", "task_snapshot_hash": "sha256:" + "44" * 32,
                "executor_actor_id": "agent:legacy", "levels_attempted": ["STATIC_CHECKS"],
                "deterministic_result": "passed", "reproducibility_result": "SKIPPED_PER_PROFILE_POLICY",
                "independent_review_result": "SKIPPED_PER_PROFILE_POLICY",
                # no independent_review_performed - this record predates D5-PRE
            },
            "created_by": "test", "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00", "status_history": [],
        }
        (runtime_dir / "P18_VERIFICATION_RESULT-legacy0001.json").write_text(
            json.dumps(legacy, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        records = list_artifacts(project, artifact_type="P18_VERIFICATION_RESULT")
        ids = [r["artifact_id"] for r in records]
        self.assertIn("P18_VERIFICATION_RESULT-legacy0001", ids)
        legacy_record = next(r for r in records if r["artifact_id"] == "P18_VERIFICATION_RESULT-legacy0001")
        self.assertNotIn("independent_review_performed", legacy_record["fields"])


if __name__ == "__main__":
    unittest.main()
