# F1-T1 — Trust Root Threat Model & Contract Freeze

**Status: DRAFT for adversarial review. Not frozen. No implementation may begin against it.**

F1 renamed per audit: *Missing Authenticated Trust Root / Forgeable Authority State*.

## 0. What this fixes, stated honestly

NoGapCode's Trust Runtime today enforces every rule it claims — against an actor that labels
itself honestly. Reproduced, not inferred:

```
mallory: never executed, never verified, only wrote one JSON file
nogap validate  -> OK
nogap decide    -> accept: "independent authoritative verification evidence passed
                            and acceptance authority is separate from execution"
```

And the executor can launder its own work:

```
mallory executes for real  (authority=execution, actor_id=mallory)
decide as mallory          -> repair        [separation holds against honesty]
mallory writes verifier-X verification evidence
decide as acceptor-1       -> accept        [separation gone]
```

And the frozen gate is a self-stored checksum, not an authenticated commitment:

```
edit rules, leave hash        -> FAIL: hash mismatch
edit rules, recompute hash    -> OK: workspace valid
```

The common root: **authority, identity and immutability are self-asserted data in files the
adversary can rewrite.** There is no trust root anywhere in the system.

The adversary with exactly this capability is not an intruder. It is the implementer agent, which
holds repository write access by construction — the actor NoGapCode exists not to trust.

## 1. Adversary model (v1)

The executing agent may be **fully adversarial inside the workspace**.

IN scope — the adversary can:

- read and write any project file, including all of `.code-loop/`
- fabricate, delete, reorder or replay any runtime record: evidence, claims, gates, decisions,
  events, artifacts, methodology state, failure/research/lifecycle records
- recompute any digest the runtime computes, because every digest input is on disk
- present any `actor_id`, `--authority`, role string or provenance field it likes
- run any command it is permitted to run, including every `nogap` subcommand
- observe all non-secret runtime state, including gate contents and fingerprints
- retry indefinitely and choose timing

OUT of scope — the adversary does **not**:

- hold any private key belonging to a verification, acceptance or freeze authority
- control the trusted control plane's own execution
- have root/admin, kernel, or hypervisor control
- have compromised the signer, the trust root, or the authority registry's root key

Explicitly undefended in v1 (state this wherever the guarantee is claimed):
root/admin compromise, kernel or firmware compromise, malware controlling the machine, trusted
signer compromise, private-key theft from inside the trust boundary, and physical access.

## 2. The rule that decides the whole design

> **No component shall sign an assertion supplied by an untrusted caller.**

A signer that accepts `{"authority": "verification", "verdict": "passed"}` and returns a signature
has moved F1 from *"I can write a file"* to *"I can ask the oracle to write it for me"*. Nothing is
gained.

Therefore the authority that signs a verification verdict **must be the same component that
performed the verification**, and it must construct the signed payload from its own observations.
Its interface accepts a *request to verify*, never a *verdict to endorse*:

```
PERMITTED   verify(run_id, gate_fingerprint, candidate_fingerprint) -> signed verdict
FORBIDDEN   sign(payload)                                           -> signature
FORBIDDEN   attest(verdict, authority)                              -> signed evidence
```

The same rule binds the freeze authority (it computes the gate commitment from the gate it is
given, and signs only what it canonicalized itself) and the acceptance authority (it re-derives
admissibility; it never signs a caller's claim that a decision is admissible).

## 3. Trusted Computing Base, and what each deployment actually guarantees

The TCB is: the trust root, the authority registry, the private keys, and the processes holding
them — the verification authority, the freeze authority, and the acceptance authority.

The current code has **no TCB at all**: `cmd_verify` is a subcommand of the same CLI process the
executor invokes, writing `authority="verification"` with whatever `--actor` it was passed. The
verifier is a function call, not a principal. Making it a principal is the work.

Three deployment modes, with **different real guarantees**. This table is normative: no mode may
advertise a stronger guarantee than its row.

| Mode | Signer isolation | Defends against a file-forging executor | Defends against a same-principal executor |
|---|---|---|---|
| **A: same OS principal** | separate process, same user | **yes** | **no** |
| **B: separate principal** | distinct OS user / container / sandbox | yes | **yes** |
| **C: external plane** | CI runner or remote signer, different host | yes | yes |

**Mode A is not a security boundary.** An adversary running as the same OS user can read the key
file, attach to the signer process, or replace its binary. Mode A closes the *file-forgery* path
and makes the trust boundary explicit, testable, and portable — it does not close the adversary
model in §1. Any claim that F1 is closed under Mode A is itself a false-success claim of exactly
the kind this project exists to prevent.

**Consequence for the roadmap:** F1 is closed only when Mode B (or C) is the deployment. Mode A is
a migration step, not a destination. The implementation must make the mode a first-class, recorded
property so a decision record can never imply a guarantee its deployment did not provide.

## 4. Authority identities and key ownership

Asymmetric per-identity keys, not a shared MAC secret. A shared secret cannot distinguish the four
authority classes: whoever holds it can impersonate all of them, which re-opens GP-8 by a different
door.

| Identity class | Holds a private key | Key lives | May sign |
|---|---|---|---|
| `execution` | **no** | — | nothing; execution evidence is unsigned by design (§7) |
| `verification` | yes, per verifier identity | TCB, outside the repository and outside `.code-loop/` | verification verdicts it produced |
| `acceptance` | yes, per acceptor identity | TCB | decision records it derived |
| `freeze` | yes | TCB | gate commitments it canonicalized |
| `human` | external approval, or a key held by a person | outside the machine where feasible | human approvals |
| `tool` | **no** | — | nothing authoritative |

The executor holds **no** key of any class. `nogap verify` as invoked by an agent becomes a request
to the verification authority, not a local write.

## 5. Authority registry, and its own root

The registry maps `key_id -> (identity, authority class, scope, validity window, state)`.

A registry the adversary can edit is not a registry: it would simply add its own public key. So:

- the registry lives **outside the repository and outside `.code-loop/`**, under the TCB, **or**
- it is itself signed by a root key held only by the TCB, and its signature is verified before use

Public material inside the project tree is a convenience cache only. It is never authoritative, and
a cache that disagrees with the TCB registry is an error, not a fallback.

The trust root is established out of band (operator provisioning, CI secret, or an explicit
initialization ceremony recorded as a decision). It is never created implicitly on first use — an
implicitly created root is a root the adversary can create first.

## 6. Canonical trust payload

Signatures cover a small, explicit payload — never a raw file, never "the JSON as it happens to be
serialized". Malleable canonicalization is signature forgery by another name.

```
schema_version          contract version; a payload of unknown version is inadmissible
key_id                  which key signed; resolves to identity and grants in the registry
producer_identity       the asserting principal, as recorded in the registry
authority_class         verification | acceptance | freeze | human
project_id              binds to a project; prevents cross-project replay
run_id                  binds to a run; prevents cross-run replay
gate_fingerprint        the authenticated gate commitment (§8)
candidate_fingerprint   task + patch + candidate; prevents cross-candidate replay
subject_digest          digest of what is being attested (result, verdict, gate payload)
verification_method     how the verdict was reached; a bare verdict is not a method
verdict                 the outcome, as observed by the signer
sequence                signer-assigned monotonic counter; never caller-supplied
signed_at               signer clock; never caller-supplied
policy_version          which admissibility policy was in force
deployment_mode         A | B | C from §3, recorded so no reader over-reads the guarantee
```

Canonicalization rules (all normative, all fail-closed on violation): UTF-8; JSON object keys
sorted by code point; no insignificant whitespace; integers only for `sequence`; timestamps as
RFC 3339 UTC with explicit precision; absent fields omitted, never `null`; unknown fields rejected
rather than ignored. Then:

```
canonical_payload -> digest -> signature over (schema_version || digest)
```

Domain separation: the signature covers the schema version alongside the digest, so a payload of
one type can never be reinterpreted as another.

## 7. What is authenticated, and what deliberately is not

**Execution evidence stays unsigned.** It is a claim by an untrusted party and is treated as such:
it is recorded, it is useful context, and it is never admissible for ACCEPT. Signing it would
imply a trust it does not have. This is unchanged from today's `authority="execution"` handling —
which the audit confirmed is correctly never counted by `is_authoritative_evidence()`.

**Verification verdicts are authenticated**, by the authority that performed them.

**Gate commitments are authenticated** (§8).

**Decision records are authenticated** by the acceptance authority, so a decision cannot be
fabricated after the fact either.

## 8. Gate authentication

The gate's current `hash` field is a checksum stored beside the data it covers: the audit
demonstrated an informed tamperer recomputes both and passes `validate` cleanly. It detects
incoherent edits, not malicious ones.

Freezing becomes an operation of the freeze authority:

```
gate payload -> canonical digest -> freeze authority signs -> authenticated gate commitment
```

`gate_fingerprint` in every other payload refers to the **authenticated commitment**, not to a
recomputable digest. Editing `rules` and re-digesting no longer helps: the adversary cannot produce
a valid commitment for the new root.

The existing `stable_hash` digests (patch, candidate) remain useful as *binding* values inside
signed payloads. They were never authenticity mechanisms and must stop being described as if they
were.

## 9. Admissibility

`is_authoritative_evidence()` today reads `provenance.authority` and believes it. It is replaced by
an ordered, fail-closed procedure. Every step is a rejection point; there is no path that reaches
admissible by default:

```
1. payload parses under a known schema_version, and canonicalizes identically      else INADMISSIBLE
2. signature verifies under key_id                                                  else INADMISSIBLE
3. key_id resolves in the authenticated registry                                    else INADMISSIBLE
4. key state is valid at signed_at (not retired-before, not revoked)                else INADMISSIBLE
5. registry grants producer_identity the claimed authority_class                    else INADMISSIBLE
6. scope covers this project_id / run_id / candidate                                else INADMISSIBLE
7. gate_fingerprint matches the authenticated commitment for this run               else INADMISSIBLE
8. candidate_fingerprint matches the live candidate                                 else STALE
9. producer_identity is not an execution identity of this run                       else INADMISSIBLE
10. deployment_mode is recorded and not weaker than policy requires                 else INADMISSIBLE
```

Only then may the Decision Engine consider the evidence. The existing checks that the audit
confirmed genuine — `acceptability()`'s executor-identity rejection, contradictory-evidence
blocking, non-passing rejection — are kept and now run on an authenticated input instead of a
self-asserted one.

## 10. Rotation, revocation, historical verification

- **Rotation**: `key_id` is in every payload; a new key is a new `key_id`. Signing switches; nothing
  historical is re-signed.
- **Retirement**: a retired key stops signing. Signatures made inside its validity window remain
  valid. Historical evidence keeps verifying.
- **Revocation (compromise)**: the registry records a compromise instant. Signatures with
  `signed_at` at or after that instant become inadmissible. Earlier ones are marked
  `disputed` — not silently valid, not silently void, because the runtime cannot know when the key
  actually leaked. A disputed decision requires human re-affirmation. Inventing a clean verdict
  here would be exactly the false certainty this contract exists to remove.
- **Retention**: the registry never forgets retired or revoked keys. Forgetting a key makes every
  decision it signed unverifiable, which silently rewrites history.

## 11. Fail-closed rules

Absent, unknown or unverifiable authentication is **inadmissible**, never "legacy compatible".

This is deliberate and it is a direct lesson from this same audit: `preflight_build()` returns
`permitted: True` for a project with no methodology state, and that fail-open is precisely why
GP-1/GP-2 cannot be enforced today. The trust root must not repeat it.

Migration for projects created before this contract is therefore **explicit, dated and recorded**:
an operator decision naming the projects and an expiry, written as a decision record, never a
silent default and never an environment variable that flips the default. A runtime that cannot
reach its registry **fails closed**; it does not proceed on a cached answer.

## 12. Consequent restatement of the audit verdicts

Until authentication exists, GP-6, GP-8 and GP-17 are recorded as:

```
Mechanism exists:                      YES  (verified at the enforcement point)
Adversarially authenticated enforcement: NO
```

Nothing built is deleted or downgraded in value. But the word *authoritative* carries its strong
meaning only after §9 holds. `enforcement.json` is not edited until F1 is closed; this contract is
the baseline against which those records will then be rewritten.

## 13. Known cost

~9 test files reference verification authority; 5 write it literally; 8 write evidence JSON
directly. NoGapBench's own `add_claim_and_evidence` performs exactly mallory's attack. The suite is
currently indistinguishable from the exploit, so authentication necessarily rewrites how tests
construct authoritative evidence — they will need a test-scoped identity inside the TCB, not a
bypass flag. A bypass flag for tests would reintroduce F1 with a friendlier name.

## 14. Open for adversarial review

1. Mode A ships first as a migration step — or do we refuse to ship until Mode B, given §3's
   guarantee table?
2. Is `nogap verify` invoked by an agent an IPC request to a resident authority, or does the
   authority re-run the checks itself in its own boundary? The second is stronger and slower.
3. Does `human` authority require a key at all in v1, or is an out-of-band approval record enough?
4. Should `sequence` be per-identity or per-run, and what breaks under concurrent signers?
5. Registry outside the repo makes clone-and-verify impossible for a third party. Do we need a
   detached, publishable verification bundle in v1, or is that v2?
6. What is the smallest primitive that satisfies §6 without pulling in a crypto dependency the
   project's Ladder would reject — and does the standard library suffice?
