# NoGapCode Runtime Architecture

NoGapCode is the product direction for Code Loop: a provider-neutral Trust Runtime. The current
`code-loop` package remains the lightweight protocol, skill, and compatibility layer until the
repository and distribution names are intentionally migrated.

## Positioning

NoGapCode is not another coding agent. It runs coding agents, humans, tools, and model providers
under shared gates, evidence provenance, policy, and deterministic decisions.

```text
NoGapCode = no gap between code claims and verified evidence
```

The core value is not multi-agent execution by itself. The core value is preventing false success:
an agent must not pass by deleting tests, relaxing thresholds, changing baselines, hiding failures,
renaming its role, or issuing ACCEPT for its own work.

Primary invariant:

```text
Execution Authority MUST NOT be Acceptance Authority.
```

## Runtime Thesis

The smallest runtime worth building has:

```text
Orchestrator
Implementer adapter
Independent Verifier
Immutable Gate
Evidence artifact
Authority identity
Bounded repair loop
Final decision
```

Anything larger must earn its place through benchmark evidence.

## Benefit Gate

Every addition must answer three questions before implementation:

```text
Need: current requirement or future option?
Benefit: what verified gap does it close?
Tradeoff: what does it cost in code, latency, tokens, attack surface, and maintenance?
```

Build only if the addition improves at least one core outcome without hiding a worse regression:

- reliability: fewer false passes, clearer recovery, less state loss
- security: smaller authority, safer tool use, stronger approval boundary
- accuracy: claims tied to deterministic evidence, fewer unsupported decisions
- speed: fewer steps, less context, faster local validation
- size: fewer files or smaller interfaces for the same behavior
- token cost: less instruction text, fewer handoffs, lower reasoning overhead

Defer future-only value. Durable execution research favors checkpoints, replay, and idempotency,
but those are expensive before local runs prove they need crash recovery. Agent-interface research
shows that smaller, purpose-built interfaces can improve coding-agent performance. Security work on
agentic systems shows that tool misuse, prompt injection, and weak approval gates are real risks, so
new features must reduce authority or strengthen evidence rather than merely add automation.

## Planes

```text
Control / Decision Plane
  deterministic lifecycle, gate policy, risk, escalation, budget, Decision Engine

Execution Plane
  AgentRuntime, execution lifecycle, bounded repair, cancellation, sandbox boundary

Tool / Capability Plane
  ToolProvider, capability metadata, permission boundary

Verification / Evidence Plane
  immutable gates, claims, independent verifier identity, provenance, stale evidence checks

State / Event Plane
  Repository, .code-loop/, append-only events, checkpoints, decisions

Observability Plane
  structured run events, routing decisions, verification and decision summaries
```

## Lifecycle

```text
task intake
-> classify risk
-> freeze gates
-> plan
-> dispatch implementer
-> collect patch
-> verify independently
-> collect evidence
-> check authority separation
-> repair if bounded
-> re-verify
-> decide pass / repair / abstain / human-review
```

## Immutable Gates

A gate is immutable for one run. It can include protected files, forbidden changes, commands,
expected metrics, thresholds, baselines, security rules, and domain invariants.

The implementer may read the gate but must not edit it. Gate edits require a new run or explicit
human approval.

## Evidence

Every important claim should link to evidence. Evidence is stronger when it is deterministic,
reproducible, and tied to a producer identity, authority class, role, commit hash, run id, gate
hash, command output, and artifact path when available.

Authoritative final acceptance requires at least one passing evidence item produced by an
independent verification or human authority for the frozen gate. Executor evidence may be useful,
but it is not authoritative for final ACCEPT.

Evidence should be modeled as edges before adopting a graph database:

```text
Claim C17
  supported-by Evidence E3
  contradicted-by Review R2
  superseded-by Claim C21
```

Start with files or SQLite. Defer graph infrastructure until queries prove it is needed.

## Authority Model

The current runtime uses a deliberately small authority model:

- `execution`: may inspect gates, edit project code, run local checks, and submit claims.
- `verification`: may produce authoritative verification evidence when independent from execution.
- `acceptance`: may issue ACCEPT only when admissible independent evidence exists.
- `human`: may act as verification or acceptance authority when recorded explicitly.
- `tool`: may produce useful non-authoritative evidence unless a policy elevates it later.

Identity is based on `actor_id` when present, falling back to producer fields such as `created_by`.
Role strings are advisory metadata; changing `role` to `verifier` does not bypass an execution
identity conflict.

## Decision Engine

The minimal acceptance policy is:

- all referenced ACCEPT evidence must be passing
- evidence must reference a known frozen gate hash
- at least one referenced item must be authoritative independent verification or human evidence
- the final acceptor must use acceptance or human authority
- the final acceptor cannot be an execution identity for the same run
- failed, blocked, or inconclusive authoritative evidence blocks ACCEPT

When these checks fail, the runtime repairs, abstains, or asks for human review rather than turning
model confidence or local checks into trust.

## Provider Contracts

Provider-neutrality is represented by separate contracts rather than one broad provider interface:

- `ModelProvider`: model metadata and invocation capability
- `AgentRuntime`: execution lifecycle for coding/reasoning clients
- `ToolProvider`: tools and permission/capability metadata
- `AuthProvider`: identity, credential, and account boundary
- `ExecutionBackend`: local, sandboxed, remote, or accelerator-backed execution

Routing decisions are serializable evidence/event metadata: selected provider/runtime/model, reason,
cheap alternatives, cost or quota metadata when known, and policy version. Pricing and model
rankings are adapter/config facts, not immutable gate semantics.

## Context Learning

NoGapCode should learn context as conditional lessons, not as raw memory. A lesson is useful only
when it records:

```text
what was learned
when it applies
which decision/evidence produced it
```

This keeps learning small and prevents stale context from becoming hidden authority. Recall should
filter by tags, decision type, or gate context; if no context matches, the lesson should stay quiet.

The runtime also maintains a small `context.json` profile derived from gates, evidence, decisions,
and lessons. This follows the useful part of agent-memory literature: write experience, manage it
into a compact profile, then read only matching context. It deliberately avoids vector memory until
retrieval needs exceed tags and explicit risk signals.

For external literature, use `docs/literature-learning.md`: NoGapCode may ingest claims from trusted
sources and high-quality GitHub projects, but every claim must pass source quality, benefit, cost,
testability, meaning-quality, and conflict checks before it is even eligible. Promotion to a trusted
lesson also requires acceptance evidence under the normal decision policy. Meaning-quality means the
learned lesson remains accurate to the source, concise enough for recall, and complete enough to
preserve the operational meaning.

Goal-directed autolearning is a bounded loop over available literature claims, not a free-running
belief engine. It should run locally or in GitHub Actions, learn only claims that match the active
goal and pass the existing gates, and submit repository changes through a pull request.

## Failure-First Research Loop

When a nontrivial attempt fails, repair should first inspect prior local evidence, previous lessons,
relevant literature, and similar project failures before blind repeated retries:

```text
Plan -> Retrieve prior evidence/literature -> Execute -> Independently Verify -> Gate
-> Accept / Reject -> Repair -> Learn
```

## Deferred

Do not build these in the first runtime:

- A2A dependency
- distributed scheduler
- Kubernetes workers
- graph database
- vector memory platform
- marketplace
- dozens of agents
- multi-cloud execution
