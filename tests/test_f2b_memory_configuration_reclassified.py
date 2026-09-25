"""MEMORY-CONFIG-CLASSIFICATION-PRE + REPAIR: MEMORY_CONFIGURATION removed from P9's declared
required_artifacts.

Survey (MEMORY-CONFIG-CLASSIFICATION-PRE) traced the kind to its origin: the single M7-A
commit that transcribed all of P0-P23 from an external methodology template, authored before
nogap_memory.py (GP-9's real mechanism, M7-I) existed, never redesigned against it afterward,
and never consumed by any test or resolver as a per-project obligation. GP-9 itself is real
and stays tracked - it was never in question. What was in question was whether P9 should gate
a transition on it as a semantic KIND, and the survey found nothing that ever needed that:
no per-project configuration exists in nogap_memory.py (mode, allowed sources, and refresh
policy are all fixed, global, and today expressed only as prose/enforcement.json narrative,
never as something a project can set differently from another project).

The correction is a contract fix, not an implementation: methodology/phases/p09.json no
longer declares MEMORY_CONFIGURATION as a required_artifact. methodology/enforcement.json's
GP-9 entry, and nogap_memory.py itself, are both untouched - this is not a claim that GP-9's
capability is complete or that PARTIAL should become anything else, only that P9's exit gate
was never the right place to represent it.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import nogap_required_kinds as rk                                         # noqa: E402


class MemoryConfigurationReclassified(unittest.TestCase):
    def test_memory_configuration_no_longer_declared_by_p9(self):
        p09 = json.loads((ROOT / "methodology" / "phases" / "p09.json").read_text(encoding="utf-8"))
        self.assertNotIn("MEMORY_CONFIGURATION", p09["required_artifacts"])
        self.assertEqual(p09["required_artifacts"], ["GOVERNANCE", "RUNTIME_STRUCTURE"])

    def test_memory_configuration_absent_from_declared_required_kinds(self):
        self.assertNotIn("MEMORY_CONFIGURATION", rk.declared_required_kinds())

    def test_memory_configuration_absent_from_both_partition_sets(self):
        self.assertNotIn("MEMORY_CONFIGURATION", rk.ENFORCED_KINDS)
        self.assertNotIn("MEMORY_CONFIGURATION", rk.DEFERRED_KINDS)

    def test_no_phase_anywhere_declares_memory_configuration(self):
        # Confirms P9 was the sole source - the reclassification did not just move the name
        # somewhere else undetected.
        for path in sorted((ROOT / "methodology" / "phases").glob("p*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("MEMORY_CONFIGURATION", data.get("required_artifacts") or [],
                             f"{path.name} still declares MEMORY_CONFIGURATION")

    def test_partition_guard_holds(self):
        # At the time this file was written, COST_MODEL was the one remaining deferred kind
        # (35 enforced / 1 deferred / 36 declared). F2b has since closed COST_MODEL too
        # (tests/test_f2b_cost_model.py) - the set-equality checks below still hold on their
        # own terms regardless of that history, only the literal deferred-set pin needed
        # updating.
        declared = rk.declared_required_kinds()
        enforced = set(rk.ENFORCED_KINDS)
        deferred = set(rk.DEFERRED_KINDS)
        self.assertEqual(declared - (enforced | deferred), set())
        self.assertEqual((enforced | deferred) - declared, set())
        self.assertEqual(len(enforced), 36)
        self.assertEqual(len(deferred), 0)
        self.assertEqual(deferred, set())
        self.assertEqual(len(declared), 36)

    def test_gp9_untouched_still_partial_owned_by_nogap_memory(self):
        # GP-9's own capability record is explicitly NOT part of this reclassification - only
        # the required_artifacts gate on P9 was wrong, never the underlying mechanism's status.
        enforcement = json.loads(
            (ROOT / "methodology" / "enforcement.json").read_text(encoding="utf-8"))
        gp9 = next(p for p in enforcement["principles"] if p["principle_id"] == "GP-9")
        self.assertEqual(gp9["status"], "PARTIAL")
        self.assertEqual(gp9["owner_component"], "nogap_memory.py")

    def test_required_kinds_module_never_imports_nogap_memory(self):
        # This reclassification is a contract correction, not an implementation change - no
        # new resolver, no artifact type, no wiring of memory_status() (or anything else from
        # nogap_memory.py) into required_kinds. A comment naming nogap_memory.py (e.g. in
        # DEFERRED_KINDS' own docstring, explaining GP-9's history) is fine; an import is not.
        source = (ROOT / "scripts" / "nogap_required_kinds.py").read_text(encoding="utf-8")
        self.assertNotIn("import nogap_memory", source)
        self.assertNotIn("from nogap_memory", source)


if __name__ == "__main__":
    unittest.main()
