#!/usr/bin/env python3
"""Validate the minimal Code Loop Council workspace shape."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED = [
    "task.yaml",
    "plan.md",
    "state.json",
    "handoffs/README.md",
    "evidence/README.md",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default=".code-loop", help=".code-loop directory or template")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    missing = [item for item in REQUIRED if not (root / item).exists()]
    if missing:
        raise SystemExit("missing required council files: " + ", ".join(missing))

    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    if state.get("phase") not in {"planning", "building", "verifying", "reviewing", "repairing", "blocked", "accepted"}:
        raise SystemExit("state.json has invalid phase")

    print(f"OK: council workspace valid: {root}")


if __name__ == "__main__":
    main()
