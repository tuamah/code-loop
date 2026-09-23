#!/usr/bin/env python3
"""F2a: what a phase's `required_artifacts` actually demands.

The rule this replaces was `if current.required_artifacts and not artifact_refs` - a non-empty
list satisfied it. Not the right kind, not valid, not bound to anything, not even existing: the
string "definitely-not-an-artifact" closed out any phase in the methodology.

The obvious repair - "the artifact must be of this phase's type" - is only a more elegant
version of the same hole. A container of the right type does not prove the required MEANING is
inside it, and deriving the demanded type from the phase's own type answers a question the
contract never asked: P14 OWNS P14_SELF_CHECK but REQUIRES EXECUTION_EVIDENCE, so the derived
rule demands an artifact the contract does not mention.

So the unit of checking is the declared semantic KIND, each proven INDEPENDENTLY:

    required kind -> closed resolver map -> resolver class -> concrete type/class
                  -> structural validation -> semantic content -> contextual binding
                  -> freshness -> verdict

**Nothing here is derived from a name.** `SCOPE` is not mapped to a field called `scope`,
because no such field is declared - `P1_SCOPE` declares `in_scope` and `out_of_scope`. Guessing
would be inventing the contract. Every mapping below comes from an actual declaration, and a
kind that has no declaration is not guessed at.

**Two closed sets, and nothing outside them.**

* ENFORCED_KINDS - checked for real.
* DEFERRED_KINDS - declared in the methodology, not yet given a semantic mapping, reported as
  SEMANTIC_VALIDATION_DEFERRED. Never PASS. This is deliberately its own state rather than
  "unmapped, enforcement off": an exception inside the decision engine is the shape that rots
  into a silent bypass, which this codebase has had to remove twice already.

A kind in neither set fails UNMAPPED. There is no generic "ignore what we do not recognize",
and a test asserts the two sets exactly partition what the phase contracts declare, so adding a
requirement to the methodology without deciding its meaning breaks CI rather than passing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# -- verdicts -------------------------------------------------------------------------------

PASS = "PASS"
MISSING = "MISSING"
WRONG_TYPE = "WRONG_TYPE"
INVALID = "INVALID"
STALE = "STALE"
OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
UNMAPPED = "UNMAPPED"
DEFERRED = "SEMANTIC_VALIDATION_DEFERRED"

# -- outcomes: three meanings, never two ------------------------------------------------------
#
# The result is deliberately TRI-STATE. An earlier draft put DEFERRED into a set called
# SATISFYING, so any later caller could ask `result in SATISFYING` and treat "we have not
# decided what this means yet" as "this was verified". Two meanings squeezed into one boolean
# is how a temporary compatibility allowance becomes a permanent silent pass.

VALIDATED = "VALIDATED"   # checked, against a declared mapping, and it holds
DEFERRED_OUTCOME = "DEFERRED"    # declared by the methodology, meaning not yet decided (F2b)
REJECTED = "REJECTED"     # checked and it does not hold, or has no declared meaning at all

#: F2a's transition policy, stated once and by name: a phase may proceed on VALIDATED or
#: DEFERRED. It is a POLICY about an undecided mapping, not evidence about the artifact, and it
#: is written here so that tightening it in F2b is a one-line change to a named rule rather
#: than an archaeology exercise across every caller.
F2A_ALLOWS_TRANSITION = frozenset({VALIDATED, DEFERRED_OUTCOME})

#: An artifact in one of these states was real once, which is exactly why it is named here.
NON_SATISFYING_STATUSES = frozenset({"SUPERSEDED", "REJECTED", "INVALIDATED"})


@dataclass(frozen=True)
class Verdict:
    """One required kind, one answer, and the reason - never a bare boolean."""

    kind: str
    status: str
    detail: str = ""

    @property
    def outcome(self) -> str:
        """VALIDATED / DEFERRED / REJECTED - the three meanings, kept apart."""
        if self.status == PASS:
            return VALIDATED
        if self.status == DEFERRED:
            return DEFERRED_OUTCOME
        return REJECTED

    @property
    def blocks_transition(self) -> bool:
        """Under F2a's policy. Never `satisfied`: nothing here says DEFERRED was verified."""
        return self.outcome not in F2A_ALLOWS_TRANSITION

    def __str__(self) -> str:
        return f"{self.kind} -> {self.status}" + (f": {self.detail}" if self.detail else "")


# -- the closed map -------------------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactField:
    """The kind names a declared FIELD of a declared artifact type."""

    artifact_type: str
    field: str


@dataclass(frozen=True)
class WholeArtifact:
    """The kind names the artifact itself, so its own type contract IS the semantic check."""

    artifact_type: str


@dataclass(frozen=True)
class ProjectFile:
    """The kind names a file produced by the work, not a record about it.

    `must_be_non_empty` defaults to FALSE and PATCH does not set it. An empty patch is a real
    and meaningful outcome - a command that ran cleanly and changed nothing - and the runtime
    has golden regression tests for exactly that case. Requiring content would have been my
    invention rather than a declaration, and it rejected three legitimate zero-effect
    executions the first time this ran. The declared requirement is that the file EXISTS and
    is inside the project; emptiness is a fact about the result, not a defect in the reference.
    """

    must_be_non_empty: bool = False


@dataclass(frozen=True)
class LedgerEvidence:
    """The kind names PROOF, which lives in the runtime evidence ledger.

    A patch is the object under inspection; evidence is the record of what happened to it, by
    whom, under which run and binding. Letting a patch path satisfy a requirement named
    `*_EVIDENCE` confuses the two, so these resolve against the ledger and nowhere else.
    """

    kinds: tuple[str, ...]
    authorities: tuple[str, ...] = ()


@dataclass(frozen=True)
class LifecycleRecord:
    """The kind names a lifecycle record (release candidate, readiness, deployment...)."""

    collection: str


#: Every mapping below is taken from an actual declaration: an exact field name in
#: ARTIFACT_TYPES, a type whose name the kind repeats, or a resolver class decided explicitly.
ENFORCED_KINDS: dict[str, Any] = {
    # -- declared FIELD of a declared type (exact matches in ARTIFACT_TYPES.required_fields) --
    "PROBLEM_STATEMENT": ArtifactField("P1_SCOPE", "problem_statement"),
    "CONSTRAINTS": ArtifactField("P1_SCOPE", "constraints"),
    "SUCCESS_CRITERIA": ArtifactField("P2_SUCCESS_CRITERIA", "success_criteria"),
    "FAILURE_CRITERIA": ArtifactField("P2_SUCCESS_CRITERIA", "failure_criteria"),
    "CLAIM_STRENGTH": ArtifactField("P2_SUCCESS_CRITERIA", "claim_strength"),
    "RISK_LEVEL": ArtifactField("P2_SUCCESS_CRITERIA", "risk_level"),
    "TRUST_BOUNDARIES": ArtifactField("P7_ARCHITECTURE", "trust_boundaries"),
    "STRATEGY_DECISION": ArtifactField("P5_STRATEGY_DECISION", "selected_strategy"),
    "BENCHMARK_PROTOCOL": ArtifactField("P10_BASELINE", "measurement_procedure"),

    # -- the kind names the whole artifact; its declared contract is the semantic check --
    "PROJECT_INTENT": WholeArtifact("P0_PROJECT_INTENT"),
    "GAP_ANALYSIS": WholeArtifact("P4_GAP_ANALYSIS"),
    "ARCHITECTURE": WholeArtifact("P7_ARCHITECTURE"),
    "ADR": WholeArtifact("P8_ADR"),
    "GOVERNANCE": WholeArtifact("P9_GOVERNANCE"),
    "BASELINE": WholeArtifact("P10_BASELINE"),
    "TASK_CONTRACT": WholeArtifact("P12_TASK_CONTRACT"),
    "VERIFICATION_PLAN": WholeArtifact("P15_VERIFICATION_PLAN"),

    # -- a file produced by the work --
    "PATCH": ProjectFile(),

    # -- proof, resolved against the runtime evidence ledger --
    "EXECUTION_EVIDENCE": LedgerEvidence(kinds=("execution",), authorities=("execution",)),
    "DETERMINISTIC_VERIFICATION_EVIDENCE": LedgerEvidence(
        kinds=("test", "review"), authorities=("verification",)),
    "REPRODUCIBILITY_EVIDENCE": LedgerEvidence(
        kinds=("test", "review", "skip"), authorities=("verification", "methodology")),

    # -- lifecycle records --
    "RELEASE_CANDIDATE": LifecycleRecord("release_candidates"),
    "RELEASE_READINESS_CHECKLIST": LifecycleRecord("release_readiness"),
    "OPERATIONAL_OBSERVATIONS": LifecycleRecord("operations"),
    "IMPROVEMENT_PROPOSAL": LifecycleRecord("improvements"),
    "LIFECYCLE_DECISION": LifecycleRecord("lifecycle_decisions"),
}

#: Declared by the methodology, semantics NOT yet decided. Enumerated, versioned and tested.
#: Each becomes an ENFORCED entry in F2b; none is guessed at in the meantime. Two of them are
#: already on the roadmap under their own names: MEMORY_CONFIGURATION is GP-9 and COST_MODEL is
#: GP-13, which is independent evidence that this list is a real contract gap rather than an
#: artifact of how the map was built.
DEFERRED_KINDS: frozenset[str] = frozenset({
    "SCOPE",                  # P1_SCOPE declares in_scope/out_of_scope; no field named "scope"
    "PRIOR_ART_MAP",          # P3_PRIOR_ART declares no "map" field
    "REQUIREMENTS",           # plural kind, per-requirement artifacts: coverage rule undecided
    "COST_MODEL",             # GP-13
    "RUNTIME_STRUCTURE",      # no declared field in P9_GOVERNANCE
    "MEMORY_CONFIGURATION",   # GP-9
    "METRICS",                # P10 declares primary_metric/secondary_metrics; coverage unclear
    "GOLDEN_GATES",           # no declared field in P11_GATE_PLAN
    "TEST_PLAN",              # no declared field in P11_GATE_PLAN
    "REVIEW_VERDICT",         # P18 declares independent_review_result; binding rule undecided
    "EVIDENCE_BUNDLE",        # no record type of its own anywhere in nogap_lifecycle. The
                              # first draft mapped it to release_candidates because an RC
                              # carries evidence_refs - a judgement, not a declaration, and
                              # exactly the invention this map exists to prevent.
})


def declared_required_kinds(methodology_dir: Path | None = None) -> set[str]:
    """Every kind any phase contract declares. The source of truth for the partition guard."""
    from nogap_methodology import METHODOLOGY_DIR

    directory = Path(methodology_dir) if methodology_dir else METHODOLOGY_DIR
    kinds: set[str] = set()
    for path in sorted((directory / "phases").glob("p*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        kinds.update(data.get("required_artifacts") or [])
    return kinds


# -- resolution -------------------------------------------------------------------------------


def _is_project_file(project: Path, ref: str) -> Path | None:
    """A file reference: real, and INSIDE the project. Containment is checked after resolving,
    so "../../etc/passwd" is not a satisfied requirement."""
    root = project.resolve()
    try:
        candidate = Path(ref) if Path(ref).is_absolute() else (root / ref)
        candidate = candidate.resolve()
        candidate.relative_to(root)
    except (ValueError, OSError):
        return None
    return candidate if candidate.is_file() else None


def _load_evidence(project: Path) -> dict[str, dict[str, Any]]:
    directory = project.resolve() / ".code-loop" / "runtime" / "evidence"
    records: dict[str, dict[str, Any]] = {}
    if not directory.is_dir():
        return records
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("id"), str):
            records[data["id"]] = data
    return records


def _resolved_artifacts(project: Path, refs: list[str]) -> dict[str, dict[str, Any]]:
    from nogap_artifacts import load_artifact
    from nogap_methodology import MethodologyValidationError

    found: dict[str, dict[str, Any]] = {}
    for ref in refs:
        if not isinstance(ref, str) or not ref.strip():
            continue
        try:
            record = load_artifact(project, ref)
        except MethodologyValidationError:
            continue
        if record is not None:
            found[ref] = record
    return found


def _check_artifact_kind(
    project: Path, kind: str, spec: Any, artifacts: dict[str, dict[str, Any]],
) -> Verdict:
    """Shared by ArtifactField and WholeArtifact: resolve, type, freshness, contract, content.

    The order matters for the REPORT, not just the result: a caller who supplied a superseded
    artifact of the right type should be told it is stale, not that it is the wrong type.
    """
    from nogap_artifacts import validate_record

    wanted = spec.artifact_type
    of_type = {ref: rec for ref, rec in artifacts.items()
               if rec.get("artifact_type") == wanted}
    if not of_type:
        if artifacts:
            supplied = sorted({str(r.get("artifact_type")) for r in artifacts.values()})
            return Verdict(kind, WRONG_TYPE,
                           f"needs {wanted}; the references supplied are {supplied}")
        return Verdict(kind, MISSING, f"no reference resolved to a {wanted} artifact")

    problems: list[str] = []
    for ref, record in sorted(of_type.items()):
        status = record.get("status")
        if status in NON_SATISFYING_STATUSES:
            problems.append(f"{ref} is {status}")
            continue
        invalid = validate_record(project, record)
        if invalid:
            problems.append(f"{ref} fails its own contract: {'; '.join(invalid)}")
            continue
        if isinstance(spec, ArtifactField):
            value = record.get("fields", {}).get(spec.field)
            if value is None or (hasattr(value, "__len__") and len(value) == 0) or (
                    isinstance(value, str) and not value.strip()):
                # The point of F2a: the right container does not prove the required meaning is
                # inside it. A valid P1_SCOPE with an empty problem_statement satisfies the
                # TYPE and fails the KIND.
                problems.append(f"{ref} carries no {spec.field}")
                continue
        return Verdict(kind, PASS, f"{ref} ({wanted})")

    stale_only = all("is SUPERSEDED" in p or "is REJECTED" in p or "is INVALIDATED" in p
                     for p in problems)
    return Verdict(kind, STALE if stale_only else INVALID, "; ".join(problems))


def _check_file_kind(project: Path, kind: str, spec: ProjectFile, refs: list[str]) -> Verdict:
    outside: list[str] = []
    empty: list[str] = []
    for ref in refs:
        if not isinstance(ref, str) or not ref.strip():
            continue
        path = _is_project_file(project, ref)
        if path is None:
            # Distinguish "points outside the project" from "not a file at all": one is an
            # attempted escape and the other is a typo, and they deserve different answers.
            try:
                probe = (Path(ref) if Path(ref).is_absolute() else project.resolve() / ref).resolve()
                probe.relative_to(project.resolve())
            except (ValueError, OSError):
                outside.append(ref)
            continue
        if spec.must_be_non_empty and path.stat().st_size == 0:
            empty.append(ref)
            continue
        return Verdict(kind, PASS, str(path))
    if outside:
        return Verdict(kind, OUT_OF_BOUNDS,
                       f"reference(s) outside the project boundary: {outside}")
    if empty:
        return Verdict(kind, INVALID, f"file(s) present but empty: {empty}")
    return Verdict(kind, MISSING, "no reference resolved to a file inside the project")


def _check_evidence_kind(
    project: Path, kind: str, spec: LedgerEvidence, refs: list[str],
) -> Verdict:
    """Proof, resolved against the ledger - never against a patch.

    An id that exists is not enough. The record must be of an accepted evidence kind, carry the
    authority that is entitled to produce it, and be bound to a run: evidence that names no run
    proves something happened somewhere, which is not the same as proving it happened here.
    """
    ledger = _load_evidence(project)
    if not ledger:
        return Verdict(kind, MISSING, "the runtime evidence ledger is empty or absent")

    problems: list[str] = []
    for ref in refs:
        if not isinstance(ref, str) or ref not in ledger:
            continue
        record = ledger[ref]
        record_kind = record.get("kind")
        if spec.kinds and record_kind not in spec.kinds:
            problems.append(f"{ref} is kind={record_kind!r}, not one of {list(spec.kinds)}")
            continue
        provenance = record.get("provenance") or {}
        authority = provenance.get("authority")
        if spec.authorities and authority not in spec.authorities:
            problems.append(
                f"{ref} was produced under authority={authority!r}, not one of "
                f"{list(spec.authorities)}")
            continue
        if not record.get("run_id"):
            problems.append(f"{ref} is bound to no run_id")
            continue
        if not provenance.get("actor_id"):
            problems.append(f"{ref} carries no actor_id provenance")
            continue
        if record.get("status") in NON_SATISFYING_STATUSES:
            problems.append(f"{ref} is {record.get('status')}")
            continue
        return Verdict(kind, PASS, f"{ref} (kind={record_kind}, authority={authority})")

    if problems:
        stale = all("is SUPERSEDED" in p or "is REJECTED" in p or "is INVALIDATED" in p
                    for p in problems)
        return Verdict(kind, STALE if stale else INVALID, "; ".join(problems))
    return Verdict(kind, MISSING,
                   "no reference resolved to an evidence record in the runtime ledger")


def _check_lifecycle_kind(
    project: Path, kind: str, spec: LifecycleRecord, refs: list[str],
) -> Verdict:
    # Resolved through the module that OWNS lifecycle storage, not by rebuilding its layout
    # here. The first version of this reimplemented the path and got the collection name for
    # OPERATIONAL_OBSERVATIONS wrong; a resolver that duplicates a storage layout is a second
    # copy of it, free to drift from the real one.
    from nogap_lifecycle import _load_one
    from nogap_methodology import MethodologyValidationError

    problems: list[str] = []
    for ref in refs:
        if not isinstance(ref, str) or not ref.strip():
            continue
        try:
            record = _load_one(project, spec.collection, ref)
        except MethodologyValidationError as exc:
            problems.append(f"{ref} will not load: {exc}")
            continue
        if record is None:
            continue
        status = record.get("status")
        if status in NON_SATISFYING_STATUSES:
            problems.append(f"{ref} is {status}")
            continue
        return Verdict(kind, PASS, f"{ref} ({spec.collection}, status={status})")
    if problems:
        stale = all("is SUPERSEDED" in p or "is REJECTED" in p or "is INVALIDATED" in p
                    for p in problems)
        return Verdict(kind, STALE if stale else INVALID, "; ".join(problems))
    return Verdict(kind, MISSING,
                   f"no reference resolved to a {spec.collection} record")


def check_required_kinds(
    project: Path, required_kinds: list[str], artifact_refs: list[str],
) -> list[Verdict]:
    """One verdict per required kind, each proven INDEPENDENTLY.

    Independence is the invariant: a single reference may satisfy several kinds only when each
    kind separately verified its own content against it. Without that, "one matching artifact
    closes the phase" is the old hole with extra steps.
    """
    refs = [r for r in artifact_refs if isinstance(r, str) and r.strip()]
    artifacts = _resolved_artifacts(project, refs)

    verdicts: list[Verdict] = []
    for kind in required_kinds:
        if kind in DEFERRED_KINDS:
            verdicts.append(Verdict(kind, DEFERRED,
                                    "declared by the methodology; semantic mapping not yet "
                                    "decided (F2b). Never reported as verified."))
            continue
        spec = ENFORCED_KINDS.get(kind)
        if spec is None:
            verdicts.append(Verdict(
                kind, UNMAPPED,
                "not in ENFORCED_KINDS and not in DEFERRED_KINDS; a requirement with no "
                "declared meaning fails closed rather than passing by default"))
        elif isinstance(spec, (ArtifactField, WholeArtifact)):
            verdicts.append(_check_artifact_kind(project, kind, spec, artifacts))
        elif isinstance(spec, ProjectFile):
            verdicts.append(_check_file_kind(project, kind, spec, refs))
        elif isinstance(spec, LedgerEvidence):
            verdicts.append(_check_evidence_kind(project, kind, spec, refs))
        elif isinstance(spec, LifecycleRecord):
            verdicts.append(_check_lifecycle_kind(project, kind, spec, refs))
        else:  # pragma: no cover - the map is closed and tested
            verdicts.append(Verdict(kind, UNMAPPED, f"unknown resolver class {type(spec)}"))
    return verdicts


def blocking(verdicts: list[Verdict]) -> list[Verdict]:
    """The verdicts that stop a transition under F2a's policy."""
    return [v for v in verdicts if v.blocks_transition]


def report(verdicts: list[Verdict]) -> str:
    """Explainable by construction: every kind, its outcome, and why.

    DEFERRED appears under its own name in the report and is never rendered as PASS, so a
    reader can see at a glance which requirements were verified and which merely have no
    decided meaning yet.
    """
    return "\n".join(f"  {v.kind}: {v.outcome} ({v.status})"
                      + (f" - {v.detail}" if v.detail else "") for v in verdicts)
