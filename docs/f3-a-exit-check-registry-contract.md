# F3-A — Exit Check Registry Contract

Status: **ACCEPTED / FROZEN.** This document fixes the semantics of a new closed
registry (`exit_gate.checks` → decided meaning) before any resolver, dispatcher, or
transition-blocking code exists — the same discipline D6 used for `P9_RUNTIME_STRUCTURE`
(`docs/d6-runtime-structure-contract.md`). No production code exists yet for anything in
this document. Consulted "Opus 5.5" for an independent second opinion per instruction; its
input shaped §3 (FAIL/ERROR), §4 (resolver contract), §5 (P23 placeholder row), and the
structural-risk fixes folded into §7.

## 0. What this closes, and what it explicitly does not

`exit_gate.checks` across `methodology/phases/p00..p23.json` are 50 free-text names, read by
`nogap_methodology.py` only for shape (non-empty list of strings) — **no code anywhere
interprets a single check name semantically today.** Three successive rounds classified all
50: F3-CLASSIFICATION-PRE (initial survey, later found to under-verify what several
mechanisms actually prove), F3-RECLASSIFICATION-PRE (ground-up re-verification against the
real 36 `ENFORCED_KINDS`, after finding `LedgerEvidence` proves only record *shape*
`(kind, authority, run_id)`, never the deeper per-run content some check names implied), and
F3-RECLASSIFICATION-FINAL-CHECK (targeted re-verification of 7 still-uncertain rows). §9 is
the authoritative, accepted result: **25 `DIRECT_COMPOSITION` (2 registry-blocked on a small
wording fix) · 13 `SMALL_BINDING` · 8 `NO_REPRESENTATION` · 3 `BUILD_INVARIANT` (a real
guarantee with no per-project observable datum - see §2's `obligation_scope`) · 1 genuine
architecture conflict (P23, its own separate survey) · Σ = 50.** This classification is a
strictly separate axis from `implementation_status` (§2): **at F3-A freeze, every one of the
50 rows is `implementation_status: UNIMPLEMENTED`** - F3-A fixes the registry's contract and
records, per row, WHAT authoritative mechanism (if any) it composes over; no resolver exists
in production code until F3-B/F3-D/F3-E build and test one.

This document fixes **only the registry contract** — the closed shape that says, for every
declared check, whether it has a decided meaning yet and (if so) where that meaning lives.
It does **not**:
- implement any resolver (that is F3-B, `DIRECT_COMPOSITION` rows only, next after this is accepted)
- wire anything into `_evaluate_transition` or block any transition (F3-F, last)
- resolve `SMALL_BINDING` bindings (F3-D) or `NO_REPRESENTATION` gaps (F3-E)
- resolve the P23 conflict or the `BUILD_INVARIANT` rows' fate (their own separate surveys,
  referenced in §7 but not run here)

## 1. Core principle: composition, never re-derivation

**F3 is a composition layer over already-authoritative predicates. It is never a second
implementation of F1/F2 semantics.** A check whose truth is already decided elsewhere (a
`required_kinds` `Verdict`, a GP-8 authority check in `nogap.py`, a ledger/evidence lookup)
MUST read that existing result, never re-implement the validation independently. This is the
reason F3-A fixes the resolver *return contract* now (§4) rather than leaving it to whatever
F3-B's implementer finds convenient — 25 different composition shapes (§4.4) behind an
underspecified `resolver_id: str` is exactly the shape that lets someone quietly re-derive
truth in F3-B without anyone noticing at review time.

## 2. Registry entry shape

One row per **declared** check (i.e., one row for every string that appears in some phase's
`exit_gate.checks`, no fewer, no more — see §6's identity/coverage invariants).

```
RegistryEntry:
  check_name: str              # exact string as declared in the phase JSON
  phase_id: str                # exact phase_id where it is declared (e.g. "P8")
  classification: DIRECT_COMPOSITION | SMALL_BINDING | NO_REPRESENTATION | BUILD_INVARIANT
                                # | CONFLICT
                                # REPAIR (third REPAIR round): WHAT KIND of check this is, per
                                # the F3-RECLASSIFICATION survey (§9) - kept strictly separate
                                # from implementation_status (WHETHER a resolver is wired in
                                # yet). A DIRECT_COMPOSITION row can be, and at F3-A freeze
                                # always is, UNIMPLEMENTED: classification says an authoritative
                                # mechanism already exists to compose over; implementation_status
                                # says whether the F3 adapter that reads it has actually been
                                # built and tested. Never conflate "this check's authoritative
                                # source is known" with "this check runs today."
  implementation_status: IMPLEMENTED | UNIMPLEMENTED   # see §2.1 - INVALID is NOT a row value.
                                # REPAIR: at F3-A freeze, EVERY row is UNIMPLEMENTED, including
                                # every DIRECT_COMPOSITION row - F3-A is a contract only; no
                                # resolver exists in production code yet (§9 legend). F3-B/F3-D/
                                # F3-E later flip individual rows to IMPLEMENTED as their
                                # resolvers are built, tested, and mutation-verified.
  obligation_scope: PROJECT | BUILD   # REPAIR (F3-RECLASSIFICATION-FINAL-CHECK finding,
                                # second REPAIR round): WHERE the check's underlying truth
                                # lives, kept strictly separate from implementation_status
                                # (CAN the registry evaluate it now) and from
                                # unimplemented_reason (WHY it isn't bound yet). PROJECT means
                                # the guarantee varies per project and per run - an ordinary
                                # exit-gate check. BUILD means the guarantee is a fact about
                                # this codebase's own implementation, true identically for
                                # every project (e.g. "execution always runs in an isolated
                                # worktree" - structurally guaranteed by nogap_execution.py
                                # having no alternate code path, verified with no per-run
                                # evidence field recording it). A BUILD-scoped row can never
                                # become a real per-project resolver by definition - it would
                                # need a different mechanism entirely (a static code-structure
                                # test, not a project-state read), which is exactly why it is
                                # tracked here rather than silently forced into PROJECT scope.
  resolver_id: str | null      # required iff IMPLEMENTED (§4); null iff UNIMPLEMENTED - so
                                # null for every row at F3-A freeze, DIRECT_COMPOSITION rows
                                # included (see planned_resolver_id below for those).
  semantic_source: str | null  # a structured identifier, not free text - uses the
                                # exact same namespaced format as resolver_id (§4), e.g.
                                # "required_kind:GOLDEN_GATES", "authority:gp8_..." - for an
                                # IMPLEMENTED row semantic_source == resolver_id's namespace
                                # string; the field exists separately only because a result's
                                # own semantic_source (§3) is compared against it at
                                # evaluation time (§3.2), not because they can ever differ by
                                # design on the registry row itself. Required iff IMPLEMENTED -
                                # so also null for every row at F3-A freeze.
  planned_resolver_id: str | null   # REPAIR (third REPAIR round), NEW: required iff
                                # classification == DIRECT_COMPOSITION, regardless of
                                # implementation_status; null for every other classification.
                                # Records the namespaced identifier (§4) that §4.4's mapping
                                # proof already established as this check's authoritative
                                # source - what resolver_id BECOMES the moment F3-B/F3-D binds
                                # and flips the row to IMPLEMENTED. This is what lets the
                                # registry state "the mechanism is known" and "no resolver
                                # exists yet" simultaneously without conflating the two: a
                                # DIRECT_COMPOSITION row's planned_resolver_id is filled in at
                                # F3-A freeze from real code (§4.4); its resolver_id stays null
                                # until F3-B actually builds and tests the adapter.
  unimplemented_reason: NOT_BOUND | NO_REPRESENTATION | WORDING_CONFLICT | SCOPE_MISMATCH
                       | RESOLVER_PENDING | null
                                # required iff UNIMPLEMENTED (i.e. every row at F3-A freeze).
                                # NOT_BOUND: real project data exists, a new small predicate
                                # still needs to be DESIGNED (SMALL_BINDING rows - F3-D).
                                # NO_REPRESENTATION: nothing represents this at all, project-
                                # or build-scoped. WORDING_CONFLICT: the check's text disagrees
                                # with reality (a small drift, or - for P23 - a deep, unresolved
                                # conflict); also used for the 2 registry-blocked
                                # DIRECT_COMPOSITION rows (P5, P8) whose mechanism is real but
                                # whose check_name text must be corrected before any resolver
                                # can bind to it (§6 invariant 7). SCOPE_MISMATCH: the declared
                                # check describes a real, true guarantee, but obligation_scope
                                # is BUILD, not PROJECT - it cannot be evaluated by a per-
                                # project resolver as this registry defines one. RESOLVER_PENDING
                                # (REPAIR, third REPAIR round, NEW): classification is
                                # DIRECT_COMPOSITION, the authoritative mechanism already
                                # exists and needs no design decision, only an adapter
                                # (resolver function) that has not been built and tested yet -
                                # the ordinary state of 23 of the 25 DIRECT_COMPOSITION rows at
                                # F3-A freeze, and the only reason value that names "purely
                                # mechanical, F3-B-ready" work rather than an open question.
                                # Distinct from NOT_BOUND (a new predicate must still be
                                # designed, not merely wired) and from WORDING_CONFLICT (the
                                # check's own text must change first).
  blocked_by: str | null       # e.g. "P23-LIFECYCLE-OUTCOME-PRE" or "BUILD-INVARIANT-PRE" for
                                # a row UNIMPLEMENTED pending a named future survey, not just
                                # "not done yet" (§5, §9). Null for RESOLVER_PENDING/NOT_BOUND/
                                # NO_REPRESENTATION rows (§6 invariant 9) - RESOLVER_PENDING
                                # work is F3-B's own ordinary backlog, not blocked on anything
                                # named.
```

### 2.1 `INVALID` is a validation-run outcome, not a row value (Opus-flagged risk, adopted)

Rev 1 of this design (pre-Opus) proposed `INVALID` as a third `implementation_status` value.
That conflates two different things: a row's own declared status, and a fact about the
*registry as a whole* (an unknown declared check with no row; a duplicate row; a phase/check
mismatch; an `IMPLEMENTED` row with no `resolver_id`; an `UNIMPLEMENTED` row with a
`resolver_id` set). None of those is a property of one valid row — they are reasons a
registry *load* fails closed before any row is even usable. So:

- `implementation_status` is two-valued: `IMPLEMENTED | UNIMPLEMENTED`.
- Registry loading is fail-closed: any of the conditions in §6 raises, the registry does not
  load partially, and no evaluation can proceed against a broken registry.

## 3. Evaluation result shape (per check, per run) — separate from the registry

**Deliberately never conflated with `implementation_status`** — "is this check defined at
all" and "did THIS check pass on THIS project just now" are different questions answered at
different times by different code.

```
ExitCheckResult:
  phase_id: str
  check_name: str
  status: PASS | FAIL | UNIMPLEMENTED | ERROR
  detail: str
  semantic_source: str | null   # copied from the registry row at evaluation time; MUST match
                                 # the row's own semantic_source or the result is ERROR (§3.2)

ExitGateEvaluation:
  phase_id: str
  results: list[ExitCheckResult]
  all_implemented: bool         # DERIVED, never stored independently (REPAIR): computed as
                                 # all(r.status != UNIMPLEMENTED for r in results) at
                                 # construction time - never a field that could disagree with
                                 # `results` itself.
  all_passed: bool              # DERIVED likewise: all(r.status == PASS for r in results).
                                 # False whenever ANY result is UNIMPLEMENTED or ERROR, not
                                 # just FAIL - restated here because it is the single most
                                 # security-relevant boolean in this whole contract.
  registry_version: str         # REPAIR: non-null, always. Fixed sentinel "unversioned"
                                 # until F3-F actually assigns real registry versions/digests -
                                 # never `null`, because null would be ambiguous between
                                 # "versioning doesn't exist yet" and "failed to read the
                                 # version," and under future enforcement a null-as-"any
                                 # version is fine" reading is exactly the kind of silent gap
                                 # this contract exists to close.
```

### 3.1 `PASS` / `FAIL` / `ERROR` — precise definitions (Opus's contribution, adopted)

- **`PASS`**: the composed authoritative predicate ran and returned a satisfied verdict.
- **`FAIL`**: the composed authoritative predicate ran and returned a real, well-formed
  negative verdict (e.g. a `required_kinds.Verdict` with a blocking status). This means **the
  project is wrong** — a real obligation is unmet.
- **`ERROR`**: the predicate could not produce a real verdict at all — it raised, its inputs
  were missing/unparseable, or its `resolver_id` did not resolve to a real symbol at runtime.
  This means **the runtime is wrong** — an F3 problem, not a project problem. `ERROR` and
  `FAIL` are never merged; a report distinguishes "your project fails this" from "F3 itself
  couldn't tell."
- **`UNIMPLEMENTED`**: the registry row itself has `implementation_status: UNIMPLEMENTED`.
  Evaluation never invents a verdict for a row with no resolver.
- **A `PASS`-shaped mechanism that finds no evidence at all** (e.g. a required-kind resolves
  to `MISSING`) reports whatever the authoritative mechanism itself reports, translated
  verbatim into `PASS`/`FAIL`/`ERROR` by that mechanism's own existing verdict vocabulary
  (e.g. `required_kinds.MISSING`/`WRONG_TYPE`/`INVALID`/`STALE` all map to `FAIL`; only a
  genuine exception or unresolvable `resolver_id` maps to `ERROR`). **F3 never re-classifies
  the authoritative verdict itself** — it only ever narrows the existing vocabulary into the
  four evaluation states, never overrides what the source mechanism already decided.
- **`ERROR` handling is fail-closed with no fallback and no retry (REPAIR, explicit)**: a
  resolver exception, an unresolvable `resolver_id`, or a `semantic_source` mismatch (§3.2)
  produces `ERROR` once, immediately. The evaluator MUST NOT retry the resolver, MUST NOT
  fall back to inferring a verdict from the check's free-text name or description, and MUST
  NOT treat a missing/erroring resolver as `PASS` under any circumstance. Under any
  enforcement mode other than `REPORT_ONLY` (§3.3), `ERROR` blocks the transition exactly
  like `FAIL` and `UNIMPLEMENTED` do — never a softer outcome than either.

### 3.2 `all_passed` is strict, and `semantic_source` must match (Opus-flagged risks, adopted)

- `all_passed` is true **only** when every result is `PASS` — never merely "no `FAIL`". An
  `ERROR` or `UNIMPLEMENTED` result must never let `all_passed` read `true` by omission.
- If a result's `semantic_source` does not match the registry row's own `semantic_source` at
  evaluation time (e.g. the registry was edited between load and evaluation, or a resolver
  reports from the wrong place), the result is `ERROR`, not silently trusted.

### 3.3 No per-result `blocks_transition` field (Opus-flagged risk, adopted)

Unlike `required_kinds.Verdict` (which carries `blocks_transition` per kind, because F2b
kinds are already wired into a real blocking transition), F3-A's `ExitCheckResult` carries
**no** `blocks_transition` field. Blocking-or-not is an **enforcement-mode property of the
phase's gate as a whole**, not a per-check flag — this is what prevents the exact failure
mode this whole effort exists to close: a phase whose exit gate is "enforced" while some of
its declared checks are quietly advisory because they happen to be unimplemented. In F3-A/
F3-C (report-only), every phase's exit-gate enforcement mode is uniformly `REPORT_ONLY`; when
F3-F turns blocking on for a given phase, it is turned on for that phase's gate as a whole,
never per-check within an already-blocking gate.

**REPAIR, stated as an explicit rule for F3-F (named now, enforced later, never silently
decided at implementation time)**: once a phase's gate enforcement mode is anything other
than `REPORT_ONLY`, that gate's evaluation containing even a single `UNIMPLEMENTED` or
`ERROR` result MUST make the gate as a whole non-passable for that transition — never a
silent `PASS`-equivalent, never an implicit downgrade to advisory for just that one check.
The only two legal states for an enforced gate are: (a) every row is `IMPLEMENTED` and every
result is `PASS`, transition proceeds; or (b) anything else, transition is blocked. There is
no third state where enforcement is "on" but selectively porous per check. If a phase is not
ready for full enforcement (some rows still `UNIMPLEMENTED`), the correct answer is to leave
that phase's gate at `REPORT_ONLY`, not to enforce it with gaps.

**Ownership of the enforcement-mode flag (REPAIR — corrected after a real gap was found in
this section's first draft; see below)**: F3-A does not define where this flag lives (F3-F's
job). What F3-A DOES fix now is the fail-closed direction, because the first draft's blanket
"default to `REPORT_ONLY` on absent/unreadable/malformed" was itself a silent fail-open path:
a phase already enforced whose stored enforcement-mode config later becomes corrupted (disk
issue, bad write, schema drift) would silently downgrade to `REPORT_ONLY` and stop blocking -
a *silent enforcement downgrade*, exactly the failure class this whole document exists to
close. The two cases are not the same and must not share one default:

- **`NOT_CONFIGURED`** (no enforcement-mode state has ever been established for this phase -
  the ordinary state for every phase before F3-F ever runs, and for any phase F3-F has not
  yet turned on): reads as `REPORT_ONLY`. This is not fail-open in the dangerous sense - there
  is no prior enforced state being silently abandoned, because none was ever established.
- **Explicitly configured, but unreadable / malformed / fails its own schema check** (a state
  record exists, naming that this phase WAS put into some enforcement mode, but it cannot be
  parsed or trusted as of this read): this is `ERROR`, fail-closed, and blocks the transition
  - never silently re-interpreted as `REPORT_ONLY`. An enforcement decision that was made and
  can no longer be read back is a runtime fault, not an invitation to fall back to the
  unenforced default.

`NOT_CONFIGURED` and `MALFORMED_CONFIGURED` MUST therefore be distinguishable states in
whatever F3-F's storage turns out to be - "no evidence of an enforcement decision" and "an
enforcement decision exists but this read of it failed" are not interchangeable, and F3-F's
own design must carry a way to tell them apart (e.g. the mere absence of a key vs. a key
present with unparseable content). This distinction is fixed here because getting it wrong
in F3-F's storage layer is exactly the kind of silent-downgrade bug that would only surface
in production.

## 4. Resolver contract (fixed now, per Opus's finding — not deferred to F3-B)

A resolver referenced by `resolver_id` is not yet implemented in F3-A, but **its shape is
fixed here** so F3-B cannot quietly under-specify it into 25 divergent one-off shapes:

```
ResolverOutcome:                        # immutable value, never a bare tuple - REPAIR: a
                                         # positional tuple makes field order itself an
                                         # unversioned ABI; a named value type does not.
  status: PASS | FAIL | ERROR
  detail: str
  semantic_source: str

ResolverContext:                        # REPAIR: fixed now, not deferred - the first draft
                                         # said "Callable[[Path, ...]]" and then separately
                                         # said the real context was deferred to F3-B, which
                                         # cannot both be true. This is the minimum real
                                         # information the 25 DIRECT_COMPOSITION checks' mapping proof
                                         # (§4.4) actually needs - nothing speculative added.
  project: Path
  phase_id: str                         # a resolver looks up its own relevant record(s) by
                                         # phase_id (via nogap_artifacts.list_artifacts/latest,
                                         # nogap_required_kinds.check_required_kinds, or
                                         # nogap_lifecycle's own lookups) - it is never handed
                                         # a caller-supplied artifact ref, unlike F2b's
                                         # transition-time required_kinds resolution. This
                                         # matches evaluate_exit_gate's own signature (§7.2):
                                         # (project, phase_id) -> ExitGateEvaluation, with no
                                         # ref list, since F3-C is report-only and runs
                                         # independently of any specific transition attempt.

Resolver: Callable[[ResolverContext, RegistryEntry], ResolverOutcome]
    # A resolver MUST NOT produce UNIMPLEMENTED - only the registry's own
    # implementation_status governs that state; a resolver that exists is by definition
    # attempting IMPLEMENTED behavior for this call.
```

### 4.1 Resolver purity (REPAIR, explicit — not implied by "composition" alone)

A resolver is **read-only and deterministic**, full stop. Concretely, a resolver MUST NOT:

- mutate any project file, artifact, evidence record, or state
- perform network I/O
- spawn a process or subprocess
- create, freeze, or otherwise write a new artifact or evidence record
- write a decision or transition record

A resolver's only allowed action is to **read** project state and existing authoritative
records (files, artifact records, the evidence ledger, gate JSON) and translate an already-
computed verdict into a `ResolverOutcome`. This is not a restatement of §1's "composition,
not re-derivation" principle — it is a separate, load-bearing constraint: without it, nothing
stops a DIRECT_COMPOSITION resolver from quietly becoming an *execution authority* in its own right (e.g.
a resolver that "checks" `frozen_gate_exists` by freezing a gate itself if none exists yet).
An F3 check observes whether a prior, independent action already happened; it never performs
that action to make itself pass.

`resolver_id` is a **namespaced string**, not an arbitrary label, so `semantic_source` is
checkable rather than free text. The namespace prefix is a **closed enum**, not an open
convention - a `resolver_id` whose prefix is not one of these five fails registry load.
**REPAIR (second REPAIR round)**: the first draft proposed only three namespaces
(`required_kind:`, `authority:`, `ledger:`) without checking them against the actual
DIRECT_COMPOSITION checks. §4.4's mapping proof below found real mechanisms that fit neither - not
guessed at, derived directly from existing authoritative code:

```
required_kind:<KIND_NAME>          e.g. required_kind:GOLDEN_GATES, required_kind:SCOPE
authority:<name>                   e.g. authority:gp8_execution_acceptance_separation
ledger:<evidence_kind>              e.g. ledger:deterministic_verification
artifact_field:<TYPE>.<field>      # NEW - composes over nogap_artifacts.validate_record's
                                    # own required_fields enforcement for one exact field,
                                    # used only when NO required_kind already targets that
                                    # field (a required_kind, when one exists for the field,
                                    # is always preferred - see §4.4)
lifecycle:<mechanism>               # NEW - composes over a specific nogap_lifecycle.py
                                    # binding mechanism not expressed as a required_kind
                                    # (e.g. release-candidate/verified-commit matching)
```

### 4.2 Resolver exception handling (REPAIR, explicit)

A resolver invocation is always wrapped by the evaluator, never called bare: any exception
raised inside a resolver is caught by the evaluator and converted to an `ERROR` result
(§3.1) - it MUST NOT propagate and crash the evaluation of the rest of the gate, and it MUST
NOT be silently skipped (a skipped result is not a valid outcome; every `IMPLEMENTED` row in
scope produces exactly one `ExitCheckResult`, `ERROR` included).

### 4.3 Purity is testable, not only declared (REPAIR, explicit)

§4.1's purity rules are meaningless as prose alone. F3-B's minimum test for every resolver:
run it twice against the same unmodified project state and assert identical
`ResolverOutcome`s (determinism), and assert the project directory's own content hash is
unchanged before/after the call (no mutation). This is named here so F3-B does not treat
purity as a comment-only convention.

**Invariant**: an `IMPLEMENTED` row's `resolver_id` MUST resolve to a real, existing
authoritative symbol (e.g. `required_kind:GOLDEN_GATES` must name a key that is actually in
`nogap_required_kinds.ENFORCED_KINDS`) — checked at registry-load time, the same fail-closed
pattern D6/F2b already use for `implementation_ref` existence checks. The resolver's call
shape itself (`ResolverContext`, above) is fixed by this contract, not deferred; only the
internal implementation of each specific resolver body is F3-B's work.

### 4.4 Mapping proof (REPAIR — required before freeze; not deferred to F3-B; corrected in
    F3-RECLASSIFICATION-FINAL-CHECK, a second, deeper verification round)

Every check the survey called `DIRECT_COMPOSITION`, checked against real `nogap_required_
kinds.ENFORCED_KINDS` entries, real `nogap_artifact_types.ARTIFACT_TYPES` required fields,
and - critically, after a first draft of this table got this wrong for four rows - the actual
**content** each mechanism proves, not just its name or phase. `LedgerEvidence`-shaped kinds
in particular were found to prove only `(kind, authority, run_id)` shape, never the deeper
per-run content some check names implied (worktree isolation, command-content matching,
identity separation before a decision exists) - three checks first assumed `DIRECT_
COMPOSITION` on this class turned out to need `SCOPE_MISMATCH` or `SMALL_BINDING` instead (see
§9's full appendix for the complete reasoning per row). This table lists only the 25 rows the
second, deeper check confirmed as genuinely `DIRECT_COMPOSITION` - the full 50-row manifest
with every classification, including the 25 that are NOT this, is §9. Every value in the
`resolver_id` column below is, on the actual registry row, that row's `planned_resolver_id`
(§2) - at F3-A freeze all 25 of these rows are `implementation_status: UNIMPLEMENTED` with
`resolver_id: null`; only `planned_resolver_id` is populated from this table today.

A `WholeArtifact`-shaped `required_kind` (e.g. `SCOPE` over all of `P1_SCOPE`) composes over
`validate_record`, which checks every one of that type's `required_fields` at once - so a
check naming just one of those fields can still bind to the whole-artifact kind's verdict
(many checks to one `resolver_id` is allowed; the reverse is not). A dedicated `ArtifactField`
kind is used instead when one exists for that exact field, since it is more precisely
attributed. `artifact_field:` is used only when neither exists.

| Phase | check_name | planned_resolver_id |
|---|---|---|
| P0 | intent_classified_as_research_production_or_experimental | `required_kind:PROJECT_INTENT` (`WholeArtifact`; `validate_record`'s P0-specific check cross-validates `intent_type` against `state["intent"]`, itself validated against the closed `INTENTS` set at state load) |
| P1 | problem_statement_exists | `required_kind:PROBLEM_STATEMENT` (dedicated `ArtifactField`) |
| P1 | constraints_recorded | `required_kind:CONSTRAINTS` (dedicated `ArtifactField`) |
| P1 | in_scope_list_nonempty | `required_kind:SCOPE` (`WholeArtifact`, no dedicated field-kind exists) |
| P1 | out_of_scope_list_exists | `required_kind:SCOPE` |
| P2 | failure_criteria_recorded | `required_kind:FAILURE_CRITERIA` (dedicated `ArtifactField`) |
| P2 | risk_level_set | `required_kind:RISK_LEVEL` (dedicated `ArtifactField`) |
| P2 | claim_strength_set | `required_kind:CLAIM_STRENGTH` (dedicated `ArtifactField`) |
| P4 | gap_analysis_references_prior_art_map | `required_kind:GAP_ANALYSIS` (`WholeArtifact`; `validate_record` includes the `prior_art_refs` reference check) |
| P5 | decision_value_is_one_of_build_buy_adopt_fork_integrate | `required_kind:STRATEGY_DECISION` (dedicated `ArtifactField`; `STRATEGY_OPTIONS` enum-validates it already) - **registry-blocked on the `HYBRID` wording fix (§6 invariant 7); mechanism-complete today** |
| P5 | decision_has_reason | `artifact_field:P5_STRATEGY_DECISION.reason` (`STRATEGY_DECISION` kind binds `selected_strategy` only, independently, per F2a's "verdict per kind" rule - `reason` has no kind of its own) |
| P8 | adr_records_reason | `required_kind:ADR` (`WholeArtifact`; `rationale` is a required field of `P8_ADR`) - **registry-blocked on the `reason`→`rationale` wording fix; mechanism-complete today** |
| P8 | cost_model_covers_at_least_one_dimension | `required_kind:COST_MODEL` |
| P9 | runtime_structure_initialized | `required_kind:RUNTIME_STRUCTURE` |
| P10 | baseline_recorded | `required_kind:BASELINE` |
| P10 | at_least_one_primary_metric_defined | `required_kind:METRICS` |
| P11 | frozen_gate_exists | `required_kind:GOLDEN_GATES` |
| P11 | stop_conditions_defined | `artifact_field:P11_GATE_PLAN.stop_conditions` (no dedicated kind targets this field; `TEST_PLAN` binds `required_tests` only) |
| P12 | task_contract_has_goal_and_scope | `required_kind:TASK_CONTRACT` (`WholeArtifact`) |
| P12 | task_contract_has_forbidden_scope | `required_kind:TASK_CONTRACT` |
| P12 | task_contract_has_acceptance_criteria | `required_kind:TASK_CONTRACT` |
| P13 | patch_artifact_recorded | `required_kind:PATCH` |
| P14 | execution_evidence_authority_is_execution | `required_kind:EXECUTION_EVIDENCE` (`LedgerEvidence(kinds=('execution',), authorities=('execution',))` - `authorities` is checked as an exact match against the evidence record's own `provenance.authority`, which is precisely this check's claim) |
| P19 | evidence_bundle_references_verification_evidence | `required_kind:EVIDENCE_BUNDLE` |
| P19 | release_candidate_commit_matches_verified_commit | `lifecycle:candidate_binding` (`nogap_lifecycle.resolve_candidate_binding`/`candidate_hash` matching - not a `required_kind`) |

All 25 resolve under the namespaces defined in §4 (no sixth namespace was needed, but this was
verified by checking every row's actual proven content, not assumed from a kind sharing a
phase or a theme with the check). Two rows (P5, P8) are mechanism-complete but registry-
blocked on a small, named wording correction - see §6 invariant 7 and §9.

## 5. Coverage: every declared check gets exactly one row, including P23's (Opus's finding, adopted)

Leaving P23's lifecycle-outcome check outside the registry entirely — because its survey
hasn't run yet — would break the "every declared check maps to exactly one registry entry"
invariant on day one, which would then need an ad hoc exclusion list: a hole in the
invariant this whole registry exists to close. Instead:

```
check_name: "lifecycle_decision_is_one_of_continue_maintain_start_v2_pivot_freeze_archive_abandon"
phase_id: "P23"
classification: CONFLICT
implementation_status: UNIMPLEMENTED
obligation_scope: PROJECT
resolver_id: null
semantic_source: null
planned_resolver_id: null
unimplemented_reason: WORDING_CONFLICT
blocked_by: "P23-LIFECYCLE-OUTCOME-PRE"
```

This is a real row like any other `UNIMPLEMENTED` row — it does not require special-casing
anywhere in the registry-loading logic, only a normal `unimplemented_reason` +
`blocked_by` pair.

## 6. Registry-load invariants (fail-closed; violating any of these means the registry does
   not load at all — see §2.1)

1. **Coverage is an exact bijection (REPAIR, stated explicitly)**:
   `{(phase_id, check_name) declared across p00..p23.json} == {(phase_id, check_name) rows in
   the registry}` — not a subset, not covered-by-allowlist, not "every declared check has AT
   LEAST one row." Set equality in both directions, enforced by invariants 2-4 together.
2. **No unknown declared check**: a check present in a phase file with no matching registry
   row fails registry load (declared ⊄ registry fails).
3. **No duplicate row**: two rows with the same `(phase_id, check_name)` fails registry load
   (registry is not even a valid function of the key otherwise).
4. **No orphan row**: a registry row whose `(phase_id, check_name)` does not appear in any
   phase file fails registry load (registry ⊄ declared fails - symmetric to invariant 2;
   2+3+4 together are exactly what make invariant 1 an exact bijection, not one-directional
   coverage).
5. **`IMPLEMENTED` requires `resolver_id` and `semantic_source`**, both non-null, and
   `resolver_id` must resolve to a real authoritative symbol (§4). At F3-A freeze this holds
   vacuously for zero rows - no row is `IMPLEMENTED` yet (§9).
6. **`UNIMPLEMENTED` requires `resolver_id` and `semantic_source` to be null**, and
   `unimplemented_reason` to be one of the five named values (§2 - `NOT_BOUND`,
   `NO_REPRESENTATION`, `WORDING_CONFLICT`, `SCOPE_MISMATCH`, `RESOLVER_PENDING`), never null.
   At F3-A freeze this holds for all 50 rows.
7. **Identity is `(phase_id, check_name)` as exact strings** (Opus-flagged risk, adopted): a
   wording fix (§9 — P5's `HYBRID`, P8's `reason`→`rationale`) changes the check's
   *text*, which is also the registry's join key. Any such fix MUST update the phase JSON
   and the registry row in the same atomic change (one commit, both sides), never one without
   the other — invariant 2 or 4 would otherwise fail immediately and correctly.
8. **`semantic_source` equality (REPAIR, second-pass finding)**: on an `IMPLEMENTED` row,
   `semantic_source` MUST equal `resolver_id`'s namespace segment exactly (e.g. `resolver_id:
   "required_kind:GOLDEN_GATES"` requires `semantic_source: "required_kind:GOLDEN_GATES"` -
   the same string). This is a real load-time check, not an assumption the two fields happen
   to agree - `semantic_source` is kept as its own field (rather than always derived at read
   time from `resolver_id`) only because `ExitCheckResult.semantic_source` (§3) is produced
   independently by the resolver at evaluation time and compared against the registry row's
   value (§3.2); a field that can never legitimately differ from another still needs its own
   name when two different pieces of code (registry loader, resolver at runtime) each produce
   a copy that must be checked against each other.
9. **`unimplemented_reason` / `blocked_by` direction (REPAIR, second-pass finding; extended in
   F3-RECLASSIFICATION-FINAL-CHECK for `SCOPE_MISMATCH`)**: exactly one direction is legal per
   reason value, not "blocked_by is optional for everyone":
   - `unimplemented_reason: WORDING_CONFLICT` REQUIRES `blocked_by` non-null, naming a real
     survey or precondition identifier (e.g. `"P23-LIFECYCLE-OUTCOME-PRE"`).
   - `unimplemented_reason: SCOPE_MISMATCH` REQUIRES `blocked_by` non-null and equal to
     `"BUILD-INVARIANT-PRE"` (a single named survey covers all `BUILD`-scoped rows together -
     see §9's appendix and §7; there is no per-row variant of this survey unless a future
     `BUILD`-scoped row turns out to need its own distinct resolution path, at which point a
     new, differently-named survey would be introduced for that row specifically, never
     silently reusing `"BUILD-INVARIANT-PRE"` for an unrelated question).
   - `unimplemented_reason: NOT_BOUND` or `NO_REPRESENTATION` REQUIRES `blocked_by` to be
     null - these describe ordinary not-yet-done work (F3-D/F3-E's own backlog), not a named
     external blocker.
   - `unimplemented_reason: RESOLVER_PENDING` REQUIRES `blocked_by` to be null (REPAIR, fourth
     REPAIR round) - it is ordinary F3-B backlog, exactly like `NOT_BOUND`/`NO_REPRESENTATION`
     above, not work blocked on a named survey or precondition. A row cannot simultaneously
     claim "nothing external is blocking this, F3-B can start now" and name a `blocked_by`.
   - A `WORDING_CONFLICT` or `SCOPE_MISMATCH` row with `blocked_by: null`, or a `NOT_BOUND`/
     `NO_REPRESENTATION`/`RESOLVER_PENDING` row with `blocked_by` set, all fail registry load.
   - P23's placeholder row (§5) is `WORDING_CONFLICT` specifically (not a fourth reason value
     such as "architecture conflict") - the wording/reality mismatch is real regardless of
     which side turns out authoritative; the *severity* of the conflict (deep architecture
     disagreement vs. simple drift) is exactly what `blocked_by`'s named survey exists to
     capture, so no separate enum value was needed for it. `SCOPE_MISMATCH` is a genuinely
     different situation from `WORDING_CONFLICT` (the check's TEXT is accurate; its SCOPE is
     wrong for this registry), which is why it does get its own value - conflating the two
     would hide the distinction §9 exists to preserve (§2's `obligation_scope` already answers
     "where does the truth live"; `unimplemented_reason: SCOPE_MISMATCH` only restates that
     answer in the one place someone reading `unimplemented_reason` alone would look for it).
10. **`obligation_scope` consistency (REPAIR, new)**: `obligation_scope: BUILD` REQUIRES
    `unimplemented_reason: SCOPE_MISMATCH` (a `BUILD`-scoped row can never be `IMPLEMENTED` as
    a project resolver, by definition - §2). `obligation_scope: PROJECT` permits any
    `implementation_status`/`unimplemented_reason` combination otherwise valid under
    invariants 5, 6, and 9.
11. **`planned_resolver_id` consistency (REPAIR, third REPAIR round, new)**: `planned_
    resolver_id` is non-null if and only if `classification: DIRECT_COMPOSITION`; null for
    every other classification. When a row's `implementation_status` is `IMPLEMENTED`,
    `resolver_id` MUST equal `planned_resolver_id` exactly - flipping a row to `IMPLEMENTED`
    binds the resolver already named at F3-A freeze time (§4.4, §9); it never introduces a
    different mapping at flip time. A row whose `classification` is not `DIRECT_COMPOSITION`
    can never become `IMPLEMENTED` via this path - `SMALL_BINDING`/`NO_REPRESENTATION` rows
    are designed and given a fresh `resolver_id` directly by F3-D/F3-E, with no `planned_
    resolver_id` precursor, since no pre-existing authoritative mechanism was found for them.
12. **`classification` / `unimplemented_reason` consistency (REPAIR, fourth REPAIR round,
    new)**: the canonical manifest (§9) already fixes exactly one legal `unimplemented_reason`
    per `classification` while `implementation_status == UNIMPLEMENTED`; this invariant makes
    the loader enforce that fact instead of trusting the manifest as documentation only:
    - `classification: DIRECT_COMPOSITION` → `unimplemented_reason` MUST be `RESOLVER_PENDING`,
      OR `WORDING_CONFLICT` **only** for a row explicitly marked registry-blocked in §9 (today:
      rows 13 and 18 only - any other `DIRECT_COMPOSITION` row with `WORDING_CONFLICT` fails
      registry load, since no other row is documented as blocked on a wording fix).
    - `classification: SMALL_BINDING` → `unimplemented_reason` MUST be `NOT_BOUND`.
    - `classification: NO_REPRESENTATION` → `unimplemented_reason` MUST be `NO_REPRESENTATION`.
    - `classification: BUILD_INVARIANT` → `unimplemented_reason` MUST be `SCOPE_MISMATCH`
      (already implied by invariant 10, restated here so the full classification/reason
      matrix lives in one place).
    - `classification: CONFLICT` → `unimplemented_reason` MUST be `WORDING_CONFLICT`.
    - Any row whose `classification`/`unimplemented_reason` pair is not one of the five above
      fails registry load. Once `implementation_status` flips to `IMPLEMENTED` (F3-B/F3-D/
      F3-E), `unimplemented_reason` becomes irrelevant for that row (must be null, per
      invariant 6's own null-symmetry) - this invariant governs only the `UNIMPLEMENTED` state,
      which is every row's state at F3-A freeze.

**Legal `IMPLEMENTED` transition paths (documented here for clarity; enforced by invariants 5,
11, and 12 together, not a new registry-load check on its own)**: a row can only ever move to
`IMPLEMENTED` by the path its `classification` allows - `DIRECT_COMPOSITION` rows via F3-B,
binding `resolver_id` to the already-fixed `planned_resolver_id` (invariant 11, no new mapping
invented); `SMALL_BINDING`/`NO_REPRESENTATION` rows via F3-D/F3-E, each requiring its own named
contract change that defines a genuinely new `resolver_id` (no `planned_resolver_id` exists to
bind to, per invariant 11); `BUILD_INVARIANT` and `CONFLICT` rows cannot become `IMPLEMENTED`
at all until their respective reserved surveys (`BUILD-INVARIANT-PRE`, `P23-LIFECYCLE-OUTCOME-
PRE`) resolve what, if anything, replaces their current `classification` - no F3 stage
authorized by this document may flip a `BUILD_INVARIANT` or `CONFLICT` row to `IMPLEMENTED`
directly.

A future F3-B deliverable (not built now) is a test that loads the registry against the real
`methodology/phases/*.json` tree and fails if invariants 1-4 do not hold — the same
"partition guard" shape `nogap_required_kinds.declared_required_kinds()` already uses for
F2b's closed map, reused here rather than inventing a second pattern.

## 7. Explicitly deferred (named, not silently dropped)

1. **F3-B**: implement resolvers for the 23 `DIRECT_COMPOSITION` rows currently
   `unimplemented_reason: RESOLVER_PENDING` (§4.4, §9 - i.e. the 25 `DIRECT_COMPOSITION` rows
   minus rows 13 (P5) and 18 (P8), which stay `WORDING_CONFLICT`-blocked), each composing over
   its already-authoritative mechanism (no new validation logic). A row flips to `IMPLEMENTED`
   only once its resolver is built and its `resolver_id` is set equal to its existing `planned_
   resolver_id` (invariant 11) - F3-B never invents a different mapping at build time. Rows 13
   and 18 may only join F3-B after their own named wording fix lands and reclassifies them from
   `WORDING_CONFLICT` to `RESOLVER_PENDING` (§6 invariant 7, §9) - not before.
2. **F3-C**: a report-only evaluator (`evaluate_exit_gate(project, phase_id) ->
   ExitGateEvaluation`) — read-only, never called from `_evaluate_transition`, never blocks
   anything. This is where `PASS/FAIL/ERROR/UNIMPLEMENTED` actually gets produced for real
   projects for the first time.
3. **F3-D**: resolve the 13 `SMALL_BINDING` rows (§9; small new checks against real existing fields),
   each flipping its row to `IMPLEMENTED`.
4. **F3-E**: resolve the 8 `NO_REPRESENTATION` rows and the remaining wording-only rows (P0's
   `objective` wording, P20's `security_reviewed` capability gap) — each individually, no
   batch resolution.
5. **P23's own survey** (`P23-LIFECYCLE-OUTCOME-PRE`): decide whether
   `methodology/phases/p23.json`'s wording or `nogap_lifecycle.LIFECYCLE_OUTCOMES` is
   authoritative, or whether both represent genuinely different, both-real concepts that need
   two different checks rather than one reconciled one. Not assumed here.
6. **F3-F**: wire blocking into `_evaluate_transition`, per-phase, only once that phase's
   registry rows are either all `IMPLEMENTED` or the phase's enforcement mode is explicitly
   left `REPORT_ONLY` for the rows that aren't. No per-check silent-advisory state inside an
   otherwise-blocking gate (§3.3). `ExitGateEvaluation.registry_version` (reserved in §3)
   gets populated here, once a transition decision needs to commit to a specific evaluated
   registry state reproducibly.
7. **No new evidence records** at any point in F3-A through F3-D: `semantic_source` on both
   the registry row and each `ExitCheckResult` is a *reference* to where truth already lives,
   never a second copy of it. Whether a transition decision eventually needs a digest/
   commitment over a set of `ExitCheckResult`s is an F3-F question, not decided here.
8. **`BUILD-INVARIANT-PRE`** (REPAIR, new - F3-RECLASSIFICATION-FINAL-CHECK's finding): decide
   what, if anything, the 3 `BUILD`-scoped rows (§9) should become. They are real, verified
   guarantees (execution always runs in an isolated worktree; deterministic verification
   always runs in a fresh worktree; the `verify` command has no code path that writes a
   decision record) with no per-project observable datum backing them - static facts about
   this codebase's own implementation, not obligations any project resolver can evaluate.
   Whether that means leaving them permanently `UNIMPLEMENTED`/`SCOPE_MISMATCH` in this
   registry, moving them to a different kind of check entirely (a codebase-level test suite
   assertion, outside `exit_gate.checks`), or something else, is not decided here - mirrors
   MEMORY_CONFIGURATION's own resolution in F2b (a build-level capability, not a per-project
   obligation, was removed from the phase contract that named it rather than given an invented
   per-project resolver).

## 8. What happens after this contract is accepted

Only F3-B may begin, and only for the 23 `DIRECT_COMPOSITION` rows currently `RESOLVER_
PENDING` (§4.4, §9 - i.e. rows 13 and 18 excluded until their own wording fix lands), each
with its own targeted tests + mutation testing + full regression, exactly the discipline this
session has used throughout F2b. Nothing in this document authorizes touching
`nogap_methodology.py`, `_evaluate_transition`, or any phase JSON's `exit_gate.checks` list
itself (renames aside, per invariant 7, and only once each specific rename is separately
approved).

## 9. Appendix — canonical 50-row classification manifest

The complete result of F3-CLASSIFICATION-PRE (initial survey), F3-RECLASSIFICATION-PRE
(ground-up re-verification against the real 36 `ENFORCED_KINDS`, prompted by finding that
`LedgerEvidence` proves only `(kind, authority, run_id)` shape, never deeper per-run content),
and F3-RECLASSIFICATION-FINAL-CHECK (targeted re-verification of 7 still-uncertain rows).
**This table is the authoritative source for every registry row's `classification`,
`implementation_status`, `obligation_scope`, `unimplemented_reason`, `blocked_by`, and
`resolver_id`/`planned_resolver_id`/`semantic_source` (where applicable) at F3-A freeze time.**
**At F3-A freeze, every one of the 50 rows has `implementation_status: UNIMPLEMENTED` and
`resolver_id: null`/`semantic_source: null` - F3-A is a contract, not an implementation; no
resolver exists in production code yet (§2, §6 invariants 5-6).** F3-B, F3-D, and F3-E each
implement a subset of these rows and flip their `implementation_status` to `IMPLEMENTED`;
none of them re-decides a `classification` already fixed here without its own named REPAIR.

Legend: **DC** = `DIRECT_COMPOSITION` (→ at freeze: `implementation_status: UNIMPLEMENTED`,
`obligation_scope: PROJECT`, `planned_resolver_id` set to the mapping below,
`unimplemented_reason: RESOLVER_PENDING` for 23 rows / `WORDING_CONFLICT` with a named
`blocked_by` for the 2 registry-blocked rows (13, 18) - F3-B flips a row to `IMPLEMENTED` with
`resolver_id == planned_resolver_id`, invariant 11); **SB** = `SMALL_BINDING` (→
`UNIMPLEMENTED`, `NOT_BOUND`, `PROJECT`, `planned_resolver_id: null` - no pre-existing
mechanism, F3-D designs a fresh `resolver_id` directly); **NR** = `NO_REPRESENTATION` (→
`UNIMPLEMENTED`, `NO_REPRESENTATION`, `PROJECT`, `planned_resolver_id: null`); **BI** =
`BUILD_INVARIANT` (→ `UNIMPLEMENTED`, `SCOPE_MISMATCH`, `BUILD`, `blocked_by: "BUILD-
INVARIANT-PRE"`, `planned_resolver_id: null`); **CONFLICT** = P23 only (→ `UNIMPLEMENTED`,
`WORDING_CONFLICT`, `PROJECT`, `blocked_by: "P23-LIFECYCLE-OUTCOME-PRE"`, `planned_resolver_id:
null`).

| # | Phase | check_name | class | authoritative source | planned_resolver_id (if DC) | wording |
|---|---|---|---|---|---|---|
| 1 | P0 | intent_classified_as_research_production_or_experimental | DC | `INTENTS` enum @ state load + P0 `intent_type` consistency check | `required_kind:PROJECT_INTENT` | NONE |
| 2 | P0 | objective_stated_in_one_paragraph_or_less | NR | no `objective` field exists; "one paragraph" unmeasurable | — | DRIFT |
| 3 | P1 | problem_statement_exists | DC | `P1_SCOPE.problem_statement` required_field | `required_kind:PROBLEM_STATEMENT` | NONE |
| 4 | P1 | in_scope_list_nonempty | DC | `P1_SCOPE.in_scope` required_field | `required_kind:SCOPE` | NONE |
| 5 | P1 | out_of_scope_list_exists | DC | `P1_SCOPE.out_of_scope` required_field | `required_kind:SCOPE` | NONE |
| 6 | P1 | constraints_recorded | DC | `P1_SCOPE.constraints` required_field | `required_kind:CONSTRAINTS` | NONE |
| 7 | P2 | success_criteria_measurable | NR | `SUCCESS_CRITERIA` proves presence only; **no "measurable" rubric exists anywhere in the codebase** (verified: zero matches for "measurable") | — | NONE |
| 8 | P2 | failure_criteria_recorded | DC | `P2_SUCCESS_CRITERIA.failure_criteria` required_field | `required_kind:FAILURE_CRITERIA` | NONE |
| 9 | P2 | risk_level_set | DC | `RISK_LEVELS` enum check in `validate_record` | `required_kind:RISK_LEVEL` | NONE |
| 10 | P2 | claim_strength_set | DC | `CLAIM_STRENGTHS` enum check | `required_kind:CLAIM_STRENGTH` | NONE |
| 11 | P3 | prior_art_map_has_..._or_explicit_none_found_justification | NR | `sources` always required non-empty; no alternate "none found" path exists | — | NONE |
| 12 | P4 | gap_analysis_references_prior_art_map | DC | `_check_references` validates `prior_art_refs` inside `validate_record` | `required_kind:GAP_ANALYSIS` | NONE |
| 13 | P5 | decision_value_is_one_of_build_buy_adopt_fork_integrate | DC (registry-blocked; `unimplemented_reason: WORDING_CONFLICT`, `blocked_by: "P5-STRATEGY-WORDING-FIX"`) | `STRATEGY_OPTIONS` enum (6 values incl. `HYBRID`) already validated | `required_kind:STRATEGY_DECISION` | DRIFT |
| 14 | P5 | decision_has_reason | DC | `P5_STRATEGY_DECISION.reason` required_field (no dedicated kind; presence enforced by `validate_record` generically) | `artifact_field:P5_STRATEGY_DECISION.reason` | NONE |
| 15 | P6 | requirements_have_stable_ids_req_prefix | SB | `next_requirement_id`/`_STABLE_ID_FIELDS` guarantee the prefix only at creation, never re-checked at read | — | NONE |
| 16 | P6 | critical_requirements_link_acceptance_criterion_and_planned_test | NR | no "critical requirement" concept anywhere; no P6↔P11 traceability field | — | NONE |
| 17 | P7 | execution_authority_and_acceptance_authority_are_distinct_identities_or_roles | SB | `P7_ARCHITECTURE.execution_authorities`/`.acceptance_authorities` real fields, no disjointness check exists | — | NONE |
| 18 | P8 | adr_records_reason | DC (registry-blocked; `unimplemented_reason: WORDING_CONFLICT`, `blocked_by: "P8-ADR-WORDING-FIX"`) | `P8_ADR.rationale` required_field | `required_kind:ADR` | DRIFT |
| 19 | P8 | cost_model_covers_at_least_one_dimension | DC | `P8_ADR.expected_cost` | `required_kind:COST_MODEL` | NONE |
| 20 | P9 | governance_defines_acceptance_authority | SB | `P9_GOVERNANCE.authority_assignments` dict real; no `"acceptance"`-key-presence check exists | — | NONE |
| 21 | P9 | runtime_structure_initialized | DC | `P9_RUNTIME_STRUCTURE` | `required_kind:RUNTIME_STRUCTURE` | NONE |
| 22 | P10 | baseline_recorded | DC | `P10_BASELINE` | `required_kind:BASELINE` | NONE |
| 23 | P10 | at_least_one_primary_metric_defined | DC | `P10_BASELINE.primary_metric` | `required_kind:METRICS` | NONE |
| 24 | P11 | frozen_gate_exists | DC | gate JSON directly | `required_kind:GOLDEN_GATES` | NONE |
| 25 | P11 | test_plan_covers_critical_requirements | NR | no "critical" concept; no P6↔P11 traceability | — | NONE |
| 26 | P11 | stop_conditions_defined | DC | `P11_GATE_PLAN.stop_conditions` required_field | `artifact_field:P11_GATE_PLAN.stop_conditions` | NONE |
| 27 | P12 | task_contract_has_goal_and_scope | DC | `P12_TASK_CONTRACT.goal`/`.scope` | `required_kind:TASK_CONTRACT` | NONE |
| 28 | P12 | task_contract_has_forbidden_scope | DC | `P12_TASK_CONTRACT.forbidden_scope` | `required_kind:TASK_CONTRACT` | NONE |
| 29 | P12 | task_contract_has_acceptance_criteria | DC | `P12_TASK_CONTRACT.acceptance_criteria` | `required_kind:TASK_CONTRACT` | NONE |
| 30 | P13 | execution_ran_inside_isolated_worktree | **BI** | verified true by construction (no alternate code path in `nogap_execution.py`); **no evidence field records it** (checked `provenance` dict directly - no `worktree_path` or equivalent) | — | NONE |
| 31 | P13 | patch_artifact_recorded | DC | patch persisted | `required_kind:PATCH` | NONE |
| 32 | P14 | execution_evidence_authority_is_execution | DC | `_check_evidence_kind`: `authority == "execution"` exact match | `required_kind:EXECUTION_EVIDENCE` | NONE |
| 33 | P14 | execution_evidence_never_self_marked_authoritative | SB | `EXECUTION_EVIDENCE`'s shape-check does not cover this; `is_authoritative_evidence()`/`execution_actor_ids()` are real, reusable standalone functions | — | NONE |
| 34 | P15 | verification_ladder_depth_matches_active_profile_risk_and_claim_strength | SB | `_effective_profile_for_phase`/`PROFILE_ORDER` real; no comparison logic against `required_levels` exists | — | NONE |
| 35 | P16 | deterministic_verification_ran_in_fresh_worktree | **BI** | same structural guarantee, same absence of per-run evidence, as row 30 | — | NONE |
| 36 | P16 | required_commands_and_forbidden_paths_checked | SB | `DETERMINISTIC_VERIFICATION_EVIDENCE` proves record shape only, not checked-content; `nogap_verification.required_commands_from_gate`/`expected_effect_from_gate` are real, reusable | — | NONE |
| 37 | P17 | result_reproduced_independently_of_original_worktree | SB | **verified**: reproducibility rerun writes a genuinely separate evidence record (distinct `evidence_id`/`run_id`, `evidence_class="reproducibility"`) tied to the same `candidate_hash` - real, observable independence proof | — | NONE |
| 38 | P18 | reviewer_identity_distinct_from_executor_identity | SB | `execution_actor_ids()` reusable directly | — | NONE |
| 39 | P18 | verdict_is_structured_not_narrative | NR | **verified**: no enum validation exists for `deterministic_result`/`reproducibility_result`/`independent_review_result` in `validate_record` - required non-empty only, could hold free text today | — | NONE |
| 40 | P18 | verifier_did_not_write_a_decision | **BI** | **verified**: `cmd_verify` has no code path to write a decision record at all (structural separation, confirmed by reading it directly) - no per-run datum distinguishes one project's verify call from another's | — | NONE |
| 41 | P19 | release_candidate_commit_matches_verified_commit | DC | `resolve_candidate_binding`/`candidate_hash` matching (G1-C2) | `lifecycle:candidate_binding` | NONE |
| 42 | P19 | evidence_bundle_references_verification_evidence | DC | EVIDENCE_BUNDLE composite check | `required_kind:EVIDENCE_BUNDLE` | NONE |
| 43 | P19 | known_limitations_recorded | SB | `known_limitations` real field on release candidate; `LifecycleRecord`'s resolver checks record existence only, not this field's content | — | NONE |
| 44 | P20 | security_reviewed | NR | zero representation anywhere in the codebase | — | DRIFT |
| 45 | P20 | rollback_plan_exists | SB | `rollback_plan_ref` real field, but required at STRICT profile only today | — | NONE |
| 46 | P20 | deployment_decision_recorded | SB | **verified**: `record_deployment_result` persists `status`+`actor`+`reason` together (a real decision record in substance, not a bare execution result) | — | NONE |
| 47 | P21 | observation_stream_active | NR | discrete records only; no "active stream" concept | — | NONE |
| 48 | P21 | incidents_preserve_evidence_before_repair | SB | `create_incident.evidence_refs` real but optional; no temporal/mandatory-linkage check exists | — | NONE |
| 49 | P22 | improvement_proposal_cites_evidence | SB | `evidence_refs` param real but optional; `IMPROVEMENT_PROPOSAL`'s `LifecycleRecord` checks existence only | — | NONE |
| 50 | P23 | lifecycle_decision_is_one_of_continue_maintain_start_v2_pivot_freeze_archive_abandon | **CONFLICT** | real `LIFECYCLE_OUTCOMES` enum shares only 3/8 values with the check's named set; 4 named values do not exist in the implementation at all | — | CONFLICT |

**Totals** (verified by counting the table, not assumed in advance): DC = 25 (23
`RESOLVER_PENDING`, ready for F3-B directly; 2 registry-blocked on wording, rows 13 and 18,
`WORDING_CONFLICT` with a named `blocked_by` until their rename lands) · SB = 13 · NR = 8 ·
BI = 3 · CONFLICT = 1 · **Σ = 50**. **Every row's `implementation_status` is `UNIMPLEMENTED`
at F3-A freeze - `classification` records what KIND of gap each row has, never whether it
already runs.**
