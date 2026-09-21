#!/usr/bin/env python3
"""Historical Continuity Audit for the F1 contracts.

Thirty amendments were produced across fifteen adversarial review rounds. Most of the
reasoning behind them lives in a conversation; only the contracts and this ledger survive
it. A later revision that rewrites a section can silently drop an invariant an earlier
round paid for, and nothing would notice - the rewrite looks like an improvement.

That is not a hypothetical. This checker's first run found AM-1, AM-2 and AM-3 cited
nowhere in either contract: two had survived unlabelled, one had been superseded, and
which was which was knowable only from the conversation.

So the ledger is canonical and this script is its enforcement: every LIVE amendment must
have its anchor present in the document that holds it, and every SUPERSEDED one must name
what replaced it. An invariant cannot be dropped by a rewrite without failing here.

    python scripts/check-f1-continuity.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "f1-amendment-ledger.md"
DOCS = {
    "T1A": ROOT / "docs" / "f1-t1a-trust-core.md",
    "T1B": ROOT / "docs" / "f1-t1b-policy-obligations.md",
    "INDEX": ROOT / "docs" / "f1-trust-root-contract.md",
}

ROW = re.compile(r"^\|\s*(AM-\d+)\s*\|\s*(\w+)\s*\|\s*([\w/-]+)\s*\|\s*`([^`]*)`\s*\|")


def main() -> int:
    if not LEDGER.is_file():
        print(f"FAIL: missing ledger: {LEDGER.relative_to(ROOT)}", file=sys.stderr)
        return 1

    texts = {name: path.read_text(encoding="utf-8") for name, path in DOCS.items() if path.is_file()}
    rows = [ROW.match(line) for line in LEDGER.read_text(encoding="utf-8").splitlines()]
    rows = [m for m in rows if m]
    if not rows:
        print("FAIL: ledger has no parsable amendment rows", file=sys.stderr)
        return 1

    problems: list[str] = []
    seen: set[str] = set()
    live = superseded = 0

    for match in rows:
        am, status, doc, anchor = match.group(1), match.group(2), match.group(3), match.group(4)
        if am in seen:
            problems.append(f"{am}: listed twice in the ledger")
        seen.add(am)

        if status == "LIVE":
            live += 1
            if doc not in texts:
                problems.append(f"{am}: names unknown document {doc!r}")
            elif not anchor:
                problems.append(f"{am}: LIVE with no anchor to verify")
            elif anchor not in texts[doc]:
                problems.append(f"{am}: anchor not found in {doc} — the invariant may have been "
                                f"dropped by a rewrite: {anchor!r}")
        elif status == "SUPERSEDED":
            superseded += 1
            if not re.fullmatch(r"AM-\d+", doc):
                problems.append(f"{am}: SUPERSEDED must name the amendment that replaced it, got {doc!r}")
            elif doc not in {m.group(1) for m in rows}:
                problems.append(f"{am}: superseded by {doc}, which is not in the ledger")
        else:
            problems.append(f"{am}: unknown status {status!r} (expected LIVE or SUPERSEDED)")

    # every amendment number from 1..max must be present: a gap means one was forgotten
    numbers = sorted(int(a.split("-")[1]) for a in seen)
    missing = sorted(set(range(1, numbers[-1] + 1)) - set(numbers))
    if missing:
        problems.append("ledger skips amendments: " + ", ".join(f"AM-{n}" for n in missing))

    if problems:
        print("FAIL: historical continuity audit", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    print(f"OK: continuity audit passed ({live} live, {superseded} superseded, "
          f"AM-1..AM-{numbers[-1]} all accounted for)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
