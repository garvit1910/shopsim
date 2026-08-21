# CONTRACT.md — the three inter-lane contracts

**Version: 3.12-draft** (3.3 flagged to Garvit 2026-08-17 and built on by
Phase 4; 3.4-draft added the experiment-adapter conventions, 3.5-draft the
live dashboard data plane, 3.6-draft the shared ad market + pricing ladder, 3.7-draft the creative-text
read surface + the Nisolo brand fixture, 3.8-draft the Phase-6 analytics that
fill C3's remaining placeholders + the opt-in social layer, 3.9-draft the
memory-graph read surface behind the dashboard's 04 Graph exhibit,
3.11-draft the frozen 04 Graph capture,
3.12-draft the frozen Shopper Mind capture behind 05 Mind,
3.10-draft the Phase-7 calibration layer — a `calibration.retrieval` sub-block,
two split retrieval constants, a learning cold-start prior and an opt-in
decision trace. All additive to the *interfaces*: no C1/C2/C3 signature, enum,
taxonomy or ENTRY_POINTS-row change, and `contracts/evidence.py` is untouched
and still frozen by hash. **3.10-draft does change BEHAVIOUR** — it is the
first version that deliberately moves numbers rather than only adding keys, so
it re-hashes runs and regenerates `fixtures/golden-run`; see the change log and
`eval/calibration.md` for what moved and why. Plus one C1 scalar bug-fix in 3.4
(cart re-derivation) — see change log; **3.4-draft through 3.11-draft all
pending Atishay's ack at the next sync**. Note: this header sat at 3.4-draft while the
3.5-draft change-log entry was already written — the bump was missed then and
is corrected here.)
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

**Concrete shapes** (Phase 3 fixed the first eight; Phase 6 / v3.8-draft fixed
the rest, which had been typed-but-empty since Phase 3):

```
fatigue_split{channel: [{tick, n, mean, high_n, high_ctr, low_n, low_ctr}]}
    channels: asset | brand_msg | concept
belief_drift[{aspect, about, segment|"all", series[], confidence_series[]}]
belief_confidence_dist[{aspect, bin_lo, bin_hi, count}]         10 bins/aspect
provenance_coverage{coverage, prefers{versions, learned_versions, with_cause,
    coverage, cause_kinds{}}, beliefs{versions, with_provenance, coverage},
    belief_scope} | null
ci{"<metric>"|"<metric>:<segment>": [lo, hi]}
    metrics: ctr · browse_rate · cart_rate · buy_rate · buy_per_exposure ·
             p_buy_need_on · p_buy_need_off
repeat_ltv_by_arm[{arm, buyers, buys, repeat_buyers, repeat_rate,
    buys_per_buyer, revenue_total, revenue_per_buyer}]
social_lift{p_buy_social_on, p_buy_social_off, lift, decisions_on,
    decisions_off, w_social, causal, note} | null
violations{count, bounce_delta}    bounce_delta = within-run pooled B - A
```

Additive keys beyond the C3 list, in emission order:
`funnel_by_creative` · `funnel_by_page` · `ctr_by_creative_by_day` (v3.4-draft)
· `revenue{total, by_creative}` (v3.6-draft).

Stand-in: committed fixture files from a ScriptedMind run land in
`/fixtures/scripted-run-1/` (Atishay, out of Phase 3). Garvit builds the entire
dashboard on those fixtures. The Phase-6 golden — 5 shoppers x 3 ticks, one
full evidence chain, every number hand-checked — is `/fixtures/golden-run/`.

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
  evidence.py, goal config, latent-quality table (+ social config, P1) — plus,
  v3.3: `config_hash` (sha256 of the canonical run_config JSON + arm name) and
  `view_hash` (the frozen ObjectiveView). **Resume** refuses if ANY hash
  changed; **branch** allows exactly `config_hash` to differ (the config delta
  IS the branch) and refuses on the rest.
- Seeded substreams keyed by stable tuples: goals `(seed,"goal",offset,tick)`,
  fulfillment `(seed,"fulfil",offset,product,purchase_t)`, social graph
  `(seed,"social",population)`; v3.3 adds exposure `(seed,"expose",offset,tick)`
  and decisions `(seed,"decide",offset,tick,stimulus_id)`. All "shopper" keys
  are block OFFSETS, never absolute ids, so the same seed reproduces the same
  trajectory in any run block.
- Consolidation applies in canonical order `(shopper_id, t, event_rank)`;
  `consolidate()` is pure; the fulfillment queue is derived from BOUGHT events
  + lag, never persisted separately.
- **Tick markers & resume (v3.3):** the runner appends a raw
  `{"type":"TICK_COMPLETE", tick, t, run, n_events, belief_counter}` record
  (fsync'd) after each fully-consolidated tick — a log record, deliberately
  NOT an EventType member (the closed taxonomy is untouched; replay treats it
  as tick metadata). All events of tick k carry `t = t0 + k·tick_seconds`,
  ordered within a shopper by event_rank. Resume = roll the partial tick back
  by timestamp (every graph write of tick k has `t == now_k` on creates or
  `valid_to == now_k` on supersessions), truncate the JSONL to the last
  marker, rebuild in-memory state from the log, re-run the tick.

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
- **3.3** (2026-08-17, Atishay — Phase 3, the runner; additive conventions
  only, no C1/C2/C3 signature, enum, taxonomy, ENTRY_POINTS-row or evidence.py
  change; flagging to Garvit at the next sync):
  1. **Run registry + fresh blocks**: every run allocates a fresh `run_index`
     from `<repo>/runs/registry.json` (blocks 0–9 reserved for the story graph
     and integration tests). Shopper ids inside configs (goal_config `scripted`
     rows, run_config) are block-0-anchored and remapped by offset into the
     active block: 1000042 means offset 42 in whatever block the run gets.
  2. **run_config.json** (`fixtures/run-configs/scripted-run-1.json` is the
     reference): seed, ticks, t0, tick_seconds, mind {decide, consolidate},
     population {size, personas}, exposure {schedule rows
     {creative_id, start_tick, end_tick, reach_prob, page_id?}, per-tick +
     72h frequency caps}, goals {config, overrides {scripted_enabled,
     waves_enabled}}, fulfillment {lag_ticks=2, sat_noise_sd=0.08 — sat =
     clamp01(latent_quality + N(0, sd))}, promos {schedule, enabled}, arms
     [{name, goal_overrides, branch_from?, divergence_tick?}].
  3. **Action→event expansion table** (`runner/expansion.py`, the v3.2 item-2
     "runner expands" made concrete): creative IGNORE→SAW, CLICK→SAW+CLICKED;
     page BOUNCE→BOUNCED **only** (no VISITED/PRICE_SEEN — a bounce must not
     teach taste, and PRICE_SEEN requires engaging past the bounce);
     fresh BROWSE→VISITED+PRICE_SEEN+BROWSED, CART→…+CARTED,
     BUY→…+CARTED+BOUGHT; resumed-cart BUY→VISITED+PRICE_SEEN+BOUGHT,
     ABANDON→VISITED+PRICE_SEEN+ABANDONED. Every page/product funnel event
     carries `cause_creative` (v3.2 item 6). Click→page happens in the SAME
     tick (second batched retrieval); consolidation runs once at tick end.
  4. **Page resolution**: a scheduled creative lands on the lowest page_id
     whose PAGE_FOR product it offers (the "consistent" variant by fixture
     convention), overridable per schedule row; a creative whose products
     have no page ends its funnel at CLICK.
  5. **NEED_SATISFIED emission**: `consolidate()` emits the `need_satisfy`
     delta, the applier supersedes-with-cause, and the runner then writes the
     NEED_SATISFIED JSONL record from `ApplyReport.satisfied_needs` — so the
     record reflects what was actually applied. Replay asserts recomputed
     satisfactions equal the logged set, per tick.
  6. **Applier fold rule** (Law-14 clarification, engine-side): same-key
     deltas within one tick — (kind, object), EXPECTS keyed with its resolved
     brand — fold into ONE supersession recording the tick's final blended
     state; the blend still applies per delta in canonical order and belief
     DERIVED_FROM accumulates every folded cause. The ≤6-writes cap counts
     distinct state changes, not event volume. `ref_price` ranks above
     `expects` in the cap priority (the Law-14 list orders only need-satisfy >
     trust > preferences > expects; ref price is load-bearing for the budget
     guards and F3/F4).
  7. **C3 concretes**: `results.json` carries the full C3 key skeleton —
     real values for run_manifest/funnel/ctr_by_day/preference_drift/
     goal_stats/reference_price_trajectory/motif_stats/violations.count,
     typed-but-empty placeholders for the Phase-6 analytics keys
     (fatigue_split, belief metrics, bounce_delta, ci). Validator:
     `runner/results.py::validate_results`. `progress.json` (per tick, atomic)
     + a read-only FastAPI (`GET /runs`, `/runs/{id}/progress`,
     `/runs/{id}/results`) serve the dashboard. No wall-clock value enters
     results.json or manifest.json: same seed ⇒ byte-identical results.

- **3.4-draft** (2026-08-18, Garvit — Phase 4, experiment adapters; additive
  conventions + one C1 scalar bug-fix; no C1/C2/C3 signature, enum, taxonomy,
  ENTRY_POINTS-row or evidence.py change; every default is a no-op — the
  committed scripted-run-1 fixtures replay byte-identical and their
  config_hash is pinned by a golden test; pending Atishay's ack at the next
  sync):
  1. **run_config additive fields** (all inside `raw` ⇒ covered by
     `config_hash`; branch/resume semantics unchanged): schedule rows gain
     `audience_segments?` (targeting) and `page_ids?` (seeded A/B split, ≥ 2
     distinct pages); arms gain `exposure_overrides?`
     ({`schedule` replace | `add` append — never both}) and `promo_overrides?`
     ({`enabled`, `schedule_inline` — an inline `product_promos` payload, so
     promo CONTENT is config_hash-covered; the promo file path never was});
     goal overrides gain `extra_waves` (wave rows) and `wave_scale`
     (m ⇒ 1 + (rm−1)·scale; 0.0 neutralizes, absent key = the exact Phase-3
     arithmetic); top-level `calibration {appraisal, choice{...,
     stage_weights}, stage_bases}` → `minds/calibration.py` params for the
     formula mind + population θ (evidence.py stays frozen; parser:
     `runner/config.py::parse_calibration`, unknown keys refused).
  2. **New substream** `(seed, "page", offset, creative_id)` — the seeded
     50/50 page assignment for `page_ids` rows. Drawn ONCE per (offset,
     creative), tick-free, never logged; re-derived by the same pure resolver
     (`steps.page_for`) at click time, state rebuild, and replay. Non-split
     rows take the static map with zero draws (`RunnerState.
     rebuild_from_records` now takes that resolver instead of a pages dict).
  3. **Audience filter position**: AFTER the per-row reach draw, before the
     cap checks — the exposure stream shape stays state- and audience-
     independent (the goal step's skip-if-live discipline); filtered
     exposures consume no caps and emit no SAW.
  4. **results.json additive keys** (validated only when present — pre-4
     fixtures keep validating): `funnel_by_creative` (SAW/CLICKED by subject,
     deeper funnel by `cause_creative`; EXPERIENCED unattributed),
     `funnel_by_page` (VISITED/BROWSED/BOUNCED + `bounce_rate` =
     BOUNCED/(VISITED+BOUNCED)), `ctr_by_creative_by_day`. results_state
     round-trips them; `from_state` tolerates pre-4 snapshots.
     `violations.bounce_delta` REMAINS the Phase-6 placeholder: cross-arm
     deltas live in the experiment `comparison.json`, never in a single
     run's results.json.
  5. **Pricing convention**: a promo-"off" arm runs the SAME promo hook with
     a zero-discount schedule over the same products — PRICED_AT is global
     objective state served by as-of reads, so an off arm that skipped the
     hook would read the on arm's discounts. Experiment arms run in declared
     order (shelf-aligning zeroed arms first, promo-heavy last, branches
     right after their sources), and each experiment uses its own t0 window.
  6. **Perception image path**: creative rows may carry `image` (path
     relative to the catalog dir). The descriptor gains `image_sha256` ONLY
     then — text descriptors, `PROMPT_VERSION "p1"`, and the five committed
     cache entries stay byte-identical (golden test recomputes their keys).
     Image entries key on `IMAGE_PROMPT_VERSION "p1-img1"`; the call is
     multimodal (data-URI content block, mime sniffed from magic bytes) with
     an image addendum on the system prompt. Ingestion
     (`shopsim.experiments.ingest`) materializes
     `fixtures/experiments/<name>/{catalog/, perception-cache/}` (demo-brand
     copied; base cache entries copied byte-identical; new ids =
     max_existing + 1, NEVER `IdAllocator.next_creative()` which restarts at
     2000001), perceives once live (loud `OPENAI_API_KEY` refusal at ingest,
     never at run time), and is idempotent. Shared fixtures' hashes never
     move.
  7. **`shopsim.experiments`**: spec types `ad_test` (one arm per creative,
     shared seed = paired populations) / `pricing` / `page_ab` (within-run
     seeded 50/50) / `scenario` (+ `fixtures/scenarios/` packs:
     `marathon-season` P0; `overpromise`, `social-on-off` P1 stubs that
     refuse with named reasons — overpromise changes `latent_quality.csv`, a
     SHARED hash ⇒ fresh-run-only, never a branch). Builders emit ordinary
     run_configs (the spec rides under an `experiment` key, hash-covered)
     and materialize the FULL effective calibration block so `config_hash`
     pins every mind constant. CLI: `python -m shopsim.experiments
     {run, compare, ingest-ads}`; cross-arm report = `comparison.json`.
     Phase 5's launcher drives this surface.
  8. **C1 bug-fix — cart re-derivation** (`hydramem/reads.py`): a BOUGHT
     resolves only carts made at or before it (symmetric with ABANDONED) —
     previously ANY historical purchase excluded the product from
     `scalars.cart` forever, desyncing the mind from the runner's cart state
     and crashing resumed-cart expansion on a repeat purchase (exactly the
     promo-addiction scenario). ScriptedMind never CARTs, so every committed
     fixture is bit-for-bit unaffected; pinned by
     `tests/test_cart_rederivation.py`.
- **3.5-draft** (2026-08-18, Garvit — Phase 5, the live dashboard; additive
  only: no C1/C2/C3 signature, enum, taxonomy, ENTRY_POINTS-row or
  evidence.py change; the three Phase-3 endpoints and every results.json/C3
  key are byte-identical; pending Atishay's ack at the next sync):
  1. **Dashboard API surface** (`runner/api.py`, same read-only FastAPI):
     `GET /runs/{id}/manifest` · `/events?after=<byte>&limit=` (JSONL tail by
     byte offset; a trailing partial line is dropped and re-served next poll;
     `after` beyond the file restarts at 0 — resume truncation) ·
     `/results-live` (latest `results_state_{k}.json` rendered through
     `ResultsAccumulator.from_state().results()` — the FULL C3 shape at tick
     k, plus `live_extras.belief_avg` from item 3, kept OUT of the C3
     skeleton so the Phase-6 `belief_*` keys stay untouched) · `/config`
     (raw run_config + an `effective` block computed with the shipped
     `RunConfig` helpers: per-arm schedule, promo windows, goal overrides +
     waves) · `/population` (deterministic `generate_population` recompute —
     identity + segment ONLY; traits/coeffs/budget never leave the server,
     Law 12/15) · `/shoppers/{offset}/{worldview | preference-history/{c} |
     belief-history | trace/{s}}` (the `export-fixtures` read pattern,
     per-run HydraMem + lock, reads as-of the last completed tick) ·
     `GET/POST /experiments`(+`/{name}`, `/ingest-ads`). The one POST spawns
     `python -m shopsim.experiments run` detached (pid + log files) — Law 8
     intact: the dashboard never writes the graph; the engine subprocess is
     the admitted writer. **Launches are serialized (409 while any run is
     live)** because `RunStore.allocate`'s registry read-modify-write is not
     concurrent-safe.
  2. **`GET .../decision-preview/{stimulus_id}`** — the "why" surface: the
     REAL `get_decision_context` → the REAL `appraise()` (traits from the
     deterministic population recompute, server-side only) → the new pure
     helper `minds.choice.stage_probabilities()` (item 4). When
     `active_need` is present the response adds a labeled counterfactual
     (same context, `active_need` nulled + goal_fit motifs stripped,
     re-appraised). No rng anywhere; two calls are byte-identical.
  3. **Belief sweep** (`runner/results.py::end_tick_sweep`): a third
     statement per shopper in the existing `run_grouped` batch (live HOLDS);
     mean trust-belief value per brand × segment lands in a new accumulator
     field `belief_avg` keyed `"trust:{brand}:{seg}"` / `"trust:{brand}:all"`
     (same per-tick list + None-padding convention as `drift`).
     `results_state` round-trips it via `.get` (pre-3.5 snapshots still
     resume); `results()` does NOT emit it — C3 and the Phase-6 placeholders
     are untouched. Powers the live "avg brand trust" pulse.
  4. **`minds/choice.py::stage_probabilities(a, s, coeffs, kind, params)`**
     (public, pure, rng-free): the per-gate advance probabilities `decide()`
     draws against — creative → CLICK; page → BROWSE/CART/BUY (BUY includes
     the budget guards). The decision path is unchanged and never calls it.

- **3.6-draft** (2026-08-19, Garvit — Phase 5 restructure: the shared ad
  market, adaptive allocation, purchase revenue, and the pricing ladder;
  additive conventions only, no C1/C2/C3 signature, enum, taxonomy,
  ENTRY_POINTS-row or evidence.py change; pending Atishay's ack at the next
  sync):
  1. **`ad_test` spec key `market {shared, allocation}`** — `shared: true`
     inverts 4.1's design: instead of one arm per creative (paired, isolated
     populations), the builder emits ONE arm named `market` carrying every
     creative row, so the ads compete for the same shoppers under the same
     frequency caps and a single `results.json` holds all N creatives.
     Isolation buys a clean causal read; the shared market buys a real
     auction — both are now expressible, and the key is absent by default so
     every existing `ad_test` spec builds byte-identically. Unknown
     `market`/`allocation` keys are refused the way `parse_calibration`
     refuses them (a typo must never be silently swallowed into a run whose
     `config_hash` then claims it was honored). `floor_share` is bounded to
     `[0, 1/N)`.
  2. **Adaptive allocation** (`exposure.allocation {enabled, prior_exposures,
     prior_clicks, floor_share, power}`, parsed by
     `runner/config.parse_allocation`, hash-covered because it rides in
     `raw`). Per tick, before the draws: each active row's `reach_prob` is
     rescaled by `N × share`, where `share` comes from the creative's
     trailing smoothed CTR `((clicks+prior_clicks)/(exposures+prior_exposures))
     ** power`, floored at `floor_share` and normalized to 1.
     **The exposure step itself is untouched**: the
     `(seed, "expose", offset, tick)` substream, the one-draw-per-active-row
     order, and the cap checks are byte-identical — only the thresholds move.
     Uniform shares reproduce the unallocated schedule exactly, so day 0 (a
     pure prior) and a disabled config are the pre-3.6 path. The stats are a
     pure function of the SAW/CLICKED log (`steps.CreativeStats`, rebuilt
     from the JSONL in `RunnerState.rebuild_from_records`), never persisted,
     so resume and branch re-derive identical allocations; tick t's weights
     see ticks 0..t-1 only (trailing, no lookahead).
  3. **results.json additive key `revenue {total, by_creative}`**
     (`runner/results.py`). `BOUGHT` already carries `price` and
     `cause_creative`, so purchase revenue is a real simulated quantity —
     accumulated in `ResultsAccumulator`, round-tripped through
     `results_state` via `.get` (pre-3.6 snapshots still resume), and
     therefore live through `/results-live` for free. `validate_results`
     checks it only when present, the same rule the 3.4 keys follow. Ad SPEND
     is deliberately NOT here: it needs an assumed CPM, so it stays in the
     dashboard (`web/lib/economics.ts`, sourced in
     `eval/market-research.md` §5) and never masquerades as engine truth.
  4. **`pricing` spec key `discount_levels []`** — replaces the
     promo_off/promo_on pair with a ladder: one arm per depth named
     `d<pct>`, built ASCENDING for the same reason the off arm ran first
     (`PRICED_AT` is shared objective state read as-of `t`, so the
     shallowest arm aligns the shelf and the deepest discount runs last),
     every arm still running the promo hook. `build.leveled_promos(promos,
     pct)` generalizes `zeroed_promos` (which is now its 0.0 rung). Absent
     key ⇒ the existing two-arm path.
  5. **Read-only endpoints** `GET /experiments/{name}/ads-manifest` (ingest
     status `ready|ingesting|none`; `ads-manifest.json` is written last by
     `ingest_ads`, so its presence IS the completion signal; catalog and
     perception_cache come back **repo-relative** because the manifest stores
     absolutes and a spec resolves those keys against the repo root) and
     `GET /experiments/{name}/ads/{creative_id}/image` (`FileResponse`
     resolved through the materialized `creatives.json` and confined to the
     experiment's catalog dir; 404 for text-only creatives). Experiment names
     are collapsed to one path segment.
  6. **comparison.json**: `_ad_section` gains a shared-market branch (all
     rows read from the single `market` arm, plus `shared_market: true` and
     the per-creative-per-day impression rows); `_pricing_section` gains
     `revenue_total` per arm and, for a ladder, a `ladder[]` + `best_level` /
     `best_arm` verdict computed once from engine data.
  7. **Bug-fix (runner, no signature change): the resumed-cart desync.**
     `decide()` treats a cart as resumed iff `scalars.cart` intersects the
     stimulus's `reference_price`; the loop was instead passing its own
     in-memory `state.carts` flag to `expand_page`. Those disagree whenever a
     shopper's REFERENCE_PRICE write loses the **Law-14 cap** (6 subjective
     writes/tick; `ref_price` ranks below PREFERS, so a shopper who saw two
     creatives in one tick can hold a cart the graph cannot show) — the mind
     then returns BROWSE while expansion demands BUY|ABANDON and the run dies
     with "resumed-cart decision returned Action.BROWSE". The loop now derives
     the flag from the same context the mind saw, so the two read one truth by
     construction; an invisible cart simply stays in runner state and resumes
     on a later tick once the price is rewritten. Pinned by
     `tests/test_cart_rederivation.py::test_expand_page_resumed_flag_matches_decide_in_cart`.
     *(Same family as the v3.4-draft cart re-derivation fix; surfaced by item 8
     making non-hero products convertible for the first time.)*
  8. **Fixture (shared, additive): `fixtures/demo-brand/page_variants.json`**
     gains pages 4000003/4000004/4000005 for products 3000003/3000004/3000006.
     Previously only 3000001 had a landing page, so creatives
     2000002/2000004/2000005 dead-ended at CLICK and could never convert —
     tolerable when each creative ran its own isolated arm, but in a SHARED
     market it let the highest-CTR ad win the whole budget while earning zero
     revenue. Existing ids are untouched (4000001 consistent / 4000002
     violating remain the A/B pair), each new page is CONSISTENT (shows its
     product's catalog attributes plus its creative's claims), and page
     resolution for 2000001/2000003 is unchanged.

- **3.7-draft** (2026-08-19, Garvit — Phase 5.8: the ads become visible, the
  brand becomes real, and the launch stops looking broken; additive
  conventions only, no C1/C2/C3 signature, enum, taxonomy, ENTRY_POINTS-row or
  evidence.py change; pending Atishay's ack at the next sync):
  1. **Creative-text read surface.** `GET /runs/{id}/creatives` and
     `/catalogs/{key}/creatives` return a `CreativeCard`: `{creative_id,
     brand_id, brand_name, name, headline, body, note?, image_url,
     authored_claims[], perceived{claims[], claimed_discounts[],
     prompt_version, model, from_image} | null, offers[{product_id, name,
     list_price, category_id, claimed_pct, page_ids[]}]}`. `/config`'s
     `creative_names` reduced every ad to `{id: name}`, which left the
     dashboard structurally unable to show what an ad SAYS. Images come back
     through `GET /runs/{id}/creatives/{cid}/image` and
     `/catalogs/{key}/creatives/{cid}/image`, both resolved through the
     **run's own catalog_dir** and `is_relative_to`-confined — one resolver
     for committed brand catalogs and ingest-materialized ones alike.
     `GET /catalogs` is a **server-side allowlist**; the client picks a key,
     never a path, and the row carries the companion `personas`/`goal_config`
     so a launch spec is assembled without the web app hardcoding paths.
     **The convention this encodes: `headline`/`body` have ZERO runtime
     effect.** They are perception input and cache-key material; behaviour
     comes from the perceived claims (CLAIMS edges) and `claimed_pct`
     (`appraisal.py` offer_attractiveness). The card carries authored AND
     perceived so a reader can see which is which.
  2. **`GET /engine/pace`** — read-only pace samples from recent complete runs
     (`per_tick_s`, recency-weighted `per_tick_s_per_100_shoppers`). An
     **observation, never a simulated quantity**, and the only source the
     dashboard's ETA is allowed to use. Rationale: per-tick cost is dominated
     by consolidation and grows with the store (measured here: the same 200×60
     shape ran 18.5 s/tick fresh and 112 s/tick loaded), so a hardcoded
     constant is wrong within a day.
  3. **`progress.json` additive status `"preparing"` + `phase`** written by
     `SimRunner.prepare()` at each milestone (population · perception ·
     catalog · stimuli · seed_population · manifest), with `tick: -1`. The
     registry row is published by `RunStore.allocate()` the moment the run dir
     exists, but `manifest.json` lands only at the END of prepare() — this is
     the only file-level signal in between, and its absence is what made a
     healthy run render as `manifest.json not found`. Consumers keyed on
     `"running"`/`"complete"` are unaffected.
  4. **Optional catalog file `brands.json`** — API-only display metadata
     (`{brand_id: {name, url, note}}`), deliberately OUTSIDE the engine's five
     catalog-dir reads, so it can never reach `config_hash`, `view_hash`, or a
     mind. Absent ⇒ cards fall back to `Brand <id>`.
  5. **`fixtures/nisolo/` — a second committed brand.** Real advertiser (real
     products, real prices, the brand's own five campaign images), simulated
     shoppers. Perceived ONCE via the new CLI and frozen;
     `fixtures/demo-brand/` and `fixtures/perception-cache/` are byte-untouched
     so their manifest hashes never move. Two conventions it establishes:
     **every offered product needs a landing page** (a page-less creative
     dead-ends at CLICK, and in a shared market wins budget while earning
     zero), and **a brand ships its own `personas.json`/`goal_config.json`**
     when its price tier differs — Nisolo's $109–295 catalog needs budgets
     scaled ×2.2 and `arrival_rates_per_tick` re-keyed onto the categories it
     actually sells, or the absolute-dollar gates in `choice.py` block nearly
     every purchase. Cited in `eval/market-research.md` §6.
  6. **`python -m shopsim.experiments perceive-catalog --catalog --cache`** —
     the only sanctioned way to mint a committed perception cache. `ingest_ads`
     remains the path for user uploads (it materializes a copy of a base
     catalog and appends, which is wrong for a standalone brand). Prints each
     creative's parsed claims and claimed discounts so a human can check the
     read before committing; re-running with the cache present makes zero
     calls. **Never hand-edit a cache entry** — that would make "perceived,
     not authored" false, and `tests/test_nisolo_fixture.py` fails if the
     sale creative's discount stops coming from its image.
  7. **comparison.json `pricing.ladder[]` gains `creatives[]` and
     `vs_control`**, plus top-level `control_level` / `best_vs_control`.
     Computed from data each arm already has (`funnel_by_creative`,
     `revenue.by_creative`) — no new engine state, all `.get`-guarded.
     Convention: **a 0.0 rung is always present** (UI-enforced), because a
     discount depth means nothing without a full-price control.
     `leveled_promos(…, 0.0)` remains `zeroed_promos`. Note the asymmetry the
     control makes visible: perceived claims override authored ones, so in the
     0% arm a sale creative **still claims its discount** while the shelf sits
     at list price — that is the expectation-violation mechanic, and the
     control is labelled "same ads, no actual price cut", never "no discount".
  8. **Three bug fixes**, each with a pinning test:
     (a) `/experiments/{name}/ads/{cid}/image` 500'd on **every real ingested
     catalog** — `ingest.py` writes `{"comment":…, "creatives":[…]}` while the
     reader iterated the dict and called `.get` on string keys; the existing
     test wrote a bare list, so it never exercised the real shape. Now read
     via `_creative_rows`, which accepts both.
     (b) `POST /experiments/ingest-ads` checked `os.environ` only, refusing a
     repo whose `<repo>/.env.local` works — the CLI resolved it and the API
     did not. Both now call the new public `perceive.resolve_api_key()`.
     (c) `_safe_name` raised `HTTPException` while `fastapi` was imported only
     inside `create_app`, so that path would have `NameError`d into a 500
     instead of a 422.

- **3.9-draft** (2026-08-20, Phase 5.9 — the Social Memory Graph; **additive
  only: two new read endpoints and one optional spec key. No C1/C2/C3
  signature, enum, taxonomy, ENTRY_POINTS-row or evidence.py change, and no
  new Cypher — pending Atishay's ack at the next sync**):
  1. **`GET /runs/{run_id}/memory-graph?focus=<csv offsets>`** — a shopper
     cohort's subgraph as `{nodes, edges}`, for the dashboard's `04 Graph`.
     Omitted `focus` lets the engine choose: `HydraMem.find_social_triads()`
     ranks mutually-trusting triples by whether they can actually SHOW the
     mechanism (a member with both `BOUGHT` and `EXPERIENCED`), so the default
     view is one that can draw `TRUSTS_PERSON -> BOUGHT -> EXPERIENCED`.
     Response also carries `run_index`, `t0`, `tick_seconds`, `ticks`,
     `head_tick`, `social_enabled`, `focus` and the ranked `candidates`.
     Node `kind` is `shopper | concept | category | brand | product | creative
     | page | belief | aspect | anchor`. NOTE the typing rule: shopper ids are
     `1_000_000 + run_index * 100_000`, so from run_index 10 on they run
     straight through the creative/product/page blocks — id ranges alone are
     NOT sufficient. The shopper set is recovered exactly instead, from
     `{focus} union {TRUSTS_PERSON destinations}`, which is complete only
     because `TRUSTS_PERSON` is the sole relationship whose destination is a
     shopper (`schema.SOCIAL_EDGES`). A second shopper-valued relationship
     would have to update that closure; a test pins the assumption.
  2. **The payload is topology + version history; the CLIENT owns time.** One
     edge per `(rel, source, target)`, with every stored row in its `versions`
     list and a `time` discipline of `static` (objective closure and
     `TRUSTS_PERSON`), `event` (`t <= as_of`) or `bitemporal`
     (`t <= as_of < valid_to`). So the dashboard's day scrub is one fetch and
     a pure filter — the same as-of rule `reads.ObjectiveCache.build` applies
     to `PRICED_AT` and `Inspector.tsx` applies to preference chains. Folding
     is not cosmetic: emitting one link per stored row would make
     `d3.forceLink` treat four visits to one page as four parallel springs,
     so the layout would encode event-log volume rather than graph shape.
     `ABOUT`/`THAT`/`DERIVED_FROM` carry no time of their own and are stamped
     with their belief node's `t`/`valid_to`, so a superseded belief version
     retires together with its whole provenance fan.
  3. **`GET /social-runs`** — registry rows whose manifest carries
     `social_config_hash`, i.e. the runs that have a trust layer at all. A new
     endpoint rather than a new field on `/runs`, so no existing payload shape
     moves. `04 Graph` links at the newest one; a run without the layer renders
     an explicit "nothing social to draw here" rather than an empty canvas.
  4. **`population.social` reaches the experiment spec** (`specs.py`
     `BaseSpec.social`, emitted by `build._population`). Previously only a raw
     run_config could turn the layer on, and a CLI run leaves its config
     outside the run store where `_cfg_for` cannot find it. Emitted ONLY when
     the spec asks for it, so every pre-social spec still builds a
     byte-identical config and its `config_hash` is unchanged; validation stays
     with the single authority, `runner.config.parse_social`.
  5. **No new Cypher.** The exporter reuses `all_edges`, `holds_history`,
     `node_props` and — for triad discovery — `adj_batch`, the one legal
     batch-read shape, which until now only `bench/probe11.py` called. Probes
     are chunked at 1,000 ids because HydraDB admission control rejects an
     `UNWIND` batch above 1,024 items. `cypher.py` is untouched, so
     `test_cypher_hygiene.py` still pins the template set.
  6. **Law 12/15 hold at the new surface.** The exporter reads the `shopper`
     node's `segment_id` and never its `budget`; latent product props remain
     unreadable. `fixtures/run-configs/social-graph-demo.json` is the committed
     run behind the exhibit (100 shoppers, 28 ticks, `w_social` 0.5).
- **3.8-draft** (2026-08-20, Phase 6 — analytics & MetricsReport; additive
  conventions only, no C1/C2/C3 signature, enum, taxonomy, ENTRY_POINTS-row or
  evidence.py change; every default is a no-op and the committed
  `fixtures/scripted-run-1` results.json still validates unchanged; pending
  Atishay's ack at the next sync):
  1. **`results.json` IS the MetricsReport, finalized.** The Phase-3 skeleton's
     typed-empty keys are now filled, split by what each needs:
     *accumulator-resident* (live through `/results-live`, exact on resume) —
     `fatigue_split`, `belief_drift`, `violations.bounce_delta`,
     `repeat_ltv_by_arm`, `social_lift`; *finalize-only* (needs the segment map
     or a graph read) — `ci`, `belief_confidence_dist`, `provenance_coverage`.
     `ResultsAccumulator.results(manifest, extras=None)` gained the optional
     second argument; with `extras=None` the finalize-only keys stay exactly
     the placeholders Phase 3 shipped, which is what `/results-live` needs
     (that path rebuilds the accumulator with no segment map and no graph
     handle). New package `engine/shopsim/analytics/`: `metrics.py` (pure,
     numpy only), `report.py` (finalize + post-hoc), `__main__.py` (the CLI).
  2. **New accumulator state, all `.get`-guarded in `from_state`** so pre-v3.8
     snapshots still resume: `by_shopper` (a positional int vector per OFFSET,
     fields in `results.py::BY_SHOPPER_FIELDS`), `revenue_by_shopper`,
     `fatigue` (per-tick channel sums), `belief_conf_avg` (same keys as the
     v3.5 `belief_avg`, filled from the same `live_holds` read — zero extra
     statements), `page_pairs`. A run whose snapshot predates this carries no
     bootstrap unit; the report says so instead of inventing intervals.
  3. **The bootstrap clusters on SHOPPERS.** One person's exposures, clicks and
     purchases are one correlated story, so the resampling unit is the offset,
     not the event. 2,000 percentile replicates, alpha 0.05, rng seeded from
     `(seed, CI_STREAM, scope, metric_index)` where CI_STREAM is
     `int.from_bytes(b"ci")` — offsets and segment ids only, never an absolute
     shopper id, so a crash/resume in a DIFFERENT run block still hashes
     identically (`test_runner_real.py::norm_results_hash`). Keys are
     `"<metric>"` for the arm and `"<metric>:<segment>"` per segment; a ratio
     whose denominator is empty gets no interval rather than a fabricated one.
  4. **Fatigue is measured at decision time**, from the context the mind
     actually saw — never re-derived from the event log. Three PARALLEL
     channels, not a decomposition: `asset` from
     `minds.choice.asset_wearout(exposures_72h, params)` (a new public alias of
     the private `_wearout`, exposed for MEASUREMENT the way v3.5 exposed
     `stage_probabilities` — registry row 12 is unchanged and no second entry
     point exists), `brand_msg` from the `brand_semantic_fatigue` motif's
     strength, `concept` from `concept_saturation` (retrieved today,
     behaviourally inert at P0 — the payload does not pretend otherwise).
     Creative-stage decisions only, since the CTR columns are the point.
     `metrics.FATIGUE_HIGH = 0.5` splits high from low; on the asset channel
     with default ChoiceParams that is `exposures_72h >= 4`, which is where the
     dashboard's own detector rule already sat.
  5. **`provenance_coverage` becomes a summary dict**, not a bare float: the
     headline number is worthless without the counts behind it. Scope is stated
     in the payload — PREFERS over its FULL version history (one statement
     returns the whole supersession chain), beliefs over the LIVE versions
     (one statement per historical belief version would be tens of thousands on
     a 60-tick run). `cause_kinds` is the F7 audit in metric form: SAW must
     never appear. Note the same-tick fold rule (v3.3 item 6) stamps a version
     with its DEEPEST cause, so CLICKED rarely appears alone.
  6. **`violations.bounce_delta` is the WITHIN-run page-split delta** — pooled
     `bounce_rate(B) - bounce_rate(A)` over the run's own `page_ids` splits in
     declared order, the same B-A convention as `comparison.json`. Cross-arm
     deltas stay in `comparison.json`; this is its per-run counterpart, and it
     is `null` (not 0.0) when the run has no split.
  7. **`python -m shopsim.analytics report --run <id|dir>`** — the Phase-6
     "one command from a run directory -> full report" checkpoint. Rebuilds the
     accumulator from the newest `results_state_*.json`, optionally sweeps the
     graph (`--no-graph` to skip: never wait on the store mid-demo), renders a
     text report, exits non-zero on C3 problems, and refreshes `results.json`
     in place only with `--write`. `--config` supplies the run_config for
     per-segment intervals (CLI runs keep theirs outside the run store).
     Degradation is loud: each missing input drops exactly one block and adds a
     named note.
  8. **`SimRunner.run()` finalizes before writing `results.json`**, so a
     completed run's file is the whole MetricsReport. A graph failure there
     degrades to a note; it never loses a finished run.
  9. **`fixtures/golden-run/` — the Phase 6.2 golden.** 5 shoppers x 3 ticks on
     the demo brand (the Appendix-F anchor, byte-frozen), ScriptedMind deciding
     and the real `consolidate()` digesting, with one full evidence chain
     inside three ticks: SAW -> CLICKED -> VISITED/PRICE_SEEN/BROWSED -> CARTED
     -> BOUGHT -> NEED_SATISFIED -> EXPERIENCED. `tests/test_golden_run.py`
     checks the committed artifacts with NO database (it re-derives the funnel
     from `events.jsonl` and recomputes every pure metric from the snapshot);
     `tests/real/test_golden_run_real.py` re-runs the config on the live store
     and demands the same report back under the run-block normalization. Two
     runs in different blocks produced byte-identical reports, so the Phase-6
     additions preserve the same-seed determinism guarantee.
 10. **Social layer (P1, pulled forward — opt-in and byte-neutral when off).**
     `population.social {enabled, degree, rewire_p, weight_min, weight_max}`,
     parsed by `runner/config.parse_social` (unknown keys refused, like
     `parse_allocation`/`parse_calibration`); absent or `enabled: false` yields
     `None` and NOT ONE `TRUSTS_PERSON` statement is emitted, so every existing
     config, fixture and hash is untouched. `population/factory.social_graph`
     draws a seeded Watts-Strogatz small world over OFFSETS from
     `(seed, SOCIAL_STREAM)` — PLAN 2.1's degree ~ 4, weights U(0.4, 0.9) — and
     `seed_population(..., social_edges=)` writes it in BOTH directions
     (retrieval reads outgoing edges only). Manifest gains
     `social_config_hash` **only when a social layer exists**, so social-free
     manifests stay byte-identical; C3 already listed the key as optional.
     `AppraisalParams.w_social` (default **0.0**) weights the channel:
     `credibility += w_social * (2*valence - 1)` from the most-trusted peer's
     `social_proof` motif, which is PLAN 2.3's wording ("credibility <- trust
     belief ... + social_proof valence") and keeps the calibrated dimension
     count at five. `Appraisal.social_proof` is now REPORTED whenever the motif
     is present even at w_social 0 — retrieved, visible in the trace, and
     behaviourally inert until a config pays for it. ENTRY_POINTS row 20 was
     already there; this honours it rather than amending it.
 11. **`social_lift` says whether it is causal.** With `w_social == 0` the
     motif is retrieved and reported but never read by `appraise()`, so the
     on/off gap is correlation — the payload carries `causal: false` and a note
     saying exactly that. `null` when no decision in the run carried the motif.
 12. **Dashboard reads the authoritative field.** `web/lib/types.ts` types
     every Phase-6 key as optional; the MESSAGE FATIGUE small multiple plots
     `fatigue_split.brand_msg`/`.asset` when the run has them and falls back to
     the client-side derivation with a visible note when it does not;
     `web/lib/detectors.ts` gains a MEASURED fatigue rule (high-cell CTR vs
     low-cell CTR from the engine's own split) that REPLACES the CTR-decay
     heuristic for any run carrying a channel — with the engine's measurement
     in hand the heuristic is not a second opinion, it is a worse one. New
     `ConfidencePanel` on the results page renders the intervals, the
     provenance line, repeat/LTV and social lift.
 13. **Bug fix (pre-existing, surfaced by running the full real suite):**
     `tests/real/test_minds_real.py::test_perception_writer_round_trip` assumed
     the store held one catalog. `LISTS` hangs off ONE global catalog anchor, so
     `ObjectiveCache` enumerates every catalog ever ingested — since Phase 5.8
     that includes Nisolo (2000101+), and the test raised `KeyError` indexing
     the demo-brand perception cache by a Nisolo creative id. Worse, had it got
     past that it would have DELETED Nisolo's `CLAIMS`/`OFFERS` edges and
     restored only the demo brand's. Now it skips creatives it has no
     perception for. Nothing in Phase 6 writes catalog or stimulus edges; this
     broke the moment a second brand touched the store on 2026-08-19.


---

## v3.10-draft — Phase 7: the calibration layer (2026-08-20)

The first version that changes behaviour on purpose. Every item below moves
numbers; none of them changes a signature, an enum, a taxonomy row or
`evidence.py`. The full before/after, with sources, is `eval/calibration.md`.

 1. **`calibration.retrieval` — retrieval constants become run configuration.**
    `schema.RetrievalParams` has always documented itself as calibration
    ("tuning them is calibration, not a contract change"), but the values were
    reachable only by editing the module default, so no run could pin what it
    actually retrieved with. A new optional `calibration.retrieval` sub-block
    parses through one authority, `runner.config.parse_retrieval`, refuses
    unknown keys the way `parse_allocation`/`parse_social`/`parse_calibration`
    do, and rides in `raw` — so `config_hash` covers it and a replay can no
    longer retrieve differently than the original run. `parse_calibration`
    keeps its three-value contract; the new block gets its own parser rather
    than changing fourteen call sites.

 2. **Two retrieval constants split apart.** `recency_half_life_s` was doing
    two unrelated jobs: how fast a past *impression* stops counting as
    repetition, and how fast a *preference* stops counting as current. At 3
    days, a seeded `PREFERS` prior — written at `t0 - 1 tick` — decayed to
    recency 0.016 by day 18, collapsing `relevance` and starving the whole
    funnel. Now `recency_half_life_s` (3 days) serves fatigue and saturation,
    and `pref_recency_half_life_s` (**30 days**) serves taste.

 3. **`violation_min_strength` (0.0 -> 0.5).** `expectation_violation` fired on
    any `EXPECTS(brand)` concept a page did not show, with no floor. Because
    `EXPECTS` accumulates from *every* creative a brand runs, 85% of page
    visits in the traced baseline carried a violation at mean strength 0.42 —
    a -0.64 utility penalty, at the BROWSE weight of 1.5, on pages doing
    nothing wrong. An expectation must now be genuinely held before failing to
    meet it counts. The deliberate A/B variant still fires: it hides a concept
    its own creative claims at strength 0.9.

 4. **Learning cold start: `(w=0, E=0)` -> `(COLD_START_W=0.5,
    COLD_START_E=1.0)`.** With no prior evidence `blend()` is degenerate — the
    first observation is all the evidence — so one CLICK set an unheld
    concept's weight to `PREF_TARGET = 1.0` outright. Mean `preference_fit`
    strength in `r039` was 0.958 and every affected `preference_drift` series
    read a flat 1.0. The constants live in `minds/calibration.py` beside the
    other tunables; `evidence.py` is untouched, the formula is unchanged, and
    only the *caller's* choice of starting state moved. Shoppers holding a
    seeded prior are byte-identical. Beliefs deliberately keep their old cold
    start: a first trust belief lands on its own event's target (0.6/0.65/sat),
    which is already a sane value, and its low evidence is what makes F10
    demonstrable.

 5. **`stage_bases.BUY` 3.2 -> 2.85.** The only mind constant the Phase-7 fit
    had to move, taking P(BUY|cart) from 0.194 to 0.247 against the 0.24-0.28
    band implied by 72-76% cart abandonment. CLICK, BROWSE and CART were
    already correct once items 2 and 3 stopped starving them. The fitted values
    are the module DEFAULTS on purpose: the simulator you get without a profile
    should be the calibrated one.

 6. **Opt-in decision trace (`--trace-decisions`).** Writes `decisions.jsonl`
    beside the run: one row per decision carrying the raw appraisal INPUTS
    (motif strengths, traits, scalars, coefficients), the gate probabilities and
    the realised action. Inputs rather than the appraised dims, because a
    candidate calibration changes `appraise()` too — replay calls the real
    `appraise()` and the real gate functions, so there is no second copy of the
    arithmetic. **Off by default: no file, no branch taken in the tick loop, and
    a byte-identical `results.json`** (`tests/test_eval_trace.py`). The trace is
    what makes calibration cost milliseconds instead of the 20-110 minutes a
    real run costs.

 7. **`fixtures/golden-run` regenerated.** Items 2-5 reshape what it records.
    The funnel is byte-identical (ScriptedMind decides there, so the choice
    model cannot move it) and prior-holding shoppers are byte-identical; what
    changed is that drift series for concepts first met inside the run read
    `[None, 0.6875, 0.77273]` instead of `[None, 1.0, 1.0]`.
    `test_first_learned_version_of_an_unheld_concept_saturates` was written to
    fail loudly if the cold-start rule ever changed. It did, and is replaced by
    `test_an_unheld_concept_starts_neutral_and_learns_gradually`, which pins the
    new rule and records the old one in its docstring.

 8. **Two named calibration profiles** (`eval/profiles/`). `reference` is
    certified against every band in `market-research.md`; `demo` moves only the
    CLICK threshold, solved for a stated target rate, and publishes the multiple
    it induces on every metric. This replaces the ad-hoc
    `{"stage_bases": {"CLICK": 2.0}}` that was copy-pasted into spec files and
    ran at ~28% CTR (~22x the band, blended ROAS ~46x).

---

## v3.11-draft — the frozen 04 Graph capture (2026-08-20)

Additive only: one read endpoint and one committed fixture. No signature, enum,
taxonomy or ENTRY_POINTS change, no new Cypher, and **no behaviour change** —
nothing here moves a number.

 1. **`GET /memory-graph` — run-independent and store-independent.** Serves
    `fixtures/social-graph/memory-graph.json` off `root = runs_dir.parent`, the
    same way `/catalogs` reaches its fixtures. Its 404 names the regeneration
    command. `GET /runs/{id}/memory-graph` and `GET /social-runs` are unchanged
    and still read the store.

 2. **Why a fixture and not a live read.** Shopper worldviews exist ONLY in
    HydraDB. `runs/` keeps events and results, but the graph goes with the
    store, and the store is archived and recreated routinely (`infra/README.md`,
    "Before a demo or a timed run" — three times on 2026-08-20 alone). A live
    read meant the dashboard's `04 Graph` blanked after every reset and reshaped
    itself run to run. This is the move `export-fixtures` / `_export_shoppers`
    already makes for worldview and trace samples, one level up.

 3. **Payload = the v3.9-draft envelope plus three keys.**
    `captured` (`run_id`, `run_index`, `arm`, `label`, `head_tick`) is
    provenance the UI is required to display — a frozen graph that does not name
    its source reads as live state, and the aside's subtitle is where it says
    so. `traces` maps `offset -> stimulus_id -> {motifs, scalars}`, captured
    from the same `get_trace` the live path calls, because Explain reads them
    and recomputing motifs client-side would mean the dashboard inventing graph
    structure. `comment` carries the usual fixture rationale. Every other key is
    shape-identical to a live read, so one TypeScript type serves both paths.

 4. **`export-graph` writes it.**
    `python -m shopsim.runner export-graph --config CFG --run RUN_ID --out FILE`,
    pinned to the last consolidated tick via `mem.set_tick` and serialized with
    `write_json_atomic` like every other committed capture. Traces are taken
    only for stimuli the shopper actually met, read off the edges just captured.

 5. **Pinned without a database**, in the `test_golden_run.py` style
    (`engine/tests/test_memory_graph.py`): every edge endpoint resolves, the
    focus triple is genuinely mutually trusting, the
    `TRUSTS_PERSON -> BOUGHT -> EXPERIENCED` chain is present, every trace key
    maps to a focus shopper and an on-screen stimulus, and every motif path
    references a node that exists. A frozen exhibit **can** go stale against a
    changed retrieval layer or motif library; these tests and
    `fixtures/social-graph/README.md` are what make that loud rather than
    silent. Regenerate after touching `hydramem/reads.py` or `contracts/enums.py`.

---

## v3.12-draft — the frozen Shopper Mind capture (2026-08-21)

Additive only: one read endpoint, one committed fixture, one exporter flag and
one optional read parameter. No signature, enum, taxonomy or ENTRY_POINTS
change, no new Cypher, and **no behaviour change** — nothing here moves a
number, and the default `export-graph` output stays byte-identical.

 1. **`GET /shopper-mind` — the pinned mind, run- and store-independent.**
    Serves `fixtures/shopper-mind/mind.json` off `root`, mirroring
    `GET /memory-graph` (v3.11 item 1). The 05 Mind page's premise is that its
    shopper is chosen ONCE and always exists — so the page never reads the
    store, never blanks on the reset ritual, and never quietly becomes a
    different shopper when a new simulation loads. The pinned shopper is
    `focus[0]` of the capture; the page hard-codes nothing.

 2. **Payload = the v3.11 frozen envelope plus three keys.** `catalog_key`
    names the catalog the demo stimuli come from, so the UI can load the ad
    cards. `demo_stimuli` lists the baked `{creative_id, page_id}` pairs —
    landing pages are per-shopper seeded (`steps.page_for`), so these are the
    pinned shopper's own pages. `previews` maps
    `offset -> stimulus_id -> ` the exact **decision-preview envelope**
    (v3.5-draft item 2: `tick`, `stimulus`, `scalars`, `motifs`, `appraisal`,
    `probabilities`, `counterfactual_need_off`), computed at export time by
    the same `appraise()`/`stage_probabilities()` the live endpoint runs.
    The shared plumbing now lives in `runner/preview.py`
    (`build_preview_ctx` / `build_population` / `compute_preview`); api.py
    delegates to it, payloads unchanged. Law 12/15 unchanged: traits, coeffs
    and latent quality never appear — appraisal dims and gate probabilities
    are already-served HTTP shapes, and `test_shopper_mind_fixture.py` scans
    the whole payload for the forbidden keys.

 3. **`export-graph --previews` writes it**; `get_memory_graph` grows an
    optional `extra_stimuli` (default `()`, so v3.9/v3.11 reads are
    untouched). `--previews` forces every scheduled creative and its landing
    page for `focus[0]` on screen, met or not: `extra_stimuli` seeds them into
    the accumulator before the objective closure, which emits their real
    CLAIMS/OFFERS/PROMOTES/SHOWS/PAGE_FOR edges from the objective cache —
    **objective edges only; nothing subjective is invented for an ad the
    shopper never saw**. Traces for `focus[0]` cover met ∪ demo stimuli, so
    the retrieval path exists for every previewed ad.

 4. **Provenance display is REQUIRED**, as in v3.11 item 3: the page must
    name `captured.run_id` and the as-of day — a frozen mind that does not
    say so reads as live state. Additionally: the Mind page's lobe layout and
    its labelled inter-lobe connectors (INFLUENCES, SHAPES, INFORMS, …) are
    the reference design's **architecture legend — presentation, not stored
    relationships** — and must render in a style visibly distinct from stored
    (solid) and derived (dashed) edges.

 5. **Pinned without a database** by `engine/tests/test_shopper_mind_fixture.py`:
    envelope keys, edge resolution, a creative AND page preview per demo
    stimulus with probabilities in [0,1] and matching `page_id`, appraisal
    dims present and in range, a trace for every previewed stimulus whose
    motif paths reference only on-screen nodes, and the forbidden-key scan.
    Source spec: `fixtures/run-configs/shopper-mind-demo.json` (nisolo
    catalog + `population.social`, the social-graph-demo calibration recipe).
    Regenerate after touching `hydramem/reads.py`, `minds/appraisal.py`,
    `minds/choice.py` or `contracts/enums.py` — see
    `fixtures/shopper-mind/README.md`.

## v3.13-draft — CTR and ROAS read at the calibrated gate (2026-08-21)

Additive only: one published table, one field on an existing read endpoint
and a display rule. No signature, enum, taxonomy or ENTRY_POINTS change, and
**no behaviour change** — no simulated number moves; the dashboard divides.

 1. **`calibration.json` → `demo_profile.click_gate_acceleration`.** The
    reference-trace replay that already publishes the demo profile's 5.6x
    (v3.10 item 4, `calibrate.evaluate` over the traced contexts), tabulated
    per shipped CLICK base: the calibrated default (`DEFAULT_STAGE_BASES`,
    multiple exactly 1.0), the committed `eval/profiles/demo.json` base, and
    every retired base named in `eval/__main__.py::RETIRED_CLICK_BASES` (2.0,
    the pre-Phase-7 hand-pick, kept while runs on it exist). Each row carries
    `click_base`, model-implied `p_click`, `multiple` vs the calibrated rate
    and a `status` string; the block names `calibrated_click_base` and
    `reference_p_click`. Regenerated by `make eval-calibrate`; its `note`
    states the first-order caveat (the replay re-scores reference contexts
    and cannot model the click→preference feedback loop — r039 on 2.0
    realised 0.28 against a tabulated 0.275; a 300x60 Nisolo run realised
    0.35).

 2. **`GET /runs/{id}/config` → `effective.click_gate`** =
    `{base, calibrated_base, acceleration, p_click_reference, p_click_model,
    source}`. `base` is the run's own `stage_bases.CLICK` (the module default
    when the config has no calibration block); `acceleration` is the
    table's `multiple` for that base matched within 1e-6, or **null** when
    the table has no row — the API never computes a factor of its own, and
    never falls back to a band mid-point. Read per request off `root`, like
    the fixture reads, so a re-calibration is served without a restart.
    Pinned by `test_api_live.py::test_config_click_gate_states_the_published_acceleration`
    and `test_studio_profile.py` (both Studio bases tabulated, calibrated at
    1.0, retired 2.0 present).

 3. **Display rule (03 Market).** The headline tiles are ALWAYS human-scale:
    **REAL CTR** = raw CTR ÷ factor and **ROAS AT REAL CTR** = blended ROAS ÷
    the same factor (only the click gate moves — 1.0x on every post-click
    metric — so CTR divides straight through and ROAS carries the same
    factor via revenue, keeping the run's own revenue per click). The per-ad
    CTR charts and roster rates use the same factor, so the page is coherent.
    The factor comes from, in priority order: (a) `effective.click_gate`
    (item 2); (b) the same table mirrored in `web/lib/calibration.ts`, keyed
    by the run's own `stage_bases.CLICK` — for an engine process that
    predates this field — pinned identical to the JSON by
    `test_studio_profile.py`; (c) **band normalisation**, only when the
    engine cannot state a multiple at all (no `run_config`, or an
    untabulated base): factor = raw CTR ÷ the researched 1.25% mid-point,
    applied only above the 0.5–2% band with >200 impressions. The raw rate,
    the factor and its source are **always printed beside the headline**
    (`RAW 34.97% ÷31.0 · PUBLISHED`, `BLENDED 173.85× ÷31.0`,
    `… · BAND-NORMALISED`) — an accelerated run must never read as a
    calibrated one, and a normalised one must never read as a published
    one. A run on the calibrated base shows its measured rate unchanged and
    says `CALIBRATED GATE`. The raw blended figures never headline a tile.
