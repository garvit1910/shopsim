"""Phase 4: audience targeting in exposure_step (CONTRACT v3.4-draft).

The law under test: the audience filter sits AFTER the per-row reach draw, so
the rng stream shape is audience-independent — filtering a row never perturbs
another row's draws — and filtered exposures consume no frequency caps.
"""

import pytest

from shopsim.runner.config import ScheduleRow
from shopsim.runner.steps import SawHistory, exposure_step

# 30 offsets alternating between two segments
SEGMENTS = {o: (1001 if o % 2 == 0 else 1002) for o in range(30)}


def row(cid, reach=0.9, audience=None):
    return ScheduleRow(creative_id=cid, start_tick=0, end_tick=5,
                       reach_prob=reach, audience_segments=audience)


def run(rows, *, cap_tick=9, cap_72h=99, offsets=None, saw=None):
    return exposure_step(
        seed=57, tick=2, schedule=tuple(rows), offsets=offsets or list(SEGMENTS),
        cap_per_tick=cap_tick, cap_72h=cap_72h, saw=saw or SawHistory(),
        segment_by_offset=SEGMENTS)


def test_audience_filter_is_exact():
    out = run([row(2000001, audience=(1001,))])
    assert out[2000001]  # somebody got exposed
    assert all(SEGMENTS[o] == 1001 for o in out[2000001])


def test_audience_none_matches_phase3_call_shape():
    rows = (row(2000001), row(2000003))
    legacy = exposure_step(seed=57, tick=2, schedule=rows, offsets=list(SEGMENTS),
                           cap_per_tick=9, cap_72h=99, saw=SawHistory())
    assert run(rows) == legacy


def test_filter_does_not_perturb_other_rows_draws():
    # uncapped: row B's exposures are identical whether row A is open to all
    # or audience-filtered to nobody — the draw is consumed either way
    open_a = run([row(2000001), row(2000003)])
    closed_a = run([row(2000001, audience=(9999,)), row(2000003)])
    assert closed_a[2000001] == []
    assert closed_a[2000003] == open_a[2000003]


def test_filtered_exposures_consume_no_caps():
    saw = SawHistory()
    out = run([row(2000001, audience=(9999,)), row(2000003)],
              cap_tick=1, saw=saw)
    assert out[2000001] == []
    # every SAW recorded belongs to the row that actually exposed
    for o in out[2000003]:
        assert saw.seen[o] == [(2, 2000003)]
    # audience-filtered ≡ reach-filtered for row B: same draws consumed,
    # same caps left free (row A exposes nobody either way)
    ghost = run([row(2000001, reach=0.0), row(2000003)], cap_tick=1)
    assert out[2000003] == ghost[2000003]


def test_audience_without_segments_map_raises():
    with pytest.raises(ValueError, match="segment_by_offset"):
        exposure_step(seed=57, tick=2, schedule=(row(2000001, audience=(1001,)),),
                      offsets=list(SEGMENTS), cap_per_tick=9, cap_72h=99,
                      saw=SawHistory())
