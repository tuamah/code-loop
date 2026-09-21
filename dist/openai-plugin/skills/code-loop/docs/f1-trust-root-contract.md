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

Eight adversarial review rounds produced twenty-one amendments and twenty-one named attacks. Review 7
established that the growth was not one contract getting stronger but **two contracts tangled
together**, so they are now separate and freeze independently:

| | Document | Question it answers | Status |
|---|---|---|---|
| **T1A** | [`f1-t1a-trust-core.md`](f1-t1a-trust-core.md) | Can any statement be authenticated, bound to an identity, a scope and an order, and read as part of a coherent state? | DRAFT rev 10, not frozen |
| **T1B** | [`f1-t1b-policy-obligations.md`](f1-t1b-policy-obligations.md) | What do the authenticated statements mean — which obligations exist, when they apply, what may be concluded? | DRAFT rev 8, not frozen |

T1A guarantees a Policy Commitment is authenticated, rooted and non-rollbackable. What it *says* is
T1B. A T1B rule enforced over unauthenticated state is decoration; a T1A substrate with no T1B
semantics authenticates statements that mean nothing in particular.

**Freezing T1A does not close F1.** The intended sequence:

```
attack T1A alone with the core attacks
  → a full round with no amendment → FREEZE T1A
attack T1B with the policy and obligation attacks
  → a full round with no amendment → FREEZE T1B
  → only then is F1 closed, and only after implementation
```

## The twenty-one attacks, and where each now lives

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

## Standing constraints

- No implementation begins against either document while it is a draft.
- `methodology/enforcement.json` is not edited until F1 closes. The M8-CLOSEOUT audit stands as the
  baseline its records will be rewritten against; until then GP-6, GP-8 and GP-17 read "mechanism
  exists: yes; adversarially authenticated enforcement: no".
- Any attack that succeeds, or whose outcome is ambiguous, blocks the freeze of its document.
