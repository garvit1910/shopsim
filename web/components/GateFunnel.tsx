/** THE FUNNEL — four Bernoulli gates, each against its published research band.
 *
 * Static, no props, no data. Values are `calibration.after` from
 * eval/results/eval_report.json; bands and their citations are eval/README.md:28-34.
 * Failure semantics are exact, from minds/choice.py:143-151 — note that failing
 * CART does NOT abandon (there is no cart yet to abandon), and failing BUY keeps
 * a fresh cart but abandons a resumed one.
 *
 * Each row is normalised to its own scale: 0.89% and 45.97% cannot share an axis,
 * so the track runs 0 → band_max × 1.5 and the band is drawn as a region inside
 * it. That is the same two-layer "reference vs actual" idea as .scard .sbar. */

type Gate = {
  stage: string;
  theta: string | null;
  value: number;
  band: [number, number];
  exit: string;
  note: string;
};

const GATES: Gate[] = [
  { stage: "CLICK", theta: "6.00", value: 0.8865, band: [0.5, 2.0], exit: "IGNORE",
    note: "Meta retail CTR 1.59–1.71%, display 0.46%" },
  { stage: "BROWSE", theta: "2.30", value: 45.97, band: [45, 55], exit: "BOUNCE",
    note: "BROWSE = 1 − bounce, target 0.45–0.55" },
  { stage: "CART", theta: "3.70", value: 14.1803, band: [10, 20], exit: "BROWSE",
    note: "fashion add-to-cart 7.1–7.7% of sessions" },
  { stage: "BUY", theta: "2.85", value: 24.3249, band: [24, 28], exit: "CART, then ABANDON",
    note: "1 − cart abandonment (72–76%)" },
];

const END: Gate = {
  stage: "VISIT → PURCHASE", theta: null, value: 1.5857, band: [1.0, 3.0], exit: "",
  note: "apparel sitewide conversion 1–3%",
};

const pct = (v: number) => `${v.toFixed(v < 10 ? 2 : 1)}%`;

function Row({ g, end }: { g: Gate; end?: boolean }) {
  const scale = g.band[1] * 1.5;
  const w = (v: number) => `${Math.min(100, (100 * v) / scale).toFixed(2)}%`;
  const inBand = g.value >= g.band[0] && g.value <= g.band[1];
  return (
    <div className={`lgate${end ? " end" : ""}`}>
      <div className="lgname">
        <b>{g.stage}</b>
        {g.theta && <span>θ {g.theta}</span>}
      </div>
      <div className="lgtrack">
        {/* what the model actually does, then the published band over it — the
            band has to stay readable where the two overlap, which is the point */}
        <i className="lgval" style={{ width: w(g.value) }} />
        <i className="lgband" style={{ left: w(g.band[0]), width: w(g.band[1] - g.band[0]) }} />
        <i className="lgtick" style={{ left: w(g.value) }} />
      </div>
      <div className="lgnum">
        <b className="num">{pct(g.value)}</b>
        <span className="num">{g.band[0]}–{g.band[1]}%{inBand ? " ✓" : " ✗"}</span>
      </div>
      <div className="lgexit">{g.exit ? <>fails to <b>{g.exit}</b></> : <span>end to end</span>}</div>
    </div>
  );
}

export default function GateFunnel() {
  return (
    <div className="lfunnel">
      <div className="lgchain">
        {["exposure", "CLICK", "BROWSE", "CART", "BUY"].map((s, i) => (
          <span key={s} className={i === 0 ? "s first" : "s"}>
            {i > 0 && <em aria-hidden="true">▶</em>}
            <b>{s}</b>
            {i > 0 && <u>{pct(GATES[i - 1].value)}</u>}
          </span>
        ))}
      </div>
      <div className="lgkey">
        <span><i className="k band" />published band</span>
        <span><i className="k val" />simulated</span>
      </div>
      {GATES.map((g) => <Row key={g.stage} g={g} />)}
      <Row g={END} end />
      <p className="lgfoot">
        Model-implied over the reference run — 300 shoppers × 20 ticks, 7,878 creative
        and 89 page decisions. Realised rates differ; the gap is reported in <code>/eval</code>{" "}
        rather than assumed away.
      </p>
    </div>
  );
}
