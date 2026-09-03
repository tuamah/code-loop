#!/usr/bin/env python3
"""M8-E1: Decision Journal Entry - regression suite.

Covers ONLY DecisionJournalEntry (construction, validation, semantic
identity, immutability, and scope safety). No append/verification/
checkpoint/persistence behavior is implemented or tested here - those
belong to M8-E2/E3/E4/E5.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nogap_decision as nd  # noqa: E402
import nogap_decision_journal as ndj  # noqa: E402


# --- shared builders ---------------------------------------------------------------

def digest(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def genesis_entry(**overrides) -> ndj.DecisionJournalEntry:
    fields = dict(journal_id="journal-1", sequence=0, decision_fingerprint=digest("decision-a"), previous_entry_fingerprint=None)
    fields.update(overrides)
    return ndj.DecisionJournalEntry(**fields)


def non_genesis_entry(**overrides) -> ndj.DecisionJournalEntry:
    fields = dict(journal_id="journal-1", sequence=1, decision_fingerprint=digest("decision-b"), previous_entry_fingerprint=digest("predecessor"))
    fields.update(overrides)
    return ndj.DecisionJournalEntry(**fields)


# --- A. VALID CONSTRUCTION -----------------------------------------------------------

class ValidConstructionTests(unittest.TestCase):
    def test_1_valid_genesis_entry_constructs(self) -> None:
        e = genesis_entry()
        self.assertEqual(e.sequence, 0)

    def test_2_valid_non_genesis_entry_constructs(self) -> None:
        e = non_genesis_entry()
        self.assertEqual(e.sequence, 1)

    def test_3_schema_version_defaults_to_m8_decision_schema_version(self) -> None:
        e = genesis_entry()
        self.assertEqual(e.schema_version, nd.M8_DECISION_SCHEMA_VERSION)

    def test_4_explicit_valid_schema_version_constructs(self) -> None:
        e = genesis_entry(schema_version=nd.M8_DECISION_SCHEMA_VERSION)
        self.assertEqual(e.schema_version, nd.M8_DECISION_SCHEMA_VERSION)


# --- M. SCHEMA VERSION VALIDATION (M8-E1-H1) --------------------------------------------

class SchemaVersionValidationTests(unittest.TestCase):
    def test_76_default_schema_version_accepted(self) -> None:
        e = genesis_entry()
        self.assertEqual(e.schema_version, nd.M8_DECISION_SCHEMA_VERSION)

    def test_77_explicit_current_schema_version_accepted(self) -> None:
        e = genesis_entry(schema_version=nd.M8_DECISION_SCHEMA_VERSION)
        self.assertEqual(e.schema_version, nd.M8_DECISION_SCHEMA_VERSION)

    def test_78_unsupported_schema_version_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(schema_version="totally-bogus-version-xyz")

    def test_79_empty_schema_version_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(schema_version="")

    def test_80_non_string_schema_version_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(schema_version=12345)

    def test_81_schema_version_validated_via_shared_supported_version_path(self) -> None:
        # Same helper object, not a reimplementation - imported, not duplicated.
        self.assertIs(ndj._require_supported_schema_version, nd._require_supported_schema_version)
        self.assertIn(nd.M8_DECISION_SCHEMA_VERSION, nd._SUPPORTED_SCHEMA_VERSIONS)
        # No independent journal-only version list or constant exists.
        self.assertFalse(hasattr(ndj, "M8_JOURNAL_SCHEMA_VERSION"))
        self.assertFalse(hasattr(ndj, "_SUPPORTED_SCHEMA_VERSIONS"))


# --- B. JOURNAL_ID VALIDATION ---------------------------------------------------------

class JournalIdValidationTests(unittest.TestCase):
    def test_5_empty_journal_id_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(journal_id="")

    def test_6_non_string_journal_id_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(journal_id=12345)


# --- C. SEQUENCE VALIDATION -----------------------------------------------------------

class SequenceValidationTests(unittest.TestCase):
    def test_7_negative_sequence_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(sequence=-1, previous_entry_fingerprint=None)

    def test_8_true_sequence_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            ndj.DecisionJournalEntry(journal_id="j", sequence=True, decision_fingerprint=digest("d"), previous_entry_fingerprint=None)

    def test_9_false_sequence_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            ndj.DecisionJournalEntry(journal_id="j", sequence=False, decision_fingerprint=digest("d"), previous_entry_fingerprint=None)

    def test_10_float_sequence_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(sequence=0.0)

    def test_11_string_sequence_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(sequence="0")

    def test_12_zero_accepted(self) -> None:
        e = genesis_entry(sequence=0)
        self.assertEqual(e.sequence, 0)

    def test_13_positive_integer_accepted(self) -> None:
        e = non_genesis_entry(sequence=7)
        self.assertEqual(e.sequence, 7)


# --- D. GENESIS/PREDECESSOR INVARIANT --------------------------------------------------

class GenesisPredecessorInvariantTests(unittest.TestCase):
    def test_14_sequence_0_plus_none_accepted(self) -> None:
        e = genesis_entry(sequence=0, previous_entry_fingerprint=None)
        self.assertIsNone(e.previous_entry_fingerprint)

    def test_15_sequence_0_plus_valid_digest_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(sequence=0, previous_entry_fingerprint=digest("x"))

    def test_16_sequence_0_plus_empty_string_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(sequence=0, previous_entry_fingerprint="")

    def test_17_sequence_gt_0_plus_none_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            non_genesis_entry(sequence=1, previous_entry_fingerprint=None)

    def test_18_sequence_gt_0_plus_valid_digest_accepted(self) -> None:
        e = non_genesis_entry(sequence=1, previous_entry_fingerprint=digest("predecessor"))
        self.assertEqual(len(e.previous_entry_fingerprint), 64)

    def test_19_sequence_gt_0_plus_malformed_digest_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            non_genesis_entry(previous_entry_fingerprint="not-a-digest")

    def test_20_sequence_gt_0_plus_short_digest_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            non_genesis_entry(previous_entry_fingerprint=digest("x")[:32])

    def test_21_sequence_gt_0_plus_non_hex_digest_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            non_genesis_entry(previous_entry_fingerprint="g" * 64)


# --- E. DECISION FINGERPRINT VALIDATION ------------------------------------------------

class DecisionFingerprintValidationTests(unittest.TestCase):
    def test_22_valid_digest_accepted(self) -> None:
        e = genesis_entry(decision_fingerprint=digest("valid"))
        self.assertEqual(len(e.decision_fingerprint), 64)

    def test_23_malformed_digest_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(decision_fingerprint="not-a-digest")

    def test_24_empty_digest_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(decision_fingerprint="")

    def test_25_short_digest_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(decision_fingerprint=digest("x")[:32])

    def test_26_non_hex_digest_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(decision_fingerprint="z" * 64)

    def test_27_non_string_digest_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(decision_fingerprint=12345)


# --- F. OPTIONAL CORRELATION FIELDS -----------------------------------------------------

class OptionalCorrelationFieldTests(unittest.TestCase):
    def test_28_record_ref_none_accepted(self) -> None:
        e = genesis_entry(record_ref=None)
        self.assertIsNone(e.record_ref)

    def test_29_non_empty_record_ref_accepted(self) -> None:
        e = genesis_entry(record_ref="record-1")
        self.assertEqual(e.record_ref, "record-1")

    def test_30_empty_record_ref_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(record_ref="")

    def test_31_non_string_record_ref_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(record_ref=42)

    def test_32_recorded_at_none_accepted(self) -> None:
        e = genesis_entry(recorded_at=None)
        self.assertIsNone(e.recorded_at)

    def test_33_non_empty_recorded_at_accepted(self) -> None:
        e = genesis_entry(recorded_at="2026-09-02T00:00:00Z")
        self.assertEqual(e.recorded_at, "2026-09-02T00:00:00Z")

    def test_34_empty_recorded_at_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(recorded_at="")

    def test_35_non_string_recorded_at_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            genesis_entry(recorded_at=12345)


# --- G. SEMANTIC PAYLOAD ---------------------------------------------------------------

class SemanticPayloadTests(unittest.TestCase):
    def test_36_semantic_payload_exact_key_set(self) -> None:
        payload = genesis_entry().semantic_payload()
        self.assertEqual(set(payload), {"journal_id", "sequence", "decision_fingerprint", "previous_entry_fingerprint", "schema_version"})

    def test_37_semantic_payload_contains_journal_id(self) -> None:
        e = genesis_entry(journal_id="journal-x")
        self.assertEqual(e.semantic_payload()["journal_id"], "journal-x")

    def test_38_semantic_payload_contains_sequence(self) -> None:
        e = non_genesis_entry(sequence=3, previous_entry_fingerprint=digest("p"))
        self.assertEqual(e.semantic_payload()["sequence"], 3)

    def test_39_semantic_payload_contains_decision_fingerprint(self) -> None:
        fp = digest("d-specific")
        e = genesis_entry(decision_fingerprint=fp)
        self.assertEqual(e.semantic_payload()["decision_fingerprint"], fp)

    def test_40_semantic_payload_contains_previous_entry_fingerprint(self) -> None:
        fp = digest("prev-specific")
        e = non_genesis_entry(previous_entry_fingerprint=fp)
        self.assertEqual(e.semantic_payload()["previous_entry_fingerprint"], fp)

    def test_41_semantic_payload_contains_schema_version(self) -> None:
        e = genesis_entry()
        self.assertEqual(e.semantic_payload()["schema_version"], nd.M8_DECISION_SCHEMA_VERSION)

    def test_42_record_ref_absent_from_semantic_payload(self) -> None:
        e = genesis_entry(record_ref="some-ref")
        self.assertNotIn("record_ref", e.semantic_payload())

    def test_43_recorded_at_absent_from_semantic_payload(self) -> None:
        e = genesis_entry(recorded_at="2026-09-02T00:00:00Z")
        self.assertNotIn("recorded_at", e.semantic_payload())

    def test_44_entry_fingerprint_absent_from_semantic_payload(self) -> None:
        e = genesis_entry()
        self.assertNotIn("entry_fingerprint", e.semantic_payload())


# --- H. ENTRY FINGERPRINT ---------------------------------------------------------------

class EntryFingerprintTests(unittest.TestCase):
    def test_45_deterministic_for_identical_semantic_inputs(self) -> None:
        a = genesis_entry()
        b = genesis_entry()
        self.assertEqual(a.entry_fingerprint, b.entry_fingerprint)

    def test_46_valid_sha256_digest_format(self) -> None:
        import re
        e = genesis_entry()
        self.assertTrue(re.match(r"^[0-9a-f]{64}$", e.entry_fingerprint))

    def test_47_changing_journal_id_changes_fingerprint(self) -> None:
        a = genesis_entry(journal_id="journal-a")
        b = genesis_entry(journal_id="journal-b")
        self.assertNotEqual(a.entry_fingerprint, b.entry_fingerprint)

    def test_48_changing_sequence_changes_fingerprint(self) -> None:
        a = genesis_entry()
        b = non_genesis_entry(sequence=1, previous_entry_fingerprint=digest("some-predecessor"))
        self.assertNotEqual(a.entry_fingerprint, b.entry_fingerprint)

    def test_49_changing_decision_fingerprint_changes_fingerprint(self) -> None:
        a = genesis_entry(decision_fingerprint=digest("d1"))
        b = genesis_entry(decision_fingerprint=digest("d2"))
        self.assertNotEqual(a.entry_fingerprint, b.entry_fingerprint)

    def test_50_changing_previous_entry_fingerprint_changes_fingerprint(self) -> None:
        a = non_genesis_entry(previous_entry_fingerprint=digest("p1"))
        b = non_genesis_entry(previous_entry_fingerprint=digest("p2"))
        self.assertNotEqual(a.entry_fingerprint, b.entry_fingerprint)

    def test_51_changing_schema_version_changes_fingerprint(self) -> None:
        a = genesis_entry()
        payload_b = dict(a.semantic_payload())
        payload_b["schema_version"] = "99"
        self.assertNotEqual(nd.fingerprint_payload(a.semantic_payload()), nd.fingerprint_payload(payload_b))


# --- I. CORRELATION NON-IDENTITY --------------------------------------------------------

class CorrelationNonIdentityTests(unittest.TestCase):
    def test_52_changing_record_ref_does_not_change_fingerprint(self) -> None:
        a = genesis_entry(record_ref="ref-a")
        b = genesis_entry(record_ref="ref-b")
        self.assertEqual(a.entry_fingerprint, b.entry_fingerprint)

    def test_53_changing_recorded_at_does_not_change_fingerprint(self) -> None:
        a = genesis_entry(recorded_at="2026-01-01T00:00:00Z")
        b = genesis_entry(recorded_at="2030-01-01T00:00:00Z")
        self.assertEqual(a.entry_fingerprint, b.entry_fingerprint)

    def test_54_changing_both_correlation_fields_does_not_change_fingerprint(self) -> None:
        a = genesis_entry(record_ref="ref-a", recorded_at="2026-01-01T00:00:00Z")
        b = genesis_entry(record_ref="ref-b", recorded_at="2030-01-01T00:00:00Z")
        self.assertEqual(a.entry_fingerprint, b.entry_fingerprint)


# --- J. CONSTRUCTION / ORDER STABILITY --------------------------------------------------

class ConstructionOrderStabilityTests(unittest.TestCase):
    def test_55_independently_constructed_identical_semantic_values_same_fingerprint(self) -> None:
        fp = digest("shared-decision")
        a = ndj.DecisionJournalEntry(journal_id="j", sequence=0, decision_fingerprint=fp, previous_entry_fingerprint=None)
        b = ndj.DecisionJournalEntry(journal_id="j", sequence=0, decision_fingerprint=fp, previous_entry_fingerprint=None)
        self.assertEqual(a.entry_fingerprint, b.entry_fingerprint)

    def test_56_repeated_entry_fingerprint_access_returns_same_value(self) -> None:
        e = genesis_entry()
        self.assertEqual(e.entry_fingerprint, e.entry_fingerprint)

    def test_57_semantic_payload_repeated_call_is_stable(self) -> None:
        e = genesis_entry()
        self.assertEqual(e.semantic_payload(), e.semantic_payload())


# --- K. IMMUTABILITY --------------------------------------------------------------------

class ImmutabilityTests(unittest.TestCase):
    def test_58_journal_id_mutation_rejected(self) -> None:
        e = genesis_entry()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            e.journal_id = "other"

    def test_59_sequence_mutation_rejected(self) -> None:
        e = genesis_entry()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            e.sequence = 5

    def test_60_decision_fingerprint_mutation_rejected(self) -> None:
        e = genesis_entry()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            e.decision_fingerprint = digest("other")

    def test_61_previous_entry_fingerprint_mutation_rejected(self) -> None:
        e = non_genesis_entry()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            e.previous_entry_fingerprint = digest("other")

    def test_62_record_ref_mutation_rejected(self) -> None:
        e = genesis_entry(record_ref="ref")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            e.record_ref = "other"

    def test_63_recorded_at_mutation_rejected(self) -> None:
        e = genesis_entry(recorded_at="2026-09-02T00:00:00Z")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            e.recorded_at = "other"

    def test_64_schema_version_mutation_rejected(self) -> None:
        e = genesis_entry()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            e.schema_version = "99"


# --- L. NON-SCOPE / SAFETY --------------------------------------------------------------

def _code_body_without_module_docstring(module) -> str:
    """Source with the module docstring stripped, so scope-safety checks scan
    only executable code - not the module docstring's prose, which legitimately
    names decision_hash/supersedes/decision-0001/etc. to document that this
    module has NO relationship to them (see nogap_decision_journal.py's
    FROZEN PLACEHOLDER ISOLATION / LEGACY ISOLATION sections)."""
    import ast
    tree = ast.parse(inspect.getsource(module))
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        tree.body = tree.body[1:]
    return ast.unparse(tree)


class NonScopeSafetyTests(unittest.TestCase):
    def test_65_no_caller_supplied_entry_fingerprint_field(self) -> None:
        field_names = {f.name for f in dataclasses.fields(ndj.DecisionJournalEntry)}
        self.assertNotIn("entry_fingerprint", field_names)

    def test_66_module_exposes_no_append_decision_entry(self) -> None:
        self.assertFalse(hasattr(ndj, "append_decision_entry"))

    def test_67_module_exposes_no_verify_decision_journal(self) -> None:
        self.assertFalse(hasattr(ndj, "verify_decision_journal"))

    def test_68_module_exposes_no_journal_checkpoint(self) -> None:
        self.assertFalse(hasattr(ndj, "JournalCheckpoint"))

    def test_69_module_exposes_no_persistence_writer(self) -> None:
        for name in ("write_journal", "save_journal", "load_journal", "read_journal"):
            self.assertFalse(hasattr(ndj, name))

    def test_70_no_new_hash_implementation_in_module(self) -> None:
        source = _code_body_without_module_docstring(ndj)
        self.assertNotIn("hashlib", source)
        self.assertNotIn("hash(", source)
        self.assertEqual(source.count("def fingerprint_payload"), 0)  # imported, not redefined

    def test_71_no_random_uuid_clock_filesystem_network_subprocess_dependency(self) -> None:
        source = _code_body_without_module_docstring(ndj)
        for banned in ("random.", "uuid.", "time.time(", "datetime.now(", "open(", "Path(", "subprocess", "requests", "os.system", "socket"):
            self.assertNotIn(banned, source)

    def test_72_no_legacy_decision_runtime_import(self) -> None:
        source = _code_body_without_module_docstring(ndj)
        for banned in ("decision-0001", "cmd_decide", "runtime_root", "repair", "accept", "abstain"):
            self.assertNotIn(banned, source)

    def test_73_no_relationship_to_decision_hash(self) -> None:
        source = _code_body_without_module_docstring(ndj)
        self.assertNotIn("decision_hash", source)

    def test_74_no_relationship_to_previous_decision_hash(self) -> None:
        source = _code_body_without_module_docstring(ndj)
        self.assertNotIn("previous_decision_hash", source)

    def test_75_no_relationship_to_supersedes(self) -> None:
        source = _code_body_without_module_docstring(ndj)
        self.assertNotIn("supersedes", source)

    def test_dependency_direction_no_circular_import(self) -> None:
        # nogap_decision.py must know nothing about nogap_decision_journal.py
        import ast
        tree = ast.parse((ROOT / "scripts" / "nogap_decision.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertNotIn("nogap_decision_journal", imported)


if __name__ == "__main__":
    unittest.main()
