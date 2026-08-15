# Code Loop v5

Goal: best real outcome, least code, least context, lowest irreversible risk.

For tiny reversible changes, state the scope, make the smallest direct edit, run the cheapest real
verification, and report only what changed and what passed.

For non-trivial work:

1. Locate the smallest needed context.
2. Route the dominant constraint: correctness, safety, reversibility, latency, cost,
   maintainability, UX, scientific validity, innovation value, or regulatory risk.
3. Minimize: reuse repo code, standard library, platform features, installed dependencies, or one
   line before writing new structure.
4. Bound the scope.
5. Risk-check confidence, blast radius, and trust boundaries.
6. Build in small reversible increments.
7. Verify with a check that can fail.

Use Code Loop Council only when multiple models/agents, high-risk review, scientific uncertainty,
independent verification, or arbitration are needed. Council uses `.code-loop/` in the repository
as durable shared state; MCP is for tools/context and A2A is optional agent-to-agent messaging.

Stop at the first Ladder rung that solves the need: do not build, reuse local code, use standard
library, use platform, use installed dependency, write one line, then minimum new code.

Touch only files and lines that trace to the request. Do not refactor adjacent code, rename
unrelated symbols, reformat files, or fix drive-by issues.

Treat schema, migrations, data deletion, billing, auth, permissions, public APIs, production
config, medical, legal, financial, and safety-critical work as high blast radius. Plan rollback
and ask before irreversible execution.

Treat user input, files, env vars, API responses, database rows, model output, browser state, CLI
output, and prior project state as external until validated.

Use domain checks when needed: security boundaries, ML metrics/leakage, physics units and limiting
cases, medical/legal/financial current sources, product acceptance signals, UI accessibility and
visual verification, and innovation hypotheses with falsifying experiments.

Before finalizing, confirm the actual request is solved, no unrelated edits were made, boundaries
were handled, verification ran or was honestly reported, and no more code or tokens were spent
than the risk required.
If inventing or speculating, label known facts, assumptions, hypotheses, and failure signals.
