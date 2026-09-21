# F1-T1 — Trust Root Threat Model & Contract

**Status: DRAFT, revision 3, after adversarial reviews 1 and 2. Not frozen. No implementation may
begin against it.**

F1 renamed per audit: *Missing Authenticated Trust Root / Forgeable Authority State*.

Revision 2 (review 1) changed §2, §3, §6, §8, §9, §10, §14 and added §7 and §16. Revision 1's §2
was itself unsafe: it required the signer to be "the same component that performed the
verification", which puts the private key inside the process executing untrusted project code —
key exfiltration written into the contract.

Revision 3 (review 2) adds three amendments found by attacking revision 2:

- **AM-1 (§7)** — run identity was resolved from `.code-loop/`, which §1 gives the adversary. A1
  partially succeeded: an attestation could be redirected onto a run of the adversary's choosing,
  and §8's "first commitment wins per run" could be sidestepped by naming a fresh `run_id`. Run
  identity is now anchored in the TCB-held authenticated gate commitment.
- **AM-2 (§7)** — re-fingerprinting the worker's tree would fail on every honest build. Master-copy
  semantics added: the controller keeps an immutable master, the worker gets a disposable copy.
- **AM-3 (§2)** — worker-output handling was advice in §16; it is now normative, together with an
  explicit rule that the controller never executes or imports project code.

## 0. What this fixes, stated honestly

NoGapCode's Trust Runtime enforces every rule it claims — against an actor that labels itself
honestly. Reproduced, not inferred:

```
mallory: never executed, never verified, only wrote one JSON file
nogap validate  -> OK
nogap decide    -> accept: "independent authoritative verification evidence passed
                            and acceptance authority is separate from execution"
```

The executor can launder its own work:

```
mallory executes for real  (authority=execution, actor_id=mallory)
decide as mallory          -> repair        [separation holds against honesty]
mallory writes verifier-X verification evidence
decide as acceptor-1       -> accept        [separation gone]
```

The frozen gate is a self-stored checksum, not an authenticated commitment:

```
edit rules, leave hash        -> FAIL: hash mismatch
edit rules, recompute hash    -> OK: workspace valid
```

Common root: **authority, identity and immutability are self-asserted data in files the adversary
can rewrite.** There is no trust root anywhere in the system. The adversary holding that capability
is not an intruder — it is the implementer agent, which has repository write access by
construction.

## 1. Adversary model (v1)

The executing agent may be **fully adversarial inside the workspace**.

IN scope — the adversary can:

- read and write any project file, including all of `.code-loop/`
- fabricate, delete, reorder or replay any runtime record
- recompute any digest the runtime computes, because every digest input is on disk
- present any `actor_id`, `--authority`, role string or provenance field
- run any command it is permitted to run, including every `nogap` subcommand
- **author the project code and tests that a verification check will execute**
- mutate the workspace at any moment, including during a verification run
- retry indefinitely and choose timing

OUT of scope — the adversary does **not**:

- hold any private key of a verification, acceptance, freeze or human authority
- control the trusted control plane's own execution
- have root/admin, kernel, or hypervisor control
- have compromised the signer, the trust root, or the registry root key
- participate in the trust-root provisioning ceremony (§5)

Explicitly undefended in v1: root/admin compromise, kernel or firmware compromise, machine-wide
malware, trusted signer compromise, private-key theft from inside the trust boundary, physical
access. State this wherever the guarantee is claimed.

## 2. The invariant that decides the design

> **The trusted verification authority MUST control, define, and independently observe the
> verification operation, and MUST construct the attestation from those observations.**
>
> **Untrusted project code MAY execute only inside an isolated verification worker that holds no
> authority key and cannot modify the authority, registry, policy, or signer.**

Two failure modes are being closed at once, and revision 1 closed only the first:

- **Signing oracle** — a signer that endorses caller-supplied assertions moves F1 from "I can write
  a file" to "I can ask the oracle to write it for me".
- **Key exfiltration** — a signer that executes adversary-authored code in its own process can have
  its key read out by that code.

So the authority splits in two, and the key never crosses the line:

```
TRUSTED VERIFICATION CONTROLLER          holds the key; never executes project code
  ├── selects the check plan from the authenticated gate
  ├── materializes and fingerprints the candidate snapshot itself (§7)
  ├── dispatches the worker
  │
  ▼
ISOLATED VERIFICATION WORKER             NO KEYS; untrusted code runs here
  └── returns raw, bounded, schema-constrained observations
        │
        ▼
TRUSTED VERIFICATION CONTROLLER
  ├── re-derives the verdict from those observations
  ├── constructs the canonical payload
  └── signs
```

Permitted and forbidden interfaces, for every authority:

```
PERMITTED   verify(request_id)            -> signed verdict, payload built by the controller
FORBIDDEN   sign(payload)                 -> signature
FORBIDDEN   attest(verdict, authority)    -> signed evidence
FORBIDDEN   verify(run, gate_fp, cand_fp) -> caller-supplied identity of what was tested (§7)
```

The freeze authority is bound by the same invariant plus an authorization requirement (§8). The
acceptance authority re-derives admissibility itself and never signs a caller's claim that a
decision is admissible.

**The controller never executes or imports project code.** It reads project bytes to fingerprint
them; execution happens only in the worker. Worker output crosses a trust boundary and is treated
as hostile input: size-bounded, schema-constrained, parsed without dynamic evaluation, and rejected
rather than coerced when malformed. A controller compromised through its own parser is a TCB
compromise, so this is normative here, not advice in §16.

## 3. Deployment modes, defined by capability

The TCB is: the trust root, the authority registry, the private keys, and the processes holding
them — the verification controller, the freeze authority, and the acceptance authority.

Today there is **no TCB**: `cmd_verify` is a subcommand of the same CLI process the executor
invokes, writing `authority="verification"` with whatever `--actor` it was passed. The verifier is
a function call, not a principal. Making it a principal is the work.

**Mode B is defined by what the executor cannot do, never by a technology name.** A container that
does not deliver these properties is Mode A no matter what it is called.

Mode B requires that the executor, and any code it authors, cannot:

```
read or copy any private authority key
write, replace or reorder the authority registry
modify the signer binary, its libraries, or its configuration
attach to, debug, trace, or dump the memory of any TCB process
invoke an arbitrary signing operation
alter the verification policy or the check plan
write or edit verification observations after the worker returns
escape the worker into the verification controller
mutate the candidate snapshot the controller materialized (§7)
```

| Mode | What it is | Stops a file-forging executor | Stops a same-principal executor | May assert `AUTHENTICATED_TRUST` |
|---|---|---|---|---|
| **A** | signer is a separate process under the same OS principal | yes | **no** | **no** |
| **B** | every capability above is denied | yes | **yes** | yes |
| **C** | TCB on a different host (CI runner, remote signer) | yes | yes | yes |

**Mode A is not a security boundary.** A same-principal adversary reads the key file, attaches to
the signer, or replaces its binary. Mode A closes the file-forgery path and makes the boundary
explicit and testable; it does not close §1. Per §14, Mode A is permitted for development and
migration only, must never emit `AUTHENTICATED_TRUST=true`, and does not close F1. Production
claims begin at Mode B.

`deployment_mode` is recorded in every payload (§6) so a reader can never over-read the guarantee.

## 4. Authority identities and key ownership

Asymmetric per-identity keys, not a shared MAC secret: a shared secret cannot distinguish the
authority classes, and whoever holds it can impersonate all of them — re-opening GP-8 by another
door.

| Identity class | Private key | Key lives | May sign |
|---|---|---|---|
| `execution` | **no** | — | nothing; execution evidence is unsigned by design (§9) |
| `verification` | yes, per controller identity | TCB, outside the repo and outside `.code-loop/` | verdicts it observed and re-derived |
| `acceptance` | yes, per acceptor identity | TCB | decisions it re-derived |
| `freeze` | yes | TCB | authorized gate commitments (§8) |
| `human` | yes — a personal key, or a TCB channel bound to a human identity | outside the machine where feasible | human approvals |
| `tool` | **no** | — | nothing authoritative |

The executor and the verification worker hold **no** key of any class.

**Human authority is authenticated too.** An out-of-band approval record inside `.code-loop/` is
forgeable exactly like everything else and is not acceptable evidence of human approval.

## 5. Authority registry and trust root

The registry maps `key_id -> (identity, authority class, scope, validity window, state)`.

A registry the adversary can edit is not a registry — it would add its own public key. Therefore it
lives **outside the repository and outside `.code-loop/`** under the TCB, **or** it is itself
signed under `NOGAP::REGISTRY::v1` by a root key held only by the TCB and verified before use.
Public material inside the project tree is a cache only; a cache disagreeing with the TCB registry
is an error, never a fallback.

The trust root is established **out of band** by an explicit provisioning ceremony recorded as a
decision. It is never created implicitly on first use — an implicitly created root is a root the
adversary can create first. An adversary present at provisioning is out of scope (§1).

## 6. Canonical payload, canonicalization, domain separation

Signatures cover a small explicit payload, never a raw file and never "the JSON as it happens to
serialize".

```
schema_version          unknown version -> inadmissible
message_type            one of the domain strings below
key_id                  resolves to identity and grants in the registry
producer_identity       the asserting principal as recorded in the registry
authority_class         verification | acceptance | freeze | human
project_id              binds to a project; blocks cross-project replay
run_id                  binds to a run; blocks cross-run replay
gate_commitment         the authenticated gate commitment (§8)
candidate_fingerprint   computed by the controller from its own snapshot (§7)
subject_digest          digest of what is attested
verification_method     how the verdict was reached; a bare verdict is not a method
verdict                 the outcome as observed by the signer
sequence                per-signing-identity, atomic, durable (§14); ordering, not freshness
signed_at               signer clock; see §10 on what it cannot prove
policy_version          admissibility policy in force
deployment_mode         A | B | C (§3)
```

**Canonicalization**: RFC 8785 (JSON Canonicalization Scheme). It is a published, testable
specification rather than a local convention, so independent implementations agree. The contract
ships JCS test vectors; a payload that does not re-canonicalize byte-identically is inadmissible.
Unknown fields are rejected, not ignored. Absent fields are omitted, never `null`.

**Domain separation** is by explicit message type, not by schema version:

```
NOGAP::GATE::v1      || canonical_payload
NOGAP::VERIFY::v1    || canonical_payload
NOGAP::DECISION::v1  || canonical_payload
NOGAP::REGISTRY::v1  || canonical_payload
NOGAP::HUMAN::v1     || canonical_payload
```

A verification signature can never be reinterpreted as a decision, even if the payloads coincide.
`message_type` inside the payload must equal the prefix signed over; a mismatch is inadmissible.

**Algorithm**: Ed25519 via `cryptography`. This is the project's first runtime dependency and the
Ladder justifies it: rung 3 (standard library) does not reach — Python ships `hashlib`/`hmac` and
no Ed25519 — and the alternatives are a shared-secret MAC that cannot separate authorities, or
hand-rolled signatures. Avoiding a maintained cryptographic library to preserve a zero-dependency
property would be optimizing the wrong variable against an empirically demonstrated trust-root
break. Private-key storage backend and OS isolation are deferred to F1-T2; raw key files are not
assumed.

## 7. Candidate identity and TOCTOU

The controller must never accept the caller's word for what it is about to test. Between a
caller-supplied `candidate_fingerprint` and the checks running, the adversary can swap the
workspace: candidate A is tested, candidate B is attested.

**Run identity must itself be authenticated (AM-1).** `run.json` and the task contract live in
`.code-loop/` and are adversary-writable under §1, so resolving a request against them lets the
adversary redirect an attestation onto a run or task of its choosing — and lets it defeat §8's
"first commitment wins per run" simply by naming a fresh `run_id`. Therefore:

- a run exists, for trust purposes, only once it has an **authenticated gate commitment** (§8)
  held by the TCB; `project_id` and `run_id` are read from that commitment, never from the workspace
- a verification request naming a run with no authenticated gate commitment is **refused**
- the TCB keeps its own record of which commitments exist; the workspace copy is a cache (§5)

The caller therefore supplies **references only**:

```
verify(request_id)            request names run/task by id; nothing self-describing
   ↓ controller:
resolve run/task via the TCB-held authenticated gate commitment  (never from the workspace)
load the authenticated gate commitment
materialize an IMMUTABLE MASTER snapshot into TCB-controlled storage
compute candidate_fingerprint FROM THE MASTER
give the worker an EPHEMERAL COPY of the master        (the worker may write to its copy)
collect bounded observations
re-confirm the MASTER's fingerprint is unchanged        else ABORT, no attestation
discard the worker copy
re-derive verdict, construct payload, sign
```

**Master-copy semantics (AM-2).** A build or test legitimately writes to the tree it runs in, so
re-fingerprinting the worker's copy would either fail on honest runs or prove nothing. The
controller retains an immutable **master** and hands the worker a disposable copy; the attestation
binds the master's fingerprint, and the post-run confirmation is of the master, not of the copy.

The master must live in storage the executor cannot mutate. A master materialized inside the
project worktree is not a master — it is the thing the adversary is still holding. If its
fingerprint changes between materialization and completion, the run aborts and nothing is signed;
a mutated candidate never produces a "best effort" attestation.

## 8. Authorized freeze

Canonicalizing and signing a gate the caller handed over is a signing oracle with extra steps.
Mallory says *"freeze this easier gate"*, the authority computes the digest itself and signs it,
the signature verifies perfectly — and the run is now governed by a gate the adversary chose.

Freezing therefore requires **authorization**, separate from **canonicalization**:

```
authorized freeze request
        +  gate content conforming to an authenticated baseline, OR an authenticated human approval
        +  project/run binding
        +  freeze policy version
                ↓
        Freeze Authority
                ↓
        signed Gate Commitment  (NOGAP::GATE::v1)
```

Rules:

- The gate content must **canonically match an authenticated gate baseline** held in the TCB and
  established at provisioning, or carry an **authenticated human approval** (§4) for this specific
  deviation, for this project and run.
- No "weakness ordering" is invented. The contract does not try to decide whether one gate is
  weaker than another; anything that is not an exact authenticated baseline match requires a human.
- **First commitment wins per run.** A second commitment for the same `run_id` is refused. Changing
  the gate means a new run with its own authorization — which is what "immutable for one run"
  actually requires.
- The separation is explicit: *"this is the data I signed"* is not *"I was authorized to adopt this
  data as the gate for this run."*

The existing `stable_hash` digests (patch, candidate) remain useful as binding values inside signed
payloads. They were never authenticity mechanisms and must stop being described as if they were.

## 9. What is authenticated, and what deliberately is not

**Execution evidence stays unsigned.** It is a claim by an untrusted party, recorded and useful as
context, never admissible for ACCEPT. Signing it would imply trust it does not have. The audit
confirmed today's `authority="execution"` handling is already correctly excluded by
`is_authoritative_evidence()`.

Authenticated: verification verdicts, gate commitments, decision records, human approvals, and the
registry itself.

## 10. Admissibility

`is_authoritative_evidence()` today reads `provenance.authority` and believes it. It is replaced by
an ordered, fail-closed procedure with no default-admissible path:

```
 1. payload parses under a known schema_version and re-canonicalizes byte-identically  else INADMISSIBLE
 2. message_type matches the signed domain prefix                                      else INADMISSIBLE
 3. signature verifies under key_id                                                    else INADMISSIBLE
 4. key_id resolves in the authenticated registry                                      else INADMISSIBLE
 5. key state permits this signature (§11)                                             else INADMISSIBLE / DISPUTED
 6. registry grants producer_identity the claimed authority_class                      else INADMISSIBLE
 7. scope covers this project_id / run_id / candidate                                  else INADMISSIBLE
 8. gate_commitment matches the authenticated commitment for this run                  else INADMISSIBLE
 9. candidate_fingerprint matches the live candidate                                   else STALE
10. producer_identity is not an execution identity of this run                         else INADMISSIBLE
11. deployment_mode is recorded and not weaker than policy requires                    else INADMISSIBLE
```

The checks the audit confirmed genuine — `acceptability()`'s executor-identity rejection,
contradictory-evidence blocking, non-passing rejection — are kept, now running on an authenticated
input instead of a self-asserted one.

## 11. Rotation, revocation, and what local time cannot prove

`signed_at` comes from the signer's own clock. There is no trusted timestamping and no transparency
log in v1, so a local timestamp is **not** proof of when a signature was made. The revocation model
must not pretend otherwise.

- **Rotation**: `key_id` is in every payload; a new key is a new `key_id`. Nothing historical is
  re-signed.
- **Retirement**: a retired key stops signing; signatures within its validity window stay valid.
- **Revocation (compromise)**: the registry records a **known-compromised-after** bound — the
  earliest instant compromise is known to have been possible, not a claim about when the key
  actually leaked. Signatures at or after that bound are **definitely invalid**. Earlier signatures
  are **DISPUTED**: not silently valid, not silently void, requiring human re-affirmation. The
  runtime never asserts a precise compromise instant it cannot establish.
- **Retention**: retired and revoked keys are never forgotten. Forgetting a key makes every decision
  it signed unverifiable, which silently rewrites history.

## 12. Fail-closed rules

Absent, unknown or unverifiable authentication is **inadmissible**, never "legacy compatible".

This is a direct lesson from the same audit: `preflight_build()` returns `permitted: True` for a
project with no methodology state, and that fail-open is precisely why GP-1/GP-2 cannot be enforced
today. The trust root must not repeat it.

Migration is therefore **explicit, dated and recorded**: an operator decision naming the projects
and an expiry, written as a decision record — never a silent default, never an environment variable
that flips it. A runtime that cannot reach its registry **fails closed**.

## 13. Consequent restatement of the audit verdicts

Until authentication exists, GP-6, GP-8 and GP-17 are recorded as:

```
Mechanism exists:                        YES  (verified at the enforcement point)
Adversarially authenticated enforcement: NO
```

Nothing built is deleted or devalued. The word *authoritative* carries its strong meaning only once
§10 holds. `enforcement.json` is not edited until F1 is closed; this contract is the baseline its
records will be rewritten against.

## 14. Resolved decisions

1. **Mode A** — permitted for development and migration. Must never emit `AUTHENTICATED_TRUST=true`
   and does not close F1. Production claims begin at Mode B.
2. **`nogap verify`** — becomes an IPC/API request to the Trusted Verification Controller. The
   controller selects the check plan, launches the isolated worker, and derives the verdict. It
   never accepts a verdict from the caller.
3. **Human authority** — must be authenticated: a personal key, or a TCB channel bound to a human
   identity. A record in `.code-loop/` is not evidence of human approval.
4. **`sequence`** — per signing identity, atomic and durable across crashes. It is an ordering and
   gap-detection mechanism, not by itself a proof of freshness.
5. **Publishable verification bundle** — v2. Not a condition for F1-v1, but the payload format must
   not foreclose it.
6. **Cryptography** — Ed25519 via `cryptography`. No HMAC, no hand-rolled primitives.

## 15. Known cost

~9 test files reference verification authority; 5 write it literally; 8 write evidence JSON
directly. NoGapBench's own `add_claim_and_evidence` performs exactly mallory's attack, so the suite
is currently indistinguishable from the exploit. Authentication necessarily rewrites how tests
construct authoritative evidence: they get a test-scoped identity inside the TCB. **A test bypass
flag is prohibited** — it would reintroduce F1 under a friendlier name.

## 16. Residual limits after this contract

These are not F1 and are not closed by it. They are recorded so no one reads an authenticated
verdict as more than it is.

- **R1 — Authenticated ≠ meaningful.** The gate names the checks; the adversary authors the code
  those checks execute. A signed verdict proves *who observed what*, never that the observation was
  a meaningful test. A project that writes a vacuous test still gets an honestly signed "passed".
  Mitigation belongs to effect verification (GP-10) and reproducibility, not to the trust root.
- **R2 — Worker output is attack surface.** The controller parses data produced under adversary
  influence. §2 makes the handling rules normative; the residual is that a parser defect inside the
  TCB is a TCB compromise, which §1 places out of scope.
- **R3 — Snapshot storage is part of the TCB.** §7's guarantee holds only while the snapshot is
  beyond the executor's reach. Under Mode A it is not.
- **R4 — Provisioning is the root of everything.** An adversary present at trust-root provisioning
  owns all of it. Out of scope by §1, but it makes the ceremony the highest-value target.

## 17. Open for adversarial review 2

Four attacks must be shown to fail against this contract before F1-T1 FREEZE:

```
A1  Signing Oracle
A2  Verifier Key Exfiltration
A3  Candidate TOCTOU
A4  Unauthorized Gate Freeze
```

An attack that fails only under conditions this contract does not require is not a pass; the
condition must be written in.
