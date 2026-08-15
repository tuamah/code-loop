# Risk Matrix

Use this only when blast radius or reversibility is unclear.

## Classify

| Risk | Examples | Required behavior |
|---|---|---|
| Low | local variable, copy tweak, isolated test, small style fix | act fast, verify cheaply |
| Medium | shared helper, user-visible behavior, dependency use, config read | plan briefly, add focused check |
| High | schema, migration, public API, auth, billing, permissions, destructive file operation | plan rollback, verify explicitly, ask before irreversible execution |
| Critical | production data, medical/legal/financial/safety-critical, secrets, deletion at scale | slow down, use authoritative sources or explicit approval, preserve audit trail |

## Confidence check

Confidence is high only when at least one is true:

- existing repo pattern directly matches
- official documentation or source confirms it
- test or reproduction proves it
- standard library/platform behavior is known and stable

Otherwise confidence is low. State the assumption or ask.

## Reversibility

Before high-risk execution, know how to undo:

- code revert
- data rollback
- feature flag
- migration rollback
- backup restore
- user-visible remediation

If rollback is unknown, do not execute irreversible operations.

## Destructive operation gate

Before deleting, overwriting, migrating, charging, publishing, sending, or changing permissions:

1. Identify exact targets.
2. Verify targets are in the intended scope.
3. Prefer dry run or preview.
4. Ask if the operation is irreversible or hard to audit.

## Hidden blast radius signals

Treat as high risk even if the diff is small:

- string values stored in data
- enum changes
- time/date/timezone logic
- caching keys
- permission defaults
- retries and idempotency
- background jobs
- external webhooks
- generated files consumed by other tools
