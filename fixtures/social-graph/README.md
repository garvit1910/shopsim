# `fixtures/social-graph/` — the frozen 04 Graph exhibit

`memory-graph.json` is a **photograph of a real run**. Every node, edge and trace in it
came out of HydraDB through the shipped read API (`HydraMem.get_memory_graph`,
`.find_social_triads`, `.get_trace`). Nothing in it is authored, mocked or reshaped for
looks.

| | |
|---|---|
| Source run | `r049-social-graph-demo-market` (run block 49, arm `market`) |
| Spec | [`fixtures/run-configs/social-graph-demo.json`](../run-configs/social-graph-demo.json) — 100 shoppers × 28 ticks, `population.social` on, `calibration.appraisal.w_social` 0.5 |
| As-of | day 27 of 28 — the last fully consolidated tick, the same clock the API pins every graph read to |
| Size | 69 nodes · 355 edges · 20 traces (3 shoppers × the stimuli each actually met) |

## Why this is committed rather than read live

Shopper worldviews live **only** in the graph store. `runs/` keeps events and results,
but the graph goes with the store — and the store is archived and recreated routinely
(see [`infra/README.md`](../../infra/README.md), "Before a demo or a timed run"; it
happened three times on 2026-08-20 alone). Reading it live meant the exhibit blanked
after every reset, and reshaped itself run to run in between. Freezing it makes the page
independent of the store's contents and of whatever simulation is loaded.

## The exhibit

The triple is picked by `find_social_triads`, which ranks mutually-trusting triples by
whether they can actually *show* the mechanism. It landed on one where all three friends
bought **and** took delivery:

```
  Owen #0026  brand_skeptic      1 bought, 1 experienced
  Duaa #0027  trail_adventurer   2 bought, 2 experienced
  Jack #0028  comfort_seeker     2 bought, 2 experienced

  #0026 <-> #0027   TRUSTS_PERSON w = 0.7890
  #0026 <-> #0028   TRUSTS_PERSON w = 0.6439
  #0027 <-> #0028   TRUSTS_PERSON w = 0.7983
```

28 `social_proof` motifs across the captured traces, e.g.

```
  [5900026, 'TRUSTS_PERSON', 5900027, 'BOUGHT', 3000001]   valence 0.6350
```

The run itself measured `social_lift` **1.32, `causal: true`** — P(buy) 3.95% on the 430
decisions that carried a `social_proof` motif against 3.00% on the 1102 that did not.
That is the first time this exhibit produced a positive causal result.

## What this is NOT

- **It does not reflect the currently loaded or running simulation.** It is one run,
  frozen. The page says so under its title; do not read it as live state.
- It is not a substitute for the live path. `GET /runs/{id}/memory-graph` still reads the
  store for any run that has one, and `/graph?run=<id>` still renders it.
- **It can go stale.** If retrieval or the motif library changes, the committed traces
  stop matching what the engine would compute today. Nothing detects that automatically —
  regenerate after any change to `hydramem/reads.py` or `contracts/enums.py`.

## Regenerating

Needs a store that actually holds the source run. If it has been archived, mount it back
first — `mv`, never `rm`, per `infra/README.md`.

```sh
cd engine
./.venv/bin/python -m shopsim.runner export-graph \
    --config ../runs/experiments/social-graph-demo/run_config.json \
    --run r049-social-graph-demo-market \
    --out ../fixtures/social-graph/memory-graph.json
```

To freeze a different run, point `--run` (and `--config`) at it; any run whose manifest
carries a `social_config_hash` will do. `GET /social-runs` lists them.

Pinned by `engine/tests/test_memory_graph.py` (no database required): every edge endpoint
resolves, the focus offsets are real shopper nodes, every trace key maps to a focus
shopper and a stimulus on screen, and the `TRUSTS_PERSON → BOUGHT → EXPERIENCED` chain is
present. Those tests are what stop a bad regeneration from shipping silently.
