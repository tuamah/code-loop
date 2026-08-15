# Literature Learning Gate

NoGapCode may learn from literature and high-quality GitHub projects, but it must not believe them
automatically.

The learning path is:

```text
source -> claim -> benefit gate -> evidence link -> lesson/context -> recall
```

Even after a claim passes the source and benefit gates, the learned lesson must be:

- accurate: faithful to the cited claim, without stronger wording than the source supports
- concise: short enough to be recalled without wasting context
- complete: covers the full operational meaning, not only a catchy fragment

## Trusted Source Priority

1. Standards, security guidance, and official docs: NIST, OWASP, MCP, OpenAI, Anthropic, Temporal,
   LangGraph, and similar primary sources.
2. Peer-reviewed papers, strong arXiv papers, and systematic reviews with clear method and evidence.
3. High-quality GitHub projects with active maintenance, tests, releases, issues, and clear license.
4. Engineering posts only when they cite evidence or reproducible artifacts.

Do not learn automatically from marketing pages, social posts, SEO comparisons, uncited opinions, or
benchmarks without reproducible method.

## Core Questions

Every literature claim must answer:

```text
What exactly is claimed?
What source supports it?
How strong is the evidence?
Does it help NoGapCode now or later?
Does it improve reliability, security, accuracy, speed, size, or token cost?
What complexity or attack surface does it add?
Can it become a test, gate, benchmark, or context lesson?
Is the learned lesson accurate, concise, and complete?
Does it conflict with existing evidence?
Learn, defer, or reject?
```

## Runtime Command

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
  --test "python scripts/nogap.py recall PROJECT --tag context" \
  --accurate --concise --complete

python scripts/nogap.py literature evaluate /path/to/project --id lit-context-0001
python scripts/nogap.py literature learn /path/to/project --id lit-context-0001
python scripts/nogap.py recall /path/to/project --tag context
```

`evaluate` rejects the claim unless source, benefit, testability, evidence strength, and all three
meaning-quality flags pass. `learn` then writes a normal decision-linked lesson, so later runtime
validation and recall use the same path as project-local lessons.

## Goal-Directed Autolearning

Continuous learning starts with one visible goal:

```bash
python scripts/nogap.py goal set /path/to/project \
  --objective "planning ai coding model like codex" \
  --tag planning \
  --tag coding-agent
python scripts/nogap.py autolearn /path/to/project
```

`autolearn` does not browse, invent, or trust new facts by itself. It processes only literature
claims already available in the runtime, checks whether they match the active goal, applies the same
source/benefit/testability/meaning-quality gates, and converts only passing claims into lessons.
Non-matching claims stay deferred; failing claims are rejected.

## What To Learn

Learn patterns that close a verified gap:

- false-success patterns
- verification methods
- security threats and mitigations
- memory/context management patterns
- benchmark designs
- gate/control weaknesses
- agent-runtime architecture constraints

Reject claims that only recommend more agents, more storage, more abstraction, or more automation
without a measurable reliability/security/accuracy/speed/size/token benefit.
