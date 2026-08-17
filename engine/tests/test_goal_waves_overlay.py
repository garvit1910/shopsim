"""Phase 4: scenario wave overlays in goal_step (CONTRACT v3.4-draft).

The default path (no extra_waves / wave_scale key) must be byte-identical to
Phase 3 — the overlay branch is only entered when a key is actually present.
"""

from pathlib import Path

from shopsim.contracts.enums import EventType
from shopsim.contracts.ids import shopper_id as make_sid
from shopsim.runner.steps import GoalConfig, GoalState, goal_step

REPO = Path(__file__).resolve().parents[2]
DEMO = REPO / "fixtures" / "demo-brand"
T0, DAY = 1_755_000_000, 86_400
SEGMENTS = {o: 1008 for o in range(60)}  # marathon_trainer: 5504 rate 0.06


def run_goal(tick: int, overrides: dict, seed=57):
    gc = GoalConfig.load(DEMO / "goal_config.json")
    return goal_step(
        seed=seed, tick=tick, now=T0 + tick * DAY, t0=T0, tick_seconds=DAY,
        run=0, goal_cfg=gc, overrides=overrides, state=GoalState(),
        segment_by_offset=SEGMENTS, sid_of=lambda o: make_sid(0, o))


def arrivals(ev, cat=5504):
    return [e for e in ev if e.type is EventType.NEED_ACTIVATED and e.subject == cat]


def test_absent_and_empty_overlay_keys_are_byte_identical():
    base, _ = run_goal(7, {})
    for overrides in ({"extra_waves": []}, {"extra_waves": None},
                      {"extra_waves": [], "wave_scale": None}):
        ev, _ = run_goal(7, overrides)
        assert ev == base


def test_wave_scale_zero_neutralizes_waves():
    # scale 0.0: multiplier becomes exactly 1.0 — same arrivals as waves off
    scaled, _ = run_goal(7, {"wave_scale": 0.0})
    off, _ = run_goal(7, {"waves_enabled": False})
    assert scaled == off
    # and strictly fewer than the configured x4 wave (in this seed's window)
    on, _ = run_goal(7, {})
    assert len(arrivals(scaled)) < len(arrivals(on))


def test_extra_wave_multiplies_only_inside_its_window():
    wave = {"category_id": 5504, "start_tick": 2, "end_tick": 3,
            "rate_multiplier": 6.0}
    inside, _ = run_goal(2, {"extra_waves": [wave]})
    base_inside, _ = run_goal(2, {})
    assert len(arrivals(inside)) > len(arrivals(base_inside))

    outside, _ = run_goal(4, {"extra_waves": [wave]})
    base_outside, _ = run_goal(4, {})
    assert outside == base_outside


def test_extra_waves_respect_waves_enabled():
    wave = {"category_id": 5504, "start_tick": 2, "end_tick": 3,
            "rate_multiplier": 6.0}
    off, _ = run_goal(2, {"extra_waves": [wave], "waves_enabled": False})
    base_off, _ = run_goal(2, {"waves_enabled": False})
    assert off == base_off


def test_overlay_keeps_stream_shape_state_independent():
    """The overlay changes rates, never the number of draws: arrivals outside
    every wave window are identical with and without an overlay present."""
    wave = {"category_id": 5500, "start_tick": 0, "end_tick": 1,
            "rate_multiplier": 5.0}
    with_overlay, _ = run_goal(7, {"extra_waves": [wave], "wave_scale": 1.0})
    base, _ = run_goal(7, {})
    # tick 7 is outside the 5500 overlay window; the 5504 base wave is active.
    # wave_scale 1.0 may differ in float ulps from the direct multiplier, so
    # compare arrival IDENTITY (who, what), not float payloads.
    assert [(e.shopper_id, e.subject) for e in with_overlay] == \
        [(e.shopper_id, e.subject) for e in base]
