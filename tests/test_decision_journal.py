#!/usr/bin/env python3
"""M8-E1/M8-E2: Decision Journal Entry + pure append/verification - regression
suite.

M8-E1 section covers DecisionJournalEntry (construction, validation,
semantic identity, immutability, scope safety). M8-E2 section covers
verify_decision_journal() (structural chain verification) and
append_decision_entry() (pure next-entry construction). No checkpoint/
persistence/replay behavior is implemented or tested here - those belong to
M8-E3/E4/E5.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import sys
import unittest
from pathlib import Path
from unittest import mock

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


# --- M8-E2 shared builders -----------------------------------------------------------

def scope(**overrides) -> nd.DecisionScope:
    fields = dict(scope_type="TASK", scope_id="TASK-1", project_id="proj-1")
    fields.update(overrides)
    return nd.DecisionScope(**fields)


def bound_record(**overrides) -> nd.DecisionRecordContract:
    """A trust-identifiable DecisionRecordContract - evaluation_fingerprint
    is supplied, so .decision_fingerprint succeeds. Mirrors
    test_decision_contracts.py's own make_record(evaluation_fingerprint=...)
    pattern exactly - not a new construction idiom."""
    fields = dict(
        decision_id="dec-1", evaluation_id="eval-1", request_id="req-1", decision_type="TASK_ACCEPTANCE",
        scope=scope(), verdict="ACCEPT", reason_codes=(), evaluation_ref="eval-1", policy_ref="policy-1",
        created_at="2026-09-02T00:00:00Z", evaluation_fingerprint=digest("fixed-eval"),
    )
    fields.update(overrides)
    return nd.DecisionRecordContract(**fields)


def unbound_record(**overrides) -> nd.DecisionRecordContract:
    """Legacy-constructible but NOT trust-identifiable: no
    evaluation_fingerprint, so .decision_fingerprint raises."""
    fields = dict(
        decision_id="dec-1", evaluation_id="eval-1", request_id="req-1", decision_type="TASK_ACCEPTANCE",
        scope=scope(), verdict="ACCEPT", reason_codes=(), evaluation_ref="eval-1", policy_ref="policy-1",
        created_at="2026-09-02T00:00:00Z",
    )
    fields.update(overrides)
    return nd.DecisionRecordContract(**fields)


def chain(n: int, journal_id: str = "journal-1") -> tuple[ndj.DecisionJournalEntry, ...]:
    """A valid linear n-entry chain, built via append_decision_entry itself
    so every test chain is guaranteed internally coherent by construction."""
    entries: list[ndj.DecisionJournalEntry] = []
    for i in range(n):
        record = bound_record(decision_id=f"dec-{i}", evaluation_fingerprint=digest(f"eval-{i}"))
        entries.append(ndj.append_decision_entry(tuple(entries), record, journal_id=journal_id))
    return tuple(entries)


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

def _executable_code_only(module) -> str:
    """Source with EVERY docstring stripped - module, class, and function/
    method level - so scope-safety checks scan only executable code, never
    prose. nogap_decision_journal.py's docstrings legitimately name
    decision_hash/supersedes/decision-0001/checkpoint/replay/clock/lock/etc.
    to document that this module has NO relationship to them (LEGACY
    ISOLATION / FROZEN PLACEHOLDER ISOLATION sections, and the M8-E2
    docstrings' own "no clock/no persistence/M8-E3 checkpoint territory"
    deferral language) - stripping only the module docstring (as M8-E1's
    version of this helper did) was insufficient once M8-E2 added
    function-level docstrings using those same words; this generalized
    version removes the leading string-literal Expr from every module/class/
    function body in the AST, not just the top-level one."""
    import ast

    class _DocstringStripper(ast.NodeTransformer):
        def _strip(self, node):
            self.generic_visit(node)
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body = node.body[1:] or [ast.Pass()]
            return node

        def visit_Module(self, node):
            return self._strip(node)

        def visit_ClassDef(self, node):
            return self._strip(node)

        def visit_FunctionDef(self, node):
            return self._strip(node)

        def visit_AsyncFunctionDef(self, node):
            return self._strip(node)

    tree = ast.parse(inspect.getsource(module))
    tree = _DocstringStripper().visit(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


class NonScopeSafetyTests(unittest.TestCase):
    def test_65_no_caller_supplied_entry_fingerprint_field(self) -> None:
        field_names = {f.name for f in dataclasses.fields(ndj.DecisionJournalEntry)}
        self.assertNotIn("entry_fingerprint", field_names)

    def test_66_module_exposes_append_decision_entry(self) -> None:
        # E1 asserted this was ABSENT; M8-E2 legitimately adds it. Updated to
        # a positive existence check now that it is in-scope and implemented.
        self.assertTrue(callable(getattr(ndj, "append_decision_entry", None)))

    def test_67_module_exposes_verify_decision_journal(self) -> None:
        # Same evolution as test_66 - M8-E2 adds this function in-scope.
        self.assertTrue(callable(getattr(ndj, "verify_decision_journal", None)))

    def test_68_module_exposes_no_journal_checkpoint(self) -> None:
        self.assertFalse(hasattr(ndj, "JournalCheckpoint"))

    def test_69_module_exposes_no_persistence_writer(self) -> None:
        for name in ("write_journal", "save_journal", "load_journal", "read_journal"):
            self.assertFalse(hasattr(ndj, name))

    def test_70_no_new_hash_implementation_in_module(self) -> None:
        source = _executable_code_only(ndj)
        self.assertNotIn("hashlib", source)
        self.assertNotIn("hash(", source)
        self.assertEqual(source.count("def fingerprint_payload"), 0)  # imported, not redefined

    def test_71_no_random_uuid_clock_filesystem_network_subprocess_dependency(self) -> None:
        source = _executable_code_only(ndj)
        for banned in ("random.", "uuid.", "time.time(", "datetime.now(", "open(", "Path(", "subprocess", "requests", "os.system", "socket"):
            self.assertNotIn(banned, source)

    def test_72_no_legacy_decision_runtime_import(self) -> None:
        source = _executable_code_only(ndj)
        for banned in ("decision-0001", "cmd_decide", "runtime_root", "repair", "accept", "abstain"):
            self.assertNotIn(banned, source)

    def test_73_no_relationship_to_decision_hash(self) -> None:
        source = _executable_code_only(ndj)
        self.assertNotIn("decision_hash", source)

    def test_74_no_relationship_to_previous_decision_hash(self) -> None:
        source = _executable_code_only(ndj)
        self.assertNotIn("previous_decision_hash", source)

    def test_75_no_relationship_to_supersedes(self) -> None:
        source = _executable_code_only(ndj)
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


# ================================================================================
# M8-E2: Pure Append + Structural Journal Verification
# ================================================================================

# --- 1. JournalVerificationResult invariant (items 1-3) ------------------------------

class JournalVerificationResultInvariantTests(unittest.TestCase):
    def test_e2_1_valid_result_with_no_reason_code_constructs(self) -> None:
        r = ndj.JournalVerificationResult(valid=True)
        self.assertTrue(r.valid)
        self.assertIsNone(r.reason_code)

    def test_e2_1b_valid_result_with_reason_code_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            ndj.JournalVerificationResult(valid=True, reason_code="SEQUENCE_INVALID")

    def test_e2_2_invalid_result_with_known_reason_code_constructs(self) -> None:
        r = ndj.JournalVerificationResult(valid=False, reason_code="SEQUENCE_INVALID")
        self.assertFalse(r.valid)
        self.assertEqual(r.reason_code, "SEQUENCE_INVALID")

    def test_e2_2b_invalid_result_without_reason_code_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            ndj.JournalVerificationResult(valid=False)

    def test_e2_3_unknown_journal_reason_rejected(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            ndj.JournalVerificationResult(valid=False, reason_code="TOTALLY_BOGUS_REASON")

    def test_e2_3b_decision_reason_code_not_accepted_for_journal_result(self) -> None:
        # DECISION_REASON_CODES is a different domain's vocabulary entirely.
        with self.assertRaises(nd.DecisionValidationError):
            ndj.JournalVerificationResult(valid=False, reason_code="MANDATORY_PREDICATE_FALSE")


# --- 2. Empty journal (items 4-5) -----------------------------------------------------

class VerifyEmptyJournalTests(unittest.TestCase):
    def test_e2_4_empty_journal_valid(self) -> None:
        r = ndj.verify_decision_journal(())
        self.assertEqual(r, ndj.JournalVerificationResult(valid=True))

    def test_e2_5_empty_journal_with_expected_journal_id_valid(self) -> None:
        # The pin defines an expected domain, but there are no entries to
        # contradict it - empty stays valid regardless of the pin.
        r = ndj.verify_decision_journal((), journal_id="journal-1")
        self.assertEqual(r, ndj.JournalVerificationResult(valid=True))


# --- 3. Valid chains (items 6-8) ------------------------------------------------------

class VerifyValidChainTests(unittest.TestCase):
    def test_e2_6_genesis_only_valid(self) -> None:
        c = chain(1)
        self.assertTrue(ndj.verify_decision_journal(c).valid)

    def test_e2_7_valid_e0_e1(self) -> None:
        c = chain(2)
        self.assertTrue(ndj.verify_decision_journal(c).valid)

    def test_e2_8_valid_e0_e1_e2(self) -> None:
        c = chain(3)
        self.assertTrue(ndj.verify_decision_journal(c).valid)


# --- 4. journal_id consistency (items 9-10) --------------------------------------------

class VerifyJournalIdConsistencyTests(unittest.TestCase):
    def test_e2_9_mixed_journal_ids_rejected(self) -> None:
        e0 = genesis_entry(journal_id="A")
        e1 = ndj.DecisionJournalEntry(journal_id="B", sequence=1, decision_fingerprint=digest("d1"), previous_entry_fingerprint=e0.entry_fingerprint)
        r = ndj.verify_decision_journal((e0, e1))
        self.assertEqual(r, ndj.JournalVerificationResult(valid=False, reason_code="JOURNAL_ID_MISMATCH"))

    def test_e2_10_internally_consistent_wrong_journal_rejected_when_pinned(self) -> None:
        c = chain(2, journal_id="B")
        self.assertTrue(ndj.verify_decision_journal(c).valid)  # consistent on its own
        r = ndj.verify_decision_journal(c, journal_id="A")
        self.assertEqual(r, ndj.JournalVerificationResult(valid=False, reason_code="JOURNAL_ID_MISMATCH"))


# --- 5. Sequence validity (items 11-15) ------------------------------------------------

class VerifySequenceValidityTests(unittest.TestCase):
    def test_e2_11_sequence_gap_rejected(self) -> None:
        c = chain(2)
        e3 = ndj.DecisionJournalEntry(journal_id="journal-1", sequence=3, decision_fingerprint=digest("d3"), previous_entry_fingerprint=c[1].entry_fingerprint)
        r = ndj.verify_decision_journal(c + (e3,))
        self.assertEqual(r, ndj.JournalVerificationResult(valid=False, reason_code="SEQUENCE_INVALID"))

    def test_e2_12_missing_genesis_rejected(self) -> None:
        e_a = non_genesis_entry(sequence=1, previous_entry_fingerprint=digest("fake"))
        e_b = ndj.DecisionJournalEntry(journal_id="journal-1", sequence=2, decision_fingerprint=digest("d2"), previous_entry_fingerprint=e_a.entry_fingerprint)
        r = ndj.verify_decision_journal((e_a, e_b))
        self.assertEqual(r, ndj.JournalVerificationResult(valid=False, reason_code="SEQUENCE_INVALID"))

    def test_e2_13_duplicate_sequence_rejected(self) -> None:
        e0a = genesis_entry(decision_fingerprint=digest("x"))
        e0b = genesis_entry(decision_fingerprint=digest("y"))
        r = ndj.verify_decision_journal((e0a, e0b))
        self.assertEqual(r, ndj.JournalVerificationResult(valid=False, reason_code="SEQUENCE_INVALID"))

    def test_e2_14_duplicate_exact_entry_rejected(self) -> None:
        c = chain(2)
        r = ndj.verify_decision_journal((c[0], c[0]))
        self.assertEqual(r, ndj.JournalVerificationResult(valid=False, reason_code="SEQUENCE_INVALID"))

    def test_e2_15_wrong_starting_sequence_rejected(self) -> None:
        e_a = non_genesis_entry(sequence=1, previous_entry_fingerprint=digest("fake"))
        r = ndj.verify_decision_journal((e_a,))
        self.assertEqual(r, ndj.JournalVerificationResult(valid=False, reason_code="SEQUENCE_INVALID"))


# --- 6. Presentation order (item 16) ---------------------------------------------------

class VerifyPresentationOrderTests(unittest.TestCase):
    def test_e2_16_correct_set_wrong_list_order_rejected(self) -> None:
        c = chain(3)
        r = ndj.verify_decision_journal((c[0], c[2], c[1]))
        self.assertEqual(r, ndj.JournalVerificationResult(valid=False, reason_code="PRESENTATION_ORDER_INVALID"))


# --- 7. Predecessor linkage (item 17) --------------------------------------------------

class VerifyPredecessorLinkageTests(unittest.TestCase):
    def test_e2_17_predecessor_mismatch_rejected(self) -> None:
        # Case L: an old entry is altered without updating the descendant's
        # previous_entry_fingerprint.
        c = chain(3)
        e1_alt = ndj.DecisionJournalEntry(journal_id="journal-1", sequence=1, decision_fingerprint=digest("altered"), previous_entry_fingerprint=c[0].entry_fingerprint)
        r = ndj.verify_decision_journal((c[0], e1_alt, c[2]))
        self.assertEqual(r, ndj.JournalVerificationResult(valid=False, reason_code="PREDECESSOR_MISMATCH"))


# --- 8. Fork (item 18) ------------------------------------------------------------------

class VerifyForkTests(unittest.TestCase):
    def test_e2_18_visible_fork_rejected(self) -> None:
        c = chain(1)
        child_a = ndj.DecisionJournalEntry(journal_id="journal-1", sequence=1, decision_fingerprint=digest("a"), previous_entry_fingerprint=c[0].entry_fingerprint)
        child_b = ndj.DecisionJournalEntry(journal_id="journal-1", sequence=1, decision_fingerprint=digest("b"), previous_entry_fingerprint=c[0].entry_fingerprint)
        r = ndj.verify_decision_journal((c[0], child_a, child_b))
        self.assertEqual(r, ndj.JournalVerificationResult(valid=False, reason_code="SEQUENCE_INVALID"))


# --- 9. Correlation fields are non-authoritative for verification (items 19-20) --------

class VerifyCorrelationNonAuthorityTests(unittest.TestCase):
    def test_e2_19_predecessor_linkage_indifferent_to_record_ref(self) -> None:
        e0_original = genesis_entry(record_ref="ref-a")
        e1 = ndj.DecisionJournalEntry(journal_id="journal-1", sequence=1, decision_fingerprint=digest("d1"), previous_entry_fingerprint=e0_original.entry_fingerprint)
        # A differently-record_ref'd but semantically identical genesis entry
        # still links correctly - entry_fingerprint excludes record_ref.
        e0_different_ref = genesis_entry(record_ref="ref-b")
        self.assertEqual(e0_original.entry_fingerprint, e0_different_ref.entry_fingerprint)
        r = ndj.verify_decision_journal((e0_different_ref, e1))
        self.assertTrue(r.valid)

    def test_e2_20_recorded_at_change_does_not_affect_validity(self) -> None:
        c = chain(2)
        e0_alt = genesis_entry(decision_fingerprint=c[0].decision_fingerprint, recorded_at="2030-01-01T00:00:00Z")
        self.assertEqual(c[0].entry_fingerprint, e0_alt.entry_fingerprint)
        r = ndj.verify_decision_journal((e0_alt, c[1]))
        self.assertTrue(r.valid)


# --- 10. Critical, permanent limitations (items 21-23) ---------------------------------

class VerifyLimitationTests(unittest.TestCase):
    def test_e2_21_valid_prefix_accepted(self) -> None:
        # STRUCTURALLY VALID PREFIX != PROOF OF COMPLETE HISTORY. A genuine
        # prefix of a longer real history verifies True - this is CORRECT,
        # not a bug: E2 only ever claims the presented chain is coherent,
        # never that it is complete. Detecting truncation needs an external
        # anchor (M8-E3 checkpoint territory), not this function.
        full = chain(4)
        prefix = full[:2]
        self.assertTrue(ndj.verify_decision_journal(prefix).valid)

    def test_e2_22_full_self_consistent_rewrite_remains_valid(self) -> None:
        # CRITICAL, PERMANENT LIMITATION: if every entry in a local chain is
        # rewritten and every descendant's previous_entry_fingerprint is
        # recomputed to match, the result verifies True. This is not
        # something E2 can or should claim to detect - it has no external
        # anchor to compare against. This test documents the limitation by
        # construction; it must never be "fixed" inside E2.
        real_rec_0 = bound_record(decision_id="real-0", evaluation_fingerprint=digest("real-eval-0"))
        real_e0 = ndj.append_decision_entry((), real_rec_0, journal_id="journal-1")
        real_rec_1 = bound_record(decision_id="real-1", evaluation_fingerprint=digest("real-eval-1"))
        real_e1 = ndj.append_decision_entry((real_e0,), real_rec_1, journal_id="journal-1")

        rewritten_rec_0 = bound_record(decision_id="rewritten-0", evaluation_fingerprint=digest("rewritten-eval-0"))
        rewritten_e0 = ndj.append_decision_entry((), rewritten_rec_0, journal_id="journal-1")
        rewritten_rec_1 = bound_record(decision_id="rewritten-1", evaluation_fingerprint=digest("rewritten-eval-1"))
        rewritten_e1 = ndj.append_decision_entry((rewritten_e0,), rewritten_rec_1, journal_id="journal-1")

        self.assertNotEqual(real_e0.entry_fingerprint, rewritten_e0.entry_fingerprint)
        self.assertTrue(ndj.verify_decision_journal((real_e0, real_e1)).valid)
        self.assertTrue(ndj.verify_decision_journal((rewritten_e0, rewritten_e1)).valid)

    def test_e2_23_hidden_fork_not_detectable(self) -> None:
        # A branch not supplied to verify_decision_journal cannot be
        # detected - each independently-presented branch verifies True on
        # its own terms, with no way to know the other exists.
        c = chain(2)
        rec_a = bound_record(decision_id="branch-a", evaluation_fingerprint=digest("branch-a-eval"))
        branch_a = ndj.append_decision_entry(c, rec_a, journal_id="journal-1")
        rec_b = bound_record(decision_id="branch-b", evaluation_fingerprint=digest("branch-b-eval"))
        branch_b = ndj.append_decision_entry(c, rec_b, journal_id="journal-1")

        self.assertTrue(ndj.verify_decision_journal(c + (branch_a,)).valid)
        self.assertTrue(ndj.verify_decision_journal(c + (branch_b,)).valid)


# --- 11. Append construction (items 24-29) ----------------------------------------------

class AppendConstructionTests(unittest.TestCase):
    def test_e2_24_genesis_append(self) -> None:
        rec = bound_record()
        e0 = ndj.append_decision_entry((), rec, journal_id="journal-1")
        self.assertEqual(e0.sequence, 0)
        self.assertIsNone(e0.previous_entry_fingerprint)
        self.assertEqual(e0.decision_fingerprint, rec.decision_fingerprint)

    def test_e2_25_second_append(self) -> None:
        rec0 = bound_record(decision_id="d0", evaluation_fingerprint=digest("e0"))
        e0 = ndj.append_decision_entry((), rec0, journal_id="journal-1")
        rec1 = bound_record(decision_id="d1", evaluation_fingerprint=digest("e1"))
        e1 = ndj.append_decision_entry((e0,), rec1, journal_id="journal-1")
        self.assertEqual(e1.sequence, 1)
        self.assertEqual(e1.previous_entry_fingerprint, e0.entry_fingerprint)

    def test_e2_26_multi_entry_append(self) -> None:
        c = chain(5)
        self.assertEqual(len(c), 5)
        self.assertEqual(tuple(e.sequence for e in c), (0, 1, 2, 3, 4))
        self.assertTrue(ndj.verify_decision_journal(c).valid)

    def test_e2_27_append_derives_sequence_not_caller_supplied(self) -> None:
        params = inspect.signature(ndj.append_decision_entry).parameters
        self.assertNotIn("sequence", params)

    def test_e2_28_append_derives_predecessor_fingerprint_not_caller_supplied(self) -> None:
        params = inspect.signature(ndj.append_decision_entry).parameters
        self.assertNotIn("previous_entry_fingerprint", params)

    def test_e2_29_append_does_not_mutate_history(self) -> None:
        e0 = ndj.append_decision_entry((), bound_record(), journal_id="journal-1")
        history = [e0]
        snapshot = list(history)
        ndj.append_decision_entry(history, bound_record(decision_id="d2", evaluation_fingerprint=digest("e2")), journal_id="journal-1")
        self.assertEqual(history, snapshot)


# --- 12. Append rejections (items 30-34) -------------------------------------------------

class AppendRejectionTests(unittest.TestCase):
    def test_e2_30_append_rejects_invalid_history(self) -> None:
        c = chain(2)
        with self.assertRaises(nd.DecisionValidationError):
            ndj.append_decision_entry((c[1], c[0]), bound_record(), journal_id="journal-1")

    def test_e2_30b_append_checks_history_before_accessing_decision_fingerprint(self) -> None:
        # This test protects the M8-E2 append trust ordering: FULL HISTORY
        # VERIFICATION PRECEDES RECORD FINGERPRINT ACCESS. Not a claim of a
        # security boundary beyond this function's own call ordering - it
        # only proves append_decision_entry never reads
        # DecisionRecordContract.decision_fingerprint until AFTER the
        # supplied history has been proven structurally valid, so a
        # corrupt-history failure and a legacy-record failure are never
        # conflated. The patched property is restored automatically by the
        # context manager even if an assertion below fails - no global
        # state leaks between tests.
        c = chain(2)
        invalid_history = (c[1], c[0])  # wrong order -> PRESENTATION_ORDER_INVALID
        accessed: list[bool] = []
        original_property = nd.DecisionRecordContract.decision_fingerprint

        def spy(self):
            accessed.append(True)
            return original_property.fget(self)

        with mock.patch.object(nd.DecisionRecordContract, "decision_fingerprint", property(spy)):
            with self.assertRaises(nd.DecisionValidationError):
                ndj.append_decision_entry(invalid_history, unbound_record(), journal_id="journal-1")

        self.assertEqual(accessed, [], "decision_fingerprint must not be accessed before history verification")

    def test_e2_31_append_rejects_mixed_journal_history(self) -> None:
        e0 = genesis_entry(journal_id="A")
        e1b = ndj.DecisionJournalEntry(journal_id="B", sequence=1, decision_fingerprint=digest("d1"), previous_entry_fingerprint=e0.entry_fingerprint)
        with self.assertRaises(nd.DecisionValidationError):
            ndj.append_decision_entry((e0, e1b), bound_record(), journal_id="A")

    def test_e2_32_append_rejects_wrong_pinned_journal(self) -> None:
        c = chain(2, journal_id="B")
        with self.assertRaises(nd.DecisionValidationError):
            ndj.append_decision_entry(c, bound_record(), journal_id="A")

    def test_e2_33_append_rejects_unbound_legacy_decision_record(self) -> None:
        with self.assertRaises(nd.DecisionValidationError):
            ndj.append_decision_entry((), unbound_record(), journal_id="journal-1")

    def test_e2_34_append_obtains_fingerprint_from_decision_record(self) -> None:
        rec = bound_record()
        e0 = ndj.append_decision_entry((), rec, journal_id="journal-1")
        self.assertEqual(e0.decision_fingerprint, rec.decision_fingerprint)


# --- 13. Append correlation fields (item 35) ---------------------------------------------

class AppendCorrelationTests(unittest.TestCase):
    def test_e2_35_append_correlation_fields_do_not_alter_semantic_identity(self) -> None:
        rec = bound_record()
        e_a = ndj.append_decision_entry((), rec, journal_id="journal-1", record_ref="ref-a", recorded_at="2026-01-01T00:00:00Z")
        e_b = ndj.append_decision_entry((), rec, journal_id="journal-1", record_ref="ref-b", recorded_at="2030-01-01T00:00:00Z")
        self.assertEqual(e_a.entry_fingerprint, e_b.entry_fingerprint)


# --- 14. Append API surface (item 36) -----------------------------------------------------

class AppendApiSurfaceTests(unittest.TestCase):
    def test_e2_36_no_raw_decision_fingerprint_append_parameter(self) -> None:
        params = inspect.signature(ndj.append_decision_entry).parameters
        self.assertNotIn("decision_fingerprint", params)
        self.assertIn("decision_record", params)


# --- 15. Schema version, unaffected by E2 (item 37) ---------------------------------------

class SchemaVersionE2RegressionTests(unittest.TestCase):
    def test_e2_37_append_does_not_expose_schema_version_override(self) -> None:
        params = inspect.signature(ndj.append_decision_entry).parameters
        self.assertNotIn("schema_version", params)

    def test_e2_37b_appended_entry_uses_default_supported_schema_version(self) -> None:
        e0 = ndj.append_decision_entry((), bound_record(), journal_id="journal-1")
        self.assertEqual(e0.schema_version, nd.M8_DECISION_SCHEMA_VERSION)

    def test_e2_37c_verify_decision_journal_never_references_schema_version(self) -> None:
        # Direct proof (not a weaker proxy) that E2 imposes no cross-entry
        # schema-version equality requirement: verify_decision_journal's own
        # EXECUTABLE code - function docstring stripped, via
        # _executable_code_only - never references schema_version at all.
        # Each DecisionJournalEntry remains individually responsible for its
        # own supported-version validation (E1's _require_supported_schema_
        # version, unchanged). This deliberately asserts nothing about a
        # future multiple-schema-version world - only that E2 today adds no
        # same-version requirement across entries.
        source = _executable_code_only(ndj)
        start = source.index("def verify_decision_journal")
        end = source.index("def append_decision_entry")
        verify_source = source[start:end]
        self.assertNotIn("schema_version", verify_source)


# --- 16. Non-scope / safety (item 38 + static safety sweep) ------------------------------

class E2NonScopeSafetyTests(unittest.TestCase):
    def test_e2_38a_no_checkpoint_symbols(self) -> None:
        for name in ("JournalCheckpoint", "DecisionJournalCheckpoint", "CheckpointVerificationResult", "verify_checkpoint", "verify_journal_against_checkpoint"):
            self.assertFalse(hasattr(ndj, name))

    def test_e2_38b_no_replay_symbols(self) -> None:
        for name in ("replay_decision_journal", "ReplayResult", "SemanticReplay"):
            self.assertFalse(hasattr(ndj, name))

    def test_e2_38c_no_persistence_symbols(self) -> None:
        for name in ("write_journal", "save_journal", "load_journal", "read_journal", "JournalManager", "append_journal_file"):
            self.assertFalse(hasattr(ndj, name))

    def test_e2_38d_no_e3_e4_e5_terms_in_executable_code(self) -> None:
        source = _executable_code_only(ndj)
        for banned in (
            "JournalCheckpoint", "CheckpointVerificationResult", "verify_journal_against_checkpoint",
            "checkpoint", "replay", "manifest", "witness", "signing", "Merkle", "blockchain",
            "transparency", "JSONL", "sqlite", "fsync",
        ):
            self.assertNotIn(banned, source)

    def test_e2_38e_reason_codes_are_journal_domain_not_decision_domain(self) -> None:
        self.assertTrue(ndj.JOURNAL_REASON_CODES.isdisjoint(nd.DECISION_REASON_CODES))
        self.assertTrue(ndj.JOURNAL_REASON_CODES.isdisjoint(nd.DECISION_TRUTH_VALUES))
        self.assertTrue(ndj.JOURNAL_REASON_CODES.isdisjoint(nd.DECISION_VERDICTS))

    def test_e2_no_sorting_in_verify_decision_journal(self) -> None:
        source = _executable_code_only(ndj)
        self.assertNotIn("sorted(", source)
        self.assertNotIn(".sort(", source)

    def test_e2_no_second_hash_path(self) -> None:
        source = _executable_code_only(ndj)
        self.assertNotIn("hashlib", source)
        self.assertNotIn("hash(", source)

    def test_e2_no_io_clock_uuid_dependency(self) -> None:
        source = _executable_code_only(ndj)
        for banned in ("random.", "uuid.", "time.time(", "datetime.now(", "open(", "Path(", "subprocess", "requests", "os.system", "socket"):
            self.assertNotIn(banned, source)

    def test_e2_append_signature_uses_decision_record_contract(self) -> None:
        params = inspect.signature(ndj.append_decision_entry).parameters
        annotation = params["decision_record"].annotation
        self.assertIn("DecisionRecordContract", str(annotation))

    def test_e2_decision_journal_entry_semantic_payload_unchanged(self) -> None:
        # Regression guard: M8-E2 must not have touched E1's frozen contract.
        e = genesis_entry()
        self.assertEqual(set(e.semantic_payload()), {"journal_id", "sequence", "decision_fingerprint", "previous_entry_fingerprint", "schema_version"})

    def test_e2_dependency_direction_still_one_way(self) -> None:
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
