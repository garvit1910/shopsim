# Hack Hydra — Master Build Plan (FINAL, v4)

**Six-State-Shopper Market Simulator on HydraDB · Track 3 (Memory & Context Retrieval)**
Team: Garvit · Atishay — two parallel lanes, two sync points. Architecture: v3 adopted, scoped — each shopper carries an evolving six-state model of a shared marketplace stored entirely in HydraDB: objective world, episodic history, subjective worldview (with confidence), learned preferences & habits, motivational goal state, and social context. Retrieval per decision = scalars + typed motif paths; appraisal interprets; a calibrated stochastic choice model acts; a post-purchase experience loop feeds the worldview back. This document replaces v3 in full. **Deadline (verified): Aug 20, 11:59 PM PT = Aug 21, 12:29 PM IST; internal freeze ≥ 6h before the PT cutoff.** Judges explicitly score graph-native use of HydraDB, and the Best-Use award targets data models "hard to pull off with vector or relational approaches" — v4 is aimed at that rubric.

## 0. How this plan works: lanes, contracts, stand-ins

```
Atishay's lane:  Phase 0 ─ Phase 1 ─ Phase 3 ─ Phase 6 ─┐            ┌─ Phase 7 ─┐
                                                         ├─ SYNC S1 ─┤           ├─ Phase 9 (ship)
Garvit's lane:   Phase 0 ─ Phase 2 ─ Phase 4 ─ Phase 5 ─┘            └─ Phase 8 ─┘
```

Phase 0 fixes three written contracts; each of you builds a stand-in for the other's half; until Sync S1 neither of you can block the other.

| Contract | What it fixes in writing | Stand-in (who builds it) | Who codes against it |
|---|---|---|---|
| **C1 — HydraMem API, v3** | `get_decision_context()` + `DecisionContext` (Appendix B): scalars (v3 MemoryPacket verbatim + worldview scalars) + `motifs[]` (enum v2, Appendix E) | `MockHydraMem` with canned v4 contexts, incl. a need-on/need-off twin pair, a low-confidence vs high-confidence belief pair, a fatigue-present case, a social case (P1) (Garvit) | Garvit's minds & adapters; Atishay builds the real one |
| **C2 — Mind interface, v3** | Three pure stages: `appraise(ctx, traits)`, `decide(appraisal, scalars, coeffs, rng)`, `consolidate(events, snapshot) -> EvidenceDeltas` + the typed persona split + the ENTRY_POINTS registry (Appendix D) | `ScriptedMind` (scalars only) + `ScriptedConsolidate` (+0.05 to one concept per CLICK) (Atishay) | Atishay's runner uses scripted minds; Garvit builds the real ones |
| **C3 — Results & metrics, v3** | `results.json` + `MetricsReport` incl. drift, goal, fatigue-split, confidence metrics (Appendix D) | Committed fixture files from a ScriptedMind run (Atishay, out of Phase 3) | Garvit builds the entire dashboard on fixtures |

Rules: any contract or registry change = 5-minute call + version bump in CONTRACT.md. `context.scalars` contains the old MemoryPacket byte-for-byte — that back-compat is why ScriptedMind and the Phase-3 runner survive every architecture change.

### Ownership at a glance

| Layer | Owner |
|---|---|
| HydraDB ops · HydraMem v3 (six-state schema, scalar + motif retrieval, supersession, provenance, catalog ingestion, replay) | Atishay |
| Sim runner (tick loop incl. goal generator, fulfillment generator, consolidation applier), event pipeline, analytics, calibration & evals | Atishay |
| Perception-as-graph-writer, personas (three families) + social graph factory (P1), appraisal, choice model, worldview update rules (evidence.py semantics) | Garvit |
| Experiment adapters + scenario packs, dashboard, store connect, recommendations | Garvit |
| Packaging, README, video, submission | Both |

**Stack (locked):** engine + HydraMem + evals in Python 3.11 (neo4j Bolt driver, numpy, FastAPI, matplotlib); dashboard in Next.js; one `docker compose up` runs hydradb + engine + web.

**Decisions the HydraDB repo made for you (unchanged from v3; design to these from line one):**

1. No `IS NULL`/`IN`/`CONTAINS` → sentinel bitemporality: live edges carry `valid_to = 9007199254740991`; supersede = SET old `valid_to = now`, CREATE new. History is never erased — on every layer (prices, beliefs, preferences, needs).
2. `WITH` pass-through; aggregates only `count/sum/avg/collect` → all scoring math in Python; "latest" = `ORDER BY t DESC LIMIT 1`.
3. One statement per request; multi-step ops sequenced client-side. **0.2-verified, stricter than assumed:** compound writes are rejected outright (`MERGE…SET`, `MATCH…MERGE/CREATE` all fail), and `UNWIND $rows` batching is narrow — batched CREATE takes **one fixed relationship type with NO properties**; `UNWIND…MATCH` must end in RETURN or DELETE (no batched SET), and the only read shape is `RETURN row.<field>, destination.id` (two unsorted projections, destination unconstrained — adjacency only, no edge/node props). Everything else = per-row single statements; throughput to be measured in Phase 1.3 against the 10k-events-≤10s target.
4. ~~`MERGE` on id only → upsert = MERGE + SET~~ **Rewritten by 0.2 probing:** bare-node CREATE/MERGE does not exist ("only one-hop edge patterns are executable"). Nodes are **implicit by integer id** — `MATCH (n {id})` succeeds on any id, props null until set. Node props: `MATCH (n {id: $id}) SET …`. Edges: single-statement one-hop `CREATE`/`MERGE (a {id: $a})-[:REL {props}]->(b {id: $b})`, inline props allowed. Consequence: "node absent" is unobservable — abstention must key off **absent edges / null props**, never node existence.
5. Integer ids, patterns anchor on id → central ID allocator (Appendix A); run isolation via shopper-id blocks.
6. Scalar properties only (no lists) → claims/attributes/needs are edges to enum nodes, never list properties.
7. One relationship type per MATCH, directed only → multi-hop motifs are never one MATCH. Route A: `algo.SPpaths` (relTypes whitelist, maxLen ≤ 4), classify paths client-side by edge-type signature. Route B: per-motif single-hop queries + Python set logic. Hour-one probe in Phase 1 decides per motif. **0.2-verified: SPpaths exists and works — bare CALL only (any MATCH prefix is rejected), integer ids in the config map: `CALL algo.SPpaths({sourceNode: $a, targetNode: $b, relTypes: ['R'], maxLen: 4}) YIELD path RETURN path` returns real Path objects; relTypes list accepted. Variable-length reads (`-[:R*1..2]->`) also work.**
8. One admitted writer per (scope, cell) → the engine process owns all writes; minds return deltas, never write; dashboard reads only through the engine.
9. Docker: pre-create `store/`+`cache/`, `--user "$(id -u):$(id -g)"`, `GRAPH_ALLOW_PLAINTEXT=true` locally, auth token file, ports 7687/8443/9090, pin the image digest.
10. v0.1.x software → all Cypher lives inside HydraMem; repo smoke scripts + Discord for anything weird.

**Architecture-v3 laws (project-internal, same rank as the above):**

11. **Closed vocabularies.** Four closed enums in ONE shared file imported by engine and minds: Concepts (~25–40), Categories (~8–12), the motif enum, the event taxonomy. Perception maps every claim onto the Concept enum (unknown → other). Vocabulary drift silently empties every graph intersection — enforced at parse time, checkpointed.
12. **Law of Single Entry.** Every behavioral variable enters the pipeline at exactly one documented point. Persona splits into three families: preference priors exist only as seeded PREFERS edges (never multiplied again in appraisal); appraisal modulators (novelty_seeking, trust_orientation, deal_proneness) enter `appraise()` only; choice coefficients (impulsivity = Gumbel temperature, price_sensitivity, switching_inertia (P1), risk_aversion (P1), budget, stage bases) enter `decide()` only. Enforced by: frozen types (`decide()` cannot receive traits by signature), the ENTRY_POINTS registry (Appendix D), a registry-completeness test, and an import-graph test (traits.py importable only by the appraisal module).
13. **Determinism by freezing.** Perception cache and appraisal cache (P1) frozen as before; the manifest now carries five hashes: perception cache, appraisal cache, evidence.py, goal config, latent-quality table (+ social config, P1). Replays refuse to run if any changed. New seeded substreams keyed by stable tuples: goals `(seed,"goal",shopper,tick)`, fulfillment `(seed,"fulfil",shopper,product,purchase_t)`, social graph `(seed,"social",population)`.
14. **The evidence hierarchy is law.** Exposure NEVER updates preferences — SAW touches awareness, adstock and EXPECTS only. All update weights live in evidence.py (Appendix F), the single source both sides import. Worldview updates are bounded: skip writes with |Δw| < ε = 0.01; ≤ 6 subjective writes per shopper per tick (priority: need-satisfy > trust > preferences > expects).
15. **Information hygiene.** Latent objective params (latent_quality, ship_reliability) reach a mind only through generated EXPERIENCED events. Retrieval whitelists must never return them. No omniscient shoppers.
16. **No graph theatre.** Every signal documents its representation. Paths where relationships genuinely matter; scalars where a value is just a value (reference price, adstock, budget). The table in §0.1 is normative.

### 0.1 The six state families (what lives where, and why it's a graph)

| # | State family | Representation | Why graph, not a column |
|---|---|---|---|
| 1 | **Objective world** — what is true | Brand/Product/Category/Concept/Creative/PageVariant; CLAIMS{strength} PROMOTES OFFERS{claimed_pct} SHOWS HAS_ATTR SOLD_BY IN_CATEGORY PRICED_AT{valid_to}; latent product props from fixtures (hidden, Law 15) | the shared truth every subjective layer diverges from; price history is time travel |
| 2 | **Episodic** — what happened | SAW CLICKED VISITED BROWSED BOUNCED CARTED ABANDONED BOUGHT PRICE_SEEN EXPERIENCED all {t, run, …}. IGNORE is derived (SAW with no CLICK), never stored | raw evidence, chronological, replayable |
| 3 | **Subjective worldview** — what they believe | reified Belief {value, evidence, about_id, that_id, t, valid_to} + HOLDS/ABOUT/THAT + DERIVED_FROM{count, first_t, last_t, kind, weight}; EXPECTS{about, strength, valid_to, cause_id}; REFERENCE_PRICE{valid_to}. confidence = E/(E+0.7), computed in Python. No live HOLDS edge = unknown = abstention (0.2: nodes are implicit by id, so absence lives on edges/props, never node existence) | provenance edges; belief-vs-truth divergence queries; as-of-T |
| 4 | **Preferences & habits** — what they like/do | PREFERS {w, evidence, source: prior\|learned, cause_kind, cause_id, t, valid_to} — the supersession chain IS the provenance timeline; HABIT {evidence, valid_to} (P1), strength = E/(E+2) | bitemporal history of a person's tastes — the flagship "what breaks without HydraDB" |
| 5 | **Goal state** — what they need now | NEEDS → Category {strength, budget_cap, deadline_t, valid_to, source: seeded\|scripted}; satisfied on category BUY (supersede w/ cause), expires at deadline; urgency computed in Python from deadline_t | goal_fit is a real 3-hop join need↔category↔product↔creative, with a queryable lifecycle |
| 6 | **Social context (P1)** — what people near them experienced | TRUSTS_PERSON {w} shopper↔shopper, seeded small-world; reads are as-of-previous-tick (no intra-tick feedback) | inherently relational; multi-hop influence paths; the strongest "vector store can't" exhibit |

**Rules hygiene:** fresh public repo, zero pre-hackathon commits, both authors committing, MIT/Apache-2.0 for your code (HydraDB's AGPL stays server-side), no Adcero code, attribute every dataset/library.

---

## Phase 0 — Both: Foundations & the Three Contracts

*Plain words: set the ground — repo, running database, and written agreements about the seams — so you don't need each other again until S1.*

### 0.1 Repo, rules, registration

Monorepo: `/engine /web /infra /eval /fixtures CONTRACT.md PLAN.md`. Both registered; both in Discord.

**Checkpoints**
- [x] git log clean (nothing pre-hackathon; both authors). LICENSE + README skeleton in. *(both authors committing as of 2026-08-16)*
- [x] Both can push. *(Garvit ✓; Atishay ✓ 2026-08-16 — gh device-flow auth as Atishay6571, pushed 483da20..aa466bc)*

### 0.2 HydraDB up and proven [Atishay drives]

Run the pinned image per repo README; verify with a round-tripped write over Bolt and HTTP; restart the container and confirm durability.

**Checkpoints**
- [x] CREATE→MATCH round-trips over Bolt and HTTP; survives docker restart. *(2026-08-16: `infra/smoke.py all` + restart + `verify`; Bolt auth = `neo4j.bearer_auth(token)`; HTTP = `POST /v1/graphs/default/query`, plain http locally)*
- [x] /readyz healthy; exact run command saved in /infra/README. *(digest-pinned compose + up.sh; findings recorded in /infra/README.md)*

### 0.3 Contracts v3 + stand-ins + shared artifacts

Write CONTRACT.md: C1 DecisionContext v3, C2 three-stage mind + persona split + ENTRY_POINTS registry, C3 results/metrics v3; event taxonomy v2; ID map (Appendix A); the four closed enums (Law 11); motif enum v2 (Appendix E); evidence.py committed and imported by both engine and mind code (Appendix F); appraisal bucket-key v2 spec (Appendix D, P1); determinism + event-log rules (JSONL = replay source of truth, now including NEED_ACTIVATED/EXPIRED/SATISFIED and EXPERIENCED records; worldview supersessions are recomputed on replay from events + evidence.py, never logged — keeps the log lean and the math the single source).

Stand-ins: Garvit writes MockHydraMem (canned scalars + canned v4 motifs, incl. the twin pair); Atishay writes ScriptedMind (scalars only — may read active_need scalars) + ScriptedConsolidate. Shared contract tests: context schema (incl. null-belief abstention case), motif enum coverage, registry completeness, evidence.py import check on both sides, consolidate purity (same inputs ⇒ same deltas).

Demo assets → `/fixtures/demo-brand/`: 1 fictional brand + 1–2 rival brands (habit/saturation exhibits need rivals), ~6 products with IN_CATEGORY and latent-quality table, 3–4 creatives, 2 page variants, 1 promo schedule, goal-scenario config (per-segment×category arrival rates + Maya's scripted schedule), social config (P1).

**Checkpoints**
- [ ] CONTRACT.md merged; each of you can explain every DecisionContext field, every motif, and every registry row. *(merged ✓; the "can explain" half is the joint ritual)*
- [x] Contract tests green on both stand-ins; twin fixture committed. *(2026-08-16: ScriptedMind/ScriptedConsolidate landed; 37 passed, 2 skipped — only the Phase-2 registry tests)*
- [x] The four enums + evidence.py live in single shared files imported by both sides. *(minds side now imports evidence.py too)*
- [x] Demo assets committed, incl. latent-quality table and goal config.

---

## Phase 1 — Atishay: HydraMem v3, the Worldview Store (uses: real HydraDB · needs nothing from Garvit)

*Plain words: build the librarian for a six-shelf library. Shelf one: the objective marketplace. Shelf two: the diary of what happened. Shelf three: what this shopper believes — each belief carrying how sure they are and which evidence made them sure. Shelf four: what they've learned to like — where every change in taste keeps a receipt (which click, which purchase caused it). Shelf five: what they need right now, with a deadline. Shelf six (P1): who they trust around them. The librarian answers one big question per decision — "find every story connecting this shopper to this stimulus" — as typed motif paths plus the usual numbers, and never, ever leaks the world's hidden truth (latent quality) directly.*

Why: divergence between shelves one and three IS the track — overwrite tracking (supersession with history on every layer), abstention (no path / no belief = no knowledge), cross-session synthesis (consolidation with provenance). The preference supersession chain and the goal lifecycle are retrieval stories no vector store can tell.

**Build items:**

- **1.1 — Hour-one probe** (now three measurements): (a) ~~does algo.SPpaths accept a heterogeneous relTypes list~~ **partially answered in 0.2** — SPpaths exists, bare-CALL form with integer ids works, relTypes list accepted (see decision 7); remaining: heterogeneous multi-type lists + both directions; (b) per-context latency, Route A vs Route B, on a seeded story graph; (c) batched Route B throughput — **caution from 0.2: UNWIND batch reads return adjacency only (`row.field` + `destination.id`), no edge props**, so props like (w, E, t, valid_to) need per-shopper singles or restructuring; measure both. Decide routing per motif; record in CONTRACT.md.
- **1.2 — Schema v3 + ID allocator + Cypher templates**: objective layer incl. Category/IN_CATEGORY and PRICED_AT{valid_to} history; subjective layer per §0.1 (Belief nodes carry denormalized about_id/that_id scalar props so the hot path reads props while the UI walks ABOUT/THAT/DERIVED_FROM edges); episodic taxonomy v2; NEEDS, TRUSTS_PERSON (P1), HABIT (P1). EXPLAIN every template once.
- **1.3 — Write path**: `ingest_catalog(csv)` (products, categories, attributes, latent table — latent props flagged unretrievable); `record_events(batch)` UNWIND per edge type; `supersede(...)` helper (works on subjective and objective edges and NEEDS); belief version supersession (SET old valid_to → CREATE new node id → re-link HOLDS/ABOUT/THAT → carry-forward + increment DERIVED_FROM; client-sequenced per constraint 3); preference supersession with {cause_kind, cause_id, t}; the EvidenceDelta applier: batch-read current (w, E) per delta key, apply the blend from evidence.py in Python, write supersessions in canonical order (shopper_id, t, event_rank); JSONL event log + run manifest (five hashes).
- **1.4 — Read path**: `get_decision_context(shopper, stimulus)`. Stimulus-side subgraph cached once per (stimulus, tick): CLAIMS→concepts, PROMOTES→brand, OFFERS→products+claimed_pct, IN_CATEGORY, current PRICED_AT, SHOWS (pages). Shopper-side, batchable via UNWIND across exposed shoppers: recent SAW (window ≈ 14 ticks) → past creative ids + t · live PREFERS · live NEEDS · trust Belief for stimulus brand (live HOLDS, filter about_id — one query thanks to denormalization) · live EXPECTS for brand · REFERENCE_PRICE for stimulus product · HABIT (P1) · TRUSTS_PERSON neighbors → peers' BOUGHT / EXPERIENCED on stimulus product, t < tick_start (P1) · UNWIND past-creative ids → their CLAIMS and their PROMOTES. Python then: adstock + 72h frequency from timestamps; preference_fit = live PREFERS ∩ stimulus claims; goal_fit = live NEEDS ∩ stimulus category (urgency from deadline); brand_semantic_fatigue = past creatives sharing BOTH a claimed concept AND the brand with the stimulus (recency-weighted); concept_saturation (P1) = concept overlap, different brand; expectation_violation = EXPECTS(about=brand) minus SHOWS at page decisions; social valence (P1). Strength thresholds + maxLen ≤ 4 + relType whitelists kill hub noise. Retrieval whitelist excludes latent props (Law 15).
- **1.5 — Trace + inspector**: `get_trace` (paths behind a decision, all motif types); `get_shopper_worldview` — live beliefs w/ value+evidence+confidence+provenance, live preferences w/ source, active needs w/ deadline, habits (P1); `get_preference_history(shopper, concept)` — the full version chain with causes, ready for the UI timeline.
- **1.6 — replay(run_config)**: fresh shopper-id block, re-ingest JSONL to tick T, recompute worldview deterministically (Law 13/14), diverge. The fulfillment queue is derived from BOUGHT events + lag — no extra state to persist; kill/resume reconstructs it from the log.

**Checkpoints**
- [ ] Routing decided per motif and written down, with measured latencies (single-context and batched).
- [ ] Contract tests green on real HydraMem (same tests the mock passes).
- [ ] Scripted story graph returns exactly the expected hits for all four P0 motifs — including a designed miss per motif (no path → motif absent → abstention works structurally) and a null trust belief for an unknown brand.
- [ ] The golden preference chain renders end-to-end: prior 0.45 → 0.476 → 0.532 → 0.614 → 0.714 → 0.761, each version carrying its cause (Appendix F numbers, asserted to the digit).
- [ ] Supersession proof on three layers: subjective (belief now vs as-of-T), objective (price now vs before the promo), goal (NEEDS active → satisfied-with-cause).
- [ ] A Belief's provenance renders: "value 0.70, confidence 0.81 — from 2 visits and 1 purchase."
- [ ] Hygiene test: latent props never appear in any DecisionContext, trace, or worldview payload.
- [ ] Goal-on/off twin: same shopper id pair, identical graphs except one NEEDS edge → contexts differ only in goal_fit + active_need.
- [ ] 10k-event batch ≤ ~10s; one context ≤ ~250ms with the stimulus cache; batched contexts for 200 shoppers × 1 stimulus ≤ ~3s; kill/restart/resume consistent (incl. pending fulfillment); replay determinism (byte-identical summaries, twice).

---

## Phase 2 — Garvit: The Minds v3 (uses: MockHydraMem · needs nothing from Atishay)

*Plain words: a shopper = three persona families (tastes they start with, lenses they interpret through, dials that turn judgment into action), eyes (an LLM that reads each ad once and writes what it claims into the objective graph), appraisal (turns retrieved motifs + numbers into interpretable 0–1 scores), gut (calibrated math + seeded dice picks the action), and a digestive system — consolidate() — that turns what happened into bounded worldview changes, strictly by the evidence hierarchy: seeing an ad teaches you what a brand says; only clicking, browsing, carting, buying and living with the product teach you what you like. The LLM never picks CLICK/BUY.*

**Build items:**

- **2.1 — Personas & population factory v3**: 6–8 segments; per shopper: preference priors → seeded PREFERS {source: prior, E0 = 2} around segment means (mixed logit); AppraisalTraits and ChoiceCoeffs drawn per Appendix D; goal-rate parameters per segment×category (consumed by the runner's generator); social small-world graph factory (P1: degree ≈ 4, weights U(0.4, 0.9), seeded). Seeded RNG only.
- **2.2 — Perception-as-graph-writer**: one LLM call per stimulus → strict JSON constrained to the Concept enum → graph delta (CLAIMS{strength}/PROMOTES/OFFERS{claimed_pct}, pages: SHOWS) through HydraMem. HAS_ATTR and IN_CATEGORY come from the catalog CSV, never the LLM. Disk-cached per stimulus hash; committed with runs.
- **2.3 — Appraisal, two impls behind one interface.** P0 dims (5): relevance ← preference_fit + goal_fit(strength×urgency) · credibility ← trust belief (value × f(confidence, trust_orientation)) + social_proof valence (P1); no belief → neutral-low floor · brand_message_fatigue ← brand_semantic_fatigue motif (recency-weighted, capped) · offer_attractiveness ← claimed_pct × deal_proneness — the perceived deal, distinct from the realized price gap in utility · expectation_alignment ← 1 − violation strength (page stage; 1.0 at ad stage). P1 dims (2): novelty ← (1 − concept_saturation) × novelty_seeking — market-freshness of the message (deliberately NOT driven by asset repetition, which already enters utility; this closes a latent v3 double-entry) · social_proof as its own dim if credibility gets crowded. Impl (a) formula (P0, default, the calibration backbone — Appendix D constants); impl (b) LLM (P1) — rubric-anchored, scored relative to a fixed reference ad, z-normalized, frozen per bucket-key v2.
- **2.4 — Choice model v3**: funnel IGNORE|CLICK → BOUNCE|BROWSE → CART|ABANDON → BUY|ABANDON. Stage utility U_s = Σ_d W[s,d]·Appraisal[d] + γ·adstock − δ·asset_wearout (+ post-click: price_sensitivity · gap, losses ×2) (+ CART/BUY, P1: switching_inertia · (H_stim − H_rival_max)) (+ BUY, P1: −risk_aversion·(1 − trust confidence)) + base_s; act with prob σ((U_s − θ_s)/τ), τ = impulsivity. Stage-conditional weights make goal-gating emerge from one entry point: relevance weighs far more at CART/BUY than at CLICK, so a shopper with no active need can still click out of curiosity but rarely buys. Guards: hard price > budget_left blocks BUY; price > active_need.budget_cap dampens BUY prob ×0.25.
- **2.5 — Worldview update rules = consolidate()**: pure function per Law 14 and Appendix F. SAW → awareness + EXPECTS(brand, claimed concepts) at weight 0.2 — nothing else. PRICE_SEEN → reference-price smoothing (α = 0.3). CLICK/BROWSE/CART/BUY → preference evidence on stimulus-claimed concepts at 0.10/0.25/0.50/1.00; BUY additionally satisfies the matching NEEDS, adds trust evidence 1.5 (target 0.65), habit +1 (P1). EXPERIENCED → trust evidence 2.0 with target = satisfaction (P1: disconfirmation multiplier ×(1 + 0.5·max(0, expectation − sat)) — overpromising ads poison trust harder); preference evidence ±0.75·(2·sat−1) only on concepts the product actually HAS_ATTR — ads teach expectations, experience teaches truth. Emits EvidenceDeltas; the engine applies them.

**Checkpoints**
- [ ] Golden perception files for the creatives + pages: schema-valid, every claim ∈ Concept enum, claimed_pct captured, rerun-stable.
- [ ] Motif-level monotonicity: +preference_fit ↑relevance · +goal_fit ↑relevance more at BUY stage than CLICK stage · +brand_semantic_fatigue ↑brand_message_fatigue · +violation ↓expectation_alignment · no paths + no awareness + no belief ⇒ engagement ≈ 0.
- [ ] No-learning-from-SAW unit: a shopper bombarded with exposures shows Δw = 0 on every learned preference while awareness/EXPECTS rise.
- [ ] Hierarchy monotonicity unit: equal counts of CLICK vs BROWSE vs CART vs BUY produce strictly ordered Δw.
- [ ] Registry-completeness + import-graph tests green; decide() signature contains no traits.
- [ ] Maya golden chain reproduced from evidence.py to the digit.
- [ ] Formula choice model produces plausible base rates (CTR ~0.5–5%).
- [ ] Same seed → identical action sequence on the mock, twice.
- [ ] LLM appraisal (if reached): calls == distinct bucket keys; real variance across buckets; spend guard + cache hit-rate logging.

---

## Phase 3 — Atishay: World Runner & Event Pipeline v3 (uses: ScriptedMind + real HydraMem)

*Plain words: the clock — now with three new hands. Each tick: needs arrive and expire, ads get shown, minds decide, events land, packages get delivered (purchases from earlier ticks come back as experiences), and at the end of the day every shopper's worldview digests what happened — in a fixed order, so replays are exact.*

**Tick loop v3:**

```
0. goal step        seeded arrivals / expiry / scripted overrides   (substream: seed,"goal",shopper,tick)
1. exposure         reach, targeting, frequency caps                (seeded)
2. stimulus caches  per (stimulus, tick) objective subgraph
3. retrieval        batched DecisionContexts
4. minds            appraise + decide per exposed shopper
5. episodic write   UNWIND batch per edge type
6. fulfillment      deliver due EXPERIENCED (purchases from t−lag)  (substream: seed,"fulfil",shopper,product,purchase_t; sat = clamp01(latent_quality + noise))
7. consolidation    consolidate() per active shopper → EvidenceDeltas → applier, canonical order
8. progress, results accumulation, checkpoint
```

**Build items:** 3.1 the loop above + progress endpoint + results.json. 3.2 replay/branch wired end-to-end (paired arms from one log; worldview recomputed, never replayed from stored deltas). 3.3 commit `/fixtures/scripted-run-1/` — ScriptedMind v2 reacts to active_need scalars (BUY only when a need is live and price ≤ cap) and ScriptedConsolidate produces a visible drift series, so the fixtures exercise goal + drift pipelines before S1.

**Checkpoints**
- [ ] 200 shoppers × 14 sim-days with ScriptedMind ≤ ~1.5 min against real HydraDB.
- [ ] Paired branch run: two arms, identical populations, per-arm funnels.
- [ ] Kill at tick 7 → resume → totals consistent, including a fulfillment delivery pending across the kill.
- [ ] Goal lifecycle visible in fixtures: NEEDS activated → satisfied-by-purchase with cause.
- [ ] Fixtures committed and C3-valid (drift + goal stats populated).

---

## Phase 4 — Garvit: Experiment Adapters v3 (uses: MockHydraMem + 20-line mini-driver)

*Plain words: three experiment types = three stimulus feeds into one engine — and every adapter keeps the objective shelf honest: pricing writes real PRICED_AT supersessions, pages write SHOWS, and now scenario packs schedule the market itself: when needs surge and how good the products secretly are.*

**Build items:** 4.1 ad test (N creatives × audience × T days). 4.2 pricing/promo: schedule → PRICED_AT supersessions + PRICE_SEEN; promo-addiction config = 3 discount cycles. 4.3 page A/B: variant descriptors → SHOWS; seeded 50/50; violation motif live. 4.4 tuning of the calibration layer only (choice weights/thresholds, smoothing α, fatigue thresholds) — evidence.py constants are frozen by hash, not tuned here. 4.5 — scenario packs: need-wave config ("marathon season": a scheduled arrival burst in one category — the demo lever); latent-quality/overpromise table (P1: claims ≫ latent quality for one brand); social on/off (P1).

**Checkpoints**
- [ ] Mini-driver runs all three experiment types on the mock.
- [ ] Violation arm bounces measurably more than the consistent arm (mini-run).
- [ ] Promo mini-run shows downward reference-price drift across cycles.
- [ ] Objective layer stays truthful: PRICED_AT history reconstructs the schedule exactly, and NEEDS history reconstructs the configured wave exactly.

---

## Phase 5 — Garvit: Dashboard & Recommendations v3 (uses: C3 fixtures + MockHydraMem)

*Plain words: the owner's cockpit — and the crown jewel: click one shopper and watch a person form. Their beliefs with confidence bars and receipts, their tastes as a timeline of cause-stamped changes, the need that made today different from last week, and the exact graph paths that explain the decision.*

**Build items:** 5.1 run launcher (experiment type, uploads, audience sliders, scenario pack, seeds). 5.2 results views: funnels per arm, segment heatmap, CTR-by-day, promo chart, fatigue-split chart (asset vs brand-message vs concept P1), preference-drift chart, goal-conversion split (P(buy | need) vs P(buy | none)), LTV/repeat toggle (P1). 5.3 shopper drill-down, four panels: diary timeline · worldview (belief cards: value + confidence bar + "from 2 visits, 1 purchase" provenance; expectations) · preference timeline (supersession chain with cause chips: "CLICK ad X · +0.05") · goals & experience (active-needs chip with countdown; experience feed) — plus the motif-path why-trace; social ring (P1). 5.4 recommendations: Grade 1 mined rules over MetricsReport, now incl. motif/goal findings ("conversions with an active need present converted 6×"; "brand-message fatigue onset at 4 exposures — rotate concepts"); Grade 2 interviews (P1: prompt = persona + that shopper's DecisionContext; answers may cite only retrieved facts).

**Checkpoints**
- [ ] Entire UI drivable on fixtures with the engine stubbed.
- [ ] The fixture story shopper renders coherently across all four panels; motifs render as paths.
- [ ] Preference timeline shows the golden chain with cause chips.
- [ ] 5 interview answers spot-checked: zero facts outside that shopper's context (P1).
- [ ] ≥ 3 sensible Grade-1 recommendations from fixture metrics.

---

## Phase 6 — Atishay: Analytics & MetricsReport v3 (uses: Phase-3 scripted runs · parallel to 4–5)

**Build items:** 6.1 funnels per arm × segment with bootstrap CIs; CTR-by-day; drop-off localization; reference-price trajectories; fatigue split (asset wearout vs brand-message vs concept P1); preference-drift curves (learned w over time per concept × segment); goal stats (conversion split, time-to-satisfaction); belief metrics (confidence distribution, drift, provenance coverage = % of subjective versions carrying a cause); violation counts + bounce delta; motif prevalence by outcome; repeat-purchase/LTV per arm (P1); social lift (P1). Emit MetricsReport per C3. 6.2 tiny golden run (5 shoppers, 3 ticks, one full evidence chain) with hand-checked numbers asserted in tests.

**Checkpoints**
- [ ] MetricsReport validates against C3.v3; drift + goal + confidence metrics populated.
- [ ] Golden-run numbers — including the evidence blend — match hand computation exactly.
- [ ] One command from run directory → full report.

---

## SYNC S1 — Both: The Great Swap (~half a day; the only integration event before shipping)

Steps: flip `--impl mock→hydra`, `--mind scripted→real`; contract tests on both real implementations; flagship scenario end-to-end; dashboard on the live engine; keep stand-ins for unit tests.

**Checkpoints**
- [ ] Both real implementations pass both contract suites (incl. registry + hygiene tests).
- [ ] 200 × 14 real×real ≤ ~4 min laptop wall-clock (consolidation included).
- [ ] Perception calls == unique stimuli; appraisal LLM calls (if enabled) == distinct bucket keys.
- [ ] Same seed twice → identical results.json hash; manifest carries all five hashes.
- [ ] Maya twin live: identical ad, need off vs on, probability gap quantified, retrieved paths listed.
- [ ] No-learning-from-exposure holds on the real stack (invariant audit over the run — see F7).
- [ ] Smoke: promo drift visible; violation arm bounces more; a fulfillment delivery updates a trust belief on screen; the preference timeline renders live.

---

## Phase 7 — Atishay: Calibration & Evals (post-S1)

*Plain words: proof it isn't a toy — the laws of advertising hold, the numbers sit in realistic ranges, and behavior changes for the right reasons, verifiable down to which event caused which belief.*

**7.1 Face-validity suite** (each = a scripted scenario or invariant audit, one command):

- **F1** frequency response rises then wears out (asset level) (v3)
- **F2** unaware + no paths + no belief ⇒ engagement ≈ 0 (v3)
- **F3** discount uplift ordering matches price sensitivity (v3)
- **F4** promo addiction: promo-window purchase share +≥15pp cycle 1→3, full-price conversion trending down (v3)
- **F5** violation arm bounces more than consistent arm (v3)
- **F6** abstention chart: gated vs ungated on an unknown brand — hallucinated familiarity ≈ 0 when gated (v3)
- **F7 (P0)** no learning from exposure — two teeth: (a) invariant audit over any run: every learned-PREFERS version's cause_kind ∈ {CLICK, BROWSE, CART, BUY, EXPERIENCED}, never SAW/none; (b) scenario: heavy-exposure arm with zero clicks → flat learned preferences, rising awareness.
- **F8 (P0)** evidence hierarchy: equal counts of CLICK vs BROWSE vs CART vs BUY → strictly ordered Δw (unit-level, deterministic).
- **F9 (P0)** the Maya law: paired twin runs (same seed), goal off vs on, same ad → BUY uplift ratio > CTR uplift ratio, both above thresholds. This is the demo claim as a test.
- **F10 (P0)** confidence-differential updating: identical contradictory evidence moves a low-E belief more than a high-E belief.
- **F11 (P0)** experience loop: latent-quality 0.85 vs 0.35 arms → trust trajectories diverge, repeat-purchase rate drops in the bad arm.
- **F12 (P0)** fatigue separation: within one brand, same-concept repetition decays CTR faster than concept rotation (cross-brand saturation third arm = P1).
- **F13 (P1)** habit: after k seeded purchases, a competitor needs Δprice ≥ threshold to convert.
- **F14 (P1)** social on/off: adoption lift among connected vs isolated shoppers.
- **F15 (P1)** overpromise: the overpromising arm wins CTR and loses 30-tick LTV — the "clicks aren't the business" exhibit.

**7.2** aggregate calibration to public CTR ranges (Criteo/Avazu), before/after documented. **7.3** rank-agreement via synthetic oracle (Spearman ≥ ~0.7 across ≥5 seeds), calibrating stage weights. **7.4** abstention chart (F6 artifact). **7.5** stretch: LongMemEval slice through HydraMem's generic API.

**Checkpoints**
- [ ] `make eval` reproduces every number and plot from scratch.
- [ ] All P0 face-validity laws hold; F7 and F9 are marked never-drop — they ARE the demo claim.
- [ ] Calibration + rank-agreement + abstention artifacts committed to /eval.

---

## Phase 8 — Garvit: Product Polish & the Story (post-S1)

**Build items:** 8.1 zero-terminal flow end-to-end. 8.2 CSV catalog import (must); Shopify dev-store pull (nice); OAuth (only if embarrassingly ahead). 8.3 — **Maya's ten beats, tuned and hand-picked:**

1. Persona prior: eco 0.45, no active needs.
2. Sees the ShoeCo ad → ignores (retrieval shows: preference_fit only, no goal, no belief).
3. Over several days she clicks/browses/carts eco stimuli → learned eco climbs 0.45 → 0.61, every step cause-stamped.
4. ReplaceRunningShoes activates (scripted).
5. The same ad → retrieval now lists goal_fit + preference_fit(0.61) + learned reference price + low brand fatigue → probability jumps an order of magnitude.
6. She buys (0.714).
7. Fulfillment delivers a positive experience → a trust belief forms, confidence rises, eco hits 0.761.
8. The next Brand-X ad lands differently again.
9. Twin control side-by-side: same seed, no goal → still ignoring.
10. The dashboard shows the paths and receipts behind every beat.

Humane error states throughout. 8.4 Grade-3 recommendations if time (P2): auto-branch a follow-up sim implementing the top recommendation → projected lift.

**Checkpoints**
- [ ] Full experiment with zero terminal use.
- [ ] CSV round-trips the demo catalog; (if reached) Shopify products in the picker.
- [ ] All ten Maya beats render live, video-ready; no blank screens on failure.

---

## Phase 9 — Both: Ship

**Build items:** 9.1 [A] `docker compose up` (hydradb pinned digest + engine + web) + `make demo`. 9.2 [G writes, A reviews] README: the four track requirements mapped to mechanisms in one sentence each — cross-session synthesis → consolidate() + evidence accumulation with provenance; chronological order → episodic supersession + goal lifecycles + lagged fulfillment; overwrite tracking → valid_to history on subjective AND objective AND needs layers; abstention → no path / no belief = no knowledge. Include the key claim verbatim: *"These are not static personas answering prompts. Each shopper has an evolving model of the marketplace: what is objectively true, what happened to them, what they believe, what they have learned to prefer, what they currently need, and what people around them have experienced. HydraDB retrieves the portion of that evolving world model relevant to each new stimulus, and those paths alter subsequent behavior."* Plus the honest lines: retrieval is a motif library (controllable behavioral laws, by design) and goals are exogenous — this sim demonstrates demand capture, not demand creation (say it before a judge does). Architecture diagram; "what breaks without HydraDB" — worldview-divergence queries, motif paths, preference time-travel, goal-lifecycle joins, provenance, branch/replay, social paths (P1); setup; eval results; attributions. Adding a mechanism later = a motif-enum row + a classifier case + a registry row — no schema change; that sentence goes in the README. 9.3 video ≤ 3:00 [G narrates]: 0:00–0:20 problem → 0:20–0:50 what we built → 0:50–1:50 Maya's beats live, twin on screen → 1:50–2:20 promo-addiction + fatigue-split + violation charts → 2:20–2:45 a recommendation + eval numbers (F7/F9 on screen) → 2:45–3:00 track fit + why HydraDB. Two takes; captions. 9.4 submit: every link tested logged-out; internal freeze ≥ 6h before Aug 20, 11:59 PM PT (= Aug 21, 12:29 PM IST).

**Checkpoints**
- [ ] Fresh clone → docker compose up + make demo reproduces the flagship run.
- [ ] Every README command copy-pastes and runs.
- [ ] Video ≤ 3:00, audible, captioned, works logged-out.
- [ ] Submitted with buffer; git log clean; no Adcero code.

---

## Cut list (law once Phases 1–6 close)

**P0 — fails without:** five of six families minimally (social excluded): Categories + latent params · EXPERIENCED + fulfillment generator (satisfaction only) · beliefs with evidence + confidence math · behavior-only preference learning with cause provenance · seeded goals + goal_fit · persona three-family split + registry · motifs {preference_fit, goal_fit, brand_semantic_fatigue, expectation_violation} · consolidate() in the tick loop · formula appraisal (5 dims) · all three experiment types · runner + paired counterfactuals · dashboard core + four-panel drill-down · F1–F12 core evals + abstention chart · compose + README + video with the Maya twin.

**P1 — cut first (or pull first if ahead):** overpromise/LTV exhibit (F15) — cheapest, highest demo value, pull this one first · social layer + social_proof + F14 · concept_saturation + novelty dim (F12 full triple) · habit/inertia + F13 · disconfirmation multiplier · LLM appraisal (bucketed, frozen) · quality belief + shipping/VFM dims · graded evidence targets · risk_aversion term · interview recommendations · rank-agreement study · Shopify dev-store pull · fancy graph viz (fallback: clean list rendering of paths).

**P2 — stretch:** Grade-3 closed-loop lift · LongMemEval slice · Bayesian beliefs · ad-induced needs (excluded on purpose: would double-count the expectation/preference channels) · attention model (real IGNORE evidence) · event-level full reification · Shopify OAuth · screenshot page perception · cloud deploy · LoRA "learned mind" distillation.

**Degradation ladder** (pre-agreed drop order inside P0 if slipping at S1, no debate): quality_belief → confidence display (keep the math) → goal urgency (needs go binary) → EXPERIENCED extra dims (satisfaction only) → brand_semantic_fatigue falls back to un-split semantic_fatigue. **Never drop F7/F9.**

## Risk register

| Risk | Mitigation |
|---|---|
| SPpaths can't do heterogeneous motif paths | Hour-one probe; Route B (per-motif single-hop + Python joins) pre-agreed; batched Route B measured too |
| Vocabulary drift silently empties intersections | Four closed enums, single shared file, parse-time enforcement, checkpointed |
| Double-count regressions (persona, fatigue, price, adstock) | Law 12 registry + completeness/import tests; offer = perceived deal, price gap = realized; novelty deliberately not adstock-driven |
| Learning-from-exposure sneaks back in (one confused updater) | F7 invariant audit runs on every eval; EXPECTS vs PREFERS updaters kept in separate functions |
| Belief-version write churn (history never erased) | Law 14 bounds (ε = 0.01, ≤6 writes/shopper/tick); watch write volume at S1 perf check |
| Consolidation nondeterminism | Canonical event ordering + pure consolidate() + seeded substreams; replay recomputes, never re-reads deltas |
| Social endogeneity / cold start (P1) | As-of-previous-tick reads; capped weight; on/off ablation is the honest exhibit |
| Goal config unrealistic | Scenario packs make waves explicit demo levers; README states goals are exogenous |
| Appraisal LLM cost/determinism (P1) | Bucket-key v2 freeze; formula appraisal is the backbone; spend cap |
| Hub-node path noise | maxLen ≤ 4, relType whitelists, strength thresholds |
| HydraDB v0.1 bug | All Cypher in HydraMem; smoke scripts; Discord; pinned digest |
| Integration crunch | Three contracts, two stand-ins, shared tests; S1 is a swap |
| Scope (v4-P0 ≈ 1.5–2 person-days over v3-P0, ~4 days left) | Cut list is law; degradation ladder pre-agreed; P1 pulls only if ahead |
| Deadline confusion | Cutoff verified: Aug 20 11:59 PM PT = Aug 21 12:29 PM IST; freeze ≥ 6h earlier |

## Working rhythm

15-minute sync at the start of each working day (contract or registry changes? blockers? batched Discord questions). End of each phase: tick checkpoints together; anything unticked rolls forward explicitly.

---

## Appendix A — ID allocation map

| Entity | Range | Notes |
|---|---|---|
| Segment | 1,000+ | ~8 |
| Concept vocabulary | 5,000–5,499 | closed enum, fixed in Phase 0.3 |
| Category vocabulary | 5,500–5,999 | closed enum, ~8–12 |
| Brand | 6,000+ | demo brand = 6,001; rivals 6,002+ |
| Belief nodes | 8,000,000+ | reified, per shopper-run block offset; new id per version |
| Creative | 2,000,000+ | |
| Product | 3,000,000+ | latent props unretrievable (Law 15) |
| PageVariant | 4,000,000+ | |
| Shopper | 1,000,000 + run_index × 100,000 | run isolation lives here; TRUSTS_PERSON stays within a run's block |

## Appendix B — DecisionContext v3 (contract C1's currency)

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

The first nine scalar fields are byte-compatible with the v3 MemoryPacket — ScriptedMind and all early code read them unchanged. `trust_belief: null` for an unknown brand is the abstention story, structurally. `active_need.budget_cap` is consumed by decide() only; the need's strength×urgency is consumed by appraise() only via the goal_fit motif (ScriptedMind, test-only, may read the scalars).

## Appendix C — Cypher templates (subset-safe; only inside HydraMem; additions to v3's set)

> **⚠ 0.2 amendment (2026-08-16, tested live — see /infra/README.md):** these templates predate the probing and several are invalid as written. Transform before use:
> 1. No `MATCH … CREATE/MERGE` compounds and no `MERGE … SET` — every write is one self-contained statement. The goal-activate template below is doubly invalid (compound + UNWIND CREATE cannot carry edge props): activation = per-row `CREATE (s {id: row.sid})-[:NEEDS {…}]->(c {id: row.cat})` singles with inline props.
> 2. No bare-node CREATE: belief-version creation (`CREATE (nb {id: $new_id, …})`) becomes implicit-node + `MATCH (nb {id: $new_id}) SET nb.value = $v, …`; re-linking (`MATCH (s),(nb) CREATE (s)-[:HOLDS]->(nb)`) becomes `CREATE (s {id: $sid})-[:HOLDS]->(nb {id: $new_id})`.
> 3. The supersede templates (`MATCH (s)-[n:X]->(c) WHERE n.valid_to > $now SET n.valid_to = $now`) are **verified working as written**, including live-edge filtering and history reads — the flagship mechanic round-trips.
> 4. Batched single-hop reads must be exactly `UNWIND $rows AS row MATCH (s {id: row.sid})-[e:TYPE]->(x) RETURN row.sid, x.id` — adjacency only; the Route-B examples below that RETURN edge props run as per-shopper singles instead.
> 5. One transient `mutation engine` 50N42 was observed once right after a restart and did not reproduce — retry a spuriously failing write once before digging.

```cypher
-- goal: activate (goal step, batched)
UNWIND $rows AS row
MATCH (s {id: row.sid}), (c {id: row.cat})
CREATE (s)-[:NEEDS {strength: row.st, budget_cap: row.cap, deadline_t: row.dl,
                    t: row.t, valid_to: 9007199254740991, source: row.src}]->(c)

-- goal: satisfy or expire = the standard two-statement supersede, with a cause
MATCH (s {id: $sid})-[n:NEEDS]->(c {id: $cat}) WHERE n.valid_to > $now
SET n.valid_to = $now
-- (satisfied: recreate is unnecessary; the closed edge with its timestamps IS the record)

-- goal_fit Route B: shopper side (batched across exposed shoppers)
UNWIND $sids AS sid MATCH (s {id: sid})-[n:NEEDS]->(c) WHERE n.valid_to > $now
RETURN sid, c.id AS cat, n.strength AS st, n.deadline_t AS dl
-- stimulus side, cached once per (stimulus, tick):
MATCH (cr {id: $cid})-[:OFFERS]->(p) RETURN p.id
MATCH (p {id: $pid})-[:IN_CATEGORY]->(c) RETURN c.id

-- brand-semantic-fatigue Route B (stimulus claims K and brand B already cached)
MATCH (s {id: $sid})-[e:SAW]->(cr) WHERE e.t > $since RETURN cr.id AS cid, e.t AS t
UNWIND $past_ids AS pid MATCH (c {id: pid})-[k:CLAIMS]->(a)   RETURN pid, a.id
UNWIND $past_ids AS pid MATCH (c {id: pid})-[:PROMOTES]->(b)  RETURN pid, b.id
-- Python: fatigue = past creatives with (claims ∩ K ≠ ∅) AND (brand == B), recency-weighted;
--         concept_saturation (P1) = overlap with brand != B

-- trust belief, hot path (denormalized props; UI walks ABOUT/THAT/DERIVED_FROM instead)
MATCH (s {id: $sid})-[:HOLDS]->(b) WHERE b.valid_to > $now
RETURN b.id, b.value, b.evidence, b.about_id, b.that_id

-- belief version supersession (client-sequenced, constraint 3)
MATCH (b {id: $old_id}) SET b.valid_to = $now
CREATE (nb {id: $new_id, value: $v, evidence: $e, about_id: $brand, that_id: $concept,
            t: $now, valid_to: 9007199254740991})
MATCH (s {id: $sid}), (nb {id: $new_id}) CREATE (s)-[:HOLDS]->(nb)
-- then ABOUT, THAT, and DERIVED_FROM {count, first_t, last_t, kind, weight} per source

-- preference supersession with a receipt
MATCH (s {id: $sid})-[p:PREFERS]->(a {id: $aid}) WHERE p.valid_to > $now SET p.valid_to = $now
MATCH (s {id: $sid}), (a {id: $aid})
CREATE (s)-[:PREFERS {w: $w, evidence: $e, source: 'learned',
                      cause_kind: $ck, cause_id: $cid, t: $now,
                      valid_to: 9007199254740991}]->(a)

-- social (P1): neighbors, then peers' purchases/experiences as-of previous tick
MATCH (s {id: $sid})-[t:TRUSTS_PERSON]->(o) RETURN o.id, t.w
UNWIND $peer_ids AS pid MATCH (x {id: pid})-[e:BOUGHT]->(p {id: $prod})
WHERE e.t < $tick_start RETURN pid, e.t
UNWIND $peer_ids AS pid MATCH (x {id: pid})-[e:EXPERIENCED]->(p {id: $prod})
WHERE e.t < $tick_start RETURN pid, e.sat, e.t
```

## Appendix D — Contracts C2 & C3 sketches

### C2 — three-stage mind + the split

```python
@frozen class AppraisalTraits:   # appraise() only
    novelty_seeking: float; trust_orientation: float; deal_proneness: float
    # preference priors (eco/luxury/…) are NOT traits — they live as seeded PREFERS edges.
    # Multiplying an affinity again in appraisal would count it twice (the PREFERS weight
    # already starts as the prior). The registry test exists to keep this true.

@frozen class ChoiceCoeffs:      # decide() only
    impulsivity: float           # = Gumbel/logistic temperature τ — its ONE entry
    price_sensitivity: float; budget: float
    switching_inertia: float     # P1
    risk_aversion: float         # P1: × (1 − trust confidence), BUY stage only
    stage_bases: dict            # θ_s per stage

def appraise(ctx: DecisionContext, traits: AppraisalTraits) -> Appraisal
# P0 dims: relevance, credibility, brand_message_fatigue,
#          offer_attractiveness, expectation_alignment          (all 0..1)
# P1 dims: novelty, social_proof
def decide(a: Appraisal, s: Scalars, coeffs: ChoiceCoeffs, rng) -> Action
# Action: IGNORE | CLICK | BOUNCE | BROWSE | CART | ABANDON | BUY
def consolidate(events: list[Event], snapshot: WorldviewSnapshot) -> list[EvidenceDelta]
# pure; EvidenceDelta = {key: (edge|belief, subject, object), target, weight, cause_kind, cause_id}
# the ENGINE applies deltas: batch-read current (w, E), blend per evidence.py, write supersessions
```

**ENTRY_POINTS registry** (excerpt — the full table lives in CONTRACT.md and code): preference priors → PREFERS seeds · PREFERS.w → appraisal:relevance · NEEDS.strength×urgency → appraisal:relevance (goal_fit) · NEEDS.budget_cap → utility:guard · trust_belief → appraisal:credibility · trust_orientation → appraisal:credibility · brand_semantic_fatigue → appraisal:brand_message_fatigue · claimed_pct×deal_proneness → appraisal:offer_attractiveness (perceived deal) · violation → appraisal:expectation_alignment · adstock & asset_wearout → utility (γ, δ) — the single asset-repetition entry · price_gap×price_sensitivity → utility (realized price) · impulsivity → τ · habit×switching_inertia → utility CART/BUY (P1) · concept_saturation → appraisal:novelty (P1) · social valence → appraisal:social_proof (P1) · risk_aversion×(1−conf) → utility BUY (P1). Tests: every Traits/Coeffs/Scalars/motif field appears exactly once; decide() has no traits param; import-graph check.

**Bucket key v2** (P1 LLM appraisal): `(stimulus_id, segment_id, sorted[(motif_type, strength∈{0,L,M,H})], trust∈{none,L,M,H}×conf∈{L,H}, need∈{none,L,M,H}, fatigue_bucket, price_gap_bucket)` — keep buckets coarse; a few hundred keys per run, cached, frozen, hash in manifest.

### C3 — results.json / MetricsReport keys

`run_manifest{seed, config_hash, perception_cache_hash, appraisal_cache_hash, evidence_hash, goal_config_hash, latent_quality_hash, social_config_hash?}` · `funnel[arm][segment]` · `ctr_by_day[]` · `fatigue_split{asset[], brand_msg[], concept[]?}` · `reference_price_trajectory[]` · `violations{count, bounce_delta}` · `motif_stats{type: {prevalence_by_outcome, mean_strength}}` · `preference_drift[{concept, segment, series}]` · `goal_stats{p_buy_need_on, p_buy_need_off, time_to_satisfaction[]}` · `belief_confidence_dist[]` · `belief_drift[]` · `provenance_coverage` · `repeat_ltv_by_arm[]?` · `social_lift?` · `ci{metric: [lo, hi]}`

## Appendix E — Motif library v2

| Motif | Path signature | Plain words | Entry point | Pri | Role |
|---|---|---|---|---|---|
| preference_fit | PREFERS · CLAIMS | "this ad claims something I (now) care about" | appraisal: relevance | P0 | behavioral |
| goal_fit | NEEDS · IN_CATEGORY · OFFERS | "this is the thing I currently need" | appraisal: relevance (strength × urgency) | P0 | behavioral |
| brand_semantic_fatigue | SAW · CLAIMS · CLAIMS ⋈ same PROMOTES brand | "this brand keeps telling me the same story" | appraisal: brand_message_fatigue | P0 | behavioral |
| expectation_violation | EXPECTS vs SHOWS diff | "the ad promised it; the page hides it" | appraisal: expectation_alignment | P0 | behavioral |
| concept_saturation | SAW · CLAIMS · CLAIMS ⋈ other brand | "every company says this now" | appraisal: novelty (inverse) | P1 | behavioral |
| social_proof | TRUSTS_PERSON · BOUGHT (+EXPERIENCED valence) | "someone I trust bought it — and how it went" | appraisal: social_proof | P1 | behavioral |
| experience_path | EXPERIENCED · SOLD_BY · PROMOTES | "my last purchase from them went well/badly" | trace only — effect routes via the trust belief | P0 | explanatory |
| habit_path | BOUGHT · SOLD_BY history | "I always buy Brand X" | trace only — effect via habit scalars | P1 | explanatory |
| ~~brand_transfer, trust_path~~ (v3) | — | retired — absorbed by trust belief / habit / social to prevent double-counting | — | — | retired |

Signals deliberately kept as scalars, not motifs (Law 16): reference price, price gap, budget, need budget cap, trust/quality belief values, habit strengths, adstock/wearout. Adding a mechanism later = a motif-enum row + a classifier case + a registry row — no schema change.

> *[Editor's note: the source message was truncated mid-Appendix E; the final sentence above is completed from the identical statement in §9.2. Anything that followed Appendix F in the original document should be pasted here by Garvit if it exists.]*

## Appendix F — evidence.py (the single source of behavioral learning)

| Event | Preference weight | Trust/belief weight | Notes |
|---|---|---|---|
| SAW | 0 | 0.2 (EXPECTS only) | awareness, adstock, expectations — never taste |
| IGNORE (derived) | 0 (P0) | 0 | ambiguous without an attention model (P2) |
| CLICK | 0.10 | 0.2 | on stimulus-claimed concepts, target = 1 |
| BROWSE / VISITED | 0.25 | 0.75 (target 0.6) | |
| CART | 0.50 | — | |
| BUY | 1.00 | 1.5 (target 0.65) | also: satisfy NEEDS; habit +1 (P1) |
| EXPERIENCED | ±0.75·(2·sat − 1) | 2.0 (target = sat) | prefs only on concepts the product HAS_ATTR; P1: weight ×(1 + 0.5·max(0, expectation − sat)) |
| Social report (P1) | 0 | 0.5 · peer_trust | |

**One formula everywhere:** `w' = (E·w + wt·target) / (E + wt)`; `E' = min(E + wt, 8)`. Priors seed E0 = 2. Belief confidence = `E / (E + 0.7)`. Contradiction moves low-E beliefs more automatically — no extra mechanism. Bounds per Law 14 (ε = 0.01, ≤ 6 writes/shopper/tick). Reference-price smoothing α = 0.3.

**The golden chain** (asserted in tests, rendered in the demo): eco prior 0.45 (E=2) → CLICK 0.476 → BROWSE 0.532 → CART 0.614 → BUY 0.714 → positive experience 0.761 (E=4.6, confidence 0.87) — each version carrying {cause_kind, cause_id, t}. A belief built from 2 visits + 1 purchase: E = 3.0 → confidence 0.81 → "Maya believes Brand X is high-quality with 81% confidence, based on two visits and one successful purchase."
