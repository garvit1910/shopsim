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
    # CONTRACT v3.4-draft: None = whole population (the Phase-3 behavior)
    audience_segments: tuple[int, ...] | None = None
    # CONTRACT v3.4-draft: seeded per-shopper A/B split over these pages
    # (substream (seed, "page", offset, creative)); excludes the row from the
    # single-page resolution map
    page_ids: tuple[int, ...] | None = None


def _parse_row(r: dict) -> ScheduleRow:
    return ScheduleRow(
        creative_id=int(r["creative_id"]),
        start_tick=int(r["start_tick"]),
        end_tick=int(r["end_tick"]),
        reach_prob=float(r["reach_prob"]),
        page_id=int(r["page_id"]) if r.get("page_id") is not None else None,
        audience_segments=(tuple(int(s) for s in r["audience_segments"])
                           if r.get("audience_segments") is not None else None),
        page_ids=(tuple(int(p) for p in r["page_ids"])
                  if r.get("page_ids") is not None else None),
    )


def _sort_rows(rows) -> tuple[ScheduleRow, ...]:
    return tuple(sorted(rows, key=lambda r: (r.creative_id, r.start_tick)))


@dataclass(frozen=True)
class ArmSpec:
    name: str
    goal_overrides: dict = field(default_factory=dict)
    branch_from: str | None = None
    divergence_tick: int | None = None
    # CONTRACT v3.4-draft: per-arm experiment levers, all inside the raw
    # config (config_hash-covered), so arms stay branch-compatible
    exposure_overrides: dict = field(default_factory=dict)
    promo_overrides: dict = field(default_factory=dict)


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
        rows = _sort_rows(_parse_row(r) for r in exposure.get("schedule", ()))
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
                exposure_overrides=dict(a.get("exposure_overrides", {})),
                promo_overrides=dict(a.get("promo_overrides", {})),
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
            bad = set(a.exposure_overrides) - {"schedule", "add"}
            if bad:
                problems.append(f"arm {a.name}: unknown exposure_overrides keys {sorted(bad)}")
            if "schedule" in a.exposure_overrides and "add" in a.exposure_overrides:
                problems.append(f"arm {a.name}: exposure_overrides carries both "
                                "'schedule' (replace) and 'add' (append)")
            bad = set(a.promo_overrides) - {"enabled", "schedule_inline"}
            if bad:
                problems.append(f"arm {a.name}: unknown promo_overrides keys {sorted(bad)}")
            enabled, path, inline = self.promos_for(a)
            if enabled and path is None and inline is None:
                problems.append(f"arm {a.name}: promos enabled with no schedule source")
        def check_rows(rows, where: str) -> None:
            for r in rows:
                if not 0.0 <= r.reach_prob <= 1.0:
                    problems.append(f"{where} {r.creative_id}: reach_prob outside [0,1]")
                if r.start_tick > r.end_tick:
                    problems.append(f"{where} {r.creative_id}: start_tick > end_tick")
                if r.page_ids is not None and len(r.page_ids) < 2:
                    problems.append(f"{where} {r.creative_id}: page_ids needs >= 2 pages")
                if r.page_ids is not None and len(set(r.page_ids)) != len(r.page_ids):
                    problems.append(f"{where} {r.creative_id}: duplicate page_ids")
                if r.audience_segments is not None and not r.audience_segments:
                    problems.append(f"{where} {r.creative_id}: empty audience_segments")

        check_rows(self.schedule, "schedule")
        for a in self.arms:
            if not a.exposure_overrides:
                continue
            try:
                check_rows(self.schedule_for(a), f"arm {a.name} schedule")
            except (KeyError, TypeError, ValueError) as ex:
                problems.append(f"arm {a.name}: bad exposure_overrides schedule ({ex})")
        try:
            self.calibration()
        except ValueError as ex:
            problems.append(str(ex))
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

    def schedule_for(self, arm: ArmSpec) -> tuple[ScheduleRow, ...]:
        """Per-arm exposure schedule (CONTRACT v3.4-draft). exposure_overrides
        supports {"schedule": [rows]} (full replacement) or {"add": [rows]}
        (append). No overrides returns the shared schedule object unchanged."""
        ov = arm.exposure_overrides
        if not ov:
            return self.schedule
        if "schedule" in ov:
            return _sort_rows(_parse_row(r) for r in ov["schedule"])
        return _sort_rows((*self.schedule,
                           *(_parse_row(r) for r in ov.get("add", ()))))

    def promos_for(self, arm: ArmSpec) -> tuple[bool, Path | None, dict | None]:
        """(enabled, schedule_path, inline_raw) for this arm (CONTRACT
        v3.4-draft). promo_overrides supports {"enabled": bool} and
        {"schedule_inline": {product_promos: [...]}} — inline schedules live in
        the raw config, so they are config_hash-covered and branch-compatible."""
        ov = arm.promo_overrides
        enabled = bool(ov.get("enabled", self.promos_enabled))
        inline = ov.get("schedule_inline")
        if inline is not None:
            return enabled, None, dict(inline)
        return enabled, self.promo_path, None

    def page_splits(self, schedule: tuple[ScheduleRow, ...] | None = None
                    ) -> dict[int, tuple[int, ...]]:
        """creative -> page variants for seeded per-shopper A/B rows."""
        rows = self.schedule if schedule is None else schedule
        return {r.creative_id: r.page_ids for r in rows if r.page_ids is not None}

    def calibration(self):
        """Optional top-level "calibration" block -> (AppraisalParams,
        ChoiceParams, stage_bases). Absent block returns the module DEFAULT
        objects — the byte-identical Phase-3 path. The block rides in raw, so
        config_hash pins every tuned constant (Law 13, CONTRACT v3.4-draft)."""
        return parse_calibration(self.raw.get("calibration"))

    def config_hash(self, arm_name: str) -> str:
        blob = canonical_json(self.raw) + "\n" + arm_name
        return hashlib.sha256(blob.encode()).hexdigest()

    def now_at(self, tick: int) -> int:
        return self.t0 + tick * self.tick_seconds

    def resolve_pages(self, view, schedule: tuple[ScheduleRow, ...] | None = None
                      ) -> dict[int, int]:
        """schedule creative -> landing page id. Default: the lowest page_id
        whose PAGE_FOR product is offered by the creative (the 'consistent'
        variant by fixture convention); per-row page_id overrides. A creative
        whose products have no page resolves to nothing — its funnel ends at
        CLICK (CONTRACT v3.3). Rows carrying page_ids resolve through the
        seeded split (steps.page_for), never this map (v3.4-draft)."""
        rows = self.schedule if schedule is None else schedule
        page_for_product: dict[int, int] = {}
        for pgid in sorted(view.stimuli):
            f = view.stimuli[pgid]
            if f.kind == "page":
                for prod in f.products:
                    page_for_product.setdefault(prod, pgid)
        out: dict[int, int] = {}
        for row in rows:
            if row.page_ids is not None:
                continue
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


def parse_calibration(block: dict | None):
    """The one calibration-block parser (RunConfig.calibration + the Phase-4
    experiment builders). None/empty -> the module DEFAULT objects."""
    from dataclasses import fields, replace

    from ..minds.calibration import (
        APPRAISAL_DIMS,
        DEFAULT_APPRAISAL_PARAMS,
        DEFAULT_CHOICE_PARAMS,
        DEFAULT_STAGE_BASES,
        STAGES,
    )

    if not block:
        return DEFAULT_APPRAISAL_PARAMS, DEFAULT_CHOICE_PARAMS, DEFAULT_STAGE_BASES
    bad = set(block) - {"appraisal", "choice", "stage_bases"}
    if bad:
        raise ValueError(f"calibration: unknown keys {sorted(bad)}")

    def override(default_obj, given: dict, *, skip=()):
        known = {f.name for f in fields(default_obj)} - set(skip)
        bad = set(given) - known
        if bad:
            raise ValueError(
                f"calibration: unknown {type(default_obj).__name__} keys {sorted(bad)}")
        return replace(default_obj, **{k: type(getattr(default_obj, k))(v)
                                       for k, v in given.items()})

    ap = override(DEFAULT_APPRAISAL_PARAMS, dict(block.get("appraisal", {})))

    choice_given = dict(block.get("choice", {}))
    weights_given = choice_given.pop("stage_weights", None)
    cp = override(DEFAULT_CHOICE_PARAMS, choice_given, skip=("stage_weights",))
    if weights_given is not None:
        bad = set(weights_given) - set(STAGES)
        if bad:
            raise ValueError(f"calibration: unknown stage_weights stages {sorted(bad)}")
        merged = []
        for stage in STAGES:
            dims = cp.weights(stage)
            given = dict(weights_given.get(stage, {}))
            bad = set(given) - set(APPRAISAL_DIMS)
            if bad:
                raise ValueError(
                    f"calibration: unknown stage_weights dims for {stage}: {sorted(bad)}")
            dims.update({k: float(v) for k, v in given.items()})
            merged.append((stage, tuple((d, dims[d]) for d in APPRAISAL_DIMS)))
        cp = replace(cp, stage_weights=tuple(merged))

    bases_given = dict(block.get("stage_bases", {}))
    bad = set(bases_given) - set(STAGES)
    if bad:
        raise ValueError(f"calibration: unknown stage_bases stages {sorted(bad)}")
    bases = dict(DEFAULT_STAGE_BASES)
    bases.update({k: float(v) for k, v in bases_given.items()})
    sb = tuple((stage, bases[stage]) for stage, _ in DEFAULT_STAGE_BASES)
    return ap, cp, sb
