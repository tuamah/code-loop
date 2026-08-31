# code-loop v5

Expert-minimal discipline and coordination protocol for coding agents: best real result, least
code, least tokens, lowest risk.

**NoGapCode is a provider-neutral Trust Runtime, not another coding agent.** It keeps execution
authority separate from acceptance authority so an agent cannot make its own work trusted merely by
producing a passing result or issuing ACCEPT. The repository and package remain `code-loop` as the
compatibility layer while the runtime contracts mature.

The future product/repository name may become `nogabcode`; package and import names stay stable
until a compatibility-preserving migration is explicit.

`code-loop` has two layers:

1. **Code Loop Core**: a lightweight single-agent discipline for building, fixing, reviewing, and
   verifying software work.
2. **Code Loop Council**: a vendor-neutral coordination protocol for multi-model software teams
   using Codex, Claude Code, Gemini, Cursor, local models, and humans.

The core rule: do not connect agents through one vendor account. Use the repository as the shared
source of truth, MCP for tools/context, and A2A only where available for agent-to-agent messaging.

## What It Does

`code-loop` helps agents:

- avoid overbuilding
- stay inside the requested scope
- distinguish local edits from high-risk changes
- treat external data as a trust boundary
- verify before claiming completion
- create room for invention without hallucination
- coordinate multiple models through durable handoffs
- use short `clo/` commands such as `clo/on`, `clo/security`, and `clo/council`
- load expert-domain depth only when needed

## Why v5

v4 was an expert-minimal skill for one agent. v5 keeps that core and adds a council protocol for
users who work with multiple AI coding tools.

| Layer | Purpose |
|---|---|
| `SKILL.md` | Fast core plus Council trigger rules |
| `AGENTS.md` | Drop-in instructions for Codex and other AGENTS.md-aware agents |
| `references/` | Optional depth loaded only when the task needs it |
| `council/` | Roles, schemas, workflows, and decision protocol |
| `runtime/` | Early NoGapCode runtime contracts for gates, claims, evidence, and events |
| `docs/` | Architecture notes for the future verified engineering runtime |
| `.code-loop-template/` | Project-local shared state template |
| `scripts/` | Instruction and Council validation helpers |
| `dist/` | Packaged OpenAI/Codex plugin and Claude Code marketplace |

## Repository Layout

```text
code-loop/
├── SKILL.md
├── AGENTS.md
├── README.md
├── LICENSE
├── agents/openai.yaml
├── references/
│   ├── council-protocol.md
│   ├── clo-commands.md
│   ├── domain-router.md
│   ├── innovation-protocol.md
│   ├── risk-matrix.md
│   ├── verification.md
│   └── token-discipline.md
├── council/
│   ├── roles/
│   ├── schemas/
│   └── workflows/
├── runtime/schemas/
├── docs/
├── .code-loop-template/
├── scripts/
├── dist/
├── .cursor/rules/code-loop.md
├── .windsurf/rules/code-loop.md
└── .clinerules/code-loop.md
```

## The Multi-Model Connection Model

For a user who has Codex, Claude Code, Gemini, and local models:

```text
User accounts      -> identity, billing, secrets, permissions
Project repository -> shared source of truth
.code-loop/        -> task state, handoffs, reports, evidence, decisions
MCP                -> tool and context access
A2A                -> optional direct agent-to-agent messaging
```

This makes `code-loop` usable by everyone, not only by one account or one platform.

## Council Levels

| Level | Name | Status |
|---|---|---|
| 1 | Manual universal | Works now: user runs each tool; agents exchange `.code-loop/` files |
| 2 | Local orchestrator | Future CLI dispatches tools using user-owned credentials |
| 3 | A2A adapters | Future adapters use A2A where vendors support it |

v5 ships Level 1 and stable file formats for Levels 2 and 3.

## Agent Budget Ladder

Use the fewest agents that can safely solve the task:

1. One agent for small, reversible work.
2. Add Scout for unfamiliar code or research.
3. Add Verifier when there is real execution, data, UI, or migration risk.
4. Add Reviewer for shared behavior, security, APIs, or user-visible changes.
5. Add Arbiter only when evidence conflicts or blast radius is high.
6. Add Skeptic for invention, science, or speculative architecture.

## CLO Commands

`clo/` commands are lightweight chat shortcuts:

| Command | Meaning |
|---|---|
| `clo/on` | Apply Code Loop |
| `clo/off` | Stop applying Code Loop unless explicitly invoked |
| `clo/council` | Use Council mode when useful |
| `clo/security` | Run the Security Gate |
| `clo/verify` | Run or define the cheapest real verification |
| `clo/min` | Prefer the least code that preserves verified behavior |

The Security Gate triggers automatically when work touches auth, secrets, user input, parsing,
database queries, shell commands, path handling, permissions, PII, network calls, production config,
dependencies, package scripts, supply chain, or CI/CD.

## Council Roles

- `Orchestrator`: scope, budget, routing, and final recommendation.
- `Scout`: read-only exploration and research.
- `Planner`: gates, success criteria, rollback path.
- `Implementer`: smallest patch.
- `Verifier`: tests, builds, traces, screenshots, benchmarks.
- `Reviewer`: correctness, scope, security, regressions.
- `Skeptic`: falsification for invention and scientific uncertainty.
- `Repairer`: fixes accepted findings only.
- `Arbiter`: resolves conflicts by evidence, not confidence.

## Trust Runtime Rule

Evidence outranks confidence:

```text
tests/build/lint > runtime traces > source docs > reviewer findings > model confidence
```

Execution authority can inspect gates, edit code, run local checks, and submit claims/artifacts.
Acceptance authority decides whether evidence is admissible. A final ACCEPT requires independent
authoritative verification evidence tied to the frozen gate hash, and the acceptor cannot be the
execution identity for the same run.

Low risk: Orchestrator may recommend acceptance after admissible verification.

Medium risk: accept after Verifier passes and Reviewer has no blocking finding.

High risk: Arbiter recommends; human approves.

Council coordinates roles and policy; it is not the acceptance root of trust.

## Install

### Codex or Any AGENTS.md-Aware Agent

```bash
cp AGENTS.md /path/to/project/AGENTS.md
```

Safe installer that never replaces existing project instructions:

```bash
python scripts/install-project.py /path/to/project
```

If the project already has `AGENTS.md` or `CLAUDE.md`, the installer appends a small Code Loop
Bridge instead of overwriting the file. If neither exists, it creates `AGENTS.md` from Code Loop.

### Initialize Council State in a Project

```bash
python scripts/init-council.py /path/to/project
python scripts/validate-council.py /path/to/project/.code-loop
```

### Initialize NoGapCode Runtime State

```bash
python scripts/nogap.py init /path/to/project --objective "Fix the bug without changing the gate"
python scripts/nogap.py freeze /path/to/project
python scripts/nogap.py validate /path/to/project
python scripts/nogap.py decide /path/to/project --actor-id acceptor-1
python scripts/nogap.py learn /path/to/project --tag gate --text "Freeze the gate before trusting evidence."
python scripts/nogap.py recall /path/to/project --tag gate
python scripts/nogap.py context /path/to/project --show
```

The visual runtime dashboard prototype is available at `dashboard/index.html`.
Run it against a real project runtime with:

```bash
python scripts/nogap.py dashboard /path/to/project
```

The Dashboard also exposes a backend-backed `Settings / Connections` view:

- `GET /api/connections` returns sanitized provider, model, and AgentRuntime status.
- `POST /api/connections/openrouter/connect` starts local OpenRouter OAuth PKCE login in the
  system browser, then stores the returned key in the OS credential store.
- `POST /api/connections/openrouter` stores the OpenRouter key in the OS credential store on
  Windows and never writes it to runtime JSON, localStorage, or event logs.
- `POST /api/connections/openrouter/test` performs a real authenticated model-discovery probe.
- `POST /api/connections/codex/test` probes the official local Codex CLI login and doctor output.
- `POST /api/connections/claude/test` reports the Claude Code CLI status without copying tokens.

Provider, model, and AgentRuntime are separate concepts. The current build routing is: Terra plans,
5.4 executes, and Sol judges. That is a construction-time policy, not acceptance authority.

The runtime is intentionally local-first and server-ready. A frozen gate is hash-locked for the run;
evidence that claims to prove work must reference the frozen gate hash. Authoritative evidence
records producer identity, authority class, role, and provenance. Lessons are scoped, tagged, and
evidence-linked. The context profile is rebuilt from gates, evidence, decisions, and lessons so the
runtime learns from use without trusting raw memory.

For literature learning, add a claim, evaluate it, then learn only if it passes source, benefit,
testability, evidence-strength, and meaning-quality gates:

```bash
python scripts/nogap.py literature add /path/to/project \
  --id lit-context-0001 \
  --title "NoGapCode runtime docs" \
  --url docs/nogapcode-runtime.md \
  --source-type official-doc \
  --claim "Useful context learning should be conditional, evidence-linked, and recalled only when matching tags apply." \
  --lesson "Learn conditional, evidence-linked lessons; recall them only by matching tags." \
  --tag context \
  --benefit accuracy \
  --benefit token-cost \
  --evidence-strength primary \
  --acceptance-evidence evidence-literature \
  --test "python scripts/nogap.py recall PROJECT --tag context" \
  --accurate --concise --complete
python scripts/nogap.py literature evaluate /path/to/project --id lit-context-0001
python scripts/nogap.py literature learn /path/to/project --id lit-context-0001
```

Literature claims can pass source/meaning checks before they are trusted, but promotion to a lesson
requires acceptance evidence under the same decision policy.

For continuous repository learning, set one active goal and let `autolearn` process only the
available gated literature claims that match it:

```bash
python scripts/nogap.py goal set /path/to/project \
  --objective "planning ai coding model like codex" \
  --tag planning \
  --tag coding-agent
python scripts/nogap.py autolearn /path/to/project
python scripts/nogap.py recall /path/to/project --tag coding-agent
```

The repository also includes `.github/workflows/autolearn.yml`. Run it manually with an objective
or let the weekly schedule process existing runtime literature. It opens a pull request when
learning changes are produced; it does not merge automatic learning directly into `main`.

### Codex / ChatGPT Plugin

The packaged plugin lives at:

```text
dist/openai-plugin/
```

Main manifest:

```text
dist/openai-plugin/.codex-plugin/plugin.json
```

### Claude Code Plugin Marketplace

The packaged Claude marketplace lives at:

```text
dist/claude-marketplace/
```

From GitHub:

```text
/plugin marketplace add tuamah/code-loop
/plugin install code-loop-plugin@code-loop-marketplace
```

Or locally:

```text
/plugin marketplace add ./dist/claude-marketplace
/plugin install code-loop-plugin@code-loop-marketplace
```

### Claude Code Skill

Project-local:

```bash
mkdir -p /path/to/project/.claude/skills/code-loop
cp -r SKILL.md references scripts council .code-loop-template /path/to/project/.claude/skills/code-loop/
```

Global:

```bash
mkdir -p ~/.claude/skills/code-loop
cp -r SKILL.md references scripts council .code-loop-template ~/.claude/skills/code-loop/
```

### Cursor / Windsurf / Cline

```bash
cp .cursor/rules/code-loop.md /path/to/project/.cursor/rules/code-loop.md
cp .windsurf/rules/code-loop.md /path/to/project/.windsurf/rules/code-loop.md
cp .clinerules/code-loop.md /path/to/project/.clinerules/code-loop.md
```

## Scientific Innovation Without Hallucination

For invention, research direction, or novel design, v5 uses:

```text
Target:
Known:
Assumptions:
Candidates:
Best experiment:
Failure signals:
Next step:
```

Creativity is welcome. Unlabeled speculation is not.

## Provider-Neutral Contracts

The runtime keeps provider concepts separate: `ModelProvider`, `AgentRuntime`, `ToolProvider`,
`AuthProvider`, and `ExecutionBackend` are distinct contracts. Routing decisions are serializable
metadata with selected provider/runtime/model, reason, cheap alternatives, quota/cost metadata when
known, and policy version. Commercial facts such as pricing or model rankings belong in adapters or
config, not immutable gate meaning.

The default local routing policy is recorded in `runtime/config/model-router.policy.json`:
`gpt-5.6-terra` plans, `gpt-5.4` implements, and `gpt-5.6-sol` judges.

## Deferred Runtime Work

NoGapCode deliberately defers distributed workers, Kubernetes, graph databases, vector-memory
platforms, mandatory A2A, automatic merge of learned lessons, and multi-cloud GPU control planes
until tests or benchmarks prove they close a real trust gap.

The intended product extension path is:

1. CLI plus localhost Dashboard.
2. Tauri installer that wraps the same Dashboard and starts the same local Runtime.
3. Optional server mode for remote access with authentication.

## Validate

```bash
python scripts/lint-instructions.py
python scripts/install-project.py /tmp/demo-project
python scripts/validate-council.py .code-loop-template
python -m unittest discover -s tests
python -m unittest discover -s benchmarks
python ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py dist/openai-plugin
```

## Release Notes

`code-loop.zip` is generated from the current v5 source tree. After changing the package, rerun
validation and regenerate the archive without nesting old archives inside it.

### 5.1.0

- Adds the NoGapCode runtime MVP contracts and scripts.
- Adds immutable gate hashing, runtime validation, and evidence-based decisions.
- Keeps `code-loop` as the protocol and compatibility package while NoGapCode matures.

## License

MIT.
