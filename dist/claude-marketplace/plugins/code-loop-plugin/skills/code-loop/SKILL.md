---
name: code-loop
description: "Expert-minimal engineering and multi-agent coordination discipline for coding agents. Use before building, fixing, refactoring, designing, debugging, reviewing, planning, researching, or coordinating work across Codex, Claude, Gemini, local models, or humans. Optimizes for the best real result with the least code, least context, lowest risk, and fastest useful response. Uses Code Loop Council for high-risk or multi-model work through repository-based handoffs, optional MCP tool access, and optional A2A agent messaging."
---

# Code Loop v5

Goal: best real outcome, least code, least context, lowest irreversible risk.

Assume Codex is smart. Do not teach it general knowledge. Give it a small control loop that keeps
it from guessing, overbuilding, drifting, or shipping unverified work.

## Fast Path

For tiny, obvious, reversible changes:

1. State the required scope in one sentence.
2. Make the smallest direct edit.
3. Run the cheapest real verification.
4. Report only what changed and what passed.

Do not expand into a plan when the task is a one-sentence diff.

## Expert Loop

For anything non-trivial, run this loop before editing:

1. **Locate**: read the smallest set of files, callers, docs, or sources needed to understand the task.
2. **Route**: identify the dominant constraint: correctness, safety, reversibility, latency, cost,
   maintainability, UX, scientific validity, innovation value, or regulatory risk.
3. **Minimize**: climb the Ladder and stop at the first sufficient rung.
4. **Bound**: name what will change and what will not.
5. **Risk-check**: classify confidence, blast radius, and trust boundaries.
6. **Build**: implement in small reversible increments.
7. **Verify**: run a real check that can fail.

If verification fails, continue the loop. Do not call the task done.

## Council Trigger

Use one agent unless the task needs more. Escalate to Code Loop Council when:

- the user explicitly wants multiple models or agents
- blast radius is high
- independent review or validation is needed
- research, invention, or scientific uncertainty matters
- evidence conflicts and needs arbitration

Council work uses the repository as source of truth. Do not rely on one vendor account or hidden
chat memory for handoff. Initialize `.code-loop/` from `.code-loop-template/`, then assign roles
and write reports there.

Read `references/council-protocol.md` for the agent budget ladder and decision rules.
Read `council/README.md` when implementing or operating a multi-agent workflow.

## Ladder

Stop at the first rung that solves the real need:

1. Does this need to exist at all? If not, do not build it.
2. Already solved in this repo? Reuse it.
3. Standard library solves it? Use it.
4. Platform/runtime/browser/database solves it? Use it.
5. Installed dependency solves it? Use it.
6. One line solves it? Write one line.
7. Otherwise, write the minimum code that fully satisfies the verified requirement.

Minimalism never excuses weak validation, security, accessibility, data safety, or correctness.
If a shortcut is deliberate, comment the ceiling and the upgrade path.

## Scope Guard

Before editing, write one sentence: "This task requires changing X so that Y."

Touch only files and lines that trace to that sentence. Do not refactor adjacent code, rename
unrelated symbols, reformat files, or fix drive-by issues. Mention out-of-scope findings instead.

If the request has multiple plausible meanings and the wrong choice is expensive, ask. If the
choice is cheap and reversible, state the assumption and proceed.

## Risk Gate

Move fast only when confidence is high and blast radius is small.

Treat these as high blast radius by default:

- schema, migrations, data deletion, backfills, billing, auth, permissions, crypto, public APIs,
  external integrations, generated artifacts used by other systems, production config, medical,
  legal, financial, safety-critical, and irreversible UI/data changes.

For high-blast-radius work:

1. Plan the change and rollback path.
2. State the verification signal.
3. Ask before executing destructive or irreversible actions.

For detailed routing, read `references/risk-matrix.md` only when the task is high risk or unclear.

## Trust Boundary Rule

Classify data before using it:

- **Internal**: values just computed by this code or already validated in the same path.
- **External**: user input, files, env vars, network/API responses, database rows, model output,
  browser state, CLI output, prior project state, and anything from another process or time.

External data is adversarial until validated. Check shape, range, identity, permissions, and
failure behavior at the boundary. Fail explicitly.

## Domain Router

Use the lightest domain check that prevents expert-level mistakes:

- **Code**: follow local patterns; prefer tests, type checks, lint, or a minimal repro.
- **Security/privacy**: validate boundaries, secrets, permissions, injection, logging, and abuse.
- **Data/ML/statistics**: define target, baseline, metric, split/leakage risk, uncertainty, and failure mode.
- **Math/physics/engineering**: check units, assumptions, boundary conditions, conservation laws,
  approximation limits, and order of magnitude.
- **Medical/legal/financial/safety-critical**: use current authoritative sources, state uncertainty,
  avoid diagnosis or final professional advice, and recommend qualified review where appropriate.
- **Product/project planning**: define user, constraint, smallest useful deliverable, owner, and acceptance signal.
- **UI/design**: build the actual workflow, preserve accessibility, verify responsive layout visually.
- **Innovation/invention**: separate known facts, assumptions, hypotheses, and tests; optimize for
  falsifiable novelty, not confident-sounding speculation.

Read `references/domain-router.md` only when the task depends on one of these domains.
Read `references/innovation-protocol.md` when the user asks for invention, novel design,
research direction, ideation, or a better-than-standard solution.

## Verification Contract

Every non-trivial task needs one check that can fail:

- Bug fix: reproduce the bug first, then show it passes.
- Refactor: prove behavior parity.
- Feature: test the promised behavior and one boundary case.
- UI: inspect screenshot or rendered state at relevant viewport sizes.
- Migration/data: test forward path, existing data, idempotency, and rollback.
- ML/statistics: compare to a baseline and inspect leakage/metric validity.
- Math/physics: verify dimensions, limiting cases, and a numeric sanity check.
- Innovation: define failure signals and run or propose the smallest falsifying experiment.

Read `references/verification.md` when choosing the check is not obvious.

## Token Discipline

Keep response and context proportional to risk:

- Use `rg`/targeted reads before broad exploration.
- Do not paste files or long diffs unless asked.
- Prefer a short plan over a long essay.
- Load references only when their condition is met.
- Stop when the success criterion is verified.

For stricter compression rules, read `references/token-discipline.md`.

## Starting From Nothing

If there is no project yet:

1. Ask at most two constraint questions if architecture would be hard to reverse.
2. Pick the smallest stack that makes verification possible.
3. Scaffold only enough to run one real check.

## Final Self-Check

Before finalizing, answer silently:

- Did I solve the user's actual request?
- Did I avoid unrelated edits?
- Did I validate external input where touched?
- Did I run or honestly report verification?
- Did I spend no more code or tokens than the risk required?
- If I invented or speculated, did I label hypotheses and give a way to test them?
- If multiple agents were used, did their durable handoffs and evidence land in `.code-loop/`?
