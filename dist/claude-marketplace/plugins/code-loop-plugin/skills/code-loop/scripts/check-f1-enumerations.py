#!/usr/bin/env python3
"""Enumeration closure check for F1-T1A's CLOSED + CHECKED vocabularies.

T1A §-1 forbids security by remembered list: every security-significant enumeration must be
DERIVED from a property, CLOSED with a mechanical check, or explicitly NON-NORMATIVE. This
script is the mechanical check for the closed ones.

Round 20 attacked it along eight paths and six landed. All six had one root cause: **the guard
derived the universe, the canonical source, the representation and the content from the very
material it was checking.**

    truncation      delete HUMAN from all four sites          -> passed (11 became 10, consistently)
    fabrication     add a 12th type to all four sites         -> passed (a peer of the other eleven)
    substitution    a "revised action enum" placed earlier    -> passed (re.search took the first)
    representation  the same set as an indented code block    -> passed (never scanned)
    drift           widen a closed action enum with `bypass`  -> passed (presence, not content)
    self-exemption  declare a real enum ILLUSTRATIVE          -> passed (the governor scoped itself)

    shadow          a second block with the same first line   -> blocked (AM-35's bijection)
    laundering      a new block under a broad declared prefix -> blocked (AM-35's bijection)

So §-1 now carries a commitment block: the message-type universe and a digest per governed
enumeration, pinned in advance. Deleting, adding, widening or re-representing an enumeration
contradicts a line someone has to edit deliberately — the AM-37 rule applied to content.

    python scripts/check-f1-enumerations.py
    python scripts/check-f1-enumerations.py --update-commitment   # acknowledge reviewed edits
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T1A = ROOT / "docs" / "f1-t1a-trust-core.md"
T1B = ROOT / "docs" / "f1-t1b-policy-obligations.md"


def digest(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()[:12]


def enumerations(text: str) -> list[tuple[str, str]]:
    """Every enumeration in the document, as (first line, full text).

    Fenced blocks, tables and indented code blocks. Round 20 moved a closed set into an indented
    block and it left the guard's sight entirely; a representation the guard does not read is a
    representation an enumeration can hide in.
    """
    found = []
    for block in re.findall(r"```\n(.*?)\n```", text, re.S):
        if block.startswith("COMMITMENT"):
            # The pin is not one of the things it pins: digesting a block that contains its own
            # digest cannot close. Its own integrity is the continuity guard's job — §-1 is a
            # digested section there, so an edit to this block fails that check instead.
            continue
        found.append((block.splitlines()[0].strip(), block))
    for header, body in re.findall(r"\n\|(.+?)\|\n\|[-| :]+\|\n((?:\|.*\n)*)", text):
        found.append((f"TABLE |{header.strip()}", header + "\n" + body))
    # Indented blocks: four-space runs that are not inside a fence and not list continuations.
    outside, fenced = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
            outside.append("")
        else:
            outside.append("" if fenced else line)
    run: list[str] = []
    for line in outside + [""]:
        if re.match(r"^ {4,}\S", line):
            run.append(line)
        else:
            if len(run) >= 2:
                found.append((run[0].strip(), "\n".join(run)))
            run = []
    return found


def commitment(text: str) -> tuple[dict[str, str], int, str] | None:
    """§-1's pinned universe. Never derived from the enumerations it commits to."""
    block = re.search(r"```\nCOMMITMENT.*?\n(.*?)\n```", text, re.S)
    if not block:
        return None
    pinned, types, types_digest = {}, 0, ""
    for line in block.group(1).splitlines():
        m = re.match(r"^MESSAGE_TYPES:\s*(\d+)\s+([0-9a-f]{12})\s*$", line)
        if m:
            types, types_digest = int(m.group(1)), m.group(2)
            continue
        m = re.match(r"^([0-9a-f]{12}|PENDING)\s+(.+?)\s*$", line)
        if m:
            pinned[m.group(2)] = m.group(1)
    return pinned, types, types_digest


def restated_schema(t1a: str, t1b: str) -> list[str]:
    """A T1B enumeration that names a message type and lists fields that type owns (AM-39).

    Revision 8 of T1B carried its own block headed `(NOGAP::APPLICABILITY::v1)` listing
    `obligation_id`, `obligation_class`, `project_scope`, `predicate_scope` and two conditions. It
    disagreed with T1A §6 on nine fields out of eleven across four revisions, and each guard read
    one contract, so neither audit could see it. A canonical source is only canonical across the
    whole set of contracts that share it.

    Sharing a *word* is not restating a schema: T1B's Verification Obligation is a TCB-internal
    record that legitimately carries an `obligation_id`. What is forbidden is naming a message type
    and then enumerating that type's fields — a second definition of the same signed object.
    """
    block = re.search(r"Message-specific body.*?\n(.*?)\n```", t1a, re.S)
    if not block:
        return ["T1A's body-schema block not found; the cross-contract check cannot run"]
    owned: dict[str, set[str]] = {}
    current = None
    for line in block.group(1).splitlines():
        m = re.match(r"\s{2}([A-Z]+)\s{2,}(.*)$", line)
        if m:
            current, rest = m.group(1), m.group(2)
        elif current:
            rest = line
        else:
            continue
        owned.setdefault(current, set()).update(
            re.findall(r"\b([a-z][a-z0-9_]*_[a-z0-9_]+)\b", rest))
    out = []
    for first, body in enumerations(t1b):
        for message_type in set(re.findall(r"NOGAP::([A-Z]+)::v1", body)):
            # A row's leading token is "|", so a table would have hidden a restatement behind a
            # representation switch — the same move round 20 used on the enumeration scan itself.
            heads = set()
            for line in body.splitlines():
                cells = [c.strip() for c in line.split("|") if c.strip()] if "|" in line else []
                tokens = [c.split()[0] for c in cells if c.split()] + line.strip().split()[:1]
                heads.update(tokens)
            hits = heads & owned.get(message_type, set())
            if hits:
                out.append(
                    f"T1B restates the {message_type} schema in {first[:38]!r}: field(s) "
                    f"{sorted(hits)} are T1A §6's, which is their single canonical source (AM-39)")
    return out


def audit(text: str, name: str) -> tuple[list[str], dict[str, str], dict[str, str]]:
    """Manifest classification, bijection and commitment for one contract.

    Returns (problems, governed prefix -> body, prefix -> acknowledged digest).
    """
    problems: list[str] = []
    manifest = re.search(r"```\n((?:GOVERNED|ILLUSTRATIVE)\s*::.*?)\n```", text, re.S)
    if not manifest:
        return ([f"{name}: closure manifest is missing — AM-32/AM-39 require one per contract"],
                {}, {})

    declared: list[tuple[str, str]] = []
    roles: dict[str, str] = {}
    for line in manifest.group(1).splitlines():
        m = re.match(r"(GOVERNED|ILLUSTRATIVE)\s*::\s*(.+)::(.+)$", line)
        if not m:
            continue
        # Split at the LAST separator: a prefix may itself contain "::" (NOGAP::PROJECT::v1).
        prefix, role = m.group(2).strip(), m.group(3).split("—")[0].strip()
        declared.append((m.group(1), prefix))
        if m.group(1) == "GOVERNED":
            if role in roles:
                problems.append(f"{name}: two governed enumerations claim the role {role!r}: "
                                f"{roles[role]!r} and {prefix!r}; a role has one canonical source")
            roles[role] = prefix
    if not declared:
        problems.append(f"{name}: closure manifest has no parsable entries")

    found = enumerations(text)
    body_of: dict[str, str] = {}
    for kind, prefix in declared:
        hits = [(f, b) for f, b in found if f.startswith(prefix)]
        if len(hits) == 0:
            problems.append(f"{name}: manifest entry matches nothing — stale declaration: {prefix!r}")
        elif len(hits) > 1:
            problems.append(
                f"{name}: manifest prefix {prefix!r} matches {len(hits)} enumerations; it must "
                f"identify exactly one, or a new one enters undeclared behind it")
        elif kind == "GOVERNED":
            body_of[prefix] = hits[0][1]
    for first, _ in found:
        matched = [p for _, p in declared if first.startswith(p)]
        if not matched:
            problems.append(f"{name}: undeclared enumeration, not in the manifest: {first[:64]!r}")
        elif len(matched) > 1:
            problems.append(f"{name}: enumeration {first[:48]!r} is claimed by {len(matched)} "
                            f"manifest entries")

    # AM-38: universe and content pinned in advance, never derived from the material.
    updates: dict[str, str] = {}
    pin = commitment(text)
    if pin is None:
        problems.append(f"{name}: no COMMITMENT block; without one the guard derives the expected "
                        f"universe from material that may itself be truncated or forged")
        return problems, body_of, updates
    pinned, _, _ = pin
    governed = {p for k, p in declared if k == "GOVERNED"}
    for prefix in sorted(governed):
        if prefix not in pinned:
            problems.append(f"{name}: governed enumeration is not pinned: {prefix!r}")
        elif prefix in body_of and pinned[prefix] != digest(body_of[prefix]):
            updates[prefix] = digest(body_of[prefix])
    for prefix in sorted(pinned):
        if prefix not in governed:
            problems.append(f"{name}: pins an enumeration the manifest no longer governs: {prefix!r}")
    n_ill = sum(1 for k, _ in declared if k == "ILLUSTRATIVE")
    m = re.search(r"^ILLUSTRATIVE_ENTRIES:\s*(\d+)\s*$", text, re.M)
    if not m:
        problems.append(f"{name}: does not pin how many ILLUSTRATIVE entries exist; without it the "
                        f"manifest can exempt a real enumeration by declaring one more")
    elif int(m.group(1)) != n_ill:
        problems.append(f"{name}: pins {m.group(1)} ILLUSTRATIVE entries, the manifest carries "
                        f"{n_ill}; a new exemption must be declared deliberately")
    return problems, body_of, updates


def roles_of(text: str) -> dict[str, str]:
    manifest = re.search(r"```\n((?:GOVERNED|ILLUSTRATIVE)\s*::.*?)\n```", text, re.S)
    out: dict[str, str] = {}
    for line in (manifest.group(1).splitlines() if manifest else []):
        m = re.match(r"GOVERNED\s*::\s*(.+)::(.+)$", line)
        if m:
            out.setdefault(m.group(2).split("—")[0].strip(), m.group(1).strip())
    return out


def main() -> int:
    for path in (T1A, T1B):
        if not path.is_file():
            print(f"FAIL: missing {path.relative_to(ROOT)}", file=sys.stderr)
            return 1
    t1a, t1b = T1A.read_text(encoding="utf-8"), T1B.read_text(encoding="utf-8")

    problems, body_a, updates_a = audit(t1a, "T1A")
    p_b, _, updates_b = audit(t1b, "T1B")
    problems += p_b
    problems += restated_schema(t1a, t1b)

    # T1A owns every message schema (AM-39), so the four-site cross-check reads T1A alone. Each
    # canonical source is named by its role in the manifest, never found by document order.
    roles = roles_of(t1a)

    def canonical(role: str) -> str:
        return body_a.get(roles.get(role, ""), "")

    domains = set(re.findall(r"NOGAP::([A-Z]+)::v1\s*\|\|", canonical("domain list")))
    actions: dict[str, list[str]] = {}
    for line in canonical("action enum").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            actions[parts[0]] = [a.strip() for a in parts[1].split("|") if a.strip()]
    bodies = {m.group(1) for line in canonical("envelope + body schemas").splitlines()
              if (m := re.match(r"\s{2}([A-Z]+)\s{2,}\S", line))}
    stage2 = {m.group(1) for line in canonical("admissibility").splitlines()
              if (m := re.match(r"\s([A-Z]+)\s{2,}\S", line))}

    for label, got in (("domain list", domains), ("action enum", set(actions)),
                       ("body schema", bodies), ("Stage 2 clause", stage2)):
        if not got:
            problems.append(f"T1A: no {label} found under its manifest role — the canonical source "
                            f"is missing or reshaped")
    for label, got in (("action enum", set(actions)), ("body schema", bodies),
                       ("Stage 2 clause", stage2)):
        for missing in sorted(domains - got):
            problems.append(f"{missing}: has a signing domain but no {label}")
        for extra in sorted(got - domains):
            problems.append(f"{extra}: has a {label} but no signing domain")
    for message_type, verbs in sorted(actions.items()):
        if not verbs:
            problems.append(f"{message_type}: action enum is empty; a type with no action cannot "
                            f"be granted (AM-20)")

    pin = commitment(t1a)
    if pin:
        _, n_types, types_digest = pin
        now = digest(" ".join(sorted(domains)))
        if len(domains) != n_types or now != types_digest:
            problems.append(f"message-type universe is not the committed one: T1A §-1 pins "
                            f"{n_types} types ({types_digest}), the document carries "
                            f"{len(domains)} ({now})")

    if "--update-commitment" in sys.argv and (updates_a or updates_b) and not problems:
        for path, updates in ((T1A, updates_a), (T1B, updates_b)):
            out = path.read_text(encoding="utf-8")
            for prefix, new in updates.items():
                out = re.sub(rf"^([0-9a-f]{{12}}|PENDING)(\s+{re.escape(prefix)}\s*)$",
                             rf"{new}\g<2>", out, flags=re.M)
            if path is T1A:
                out = re.sub(r"^MESSAGE_TYPES:\s*\d+\s+[0-9a-f]{12}\s*$",
                             f"MESSAGE_TYPES: {len(domains)} {digest(' '.join(sorted(domains)))}",
                             out, flags=re.M)
            path.write_text(out, encoding="utf-8")
        total = len(updates_a) + len(updates_b)
        print(f"acknowledged {total} reviewed enumeration change(s): "
              + ", ".join(sorted(updates_a) + sorted(updates_b)))
        return 0
    for name, updates in (("T1A", updates_a), ("T1B", updates_b)):
        for prefix, now in sorted(updates.items()):
            problems.append(f"{name}: governed enumeration changed: {prefix!r} (now {now}). Review "
                            f"it; if editorial, re-run with --update-commitment to acknowledge it.")

    if problems:
        print("FAIL: F1 closed vocabularies disagree", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print("\nSee T1A §-1 and T1B §B0: a CLOSED + CHECKED enumeration has one canonical source "
              "across both contracts, every dependent site agrees, and its universe and content "
              "are pinned in advance.", file=sys.stderr)
        return 1

    print(f"OK: F1 closed vocabularies agree ({len(domains)} committed message types; domain, "
          f"action enum, body schema and Stage 2 clause present for each; T1A and T1B read as one "
          f"set, no cross-contract schema restated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
