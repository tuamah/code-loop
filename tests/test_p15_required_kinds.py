"""D4-PRE-C2: P15 required_evidence_kinds matches what the deterministic layer produces.

effect_scope is always produced; deterministic only when the frozen gate has required
commands (decided by nogap_verification.required_commands_from_gate on that same gate).
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import nogap_artifacts as na                                              # noqa: E402
import nogap_verify_binding as vb                                         # noqa: E402
import methodology_fixture_builder as fbuilder                            # noqa: E402
from test_evidence_classes import _git_project                            # noqa: E402

DETERMINISTIC_LAYER = {"effect_scope", "deterministic"}


def _run(risk: str, commands: list[str] | None):
    project = _git_project(risk)
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "nogap.py"), "init",
                           str(project), "--objective", "fixture"], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    env = {}
    if commands is not None:
        gate_path = project / ".code-loop" / "runtime" / "gates" / "gate-0001.json"
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        gate["rules"]["required_commands"] = commands
        gate_path.write_text(json.dumps(gate, indent=2), encoding="utf-8")
        bindir = Path(tempfile.mkdtemp())
        shim = bindir / "pytest"
        shim.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
        env = {"PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"}
    with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
        fbuilder.advance_via_real_pipeline(project)
    plans = na.list_artifacts(project, artifact_type="P15_VERIFICATION_PLAN")
    assert len(plans) == 1, plans
    records = [json.loads(p.read_text(encoding="utf-8")) for p in
               (project / ".code-loop" / "runtime" / "evidence").glob("*.json")]
    produced = {r.get("evidence_class") for r in records
                if r.get("provenance", {}).get("authority") == "verification"}
    return plans[0]["fields"], produced, vb.derive_verification_depth(project)


class P15RequiredKinds(unittest.TestCase):
    # Each run is isolated: its result OR its exception is recorded, so one failing run
    # cannot stop the others. Reading a run that raised fails the calling test explicitly.
    RUNS = {
        "no_cmd": ("low", None),
        "with_cmd": ("medium", ["pytest -k unit"]),
        # medium risk sets every depth flag, so gate shape and depth diverge here
        "med_no_cmd": ("medium", None),
    }

    @classmethod
    def setUpClass(cls):
        cls._results = {}
        for name, (risk, commands) in cls.RUNS.items():
            try:
                cls._results[name] = (True, _run(risk, commands))
            except BaseException as exc:  # noqa: BLE001 - SystemExit is how nogap rejects
                cls._results[name] = (False, exc)

    def __getattr__(self, name):
        results = type(self).__dict__.get("_results") or {}
        if name not in results:
            raise AttributeError(name)
        ok, value = results[name]
        if not ok:
            self.fail(f"pipeline run {name!r} raised {type(value).__name__}: {value}")
        return value

    def test_t1_no_required_commands(self):
        for run in ("no_cmd", "med_no_cmd"):
            with self.subTest(run=run):
                kinds = getattr(self, run)[0]["required_evidence_kinds"]
                self.assertIn("effect_scope", kinds)
                self.assertNotIn("deterministic", kinds)

    def test_t2_with_required_commands(self):
        kinds = self.with_cmd[0]["required_evidence_kinds"]
        self.assertIn("effect_scope", kinds)
        self.assertIn("deterministic", kinds)

    def test_t3_depth_flags_unchanged(self):
        for fields, _, depth in (self.no_cmd, self.with_cmd):
            kinds = fields["required_evidence_kinds"]
            self.assertEqual("reproducibility" in kinds, bool(depth["reproducibility_required"]))
            self.assertEqual("independent_review" in kinds, bool(depth["independent_review_required"]))
        # the two runs differ in depth, so both branches of the flag are exercised
        self.assertNotEqual(self.no_cmd[2]["reproducibility_required"],
                            self.with_cmd[2]["reproducibility_required"])

    def test_t4_contract_producer_agreement(self):
        for run in ("no_cmd", "with_cmd", "med_no_cmd"):
            with self.subTest(run=run):
                fields, produced, _ = getattr(self, run)
                required = set(fields["required_evidence_kinds"]) & DETERMINISTIC_LAYER
                self.assertTrue(required <= produced, (required, produced))
                if "deterministic" not in fields["required_evidence_kinds"]:
                    self.assertNotIn("deterministic", produced)
        self.assertIn("deterministic", self.with_cmd[1])

    def test_t5_effect_scope_never_satisfies_deterministic(self):
        # behavioural: with no commands, effect_scope is produced but deterministic is not required
        fields, produced, _ = self.no_cmd
        self.assertIn("effect_scope", produced)
        self.assertNotIn("deterministic", produced)
        # structural: no source equates the two class names
        for path in (ROOT / "scripts").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Compare) and len(node.comparators) == 1:
                    names = {getattr(n, "value", None) for n in (node.left, node.comparators[0])}
                    self.assertNotEqual(names, DETERMINISTIC_LAYER, f"{path.name}: {ast.unparse(node)}")
                if isinstance(node, ast.Dict):
                    for k, v in zip(node.keys, node.values):
                        pair = {getattr(k, "value", None), getattr(v, "value", None)}
                        self.assertNotEqual(pair, DETERMINISTIC_LAYER, f"{path.name}: alias map")


if __name__ == "__main__":
    unittest.main()
