"""The decision trace — what the mind actually saw, so calibration is cheap.

Calibrating by editing a constant and paying 20-110 minutes for a full run does
not converge. This module records one row per decision (the raw APPRAISAL
INPUTS, not the appraised dims), which lets any candidate calibration be
replayed offline in milliseconds against the exact contexts a real run produced.

Two rules keep it honest:

  * **Inputs, never outputs.** A candidate calibration changes `appraise()` too
    (w_pref, offer_norm, the cold gate), so storing the five dims would freeze
    half the parameters. Rows carry motif strengths, traits and scalars, and
    replay calls the REAL `appraise()` and the REAL gate functions. There is no
    second copy of the arithmetic anywhere in this file.
  * **Off by default.** No `--trace-decisions` means no file, no branch taken in
    the tick loop, and a byte-identical `results.json`
    (tests/test_eval_trace.py::test_tracing_off_is_byte_identical).

Replay is FIRST-ORDER: it re-scores the contexts the baseline run produced, so
it cannot model the feedback loop where more clicks teach more preferences which
raise relevance. That gap is not hidden — `calibrate.py` reports predicted
vs realised for every fitted profile, and the fit iterates until it closes.

theta arithmetic: a shopper's stage base is
`calibration_base[stage] + segment_theta_adjust[stage] + N(0, theta_jitter_sd)`
(population/factory.py). The last two terms do not depend on the first, so
rebasing a traced shopper onto a candidate profile is exact:
`theta' = theta_traced - base_traced[stage] + base_candidate[stage]`.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from ..contracts.enums import Action
from ..contracts.types import ChoiceCoeffs, DecisionContext
from ..minds.appraisal import appraise
from ..minds.calibration import (
    DEFAULT_APPRAISAL_PARAMS,
    DEFAULT_CHOICE_PARAMS,
    DEFAULT_STAGE_BASES,
    STAGES,
)
from ..minds.choice import stage_probabilities
from ..minds.objective_view import StimulusFacts

TRACE_VERSION = 1
TRACE_FILENAME = "decisions.jsonl"

# Positional row schema. A 300x30 run traces ~25k decisions; positional rows
# keep that near 5 MB instead of 15 MB, and the header line makes the file
# self-describing rather than depending on this tuple staying in sync.
FIELDS: tuple[str, ...] = (
    "tick", "offset", "segment", "kind", "stimulus",
    # --- appraisal inputs (motifs) ---
    "pref_strength", "pref_recency", "goal_strength", "goal_urgency",
    "fatigue_strength", "violation_strength", "social_valence", "social_peer_trust",
    "n_motifs",
    # --- appraisal inputs (traits + stimulus + belief) ---
    "trust_orientation", "deal_proneness", "novelty_seeking",
    "claimed_pct", "aware_of_brand",
    "trust_value", "trust_evidence",
    # --- decide() scalars ---
    "adstock", "exposures_72h", "current_price_gap", "budget_left",
    "in_cart", "ref_price_min",
    "need_strength", "need_urgency", "need_budget_cap",
    # --- shopper coefficients (stage bases in STAGES order) ---
    "impulsivity", "price_sensitivity",
    "theta_click", "theta_browse", "theta_cart", "theta_buy",
    # --- realised outcome ---
    "action",
)
_IDX = {name: i for i, name in enumerate(FIELDS)}

_THETA_FIELDS = ("theta_click", "theta_browse", "theta_cart", "theta_buy")


def _strongest(ctx: DecisionContext, mtype) -> object | None:
    best = None
    for m in ctx.motifs:
        if m.type is mtype and (best is None or (m.strength or 0.0) > (best.strength or 0.0)):
            best = m
    return best


def _r(x, n=6):
    return None if x is None else round(float(x), n)


class DecisionTrace:
    """Append-only writer. One instance per arm; the runner owns its lifetime."""

    def __init__(self, path: Path, *, header: dict):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w")
        self._fh.write(json.dumps({
            "trace_version": TRACE_VERSION,
            "fields": list(FIELDS),
            **header,
        }, sort_keys=True) + "\n")
        self.n = 0

    def record(self, *, ctx: DecisionContext, traits, coeffs: ChoiceCoeffs,
               stim: StimulusFacts | None, kind: str, action: Action,
               tick: int, offset: int, segment: int, stimulus: int) -> None:
        from ..contracts.enums import MotifType

        s = ctx.scalars
        pref = _strongest(ctx, MotifType.PREFERENCE_FIT)
        goal = _strongest(ctx, MotifType.GOAL_FIT)
        fat = _strongest(ctx, MotifType.BRAND_SEMANTIC_FATIGUE)
        viol = _strongest(ctx, MotifType.EXPECTATION_VIOLATION)
        peer = None
        for m in ctx.motifs:
            if m.type is MotifType.SOCIAL_PROOF and (
                    peer is None or (m.peer_trust or 0.0) > (peer.peer_trust or 0.0)):
                peer = m
        b = s.trust_belief
        need = s.active_need
        refs = s.reference_price or {}
        row = [
            int(tick), int(offset), int(segment), kind, int(stimulus),
            _r(pref.strength) if pref else None,
            _r(pref.recency) if pref else None,
            _r(goal.strength) if goal else None,
            _r(goal.urgency) if goal else None,
            _r(fat.strength) if fat else None,
            _r(viol.strength) if viol else None,
            _r(peer.valence) if peer else None,
            _r(peer.peer_trust) if peer else None,
            len(ctx.motifs),
            _r(traits.trust_orientation), _r(traits.deal_proneness),
            _r(traits.novelty_seeking),
            _r(stim.max_claimed_pct) if stim is not None else 0.0,
            bool(s.aware_of_brand),
            _r(b.value) if b else None, _r(b.evidence) if b else None,
            _r(s.adstock), int(s.exposures_72h), _r(s.current_price_gap),
            _r(s.budget_left, 4),
            bool(set(s.cart) & set(refs)),
            _r(min(refs.values()), 4) if refs else None,
            _r(need.strength) if need else None,
            _r(need.urgency) if need else None,
            _r(need.budget_cap, 4) if need else None,
            _r(coeffs.impulsivity), _r(coeffs.price_sensitivity),
            *(_r(coeffs.stage_base(st)) for st in STAGES),
            action.value if hasattr(action, "value") else str(action),
        ]
        self._fh.write(json.dumps(row, separators=(",", ":")) + "\n")
        self.n += 1

    def close(self) -> None:
        if self._fh is not None and not self._fh.closed:
            self._fh.flush()
            self._fh.close()


# ---------------------------------------------------------------------------
# reading + replay
# ---------------------------------------------------------------------------


def load(path: Path | str) -> tuple[dict, list[list]]:
    """(header, rows). Rows stay positional — `field(row, name)` reads them."""
    path = Path(path)
    with path.open() as fh:
        header = json.loads(fh.readline())
        if header.get("trace_version") != TRACE_VERSION:
            raise ValueError(
                f"{path.name}: trace_version {header.get('trace_version')}, "
                f"this build reads {TRACE_VERSION}")
        if tuple(header.get("fields", ())) != FIELDS:
            raise ValueError(f"{path.name}: field schema does not match this build")
        rows = [json.loads(line) for line in fh if line.strip()]
    return header, rows


def field(row: list, name: str):
    return row[_IDX[name]]


def rebuild(row: list) -> tuple[DecisionContext, object, StimulusFacts | None, ChoiceCoeffs, str]:
    """A traced row back into the exact arguments appraise()/decide() took.

    Motif dicts are rebuilt through DecisionContext.from_dict, so the validator
    that guards every real context guards replayed ones too — a trace that
    cannot round-trip fails loudly here rather than silently mis-scoring a fit.
    """
    from ..contracts.types import AppraisalTraits

    g = lambda n: field(row, n)  # noqa: E731
    motifs = []
    if g("pref_strength") is not None:
        motifs.append({"type": "preference_fit", "strength": g("pref_strength"),
                       "evidence": 2.0, "recency": g("pref_recency"),
                       "path": [1, "PREFERS", 5003, "CLAIMS", 2]})
    if g("goal_strength") is not None:
        motifs.append({"type": "goal_fit", "strength": g("goal_strength"),
                       "urgency": g("goal_urgency"),
                       "path": [1, "NEEDS", 5504, "IN_CATEGORY", 3, "OFFERS", 2]})
    if g("fatigue_strength") is not None:
        motifs.append({"type": "brand_semantic_fatigue", "strength": g("fatigue_strength"),
                       "recency": 1.0, "brand": 6001,
                       "path": [1, "SAW", 2, "CLAIMS", 5003, "CLAIMS", 2]})
    if g("violation_strength") is not None:
        motifs.append({"type": "expectation_violation", "strength": g("violation_strength"),
                       "path": [1, "EXPECTS", 5003, "NOT_SHOWN_BY", 4]})
    if g("social_valence") is not None:
        motifs.append({"type": "social_proof", "valence": g("social_valence"),
                       "peer_trust": g("social_peer_trust"), "experience": 1.0,
                       "path": [1, "TRUSTS_PERSON", 9, "BOUGHT", 3]})

    trust = None
    if g("trust_value") is not None:
        from ..contracts import evidence as ev
        e = g("trust_evidence")
        trust = {"value": g("trust_value"), "evidence": e, "confidence": ev.confidence(e)}
    need = None
    if g("need_strength") is not None:
        need = {"category": 5504, "strength": g("need_strength"),
                "urgency": g("need_urgency"), "budget_cap": g("need_budget_cap")}
    ref = {"3000001": g("ref_price_min")} if g("ref_price_min") is not None else {}
    ctx = DecisionContext.from_dict({
        "scalars": {
            "shopper_id": 1_000_000 + int(g("offset")),
            "aware_of_brand": bool(g("aware_of_brand")),
            "adstock": g("adstock"), "exposures_72h": int(g("exposures_72h")),
            "last_seen_t": None, "reference_price": ref,
            "current_price_gap": g("current_price_gap"),
            "budget_left": g("budget_left"),
            "cart": [3000001] if g("in_cart") else [],
            "trust_belief": trust, "quality_belief": None,
            "active_need": need, "habit": None,
        },
        "motifs": motifs,
    })
    traits = AppraisalTraits(
        trust_orientation=g("trust_orientation"),
        deal_proneness=g("deal_proneness"),
        novelty_seeking=g("novelty_seeking"))
    # max_claimed_pct is a derived property of `offers`, so the claimed deal is
    # replayed by putting it back on the offer it came from.
    pct = g("claimed_pct") or 0.0
    stim = StimulusFacts(
        stimulus_id=int(g("stimulus")), kind=g("kind"), brand_id=6001,
        claims={}, offers=({3000001: pct} if pct else {}),
        shows=frozenset(), products={})
    coeffs = ChoiceCoeffs(
        impulsivity=g("impulsivity"), price_sensitivity=g("price_sensitivity"),
        budget=g("budget_left"),
        stage_bases=tuple((st, g(f)) for st, f in zip(STAGES, _THETA_FIELDS)))
    return ctx, traits, stim, coeffs, g("kind")


def rebase_coeffs(coeffs: ChoiceCoeffs, traced_base, candidate_base) -> ChoiceCoeffs:
    """Move a traced shopper onto a candidate profile's stage bases.

    Exact, because segment theta_adjust and the per-shopper jitter are additive
    and independent of the calibration base (population/factory.py step 5)."""
    from dataclasses import replace

    old, new = dict(traced_base), dict(candidate_base)
    return replace(coeffs, stage_bases=tuple(
        (st, coeffs.stage_base(st) - old[st] + new[st]) for st in STAGES))


def retrofit(rows: list[list], *, traced_pref_half_life_days: float = 3.0,
             pref_half_life_days: float | None = None,
             violation_min_strength: float | None = None) -> list[list]:
    """Re-derive traced motif fields under candidate RETRIEVAL parameters.

    Retrieval constants cannot be replayed by re-scoring alone — they change
    what the read path produces, not what the mind does with it. Two of them can
    be recovered exactly from what the trace already stores, which is enough to
    fit the two that mattered:

      * `pref_recency` is `exp(-ln2 * age / half_life)`, and that is invertible:
        `age = -half_life * log2(recency)`. Recovering the age lets the recency
        be recomputed under any other half-life with no approximation.
      * `violation_min_strength` is a threshold on a value the row already
        carries, so applying a different floor is exact by construction.

    Anything else (fatigue_norm, adstock_half_life_s) needs a real run, because
    it depends on the SAW history rather than on a stored scalar. The fit says
    so rather than pretending otherwise.
    """
    if pref_half_life_days is None and violation_min_strength is None:
        return rows
    i_rec, i_viol = _IDX["pref_recency"], _IDX["violation_strength"]
    out = []
    for row in rows:
        row = list(row)
        rec = row[i_rec]
        if pref_half_life_days is not None and rec is not None and rec > 0.0:
            age_days = -traced_pref_half_life_days * math.log2(rec)
            row[i_rec] = round(2.0 ** (-age_days / pref_half_life_days), 6)
        if violation_min_strength is not None and row[i_viol] is not None:
            if row[i_viol] < violation_min_strength:
                row[i_viol] = None
        out.append(row)
    return out


def score(rows: list[list], *, appraisal_params=DEFAULT_APPRAISAL_PARAMS,
          choice_params=DEFAULT_CHOICE_PARAMS,
          stage_bases=None,
          traced_stage_bases=DEFAULT_STAGE_BASES) -> dict:
    """Model-implied funnel rates for a candidate calibration over traced rows.

    Returns mean gate probabilities, which are a far lower-variance estimator
    than realised counts: `buy_given_cart` is credible from a few thousand page
    decisions even when only a handful of purchases actually happened. The
    realised rates over the same rows come back too, so the caller can see how
    far the baseline sat from its own model.
    """
    # `stage_bases=None` means "score the run under its OWN profile". Defaulting
    # it to the module bases instead was a live footgun: a caller passing only
    # traced_stage_bases silently REBASED every shopper off the profile the run
    # actually used, and the resulting numbers looked plausible.
    if stage_bases is None:
        stage_bases = traced_stage_bases
    sums = {"CLICK": 0.0, "BROWSE": 0.0, "CART": 0.0, "BUY": 0.0}
    counts = {"CLICK": 0, "BROWSE": 0, "CART": 0, "BUY": 0}
    realised = {"creative": 0, "click": 0, "page": 0,
                "browse": 0, "cart": 0, "buy": 0, "bounce": 0}
    rebase = dict(traced_stage_bases) != dict(stage_bases)

    for row in rows:
        ctx, traits, stim, coeffs, kind = rebuild(row)
        if rebase:
            coeffs = rebase_coeffs(coeffs, traced_stage_bases, stage_bases)
        a = appraise(ctx, traits, stim, params=appraisal_params)
        probs = stage_probabilities(a, ctx.scalars, coeffs, kind=kind,
                                    params=choice_params)
        for stage, p in probs.items():
            sums[stage] += p
            counts[stage] += 1
        action = field(row, "action")
        if kind == "creative":
            realised["creative"] += 1
            realised["click"] += action == "CLICK"
        else:
            realised["page"] += 1
            realised["bounce"] += action == "BOUNCE"
            realised["browse"] += action in ("BROWSE", "CART", "BUY", "ABANDON")
            realised["cart"] += action in ("CART", "BUY", "ABANDON")
            realised["buy"] += action == "BUY"

    def mean(stage):
        return sums[stage] / counts[stage] if counts[stage] else None

    def ratio(num, den):
        return realised[num] / realised[den] if realised[den] else None

    p_click, p_browse = mean("CLICK"), mean("BROWSE")
    p_cart, p_buy = mean("CART"), mean("BUY")
    visit_to_purchase = None
    if None not in (p_browse, p_cart, p_buy):
        visit_to_purchase = p_browse * p_cart * p_buy
    return {
        "model": {
            "p_click": p_click,
            "p_browse": p_browse,
            "bounce_rate": None if p_browse is None else 1.0 - p_browse,
            "p_cart_given_browse": p_cart,
            "p_buy_given_cart": p_buy,
            "visit_to_purchase": visit_to_purchase,
            "buy_per_exposure": (None if None in (p_click, visit_to_purchase)
                                 else p_click * visit_to_purchase),
        },
        "realised": {
            "ctr": ratio("click", "creative"),
            "bounce_rate": ratio("bounce", "page"),
            "p_cart_given_browse": ratio("cart", "browse"),
            "p_buy_given_cart": ratio("buy", "cart"),
            "visit_to_purchase": ratio("buy", "page"),
        },
        "n": {"creative_decisions": realised["creative"], "page_decisions": realised["page"]},
    }
