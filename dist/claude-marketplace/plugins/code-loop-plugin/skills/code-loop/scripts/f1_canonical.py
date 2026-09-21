#!/usr/bin/env python3
"""RFC 8785 (JCS) canonicalization, restricted to the profile F1 payloads use.

T1A §6 requires a published, testable canonicalization rather than a local convention, so that
independent implementations agree, and makes a payload that does not re-canonicalize byte-identically
inadmissible.

**The restriction is deliberate and enforced, not an omission.** RFC 8785 serializes numbers with
ECMAScript `Number::toString`, whose shortest-round-trip float formatting differs from Python's
`repr` in exponent form (`1e+21` vs `1e21`, `1e-05` vs `1e-5`). Every field in §6's body schemas is
a string, a digest, an integer or a list of those — no F1 payload contains a float. So this
implementation **rejects non-integer numbers** rather than approximating a formatter it cannot test
against real payloads. A canonicalizer that silently disagrees with another implementation on a
value it was never exercised on is worse than one that refuses the value: the refusal is visible,
and `verify` fails closed rather than accepting bytes the signer never meant.

Integers are exact under both specifications, so the profile is byte-identical to full JCS for
everything F1 signs.

    canonicalize({"b": 1, "a": "x"})  ->  b'{"a":"x","b":1}'
"""

from __future__ import annotations

ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f",
           "\n": "\\n", "\r": "\\r", "\t": "\\t"}


class CanonicalizationError(ValueError):
    """The value cannot be canonicalized, so it must not be signed or accepted."""


def _string(value: str) -> str:
    out = ['"']
    for ch in value:
        if ch in ESCAPES:
            out.append(ESCAPES[ch])
        elif ch < "\x20":
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _number(value: int) -> str:
    # bool is a subclass of int and serializes as true/false, handled before this is reached.
    if not isinstance(value, int) or isinstance(value, bool):
        raise CanonicalizationError(f"non-integer number in canonical payload: {value!r}")
    return str(value)


def _value(value: object) -> str:
    if value is None:
        # §6: absent fields are omitted, never null. A null reaching canonicalization means a
        # schema allowed a field to exist with no value, which is the optional-everywhere shape
        # AM-19 removed.
        raise CanonicalizationError("null in canonical payload; absent fields are omitted (§6)")
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, int):
        return _number(value)
    if isinstance(value, float):
        raise CanonicalizationError(
            f"float in canonical payload: {value!r}. This profile is integers-only; see the module "
            f"docstring for why a float is refused rather than approximated.")
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_value(v) for v in value) + "]"
    if isinstance(value, dict):
        items = []
        for key in sorted(value, key=lambda k: _sort_key(k)):
            items.append(_string(key) + ":" + _value(value[key]))
        return "{" + ",".join(items) + "}"
    raise CanonicalizationError(f"unserializable type in canonical payload: {type(value).__name__}")


def _sort_key(key: object) -> bytes:
    if not isinstance(key, str):
        raise CanonicalizationError(f"non-string object key: {key!r}")
    # RFC 8785 sorts by UTF-16 code units, not code points: they differ above the BMP, where a
    # surrogate pair sorts below U+E000..U+FFFF. Python's default str ordering is by code point.
    return key.encode("utf-16-be", errors="surrogatepass")


def canonicalize(value: object) -> bytes:
    """The canonical UTF-8 bytes of a JSON value, or raise."""
    return _value(value).encode("utf-8")
