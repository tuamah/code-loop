#!/usr/bin/env python3
"""Methodology contracts (M7-A) + project intent / adaptive depth (M7-B).

M7-A loads and validates the static methodology contracts under methodology/.
M7-B adds per-project state: ProjectIntent, RiskLevel, ClaimStrength, and a
deterministic ProcessDepth (profile) derivation, plus explicit phase-level
escalation and attributed, logged, project-level downgrade. Both stay
standalone: nogap.py only gets a thin `methodology` subcommand that calls into
this module - "Methodology logic MUST NOT be embedded throughout nogap.py."

There is still no P0-P23 transition engine here (that is M7-C): a freshly
initialized project's current_phase is always "P0" with no transition logic
behind it - that is a starting value, not a state machine.

Fails closed throughout: any malformed contract or state file, any reference
to an unknown phase/macro_phase/loop/principle/profile/intent/risk/claim
strength, or a downgrade attempted without an explicit actor and reason,
raises MethodologyValidationError. There is no silent-partial-load path and
no silent downgrade path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
METHODOLOGY_DIR = ROOT / "methodology"

MACRO_PHASES = {"DEFINE", "RESEARCH", "DESIGN", "PREPARE", "BUILD", "VERIFY", "RELEASE", "OPERATE", "EVOLVE"}
LOOPS = {"research_loop", "build_loop", "verify_loop", "repair_loop", "improvement_loop"}
PROFILES = {"LIGHT", "STANDARD", "STRICT"}
PRINCIPLE_CLASSES = {"A", "B", "C"}
LOOP_STATUSES = {"ACTIVE", "RESOLVED", "BLOCKED", "INCONCLUSIVE"}


class MethodologyValidationError(Exception):
    """Raised for any malformed contract or unknown reference. Fail closed, never partial-load."""


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise MethodologyValidationError(f"missing required file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MethodologyValidationError(f"{path} is invalid JSON: {exc}") from exc


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MethodologyValidationError(message)


@dataclass
class PhaseContract:
    id: str
    macro_phase: str
    name: str
    exit_gate: dict[str, Any]
    allowed_next: list[str]
    allowed_back_transitions: list[str]
    failure_transition: str | None
    minimum_profile: str
    loop: str | None = None
    required_inputs: list[str] = field(default_factory=list)
    required_artifacts: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    required_roles: list[str] = field(default_factory=list)


@dataclass
class Principle:
    id: str
    name: str
    statement: str
    cls: str


@dataclass
class ProcessProfile:
    id: str
    name: str
    description: str
    skippable_phases: list[str]


@dataclass
class MethodologyDefinition:
    methodology_id: str
    version: str
    macro_phases: list[str]
    subphases: list[str]
    loops: list[str]
    principle_ids: list[str]
    phases: dict[str, PhaseContract]
    principles: dict[str, Principle]
    profiles: dict[str, ProcessProfile]

    def get_phase(self, phase_id: str) -> PhaseContract:
        if phase_id not in self.phases:
            raise MethodologyValidationError(f"unknown phase: {phase_id}")
        return self.phases[phase_id]

    def get_principle(self, principle_id: str) -> Principle:
        if principle_id not in self.principles:
            raise MethodologyValidationError(f"unknown principle: {principle_id}")
        return self.principles[principle_id]

    def get_profile(self, profile_id: str) -> ProcessProfile:
        if profile_id not in self.profiles:
            raise MethodologyValidationError(f"unknown profile: {profile_id}")
        return self.profiles[profile_id]

    def phases_in_macro(self, macro_phase: str) -> list[PhaseContract]:
        _require(macro_phase in self.macro_phases, f"unknown macro phase: {macro_phase}")
        return [phase for phase in self.phases.values() if phase.macro_phase == macro_phase]


def _parse_phase_contract(data: Any, source: Path) -> PhaseContract:
    _require(isinstance(data, dict), f"{source}: phase contract must be a JSON object")
    for key in ("id", "macro_phase", "name", "exit_gate", "allowed_next", "allowed_back_transitions", "minimum_profile"):
        _require(key in data, f"{source}: missing required field {key!r}")
    _require(isinstance(data["id"], str) and data["id"].startswith("P"), f"{source}: id must be a P-prefixed string")
    _require(data["macro_phase"] in MACRO_PHASES, f"{source}: unknown macro_phase {data['macro_phase']!r}")
    loop = data.get("loop")
    _require(loop is None or loop in LOOPS, f"{source}: unknown loop {loop!r}")
    _require(data["minimum_profile"] in PROFILES, f"{source}: unknown minimum_profile {data['minimum_profile']!r}")
    gate = data["exit_gate"]
    _require(isinstance(gate, dict) and "description" in gate and "checks" in gate, f"{source}: exit_gate must have description and checks")
    _require(isinstance(gate["checks"], list) and len(gate["checks"]) >= 1, f"{source}: exit_gate.checks must be a non-empty list")
    failure_transition = data.get("failure_transition")
    _require(
        failure_transition is None or (isinstance(failure_transition, str) and (failure_transition == "REPAIR_LOOP" or failure_transition.startswith("P"))),
        f"{source}: failure_transition must be null, a phase id, or REPAIR_LOOP",
    )
    return PhaseContract(
        id=data["id"],
        macro_phase=data["macro_phase"],
        name=data["name"],
        exit_gate=gate,
        allowed_next=list(data["allowed_next"]),
        allowed_back_transitions=list(data["allowed_back_transitions"]),
        failure_transition=failure_transition,
        minimum_profile=data["minimum_profile"],
        loop=loop,
        required_inputs=list(data.get("required_inputs", [])),
        required_artifacts=list(data.get("required_artifacts", [])),
        required_evidence=list(data.get("required_evidence", [])),
        required_roles=list(data.get("required_roles", [])),
    )


def load_methodology(methodology_dir: Path = METHODOLOGY_DIR) -> MethodologyDefinition:
    top = _read_json(methodology_dir / "methodology.json")
    _require(isinstance(top, dict), "methodology.json must be a JSON object")
    for key in ("methodology_id", "version", "macro_phases", "subphases", "loops", "principles"):
        _require(key in top, f"methodology.json missing required field {key!r}")
    for macro in top["macro_phases"]:
        _require(macro in MACRO_PHASES, f"methodology.json: unknown macro_phase {macro!r}")
    for loop in top["loops"]:
        _require(loop in LOOPS, f"methodology.json: unknown loop {loop!r}")

    phases_dir = methodology_dir / "phases"
    phase_files = sorted(phases_dir.glob("p*.json")) if phases_dir.is_dir() else []
    _require(bool(phase_files), f"no phase files found under {phases_dir}")
    phases: dict[str, PhaseContract] = {}
    for path in phase_files:
        contract = _parse_phase_contract(_read_json(path), path)
        _require(contract.id not in phases, f"duplicate phase id {contract.id} in {path}")
        phases[contract.id] = contract

    declared_subphases = set(top["subphases"])
    found_subphases = set(phases)
    _require(
        declared_subphases == found_subphases,
        "methodology.json subphases do not match phase files on disk: "
        f"declared-only={sorted(declared_subphases - found_subphases)}, "
        f"file-only={sorted(found_subphases - declared_subphases)}",
    )

    used_macro_phases = {phase.macro_phase for phase in phases.values()}
    _require(
        used_macro_phases == set(top["macro_phases"]),
        "methodology.json macro_phases do not match macro phases actually used by phase contracts: "
        f"declared-only={sorted(set(top['macro_phases']) - used_macro_phases)}, "
        f"used-only={sorted(used_macro_phases - set(top['macro_phases']))}",
    )

    for phase in phases.values():
        for ref in (*phase.allowed_next, *phase.allowed_back_transitions):
            _require(ref in phases, f"{phase.id}: references unknown phase {ref!r}")
        if phase.failure_transition and phase.failure_transition != "REPAIR_LOOP":
            _require(phase.failure_transition in phases, f"{phase.id}: failure_transition references unknown phase {phase.failure_transition!r}")

    principles_data = _read_json(methodology_dir / "principles.json")
    _require(isinstance(principles_data, dict) and isinstance(principles_data.get("principles"), list), "principles.json must contain a 'principles' array")
    principles: dict[str, Principle] = {}
    for entry in principles_data["principles"]:
        for key in ("id", "name", "statement", "class"):
            _require(key in entry, f"principles.json: entry missing required field {key!r}")
        _require(entry["class"] in PRINCIPLE_CLASSES, f"principles.json: {entry.get('id')} has unknown class {entry['class']!r}")
        _require(entry["id"] not in principles, f"principles.json: duplicate principle id {entry['id']}")
        principles[entry["id"]] = Principle(id=entry["id"], name=entry["name"], statement=entry["statement"], cls=entry["class"])

    declared_principles = set(top["principles"])
    found_principles = set(principles)
    _require(
        declared_principles == found_principles,
        "methodology.json principles do not match principles.json: "
        f"declared-only={sorted(declared_principles - found_principles)}, "
        f"file-only={sorted(found_principles - declared_principles)}",
    )

    profiles_dir = methodology_dir / "profiles"
    profile_files = sorted(profiles_dir.glob("*.json")) if profiles_dir.is_dir() else []
    _require(bool(profile_files), f"no profile files found under {profiles_dir}")
    profiles: dict[str, ProcessProfile] = {}
    for path in profile_files:
        data = _read_json(path)
        for key in ("id", "name", "description", "skippable_phases"):
            _require(key in data, f"{path}: missing required field {key!r}")
        _require(data["id"] in PROFILES, f"{path}: unknown profile id {data['id']!r}")
        for phase_id in data["skippable_phases"]:
            _require(phase_id in phases, f"{path}: skippable_phases references unknown phase {phase_id!r}")
        profiles[data["id"]] = ProcessProfile(
            id=data["id"], name=data["name"], description=data["description"],
            skippable_phases=list(data["skippable_phases"]),
        )
    _require(set(profiles) == PROFILES, f"expected profiles {sorted(PROFILES)}, found {sorted(profiles)}")

    return MethodologyDefinition(
        methodology_id=top["methodology_id"],
        version=top["version"],
        macro_phases=list(top["macro_phases"]),
        subphases=list(top["subphases"]),
        loops=list(top["loops"]),
        principle_ids=list(top["principles"]),
        phases=phases,
        principles=principles,
        profiles=profiles,
    )


# ---------------------------------------------------------------------------
# M7-B: Project Intent + Adaptive Depth
# ---------------------------------------------------------------------------

INTENTS = {"research", "production", "experimental"}
RISK_LEVELS = {"low", "medium", "high"}
CLAIM_STRENGTHS = {"low", "medium", "high"}
PROFILE_ORDER = {"LIGHT": 0, "STANDARD": 1, "STRICT": 2}

# Deterministic, disclosed derivation: raw_score = max(risk, claim_strength, intent floor).
# production always floors at STANDARD regardless of risk/claim, because production work
# affects real users even when a specific task looks low-risk. research/experimental have
# no such floor - their depth comes entirely from the stated risk and claim strength.
_RISK_SCORE = {"low": 0, "medium": 1, "high": 2}
_CLAIM_SCORE = {"low": 0, "medium": 1, "high": 2}
_INTENT_FLOOR = {"experimental": 0, "research": 0, "production": 1}
_SCORE_TO_PROFILE = {0: "LIGHT", 1: "STANDARD", 2: "STRICT"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class ProfileDerivation:
    """The disclosed *why* behind a derived profile - never hidden from the caller."""

    intent: str
    risk: str
    claim_strength: str
    risk_score: int
    claim_score: int
    intent_floor: int
    raw_score: int
    profile: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent, "risk": self.risk, "claim_strength": self.claim_strength,
            "risk_score": self.risk_score, "claim_score": self.claim_score, "intent_floor": self.intent_floor,
            "raw_score": self.raw_score, "profile": self.profile, "reason": self.reason,
        }


def derive_profile(intent: str, risk: str, claim_strength: str) -> ProfileDerivation:
    _require(intent in INTENTS, f"unknown intent: {intent!r}; must be one of {sorted(INTENTS)}")
    _require(risk in RISK_LEVELS, f"unknown risk level: {risk!r}; must be one of {sorted(RISK_LEVELS)}")
    _require(claim_strength in CLAIM_STRENGTHS, f"unknown claim strength: {claim_strength!r}; must be one of {sorted(CLAIM_STRENGTHS)}")
    risk_score = _RISK_SCORE[risk]
    claim_score = _CLAIM_SCORE[claim_strength]
    intent_floor = _INTENT_FLOOR[intent]
    raw_score = max(risk_score, claim_score, intent_floor)
    profile = _SCORE_TO_PROFILE[raw_score]
    drivers = []
    if risk_score == raw_score:
        drivers.append(f"risk={risk}")
    if claim_score == raw_score:
        drivers.append(f"claim_strength={claim_strength}")
    if intent_floor == raw_score and intent_floor > 0:
        drivers.append(f"intent={intent} floor")
    reason = f"{profile} driven by " + " and ".join(drivers) if drivers else f"{profile} (all factors at minimum)"
    return ProfileDerivation(intent, risk, claim_strength, risk_score, claim_score, intent_floor, raw_score, profile, reason)


def methodology_state_dir(project: Path) -> Path:
    return project.resolve() / ".code-loop" / "methodology"


def methodology_state_path(project: Path) -> Path:
    return methodology_state_dir(project) / "state.json"


def _validate_state_shape(data: Any, source: Path) -> None:
    _require(isinstance(data, dict), f"{source}: state must be a JSON object")
    for key in (
        "methodology_id", "methodology_version", "intent", "risk", "claim_strength",
        "derived_profile", "derivation", "effective_profile", "phase_profile_overrides",
        "downgrade_log", "current_phase", "transition_history", "loops",
        "created_by", "created_at", "updated_at",
    ):
        _require(key in data, f"{source}: missing required field {key!r}")
    _require(data["intent"] in INTENTS, f"{source}: unknown intent {data['intent']!r}")
    _require(data["risk"] in RISK_LEVELS, f"{source}: unknown risk {data['risk']!r}")
    _require(data["claim_strength"] in CLAIM_STRENGTHS, f"{source}: unknown claim_strength {data['claim_strength']!r}")
    _require(data["derived_profile"] in PROFILE_ORDER, f"{source}: unknown derived_profile {data['derived_profile']!r}")
    _require(data["effective_profile"] in PROFILE_ORDER, f"{source}: unknown effective_profile {data['effective_profile']!r}")
    overrides = data["phase_profile_overrides"]
    _require(isinstance(overrides, dict), f"{source}: phase_profile_overrides must be an object")
    for key, value in overrides.items():
        _require(value in PROFILE_ORDER, f"{source}: phase_profile_overrides[{key!r}] has unknown profile {value!r}")
    downgrade_log = data["downgrade_log"]
    _require(isinstance(downgrade_log, list), f"{source}: downgrade_log must be an array")
    for entry in downgrade_log:
        for key in ("from_profile", "to_profile", "actor_id", "reason", "authorized_at"):
            _require(key in entry, f"{source}: downgrade_log entry missing {key!r}")
    _require(data["current_phase"].startswith("P"), f"{source}: current_phase must be a P-id")
    history = data["transition_history"]
    _require(isinstance(history, list), f"{source}: transition_history must be an array")
    for entry in history:
        for key in ("transition_id", "from_phase", "to_phase", "transition_type", "reason", "actor_id", "authority_class", "timestamp"):
            _require(key in entry, f"{source}: transition_history entry missing {key!r}")
    loops = data["loops"]
    _require(isinstance(loops, list), f"{source}: loops must be an array")
    for loop in loops:
        for key in ("loop_id", "loop_type", "origin_phase", "current_phase", "reason", "status", "entered_at"):
            _require(key in loop, f"{source}: loop entry missing {key!r}")
        _require(loop["loop_type"] in LOOPS, f"{source}: loop {loop.get('loop_id')} has unknown loop_type {loop['loop_type']!r}")
        _require(loop["status"] in LOOP_STATUSES, f"{source}: loop {loop.get('loop_id')} has unknown status {loop['status']!r}")


def load_state(project: Path) -> dict[str, Any] | None:
    """Returns None if uninitialized (a truthful, non-error 'nothing here yet' state),
    or the validated state dict. Raises MethodologyValidationError for anything malformed."""
    path = methodology_state_path(project)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MethodologyValidationError(f"{path} is invalid JSON: {exc}") from exc
    _validate_state_shape(data, path)
    return data


def _write_state(project: Path, state: dict[str, Any]) -> None:
    path = methodology_state_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def init_project(
    project: Path,
    intent: str,
    risk: str,
    claim_strength: str,
    actor: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    path = methodology_state_path(project)
    if path.is_file() and not force:
        raise MethodologyValidationError(f"{path} already exists; use --force to reinitialize")
    definition = load_methodology()
    derivation = derive_profile(intent, risk, claim_strength)
    timestamp = _now()
    state = {
        "methodology_id": definition.methodology_id,
        "methodology_version": definition.version,
        "intent": intent,
        "risk": risk,
        "claim_strength": claim_strength,
        "derived_profile": derivation.profile,
        "derivation": derivation.as_dict(),
        "effective_profile": derivation.profile,
        "phase_profile_overrides": {},
        "downgrade_log": [],
        "current_phase": "P0",
        "transition_history": [],
        "loops": [],
        "created_by": actor,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    _write_state(project, state)
    return state


def escalate_phase(project: Path, phase_or_macro: str, profile: str, actor: str) -> dict[str, Any]:
    """Phase-level escalation only ever raises rigor above the project's effective profile.

    It is never a downgrade path: a lower value here is rejected, pointing the caller at
    downgrade_profile() instead, which requires the explicit attribution this does not.
    """
    state = load_state(project)
    if state is None:
        raise MethodologyValidationError(f"no methodology state at {project}; run 'nogap methodology init' first")
    _require(profile in PROFILE_ORDER, f"unknown profile: {profile!r}")
    definition = load_methodology()
    _require(
        phase_or_macro in MACRO_PHASES or phase_or_macro in definition.phases,
        f"unknown phase or macro phase: {phase_or_macro!r}",
    )
    effective = state["effective_profile"]
    _require(
        PROFILE_ORDER[profile] >= PROFILE_ORDER[effective],
        f"phase escalation must be >= the current effective profile ({effective}); "
        f"a lower value is a downgrade and must go through downgrade_profile with an explicit reason",
    )
    state["phase_profile_overrides"][phase_or_macro] = profile
    state["updated_at"] = _now()
    _write_state(project, state)
    return state


def downgrade_profile(project: Path, to_profile: str, actor: str, reason: str) -> dict[str, Any]:
    """The only path that can lower effective_profile - and it can never be silent.

    Requires a non-empty actor and reason, and always appends to downgrade_log: an
    attributable, auditable record, never a quiet overwrite.
    """
    state = load_state(project)
    if state is None:
        raise MethodologyValidationError(f"no methodology state at {project}; run 'nogap methodology init' first")
    _require(to_profile in PROFILE_ORDER, f"unknown profile: {to_profile!r}")
    _require(bool(actor and actor.strip()), "downgrade requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "downgrade requires an explicit, non-empty reason")
    current = state["effective_profile"]
    _require(
        PROFILE_ORDER[to_profile] < PROFILE_ORDER[current],
        f"{to_profile} is not lower than the current effective profile {current}; "
        f"use escalate_phase to raise a specific phase instead",
    )
    state["downgrade_log"].append({
        "from_profile": current,
        "to_profile": to_profile,
        "actor_id": actor.strip(),
        "reason": reason.strip(),
        "authorized_at": _now(),
    })
    state["effective_profile"] = to_profile
    state["updated_at"] = _now()
    _write_state(project, state)
    return state


def status(project: Path) -> dict[str, Any]:
    """Always truthful about missing/uninitialized state - never fabricates a default."""
    state = load_state(project)
    if state is None:
        return {"initialized": False, "path": str(methodology_state_path(project))}
    return {"initialized": True, "path": str(methodology_state_path(project)), **state}


# ---------------------------------------------------------------------------
# M7-C: P0-P23 Methodology State Machine
#
# This engine answers "what phase, what's next, what's missing, why blocked,
# which loop" - it does not judge whether execution succeeded (that's
# nogap_effects.py / M6-D) and it does not decide ACCEPT/REJECT (that's
# nogap.py's cmd_decide). current_phase changes only through transition():
# there is no other function anywhere that assigns it.
# ---------------------------------------------------------------------------

TRANSITION_AUTHORITY_CLASSES = {"execution", "verification", "acceptance", "human", "tool"}
# Every failure_transition in the contract graph that names a real phase (not REPAIR_LOOP)
# points at P13: repairing means redoing controlled implementation. REPAIR_LOOP itself is
# symbolic (root cause not yet known), so resolving it lands here too, by the same convention.
_UNIVERSAL_REPAIR_TARGET = "P13"


def _require_state(project: Path) -> tuple[dict[str, Any], MethodologyDefinition]:
    state = load_state(project)
    if state is None:
        raise MethodologyValidationError(f"no methodology state at {project}; run 'nogap methodology init' first")
    definition = load_methodology()
    _require(
        state["methodology_version"] == definition.version,
        f"methodology version mismatch: project state was created under v{state['methodology_version']} "
        f"but the loaded methodology definition is v{definition.version}",
    )
    return state, definition


def _effective_profile_for_phase(state: dict[str, Any], phase: PhaseContract) -> str:
    overrides = state["phase_profile_overrides"]
    if phase.id in overrides:
        return overrides[phase.id]
    if phase.macro_phase in overrides:
        return overrides[phase.macro_phase]
    return state["effective_profile"]


def _runtime_evidence_ids(project: Path) -> set[str] | None:
    """Ids found under <project>/.code-loop/runtime/evidence (M6's evidence ledger), or None
    if that runtime doesn't exist at all - nothing to resolve against, so refs are accepted at
    face value rather than fabricating a rejection for a project with no runtime yet."""
    evidence_dir = project.resolve() / ".code-loop" / "runtime" / "evidence"
    if not evidence_dir.is_dir():
        return None
    ids: set[str] = set()
    for path in evidence_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("id"), str):
            ids.add(data["id"])
    return ids


def _is_skippable(definition: MethodologyDefinition, state: dict[str, Any], phase: PhaseContract) -> bool:
    effective = _effective_profile_for_phase(state, phase)
    profile_obj = definition.get_profile(effective)
    return phase.id in profile_obj.skippable_phases and PROFILE_ORDER[effective] < PROFILE_ORDER[phase.minimum_profile]


def _resolve_forward_target(definition: MethodologyDefinition, state: dict[str, Any], from_phase: PhaseContract) -> tuple[str | None, list[str]]:
    """Follows allowed_next, skipping a chain of phases the *active* profile permits skipping.
    Returns (final_target_id_or_None, [skipped_phase_ids])."""
    if not from_phase.allowed_next:
        return None, []
    target_id = from_phase.allowed_next[0]
    skipped: list[str] = []
    while True:
        target = definition.get_phase(target_id)
        if _is_skippable(definition, state, target):
            skipped.append(target_id)
            if not target.allowed_next:
                return target_id, skipped
            target_id = target.allowed_next[0]
            continue
        return target_id, skipped


def _classify_edge(definition: MethodologyDefinition, current: PhaseContract, to: str) -> str | None:
    """Structural-only classification: is `to` a plain legal edge from `current`, and what
    transition_type applies? Returns None if there is no such edge at all."""
    if to in current.allowed_next:
        target = definition.get_phase(to)
        return "LOOP_ENTRY" if (target.loop and target.loop != current.loop) else "FORWARD"
    if to in current.allowed_back_transitions:
        target = definition.get_phase(to)
        return "LOOP_RETURN" if target.loop else "BACKWARD"
    if current.failure_transition and to == current.failure_transition and to != "REPAIR_LOOP":
        target = definition.get_phase(to)
        return "LOOP_RETURN" if target.loop else "BACKWARD"
    return None


def _evaluate_transition(
    project: Path,
    state: dict[str, Any],
    definition: MethodologyDefinition,
    to: str,
    evidence_refs: list[str],
    artifact_refs: list[str],
) -> dict[str, Any]:
    reasons: list[str] = []
    current_id = state["current_phase"]
    current = definition.get_phase(current_id)  # fail closed if current_phase itself is corrupted

    if to == "REPAIR_LOOP":
        if current.failure_transition != "REPAIR_LOOP":
            reasons.append(f"{current_id} does not route failures to REPAIR_LOOP")
        if any(loop["status"] == "ACTIVE" for loop in state["loops"]):
            reasons.append("an active loop already exists; resolve it before entering a new one")
        return {"allowed": not reasons, "transition_type": None if reasons else "LOOP_ENTRY", "blocked_reasons": reasons, "skipped_phases": []}

    _require(to in definition.phases, f"unknown target phase: {to!r}")

    # An active repair_loop originating at the current phase authorizes returning to the
    # universal repair target, even though "REPAIR_LOOP" itself (not a real phase) is what
    # current.failure_transition names.
    active_repair = next(
        (loop for loop in state["loops"] if loop["status"] == "ACTIVE" and loop["loop_type"] == "repair_loop" and loop["origin_phase"] == current_id),
        None,
    )
    if active_repair and to == _UNIVERSAL_REPAIR_TARGET:
        transition_type: str | None = "LOOP_RETURN"
        skipped: list[str] = []
    else:
        skip_target, skip_chain = _resolve_forward_target(definition, state, current)
        if skip_target == to and skip_chain:
            transition_type, skipped = "SKIP", skip_chain
        else:
            transition_type, skipped = _classify_edge(definition, current, to), []
            if transition_type is None:
                reasons.append(
                    f"{to} is not a legal transition from {current_id} "
                    f"(allowed_next={current.allowed_next}, allowed_back={current.allowed_back_transitions}, "
                    f"failure_transition={current.failure_transition})"
                )

    if current.required_evidence and not evidence_refs:
        reasons.append(f"{current_id} requires evidence ({current.required_evidence}) but none was supplied")
    if current.required_artifacts and not artifact_refs:
        reasons.append(f"{current_id} requires artifacts ({current.required_artifacts}) but none was supplied")

    known_evidence = _runtime_evidence_ids(project)
    if known_evidence is not None and evidence_refs:
        unknown = [ref for ref in evidence_refs if ref not in known_evidence]
        if unknown:
            reasons.append(f"unknown evidence reference(s), not found in the runtime evidence ledger: {unknown}")

    return {
        "allowed": not reasons,
        "transition_type": transition_type if not reasons else None,
        "blocked_reasons": reasons,
        "skipped_phases": skipped,
    }


def can_transition(project: Path, to: str, evidence_refs: list[str] = (), artifact_refs: list[str] = ()) -> dict[str, Any]:
    """Read-only dry run: does not write anything."""
    state, definition = _require_state(project)
    return _evaluate_transition(project, state, definition, to, list(evidence_refs), list(artifact_refs))


def _new_loop_record(loop_type: str, origin_phase: str, current_phase: str, reason: str, evidence_refs: list[str]) -> dict[str, Any]:
    timestamp = _now()
    digest = hashlib.sha256(f"{loop_type}{origin_phase}{timestamp}".encode("utf-8")).hexdigest()[:12]
    return {
        "loop_id": f"loop-{digest}",
        "loop_type": loop_type,
        "origin_phase": origin_phase,
        "current_phase": current_phase,
        "reason": reason,
        "status": "ACTIVE",
        "entered_at": timestamp,
        "resolved_at": None,
        "evidence_refs": list(evidence_refs),
    }


def transition(
    project: Path,
    to: str,
    actor: str,
    reason: str,
    *,
    evidence_refs: list[str] = (),
    artifact_refs: list[str] = (),
    authority_class: str = "human",
) -> dict[str, Any]:
    """The only function that ever assigns state["current_phase"]."""
    _require(bool(actor and actor.strip()), "transition requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "transition requires a non-empty reason")
    _require(authority_class in TRANSITION_AUTHORITY_CLASSES, f"unknown authority_class: {authority_class!r}")
    state, definition = _require_state(project)
    evidence_refs = list(evidence_refs)
    artifact_refs = list(artifact_refs)

    evaluation = _evaluate_transition(project, state, definition, to, evidence_refs, artifact_refs)
    if not evaluation["allowed"]:
        raise MethodologyValidationError(
            f"transition {state['current_phase']} -> {to} rejected: " + "; ".join(evaluation["blocked_reasons"])
        )

    current_id = state["current_phase"]
    current = definition.get_phase(current_id)
    transition_type = evaluation["transition_type"]
    timestamp = _now()
    digest = hashlib.sha256(f"{current_id}{to}{timestamp}".encode("utf-8")).hexdigest()[:12]

    record: dict[str, Any] = {
        "transition_id": f"transition-{digest}",
        "methodology_id": state["methodology_id"],
        "methodology_version": state["methodology_version"],
        "from_phase": current_id,
        "to_phase": to,
        "transition_type": transition_type,
        "reason": reason.strip(),
        "actor_id": actor.strip(),
        "authority_class": authority_class,
        "evidence_refs": evidence_refs,
        "artifact_refs": artifact_refs,
        "timestamp": timestamp,
        "profile_at_transition": _effective_profile_for_phase(state, current),
    }
    if transition_type == "SKIP":
        record["skipped_phases"] = evaluation["skipped_phases"]
    state["transition_history"].append(record)

    if to == "REPAIR_LOOP":
        state["loops"].append(_new_loop_record("repair_loop", current_id, current_id, reason.strip(), evidence_refs))
        # current_phase intentionally unchanged: REPAIR_LOOP is not a real phase to occupy.
    else:
        target = definition.get_phase(to)
        for loop in state["loops"]:
            if loop["status"] != "ACTIVE":
                continue
            if loop["loop_type"] == "repair_loop" and loop["origin_phase"] == current_id and to == _UNIVERSAL_REPAIR_TARGET:
                loop["status"], loop["resolved_at"], loop["current_phase"] = "RESOLVED", timestamp, to
            elif loop["loop_type"] == current.loop and current.loop != (target.loop or None):
                loop["status"], loop["resolved_at"], loop["current_phase"] = "RESOLVED", timestamp, to
        if transition_type == "LOOP_ENTRY" and target.loop:
            if not any(loop["status"] == "ACTIVE" and loop["loop_type"] == target.loop for loop in state["loops"]):
                state["loops"].append(_new_loop_record(target.loop, current_id, to, reason.strip(), evidence_refs))
        state["current_phase"] = to

    state["updated_at"] = timestamp
    _write_state(project, state)
    return state


def resolve_loop(project: Path, loop_id: str, status_value: str, actor: str, reason: str) -> dict[str, Any]:
    """Explicit manual resolution for a loop transition() didn't already auto-resolve (e.g.
    marking a stuck loop BLOCKED/INCONCLUSIVE instead of leaving it dangling ACTIVE)."""
    _require(status_value in LOOP_STATUSES and status_value != "ACTIVE", f"unknown resolution status: {status_value!r}")
    _require(bool(actor and actor.strip()), "loop resolution requires a non-empty actor_id")
    _require(bool(reason and reason.strip()), "loop resolution requires a non-empty reason")
    state, _definition = _require_state(project)
    loop = next((item for item in state["loops"] if item["loop_id"] == loop_id), None)
    if loop is None:
        raise MethodologyValidationError(f"unknown loop_id: {loop_id!r}")
    _require(loop["status"] == "ACTIVE", f"loop {loop_id} is not ACTIVE (status={loop['status']!r})")
    loop["status"] = status_value
    loop["resolved_at"] = _now()
    state["updated_at"] = loop["resolved_at"]
    _write_state(project, state)
    return state


def active_loops(project: Path) -> list[dict[str, Any]]:
    state, _definition = _require_state(project)
    return [loop for loop in state["loops"] if loop["status"] == "ACTIVE"]


def evaluate_phase_status(project: Path, phase_id: str | None = None) -> str:
    """NOT_STARTED | ACTIVE | BLOCKED | READY_TO_EXIT | COMPLETED.

    COMPLETED is earned only by an actual recorded forward-flavored transition_history entry
    (FORWARD/LOOP_ENTRY/SKIP) whose from_phase is this phase - never asserted directly, and
    never inferred merely from current_phase having moved past it some other way.
    """
    state, definition = _require_state(project)
    phase_id = phase_id or state["current_phase"]
    phase = definition.get_phase(phase_id)  # fail closed on an unknown phase id

    if phase_id == state["current_phase"]:
        if not phase.allowed_next:
            return "ACTIVE"
        evaluation = _evaluate_transition(project, state, definition, phase.allowed_next[0], [], [])
        return "READY_TO_EXIT" if evaluation["allowed"] else "BLOCKED"

    exited_forward = any(
        entry["from_phase"] == phase_id and entry["transition_type"] in {"FORWARD", "LOOP_ENTRY", "SKIP"}
        for entry in state["transition_history"]
    )
    return "COMPLETED" if exited_forward else "NOT_STARTED"


# ---------------------------------------------------------------------------
# M7-D: Golden Principle Enforcement Map
#
# This is a truthful, read-only description of what enforcement CAPABILITY
# exists today - never a claim about any specific project's compliance, and
# never consulted by the trust runtime to make any decision. Editing
# methodology/enforcement.json changes only what is reported, not what
# nogap.py actually enforces: acceptability(), gate hashing, verify_effect(),
# etc. are entirely independent of this file.
# ---------------------------------------------------------------------------

ENFORCEMENT_STATUSES = {"ENFORCED", "PARTIAL", "DECLARED", "ADVISORY", "DEFERRED"}
ENFORCEMENT_SCOPES = {"trust_runtime", "methodology_engine", "cross_cutting"}
# Every owner_component value that appears anywhere in methodology/enforcement.json must be
# registered here - an unregistered identifier fails closed rather than being silently trusted.
OWNER_COMPONENTS = {
    "none",
    "trust_runtime_event_ledger",
    "nogap.py:acceptability",
    "nogap.py:cmd_validate",
    "nogap.py:cmd_freeze",
    "nogap.py:write_isolated_run_evidence",
    "nogap.py:route_implementer",
    "nogap_adapters.py",
    "nogap_effects.py",
    "nogap_methodology.py:init_project",
    "nogap_methodology.py:transition",
    "nogap_methodology.py:derive_profile",
    "nogap_failure.py",
    "nogap_failure.py:record_research",
    "nogap_memory.py",
    "nogap_research.py",
    "nogap_research.py:assess_claim",
    "nogap_lifecycle.py",
    "nogap_lifecycle.py:evaluate_release_readiness",
}


@dataclass
class PrincipleEnforcement:
    principle_id: str
    classification: str
    status: str
    scope: str
    owner_component: str
    mechanism: str
    evidence_kind: str | None
    implemented_by: list[str]
    tests: list[str]
    future_milestone: str | None
    notes: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "principle_id": self.principle_id, "classification": self.classification, "status": self.status,
            "scope": self.scope, "owner_component": self.owner_component, "mechanism": self.mechanism,
            "evidence_kind": self.evidence_kind, "implemented_by": self.implemented_by, "tests": self.tests,
            "future_milestone": self.future_milestone, "notes": self.notes,
        }


def _resolve_reference(ref: str) -> Path:
    """A "path" or "path::rest" or "path:rest" reference's file part, resolved from repo ROOT."""
    file_part = ref.split("::")[0].split(":")[0]
    return ROOT / file_part


def load_enforcement_map(methodology_dir: Path = METHODOLOGY_DIR) -> dict[str, PrincipleEnforcement]:
    """Fails closed on: malformed JSON, missing/duplicate/unknown principle_id, unknown status/
    classification/scope/owner_component, or a mismatch against methodology/principles.json's
    classification (classification is reused from M7-A, never re-derived here)."""
    definition = load_methodology()  # principles.json is the classification source of truth
    data = _read_json(methodology_dir / "enforcement.json")
    _require(isinstance(data, dict) and isinstance(data.get("principles"), list), "enforcement.json must contain a 'principles' array")

    records: dict[str, PrincipleEnforcement] = {}
    for entry in data["principles"]:
        _require(isinstance(entry, dict), "enforcement.json: each principle entry must be an object")
        for key in (
            "principle_id", "classification", "status", "scope", "owner_component",
            "mechanism", "evidence_kind", "implemented_by", "tests", "future_milestone", "notes",
        ):
            _require(key in entry, f"enforcement.json: entry missing required field {key!r}")
        principle_id = entry["principle_id"]
        _require(principle_id in definition.principles, f"enforcement.json: unknown principle_id {principle_id!r}")
        _require(principle_id not in records, f"enforcement.json: duplicate principle_id {principle_id!r}")
        _require(
            entry["classification"] == definition.get_principle(principle_id).cls,
            f"enforcement.json: {principle_id} classification {entry['classification']!r} does not match "
            f"principles.json's {definition.get_principle(principle_id).cls!r} - classification is reused, not re-derived",
        )
        _require(entry["status"] in ENFORCEMENT_STATUSES, f"enforcement.json: {principle_id} has unknown status {entry['status']!r}")
        _require(entry["scope"] in ENFORCEMENT_SCOPES, f"enforcement.json: {principle_id} has unknown scope {entry['scope']!r}")
        _require(
            entry["owner_component"] in OWNER_COMPONENTS,
            f"enforcement.json: {principle_id} has unregistered owner_component {entry['owner_component']!r}",
        )
        records[principle_id] = PrincipleEnforcement(
            principle_id=principle_id, classification=entry["classification"], status=entry["status"],
            scope=entry["scope"], owner_component=entry["owner_component"], mechanism=entry["mechanism"],
            evidence_kind=entry["evidence_kind"], implemented_by=list(entry["implemented_by"]),
            tests=list(entry["tests"]), future_milestone=entry["future_milestone"], notes=entry["notes"],
        )

    _require(
        set(records) == set(definition.principles),
        f"enforcement.json does not cover exactly the 20 canonical principles: "
        f"missing={sorted(set(definition.principles) - set(records))}, extra={sorted(set(records) - set(definition.principles))}",
    )
    return records


def get_principle_enforcement(principle_id: str) -> PrincipleEnforcement:
    records = load_enforcement_map()
    if principle_id not in records:
        raise MethodologyValidationError(f"unknown principle: {principle_id}")
    return records[principle_id]


def list_principle_enforcement() -> list[PrincipleEnforcement]:
    records = load_enforcement_map()
    return [records[pid] for pid in sorted(records, key=lambda p: int(p.split("-")[1]))]


def methodology_compliance_summary() -> dict[str, Any]:
    """Enforcement CAPABILITY summary - global, not tied to any project's actual compliance.
    ADVISORY and DEFERRED principles never contribute to the enforced count; only status=ENFORCED
    does. Distinguishing capability from a specific project's compliance is deliberate: this
    milestone is about what NoGapCode CAN enforce, not what any one project currently satisfies."""
    records = list_principle_enforcement()
    counts = {status: 0 for status in ENFORCEMENT_STATUSES}
    for record in records:
        counts[record.status] += 1
    return {
        "total": len(records),
        "counts": counts,
        "enforced": counts["ENFORCED"],
        "partial": counts["PARTIAL"],
        "declared": counts["DECLARED"],
        "advisory": counts["ADVISORY"],
        "deferred": counts["DEFERRED"],
    }


def resolvable_references(record: PrincipleEnforcement) -> dict[str, list[str]]:
    """For CLI/inspection use: which of a record's implemented_by/tests references actually
    resolve to a file on disk right now, and which don't (a documentation-drift signal)."""
    return {
        "implemented_by_missing": [ref for ref in record.implemented_by if not _resolve_reference(ref).is_file()],
        "tests_missing": [ref for ref in record.tests if not _resolve_reference(ref).is_file()],
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Validate the methodology contracts under methodology/.")
    parser.add_argument("action", choices=["validate"])
    parser.add_argument("--dir", default=str(METHODOLOGY_DIR))
    args = parser.parse_args()

    definition = load_methodology(Path(args.dir))
    print(
        f"OK: {definition.methodology_id} v{definition.version} - "
        f"{len(definition.phases)} phases, {len(definition.principles)} principles, "
        f"{len(definition.profiles)} profiles, {len(definition.loops)} loops"
    )


if __name__ == "__main__":
    main()
