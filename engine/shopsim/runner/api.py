"""Read-only progress/results API (PLAN 3.1) + the Phase-5 live-dashboard
surface (CONTRACT v3.5-draft, pending Atishay's ack).

The three Phase-3 endpoints are byte-identical. Everything else is additive
and read-only except POST /experiments{,/ingest-ads}, which spawn the engine
CLI detached — Law 8 intact: the dashboard never writes the graph; the engine
subprocess is the one admitted writer. Launches are serialized (409 while any
run is live) because RunStore.allocate's registry read-modify-write is not
concurrent-safe.

Thin by design: file serving reuses the loop's atomic snapshots; graph reads
reuse the shipped HydraMem read API (the export-fixtures pattern);
decision-preview reuses the pure appraise()/stage_probabilities() math with a
deterministic population recompute (traits/coeffs never leave the server —
Law 12/15).
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
from dataclasses import is_dataclass
from enum import Enum
from functools import partial
from pathlib import Path


STALE_AFTER_S = 300  # a "running" row with no progress for this long is stale


def _pid_is_live_orchestrator(pid: int) -> bool:
    """True only for a live, non-zombie process actually running the
    experiments CLI. `os.kill(pid, 0)` alone is wrong here: it succeeds on
    zombies (our un-reaped launch children) and on reused pids — the source
    of the every-launch-409s bug."""
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat=,command="],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        return False
    if not out:
        return False
    stat, _, command = out.partition(" ")
    if stat.startswith("Z"):
        return False
    return "shopsim.experiments" in command


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


def create_app(runs_dir: Path):
    from fastapi import FastAPI, HTTPException

    app = FastAPI(title="shopsim runner", version="0.2.0")
    runs_dir = Path(runs_dir)
    root = runs_dir.parent
    exp_root = runs_dir / "experiments"

    # per-process caches (immutable per run) + per-run HydraMem serialization
    _mems: dict[str, object] = {}
    _mem_locks: dict[str, threading.Lock] = {}
    _pops: dict[str, tuple] = {}      # run_id -> (specs, shoppers)
    _previews: dict[str, dict] = {}   # run_id -> {cfg, view, mind, cp, page_of}
    _procs: list = []                 # spawned Popen handles, reaped in _busy_reason
    _global_lock = threading.Lock()

    # ---- shared helpers ----------------------------------------------------

    def _store():
        from .runstore import RunStore
        return RunStore(root)

    def _row(run_id: str) -> dict:
        try:
            return _store().find(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"unknown run {run_id}")

    def _run_file(run_id: str, name: str) -> dict:
        path = runs_dir / run_id / name
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"{run_id}/{name} not found")
        return json.loads(path.read_text())

    def _progress_or_empty(run_id: str) -> dict:
        path = runs_dir / run_id / "progress.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def _clock(run_id: str) -> tuple[int, int, dict]:
        """(last_completed_tick, now, manifest) — reads stay bitemporally
        consistent as-of the last fully consolidated tick."""
        manifest = _run_file(run_id, "manifest.json")
        prog = _progress_or_empty(run_id)
        if prog.get("status") == "complete":
            tick = int(manifest["ticks"]) - 1
        else:
            tick = int(prog.get("tick", 0))
        now = int(manifest["t0"]) + tick * int(manifest["tick_seconds"])
        return tick, now, manifest

    def _cfg_for(run_id: str):
        row = _row(run_id)
        cfg_path = exp_root / row["label"] / "run_config.json"
        if not cfg_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"no run_config for label {row['label']!r} — only "
                       "experiment-launched runs carry one (CLI runs keep "
                       "their config outside the run store)")
        from .config import RunConfig
        return row, RunConfig.load(cfg_path)

    # ---- Phase-3 endpoints (byte-identical) --------------------------------

    @app.get("/runs")
    def list_runs() -> list[dict]:
        reg = runs_dir / "registry.json"
        if not reg.exists():
            return []
        return json.loads(reg.read_text())["runs"]

    @app.get("/runs/{run_id}/progress")
    def progress(run_id: str) -> dict:
        return _run_file(run_id, "progress.json")

    @app.get("/runs/{run_id}/results")
    def results(run_id: str) -> dict:
        return _run_file(run_id, "results.json")

    # ---- v3.5-draft: file serving ------------------------------------------

    @app.get("/runs/{run_id}/manifest")
    def manifest(run_id: str) -> dict:
        return _run_file(run_id, "manifest.json")

    @app.get("/runs/{run_id}/events")
    def events(run_id: str, after: int = 0, limit: int = 5000) -> dict:
        path = runs_dir / run_id / "events.jsonl"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"{run_id}/events.jsonl not found")
        size = path.stat().st_size
        if after > size:
            after = 0  # log truncated by a resume rollback — replay from the top
        if after < 0:
            after = 0
        records: list[dict] = []
        consumed = 0
        with path.open("rb") as fh:
            fh.seek(after)
            data = fh.read()
        lines = data.split(b"\n")
        lines.pop()  # trailing chunk: either b"" (clean \n end) or a partial line
        for ln in lines[:limit]:
            consumed += len(ln) + 1
            if ln.strip():
                records.append(json.loads(ln))
        nxt = after + consumed
        return {"records": records, "next": nxt, "eof": nxt >= size}

    @app.get("/runs/{run_id}/results-live")
    def results_live(run_id: str) -> dict:
        d = runs_dir / run_id
        prog = _progress_or_empty(run_id)
        status = prog.get("status", "running")

        def _latest_state() -> dict | None:
            snaps = sorted(d.glob("results_state_*.json"),
                           key=lambda p: int(p.stem.rsplit("_", 1)[1]))
            for p in reversed(snaps):
                try:
                    return json.loads(p.read_text())
                except FileNotFoundError:
                    continue  # the loop's keep-last-2 deletion race
            return None

        snap = _latest_state()
        extras = {"belief_avg": (snap or {}).get("state", {}).get("belief_avg", {})}
        final = d / "results.json"
        if final.exists():
            return {"tick": prog.get("tick"), "status": status,
                    "results": json.loads(final.read_text()), "live_extras": extras}
        if snap is None:
            raise HTTPException(status_code=404,
                                detail=f"{run_id}: no results yet (tick 0 in flight)")
        man = _run_file(run_id, "manifest.json")
        from .results import ResultsAccumulator
        acc = ResultsAccumulator.from_state(
            snap["state"], segment_by_offset={}, drift_concepts=[], hero_product=None)
        return {"tick": snap["tick"], "status": status,
                "results": acc.results(man), "live_extras": extras}

    # ---- v3.5-draft: config + population -----------------------------------

    @app.get("/runs/{run_id}/config")
    def run_config(run_id: str) -> dict:
        row, cfg = _cfg_for(run_id)
        from .steps import GoalConfig, PromoSchedule
        arm = cfg.arm(row["arm"])
        sched = cfg.schedule_for(arm)
        enabled, promo_path, promo_inline = cfg.promos_for(arm)
        windows: dict[str, list] = {}
        if enabled:
            ps = (PromoSchedule.from_raw(promo_inline) if promo_inline is not None
                  else PromoSchedule.load(promo_path) if promo_path else None)
            if ps is not None:
                windows = {str(p): [list(w) for w in ws]
                           for p, ws in sorted(ps.windows.items())}
        goal_cfg = GoalConfig.load(cfg.goal_config_path)
        creative_names: dict[str, str] = {}
        creatives_path = cfg.catalog_dir / "creatives.json"
        if creatives_path.exists():
            doc = json.loads(creatives_path.read_text())
            creative_names = {str(r["creative_id"]): r.get("name", str(r["creative_id"]))
                              for r in doc.get("creatives", [])}
        return {
            "raw": cfg.raw,
            "effective": {
                "creative_names": creative_names,
                "label": cfg.label, "arm": row["arm"], "seed": cfg.seed,
                "ticks": cfg.ticks, "t0": cfg.t0, "tick_seconds": cfg.tick_seconds,
                "population_size": cfg.population_size,
                "schedule": _jsonable(list(sched)),
                "promos_enabled": enabled,
                "promo_windows": windows,  # product -> [[start, end, pct], ...]
                "goal_overrides": cfg.goal_overrides(arm),
                "goal_waves": [dict(w) for w in goal_cfg.waves],
                "arms": [a.name for a in cfg.arms],
            },
        }

    def _population(run_id: str):
        with _global_lock:
            cached = _pops.get(run_id)
        if cached is not None:
            return cached
        row, cfg = _cfg_for(run_id)
        from ..population.factory import (
            PopulationConfig, generate_population, load_segment_specs)
        _ap, _cp, stage_bases = cfg.calibration()
        specs = load_segment_specs(cfg.personas_path)
        shoppers = generate_population(PopulationConfig(
            seed=cfg.seed, population_size=cfg.population_size,
            segments=specs, run_index=row["run_index"],
            stage_bases=stage_bases))
        with _global_lock:
            _pops[run_id] = (specs, shoppers)
        return specs, shoppers

    @app.get("/runs/{run_id}/population")
    def population(run_id: str) -> dict:
        specs, shoppers = _population(run_id)
        from ..contracts.ids import shopper_offset
        # identity + segment ONLY — traits/coeffs/budget stay server-side
        return {
            "segments": [{"segment_id": s.segment_id, "name": s.name,
                          "share": s.share} for s in specs],
            "shoppers": [{"offset": shopper_offset(s.shopper_id),
                          "shopper_id": s.shopper_id,
                          "segment_id": s.segment_id} for s in shoppers],
        }

    # ---- v3.5-draft: shopper reads (the export-fixtures pattern) -----------

    def _mem_for(run_id: str):
        with _global_lock:
            if run_id not in _mems:
                row = _row(run_id)
                from ..hydramem.real import HydraMem
                try:
                    _mems[run_id] = HydraMem(run_index=row["run_index"])
                except Exception as ex:  # store down / auth — say so plainly
                    raise HTTPException(status_code=503,
                                        detail=f"HydraDB unreachable: {ex}")
                _mem_locks[run_id] = threading.Lock()
            return _mems[run_id], _mem_locks[run_id]

    def _shopper_read(run_id: str, offset: int, fn):
        mem, lock = _mem_for(run_id)
        tick, now, _man = _clock(run_id)
        row = _row(run_id)
        from ..contracts.ids import shopper_id as make_sid
        sid = make_sid(row["run_index"], offset)
        with lock:
            mem.set_tick(tick=tick, now=now)
            try:
                return fn(mem, sid)
            except Exception as ex:
                raise HTTPException(status_code=503, detail=f"graph read failed: {ex}")

    @app.get("/runs/{run_id}/shoppers/{offset}/worldview")
    def worldview(run_id: str, offset: int) -> dict:
        return _shopper_read(run_id, offset,
                             lambda mem, sid: mem.get_shopper_worldview(sid))

    @app.get("/runs/{run_id}/shoppers/{offset}/preference-history/{concept_id}")
    def preference_history(run_id: str, offset: int, concept_id: int) -> list[dict]:
        return _shopper_read(run_id, offset,
                             lambda mem, sid: mem.get_preference_history(sid, concept_id))

    @app.get("/runs/{run_id}/shoppers/{offset}/belief-history")
    def belief_history(run_id: str, offset: int) -> list[dict]:
        return _shopper_read(run_id, offset,
                             lambda mem, sid: mem.get_belief_history(sid))

    @app.get("/runs/{run_id}/shoppers/{offset}/trace/{stimulus_id}")
    def trace(run_id: str, offset: int, stimulus_id: int) -> dict:
        return _shopper_read(run_id, offset,
                             lambda mem, sid: mem.get_trace(sid, stimulus_id))

    # ---- v3.5-draft item 2: decision preview (real math, no rng) -----------

    def _preview_ctx(run_id: str) -> dict:
        with _global_lock:
            cached = _previews.get(run_id)
        if cached is not None:
            return cached
        row, cfg = _cfg_for(run_id)
        from ..minds import FormulaMind, ObjectiveView
        from ..perception.cache import perceived_maps
        from ..perception.perceive import perceive_catalog
        from . import steps

        def _no_llm(*_a, **_k):
            raise HTTPException(status_code=503,
                                detail="perception cache incomplete for this run")

        perceived, calls = perceive_catalog(
            cfg.catalog_dir, cache_dir=cfg.perception_cache, call=_no_llm)
        assert calls == 0
        claims, offers = perceived_maps(perceived)
        view = ObjectiveView.from_catalog(cfg.catalog_dir, claims, offers)
        ap, cp, _sb = cfg.calibration()
        arm = cfg.arm(row["arm"])
        sched = cfg.schedule_for(arm)
        page_of = partial(steps.page_for, cfg.seed,
                          cfg.page_splits(sched), cfg.resolve_pages(view, sched))
        built = {"view": view,
                 "mind": FormulaMind(view, appraisal_params=ap, choice_params=cp),
                 "cp": cp, "page_of": page_of}
        with _global_lock:
            _previews[run_id] = built
        return built

    @app.get("/runs/{run_id}/shoppers/{offset}/decision-preview/{stimulus_id}")
    def decision_preview(run_id: str, offset: int, stimulus_id: int) -> dict:
        pv = _preview_ctx(run_id)
        facts = pv["view"].facts(stimulus_id)
        if facts is None:
            raise HTTPException(status_code=404,
                                detail=f"unknown stimulus {stimulus_id}")
        _specs, shoppers = _population(run_id)
        if not 0 <= offset < len(shoppers):
            raise HTTPException(status_code=404, detail=f"offset {offset} out of range")
        sh = shoppers[offset]
        ctx = _shopper_read(run_id, offset,
                            lambda mem, sid: mem.get_decision_context(sid, stimulus_id))
        bound = pv["mind"].for_stimulus(stimulus_id)
        from dataclasses import replace
        from ..minds.choice import stage_probabilities
        a = bound.appraise(ctx, sh.traits)
        probs = stage_probabilities(a, ctx.scalars, sh.coeffs,
                                    kind=facts.kind, params=pv["cp"])
        counterfactual = None
        if ctx.scalars.active_need is not None:
            ctx2 = replace(
                ctx,
                scalars=replace(ctx.scalars, active_need=None),
                motifs=[m for m in ctx.motifs if m.type.value != "goal_fit"])
            a2 = bound.appraise(ctx2, sh.traits)
            counterfactual = {
                "label": "same context, need removed",
                "appraisal": _jsonable(a2),
                "probabilities": stage_probabilities(
                    a2, ctx2.scalars, sh.coeffs, kind=facts.kind, params=pv["cp"]),
            }
        tick, _now, _man = _clock(run_id)
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

    # ---- v3.5-draft: experiments -------------------------------------------

    def _orchestrator(name: str) -> dict | None:
        pidf = exp_root / name / "orchestrator.pid"
        if not pidf.exists():
            return None
        try:
            pid = int(pidf.read_text().strip())
        except ValueError:
            return None
        try:  # reap it if it is our own exited child (clears the zombie)
            os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, PermissionError, OSError):
            pass
        return {"pid": pid, "alive": _pid_is_live_orchestrator(pid)}

    def _busy_reason() -> str | None:
        import time
        for proc in list(_procs):  # reap finished launch children
            if proc.poll() is not None:
                _procs.remove(proc)
        if exp_root.exists():
            for d in sorted(exp_root.iterdir()):
                if not d.is_dir():
                    continue
                orch = _orchestrator(d.name)
                if orch and orch["alive"]:
                    return (f"experiment {d.name!r} is running (pid {orch['pid']}) — "
                            "launches are serialized (registry allocation is "
                            "not concurrent-safe, CONTRACT v3.5-draft)")
        # registry rows: block only on rows showing recent activity; anything
        # quiet past STALE_AFTER_S is auto-healed to 'stale' (crashed runs and
        # zombie leftovers must never wedge the launcher — v3.5-draft).
        store = _store()
        now_s = time.time()
        for r in store.rows():
            if r.get("status") not in ("running", "created"):
                continue
            prog = _progress_or_empty(r["run_id"])
            ref = prog.get("updated_at")
            if ref is None:
                try:
                    ref = Path(r["dir"]).stat().st_mtime
                except OSError:
                    ref = 0
            if now_s - ref < STALE_AFTER_S:
                return (f"run {r['run_id']} looks live (activity {int(now_s - ref)}s ago) — "
                        "launches are serialized; retry with force=1 to override")
            store.set_status(r["run_id"], "stale")
        return None

    @app.get("/experiments")
    def list_experiments() -> list[dict]:
        out = []
        if not exp_root.exists():
            return out
        rows = _store().rows()
        for d in sorted(exp_root.iterdir()):
            cfg_path = d / "run_config.json"
            if not d.is_dir() or not cfg_path.exists():
                continue
            raw = json.loads(cfg_path.read_text())
            arm_rows = [r for r in rows if r["label"] == raw.get("label")]
            out.append({
                "name": d.name,
                "spec_type": raw.get("experiment", {}).get("type"),
                "arms": [a.get("name") for a in raw.get("arms", [])],
                "has_comparison": (d / "comparison.json").exists(),
                "runs": [{"run_id": r["run_id"], "arm": r["arm"],
                          "status": r["status"]} for r in arm_rows],
            })
        return out

    @app.get("/experiments/{name}")
    def experiment_detail(name: str) -> dict:
        d = exp_root / name
        cfg_path = d / "run_config.json"
        if not cfg_path.exists():
            raise HTTPException(status_code=404, detail=f"unknown experiment {name}")
        raw = json.loads(cfg_path.read_text())
        comparison = None
        if (d / "comparison.json").exists():
            comparison = json.loads((d / "comparison.json").read_text())
        arm_runs = []
        for r in _store().rows():
            if r["label"] != raw.get("label"):
                continue
            arm_runs.append({"run_id": r["run_id"], "arm": r["arm"],
                             "status": r["status"],
                             "progress": _progress_or_empty(r["run_id"])})
        log_tail = ""
        logf = d / "orchestrator.log"
        if logf.exists():
            log_tail = logf.read_text(errors="replace")[-4000:]
        return {"name": name, "run_config": raw, "comparison": comparison,
                "arm_runs": arm_runs, "orchestrator": _orchestrator(name),
                "log_tail": log_tail}

    @app.post("/experiments", status_code=202)
    def launch_experiment(spec: dict, force: bool = False) -> dict:
        from .runstore import write_json_atomic
        from ..experiments.specs import parse_spec
        try:
            parsed = parse_spec(spec)
        except (KeyError, ValueError, TypeError) as ex:
            raise HTTPException(status_code=422, detail=f"invalid spec: {ex}")
        busy = None if force else _busy_reason()
        if busy is not None:
            raise HTTPException(status_code=409, detail=busy)
        exp_dir = exp_root / parsed.name
        exp_dir.mkdir(parents=True, exist_ok=True)
        spec_path = exp_dir / "spec.json"
        write_json_atomic(spec_path, spec)
        log = open(exp_dir / "orchestrator.log", "ab")
        proc = subprocess.Popen(
            [sys.executable, "-m", "shopsim.experiments", "run",
             "--spec", str(spec_path), "--verbose"],
            cwd=str(root / "engine"), stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)
        _procs.append(proc)
        (exp_dir / "orchestrator.pid").write_text(str(proc.pid))
        return {"experiment": parsed.name, "pid": proc.pid, "status": "launched"}

    @app.post("/experiments/ingest-ads", status_code=202)
    def ingest_ads_endpoint(body: dict) -> dict:
        # resolve exactly as the CLI does (env, then <repo>/.env.local) —
        # an env-only check refuses a repo whose .env.local works fine
        from ..perception.perceive import resolve_api_key

        if not resolve_api_key():
            raise HTTPException(
                status_code=400,
                detail="OPENAI_API_KEY unset (checked env and <repo>/.env.local) — "
                       "ingestion perceives new ads live, once, at ingest time "
                       "(CONTRACT v3.4-draft item 6)")
        spec = body.get("spec")
        if not isinstance(spec, dict) or not spec.get("ads"):
            raise HTTPException(status_code=422, detail="body.spec.ads[] required")
        name = str(body.get("name") or spec.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="an experiment name is required")
        from .runstore import write_json_atomic
        stage_dir = root / "fixtures" / "experiments" / name / "uploads"
        stage_dir.mkdir(parents=True, exist_ok=True)
        for im in body.get("images", []):
            fn = Path(str(im.get("filename", ""))).name
            if not fn:
                raise HTTPException(status_code=422, detail="image without filename")
            try:
                blob = base64.b64decode(im["b64"])
            except (KeyError, ValueError) as ex:
                raise HTTPException(status_code=422, detail=f"bad image payload: {ex}")
            (stage_dir / fn).write_bytes(blob)
        # image paths in the spec resolve relative to the spec file (ingest.py)
        spec_path = stage_dir / "ads-spec.json"
        write_json_atomic(spec_path, spec)
        log = open(stage_dir / "ingest.log", "ab")
        proc = subprocess.Popen(
            [sys.executable, "-m", "shopsim.experiments", "ingest-ads",
             "--spec", str(spec_path), "--name", name],
            cwd=str(root / "engine"), stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)
        _procs.append(proc)
        return {"experiment": name, "pid": proc.pid, "status": "ingesting",
                "log": str(stage_dir / "ingest.log")}

    @app.get("/runs/{run_id}/creatives")
    def run_creatives(run_id: str) -> dict:
        """The ads themselves (v3.7-draft).

        /config deliberately reduces creatives to {id: name}, which left the
        dashboard unable to show what an ad actually SAYS. This returns the
        whole card, including what the perception cache recorded — the
        perceived claims are what the simulation reacts to, while headline and
        body are perception input with no runtime effect, so the UI can show
        both and be honest about which is which."""
        _row, cfg = _cfg_for(run_id)
        return {
            "catalog": str(cfg.catalog_dir),
            "perception_cache": str(cfg.perception_cache),
            "creatives": _creative_cards(cfg.catalog_dir, cfg.perception_cache,
                                         lambda cid: f"/runs/{run_id}/creatives/{cid}/image"),
        }

    @app.get("/runs/{run_id}/creatives/{creative_id}/image")
    def run_creative_image(run_id: str, creative_id: int):
        """One resolver for both worlds: a committed brand catalog and an
        experiment catalog materialized by ingest-ads both live behind the
        run's own catalog_dir."""
        _row, cfg = _cfg_for(run_id)
        return _serve_catalog_image(cfg.catalog_dir, creative_id)

    @app.get("/engine/pace")
    def engine_pace(limit: int = 5) -> dict:
        """How fast this machine is simulating right now (v3.7-draft).

        An OBSERVATION, never a simulated quantity. Per-tick cost is dominated
        by HydraDB consolidation and rises as the store grows — measured on
        this repo, the same 200x60 shape ran at 18.5 s/tick on a fresh store
        and 112 s/tick on a loaded one. A hardcoded constant would therefore
        lie within a day; reading recent runs tracks reality."""
        samples = []
        for row in reversed(_store().rows()):
            if row.get("status") != "complete":
                continue
            prog = _progress_or_empty(row["run_id"])
            ticks, wall = prog.get("ticks") or 0, prog.get("total_wall_s") or 0
            if ticks <= 0 or wall <= 0:
                continue
            pop = prog.get("population_size") or 0
            if not pop:
                try:
                    _r, cfg = _cfg_for(row["run_id"])
                    pop = cfg.population_size
                except Exception:       # noqa: BLE001 - a config may be gone
                    pop = 0
            samples.append({
                "run_id": row["run_id"], "ticks": ticks, "population": pop,
                "total_wall_s": round(wall, 1),
                "per_tick_s": round(wall / ticks, 2),
                "updated_at": prog.get("updated_at"),
            })
            if len(samples) >= max(1, limit):
                break

        # Weight by recency, halving per step back. Store size (and therefore
        # pace) changes underneath us — a plain mean of a fresh-store run and
        # three pre-reset ones would predict ~4x too slow.
        rated = [s for s in samples if s["population"]]
        if rated:
            num = den = 0.0
            for i, smp in enumerate(rated):          # samples are newest-first
                w = 0.5 ** i
                num += w * smp["per_tick_s"] * 100 / smp["population"]
                den += w
            per_100 = num / den
        else:
            per_100 = None
        return {"samples": samples,
                "per_tick_s_per_100_shoppers": round(per_100, 2) if per_100 else None}

    @app.get("/catalogs")
    def list_catalogs() -> list[dict]:
        """Server-side allowlist of pickable catalogs — the client never sends
        a path. Each row carries the companion config paths so a launch spec
        can be assembled without the web app hardcoding them."""
        return _catalog_rows(root)

    @app.get("/catalogs/{key}/creatives")
    def catalog_creatives(key: str) -> dict:
        row = _catalog_row(root, key)
        return {
            "key": key, "label": row["label"], "catalog": row["catalog"],
            "creatives": _creative_cards(
                root / row["catalog"], root / row["perception_cache"],
                lambda cid: f"/catalogs/{key}/creatives/{cid}/image"),
        }

    @app.get("/catalogs/{key}/creatives/{creative_id}/image")
    def catalog_creative_image(key: str, creative_id: int):
        row = _catalog_row(root, key)
        return _serve_catalog_image(root / row["catalog"], creative_id)

    @app.get("/experiments/{name}/ads-manifest")
    def ads_manifest(name: str) -> dict:
        """Ingest status + the paths a launch spec must carry (v3.6-draft).

        ads-manifest.json is written LAST by ingest_ads, so its presence is
        the completion signal. Paths come back repo-relative: the manifest
        stores absolutes, but a spec's catalog/perception_cache resolve
        against the repo root, so forwarding absolutes would break the
        moment the engine runs anywhere else (a container, say)."""
        fx = root / "fixtures" / "experiments" / _safe_name(name)
        mpath = fx / "ads-manifest.json"
        if mpath.exists():
            manifest = json.loads(mpath.read_text())
            for key in ("catalog", "perception_cache"):
                p = Path(str(manifest.get(key, "")))
                if p.is_absolute():
                    try:
                        manifest[key] = str(p.relative_to(root))
                    except ValueError:
                        pass
            return {"status": "ready", "manifest": manifest,
                    "catalog": manifest.get("catalog"),
                    "perception_cache": manifest.get("perception_cache")}
        uploads = fx / "uploads"
        if uploads.exists():
            logf = uploads / "ingest.log"
            return {"status": "ingesting", "manifest": None,
                    "log_tail": (logf.read_text(errors="replace")[-4000:]
                                 if logf.exists() else "")}
        return {"status": "none", "manifest": None}

    @app.get("/experiments/{name}/ads/{creative_id}/image")
    def ad_image(name: str, creative_id: int):
        """The uploaded creative's own image, for studio cards and the river
        legend. Resolved through the materialized catalog and confined to it —
        the id picks the row, the row names the file, nothing else is
        reachable."""
        from fastapi.responses import FileResponse

        cat = root / "fixtures" / "experiments" / _safe_name(name) / "catalog"
        rows_path = cat / "creatives.json"
        if not rows_path.exists():
            raise HTTPException(status_code=404, detail=f"no ingested catalog for {name!r}")
        rows = _creative_rows(rows_path)
        row = next((r for r in rows if int(r.get("creative_id", 0)) == creative_id), None)
        if row is None:
            raise HTTPException(status_code=404, detail=f"no creative {creative_id} in {name!r}")
        rel = str(row.get("image") or "")
        if not rel:
            raise HTTPException(status_code=404, detail=f"creative {creative_id} is text-only")
        target = (cat / rel).resolve()
        if not target.is_file() or not target.is_relative_to(cat.resolve()):
            raise HTTPException(status_code=404, detail="image not found")
        return FileResponse(target)

    return app


_CATALOGS = (
    ("nisolo", "Nisolo", "fixtures/nisolo", "fixtures/nisolo/perception-cache",
     "fixtures/nisolo/personas.json", "fixtures/nisolo/goal_config.json"),
    ("demo-brand", "Demo brand (value tier)", "fixtures/demo-brand",
     "fixtures/perception-cache", "fixtures/demo-brand/personas.json",
     "fixtures/demo-brand/goal_config.json"),
)


def _catalog_rows(root: Path) -> list[dict]:
    """The committed brands, plus any catalog materialized by ingest-ads.
    An allowlist, not a path parameter: the client picks a key, never a dir."""
    rows = []
    for key, label, catalog, cache, personas, goals in _CATALOGS:
        if not (root / catalog / "creatives.json").exists():
            continue
        rows.append({"key": key, "label": label, "catalog": catalog,
                     "perception_cache": cache, "personas": personas,
                     "goal_config": goals,
                     "n_creatives": len(_creative_rows(root / catalog / "creatives.json"))})
    exp_root = root / "fixtures" / "experiments"
    for d in sorted(exp_root.glob("*/catalog/creatives.json")) if exp_root.is_dir() else []:
        name = d.parent.parent.name
        rows.append({
            "key": f"upload:{name}", "label": f"Your upload · {name}",
            "catalog": str(d.parent.relative_to(root)),
            "perception_cache": f"fixtures/experiments/{name}/perception-cache",
            "personas": None, "goal_config": None,
            "n_creatives": len(_creative_rows(d))})
    return rows


def _catalog_row(root: Path, key: str) -> dict:
    from fastapi import HTTPException

    row = next((r for r in _catalog_rows(root) if r["key"] == key), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown catalog {key!r}")
    return row


def _serve_catalog_image(catalog_dir: Path, creative_id: int):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    rows_path = Path(catalog_dir) / "creatives.json"
    if not rows_path.exists():
        raise HTTPException(status_code=404, detail="no catalog for this run")
    row = next((r for r in _creative_rows(rows_path)
                if int(r.get("creative_id", 0)) == creative_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no creative {creative_id}")
    rel = str(row.get("image") or "")
    if not rel:
        raise HTTPException(status_code=404, detail=f"creative {creative_id} is text-only")
    base = Path(catalog_dir).resolve()
    target = (base / rel).resolve()
    if not target.is_file() or not target.is_relative_to(base):
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(target)


def _creative_cards(catalog_dir: Path, cache_dir: Path | None, image_url) -> list[dict]:
    """Everything the dashboard needs to render an ad as an ad.

    `perceived` is read back through the same key `perceive` writes, so the
    card can report not just WHAT was claimed but HOW it was read — from the
    image or from the text. That distinction is the exhibit: the sale ad's
    discount is perceived, never authored."""
    import csv as _csv
    import hashlib as _hashlib

    from ..contracts.enums import Concept
    from ..perception import cache as pcache
    from ..perception import perceive as pperceive

    catalog_dir = Path(catalog_dir)
    rows_path = catalog_dir / "creatives.json"
    if not rows_path.exists():
        return []

    products: dict[int, dict] = {}
    csv_path = catalog_dir / "catalog.csv"
    if csv_path.exists():
        with csv_path.open() as fh:
            for r in _csv.DictReader(fh):
                products[int(r["product_id"])] = r

    pages: dict[int, list[int]] = {}
    pv_path = catalog_dir / "page_variants.json"
    if pv_path.exists():
        for p in json.loads(pv_path.read_text()).get("page_variants", []):
            pages.setdefault(int(p["product_id"]), []).append(int(p["page_id"]))

    brands: dict[str, dict] = {}
    b_path = catalog_dir / "brands.json"
    if b_path.exists():
        brands = json.loads(b_path.read_text())

    def cname(cid: int) -> str:
        try:
            return Concept(int(cid)).name
        except ValueError:
            return str(cid)

    out = []
    for cr in _creative_rows(rows_path):
        cid = int(cr["creative_id"])
        image_rel = cr.get("image")
        perceived = None
        if cache_dir is not None:
            try:
                image_sha = (_hashlib.sha256((catalog_dir / image_rel).read_bytes()).hexdigest()
                             if image_rel else None)
                descriptor = pperceive.descriptor_for(cr, image_sha256=image_sha)
                version = (pperceive.IMAGE_PROMPT_VERSION if image_rel
                           else pperceive.PROMPT_VERSION)
                key = pperceive.stimulus_hash(descriptor, version, pperceive.DEFAULT_MODEL)
                entry = pcache.load(Path(cache_dir), cid, key)
            except (OSError, KeyError, ValueError):
                entry = None
            if entry is not None:
                o = entry.get("output", {})
                perceived = {
                    "claims": [{"concept": c["concept"], "strength": c["strength"]}
                               for c in o.get("claims", [])],
                    "claimed_discounts": o.get("claimed_discounts", []),
                    "prompt_version": entry.get("prompt_version"),
                    "model": entry.get("model"),
                    "from_image": bool(image_rel),
                }
        brand_id = int(cr.get("brand_id", 0))
        out.append({
            "creative_id": cid,
            "brand_id": brand_id,
            "brand_name": brands.get(str(brand_id), {}).get("name") or f"Brand {brand_id}",
            "name": cr.get("name", str(cid)),
            "headline": cr.get("headline", ""),
            "body": cr.get("body", ""),
            "note": cr.get("note"),
            "image_url": image_url(cid) if image_rel else None,
            "authored_claims": [
                {"concept_id": int(c["concept_id"]), "concept": cname(c["concept_id"]),
                 "strength": c["strength"]}
                for c in cr.get("claims", [])],
            "perceived": perceived,
            "offers": [
                {"product_id": int(o["product_id"]),
                 "name": products.get(int(o["product_id"]), {}).get("name", ""),
                 "list_price": float(products.get(int(o["product_id"]), {})
                                     .get("list_price", 0) or 0),
                 "category_id": int(products.get(int(o["product_id"]), {})
                                    .get("category_id", 0) or 0),
                 "claimed_pct": o.get("claimed_pct", 0.0),
                 "page_ids": sorted(pages.get(int(o["product_id"]), []))}
                for o in cr.get("offers", [])],
        })
    return out


def _creative_rows(path: Path) -> list[dict]:
    """creatives.json comes in two shapes: the committed catalogs and
    ingest.py both write {"comment": ..., "creatives": [...]}, while some
    fixtures/tests write a bare list. Iterating the dict form yields string
    keys, so a reader that assumes a list 500s on every real catalog."""
    doc = json.loads(path.read_text())
    return doc["creatives"] if isinstance(doc, dict) else doc


def _safe_name(name: str) -> str:
    """Experiment names index directories — keep them to one path segment."""
    from fastapi import HTTPException

    clean = Path(name).name
    if not clean or clean in (".", ".."):
        raise HTTPException(status_code=422, detail=f"bad experiment name {name!r}")
    return clean


def serve(root: Path, port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(create_app(Path(root) / "runs"), host="127.0.0.1", port=port)
