/** Mirrors of the engine API payloads (CONTRACT v3.5-draft, runner/api.py). */

export interface RegistryRow {
  run_id: string;
  run_index: number;
  label: string;
  arm: string;
  kind: string;
  seed: number;
  config_hash: string;
  dir: string;
  status: "created" | "running" | "complete" | string;
}

export interface Progress {
  /** "preparing" is written during prepare(), before manifest.json exists */
  phase?: string;
  population_size?: number;
  run_id: string;
  arm: string;
  label: string;
  status: "running" | "complete" | string;
  tick: number;
  ticks: number;
  phase_s: Record<string, number>;
  total_wall_s: number;
  updated_at: number;
}

export interface Manifest {
  seed: number;
  run_index: number;
  label: string;
  arm: string;
  t0: number;
  tick_seconds: number;
  ticks: number;
  config_hash: string;
  [k: string]: unknown;
}

/** One events.jsonl record. Funnel events carry subject/cause_creative/price;
 * NEED_* carry strength/urgency/budget_cap; TICK_COMPLETE carries tick. */
export interface EventRecord {
  type: string;
  shopper_id?: number;
  subject?: number;
  t?: number;
  run?: number;
  tick?: number; // TICK_COMPLETE
  cause_creative?: number;
  price?: number;
  sat?: number;
  strength?: number;
  urgency?: number;
  budget_cap?: number;
  deadline_t?: number;
  source?: string;
  n_events?: number;
}

export interface EventsPage {
  records: EventRecord[];
  next: number;
  eof: boolean;
}

export interface CtrDay {
  tick: number;
  exposures: number;
  clicks: number;
  ctr: number | null;
}

/** The C3 results.json shape — only the keys the dashboard consumes are
 * typed strictly; the rest ride along. */
export interface C3Results {
  run_manifest: Manifest;
  funnel: Record<string, Record<string, Record<string, number>>>; // arm -> segment -> type -> n
  ctr_by_day: CtrDay[];
  ctr_by_creative_by_day?: { creative: number; tick: number; exposures: number; clicks: number; ctr: number | null }[];
  funnel_by_creative?: Record<string, Record<string, number>>;
  funnel_by_page?: Record<string, Record<string, number> & { bounce_rate?: number | null }>;
  preference_drift: { concept: number; segment: number; series: (number | null)[] }[];
  reference_price_trajectory: {
    tick: number; current_price: number | null;
    mean_reference_price: number | null; n_holders: number;
  }[];
  goal_stats: { p_buy_need_on: number | null; p_buy_need_off: number | null; time_to_satisfaction: number[] };
  motif_stats: Record<string, { prevalence_by_outcome: Record<string, number>; mean_strength: number | null }>;
  violations: { count: number; bounce_delta: number | null };
  /** Phase 6 / CONTRACT v3.8-draft. Optional throughout: every run recorded
   * before Phase 6 carries these as empty placeholders, and the UI falls back
   * rather than pretending the engine said something it did not. */
  fatigue_split?: Record<string, FatigueRow[]>;
  belief_drift?: BeliefDriftRow[];
  belief_confidence_dist?: { aspect: string; bin_lo: number; bin_hi: number; count: number }[];
  provenance_coverage?: ProvenanceCoverage | null;
  /** metric -> [lo, hi], 95% bootstrap over shoppers. Keys are "<metric>" for
   * the arm and "<metric>:<segment>" per segment. */
  ci?: Record<string, [number, number]>;
  repeat_ltv_by_arm?: RepeatLtvRow[];
  social_lift?: SocialLift | null;
  [k: string]: unknown;
}

/** One tick of one fatigue channel. `mean` is the population mean channel
 * level among that tick's creative decisions; high/low split those decisions
 * at the engine's own threshold, so the CTR columns are a direct measurement
 * rather than a time-series inference. */
export interface FatigueRow {
  tick: number;
  n: number;
  mean: number;
  high_n: number;
  high_ctr: number | null;
  low_n: number;
  low_ctr: number | null;
}

export interface BeliefDriftRow {
  aspect: string;
  about: number;
  segment: number | "all";
  series: (number | null)[];
  confidence_series: (number | null)[];
}

export interface ProvenanceCoverage {
  coverage: number | null;
  prefers: {
    versions: number; learned_versions: number; with_cause: number;
    coverage: number | null; cause_kinds: Record<string, number>;
  };
  beliefs: { versions: number; with_provenance: number; coverage: number | null };
  belief_scope: string;
}

export interface RepeatLtvRow {
  arm: string; buyers: number; buys: number; repeat_buyers: number;
  repeat_rate: number | null; buys_per_buyer: number | null;
  revenue_total: number; revenue_per_buyer: number | null;
}

export interface SocialLift {
  p_buy_social_on: number | null; p_buy_social_off: number | null;
  lift: number | null; decisions_on: number; decisions_off: number;
  w_social: number; causal: boolean; note: string;
}

export interface ResultsLive {
  tick: number | null;
  status: string;
  results: C3Results;
  live_extras: { belief_avg: Record<string, (number | null)[]> };
}

export interface ScheduleRow {
  creative_id: number;
  start_tick: number;
  end_tick: number;
  reach_prob: number;
  page_id: number | null;
  audience_segments: number[] | null;
  page_ids: number[] | null;
}

export interface RunConfigPayload {
  raw: Record<string, unknown>;
  effective: {
    creative_names: Record<string, string>;
    label: string; arm: string; seed: number; ticks: number; t0: number;
    tick_seconds: number; population_size: number;
    schedule: ScheduleRow[];
    promos_enabled: boolean;
    promo_windows: Record<string, [number, number, number][]>; // product -> [start, end, pct]
    goal_overrides: Record<string, unknown>;
    goal_waves: { category_id: number; start_tick: number; end_tick: number; rate_multiplier: number }[];
    arms: string[];
  };
}

export interface Population {
  segments: { segment_id: number; name: string; share: number }[];
  shoppers: { offset: number; shopper_id: number; segment_id: number }[];
}

export interface BeliefPayload {
  belief_id: number; about_id: number; aspect: string;
  value: number; evidence: number; confidence: number;
  provenance: { kind: string; target: number; count: number; first_t: number; last_t: number; weight: number }[];
  provenance_sentence: string;
}

export interface Worldview {
  shopper_id: number;
  beliefs: BeliefPayload[];
  preferences: { concept: number; w: number; evidence: number; source: string; cause_kind: string; cause_id: number; t: number }[];
  active_needs: { category: number; strength: number; budget_cap: number; deadline_t: number; source: string }[];
  habits: { brand: number; evidence: number }[];
  expects: { concept: number; about: number; strength: number }[];
}

export interface PrefVersion {
  w: number; evidence: number; source: string; cause_kind: string;
  cause_id: number; t: number; valid_to: number;
}

export interface MotifPayload {
  type: string;
  path: (number | string)[];
  strength?: number; urgency?: number; evidence?: number; recency?: number;
  brand?: number; valence?: number;
  [k: string]: unknown;
}

export interface TracePayload {
  shopper_id: number; stimulus_id: number;
  scalars: Record<string, unknown>;
  motifs: MotifPayload[];
}

export interface DecisionPreview {
  tick: number;
  stimulus: { id: number; kind: "creative" | "page"; page_id: number | null };
  scalars: Record<string, unknown>;
  motifs: MotifPayload[];
  appraisal: Record<string, number | null>;
  probabilities: Record<string, number>;
  counterfactual_need_off: null | {
    label: string;
    appraisal: Record<string, number | null>;
    probabilities: Record<string, number>;
  };
}

export interface ExperimentSummary {
  name: string; spec_type: string | null; arms: string[];
  has_comparison: boolean;
  runs: { run_id: string; arm: string; status: string }[];
}

export interface ExperimentDetail {
  name: string;
  run_config: Record<string, unknown>;
  comparison: Record<string, unknown> | null;
  arm_runs: { run_id: string; arm: string; status: string; progress: Partial<Progress> }[];
  orchestrator: { pid: number; alive: boolean } | null;
  log_tail: string;
}

/** GET /experiments/{name}/ads-manifest (v3.6-draft) — what Studio polls
 * after an upload to learn the ingested creative ids and the repo-relative
 * catalog/perception-cache paths a launch spec must carry. */
export interface EnginePace {
  samples: { run_id: string; ticks: number; population: number;
             total_wall_s: number; per_tick_s: number }[];
  per_tick_s_per_100_shoppers: number | null;
}

export interface AdsManifest {
  experiment: string;
  catalog: string;
  perception_cache: string;
  ingested: { creative_id: number; name: string; image: string }[];
  perception_calls: number;
  all_creative_ids: number[];
}

export interface AdsManifestPayload {
  status: "ready" | "ingesting" | "none";
  manifest: AdsManifest | null;
  catalog?: string;
  perception_cache?: string;
  log_tail?: string;
}

/** GET /runs/{id}/creatives and /catalogs/{key}/creatives (v3.7-draft) — the
 * ad as an ad. `headline`/`body` have ZERO runtime effect: they are perception
 * input and cache-key material, shown so a human can read the ad. What the
 * simulation reacts to is `perceived.claims` and the claimed discount. */
export interface CreativeClaim { concept_id?: number; concept: string; strength: number }

export interface CreativeOffer {
  product_id: number;
  name: string;
  list_price: number;
  category_id: number;
  claimed_pct: number;
  page_ids: number[];
}

export interface CreativeCard {
  creative_id: number;
  brand_id: number;
  brand_name: string;
  name: string;
  headline: string;
  body: string;
  note?: string | null;
  image_url: string | null;
  authored_claims: CreativeClaim[];
  perceived: {
    claims: CreativeClaim[];
    claimed_discounts: { product_id: number; claimed_pct: number }[];
    prompt_version: string;
    model: string;
    from_image: boolean;
  } | null;
  offers: CreativeOffer[];
}

export interface CatalogSummary {
  key: string;
  label: string;
  catalog: string;
  perception_cache: string;
  personas: string | null;
  goal_config: string | null;
  n_creatives: number;
}

/** ---- v3.9-draft: the memory graph (GET /runs/{id}/memory-graph) --------
 * The payload is the graph's TOPOLOGY plus each edge's full version history;
 * the day scrub is a client-side filter over `time` + t/valid_to, so moving
 * through days costs no round-trips. See engine/shopsim/hydramem/memgraph.py. */

export type GraphNodeKind =
  | "shopper" | "concept" | "category" | "brand" | "product"
  | "creative" | "page" | "belief" | "aspect" | "anchor";

/** How an edge answers "were you there on day N". `static` = always (the
 * objective closure and TRUSTS_PERSON); `event` = t <= as_of; `bitemporal` =
 * t <= as_of < valid_to. */
export type GraphEdgeTime = "static" | "event" | "bitemporal";

export type GraphEdgeFamily =
  | "objective" | "episodic" | "subjective" | "preference" | "social";

export interface GraphNode {
  id: number;
  kind: GraphNodeKind;
  label: string | null;
  sub: string | null;
  props: Record<string, unknown>;
}

export interface GraphEdgeVersion {
  t?: number; valid_to?: number;
  [k: string]: unknown;
}

export interface GraphEdge {
  id: string;
  source: number;
  target: number;
  rel: string;
  family: GraphEdgeFamily;
  time: GraphEdgeTime;
  derived: boolean;
  owner: number;
  count: number;
  versions: GraphEdgeVersion[];
  reciprocal?: boolean;
}

export interface TriadCandidate {
  shopper_ids: number[];
  offsets: number[];
  why: string;
}

export interface MemoryGraph {
  run_id: string;
  run_index: number;
  t0: number;
  tick_seconds: number;
  ticks: number;
  head_tick: number;
  social_enabled: boolean;
  focus: number[];
  candidates: TriadCandidate[];
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface SocialRunRow {
  run_id: string;
  label: string | null;
  arm: string | null;
  status: string | null;
  run_index: number;
  ticks: number;
  t0: number;
  tick_seconds: number;
}


/** GET /engine/busy — the launch guard's verdict, structured.
 * `stale: true` means the row is marked running but no writer process exists,
 * which is the only case where forcing past the guard is safe. */
export interface EngineBusyBlocker {
  kind: "experiment" | "run";
  reason: string;
  stale: boolean;
  pid: number | null;
  run_id?: string;
  label?: string | null;
  arm?: string | null;
  experiment?: string;
  command?: string;
  tick?: number | null;
  ticks?: number | null;
  quiet_s?: number;
}

export interface EngineBusy {
  busy: boolean;
  blocker: EngineBusyBlocker | null;
}
