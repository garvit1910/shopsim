/** The front door. Deliberately a server component: everything here is static
 * markup and only the constellation hydrates. Shell bypasses this route, so
 * there is no sidebar, no topbar, and — the point of the exercise — not a
 * single request to the engine. The page has to open cold.
 *
 * Almost every string is lifted verbatim from the repo rather than written for
 * the occasion, cited beside the block that uses it. The one exception is
 * "5,000 stateful shoppers. 60 days.", which is DESIGN SCALE and not a run that
 * happened — the largest run on disk is 200 × 60 (infra/README.md:156-159).
 * That is why the numbers band is headed DESIGNED FOR. */

import Link from "next/link";
import ParticleField from "@/components/ParticleField";
import ArchitectureDiagram from "@/components/ArchitectureDiagram";
import GateFunnel from "@/components/GateFunnel";

/** The comparison. Left column is the failure mode this engine refuses
 * structurally; right column is the mechanism that refuses it. */
const COMPARE: [string, string][] = [
  ["A persona answers a prompt, then forgets it",
    "Six state families per shopper, retrieved per decision as scalars plus typed motif paths"],
  ["Ask twice, get the same answer twice",
    "Preferences supersede — every version carries the click or purchase that caused it"],
  ["Confidently familiar with a brand it has never seen",
    "No path, no belief, no knowledge: appraisal is gated and abstains"],
  ["State stitched across a vector store, a graph and Postgres",
    "One graph. Beliefs, prices, goals and exposures all bitemporal in the same store"],
];

/** README.md:95-99, verbatim. */
const BREAKS: [string, string][] = [
  ["Worldview-divergence queries", "belief versus truth, as of any tick"],
  ["Typed motif paths", "one evidence set per decision, not a similarity score"],
  ["Preference time-travel", "PREFERS supersession chains with cause receipts"],
  ["Goal-lifecycle joins", "need ↔ category ↔ product ↔ creative, three hops"],
  ["Belief provenance", "which event made them sure, and how sure"],
  ["Branch and replay", "one seed, two histories, compared"],
  ["Social influence paths", "who they trust, and what those people experienced"],
];

const PAPER = "https://arxiv.org/abs/2506.12078";

const NUMS: [string, string][] = [
  ["5,000", "stateful shoppers"],
  ["60", "days"],
  ["6", "state families each"],
  ["1", "graph"],
];

function Ticks() {
  return (
    <span className="lticks" aria-hidden="true">
      <i className="tl" /><i className="tr" /><i className="bl" /><i className="br" />
    </span>
  );
}

export default function LandingPage() {
  return (
    <main className="landing">
      {/* The field belongs to .ltop, not to the hero: it runs behind BOTH opening
          screens so scrolling from one to the next reads as one continuous canvas
          rather than two pages. Each screen still carries its own scrim and frame. */}
      <div className="ltop">
        <ParticleField />

      <section className="lhero">
        <div className="lscrim" aria-hidden="true" />
        <div className="lframe" aria-hidden="true">
          <i className="tl" /><i className="tr" /><i className="bl" /><i className="br" />
        </div>

        <div className="lherobody">
          <h1 className="lmark">ShopSim</h1>
          <p className="lsub">Shopper simulation for advertising</p>
          <p className="lbyline">
            5,000 stateful shoppers. 60 days. Every preference, every past ad,
            every belief. A probabilistic model that lives entirely in HydraDB.
          </p>
          <div className="lbtns">
            <Link className="lcta" href="/studio">enter simulation <b>&rarr;</b></Link>
            <a className="lcta ghost" href="#architecture">see the architecture</a>
          </div>
        </div>

        <div className="lstrip">
          <span>Stateful shoppers</span>
          <span>Probabilistic choice</span>
          <span>Every preference versioned</span>
          <span>Every ad ever seen retained</span>
          <span className="on">All in HydraDB</span>
          <span className="lscroll" aria-hidden="true">&darr;</span>
        </div>
      </section>

      <section className="lpaper">
        <div className="lscrim" aria-hidden="true" />
        <div className="lframe" aria-hidden="true">
          <i className="tl" /><i className="tr" /><i className="bl" /><i className="br" />
        </div>
        <div className="lpbody">
          <p className="lkick">research</p>
          <h2 className="lhead">State is the hard part.</h2>
          {/* The quoted phrase is verbatim from the abstract. This cites a result and
              then names a different problem — no claim of collaboration or lineage. */}
          <p className="lprose">
            Light Society scaled LLM agent societies past one billion agents by
            formalising social processes as{" "}
            <em>&ldquo;structured transitions of agent and environment states.&rdquo;</em>
          </p>
          <p className="lprose">
            What it does not address is where that state lives between transitions.
            ShopSim&rsquo;s answer is HydraDB: six state families per shopper, every
            belief versioned, every preference stamped with the event that caused it,
            queryable as of any tick.
          </p>
          <div className="lbtns">
            <a className="lcta" href={PAPER} target="_blank" rel="noopener noreferrer">
              view <b>&#8599;</b>
            </a>
          </div>
          <p className="lpcite">
            <a href={PAPER} target="_blank" rel="noopener noreferrer">
              Modeling Earth-Scale Human-Like Societies with One Billion Agents
            </a>
            <span>Guan et al. &middot; arXiv:2506.12078 &middot; June 2025</span>
          </p>
        </div>
      </section>
      </div>

      <section className="lband invert">
        <Ticks />
        <div className="lbin">
          <p className="lkick">01 &mdash; not personas</p>
          <h2 className="lhead">Personas answer.<br />Shoppers remember.</h2>
          <div className="lcmp">
            <div className="h a">Without state</div>
            <div className="h b">With HydraDB</div>
            {COMPARE.map(([a, b]) => (
              <div key={a} style={{ display: "contents" }}>
                <div className="c a">{a}</div>
                <div className="c b">{b}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="lband" id="architecture">
        <div className="lbin">
          <p className="lkick">02 &mdash; architecture overview</p>
          <h2 className="lhead">One stimulus,<br />end to end.</h2>
          <p className="lprose">
            Perception runs once per creative and freezes. Everything after it is
            deterministic given a seed: retrieval pulls the portion of the shopper&rsquo;s
            world model this stimulus touches, appraisal interprets it, a staged
            stochastic choice model acts, and what happens next is written back as
            a new version of what they believe.
          </p>
          <ArchitectureDiagram />
        </div>
      </section>

      <section className="lband alt" id="funnel">
        <div className="lbin">
          <p className="lkick">03 &mdash; the funnel</p>
          <h2 className="lhead">Four gates.</h2>
          <p className="lprose">
            Each gate is one Bernoulli draw against a logistic:
            <code> P = σ((U − θ) / τ)</code>, where U is a weighted sum of the five
            appraisal dimensions plus adstock, minus wearout and — after the click —
            the realized price gap. Failing a gate is never a silent drop. It has a name.
          </p>
          <GateFunnel />
        </div>
      </section>

      <section className="lband" id="hydradb">
        <div className="lbin">
          <p className="lkick">04 &mdash; what breaks without HydraDB</p>
          <h2 className="lhead">Retrieval stories a<br />vector store cannot tell.</h2>
          <ul className="lbreaks">
            {BREAKS.map(([t, m]) => (
              <li key={t}><b>{t}</b><span>{m}</span></li>
            ))}
          </ul>
          <p className="lquote small">
            The preference supersession chain and the goal lifecycle are retrieval
            stories no vector store can tell.
          </p>
        </div>
      </section>

      <section className="lband alt last">
        <div className="lbin">
          <p className="lkick">05 &mdash; designed for</p>
          <div className="lnums">
            {NUMS.map(([v, l]) => (
              <div key={l}><b className="num">{v}</b><span>{l}</span></div>
            ))}
          </div>
          <p className="lprose narrow">
            Six state families per shopper, every one of them a set of edges in a single
            graph: what is true, what happened, what they believe, what they have learned
            to prefer, what they need now, and who they trust. Nothing is overwritten —
            beliefs, prices and preferences all supersede, carrying the event that caused
            them.
          </p>
          <div className="lbtns">
            <Link className="lcta" href="/studio">enter simulation <b>&rarr;</b></Link>
          </div>
        </div>
      </section>

      <footer className="lfoot">
        <div className="lfrow">
          <span className="lwordmark"><i />ShopSim</span>
          <span>Hack Hydra &middot; Track 3: Memory &amp; Context Retrieval</span>
          <span>Garvit &middot; Atishay</span>
        </div>
        {/* README.md:22-24 — PLAN.md:394: "say it before a judge does". */}
        <p className="lfine">
          Honest scoping: retrieval is a motif library (controllable behavioral laws, by
          design), and goals are exogenous &mdash; this sim demonstrates demand capture,
          not demand creation. Population and horizon above are design scale; the largest
          run on disk is 200 shoppers &times; 60 days.
        </p>
      </footer>
    </main>
  );
}
