# F1-T1B — Trusted Policy & Obligation Semantics

**Status: FROZEN, revision 10, after adversarial review 3.** Review 1 produced AM-39 (one schema
defined in both contracts) and review 2 produced AM-40 (supersession had no owner, no
representation and no enforcement point); both were cross-contract and reopened T1A. Review 3 was
confirmatory against this revision with no prior edit: the nine semantic attacks, the eight-shape
lineage matrix, the thirteen-question override matrix, the R5 boundary, both representability
directions, semantic state/effect, closure across T1A and T1B, continuity, and canonical-schema
uniqueness — **zero gaps**, and every probe mutation-tested to fail when its rule is removed.

**What FROZEN means.** No semantic change may be made to this document except through a new
numbered amendment that explicitly reopens T1B, is recorded in `f1-amendment-ledger.md`, and states
which invariant it changes and why. T1B defines no message schema; T1A §6 remains the single
canonical source (AM-39), so a schema change reopens T1A, not this document.

T1B answers the question T1A deliberately does not: **what do the authenticated statements mean?**
Which obligations exist, what class they carry, when they apply, how that may change, and what may
be concluded from a verdict. T1A can be frozen without T1B; F1 is closed only when both are.

Every rule here assumes T1A's substrate. A T1B rule enforced over unauthenticated state is
decoration.

## B0. Closure rules for this contract (AM-32, AM-39)

T1A §-1 forbids security by remembered list, and T1A took fifteen adversarial rounds to discover
that its own enumerations were one. T1B inherits the rule from the start rather than repeating the
journey. Every security-significant enumeration here is **DERIVED** from a property, **CLOSED +
CHECKED** by a mechanical check, or **NON-NORMATIVE** and marked as such.

T1B adds one rule of its own, which AM-39 exists to enforce:

> **T1B defines no message schema. T1A §6 is the single canonical source; T1B states what fields
> mean. A schema restated here is a second canonical source, which is what defining it twice
> already cost.**

The manifest below is checked by `scripts/check-f1-enumerations.py`, which reads T1A and T1B as one
F1 set — a cross-contract duplicate is exactly the defect neither document's own audit could see.

```
GOVERNED     :: TABLE |Field (T1A §6) :: applicability field semantics — CLOSED+CHECKED (AM-39)
GOVERNED     :: Verification Obligation :: obligation record — CLOSED+CHECKED (AM-8)
ILLUSTRATIVE :: GOVERNED     :: this manifest
ILLUSTRATIVE :: FAIL(obligation O :: supersession history example
ILLUSTRATIVE :: O1 applicable :: the narrowing attack shape
ILLUSTRATIVE :: Project Genesis  ──anchors──> :: policy anchoring diagram
```

```
COMMITMENT — T1B, pinned in advance (AM-38 applied to T1B)
ILLUSTRATIVE_ENTRIES: 4
be8f3033615c  TABLE |Field (T1A §6)
3332e3f00eca  Verification Obligation
```

## B1. Task relation and obligations

**Task relation carries no power over obligations (AM-11).** Revision 5 left Task Genesis deciding
between four relations without saying how — and any classifier driven by similarity, task text, or
caller hints is an oracle the adversary tunes until it returns `NEW_TASK` (A11). The fix is not a
better classifier; it is to remove the prize:

> **No task relation, and no combination of them, changes which obligations a candidate must
> satisfy.**

- `NEW_TASK` does not clear project obligations; they were never the task's to clear (§B3).
- `SUPERSEDES` does not transfer or discharge an obligation. Only an authenticated applicability
  transition (§B4) changes an obligation's state — task relations are not that mechanism.
- Task Genesis alone may never drop lineage.
- An unclear relation is `AMBIGUOUS_RELATION`: **fail closed**, escalate to human authority (T1A §4).

Relation therefore stays useful for organising work and reading history, and is worthless as an
escape from it.


## B2. Run lineage (AM-6)

A fresh run must not be a fresh start. Without lineage, the adversary simply retries: run, get an
adverse verdict, mint another run, repeat until a flaky check passes, then present that run's
ACCEPT. Every run in that sequence is individually honest, and the sequence as a whole is laundering.

- Every Run Commitment records `parent_run_commitments` for the same task, assembled by the TCB
  from its own records — never from the workspace, which cannot be trusted to remember.
- The acceptance authority evaluates a candidate against **the task's whole lineage**. Revision 4
  said an adverse verdict is cleared by a verdict on a *different* candidate; that was wrong, and
  §B3 replaces it. A different fingerprint proves different bytes, never a repair.
- Omission is not possible: lineage lives in the TCB, so a caller that simply does not mention
  earlier runs changes nothing.
- Run creation is deliberately **not** rate-limited by magic. Creating a thousand runs is useless by
  construction: each one still gets a baseline-bound gate (T1A §8), so more runs never yield an easier
  gate, and lineage means more runs never yield a cleaner history.


## B3. Verification obligations and supersession (AM-8, AM-16, AM-17)

Admissibility asks whether a verdict is genuine. It does not ask whether the *conclusion drawn from
it* is sound. Revision 4's rule — an adverse verdict is cleared by a verdict on a different
candidate — fails exactly there: a comment, a whitespace change, a touched unrelated file all yield
a new `candidate_fingerprint`, so the adversary manufactures a repair history without repairing
anything (A9). **Different bytes is not a fixed defect.**

A failure is therefore attached to an **obligation**, not to a fingerprint:

```
Verification Obligation
  obligation_id        stable across candidates and runs
  project_commitment   obligations are PROJECT-scoped, not task-scoped
  predicate_identity   which assertion, named by the authenticated gate baseline
  failure_semantics    what counts as adverse for this predicate
  applicability        resolved from the Applicability Commitment (§B4), never from the gate
                       alone and never claimed by the caller
```

Obligations are **project-scoped on purpose**: that is what closes A7. Minting a new task cannot
escape an obligation the project still owes, because the obligation never belonged to the task.

The acceptance rule follows from this and is deliberately blunt:

> **ACCEPT requires a current authenticated PASS on every applicable obligation, for the exact
> candidate being accepted.**

No inherited PASS, no credit from a sibling candidate, no clearing by novelty. A trivially altered
descendant must re-satisfy every applicable obligation on itself; if the real defect is still there,
the same obligation fails again. This closes A5, A7 and A9 with one rule rather than three special
cases.

**Supersession records, it never erases.** History retains both:

```
FAIL(obligation O, candidate A, run R1)
PASS(obligation O, candidate B, run R2)
```

**A supersession is an override, so it has an owner (AM-40).** Review 2 asked seven questions of
this rule and six had no answer, because the relation was not representable: nothing in any message
said "this verdict supersedes that one", so the decider was left to assert its own repair history.
The assertion now lives in `VERIFY.supersedes` (T1A §6), signed by the verification authority, and
T1A §10's Stage 2 enforces the conditions — they are not prose in this document that the
admissibility procedure never reads.

A later verdict supersedes an earlier adverse one only when all hold: same **`obligation_id`**; the
candidate is a **TCB-recorded descendant** of the adverse one (structural under AM-9, not claimed);
the gate and policy in force **at the current head** are equal or stronger; it is a **PASS**; and
the superseded verdict is **not already superseded** — otherwise one adverse verdict is cleared by
many descendants at once, which is A24's race applied to verdicts.

> **A supersession may only raise the burden of a decision, never lower it.**

It selects which verdict is current; it never substitutes for one. The acceptance rule is
unchanged and unconditional: a current PASS on every applicable obligation, bound to the exact
candidate being accepted. So a supersession cannot be replayed into credit — replaying it changes
which verdict is current for a candidate that must still pass on its own — and it cannot make an
obligation non-existent rather than non-applicable, which §B4 and AM-16 govern separately.

Policy — not the trust root — then decides whether that supersession counts as repair. Every
decision record carries the adverse verdicts it superseded, so a candidate that passed on attempt 47
is visibly that.

**Obligations must be born, not merely not-killed (AM-16).** §B4 forbids silent deactivation, but
revision 7 never said where the obligation set comes from. If a candidate can reach a decision with
`{O1, O2}` while the obligation it should have faced, `O3`, was never created or activated, then
"PASS on every applicable obligation" succeeds perfectly — because the missing one never entered the
set (A16). That is the same attack as silent deactivation, moved to the moment of birth.

> **Silence cannot prevent birth any more than it can cause deactivation.**

The obligation set is therefore an **authenticated Obligation-Set Commitment**, anchored at Project
Genesis (`obligation_policy_baseline`, T1A §6) and derived deterministically and reproducibly from
`Project Genesis + the current Policy Commitment + the authenticated Gate Baseline`. A decision
names that commitment; an obligation set assembled ad hoc, or assembled by whatever the current
gate happens to mention, is refused. Omission is never a lawful route to not applying an
obligation.

**One derivation, not a choice of two (AM-39).** Revision 8 offered genesis-anchoring *or*
derivation from `Policy Root + Gate Baseline + Predicate Registry`. The second branch named an
authority that existed nowhere — no message type, no schema, no authority — and a disjunction at
the moment of obligation birth is the same silence this rule exists to forbid: two admissible
answers to "where did this set come from" is one answer too many. `Predicate Registry` is removed
from v1; `predicate_class_map_digest` in the Policy Commitment carries
`predicate_identity -> obligation_class`, which is all it was ever needed for.

**Class is assigned by policy, never chosen by the object (AM-17).** AM-14 moved
`class -> required authority` into the Policy Root, which is right — but the Applicability
Commitment still carried its own `obligation_class`. Whoever creates an obligation could then label
a security-critical predicate `LOW` and let the policy faithfully map that to a weak authority. The
object does not set its protection directly; it sets the key policy uses to look it up (A17), which
is the same thing wearing a hat.

> **A protected object may not choose its own protection class either.**

`predicate_identity -> obligation_class` comes from the Policy Commitment's
`predicate_class_map_digest` (T1A §6, AM-39), never from the caller and never from the obligation
record. It is a separate commitment from `class_authority_map_digest`, which carries
`obligation_class -> required authority`: two different authorities, two digests, so the chain
`predicate_identity -> obligation_class -> required authority` is authenticated at every link.
Reclassifying a predicate downward is a weakening, and is governed by §B4's rules for weakening
coverage.

**Supersession is not proof of causal repair.** See §B5.


## B4. Applicability is part of the trust root (AM-10, AM-13, AM-14)

§B3 requires a PASS on every **applicable** obligation, and revision 5 let the gate decide what
"applicable" meant. That hands the adversary a second laundry: instead of changing the candidate
until the failure disappears, change the *scope* until the obligation does.

```
O1 applicable -> FAIL            becomes            O1 not applicable -> no PASS required
```

The word *applicable* is therefore load-bearing, and anything load-bearing must be authenticated
exactly like identity, gate and candidate. Applicability gets its own commitment and its own
lineage:

The message is `NOGAP::APPLICABILITY::v1`. **Its schema is T1A §6's and only T1A §6's (AM-39)** —
this section says what the fields mean, and deliberately does not restate them. Revision 8 carried
its own field list here, and the two disagreed on nine fields out of eleven for four revisions,
with each document enforcing rules over fields the other lacked.

| Field (T1A §6) | What it means here |
|---|---|
| `obligation_class` | risk class; the POLICY maps class -> required authority (AM-14) |
| `predicate_scope_digest` | binds the scope the obligation covers; shrinking it is narrowing |
| `condition_commitment` | binds the activation and deactivation conditions |
| `transition` | which change this message authorizes: activate, deactivate or narrow |
| `authorization_ref` | the authorization admissible for this class and this transition |
| `epoch`, `previous_commitment` | the append-only lineage a transition takes its place in |

Rules:

- **An activated obligation stays activated** on the project's and candidate's descendants until an
  **authenticated applicability transition** authorizes otherwise.
- **Silence is not deactivation.** A later gate that simply does not mention an obligation
  deactivates nothing. Revision 5's "derived from the current gate" is exactly the defect.
- **Narrowing is deactivation.** Shrinking `predicate_scope` so the candidate falls outside it is
  the same move as removal and needs the same authority. The rule covers scope changes, not just
  deletions.
- **Protection level is pre-declared, never read off the current state (AM-13).** Revision 6 keyed
  the strong-authority requirement on the obligation being *currently adverse*. The adversary simply
  waits less: deactivate while the obligation is still green, then submit the candidate that would
  have failed it. No red obligation was ever switched off, and the check vanished exactly when it
  was about to matter (A13). Therefore the authority needed to weaken coverage — delete, deactivate
  or narrow — is fixed in advance by the obligation's **class** (AM-14), not by its state at the
  moment of the request. A currently-adverse obligation may raise the bar further; it may never be
  the only thing that raises it.

  The general rule, so later amendments do not reintroduce this shape: **any guard conditioned on
  state observed at request time is timing-attackable.** Protection must be a declared property.

- **Weakening must be visible in the decision it enables.** Prevention is not the whole job here:
  a decision record must surface every applicability weakening within its lineage, so a
  deactivation standing immediately before an acceptance is readable as what it is.
- Transitions are **append-only with lineage**, so the history reads "O1 was active and failing, then
  deactivated by X, under authority Y, at sequence N" rather than "O1 was never applicable."

**Authority comes from a Policy Root, never from the protected object (AM-14).** Revision 6 put
`authority_required_for_change` *inside* the Applicability Commitment — so the object declared how
hard it was to weaken itself. That is F1's original shape one level up: instead of a JSON file
asserting `authority="verification"`, a policy object asserts its own protection level.

> **A protected object may not define the authority required to weaken its own protection.**

```
Project Genesis  ──anchors──>  Policy Commitment        (NOGAP::POLICY::v1)
                                 obligation_class -> authority required for
                                   activation | deactivation | narrowing
                                       ↓ referenced by
                               Applicability Commitment  (carries obligation_class only)
```

Changing the policy itself requires the policy root's own authority — human by default. The regress
terminates where AM-12 says it does: at the Project Genesis ceremony. Without that anchor, A14 is
"solved" by minting yet another root, which is not a solution but a rename.



## B5. Residual limit

- **R5 — Supersession cannot prove causation.** A PASS on a descendant after a FAIL may be a real
  fix or a flaky predicate that happened to pass. The trust root binds facts; it cannot infer that
  one caused the other, and it must not pretend to. The residual laundering vector is therefore
  flakiness: retry until every applicable obligation passes at once. Mitigation is policy, not
  cryptography — require predicates to be deterministic or reproducible, require N consecutive
  passes, or require human sign-off to supersede nominated obligation classes. This is the exact
  seam between *cryptographically valid* and *engineering-valid*, and NoGapCode must state which one
  it is claiming.

  **R5 is a declared boundary, not a gap to read past (AM-40).** `FAIL` then `PASS` establishes
  exactly one thing: that the current verdict for this obligation on this candidate is a PASS under
  the policy in force. It does not establish that the change caused the repair, and no sequence of
  verdicts ever will. A system that needs causal repair must **declare that burden here** — a
  named policy obligation with its own predicate, deterministic or N-of-N or human-signed — and
  never infer it from the order of the records. An unstated causal claim is the one place this
  contract could be read as promising more than it proves.
