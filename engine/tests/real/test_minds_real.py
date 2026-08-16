"""Phase-2 real-backend integration: the minds against the live HydraMem.

Three proofs on the real store:
  1. population seeding → retrieval: seeded PREFERS priors surface as
     preference_fit motifs in a real DecisionContext;
  2. consolidate() → DeltaApplier: the golden chain reproduced from EVENTS
     end-to-end (mind emits, engine applies, history carries receipts);
  3. perception writer round-trip: perceived CLAIMS/OFFERS land in the graph
     and read back through the ObjectiveCache.

Shoppers live in run-block 8 (1_800_000+) — disjoint from the story cast —
and every write is cleaned up so the story graph stays canonical.
"""

import pytest

from shopsim.contracts.enums import EventType, MotifType
from shopsim.contracts.types import Event
from shopsim.hydramem import cypher, schema, story
from shopsim.hydramem.writes import OrderedDelta, ingest_catalog
from shopsim.minds.consolidation import consolidate
from shopsim.minds.objective_view import ObjectiveView
from shopsim.perception.cache import perceived_maps
from shopsim.perception.perceive import perceive_catalog
from shopsim.perception.writer import write_stimuli
from shopsim.population import PopulationConfig, generate_population, seed_population
from shopsim.population.factory import load_segment_specs

pytestmark = pytest.mark.real

RUN_BLOCK = 8  # 1_800_000+: disjoint from the story cast and bench blocks
NOW = story.STORY_NOW


def _fail_call(descriptor, model):
    raise AssertionError("LLM must never be called from tests")


@pytest.fixture(scope="module")
def demo_dir(fixtures_dir):
    return fixtures_dir / "demo-brand"


@pytest.fixture(scope="module")
def view(demo_dir):
    return ObjectiveView.from_catalog(demo_dir)


def test_population_seeds_surface_as_preference_fit(mock, fixtures_dir, demo_dir):
    mem = mock.mem
    specs = load_segment_specs(demo_dir / "personas.json")
    pop = generate_population(PopulationConfig(
        seed=11, population_size=6, segments=specs, run_index=RUN_BLOCK))
    try:
        seed_population(mem, pop, t=NOW - 5 * story.DAY)
        mem.set_tick(tick=story.STORY_TICK, now=NOW, tick_start=story.STORY_TICK_START)
        stim_claims = set(ObjectiveView.from_catalog(demo_dir).facts(story.STIM_AD).claims)
        hits = 0
        for sh in pop:
            ctx = mem.get_decision_context(sh.shopper_id, story.STIM_AD)
            expected = {c for c, w in sh.priors if c in stim_claims and w >= 0.05}
            pref_motifs = [m for m in ctx.motifs if m.type is MotifType.PREFERENCE_FIT]
            if expected:
                assert pref_motifs, (sh.segment_id, sh.priors)
                assert pref_motifs[0].path[2] in expected
                hits += 1
            else:
                assert not pref_motifs
        assert hits > 0, "population must include stimulus-relevant priors"
    finally:
        for sh in pop:
            for concept_id, _ in sh.priors:
                mem.client.run_stmt(cypher.delete_edge("PREFERS", sh.shopper_id, concept_id))


def test_golden_chain_from_events_through_applier(mock, view):
    """The full loop: events → consolidate() → apply_deltas → supersession
    history with receipts, digit-exact per Appendix F."""
    mem = mock.mem
    sid = 1_800_990  # inside run-block 8, never used by the population test
    chain = [
        Event(EventType.CLICKED, sid, NOW - 9 * story.DAY, 0, story.STIM_AD,
              (("cause_creative", story.STIM_AD),)),
        Event(EventType.BROWSED, sid, NOW - 8 * story.DAY, 0, story.PAGE_OK,
              (("cause_creative", story.STIM_AD),)),
        Event(EventType.CARTED, sid, NOW - 7 * story.DAY, 0, story.PRODUCT,
              (("cause_creative", story.STIM_AD),)),
        Event(EventType.BOUGHT, sid, NOW - 6 * story.DAY, 0, story.PRODUCT,
              (("price", 39.0), ("cause_creative", story.STIM_AD))),
        Event(EventType.EXPERIENCED, sid, NOW - 4 * story.DAY, 0, story.PRODUCT,
              (("sat", 1.0),)),
    ]
    saved = (mem._tick, mem._now, mem._tick_start)
    touched_concepts = {story.ECO, 5005, 5011, 5001, 5004}
    try:
        mem.set_tick(tick=0, now=NOW - 10 * story.DAY, tick_start=NOW - 10 * story.DAY)
        mem.seed_preference(sid, story.ECO, 0.45, t=NOW - 10 * story.DAY)
        for tick, ev in enumerate(chain, start=1):
            snapshot = mem.snapshot_worldview(sid)
            deltas = consolidate([ev], snapshot, view)
            ordered = [OrderedDelta(ev.t, rank, d) for rank, d in enumerate(deltas)]
            mem.set_tick(tick=tick, now=ev.t, tick_start=ev.t)
            mem.apply_deltas({sid: ordered})

        hist = mem.get_preference_history(sid, story.ECO)
        assert [round(r["w"], 3) for r in hist] == [0.45, 0.476, 0.532, 0.614, 0.714, 0.761]
        assert hist[-1]["evidence"] == pytest.approx(4.6)
        assert [(r["cause_kind"], r["cause_id"]) for r in hist] == [
            ("SEED", 0),
            ("CLICKED", story.STIM_AD),
            ("BROWSED", story.PAGE_OK),
            ("CARTED", story.PRODUCT),
            ("BOUGHT", story.PRODUCT),
            ("EXPERIENCED", story.PRODUCT),
        ]
        # the BUY and the delivery also formed a trust belief about the brand
        wv = mem.get_shopper_worldview(sid)
        trust = [b for b in wv["beliefs"] if b["about_id"] == story.SHOECO]
        assert trust and trust[0]["evidence"] > 0
    finally:
        mem.set_tick(tick=saved[0], now=saved[1], tick_start=saved[2])
        for concept in touched_concepts:
            mem.client.run_stmt(cypher.delete_edge("PREFERS", sid, concept))
        for rel in ("CLICKED", "BROWSED", "CARTED", "BOUGHT", "EXPERIENCED"):
            for target in (story.STIM_AD, story.PAGE_OK, story.PRODUCT):
                mem.client.run_stmt(cypher.delete_edge(rel, sid, target))
        for r in mem.client.run_stmt(cypher.holds_history(sid)):
            b = r["dst"]
            mem.client.run_stmt(cypher.delete_edge("HOLDS", sid, b))
            mem.client.run_stmt(cypher.delete_edge("ABOUT", b, story.SHOECO))
            mem.client.run_stmt(cypher.delete_edge("THAT", b, schema.ASPECT_TRUST_ID))
            for target in (story.PAGE_OK, story.PRODUCT):
                mem.client.run_stmt(cypher.delete_edge("DERIVED_FROM", b, target))
        for concept in touched_concepts:
            mem.client.run_stmt(cypher.delete_edge("EXPECTS", sid, concept))


def test_perception_writer_round_trip(mock, demo_dir):
    """Perceived stimulus facts land in the objective graph and read back
    through the same ObjectiveCache the retrieval path uses."""
    mem = mock.mem
    perceived, calls = perceive_catalog(demo_dir, call=_fail_call)
    assert calls == 0
    authored_claims = {}  # (creative, concept) pairs to restore afterwards
    try:
        # clear the authored stimulus claims/offers so the read-back is
        # unambiguous (MERGE keys on props: differing strengths would coexist)
        cache0 = mem.cache
        cache0.build(mem._now)
        for cid, meta in cache0.creatives.items():
            authored_claims[cid] = meta
            for concept in set(meta["claims"]) | set(perceived[cid].claims_dict):
                mem.client.run_stmt(cypher.delete_edge("CLAIMS", cid, concept))
            for product in set(meta["offers"]) | set(perceived[cid].offers_dict):
                mem.client.run_stmt(cypher.delete_edge("OFFERS", cid, product))

        write_stimuli(mem.client, demo_dir, perceived)
        mem.cache._built_at = None
        mem.cache.build(mem._now)
        for cid, p in perceived.items():
            assert mem.cache.creatives[cid]["claims"] == p.claims_dict
            assert mem.cache.creatives[cid]["offers"] == p.offers_dict
        # the perception-driven view is what the minds would be bound to
        claims, offers = perceived_maps(perceived)
        view = ObjectiveView.from_catalog(demo_dir, claims, offers)
        assert view.facts(story.STIM_AD).max_claimed_pct == pytest.approx(0.15)
    finally:
        for cid, p in perceived.items():
            for concept in set(p.claims_dict) | set(authored_claims.get(cid, {}).get("claims", {})):
                mem.client.run_stmt(cypher.delete_edge("CLAIMS", cid, concept))
            for product in set(p.offers_dict) | set(authored_claims.get(cid, {}).get("offers", {})):
                mem.client.run_stmt(cypher.delete_edge("OFFERS", cid, product))
        ingest_catalog(mem.client, demo_dir)  # restore the authored graph
        mem.cache._built_at = None
