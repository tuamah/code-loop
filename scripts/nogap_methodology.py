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
        "downgrade_log", "current_phase", "created_by", "created_at", "updated_at",
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
