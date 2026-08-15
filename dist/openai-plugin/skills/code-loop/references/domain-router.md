# Domain Router

Use this only when the task depends on domain judgment beyond ordinary coding.

## Routing rule

Name the domain and the dominant constraint before acting:

- correctness
- safety
- reversibility
- latency
- cost
- maintainability
- UX
- scientific validity
- innovation value
- regulatory or clinical risk

If two constraints conflict, optimize for the one with the highest cost of being wrong.

## Code and architecture

Ask:

- Is this already solved locally?
- What existing pattern owns this behavior?
- What is the smallest public surface change?
- What test proves behavior, not implementation taste?

Avoid new abstractions unless they remove real duplication or isolate a volatile boundary.

## Security and privacy

Check:

- authentication and authorization
- input validation and output encoding
- injection surfaces
- secret handling and logs
- least privilege
- rate limits and abuse paths
- data retention and deletion behavior

Never trade security for minimal code.

## Data, ML, and statistics

Define before building:

- target variable or decision
- baseline
- metric and why it matches the goal
- train/validation/test split
- leakage risks
- uncertainty or confidence interval
- failure mode and monitoring signal

Prefer a simple baseline that can be measured over a complex model that cannot be trusted.

## Math, physics, and engineering

Check:

- units and dimensions
- boundary conditions
- limiting cases
- conservation laws or invariants
- approximation assumptions
- order of magnitude
- numerical stability

If the result violates units, scale, or invariants, the implementation is probably wrong.

## Medical, legal, financial, and safety-critical work

Use current authoritative sources when facts, rules, treatments, prices, or regulations can
change. State uncertainty and do not present model output as final professional advice.

For medical work: do not diagnose; distinguish education from clinical recommendation.

For financial work: avoid certainty about returns; distinguish analysis from advice.

For legal work: flag jurisdiction and date sensitivity.

## Product and project planning

Define:

- user
- job to be done
- hard constraints
- smallest useful deliverable
- owner or handoff point
- acceptance signal
- rollback or exit condition

If the smallest useful deliverable is unclear, ask one focused question.

## Innovation and invention

Create space for new ideas, but keep epistemic labels strict:

- known facts
- assumptions
- hypotheses
- tests that could falsify the idea

Prefer 2-4 meaningfully different candidates over a long brainstorm. Score by expected value,
feasibility, novelty, risk, and verification cost. Choose the cheapest experiment that can kill
or strengthen the idea.

For details, use `references/innovation-protocol.md`.

## UI and design

Build the workflow, not a brochure. Check:

- main task path
- empty, loading, error, and success states
- keyboard and screen-reader accessibility
- responsive layout
- contrast and text fit
- visual verification in at least one relevant viewport
