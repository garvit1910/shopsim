/** ARCHITECTURE OVERVIEW — the mind's per-decision pipeline, for the landing page.
 *
 * Static markup, no props, no data: a server component that ships as HTML. Every
 * label here is a real identifier in this repo, cited beside the block that uses
 * it — if one of these names changes in the engine, this diagram is wrong and
 * should be changed with it.
 *
 * Drawn in CSS boxes rather than SVG. Connectors are a dashed rail plus a glyph
 * arrowhead, which is the codebase's existing vocabulary for an arrow (there is
 * no <marker> anywhere in the repo, but ▸ ▾ ▼ ● → ↓ are used throughout). */

/** hydramem/schema.py:35-104 — the edge types, grouped by the six state
 * families of PLAN.md:58-67. Names are exact relationship types. */
const FAMILIES: [string, string, string, string[]][] = [
  ["01", "Objective world", "what is true",
    ["SOLD_BY", "IN_CATEGORY", "HAS_ATTR", "PRICED_AT", "CLAIMS", "PROMOTES", "OFFERS", "SHOWS", "PAGE_FOR"]],
  ["02", "Episodic", "what happened",
    ["SAW", "CLICKED", "VISITED", "BROWSED", "BOUNCED", "CARTED", "ABANDONED", "BOUGHT", "EXPERIENCED"]],
  ["03", "Subjective worldview", "what they believe",
    ["HOLDS", "ABOUT", "THAT", "DERIVED_FROM", "EXPECTS", "REFERENCE_PRICE"]],
  ["04", "Preferences & habits", "what they like / do", ["PREFERS", "HABIT"]],
  ["05", "Goal state", "what they need now", ["NEEDS"]],
  ["06", "Social context", "who they trust", ["TRUSTS_PERSON"]],
];

/** CONTRACT.md:138-158 — three pure stages. Motif types CONTRACT.md:313-324,
 * appraisal dims minds/calibration.py:21-27, thresholds :113-116. */
const MIND: [string, string, string[]][] = [
  ["Retrieve", "DecisionContext — 13 scalars + typed motif paths", [
    "preference_fit", "goal_fit", "brand_semantic_fatigue",
    "expectation_violation", "concept_saturation", "social_proof",
  ]],
  ["Appraise", "five dimensions, 0..1 — formula, not a prompt", [
    "relevance", "credibility", "brand_message_fatigue",
    "offer_attractiveness", "expectation_alignment",
  ]],
  ["Decide", "four gates · P = σ((U − θ) / τ)", [
    "CLICK θ 6.00", "BROWSE θ 2.30", "CART θ 3.70", "BUY θ 2.85",
  ]],
];

function Conn({ label }: { label: string }) {
  return (
    <div className="lconn">
      <i aria-hidden="true" />
      <span>{label}</span>
      <b aria-hidden="true">▼</b>
    </div>
  );
}

export default function ArchitectureDiagram() {
  return (
    <div className="larch">
      {/* perception/perceive.py:1-11 — one strict structured-output call per
          unique creative, cached forever, never deciding actions. */}
      <section className="lreg">
        <p className="lregh">Perception — once per run, then frozen</p>
        <div className="lflow">
          <div className="lnode"><b>creative</b><span>name · headline · body · offered products</span></div>
          <em aria-hidden="true">▶</em>
          <div className="lnode"><b>gpt-4o-mini</b><span>temperature 0 · strict JSON schema</span></div>
          <em aria-hidden="true">▶</em>
          <div className="lnode"><b>Concept enum</b><span>unknown → OTHER</span></div>
          <em aria-hidden="true">▶</em>
          <div className="lnode"><b>perception-cache/</b><span>keyed by stimulus hash</span></div>
        </div>
        <div className="lchips">
          <span className="lct">emits</span>
          {["CLAIMS{strength}", "OFFERS{claimed_pct}", "PROMOTES", "SHOWS"].map((c) => (
            <span key={c} className="lchip">{c}</span>
          ))}
        </div>
        <p className="lregn">The LLM never touches a decision. Engine runs are offline —
          perception must come from the cache.</p>
      </section>

      <Conn label="frozen ObjectiveView" />

      {/* The emphasized region: this is the part that is HydraDB. */}
      <section className="lreg core">
        <p className="lregh">HydraMem — six state families, one graph</p>
        <div className="lfam">
          {FAMILIES.map(([n, name, gloss, edges]) => (
            <div key={n} className="lfamrow">
              <span className="n">{n}</span>
              <div className="t"><b>{name}</b><span>{gloss}</span></div>
              <div className="e">
                {edges.map((e) => <span key={e} className="lchip">{e}</span>)}
              </div>
            </div>
          ))}
        </div>
        <p className="lregn">Live edges carry <code>valid_to = 9007199254740991</code>.
          Supersede, never overwrite — history is never erased.</p>
      </section>

      <Conn label="get_decision_contexts() · Route B · 12–13 single-hop reads · ~0.3 ms each · 9 ms per context warm" />

      <section className="lreg">
        <p className="lregh">The mind — three pure stages, never writes</p>
        <div className="lmind">
          {MIND.map(([name, sub, chips], i) => (
            <div key={name} className="lstage">
              {i > 0 && <em className="lsarrow" aria-hidden="true">▶</em>}
              <div className="lnode tall">
                <b>{name}</b><span>{sub}</span>
                <div className="lchips">
                  {chips.map((c) => <span key={c} className="lchip">{c}</span>)}
                </div>
              </div>
            </div>
          ))}
        </div>
        <p className="lregn">Minds return <code>EvidenceDelta</code>s. They never write to
          the graph — one admitted writer owns every mutation.</p>
      </section>

      <Conn label="Action — IGNORE | CLICK → BOUNCE | BROWSE → CART | ABANDON → BUY" />

      <section className="lreg">
        <p className="lregh">Experience loop — what the shopper learns</p>
        <div className="lflow">
          <div className="lnode"><b>BOUGHT</b><span>episodic edge, priced</span></div>
          <em aria-hidden="true">▶</em>
          <div className="lnode"><b>EXPERIENCED{"{sat}"}</b><span>after the fulfillment lag</span></div>
          <em aria-hidden="true">▶</em>
          <div className="lnode"><b>consolidate()</b><span>pure — same inputs, same deltas</span></div>
          <em aria-hidden="true">▶</em>
          <div className="lnode"><b>DeltaApplier</b><span>the one admitted writer</span></div>
        </div>
        {/* contracts/evidence.py:93-103 — the one formula. */}
        <pre className="lmath">{`w′ = (E·w + wt·target) / (E + wt)      E′ = min(E + wt, 8)
confidence = E / (E + 0.7)             SET old valid_to = now; CREATE new`}</pre>
        <p className="lregn">Preference versions carry the event that caused them, so every
          change of taste keeps a receipt.</p>
      </section>

      <div className="lloop"><b aria-hidden="true">▲</b><span>feeds back into HydraMem</span></div>
    </div>
  );
}
