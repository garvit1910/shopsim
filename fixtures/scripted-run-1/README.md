# scripted-run-1 — the Phase-3 C3 fixture set

200 shoppers × 14 sim-days, ScriptedMind v2 decides + real `consolidate()`
digests (hybrid, CONTRACT v3.3). Arm `need_on` ran live; arm `need_off` was
**branched from need_on's event log at tick 6** (replayed into a fresh shopper
block, worldview recomputed from evidence.py, never from stored deltas) with
the marathon wave and Maya's scripted need turned off. Seed 57.

Regenerate: `uv run python -m shopsim.runner run --config
fixtures/run-configs/scripted-run-1.json` then `... branch --arm need_off`
then `... export-fixtures --out fixtures/scripted-run-1` (from `engine/`,
HydraDB up). Content is deterministic: same seed ⇒ byte-identical results
(modulo `run_manifest.run_index`, an allocation artifact).

## Files

- `results.json` — the merged C3 payload (funnel carries BOTH arms; flat keys
  from the primary arm). Validated by
  `engine/shopsim/runner/results.py::validate_results`. Phase-6 keys
  (fatigue_split, belief metrics, bounce_delta, ci) are present but
  typed-empty until Phase 6.
- `run_config.json` — the exact config; `<arm>/manifest.json` — Law-13 hashes.
- `<arm>/events.jsonl` — full event log (replay source of truth), incl.
  NEED_* lifecycle records and TICK_COMPLETE markers.
- `<arm>/results.json`, `<arm>/progress.json` — per-arm C3 + final progress
  (phase wall-clocks).
- `<arm>/shoppers/offset_*.json` — drill-down samples for Phase 5.3:
  `get_shopper_worldview` (belief cards with confidence + provenance
  sentences), `get_trace` vs the EcoStride Sale ad, and
  `get_preference_history` for eco (5003). Offsets 41/42 are the Maya twin
  pair (both eco_enthusiast under seed 57) + the arm's two busiest buyers.

## The headline numbers

- Maya (offset 42), need_on: browses eco ads (ref price + eco drift), scripted
  need tick 8 → CLICK → BUY tick 10 → NEED_SATISFIED (cause: BOUGHT 3000001)
  → EXPERIENCED tick 12; eco 0.699 → 0.898, every version cause-stamped; trust
  belief 0.70 @ 0.90 confidence "from 2 visits, 2 browses, 1 purchase and 1
  delivery". need_off: the same shopper browses and never buys.
- Arms: 56 buys (need_on) vs 32 (need_off); `p_buy_need_on 0.59` vs
  `p_buy_need_off 0.0` at page decisions (ScriptedMind is deterministic, so
  the split is sharp by construction — the formula mind softens it at S1).
- `reference_price_trajectory` shows all three promo cycles (list 39.00 ↔
  33.15/31.20) with the mean reference price drifting down — the F4 exhibit.

Caveats (stand-in honesty): ScriptedMind never CARTs, so CART/ABANDON funnel
rows are zero in these fixtures (the cart-resume path is exercised by
FormulaMind runs and choice.py units); its deterministic click rule yields a
high CTR among repeat-exposed shoppers (~0.5 among exposed) — do not read it
as a calibrated rate (that's `bench/calibrate_choice.py`'s job).
