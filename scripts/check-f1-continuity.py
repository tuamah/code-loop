#!/usr/bin/env python3
"""Historical Continuity Audit for the F1 contracts.

Thirty-five amendments came out of seventeen adversarial review rounds. Most of the reasoning
lives in a conversation; only the contracts and the ledger survive it. A rewrite that looks like
an improvement can drop an invariant an earlier round paid for, and without a canonical record
nothing notices.

Round 18 attacked this checker and broke it four ways. Its first version verified that an
anchor *string* was present, which proved text existed and nothing about what it meant:

    kept `A valid head is not the current head (AM-18)` as a heading, and rewrote the rule
    beneath it to "a decision may use any cryptographically valid head"      -> passed

    marked AM-18 SUPERSEDED by AM-35, which carries none of its invariant   -> passed
    built a supersession cycle AM-18 -> AM-29 -> AM-18                      -> passed
    reflowed one line of AM-29's heading, changing nothing at all           -> FAILED

So it now digests the whole section an invariant lives in, over whitespace-normalized text.
Reflow no longer trips it; editing the rule does. Supersession must be inherited by exactly one
live amendment rather than merely pointed at, and cycles are rejected.

**What this can and cannot prove.** A digest proves the text did not change. It cannot prove
that changed text preserves meaning — no script can. What it does is make drift impossible to
perform *silently*: any edit to a section holding an invariant fails CI until someone updates the
ledger deliberately, and that update is a visible line in a diff for a reviewer to judge. The
guarantee is "no unacknowledged change", not "no harmful change".

    python scripts/check-f1-continuity.py
    python scripts/check-f1-continuity.py --update-digests   # acknowledge reviewed edits
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "f1-amendment-ledger.md"
DOCS = {
    "T1A": ROOT / "docs" / "f1-t1a-trust-core.md",
    "T1B": ROOT / "docs" / "f1-t1b-policy-obligations.md",
}
ROW = re.compile(
    r"^\|\s*(AM-\d+)\s*\|\s*(\w+)\s*\|\s*([\w/-]+)\s*\|\s*`([^`]*)`\s*\|\s*`([^`]*)`\s*\|\s*([^|]*)\|"
)


def section_digest(text: str, anchor: str) -> str | None:
    """Digest of the section the anchor lives in, whitespace-normalized.

    The section, not the line: an invariant is its rule plus the reasoning that bounds it, and a
    checker that watched only the heading is what round 18 defeated.
    """
    # Split by heading first, then match inside normalized sections. Searching the raw text for a
    # raw anchor made a reflowed line look like a deleted invariant — round 18's false positive.
    sections, current = [], []
    for line in text.splitlines():
        if line.startswith("#") and current:
            sections.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current))

    needle = " ".join(anchor.split())
    if not needle:
        return None
    hits = [" ".join(s.split()) for s in sections if needle in " ".join(s.split())]
    if len(hits) != 1:
        # Round 19: a decoy section quoting the anchor takes the first match, and one
        # editorial-looking --update-digests then points the watch at the decoy forever.
        # Ambiguity is the defect, so it fails here rather than being acknowledged away.
        return f"AMBIGUOUS:{len(hits)}"
    return hashlib.sha256(hits[0].encode("utf-8")).hexdigest()[:12]


def parse() -> tuple[list[dict], list[str]]:
    rows, problems = [], []
    if not LEDGER.is_file():
        return rows, [f"missing ledger: {LEDGER.relative_to(ROOT)}"]
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if m:
            rows.append({
                "am": m.group(1), "status": m.group(2), "where": m.group(3),
                "anchor": m.group(4), "digest": m.group(5), "inherits": m.group(6).strip(),
            })
    if not rows:
        problems.append("ledger has no parsable amendment rows")
    return rows, problems


def main() -> int:
    update = "--update-digests" in sys.argv
    rows, problems = parse()
    if not rows:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1

    texts = {name: path.read_text(encoding="utf-8") for name, path in DOCS.items() if path.is_file()}
    known = {r["am"] for r in rows}
    inherited: dict[str, list[str]] = {}
    seen: set[str] = set()
    updates: dict[str, str] = {}

    for row in rows:
        am, status, where, anchor = row["am"], row["status"], row["where"], row["anchor"]
        if am in seen:
            problems.append(f"{am}: listed twice")
        seen.add(am)

        for target in filter(None, (t.strip() for t in row["inherits"].split(","))):
            if target not in known:
                problems.append(f"{am}: claims to inherit {target}, which is not in the ledger")
            inherited.setdefault(target, []).append(am)

        if status == "LIVE":
            if where not in texts:
                problems.append(f"{am}: names unknown document {where!r}")
                continue
            if not anchor:
                problems.append(f"{am}: LIVE with no anchor")
                continue
            digest = section_digest(texts[where], anchor)
            if digest is None:
                problems.append(f"{am}: anchor not found in {where} — the invariant may have been "
                                f"dropped by a rewrite: {anchor!r}")
            elif digest.startswith("AMBIGUOUS:"):
                problems.append(f"{am}: anchor matches {digest.split(':')[1]} sections in {where}; it "
                                f"must identify exactly one, or the watch can be moved to a decoy: "
                                f"{anchor!r}")
            elif digest != row["digest"]:
                if update:
                    updates[am] = digest
                else:
                    problems.append(
                        f"{am}: the section holding this invariant changed "
                        f"(ledger {row['digest']}, now {digest}). Review the change; if it is "
                        f"editorial, re-run with --update-digests to acknowledge it.")
        elif status == "SUPERSEDED":
            if not re.fullmatch(r"AM-\d+", where):
                problems.append(f"{am}: SUPERSEDED must name its replacement, got {where!r}")
            elif where not in known:
                problems.append(f"{am}: superseded by {where}, which is not in the ledger")
        else:
            problems.append(f"{am}: unknown status {status!r}")

    # Supersession must be inheritance, not a pointer: something has to still carry the invariant.
    for row in rows:
        if row["status"] == "SUPERSEDED":
            heirs = inherited.get(row["am"], [])
            live = [h for h in heirs if any(r["am"] == h and r["status"] == "LIVE" for r in rows)]
            if len(live) != 1:
                problems.append(
                    f"{row['am']}: superseded but inherited by {len(live)} live amendment(s); "
                    f"exactly one must declare it and carry its invariant forward")

    # A cycle means no amendment actually holds the invariant.
    replacement = {r["am"]: r["where"] for r in rows if r["status"] == "SUPERSEDED"}
    for start in replacement:
        seen_chain, node = [], start
        while node in replacement:
            if node in seen_chain:
                problems.append("supersession cycle: " + " -> ".join(seen_chain + [node]))
                break
            seen_chain.append(node)
            node = replacement[node]

    numbers = sorted(int(a.split("-")[1]) for a in seen)
    missing = sorted(set(range(1, numbers[-1] + 1)) - set(numbers))
    if missing:
        problems.append("ledger skips: " + ", ".join(f"AM-{n}" for n in missing))

    # Round 19: the gap check derives the ledger's extent from the ledger, so deleting the
    # highest row passed, and so did inventing AM-37. Extent must be declared separately: a
    # truncation or a fabrication now contradicts a line a reviewer has to edit on purpose.
    declared = re.search(r"^AMENDMENTS:\s*(\d+)\s+through\s+AM-(\d+)\s*$",
                         LEDGER.read_text(encoding="utf-8"), re.M)
    if not declared:
        problems.append("ledger declares no extent; it needs a line `AMENDMENTS: <count> through "
                        "AM-<highest>` so a deleted or invented row contradicts it")
    else:
        count, highest = int(declared.group(1)), int(declared.group(2))
        if count != len(rows):
            problems.append(f"ledger declares {count} amendments but carries {len(rows)} rows")
        if highest != numbers[-1]:
            problems.append(f"ledger declares AM-{highest} as highest but carries AM-{numbers[-1]}")

    if update and updates and not problems:
        text = LEDGER.read_text(encoding="utf-8")
        for am, digest in updates.items():
            text = re.sub(rf"(\|\s*{am}\s*\|[^|]*\|[^|]*\|[^|]*\|\s*)`[^`]*`", rf"\g<1>`{digest}`", text)
        LEDGER.write_text(text, encoding="utf-8")
        print(f"acknowledged {len(updates)} reviewed section change(s): " + ", ".join(sorted(updates)))
        return 0

    if problems:
        print("FAIL: historical continuity audit", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    live = sum(1 for r in rows if r["status"] == "LIVE")
    print(f"OK: continuity audit passed ({live} live, {len(rows) - live} superseded, "
          f"AM-1..AM-{numbers[-1]} accounted for, section digests match)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
