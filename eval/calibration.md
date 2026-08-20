# 7.2 — Aggregate calibration, before and after

*What Phase 7 changed, why each change was made, and what the numbers were on
either side of it. Bands and sources are in [market-research.md](market-research.md).*

## The problem, as the committed runs recorded it

Two runs sat on `main` at the end of Phase 6, on opposite sides of one constant:

| run | profile | CTR | bounce | cart\|browse | buy\|cart | BOUGHT | blended ROAS |
|---|---|---|---|---|---|---|---|
| `r027` market-demo | `stage_bases.CLICK = 6.0` (default) | **0.67%** ✓ | 66.7% ✗ | 6.7% ✗ | — | **0** | — |
| `r039` market-20260819 | `stage_bases.CLICK = 2.0` (demo) | **28.0%** ✗ | 63.6% ✗ | 12.0% ✓ | 31.3% | 25 | **~46×** ✗ |
| target | — | 0.5–2% | 45–55% | 10–20% | 24–28% | — | 1.5–4× |

The obvious reading — "the click gate is mis-set, pick a value between 2.0 and
6.0" — is wrong, and acting on it would have buried the actual faults. Three
things were really happening.

## What the decision trace showed

Phase 7 added an opt-in decision trace (`--trace-decisions`): one row per
decision carrying the raw appraisal *inputs*, so any candidate calibration can
be replayed offline against contexts a real run actually produced. The first
traced baseline (300 shoppers × 24 days) reported:

```
pref_recency     mean 0.230   p50 0.125     <- preferences had gone stale
violation share  0.853        mean 0.42     <- 85% of page visits "violated"
trust share      0.021                      <- almost nobody holds a belief
model CTR 0.77%  bounce 59.9%  cart|browse 12.3%  buy|cart 17.5%
```

### 1. Taste was decaying at the speed of an ad

`preference_fit` carries a `recency` factor, and it shared **one constant** with
the fatigue and saturation motifs: `recency_half_life_s = 3 days`. A seeded
`PREFERS` prior is written at `t0 − 1 tick`, so by day 18 of a campaign its
recency had decayed to `2^(-18/3) = 0.016`. Since
`relevance = w_pref · (strength × recency)`, relevance had collapsed to a
twentieth of its day-one value and the entire funnel starved behind it.

An ad you saw on Tuesday is stale by Friday. Liking cushioned shoes is not.
These were never the same quantity; they were the same variable.

**Fix:** split them. `pref_recency_half_life_s = 30 days` for taste,
`recency_half_life_s = 3 days` retained for ad repetition
(`engine/shopsim/hydramem/schema.py`).

### 2. Every landing page was "violating" an expectation

`expectation_violation` fires on `EXPECTS(brand) − page SHOWS`, with no floor at
all. `EXPECTS` accumulates from *any* of a brand's creatives, so a shopper who
saw the comfort ad and landed on the eco page carried a violation — at mean
strength 0.42, which at the BROWSE weight of 1.5 is a **−0.64 utility penalty on
a page doing nothing wrong**. That, not the choice model, is what held bounce at
60–65%.

**Fix:** `violation_min_strength = 0.5` — an expectation must be genuinely held
before failing to meet it counts. The deliberate A/B variant still fires: it
hides a concept its own creative claims at strength 0.9.

### 3. The first click on a new concept ended learning immediately

The applier started an unheld concept at `(w = 0, E = 0)`, which makes
`blend()` degenerate: with no prior evidence, the first observation *is* all the
evidence, so one CLICK set `w = PREF_TARGET = 1.0` outright. Mean
`preference_fit` strength in `r039` was **0.958**, and every `preference_drift`
series for such a concept read a flat `1.0`. The chart could not show learning
because learning had finished on contact.

**Fix:** `COLD_START_W = 0.5`, `COLD_START_E = 1.0`
(`engine/shopsim/minds/calibration.py`). A shopper with no view on a concept is
*neutral* about it, and that neutrality is worth about half a seeded prior.
`contracts/evidence.py` is untouched and still frozen — the blend formula is
unchanged, only the caller's choice of starting state moved.

PLAN.md pinned the old behaviour in
`test_first_learned_version_of_an_unheld_concept_saturates` precisely so that a
future change would "fail loudly rather than silently reshape every drift
chart". It did, and the test was rewritten to pin the new rule with the old one
recorded in its docstring.

## The fit

With retrieval no longer starving the funnel, `shopsim.eval.calibrate` fit the
stage thresholds by coordinate descent over the traced contexts, scored against
the published bands. **Only one mind constant had to move:**

| constant | before | after | why |
|---|---|---|---|
| `stage_bases.CLICK` | 6.0 | 6.0 | already right |
| `stage_bases.BROWSE` | 2.3 | 2.3 | already right |
| `stage_bases.CART` | 3.7 | 3.7 | already right |
| `stage_bases.BUY` | 3.2 | **2.85** | P(BUY\|cart) 0.194 → 0.247 |

That is the useful result: the choice model was close to correctly calibrated
all along, and what looked like four broken gates was two retrieval constants
and a degenerate cold start.

## Before and after

Measured on the reference shape (300 shoppers × 20 days, demo-brand catalog, all
five creatives, promos on, **no A/B split** — see below), model-implied rates
over real traced decision contexts:

| metric | band | before | after | source |
|---|---|---|---|---|
| `p_click` | 0.005–0.020 | 0.0077 ✓ | 0.0085 ✓ | §1 Meta retail CTR 1.59–1.71% |
| `bounce_rate` | 0.45–0.55 | 0.599 ✗ | 0.511 ✓ | §2 BROWSE = 1 − bounce |
| `p_cart_given_browse` | 0.10–0.20 | 0.123 ✓ | 0.149 ✓ | §2 add-to-cart ~7% of sessions, ~2× on non-bounce |
| `p_buy_given_cart` | 0.24–0.28 | 0.175 ✗ | 0.247 ✓ | §2 1 − cart abandonment (72–76%) |
| `visit_to_purchase` | 0.01–0.03 | 0.0087 ✗ | 0.0180 ✓ | §2 apparel sitewide conversion 1–3% |

`visit_to_purchase` is the consistency check rather than an independent target:
0.49 × 0.15 × 0.25 ≈ 1.8%, which is where the apparel band independently lands.
The gates agree with each other, which is what "internally consistent" has to
mean.

## One more thing the baseline was doing to itself

Every pre-Phase-7 run carried `page_ids: [4000001, 4000002]`, a seeded 50/50
split that sends **half of all page traffic to the variant that deliberately
hides a claimed discount**. That is the right design for F5, which exists to
measure exactly that penalty. It is the wrong design for a reference run: a
normal site does not sabotage half its own landing pages, and leaving the split
on is a second reason the committed runs read a 63–67% bounce rate. The
reference config runs unsplit; the violating variant lives in `eval/specs/f5-violation.json`.

## The two profiles

| profile | what it is | when to use it |
|---|---|---|
| [`reference`](profiles/reference.json) | the calibrated profile above, certified against published bands | every eval artifact, every published number |
| [`demo`](profiles/demo.json) | accelerated, for a live demo at demo scale | the dashboard, where a 1% CTR over 300 shoppers produces too few events to show anything |

The honest problem the `demo` profile exists for: at a correctly calibrated
1.25% CTR, 300 shoppers × 20 days ≈ 11,000 impressions ≈ 140 clicks ≈ 2
purchases. Those are the *right* numbers and they make a dashboard that looks
broken. Rather than pretend otherwise, the demo profile states its acceleration
on every metric it distorts — see `eval/results/calibration.json`
(`demo_multiples`) and the CTR multiple already shown on the dashboard.

## Reproducing

```sh
make eval-fast     # analytic tier + rank agreement + report, seconds, no database
make eval          # everything, including the real scenario runs
```

The fit itself:

```sh
cd engine
../engine/.venv/bin/python -m shopsim.eval fit \
    --trace ../runs/<a traced run>/decisions.jsonl \
    --from-profile reference
```
