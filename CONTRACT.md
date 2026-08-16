# CONTRACT.md — the three inter-lane contracts

**Version: 3.2-draft** (v3.2 entries are additive conventions from Garvit's
Phase 2, **pending Atishay's ack** per the change rule — see change log)
**Change rule:** any contract or registry change = 5-minute call + version bump here, with a line in the change log at the bottom. `context.scalars` keeps the old v3 MemoryPacket byte-for-byte (first nine fields) — that back-compat is why ScriptedMind and the Phase-3 runner survive every architecture change.

Code is the enforcement layer: everything in this file has a single importable
source of truth under `engine/shopsim/contracts/` — `enums.py`, `ids.py`,
`evidence.py`, `types.py`, `registry.py`. If prose and code ever disagree, fix
the disagreement (call + bump); never let them drift silently.

---

## C1 — HydraMem API, v3

### Interface

```python
get_decision_context(shopper_id: int, stimulus_id: int) -> DecisionContext
```

Implementations: `shopsim.hydramem.mock.MockHydraMem` (Garvit's stand-in, canned
contexts from `/fixtures/contexts/`) and the real HydraMem (Atishay, Phase 1,
same signature; also `get_trace`, `get_shopper_worldview`,
`get_preference_history`, `ingest_catalog`, `record_events`, `supersede`,
`replay` per PLAN.md Phase 1 — those are engine-internal and not consumed by
minds, so they are specified by PLAN.md rather than frozen here).

### DecisionContext

Canonical example (Appendix B of PLAN.md, verbatim):

```json
{
  "scalars": {
    "shopper_id": 1000042,
    "aware_of_brand": true,
    "adstock": 0.62,
    "exposures_72h": 3,
    "last_seen_t": 1755150000,
    "reference_price": {"3000001": 39.0},
    "current_price_gap": -0.15,
    "budget_left": 120.0,
    "cart": [],

    "trust_belief":   {"value": 0.70, "evidence": 3.0, "confidence": 0.81},
    "quality_belief": null,
    "active_need":    {"category": 5504, "strength": 0.8, "urgency": 0.7, "budget_cap": 90.0},
    "habit":          {"stim_brand": 0.0, "rival_max": 0.55}
  },
  "motifs": [
    {"type": "goal_fit", "strength": 0.8, "urgency": 0.7,
     "path": [1000042, "NEEDS", 5504, "IN_CATEGORY", 3000001, "OFFERS", 2000003]},
    {"type": "preference_fit", "strength": 0.61, "evidence": 2.85, "recency": 1.0,
     "path": [1000042, "PREFERS", 5003, "CLAIMS", 2000003]},
    {"type": "brand_semantic_fatigue", "strength": 0.6, "recency": 0.7, "brand": 6001,
     "path": [1000042, "SAW", 2000001, "CLAIMS", 5003, "CLAIMS", 2000003]},
    {"type": "expectation_violation", "strength": 0.9,
     "path": [1000042, "EXPECTS", 5011, "NOT_SHOWN_BY", 4000002]},
    {"type": "social_proof", "valence": 0.8, "peer_trust": 0.7, "experience": 0.9,
     "path": [1000042, "TRUSTS_PERSON", 1000077, "BOUGHT", 3000001]}
  ]
}
```

### Scalar fields

The **first nine** fields are the v3 MemoryPacket, byte-compatible — do not
rename, reorder semantics, or retype them.

| Field | Type | Semantics | Consumed at |
|---|---|---|---|
| `shopper_id` | int | Appendix A shopper block | identity (bookkeeping) |
| `aware_of_brand` | bool | any SAW of a stimulus PROMOTES-ing this brand in window | appraise (F2 abstention gate; exact use fixed in Phase 2) |
| `adstock` | float ≥ 0 | decayed exposure pressure for this stimulus's brand | decide: utility `+γ·adstock` |
| `exposures_72h` | int ≥ 0 | frequency count, this stimulus, 72h window | decide: input to asset_wearout (δ term) |
| `last_seen_t` | int (epoch) or null | last SAW of this stimulus | decide: input to asset_wearout (δ term) |
| `reference_price` | {product_id(str): float} | shopper's smoothed reference price(s) for stimulus product(s) | engine-side: computes `current_price_gap` (display in UI) |
| `current_price_gap` | float | (current − reference)/reference; negative = realized deal | decide: utility `price_sensitivity · gap`, losses ×2 |
| `budget_left` | float | remaining spend budget this run | decide: hard guard `price > budget_left` blocks BUY |
| `cart` | [product_id] | current cart contents | decide: funnel stage state |
| `trust_belief` | BeliefScalar or **null** | live Belief about stimulus brand: `{value, evidence, confidence}` where `confidence = E/(E+0.7)` | appraise: credibility (P1: also decide risk term reads its confidence) |
| `quality_belief` | BeliefScalar or **null** | P1 quality belief, same shape | appraise: credibility/quality dims (P1) |
| `active_need` | ActiveNeed or **null** | `{category, strength, urgency, budget_cap}`; urgency computed in Python from deadline_t | `budget_cap` → decide only (BUY damp ×0.25); strength×urgency → appraise only, **via the goal_fit motif** (ScriptedMind, test-only, may read the scalars) |
| `habit` | HabitScalar or null | `{stim_brand, rival_max}`, strengths E/(E+2) | decide: `switching_inertia·(H_stim − H_rival_max)` at CART/BUY (P1) |

**Abstention, structurally:** `trust_belief: null` = no belief node = unknown
brand — appraisal must floor to neutral-low, never invent familiarity.
`active_need: null` = no goal_fit motif may appear. An empty `motifs` list is a
valid context (no paths = no knowledge). No belief/motif is ever fabricated to
fill a field.

**Information hygiene (Law 15):** `latent_quality` and `ship_reliability` must
never appear anywhere in a DecisionContext, trace, or worldview payload. The
hygiene contract test scans recursively for these keys.

### Motif entries

`type` ∈ MotifType enum (see Motif library below). `path` is the typed
evidence path: alternating node ids and edge-type strings. Per-type required
fields:

| type | required fields besides `type`/`path` |
|---|---|
| `preference_fit` | strength, evidence, recency |
| `goal_fit` | strength, urgency |
| `brand_semantic_fatigue` | strength, recency, brand |
| `expectation_violation` | strength |
| `concept_saturation` (P1) | strength |
| `social_proof` (P1) | valence, peer_trust, experience |
| `experience_path` / `habit_path` | explanatory only — appear in `get_trace`, never in `DecisionContext.motifs` |

Mock fixture obligations (all committed under `/fixtures/contexts/`):
need-on/need-off **twin pair** (identical except `active_need` + `goal_fit`),
low- vs high-confidence **belief pair**, a **fatigue-present** case, a
**social** case (P1), an **unknown-brand abstention** case (null trust, empty
motifs), and the Appendix-B reference context verbatim.

---

## C2 — Mind interface, v3

Three pure stages; minds never write to the graph (Law: one admitted writer —
the engine applies deltas).

```python
def appraise(ctx: DecisionContext, traits: AppraisalTraits) -> Appraisal
def decide(a: Appraisal, s: Scalars, coeffs: ChoiceCoeffs, rng) -> Action
def consolidate(events: list[Event], snapshot: WorldviewSnapshot) -> list[EvidenceDelta]
```

- `Appraisal` P0 dims (all 0..1): `relevance`, `credibility`,
  `brand_message_fatigue`, `offer_attractiveness`, `expectation_alignment`.
  P1 dims: `novelty`, `social_proof`.
- `Action`: IGNORE | CLICK | BOUNCE | BROWSE | CART | ABANDON | BUY
  (funnel: IGNORE|CLICK → BOUNCE|BROWSE → CART|ABANDON → BUY|ABANDON).
- `consolidate` is **pure**: same inputs ⇒ same deltas (contract-tested). It
  emits `EvidenceDelta{key: (kind: edge|belief, subject, object), target,
  weight, cause_kind, cause_id}`; the ENGINE applies them — batch-read current
  (w, E), blend per evidence.py, write supersessions in canonical order
  (shopper_id, t, event_rank).

### The typed persona split (Law 12)

```python
@frozen AppraisalTraits:  novelty_seeking, trust_orientation, deal_proneness   # appraise() only
@frozen ChoiceCoeffs:     impulsivity (= temperature τ, its ONE entry),
                          price_sensitivity, budget,
                          switching_inertia (P1), risk_aversion (P1),
                          stage_bases {stage: θ_s}                              # decide() only
```

Preference priors are **not** traits — they exist only as seeded PREFERS edges
(E0 = 2). Multiplying an affinity again in appraisal would count it twice.

### ENTRY_POINTS registry (full table — mirrored in `registry.py`, tested)

Each row: variable(s) consumed → the ONE pipeline point where they enter.

| # | Variable(s) | Entry point | Stage | Pri |
|---|---|---|---|---|
| 1 | preference priors (segment means) | seeded PREFERS edges, population factory | seeding | P0 |
| 2 | `preference_fit` motif (PREFERS.w ∩ claims) | appraisal: relevance | appraise | P0 |
| 3 | `goal_fit` motif (NEEDS.strength × urgency) | appraisal: relevance | appraise | P0 |
| 4 | scalar `active_need.budget_cap` | BUY damp ×0.25 guard | decide | P0 |
| 5 | scalar `trust_belief` (value × f(confidence, ·)) | appraisal: credibility | appraise | P0 |
| 6 | trait `trust_orientation` | appraisal: credibility | appraise | P0 |
| 7 | scalar `aware_of_brand` | appraisal: F2 abstention gate | appraise | P0 |
| 8 | `brand_semantic_fatigue` motif | appraisal: brand_message_fatigue | appraise | P0 |
| 9 | stimulus `claimed_pct` × trait `deal_proneness` | appraisal: offer_attractiveness (perceived deal) | appraise | P0 |
| 10 | `expectation_violation` motif | appraisal: expectation_alignment (1 − strength) | appraise | P0 |
| 11 | scalar `adstock` | utility +γ·adstock | decide | P0 |
| 12 | scalars `exposures_72h`, `last_seen_t` → asset_wearout | utility −δ·asset_wearout (the single asset-repetition entry, with row 11) | decide | P0 |
| 13 | scalar `current_price_gap` × coeff `price_sensitivity` | utility (realized price; losses ×2) | decide | P0 |
| 14 | scalar `reference_price` | engine-side input to `current_price_gap`; UI display | engine | P0 |
| 15 | coeff `impulsivity` | σ temperature τ | decide | P0 |
| 16 | coeff `budget` + scalar `budget_left` | hard guard: price > budget_left blocks BUY | decide | P0 |
| 17 | coeff `stage_bases` | θ_s per funnel stage | decide | P0 |
| 18 | scalar `cart` | funnel stage state | decide | P0 |
| 19 | `concept_saturation` motif × trait `novelty_seeking` | appraisal: novelty (deliberately NOT adstock-driven) | appraise | P1 |
| 20 | `social_proof` motif | appraisal: social_proof | appraise | P1 |
| 21 | scalar `habit` × coeff `switching_inertia` | utility CART/BUY: ·(H_stim − H_rival_max) | decide | P1 |
| 22 | coeff `risk_aversion` × (1 − trust confidence) | utility BUY: −risk_aversion·(1−conf) | decide | P1 |
| 23 | scalar `quality_belief` | appraisal: quality/credibility dims | appraise | P1 |

**Registry tests (completeness + separation):**
1. every `AppraisalTraits` field appears in **exactly one** row, and only in appraise-stage rows;
2. every `ChoiceCoeffs` field appears in **exactly one** row, and only in decide-stage rows;
3. every `Scalars` field appears in **at least one** row (`shopper_id` exempt as identity; `trust_belief` appears twice by design — rows 5 and 22 — the only sanctioned dual read, P1);
4. every **behavioral** motif appears in exactly one row; **explanatory** motifs (experience_path, habit_path) appear in none;
5. `decide()` signature contains no traits parameter (Phase-2 test);
6. import-graph: traits module importable only by the appraisal module (Phase-2 test).

### Bucket key v2 (P1 LLM appraisal freeze)

`(stimulus_id, segment_id, sorted[(motif_type, strength∈{0,L,M,H})], trust∈{none,L,M,H}×conf∈{L,H}, need∈{none,L,M,H}, fatigue_bucket, price_gap_bucket)` — coarse buckets, a few hundred keys per run, cached, frozen, hash in manifest. Formula appraisal is the calibration backbone; the LLM impl is P1.

---

## C3 — Results & metrics, v3

`results.json` / `MetricsReport` top-level keys (all snake_case; optional keys marked `?`):

```
run_manifest{seed, config_hash, perception_cache_hash, appraisal_cache_hash,
             evidence_hash, goal_config_hash, latent_quality_hash, social_config_hash?}
funnel[arm][segment]
ctr_by_day[]
fatigue_split{asset[], brand_msg[], concept[]?}
reference_price_trajectory[]
violations{count, bounce_delta}
motif_stats{type: {prevalence_by_outcome, mean_strength}}
preference_drift[{concept, segment, series}]
goal_stats{p_buy_need_on, p_buy_need_off, time_to_satisfaction[]}
belief_confidence_dist[]
belief_drift[]
provenance_coverage
repeat_ltv_by_arm[]?
social_lift?
ci{metric: [lo, hi]}
```

Stand-in: committed fixture files from a ScriptedMind run land in
`/fixtures/scripted-run-1/` (Atishay, out of Phase 3). Garvit builds the entire
dashboard on those fixtures.

---

## Event taxonomy v2

**Episodic edges** (stored in HydraDB, all carry `{t, run, …}`):
`SAW, CLICKED, VISITED, BROWSED, BOUNCED, CARTED, ABANDONED, BOUGHT, PRICE_SEEN, EXPERIENCED`.

**Log-only records** (JSONL, never episodic edges):
`NEED_ACTIVATED, NEED_EXPIRED, NEED_SATISFIED` — the NEEDS lifecycle itself
lives as supersessions on the NEEDS edge.

**Derived, never stored:** IGNORE (a SAW with no CLICK) — it is an `Action`,
not an event.

---

## Closed vocabularies (Law 11)

Four closed enums, ONE shared file: `engine/shopsim/contracts/enums.py` —
`Concept` (30, ids 5000–5029, incl. `OTHER`; unknown perception claims map to
`OTHER`), `Category` (10, ids 5500–5509), `MotifType`, `EventType` (+ the
`Action` enum). Enforced at parse time; vocabulary drift silently empties every
graph intersection. Adding a member = contract change (call + bump).

Anchor ids fixed by the Appendix-B example: `ECO_FRIENDLY = 5003`,
`DISCOUNT = 5011`, `RUNNING_SHOES = 5504`.

## ID allocation map (Appendix A)

| Entity | Range |
|---|---|
| Segment | 1,000+ |
| Concept | 5,000–5,499 |
| Category | 5,500–5,999 |
| Brand | 6,000+ (demo = 6,001 ShoeCo; rivals 6,002 TrailForge, 6,003 UrbanStride) |
| Shopper | 1,000,000 + run_index × 100,000 (run isolation; TRUSTS_PERSON stays within a run block) |
| Creative | 2,000,000+ |
| Product | 3,000,000+ (latent props unretrievable, Law 15) |
| PageVariant | 4,000,000+ |
| Belief node | 8,000,000+ (per shopper-run block offset; new id per version) |

Code: `engine/shopsim/contracts/ids.py`.

## Motif library v2 (Appendix E)

| Motif | Path signature | Entry point | Pri | Role |
|---|---|---|---|---|
| preference_fit | PREFERS · CLAIMS | appraisal: relevance | P0 | behavioral |
| goal_fit | NEEDS · IN_CATEGORY · OFFERS | appraisal: relevance (strength × urgency) | P0 | behavioral |
| brand_semantic_fatigue | SAW · CLAIMS · CLAIMS ⋈ same PROMOTES brand | appraisal: brand_message_fatigue | P0 | behavioral |
| expectation_violation | EXPECTS vs SHOWS diff | appraisal: expectation_alignment | P0 | behavioral |
| concept_saturation | SAW · CLAIMS · CLAIMS ⋈ other brand | appraisal: novelty (inverse) | P1 | behavioral |
| social_proof | TRUSTS_PERSON · BOUGHT (+EXPERIENCED valence) | appraisal: social_proof | P1 | behavioral |
| experience_path | EXPERIENCED · SOLD_BY · PROMOTES | trace only — effect via trust belief | P0 | explanatory |
| habit_path | BOUGHT · SOLD_BY history | trace only — effect via habit scalars | P1 | explanatory |

Retired (v3, absorbed to prevent double-counting): `brand_transfer`,
`trust_path` — must NOT exist in the enum.

Signals deliberately scalars, not motifs (Law 16): reference price, price gap,
budget, need budget cap, trust/quality belief values, habit strengths,
adstock/wearout.

**Routing (Phase 1.1 probe, 2026-08-16, measured live — see `engine/bench/probe11.py`):**

**Route B everywhere.** `algo.SPpaths` accepts heterogeneous relTypes lists but is
strictly direction-following — every motif path traverses at least one edge against
its stored direction (e.g. `PREFERS→concept←CLAIMS`), and those calls return 0 paths.
SPpaths also cannot return edge props (w, E, t), which the motifs need anyway.
Route B = per-shopper single-hop reads (~0.3ms each) joined in Python against the
per-tick stimulus/objective cache. Full contexts: one ≈ 9ms warm; 200 shoppers × 1
stimulus batched ≈ 0.6s.

| Motif | Route (A = SPpaths / B = single-hop + Python) | Measured latency |
|---|---|---|
| preference_fit | B (`PREFERS` single + cached stimulus `CLAIMS`) | 0.35ms med / 0.46ms p95 per shopper statement |
| goal_fit | B (`NEEDS` single + cached `IN_CATEGORY`/`OFFERS`) | 0.32ms med / 0.35ms p95 |
| brand_semantic_fatigue | B (windowed `SAW` single + cached claims, Python join) | 0.31ms med / 0.34ms p95 |
| expectation_violation | B (`EXPECTS` single + cached `SHOWS` diff) | 0.31ms med / 0.35ms p95 |

Probe by-catch (now load-bearing in `hydramem/cypher.py`): multi-assignment `SET`,
compound `WHERE … AND …`, `WHERE` on destination-node props, destination-node props
in one-hop RETURNs, and `ORDER BY … LIMIT` all work; aggregates (`count()`) do NOT —
all counting stays in Python. Batched UNWIND DELETE requires both endpoints anchored.
Prop-carrying writes are server-serialized at ~200–230 stmts/s (single-writer
commit path; parallel sessions don't help; the slatedb env override proved inert —
see /infra/README.md "Write throughput"). The 10k-batch perf target is amended in
PLAN.md accordingly; real per-tick load fits the Phase-3/S1 wall-clock budgets,
with write-behind overlap as the pre-agreed escalation.

## Evidence table (Appendix F) — source of truth: `engine/shopsim/contracts/evidence.py`

| Event | Pref weight | Trust/belief weight | Notes |
|---|---|---|---|
| SAW | 0 | 0.2 (EXPECTS only) | awareness, adstock, expectations — never taste |
| IGNORE (derived) | 0 (P0) | 0 | ambiguous without an attention model (P2) |
| CLICK | 0.10 | 0.2 | prefs on stimulus-claimed concepts, target = 1 |
| BROWSE / VISITED | 0.25 | 0.75 (target 0.6) | |
| CART | 0.50 | — | |
| BUY | 1.00 | 1.5 (target 0.65) | also: satisfy NEEDS; habit +1 (P1) |
| EXPERIENCED | ±0.75·(2·sat−1) | 2.0 (target = sat) | prefs only on HAS_ATTR concepts; P1: ×(1 + 0.5·max(0, expectation − sat)) |
| Social report (P1) | 0 | 0.5 · peer_trust | |

One formula everywhere: `w' = (E·w + wt·target)/(E + wt)`; `E' = min(E + wt, 8)`.
Priors seed E0 = 2. Confidence = `E/(E + 0.7)`. Bounds (Law 14): skip |Δw| < ε
= 0.01; ≤ 6 subjective writes/shopper/tick, priority need-satisfy > trust >
preferences > expects. Reference-price smoothing α = 0.3.

The signed EXPERIENCED preference weight `±0.75·(2·sat−1)` is encoded as
magnitude `0.75·|2·sat−1|` with target 1 if sat ≥ 0.5 else 0 (sat = 1 ⇒
weight 0.75 toward 1, reproducing the golden chain's 0.761; sat = 0 ⇒ weight
0.75 toward 0).

Golden chain (contract-tested to the digit): eco prior 0.45 (E=2) → CLICK
0.476 → BROWSE 0.532 → CART 0.614 → BUY 0.714 → positive experience 0.761
(E=4.6, confidence 0.87). Trust from 2 visits + 1 purchase: E=3.0 → confidence
0.81.

## Determinism & event-log rules (Law 13)

- **JSONL event log is the replay source of truth**, including
  NEED_ACTIVATED/EXPIRED/SATISFIED and EXPERIENCED records. Worldview
  supersessions are **recomputed on replay** from events + evidence.py — never
  logged (keeps the log lean and the math the single source).
- Run manifest carries **five hashes**: perception cache, appraisal cache,
  evidence.py, goal config, latent-quality table (+ social config, P1). Replays
  refuse to run if any changed.
- Seeded substreams keyed by stable tuples: goals `(seed,"goal",shopper,tick)`,
  fulfillment `(seed,"fulfil",shopper,product,purchase_t)`, social graph
  `(seed,"social",population)`.
- Consolidation applies in canonical order `(shopper_id, t, event_rank)`;
  `consolidate()` is pure; the fulfillment queue is derived from BOUGHT events
  + lag, never persisted separately.

## Shared contract tests (run on both stand-ins AND both real implementations)

`engine/tests/`: context schema (incl. null-belief abstention), motif enum
coverage, registry completeness + stage separation, evidence.py golden-chain
digit-exact + E-cap + trust fixture, twin-pair minimal diff, hygiene (no latent
props), consolidate purity (skips until a Mind implementation exists).

---

## Change log

- **3.0** (2026-08-16): initial commit of contracts v3 per Master Plan v4.
  Appendix F transcribed from the authoritative copy (Garvit); signed
  EXPERIENCED weight encoding fixed as magnitude+target (see Evidence table).
  Routing table left TBD for Atishay's Phase 1.1 probe.
- **3.1** (2026-08-16, Atishay): routing table filled from the Phase 1.1 probe —
  Route B for all four P0 motifs (SPpaths is direction-following; heterogeneous
  reversed-hop paths return nothing). Real HydraMem landed
  (`engine/shopsim/hydramem/real.py`); the full contract suite passes on it via
  `SHOPSIM_HYDRAMEM=real uv run pytest` against the seeded story graph. New
  EvidenceDelta kind conventions documented in `hydramem/writes.py` (kind strings
  "expects"/"ref_price"/"need_satisfy"/"habit"/"belief:quality" beside the C2
  "edge"/"belief"): additive, no signature change — flagging to Garvit whose
  consolidate() will emit them.
- **3.2-draft** (2026-08-17, Garvit — Phase 2; **additive conventions only, no
  C1/C2/C3 signature, enum, taxonomy, ENTRY_POINTS-row or evidence.py change;
  pending Atishay's ack at the next sync**):
  1. **Mind-bound ObjectiveView** (`minds/objective_view.py`): stimulus-side
     objective facts (claims, claimed_pct, SHOWS) + catalog truth (HAS_ATTR,
     SOLD_BY, IN_CATEGORY) reach the mind at construction —
     `FormulaMind(view).for_stimulus(id)` — never through C1 scalars. This is
     how registry row 9 (`stimulus:claimed_pct`) is fed, and what
     `consolidate()` uses for concept attribution. The view is frozen and
     hashable (manifest input).
  2. **Funnel semantics (two-phase, deepest-action)**: a creative decision
     returns IGNORE|CLICK; a page decision walks BOUNCE|BROWSE → CART →
     BUY|ABANDON with one rng draw per gate and returns the deepest stage
     reached (fail the cart gate after browsing ⇒ BROWSE — ABANDONED is
     reserved for a resumed cart failing BUY, since the episodic ABANDONED
     edge targets a carted product). The runner expands the returned Action
     into episodic events.
  3. **Sanctioned price derivation in decide()**: current price =
     `reference_price × (1 + current_price_gap)`; with no reference price the
     budget guards (rows 4/16) cannot fire. No new Scalars field.
  4. **EXPECTS delta target = perceived claim strength** (SAW and the CLICKED
     reinforcement, weight from evidence.py); the applier α-smooths toward it
     and resolves the brand from the causing creative's PROMOTES.
  5. **Perception owns stimulus edges in engine runs**:
     `ingest_catalog(..., include_stimuli=False)` (default True keeps every
     Phase-0/1 path byte-identical) + `perception.writer.write_stimuli()`
     writing CLAIMS{strength}/PROMOTES/OFFERS{claimed_pct}/SHOWS/PAGE_FOR from
     the committed perception cache (`fixtures/perception-cache/`, one OpenAI
     structured-output call per unique stimulus, Concept-enum enforced,
     unknown → OTHER). HAS_ATTR/IN_CATEGORY/prices stay catalog-only.
  6. **`cause_creative` event prop** (Event.props, JSONL-only — not a graph
     edge prop): the runner stamps page/product funnel events with the
     originating creative id so `consolidate()` attributes preference evidence
     to the ad's claimed concepts; without it, attribution falls back to
     catalog truth (HAS_ATTR ∩ SHOWS for pages, HAS_ATTR for products).
  7. **Segments 1007–1013** added to `fixtures/demo-brand/goal_config.json`
     (additive rows) + the new `fixtures/demo-brand/personas.json` consumed by
     `population/factory.py`; population size and segment count are config
     (validated to 50 segments / 5,000 shoppers). Law-12 import isolation is
     enforced as source-scans (traits stay in `contracts/types.py`).
