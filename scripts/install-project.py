#!/usr/bin/env python3
"""Install Code Loop into a project without replacing existing agent instructions."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_MARKER = "<!-- code-loop-bridge -->"
BRIDGE = f"""
{BRIDGE_MARKER}
## Code Loop Bridge

Project-specific instructions in this file remain authoritative.

When the user invokes `clo/on`, `clo/council`, `clo/security`, `clo/verify`, or `clo/min`, apply
Code Loop as an additional discipline layer. Do not replace or weaken this project's existing
agent instructions.

Use `.code-loop/` for durable handoffs between Codex, Claude, Gemini, local models, and humans.
Do not edit application code while acting only as Scout, Reviewer, Skeptic, or Planner.
"""


def append_bridge(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if BRIDGE_MARKER in text:
        return f"kept existing bridge in {path.name}"
    path.write_text(text.rstrip() + "\n\n" + BRIDGE.lstrip(), encoding="utf-8")
    return f"appended bridge to existing {path.name}"


def copy_code_loop_agents(path: Path) -> str:
    shutil.copyfile(ROOT / "AGENTS.md", path)
    return "created AGENTS.md from Code Loop"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs="?", default=".", help="project root")
    parser.add_argument("--no-council", action="store_true", help="do not initialize .code-loop")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    if not target.exists():
        raise SystemExit(f"target does not exist: {target}")

    actions: list[str] = []
    instruction_files = [target / "AGENTS.md", target / "CLAUDE.md"]
    existing = [path for path in instruction_files if path.exists()]

    if existing:
        for path in existing:
            actions.append(append_bridge(path))
    else:
        actions.append(copy_code_loop_agents(target / "AGENTS.md"))

    if not args.no_council:
        council = target / ".code-loop"
        if council.exists():
            actions.append("kept existing .code-loop")
        else:
            shutil.copytree(ROOT / ".code-loop-template", council)
            actions.append("created .code-loop from template")

    for action in actions:
        print(action)


if __name__ == "__main__":
    main()
