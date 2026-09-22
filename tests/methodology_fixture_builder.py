"""Central fixture factory: real methodology history, built through production APIs.

Before F2a, test fixtures walked the phase graph passing placeholder strings like
`artifact_refs=["artifact-placeholder"]`. The helper they used said so outright - "content
doesn't matter here, only presence/absence does at this milestone" - and that was true of the
rule as it then existed. F2a made it false, and three separate test modules turned out to be
standing on scaffolding that resolved to nothing.

The repair is not a seam inside `transition()`. That function IS F2a's enforcement point, so a
test-only bypass there would create a path that skips the very property the tests exist to
prove, in the one item whose whole purpose is refusing fictitious references.

So this builder produces REAL history:

* artifacts through `nogap_artifacts.create_artifact`
* phase movement through the real `transition()` engine
* evidence as real records in the runtime ledger
* patches as real files inside the project

Two invariants, each with its own guard test:

1. **It never writes methodology state directly.** No poking `current_phase`; every phase
   change is a transition the engine agreed to.
2. **It never invents ids.** Every reference it passes came back from the API that created
   the thing being referenced.

A fixture that fakes the references under test cannot witness the rule it stands in for.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from nogap_artifacts import ARTIFACT_TYPES, create_artifact
from nogap_methodology import load_methodology, status as mstatus, transition

#: Phases whose completion obligation is a ledger evidence record rather than an artifact.
_EVIDENCE_PHASES = {
    "P14": ("execution", "execution"),
    "P16": ("test", "verification"),
    "P17": ("test", "verification"),
}


class FixtureBuilder:
    """Builds a project forward through real phases, satisfying what each one owes."""

    def __init__(self, project: Path, actor: str = "fixture"):
        self.project = Path(project)
        self.actor = actor
        self.artifacts: dict[str, dict[str, Any]] = {}
        self.evidence_ids: list[str] = []
        self.patch_path: str | None = None

    # -- real records -------------------------------------------------------------------

    def _runtime_evidence(self, kind: str, authority: str) -> str:
        """A real record in the runtime evidence ledger, in the ledger's own shape.

        Written here rather than driven through an executor because these fixtures are about
        phase mechanics, not about running processes - but the RECORD is real: a generated
        id, a run binding and actor provenance, which is what the evidence resolver checks.
        """
        directory = self.project.resolve() / ".code-loop" / "runtime" / "evidence"
        directory.mkdir(parents=True, exist_ok=True)
        evidence_id = f"evidence-{uuid.uuid4().hex[:12]}"
        (directory / f"{evidence_id}.json").write_text(json.dumps({
            "id": evidence_id,
            "run_id": "run-0001",
            "kind": kind,
            "status": "passed",
            "provenance": {"created_by": self.actor, "actor_id": self.actor,
                           "authority": authority, "role": "executor"},
            "summary": "fixture evidence",
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.evidence_ids.append(evidence_id)
        return evidence_id

    def _patch_file(self) -> str:
        path = self.project.resolve() / "fixture-change.patch"
        path.write_text("diff --git a/x b/x\n", encoding="utf-8")
        self.patch_path = "fixture-change.patch"
        return self.patch_path

    def _artifact_for(self, phase_id: str) -> str | None:
        """Create the artifact this phase owes, if it has a declared type, with real refs."""
        from nogap_artifacts import PHASE_TO_ARTIFACT_TYPE

        artifact_type = PHASE_TO_ARTIFACT_TYPE.get(phase_id)
        if artifact_type is None:
            return None
        extra = {"status": "VERIFICATION_COMPLETE_AWAITING_DECISION"} if (
            artifact_type == "P18_VERIFICATION_RESULT") else {}
        record = create_artifact(self.project, artifact_type,
                                 _FIELDS[artifact_type](self), actor=self.actor, **extra)
        self.artifacts[phase_id] = record
        return record["artifact_id"]

    # -- what a phase owes to be left forward ---------------------------------------------

    def obligations(self, phase_id: str) -> tuple[list[str], list[str]]:
        """(artifact_refs, evidence_refs) that genuinely satisfy leaving `phase_id`."""
        artifact_refs: list[str] = []
        if phase_id == "P13":
            artifact_refs.append(self._patch_file())
        elif phase_id in _EVIDENCE_PHASES:
            kind, authority = _EVIDENCE_PHASES[phase_id]
            artifact_refs.append(self._runtime_evidence(kind, authority))
        else:
            made = self._artifact_for(phase_id)
            if made:
                artifact_refs.append(made)

        # Once a runtime ledger exists, every evidence ref is resolved against it, so the
        # fixture cites a real record rather than a placeholder that would now be rejected.
        evidence_refs: list[str] = []
        if load_methodology().get_phase(phase_id).required_evidence:
            evidence_refs.append(self.evidence_ids[-1] if self.evidence_ids
                                 else self._runtime_evidence("execution", "execution"))
        return artifact_refs, evidence_refs

    def advance_to(self, target_phase: str) -> dict[str, Any]:
        """Walk forward to `target_phase`, satisfying each phase's obligations for real."""
        definition = load_methodology()
        state = mstatus(self.project)
        guard = 0
        while state["current_phase"] != target_phase:
            guard += 1
            if guard > 40:
                raise AssertionError(
                    f"no forward path from {state['current_phase']} to {target_phase}")
            current = definition.get_phase(state["current_phase"])
            if not current.allowed_next:
                raise AssertionError(f"{current.id} has no forward edge")
            nxt = current.allowed_next[0]
            artifact_refs, evidence_refs = self.obligations(current.id)
            state = transition(self.project, nxt, actor=self.actor,
                               reason=f"fixture advance to {nxt}",
                               artifact_refs=artifact_refs, evidence_refs=evidence_refs,
                               authority_class="tool")
        return state


def _f(**kw):
    return lambda self: kw


#: Field sets for each artifact type, mirroring what ARTIFACT_TYPES declares as required.
_FIELDS: dict[str, Any] = {
    # intent/risk/claim are read from the project's OWN state, never hardcoded: an artifact
    # that contradicts the state it belongs to is rejected by create_artifact, and rightly so.
    "P0_PROJECT_INTENT": lambda self: dict(
        project_name="demo", intent_type=mstatus(self.project)["intent"], problem_summary="x",
        target_users_or_context="team", desired_outcome="y", owner="team",
        initial_constraints=["budget"]),
    "P1_SCOPE": _f(problem_statement="x", in_scope=["a"], out_of_scope=["b"],
                   constraints=["c"], dependencies=["d"], known_assumptions=["e"]),
    "P2_SUCCESS_CRITERIA": lambda self: dict(
        success_criteria=["works"], failure_criteria=["crashes"],
        risk_level=mstatus(self.project)["risk"],
        claim_strength=mstatus(self.project)["claim_strength"],
        critical_claims=["c1"], stop_conditions=["s1"]),
    "P3_PRIOR_ART": _f(research_question="q", search_scope="s", sources=["s1"],
                       candidate_solutions=["c1"], key_findings=["f1"], limitations=["l1"]),
    "P4_GAP_ANALYSIS": lambda self: dict(
        requirements_or_needs=["n"], existing_solutions=["s"], covered_capabilities=["c"],
        missing_capabilities=["m"], tradeoffs=["t"], gaps=["g"],
        prior_art_refs=[self.artifacts["P3"]["artifact_id"]]),
    "P5_STRATEGY_DECISION": lambda self: dict(
        selected_strategy="BUILD", alternatives_considered=["BUY"], reason="r", cost="low",
        risk="low", gap_analysis_refs=[self.artifacts["P4"]["artifact_id"]]),
    "P6_REQUIREMENT": lambda self: dict(
        type="functional", statement="system must do X", priority="high",
        acceptance_criteria=["X happens"],
        strategy_decision_refs=[self.artifacts["P5"]["artifact_id"]]),
    "P7_ARCHITECTURE": lambda self: dict(
        components=["svc1"], trust_boundaries=["b1"], execution_authorities=["agent"],
        acceptance_authorities=["human"],
        requirement_refs=[self.artifacts["P6"]["fields"]["requirement_id"]],
        responsibilities=["svc1 does X"], interfaces=["api"], external_dependencies=["db"],
        # Profile-required at STRICT. Supplied unconditionally so one builder serves every
        # profile rather than silently working only at LIGHT.
        failure_domains=["svc1"], data_security_boundaries=["pii"]),
    "P8_ADR": lambda self: dict(
        decision="use postgres", context="need durable storage",
        alternatives=["sqlite", "postgres"], selected_option="postgres", rationale="scale",
        consequences=["ops burden"], expected_cost="medium",
        architecture_refs=[self.artifacts["P7"]["artifact_id"]],
        vendor_lock_in="none"),  # profile-required at STRICT
    "P9_GOVERNANCE": lambda self: dict(
        roles=["architect", "verifier"], authority_assignments={"acceptance": "human:owner"},
        execution_backend_policy="isolated worktree only",
        verification_policy="independent review required",
        human_approval_requirements=["release"],
        adr_refs=[self.artifacts["P8"]["artifact_id"]]),
    "P10_BASELINE": _f(baseline_description="manual process", primary_metric="completion time",
                       secondary_metrics=["error rate"], measurement_procedure="manual timing"),
    "P11_GATE_PLAN": lambda self: dict(
        gate_id="gate-plan-1", required_tests=["unit"], evidence_requirements=["execution"],
        stop_conditions=["security fail"], verification_depth="standard",
        requirement_refs=[self.artifacts["P6"]["fields"]["requirement_id"]],
        required_commands=["pytest -k unit"], forbidden_paths=["secrets.env"]),
    "P15_VERIFICATION_PLAN": lambda self: dict(
        task_id=self.artifacts["P12"]["fields"]["task_id"], profile="LIGHT",
        risk=mstatus(self.project)["risk"],
        claim_strength=mstatus(self.project)["claim_strength"], required_levels=["STATIC_CHECKS"],
        required_validation_levels=["INTERNAL"], required_evidence_kinds=["deterministic"],
        independent_review_required=False, reproducibility_required=False,
        external_validation_required=False),
    "P18_VERIFICATION_RESULT": lambda self: dict(
        verification_plan_id=self.artifacts["P15"]["fields"]["verification_plan_id"],
        task_id=self.artifacts["P12"]["fields"]["task_id"], candidate_hash="sha256:c",
        patch_hash="sha256:p", gate_hash="sha256:g",
        methodology_version_at_verification=load_methodology().version,
        profile_at_verification="LIGHT", task_snapshot_hash="sha256:t",
        executor_actor_id="agent:fixture", levels_attempted=["STATIC_CHECKS"],
        deterministic_result="passed", reproducibility_result="SKIPPED_PER_PROFILE_POLICY",
        independent_review_result="SKIPPED_PER_PROFILE_POLICY"),
    "P14_SELF_CHECK": lambda self: dict(
        task_id=self.artifacts["P12"]["fields"]["task_id"], patch_hash="sha256:p",
        execution_evidence_ids=[self.evidence_ids[-1]] if self.evidence_ids else []),
    "P12_TASK_CONTRACT": lambda self: dict(
        goal="implement X", scope=["svc1"], forbidden_scope=["unrelated"],
        acceptance_criteria=["X happens"], planned_tests=["unit"],
        required_evidence=["execution"], stop_conditions=["security fail"],
        requirement_refs=[self.artifacts["P6"]["fields"]["requirement_id"]],
        gate_plan_refs=[self.artifacts["P11"]["artifact_id"]]),
}


def at_phase(project: Path, target_phase: str, actor: str = "fixture") -> FixtureBuilder:
    """Build a project with REAL history up to `target_phase`, and return the builder."""
    builder = FixtureBuilder(project, actor=actor)
    builder.advance_to(target_phase)
    return builder
