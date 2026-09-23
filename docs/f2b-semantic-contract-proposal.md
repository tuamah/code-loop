# F2b — Semantic Contract Proposal (12 kinds)

**Status: PROPOSAL. No implementation, no resolver, no migration.**

F2a closed a hole by making `required_artifacts` mean something: each declared semantic KIND is
proven independently against the references supplied. Fourteen kinds could not be mapped, because
the methodology declares *what* each phase owes without declaring *how to tell whether it was
delivered*. Guessing those mappings from field names is the one thing that would reintroduce the
hole in a more elegant form — a container of the right type is not proof the required meaning is
inside it.

This document proposes the missing declarations. It changes no code. Two kinds are deliberately
absent: `MEMORY_CONFIGURATION` belongs to GP-9 and `COST_MODEL` to GP-13, and specifying them here
would either duplicate that work or pre-commit it.

Each entry states five things:

    semantic definition -> authoritative owner -> concrete source
      -> completeness / binding rule -> failure conditions

---

## Part 1 — Specifiable now

These need a more precise declaration, not a new owner.

### 1. SCOPE (P1)

- **Semantic definition.** The bounded statement of what the project will and will not address.
  Scope is intrinsically a *pair*: a boundary is defined as much by exclusion as inclusion, so
  `in_scope` alone does not express it.
- **Authoritative owner.** Methodology artifact (`P1_SCOPE`).
- **Concrete source.** The `P1_SCOPE` artifact **as a whole**, not one field.
- **Completeness rule.** The artifact resolves, is ACTIVE, passes `validate_record`, and both
  `in_scope` and `out_of_scope` are present and non-empty. Declaring the whole artifact avoids
  inventing a field named `scope`, which `P1_SCOPE` does not declare.
- **Failure conditions.** `MISSING` (no P1_SCOPE resolves) · `WRONG_TYPE` · `INVALID` (contract
  fails, or either half of the pair is empty) · `STALE` (SUPERSEDED/REJECTED).

### 2. PRIOR_ART_MAP (P3)

- **Semantic definition.** The recorded survey of prior art the project examined before choosing
  an approach.
- **Authoritative owner.** Methodology artifact (`P3_PRIOR_ART`).
- **Concrete source.** The `P3_PRIOR_ART` artifact as a whole. The kind's name says "map", but no
  field of that name is declared, and inventing one would be the heuristic this document exists
  to avoid. The artifact's own contract (`research_question`, `search_scope`, `sources`,
  `candidate_solutions`, `key_findings`, `limitations`) *is* the map.
- **Completeness rule.** Resolves, ACTIVE, passes `validate_record`.
- **Failure conditions.** `MISSING` · `WRONG_TYPE` · `INVALID` · `STALE`.

### 3. TEST_PLAN (P11)

- **Semantic definition.** The declared set of tests the gate expects to be run.
- **Authoritative owner.** Methodology artifact (`P11_GATE_PLAN`).
- **Concrete source.** The `required_tests` field of `P11_GATE_PLAN`.
- **Completeness rule.** Artifact resolves, ACTIVE, valid, and `required_tests` is non-empty.
- **Failure conditions.** `MISSING` · `WRONG_TYPE` · `INVALID` (empty `required_tests`) · `STALE`.
- **Note — two kinds, one container.** P11 declares both `TEST_PLAN` and `GOLDEN_GATES`, and both
  would otherwise be satisfied by one artifact. This proposal separates them by OWNER (below), so
  a single `P11_GATE_PLAN` no longer silently satisfies both.

### 4. BENCHMARK_PROTOCOL (P10)

- **Semantic definition.** The declared procedure by which the baseline's metrics are measured —
  how a number is obtained, not which numbers matter.
- **Authoritative owner.** Methodology artifact (`P10_BASELINE`).
- **Concrete source.** The `measurement_procedure` field.
- **DECLARATION REQUIRED BEFORE MAPPING.** `measurement_procedure` is a plausible reading of
  "benchmark protocol", but the contract nowhere says they are the same thing. This proposal asks
  for that equivalence to be **stated in the phase contract**, after which the mapping follows. If
  the intent was a richer protocol (environment, repetitions, tolerances), the field is
  insufficient and the kind stays deferred rather than being satisfied by a prose sentence.
- **Completeness rule (if the equivalence is declared).** Artifact resolves, ACTIVE, valid, and
  `measurement_procedure` is present and non-empty.
- **Failure conditions.** `MISSING` · `WRONG_TYPE` · `INVALID` · `STALE` · `UNMAPPED` until the
  equivalence is declared.

### 5. METRICS (P10)

- **Semantic definition.** The set of measures against which the baseline is stated.
- **Authoritative owner.** Methodology artifact (`P10_BASELINE`).
- **Concrete source.** The declared metric set: `primary_metric` **and** `secondary_metrics`
  together.
- **Completeness rule.** `primary_metric` present and non-empty. `secondary_metrics` may be empty
  — a baseline with one measure is legitimate — but the field must exist. Choosing arbitrarily
  between the two fields would let a baseline declare secondaries and no primary, or the reverse,
  and still satisfy "metrics".
- **Failure conditions.** `MISSING` · `WRONG_TYPE` · `INVALID` (no `primary_metric`) · `STALE`.

### 6. REVIEW_VERDICT (P18)

- **Semantic definition.** The recorded outcome of independent review **of a specific candidate,
  by a specific reviewer**. A verdict detached from what it judged and who issued it is not a
  verdict; it is a word.
- **Authoritative owner.** Verification authority (`P18_VERIFICATION_RESULT`).
- **Concrete source.** THREE bound facts, not one field:
  1. the result — `independent_review_result`
  2. the reviewed subject — `candidate_hash` and `task_id`
  3. the reviewing identity — distinct from `executor_actor_id`
- **Completeness / binding rule.** The artifact resolves, is valid, `independent_review_result` is
  a decided value (not `PENDING`), the candidate binding is present, and the reviewing identity is
  **not** the executing identity. `independent_review_result` alone is insufficient precisely
  because it can read `passed` while saying nothing about who passed it or what they examined.
- **OPEN QUESTION FOR THE USER.** `P18_VERIFICATION_RESULT` declares `executor_actor_id` but no
  `reviewer_actor_id`. Independence is enforced today at verification time
  (`reviewer_is_independent`), but the *result artifact* does not record who reviewed. Binding the
  kind to a reviewing identity therefore requires either a new declared field or resolution
  against the evidence ledger. This is a contract gap, and the kind stays deferred until it is
  decided.
- **Failure conditions.** `MISSING` · `WRONG_TYPE` · `INVALID` (undecided result, or absent
  binding) · `STALE` · a reviewer identical to the executor.

### 7. GOLDEN_GATES (P11)

- **Semantic definition.** The gate conditions that actually bind execution — what the system will
  refuse to accept — as opposed to the gate a phase *planned*.
- **Authoritative owner.** **The Trust Runtime, not the methodology artifact.** This is the one
  Group A kind whose owner differs from its declaring phase's artifact.
- **Concrete source.** The **frozen** Trust gate (`.code-loop/runtime/gates/gate-0001.json`) with
  `status == "frozen"` and a `hash` matching its payload.
- **Rationale.** `P11_GATE_PLAN` is intent; a frozen gate is the enforced condition. Satisfying
  "golden gates" from the plan would let a phase declare gates it never froze — the artifact would
  assert a constraint the runtime was never bound by. The plan can *disagree* with the frozen gate,
  which is why `gate_alignment_reasons` already exists; that alignment stays a SEPARATE check and
  is not folded into this kind.
- **Completeness rule.** A frozen gate exists, its hash matches its payload, and its `rules`
  declare at least one binding condition.
- **Failure conditions.** `MISSING` (no frozen gate) · `INVALID` (hash mismatch — a gate edited
  after freezing) · `STALE` (superseded by a later freeze). Note this kind cannot produce
  `WRONG_TYPE`: it does not resolve against artifacts at all.

---

## Part 2 — Contract correction required before any mapping

For these the current *declaration* is wrong or incomplete. No resolver should be written against
a name that does not describe what it names.

### 8. BUILD_VS_BUY_DECISION (P5) — the NAME is wrong

- **Problem.** The kind is binary; `STRATEGY_OPTIONS` declares six values: `BUILD`, `BUY`, `ADOPT`,
  `FORK`, `INTEGRATE`, `HYBRID`. A project that selected `FORK` has made a strategy decision that
  the kind's own name cannot express. Mapping it to `selected_strategy` would paper a six-way
  decision over a two-way name.
- **Proposed correction.** Rename the declared kind to `STRATEGY_DECISION` in the P5 phase
  contract. This is a methodology-definition change, not a mapping.
- **After correction.** Owner: `P5_STRATEGY_DECISION`. Source: `selected_strategy`. Complete when
  it holds a member of `STRATEGY_OPTIONS` and `gap_analysis_refs` resolves.
- **Until corrected.** Stays deferred.

### 9. RISK_CLASSIFICATION (P2) — equivalence UNDECLARED

- **Problem.** `P2_SUCCESS_CRITERIA` declares `risk_level`. Whether a *classification* is the same
  thing as a *level* is a contract question. A level is one scalar; a classification may mean
  level plus the reasoning, or a multi-dimensional categorisation.
- **Proposed correction.** The contract must either (a) declare that `RISK_CLASSIFICATION` is
  satisfied by `risk_level`, or (b) declare the components a classification requires.
- **Until corrected.** Stays deferred. Assuming (a) is exactly the near-miss-name heuristic that
  this pass exists to prevent.

### 10. REQUIREMENTS (P6) — COMPLETENESS undeclared

- **Problem.** The kind is plural; `P6_REQUIREMENT` is one artifact per requirement. "At least one
  requirement exists" is a weak reading that would let a project leave P6 with a single
  placeholder. Nothing declares what makes a requirement SET complete.
- **Relevant declared facts.** Requirements carry `requirement_id` and a status from
  `{ACTIVE, SUPERSEDED, REJECTED, SATISFIED}`; `P7_ARCHITECTURE` and `P11_GATE_PLAN` both carry
  `requirement_refs`, so downstream phases already reference requirements individually.
- **Candidate completeness rules (for the user to choose, NOT to be assumed).**
  (a) at least one ACTIVE requirement; (b) every ACTIVE requirement traces to the P5 strategy
  decision; (c) coverage — every requirement referenced downstream resolves to an ACTIVE
  requirement.
- **Until decided.** Stays deferred.

### 11. RUNTIME_STRUCTURE (P9) — NO representation exists

- **Problem.** `P9_GOVERNANCE` declares no such field, and no module represents a runtime
  structure. There is nothing to resolve against.
- **Proposed correction.** Requires a declaration and an owner before anything else. This is
  design, not mapping.
- **Until decided.** Stays deferred.

### 12. EVIDENCE_BUNDLE (P19) — NO authoritative type

- **Problem.** No record type of this name exists anywhere in `nogap_lifecycle`. An earlier draft
  of the F2a map bound it to `release_candidates` because a release candidate carries
  `evidence_refs`. That was a judgement, not a declaration, and it was withdrawn.
- **Proposed correction.** Either a new authoritative record type, or an explicit declaration that
  a release candidate's evidence set IS the bundle — stated in the contract, not inferred from the
  presence of a field.
- **Until decided.** Stays deferred. Binding it to `release_candidates` without that declaration
  would repeat the withdrawn mistake.

---

## Summary

| kind | proposed owner | status after this pass |
|---|---|---|
| SCOPE | `P1_SCOPE` (whole) | specifiable |
| PRIOR_ART_MAP | `P3_PRIOR_ART` (whole) | specifiable |
| TEST_PLAN | `P11_GATE_PLAN.required_tests` | specifiable |
| METRICS | `P10_BASELINE` metric set | specifiable |
| GOLDEN_GATES | **frozen Trust gate** | specifiable |
| BENCHMARK_PROTOCOL | `P10_BASELINE.measurement_procedure` | needs one declared equivalence |
| REVIEW_VERDICT | verification authority | needs a reviewer-identity binding |
| BUILD_VS_BUY_DECISION | `P5_STRATEGY_DECISION` | needs a RENAME |
| RISK_CLASSIFICATION | `P2_SUCCESS_CRITERIA` | needs a declared equivalence or components |
| REQUIREMENTS | `P6_REQUIREMENT` set | needs completeness semantics |
| RUNTIME_STRUCTURE | none | needs a declaration and an owner |
| EVIDENCE_BUNDLE | none | needs an authoritative type |

Five are specifiable as written. Two need a single declaration each. Five need contract design.
`MEMORY_CONFIGURATION` (GP-9) and `COST_MODEL` (GP-13) are out of scope here by decision.

Nothing in this document may be implemented before the user rules on it. A kind whose semantics
are not decided stays `SEMANTIC_VALIDATION_DEFERRED` — visible, enumerated, and never reported as
verified.
