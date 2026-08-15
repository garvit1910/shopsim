# ShopSim — a six-state-shopper market simulator on HydraDB

> These are not static personas answering prompts. Each shopper has an evolving
> model of the marketplace: what is objectively true, what happened to them,
> what they believe, what they have learned to prefer, what they currently
> need, and what people around them have experienced. HydraDB retrieves the
> portion of that evolving world model relevant to each new stimulus, and
> those paths alter subsequent behavior.

Hack Hydra submission — **Track 3: Memory & Context Retrieval**.
Team: Garvit · Atishay.

## Track fit (one sentence each)

| Requirement | Mechanism |
|---|---|
| Cross-session synthesis | `consolidate()` + evidence accumulation with provenance (`DERIVED_FROM`, cause-stamped `PREFERS` versions) |
| Chronological order | Episodic supersession + goal lifecycles + lagged fulfillment |
| Overwrite tracking | `valid_to` history on the subjective AND objective AND needs layers — history is never erased |
| Abstention | No path / no belief = no knowledge (null trust belief, empty motif list, gated appraisal) |

Honest scoping, stated up front: retrieval is a **motif library** (controllable
behavioral laws, by design), and goals are **exogenous** — this sim demonstrates
demand *capture*, not demand *creation*.

Adding a mechanism later = a motif-enum row + a classifier case + a registry
row — no schema change.

## Repo layout

```
engine/    Python 3.11 — HydraMem, sim runner, minds, contracts (shared enums, evidence.py)
web/       Next.js dashboard (Phase 5)
infra/     HydraDB run config + docker compose (Atishay)
eval/      Calibration & face-validity evals F1–F15 (Phase 7)
fixtures/  Demo brand assets + canned DecisionContexts + scripted-run fixtures
CONTRACT.md  The three inter-lane contracts (C1/C2/C3) — versioned; changes need a call
PLAN.md      Master build plan v4
```

## Setup (skeleton — final commands land in Phase 9)

```bash
# engine dev setup
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e './engine[dev]'
pytest engine

# full stack (Phase 9)
docker compose up   # hydradb (pinned digest) + engine + web
make demo
```

Secrets live in `.env.local` (gitignored). Copy `.env.example` if/when added.

## What breaks without HydraDB

Worldview-divergence queries (belief vs truth), typed motif paths per decision,
preference time-travel (`PREFERS` supersession chains with cause receipts),
goal-lifecycle joins, belief provenance, branch/replay, social influence paths (P1).

## Evals

See `/eval` (Phase 7): `make eval` reproduces every number and plot.
F7 (no learning from exposure) and F9 (the Maya law) are never-drop invariants.

## Attribution & license

- Our code: MIT (see `LICENSE`). HydraDB itself is AGPL and stays server-side.
- Aggregate CTR calibration ranges: Criteo / Avazu public datasets (Phase 7).
- All brands, products, and people in the fixtures are fictional.
