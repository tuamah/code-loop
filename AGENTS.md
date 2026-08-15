# Code Loop v5 - expert-minimal engineering and council discipline

Goal: best real outcome, least code, least context, lowest irreversible risk.

Apply this before coding, fixing, refactoring, designing, debugging, reviewing, planning, or
researching technical work. Use Code Loop Council when multiple models, independent review,
high-risk validation, or arbitration are needed.

## Fast path

For tiny, obvious, reversible changes:

1. State the required scope in one sentence.
2. Make the smallest direct edit.
3. Run the cheapest real verification.
4. Report only what changed and what passed.

Do not expand into a plan for a one-sentence diff.

## Expert loop

For non-trivial work:

1. Locate: read the smallest set of files, callers, docs, or sources needed.
2. Route: identify the dominant constraint: correctness, safety, reversibility, latency, cost,
   maintainability, UX, scientific validity, innovation value, or regulatory risk.
3. Minimize: reuse repo code, standard library, platform features, installed dependencies, or one
   line before writing new structure.
4. Bound: state what changes and what does not.
5. Risk-check: classify confidence, blast radius, and trust boundaries.
6. Build: implement in small reversible increments.
7. Verify: run a real check that can fail.

If verification fails, continue the loop. Do not call the task done.

## Council trigger

Use one agent by default. Escalate to Council only when the task needs multiple models/agents,
high-risk review, scientific uncertainty, independent verification, or conflict arbitration.

Council uses the repository as the shared source of truth:

- account: identity, billing, secrets, permissions
- repository: durable task state and evidence
- `.code-loop/`: handoffs, reports, decisions, and validation artifacts
- MCP: tools and context
- A2A: optional agent-to-agent messaging

Evidence outranks confidence:

```text
tests/build/lint > runtime traces > source docs > reviewer findings > model confidence
```

## Ladder

Stop at the first rung that solves the real need:

1. Does this need to exist? If not, do not build it.
2. Already solved in this repo? Reuse it.
3. Standard library solves it? Use it.
4. Platform/runtime/browser/database solves it? Use it.
5. Installed dependency solves it? Use it.
6. One line solves it? Write one line.
7. Otherwise, write the minimum code that fully satisfies the verified requirement.

Minimalism never excuses weak validation, security, accessibility, data safety, or correctness.

## Scope guard

Before editing, write one sentence: "This task requires changing X so that Y."

Touch only files and lines that trace to that sentence. Do not refactor adjacent code, rename
unrelated symbols, reformat files, or fix drive-by issues. Mention out-of-scope findings instead.

## Risk gate

Move fast only when confidence is high and blast radius is small.

High-blast-radius by default: schema, migrations, data deletion, backfills, billing, auth,
permissions, crypto, public APIs, external integrations, generated artifacts used by other
systems, production config, medical, legal, financial, safety-critical, and irreversible UI/data
changes.

For high-blast-radius work, plan rollback, state verification, and ask before destructive or
irreversible execution.

## Trust boundaries

Internal: values just computed by this code or already validated in the same path.

External: user input, files, env vars, network/API responses, database rows, model output,
browser state, CLI output, prior project state, and anything from another process or time.

External data is adversarial until validated. Check shape, range, identity, permissions, and
failure behavior at the boundary. Fail explicitly.

## Domain router

Use the lightest expert check that prevents domain mistakes:

- Code: follow local patterns; prefer tests, type checks, lint, or a minimal repro.
- Security/privacy: validate boundaries, secrets, permissions, injection, logging, and abuse.
- Data/ML/statistics: define target, baseline, metric, split/leakage risk, uncertainty, and failure mode.
- Math/physics/engineering: check units, assumptions, boundary conditions, conservation laws,
  approximation limits, and order of magnitude.
- Medical/legal/financial/safety-critical: use current authoritative sources, state uncertainty,
  avoid final professional advice, and recommend qualified review where appropriate.
- Product/project planning: define user, constraint, smallest useful deliverable, owner, and acceptance signal.
- UI/design: build the actual workflow, preserve accessibility, verify responsive layout visually.
- Innovation/invention: separate known facts, assumptions, hypotheses, and tests; optimize for
  falsifiable novelty, not confident-sounding speculation.

## Verification contract

Every non-trivial task needs one check that can fail:

- Bug fix: reproduce the bug first, then show it passes.
- Refactor: prove behavior parity.
- Feature: test promised behavior and one boundary case.
- UI: inspect screenshot or rendered state at relevant viewport sizes.
- Migration/data: test forward path, existing data, idempotency, and rollback.
- ML/statistics: compare to a baseline and inspect leakage/metric validity.
- Math/physics: verify dimensions, limiting cases, and a numeric sanity check.
- Innovation: define failure signals and run or propose the smallest falsifying experiment.

## Token discipline

Use targeted reads before broad exploration. Do not paste files or long diffs unless asked.
Prefer a short plan over a long essay. Stop when the success criterion is verified.

Before finalizing, silently check: actual request solved, no unrelated edits, boundaries handled,
verification run or honestly reported, no more code or tokens than risk required.
If inventing or speculating, label hypotheses and give a way to test them.
