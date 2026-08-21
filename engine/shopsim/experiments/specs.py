"""Experiment spec schemas (Phase 4, CONTRACT v3.4-draft).

Four spec types, one JSON envelope. A spec is the user-facing description of
an experiment; build.py expands it into an ordinary run_config. Everything a
spec says ends up inside the generated config's raw JSON, so config_hash pins
the whole experiment definition (Law 13).

Common envelope (every type):
    type          "ad_test" | "pricing" | "page_ab" | "scenario"
    name          experiment label (run_config label + runs registry key)
    seed          the ONE rng seed
    ticks, t0     experiment window — give each experiment a DISTINCT t0
                  window: PRICED_AT is global objective state and the as-of
                  reads key on t (v3.4-draft pricing convention)
    population    {size, personas?, social?}
                  social is the P1 trust layer (CONTRACT v3.9-draft): the same
                  {enabled, degree, rewire_p, weight_min, weight_max} block
                  run_config.population.social takes, validated by the one
                  authority — runner.config.parse_social — when the generated
                  config is loaded. Absent (the default) means the key is not
                  emitted at all, so every pre-social spec builds a
                  byte-identical config.
    mind          {decide?, consolidate?} — default formula/formula
    catalog, perception_cache, goal_config    default demo-brand paths
    calibration   optional 4.4 block (run_config "calibration" shape)
    scenario_packs  optional [pack names] from fixtures/scenarios/
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SPEC_TYPES = ("ad_test", "pricing", "page_ab", "scenario")

_DEF_PERSONAS = "fixtures/demo-brand/personas.json"
_DEF_CATALOG = "fixtures/demo-brand"
_DEF_CACHE = "fixtures/perception-cache"
_DEF_GOALS = "fixtures/demo-brand/goal_config.json"


@dataclass(frozen=True)
class BaseSpec:
    type: str
    name: str
    seed: int
    ticks: int
    t0: int
    population_size: int
    tick_seconds: int = 86_400
    personas: str = _DEF_PERSONAS
    catalog: str = _DEF_CATALOG
    perception_cache: str = _DEF_CACHE
    goal_config: str = _DEF_GOALS
    mind_decide: str = "formula"
    mind_consolidate: str = "formula"
    frequency_cap_per_tick: int = 2
    frequency_cap_72h: int = 6
    fulfillment_lag_ticks: int = 2
    sat_noise_sd: float = 0.08
    calibration: dict = field(default_factory=dict)
    social: dict = field(default_factory=dict)
    scenario_packs: tuple[str, ...] = ()
    raw: dict = field(default_factory=dict)  # the whole parsed spec


@dataclass(frozen=True)
class AdExperimentSpec(BaseSpec):
    """4.1: N creatives × audience × T days — ONE ARM PER CREATIVE, all arms
    sharing the seed. Identical populations, and with equal reach_prob the
    single-row exposure draws match across arms too: a clean paired design
    with no frequency-cap competition between creatives.

    market {shared, allocation} (v3.6-draft) switches to the opposite design:
    ONE arm carrying every creative row, so the ads compete for the same
    shoppers under the shared frequency caps. Paired isolation is traded away
    for a real market — which is the point when allocation is on."""

    creatives: tuple[dict, ...] = ()  # schedule-row dicts (creative_id, reach_prob, ...)
    market: dict = field(default_factory=dict)  # {"shared": bool, "allocation": {...}}


@dataclass(frozen=True)
class PricingExperimentSpec(BaseSpec):
    """4.2: promo schedule → PRICED_AT supersessions + PRICE_SEEN. Two arms:
    promo_off runs the SAME promo hook with every discount zeroed (PRICED_AT
    is shared objective state — the off arm must keep aligning the shelf, not
    skip it), promo_on runs the real schedule and is orchestrated LAST.

    discount_levels (v3.6-draft) replaces the pair with a LADDER: one arm per
    depth, ascending, each arm overriding every cycle's discount_pct with its
    own level. "Which discount does the population actually respond to" then
    reads straight off the arm comparison."""

    promo_schedule: str | None = None  # path, or None with inline product_promos
    product_promos: tuple[dict, ...] = ()  # inline alternative to the path
    exposure: tuple[dict, ...] = ()  # schedule rows — the funnel that sees prices
    discount_levels: tuple[float, ...] = ()  # e.g. (0.0, 0.1, 0.2, 0.3)


@dataclass(frozen=True)
class PageABExperimentSpec(BaseSpec):
    """4.3: seeded 50/50 within one run — a single schedule row with
    page_ids [a, b]; the (seed, "page", offset, creative) substream is the
    assignment. Per-variant funnels carry the comparison."""

    creative_id: int = 0
    page_ids: tuple[int, ...] = ()
    reach_prob: float = 0.3
    start_tick: int | None = None
    end_tick: int | None = None
    audience_segments: tuple[int, ...] | None = None
    split: tuple[float, ...] = (0.5, 0.5)


@dataclass(frozen=True)
class ScenarioRunSpec(BaseSpec):
    """4.5: a base config (or the demo defaults) + scenario packs, with an
    on/off arm pair as the demo lever."""

    base_config: str | None = None
    exposure: tuple[dict, ...] = ()
    promo_schedule: str | None = None
    promos_enabled: bool = False
    arms: tuple[dict, ...] = ()  # default: the pack's on/off pair


def _base_kwargs(raw: dict) -> dict:
    pop = raw["population"]
    mind = raw.get("mind", {})
    return dict(
        type=raw["type"],
        name=str(raw["name"]),
        seed=int(raw["seed"]),
        ticks=int(raw["ticks"]),
        t0=int(raw["t0"]),
        tick_seconds=int(raw.get("tick_seconds", 86_400)),
        population_size=int(pop["size"]),
        personas=str(pop.get("personas", _DEF_PERSONAS)),
        catalog=str(raw.get("catalog", _DEF_CATALOG)),
        perception_cache=str(raw.get("perception_cache", _DEF_CACHE)),
        goal_config=str(raw.get("goal_config", _DEF_GOALS)),
        mind_decide=str(mind.get("decide", "formula")),
        mind_consolidate=str(mind.get("consolidate", "formula")),
        frequency_cap_per_tick=int(raw.get("frequency_cap_per_tick", 2)),
        frequency_cap_72h=int(raw.get("frequency_cap_72h", 6)),
        fulfillment_lag_ticks=int(raw.get("fulfillment", {}).get("lag_ticks", 2)),
        sat_noise_sd=float(raw.get("fulfillment", {}).get("sat_noise_sd", 0.08)),
        calibration=dict(raw.get("calibration", {})),
        social=dict(pop.get("social", {})),
        scenario_packs=tuple(raw.get("scenario_packs", ())),
        raw=raw,
    )


_MARKET_KEYS = {"shared", "allocation"}
_ALLOC_KEYS = {"enabled", "prior_exposures", "prior_clicks", "floor_share", "power"}


def _market_problems(market: dict, n_creatives: int) -> list[str]:
    """ad_test market{} validation (v3.6-draft). Unknown keys are refused the
    way parse_calibration refuses them: a typo must never be silently ignored
    into a run whose config_hash then claims it was honored."""
    if not market:
        return []
    problems: list[str] = []
    bad = set(market) - _MARKET_KEYS
    if bad:
        problems.append(f"market: unknown keys {sorted(bad)}")
    shared = market.get("shared", False)
    if not isinstance(shared, bool):
        problems.append("market.shared must be a bool")
    if shared and n_creatives < 2:
        problems.append("market.shared needs at least 2 creatives — a market "
                        "of one is just the single-arm path")
    alloc = market.get("allocation", {})
    if alloc:
        if not isinstance(alloc, dict):
            problems.append("market.allocation must be an object")
        else:
            bad_alloc = set(alloc) - _ALLOC_KEYS
            if bad_alloc:
                problems.append(f"market.allocation: unknown keys {sorted(bad_alloc)}")
            if alloc.get("enabled") and not shared:
                problems.append("market.allocation needs market.shared — "
                                "isolated arms have nothing to reallocate between")
            floor = float(alloc.get("floor_share", 0.05))
            if not 0.0 <= floor < 1.0 / max(n_creatives, 1):
                problems.append(
                    f"market.allocation.floor_share must be in [0, 1/N) = "
                    f"[0, {1.0 / max(n_creatives, 1):.3f}) for {n_creatives} "
                    "creatives (N floors must leave room to redistribute)")
            if float(alloc.get("power", 2.0)) < 0.0:
                problems.append("market.allocation.power must be >= 0")
            for key in ("prior_exposures", "prior_clicks"):
                if float(alloc.get(key, 1.0)) <= 0.0:
                    problems.append(f"market.allocation.{key} must be > 0 "
                                    "(the prior is what makes day 0 uniform)")
    return problems


def load_spec(path: Path | str):
    raw = json.loads(Path(path).read_text())
    return parse_spec(raw)


def parse_spec(raw: dict):
    stype = raw.get("type")
    if stype not in SPEC_TYPES:
        raise ValueError(f"spec type must be one of {SPEC_TYPES}, got {stype!r}")
    base = _base_kwargs(raw)
    ticks = base["ticks"]
    problems: list[str] = []

    if stype == "ad_test":
        creatives = []
        for row in raw.get("creatives", ()):
            r = dict(row)
            r.setdefault("start_tick", 0)
            r.setdefault("end_tick", ticks - 1)
            creatives.append(r)
        if not creatives:
            problems.append("ad_test needs at least one creatives[] row")
        seen = [r["creative_id"] for r in creatives]
        if len(set(seen)) != len(seen):
            problems.append("ad_test creatives must be unique (one arm per creative)")
        market = dict(raw.get("market", {}))
        problems.extend(_market_problems(market, len(creatives)))
        spec = AdExperimentSpec(**base, creatives=tuple(creatives), market=market)

    elif stype == "pricing":
        promo = raw.get("promo", {})
        schedule = promo.get("schedule")
        inline = tuple(promo.get("product_promos", ()))
        if (schedule is None) == (not inline):
            problems.append("pricing needs exactly one of promo.schedule (path) "
                            "or promo.product_promos (inline)")
        exposure = tuple(raw.get("exposure", {}).get("schedule", ()))
        if not exposure:
            problems.append("pricing needs exposure.schedule rows — without a "
                            "funnel nobody ever sees a price")
        levels = tuple(float(x) for x in raw.get("discount_levels", ()))
        if levels:
            if len(set(levels)) != len(levels):
                problems.append("pricing discount_levels must be distinct")
            if any(not 0.0 <= x <= 0.9 for x in levels):
                problems.append("pricing discount_levels must each be in [0, 0.9]")
            if len(levels) < 2:
                problems.append("pricing discount_levels needs at least 2 levels "
                                "(one level is just a single-arm run)")
        spec = PricingExperimentSpec(
            **base, promo_schedule=schedule, product_promos=inline,
            exposure=exposure, discount_levels=levels)

    elif stype == "page_ab":
        page_ids = tuple(int(p) for p in raw.get("page_ids", ()))
        if len(page_ids) != 2 or len(set(page_ids)) != 2:
            problems.append("page_ab needs exactly two distinct page_ids")
        split = tuple(float(s) for s in raw.get("split", (0.5, 0.5)))
        if split != (0.5, 0.5):
            problems.append("page_ab split must be [0.5, 0.5] at P0 "
                            "(the seeded substream is a fair coin)")
        if "creative_id" not in raw:
            problems.append("page_ab needs creative_id")
        spec = PageABExperimentSpec(
            **base,
            creative_id=int(raw.get("creative_id", 0)),
            page_ids=page_ids,
            reach_prob=float(raw.get("reach_prob", 0.3)),
            start_tick=(int(raw["start_tick"]) if "start_tick" in raw else None),
            end_tick=(int(raw["end_tick"]) if "end_tick" in raw else None),
            audience_segments=(tuple(int(s) for s in raw["audience_segments"])
                               if raw.get("audience_segments") else None),
            split=split)

    else:  # scenario
        if not base["scenario_packs"]:
            problems.append("scenario needs scenario_packs")
        spec = ScenarioRunSpec(
            **base,
            base_config=raw.get("base_config"),
            exposure=tuple(raw.get("exposure", {}).get("schedule", ())),
            promo_schedule=raw.get("promo", {}).get("schedule"),
            promos_enabled=bool(raw.get("promo", {}).get("enabled", False)),
            arms=tuple(raw.get("arms", ())))

    if problems:
        raise ValueError(f"invalid {stype} spec: " + "; ".join(problems))
    return spec


# -- scenario packs ---------------------------------------------------------


def scenarios_dir(root: Path) -> Path:
    return root / "fixtures" / "scenarios"


def _module_repo_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "fixtures").is_dir() and (parent / "engine").is_dir():
            return parent
    return None


def load_pack(root: Path, name: str) -> dict:
    """Pack lookup: the experiment root first, then the repo the package
    ships in — specs living outside the repo (tests, tmp dirs) still find
    the committed packs."""
    dirs = [scenarios_dir(root)]
    mod_root = _module_repo_root()
    if mod_root is not None and scenarios_dir(mod_root) not in dirs:
        dirs.append(scenarios_dir(mod_root))
    path = next((d / f"{name}.json" for d in dirs if (d / f"{name}.json").exists()),
                None)
    if path is None:
        have = sorted({p.stem for d in dirs if d.is_dir()
                       for p in d.glob("*.json")})
        raise ValueError(f"unknown scenario pack {name!r} (have {have})")
    pack = json.loads(path.read_text())
    status = pack.get("status", "P0")
    if status != "P0":
        raise ValueError(
            f"scenario pack {name!r} is {status}: "
            + pack.get("reason", "not implemented at P0"))
    return pack
