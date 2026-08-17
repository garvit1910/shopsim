"""Read path: objective/stimulus/peer caches + per-shopper retrieval + the
Python assembly of every scalar and motif (C1 DecisionContext).

Routing (Phase 1.1 probe, recorded in CONTRACT.md): Route B everywhere —
SPpaths is strictly direction-following, and every motif path traverses at
least one edge against its stored direction, so motifs are per-shopper
single-hop reads joined in Python against the cached stimulus subgraph.

Abstention is structural: no live PREFERS overlap -> no preference_fit; no
matching live NEEDS -> active_need null AND no goal_fit (the validator
enforces the biconditional); no HOLDS row for the stimulus brand -> null
trust_belief. Nothing is fabricated to fill a field (C1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..contracts import evidence
from ..contracts.enums import MotifType
from ..contracts.ids import CREATIVE_BASE, PAGE_VARIANT_BASE, PRODUCT_BASE
from . import cypher, schema
from .client import HydraClient, Statement


def _decay(age_s: float, half_life_s: float) -> float:
    return math.exp(-math.log(2.0) * max(age_s, 0.0) / half_life_s)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ---------------------------------------------------------------------------
# objective / stimulus cache
# ---------------------------------------------------------------------------


@dataclass
class StimulusView:
    """One stimulus's slice of the objective world, per (stimulus, tick)."""

    stimulus_id: int
    kind: str  # "creative" | "page"
    brand_id: int
    claims: dict[int, float] = field(default_factory=dict)  # concept -> strength
    offers: dict[int, float] = field(default_factory=dict)  # product -> claimed_pct
    shows: frozenset[int] = frozenset()  # page concepts
    products: dict[int, int] = field(default_factory=dict)  # product -> category
    prices: dict[int, float] = field(default_factory=dict)  # product -> current price


class ObjectiveCache:
    """The whole objective layer, rebuilt lazily once per tick (~50 cheap
    singles). Makes fatigue/saturation pure Python: past-creative claims
    never need per-decision queries."""

    def __init__(self, client: HydraClient):
        self.client = client
        self.creatives: dict[int, dict] = {}
        self.pages: dict[int, dict] = {}
        self.product_category: dict[int, int] = {}
        self.product_brand: dict[int, int] = {}
        self.prices: dict[int, float] = {}
        self.promotes: dict[int, int] = {}
        self._built_at: int | None = None

    def build(self, now: int) -> None:
        if self._built_at == now:
            return
        c = self.client
        listed = [r["dst"] for r in c.run_stmt(cypher.all_edges("LISTS", schema.CATALOG_ID))]
        creative_ids = [i for i in listed if CREATIVE_BASE <= i < PRODUCT_BASE]
        product_ids = [i for i in listed if PRODUCT_BASE <= i < PAGE_VARIANT_BASE]
        page_ids = [i for i in listed if i >= PAGE_VARIANT_BASE]

        for pid in product_ids:
            cat = c.run_stmt(cypher.all_edges("IN_CATEGORY", pid))
            self.product_category[pid] = cat[0]["dst"] if cat else 0
            brand = c.run_stmt(cypher.all_edges("SOLD_BY", pid))
            self.product_brand[pid] = brand[0]["dst"] if brand else 0
            # as-of-now selection (not bare liveness): a completed branch arm
            # or a prior run leaves future/parallel PRICED_AT versions live;
            # the price *at* now is the newest version opened at or before now.
            price = [r for r in c.run_stmt(cypher.all_edges(
                "PRICED_AT", pid, ("price", "t", "valid_to")))
                if r["t"] <= now < r["valid_to"]]
            if price:
                self.prices[pid] = max(price, key=lambda r: r["t"])["price"]

        for cid in creative_ids:
            claims = {r["dst"]: r["strength"] for r in c.run_stmt(
                cypher.all_edges("CLAIMS", cid, ("strength",)))}
            offers = {r["dst"]: r["claimed_pct"] for r in c.run_stmt(
                cypher.all_edges("OFFERS", cid, ("claimed_pct",)))}
            promoted = c.run_stmt(cypher.all_edges("PROMOTES", cid))
            brand = promoted[0]["dst"] if promoted else 0
            self.creatives[cid] = {"brand": brand, "claims": claims, "offers": offers}
            self.promotes[cid] = brand

        for pgid in page_ids:
            shows = frozenset(r["dst"] for r in c.run_stmt(cypher.all_edges("SHOWS", pgid)))
            target = c.run_stmt(cypher.all_edges("PAGE_FOR", pgid))
            prod = target[0]["dst"] if target else 0
            self.pages[pgid] = {"product": prod, "shows": shows,
                                "brand": self.product_brand.get(prod, 0)}
        self._built_at = now

    def stimulus_view(self, stimulus_id: int) -> StimulusView:
        if stimulus_id in self.creatives:
            cr = self.creatives[stimulus_id]
            products = {p: self.product_category.get(p, 0) for p in cr["offers"]}
            return StimulusView(
                stimulus_id=stimulus_id, kind="creative", brand_id=cr["brand"],
                claims=dict(cr["claims"]), offers=dict(cr["offers"]), products=products,
                prices={p: self.prices[p] for p in products if p in self.prices})
        if stimulus_id in self.pages:
            pg = self.pages[stimulus_id]
            prod = pg["product"]
            return StimulusView(
                stimulus_id=stimulus_id, kind="page", brand_id=pg["brand"],
                shows=pg["shows"], products={prod: self.product_category.get(prod, 0)},
                prices={prod: self.prices[prod]} if prod in self.prices else {})
        raise KeyError(f"unknown stimulus {stimulus_id} (not LISTS-registered)")


# ---------------------------------------------------------------------------
# per-shopper raw reads
# ---------------------------------------------------------------------------

# (name, statement builder) — executed in order via run_grouped, results
# zipped back by index.


def shopper_read_plan(
    shopper_id: int, now: int, params: schema.RetrievalParams, stim: StimulusView
) -> list[tuple[str, Statement]]:
    plan: list[tuple[str, Statement]] = [
        ("saw", cypher.events_since("SAW", shopper_id, now - params.saw_window_seconds, ("t",))),
        ("prefers", cypher.live_edges("PREFERS", shopper_id, now, ("w", "evidence", "t"))),
        ("needs", cypher.live_edges("NEEDS", shopper_id, now,
                                    ("strength", "budget_cap", "deadline_t"))),
        ("holds", cypher.live_holds(shopper_id, now)),
        ("expects", cypher.live_edges("EXPECTS", shopper_id, now, ("about", "strength"))),
        ("ref_price", cypher.live_edges("REFERENCE_PRICE", shopper_id, now, ("price",))),
        ("habit", cypher.live_edges("HABIT", shopper_id, now, ("evidence",))),
        ("bought", cypher.all_edges("BOUGHT", shopper_id, ("t", "price"))),
        ("carted", cypher.all_edges("CARTED", shopper_id, ("t",))),
        ("abandoned", cypher.all_edges("ABANDONED", shopper_id, ("t",))),
        ("props", cypher.node_props("shopper", shopper_id, ("segment_id", "budget"))),
        ("trusts", cypher.all_edges("TRUSTS_PERSON", shopper_id, ("w",))),
    ]
    if stim.kind == "page":
        plan.append(("visited", cypher.all_edges("VISITED", shopper_id, ("t",))))
    return plan


def peer_read_plan(peer_id: int) -> list[tuple[str, Statement]]:
    return [
        ("peer_bought", cypher.all_edges("BOUGHT", peer_id, ("t", "price"))),
        ("peer_experienced", cypher.all_edges("EXPERIENCED", peer_id, ("t", "sat"))),
    ]


# ---------------------------------------------------------------------------
# assembly (pure — unit-testable without a database)
# ---------------------------------------------------------------------------


def assemble_context(
    shopper_id: int,
    rows: dict[str, list[dict]],
    stim: StimulusView,
    cache: ObjectiveCache,
    peers: dict[int, dict[str, list[dict]]],
    now: int,
    tick_start: int,
    params: schema.RetrievalParams,
    *,
    trace: bool = False,
) -> dict[str, Any]:
    """Build the C1 payload dict from raw rows. With trace=True, thresholds
    relax, all candidate motifs are kept, and explanatory motifs appear."""

    saw = [(r["dst"], r["t"]) for r in rows.get("saw", ())]
    prefers = {r["dst"]: (r["w"], r["evidence"], r["t"]) for r in rows.get("prefers", ())}
    needs = {r["dst"]: (r["strength"], r["budget_cap"], r["deadline_t"])
             for r in rows.get("needs", ())}
    holds = rows.get("holds", ())
    expects = [(r["dst"], r["about"], r["strength"]) for r in rows.get("expects", ())]
    ref_price = {r["dst"]: r["price"] for r in rows.get("ref_price", ())}
    habits = {r["dst"]: r["evidence"] for r in rows.get("habit", ())}
    bought = [(r["dst"], r["t"], r.get("price") or 0.0) for r in rows.get("bought", ())]
    carted = [(r["dst"], r["t"]) for r in rows.get("carted", ())]
    abandoned = [(r["dst"], r["t"]) for r in rows.get("abandoned", ())]
    props = rows.get("props", [{}])
    trusts = {r["dst"]: r["w"] for r in rows.get("trusts", ())}
    visited = [(r["dst"], r["t"]) for r in rows.get("visited", ())]

    # -- scalars ------------------------------------------------------------
    brand_creatives = {cid for cid, meta in cache.creatives.items()
                       if meta["brand"] == stim.brand_id}
    brand_saw = [(cid, t) for cid, t in saw if cid in brand_creatives]
    aware = bool(brand_saw)
    adstock = sum(_decay(now - t, params.adstock_half_life_s) for _, t in brand_saw)

    if stim.kind == "creative":
        own = [t for cid, t in saw if cid == stim.stimulus_id]
    else:
        own = [t for pgid, t in visited if pgid == stim.stimulus_id]
    exposures_72h = sum(1 for t in own if now - t <= params.freq_window_seconds)
    last_seen_t = max(own) if own else None

    stim_ref = {p: ref_price[p] for p in stim.products if p in ref_price}
    primary = next(iter(stim.products), None)
    gap = 0.0
    if primary is not None and primary in stim_ref and stim_ref[primary] > 0 \
            and primary in stim.prices:
        gap = (stim.prices[primary] - stim_ref[primary]) / stim_ref[primary]

    budget = props[0].get("budget") if props else None
    budget = params.budget_default if budget is None else budget
    budget_left = budget - sum(p for _, _, p in bought)

    # A purchase or abandonment resolves only carts made AT OR BEFORE it —
    # a later re-cart of a previously bought product is live again (repeat
    # purchases, e.g. across promo cycles; v3.4-draft bug-fix: the old
    # any-historical-BOUGHT exclusion desynced from the runner's cart state
    # and crashed resumed-cart expansion on the second cycle).
    cart = sorted({pid for pid, t in carted
                   if not any(b_pid == pid and b_t >= t for b_pid, b_t, _ in bought)
                   and not any(a_pid == pid and a_t >= t for a_pid, a_t in abandoned)})

    def belief_scalar(aspect: int):
        for r in holds:
            if r["about_id"] == stim.brand_id and r["that_id"] == aspect:
                e = r["evidence"]
                return {"value": r["value"], "evidence": e,
                        "confidence": evidence.confidence(e)}
        return None

    trust_belief = belief_scalar(schema.ASPECT_TRUST_ID)
    quality_belief = belief_scalar(schema.ASPECT_QUALITY_ID)

    habit_scalar = None
    if habits:
        stim_h = evidence.habit_strength(habits.get(stim.brand_id, 0.0))
        rival = [evidence.habit_strength(e) for b, e in habits.items() if b != stim.brand_id]
        habit_scalar = {"stim_brand": stim_h, "rival_max": max(rival) if rival else 0.0}

    # -- motifs -------------------------------------------------------------
    motifs: list[dict] = []

    # preference_fit: live PREFERS ∩ stimulus claims
    pref_min = 0.0 if trace else params.pref_min_w
    claim_min = 0.0 if trace else params.claim_min_strength
    pref_hits = []
    for concept, strength in stim.claims.items():
        if strength < claim_min or concept not in prefers:
            continue
        w, e, t = prefers[concept]
        if w < pref_min:
            continue
        pref_hits.append((w * strength, {
            "type": MotifType.PREFERENCE_FIT.value, "strength": w, "evidence": e,
            "recency": _decay(now - t, params.recency_half_life_s),
            "path": [shopper_id, "PREFERS", concept, "CLAIMS", stim.stimulus_id]}))
    pref_hits.sort(key=lambda x: -x[0])
    motifs += [m for _, m in (pref_hits if trace else pref_hits[:1])]

    # goal_fit + the active_need scalar (emitted iff matched — biconditional)
    active_need = None
    goal_hits = []
    for pid, cat in stim.products.items():
        if cat in needs:
            strength, cap, deadline = needs[cat]
            urgency = _clamp01(1.0 - (deadline - now) / params.urgency_horizon_s)
            edge_label = "OFFERS" if stim.kind == "creative" else "PAGE_FOR"
            goal_hits.append((strength * urgency, cat, cap, urgency, {
                "type": MotifType.GOAL_FIT.value, "strength": strength, "urgency": urgency,
                "path": [shopper_id, "NEEDS", cat, "IN_CATEGORY", pid,
                         edge_label, stim.stimulus_id]}))
    if goal_hits:
        goal_hits.sort(key=lambda x: -x[0])
        best = goal_hits[0]
        active_need = {"category": best[1], "strength": best[4]["strength"],
                       "urgency": best[3], "budget_cap": best[2]}
        motifs += [g[4] for g in (goal_hits if trace else goal_hits[:1])]

    # brand_semantic_fatigue / concept_saturation: past SAW creatives sharing
    # a claimed concept with the stimulus, split by same/other brand
    fatigue_contrib: list[tuple[float, int, int, int]] = []  # (r, t, cid, shared)
    saturation_contrib: list[tuple[float, int, int, int]] = []
    for cid, t in saw:
        if cid == stim.stimulus_id:
            continue
        meta = cache.creatives.get(cid)
        if meta is None:
            continue
        shared = [c for c in meta["claims"] if c in stim.claims]
        if not shared:
            continue
        r = _decay(now - t, params.recency_half_life_s)
        row = (r, t, cid, shared[0])
        if meta["brand"] == stim.brand_id:
            fatigue_contrib.append(row)
        else:
            saturation_contrib.append(row)

    if fatigue_contrib:
        fatigue_contrib.sort(key=lambda x: -x[1])
        r_sum = sum(r for r, _, _, _ in fatigue_contrib)
        _, _, recent_cid, shared = fatigue_contrib[0]
        motifs.append({
            "type": MotifType.BRAND_SEMANTIC_FATIGUE.value,
            "strength": min(1.0, r_sum / params.fatigue_norm),
            "recency": fatigue_contrib[0][0], "brand": stim.brand_id,
            "path": [shopper_id, "SAW", recent_cid, "CLAIMS", shared,
                     "CLAIMS", stim.stimulus_id]})
    if saturation_contrib:
        saturation_contrib.sort(key=lambda x: -x[1])
        r_sum = sum(r for r, _, _, _ in saturation_contrib)
        _, _, recent_cid, shared = saturation_contrib[0]
        motifs.append({
            "type": MotifType.CONCEPT_SATURATION.value,
            "strength": min(1.0, r_sum / params.saturation_norm),
            "path": [shopper_id, "SAW", recent_cid, "CLAIMS", shared,
                     "CLAIMS", stim.stimulus_id]})

    # expectation_violation: page stimuli only — EXPECTS(brand) minus SHOWS
    if stim.kind == "page":
        violated = [(s, concept) for concept, about, s in expects
                    if about == stim.brand_id and concept not in stim.shows]
        if violated:
            violated.sort(key=lambda x: -x[0])
            strength, concept = violated[0]
            motifs.append({
                "type": MotifType.EXPECTATION_VIOLATION.value, "strength": strength,
                "path": [shopper_id, "EXPECTS", concept, "NOT_SHOWN_BY", stim.stimulus_id]})

    # social_proof (P1): trusted peers' pre-tick BOUGHT on stimulus products
    social_hits = []
    for peer, w in trusts.items():
        peer_rows = peers.get(peer, {})
        p_bought = [(r["dst"], r["t"]) for r in peer_rows.get("peer_bought", ())
                    if r["dst"] in stim.products and r["t"] < tick_start]
        if not p_bought:
            continue
        pid, _ = max(p_bought, key=lambda x: x[1])
        exps = [r["sat"] for r in peer_rows.get("peer_experienced", ())
                if r["dst"] == pid and r["t"] < tick_start]
        experience = exps[-1] if exps else params.social_default_experience
        valence = _clamp01((w * (2 * experience - 1) + 1) / 2)
        social_hits.append((w, {
            "type": MotifType.SOCIAL_PROOF.value, "valence": valence,
            "peer_trust": w, "experience": experience,
            "path": [shopper_id, "TRUSTS_PERSON", peer, "BOUGHT", pid]}))
    social_hits.sort(key=lambda x: -x[0])
    motifs += [m for _, m in (social_hits if trace else social_hits[:1])]

    if trace:
        # explanatory motifs (get_trace only — never in DecisionContext.motifs)
        for pid, t, _ in bought:
            b = cache.product_brand.get(pid)
            if b == stim.brand_id:
                motifs.append({"type": MotifType.HABIT_PATH.value,
                               "path": [shopper_id, "BOUGHT", pid, "SOLD_BY", b]})
        for r in rows.get("experienced_self", ()):
            pid = r["dst"]
            b = cache.product_brand.get(pid)
            if b == stim.brand_id:
                motifs.append({"type": MotifType.EXPERIENCE_PATH.value,
                               "path": [shopper_id, "EXPERIENCED", pid, "SOLD_BY", b]})

    return {
        "scalars": {
            "shopper_id": shopper_id,
            "aware_of_brand": aware,
            "adstock": adstock,
            "exposures_72h": exposures_72h,
            "last_seen_t": last_seen_t,
            "reference_price": {str(k): v for k, v in stim_ref.items()},
            "current_price_gap": gap,
            "budget_left": budget_left,
            "cart": cart,
            "trust_belief": trust_belief,
            "quality_belief": quality_belief,
            "active_need": active_need,
            "habit": habit_scalar,
        },
        "motifs": motifs,
    }
