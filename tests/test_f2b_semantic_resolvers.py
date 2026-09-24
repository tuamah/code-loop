"""F2b D4 Step 0: PhaseContract.semantic_resolvers, parsed and validated fail-closed at
methodology load time against the closed SEMANTIC_RESOLVERS registry.

Step 0 was declaration only; D4 has since moved EVIDENCE_BUNDLE into ENFORCED_KINDS.
"""

from __future__ import annotations

import ast
import inspect
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nogap_methodology as nm  # noqa: E402
import nogap_required_kinds as rk  # noqa: E402

DECL = {"EVIDENCE_BUNDLE": "EVIDENCE_BUNDLE_RESOLVER"}


class SemanticResolversCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.methodology_dir = Path(self.dir.name) / "methodology"
        shutil.copytree(nm.METHODOLOGY_DIR, self.methodology_dir)

    def path(self, phase: str) -> Path:
        return self.methodology_dir / "phases" / f"{phase}.json"

    def load(self, phase: str) -> dict:
        return json.loads(self.path(phase).read_text(encoding="utf-8"))

    def write(self, phase: str, data: dict) -> None:
        self.path(phase).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def set_resolvers(self, phase: str, resolvers, *, add_required: str | None = None) -> None:
        data = self.load(phase)
        if resolvers is None:
            data.pop("semantic_resolvers", None)
        else:
            data["semantic_resolvers"] = resolvers
        if add_required and add_required not in data["required_artifacts"]:
            data["required_artifacts"].append(add_required)
        self.write(phase, data)

    def assert_rejected(self, fragment: str) -> None:
        with self.assertRaises(nm.MethodologyValidationError) as ctx:
            nm.load_methodology(self.methodology_dir)
        self.assertIn(fragment, str(ctx.exception))

    # T1
    def test_t1_recognized_declaration_loads(self):
        self.set_resolvers("p19", dict(DECL))
        m = nm.load_methodology(self.methodology_dir)
        self.assertEqual(m.phases["P19"].semantic_resolvers, DECL)

    # T2
    def test_t2_unrecognized_resolver_name_fails(self):
        self.set_resolvers("p19", {"EVIDENCE_BUNDLE": "NOT_A_REAL_RESOLVER"})
        self.assert_rejected("unknown resolver 'NOT_A_REAL_RESOLVER'")

    # T3
    def test_t3_key_not_in_required_artifacts_fails(self):
        self.set_resolvers("p19", {"NOT_REQUIRED": "EVIDENCE_BUNDLE_RESOLVER"})
        self.assert_rejected("not in this phase's required_artifacts")

    # T4 - needs two recognized names, so the closed registry is widened for this test only.
    def test_t4_same_kind_different_names_across_phases_fails(self):
        self.set_resolvers("p19", dict(DECL))
        self.set_resolvers("p18", {"EVIDENCE_BUNDLE": "OTHER_RESOLVER"}, add_required="EVIDENCE_BUNDLE")
        widened = {"OTHER_RESOLVER": rk.SemanticResolverSpec(kind="EVIDENCE_BUNDLE")}
        with mock.patch.dict(rk.SEMANTIC_RESOLVERS, widened):
            self.assert_rejected("conflicting semantic_resolvers for 'EVIDENCE_BUNDLE'")

    # T5
    def test_t5_same_kind_same_name_across_phases_loads(self):
        self.set_resolvers("p19", dict(DECL))
        self.set_resolvers("p18", dict(DECL), add_required="EVIDENCE_BUNDLE")
        m = nm.load_methodology(self.methodology_dir)
        self.assertEqual(m.phases["P18"].semantic_resolvers, DECL)
        self.assertEqual(m.phases["P19"].semantic_resolvers, DECL)

    # T8
    def test_t8_absent_key_defaults_to_empty(self):
        self.set_resolvers("p19", None)
        m = nm.load_methodology(self.methodology_dir)
        self.assertEqual(m.phases["P19"].semantic_resolvers, {})
        self.assertEqual(m.phases["P1"].semantic_resolvers, {})

    def test_parse_rejects_non_string_value(self):
        self.set_resolvers("p19", {"EVIDENCE_BUNDLE": {"name": "EVIDENCE_BUNDLE_RESOLVER"}})
        self.assert_rejected("must be a non-empty resolver name string")

    def test_parse_rejects_non_object(self):
        self.set_resolvers("p19", ["EVIDENCE_BUNDLE_RESOLVER"])
        self.assert_rejected("semantic_resolvers must be a JSON object")


class RealMethodology(unittest.TestCase):
    # T6
    def test_t6_real_methodology_loads_with_p19_declaration(self):
        m = nm.load_methodology()
        self.assertEqual(m.phases["P19"].semantic_resolvers, DECL)
        # D4 overturns Step 0's premise by design: the kind is now enforced.
        self.assertIn("EVIDENCE_BUNDLE", rk.ENFORCED_KINDS)
        self.assertNotIn("EVIDENCE_BUNDLE", rk.DEFERRED_KINDS)

    def test_registry_is_closed_literal(self):
        self.assertIsInstance(rk.SEMANTIC_RESOLVERS, dict)
        self.assertIn("EVIDENCE_BUNDLE_RESOLVER", rk.SEMANTIC_RESOLVERS)
        self.assertIs(nm.SEMANTIC_RESOLVERS, rk.SEMANTIC_RESOLVERS)


class NoDynamicResolution(unittest.TestCase):
    # T7
    def test_t7_no_dynamic_import_or_getattr_in_new_code(self):
        sources = [
            inspect.getsource(nm._validate_semantic_resolvers),
            inspect.getsource(nm._parse_phase_contract),
        ]
        registry_src = (ROOT / "scripts" / "nogap_required_kinds.py").read_text(encoding="utf-8")
        tree = ast.parse(registry_src)
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "SEMANTIC_RESOLVERS":
                sources.append(ast.unparse(node))
                literal = node.value
                self.assertIsInstance(literal, ast.Dict)
                self.assertTrue(all(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in literal.keys))
                self.assertTrue(all(isinstance(v, ast.Call) and v.func.id == "SemanticResolverSpec"
                                    for v in literal.values))
                break
        else:
            self.fail("SEMANTIC_RESOLVERS not found as a literal assignment")
        banned = {"getattr", "__import__", "import_module", "eval", "exec", "globals", "locals", "vars"}
        for src in sources:
            for node in ast.walk(ast.parse(src)):
                self.assertNotIsInstance(node, (ast.Import, ast.ImportFrom))
                if isinstance(node, ast.Name):
                    self.assertNotIn(node.id, banned | {"importlib"})
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, banned)


if __name__ == "__main__":
    unittest.main()
