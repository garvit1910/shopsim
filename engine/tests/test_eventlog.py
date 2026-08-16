"""JSONL event log + manifest hashing (Law 13, replay's inputs). No DB."""

import json

from shopsim.contracts.enums import EventType
from shopsim.contracts.types import Event
from shopsim.eventlog import JsonlEventLog, manifest_hashes, read_events


def test_append_event_round_trips(tmp_path):
    path = tmp_path / "run.jsonl"
    with JsonlEventLog(path) as log:
        log.append_event(Event(type=EventType.BOUGHT, shopper_id=1000042,
                               t=1755150000, run=0, subject=3000001,
                               props=(("price", 39.0),)))
        log.append({"type": "NEED_SATISFIED", "shopper_id": 1000042,
                    "t": 1755150000, "run": 0, "subject": 5504,
                    "cause_kind": "BOUGHT", "cause_id": 3000001})
    records = read_events(path)
    assert len(records) == 2
    assert records[0] == {"type": "BOUGHT", "shopper_id": 1000042, "t": 1755150000,
                          "run": 0, "subject": 3000001, "price": 39.0}
    assert records[1]["type"] == "NEED_SATISFIED"
    # append mode: reopening adds, never truncates
    with JsonlEventLog(path) as log:
        log.append({"type": "SAW", "shopper_id": 1, "t": 2, "run": 0, "subject": 3})
    assert len(read_events(path)) == 3
    # one JSON object per line, machine-parseable
    for line in path.read_text().strip().splitlines():
        json.loads(line)


def test_manifest_hashes(tmp_path):
    goal = tmp_path / "goal.json"
    goal.write_text('{"waves": []}')
    h = manifest_hashes(goal_config=goal, latent_quality=b"product_id,latent\n")
    # evidence hash always present — computed from contracts/evidence.py bytes
    assert h["evidence_hash"] and len(h["evidence_hash"]) == 64
    assert h["goal_config_hash"] and h["latent_quality_hash"]
    assert h["perception_cache_hash"] is None  # not built yet, honestly absent
    assert "social_config_hash" not in h  # P1: only when provided
    # deterministic
    assert h == manifest_hashes(goal_config=goal, latent_quality=b"product_id,latent\n")
    # content-sensitive
    goal.write_text('{"waves": [1]}')
    assert manifest_hashes(goal_config=goal)["goal_config_hash"] != h["goal_config_hash"]
