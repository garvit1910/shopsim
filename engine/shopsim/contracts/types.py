"""C1/C2 currency: DecisionContext and the mind-side types (CONTRACT.md).

The first nine Scalars fields are the v3 MemoryPacket, byte-compatible — do
not rename, reorder semantics, or retype them (MEMORY_PACKET_FIELDS below).

AppraisalTraits and ChoiceCoeffs are frozen on purpose (Law 12): decide()
cannot receive traits by signature, appraise() cannot receive coeffs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol

from .enums import BEHAVIORAL_MOTIFS, Action, EventType, MotifType
from .evidence import CONFIDENCE_K

# ---------------------------------------------------------------------------
# C1 — DecisionContext
# ---------------------------------------------------------------------------

# The v3 MemoryPacket, byte-for-byte. ScriptedMind and all early code read
# exactly these; back-compat here is why stand-ins survive contract changes.
MEMORY_PACKET_FIELDS = (
    "shopper_id",
    "aware_of_brand",
    "adstock",
    "exposures_72h",
    "last_seen_t",
    "reference_price",
    "current_price_gap",
    "budget_left",
    "cart",
)

WORLDVIEW_SCALAR_FIELDS = ("trust_belief", "quality_belief", "active_need", "habit")

# Law 15: latent objective params must never appear in any payload a mind sees.
FORBIDDEN_PAYLOAD_KEYS = ("latent_quality", "ship_reliability")


@dataclass(frozen=True)
class BeliefScalar:
    value: float
    evidence: float
    confidence: float  # = E / (E + 0.7), computed in Python, denormalized here


@dataclass(frozen=True)
class ActiveNeed:
    category: int
    strength: float
    urgency: float  # computed in Python from deadline_t
    budget_cap: float  # consumed by decide() ONLY (registry row 4)


@dataclass(frozen=True)
class HabitScalar:
    stim_brand: float
    rival_max: float


@dataclass(frozen=True)
class Scalars:
    shopper_id: int
    aware_of_brand: bool
    adstock: float
    exposures_72h: int
    last_seen_t: int | None
    reference_price: dict[int, float]
    current_price_gap: float
    budget_left: float
    cart: tuple[int, ...]
    trust_belief: BeliefScalar | None  # null = unknown brand = abstention
    quality_belief: BeliefScalar | None  # P1
    active_need: ActiveNeed | None  # null = no active goal
    habit: HabitScalar | None  # P1


@dataclass(frozen=True)
class Motif:
    """One typed evidence path. `path` alternates node ids and edge-type
    strings. Required numeric fields vary per type (MOTIF_REQUIRED_FIELDS)."""

    type: MotifType
    path: tuple[Any, ...]
    strength: float | None = None
    urgency: float | None = None
    evidence: float | None = None
    recency: float | None = None
    brand: int | None = None
    valence: float | None = None
    peer_trust: float | None = None
    experience: float | None = None


MOTIF_REQUIRED_FIELDS: dict[MotifType, tuple[str, ...]] = {
    MotifType.PREFERENCE_FIT: ("strength", "evidence", "recency"),
    MotifType.GOAL_FIT: ("strength", "urgency"),
    MotifType.BRAND_SEMANTIC_FATIGUE: ("strength", "recency", "brand"),
    MotifType.EXPECTATION_VIOLATION: ("strength",),
    MotifType.CONCEPT_SATURATION: ("strength",),
    MotifType.SOCIAL_PROOF: ("valence", "peer_trust", "experience"),
}


@dataclass(frozen=True)
class DecisionContext:
    scalars: Scalars
    motifs: tuple[Motif, ...]

    @classmethod
    def from_dict(cls, data: dict) -> "DecisionContext":
        problems = validate_context(data)
        if problems:
            raise ValueError("invalid DecisionContext: " + "; ".join(problems))
        s = data["scalars"]

        def belief(v):
            return None if v is None else BeliefScalar(v["value"], v["evidence"], v["confidence"])

        scalars = Scalars(
            shopper_id=s["shopper_id"],
            aware_of_brand=s["aware_of_brand"],
            adstock=float(s["adstock"]),
            exposures_72h=int(s["exposures_72h"]),
            last_seen_t=s["last_seen_t"],
            reference_price={int(k): float(v) for k, v in s["reference_price"].items()},
            current_price_gap=float(s["current_price_gap"]),
            budget_left=float(s["budget_left"]),
            cart=tuple(s["cart"]),
            trust_belief=belief(s["trust_belief"]),
            quality_belief=belief(s["quality_belief"]),
            active_need=None
            if s["active_need"] is None
            else ActiveNeed(
                category=s["active_need"]["category"],
                strength=s["active_need"]["strength"],
                urgency=s["active_need"]["urgency"],
                budget_cap=s["active_need"]["budget_cap"],
            ),
            habit=None
            if s["habit"] is None
            else HabitScalar(s["habit"]["stim_brand"], s["habit"]["rival_max"]),
        )
        motifs = tuple(
            Motif(
                type=MotifType(m["type"]),
                path=tuple(m["path"]),
                **{
                    k: m[k]
                    for k in (
                        "strength",
                        "urgency",
                        "evidence",
                        "recency",
                        "brand",
                        "valence",
                        "peer_trust",
                        "experience",
                    )
                    if k in m
                },
            )
            for m in data["motifs"]
        )
        return cls(scalars=scalars, motifs=motifs)

    def to_dict(self) -> dict:
        s = self.scalars

        def belief(b):
            return (
                None
                if b is None
                else {"value": b.value, "evidence": b.evidence, "confidence": b.confidence}
            )

        out_scalars = {
            "shopper_id": s.shopper_id,
            "aware_of_brand": s.aware_of_brand,
            "adstock": s.adstock,
            "exposures_72h": s.exposures_72h,
            "last_seen_t": s.last_seen_t,
            "reference_price": {str(k): v for k, v in s.reference_price.items()},
            "current_price_gap": s.current_price_gap,
            "budget_left": s.budget_left,
            "cart": list(s.cart),
            "trust_belief": belief(s.trust_belief),
            "quality_belief": belief(s.quality_belief),
            "active_need": None
            if s.active_need is None
            else {
                "category": s.active_need.category,
                "strength": s.active_need.strength,
                "urgency": s.active_need.urgency,
                "budget_cap": s.active_need.budget_cap,
            },
            "habit": None
            if s.habit is None
            else {"stim_brand": s.habit.stim_brand, "rival_max": s.habit.rival_max},
        }
        out_motifs = []
        for m in self.motifs:
            entry: dict[str, Any] = {"type": m.type.value}
            for k in MOTIF_REQUIRED_FIELDS.get(m.type, ()):
                entry[k] = getattr(m, k)
            entry["path"] = list(m.path)
            out_motifs.append(entry)
        return {"scalars": out_scalars, "motifs": out_motifs}


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_belief(v: Any, name: str, problems: list[str]) -> None:
    if v is None:
        return
    if not isinstance(v, dict):
        problems.append(f"{name} must be null or an object")
        return
    for k in ("value", "evidence", "confidence"):
        if not _is_num(v.get(k)):
            problems.append(f"{name}.{k} missing or not numeric")
            return
    # denormalized confidence must agree with E/(E+0.7) up to display rounding
    expect = v["evidence"] / (v["evidence"] + CONFIDENCE_K)
    if not math.isclose(v["confidence"], expect, abs_tol=0.005):
        problems.append(
            f"{name}.confidence {v['confidence']} inconsistent with "
            f"E/(E+{CONFIDENCE_K}) = {expect:.4f}"
        )


def _scan_forbidden(node: Any, problems: list[str], where: str = "context") -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if any(bad in str(k) for bad in FORBIDDEN_PAYLOAD_KEYS):
                problems.append(f"forbidden latent key '{k}' in {where} (Law 15)")
            _scan_forbidden(v, problems, where)
    elif isinstance(node, list):
        for item in node:
            _scan_forbidden(item, problems, where)


def validate_context(data: dict) -> list[str]:
    """C1 schema check. Returns a list of problems; empty list = valid."""
    problems: list[str] = []
    if not isinstance(data, dict) or "scalars" not in data or "motifs" not in data:
        return ["context must be an object with 'scalars' and 'motifs'"]
    s, motifs = data["scalars"], data["motifs"]
    if not isinstance(s, dict):
        return ["scalars must be an object"]
    if not isinstance(motifs, list):
        return ["motifs must be an array"]

    for name in MEMORY_PACKET_FIELDS + WORLDVIEW_SCALAR_FIELDS:
        if name not in s:
            problems.append(f"scalars.{name} missing")
    if problems:
        return problems

    if not isinstance(s["shopper_id"], int):
        problems.append("shopper_id must be int")
    if not isinstance(s["aware_of_brand"], bool):
        problems.append("aware_of_brand must be bool")
    if not _is_num(s["adstock"]) or s["adstock"] < 0:
        problems.append("adstock must be a number >= 0")
    if not isinstance(s["exposures_72h"], int) or s["exposures_72h"] < 0:
        problems.append("exposures_72h must be an int >= 0")
    if s["last_seen_t"] is not None and not isinstance(s["last_seen_t"], int):
        problems.append("last_seen_t must be int epoch or null")
    if not isinstance(s["reference_price"], dict) or not all(
        _is_num(v) for v in s["reference_price"].values()
    ):
        problems.append("reference_price must be {product_id: number}")
    if not _is_num(s["current_price_gap"]):
        problems.append("current_price_gap must be a number")
    if not _is_num(s["budget_left"]):
        problems.append("budget_left must be a number")
    if not isinstance(s["cart"], list):
        problems.append("cart must be an array")
    _check_belief(s["trust_belief"], "trust_belief", problems)
    _check_belief(s["quality_belief"], "quality_belief", problems)

    need = s["active_need"]
    if need is not None:
        if not isinstance(need, dict):
            problems.append("active_need must be null or an object")
        else:
            for k in ("category", "strength", "urgency", "budget_cap"):
                if not _is_num(need.get(k)):
                    problems.append(f"active_need.{k} missing or not numeric")
    habit = s["habit"]
    if habit is not None:
        if not isinstance(habit, dict) or not all(
            _is_num(habit.get(k)) for k in ("stim_brand", "rival_max")
        ):
            problems.append("habit must be null or {stim_brand, rival_max}")

    behavioral_values = {m.value for m in BEHAVIORAL_MOTIFS}
    seen_types: list[str] = []
    for i, m in enumerate(motifs):
        if not isinstance(m, dict) or "type" not in m or "path" not in m:
            problems.append(f"motifs[{i}] must be an object with 'type' and 'path'")
            continue
        mtype = m["type"]
        if mtype not in behavioral_values:
            problems.append(
                f"motifs[{i}].type '{mtype}' not a behavioral MotifType "
                "(explanatory motifs are trace-only)"
            )
            continue
        seen_types.append(mtype)
        for k in MOTIF_REQUIRED_FIELDS[MotifType(mtype)]:
            if not _is_num(m.get(k)):
                problems.append(f"motifs[{i}] ({mtype}) missing numeric field '{k}'")
        path = m["path"]
        if not isinstance(path, list) or len(path) < 3 or len(path) % 2 == 0:
            problems.append(f"motifs[{i}].path must alternate node, edge, node, … (odd length >= 3)")
        else:
            for j, elem in enumerate(path):
                ok = isinstance(elem, int) if j % 2 == 0 else isinstance(elem, str)
                if not ok:
                    problems.append(f"motifs[{i}].path[{j}] must be a {'node id' if j % 2 == 0 else 'edge type'}")
                    break

    # goal consistency: goal_fit <=> active_need (abstention, structurally)
    has_goal_fit = MotifType.GOAL_FIT.value in seen_types
    if has_goal_fit and need is None:
        problems.append("goal_fit motif present but active_need is null")
    if need is not None and not has_goal_fit:
        problems.append("active_need present but no goal_fit motif retrieved")

    _scan_forbidden(data, problems)
    return problems


# ---------------------------------------------------------------------------
# C2 — Mind interface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AppraisalTraits:
    """appraise() only (Law 12). Preference priors are NOT traits — they live
    as seeded PREFERS edges (E0 = 2); multiplying an affinity again in
    appraisal would count it twice. The registry test keeps this true."""

    novelty_seeking: float
    trust_orientation: float
    deal_proneness: float


@dataclass(frozen=True)
class ChoiceCoeffs:
    """decide() only (Law 12). stage_bases is a tuple of (stage, theta) pairs
    so the dataclass stays frozen/hashable; use stage_base()."""

    impulsivity: float  # = Gumbel/logistic temperature tau — its ONE entry
    price_sensitivity: float
    budget: float
    switching_inertia: float = 0.0  # P1
    risk_aversion: float = 0.0  # P1: x (1 - trust confidence), BUY stage only
    stage_bases: tuple[tuple[str, float], ...] = ()

    def stage_base(self, stage: str) -> float:
        for name, theta in self.stage_bases:
            if name == stage:
                return theta
        raise KeyError(f"no stage base for {stage!r}")


@dataclass(frozen=True)
class Appraisal:
    """P0 dims, all 0..1. P1 dims default to None until pulled."""

    relevance: float
    credibility: float
    brand_message_fatigue: float
    offer_attractiveness: float
    expectation_alignment: float
    novelty: float | None = None  # P1
    social_proof: float | None = None  # P1


@dataclass(frozen=True)
class Event:
    """One episodic/log record, as consolidate() consumes it."""

    type: EventType
    shopper_id: int
    t: int
    run: int
    subject: int  # the stimulus/product/page the event is about
    props: tuple[tuple[str, Any], ...] = ()  # e.g. (("sat", 0.9),)

    def prop(self, key: str, default: Any = None) -> Any:
        for k, v in self.props:
            if k == key:
                return v
        return default


@dataclass(frozen=True)
class EvidenceDeltaKey:
    kind: str  # "edge" | "belief"
    subject: int
    object: int


@dataclass(frozen=True)
class EvidenceDelta:
    """consolidate() output. Minds never write: the ENGINE applies deltas —
    batch-read current (w, E), blend per evidence.py, write supersessions in
    canonical order (shopper_id, t, event_rank)."""

    key: EvidenceDeltaKey
    target: float
    weight: float
    cause_kind: EventType
    cause_id: int


@dataclass(frozen=True)
class WorldviewSnapshot:
    """Read-only worldview slice handed to consolidate(). Tuples of tuples so
    the snapshot is frozen; the engine builds it from live edges."""

    prefs: tuple[tuple[int, float, float], ...] = ()  # (concept_id, w, E)
    beliefs: tuple[tuple[int, int, float, float], ...] = ()  # (about_id, that_id, value, E)
    expects: tuple[tuple[int, int, float], ...] = ()  # (brand_id, concept_id, strength)
    reference_price: tuple[tuple[int, float], ...] = ()  # (product_id, price)
    active_needs: tuple[tuple[int, float, float], ...] = ()  # (category_id, strength, deadline_t)


class Mind(Protocol):
    """C2: three pure stages. decide() takes coeffs, never traits — enforced
    by signature (Law 12) and the Phase-2 signature test."""

    def appraise(self, ctx: DecisionContext, traits: AppraisalTraits) -> Appraisal: ...

    def decide(self, a: Appraisal, s: Scalars, coeffs: ChoiceCoeffs, rng: Any) -> Action: ...

    def consolidate(
        self, events: list[Event], snapshot: WorldviewSnapshot
    ) -> list[EvidenceDelta]: ...
