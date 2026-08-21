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
import type { AdsManifest, CatalogSummary, CreativeCard, EngineBusyBlocker, EnginePace } from "@/lib/types";
import { estimate, fmtDuration } from "@/lib/eta";
import Stepper, { pipelineSteps } from "@/components/Stepper";
import AdCard from "@/components/AdCard";
import CreativeViewer from "@/components/CreativeViewer";
import { selectMindAd } from "@/lib/mind";

type Mode = "market" | "ladder" | "page_ab" | "scenario";

const PAGES = [4000001, 4000002];
const PACKS = ["marathon-season", "overpromise", "social-on-off"];
const today = () => new Date().toISOString().slice(0, 10).replace(/-/g, "");
/** minute-resolution so two launches on the same day never share a label */
const stamp = () => `${today()}-${new Date().toTimeString().slice(0, 5).replace(":", "")}`;

/** The accelerated CLICK threshold, from the committed `eval/profiles/demo.json`.
 *
 * SOLVED, not picked: `shopsim.eval.calibrate.solve_stage_base` bisects for a
 * stated 5% target CTR against the reference run's own decision trace, and the
 * resulting acceleration is published per metric in
 * `eval/results/calibration.json` -> demo_profile.multiples: 5.6x on CTR and
 * exactly 1.0x on bounce, cart|browse, buy|cart and visit-to-purchase. Only the
 * click gate moves; everything below it is still the certified funnel.
 *
 * This replaces a hand-picked 2.0 that Phase 7 explicitly retired. A 300x60
 * Nisolo run on 2.0 measured 35% CTR (~28x the researched band) and a blended
 * ROAS of 104x against a real-world 1.5-4x — the exact failure the demo profile
 * exists to prevent. `tests/test_studio_profile.py` pins this against the
 * committed profile so the two cannot drift apart again. */
const DEMO_CLICK_BASE = 4.07;

/** min/max on a bare number input are validation HINTS — they do not clamp
 * typed input, and an emptied field yields Number("") === 0. That shipped
 * `ticks: 0, end_tick: -1` to the engine. Keep the last good value instead. */
const clamp = (raw: string, lo: number, hi: number, fallback: number): number => {
  const n = Number(raw);
  if (raw.trim() === "" || !Number.isFinite(n)) return fallback;
  return Math.min(hi, Math.max(lo, n));
};

export default function StudioPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("market");
  const [name, setName] = useState(() => `market-${stamp()}`);
  const [seed, setSeed] = useState(424);
  // PLAN's demo-capture shape (5 ads x 60 days). On a FRESH store 300x60 is
  // ~17 min; on a loaded one the same run is hours, which is why the ETA below
  // reads /engine/pace rather than trusting a constant. Archive the store
  // before a long run (infra/README.md).
  const [ticks, setTicks] = useState(60);
  const [population, setPopulation] = useState(300);
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
  /** index into `cards` of the creative open in the lightbox */
  const [viewing, setViewing] = useState<number | null>(null);
  const [phase, setPhase] = useState<"idle" | "ingesting" | "launching">("idle");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  /** structured detail behind a 409 — what is holding the engine */
  const [blocker, setBlocker] = useState<EngineBusyBlocker | null>(null);
  /** measured per-tick pace on THIS machine, so the pre-launch ETA tracks the
   * store's current state instead of a constant that goes stale in a day */
  const [pace, setPace] = useState<EnginePace | null>(null);
  const [note, setNote] = useState<string | null>(null);

  // a fresh t0 window per experiment (v3.4-draft item 5)
  const [t0] = useState(() => 1_700_000_000 + (Math.floor(Date.now() / 1000) % 100_000_000));

  useEffect(() => { setErr(null); }, [mode]);
  useEffect(() => { api.pace().then(setPace).catch(() => {}); }, []);

  /** What this run will cost, priced before you launch it rather than after. */
  const preEta = estimate({ pace, population, ticks, progress: null });

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
      setViewing(null);   // an index into the OLD catalog would point at the wrong ad
    }).catch(() => { if (alive) { setCards([]); setViewing(null); } });
    return () => { alive = false; };
  }, [catalogKey, mode]);

  const catalog = catalogs.find((c) => c.key === catalogKey);

  const maxPicks = mode === "ladder" ? 3 : 99;

  const toggle = (id: number) => {
    // picking an ad also makes it the Mind page's current stimulus
    if (!picked.includes(id)) selectMindAd(id);
    setPicked((p) => (p.includes(id)
      ? p.filter((x) => x !== id)
      : p.length >= maxPicks ? [...p.slice(1), id] : [...p, id]));
  };

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
        // The CLICK base is loosened to the value Phase 7 SOLVED for a stated
        // 5% target (DEMO_CLICK_BASE) rather than a number picked by hand.
        ...(accelerate ? { calibration: { stage_bases: { CLICK: DEMO_CLICK_BASE } } } : {}),
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
        ...(accelerate ? { calibration: { stage_bases: { CLICK: DEMO_CLICK_BASE } } } : {}),
      };
    }
    if (mode === "page_ab") {
      return { ...base, type: "page_ab", creative_id: abCreative, page_ids: PAGES, reach_prob: reach };
    }
    return { ...base, type: "scenario", scenario_packs: packs, exposure: { schedule: rows } };
  };

  const submit = async (force = false) => {
    setBusy(true); setErr(null); setNote(null); setBlocker(null);
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
      // A 409 means something else owns the engine. Ask WHAT, so the refusal
      // can name it — and so FORCE is only offered when the blocker is a
      // crashed leftover rather than a writer that is genuinely mid-run.
      if (ex instanceof ApiError && ex.status === 409) {
        setBlocker((await api.busy().catch(() => null))?.blocker ?? null);
      }
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
    // prepare() is population generation + graph seeding, ~12s per 100
    // shoppers (eta.ts) before the first tick exists — a 300-shopper run can
    // spend well over a minute there, and the old ~45s ceiling gave up and
    // never navigated. 4 minutes covers the shapes Studio can launch.
    for (let i = 0; i < 300; i++) {
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
                {cards.map((c, i) => (
                  <AdCard key={c.creative_id} card={c} compact
                    selected={picked.includes(c.creative_id)}
                    onClick={() => toggle(c.creative_id)}
                    onPreview={() => setViewing(i)} />
                ))}
              </div>
            </div>
          )}

          <div className="fieldgrid">
            <label className="field"><span>name</span>
              <input value={name} disabled={busy}
                onChange={(e) => setName(e.target.value.replace(/[^a-z0-9-]/gi, "-").toLowerCase())} /></label>
            <label className="field"><span>seed</span>
              <input type="number" value={seed}
                onChange={(e) => setSeed(clamp(e.target.value, 0, 2 ** 31 - 1, seed))} /></label>
            <label className="field"><span>days</span>
              <input type="number" min={2} max={90} value={ticks}
                onChange={(e) => setTicks(clamp(e.target.value, 2, 90, ticks))} /></label>
            <label className="field"><span>shoppers</span>
              <input type="number" min={10} max={5000} value={population}
                onChange={(e) => setPopulation(clamp(e.target.value, 10, 5000, population))} /></label>
            <label className="field"><span>total reach / day</span>
              <input type="number" step={0.05} min={0.05} max={1} value={reach}
                onChange={(e) => setReach(clamp(e.target.value, 0.05, 1, reach))} /></label>
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
                the market page shows CTR and ROAS at the calibrated gate — divided back by the
                published ~5.7× acceleration, raw rate printed beside them.</span>
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
            {!busy && (
              <span className="mono" style={{ fontSize: 12, color: "var(--ink-2)" }}>
                est. {fmtDuration(preEta.remainingS)} · {population} shoppers x {ticks} days
                {preEta.perTickS != null && ` · ~${preEta.perTickS.toFixed(0)}s/day`}
                {pace?.per_tick_s_per_100_shoppers == null && " (no local pace yet — fresh-store estimate)"}
              </span>
            )}
          </div>
          {preEta.remainingS != null && preEta.remainingS > 1800 && (
            <div className="warnbox" style={{ marginTop: 10 }}>
              This run is estimated at {fmtDuration(preEta.remainingS)}. Per-tick cost
              grows with the store — archive it first (infra/README.md) and the
              same shape typically runs several times faster.
            </div>
          )}

          {err && (
            <div className="errbox" style={{ marginTop: 12 }}>
              {err}
              {blocker && !blocker.stale && (
                <div style={{ marginTop: 8, fontSize: 12.5 }}>
                  Holding the engine: <b>{blocker.run_id ?? blocker.experiment}</b>
                  {blocker.tick != null && ` · tick ${blocker.tick}/${blocker.ticks}`}
                  {blocker.command && <> · started outside the dashboard by <code>{blocker.command}</code></>}
                  <div style={{ marginTop: 6, color: "var(--ink-2)" }}>
                    Launches are serialized because the run registry&apos;s
                    read-modify-write is not concurrent-safe. Forcing past a live
                    writer can corrupt it, so there is no override here — wait for
                    it to finish, or stop it.
                  </div>
                </div>
              )}
              {blocker?.stale && (
                <div style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 12.5, marginBottom: 6 }}>
                    <b>{blocker.run_id}</b> is marked running but no writer process
                    exists (last moved {blocker.quiet_s}s ago) — it looks crashed.
                  </div>
                  <button className="storybtn on" onClick={() => submit(true)} disabled={busy}>
                    FORCE LAUNCH (the blocking run appears dead)
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

      {viewing !== null && cards[viewing] && (
        <CreativeViewer cards={cards} index={viewing} onIndex={setViewing}
          onClose={() => setViewing(null)}
          selected={picked.includes(cards[viewing].creative_id)}
          onToggle={() => toggle(cards[viewing].creative_id)} />
      )}
    </>
  );
}
