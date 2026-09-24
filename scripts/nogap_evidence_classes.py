"""Sole owner of the declared evidence-class vocabulary (D4-PRE-C).

`evidence_class` is the SEMANTIC meaning of an evidence record, stamped by the writer
that knows it. It is separate from `kind` (storage representation) and is never derived
from `kind`. "plan" and "skip" are record categories, not evidence classes.
Stdlib-only; imports nothing from this codebase.
"""

EVIDENCE_CLASSES = frozenset({
    "execution",
    "deterministic",
    "effect_scope",
    "reproducibility",
    "independent_review",
})
