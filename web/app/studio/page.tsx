"use client";

/** 02 STUDIO — put your ads into the market.
 *
 * The flow that used to be broken: uploads were ingested (perceived once,
 * multimodally, then frozen) but the launched spec never referenced the
 * catalog those new creatives landed in, so the run quietly simulated the
 * stock demo ads instead. Studio now polls /ads-manifest until ingestion
 * finishes and launches with the manifest's own catalog, perception_cache
 * and creative ids — the ads you uploaded are the ads that run. */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { AdsManifest, CatalogSummary, CreativeCard } from "@/lib/types";
import Stepper, { pipelineSteps } from "@/components/Stepper";
import AdCard from "@/components/AdCard";

type Mode = "market" | "ladder" | "page_ab" | "scenario";

const PAGES = [4000001, 4000002];
const PACKS = ["marathon-season", "overpromise", "social-on-off"];
const today = () => new Date().toISOString().slice(0, 10).replace(/-/g, "");
/** minute-resolution so two launches on the same day never share a label */
const stamp = () => `${today()}-${new Date().toTimeString().slice(0, 5).replace(":", "")}`;

export default function StudioPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("market");
  const [name, setName] = useState(() => `market-${stamp()}`);
  const [seed, setSeed] = useState(424);
  // sized so a run finishes while you watch it: on a fresh store this is
  // minutes, not the ~2 hours a 200x60 run costs on a loaded one
  const [ticks, setTicks] = useState(24);
  const [population, setPopulation] = useState(150);
  const [reach, setReach] = useState(0.6);
  const [allocate, setAllocate] = useState(true);
  const [accelerate, setAccelerate] = useState(true);
  const [picked, setPicked] = useState<number[]>([2000001, 2000003, 2000004]);
  const [abCreative, setAbCreative] = useState(2000003);
  const [depths, setDepths] = useState<number[]>([20, 40]);
  const [promoFrom, setPromoFrom] = useState(3);
  const [promoTo, setPromoTo] = useState(10);
  const [packs, setPacks] = useState<string[]>(["marathon-season"]);
  const [images, setImages] = useState<{ filename: string; b64: string }[]>([]);
  const [manifest, setManifest] = useState<AdsManifest | null>(null);
  const [catalogs, setCatalogs] = useState<CatalogSummary[]>([]);
  const [catalogKey, setCatalogKey] = useState("nisolo");
  const [cards, setCards] = useState<CreativeCard[]>([]);
  const [phase, setPhase] = useState<"idle" | "ingesting" | "launching">("idle");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  // a fresh t0 window per experiment (v3.4-draft item 5)
  const [t0] = useState(() => 1_700_000_000 + (Math.floor(Date.now() / 1000) % 100_000_000));

  useEffect(() => { setErr(null); }, [mode]);

  useEffect(() => {
    api.catalogs().then((rows) => {
      setCatalogs(rows);
      if (!rows.some((r) => r.key === catalogKey) && rows.length) setCatalogKey(rows[0].key);
    }).catch(() => {});
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let alive = true;
    api.catalogCreatives(catalogKey).then((r) => {
      if (!alive) return;
      setCards(r.creatives);
      setPicked(r.creatives.map((c) => c.creative_id).slice(0, mode === "ladder" ? 2 : 5));
    }).catch(() => alive && setCards([]));
    return () => { alive = false; };
  }, [catalogKey, mode]);

  const catalog = catalogs.find((c) => c.key === catalogKey);

  const maxPicks = mode === "ladder" ? 3 : 99;

  const toggle = (id: number) =>
    setPicked((p) => (p.includes(id)
      ? p.filter((x) => x !== id)
      : p.length >= maxPicks ? [...p.slice(1), id] : [...p, id]));

  const onFiles = async (files: FileList | null) => {
    if (!files) return;
    const out: { filename: string; b64: string }[] = [];
    for (const f of Array.from(files)) {
      const buf = new Uint8Array(await f.arrayBuffer());
      let bin = "";
      buf.forEach((b) => { bin += String.fromCharCode(b); });
      out.push({ filename: f.name, b64: btoa(bin) });
    }
    setImages((prev) => [...prev, ...out]);
  };

  /** Upload → perceive → manifest. Returns the manifest the launch needs. */
  const ingest = async (): Promise<AdsManifest> => {
    setPhase("ingesting");
    setNote(`perceiving ${images.length} ad${images.length > 1 ? "s" : ""} — one multimodal pass, then frozen…`);
    await api.ingestAds({
      name,
      spec: {
        name,
        ads: images.map((im) => ({
          image: im.filename, brand_id: 6001,
          offer_product_ids: [3000001], name: im.filename.replace(/\.[^.]+$/, ""),
        })),
      },
      images,
    });
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      const body = await api.adsManifest(name).catch(() => null);
      if (body?.status === "ready" && body.manifest) {
        setManifest(body.manifest);
        setImages([]);
        setPicked(body.manifest.ingested.map((a) => a.creative_id));
        setNote(`ingested ${body.manifest.ingested.length} ad(s) · ${body.manifest.perception_calls} perception call(s)`);
        return body.manifest;
      }
      if (body?.status === "ingesting" && body.log_tail) {
        setNote(body.log_tail.trim().split("\n").at(-1) ?? "perceiving…");
      }
    }
    throw new Error("ingestion did not finish in time — check the engine log");
  };

  const buildSpec = (m: AdsManifest | null): Record<string, unknown> => {
    const base: Record<string, unknown> = {
      name, seed, ticks, t0,
      population: {
        size: population,
        ...(catalog?.personas ? { personas: catalog.personas } : {}),
      },
      // the catalog actually being previewed — without these the run silently
      // falls back to the stock demo brand, which was the old wiring bug
      ...(m
        ? { catalog: m.catalog, perception_cache: m.perception_cache }
        : catalog
          ? { catalog: catalog.catalog, perception_cache: catalog.perception_cache }
          : {}),
      ...(!m && catalog?.goal_config ? { goal_config: catalog.goal_config } : {}),
    };
    const rows = picked.map((id) => ({
      creative_id: id, start_tick: 0, end_tick: ticks - 1,
      // split the day's reach across the ads so the per-tick frequency cap
      // (2/shopper) never throttles the winner out of its own market
      reach_prob: Math.min(1, reach / Math.max(1, picked.length)),
    }));

    if (mode === "market") {
      return {
        ...base, type: "ad_test",
        creatives: rows.map(({ creative_id, reach_prob }) => ({ creative_id, reach_prob })),
        market: { shared: true, allocation: { enabled: allocate } },
        // ACCELERATED MARKET. At the researched calibration (P(CLICK|exposure)
        // 0.5-2%, market-research.md §1) a demo-scale population yields
        // single-digit clicks and no purchases, so the money tiles read $0.
        // Loosening the CLICK base buys a readable funnel at the cost of a
        // CTR far above the real band — so the dashboard computes the multiple
        // from the run's own numbers and prints it next to the tiles. Nothing
        // else is rescaled: prices, budgets and purchase amounts stay real.
        ...(accelerate ? { calibration: { stage_bases: { CLICK: 2.0 } } } : {}),
      };
    }
    if (mode === "ladder") {
      // The discounted products are the ones the SELECTED ads actually offer.
      // This used to be a hardcoded 3000001 regardless of the ads picked, so
      // the ladder could discount a product no chosen ad was even selling.
      const productIds = [...new Set(
        cards.filter((c) => picked.includes(c.creative_id))
             .flatMap((c) => c.offers.map((o) => o.product_id)))];
      const cycles = [{ cycle: 1, start_tick: promoFrom - 1, end_tick: promoTo - 1,
                        discount_pct: 0 }];  // engine overrides per arm
      return {
        ...base, type: "pricing",
        // 0% is ALWAYS sent: without a full-price control there is nothing to
        // compare a discount against
        discount_levels: [...new Set([0, ...depths.map((d) => d / 100)])].sort((a, b) => a - b),
        promo: { product_promos: productIds.map((pid) => ({ product_id: pid, cycles })) },
        exposure: { schedule: rows },
        ...(accelerate ? { calibration: { stage_bases: { CLICK: 2.0 } } } : {}),
      };
    }
    if (mode === "page_ab") {
      return { ...base, type: "page_ab", creative_id: abCreative, page_ids: PAGES, reach_prob: reach };
    }
    return { ...base, type: "scenario", scenario_packs: packs, exposure: { schedule: rows } };
  };

  const submit = async (force = false) => {
    setBusy(true); setErr(null); setNote(null);
    try {
      const m = images.length ? await ingest() : manifest;
      setPhase("launching");
      const before = new Set((await api.runs().catch(() => [])).map((r) => r.run_id));
      const res = await api.launch(buildSpec(m), force);
      setNote(`launched ${res.experiment} — waiting for the engine to claim a run…`);
      const runId = await waitForFirstRun(res.experiment, before);
      if (!runId) {
        const detail = await api.experiment(res.experiment).catch(() => null);
        throw new Error(detail?.log_tail?.trim().split("\n").slice(-3).join(" ")
          || "the engine did not register a run — check the orchestrator log");
      }
      router.push(`/market/${runId}`);
    } catch (ex) {
      setErr(ex instanceof ApiError ? `${ex.status}: ${ex.message}` : String(ex));
      setBusy(false);
      setPhase("idle");
    }
  };

  /** Wait for a genuinely NEW run row.
   *
   * Matching on label alone had two failure modes: it returned during
   * prepare() (before the run had a manifest, which is what produced the red
   * "manifest.json not found"), and on a same-day relaunch it matched a
   * PREVIOUS run with the same label and navigated to a stale, already
   * finished run. Snapshotting the ids first removes both. */
  const waitForFirstRun = async (label: string, before: Set<string>): Promise<string | null> => {
    for (let i = 0; i < 56; i++) {
      await new Promise((r) => setTimeout(r, 800));
      try {
        const runs = await api.runs();
        const row = runs.filter((r) => r.label === label && !before.has(r.run_id)).at(-1);
        if (row) return row.run_id;
      } catch { /* retry */ }
    }
    return null;
  };


  return (
    <>
      <Stepper steps={pipelineSteps({
        hasAds: images.length > 0 || Boolean(manifest),
        perceived: Boolean(manifest),
        launched: phase === "launching",
        runStatus: null,
      })} />
      <main className="wrap" style={{ maxWidth: 1000 }}>
        <div className="sechead">
          <h1>Studio</h1>
          <div className="secmeta">upload your ads · they compete in one simulated market</div>
        </div>

        <div className="panel" style={{ padding: 16 }}>
          <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
            {([["market", "AD MARKET"], ["ladder", "PRICE LADDER"],
               ["page_ab", "PAGE A/B"], ["scenario", "SCENARIO"]] as [Mode, string][]).map(([m, label]) => (
              <button key={m} className={`btn ${mode === m ? "primary" : ""}`} onClick={() => setMode(m)}>
                {label}
              </button>
            ))}
          </div>

          {mode === "market" && (
            <div style={{ marginBottom: 18 }}>
              <div className="ph" style={{ padding: "0 0 6px" }}>
                YOUR ADS · PERCEIVED ONCE BY THE MULTIMODAL EYE, THEN FROZEN
              </div>
              <input type="file" accept="image/png,image/jpeg,image/webp" multiple
                onChange={(e) => onFiles(e.target.files)} disabled={busy} />
              {images.length > 0 && (
                <div className="mono" style={{ fontSize: 11.5, marginTop: 8 }}>
                  staged: {images.map((im) => im.filename).join(" · ")}{" "}
                  <button style={{ color: "var(--bad)" }} onClick={() => setImages([])}>clear</button>
                </div>
              )}
              {manifest && (
                <div className="okbox" style={{ marginTop: 10, fontSize: 12.5 }}>
                  ingested into <code>{manifest.catalog}</code> — {manifest.ingested.length} new
                  creative(s), {manifest.perception_calls} perception call(s). These ids now run.
                </div>
              )}
            </div>
          )}

          {(mode === "market" || mode === "ladder" || mode === "scenario") && (
            <div style={{ marginBottom: 18 }}>
              <div className="ph" style={{ padding: "0 0 6px" }}>
                BRAND / CATALOG
                {catalog && <span className="phnote">{catalog.catalog}</span>}
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
                {catalogs.map((c) => (
                  <button key={c.key} className={`btn ${catalogKey === c.key ? "primary" : ""}`}
                    onClick={() => setCatalogKey(c.key)}>
                    {c.label} · {c.n_creatives}
                  </button>
                ))}
              </div>
              <div className="ph" style={{ padding: "0 0 6px" }}>
                {mode === "market"
                  ? `ADS IN THE MARKET · ${picked.length} SELECTED · ONE SHARED POPULATION`
                  : "ADS CARRYING THE FUNNEL"}
              </div>
              <div className="adgrid">
                {cards.map((c) => (
                  <AdCard key={c.creative_id} card={c} compact
                    selected={picked.includes(c.creative_id)}
                    onClick={() => toggle(c.creative_id)} />
                ))}
              </div>
            </div>
          )}

          <div className="fieldgrid">
            <label className="field"><span>name</span>
              <input value={name} disabled={busy}
                onChange={(e) => setName(e.target.value.replace(/[^a-z0-9-]/gi, "-").toLowerCase())} /></label>
            <label className="field"><span>seed</span>
              <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} /></label>
            <label className="field"><span>days</span>
              <input type="number" min={2} max={90} value={ticks}
                onChange={(e) => setTicks(Number(e.target.value))} /></label>
            <label className="field"><span>shoppers</span>
              <input type="number" min={10} max={5000} value={population}
                onChange={(e) => setPopulation(Number(e.target.value))} /></label>
            <label className="field"><span>total reach / day</span>
              <input type="number" step={0.05} min={0.05} max={1} value={reach}
                onChange={(e) => setReach(Number(e.target.value))} /></label>
          </div>

          {mode === "market" && (
            <label style={{ display: "flex", gap: 9, alignItems: "flex-start", marginTop: 16 }}>
              <input type="checkbox" checked={accelerate}
                onChange={(e) => setAccelerate(e.target.checked)} style={{ marginTop: 3 }} />
              <span style={{ fontSize: 13 }}>
                <b>Accelerated market</b> — raise click rates so a demo-sized population
                produces a readable funnel and real revenue.
                <span style={{ color: "var(--muted)" }}> Off = the researched 0.5–2% CTR band,
                where {population} shoppers over {ticks} days yield almost no purchases. Either way
                the market page prints the CTR multiple against the real-world band.</span>
              </span>
            </label>
          )}

          {mode === "market" && (
            <label style={{ display: "flex", gap: 9, alignItems: "flex-start", marginTop: 12 }}>
              <input type="checkbox" checked={allocate} onChange={(e) => setAllocate(e.target.checked)}
                style={{ marginTop: 3 }} />
              <span style={{ fontSize: 13 }}>
                <b>Adaptive allocation</b> — each day, reach shifts toward the ads earning clicks
                (trailing smoothed CTR, floored at 5% so nothing is ever switched off).
                <span style={{ color: "var(--muted)" }}> Off = every ad keeps its configured reach all {ticks} days.</span>
              </span>
            </label>
          )}

          {mode === "ladder" && (
            <div style={{ marginTop: 16 }}>
              <div className="ph" style={{ padding: "0 0 6px" }}>
                DISCOUNT DEPTHS · 0% CONTROL ALWAYS RUNS
              </div>
              <div className="depths">
                <span className="depth control" title="Always included: the same ads at full price, so every depth has something to be measured against.">
                  0% CONTROL
                </span>
                {[10, 20, 30, 40].map((d) => (
                  <button key={d} type="button"
                    className={`depth ${depths.includes(d) ? "on" : ""}`}
                    aria-pressed={depths.includes(d)}
                    onClick={() => setDepths((p) =>
                      p.includes(d) ? p.filter((x) => x !== d) : [...p, d].sort((a, b) => a - b))}>
                    {d}% off
                  </button>
                ))}
              </div>
              <div className="fieldgrid" style={{ marginTop: 12 }}>
                <label className="field"><span>discount runs from day</span>
                  <input type="number" min={1} max={ticks} value={promoFrom}
                    onChange={(e) => setPromoFrom(Number(e.target.value))} /></label>
                <label className="field"><span>…through day</span>
                  <input type="number" min={1} max={ticks} value={promoTo}
                    onChange={(e) => setPromoTo(Number(e.target.value))} /></label>
              </div>
              <div className="note" style={{ padding: "10px 0 0", fontSize: 12.5 }}>
                <b>{depths.length + 1} simulations</b> run back to back — one per depth plus the
                control — on the identical seeded population, discounting{" "}
                {[...new Set(cards.filter((c) => picked.includes(c.creative_id))
                    .flatMap((c) => c.offers.map((o) => o.name)))].join(", ") || "the selected ads' products"}.
                The verdict reports each depth against the control, per ad.
                {depths.length === 0 && (
                  <div style={{ color: "var(--gold)", marginTop: 6 }}>
                    Pick at least one depth — a control on its own has nothing to compare to.
                  </div>
                )}
              </div>
            </div>
          )}

          {mode === "page_ab" && (
            <div style={{ marginTop: 14 }}>
              <div className="ph" style={{ padding: "0 0 6px" }}>
                CREATIVE · CLICKS SPLIT 50/50 ACROSS PAGES {PAGES.join(" vs ")} (SEEDED)
              </div>
              <select value={abCreative} onChange={(e) => setAbCreative(Number(e.target.value))}>
                {cards.map((c) => <option key={c.creative_id} value={c.creative_id}>{c.name}</option>)}
              </select>
            </div>
          )}

          {mode === "scenario" && (
            <div style={{ marginTop: 14 }}>
              <div className="ph" style={{ padding: "0 0 6px" }}>SCENARIO PACKS · ON/OFF ARM PAIR IS THE EXHIBIT</div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {PACKS.map((p) => (
                  <button key={p} className={`btn ${packs.includes(p) ? "primary" : ""}`}
                    onClick={() => setPacks((prev) => prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p])}>
                    {p}{p !== "marathon-season" ? " (P1 stub)" : ""}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div style={{ marginTop: 20, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <button className="btn primary" disabled={busy || (mode === "ladder" && depths.length === 0)} onClick={() => submit()}>
              {phase === "ingesting" ? "PERCEIVING ADS…"
                : phase === "launching" ? "LAUNCHING…"
                : mode === "market" ? "RUN THE MARKET →" : "RUN SIMULATION →"}
            </button>
            {note && <span className="mono" style={{ fontSize: 12, color: "var(--good)" }}>{note}</span>}
          </div>

          {err && (
            <div className="errbox" style={{ marginTop: 12 }}>
              {err}
              {err.startsWith("409") && (
                <div style={{ marginTop: 8 }}>
                  <button className="storybtn on" onClick={() => submit(true)} disabled={busy}>
                    FORCE LAUNCH (override the serialization guard)
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="panel note" style={{ marginTop: 12 }}>
          {mode === "market"
            ? `All ${picked.length} ads run in ONE simulation against the same ${population} shoppers, sharing the frequency caps — so winning an impression means taking it from another ad. Watch the allocation river narrow.`
            : "Arms run sequentially (registry allocation is serialized — a second launch while one runs returns 409, verbatim above)."}
        </div>
      </main>
    </>
  );
}
