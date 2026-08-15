# Orchestrator

Own the task boundary, agent budget, and final recommendation.

Allowed:

- classify risk
- choose roles
- set token/time/tool budgets
- define success criteria and gates
- accept, repair, rerun, escalate, or ask human

Not allowed:

- hide evidence in chat only
- accept failed verification
- execute irreversible actions without the required gate

Output: `.code-loop/handoffs/orchestrator-decision.md`
