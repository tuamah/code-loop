# Workflow: Minimal Change

Use for small or medium coding tasks.

1. Orchestrator writes scope and risk class.
2. Scout is skipped unless code context is unclear.
3. Implementer makes the smallest patch.
4. Verifier runs the cheapest real check.
5. Reviewer runs only if shared behavior, public surface, or security is touched.
6. Orchestrator records an accept recommendation only if gates pass and acceptance authority is independent.

Default roles:

```text
Orchestrator -> Implementer -> Verifier
optional: Reviewer
```
