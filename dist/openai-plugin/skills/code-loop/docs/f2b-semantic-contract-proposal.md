# F2b — Semantic Contract, Revision 2 (NORMATIVE DRAFT)

**Status: NORMATIVE DRAFT, not yet implemented.** No resolver, no migration, no enforcement.
Every kind below still reports `SEMANTIC_VALIDATION_DEFERRED` until it is implemented
kind-by-kind after review of this revision.

Revision 1 was a proposal. This revision records the user's rulings and states them as the
contract the implementation will be held to. Where a ruling changed the proposal, the change and
its reason are kept visible rather than silently absorbed — a contract that hides why it says
what it says invites the next reader to re-derive it wrongly.

MUST / MUST NOT are normative. "Declaration required" means a change to the methodology contract
data must land **before** the kind can be enforced.

---

## 0. What changed from Revision 1

| kind | Rev 1 | Rev 2 |
|---|---|---|
| `REVIEW_VERDICT` | add `reviewer_actor_id` to P18 | **rejected** — bind P18 to authoritative evidence instead |
| `REQUIREMENTS` | three candidate rules offered | **decided** — authoritative active-set coverage |
| `EVIDENCE_BUNDLE` | needs a new record type | **decided** — the frozen evidence set of the release candidate, declared explicitly |
| `RISK_CLASSIFICATION` | declare an equivalence to `risk_level` | **renamed** to `RISK_LEVEL` |
| `BUILD_VS_BUY_DECISION` | rename proposed | **rename approved** → `STRATEGY_DECISION` |
| `GOLDEN_GATES` | "its `rules` declare a binding condition" | **corrected** — no `rules` field may be assumed; use the declared integrity check |

The `REVIEW_VERDICT` ruling is the most consequential. Adding `reviewer_actor_id` to
`P18_VERIFICATION_RESULT` would have created a SECOND COPY of a fact the verification layer
already holds, free to diverge from it later. A contract that stores the same truth twice has
two truths.

---

## 1. Declaration changes required first

These are changes to the methodology contract data. Until each lands, its kind stays deferred.

**D1 — rename `BUILD_VS_BUY_DECISION` to `STRATEGY_DECISION`** in the P5 phase contract.
`STRATEGY_OPTIONS` declares six values (`BUILD`, `BUY`, `ADOPT`, `FORK`, `INTEGRATE`, `HYBRID`);
a binary name cannot express a project that selected `FORK`.

**D2 — rename `RISK_CLASSIFICATION` to `RISK_LEVEL`** in the P2 phase contract. What is declared
is a scalar `risk_level`. Rather than give "classification" a meaning larger than the data and
then compress it back down, the kind takes the name of the thing that exists. A multidimensional
risk classification, if wanted later, is a NEW artifact and contract — not a reinterpretation of
this one.

**D3 — declare that `measurement_procedure` IS the benchmark protocol** in the P10 phase
contract. The equivalence is plausible but nowhere stated, and an unstated equivalence is a
heuristic.

**D4 — declare that a release candidate's frozen `evidence_refs` set IS the evidence bundle** in
the P19 phase contract. This resolves Revision 1's open question WITHOUT a new record type, but
only because it is declared. Re-deriving it from "a release candidate happens to carry
`evidence_refs`" is the inference that was withdrawn during F2a and MUST NOT return.

**D5 — declare a P18-to-evidence binding** (see §2.6). `P18_VERIFICATION_RESULT` MUST carry a
resolvable reference to the authoritative verification evidence that produced its verdict.

**D6 — a new representation for `RUNTIME_STRUCTURE`** (see §3.1). Not designed here.

---

## 2. Normative semantics

### 2.1 SCOPE (P1) — APPROVED

- **Semantic definition.** The bounded statement of what the project will and will not address.
  Scope is intrinsically a pair: a boundary is defined as much by exclusion as by inclusion.
- **Authoritative owner.** Methodology artifact.
- **Concrete source.** The `P1_SCOPE` artifact **as a whole**. No field named `scope` is declared
  and none MUST be invented.
- **Completeness rule.** The artifact MUST resolve, MUST be ACTIVE, MUST pass `validate_record`,
  and BOTH `in_scope` and `out_of_scope` MUST be present and non-empty.
- **Failure conditions.** `MISSING` · `WRONG_TYPE` · `INVALID` (contract fails, or either half of
  the pair empty) · `STALE`.

### 2.2 PRIOR_ART_MAP (P3) — APPROVED

- **Semantic definition.** The recorded survey of prior art examined before choosing an approach.
- **Authoritative owner.** Methodology artifact.
- **Concrete source.** The `P3_PRIOR_ART` artifact as a whole. The artifact's own declared
  contract IS the map; no field of that name exists and none MUST be invented.
- **Completeness rule.** Resolves, ACTIVE, passes `validate_record`.
- **Failure conditions.** `MISSING` · `WRONG_TYPE` · `INVALID` · `STALE`.

### 2.3 TEST_PLAN (P11) — APPROVED

- **Semantic definition.** The declared set of tests the gate expects to be run.
- **Authoritative owner.** Methodology artifact (intent layer).
- **Concrete source.** `P11_GATE_PLAN.required_tests`.
- **Completeness rule.** Artifact resolves, ACTIVE, valid; `required_tests` non-empty.
- **Failure conditions.** `MISSING` · `WRONG_TYPE` · `INVALID` · `STALE`.
- **Separation.** P11 declares both `TEST_PLAN` and `GOLDEN_GATES`. They are separated by OWNER
  (§2.7), so one `P11_GATE_PLAN` MUST NOT satisfy both.

### 2.4 BENCHMARK_PROTOCOL (P10) — APPROVED WITH DECLARATION D3

- **Semantic definition.** The declared procedure by which the baseline's metrics are measured:
  how a number is obtained, not which numbers matter.
- **Authoritative owner.** Methodology artifact.
- **Concrete source.** `P10_BASELINE.measurement_procedure`, **once D3 declares the equivalence**.
- **Completeness rule.** Artifact resolves, ACTIVE, valid; `measurement_procedure` present and
  non-empty.
- **Failure conditions.** `MISSING` · `WRONG_TYPE` · `INVALID` · `STALE` · `UNMAPPED` before D3.

### 2.5 METRICS (P10) — APPROVED

- **Semantic definition.** The set of measures against which the baseline is stated.
- **Authoritative owner.** Methodology artifact.
- **Concrete source.** The declared metric SET: `primary_metric` AND `secondary_metrics` together.
- **Completeness rule.** `primary_metric` MUST be present and non-empty. `secondary_metrics` MAY
  be empty — a baseline with one measure is legitimate — but the field MUST exist. Satisfying the
  kind from either field alone would let a baseline declare secondaries and no primary, or the
  reverse, and still claim "metrics".
- **Failure conditions.** `MISSING` · `WRONG_TYPE` · `INVALID` (no `primary_metric`) · `STALE`.

### 2.6 REVIEW_VERDICT (P18) — DESIGN CHANGED, REQUIRES D5

- **Semantic definition.** The outcome of independent review OF a specific candidate, BY an
  identity distinct from the executor, PROVEN by authoritative evidence. A verdict detached from
  what it judged and who issued it is not a verdict; it is a word.
- **Authoritative owner.** The **verification evidence layer**. `P18_VERIFICATION_RESULT` is the
  RESULT RECORD; it is not itself the proof.
- **Rejected alternative, and why.** Revision 1 proposed adding `reviewer_actor_id` to P18. That
  is rejected: the reviewing identity already exists in the verification evidence, and copying it
  into the result artifact creates a second instance of one fact which can later disagree with the
  first. The result record MUST reference the evidence, not restate it.
- **Concrete source.** The chain:

      P18_VERIFICATION_RESULT
        -> references (D5)
      authoritative verification evidence
        -> proves: reviewer identity, candidate/task binding, verdict, independence

- **Completeness / binding rule.** All of the following MUST hold:
  1. the P18 artifact resolves, is ACTIVE, passes `validate_record`;
  2. `independent_review_result` is a DECIDED value — `PENDING` is not a verdict;
  3. the referenced evidence resolves to an authoritative verification record;
  4. **the P18 result EQUALS the evidence verdict**;
  5. **the P18 candidate/task binding EQUALS the evidence candidate/task binding**;
  6. **the reviewing identity is NOT the executing identity**.
- **Failure conditions.** `MISSING` · `WRONG_TYPE` · `INVALID` (undecided verdict; unresolvable
  evidence reference; **any divergence between the result record and the evidence it cites**;
  reviewer identical to executor) · `STALE`.
- **Note on divergence.** Conditions 4 and 5 are the reason for this design. If the result and the
  evidence can disagree, the artifact can assert a pass the evidence never supported. Divergence
  MUST be a binding failure, never a preference for one side.

### 2.7 GOLDEN_GATES (P11) — APPROVED, OWNER DIFFERS FROM DECLARING PHASE

- **Semantic definition.** The gate conditions that ACTUALLY BIND execution — what the system will
  refuse to accept — as distinct from the gate a phase planned.
- **Authoritative owner.** **The Trust Runtime**, not the methodology artifact. This is the only
  kind in this contract whose owner is not its declaring phase's artifact.
- **Concrete source.** The current **frozen** Trust gate.
- **Rationale.** `P11_GATE_PLAN` is INTENT; a frozen gate is the ENFORCED condition. Satisfying
  this kind from the plan would let a phase assert a constraint the runtime was never bound by.
- **Completeness rule.** Determined by the **declared integrity check**, not by an assumed field:
  1. a gate exists with `status == "frozen"`;
  2. its `hash` EQUALS the hash recomputed from its payload — the check `cmd_validate` already
     performs, and the same one used to reject a gate edited after freezing;
  3. it declares at least one actual binding condition.
- **Implementation constraint (normative).** The implementation MUST NOT assume a field named
  `rules`, or any other shape, unless the gate's own declared structure provides it. There is
  currently **no gate schema file and no dedicated gate validator**; the authoritative integrity
  logic lives in `cmd_validate`. The implementation MUST use that logic rather than re-deriving
  it, and if a gate schema is later introduced it becomes the source.
- **Alignment stays separate.** `gate_alignment_reasons` compares plan against frozen gate. That
  remains its OWN check and MUST NOT be folded into this kind.
- **Failure conditions.** `MISSING` (no frozen gate) · `INVALID` (hash mismatch, or no binding
  condition) · `STALE` (superseded by a later freeze). This kind CANNOT produce `WRONG_TYPE`: it
  does not resolve against artifacts at all.

### 2.8 STRATEGY_DECISION (P5) — REQUIRES D1

- **Semantic definition.** The recorded decision of how the project will obtain the capability,
  chosen from the declared option set.
- **Authoritative owner.** Methodology artifact.
- **Concrete source.** `P5_STRATEGY_DECISION.selected_strategy`.
- **Completeness rule.** Artifact resolves, ACTIVE, valid; `selected_strategy` is a member of
  `STRATEGY_OPTIONS`; `gap_analysis_refs` resolves.
- **Failure conditions.** `MISSING` · `WRONG_TYPE` · `INVALID` (value outside the declared enum,
  or unresolvable `gap_analysis_refs`) · `STALE` · `UNMAPPED` before D1.

### 2.9 RISK_LEVEL (P2) — REQUIRES D2

- **Semantic definition.** The declared scalar risk level of the project.
- **Authoritative owner.** Methodology artifact.
- **Concrete source.** `P2_SUCCESS_CRITERIA.risk_level`.
- **Completeness rule.** Artifact resolves, ACTIVE, valid; `risk_level` present and a declared
  value.
- **Failure conditions.** `MISSING` · `WRONG_TYPE` · `INVALID` · `STALE` · `UNMAPPED` before D2.

### 2.10 REQUIREMENTS (P6) — SEMANTICS DECIDED: authoritative active-set coverage

- **Semantic definition.** The complete set of requirements currently in force. Not "a
  requirement exists".
- **Authoritative owner.** Methodology artifacts (`P6_REQUIREMENT`, one per requirement).
- **Concrete source.** `R` = every `P6_REQUIREMENT` whose status is `ACTIVE`.
- **Completeness rule.** On leaving P6, ALL of the following MUST hold:
  1. `R` is NOT empty;
  2. every member of `R` passes `validate_record`;
  3. every `requirement_id` in `R` is UNIQUE;
  4. **the references supplied for this kind MUST COVER ALL OF `R`** — not one arbitrary member;
  5. a `SUPERSEDED` or `REJECTED` requirement MUST NOT stand in for an `ACTIVE` one.
- **Failure conditions.** `MISSING` / incomplete — an ACTIVE requirement is not covered by the
  references supplied · `INVALID` — duplicate or conflicting `requirement_id`, or a member that
  fails its contract · `STALE` — a superseded or rejected requirement offered in place of an
  active one.
- **Deliberate independence.** This rule depends only on P6 itself. It does NOT reference P7 or
  P11, which do not exist yet when P6 is left. Coverage rules that looked downstream were
  considered and rejected for that reason.

### 2.11 EVIDENCE_BUNDLE (P19) — SEMANTICS DECIDED, REQUIRES D4

- **Semantic definition.** The evidence set frozen with a release candidate: the proof carried
  forward with the thing being released.
- **Authoritative owner.** The **release candidate** is the CONTAINER and BINDING OWNER. The
  bundle is not itself a record type, and none is created.
- **Concrete source.** The `evidence_refs` set of the release candidate under consideration,
  **once D4 declares it**.
- **Completeness rule.** A non-empty list is NOT sufficient. Every member MUST:
  1. resolve to an authoritative evidence record;
  2. be current — not stale, superseded or invalidated;
  3. bind to the task/candidate this release candidate covers;
  4. satisfy the evidence kinds required for the release.
- **OPEN QUESTION (must be answered before implementation).** Which declaration governs
  requirement 4? Both `P11_GATE_PLAN.evidence_requirements` and
  `P15_VERIFICATION_PLAN.required_evidence_kinds` exist. This contract does NOT choose between
  them; choosing would be exactly the inference this pass exists to prevent.
- **Failure conditions.** `MISSING` (no candidate, or an empty set) · `INVALID` (a member that
  does not resolve, or is bound to a different task/candidate, or a missing required evidence
  kind) · `STALE` (a member no longer current).

---

## 3. Still deferred

### 3.1 RUNTIME_STRUCTURE (P9) — NEW REPRESENTATION REQUIRED

No field of `P9_GOVERNANCE` declares it, no module represents it, and nothing exists to resolve
against. It requires a new schema — `P9_RUNTIME_STRUCTURE` or an equivalent authoritative
representation — with its components and boundaries defined.

**It MUST NOT be designed incidentally inside a resolver.** A representation invented to make a
check pass is a contract written by its own enforcement, which is the inversion this whole item
exists to prevent. Stays `SEMANTIC_VALIDATION_DEFERRED`.

### 3.2 Owned by later closure items

| kind | owner | item |
|---|---|---|
| `MEMORY_CONFIGURATION` | `nogap_memory.py` (GP-9, PARTIAL) | closure item 6 |
| `COST_MODEL` | **none declared** (GP-13, DECLARED) | closure item 7 |

Out of scope here by decision. `enforcement.json` records `GP-13.owner_component` as `none`, so
`COST_MODEL` has no owner by the project's own declaration and cannot be mapped until item 7
gives it one.

---

## 4. State after Revision 2

| status | kinds |
|---|---|
| semantics closed, implementable after D1-D4 | SCOPE, PRIOR_ART_MAP, TEST_PLAN, BENCHMARK_PROTOCOL, METRICS, GOLDEN_GATES, STRATEGY_DECISION, RISK_LEVEL, REQUIREMENTS, EVIDENCE_BUNDLE |
| needs binding declaration D5 | REVIEW_VERDICT |
| needs an independent representation D6 | RUNTIME_STRUCTURE |
| later closure items | MEMORY_CONFIGURATION (GP-9), COST_MODEL (GP-13) |

Two questions remain open inside otherwise-decided kinds, and both are recorded rather than
resolved by assumption: the P18-to-evidence reference D5 requires, and which declaration governs
required evidence kinds for a release (§2.11).

Nothing here is implemented. Implementation proceeds kind-by-kind only after this revision is
reviewed.
