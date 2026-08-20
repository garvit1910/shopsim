"""Decision-preview math shared by the API and the graph exporter.

These are the pure bodies of api.py's `_preview_ctx` / `_population` /
`decision_preview` (CONTRACT v3.5-draft item 2), lifted so that
`export-graph --previews` (v3.12-draft) can bake the exact same envelope into
the frozen Shopper Mind capture without FastAPI in the room. The API keeps its
caching, locking and HTTP error translation and delegates here — no math
change, and Law 12/15 unchanged: traits/coeffs stay inside the process, only
appraisal dims and gate probabilities leave.
"""

from __future__ import annotations

from dataclasses import is_dataclass, replace
from enum import Enum
from functools import partial


def _jsonable(obj):
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f: _jsonable(getattr(obj, f)) for f in obj.__dataclass_fields__}
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def build_preview_ctx(cfg, arm_name: str) -> dict:
    """The per-run immutable preview context: objective view, bound mind,
    choice params, and the seeded page router. Raises ValueError when the
    perception cache is incomplete (callers translate: API -> 503, CLI ->
    plain error)."""
    from ..minds import FormulaMind, ObjectiveView
    from ..perception.cache import perceived_maps
    from ..perception.perceive import perceive_catalog
    from . import steps

    def _no_llm(*_a, **_k):
        raise ValueError("perception cache incomplete for this run")

    perceived, calls = perceive_catalog(
        cfg.catalog_dir, cache_dir=cfg.perception_cache, call=_no_llm)
    assert calls == 0
    claims, offers = perceived_maps(perceived)
    view = ObjectiveView.from_catalog(cfg.catalog_dir, claims, offers)
    ap, cp, _sb = cfg.calibration()
    arm = cfg.arm(arm_name)
    sched = cfg.schedule_for(arm)
    page_of = partial(steps.page_for, cfg.seed,
                      cfg.page_splits(sched), cfg.resolve_pages(view, sched))
    return {"view": view,
            "mind": FormulaMind(view, appraisal_params=ap, choice_params=cp),
            "cp": cp, "page_of": page_of, "sched": sched}


def build_population(cfg, run_index: int):
    """Deterministic population recompute — (specs, shoppers). Traits/coeffs
    live only in the returned objects; they must never be serialized."""
    from ..population.factory import (
        PopulationConfig, generate_population, load_segment_specs)
    _ap, _cp, stage_bases = cfg.calibration()
    specs = load_segment_specs(cfg.personas_path)
    shoppers = generate_population(PopulationConfig(
        seed=cfg.seed, population_size=cfg.population_size,
        segments=specs, run_index=run_index,
        stage_bases=stage_bases))
    return specs, shoppers


def compute_preview(pv: dict, ctx, shopper, offset: int,
                    stimulus_id: int, tick: int) -> dict:
    """The decision-preview envelope for one (shopper, stimulus) — real math,
    no rng. Raises ValueError for a stimulus the objective view doesn't know."""
    from ..minds.choice import stage_probabilities

    facts = pv["view"].facts(stimulus_id)
    if facts is None:
        raise ValueError(f"unknown stimulus {stimulus_id}")
    bound = pv["mind"].for_stimulus(stimulus_id)
    a = bound.appraise(ctx, shopper.traits)
    probs = stage_probabilities(a, ctx.scalars, shopper.coeffs,
                                kind=facts.kind, params=pv["cp"])
    counterfactual = None
    if ctx.scalars.active_need is not None:
        ctx2 = replace(
            ctx,
            scalars=replace(ctx.scalars, active_need=None),
            motifs=[m for m in ctx.motifs if m.type.value != "goal_fit"])
        a2 = bound.appraise(ctx2, shopper.traits)
        counterfactual = {
            "label": "same context, need removed",
            "appraisal": _jsonable(a2),
            "probabilities": stage_probabilities(
                a2, ctx2.scalars, shopper.coeffs, kind=facts.kind,
                params=pv["cp"]),
        }
    return {
        "tick": tick,
        "stimulus": {"id": stimulus_id, "kind": facts.kind,
                     "page_id": (pv["page_of"](offset, stimulus_id)
                                 if facts.kind == "creative" else None)},
        "scalars": _jsonable(ctx.scalars),
        "motifs": _jsonable(list(ctx.motifs)),
        "appraisal": _jsonable(a),
        "probabilities": probs,
        "counterfactual_need_off": counterfactual,
    }
