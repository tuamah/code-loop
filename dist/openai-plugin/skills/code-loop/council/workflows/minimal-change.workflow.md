# Workflow: Minimal Change

Use for small or medium coding tasks.

1. Orchestrator writes scope and risk class.
2. Scout is skipped unless code context is unclear.
3. Implementer makes the smallest patch.
4. Verifier runs the cheapest real check.
5. Reviewer runs only if shared behavior, public surface, or security is touched.
6. Orchestrator accepts if gates pass.

Default roles:

```text
Orchestrator -> Implementer -> Verifier
optional: Reviewer
```
