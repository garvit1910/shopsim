"""Phase 3: C3 results accumulation, state round-trip, and validation."""

import json
from pathlib import Path

from shopsim.contracts.enums import Action, EventType
from shopsim.contracts.ids import shopper_id as make_sid
from shopsim.contracts.types import Event
from shopsim.hydramem.mock import MockHydraMem
from shopsim.runner.results import ResultsAccumulator, validate_results

REPO = Path(__file__).resolve().parents[2]
T0, DAY = 1_755_000_000, 86_400

MANIFEST = {
    "seed": 57, "config_hash": "c" * 64, "perception_cache_hash": "p" * 64,
    "appraisal_cache_hash": None, "evidence_hash": "e" * 64,
    "goal_config_hash": "g" * 64, "latent_quality_hash": "l" * 64,
}


def make_acc():
    return ResultsAccumulator(
        arm="need_on", segment_by_offset={0: 1001, 1: 1008},
        drift_concepts=[5003], hero_product=3000001)


def observe_some(acc):
    sid = make_sid(0, 0)
    events = [
        Event(EventType.SAW, sid, T0, 0, 2000003),
        Event(EventType.CLICKED, sid, T0, 0, 2000003),
        Event(EventType.BOUGHT, sid, T0, 0, 3000001, props=(("price", 33.15),)),
    ]
    acc.observe_events(events, tick=0)
    ctx = MockHydraMem(REPO / "fixtures").by_name("twin-need-on")
    acc.observe_decision(ctx, Action.BUY, "page")
    ctx_off = MockHydraMem(REPO / "fixtures").by_name("twin-need-off")
    acc.observe_decision(ctx_off, Action.BROWSE, "page")
    acc.observe_satisfaction(activated_tick=2, satisfied_tick=5)


def test_skeleton_is_c3_valid_and_populated():
    acc = make_acc()
    observe_some(acc)
    results = acc.results(MANIFEST)
    assert validate_results(results) == []
    assert results["funnel"]["need_on"]["1001"]["BOUGHT"] == 1
    assert results["ctr_by_day"][0]["ctr"] == 1.0
    assert results["goal_stats"]["p_buy_need_on"] == 1.0
    assert results["goal_stats"]["p_buy_need_off"] == 0.0
    assert results["goal_stats"]["time_to_satisfaction"] == [3]
    assert "preference_fit" in results["motif_stats"]
    assert results["motif_stats"]["preference_fit"]["prevalence_by_outcome"] == {
        "BROWSE": 1, "BUY": 1}
    # typed-empty Phase-6 keys are present
    assert results["fatigue_split"] == {"asset": [], "brand_msg": []}
    assert results["belief_confidence_dist"] == [] and results["ci"] == {}


def test_state_round_trips_exactly():
    acc = make_acc()
    observe_some(acc)
    state = json.loads(json.dumps(acc.state()))  # through JSON, like the file
    back = ResultsAccumulator.from_state(
        state, segment_by_offset=acc.segment_by_offset,
        drift_concepts=acc.drift_concepts, hero_product=acc.hero_product)
    assert back.results(MANIFEST) == acc.results(MANIFEST)


def test_validator_catches_missing_and_mistyped():
    acc = make_acc()
    results = acc.results(MANIFEST)
    broken = dict(results)
    del broken["goal_stats"]
    assert any("goal_stats" in p for p in validate_results(broken))
    broken = dict(results)
    broken["funnel"] = []
    assert any("funnel" in p for p in validate_results(broken))
    broken = dict(results)
    broken["run_manifest"] = {"seed": 1}
    assert any("run_manifest" in p for p in validate_results(broken))
