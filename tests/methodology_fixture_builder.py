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

    def __init__(self, project: Path, actor: str = "fixture",
                 materialize_evidence: bool = True):
        self.project = Path(project)
        self.actor = actor
        self.artifacts: dict[str, dict[str, Any]] = {}
        self.evidence_ids: list[str] = []
        self.patch_path: str | None = None
        self._lifecycle: dict[str, str] = {}
        self._gate_hash: str | None = None
        # Some tests are ABOUT the absence of a Trust runtime - "an unresolvable evidence ref
        # is accepted when there is no ledger to resolve against". A builder that creates one
        # unconditionally destroys that premise, so evidence materialization is opt-out and
        # the runtime is established lazily, at the first moment something actually needs it.
        self.materialize_evidence = materialize_evidence

    def ensure_gate(self) -> str:
        """The Trust runtime and a genuinely frozen gate, created once, on first need.

        Ordering is not incidental: `nogap init` refuses a project that already has a runtime
        directory, and writing an evidence record creates one - so this runs BEFORE the first
        evidence write, not after.
        """
        if self._gate_hash is None:
            self._gate_hash = _ensure_frozen_gate(self)
        return self._gate_hash

    # -- real records -------------------------------------------------------------------

    def _runtime_evidence(self, kind: str, authority: str) -> str:
        """A real record in the runtime evidence ledger, in the ledger's own shape.

        Written here rather than driven through an executor because these fixtures are about
        phase mechanics, not about running processes - but the RECORD is real: a generated
        id, a run binding and actor provenance, which is what the evidence resolver checks.
        """
        self.ensure_gate()  # before the directory exists, or `nogap init` refuses
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

    def _lifecycle_for(self, phase_id: str) -> list[str]:
        """Real lifecycle records for P19-P21, through nogap_lifecycle's own APIs.

        Created lazily and cached, because these phases' obligations name records that the
        lifecycle module owns - the builder resolves them through it rather than rebuilding
        its storage, which is the mistake the F2a lifecycle resolver already made once.
        """
        import nogap_lifecycle as nlc

        if phase_id == "P19":
            if "rc" not in self._lifecycle:
                rc = nlc.create_release_candidate(
                    self.project, version="0.0.1", candidate_ref="fixture-rc",
                    code_revision="deadbeef", actor=self.actor, reason="fixture candidate")
                self._lifecycle["rc"] = rc["release_candidate_id"]
            return [self._lifecycle["rc"]]
        if phase_id == "P20":
            return [self._lifecycle["readiness"]] if "readiness" in self._lifecycle else []
        if phase_id == "P21":
            return [self._lifecycle["observation"]] if "observation" in self._lifecycle else []
        return []

    def obligations(self, phase_id: str) -> tuple[list[str], list[str]]:
        """(artifact_refs, evidence_refs) that genuinely satisfy leaving `phase_id`."""
        artifact_refs: list[str] = []
        if phase_id == "P13":
            artifact_refs.append(self._patch_file())
        elif phase_id in _EVIDENCE_PHASES:
            kind, authority = _EVIDENCE_PHASES[phase_id]
            artifact_refs.append(self._runtime_evidence(kind, authority))
            if phase_id == "P14":
                # P14's declared obligation is EXECUTION_EVIDENCE, but the verification
                # binding is anchored to the P14_SELF_CHECK artifact - readiness later
                # reports the task's evidence as stale without it. Both are real records
                # created through production APIs; neither substitutes for the other.
                self._artifact_for("P14")
        elif phase_id in {"P19", "P20", "P21"}:
            artifact_refs.extend(self._lifecycle_for(phase_id))
        else:
            made = self._artifact_for(phase_id)
            if made:
                artifact_refs.append(made)

        # Once a runtime ledger exists, every evidence ref is resolved against it, so the
        # fixture cites a real record rather than a placeholder that would now be rejected.
        evidence_refs: list[str] = []
        if self.materialize_evidence and load_methodology().get_phase(phase_id).required_evidence:
            evidence_refs.append(self.evidence_ids[-1] if self.evidence_ids
                                 else self._runtime_evidence("execution", "execution"))
        return artifact_refs, evidence_refs

    def _drive_lifecycle(self) -> None:
        """Hand P18->P21 to nogap_lifecycle and let IT move the phases.

        Orchestration only. The builder does not create candidates, readiness records,
        deployments or observations of its own, and does not decide when a phase is complete:
        those are lifecycle semantics and the owner module holds them. Notably
        evaluate_release_readiness() performs the P19->P20 transition itself, so a builder
        that "made a readiness record" mid-walk would be reimplementing that module's rules
        beside it - and a second copy of a rule is free to drift from the real one.
        """
        import nogap_lifecycle as nlc

        # The candidate carries the REAL verification evidence the builder already produced:
        # freeze_release_candidate derives its transition evidence from verification_refs, so
        # supplying them is handing the owner API what it asks for, not second-guessing it.
        # P18's own obligation. The walk stops AT P18, so this is created here rather than
        # on the way out - readiness refuses a candidate whose task has no recorded
        # methodology verification result, and rightly so.
        if "P18" not in self.artifacts:
            self._artifact_for("P18")
        verification = [e for e in self.evidence_ids]
        # included_task_refs is the candidate's link to the work it contains; readiness
        # refuses without it ("minimum P15/P16 verification is required at every profile").
        # The builder supplies the REAL task it created at P12.
        tasks = ([self.artifacts["P12"]["fields"]["task_id"]]
                 if "P12" in self.artifacts else [])
        rc = nlc.create_release_candidate(
            self.project, version="0.0.1", candidate_ref="fixture-rc",
            code_revision="deadbeef", verification_refs=verification,
            included_task_refs=tasks, candidate_bindings=real_candidate_bindings(self.project, tasks),
            actor=self.actor, reason="fixture candidate")
        rc_id = rc["release_candidate_id"]
        nlc.freeze_release_candidate(self.project, rc_id, actor=self.actor, reason="freeze")
        readiness = nlc.evaluate_release_readiness(
            self.project, rc_id, actor=self.actor, reason="evaluate readiness")
        deployment = nlc.create_deployment(
            self.project, release_candidate_id=rc_id,
            readiness_id=readiness["readiness_id"], environment="production",
            deployment_target="k8s", actor=self.actor, reason="deploy")
        nlc.record_deployment_result(
            self.project, deployment["deployment_id"], status="SUCCEEDED",
            actor=self.actor, reason="deploy completed")
        self._lifecycle.update({"rc": rc_id, "readiness": readiness["readiness_id"],
                                "deployment": deployment["deployment_id"]})

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
            if current.id == "P18" and target_phase in {"P19", "P20", "P21"}:
                self._drive_lifecycle()
                state = mstatus(self.project)
                continue
            if not current.allowed_next:
                raise AssertionError(f"{current.id} has no forward edge")
            nxt = current.allowed_next[0]
            artifact_refs, evidence_refs = self.obligations(current.id)
            state = transition(self.project, nxt, actor=self.actor,
                               reason=f"fixture advance to {nxt}",
                               artifact_refs=artifact_refs, evidence_refs=evidence_refs,
                               authority_class="tool")
        return state


def _ensure_frozen_gate(builder: "FixtureBuilder") -> str:
    """Initialize the real Trust runtime and freeze a real gate; return ITS hash.

    P18_VERIFICATION_RESULT requires a non-empty gate_hash, and readiness compares that
    value against the live frozen gate. With no Trust runtime there is no frozen gate, so any
    value the fixture could supply is either empty (rejected) or the hash of a gate that was
    never frozen (stale - and the system is right to say so). The fixture therefore has what
    a real verification would have had: an actually frozen gate.

    The hash is read back from the frozen gate through nogap_build._frozen_gate(), never
    written by hand and never recomputed here. A fixture that computes a hash beside the
    owner is a fixture that can agree with itself while disagreeing with the system.
    """
    import subprocess
    import sys as _sys

    from nogap_build import _frozen_gate

    existing = _frozen_gate(builder.project)
    if existing and existing.get("hash"):
        return existing["hash"]

    root = Path(__file__).resolve().parents[1]
    runtime = builder.project.resolve() / ".code-loop" / "runtime"
    argvs = [["freeze", str(builder.project)]]
    if not (runtime / "run.json").is_file():
        argvs.insert(0, ["init", str(builder.project), "--objective", "fixture"])
    for argv in argvs:
        done = subprocess.run([_sys.executable, str(root / "scripts" / "nogap.py"), *argv],
                              capture_output=True, text=True)
        assert done.returncode == 0, f"{argv[0]} failed: {done.stdout}{done.stderr}"
    gate = _frozen_gate(builder.project)
    assert gate and gate.get("hash"), "freeze did not produce a hashed gate"
    return gate["hash"]


def real_candidate_bindings(project: Path, task_ids: list[str]) -> dict[str, str]:
    """G1-C3 fixture repair: {task_id: candidate_hash} read from the REAL
    P18_VERIFICATION_RESULT the production path already created for each task. Never
    computed or invented. A task with no P18 is left unbound (freeze then fails closed,
    honestly); more than one P18 for a task is refused rather than picking one."""
    from nogap_artifacts import list_artifacts
    bindings: dict[str, str] = {}
    for task_id in task_ids:
        matches = [r for r in list_artifacts(project, artifact_type="P18_VERIFICATION_RESULT")
                   if r["fields"].get("task_id") == task_id]
        assert len(matches) <= 1, f"fixture: {len(matches)} P18 records for {task_id!r}; refusing to pick one"
        if matches:
            bindings[task_id] = matches[0]["fields"]["candidate_hash"]
    return bindings


def _binding_snapshot(self) -> dict[str, Any]:
    """The live binding fields for this builder's task, via the module that owns them."""
    from nogap_verify_binding import verification_binding_snapshot

    # gate_hash comes from a REAL frozen gate, so readiness compares like with like.
    snapshot = verification_binding_snapshot(
        self.project, self.artifacts["P12"]["fields"]["task_id"],
        self.ensure_gate())
    return snapshot  # requirement_refs included: readiness compares it against the contract


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
    # The binding fields are computed by nogap_verify_binding, not invented. Readiness checks
    # this verification against the LIVE bindings, so placeholder hashes read as "stale" -
    # correctly. The owner module already answers "what would a fresh result's binding be",
    # and the builder asks it rather than recomputing the same thing beside it.
    "P18_VERIFICATION_RESULT": lambda self: dict(
        verification_plan_id=self.artifacts["P15"]["fields"]["verification_plan_id"],
        profile_at_verification="LIGHT", executor_actor_id="agent:fixture",
        levels_attempted=["STATIC_CHECKS"], deterministic_result="passed",
        reproducibility_result="SKIPPED_PER_PROFILE_POLICY",
        independent_review_result="SKIPPED_PER_PROFILE_POLICY",
        task_id=self.artifacts["P12"]["fields"]["task_id"],
        **_binding_snapshot(self)),
    "P14_SELF_CHECK": lambda self: dict(
        task_id=self.artifacts["P12"]["fields"]["task_id"], patch_hash="sha256:p",
        execution_evidence_ids=[self.evidence_ids[-1]] if self.evidence_ids else [],
        changed_files=["x"], process_outcome="completed",
        expected_effect_result="EXPECTED_EFFECT_PRESENT"),
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


# -- real-pipeline mode ---------------------------------------------------------------------
#
# Reaching P21 honestly is not a matter of advancing phases: P21 is entered by a SUCCEEDED
# deployment, a deployment requires a release decision of ACCEPT, and cmd_decide reaches
# ACCEPT only from independent authoritative verification. Each of those is a real rule, so
# the fixture satisfies them by doing the work rather than by arranging its appearance.
#
# What this mode must NOT do, and does not:
#   * no test-only authority override
#   * no fabricated verdict, and no evidence injected behind the verifier's back
#   * no direct methodology-state write
#   * no reimplementation of Decision Engine or lifecycle rules - it calls them
#
# If the pipeline yields ABSTAIN the fixture FAILS LOUDLY. An abstain is the system correctly
# refusing to accept work it cannot vouch for; a fixture that routed around it would be
# manufacturing the eligibility the rule exists to withhold.

EXECUTOR_ID = "codex"        # distinct identities, because independence is the property
REVIEWER_ID = "claude"       # under test - a reviewer that is the executor is not one


class _StubRuntime:
    """A minimal AgentRuntime. It runs a REAL process in a REAL worktree; only the choice
    of command is canned, so execution and review remain genuine observable effects."""

    kind = "AgentRuntime"

    def __init__(self, adapter_id: str, command):
        self.id = adapter_id
        self._command = command

    def health(self):
        return {"status": "connected", "trust_status": "READY"}

    def capabilities(self):
        return {"id": self.id, "kind": self.kind, "can_execute": False,
                "supported_operations": []}

    def build_exec_command(self, prompt, worktree):
        return self._command


def _pipeline_adapters():
    import sys as _sys

    review = json.dumps({"verdict": "pass", "notes": "independent review"})
    return {
        EXECUTOR_ID: _StubRuntime(EXECUTOR_ID, [
            _sys.executable, "-c", "open('target.txt','w').write('work')"]),
        REVIEWER_ID: _StubRuntime(REVIEWER_ID, [
            _sys.executable, "-c", f"open('.nogap-review.json','w').write({review!r})"]),
    }


def _ensure_git_repo(project: Path) -> None:
    import subprocess

    if (project / ".git").is_dir():
        return
    run = lambda *a: subprocess.run(["git", *a], cwd=project, check=True, capture_output=True)
    run("init", "-q")
    run("config", "user.email", "fixture@example.invalid")
    run("config", "user.name", "fixture")
    (project / "README.md").write_text("fixture\n", encoding="utf-8")
    run("add", "README.md")
    run("commit", "-q", "-m", "fixture baseline")


def advance_via_real_pipeline(project: Path, actor: str = "fixture") -> "FixtureBuilder":
    """Drive the genuine chain and return the builder once P21 is reached.

        real execution -> independent authoritative verification -> ACCEPT decision
        -> release candidate -> readiness -> deployment -> P21

    Every step is a production entry point. The builder's job here is orchestration: it
    supplies real inputs and checks the outcome, and never decides a verdict or a phase.
    """
    import argparse

    import nogap
    import nogap_adapters
    import nogap_lifecycle as nlc

    # Real execution happens in a real git worktree, so the project must be a real
    # repository. Establishing that is environment setup, the same kind of thing as
    # `nogap init` - it is not a rule the builder is deciding.
    _ensure_git_repo(project)
    builder = FixtureBuilder(project, actor=actor)
    builder.advance_to("P12")
    # P12's own obligation. advance_to stops AT P12, and an artifact a phase owes is created
    # on the way out - so the task contract the run binds to has to be made explicitly here.
    builder._artifact_for("P12")
    task_id = builder.artifacts["P12"]["fields"]["task_id"]

    saved = dict(nogap_adapters.ADAPTERS)
    nogap_adapters.ADAPTERS.clear()
    nogap_adapters.ADAPTERS.update(_pipeline_adapters())
    try:
        # P12 -> P13 -> P14: a real command in a real isolated worktree.
        nogap.cmd_run(argparse.Namespace(
            path=str(project), actor=actor, execute=True, execute_timeout=600,
            task_id=task_id))
        # P15 -> P18: the verification ladder, with a reviewer whose identity differs from
        # the executor's. Passing --review is what makes the result INDEPENDENT.
        nogap.cmd_verify_methodology(argparse.Namespace(
            path=str(project), dispatch=None, timeout=120, review=True, review_timeout=120,
            actor="verifier"))
        # The Decision Engine decides. The fixture only checks what it decided.
        nogap.cmd_decide(argparse.Namespace(
            path=str(project), actor="nogap decide", actor_id="human:owner",
            authority="acceptance"))
    finally:
        nogap_adapters.ADAPTERS.clear()
        nogap_adapters.ADAPTERS.update(saved)

    decisions = sorted((project.resolve() / ".code-loop" / "runtime" / "decisions")
                       .glob("*.json"))
    assert decisions, "the pipeline produced no decision at all"
    decision = json.loads(decisions[-1].read_text(encoding="utf-8"))
    assert decision["decision"] == "accept", (
        f"the Decision Engine returned {decision['decision']!r}, not accept: "
        f"{decision.get('reason')!r}. The fixture FAILS here on purpose - an abstain means "
        f"the independent verification was not authoritative, and manufacturing eligibility "
        f"past it would defeat the rule this chain exists to honour.")

    builder.evidence_ids = [
        p.stem for p in (project.resolve() / ".code-loop" / "runtime" / "evidence").glob("*.json")]
    rc = nlc.create_release_candidate(
        project, version="0.0.1", candidate_ref="fixture-rc", code_revision="deadbeef",
        verification_refs=builder.evidence_ids, included_task_refs=[task_id],
        evidence_refs=sorted(
            p.stem for pattern in ("evidence-exec-*.json", "evidence-verify-*.json")
            for p in (project.resolve() / ".code-loop" / "runtime" / "evidence").glob(pattern)),
        decision_refs=[decision["id"]], candidate_bindings=real_candidate_bindings(project, [task_id]),
        actor=actor, reason="fixture candidate")
    rc_id = rc["release_candidate_id"]
    nlc.freeze_release_candidate(project, rc_id, actor=actor, reason="freeze")
    readiness = nlc.evaluate_release_readiness(
        project, rc_id, actor=actor, reason="evaluate readiness")
    deployment = nlc.create_deployment(
        project, release_candidate_id=rc_id, readiness_id=readiness["readiness_id"],
        environment="production", deployment_target="k8s",
        decision_refs=[decision["id"]], actor=actor, reason="deploy")
    nlc.record_deployment_result(
        project, deployment["deployment_id"], status="SUCCEEDED", actor=actor,
        reason="deploy completed")
    # A real operational observation against the real deployment. P21 declares
    # OPERATIONAL_OBSERVATIONS, so a fixture that stops short here cannot leave P21 - and
    # should not be able to.
    observation = nlc.record_operational_observation(
        project, deployment_id=deployment["deployment_id"], signal_type="metric",
        metric_name="latency_ms", metric_value=100.0, actor=actor,
        reason="fixture telemetry")
    builder._lifecycle.update({"rc": rc_id, "readiness": readiness["readiness_id"],
                               "deployment": deployment["deployment_id"],
                               "observation": observation["observation_id"]})
    return builder
