#!/usr/bin/env python3
"""Checks for nogap_effects.py.

Two independent false-success shapes must both stay closed:
1. RC=0, no effect -> never "passed" (verify_effect judges the patch alone).
2. Effect present, but the process then crashed -> never "passed" either
   (classify_agent_execution requires BOTH a normal exit AND a satisfied effect).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from nogap_effects import (  # noqa: E402
    EffectVerdict,
    ExpectedEffect,
    classify_agent_execution,
    touched_paths,
    verify_effect,
)

CREATE_PATCH = (
    "diff --git a/new_file.txt b/new_file.txt\n"
    "new file mode 100644\n"
    "index 0000000..5110780\n"
    "--- /dev/null\n"
    "+++ b/new_file.txt\n"
    "@@ -0,0 +1 @@\n"
    "+hello\n"
)

MULTI_FILE_PATCH = CREATE_PATCH + (
    "diff --git a/settings.json b/settings.json\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/settings.json\n"
    "@@ -0,0 +1 @@\n"
    "+{}\n"
)


class TouchedPathsTests(unittest.TestCase):
    def test_parses_new_file_path(self) -> None:
        self.assertEqual(touched_paths(CREATE_PATCH), {"new_file.txt"})

    def test_parses_multiple_files(self) -> None:
        self.assertEqual(touched_paths(MULTI_FILE_PATCH), {"new_file.txt", "settings.json"})

    def test_empty_patch_has_no_touched_paths(self) -> None:
        self.assertEqual(touched_paths(""), set())


class VerifyEffectTests(unittest.TestCase):
    """verify_effect() is pure: it never sees returncode, timeout, or cancel."""

    def test_empty_patch_is_unsatisfied_under_any(self) -> None:
        verdict = verify_effect("", ExpectedEffect(change_type="ANY"))
        self.assertEqual(verdict.outcome, "unsatisfied")

    def test_any_change_type_accepts_any_observed_change(self) -> None:
        verdict = verify_effect(CREATE_PATCH, ExpectedEffect(change_type="ANY"))
        self.assertEqual(verdict.outcome, "satisfied")
        self.assertEqual(verdict.observed_paths, ["new_file.txt"])

    def test_required_path_present_is_satisfied(self) -> None:
        verdict = verify_effect(CREATE_PATCH, ExpectedEffect(change_type="CREATE", required_paths=["new_file.txt"]))
        self.assertEqual(verdict.outcome, "satisfied")

    def test_required_path_missing_is_unsatisfied_even_with_other_changes(self) -> None:
        verdict = verify_effect(CREATE_PATCH, ExpectedEffect(change_type="CREATE", required_paths=["expected.txt"]))
        self.assertEqual(verdict.outcome, "unsatisfied")

    def test_forbidden_path_touched_is_unsatisfied_even_if_required_path_also_touched(self) -> None:
        verdict = verify_effect(
            MULTI_FILE_PATCH,
            ExpectedEffect(change_type="ANY", required_paths=["new_file.txt"], forbidden_paths=["settings.json"]),
        )
        self.assertEqual(verdict.outcome, "unsatisfied")

    def test_no_change_allowed_satisfied_on_empty_patch(self) -> None:
        self.assertEqual(verify_effect("", ExpectedEffect(change_type="NO_CHANGE_ALLOWED")).outcome, "satisfied")

    def test_no_change_allowed_unsatisfied_if_anything_changed(self) -> None:
        self.assertEqual(verify_effect(CREATE_PATCH, ExpectedEffect(change_type="NO_CHANGE_ALLOWED")).outcome, "unsatisfied")

    def test_content_assertion_checked_against_the_patch_text(self) -> None:
        expected = ExpectedEffect(change_type="CREATE", required_paths=["new_file.txt"], content_contains={"new_file.txt": "+hello"})
        self.assertEqual(verify_effect(CREATE_PATCH, expected).outcome, "satisfied")
        bad = ExpectedEffect(change_type="CREATE", required_paths=["new_file.txt"], content_contains={"new_file.txt": "+goodbye"})
        self.assertEqual(verify_effect(CREATE_PATCH, bad).outcome, "unsatisfied")

    def test_invalid_change_type_is_rejected_at_construction(self) -> None:
        with self.assertRaises(ValueError):
            ExpectedEffect(change_type="NOT_A_REAL_TYPE")


class ClassifyAgentExecutionTests(unittest.TestCase):
    """Execution success = normal process completion AND verified expected effect."""

    def test_clean_exit_with_satisfied_effect_passes(self) -> None:
        status, code, _ = classify_agent_execution("exited", 0, EffectVerdict("satisfied", "ok", ["f.txt"]))
        self.assertEqual(status, "passed")
        self.assertEqual(code, "EXPECTED_EFFECT_PRESENT")

    def test_golden_regression_clean_exit_no_effect_is_never_passed(self) -> None:
        # RC=0, empty patch: exactly what the real Codex Windows-sandbox failure looked like.
        status, code, _ = classify_agent_execution("exited", 0, EffectVerdict("unsatisfied", "nothing changed", []))
        self.assertNotEqual(status, "passed")
        self.assertEqual(status, "failed")
        self.assertEqual(code, "NO_EXPECTED_EFFECT")

    def test_golden_regression_crashed_process_with_satisfied_effect_is_never_passed(self) -> None:
        # The symmetric bug: agent wrote the expected file, then exited 1. A crashed run
        # cannot be trusted as complete just because the patch happens to look right.
        status, code, reason = classify_agent_execution("exited", 1, EffectVerdict("satisfied", "file present", ["f.txt"]))
        self.assertNotEqual(status, "passed")
        self.assertEqual(status, "failed")
        self.assertEqual(code, "EFFECT_PRESENT_BUT_PROCESS_ABNORMAL")
        self.assertIn("crashed", reason.lower())

    def test_crashed_process_with_unsatisfied_effect_fails(self) -> None:
        status, code, _ = classify_agent_execution("exited", 1, EffectVerdict("unsatisfied", "nothing changed", []))
        self.assertEqual(status, "failed")
        self.assertEqual(code, "PROCESS_ABNORMAL_NO_EFFECT")

    def test_timed_out_is_inconclusive_regardless_of_effect(self) -> None:
        status, code, _ = classify_agent_execution("timed_out", None, EffectVerdict("satisfied", "irrelevant", ["f.txt"]))
        self.assertEqual(status, "inconclusive")
        self.assertEqual(code, "TIMED_OUT")

    def test_cancelled_is_blocked_regardless_of_effect(self) -> None:
        status, code, _ = classify_agent_execution("cancelled", None, EffectVerdict("satisfied", "irrelevant", ["f.txt"]))
        self.assertEqual(status, "blocked")
        self.assertEqual(code, "CANCELLED")

    def test_custom_allowed_exit_codes_widens_what_counts_as_normal(self) -> None:
        # An adapter/runtime may declare non-zero codes as normal (e.g. a linter's "issues
        # found" code); this is adapter policy, not something hardcoded in the classifier.
        status, _, _ = classify_agent_execution("exited", 2, EffectVerdict("satisfied", "ok", ["f.txt"]), allowed_exit_codes=[0, 2])
        self.assertEqual(status, "passed")


if __name__ == "__main__":
    unittest.main()
