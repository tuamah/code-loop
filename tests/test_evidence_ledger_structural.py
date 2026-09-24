#!/usr/bin/env python3
"""D4-PRE-B2 structural regression: exactly ONE evidence-ledger reader exists.

Before B2, four modules (nogap_research.py, nogap_failure.py, nogap_methodology.py,
nogap_lifecycle.py) each kept their own private copy of the evidence-ledger reader
(`_evidence_ids` / `_runtime_evidence_ids`), with a `set[str] | None` sentinel that meant
"accept everything" at some call sites and "nothing exists" at others. B2 replaced all four
with calls to the single `nogap_evidence_ledger.read_evidence_ledger()`.

This test is AST-based (not a substring grep) so a reader reintroduced under a different
name, or wrapped, indented, or reformatted differently, still gets caught - what matters is
that a module defines a FUNCTION that itself reads `.code-loop/runtime/evidence` (i.e.
walks/globs that directory), not what it happens to be named this week.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

#: The four modules that must NOT define their own ledger reader.
CALLER_MODULES = [
    "nogap_research.py",
    "nogap_failure.py",
    "nogap_methodology.py",
    "nogap_lifecycle.py",
]


def _source_mentions_evidence_glob(node: ast.AST) -> bool:
    """True if this function body itself globs/iterates a directory named "evidence" -
    the behavioural signature of a ledger reader, independent of what it is called."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value == "evidence":
            return True
    return False


class SingleEvidenceLedgerReaderTests(unittest.TestCase):
    def test_shared_reader_module_exists_and_is_importable(self) -> None:
        import nogap_evidence_ledger as nel

        self.assertTrue(callable(nel.read_evidence_ledger))

    def test_no_caller_module_defines_its_own_evidence_glob_function(self) -> None:
        """AST-walk each of the four caller modules: no top-level (or nested) function
        definition, whatever it is named, may itself contain the "walk the evidence
        directory" logic. That logic must exist exactly once, in nogap_evidence_ledger.py."""
        offenders: list[str] = []
        for filename in CALLER_MODULES:
            path = SCRIPTS / filename
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if _source_mentions_evidence_glob(node):
                        offenders.append(f"{filename}::{node.name}")
        self.assertEqual(
            offenders, [],
            f"a caller module defines its own evidence-ledger reader (should call "
            f"nogap_evidence_ledger.read_evidence_ledger() instead): {offenders}",
        )

    def test_known_old_reader_names_are_gone(self) -> None:
        """Belt-and-suspenders: the specific pre-B2 names must not exist anywhere in the
        four caller modules, even as a dead/unused definition."""
        banned = {"_evidence_ids", "_runtime_evidence_ids"}
        offenders: list[str] = []
        for filename in CALLER_MODULES:
            path = SCRIPTS / filename
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in banned:
                    offenders.append(f"{filename}::{node.name}")
        self.assertEqual(offenders, [], f"a banned pre-B2 reader name reappeared: {offenders}")

    def test_all_four_caller_modules_import_the_shared_reader(self) -> None:
        """Each of the four modules must actually import read_evidence_ledger from the
        shared module - defining nothing of their own AND never calling the real one
        would silently make evidence refs unenforceable everywhere."""
        for filename in CALLER_MODULES:
            path = SCRIPTS / filename
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported = False
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "nogap_evidence_ledger":
                    if any(alias.name == "read_evidence_ledger" for alias in node.names):
                        imported = True
            self.assertTrue(imported, f"{filename} does not import read_evidence_ledger from nogap_evidence_ledger")


if __name__ == "__main__":
    unittest.main()
