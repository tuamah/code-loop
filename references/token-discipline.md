# Token Discipline

Use this only when the task is broad, context-heavy, or likely to trigger over-explanation.

## Context budget

Read in this order:

1. Project instructions.
2. File tree.
3. Directly touched files.
4. Callers/tests for touched behavior.
5. Domain references only when needed.

Avoid loading generated directories, dependency folders, build output, large snapshots, and logs
unless the task is specifically about them.

## Response budget

Default final answer:

- what changed
- how it was verified
- any important limitation

Avoid restating code, narrating every command, or explaining generic engineering principles.

## Planning budget

Use a plan only when it prevents wrong work. Keep it to checkable steps. For small edits, a scope
sentence plus verification is enough.

## Research budget

Search only when the fact is unstable, high stakes, niche, or explicitly requested. Prefer primary
sources. Summarize findings, do not paste long excerpts.

For ideation, generate fewer but sharper candidates. Do not spend tokens making every idea sound
equally good; rank them and pick the cheapest falsifying experiment.

## Code budget

Prefer deletion over addition when behavior stays correct. Prefer local code over new global
abstraction. Prefer a platform feature over a dependency. Prefer a dependency already installed
over adding a new one.
