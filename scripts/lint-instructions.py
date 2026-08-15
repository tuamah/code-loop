#!/usr/bin/env python3
"""Small instruction hygiene checks for code-loop."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_FILES = [
    ROOT / "SKILL.md",
    ROOT / "AGENTS.md",
    ROOT / "README.md",
    ROOT / "agents" / "openai.yaml",
    *sorted((ROOT / "references").glob("*.md")),
]

MAX_SKILL_LINES = 180
MAX_AGENTS_LINES = 130
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

    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    if not skill.startswith("---\nname: code-loop\n"):
        fail("SKILL.md must start with code-loop YAML frontmatter")
    openai_yaml = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
    if "$code-loop" not in openai_yaml:
        fail("agents/openai.yaml default_prompt must mention $code-loop")

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
        "references/domain-router.md",
        "references/innovation-protocol.md",
        "references/risk-matrix.md",
        "references/verification.md",
        "references/token-discipline.md",
    ]
    for ref in required_refs:
        if ref not in skill:
            fail(f"SKILL.md does not reference {ref}")

    print("OK: instruction hygiene checks passed")


if __name__ == "__main__":
    main()
