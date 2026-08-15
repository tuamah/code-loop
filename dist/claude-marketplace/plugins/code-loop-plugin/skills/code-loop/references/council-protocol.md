# Council Protocol

Use this when one model is not enough: multi-model work, high-risk changes, independent review,
research/invention, or tasks where Codex, Claude, Gemini, local models, and humans may collaborate.

## Principle

Do not connect agents through a vendor account. Use the repository as the shared source of truth.

```text
account = identity, billing, secrets, permissions
repository = durable task state and evidence
MCP = tools and context
A2A = optional agent-to-agent messaging
```

Code Loop must be A2A-ready, not A2A-dependent.

## Agent Budget Ladder

Use the fewest agents that can safely solve the task:

1. One agent for small, reversible work.
2. Add Scout for unfamiliar code or research.
3. Add Verifier when there is real execution, data, UI, or migration risk.
4. Add Reviewer for shared behavior, security, APIs, or user-visible changes.
5. Add Arbiter only when evidence conflicts or blast radius is high.
6. Add Skeptic for invention, science, or speculative architecture.

## Source of truth

For a user project, create `.code-loop/` from `.code-loop-template/`.

Every agent reads the same task files and writes bounded reports:

- `task.yaml`: objective, constraints, budget, risk class
- `plan.md`: current plan and gates
- `handoffs/*.md`: reports from agents
- `evidence/*`: test output, traces, screenshots, benchmarks
- `state.json`: current phase and decision status

## Decision rule

Evidence outranks confidence:

```text
tests/build/lint > runtime traces > source docs > reviewer findings > model confidence
```

Low risk: Orchestrator may accept after verification.

Medium risk: accept after Verifier passes and Reviewer has no blocking finding.

High risk: Arbiter recommends; human approves.

If evidence conflicts, repair or rerun before accepting.

## More detail

Read `council/README.md` for roles, workflows, schemas, and adapters.
