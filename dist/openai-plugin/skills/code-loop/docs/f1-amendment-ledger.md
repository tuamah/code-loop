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

**Digest** is of the whole section the anchor heads, whitespace-normalized: editing the rule fails
CI, reflowing a line does not. **Inherits** is how supersession works — an amendment may only be
retired if exactly one live amendment declares it and carries its invariant forward, so
"superseded" can never mean "we stopped talking about it".

**Extent** is declared, not derived. Round 19 deleted the highest-numbered row and the audit
passed: the gap check asked the ledger how many amendments the ledger has. It also accepted an
invented AM-37 granting an authority nobody agreed to. The count below is the external pin — a
truncation or a fabrication now contradicts a line someone has to edit deliberately.

```
AMENDMENTS: 40 through AM-40
```

**Reopening a frozen contract.** T1A was frozen at revision 22, commit `b667d64`, after adversarial
review 21 completed clean. The first adversarial review of T1B then found defects in the *seam*
between the two contracts, which neither document's own audit could see because every guard read
one document. AM-39 reopened T1A under the freeze rule — a numbered amendment that names what it
changes and why — and T1A re-freezes at revision 23. The earlier freeze is not annulled: it was
correct on the evidence then available, and this is the case reopen-by-amendment exists for.

```
F1-T1A rev22   FROZEN at b667d64
               REOPENED by AM-39
               reason: cross-contract representability defects found in T1B review 1
F1-T1A rev23   re-frozen after the AM-39 regression
               REOPENED by AM-40
               reason: supersession had no owner, no representation and no enforcement
                       point; found in T1B review 2
F1-T1A rev24   re-frozen after the AM-40 regression
```

Status is `LIVE` (the invariant is in force and located) or `SUPERSEDED` (replaced by a later
amendment, named in the Where column). A superseded amendment is never deleted: it records a
decision that was reconsidered, and why.

| AM | Status | Where | Anchor | Digest | Inherits | Invariant |
|---|---|---|---|---|---|---|
| AM-1 | SUPERSEDED | AM-4 | `` | `` |  | Run identity anchored in the gate commitment — circular; the caller still minted it |
| AM-2 | LIVE | T1A | `Master ownership and lifecycle` | `00df7e8ab0d7` |  | The controller keeps an immutable master; the worker gets a disposable copy |
| AM-3 | LIVE | T1A | `size-bounded, schema-constrained` | `a3324affaed1` |  | Worker output is hostile input; the controller never executes project code |
| AM-4 | LIVE | T1A | `Run genesis (AM-4)` | `dd6477756eaa` | AM-1 | A Run Genesis Authority mints run identity; the caller never chooses it |
| AM-5 | LIVE | T1A | `content-addressed (AM-5)` | `7d694b761616` |  | A candidate is named only by content-addressed references; nothing to tear |
| AM-6 | LIVE | T1B | `Run lineage (AM-6)` | `2179c1119511` |  | Run lineage is TCB-held; a fresh run is not a fresh start |
| AM-7 | LIVE | T1A | `The trust chain (AM-7)` | `2afecb2b4860` |  | An authenticated Task Commitment sits above the run; relation is authorized |
| AM-8 | LIVE | T1B | `(AM-8, AM-16, AM-17)` | `c1ce76a68de7` |  | Failures attach to project-scoped obligations, never to fingerprints |
| AM-9 | LIVE | T1A | `Content-addressed is not authorized (AM-9)` | `7d694b761616` |  | The authorized base is a TCB commitment; a caller-named base is refused |
| AM-10 | LIVE | T1B | `(AM-10, AM-13, AM-14)` | `602ac5f7fa11` |  | Applicability is authenticated; silence does not deactivate, narrowing does |
| AM-11 | LIVE | T1B | `no power over obligations (AM-11)` | `5af11196fff8` |  | No task relation changes which obligations a candidate must satisfy |
| AM-12 | LIVE | T1A | `Project genesis and the initial base (AM-12)` | `382eab97ee83` |  | Genesis records a digest, never a ref, under a human-authorized ceremony |
| AM-13 | LIVE | T1B | `pre-declared, never read off the current state (AM-13)` | `602ac5f7fa11` |  | Protection level is fixed by class in advance, not by current red/green state |
| AM-14 | LIVE | T1A | `the Policy Root (AM-14)` | `382eab97ee83` |  | A protected object may not define the authority required to weaken it |
| AM-15 | LIVE | T1A | `snapshot-consistent, not merely individually authenticated` | `88e9b7728f9e` |  | A decision derives from one coherent snapshot and CAS-checks before signing |
| AM-16 | LIVE | T1B | `born, not merely not-killed (AM-16)` | `c1ce76a68de7` |  | Silence cannot prevent an obligation's birth any more than cause deactivation |
| AM-17 | LIVE | T1B | `never chosen by the object (AM-17)` | `c1ce76a68de7` |  | A protected object may not choose its own protection class |
| AM-18 | LIVE | T1A | `A valid head is not the current head (AM-18)` | `88e9b7728f9e` |  | Only the current authoritative head may be used, never any valid one |
| AM-19 | LIVE | T1A | `One payload shape for every message type was a defect (AM-19)` | `f0ff38fe8238` |  | Ten closed domains; common envelope plus a per-type body schema |
| AM-20 | LIVE | T1A | `A valid key is not every authority (AM-20)` | `d9f1a62b5744` |  | The registry grants message types, actions and scope per key |
| AM-21 | LIVE | T1A | `Authorization is not authentication (AM-21)` | `2a66269deee8` |  | A human authorization is purpose-bound and consumed once |
| AM-22 | LIVE | T1A | `The procedure is normative and complete (AM-22)` | `3f9782daed24` |  | Admissibility is a two-stage procedure; a rule absent from it is not enforced |
| AM-23 | LIVE | T1A | `The action must be signed, not inferred (AM-23)` | `f0ff38fe8238` |  | The exact action is in the signed envelope, from a closed per-type enum |
| AM-24 | LIVE | T1A | `(AM-24, AM-25)` | `9938f798d27a` |  | A single-use authorization is a linear capability, consumed atomically |
| AM-25 | LIVE | T1A | `assert current_head == expected_previous` | `9938f798d27a` |  | Validation and mutation of authoritative state are one transaction |
| AM-26 | LIVE | T1A | `One transactional domain` | `9938f798d27a` |  | All such state lives in one serialized domain; authorities are scopes over it |
| AM-27 | LIVE | T1A | `Its body schema lives with the others in` | `c5bed291a665` |  | The one sanctioned fail-closed exemption is a representable, authenticated message |
| AM-28 | LIVE | T1A | `The class is not the gate; the registry grant is (AM-28)` | `3a4aedf4542c` |  | Migration is atomic and headed; §4 is a summary; a grant never elevates trust |
| AM-29 | LIVE | T1A | `Statefulness is defined by effect, not by fields (AM-29)` | `9938f798d27a` |  | Statefulness is decided by effect, never by shape and never by the author |
| AM-30 | LIVE | T1A | `S is a definition, not a list (AM-30)` | `88e9b7728f9e` |  | The snapshot is the set of facts the decision reads; a read fact absent is a defect |
| AM-31 | LIVE | T1A | `Mode B is an invariant, not a list of nine prohibitions (AM-31)` | `b5179f931ea0` |  | Mode B is a five-clause invariant; the nine capabilities are test vectors for it |
| AM-32 | LIVE | T1A | `Closure rules for this contract (AM-32)` | `9b3e59ac8cc9` |  | Every security-significant enumeration is DERIVED, CLOSED+CHECKED, or NON-NORMATIVE |
| AM-33 | LIVE | T1A | `The rule applies to itself (AM-33)` | `25019dbc777a` |  | The closure manifest is canonical and checked; no enumeration enters undeclared |
| AM-34 | LIVE | T1A | `Clause 3 says *outcome* deliberately (AM-34)` | `b5179f931ea0` |  | Mode B forbids influence that moves the outcome toward acceptance, not all influence |
| AM-36 | LIVE | T1A | `Continuity is a guard, not a memory (AM-36)` | `8f86d8f91d08` |  | Invariants are digested; supersession must be inherited by exactly one live amendment |
| AM-35 | LIVE | T1A | `bijection, not mere coverage` | `25019dbc777a` |  | The closure manifest is a bijection; enumerations are blocks or tables, both scanned |
| AM-37 | LIVE | T1A | `The ledger is not self-attesting (AM-37)` | `e16846724046` |  | Anchors must be unambiguous; the ledger's extent is declared, never derived |
| AM-38 | LIVE | T1A | `The guard may not derive what it is guarding (AM-38)` | `136295e8ca7d` |  | Universe, source, representation and content of every governed enumeration are pinned in advance |
| AM-39 | LIVE | T1A | `A schema defined twice is defined nowhere (AM-39)` | `35a8ab3293e8` |  | T1A is the single canonical source for every schema; T1B states meaning only; both contracts are one closure set |
| AM-40 | LIVE | T1A | `An override with no owner is not a rule (AM-40)` | `d0f3c428dc12` |  | Supersession is signed by the verification authority, raise-only, non-repeatable, and enforced in Stage 2 |
