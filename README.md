# code-loop v4

[العربية](README.ar.md)

Expert-minimal discipline for coding agents: best real result, least code, least tokens, lowest risk.

`code-loop` is not a giant prompt full of domain facts. It is a small decision system that helps
coding agents know when to move fast, when to slow down, when to research, when to verify, and
when not to write code at all.

## What It Does

`code-loop` helps an agent:

- avoid overbuilding
- stay inside the requested scope
- distinguish local edits from high-risk changes
- treat external data as a trust boundary
- verify before claiming completion
- create room for invention without hallucination
- load expert-domain depth only when needed: security, ML/statistics, physics, medicine, design, planning

## Why v4

v3 was a five-question engineering loop. v4 turns it into a lighter, sharper system:

| Layer | Purpose |
|---|---|
| `SKILL.md` | Fast core: Fast Path, Expert Loop, Ladder, Risk Gate, Domain Router |
| `AGENTS.md` | Drop-in instructions for Codex and other AGENTS.md-aware agents |
| `references/` | Optional depth loaded only when the task needs it |
| `scripts/lint-instructions.py` | Instruction hygiene checks to prevent bloat and weak rules |
| `dist/` | Packaged OpenAI/Codex plugin and Claude Code marketplace |

## Repository Layout

```text
code-loop/
├── SKILL.md
├── AGENTS.md
├── README.md
├── README.ar.md
├── LICENSE
├── agents/openai.yaml
├── references/
│   ├── domain-router.md
│   ├── innovation-protocol.md
│   ├── risk-matrix.md
│   ├── verification.md
│   └── token-discipline.md
├── scripts/
│   └── lint-instructions.py
├── dist/
│   ├── openai-plugin/
│   └── claude-marketplace/
├── .cursor/rules/code-loop.md
├── .windsurf/rules/code-loop.md
└── .clinerules/code-loop.md
```

## Install

### Codex or Any AGENTS.md-Aware Agent

```bash
cp AGENTS.md /path/to/project/AGENTS.md
```

### Codex / ChatGPT Plugin

The packaged plugin lives at:

```text
dist/openai-plugin/
```

Main manifest:

```text
dist/openai-plugin/.codex-plugin/plugin.json
```

Use it through a local marketplace during development, or submit/package it through the OpenAI
plugin publishing flow.

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

Or locally from this repository:

```text
/plugin marketplace add ./dist/claude-marketplace
/plugin install code-loop-plugin@code-loop-marketplace
```

### Claude Code Skill

Project-local:

```bash
mkdir -p /path/to/project/.claude/skills/code-loop
cp -r SKILL.md references scripts /path/to/project/.claude/skills/code-loop/
```

Global:

```bash
mkdir -p ~/.claude/skills/code-loop
cp -r SKILL.md references scripts ~/.claude/skills/code-loop/
```

### Cursor / Windsurf / Cline

Copy the matching rules file:

```bash
cp .cursor/rules/code-loop.md /path/to/project/.cursor/rules/code-loop.md
cp .windsurf/rules/code-loop.md /path/to/project/.windsurf/rules/code-loop.md
cp .clinerules/code-loop.md /path/to/project/.clinerules/code-loop.md
```

## Core Philosophy

1. Read the smallest context that is enough.
2. Reuse what exists before writing new code.
3. Write the least code that produces a verified result.
4. Do not expand scope.
5. Risk-check before execution.
6. For invention: separate known facts, assumptions, and hypotheses.
7. Verify with a check that can fail.
8. Spend no more words or code than the risk requires.

## Scientific Innovation Without Hallucination

When the user asks for invention, research direction, or a novel design, v4 uses a compact
scientific protocol:

```text
Target:
Known:
Assumptions:
Candidates:
Best experiment:
Failure signals:
Next step:
```

This lets the agent be creative without selling speculation as fact. See
`references/innovation-protocol.md`.

## Expert Domains

v4 does not pretend the agent is always a doctor, physicist, statistician, designer, and project
lead at once. It routes the task to the right expert checks only when needed:

- medical/legal/financial: use current authoritative sources and state uncertainty
- ML/statistics: define target, baseline, metric, leakage, uncertainty
- physics/engineering: check units, boundaries, approximations, and order of magnitude
- security: check permissions, secrets, injection, logging, and abuse paths
- design: build the actual workflow and verify visually
- innovation: generate 2-4 distinct candidates, pick the cheapest test, define failure signals

## Validate

```bash
python scripts/lint-instructions.py
python ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py dist/openai-plugin
```

The hygiene check verifies that:

- required reference files exist
- `SKILL.md` and `AGENTS.md` stay lightweight
- weak instruction patterns and cache artifacts are absent
- the core skill links to required references

## Release Notes

`code-loop.zip` is generated from the current v4 source tree. After changing the package, rerun
validation and regenerate the archive without nesting old archives inside it.

## License

MIT.
