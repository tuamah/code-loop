# F1 — Missing Authenticated Trust Root / Forgeable Authority State

**F1 overall: OPEN.** This page is the index and status. The contract itself is now two documents.

F1 was found during the M8-CLOSEOUT enforcement audit and reproduced, not inferred: a writer that
never executed and never verified reached ACCEPT by authoring one JSON file; an executor laundered
its own work through an invented verifier identity; and the "immutable" frozen gate turned out to be
a checksum stored beside the data it covers, so editing the rules and recomputing the hash passed
validation cleanly. The common root is that authority, identity and immutability were self-asserted
data in files the adversary can rewrite — and that adversary is the implementer agent, which holds
repository write access by construction.

## The two contracts

Twenty-one adversarial review rounds produced thirty-eight amendments and thirty-five named attacks. Review 7
established that the growth was not one contract getting stronger but **two contracts tangled
together**, so they are now separate and freeze independently:

| | Document | Question it answers | Status |
|---|---|---|---|
| **T1A** | [`f1-t1a-trust-core.md`](f1-t1a-trust-core.md) | Can any statement be authenticated, bound to an identity, a scope and an order, and read as part of a coherent state? | **FROZEN rev 24** (reopened twice: AM-39, AM-40) |
| **Ledger** | [`f1-amendment-ledger.md`](f1-amendment-ledger.md) | What every amendment established, where it lives now, and whether it is still in force | canonical, CI-checked |
| **T1B** | [`f1-t1b-policy-obligations.md`](f1-t1b-policy-obligations.md) | What do the authenticated statements mean — which obligations exist, when they apply, what may be concluded? | **FROZEN rev 10** |

T1A guarantees a Policy Commitment is authenticated, rooted and non-rollbackable. What it *says* is
T1B. A T1B rule enforced over unauthenticated state is decoration; a T1A substrate with no T1B
semantics authenticates statements that mean nothing in particular.

### T1A FREEZE

Round 21 completed clean against revision 22 and T1A is frozen at that content. The digests below pin
the content. The freeze commit is `b667d64` on `claude/affectionate-edison-6ph9cf`; the local tag
`f1-t1a-freeze-rev22` marks it, but this remote refuses tag refs, so the commit hash is the
authoritative pin.

```
FROZEN — F1-T1A, revision 24, after the AM-40 regression
sha256  docs/f1-t1a-trust-core.md    be3fe5bb12a1496c5a45817bcf0e151ff7bd14d0f37cdcecb016f7d4245812b3
sha256  docs/f1-amendment-ledger.md  b534307f0614504d115545d69112577b9fc2feac9fdd68df43ba6c004d98c169

rev22  FROZEN at b667d64 — review 21 clean
       REOPENED by AM-39: one schema defined in both contracts (T1B review 1)
rev23  re-frozen
       REOPENED by AM-40: supersession had no owner, no representation, no
                          enforcement point (T1B review 2)
rev24  re-frozen: 9/9 T1B attacks blocked, 6/6 lineage shapes blocked,
       17/17 legacy attacks blocked, 0 security-semantic delta outside AM-40
```

```
FROZEN — F1-T1B, revision 10, after adversarial review 3
sha256  docs/f1-t1b-policy-obligations.md  46e54cef6d4569043291b9d7444955c8f0ae9030da05b9952025dc6b3dd66b7e

review 1  AM-39 — one schema defined in both contracts (reopened T1A)
review 2  AM-40 — supersession had no owner, representation or enforcement point
review 3  confirmatory, no prior edit: 9/9 attacks, 8/8 lineage shapes,
          13/13 override questions, R5, representability both ways,
          state/effect, closure, continuity, canonical uniqueness — 0 gaps
```

**F1's contract design is closed.** Both contracts are frozen and the seam between them is checked
mechanically. What is frozen is the design, not an implementation: no code in this repository
implements any of it yet, and §16's residual limits (R1-R5) stand as stated.

No semantic change may be made to T1A except through a new numbered amendment that explicitly
reopens it, is recorded in the ledger, and names the invariant it changes. An editorial change is
still possible and still has to be acknowledged deliberately in the ledger, so the digests above
move only with a visible diff. T1B is not frozen and is the next target.

**Freezing T1A does not close F1.** The intended sequence:

```
attack T1A alone with the core attacks
  → a full round with no amendment → FREEZE T1A
attack T1B with the policy and obligation attacks
  → a full round with no amendment → FREEZE T1B
  → only then is F1 closed, and only after implementation
```

## The twenty-four attacks, and where each now lives

```
T1A — Authenticated Trust Core
  A1   Signing Oracle
  A2   Verifier Key Exfiltration
  A3   Candidate TOCTOU
  A4   Unauthorized Gate Freeze
  A5   Fresh-Run Laundering              (run genesis half)
  A6   Master Substitution
  A7   Fresh-Task Laundering             (task identity half)
  A8   Base Rebinding
  A12  Project/Base Genesis Substitution
  A15  Mixed-State / Decision TOCTOU
  A18  Signed-Policy Rollback
  A19  Missing Domain Separation for Core Commitments
  A20  Authority-Class Gap / Genesis Signer Ambiguity
  A21  Authorization Replay / Human Approval Reuse
  A22  Action Confusion / Unbound Action
  A23  Human Authorization Double-Spend
  A24  Authoritative Head Fork / Transition TOCTOU

T1B — Trusted Policy & Obligation Semantics
  A5   Fresh-Run Laundering              (obligation half)
  A7   Fresh-Task Laundering             (obligation half)
  A9   Trivial-Change Failure Laundering
  A10  Applicability Narrowing
  A11  Task-Relation Laundering
  A13  Pre-Failure Applicability Laundering
  A14  Self-Authorized Policy Downgrade
  A16  Obligation Omission at Birth
  A17  Obligation-Class Laundering
```

A5 and A7 appear in both because each has two halves: minting an identity (T1A) and escaping a
history (T1B). Both halves must fail.

## Review history

Every round found something, and three rounds running found defects in machinery the previous round
had just added — which is why the split matters more than another amendment would.

| Round | Found | Amendments |
|---|---|---|
| 1 | §2 put the signing key inside the process running untrusted code | AM-1…3 |
| 2 | A1 rested on adversary-controlled run identity | AM-1 |
| 3 | A5, A6 succeeded; AM-1 was circular | AM-4…6 |
| 4 | A7, A8, A9 succeeded; AM-6 was semantically wrong | AM-7…9 |
| 5 | A10, A11, A12 succeeded; A10 defeated AM-8 | AM-10…12 |
| 6 | A13, A14, A15 succeeded; A13 defeated AM-10 by timing | AM-13…15 |
| 7 | A16, A17, A18 succeeded; established the T1A/T1B seam | AM-16…18 |
| 8 | A19, A20, A21 succeeded — all three inside the core, no new semantic layer | AM-19…21 |
| 9 | first full 14-attack round on T1A: **12 blocked, 2 composed attacks passed**. §10's procedure still tested a field AM-19 had deleted and tested neither AM-20's grants nor AM-21's binding | AM-22 |
| 10 | A22, A23, A24 — the granted action was never carried in the signed message, and consumption and head transitions were check-then-act, which are races | AM-23…25 |
| 11 | full 17-attack round on T1A: **15 blocked, A23/A24 ambiguous** on the cross-authority case. AM-25 required one atomic transition across state §3.1 permits to be partitioned | AM-26 |
| 12 | full 17-attack round: **17/17 blocked**, both concurrency composed cases included. One amendment still required, found outside the attack list: §12's migration grant had no representable message | AM-27 |
| 13 | 17/17 blocked again, plus a systematic representability audit in both directions: 3 gaps, all created or exposed by the previous round's own amendment | AM-28 |
| 14 | 17/17 blocked, both representability audits clean. A **semantic statefulness** audit failed it: statefulness was defined by fields, and the decision CAS covered only elements named `*_head` | AM-29 |
| 15 | 17/17 blocked; representability and statefulness audits clean. A **snapshot-mutability** audit failed it: migration state and authorization consumption state were absent from the snapshot entirely | AM-30 |

Three properties turned out to be distinct, and the contract needed each separately:

```
integrity     the bytes did not change          (a digest gives this)
authenticity  a specific authority said it      (a signature gives this)
currency      it is still the operative one     (a monotonic head gives this)
```

Rules that held only one of the three were defeated in rounds 5, 6 and 7 respectively. Round 8 added
a fourth, at the boundary between them:

```
authorization  this signer approved THIS operation, once
```

Authentication proves who signed; it never proves what they authorized.

Round 8 was the first round whose findings introduced no new layer — all three sat in message
identity, signer authority and authorization binding. Round 9 then found that the two rules round 8
added had been written into the sections that describe them and never into §10, the procedure that
enforces them:

> **A rule stated in one section and absent from the procedure that enforces it is not enforced.**

Round 9 also surfaced the maintenance hazard behind it: AM-19 replaced the payload, and the
admissibility list written against the old payload was left in place, still testing a field that no
longer existed. Amendments are not additive — each one must be checked against the procedure it
touches.

Round 10 added a fifth property, orthogonal to the other four:

```
atomicity      validation and mutation of authoritative state are one operation
```

A single-use authorization is a linear capability, and a head is a single-writer register. Rules
written as "check, then act" hold against a sequential adversary and fail against a concurrent one,
so A23 and A24 are the concurrent cases of A21 and A18 rather than new semantics.

Rounds 8 through 11 introduced no new semantic layer: message identity, signer authority,
authorization binding, action binding, atomicity, and finally where the state that atomicity spans
must live. The findings are converging on the substrate rather than expanding past it, and round 11
is the first whose single finding was a **consistency defect between two existing sections** rather
than a missing rule — §3.1 permitted a topology §10.1 could not survive.

Round 12 is the first in which **every attack was blocked**. It still produced an amendment, and
the amendment came from a direction the attack list does not cover: reading the contract for
internal representability rather than attacking it. §12 sanctioned exactly one exemption from
fail-closed and described it as "a decision record", while §6's closed model had no migration
message and `DECISION`'s closed action enum could not express one — so the only sanctioned exemption
was the only thing in the contract that could not be an authenticated message.

That is worth naming as a third failure mode alongside the other two the reviews have produced:

```
a missing rule            rounds 1-8
a rule the enforcing procedure does not implement   round 9
a rule two sections contradict                      round 11
a rule nothing in the model can express             round 12
```

Round 13 added the systematic form of that check — every rule traced forward to its representation
and enforcement, every message traced back to its producer and consumer — and it found three gaps,
all of them created or exposed by round 12's own amendment. The lesson is now explicit in the
contract rather than in this history: a list of what must be atomic is a list to be forgotten, so
AM-28 replaces it with a property of the message itself — a body carrying a head transitions
authoritative state, and a type added without answering that question is inadmissible.

Round 14 added the last of the audit forms: **statefulness by effect rather than by shape**. A rule
that tests for the presence of a field admits anything that achieves the same effect differently,
and a rule that leaves classification to whoever adds a type is A17 wearing another hat. The
concrete instance was inside AM-15's own fix — the decision CAS asserted the elements named
`*_head`, while the snapshot also carried a mutable verdict set that no head covered.

That produced the sixth and last property this contract needed, and it is a meta-property rather
than another mechanism:

```
effect        a rule is about what a message does, never about what it looks like
```

Rounds 13, 14 and 15 found **the same class of defect three times**, and AM-28, AM-29 and AM-30 are
the same move: replacing a hand-maintained enumeration with a defining property.

```
AM-28  a list of what must be atomic        →  AM-29  statefulness by effect
AM-29  a CAS over elements named *_head     →  every mutable element
AM-30  a list of snapshot elements          →  S is defined as what the decision reads
```

The discriminating evidence is in which enumerations failed. The three that are **declared closed
and mechanically checkable** — the domain list, the per-type action enums, the stage-2 clauses —
have produced **zero** findings across all three rounds; a script cross-checks them in seconds. Every
finding in rounds 13-15 came from an **informal prose list** that had to be remembered when
something was added.

So the defect class is not the contract's size, and not its subject matter. It is enumerations with
no closure property. One such list is still unamended and was left deliberately untouched as
evidence: §3's nine Mode B capabilities, a hand-maintained list with no defining property, in the
same shape as the two that just failed.

**Revision 17 is the Enumeration Closure Pass, not an attack round.** The anti-pattern behind
rounds 13-15 now has a name and a prohibition: *security by remembered list*. T1A §-1 requires every
security-significant enumeration to be DERIVED, CLOSED + CHECKED, or NON-NORMATIVE, and classifies
all of them. Mode B stopped being nine prohibitions and became a five-clause invariant with the nine
as test vectors, so a capability nobody anticipated no longer satisfies it by absence.

Two scripts make it mechanical, and **both found real drift on their first run**:

```
check-f1-enumerations.py   MIGRATION had a signing domain but no body schema in §6
check-f1-continuity.py     AM-1, AM-2, AM-3 cited nowhere in either contract
```

The second is the K2 lesson applied to ourselves. Thirty-two amendments were produced in
conversation; only the contracts survive it. Two of those three had survived unlabelled, one had
been superseded — and which was which was knowable only from the conversation that produced them.
`f1-amendment-ledger.md` is now canonical: every LIVE amendment must have its invariant located in
a document, every SUPERSEDED one must name its replacement, and CI fails if a rewrite drops one.
The same anti-pattern that let an invariant slip out of a contract is the one that lets a week of
work slip out of a project's memory; the fix is the same in both cases — a canonical source and a
mechanical check, never a remembered list.

**Round 16** ran the full seven-part package against revision 17. Seventeen attacks blocked; the
representability, statefulness and snapshot audits clean; both automated guards green. The
**closure audit failed it**, and on the sharpest possible point: §-1 forbade security by remembered
list and was itself enforced by a fourteen-row table nothing checked. A future amendment adding a
list — which AM-19, AM-23, AM-25 and AM-27 each did — could have omitted itself from that table
with both guards staying green.

That is A14 and A17 one level higher: the policy object setting its own protection, the obligation
choosing its own class, and now the closure rule exempting itself from closure. **The governing
object is not exempt from its own governance.** AM-33 makes §-1's manifest canonical and requires
every fenced block in T1A to match it, so an enumeration cannot enter undeclared; the guard was
verified to fail on exactly the move a future amendment would make.

AM-34 came from the same round: Mode B's clause 3 forbade influencing trusted computation at all,
which no co-resident process can satisfy, since timing and resource pressure are influence. An
invariant that can never be literally true is as useless as one always true. It now forbids
influence that moves the **outcome toward acceptance** — resource pressure drives fail-closed,
which is availability and out of scope.

## The freeze criterion, restated

"Zero amendments" stopped being the right test once the contract matured: a typo fix should not
reset the counter. The criterion is now **zero security-semantic delta**, and the decisive question
for any change is:

> **Is there a single execution case whose verdict differed before the change and after it?**

Yes → semantic; the round fails. No → editorial, and only if every guard and test keeps its
expectations unchanged. Editorial corrections get no AM-number: an amendment means a change to the
security model, and numbering comma fixes would make the ledger claim discoveries that never
happened.

A round is clean when it finds no change to: the accepted/rejected set, the threat model, an
authority or scope, a cryptographic binding, a schema/domain/action, admissibility, a state
transition or its atomicity, current-head semantics, fail-closed behaviour, a trust claim,
migration behaviour, or any MUST/MUST NOT an implementation depends on.

By that test AM-33 and AM-34 were both semantic — one changed the enforceability of the closure
rule, the other changed what Mode B forbids — so round 16 failed correctly.

**Round 17** attacked AM-33 and AM-34 directly. AM-34 held. AM-33's guard did not, and the two
attacks were run rather than reasoned about:

```
a block beginning `epoch`, behind the manifest's short `epoch` prefix   → passed silently
a security table instead of a fenced block                             → not scanned at all
```

AM-35 makes the manifest a **bijection** — every entry matches exactly one enumeration and every
enumeration exactly one entry, so a prefix covering two things can no longer cover the next thing —
and constrains security-significant enumerations to blocks and tables, which makes the scan's reach
complete rather than a matter of where someone put a list. Both attacks now fail.

**Round 18** turned the same hostility on `check-f1-continuity.py` that round 17 had turned on the
enumeration guard, and broke it in all four categories asked for:

```
anchor kept, rule beneath it inverted            -> passed   (false negative)
AM-18 marked SUPERSEDED by an AM carrying none   -> passed   (hidden loss)
supersession cycle AM-18 -> AM-29 -> AM-18       -> passed
one line reflowed, nothing changed               -> FAILED   (false positive)
```

The first version verified a string was present, which proves text exists and nothing about what it
means. AM-36 digests the whole section an invariant heads, over whitespace-normalized text, so
reflow no longer trips it and editing the rule does; supersession becomes inheritance, with exactly
one live amendment required to declare a retired one and carry its invariant forward; cycles are
rejected. All four attacks now behave correctly.

And the limit is written into the contract rather than left implied:

> A digest proves text did not change. It cannot prove that changed text means the same thing. No
> script can. What it buys is that drift cannot happen *silently* — the change becomes a line in a
> diff a reviewer must judge. The guarantee is "no unacknowledged change", never "no harmful
> change".

**Round 19** attacked the ledger `check-f1-continuity.py` treats as canonical. Three of three
landed. **A25** deleted the highest-numbered row and the audit passed: the gap check derived the
ledger's extent from the ledger, so truncation at the top left no gap to find (deleting a *middle*
row was caught). **A27** added an invented AM-37 granting the controller permission to delegate
acceptance, and it passed as a peer of thirty-six reviewed amendments. **A26** planted a decoy
section quoting AM-18's anchor; it failed CI once, as an ordinary digest change indistinguishable
from a reflow, and acknowledging it as editorial moved the watch to the decoy permanently.

AM-37 makes anchors unambiguous and the ledger's extent declared rather than derived. Enforcing
the first rule immediately found that **AM-15, AM-19 and AM-27 had been watching the wrong
sections all along** — their anchors matched the closure manifest and the §6 domain table before
reaching §10.3, §6 and §12, so those three invariants could have been rewritten with CI green.
That was a live false negative in the shipped ledger, not a hypothetical.

**Round 20** attacked `check-f1-enumerations.py`, the last unexamined proof surface, along eight
paths. Six landed, with one root cause: **the guard derived the universe, the canonical source, the
representation and the content from the material it was checking.** Deleting HUMAN from all four
sites passed and adding a twelfth type passed, because eleven was only ever "what we found today".
A "revised action enum" placed earlier in the file became canonical, because the source was found
by document order. The same set written as an indented code block was never scanned. Widening an
action enum with `bypass` passed, because the guard checked agreement, not content. Declaring a
real enumeration ILLUSTRATIVE exempted it. Only the shadow and laundering paths were already
blocked, by AM-35's bijection.

AM-38 pins all four in §-1's commitment block. Enforcing it found nothing pre-existing — unlike
round 19 — and the contract's normative text was again untouched except to record the rule.

**Round 21** was confirmatory: the full package against revision 22 with no prior edit and no new
scope. Seventeen attacks blocked, six structural audits clean, and all seventeen guard probes from
rounds 18–20 behaving correctly with editorial reflow still passing. One probe reported A2 missing;
it was the probe, which matched a clause across a line wrap and missed the blockquote marker — the
clause is in §2. **Zero successful, zero partial, zero ambiguous, zero security-semantic delta,
zero guard weakening, zero hidden continuity loss, no uncommitted legal universe.**

That is the first round in twenty-one to complete without a delta, and it broke the loop in which
each fix produced a new surface. **T1A is frozen at revision 22.** T1B has not yet been attacked
independently and is next.

## Standing constraints

- No implementation begins against either document while it is a draft.
- `methodology/enforcement.json` is not edited until F1 closes. The M8-CLOSEOUT audit stands as the
  baseline its records will be rewritten against; until then GP-6, GP-8 and GP-17 read "mechanism
  exists: yes; adversarially authenticated enforcement: no".
- Any attack that succeeds, or whose outcome is ambiguous, blocks the freeze of its document.
