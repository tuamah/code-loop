# Workflow: High-Risk Change

Use for migrations, auth, billing, public APIs, destructive operations, production config, or
safety-critical work.

1. Orchestrator classifies risk and requires rollback.
2. Scout maps affected systems and existing data/contracts.
3. Planner defines gates and human approval points.
4. Implementer changes only the accepted scope.
5. Verifier tests forward path, rollback, existing data, and boundary cases.
6. Reviewer inspects for regressions and missed blast radius.
7. Arbiter decides accept, repair, rerun, or human approval.

Default roles:

```text
Orchestrator -> Scout -> Planner -> Implementer -> Verifier -> Reviewer -> Arbiter
```
