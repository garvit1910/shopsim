"""C2 contract tests that need a Mind implementation.

SKIPS until Atishay's ScriptedMind/ScriptedConsolidate stand-in lands at
shopsim/minds/scripted.py (Phase 0, Atishay's lane). Garvit's real minds
(Phase 2) must pass the same tests.
"""

import pytest

from shopsim.contracts.enums import EventType
from shopsim.contracts.types import Event, WorldviewSnapshot

scripted = pytest.importorskip(
    "shopsim.minds.scripted",
    reason="Atishay's ScriptedMind stand-in not landed yet (Phase 0, Atishay lane)",
)


def _consolidator():
    if hasattr(scripted, "ScriptedConsolidate"):
        return scripted.ScriptedConsolidate()
    pytest.skip("shopsim.minds.scripted exposes no ScriptedConsolidate")


def test_consolidate_purity_same_inputs_same_deltas():
    consolidator = _consolidator()
    events = [
        Event(type=EventType.CLICKED, shopper_id=1000041, t=10, run=0, subject=2000003),
        Event(type=EventType.SAW, shopper_id=1000041, t=9, run=0, subject=2000003),
    ]
    snapshot = WorldviewSnapshot(prefs=((5003, 0.45, 2.0),))
    first = consolidator.consolidate(list(events), snapshot)
    second = consolidator.consolidate(list(events), snapshot)
    assert first == second


def test_consolidate_returns_no_pref_delta_for_saw_only():
    """Even the scripted stand-in obeys Law 14: SAW alone earns no preference evidence."""
    consolidator = _consolidator()
    events = [Event(type=EventType.SAW, shopper_id=1000041, t=9, run=0, subject=2000003)]
    snapshot = WorldviewSnapshot(prefs=((5003, 0.45, 2.0),))
    deltas = consolidator.consolidate(events, snapshot)
    assert not [d for d in deltas if d.key.kind == "edge"], (
        "SAW must never produce preference-edge evidence (Law 14 / F7)"
    )
