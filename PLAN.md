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
- [x] Routing decided per motif and written down, with measured latencies (single-context and batched). *(2026-08-16: Route B everywhere — SPpaths is strictly direction-following, reversed-hop motif paths return 0 paths; CONTRACT.md §Routing + /infra/README.md Phase-1.1 section)*
- [x] Contract tests green on real HydraMem (same tests the mock passes). *(SHOPSIM_HYDRAMEM=real: full suite incl. real-marked integration tests, 62 passed at Phase-1 close — 155 as of Phase 3; default mock run byte-identical)*
- [x] Scripted story graph returns exactly the expected hits for all four P0 motifs — including a designed miss per motif (no path → motif absent → abstention works structurally) and a null trust belief for an unknown brand. *(story.py cast + tests/real/test_motifs_real.py; P1 social_proof hit/miss too)*
- [x] The golden preference chain renders end-to-end: prior 0.45 → 0.476 → 0.532 → 0.614 → 0.714 → 0.761, each version carrying its cause (Appendix F numbers, asserted to the digit). *(test_golden_chain_real.py, on a dedicated shopper — 1000042 stays twin-symmetric)*
- [x] Supersession proof on three layers: subjective (belief now vs as-of-T), objective (price now vs before the promo), goal (NEEDS active → satisfied-with-cause). *(test_supersession_real.py)*
- [x] A Belief's provenance renders: "value 0.70, confidence 0.81 — from 2 visits and 1 purchase." *(get_shopper_worldview provenance_sentence, DERIVED_FROM-backed)*
- [x] Hygiene test: latent props never appear in any DecisionContext, trace, or worldview payload. *(validate_context at the read boundary + payload scans + cypher.py source-scan test)*
- [x] Goal-on/off twin: same shopper id pair, identical graphs except one NEEDS edge → contexts differ only in goal_fit + active_need. *(live on the real graph)*
- [x] ~~10k-event batch ≤ ~10s~~ **amended by 1.1 probing** (same rank as the 0.2 amendments): one context 9ms ✓ (≤250ms), 200×1 batch 0.63s ✓ (≤3s); the 10k batch measures **~47–58s** because prop-carrying writes commit at ~200–230/s through the single-writer path — transport/parallelism/consistency-independent, and the slatedb env override proved inert (per-write WriteOptions, not a Setting; flush_interval already 1ms — see /infra/README.md). The target predates this measurement. Real load ≈2s/tick fits Phase-3 (≤1.5 min) and S1 (≤4 min) budgets; pre-agreed escalations recorded in /infra/README.md (write-behind overlap; last-resort tick-partitioned rel types ≈5s/10k). ~~kill/restart/resume · replay determinism~~ *(moved to Phase 3 with replay, 2026-08-16)*

---

## Phase 2 — Garvit: The Minds v3 (uses: ~~MockHydraMem · needs nothing from Atishay~~ **amended 2026-08-17**: Phase 1 shipped first, so Phase 2 was built and integration-tested against the **real HydraMem** on a live local HydraDB — `tests/real/test_minds_real.py`; MockHydraMem retained for unit tests only)

*Plain words: a shopper = three persona families (tastes they start with, lenses they interpret through, dials that turn judgment into action), eyes (an LLM that reads each ad once and writes what it claims into the objective graph), appraisal (turns retrieved motifs + numbers into interpretable 0–1 scores), gut (calibrated math + seeded dice picks the action), and a digestive system — consolidate() — that turns what happened into bounded worldview changes, strictly by the evidence hierarchy: seeing an ad teaches you what a brand says; only clicking, browsing, carting, buying and living with the product teach you what you like. The LLM never picks CLICK/BUY.*

**Build items:**

- **2.1 — Personas & population factory v3**: ~~6–8 segments~~ **13 authored segments** (`fixtures/demo-brand/personas.json`, archetypes + numbers grounded in `/eval/market-research.md`; population size and segment count are pure config, architecture validated at 50 segments × 5,000 shoppers — 2026-08-17); per shopper: preference priors → seeded PREFERS {source: prior, E0 = 2} around segment means (mixed logit); AppraisalTraits and ChoiceCoeffs drawn per Appendix D; goal-rate parameters per segment×category (consumed by the runner's generator; rows for segments 1007–1013 added to goal_config.json); social small-world graph factory (P1: degree ≈ 4, weights U(0.4, 0.9), seeded). Seeded RNG only — per-shopper substreams `(seed, "pop", offset)`, so growing the population never changes existing shoppers.
- **2.2 — Perception-as-graph-writer**: one LLM call per stimulus → strict JSON constrained to the Concept enum → graph delta (CLAIMS{strength}/PROMOTES/OFFERS{claimed_pct}, pages: SHOWS) through HydraMem. HAS_ATTR and IN_CATEGORY come from the catalog CSV, never the LLM. Disk-cached per stimulus hash; committed with runs.
- **2.3 — Appraisal, two impls behind one interface.** P0 dims (5): relevance ← preference_fit + goal_fit(strength×urgency) · credibility ← trust belief (value × f(confidence, trust_orientation)) + social_proof valence (P1); no belief → neutral-low floor · brand_message_fatigue ← brand_semantic_fatigue motif (recency-weighted, capped) · offer_attractiveness ← claimed_pct × deal_proneness — the perceived deal, distinct from the realized price gap in utility · expectation_alignment ← 1 − violation strength (page stage; 1.0 at ad stage). P1 dims (2): novelty ← (1 − concept_saturation) × novelty_seeking — market-freshness of the message (deliberately NOT driven by asset repetition, which already enters utility; this closes a latent v3 double-entry) · social_proof as its own dim if credibility gets crowded. Impl (a) formula (P0, default, the calibration backbone — Appendix D constants); impl (b) LLM (P1) — rubric-anchored, scored relative to a fixed reference ad, z-normalized, frozen per bucket-key v2.
- **2.4 — Choice model v3**: funnel IGNORE|CLICK → BOUNCE|BROWSE → CART|ABANDON → BUY|ABANDON. Stage utility U_s = Σ_d W[s,d]·Appraisal[d] + γ·adstock − δ·asset_wearout (+ post-click: price_sensitivity · gap, losses ×2) (+ CART/BUY, P1: switching_inertia · (H_stim − H_rival_max)) (+ BUY, P1: −risk_aversion·(1 − trust confidence)) + base_s; act with prob σ((U_s − θ_s)/τ), τ = impulsivity. Stage-conditional weights make goal-gating emerge from one entry point: relevance weighs far more at CART/BUY than at CLICK, so a shopper with no active need can still click out of curiosity but rarely buys. Guards: hard price > budget_left blocks BUY; price > active_need.budget_cap dampens BUY prob ×0.25.
- **2.5 — Worldview update rules = consolidate()**: pure function per Law 14 and Appendix F. SAW → awareness + EXPECTS(brand, claimed concepts) at weight 0.2 — nothing else. PRICE_SEEN → reference-price smoothing (α = 0.3). CLICK/BROWSE/CART/BUY → preference evidence on stimulus-claimed concepts at 0.10/0.25/0.50/1.00; BUY additionally satisfies the matching NEEDS, adds trust evidence 1.5 (target 0.65), habit +1 (P1). EXPERIENCED → trust evidence 2.0 with target = satisfaction (P1: disconfirmation multiplier ×(1 + 0.5·max(0, expectation − sat)) — overpromising ads poison trust harder); preference evidence ±0.75·(2·sat−1) only on concepts the product actually HAS_ATTR — ads teach expectations, experience teaches truth. Emits EvidenceDeltas; the engine applies them.

**Checkpoints**
- [x] Golden perception files for the creatives + pages: schema-valid, every claim ∈ Concept enum, claimed_pct captured, rerun-stable. *(2026-08-17: fixtures/perception-cache/, gpt-4o-mini structured outputs, 5 calls = 5 unique stimuli; claimed_pct exact on all five; authored claims ⊆ perceived — the copy asserts more than the authored minimum (e.g. Apex's own "10% off"), recorded in tests/test_perception.py)*
- [x] Motif-level monotonicity: +preference_fit ↑relevance · +goal_fit ↑relevance more at BUY stage than CLICK stage · +brand_semantic_fatigue ↑brand_message_fatigue · +violation ↓expectation_alignment · no paths + no awareness + no belief ⇒ engagement ≈ 0. *(tests/test_appraise.py + F9-shape funnel test in test_decide.py)*
- [x] No-learning-from-SAW unit: a shopper bombarded with exposures shows Δw = 0 on every learned preference while awareness/EXPECTS rise. *(test_consolidate.py)*
- [x] Hierarchy monotonicity unit: equal counts of CLICK vs BROWSE vs CART vs BUY produce strictly ordered Δw. *(test_consolidate.py)*
- [x] Registry-completeness + import-graph tests green; decide() signature contains no traits. *(both Phase-2 registry tests live: signature + Law-12 source-scan — traits stay in contracts/types.py per the v3.2 note)*
- [x] Maya golden chain reproduced from evidence.py to the digit. *(unit: test_consolidate.py from events; real: tests/real/test_minds_real.py — events → consolidate() → applier → cause-stamped history on the live store)*
- [x] Formula choice model produces plausible base rates (CTR ~0.5–5%). *(bench/calibrate_choice.py: mean P(click|exposure) 0.79%, browse 0.47, cart|browse 0.13, buy|cart 0.20 — all inside the researched bands in /eval/market-research.md)*
- [x] Same seed → identical action sequence on the mock, twice. *(test_decide.py)*
- [ ] LLM appraisal (if reached): calls == distinct bucket keys; real variance across buckets; spend guard + cache hit-rate logging. *(P1 — not pulled; strict-P0 decision 2026-08-17)*

> *Phase-2 deltas vs the prose above (2026-08-17, agreed with Garvit): 13 authored segments instead of 6–8 (personas.json; population size + segment count are pure config, architecture validated at 50 segments / 5,000 shoppers); stimulus facts reach the mind via a bound ObjectiveView; perception owns stimulus-edge writes in engine runs (`ingest_catalog(include_stimuli=False)`); every new constant grounded in /eval/market-research.md. Full list in CONTRACT.md v3.2-draft, pending Atishay's ack.*

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

**Build items:** 3.1 the loop above + progress endpoint + results.json. 3.2 replay/branch wired end-to-end (paired arms from one log; worldview recomputed, never replayed from stored deltas). 3.3 commit `/fixtures/scripted-run-1/` — ScriptedMind v2 reacts to active_need scalars (BUY only when a need is live and price ≤ cap) and ~~ScriptedConsolidate produces a visible drift series~~ **amended 2026-08-17 (hybrid, CONTRACT v3.3)**: the fixture run digests events through the REAL `minds.consolidation.consolidate()` (ScriptedMind decides, formula consolidates) so the fixtures carry real belief/EXPECTS/ref-price series; ScriptedConsolidate stays as the C2 purity stand-in only. ScriptedMind v2 is stimulus-kind-aware per the v3.2 two-phase funnel.

**Checkpoints**
- [x] 200 shoppers × 14 sim-days with ScriptedMind ≤ ~1.5 min against real HydraDB. *(2026-08-17: **78.4s** on a fresh store — consolidation 42.6s, episodic 19.2s, retrieval+rest ~16s; per-phase wall-clocks in progress.json; results byte-identical to the committed fixtures. Operational finding, same rank as the 0.2/1.1 amendments: the write ceiling degrades with store size — ~220 stmts/s near-empty → ~82/s at 417MB of accumulated dev runs, restart-independent; wipe `infra/hydradb-data/store` (archive) to restore. Perf checkpoints are measured on a fresh store — that's what a judge's compose-up sees. Write-behind escalations remain pre-agreed but were not needed.)*
- [x] Paired branch run: two arms, identical populations, per-arm funnels. *(need_off branched from need_on's log at tick 6 into a fresh block, worldview recomputed; prefix byte-identical (offset-normalized), 56 vs 32 buys; per-arm funnels in fixtures/scripted-run-1/results.json)*
- [x] Kill at tick 7 → resume → totals consistent, including a fulfillment delivery pending across the kill. *(--crash-after consolidation:7 → resume: rollback-by-timestamp of the partial tick (episodic deletes + subjective/belief reopens), JSONL truncated to the TICK_COMPLETE marker, re-run — results.json AND event log byte-identical to an uninterrupted same-seed run; EXPERIENCED delivered across the kill; also unit-scale in tests/real/test_runner_real.py)*
- [x] Goal lifecycle visible in fixtures: NEEDS activated → satisfied-by-purchase with cause. *(Maya offset 42: scripted NEED_ACTIVATED t8 → BOUGHT t10 → NEED_SATISFIED{cause BOUGHT 3000001} → EXPERIENCED t12; closed NEEDS edge carries closed_cause_kind/id on the live graph)*
- [x] Fixtures committed and C3-valid (drift + goal stats populated). *(fixtures/scripted-run-1/: merged results.json validates (runner/results.py), 65 drift series, p_buy_need_on 0.59 vs need_off 0.0, ref-price trajectory shows all 3 promo cycles; drill-down worldview/trace/history samples for the Maya twin + busiest buyers)*

---

## Phase 4 — Garvit: Experiment Adapters v3 (uses: ~~MockHydraMem + 20-line mini-driver~~ **amended 2026-08-18**: Phase 3 shipped first, so Phase 4 rides the REAL runner via its programmatic API (`RunConfig`/`RunStore`/`SimRunner`/`replay.branch`) — the "mini-driver" is `python -m shopsim.experiments run` on mini-configs against the live store; MockHydraMem retained for unit tests only)

*Plain words: three experiment types = three stimulus feeds into one engine — and every adapter keeps the objective shelf honest: pricing writes real PRICED_AT supersessions, pages write SHOWS, and now scenario packs schedule the market itself: when needs surge and how good the products secretly are.*

**Build items:** 4.1 ad test (N creatives × audience × T days) — *shipped as one arm per creative on a shared seed (paired populations, no cap competition), per-row `audience_segments` targeting, per-creative funnels/CTR in results, and **image-ad upload** (`ingest-ads`: per-experiment catalog + frozen multimodal perception cache; text-creative cache hashes untouched)*. 4.2 pricing/promo: schedule → PRICED_AT supersessions + PRICE_SEEN; promo-addiction config = 3 discount cycles — *shipped over the Phase-3 promo hook; promo-off arms run a zeroed schedule (shared shelf), inline schedules are config_hash-covered*. 4.3 page A/B: variant descriptors → SHOWS; seeded 50/50; violation motif live — *shipped within-run via the `(seed,"page",offset,creative)` substream + per-variant bounce rates*. 4.4 tuning of the calibration layer only (choice weights/thresholds, smoothing α, fatigue thresholds) — evidence.py constants are frozen by hash, not tuned here — *shipped as the run_config `calibration` block (config_hash pins it); default retuning deferred, gated on bench/calibrate_choice.py*. 4.5 — scenario packs: need-wave config ("marathon season": a scheduled arrival burst in one category — the demo lever); latent-quality/overpromise table (P1: claims ≫ latent quality for one brand); social on/off (P1) — *shipped as `fixtures/scenarios/` overlays (+ `extra_waves`/`wave_scale`); P1 packs are refusing stubs*. All conventions in CONTRACT.md v3.4-draft, pending Atishay's ack.

**Checkpoints**
- [x] ~~Mini-driver runs all three experiment types on the mock~~ **amended 2026-08-18**: the experiments CLI runs all three types against the real store. *(tests/real/test_experiments_real.py: ad/pricing/page_ab through the orchestrator + the CLI subprocess end-to-end; unit suite covers the adapters on mocks)*
- [x] Violation arm bounces measurably more than the consistent arm (mini-run). *(within-run 50/50 on creative 2000003: identical exposure stream, only the landing page differs; bounce_rate(4000002) > bounce_rate(4000001), bounce_delta > 0 in comparison.json — test_page_ab_violation_bounce)*
- [x] Promo mini-run shows downward reference-price drift across cycles. *(promo_on arm: mean reference price falls cycle 1 → 3 and ends below list; promo_off shelf flat at 39.00 — test_pricing_promo_mini. Also surfaced+fixed a latent repeat-purchase cart bug that crashed cycle-2 resumed carts, v3.4-draft item 8)*
- [x] Objective layer stays truthful: PRICED_AT history reconstructs the schedule exactly, and NEEDS history reconstructs the configured wave exactly. *(as-of reads over PRICED_AT history reproduce round(39·(1−pct),2) at every tick; the graph's NEEDS set equals the pure goal_step recomputation for wave_on AND wave_off, arrivals outside the window identical across arms — test_pricing_promo_mini + test_needs_wave_reconstruction)*

---

## Phase 5 — Garvit: Dashboard & Recommendations v3 (uses: ~~C3 fixtures + MockHydraMem~~ **amended 2026-08-19**: built against the REAL stack from the start — the live runner API (CONTRACT v3.5-draft endpoint set), real HydraMem reads, real experiment launches; fixtures/mocks are unit-test scaffolding only. **Restructured the same day** to the SwarmAds-style shell: a numbered sidebar (01 Setup · 02 Studio · 03 Market · 04 Shoppers · 05 Learnings) + pipeline stepper replacing the two-link topbar; the Market page cut from 22 simultaneous panels to one KPI row + the allocation-river hero (the rest relocated into a collapsed drawer, nothing deleted); a **shared ad market** where uploaded ads compete for one population with daily CTR-driven reallocation (v3.6-draft); **money KPIs** (revenue simulated, spend from a researched CPM in `eval/market-research.md` §5); and an **N-arm discount ladder** answering "which discount depth does the population actually reward". **Extended 2026-08-20 as Phase 5.8** — the advertiser became real (`fixtures/nisolo/`, claims perceived off the brand's own creatives), the ads became visible end-to-end, the launch race was fixed and the ladder gained an always-on control. All conventions in CONTRACT.md **v3.7-draft**, pending Atishay's ack.)

*Plain words: the owner's cockpit — and the crown jewel: click one shopper and watch a person form. Their beliefs with confidence bars and receipts, their tastes as a timeline of cause-stamped changes, the need that made today different from last week, and the exact graph paths that explain the decision.*

**Build items:** 5.1 run launcher (experiment type, uploads, audience sliders, scenario pack, seeds) — *shipped as `/studio`: a brand/catalog picker over the server-side allowlist (`GET /catalogs`), real ad cards, image upload → ingest → **poll `/ads-manifest` → launch with the ingested catalog** (the wiring gap that silently ran the stock brand), four spec types, and a live ETA as you edit days/shoppers*. 5.2 results views: funnels per arm, segment heatmap, CTR-by-day, promo chart, fatigue-split chart (asset vs brand-message vs concept P1), preference-drift chart, goal-conversion split (P(buy | need) vs P(buy | none)), LTV/repeat toggle (P1) — *shipped as `/runs/[id]/results` (segment×stage heatmap, CTR-by-creative, motif stats, page A/B, preference drift, 6 small multiples) plus the live Market page; **fatigue is derived client-side from the event stream**, not from the C3 `fatigue_split` key (still Phase 6); LTV/repeat remains P1*. 5.3 shopper drill-down, four panels: diary timeline · worldview (belief cards: value + confidence bar + "from 2 visits, 1 purchase" provenance; expectations) · preference timeline (supersession chain with cause chips: "CLICK ad X · +0.05") · goals & experience (active-needs chip with countdown; experience feed) — plus the motif-path why-trace; social ring (P1) — *shipped as `components/Inspector.tsx` over the v3.5-draft shopper endpoints, incl. **decision replay** through the pure `/decision-preview` (real appraisal + `stage_probabilities`, with a need-off counterfactual) and preference version rails*. 5.4 recommendations: Grade 1 mined rules over MetricsReport, now incl. motif/goal findings ("conversions with an active need present converted 6×"; "brand-message fatigue onset at 4 exposures — rotate concepts"); Grade 2 interviews (P1: prompt = persona + that shopper's DecisionContext; answers may cite only retrieved facts) — *shipped as `web/lib/recommendations.ts`: up to 6 rule-based cards, each carrying the cited numbers it fired on; Grade 2 remains P1*.

**Checkpoints**
- [x] ~~Entire UI drivable on fixtures with the engine stubbed.~~ **amended 2026-08-19**: the UI is drivable against the live engine API — index, studio, market, results and experiment pages all read real endpoints; `npm run build` clean.
- [x] The story shopper renders coherently across all four panels; motifs render as paths. *(Verified 2026-08-18 on the demo brand — Maya #0042: decision replay P(buy) 0.345 vs 0.152 need-removed, motif paths, abstention on a null belief. **Not yet re-verified against the Nisolo catalog.**)*
- [ ] Preference timeline shows the golden chain with cause chips. *(Rails + cause chips render; the golden chain itself is a demo-brand fixture and has not been re-pinned on Nisolo.)*
- [ ] 5 interview answers spot-checked: zero facts outside that shopper's context (P1).
- [x] ≥ 3 sensible Grade-1 recommendations from fixture metrics. *(`web/lib/recommendations.ts` mines 6 rules — need-wave timing, creative rotation, promo addiction, budget shift, landing-page alignment, drift — each rendered with the numbers that triggered it. How many fire is run-dependent.)*

**Phase-5.8 — the real brand (2026-08-19, later)**
- [x] **The ads are visible.** `/config` reduced every creative to `{id: name}` and no endpoint served ad copy, so the UI's ceiling was a name and a colour chip — text ads literally rendered as a grey "TEXT AD" box. New `CreativeCard` surface + `AdCard`/`AdRoster`: image, headline, body, perceived-claim chips, offer and price, on the market page, Studio, the CTR multiples and the river legend.
- [x] **The brand is real.** `fixtures/nisolo/` — Nisolo's own five campaign creatives, real products at real prices ($109–295), perceived once by the multimodal eye and frozen. The "Up to 40% Off" creative's discount is **read off the image**, never authored; a test fails if that stops being true. `fixtures/demo-brand/` is byte-untouched.
- [x] **Premium recalibration.** Budgets ×2.2 and `budget_cap_by_category` from the observed price bands, or the absolute-dollar gates in `choice.py` block nearly every purchase; arrival rates re-keyed onto the categories Nisolo sells. Cited in `eval/market-research.md` §6. *(Verified: a 60×6 smoke run buys at $109/$150/$250.)*
- [x] **The launch no longer looks broken.** The registry publishes a run before `prepare()` writes its manifest; `waitForFirstRun` matched on label alone and `loadStatic` awaited the manifest unguarded, so a healthy run rendered `manifest.json not found` with no recovery but a reload. Now: new-run detection, a non-fatal manifest with a boot poller, an additive `"preparing"` status naming the phase, and an ETA countdown fed by `GET /engine/pace` that rolls forward +2:00 rather than stalling at zero.
- [x] **The ladder answers the question.** Pick 1–3 ads, pick depths; a **0% control always runs**, the discounted products are derived from the ads you picked (previously hardcoded to one unrelated product), and the verdict reports each depth against the control, per ad. *(Verified on a real 3-arm run: full price won at $777 vs $733/$690 — the same six shoppers bought at every depth, so the discount was pure margin loss plus $37 of reference-price erosion.)*
- [x] **Engine pace is the schedule.** Measured: the same 200×60 shape ran 18.5 s/tick on a fresh store and 112 s/tick on a loaded one, consolidation 60–80% of every tick. The store-reset ritual is in `infra/README.md`; Studio defaults dropped to 150×24 so a run finishes while you watch it.
- [ ] Demo capture on a freshly reset store.

**Phase-5 restructure additions (2026-08-19)**
- [x] Uploaded ads actually reach the simulation — Studio ingests, polls `/ads-manifest`, and launches with the manifest's catalog + perception cache + creative ids. *(Before: `buildSpec()` emitted none of those, so uploads were perceived and then silently ignored while the stock demo catalog ran.)*
- [x] Shared ad market + adaptive allocation, deterministic and resume-identical. *(tests/test_allocation.py; the exposure substream, draw order and cap checks are untouched — only reach thresholds move.)*
- [x] Purchase revenue in results (`revenue {total, by_creative}`), live via `/results-live`; ad spend stays a labeled dashboard assumption, never engine truth.
- [x] Pricing discount ladder (`discount_levels`) → one arm per depth + a revenue verdict with a reference-price-erosion warning.
- [ ] End-to-end demo capture on a wiped store (5 ads × 60 days, then the ladder).

---

## Phase 5.9 — Garvit: The Social Memory Graph (the `04 Graph` exhibit) — **added 2026-08-20**

PLAN §0.1 row 6 calls multi-hop social influence "the strongest *vector store can't* exhibit", and after Phase 6 pulled the P1 layer forward it was still invisible: a `motif_stats` row and a `social_lift` number. Meanwhile the sidebar's `04 Shoppers` was dead — it linked to `/market/<id>#shoppers`, an anchor that exists nowhere, so it landed on Market with Market highlighted. Both are fixed by the same thing: `04 Shoppers` becomes **`04 Graph`**, a force-directed drawing of three mutually-trusting shoppers and their real HydraDB neighbourhoods, in one connected graph.

- **5.9.1 — the read surface.** `hydramem/memgraph.py` (read plans + a pure assembler) and two facade methods, `HydraMem.find_social_triads()` / `.get_memory_graph()`. No new Cypher: `all_edges`, `holds_history`, `node_props`, and `adj_batch` for triad discovery — the one legal batch-read shape, until now called only by `bench/probe11.py`. Exposed as `GET /runs/{id}/memory-graph` and `GET /social-runs`. Conventions in CONTRACT.md **v3.9-draft**, pending Atishay's ack.
- **5.9.2 — the engine picks the exhibit.** A triple is only worth drawing if it can SHOW the mechanism, so candidates are ranked by whether a member both bought and lived with something — the `TRUSTS_PERSON -> BOUGHT -> EXPERIENCED` chain `social_proof` walks. On `r044-social-smoke-golden` that lands deterministically on offsets 0/1/2 — Asha, Leo and Maya — where Leo bought the EcoStride Runner on day 1 and rated it 0.8589 on day 2, and Maya trusts him at 0.7976.
- **5.9.3 — the client owns time.** The payload is topology plus every edge's version history and a `time` discipline, so the day scrub is a pure filter over `t`/`valid_to`, not a refetch — the same as-of rule `ObjectiveCache.build` and `Inspector.tsx` already use. A worldview visibly grows across days, and superseded belief versions retire with their whole provenance fan.
- **5.9.4 — the canvas.** `web/components/MemoryGraph.tsx`, adapted from AlexVanK's force-directed pen: the same simulation, the same elliptical-arc edges, the same drag-to-pin and dblclick-to-unpin, the same radius/saturation-by-connectivity. The pen's `link`/`linkish` pair carries our meaning — solid where HydraDB really stores the relationship, dashed where the engine derives it. Palette moved only far enough to sit with the terminal (stripe and pin take `--gold`, the dashed link and the explain highlight take `--accent`), and hue splits three ways because a worldview has parts a board-game graph does not: cyan world, green people, gold mind.
- **5.9.5 — the run.** `fixtures/run-configs/social-graph-demo.json`. `population.social` had to reach the experiment spec first (additive, emitted only when asked for, so every pre-social spec still hashes identically). A first pass at the default CLICK threshold drew 819 exposures, 8 clicks and zero purchases — a truthful simulation and a useless exhibit — so the spec carries `stage_bases.CLICK 2`, the same threshold the shipped `market-20260819` run uses.

- **5.9.6 — frozen, and dark (2026-08-20).** Reading the store live was wrong for this view. Shopper worldviews exist only in HydraDB, and the store is archived and recreated routinely — three times on 2026-08-20 alone — so the exhibit blanked after every reset and reshaped itself run to run in between. `export-graph` now freezes one real run (`r049`, day 27: 69 nodes, 355 edges, 20 traces, a triple where all three friends bought and took delivery) into `fixtures/social-graph/`, `GET /memory-graph` serves it, and `/graph` shows it whatever simulation is loaded. `?run=<id>` keeps the live path. The traces ride along because Explain reads them and recomputing motifs in the browser would mean the dashboard inventing graph structure. Conventions in CONTRACT.md **v3.11-draft**.
- **5.9.7 — the palette followed the ground.** The hazard stripe is gone and the canvas takes `--page`, the aside `--surface`, both wearing the app's own `.panel` border. Node hues are untouched; the one forced change is the lightness ramp, which the pen runs DOWN with connectivity (`99 - w*7`) — correct on white, backwards on black, where it made the least-connected nodes the brightest things on screen. Inverted to `34 + w*7`: same hues, same saturation, same linear form, so "more edges, stronger hue" still holds, now measured against dark.

**Honest limits:** `get_trace` recomputes against the store as of the last consolidated tick, not the tick a decision was actually made on, and the Explain panel says so rather than implying a replay. Nothing per-decision is persisted (`observe_decision` keeps counts, not paths), so "explain this decision" is a live re-derivation — and in the frozen capture it is that re-derivation, taken once and committed. A frozen exhibit can go stale against a changed retrieval layer; `fixtures/social-graph/README.md` says so and names the one command that regenerates it.

---

## Phase 6 — Atishay: Analytics & MetricsReport v3 (uses: Phase-3 scripted runs · parallel to 4–5) — **amended 2026-08-20**: roughly two thirds of 6.1's *metric emission* already landed inside Phases 3–5, because the live dashboard needed those series before Phase 6 was scheduled. What remains is the genuinely statistical half (CIs, the belief distributions, the fatigue split) plus the 6.2 golden run. Ownership unchanged — this is a status note, not a handover. **Closed the same day** (Garvit, with Atishay's phases untouched): the statistical half shipped as `engine/shopsim/analytics/`, the placeholders became authoritative and the UI now reads them, the 6.2 golden is committed at `fixtures/golden-run/`, and the P1 social layer was pulled forward as an opt-in, byte-neutral-when-off addition. Conventions in CONTRACT.md **v3.8-draft**, pending Atishay's ack.

**Build items:** 6.1 funnels per arm × segment with bootstrap CIs; CTR-by-day; drop-off localization; reference-price trajectories; fatigue split (asset wearout vs brand-message vs concept P1); preference-drift curves (learned w over time per concept × segment); goal stats (conversion split, time-to-satisfaction); belief metrics (confidence distribution, drift, provenance coverage = % of subjective versions carrying a cause); violation counts + bounce delta; motif prevalence by outcome; repeat-purchase/LTV per arm (P1); social lift (P1). Emit MetricsReport per C3. 6.2 tiny golden run (5 shoppers, 3 ticks, one full evidence chain) with hand-checked numbers asserted in tests.

*Shipped 2026-08-20 as `engine/shopsim/analytics/` — three files, each with one job:*
`metrics.py` **pure** (numpy only, no DB, no clock: every arithmetic claim in the report is unit-testable without a store) · `report.py` the finalize pass + the post-hoc rebuild (the only code here that touches HydraDB or a run directory) · `__main__.py` the CLI. `runner/results.py` keeps the accumulator; the import direction is one-way (`results.py → analytics.metrics`, `analytics.report → results.py`), which is why the package `__init__` stays import-free.

*The split that shapes everything else:* a Phase-6 key is either **accumulator-resident** — computed from state the tick loop already keeps, therefore live through `/results-live` and exact across a resume (`fatigue_split`, `belief_drift`, `violations.bounce_delta`, `repeat_ltv_by_arm`, `social_lift`) — or **finalize-only**, because it needs the segment map or a graph read (`ci`, `belief_confidence_dist`, `provenance_coverage`). `results(manifest)` without the new optional `extras` emits the finalize-only keys as the same typed-empty placeholders Phase 3 shipped, so the live path is byte-identical to Phase 5. The one new per-tick cost is a per-offset count vector (`results.py::BY_SHOPPER_FIELDS`); the belief sweep is one read-only pass at the end of the run (~4 statements/shopper, fanned out — reads are ~0.3 ms, it is writes that are serialized at ~200/s).

**Status as of 2026-08-20 — what `results.json` actually emits today**

*Already populated* (shipped early, in the phase noted; verified against
`runs/r033-nisolo-smoke-market/results.json`):

| 6.1 item | key | landed in |
|---|---|---|
| funnels per arm × segment | `funnel` | Phase 3 |
| CTR-by-day | `ctr_by_day` | Phase 3 |
| CTR per creative per day | `ctr_by_creative_by_day` | Phase 4.1a |
| drop-off localization | `funnel_by_creative`, `funnel_by_page` (+`bounce_rate`) | Phase 4.1a |
| reference-price trajectories | `reference_price_trajectory` | Phase 3 / 4.2 |
| preference-drift curves | `preference_drift` | Phase 3 |
| goal stats (split + time-to-satisfaction) | `goal_stats` | Phase 3 |
| motif prevalence by outcome | `motif_stats` | Phase 3 |
| violation counts | `violations.count` | Phase 3 |

*Beyond the original C3 list* (added because the dashboard needed them):
**`revenue {total, by_creative}`** (v3.6-draft — purchase money is simulated
truth; ad spend deliberately stays a labelled dashboard assumption);
**`belief_avg`** trust sweep, carried through `results_state` →
`/results-live.live_extras` and *not* emitted into the C3 skeleton so the
Phase-6 `belief_*` keys stay free (v3.5-draft); and **cross-arm analytics in
`comparison.json`** — the ad_test per-creative table, and the pricing ladder's
per-rung `creatives[]` + `vs_control` + `control_level`/`best_vs_control`
(v3.7-draft).

*Closed 2026-08-20 — the real Phase 6 work (CONTRACT v3.8-draft, new package `engine/shopsim/analytics/`):*
- [x] `ci` — bootstrap confidence intervals on the funnels, **clustered on shoppers** (a person's events are one correlated story, so the offset is the independent unit — the accumulator now keeps a per-offset count vector for exactly this). 2,000 percentile replicates seeded from `(seed, "ci", scope, metric)`; keys are `<metric>` per arm and `<metric>:<segment>` per segment. A ratio with an empty denominator gets no interval rather than a fabricated one.
- [x] `fatigue_split` — three PARALLEL channels measured at decision time from the context the mind actually saw: `asset` (`choice.asset_wearout`, the same number the utility subtracted), `brand_msg` (the `brand_semantic_fatigue` motif), `concept` (`concept_saturation`, retrieved but behaviourally inert at P0 — said so, not hidden). Per tick: mean level plus the CTR of high- vs low-fatigue decisions, which answers F12 directly. **The UI now reads the field**: the fatigue panel plots the engine channels and falls back to the client derivation, visibly labelled, only for runs recorded before this; `detectors.ts` gained a measured rule that replaces the CTR-decay heuristic wherever a channel exists.
- [x] `belief_confidence_dist`, `belief_drift`, `provenance_coverage` — the belief metrics. Drift and its new confidence twin come free from the v3.5 sweep's existing `live_holds` read; the distribution and coverage come from one read-only end-of-run sweep (~4 statements/shopper, parallel). `provenance_coverage` is a summary dict, not a bare float, and states its own scope (PREFERS over full version history, beliefs over live versions). Its `cause_kinds` histogram is **F7 as a metric**: on the golden it reads `{BOUGHT 1, BROWSED 25, EXPERIENCED 3}` — SAW never appears.
- [x] `violations.bounce_delta` — the per-run counterpart: pooled B−A over the run's own seeded `page_ids` splits, in declared order. Cross-arm deltas stay in `comparison.json`.
- [x] repeat-purchase / LTV per arm (P1) — realized revenue per buyer over the simulated window, no projection. **Social lift (P1) with the layer built**: `population.social` draws a seeded Watts-Strogatz small world (degree ≈ 4, weights U(0.4, 0.9), substream `(seed,"social",population)`) and writes `TRUSTS_PERSON`; `AppraisalParams.w_social` (default 0.0) feeds the `social_proof` motif's valence into credibility per registry row 20. **Opt-in and byte-neutral when off** — absent config ⇒ zero social statements, and the Phase-6 golden re-runs unchanged, which is the proof. `social_lift` carries `causal: false` when w_social is 0, because a gap measured through an inert channel is correlation.
- [x] **6.2 golden run** — `fixtures/golden-run/`: 5 shoppers × 3 ticks on the demo brand, ScriptedMind deciding and the real `consolidate()` digesting, one full evidence chain inside three ticks (SAW → CLICKED → VISITED/PRICE_SEEN/BROWSED → CARTED → BOUGHT → NEED_SATISFIED → EXPERIENCED). `tests/test_golden_run.py` checks the committed artifacts with **no database** — re-deriving the funnel from `events.jsonl` and recomputing every pure metric from the snapshot — and `tests/real/test_golden_run_real.py` re-runs it on the live store for the same report back.

**Checkpoints**
- [x] MetricsReport validates against C3.v3; drift + goal + confidence metrics populated. *(2026-08-20: every C3 key carries a value on `fixtures/golden-run/results.json` — `belief_confidence_dist` (10 bins/aspect), `belief_drift` (value + confidence series), `provenance_coverage` (1.0), `ci`, `fatigue_split`, `bounce_delta`, `repeat_ltv_by_arm`; `social_lift` is `null` on a social-free run by design and real on a social one. `validate_results` gained row-shape checks for each and still accepts every pre-Phase-6 file, including the frozen `fixtures/scripted-run-1/results.json`.)*
- [x] Golden-run numbers — including the evidence blend — match hand computation exactly. *(The blend stays pinned by `test_evidence.py`/`test_consolidate.py`/`test_golden_chain_real.py`; the whole-run report is now pinned too — 19 DB-free assertions in `tests/test_golden_run.py`, each carrying the arithmetic that produces it, plus 4 live-stack assertions. Same-seed determinism re-verified across two run blocks: byte-identical under the run_index normalization.)*
- [x] One command from run directory → full report. *(`python -m shopsim.analytics report --run <id|dir> [--config CFG] [--write] [--no-graph] [--json]`. Verified on a fresh run and on `runs/r033-nisolo-smoke-market`, where it degrades honestly — it names the blocks a pre-Phase-6 snapshot cannot support instead of inventing them. `--no-graph` exists so a demo capture never waits on the store; without `--write` the command is strictly read-only.)*

**Suite at Phase-6 close (2026-08-20):** `uv run pytest -q` **337 passed, 41 skipped** (was 290/34 at Phase-5 close — +47 from `test_metrics.py`, `test_golden_run.py`, `test_social.py` and the extensions to `test_runner_results.py`/`test_appraise.py`); `SHOPSIM_HYDRAMEM=real uv run pytest tests/real -q` **39 passed** in 44 min. That wall-clock is the loaded-store effect the Phase-3 amendment and `infra/README.md` already record, not a Phase-6 cost. `cd web && npm run build` clean.

*One pre-existing failure found and fixed on the way (not Phase 6):* `tests/real/test_minds_real.py::test_perception_writer_round_trip` assumed the store held a single catalog. `LISTS` hangs off ONE global catalog anchor, so `ObjectiveCache` enumerates every catalog ever ingested — since Phase 5.8 that includes Nisolo (2000101+) — and the test raised `KeyError` indexing the demo-brand perception cache with a Nisolo creative id. Had it got past that it would have **deleted Nisolo's `CLAIMS`/`OFFERS` edges** and restored only the demo brand's. It now skips creatives it has no perception for. Nothing in Phase 6 writes catalog or stimulus edges; this broke the moment a second brand touched the store on 2026-08-19.

*Operational finding worth carrying forward (pinned, not fixed — `evidence.py` is frozen by hash, Law 13):* `blend()` starts a concept the shopper has never held at `(w=0, E=0)`, so the **first** behavioral event on it sets `w = PREF_TARGET = 1.0` outright — with no prior evidence, the observation is all the evidence there is. Shoppers who held a prior (E0 = 2) blend normally. This is why a preference-drift series can read a flat `1.0`, and it predates Phase 6 (visible in `fixtures/scripted-run-1` and every Phase-5 run). `tests/test_golden_run.py::test_first_learned_version_of_an_unheld_concept_saturates` pins it deliberately, so a future cold-start rule change fails loudly rather than silently reshaping every drift chart.

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

## Phase 7 — Atishay: Calibration & Evals (post-S1) — **analytic + audit tiers closed 2026-08-20; scenario tier OPEN** (Garvit, Atishay's phases untouched)

*Plain words: proof it isn't a toy — the laws of advertising hold, the numbers sit in realistic ranges, and behavior changes for the right reasons, verifiable down to which event caused which belief.*

**What shipped, and the one finding worth carrying forward.** F1–F12 are implemented across three tiers (`engine/shopsim/eval/`): **analytic** (pure mind arithmetic, no database, any number of seeds — F1, F2, F3, F6, F8, F10, the rank-agreement study and the whole calibration fit), **scenario** (real runs through the ordinary `SimRunner`/`replay.branch` path — F4, F5, F7b, F9, F11, F12) and **audit** (F7a, an assertion over the `provenance_coverage` Phase 6 already computes). F13–F15 stay cut, per the P1 list. `make eval` reproduces everything; `make eval-fast` skips the real runs and finishes in seconds.

**What is NOT done, stated plainly:** the scenario tier has never completed a pass. F4, F5, F7b, F9, F11 and F12 have code, specs and thresholds but no measured numbers — the first run got through F5 and was interrupted mid-F9, and `cmd_scenarios` only writes `scenarios.json` after its whole loop, so nothing was kept. **F9 is the Maya law, i.e. the demo claim as a test, and it is currently unproven.** Running the tier is ~45 min on a freshly archived store and 4+ hours on a loaded one; run it one scenario at a time (`shopsim.eval scenarios --only F9`), since each invocation merges into the results file.

The finding: **what looked like a badly calibrated choice model was mostly two retrieval constants and a degenerate cold start.** The committed runs disagreed by 40× on CTR (`r027` 0.67%, `r039` 28%) and both read a 63–67% bounce rate against a researched 45–55%, which invited a "pick a CLICK threshold between 2.0 and 6.0" fix. Adding an opt-in decision trace (`--trace-decisions`) and replaying real contexts offline showed the actual causes: (1) `recency_half_life_s` was one constant doing two jobs, so a seeded `PREFERS` prior — a standing disposition — decayed at ad speed and had lost 98% of its weight by day 18, starving `relevance`; (2) `expectation_violation` had no strength floor, so `EXPECTS` accumulated from *any* of a brand's creatives fired against *every* landing page, penalising 85% of page visits by −0.64 utility; (3) the applier cold-started an unheld concept at `(w=0, E=0)`, which makes `blend()` degenerate, so one CLICK set the weight to 1.0 outright and every affected drift chart read a flat line. With those fixed, **exactly one mind constant had to move** (`stage_bases.BUY` 3.2 → 2.85) and all five funnel metrics land in band. Details, sources and the before/after: `eval/calibration.md`; conventions in CONTRACT.md **v3.10-draft**, pending Atishay's ack.

*Two limits stated rather than buried:* offline replay is first-order (it cannot model the loop where more clicks teach more preferences), which is why every fitted profile is verified on a real re-run and the predicted-vs-realised gap is reported; and 7.3's oracle reads the same population priors the simulator does, making it a construct-validity check, not external validation.

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
- [x] `make eval` reproduces every number and plot from scratch (`make eval-fast` for the database-free tiers, which includes calibration — replaying a trace needs no database). One data prerequisite, now explicit: the calibration tier replays a *traced* reference run and `/runs/` is gitignored, so `make eval-reference` produces one and `make eval` invokes it when missing.
- [ ] **All P0 face-validity laws hold. Eight of nine measured do; F9 does not.** Passing: F1, F2, F3, F5, F6, F7a, F8, F10. **F9 — the Maya law, the demo claim as a test — is RED on its first real measurement**: the ordering holds (BUY uplift 1.095× > CTR uplift 1.032×) and the within-run contrast reads 1.789×, but the cross-arm floors are missed on 21 vs 23 purchases, with `divergence_tick: 4` of 14 leaving 29% of the twin as shared history. Diagnosis and the honest options are in `eval/INDEX.md`; the threshold is not being lowered. Still unmeasured: F4, F7b, F11, and F12's rotation arm. `make eval` exits non-zero while any never-drop law is red or unmeasured. Each law has a test proving it can go RED — a suite whose assertions cannot fail is decoration (`tests/test_eval_laws.py`).
- [x] Calibration + rank-agreement + abstention artifacts committed to /eval.

*Also worth recording:* charts are hand-written deterministic SVG rather than a plotting library, because "reproduces every plot from scratch" and a library whose PNG output varies with version, font stack and platform are not compatible. They also diff cleanly in git, so a calibration change shows as a chart change in review.

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
- [ ] **Store reset before the capture** (`infra/README.md`). Measured 2026-08-19: the *same* 200×60 shape ran 18.5 s/tick on a fresh store and 112 s/tick on a loaded one — consolidation is 60–80% of every tick and slows as the graph grows. A flagship run started on a full store is hours, not minutes. This is the single likeliest way to lose the demo window.

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
