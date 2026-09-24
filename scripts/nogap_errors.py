#!/usr/bin/env python3
"""The project's central validation exception: pure, no imports from this codebase.

`MethodologyValidationError` is raised throughout the nogap_* modules for any malformed
contract, unknown reference, or ledger failure - fail closed, never partial-load. It lives in
its own neutral module, depending on nothing else in this codebase, so that any module (a ledger
reader, the methodology engine, an artifact registry, ...) can raise or catch it without risking
an import cycle. nogap_methodology.py imports and re-exports it under its own name, so every
existing `from nogap_methodology import MethodologyValidationError` call site elsewhere in the
repo keeps working unchanged and refers to this exact class object.
"""

from __future__ import annotations


class MethodologyValidationError(Exception):
    """Raised for any malformed contract, unknown reference, or evidence-ledger failure.
    Fail closed, never partial-load."""
