#!/usr/bin/env python3
"""M7-A: loads and validates the methodology contracts under methodology/.

This module only represents and validates the methodology - it does not run it.
No project state, no phase transitions, no CLI wiring into nogap.py: that is
M7-B (Project Intent + Adaptive Depth) and M7-C (the P0-P23 state machine).
Keeping this module standalone (not imported by nogap.py) is deliberate:
"Methodology logic MUST NOT be embedded throughout nogap.py."

Fails closed: any malformed contract, any reference to an unknown phase, macro
phase, loop, or principle, or any cross-reference mismatch between
methodology.json and the files on disk raises MethodologyValidationError. There
is no silent-partial-load path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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
