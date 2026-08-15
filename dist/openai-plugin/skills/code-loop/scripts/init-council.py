#!/usr/bin/env python3
"""Initialize a project-local .code-loop workspace from the template."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / ".code-loop-template"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs="?", default=".", help="project root to initialize")
    parser.add_argument("--force", action="store_true", help="replace an existing .code-loop directory")
    args = parser.parse_args()

    target = Path(args.target).resolve() / ".code-loop"
    if target.exists():
        if not args.force:
            raise SystemExit(f"{target} already exists; use --force to replace it")
        shutil.rmtree(target)

    shutil.copytree(TEMPLATE, target)
    print(f"initialized {target}")


if __name__ == "__main__":
    main()
