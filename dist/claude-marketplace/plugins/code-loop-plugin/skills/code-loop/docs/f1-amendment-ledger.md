# F1 — Amendment Ledger

**Canonical record of every amendment.** Thirty amendments came out of fifteen adversarial review
rounds. The reasoning behind them lived in a conversation; only the contracts and this file survive
it. A rewrite that looks like an improvement can silently drop an invariant an earlier round paid
for, and without a canonical record nothing notices.

`scripts/check-f1-continuity.py` enforces this table: every **LIVE** amendment must have its anchor
present in the named document, every **SUPERSEDED** one must name its replacement, and the
numbering may not skip. The checker's first run found AM-1, AM-2 and AM-3 cited nowhere in either
contract — two had survived unlabelled and one had been superseded, and which was which was knowable
only from the conversation. That is the failure this file exists to prevent.

Status is `LIVE` (the invariant is in force and located) or `SUPERSEDED` (replaced by a later
amendment, named in the Where column). A superseded amendment is never deleted: it records a
decision that was reconsidered, and why.

| AM | Status | Where | Anchor | Invariant |
|---|---|---|---|---|
| AM-1 | SUPERSEDED | AM-4 | `` | Run identity anchored in the gate commitment — circular; the caller still minted it |
| AM-2 | LIVE | T1A | `Master ownership and lifecycle` | The controller keeps an immutable master; the worker gets a disposable copy |
| AM-3 | LIVE | T1A | `size-bounded, schema-constrained` | Worker output is hostile input; the controller never executes project code |
| AM-4 | LIVE | T1A | `Run genesis (AM-4)` | A Run Genesis Authority mints run identity; the caller never chooses it |
| AM-5 | LIVE | T1A | `content-addressed (AM-5)` | A candidate is named only by content-addressed references; nothing to tear |
| AM-6 | LIVE | T1B | `Run lineage (AM-6)` | Run lineage is TCB-held; a fresh run is not a fresh start |
| AM-7 | LIVE | T1A | `The trust chain (AM-7)` | An authenticated Task Commitment sits above the run; relation is authorized |
| AM-8 | LIVE | T1B | `(AM-8, AM-16, AM-17)` | Failures attach to project-scoped obligations, never to fingerprints |
| AM-9 | LIVE | T1A | `Content-addressed is not authorized (AM-9)` | The authorized base is a TCB commitment; a caller-named base is refused |
| AM-10 | LIVE | T1B | `(AM-10, AM-13, AM-14)` | Applicability is authenticated; silence does not deactivate, narrowing does |
| AM-11 | LIVE | T1B | `no power over obligations (AM-11)` | No task relation changes which obligations a candidate must satisfy |
| AM-12 | LIVE | T1A | `Project genesis and the initial base (AM-12)` | Genesis records a digest, never a ref, under a human-authorized ceremony |
| AM-13 | LIVE | T1B | `pre-declared, never read off the current state (AM-13)` | Protection level is fixed by class in advance, not by current red/green state |
| AM-14 | LIVE | T1A | `the Policy Root (AM-14)` | A protected object may not define the authority required to weaken it |
| AM-15 | LIVE | T1A | `Trusted Decision State Snapshot` | A decision derives from one coherent snapshot and CAS-checks before signing |
| AM-16 | LIVE | T1B | `born, not merely not-killed (AM-16)` | Silence cannot prevent an obligation's birth any more than cause deactivation |
| AM-17 | LIVE | T1B | `never chosen by the object (AM-17)` | A protected object may not choose its own protection class |
| AM-18 | LIVE | T1A | `A valid head is not the current head (AM-18)` | Only the current authoritative head may be used, never any valid one |
| AM-19 | LIVE | T1A | `(AM-19)` | Ten closed domains; common envelope plus a per-type body schema |
| AM-20 | LIVE | T1A | `A valid key is not every authority (AM-20)` | The registry grants message types, actions and scope per key |
| AM-21 | LIVE | T1A | `Authorization is not authentication (AM-21)` | A human authorization is purpose-bound and consumed once |
| AM-22 | LIVE | T1A | `The procedure is normative and complete (AM-22)` | Admissibility is a two-stage procedure; a rule absent from it is not enforced |
| AM-23 | LIVE | T1A | `The action must be signed, not inferred (AM-23)` | The exact action is in the signed envelope, from a closed per-type enum |
| AM-24 | LIVE | T1A | `(AM-24, AM-25)` | A single-use authorization is a linear capability, consumed atomically |
| AM-25 | LIVE | T1A | `assert current_head == expected_previous` | Validation and mutation of authoritative state are one transaction |
| AM-26 | LIVE | T1A | `One transactional domain` | All such state lives in one serialized domain; authorities are scopes over it |
| AM-27 | LIVE | T1A | `NOGAP::MIGRATION::v1` | The one sanctioned fail-closed exemption is a representable, authenticated message |
| AM-28 | LIVE | T1A | `The class is not the gate; the registry grant is (AM-28)` | Migration is atomic and headed; §4 is a summary; a grant never elevates trust |
| AM-29 | LIVE | T1A | `Statefulness is defined by effect, not by fields (AM-29)` | Statefulness is decided by effect, never by shape and never by the author |
| AM-30 | LIVE | T1A | `S is a definition, not a list (AM-30)` | The snapshot is the set of facts the decision reads; a read fact absent is a defect |
| AM-31 | LIVE | T1A | `Mode B is an invariant, not a list of nine prohibitions (AM-31)` | Mode B is a five-clause invariant; the nine capabilities are test vectors for it |
| AM-32 | LIVE | T1A | `Closure rules for this contract (AM-32)` | Every security-significant enumeration is DERIVED, CLOSED+CHECKED, or NON-NORMATIVE |
