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


@dataclass(frozen=True)
class EvidenceBundle:
    """EVIDENCE_BUNDLE (F2b Rev 2.1 section 2.11): the evidence set frozen with a V3 release candidate.

    A marker with no fields because the check is COMPOSITE and fits none of the other shapes:
    it needs the RC's frozen state, its candidate_bindings resolved to real P18 results, the
    frozen evidence_refs snapshot resolved in the ledger, and class coverage against the union
    of every valid P11 plan and the P15 plans those P18 results name. No single artifact field,
    whole artifact, file, ledger kind or lifecycle collection expresses that.
    """


@dataclass(frozen=True)
class ReviewVerdict:
    """REVIEW_VERDICT (F2b Rev 2.1 section 2.6/2.6.1): the RC's independent review verdicts,
    checked pre-freeze at P18->P19 (see nogap_lifecycle.review_verdict_problem's docstring
    for why this never requires FROZEN/V3, unlike EVIDENCE_BUNDLE). A marker with no fields
    for the same reason EVIDENCE_BUNDLE has none: the check is composite and owned entirely
    by nogap_lifecycle.py, not expressible as a single artifact field/type/file/ledger kind.
    """


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
    "TEST_PLAN": ArtifactField("P11_GATE_PLAN", "required_tests"),

    # -- the kind names the whole artifact; its declared contract is the semantic check --
    "PROJECT_INTENT": WholeArtifact("P0_PROJECT_INTENT"),
    "GAP_ANALYSIS": WholeArtifact("P4_GAP_ANALYSIS"),
    "ARCHITECTURE": WholeArtifact("P7_ARCHITECTURE"),
    "ADR": WholeArtifact("P8_ADR"),
    "GOVERNANCE": WholeArtifact("P9_GOVERNANCE"),
    "BASELINE": WholeArtifact("P10_BASELINE"),
    "TASK_CONTRACT": WholeArtifact("P12_TASK_CONTRACT"),
    "VERIFICATION_PLAN": WholeArtifact("P15_VERIFICATION_PLAN"),
    "SCOPE": WholeArtifact("P1_SCOPE"),
    "METRICS": WholeArtifact("P10_BASELINE"),
    "PRIOR_ART_MAP": WholeArtifact("P3_PRIOR_ART"),

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

    # -- composite: the frozen RC's evidence bundle (section 2.11) --
    "EVIDENCE_BUNDLE": EvidenceBundle(),

    # -- composite: the RC's independent review verdicts, pre-freeze (section 2.6/2.6.1) --
    "REVIEW_VERDICT": ReviewVerdict(),
}


@dataclass(frozen=True)
class SemanticResolverSpec:
    """A named semantic resolver a phase contract may declare, and the ONE kind it is for."""

    kind: str


#: Closed registry of semantic resolvers a phase contract may declare in `semantic_resolvers`
#: (F2b Rev 2.1). Hand-written literal. nogap_methodology.py rejects any name not here and runs
#: `semantic_resolver_agreement_problem` at load time, so contract declaration, this registry
#: and the ENFORCED_KINDS implementation must all agree.
SEMANTIC_RESOLVERS: dict[str, SemanticResolverSpec] = {
    "EVIDENCE_BUNDLE_RESOLVER": SemanticResolverSpec(kind="EVIDENCE_BUNDLE"),
    "REVIEW_VERDICT_RESOLVER": SemanticResolverSpec(kind="REVIEW_VERDICT"),
}


def semantic_resolver_agreement_problem(kind: str, name: str) -> str | None:
    """Three-way agreement for one `{kind: name}` declaration; None when it holds."""
    spec = SEMANTIC_RESOLVERS.get(name)
    if spec is None:
        return f"references unknown resolver {name!r}"
    if spec.kind != kind:
        return f"resolver {name!r} is registered for kind {spec.kind!r}, not {kind!r}"
    if kind not in ENFORCED_KINDS:
        return f"resolver {name!r} is declared for {kind!r}, which has no implementation in ENFORCED_KINDS"
    return None

#: Declared by the methodology, semantics NOT yet decided. Enumerated, versioned and tested.
#: Each becomes an ENFORCED entry in F2b; none is guessed at in the meantime. Two of them are
#: already on the roadmap under their own names: MEMORY_CONFIGURATION is GP-9 and COST_MODEL is
#: GP-13, which is independent evidence that this list is a real contract gap rather than an
#: artifact of how the map was built.
DEFERRED_KINDS: frozenset[str] = frozenset({
    "REQUIREMENTS",           # plural kind, per-requirement artifacts: coverage rule undecided
    "COST_MODEL",             # GP-13
    "RUNTIME_STRUCTURE",      # no declared field in P9_GOVERNANCE
    "MEMORY_CONFIGURATION",   # GP-9
    "GOLDEN_GATES",           # no declared field in P11_GATE_PLAN
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


def _check_evidence_bundle_kind(
    project: Path, kind: str, spec: EvidenceBundle, refs: list[str],
) -> Verdict:
    """Section 2.11, per resolvable release candidate, first failing condition wins.

    Deliberately NOT here: any status judgment on P18 results or on evidence records (R3/R7:
    resolution and class presence are not acceptance), and any supersession concept for P11 or
    evidence (none exists in the schema).
    """
    # Same resolution approach as _check_lifecycle_kind: the lifecycle owner's loader.
    from nogap_artifacts import list_artifacts, validate_record
    from nogap_evidence_classes import EVIDENCE_CLASSES
    from nogap_evidence_ledger import read_evidence_ledger
    from nogap_lifecycle import (
        _load_one, has_fingerprint_frozen_candidate_bindings,
        has_fingerprint_frozen_evidence_bundle, resolve_candidate_bindings)
    from nogap_methodology import MethodologyValidationError

    def bundle_problem(ref: str, record: dict[str, Any]) -> str | None:
        if record.get("status") != "FROZEN":                                   # b
            return f"{ref} is not FROZEN (status={record.get('status')!r})"
        version = record.get("candidate_fingerprint_version")
        if version != "3":                                                     # c
            return f"{ref} has candidate_fingerprint_version={version!r}, not '3'"
        if not has_fingerprint_frozen_evidence_bundle(record):                 # d
            return f"{ref} has no fingerprint-frozen evidence bundle"
        if not has_fingerprint_frozen_candidate_bindings(record):              # e
            return f"{ref} has no fingerprint-frozen candidate_bindings"
        bindings = record.get("candidate_bindings")
        tasks = record.get("included_task_refs")
        if not isinstance(bindings, dict) or not isinstance(tasks, list):
            return f"{ref} candidate_bindings/included_task_refs are malformed"
        if set(bindings) != set(tasks):                                        # f
            return (f"{ref} candidate_bindings do not cover included_task_refs exactly: "
                    f"missing={sorted(set(tasks) - set(bindings))} "
                    f"extra={sorted(set(bindings) - set(tasks))}")
        try:                                                                   # g
            p18s = resolve_candidate_bindings(project, bindings)
        except MethodologyValidationError as exc:
            return f"{ref} candidate binding does not resolve: {exc}"
        snapshot = record["freeze_record"].get("evidence_refs")                # h
        if not isinstance(snapshot, list) or not snapshot:
            return f"{ref} frozen evidence_refs snapshot is empty or malformed"
        try:
            ledger = read_evidence_ledger(project)
        except MethodologyValidationError as exc:
            return f"{ref} evidence ledger will not read: {exc}"
        pairs = set(bindings.items())
        covered: set[str] = set()
        for eid in snapshot:                                                   # i
            path = ledger.ids.get(eid) if isinstance(eid, str) else None
            if path is None:
                return f"{ref} frozen evidence ref {eid!r} does not resolve in the evidence ledger"
            try:
                evidence = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return f"{ref} frozen evidence ref {eid!r} will not load: {exc}"
            if (not isinstance(evidence, dict) or evidence.get("id") != eid
                    or not isinstance(evidence.get("provenance"), dict)):
                return f"{ref} frozen evidence ref {eid!r} is a malformed evidence record"
            evidence_class = evidence.get("evidence_class")
            if evidence_class not in EVIDENCE_CLASSES:                         # j: legacy covers nothing
                continue
            provenance = evidence["provenance"]
            if (provenance.get("task_id"), provenance.get("candidate_hash")) not in pairs:
                continue                                                       # k: unbound covers nothing
            covered.add(evidence_class)
        p11s = [r for r in list_artifacts(project, artifact_type="P11_GATE_PLAN")
                if not validate_record(project, r)]
        if not p11s:                                                           # l
            return f"{ref}: no valid P11_GATE_PLAN in the project; an absent source is not an empty requirement"
        required: set[str] = set()
        for plan in p11s:
            values = plan["fields"].get("evidence_requirements")
            if not isinstance(values, list):
                return f"{ref}: {plan.get('artifact_id')} evidence_requirements is not a list"
            required |= set(values)
        p15s = [r for r in list_artifacts(project, artifact_type="P15_VERIFICATION_PLAN")
                if not validate_record(project, r)]
        for task_id, p18 in sorted(p18s.items()):
            plan_id = p18["fields"].get("verification_plan_id")
            plans = [r for r in p15s if r["fields"].get("verification_plan_id") == plan_id]
            if len(plans) != 1:
                return (f"{ref}: P18 {p18.get('artifact_id')} for {task_id!r} names verification_plan_id="
                        f"{plan_id!r}, which resolves to {len(plans)} valid P15_VERIFICATION_PLAN records")
            values = plans[0]["fields"].get("required_evidence_kinds")
            if not isinstance(values, list):
                return f"{ref}: {plans[0].get('artifact_id')} required_evidence_kinds is not a list"
            required |= set(values)
        missing = sorted(required - covered)                                   # m
        if missing:
            return (f"{ref} leaves required evidence class(es) uncovered by bound, classed "
                    f"frozen evidence: {missing}")
        return None

    problems: list[str] = []
    for ref in refs:                                                           # a
        if not isinstance(ref, str) or not ref.strip():
            continue
        try:
            record = _load_one(project, "release_candidates", ref)
        except MethodologyValidationError as exc:
            problems.append(f"{ref} will not load: {exc}")
            continue
        if record is None:
            continue
        problem = bundle_problem(ref, record)
        if problem is None:                                                    # o
            return Verdict(kind, PASS, f"{ref} (frozen V3 evidence bundle covers its required classes)")
        problems.append(problem)
    if problems:
        return Verdict(kind, INVALID, "; ".join(problems))
    return Verdict(kind, MISSING, "no resolvable release candidate")


def _check_review_verdict_kind(
    project: Path, kind: str, spec: ReviewVerdict, refs: list[str],
) -> Verdict:
    """Delegates entirely to nogap_lifecycle.review_verdict_problem - the owner module for
    candidate_bindings/RC resolution (mirrors _check_evidence_bundle_kind's use of the same
    module for the same reason: this file declares WHAT a kind means, not how RC/P18/evidence
    records are loaded and cross-checked)."""
    from nogap_lifecycle import _load_one, review_verdict_problem
    from nogap_methodology import MethodologyValidationError

    problems: list[str] = []
    for ref in refs:
        if not isinstance(ref, str) or not ref.strip():
            continue
        try:
            record = _load_one(project, "release_candidates", ref)
        except MethodologyValidationError as exc:
            problems.append(f"{ref} will not load: {exc}")
            continue
        if record is None:
            continue
        try:
            problem = review_verdict_problem(project, ref)
        except MethodologyValidationError as exc:
            problems.append(f"{ref} candidate binding does not resolve: {exc}")
            continue
        if problem is None:
            return Verdict(kind, PASS, f"{ref} (every candidate_bindings P18 carries a valid review verdict)")
        problems.append(problem)
    if problems:
        return Verdict(kind, INVALID, "; ".join(problems))
    return Verdict(kind, MISSING, "no resolvable release candidate")


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
        elif isinstance(spec, EvidenceBundle):
            verdicts.append(_check_evidence_bundle_kind(project, kind, spec, refs))
        elif isinstance(spec, ReviewVerdict):
            verdicts.append(_check_review_verdict_kind(project, kind, spec, refs))
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
