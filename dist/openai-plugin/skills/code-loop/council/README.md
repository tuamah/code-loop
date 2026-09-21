# Code Loop Council

Code Loop Council is the v5 coordination layer for multi-model software work. It is above or beside
the NoGapCode Trust Runtime; it is not the acceptance root of trust.

It is vendor-neutral: Codex, Claude Code, Gemini, Cursor, local models, and humans can participate
because the repository stores task state, reports, evidence, and decisions.

## Architecture

```text
User accounts      -> identity, billing, secrets, permissions
Project repo       -> shared source of truth
.code-loop/        -> task state, handoffs, evidence, decisions
MCP                -> tools and project context
A2A                -> optional agent-to-agent transport
NoGapCode runtime  -> immutable gates, evidence provenance, acceptance policy
Code Loop Council  -> roles, routing, and coordination policy
```

## Levels

| Level | Name | How it works |
|---|---|---|
| 1 | Manual universal | User runs each tool; agents communicate through `.code-loop/` files |
| 2 | Local orchestrator | A local CLI dispatches Codex/Claude/Gemini/API calls using user-owned credentials |
| 3 | A2A adapters | Agents exchange tasks directly when A2A support exists |

v5 is built for Level 1 now and keeps the file formats stable for Level 2 and Level 3.

## Roles

- `Orchestrator`: owns scope, budget, routing, and final recommendation.
- `Scout`: read-only exploration and research.
- `Planner`: turns the request into gates and success criteria.
- `Implementer`: writes the smallest patch.
- `Verifier`: runs checks and records evidence.
- `Reviewer`: reviews diff for bugs, scope, security, and regressions.
- `Skeptic`: attacks speculative ideas and defines falsification.
- `Repairer`: fixes only accepted findings.
- `Arbiter`: resolves conflicts by evidence, not confidence.

Each role is detailed in `council/roles/`.

Role names do not prove independence. Acceptance depends on recorded authority identity:
`execution`, `verification`, `acceptance`, or `human`.

## Source of truth

Copy `.code-loop-template/` into a project as `.code-loop/`.

Agents must not rely on hidden chat memory for handoff. Durable artifacts win.

## Decision ladder

```text
if required checks fail:
  reject or repair
elif scope was violated:
  repair
elif high risk and rollback/human approval is missing:
  pause
elif independent authoritative verification passes and acceptor is not execution identity:
  recommend accept
else:
  ask Arbiter to choose repair, rerun, or human decision
```

The runtime rejects ACCEPT when the same authority identity implemented and accepted the work, when
the only passing evidence came from execution authority, or when authoritative evidence conflicts.

## Adapter policy

Adapters are optional. A tool can participate if it can:

1. read `.code-loop/task.yaml` and `.code-loop/plan.md`
2. write one bounded report to `.code-loop/handoffs/`
3. attach evidence or exact commands when it validates anything
4. avoid writing outside its assigned role

MCP adapters provide tools/context. A2A adapters provide agent-to-agent messaging. The repo remains
the audit log even when A2A is available.
