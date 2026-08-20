/** Typed fetchers — everything goes through the same-origin proxy /api/sim. */

import type {
  AdsManifestPayload, CatalogSummary, CreativeCard, DecisionPreview,
  EngineBusy, EnginePace, EventsPage, ExperimentDetail,
  ExperimentSummary, Manifest, MemoryGraph, Population, PrefVersion, Progress,
  RegistryRow, ResultsLive, RunConfigPayload, SocialRunRow, TracePayload,
  Worldview,
} from "./types";

const BASE = "/api/sim";

/** Image URLs. The card's own `image_url` is server-built and relative, so
 * these only prefix the proxy base. Text-only ads have image_url === null. */
export const proxied = (path: string) => `${BASE}${path}`;

/** Image URL for an ingested creative (404s for text-only ads). */
export const adImageUrl = (name: string, creativeId: number) =>
  `${BASE}/experiments/${encodeURIComponent(name)}/ads/${creativeId}/image`;

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, detail?.detail ?? res.statusText);
  }
  return res.json();
}

export class ApiError extends Error {
  constructor(public status: number, detail: string) {
    super(detail);
  }
}

export const api = {
  runs: () => get<RegistryRow[]>("/runs"),
  progress: (id: string) => get<Progress>(`/runs/${id}/progress`),
  manifest: (id: string) => get<Manifest>(`/runs/${id}/manifest`),
  results: (id: string) => get<Record<string, unknown>>(`/runs/${id}/results`),
  resultsLive: (id: string) => get<ResultsLive>(`/runs/${id}/results-live`),
  events: (id: string, after = 0, limit = 5000) =>
    get<EventsPage>(`/runs/${id}/events?after=${after}&limit=${limit}`),
  config: (id: string) => get<RunConfigPayload>(`/runs/${id}/config`),
  population: (id: string) => get<Population>(`/runs/${id}/population`),
  worldview: (id: string, offset: number) =>
    get<Worldview>(`/runs/${id}/shoppers/${offset}/worldview`),
  preferenceHistory: (id: string, offset: number, concept: number) =>
    get<PrefVersion[]>(`/runs/${id}/shoppers/${offset}/preference-history/${concept}`),
  beliefHistory: (id: string, offset: number) =>
    get<Record<string, unknown>[]>(`/runs/${id}/shoppers/${offset}/belief-history`),
  trace: (id: string, offset: number, stimulus: number) =>
    get<TracePayload>(`/runs/${id}/shoppers/${offset}/trace/${stimulus}`),
  decisionPreview: (id: string, offset: number, stimulus: number) =>
    get<DecisionPreview>(`/runs/${id}/shoppers/${offset}/decision-preview/${stimulus}`),
  /** Runs that carry a TRUSTS_PERSON layer — the ones 04 Graph can draw. */
  socialRuns: () => get<SocialRunRow[]>("/social-runs"),
  /** Omit `focus` to let the engine pick the best mutually-trusting triple. */
  memoryGraph: (id: string, focus?: number[]) =>
    get<MemoryGraph>(`/runs/${id}/memory-graph${
      focus && focus.length ? `?focus=${focus.join(",")}` : ""}`),
  experiments: () => get<ExperimentSummary[]>("/experiments"),
  /** Is the engine free, and if not, what is holding it? Answers the question
   * a bare 409 could not: WHICH run, started by WHICH process, how far along,
   * and whether it is genuinely live or a crashed leftover. */
  busy: () => get<EngineBusy>("/engine/busy"),
  experiment: (name: string) => get<ExperimentDetail>(`/experiments/${encodeURIComponent(name)}`),
  creatives: (runId: string) =>
    get<{ catalog: string; perception_cache: string; creatives: CreativeCard[] }>(
      `/runs/${runId}/creatives`),
  catalogs: () => get<CatalogSummary[]>("/catalogs"),
  pace: () => get<EnginePace>("/engine/pace"),
  catalogCreatives: (key: string) =>
    get<{ key: string; label: string; catalog: string; creatives: CreativeCard[] }>(
      `/catalogs/${encodeURIComponent(key)}/creatives`),
  adsManifest: (name: string) =>
    get<AdsManifestPayload>(`/experiments/${encodeURIComponent(name)}/ads-manifest`),
  launch: async (spec: Record<string, unknown>, force = false) => {
    const res = await fetch(`${BASE}/experiments${force ? "?force=1" : ""}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(spec),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(res.status, body?.detail ?? res.statusText);
    return body as { experiment: string; pid: number; status: string };
  },
  ingestAds: async (payload: { name: string; spec: Record<string, unknown>; images: { filename: string; b64: string }[] }) => {
    const res = await fetch(`${BASE}/experiments/ingest-ads`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(res.status, body?.detail ?? res.statusText);
    return body as { experiment: string; pid: number; status: string };
  },
};
