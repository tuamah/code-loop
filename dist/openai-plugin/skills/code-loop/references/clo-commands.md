# CLO Commands

Use these as lightweight chat shortcuts. They are text conventions, not a required platform API.

| Command | Meaning |
|---|---|
| `clo/on` | Apply Code Loop to following work |
| `clo/off` | Stop applying Code Loop unless explicitly invoked |
| `clo/council` | Use Council mode when multi-agent coordination is useful |
| `clo/security` | Run the Security Gate before accepting the work |
| `clo/verify` | Run or define the cheapest real verification |
| `clo/min` | Prefer the least code that preserves verified behavior |

## Security Gate

Trigger automatically when work touches:

- authentication, authorization, sessions, tokens, cookies
- secrets, keys, credentials, environment variables
- user input, file upload, deserialization, parsing
- database queries, shell commands, path handling
- permissions, roles, tenant boundaries, billing, webhooks
- logging, telemetry, PII, data retention, deletion
- public APIs, network calls, production config
- dependencies, package scripts, supply chain, CI/CD

## Required security checks

For touched surfaces only, verify:

1. input validation and output encoding
2. authentication and authorization path
3. least privilege and tenant/user isolation
4. injection surfaces: SQL, shell, path, template, prompt, SSRF, XSS
5. secret handling: no hardcoding, leaking, logging, or broad exposure
6. error behavior: no sensitive data in errors/logs
7. dependency or generated-code trust boundary
8. rollback or containment for high-risk security changes

## Output shape

Keep it short:

```text
Security Gate:
- touched surfaces:
- checks run:
- blocking findings:
- residual risk:
```

If a blocking security finding exists, do not accept the task as done.
