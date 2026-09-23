"""F2b D3 Part A: PhaseContract.artifact_field_bindings, parsed and validated fail-closed at
methodology load time.

Each test builds a temporary methodology directory (copied from the real one) and mutates a
single phase file, proving the load-time validator rejects it with MethodologyValidationError.
The happy path is covered by test_f2b_benchmark_protocol.py, which loads the real methodology.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nogap_methodology as nm  # noqa: E402


class TemporaryMethodologyCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.methodology_dir = Path(self.dir.name) / "methodology"
        shutil.copytree(nm.METHODOLOGY_DIR, self.methodology_dir)

    def p10_path(self) -> Path:
        return self.methodology_dir / "phases" / "p10.json"

    def write_p10(self, data: dict) -> None:
        self.p10_path().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def load_p10(self) -> dict:
        return json.loads(self.p10_path().read_text(encoding="utf-8"))


class BindingStructuralValidation(TemporaryMethodologyCase):
    def test_binding_key_not_in_required_artifacts_fails(self):
        data = self.load_p10()
        data["artifact_field_bindings"] = {
            "NOT_REQUIRED": {"artifact_type": "P10_BASELINE", "field": "measurement_procedure"}
        }
        self.write_p10(data)
        with self.assertRaises(nm.MethodologyValidationError) as ctx:
            nm.load_methodology(self.methodology_dir)
        self.assertIn("required_artifacts", str(ctx.exception))

    def test_unknown_artifact_type_fails(self):
        data = self.load_p10()
        data["artifact_field_bindings"] = {
            "BENCHMARK_PROTOCOL": {"artifact_type": "NOT_A_TYPE", "field": "measurement_procedure"}
        }
        self.write_p10(data)
        with self.assertRaises(nm.MethodologyValidationError) as ctx:
            nm.load_methodology(self.methodology_dir)
        self.assertIn("unknown artifact_type", str(ctx.exception))

    def test_artifact_type_from_wrong_phase_fails(self):
        data = self.load_p10()
        data["artifact_field_bindings"] = {
            "BENCHMARK_PROTOCOL": {"artifact_type": "P1_SCOPE", "field": "problem_statement"}
        }
        self.write_p10(data)
        with self.assertRaises(nm.MethodologyValidationError) as ctx:
            nm.load_methodology(self.methodology_dir)
        self.assertIn("belongs to", str(ctx.exception))

    def test_unknown_field_fails(self):
        data = self.load_p10()
        data["artifact_field_bindings"] = {
            "BENCHMARK_PROTOCOL": {"artifact_type": "P10_BASELINE", "field": "not_a_field"}
        }
        self.write_p10(data)
        with self.assertRaises(nm.MethodologyValidationError) as ctx:
            nm.load_methodology(self.methodology_dir)
        self.assertIn("undeclared field", str(ctx.exception))

    def test_conflicting_binding_across_phases_fails(self):
        p10 = self.load_p10()
        p10["artifact_field_bindings"] = {
            "BENCHMARK_PROTOCOL": {"artifact_type": "P10_BASELINE", "field": "measurement_procedure"}
        }
        self.write_p10(p10)
        p11_path = self.methodology_dir / "phases" / "p11.json"
        p11 = json.loads(p11_path.read_text(encoding="utf-8"))
        p11.setdefault("required_artifacts", []).append("BENCHMARK_PROTOCOL")
        p11["artifact_field_bindings"] = {
            "BENCHMARK_PROTOCOL": {"artifact_type": "P11_GATE_PLAN", "field": "required_tests"}
        }
        p11_path.write_text(json.dumps(p11, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(nm.MethodologyValidationError) as ctx:
            nm.load_methodology(self.methodology_dir)
        self.assertIn("conflicting artifact_field_bindings", str(ctx.exception))

    def test_malformed_binding_shape_fails(self):
        data = self.load_p10()
        data["artifact_field_bindings"] = {"BENCHMARK_PROTOCOL": "not-a-dict"}
        self.write_p10(data)
        with self.assertRaises(nm.MethodologyValidationError):
            nm.load_methodology(self.methodology_dir)

    def test_binding_with_extra_key_fails(self):
        data = self.load_p10()
        data["artifact_field_bindings"] = {
            "BENCHMARK_PROTOCOL": {
                "artifact_type": "P10_BASELINE", "field": "measurement_procedure", "extra": "x",
            }
        }
        self.write_p10(data)
        with self.assertRaises(nm.MethodologyValidationError):
            nm.load_methodology(self.methodology_dir)

    def test_binding_to_a_profile_only_field_fails(self):
        # P7_ARCHITECTURE declares "failure_domains" only in profile_required_fields (STRICT),
        # never in required_fields. required_artifacts (and any kind bound through
        # artifact_field_bindings) applies at every profile, so a binding to a
        # profile-conditional field must be rejected, not silently admitted.
        p7_path = self.methodology_dir / "phases" / "p07.json"
        p7 = json.loads(p7_path.read_text(encoding="utf-8"))
        self.assertIn("ARCHITECTURE", p7.get("required_artifacts", []))
        p7["artifact_field_bindings"] = {
            "ARCHITECTURE": {"artifact_type": "P7_ARCHITECTURE", "field": "failure_domains"}
        }
        p7_path.write_text(json.dumps(p7, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(nm.MethodologyValidationError) as ctx:
            nm.load_methodology(self.methodology_dir)
        self.assertIn("undeclared field", str(ctx.exception))

    def test_no_bindings_anywhere_still_loads(self):
        # baseline sanity: the real methodology (before D3 declares a binding) must still load.
        nm.load_methodology(self.methodology_dir)


if __name__ == "__main__":
    unittest.main()
