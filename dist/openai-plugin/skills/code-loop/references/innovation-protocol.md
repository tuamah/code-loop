# Innovation Protocol

Use this when the user asks for invention, ideation, research direction, novel architecture,
scientific design, product concept, algorithm design, or a better-than-standard solution.

## Prime directive

Create room for novelty without pretending uncertainty is fact.

Separate every output into:

- **Known**: grounded in existing code, data, sources, laws, measurements, or standard theory.
- **Assumed**: necessary assumptions that are not yet verified.
- **Hypothesized**: plausible new ideas that may be wrong.
- **Testable**: experiments, prototypes, simulations, or checks that can falsify the idea.

Never present a hypothesis as established truth.

## Creative loop

1. Define the target outcome and hard constraints.
2. Identify first principles, invariants, and known limits.
3. Generate 2-4 candidate ideas that differ meaningfully.
4. Score candidates by expected value, feasibility, novelty, risk, and verification cost.
5. Select the cheapest promising experiment.
6. Build the smallest prototype or analysis that can disprove it.
7. Report what survived, what failed, and what remains unknown.

## Scientific guardrails

For each non-obvious claim, attach one of:

- source or local evidence
- derivation
- dimensional/unit check
- empirical measurement
- simulation result
- analogy explicitly labeled as analogy
- assumption explicitly labeled as assumption

If none applies, call it speculation and reduce confidence.

## Anti-hallucination checks

Before proposing a novel solution, ask:

- What would make this false?
- Which constraint dominates?
- Does it violate known physics, math, security, UX, or business constraints?
- Is there a simpler baseline?
- What existing solution must it beat?
- What is the smallest experiment that can invalidate it?

## Invention output shape

Use this compact structure:

```text
Target:
Known:
Assumptions:
Candidates:
Best experiment:
Failure signals:
Next step:
```

Keep candidate descriptions short. Let evidence expand only after a candidate survives.

## When to search

Search or use authoritative sources when:

- the domain is high stakes
- the facts may have changed
- the idea depends on state of the art
- the user asks for best/latest
- prior art or patent-like novelty matters

Prefer primary sources, official docs, papers, standards, and measured project data.

## Engineering invention

For novel code or architecture:

- define the baseline implementation
- isolate the experiment behind a small interface
- keep rollback cheap
- measure one success metric
- avoid global abstractions until the experiment works twice

## Scientific invention

For physics, math, ML, or experimental design:

- state equations or governing principles
- check units and limiting cases
- define measurement noise and uncertainty
- compare against a simple baseline model
- avoid claiming causality without an identification strategy

## Product invention

For product ideas:

- define the user and painful job
- state the non-obvious insight
- identify the smallest useful artifact
- define a behavior-based success signal
- avoid vanity metrics as proof
