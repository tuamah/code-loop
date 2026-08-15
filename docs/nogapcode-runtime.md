# NoGapCode Runtime Architecture

NoGapCode is the product direction for Code Loop: a vendor-neutral verified engineering runtime.
The current `code-loop` package remains the lightweight protocol, skill, and compatibility layer
until the repository and distribution names are intentionally migrated.

## Positioning

NoGapCode is not another coding agent. It runs coding agents under shared gates, evidence, policy,
and decisions.

```text
NoGapCode = no gap between code claims and verified evidence
```

The core value is not multi-agent execution by itself. The core value is preventing false success:
an agent must not pass by deleting tests, relaxing thresholds, changing baselines, hiding failures,
or rewriting the definition of done.

## Runtime Thesis

The smallest runtime worth building has:

```text
Orchestrator
Implementer adapter
Independent Verifier
Immutable Gate
Evidence artifact
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
Control Plane
  Council policy, gate policy, budget, escalation, final decision

Execution Plane
  Task lifecycle, provider adapters, tool access, sandbox, retries, cancellation

Evidence Plane
  Claims, tests, traces, reviews, artifacts, provenance, stale evidence checks

State Plane
  Repository, .code-loop/, append-only events, checkpoints, decisions
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
reproducible, and tied to a commit hash, run id, gate hash, and command output.

Evidence should be modeled as edges before adopting a graph database:

```text
Claim C17
  supported-by Evidence E3
  contradicted-by Review R2
  superseded-by Claim C21
```

Start with files or SQLite. Defer graph infrastructure until queries prove it is needed.

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
