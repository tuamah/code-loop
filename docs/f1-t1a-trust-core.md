# F1-T1A — Authenticated Trust Core

**Status: DRAFT, revision 10, after adversarial review 9. NOT FROZEN.** Review 9 ran the full
fourteen-attack round: twelve blocked, and the two composed attacks introduced by review 8 passed —
because §10's procedure had not been rebuilt when AM-19 replaced the payload it was written against. Split out of the single F1-T1
contract after review 7, which established where the seam lies. Review 8 attacked the core alone and
found three defects in it — A19 missing domain separation for the newest commitments, A20 a registry
that granted nothing, A21 human approvals replayable across operations — all three inside message
identity, signer authority and authorization binding rather than in any new semantic layer. See `f1-trust-root-contract.md` for F1's overall
status and for F1-T1B.

T1A answers one question: **can any statement in this system be authenticated, bound to an identity,
a scope and an order, and read as part of a coherent state?** It says nothing about what the
statements should mean — that is T1B's subject. The two freeze independently, and freezing T1A does
not close F1.

Scope boundary, so nothing falls between the two documents:

| T1A owns | T1B owns |
|---|---|
| keys, identities, registry, trust root | which obligations exist and in which class |
| controller/worker isolation | when an obligation is applicable |
| project / task / run / gate / base commitments | how applicability may change |
| content-addressed candidates | what counts as supersession |
| attestation, admissibility, decision-snapshot consistency | how flaky checks are handled |
| canonicalization, domain separation, anti-rollback | what evidence burden is sufficient |

T1A guarantees a Policy Commitment is authenticated, rooted and non-rollbackable. What it *says* is
T1B.

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

### 5.1 A valid key is not every authority (AM-20)

§4 names key classes and §3.1 calls the eight authorities "authorization scopes", but revision 8
never said what the registry actually **enforces**. A verifier reading a `RUN` commitment signed by
the key it also knows as the freeze authority had no rule to apply. That gap is the whole ballgame:
without it, holding any TCB key is holding all of them (A20).

The registry therefore grants explicitly, per key:

```
key_id ->
  allowed_message_types     which domains (§6) this key may sign, enumerated
  allowed_actions           which operations within them
  allowed_projects          scope, or a declared wildcard
  validity                  window, state, epoch (§10.3)
```

> **Possessing a valid key is not possessing every TCB authority.** A signature is admissible only
> if the registry grants *that* `key_id` *that* `message_type` and action, in *that* scope.

This is deliberately independent of process topology (§3.1). One control-plane key may legitimately
carry several scopes; what may never happen is a key exercising an authority the registry did not
grant it. Genesis authorities — project, task, run — are ordinary grants under this rule, not
implicit powers: revision 8 left them as scopes with no cryptographic principal, and they now
resolve like every other signer.

## 6. Canonical payload, canonicalization, domain separation

Signatures cover a small explicit payload, never a raw file and never "the JSON as it happens to
serialize".

**One payload shape for every message type was a defect (AM-19).** Revision 8 defined a single
canonical payload carrying `verdict`, `verification_method`, `gate_commitment`,
`candidate_fingerprint` and the rest — fields that are meaningless for a `PROJECT` commitment, and
that a `HUMAN` approval may have no run or gate for at all. Optional-everywhere fields are how a
field that means nothing today becomes a hole tomorrow. The payload therefore splits into a common
envelope and a message-specific body, and a body is validated against its own schema:

```
Common Signed Envelope            present in every message, identical meaning in every message
  schema_version                  unknown version -> inadmissible
  message_type                    one of the domains below; must equal the signed prefix
  key_id                          resolves to identity, grants and validity in the registry
  producer_identity               the asserting principal, as recorded in the registry
  sequence                        per-signing-identity, atomic, durable; ordering, not freshness
  signed_at                       signer clock; see §11 on what it cannot prove
  deployment_mode                 A | B | C (§3)

Message-specific body             validated against the schema for message_type, and no other
  PROJECT        project_id, repository_identity, initial_base_digest, policy_baseline,
                 gate_baseline, obligation_policy_baseline, provisioned_by, provisioning_sequence
  TASK           project_commitment, task_digest, relation, parent_task_commitment
  RUN            project_commitment, task_commitment, creation_nonce, run_id,
                 parent_run_commitments, authorized_base_commitment, policy_head
  GATE           run_commitment, gate_content_digest, baseline_match | human_authorization,
                 freeze_policy_version
  VERIFY         run_commitment, gate_commitment, candidate_fingerprint, obligation_id,
                 verification_method, verdict, observation_digest
  DECISION       run_commitment, candidate_fingerprint, decision, decision_snapshot_digest,
                 superseded_adverse_verdicts, policy_head
  POLICY         project_commitment, epoch, previous_commitment, class_authority_map_digest
  APPLICABILITY  project_commitment, obligation_id, obligation_class, transition, epoch,
                 previous_commitment, authorization_ref
  REGISTRY       epoch, previous_commitment, key_grants_digest
  HUMAN          authorization body (§6.1)
```

A field absent from a body's schema is not optional — it is **rejected**. There is no shared
grab-bag in which an unused field can quietly acquire meaning.

**Canonicalization**: RFC 8785 (JSON Canonicalization Scheme). It is a published, testable
specification rather than a local convention, so independent implementations agree. The contract
ships JCS test vectors; a payload that does not re-canonicalize byte-identically is inadmissible.
Unknown fields are rejected, not ignored. Absent fields are omitted, never `null`.

**Domain separation** is by explicit message type, not by schema version:

```
NOGAP::PROJECT::v1        || canonical_payload
NOGAP::TASK::v1           || canonical_payload
NOGAP::RUN::v1            || canonical_payload
NOGAP::GATE::v1           || canonical_payload
NOGAP::VERIFY::v1         || canonical_payload
NOGAP::DECISION::v1       || canonical_payload
NOGAP::POLICY::v1         || canonical_payload
NOGAP::APPLICABILITY::v1  || canonical_payload
NOGAP::REGISTRY::v1       || canonical_payload
NOGAP::HUMAN::v1          || canonical_payload
```

Revision 8 used `PROJECT`, `TASK`, `RUN`, `POLICY` and `APPLICABILITY` throughout §7 and §10 while
defining domains only for the other five, so the newest and most powerful commitments in the
contract had no signing domain at all (A19). The list above is **closed**: a message type without a
domain string and a body schema cannot be signed, and adding one is a contract change.

A verification signature can never be reinterpreted as a decision, even if the bodies coincide.
`message_type` inside the envelope must equal the prefix signed over; a mismatch is inadmissible.

### 6.1 Authorization is not authentication (AM-21)

The contract leans on "authenticated human approval" in three places — a gate deviation (§8), an
applicability weakening (T1B), an ambiguous task relation (§7.0). Revision 8 never bound an approval
to the operation it approved. A human approves a gate deviation for run X; the signature is valid
forever, for anything that asks for a human approval, so it is replayed to found a second project,
authorize a different run, or weaken a policy (A21).

> **Authentication proves who signed. Authorization must additionally prove what exact operation
> that signer authorized.**

A `HUMAN` body is purpose-bound:

```
authorization_id       unique; the consumption record keys on it
action_type            the single operation authorized
target_message_type    the domain it may be consumed by, and no other
project_commitment     which project
subject_digest         the exact thing approved — this gate content, this transition
requested_transition   for a state change, the precise from -> to
policy_head            the policy under which approval was given (§10.3)
use_semantics          single-use, or reusable within an explicitly declared scope
expiry
```

Consumption is recorded in the TCB. A single-use authorization presented twice is **refused on the
second attempt**, and a reusable one is refused outside its declared scope. An authorization whose
`policy_head` is no longer current is refused: approval was given under rules that have since
changed, and silently carrying it forward would re-open A18 through the human path.

This closes the loop back to the very first invariant (§2). A signing oracle signs what it is told;
a replayable approval is the same failure in slower motion — a human's intent, detached from its
object, becomes a token anyone can spend.

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
an ordered, fail-closed procedure with no default-admissible path.

**The procedure is normative and complete (AM-22).** Revision 9 left an eleven-step list written
against the single payload AM-19 had already replaced: step 6 tested `authority_class`, a field the
envelope no longer has, and no step tested AM-20's grants or AM-21's authorization binding at all.
Those rules existed only as prose in §5.1 and §6.1 while §10 claimed to be the place admissibility
is decided — so the composed attacks (a valid key signing a message type it was never granted; a
genuine human approval replayed onto another operation) passed every enumerated step. A rule stated
in one section and absent from the procedure that enforces it is not enforced.

The procedure now mirrors AM-19's split: a stage every message passes, then a stage keyed on
`message_type`. A message type with no stage-2 clause is inadmissible rather than waved through.

```
STAGE 1 — every message, in order
 1. envelope parses at a known schema_version and re-canonicalizes byte-identically   else INADMISSIBLE
 2. message_type is in §6's closed domain list                                        else INADMISSIBLE
 3. message_type equals the signed domain prefix                                      else INADMISSIBLE
 4. body validates against THAT message_type's schema; unknown fields reject           else INADMISSIBLE
 5. signature verifies under key_id                                                    else INADMISSIBLE
 6. key_id resolves in the authenticated registry at its current head                  else INADMISSIBLE
 7. key state permits a signature at signed_at (§11)                     else INADMISSIBLE / DISPUTED
 8. registry grants this key_id THIS message_type and action (§5.1)                    else INADMISSIBLE
 9. registry grant covers this project scope (§5.1)                                    else INADMISSIBLE
10. every head the body names is the current authoritative head (§10.3, AM-18)         else INADMISSIBLE
11. sequence is consistent for this signing identity; gaps are reported, not ignored   else INADMISSIBLE
12. deployment_mode is recorded and not weaker than policy requires                    else INADMISSIBLE

STAGE 2 — by message_type
 VERIFY         gate_commitment is the authenticated commitment for this run           else INADMISSIBLE
                candidate_fingerprint matches the live candidate                       else STALE
                producer_identity is not an execution identity of this run             else INADMISSIBLE
 DECISION       decision_snapshot_digest resolves and its heads were current at CAS    else INADMISSIBLE
                producer_identity is not an execution identity of this run             else INADMISSIBLE
 GATE           names a TCB-held Run Commitment; baseline match OR a HUMAN
                authorization admissible for THIS gate content (§8)                    else INADMISSIBLE
 HUMAN          purpose-binding holds: action_type, target_message_type, subject_digest
                and requested_transition match the operation being authorized          else INADMISSIBLE
                not previously consumed, or within its declared reusable scope (§6.1)  else INADMISSIBLE
                policy_head is current; not expired                                    else INADMISSIBLE
 PROJECT        provisioning ceremony recorded; repository_identity binds (§7.0.1)     else INADMISSIBLE
 TASK           project_commitment resolves; relation authorized, not declared (§7.0)  else INADMISSIBLE
 RUN            task_commitment resolves; run_id was TCB-minted (§7.1);
                authorized_base_commitment resolves (§7.2)                             else INADMISSIBLE
 POLICY         epoch is current head; previous_commitment chains (§10.3)              else INADMISSIBLE
 APPLICABILITY  epoch chains; authorization_ref is an admissible HUMAN or policy-granted
                authorization for this class and transition (T1B §B4)                  else INADMISSIBLE
 REGISTRY       signed by the trust root; epoch chains (§5)                            else INADMISSIBLE
```

Stage 1 step 8 is what makes a key a *scoped* principal rather than a TCB master key, and the HUMAN
clause is what makes an approval an authorization rather than a token. Both were the round-9
composed attacks.

The checks the audit confirmed genuine — `acceptability()`'s executor-identity rejection,
contradictory-evidence blocking, non-passing rejection — are kept, now running on an authenticated
input instead of a self-asserted one.

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

**A valid head is not the current head (AM-18).** Snapshot consistency still lets the adversary pick
*which* coherent state to observe. Two policies can both carry perfect signatures:

```
Policy v1   valid signature, weaker
Policy v2   valid signature, stronger
```

Pinning `policy_head` to v1 yields a decision in which every signature verifies, every input is
authenticated, the snapshot is coherent — and a deliberately superseded policy was applied (A18).

> **A decision may use only the current authoritative head, never merely a cryptographically valid
> one.**

This applies to **every** head in the snapshot, not only policy: `registry_head`,
`applicability_head`, `project_head` and the obligation set are each open to the same move. So each
carries a monotonic epoch held by the TCB, and each commitment names its predecessor:

```
epoch                      monotonic, TCB-held, never caller-supplied
previous_commitment        chains each head to the one it supersedes
current_head               the TCB's answer; a snapshot pinning anything else is refused
```

Stated generally, because this is the sixth variant of the same mistake in this contract:
**authenticity establishes that a statement was made; it never establishes that it is still the
operative one.** Integrity, authenticity and currency are three properties, and this contract has now
needed all three separately.

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
- **R4 — Provisioning is the root of everything.** An adversary present at trust-root provisioning
  owns all of it. Out of scope by §1, but it makes the ceremony the highest-value target.

