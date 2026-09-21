#!/usr/bin/env python3
"""Enumeration closure check for F1-T1A's CLOSED + CHECKED vocabularies.

T1A §-1 forbids security by remembered list: every security-significant enumeration must be
DERIVED from a property, CLOSED with a mechanical check, or explicitly NON-NORMATIVE. This
script is the mechanical check for the closed ones.

It proves the four per-message-type vocabularies agree with each other. They are written in
four different places and were drifting: round 9 found §10's procedure still testing a field
§6 had deleted, and round 13 found a message type carrying a head that §10.1's transaction
list had never heard of. A cross-check takes milliseconds and would have caught both.

    python scripts/check-f1-enumerations.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T1A = ROOT / "docs" / "f1-t1a-trust-core.md"


def main() -> int:
    if not T1A.is_file():
        print(f"FAIL: missing {T1A.relative_to(ROOT)}", file=sys.stderr)
        return 1
    text = T1A.read_text(encoding="utf-8")

    domains = set(re.findall(r"NOGAP::([A-Z]+)::v1\s*\|\|", text))

    actions_block = re.search(r"```\n(PROJECT\s+genesis.*?)\n```", text, re.S)
    actions: dict[str, list[str]] = {}
    if actions_block:
        for line in actions_block.group(1).splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                actions[parts[0]] = [a.strip() for a in parts[1].split("|") if a.strip()]

    bodies_block = re.search(r"Message-specific body.*?\n(.*?)\n```", text, re.S)
    bodies = set()
    if bodies_block:
        for line in bodies_block.group(1).splitlines():
            mm = re.match(r"\s{2}([A-Z]+)\s{2,}\S", line)
            if mm:
                bodies.add(mm.group(1))

    stage2_block = re.search(r"STAGE 2 — by message_type\n(.*?)\n```", text, re.S)
    stage2 = set()
    if stage2_block:
        for line in stage2_block.group(1).splitlines():
            mm = re.match(r"\s([A-Z]+)\s{2,}\S", line)
            if mm:
                stage2.add(mm.group(1))

    problems: list[str] = []
    if not domains:
        problems.append("no NOGAP::*::v1 domains found — §6's closed list is missing or reshaped")
    if not actions:
        problems.append("no per-type action enum found — AM-23's closed enum is missing or reshaped")
    if not bodies:
        problems.append("no per-type body schemas found — AM-19's split is missing or reshaped")
    if not stage2:
        problems.append("no STAGE 2 clauses found — AM-22's procedure is missing or reshaped")

    for name, found in (("action enum", set(actions)), ("body schema", bodies), ("Stage 2 clause", stage2)):
        for missing in sorted(domains - found):
            problems.append(f"{missing}: has a signing domain but no {name}")
        for extra in sorted(found - domains):
            problems.append(f"{extra}: has a {name} but no signing domain")

    for message_type, verbs in sorted(actions.items()):
        if not verbs:
            problems.append(f"{message_type}: action enum is empty; a type with no action cannot be granted (AM-20)")

    # AM-33: the closure rule applies to itself. Every fenced block must be declared in §-1's
    # manifest, so a new enumeration cannot enter the document without being classified.
    manifest = re.search(r"```\n((?:GOVERNED|ILLUSTRATIVE).*?)\n```", text, re.S)
    if not manifest:
        problems.append("§-1's closure manifest is missing — AM-33 requires it as the canonical source")
    else:
        prefixes = []
        for line in manifest.group(1).splitlines():
            mm = re.match(r"(GOVERNED|ILLUSTRATIVE)\s{2,}(\S.*?)\s{2,}\S", line)
            if mm:
                prefixes.append(mm.group(2).strip())
        if not prefixes:
            problems.append("§-1's closure manifest has no parsable entries")
        for block in re.findall(r"```\n(.*?)\n```", text, re.S):
            first = block.splitlines()[0].strip()
            if not any(first.startswith(prefix) for prefix in prefixes):
                problems.append(f"undeclared enumeration block, not in §-1's manifest: {first[:64]!r}")

    if problems:
        print("FAIL: F1-T1A closed vocabularies disagree", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print("\nSee T1A §-1: a CLOSED + CHECKED enumeration must have one canonical source and "
              "every dependent site must agree.", file=sys.stderr)
        return 1

    print(f"OK: F1-T1A closed vocabularies agree ({len(domains)} message types; "
          f"domain, action enum, body schema and Stage 2 clause present for each)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
