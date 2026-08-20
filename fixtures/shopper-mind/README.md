# `fixtures/shopper-mind/` — the frozen 05 Mind exhibit

`mind.json` is a **photograph of a real run**, exactly like
[`fixtures/social-graph/`](../social-graph/README.md) one page over — every
node, edge, trace and preview came out of HydraDB and the engine's own
decision math through the shipped read API. Nothing is authored, mocked or
reshaped for looks.

| | |
|---|---|
| Source run | `r072-shopper-mind-demo-market` (run block 72, arm `market`) |
| Spec | [`fixtures/run-configs/shopper-mind-demo.json`](../run-configs/shopper-mind-demo.json) — the nisolo catalog (brand 6100, five real image ads), 100 shoppers × 28 ticks, `population.social` on, `w_social` 0.5 |
| As-of | day 27 of 28 — the last fully consolidated tick |
| The pinned shopper | `focus[0]` = offset **76**, the lead of the triad `find_social_triads` ranked best |
| Size | 65 nodes · 459 edges · 27 traces · **10 previews** (5 creatives + their landing pages, for the pinned shopper) |

## What's here beyond a social-graph capture (v3.12-draft)

`export-graph --previews` adds three keys to the envelope:

- **`catalog_key`** — which catalog the demo stimuli come from (`nisolo`), so
  the page can load the ad cards (image, headline, perceived claims).
- **`demo_stimuli`** — the five `{creative_id, page_id}` pairs baked for the
  pinned shopper. Landing pages are per-shopper seeded (`steps.page_for`), so
  these page ids are *this shopper's* pages.
- **`previews`** — `offset -> stimulus_id -> ` the exact `decision-preview`
  envelope (`scalars`, `motifs`, `appraisal`, `probabilities`,
  `counterfactual_need_off`), computed at export time by the very same
  `appraise()` / `stage_probabilities()` the live endpoint runs, via the
  shared `runner/preview.py`. No new math, no rng. Traits/coeffs still never
  leave the engine (Law 12/15) — only appraisal dims and gate probabilities.

Un-met stimuli are forced on screen by `get_memory_graph(extra_stimuli=…)`,
which closes them over their **objective** edges only (CLAIMS/OFFERS/
PROMOTES/SHOWS/PAGE_FOR from the store's objective cache) — nothing
subjective is invented for an ad the shopper never saw.

## Why this is committed rather than read live

Same reason as the social-graph exhibit: shopper worldviews live **only** in
the graph store, and the store is archived and recreated routinely
(`infra/README.md`, "Before a demo or a timed run"). The Mind page's whole
premise is that the pinned mind is chosen once and **always exists** — so it
must not blank when the store resets, and must not quietly become a different
shopper when a new simulation loads.

## What this is NOT

- **It does not reflect the currently loaded or running simulation.** The page
  says which run it is a photograph of, under its title — required provenance
  (v3.12-draft): a frozen mind that does not name its source reads as live.
- The lobe layout and the labelled inter-lobe connectors (INFLUENCES,
  SHAPES, …) on the page are the reference design's architecture legend —
  **presentation, not stored relationships**. Every solid edge is stored;
  every dashed edge is engine-derived; the connectors are neither and are
  styled apart.
- **It can go stale.** Regenerate after any change to `hydramem/reads.py`,
  `minds/appraisal.py`, `minds/choice.py`, or `contracts/enums.py` — the
  committed traces/previews stop matching what the engine would compute.

## Regenerating

Needs a store that actually holds the source run. If it has been archived,
mount it back first — `mv`, never `rm`, per `infra/README.md`. Or run the
spec again (fresh store, ~3 minutes) and export from the new run id:

```sh
cd engine
./.venv/bin/python -m shopsim.experiments run \
    --spec ../fixtures/run-configs/shopper-mind-demo.json --verbose
./.venv/bin/python -m shopsim.runner export-graph \
    --config ../runs/experiments/shopper-mind-demo/run_config.json \
    --run r0XX-shopper-mind-demo-market \
    --out ../fixtures/shopper-mind/mind.json --previews
```

Pinned by `engine/tests/test_shopper_mind_fixture.py` (no database required):
envelope keys, edge resolution, a creative **and** page preview per demo
stimulus with in-range probabilities, trace coverage for every previewed
stimulus with every motif-path node on screen, and the Law 12/15 forbidden-key
scan. Those tests are what stop a bad regeneration from shipping silently.
