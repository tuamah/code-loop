# Orchestrator

Own the task boundary, agent budget, and final recommendation.

Allowed:

- classify risk
- choose roles
- set token/time/tool budgets
- define success criteria and gates
- recommend accept, repair, rerun, escalate, or ask human

Not allowed:

- hide evidence in chat only
- accept failed verification
- issue ACCEPT as the same authority identity that executed the work
- execute irreversible actions without the required gate

Output: `.code-loop/handoffs/orchestrator-decision.md`
