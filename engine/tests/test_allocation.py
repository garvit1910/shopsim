"""Phase 5: adaptive daily allocation in the shared ad market (v3.6-draft).

The laws under test:
  * day 0 is uniform (the Laplace prior), so allocation never front-runs
    evidence it does not have yet;
  * shares always sum to 1 and never fall below floor_share — a losing ad
    keeps a sliver of reach and can still argue its way back;
  * allocation only moves reach THRESHOLDS: with uniform shares the rescaled
    schedule reproduces the unallocated draws byte-for-byte, and a disabled
    config never touches the schedule object at all;
  * the weights are a pure function of the SAW/CLICKED log, so a resumed run
    re-derives the same allocation as an uninterrupted one.
"""

import pytest

from shopsim.runner.config import ScheduleRow, parse_allocation
from shopsim.runner.steps import (
    AllocationConfig,
    CreativeStats,
    SawHistory,
    allocated_schedule,
    allocation_shares,
    exposure_step,
)

CIDS = (2000001, 2000002, 2000003, 2000004, 2000005)
OFFSETS = list(range(60))


def row(cid, reach=0.4, start=0, end=59):
    return ScheduleRow(creative_id=cid, start_tick=start, end_tick=end,
                       reach_prob=reach)


def market(reach=0.4):
    return tuple(row(c, reach) for c in CIDS)


def alloc(**kw):
    return AllocationConfig(**{"enabled": True, **kw})


def stats(saw: dict, clicked: dict) -> CreativeStats:
    return CreativeStats(exposures=dict(saw), clicks=dict(clicked))


# -- shares -----------------------------------------------------------------


def test_day_zero_is_uniform():
    shares = allocation_shares(alloc(), market(), CreativeStats())
    assert set(shares) == set(CIDS)
    assert all(s == pytest.approx(1 / len(CIDS)) for s in shares.values())


def test_shares_sum_to_one():
    s = stats({c: 100 for c in CIDS}, {2000001: 30, 2000002: 1, 2000003: 12})
    assert sum(allocation_shares(alloc(), market(), s).values()) == pytest.approx(1.0)


def test_floor_holds_under_extreme_skew():
    # one runaway winner, four ads with zero clicks over a big sample
    s = stats({c: 5000 for c in CIDS}, {2000001: 4000})
    shares = allocation_shares(alloc(floor_share=0.05), market(), s)
    assert min(shares.values()) >= 0.05 - 1e-12
    assert shares[2000001] == max(shares.values())
    assert sum(shares.values()) == pytest.approx(1.0)


def test_winner_gains_share_over_loser():
    s = stats({c: 200 for c in CIDS}, {2000001: 40, 2000005: 2})
    shares = allocation_shares(alloc(), market(), s)
    assert shares[2000001] > 1 / len(CIDS) > shares[2000005]


def test_power_controls_concentration():
    s = stats({c: 200 for c in CIDS}, {2000001: 40, 2000005: 2})
    flat = allocation_shares(alloc(power=1.0), market(), s)
    sharp = allocation_shares(alloc(power=3.0), market(), s)
    assert sharp[2000001] > flat[2000001]


def test_only_active_rows_get_shares():
    rows = (row(2000001), row(2000002, start=10, end=20))
    active = [r for r in rows if r.start_tick <= 0 <= r.end_tick]
    shares = allocation_shares(alloc(), active, CreativeStats())
    assert set(shares) == {2000001}


def test_empty_rows_gives_empty_shares():
    assert allocation_shares(alloc(), [], CreativeStats()) == {}


# -- schedule rescale -------------------------------------------------------


def test_uniform_shares_reproduce_base_reach():
    rows = market(reach=0.4)
    uniform = {c: 1 / len(CIDS) for c in CIDS}
    assert allocated_schedule(rows, uniform) == rows


def test_rescale_is_share_times_n():
    rows = market(reach=0.4)
    shares = {c: 0.1 for c in CIDS}
    shares[2000001] = 0.6
    out = {r.creative_id: r.reach_prob for r in allocated_schedule(rows, shares)}
    assert out[2000001] == pytest.approx(min(1.0, 0.4 * 5 * 0.6))
    assert out[2000005] == pytest.approx(0.4 * 5 * 0.1)


def test_rescale_clamps_at_one():
    rows = (row(2000001, reach=0.9), row(2000002, reach=0.9))
    out = allocated_schedule(rows, {2000001: 0.95, 2000002: 0.05})
    assert out[0].reach_prob == 1.0


def test_inactive_rows_pass_through_untouched():
    rows = (row(2000001), row(2000002, start=10, end=20))
    out = allocated_schedule(rows, {2000001: 1.0})
    assert out[1] is rows[1]


def test_empty_shares_returns_schedule_identity():
    rows = market()
    assert allocated_schedule(rows, {}) is rows


# -- the disabled path stays byte-identical ---------------------------------


def test_uniform_allocation_gives_identical_exposure_draws():
    """The whole safety argument in one assertion: rescaling by uniform
    shares changes no threshold, so the exposure step returns exactly what
    the unallocated schedule returns."""
    rows = market(reach=0.4)
    shares = allocation_shares(alloc(), rows, CreativeStats())  # day 0 = uniform
    base = exposure_step(seed=424, tick=0, schedule=rows, offsets=OFFSETS,
                         cap_per_tick=2, cap_72h=6, saw=SawHistory())
    allocated = exposure_step(seed=424, tick=0,
                              schedule=allocated_schedule(rows, shares),
                              offsets=OFFSETS, cap_per_tick=2, cap_72h=6,
                              saw=SawHistory())
    assert allocated == base


def test_parse_allocation_absent_is_none():
    assert parse_allocation(None) is None
    assert parse_allocation({}) is None


def test_parse_allocation_refuses_unknown_keys():
    with pytest.raises(ValueError, match="unknown keys"):
        parse_allocation({"enabled": True, "flor_share": 0.1})


def test_parse_allocation_defaults():
    cfg = parse_allocation({"enabled": True})
    assert (cfg.enabled, cfg.floor_share, cfg.power) == (True, 0.05, 2.0)
    assert (cfg.prior_exposures, cfg.prior_clicks) == (120.0, 6.0)
    # the prior encodes a 5% learning-phase CTR
    assert cfg.prior_clicks / cfg.prior_exposures == pytest.approx(0.05)


# -- stats are pure event-log derivatives -----------------------------------


def test_apply_record_matches_observe():
    """The resume path (apply_record over JSONL dicts) and the live path
    (observe over Event objects) must agree — that equality is what makes a
    resumed run allocate identically."""
    from shopsim.contracts.enums import EventType
    from shopsim.contracts.types import Event

    events = [
        Event(type=EventType.SAW, shopper_id=2000001, subject=2000001, t=100, run=1),
        Event(type=EventType.SAW, shopper_id=2000002, subject=2000001, t=100, run=1),
        Event(type=EventType.CLICKED, shopper_id=2000001, subject=2000001, t=100, run=1),
        Event(type=EventType.SAW, shopper_id=2000003, subject=2000002, t=100, run=1),
    ]
    live = CreativeStats()
    live.observe(events)

    resumed = CreativeStats()
    for e in events:
        resumed.apply_record({"type": e.type.value, "subject": e.subject,
                              "shopper_id": e.shopper_id, "t": e.t})

    assert (live.exposures, live.clicks) == (resumed.exposures, resumed.clicks)
    assert live.exposures == {2000001: 2, 2000002: 1}
    assert live.clicks == {2000001: 1}


def test_non_creative_events_do_not_pollute_stats():
    s = CreativeStats()
    for rec in ({"type": "BOUGHT", "subject": 3000001},
                {"type": "TICK_COMPLETE", "tick": 3},
                {"type": "NEED_ACTIVATED", "subject": 5001}):
        s.apply_record(rec)
    assert (s.exposures, s.clicks) == ({}, {})


def test_smoothed_ctr_uses_prior():
    s = stats({2000001: 0}, {})
    cfg = alloc(prior_exposures=20.0, prior_clicks=1.0)
    assert s.smoothed_ctr(2000001, cfg) == pytest.approx(0.05)
    s2 = stats({2000001: 80}, {2000001: 19})
    assert s2.smoothed_ctr(2000001, cfg) == pytest.approx(0.2)


def test_stronger_prior_slows_early_concentration():
    """The learning-phase property: after one thin day of evidence a weak
    prior crowns a winner, a strong one waits for more."""
    day1 = stats({c: 40 for c in CIDS}, {2000001: 6, 2000002: 2})
    weak = allocation_shares(alloc(prior_exposures=20.0, prior_clicks=1.0),
                             market(), day1)
    strong = allocation_shares(alloc(prior_exposures=120.0, prior_clicks=6.0),
                               market(), day1)
    assert weak[2000001] > strong[2000001] > 1 / len(CIDS)
