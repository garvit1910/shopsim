"""Phase 3: TICK_COMPLETE marker mechanics — split, truncate, group-by-tick,
and replay record remapping / hash refusal."""

import json

from shopsim.contracts.enums import EventType
from shopsim.contracts.ids import shopper_id as make_sid
from shopsim.eventlog import JsonlEventLog
from shopsim.runner.replay import _remap_event
from shopsim.runner.rollback import (
    group_by_tick,
    load_records,
    split_at_last_marker,
    truncate_log,
)
from shopsim.runner.runstore import check_hashes

T0, DAY = 1_755_000_000, 86_400


def write_log(path, ticks_done: int, partial: int) -> None:
    with JsonlEventLog(path) as log:
        for k in range(ticks_done):
            log.append({"type": "SAW", "shopper_id": 1_000_000, "t": T0 + k * DAY,
                        "run": 0, "subject": 2_000_001})
            log.append({"type": "TICK_COMPLETE", "tick": k, "t": T0 + k * DAY,
                        "run": 0, "n_events": 1, "belief_counter": k})
        for _ in range(partial):
            log.append({"type": "CLICKED", "shopper_id": 1_000_000,
                        "t": T0 + ticks_done * DAY, "run": 0, "subject": 2_000_001})


def test_split_truncate_roundtrip(tmp_path):
    p = tmp_path / "events.jsonl"
    write_log(p, ticks_done=3, partial=2)
    records = load_records(p)
    clean, partial, marker = split_at_last_marker(records)
    assert marker["tick"] == 2 and marker["belief_counter"] == 2
    assert len(partial) == 2 and all(r["type"] == "CLICKED" for r in partial)

    truncate_log(p, clean)
    records2 = load_records(p)
    assert records2 == clean
    _, partial2, marker2 = split_at_last_marker(records2)
    assert partial2 == [] and marker2["tick"] == 2

    by_tick = group_by_tick(records2)
    assert sorted(by_tick) == [0, 1, 2]
    assert all(len(v) == 1 for v in by_tick.values())


def test_split_with_no_marker(tmp_path):
    p = tmp_path / "events.jsonl"
    write_log(p, ticks_done=0, partial=3)
    clean, partial, marker = split_at_last_marker(load_records(p))
    assert clean == [] and len(partial) == 3 and marker is None


def test_remap_event_field_table():
    rec = {"type": "BOUGHT", "shopper_id": make_sid(0, 42), "t": T0, "run": 0,
           "subject": 3_000_001, "price": 33.15, "cause_creative": 2_000_003}
    e = _remap_event(rec, run_index=12, sid_of=lambda o: make_sid(12, o))
    assert e.shopper_id == make_sid(12, 42)  # remapped by offset
    assert e.run == 12  # remapped
    assert e.subject == 3_000_001  # objective ids unchanged
    assert e.t == T0  # world time unchanged
    assert e.prop("price") == 33.15 and e.prop("cause_creative") == 2_000_003
    assert e.type is EventType.BOUGHT


def test_check_hashes_config_toggle():
    rec = {"evidence_hash": "e", "perception_cache_hash": "p", "goal_config_hash": "g",
           "latent_quality_hash": "l", "view_hash": "v", "config_hash": "A"}
    cur = dict(rec, config_hash="B")
    assert check_hashes(rec, cur, include_config=False) == []  # branch: config may differ
    assert any("config_hash" in p for p in check_hashes(rec, cur, include_config=True))
    cur2 = dict(rec, evidence_hash="X")
    assert any("evidence_hash" in p for p in check_hashes(rec, cur2, include_config=False))


def test_marker_survives_json_roundtrip(tmp_path):
    p = tmp_path / "events.jsonl"
    log = JsonlEventLog(p)
    log.append({"type": "TICK_COMPLETE", "tick": 0, "t": T0, "run": 0,
                "n_events": 0, "belief_counter": 7})
    log.sync()
    log.close()
    rec = json.loads(p.read_text().strip())
    assert rec["belief_counter"] == 7
