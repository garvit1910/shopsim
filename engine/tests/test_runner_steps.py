"""Phase 3: goal/exposure/fulfillment/promo generators — determinism + semantics."""

from pathlib import Path

from shopsim.contracts.enums import EventType
from shopsim.contracts.ids import shopper_id as make_sid
from shopsim.runner.steps import (
    FulfillmentQueue,
    GoalConfig,
    GoalState,
    PromoSchedule,
    SawHistory,
    exposure_step,
    fulfillment_step,
    goal_step,
    load_latent_quality,
)

REPO = Path(__file__).resolve().parents[2]
DEMO = REPO / "fixtures" / "demo-brand"
T0, DAY = 1_755_000_000, 86_400
RUN = 0


def sid_of(offset: int) -> int:
    return make_sid(RUN, offset)


def run_goal(tick: int, state: GoalState, segments: dict, overrides=None, seed=57):
    gc = GoalConfig.load(DEMO / "goal_config.json")
    return goal_step(
        seed=seed, tick=tick, now=T0 + tick * DAY, t0=T0, tick_seconds=DAY,
        run=RUN, goal_cfg=gc, overrides=overrides or {}, state=state,
        segment_by_offset=segments, sid_of=sid_of)


SEGMENTS = {o: 1008 for o in range(40)}  # marathon_trainer: 5504 rate 0.06


def test_goal_arrivals_deterministic():
    ev1, _ = run_goal(3, GoalState(), SEGMENTS)
    ev2, _ = run_goal(3, GoalState(), SEGMENTS)
    assert ev1 == ev2
    assert any(e.type is EventType.NEED_ACTIVATED for e in ev1)
    for e in ev1:
        if e.type is EventType.NEED_ACTIVATED:
            assert e.prop("source") == "seeded"
            assert 0.5 <= e.prop("strength") <= 0.9
            assert T0 + 3 * DAY + 4 * DAY <= e.prop("deadline_t") <= T0 + 3 * DAY + 8 * DAY


def test_wave_multiplies_arrivals_in_window():
    def count(tick, waves):
        ev, _ = run_goal(tick, GoalState(), SEGMENTS, {"waves_enabled": waves})
        return sum(1 for e in ev if e.type is EventType.NEED_ACTIVATED
                   and e.subject == 5504)
    # marathon_season: x4 on 5504, ticks 6-9
    assert count(7, True) > count(7, False)
    assert count(2, True) == count(2, False)  # outside the window


def test_skip_if_live_and_expiry():
    state = GoalState()
    state.live[(0, 5504)] = (T0 + 10 * DAY, 0)  # live need, far deadline
    ev, _ = run_goal(3, state, {0: 1008})
    assert not [e for e in ev if e.type is EventType.NEED_ACTIVATED and e.subject == 5504]

    state = GoalState()
    state.live[(0, 5504)] = (T0 + 2 * DAY, 0)  # deadline before tick 3
    ev, _ = run_goal(3, state, {0: 1008})
    expired = [e for e in ev if e.type is EventType.NEED_EXPIRED]
    assert [(e.shopper_id, e.subject) for e in expired] == [(sid_of(0), 5504)]
    assert (0, 5504) not in state.live


def test_scripted_wins_and_fires_exactly_once():
    # goal_config scripts offset 42, category 5504, activate_tick 8
    segments = {42: 1001}
    state = GoalState()
    state.live[(42, 5504)] = (T0 + 20 * DAY, 5)  # a seeded need is already live
    ev, _ = run_goal(8, state, segments)
    kinds = [(e.type, e.prop("source")) for e in ev if e.shopper_id == sid_of(42)]
    assert (EventType.NEED_EXPIRED, None) in kinds  # seeded need closed first
    assert (EventType.NEED_ACTIVATED, "scripted") in kinds
    assert state.live[(42, 5504)][0] == T0 + 13 * DAY  # deadline_tick 13

    ev2, _ = run_goal(7, GoalState(), segments)  # wrong tick: nothing scripted
    assert not [e for e in ev2 if e.prop("source") == "scripted"]

    ev3, _ = run_goal(8, GoalState(), segments, {"scripted_enabled": False})
    assert not [e for e in ev3 if e.prop("source") == "scripted"]


def test_goal_state_rebuilds_from_records():
    state = GoalState()
    ev, _ = run_goal(3, state, SEGMENTS)
    rebuilt = GoalState()
    for e in ev:
        rec = {"type": e.type.value, "shopper_id": e.shopper_id, "t": e.t,
               "subject": e.subject, **dict(e.props)}
        rebuilt.apply_record(rec, T0, DAY)
    assert rebuilt.live == state.live


class Row:
    def __init__(self, creative_id, start_tick, end_tick, reach_prob):
        self.creative_id, self.start_tick = creative_id, start_tick
        self.end_tick, self.reach_prob = end_tick, reach_prob


def test_exposure_deterministic_and_capped():
    rows = (Row(2000001, 0, 5, 0.9), Row(2000003, 0, 5, 0.9))
    offs = list(range(30))
    a = exposure_step(seed=57, tick=2, schedule=rows, offsets=offs,
                      cap_per_tick=1, cap_72h=4, saw=SawHistory())
    b = exposure_step(seed=57, tick=2, schedule=rows, offsets=offs,
                      cap_per_tick=1, cap_72h=4, saw=SawHistory())
    assert a == b
    # per-tick cap 1: nobody sees both creatives
    both = set(a[2000001]) & set(a[2000003])
    assert not both

    # 72h cap: a shopper saturated over ticks 0-2 gets nothing at tick 2
    saw = SawHistory()
    for tk in (0, 0, 1, 1):
        saw.record(7, tk, 2000001)
    c = exposure_step(seed=57, tick=2, schedule=rows, offsets=[7],
                      cap_per_tick=2, cap_72h=4, saw=saw)
    assert 7 not in c[2000001] and 7 not in c[2000003]


def test_exposure_respects_schedule_window():
    rows = (Row(2000001, 3, 5, 1.0),)
    out = exposure_step(seed=57, tick=2, schedule=rows, offsets=[0, 1],
                        cap_per_tick=2, cap_72h=9, saw=SawHistory())
    assert out == {}


def test_fulfillment_lag_noise_and_rebuild():
    latent = load_latent_quality(DEMO)
    q = FulfillmentQueue()
    q.record_bought(3, 3000001, T0 + 2 * DAY, 2)
    q.record_bought(4, 3000006, T0 + 3 * DAY, 3)

    none_yet = fulfillment_step(seed=57, tick=3, now=T0 + 3 * DAY, run=RUN,
                                lag_ticks=2, sat_noise_sd=0.08, queue=q,
                                latent=latent, sid_of=sid_of)
    assert none_yet == []

    due = fulfillment_step(seed=57, tick=4, now=T0 + 4 * DAY, run=RUN,
                           lag_ticks=2, sat_noise_sd=0.08, queue=q,
                           latent=latent, sid_of=sid_of)
    assert [(e.shopper_id, e.subject) for e in due] == [(sid_of(3), 3000001)]
    sat = due[0].prop("sat")
    assert 0.0 <= sat <= 1.0
    # same substream key => same noise
    again = fulfillment_step(seed=57, tick=4, now=T0 + 4 * DAY, run=RUN,
                             lag_ticks=2, sat_noise_sd=0.08, queue=q,
                             latent=latent, sid_of=sid_of)
    assert again[0].prop("sat") == sat
    # latent separation survives the noise on average (F11 precondition)
    assert latent[3000001] > 0.8 and latent[3000006] < 0.4


def test_promo_schedule_windows():
    promo = PromoSchedule.load(DEMO / "promo_schedule.json")
    assert promo.discount_at(3000001, 2) == 0.0
    assert promo.discount_at(3000001, 3) == 0.15
    assert promo.discount_at(3000001, 6) == 0.0
    assert promo.discount_at(3000001, 12) == 0.20
    assert promo.discount_at(3000002, 4) == 0.0
