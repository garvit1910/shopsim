"""Phase 4: per-creative and per-page-variant results dimensions
(CONTRACT v3.4-draft) — additive keys, exact state round-trip, and the
committed Phase-3 fixture still validates."""

import json
from pathlib import Path

from shopsim.contracts.enums import EventType
from shopsim.contracts.ids import shopper_id as make_sid
from shopsim.contracts.types import Event
from shopsim.runner.results import ResultsAccumulator, validate_results

REPO = Path(__file__).resolve().parents[2]
T0 = 1_755_000_000

MANIFEST = {
    "seed": 57, "config_hash": "c" * 64, "perception_cache_hash": "p" * 64,
    "appraisal_cache_hash": None, "evidence_hash": "e" * 64,
    "goal_config_hash": "g" * 64, "latent_quality_hash": "l" * 64,
}


def make_acc():
    return ResultsAccumulator(
        arm="main", segment_by_offset={0: 1001, 1: 1008, 2: 1003},
        drift_concepts=[5003], hero_product=3000001)


def funnel_events():
    """Two creatives; creative 2000003's click lands on page 4000002 and
    bounces; 2000001's click browses page 4000001 through to BOUGHT."""
    s0, s1, s2 = (make_sid(0, o) for o in (0, 1, 2))
    cause1 = (("cause_creative", 2000001),)
    return [
        Event(EventType.SAW, s0, T0, 0, 2000001),
        Event(EventType.CLICKED, s0, T0, 0, 2000001),
        Event(EventType.VISITED, s0, T0, 0, 4000001, props=cause1),
        Event(EventType.BROWSED, s0, T0, 0, 4000001, props=cause1),
        Event(EventType.CARTED, s0, T0, 0, 3000001, props=cause1),
        Event(EventType.BOUGHT, s0, T0, 0, 3000001,
              props=(("cause_creative", 2000001), ("price", 33.15))),
        Event(EventType.SAW, s1, T0, 0, 2000003),
        Event(EventType.CLICKED, s1, T0, 0, 2000003),
        Event(EventType.BOUNCED, s1, T0, 0, 4000002,
              props=(("cause_creative", 2000003),)),
        Event(EventType.SAW, s2, T0, 0, 2000003),
        # fulfillment event: attributed to no creative
        Event(EventType.EXPERIENCED, s0, T0, 0, 3000001, props=(("sat", 0.8),)),
    ]


def test_per_creative_funnel_and_ctr():
    acc = make_acc()
    acc.observe_events(funnel_events(), tick=0)
    results = acc.results(MANIFEST)
    assert validate_results(results) == []

    fc = results["funnel_by_creative"]
    assert fc["2000001"]["SAW"] == 1
    assert fc["2000001"]["CLICKED"] == 1
    assert fc["2000001"]["BROWSED"] == 1
    assert fc["2000001"]["BOUGHT"] == 1
    assert fc["2000003"]["SAW"] == 2
    assert fc["2000003"]["CLICKED"] == 1
    assert fc["2000003"]["BOUNCED"] == 1
    assert fc["2000003"]["BOUGHT"] == 0
    # EXPERIENCED is unattributed
    assert fc["2000001"]["EXPERIENCED"] == 0

    rows = {(r["creative"], r["tick"]): r for r in results["ctr_by_creative_by_day"]}
    assert rows[(2000001, 0)]["ctr"] == 1.0
    assert rows[(2000003, 0)]["exposures"] == 2
    assert rows[(2000003, 0)]["ctr"] == 0.5


def test_per_page_funnel_and_bounce_rate():
    acc = make_acc()
    acc.observe_events(funnel_events(), tick=0)
    results = acc.results(MANIFEST)

    fp = results["funnel_by_page"]
    assert fp["4000001"]["VISITED"] == 1
    assert fp["4000001"]["BOUNCED"] == 0
    assert fp["4000001"]["bounce_rate"] == 0.0
    assert fp["4000002"]["BOUNCED"] == 1
    assert fp["4000002"]["VISITED"] == 0
    assert fp["4000002"]["bounce_rate"] == 1.0


def test_state_round_trips_exactly_with_new_dims():
    acc = make_acc()
    acc.observe_events(funnel_events(), tick=0)
    acc.observe_events(funnel_events(), tick=1)
    state = json.loads(json.dumps(acc.state()))  # through JSON, like the file
    back = ResultsAccumulator.from_state(
        state, segment_by_offset=acc.segment_by_offset,
        drift_concepts=acc.drift_concepts, hero_product=acc.hero_product)
    assert back.results(MANIFEST) == acc.results(MANIFEST)
    assert back.by_creative == acc.by_creative
    assert back.by_page == acc.by_page
    assert back.ctr_creative == acc.ctr_creative


def test_from_state_tolerates_pre_phase4_snapshot():
    acc = make_acc()
    acc.observe_events(funnel_events(), tick=0)
    state = json.loads(json.dumps(acc.state()))
    for key in ("by_creative", "by_page", "ctr_creative"):
        del state[key]
    back = ResultsAccumulator.from_state(
        state, segment_by_offset=acc.segment_by_offset,
        drift_concepts=acc.drift_concepts, hero_product=acc.hero_product)
    assert back.by_creative == {} and back.by_page == {}
    assert validate_results(back.results(MANIFEST)) == []


def test_committed_phase3_fixture_still_validates():
    fixture = json.loads(
        (REPO / "fixtures" / "scripted-run-1" / "results.json").read_text())
    assert "funnel_by_creative" not in fixture  # pre-Phase-4 shape
    assert validate_results(fixture) == []


def test_validator_checks_new_keys_when_present():
    acc = make_acc()
    acc.observe_events(funnel_events(), tick=0)
    results = acc.results(MANIFEST)
    broken = dict(results)
    broken["funnel_by_page"] = {"4000001": {"VISITED": 1}}  # no bounce_rate
    assert any("bounce_rate" in p for p in validate_results(broken))
    broken = dict(results)
    broken["ctr_by_creative_by_day"] = [{"tick": 0}]
    assert any("ctr_by_creative_by_day" in p for p in validate_results(broken))
