"""Shared contract layer — the single importable source of truth for CONTRACT.md.

Both lanes (engine/HydraMem and minds) import from here and only from here:
enums (Law 11), ids (Appendix A), evidence (Appendix F, Law 14),
types (C1/C2 currency), registry (Law 12).
"""

from .enums import Action, Category, Concept, EventType, MotifType
from .evidence import EVIDENCE_TABLE, blend, confidence
from .types import (
    Appraisal,
    AppraisalTraits,
    ChoiceCoeffs,
    DecisionContext,
    EvidenceDelta,
    validate_context,
)

__all__ = [
    "Action",
    "Appraisal",
    "AppraisalTraits",
    "Category",
    "ChoiceCoeffs",
    "Concept",
    "DecisionContext",
    "EVIDENCE_TABLE",
    "EventType",
    "EvidenceDelta",
    "MotifType",
    "blend",
    "confidence",
    "validate_context",
]
