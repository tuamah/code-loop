# NoGapCode Runtime

Read this when a project contains `.code-loop/runtime/`, or before running or trusting any
`nogap` command. Everything else in Code Loop is discipline you apply yourself; this is the part
that records what happened and refuses to call unverified work done.

The runtime does not make an agent trustworthy. It makes an agent's claims checkable.

## The Rule That Makes The Rest Work

```text
Execution Authority MUST NOT be Acceptance Authority.
```

An implementer may read the gate, edit code, run local checks, and submit claims. It may never
issue ACCEPT for its own run. Renaming a role to `verifier` does not change identity: the check is
on `actor_id`, not on the word. Local checks and model confidence are not acceptance evidence.

```text
tests/build/lint > runtime traces > source docs > reviewer findings > model confidence
```

## Minimum Loop

```bash
python scripts/nogap.py init .          # create the runtime workspace
python scripts/nogap.py freeze .        # freeze the gate for this run - hashed, immutable
python scripts/nogap.py run . --execute # plan, route, dispatch, collect the patch
python scripts/nogap.py verify-methodology .   # P15-P18 ladder over workspace evidence (NON-AUTHORITATIVE)
python scripts/nogap.py verify <request-id> .  # trusted verification; fails closed without a provisioned trust root
python scripts/nogap.py decide .        # accept / repair / abstain / human-review
python scripts/nogap.py status .        # where this run stands
```

`freeze` is what makes the rest meaningful. The gate is hashed; editing it after the fact is
detected and fails validation. Do not edit a frozen gate to make a run pass - start a new run, or
get explicit human approval.

`decide` is the only command that can accept. Execution evidence alone never reaches ACCEPT: it
needs passing evidence from an independent verification or human authority, tied to the frozen
gate hash, from an identity that did not execute the run.

## What Each Command Is For

| Command | Use it when |
|---|---|
| `init`, `freeze` | starting a run that will produce claims someone must trust |
| `run`, `execute` | dispatching work to an agent runtime, or running one command in an isolated worktree |
| `verify` | the trusted path: a verification request id in, a signed attestation out; fails closed without a provisioned trust root |
| `verify-methodology` | NON-AUTHORITATIVE: the P15-P18 ladder over workspace evidence |
| `decide` | issuing the final accept / repair / abstain / human-review |
| `status` | checking run state before assuming anything about it |
| `methodology` | driving the P0-P23 lifecycle and its artifacts (`init`, `transition`, `readiness`, `artifact-*`) |
| `failure` | a bounded repair cycle that preserves evidence (`create` through `resolve`) |
| `research` | recording questions, hypotheses, protocols, experiments, and claim assessments |
| `lifecycle` | release, deployment, incident, and improvement records |
| `memory` | the derived project profile: `build`, `query`, `verify` |
| `learn`, `recall`, `goal`, `context`, `literature`, `autolearn` | gated context learning - see `docs/literature-learning.md` |
| `dashboard` | serving the localhost control plane for runtime status and provider connections |
| `validate` | re-checking the whole workspace: gate hashes, evidence, lesson provenance |

## Reading The Output

The runtime says what its evidence does *not* prove, and those lines are load-bearing:

```text
execution evidence is not authoritative on its own: independent verification is still required
verification evidence is not ACCEPT: only 'nogap decide' can accept
BUILD_COMPLETE_AWAITING_VERIFICATION
```

A command that printed `passed` has not accepted anything. Report what the decision was, not what
the last green line looked like.

## Stale Evidence

Verification evidence is bound to a candidate: task, patch hash, candidate hash, gate hash,
methodology version, and requirement set. Change any of them - a repair producing a new patch, a
re-frozen gate - and the stored result no longer describes the current candidate. The runtime
detects this and blocks resolution; do not work around it by re-running only the parts that pass.

## What Not To Do

- do not edit a frozen gate, delete a test, relax a threshold, or move a baseline to get green
- do not accept your own execution evidence, under any role name
- do not treat `nogap validate` passing as acceptance; it checks integrity, not merit
- do not hand-write evidence files to represent runs that did not happen

## Deeper

- `docs/nogapcode-runtime.md`: architecture, planes, authority model, decision policy
- `docs/literature-learning.md`: the gate external claims must pass before becoming lessons
- `runtime/schemas/`: the record contracts (gate, claim, evidence, decision, run-event, lesson)
- `benchmarks/nogapbench/`: the false-success traps this runtime is measured against
