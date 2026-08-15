# code-loop v5

Expert-minimal discipline and coordination protocol for coding agents: best real result, least
code, least tokens, lowest risk.

**NoGapCode** is the product direction for the future runtime: no gap between code claims and
verified evidence. The repository and package remain `code-loop` while the runtime contracts mature.

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

## Decision Rule

Evidence outranks confidence:

```text
tests/build/lint > runtime traces > source docs > reviewer findings > model confidence
```

Low risk: Orchestrator may accept after verification.

Medium risk: accept after Verifier passes and Reviewer has no blocking finding.

High risk: Arbiter recommends; human approves.

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
python scripts/nogap.py decide /path/to/project
python scripts/nogap.py learn /path/to/project --tag gate --text "Freeze the gate before trusting evidence."
python scripts/nogap.py recall /path/to/project --tag gate
python scripts/nogap.py context /path/to/project --show
```

The runtime is intentionally local-first. A frozen gate is hash-locked for the run; evidence that
claims to prove work must reference the frozen gate hash. Lessons are scoped, tagged, and
evidence-linked. The context profile is rebuilt from gates, evidence, decisions, and lessons so the
runtime learns from use without trusting raw memory.

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
