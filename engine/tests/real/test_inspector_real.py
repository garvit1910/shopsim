"""Phase-1 checkpoints: belief provenance renders ("value 0.70, confidence
0.81 — from 2 visits and 1 purchase"); the twin pair differs only in goal;
hygiene holds on every real payload (context, trace, worldview)."""

import pytest

from shopsim.contracts.enums import MotifType
from shopsim.contracts.types import FORBIDDEN_PAYLOAD_KEYS
from shopsim.hydramem import story

pytestmark = pytest.mark.real


def test_belief_provenance_sentence(mock):
    wv = mock.mem.get_shopper_worldview(story.PROVENANCE)
    assert len(wv["beliefs"]) == 1
    b = wv["beliefs"][0]
    assert b["about_id"] == story.SHOECO and b["aspect"] == "trust"
    assert b["value"] == pytest.approx(0.70)
    assert b["evidence"] == pytest.approx(3.0)
    assert b["confidence"] == pytest.approx(0.81, abs=0.005)
    assert b["provenance_sentence"] == "from 2 visits and 1 purchase"
    kinds = {r["kind"]: r["count"] for r in b["provenance"]}
    assert kinds == {"VISITED": 2, "BOUGHT": 1}


def test_twin_contexts_differ_only_in_goal(mock):
    off = mock.get_decision_context(story.TWIN_OFF, story.STIM_AD).to_dict()
    on = mock.get_decision_context(story.TWIN_ON, story.STIM_AD).to_dict()

    s_off, s_on = off["scalars"], on["scalars"]
    assert s_off.pop("shopper_id") != s_on.pop("shopper_id")
    assert s_off.pop("active_need") is None
    need = s_on.pop("active_need")
    assert need["category"] == story.RUNNING
    assert s_off == s_on, "twins must be identical outside active_need"

    def norm(motifs):
        out = []
        for m in motifs:
            m = dict(m)
            m["path"] = ["<shopper>"] + m["path"][1:]
            out.append(m)
        return out

    goal = [m for m in norm(on["motifs"]) if m["type"] == MotifType.GOAL_FIT.value]
    rest = [m for m in norm(on["motifs"]) if m["type"] != MotifType.GOAL_FIT.value]
    assert len(goal) == 1
    assert rest == norm(off["motifs"])


def _scan(node, where):
    if isinstance(node, dict):
        for k, v in node.items():
            assert not any(bad in str(k) for bad in FORBIDDEN_PAYLOAD_KEYS), (
                f"latent key '{k}' leaked into {where}")
            _scan(v, where)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _scan(item, where)


def test_hygiene_on_every_real_payload(mock):
    mem = mock.mem
    for name, (sid, stim) in mock.cases.items():
        _scan(mock.get_decision_context(sid, stim).to_dict(), f"context {name}")
        _scan(mem.get_trace(sid, stim), f"trace {name}")
        _scan(mem.get_shopper_worldview(sid), f"worldview {name}")


def test_trace_relaxes_and_may_add_explanatory_motifs(mock):
    trace = mock.mem.get_trace(story.TWIN_ON, story.STIM_AD)
    trace_types = {m["type"] for m in trace["motifs"]}
    ctx_types = {m.type.value for m in
                 mock.get_decision_context(story.TWIN_ON, story.STIM_AD).motifs}
    assert ctx_types <= trace_types  # trace is a superset view
