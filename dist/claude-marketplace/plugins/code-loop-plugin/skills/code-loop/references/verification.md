# Verification

Use this only when the correct check is not obvious.

## Choose the cheapest failing check

Verification must be able to fail. Prefer the smallest check that proves the promised behavior.

| Task | Minimum useful verification |
|---|---|
| Typo/docs | render or inspect changed text |
| Bug fix | failing repro first, then passing test |
| Feature | focused test for main path and one boundary case |
| Refactor | existing tests or behavior parity check |
| API | request/response contract test and bad-input case |
| UI | screenshot/rendered inspection at relevant viewport |
| Accessibility | keyboard path, labels, contrast, focus state |
| Migration | forward, existing data, idempotency, rollback |
| Performance | baseline and after measurement under comparable conditions |
| ML/statistics | baseline metric, split integrity, leakage check |
| Math/physics | units, limiting cases, numeric sanity check |
| Security | hostile input and permission boundary check |
| Innovation | failure signal, baseline comparison, smallest falsifying experiment |

## Bug fix protocol

1. Reproduce the failure.
2. Confirm the reproduction fails for the right reason.
3. Fix the root cause.
4. Re-run the reproduction and relevant nearby checks.

If a failing test is impossible, explain why and use the closest runnable proof.

## UI protocol

Check:

- desktop and mobile framing when layout is responsive
- text fit
- no incoherent overlap
- loading/empty/error states if touched
- interactive elements are reachable and visibly focused

Prefer screenshot or browser inspection over imagination.

## Data migration protocol

Check:

- old rows
- new writes
- mixed old/new state
- idempotency
- rollback
- queries that filter on changed values

Do not treat a code-only diff as sufficient when existing data must change.

## Reporting

Report exact commands or checks run and whether they passed. If not run, say why.

## Innovation protocol

For novel ideas, verification can be a prototype, simulation, derivation, paper/source check,
benchmark, user test, or red-team critique. It must say what result would make the idea weaker or
wrong.
