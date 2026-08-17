"""RunConfig — the run_config.json schema, loading, validation, and hashing.

config_hash = sha256 of the canonical raw JSON + the arm name (CONTRACT v3.3:
it rides in the run manifest; resume refuses on any mismatch, branch allows
exactly this one hash to differ).

Shopper ids inside configs (goal_config scripted rows) are block-0-anchored
and remapped by offset into the active run block (CONTRACT v3.3).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


def canonical_json(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True)


def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for cand in (p, *p.parents):
        if (cand / "fixtures").is_dir() and (cand / "engine").is_dir():
            return cand
    # test configs live outside the repo and use absolute paths; the start
    # dir then anchors the run store (runs/ lands next to the config)
    return p


@dataclass(frozen=True)
class ScheduleRow:
    creative_id: int
    start_tick: int
    end_tick: int  # inclusive
    reach_prob: float
    page_id: int | None = None  # overrides the default page resolution


@dataclass(frozen=True)
class ArmSpec:
    name: str
    goal_overrides: dict = field(default_factory=dict)
    branch_from: str | None = None
    divergence_tick: int | None = None


_MINDS = ("scripted", "formula")


@dataclass
class RunConfig:
    label: str
    seed: int
    ticks: int
    t0: int
    tick_seconds: int
    mind_decide: str
    mind_consolidate: str
    population_size: int
    personas_path: Path
    catalog_dir: Path
    perception_cache: Path
    schedule: tuple[ScheduleRow, ...]
    frequency_cap_per_tick: int
    frequency_cap_72h: int
    goal_config_path: Path
    goal_overrides_base: dict
    fulfillment_lag_ticks: int
    sat_noise_sd: float
    promo_path: Path | None
    promos_enabled: bool
    arms: tuple[ArmSpec, ...]
    raw: dict
    root: Path

    # -- loading -------------------------------------------------------------

    @classmethod
    def load(cls, path: Path | str) -> "RunConfig":
        path = Path(path)
        raw = json.loads(path.read_text())
        root = find_repo_root(path.parent)

        def rp(p: str) -> Path:
            return (root / p).resolve()

        mind = raw.get("mind", {})
        exposure = raw.get("exposure", {})
        rows = tuple(sorted(
            (ScheduleRow(
                creative_id=int(r["creative_id"]),
                start_tick=int(r["start_tick"]),
                end_tick=int(r["end_tick"]),
                reach_prob=float(r["reach_prob"]),
                page_id=int(r["page_id"]) if r.get("page_id") is not None else None,
            ) for r in exposure.get("schedule", ())),
            key=lambda r: (r.creative_id, r.start_tick)))
        goals = raw.get("goals", {})
        fulfillment = raw.get("fulfillment", {})
        promos = raw.get("promos", {})
        arms = tuple(
            ArmSpec(
                name=a["name"],
                goal_overrides=dict(a.get("goal_overrides", {})),
                branch_from=a.get("branch_from"),
                divergence_tick=(int(a["divergence_tick"])
                                 if a.get("divergence_tick") is not None else None),
            )
            for a in raw.get("arms", ({"name": "main"},))
        )

        cfg = cls(
            label=str(raw["label"]),
            seed=int(raw["seed"]),
            ticks=int(raw["ticks"]),
            t0=int(raw["t0"]),
            tick_seconds=int(raw.get("tick_seconds", 86_400)),
            mind_decide=mind.get("decide", "scripted"),
            mind_consolidate=mind.get("consolidate", "formula"),
            population_size=int(raw["population"]["size"]),
            personas_path=rp(raw["population"]["personas"]),
            catalog_dir=rp(raw.get("catalog_dir", "fixtures/demo-brand")),
            perception_cache=rp(raw.get("perception_cache", "fixtures/perception-cache")),
            schedule=rows,
            frequency_cap_per_tick=int(exposure.get("frequency_cap_per_tick", 2)),
            frequency_cap_72h=int(exposure.get("frequency_cap_72h", 6)),
            goal_config_path=rp(goals.get("config", "fixtures/demo-brand/goal_config.json")),
            goal_overrides_base=dict(goals.get("overrides", {})),
            fulfillment_lag_ticks=int(fulfillment.get("lag_ticks", 2)),
            sat_noise_sd=float(fulfillment.get("sat_noise_sd", 0.08)),
            promo_path=(rp(promos["schedule"]) if promos.get("schedule") else None),
            promos_enabled=bool(promos.get("enabled", False)),
            arms=arms,
            raw=raw,
            root=root,
        )
        cfg.validate()
        return cfg

    # -- validation ----------------------------------------------------------

    def validate(self) -> None:
        problems = []
        if self.ticks <= 0:
            problems.append("ticks must be positive")
        if self.population_size <= 0:
            problems.append("population.size must be positive")
        if self.mind_decide not in _MINDS or self.mind_consolidate not in _MINDS:
            problems.append(f"mind.decide/consolidate must be one of {_MINDS}")
        for p in (self.personas_path, self.catalog_dir, self.goal_config_path):
            if not p.exists():
                problems.append(f"missing path {p}")
        if self.promos_enabled and (self.promo_path is None or not self.promo_path.exists()):
            problems.append("promos.enabled but promos.schedule missing")
        names = [a.name for a in self.arms]
        if len(set(names)) != len(names):
            problems.append("duplicate arm names")
        for a in self.arms:
            if a.branch_from is not None:
                if a.branch_from not in names:
                    problems.append(f"arm {a.name}: unknown branch_from {a.branch_from}")
                if a.divergence_tick is None or not 0 <= a.divergence_tick < self.ticks:
                    problems.append(f"arm {a.name}: divergence_tick outside [0, ticks)")
        for r in self.schedule:
            if not 0.0 <= r.reach_prob <= 1.0:
                problems.append(f"schedule {r.creative_id}: reach_prob outside [0,1]")
            if r.start_tick > r.end_tick:
                problems.append(f"schedule {r.creative_id}: start_tick > end_tick")
        if problems:
            raise ValueError("invalid run_config: " + "; ".join(problems))

    # -- derived -------------------------------------------------------------

    def arm(self, name: str) -> ArmSpec:
        for a in self.arms:
            if a.name == name:
                return a
        raise KeyError(f"unknown arm {name!r} (have {[a.name for a in self.arms]})")

    def goal_overrides(self, arm: ArmSpec) -> dict:
        merged = {"scripted_enabled": True, "waves_enabled": True}
        merged.update(self.goal_overrides_base)
        merged.update(arm.goal_overrides)
        return merged

    def config_hash(self, arm_name: str) -> str:
        blob = canonical_json(self.raw) + "\n" + arm_name
        return hashlib.sha256(blob.encode()).hexdigest()

    def now_at(self, tick: int) -> int:
        return self.t0 + tick * self.tick_seconds

    def resolve_pages(self, view) -> dict[int, int]:
        """schedule creative -> landing page id. Default: the lowest page_id
        whose PAGE_FOR product is offered by the creative (the 'consistent'
        variant by fixture convention); per-row page_id overrides. A creative
        whose products have no page resolves to nothing — its funnel ends at
        CLICK (CONTRACT v3.3)."""
        page_for_product: dict[int, int] = {}
        for pgid in sorted(view.stimuli):
            f = view.stimuli[pgid]
            if f.kind == "page":
                for prod in f.products:
                    page_for_product.setdefault(prod, pgid)
        out: dict[int, int] = {}
        for row in self.schedule:
            if row.page_id is not None:
                out[row.creative_id] = row.page_id
                continue
            facts = view.facts(row.creative_id)
            if facts is None:
                continue
            pages = [page_for_product[p] for p in sorted(facts.offers) if p in page_for_product]
            if pages:
                out[row.creative_id] = pages[0]
        return out
