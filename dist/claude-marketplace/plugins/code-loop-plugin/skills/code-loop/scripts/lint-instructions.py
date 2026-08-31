#!/usr/bin/env python3
"""Small instruction hygiene checks for code-loop."""

from __future__ import annotations

import re
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_FILES = [
    ROOT / "SKILL.md",
    ROOT / "AGENTS.md",
    ROOT / "README.md",
    ROOT / "agents" / "openai.yaml",
    ROOT / "dashboard" / "index.html",
    *sorted((ROOT / "references").glob("*.md")),
    *sorted((ROOT / "council" / "roles").glob("*.md")),
    *sorted((ROOT / "council" / "workflows").glob("*.md")),
]

MAX_SKILL_LINES = 190
MAX_AGENTS_LINES = 150
BAN_PATTERNS = {
    "pycache mention": re.compile(r"__pycache__|\.pyc\b"),
    "vague quality command": re.compile(r"\b(write|make|produce) (clean|good|best) code\b", re.I),
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def main() -> None:
    missing = [str(path.relative_to(ROOT)) for path in TEXT_FILES if not path.exists()]
    if missing:
        fail("missing files: " + ", ".join(missing))
    if (ROOT / "README.ar.md").exists():
        fail("README.ar.md should not exist; public package is English-only")

    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    if not skill.startswith("---\nname: code-loop\n"):
        fail("SKILL.md must start with code-loop YAML frontmatter")
    openai_yaml = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
    if "$code-loop" not in openai_yaml:
        fail("agents/openai.yaml default_prompt must mention $code-loop")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if "README.ar.md" in readme or "العربية" in readme:
        fail("README.md must be English-only")

    line_counts = {
        "SKILL.md": len(skill.splitlines()),
        "AGENTS.md": len((ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines()),
    }
    if line_counts["SKILL.md"] > MAX_SKILL_LINES:
        fail(f"SKILL.md too long: {line_counts['SKILL.md']} > {MAX_SKILL_LINES}")
    if line_counts["AGENTS.md"] > MAX_AGENTS_LINES:
        fail(f"AGENTS.md too long: {line_counts['AGENTS.md']} > {MAX_AGENTS_LINES}")

    for path in TEXT_FILES:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for label, pattern in BAN_PATTERNS.items():
            if pattern.search(text):
                fail(f"{rel} contains banned pattern: {label}")

    required_refs = [
        "references/clo-commands.md",
        "references/council-protocol.md",
        "references/domain-router.md",
        "references/innovation-protocol.md",
        "references/risk-matrix.md",
        "references/verification.md",
        "references/token-discipline.md",
    ]
    for ref in required_refs:
        if ref not in skill:
            fail(f"SKILL.md does not reference {ref}")

    json_files = [
        *[path for root in [ROOT / "council" / "schemas", ROOT / "runtime" / "schemas"] for path in sorted(root.glob("*.schema.json"))],
        ROOT / "dist" / "openai-plugin" / ".codex-plugin" / "plugin.json",
        ROOT / "dist" / "claude-marketplace" / ".claude-plugin" / "marketplace.json",
        ROOT / "dist" / "claude-marketplace" / "plugins" / "code-loop-plugin" / ".claude-plugin" / "plugin.json",
    ]
    for path in json_files:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"{path.relative_to(ROOT)} is invalid JSON: {exc}")

    required_paths = [
        ROOT / "council" / "README.md",
        ROOT / "council" / "schemas" / "task.schema.json",
        ROOT / "council" / "schemas" / "handoff.schema.json",
        ROOT / "council" / "schemas" / "decision.schema.json",
        ROOT / ".code-loop-template" / "task.yaml",
        ROOT / ".code-loop-template" / "plan.md",
        ROOT / ".code-loop-template" / "state.json",
        ROOT / "scripts" / "init-council.py",
        ROOT / "scripts" / "install-project.py",
        ROOT / "scripts" / "validate-council.py",
        ROOT / "scripts" / "nogap.py",
        ROOT / "scripts" / "nogap_dashboard.py",
        ROOT / "dashboard" / "index.html",
        ROOT / "runtime" / "config" / "model-router.policy.json",
        ROOT / "benchmarks" / "__init__.py",
        ROOT / "benchmarks" / "nogapbench" / "__init__.py",
        ROOT / "benchmarks" / "nogapbench" / "test_nogapbench.py",
        ROOT / "docs" / "nogapcode-runtime.md",
        ROOT / "docs" / "literature-learning.md",
        ROOT / "runtime" / "schemas" / "gate.schema.json",
        ROOT / "runtime" / "schemas" / "claim.schema.json",
        ROOT / "runtime" / "schemas" / "evidence.schema.json",
        ROOT / "runtime" / "schemas" / "run-event.schema.json",
        ROOT / "runtime" / "schemas" / "decision.schema.json",
        ROOT / "runtime" / "schemas" / "lesson.schema.json",
        ROOT / "runtime" / "schemas" / "literature-claim.schema.json",
        ROOT / "runtime" / "schemas" / "routing-decision.schema.json",
    ]
    missing_required = [str(path.relative_to(ROOT)) for path in required_paths if not path.exists()]
    if missing_required:
        fail("missing v5 council files: " + ", ".join(missing_required))

    print("OK: instruction hygiene checks passed")


if __name__ == "__main__":
    main()
