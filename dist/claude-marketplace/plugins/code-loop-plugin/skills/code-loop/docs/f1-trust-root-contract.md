# F1-T1 — Trust Root Threat Model & Contract

**Status: DRAFT, revision 7, after adversarial reviews 1-6. NOT FROZEN. Review 6 found three more
attacks, including one that defeats revision 6's newest rule by timing alone; no implementation may
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

Revision 4 (review 3) adds three more, from attacking revision 3:

- **AM-4 (§7.1)** — AM-1 was circular: run identity came from the gate commitment, which itself
  carried a run binding, so the caller still minted run identity. A **Run Genesis Authority** in the
  TCB now mints it, and the dependency runs one way: run, then gate, then verification.
- **AM-5 (§7.2)** — **A6 succeeded.** Copying a mutable working tree is not atomic, so the adversary
  mutates during materialization and the master becomes a torn read: a mixture that never coherently
  existed, which the attestation would describe honestly. Candidates are now named only by
  content-addressed references, so there is nothing to tear.
- **AM-6 (§7.3)** — **A5 succeeded.** Nothing linked runs, so the adversary retried with a fresh run
  until a flaky check passed and presented that run's ACCEPT. Run lineage is now TCB-held.

Revision 5 (review 4) adds three more, found by inspecting revision 4 rather than by re-running the
attacks — the invariants were incomplete, so testing them would have measured the wrong thing:

- **AM-7 (§7.0)** — **A7 succeeded.** Lineage was gathered "for the same task", but only
  `task_digest` named a task, and that is caller-authored text. Rewording a task minted a fresh
  identity with empty lineage: Run Genesis had merely moved laundering up one level. An
  authenticated Task Commitment now sits above the run, the executor never chooses `task_id`, and
  the task's relation to existing tasks is authorized rather than declared.
- **AM-8 (§10.1)** — **A9 succeeded, and AM-6 was semantically wrong.** "Cleared by a verdict on a
  different candidate" treats different bytes as a repair, so a comment or a whitespace change
  manufactured a repair history. Failures now attach to project-scoped **obligations**, and ACCEPT
  requires a current authenticated PASS on every applicable obligation for the exact candidate being
  accepted. One rule closes A5, A7 and A9.
- **AM-9 (§7.2)** — **A8 succeeded.** Content addressing proves bytes did not change; it never
  proves they were the bytes it was permissible to build on. A caller-supplied `base_digest` let the
  adversary pick a base where the failing check does not exist. The authorized base is now a TCB
  commitment and a mismatch is refused. Integrity is not authenticity, one level further in.

Revision 6 (review 5) adds three more. Two of them attack machinery the previous round introduced,
which is the expected shape of this process:

- **AM-10 (§10.2)** — **A10 succeeded, against AM-8 itself.** AM-8 required a PASS on every
  *applicable* obligation and let the gate decide what applicable meant, so the adversary stops
  laundering the candidate and launders the scope instead: an obligation that is FAILING becomes an
  obligation that is not required. Applicability now has its own authenticated commitment and
  lineage. Silence does not deactivate, narrowing counts as deactivation, and switching off a
  currently-adverse obligation demands strictly stronger authority than switching off a passing one.
- **AM-11 (§7.0)** — **A11 succeeded, against AM-7.** Task Genesis was given four relations to
  choose between and no stated basis for choosing; any classifier driven by task text or caller
  hints is an oracle the adversary tunes until it yields `NEW_TASK`. Rather than a better
  classifier, the prize is removed: no task relation changes which obligations a candidate must
  satisfy, and an unclear relation fails closed to human authority.
- **AM-12 (§7.0.1)** — **A12 succeeded.** AM-9 derived the authorized base from "authenticated
  project state" without ever saying where the first such state came from. Adopting repository HEAD
  or a caller-named commit at provisioning moves Base Rebinding to the founding moment. A Project
  Genesis Commitment now records a digest — never a mutable ref — under a human-authorized ceremony.
  This is where the regress terminates, and it terminates in an act of authorization, not a
  computation.

Revision 7 (review 6) adds three more. The subject has shifted: the first rounds protected files and
identity, these protect **the meaning of policy itself**.

- **AM-13 (§10.2)** — **A13 succeeded, against AM-10.** AM-10 demanded stronger authority to
  deactivate a *currently adverse* obligation. The adversary does not wait: it deactivates while the
  obligation is still green, then submits the candidate that would have failed it. No red obligation
  was ever switched off. Protection level is now fixed in advance by obligation class, and the
  general shape is named: a guard conditioned on state observed at request time is
  timing-attackable.
- **AM-14 (§10.2)** — **A14 succeeded.** `authority_required_for_change` lived inside the
  Applicability Commitment, so the protected object declared how hard it was to weaken itself — F1's
  original shape one level up. Authority now comes from a Policy Root anchored at Project Genesis:
  a protected object may not define the authority required to weaken its own protection.
- **AM-15 (§10.3)** — **A15 succeeded.** Every input was individually authenticated, but nothing
  required them to be read as one state. The acceptance authority now derives from an atomic Trusted
  Decision State Snapshot, asserts every head unchanged before signing, and binds the snapshot digest
  into the payload. This is the third torn read in the contract, and the first inside the TCB itself.

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

### 3.1 Logical authorities are not a service count

Each round of this review closed a gap by naming an authority, and the list is now:

```
Registry Root · Project Genesis · Task Genesis · Run Genesis · Freeze
Verification Controller · Acceptance · Human
```

That is eight **authorization scopes**, and it would be a poor reading to build eight services with
eight keys. F1-T2 may co-locate them in a single control plane provided the separations that do the
security work survive:

| Separation | Nature | May it be co-resident? |
|---|---|---|
| worker ↔ controller | untrusted code execution | **no** — this is the one hard isolation boundary (§2, §3) |
| authority ↔ authority | authorization scope | yes, as distinct scopes and key roles in one plane |
| message domains | cryptographic domain separation (§6) | must stay distinct regardless of topology |
| human authority | outside the machine where feasible (§4) | no |

Splitting semantic authority does not require exploding the architecture into ten processes.
Collapsing the worker boundary, on the other hand, silently returns the deployment to Mode A.

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

## 7. Run genesis, candidate identity, and TOCTOU

### 7.0 The trust chain (AM-7)

Revision 4 stopped at `run -> gate -> verification`. That is too short. `parent_run_commitments`
was gathered "for the same task", but the only thing naming a task was `task_digest` — a digest of
caller-authored text (§7.4). Change a word, a description, any whitespace, and the task is new:

```
task A   -> adverse lineage
task A'  -> new task_digest -> first run -> parent_run_commitments = []
```

Run Genesis alone therefore only moved laundering up one level, from **Fresh-Run** to **Fresh-Task**
(A7). The chain must start above the task, and every link must be minted by the TCB:

```
Project Genesis           (Project Commitment, NOGAP::PROJECT::v1) — §7.0.1
        ↓
Authenticated Task        (Task Commitment, NOGAP::TASK::v1)
        ↓
TCB-minted Run            (Run Commitment, §7.1)
        ↓
Authorized Base + Gate    (§7.2, §8)
        ↓
Content-addressed Candidate
        ↓
Verification Obligation   (§10.1)
        ↓
Authenticated Verdict
        ↓
Explicit Supersession Rules
        ↓
Acceptance Decision
```

**The executor never chooses `task_id`.** It may submit a task description; a Task Genesis Authority
in the TCB mints the identity and records the task's relation to existing tasks:

```
NEW_TASK | CONTINUATION_OF(task-X) | SUPERSEDES(task-X) | CHILD_OF(task-X)
```

That relation is **authorized, not merely declared**. A caller asserting `NEW_TASK` is exactly the
A7 move, so the authority decides the relation from TCB-held state.

**Task relation carries no power over obligations (AM-11).** Revision 5 left Task Genesis deciding
between four relations without saying how — and any classifier driven by similarity, task text, or
caller hints is an oracle the adversary tunes until it returns `NEW_TASK` (A11). The fix is not a
better classifier; it is to remove the prize:

> **No task relation, and no combination of them, changes which obligations a candidate must
> satisfy.**

- `NEW_TASK` does not clear project obligations; they were never the task's to clear (§10.1).
- `SUPERSEDES` does not transfer or discharge an obligation. Only an authenticated applicability
  transition (§10.2) changes an obligation's state — task relations are not that mechanism.
- Task Genesis alone may never drop lineage.
- An unclear relation is `AMBIGUOUS_RELATION`: **fail closed**, escalate to human authority (§4).

Relation therefore stays useful for organising work and reading history, and is worthless as an
escape from it.

### 7.0.1 Project genesis and the initial base (AM-12)

AM-9 derives the authorized base from "authenticated project state". A12 asks the only question that
matters about that phrase: **where did the first authenticated project state come from?** If
provisioning adopts repository HEAD, or a commit the caller names, Base Rebinding has simply moved
to the founding moment.

```
Project Genesis Commitment        (human/operator-authorized ceremony, §5)
  project_id
  repository_identity       binds the project to a repository; blocks same-name substitution
  initial_base_digest       a DIGEST, never a mutable ref — a branch name is not a commitment
  policy_baseline           the Policy Root (AM-14): obligation_class -> required authority
  gate_baseline             what §8 matches gate content against
  obligation_policy_baseline  which obligations exist and in which class
  provisioned_by
  provisioning_sequence
```

Adopting the repository's current HEAD is acceptable **only** when a human authorizes that specific
digest and the ceremony records the digest itself. A ref moves; a digest does not.

This is where the regress terminates, and it terminates in an **act of authorization, not a
computation**. Every authenticated derivation in this contract bottoms out here. The contract's job
is to make that point singular, explicit and auditable rather than implicit and scattered — which is
also why R4 names provisioning the highest-value target in the whole design.

### 7.1 Run genesis (AM-4) — breaking revision 3's circular dependency

Revision 3 said run identity is read from the authenticated gate commitment (§8), while §8 said the
gate commitment carries a project/run binding. That is circular: `run_id` must already exist before
the commitment that supposedly defines it, so whoever supplies it at freeze time **mints run
identity** — and that is the caller. Run creation was therefore still an adversary primitive, which
is also what made A5 (§17) trivial.

Run identity is minted by a **Run Genesis Authority** inside the TCB, before any gate exists:

```
Trusted Run Manifest                       (built by the TCB, not read from the workspace)
  project_id            resolved from the TCB's authenticated project binding, never caller text
  task_digest           digest of the task contract; a binding, not an endorsement (§7.4)
  policy_version
  creation_nonce        TCB-generated; never caller-supplied
  run_id                TCB-derived from (project_id, creation_nonce, creation_sequence)
  parent_run_commitments  lineage for this task (§7.3); empty only for the first run
  created_by_authority
  creation_sequence     per-authority, atomic, durable
        ↓ signed
  Run Commitment        (NOGAP::RUN::v1)
        ↓ referenced by
  Gate Commitment       (NOGAP::GATE::v1, §8) — carries run_commitment_digest, not a bare run_id
        ↓ referenced by
  Verification / Decision payloads — carry both commitments
```

The dependency now runs one way: **project, task, run, gate, verification.** A caller may *request*
a run; it can never choose the resulting identity. A request naming a `run_id` that the TCB did not
mint is refused, and a gate commitment whose `run_commitment_digest` resolves to no TCB-held Run
Commitment is refused.

The interface takes an **authenticated Task Commitment**, never a caller-supplied digest:

```
FORBIDDEN   create_run(task_digest)                    caller names the task, and so its lineage
PERMITTED   create_run(authenticated_task_commitment)  caller says only "a run for this task"
```

From that commitment the authority resolves project, task identity, parent runs, authorized base
(§7.2) and policy out of TCB state. The caller supplies none of them.

### 7.2 Candidate acquisition must be content-addressed (AM-5)

"Materialize an immutable master snapshot" was not enough. §1 grants the adversary mutation *at any
moment*, and copying a working tree is not atomic: the adversary mutates during the copy and the
master becomes a **torn read** — a mixture of candidate A and candidate B that never coherently
existed. The attestation would then be perfectly honest about a state no one ever authored, and the
adversary can shape the tear so that the mixture passes checks neither A nor B would.

The fix is not a faster copy. It is to stop snapshotting mutable state at all:

- A candidate is identified by **content-addressed references**, never by "the working tree as it
  currently is": `base_digest` (an immutable base object) plus `patch_digest` (immutable content).

**Content-addressed is not authorized (AM-9).** A digest proves *these bytes did not change*. It
never proves *these were the bytes it was permissible to build on*. If the caller supplies
`base_digest`, it picks the base: an older commit, a branch where the failing test does not exist,
any object it can reach. That is the same lesson as F1 itself — integrity is not authenticity — one
level further in. Therefore:

- the **authorized base** for a task is a TCB-held commitment, derived from authenticated project
  state and recorded in the Task Commitment (§7.0), not taken from the request
- the controller checks `base_digest == the base committed for this task/run`, and **refuses**
  otherwise; it never accepts a base named by the caller
- for a repair run, the authorized base is the prior candidate, which is what makes candidate
  lineage (§10.1) structural rather than claimed
- Both are recorded in the Run Commitment's candidate binding before verification begins.
- The controller materializes the master **from those objects**, not from the workspace. The
  content of a content-addressed object cannot change under it, so there is nothing to tear.
- If a reference does not resolve, verification is refused. It is never resolved "as close as
  possible" to something in the workspace.

This aligns with what the runtime already produces: `nogap execute` yields a patch, and today's
`candidate_hash` is already derived from `patch_hash`. What changes is that those digests stop
being descriptive labels and become the **only** way the candidate is named.

### 7.3 Run lineage (AM-6)

A fresh run must not be a fresh start. Without lineage, the adversary simply retries: run, get an
adverse verdict, mint another run, repeat until a flaky check passes, then present that run's
ACCEPT. Every run in that sequence is individually honest, and the sequence as a whole is laundering.

- Every Run Commitment records `parent_run_commitments` for the same task, assembled by the TCB
  from its own records — never from the workspace, which cannot be trusted to remember.
- The acceptance authority evaluates a candidate against **the task's whole lineage**. Revision 4
  said an adverse verdict is cleared by a verdict on a *different* candidate; that was wrong, and
  §10.1 replaces it. A different fingerprint proves different bytes, never a repair.
- Omission is not possible: lineage lives in the TCB, so a caller that simply does not mention
  earlier runs changes nothing.
- Run creation is deliberately **not** rate-limited by magic. Creating a thousand runs is useless by
  construction: each one still gets a baseline-bound gate (§8), so more runs never yield an easier
  gate, and lineage means more runs never yield a cleaner history.

### 7.4 What a signature over caller-derived content does and does not mean

`task_digest` binds a payload to a task contract the caller authored. Signing a *binding* to
caller-supplied content is not an *endorsement* of that content, and nothing downstream may treat it
as one. Only fields the authority itself derived — verdict, candidate_fingerprint, sequence,
signed_at, deployment_mode — carry the authority's word.

### 7.5 The verification sequence

```
verify(request_id)            request names run/task by id; nothing self-describing
   ↓ controller:
resolve the TCB-held Run Commitment            (never from the workspace)
load the Gate Commitment bound to it
resolve base_digest + patch_digest from the candidate binding   else REFUSE
materialize the MASTER from those content-addressed objects into TCB storage
derive candidate_fingerprint from the MASTER
hand the worker an EPHEMERAL COPY               (the worker may write to, or destroy, its copy)
collect bounded observations
re-confirm the MASTER is unchanged              else ABORT, no attestation
discard the worker copy
re-derive verdict, construct payload, sign
```

**Master ownership and lifecycle.** The master is created by the controller, lives in TCB-controlled
storage for the life of the verification, and is destroyed or retained by policy afterwards. The
executor can neither read-modify nor replace it, and destroying the worker copy — which the worker
is free to do — has no effect on it. A master materialized inside the project worktree is not a
master; it is the thing the adversary is still holding (see R3).

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
- The freeze request must name a **TCB-held Run Commitment** (§7.1). A gate commitment is bound to
  `run_commitment_digest`, never to a bare `run_id` the caller chose.
- **First commitment wins per run.** A second commitment for the same Run Commitment is refused.
  Changing the gate means a new run with its own genesis and authorization — which is what
  "immutable for one run" actually requires. Because every run's gate is baseline-bound, minting
  more runs does not produce an easier gate (§7.3).
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

### 10.1 Verification obligations and supersession (AM-8)

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
  applicability        which candidates it applies to, decided by the gate, never claimed
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

A later verdict may be recorded as superseding an earlier adverse one only when all hold: it is on
the **same `obligation_id`**; the candidate is a **TCB-recorded descendant** of the adverse one
(structural under AM-9, not claimed); the gate/policy in force is **equal or stronger**; and it is a
PASS. Policy — not the trust root — then decides whether that supersession counts as repair. Every
decision record carries the adverse verdicts it superseded, so a candidate that passed on attempt 47
is visibly that.

**Supersession is not proof of causal repair.** See R5.

### 10.2 Applicability is part of the trust root (AM-10)

§10.1 requires a PASS on every **applicable** obligation, and revision 5 let the gate decide what
"applicable" meant. That hands the adversary a second laundry: instead of changing the candidate
until the failure disappears, change the *scope* until the obligation does.

```
O1 applicable -> FAIL            becomes            O1 not applicable -> no PASS required
```

The word *applicable* is therefore load-bearing, and anything load-bearing must be authenticated
exactly like identity, gate and candidate. Applicability gets its own commitment and its own
lineage:

```
Applicability Commitment          (NOGAP::APPLICABILITY::v1)
  obligation_id
  obligation_class          risk class; the POLICY maps class -> required authority (AM-14)
  project_scope
  predicate_scope
  activation_condition
  deactivation_condition
```

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


### 10.3 The decision must observe one coherent state (AM-15)

Every input to ACCEPT is now individually authenticated. That is still not enough. The acceptance
authority reads many of them — project, policy, task, run, gate, base, obligations, applicability,
verdicts, registry — and if it reads them at different moments, each read is valid while the
combination never existed:

```
read PASS for O1            ✓ authentic
applicability or policy changes
read PASS for O2            ✓ authentic
authorized base or run head moves
sign ACCEPT                 ← derived from a state that never held as a whole
```

This is the third torn read in this contract. A6 tore the workspace; A15 tears the TCB's own state.
The general rule, stated once so a fourth instance is not invented: **any multi-source read that
feeds an attested conclusion must be snapshot-consistent, not merely individually authenticated.**

It is also M8's lesson returning: deep immutability of each input does not compose into
decision-level consistency when the inputs are read at different times.

```
Trusted Decision State Snapshot
  project_head
  policy_head
  task_commitment
  run_commitment
  gate_commitment
  authorized_base_commitment
  candidate_fingerprint
  obligation_set_commitment
  applicability_head
  verification_verdict_set
  registry_head
```

```
derive the decision from snapshot S
  ↓
before signing, assert every head is unchanged   (compare-and-swap)
  ↓
sign the decision, binding S's digest into the payload
```

- On CAS failure the decision is **aborted and re-derived from a fresh snapshot**. It is never
  patched, merged, or partially re-read — partial re-reads are how torn state returns.
- `decision_snapshot_digest` is part of the signed payload, so a later reader can re-derive the
  decision from the same state instead of trusting that it was coherent.
- A verdict arriving mid-decision belongs to the next snapshot, never half of this one.

Equivalently, a single monotonic event-log head covering all of this state satisfies the rule; what
matters is that one coherent point in time is named, not how it is implemented.

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
- **R2 — Adversary-influenced input to the TCB is attack surface.** The controller parses worker
  output, and under AM-5 it also resolves and materializes content-addressed objects the adversary
  authored. Any tool it runs over that data — an archiver, a patch applier, a parser — is TCB
  surface. §2 makes the handling rules normative; the residual is that a defect inside the TCB is a
  TCB compromise, which §1 places out of scope.
- **R3 — Snapshot storage is part of the TCB.** §7's guarantee holds only while the snapshot is
  beyond the executor's reach. Under Mode A it is not.
- **R5 — Supersession cannot prove causation.** A PASS on a descendant after a FAIL may be a real
  fix or a flaky predicate that happened to pass. The trust root binds facts; it cannot infer that
  one caused the other, and it must not pretend to. The residual laundering vector is therefore
  flakiness: retry until every applicable obligation passes at once. Mitigation is policy, not
  cryptography — require predicates to be deterministic or reproducible, require N consecutive
  passes, or require human sign-off to supersede nominated obligation classes. This is the exact
  seam between *cryptographically valid* and *engineering-valid*, and NoGapCode must state which one
  it is claiming.
- **R4 — Provisioning is the root of everything.** An adversary present at trust-root provisioning
  owns all of it. Out of scope by §1, but it makes the ceremony the highest-value target.

## 17. Open for adversarial review 2

**Fifteen** attacks must be shown to fail before F1-T1 FREEZE.

Review 3, against revision 3:

```
A1  Signing Oracle              blocked, but rested on a circular run identity  -> AM-4
A2  Verifier Key Exfiltration   blocked (Mode B); TCB input surface widened     -> R2
A3  Candidate TOCTOU            blocked, and strengthened                       -> AM-5
A4  Unauthorized Gate Freeze    blocked, now anchored to a TCB-minted run       -> AM-4
A5  Fresh-Run Laundering        SUCCEEDED                                       -> AM-6
A6  Master Substitution         SUCCEEDED                                       -> AM-5
```

Review 4, against revision 4, by inspection:

```
A7  Fresh-Task Laundering               SUCCEEDED                      -> AM-7
A8  Base Rebinding                      SUCCEEDED                      -> AM-9
A9  Trivial-Change Failure Laundering   SUCCEEDED; AM-6 was wrong      -> AM-8
```

Review 5, against revision 5, by inspection:

```
A10 Applicability Narrowing             SUCCEEDED, against AM-8    -> AM-10
A11 Task-Relation Laundering            SUCCEEDED, against AM-7    -> AM-11
A12 Project/Base Genesis Substitution   SUCCEEDED                  -> AM-12
```

Review 6, against revision 6, by inspection:

```
A13 Pre-Failure Applicability Laundering  SUCCEEDED, against AM-10   -> AM-13
A14 Self-Authorized Policy Downgrade      SUCCEEDED                  -> AM-14
A15 Mixed-State / Decision TOCTOU         SUCCEEDED                  -> AM-15
```

Revision 7 has not been attacked. Review 7 must run all fifteen against it. Any attack that
succeeds, or whose outcome is ambiguous, blocks the freeze.

The trend is now three rounds long: reviews 4, 5 and 6 each found defects in machinery the previous
round had just introduced. Every new authority and every new rule is new attack surface, so the
fifteen are re-run in full rather than only the newest three. Convergence is not guaranteed by
adding amendments, and a round that adds none would be better evidence of it than a round that adds
three.

An attack that fails only under conditions this contract does not require is not a pass; the
condition must be written in.
