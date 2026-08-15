"""The goal twin (C1 mock obligation, Phase-1 checkpoint, F9's fixture):
identical contexts except one NEEDS edge -> active_need + goal_fit only."""

from shopsim.contracts.enums import MotifType


def _wrapper(context_wrappers, name):
    for _, wrapper in context_wrappers:
        if wrapper["name"] == name:
            return wrapper
    raise AssertionError(f"fixture {name} missing")


def _normalized_motifs(motifs):
    """Paths start at the shopper node; mask it so twins compare structurally."""
    out = []
    for m in motifs:
        m = dict(m)
        m["path"] = ["<shopper>"] + m["path"][1:]
        out.append(m)
    return out


def test_twins_differ_only_in_goal(context_wrappers):
    off = _wrapper(context_wrappers, "twin-need-off")["context"]
    on = _wrapper(context_wrappers, "twin-need-on")["context"]

    s_off, s_on = dict(off["scalars"]), dict(on["scalars"])
    assert s_off.pop("shopper_id") != s_on.pop("shopper_id")  # a twin PAIR of ids

    assert s_off.pop("active_need") is None
    need = s_on.pop("active_need")
    assert need == {"category": 5504, "strength": 0.8, "urgency": 0.7, "budget_cap": 90.0}

    assert s_off == s_on, "twins must be identical outside active_need"

    m_on = _normalized_motifs(on["motifs"])
    m_off = _normalized_motifs(off["motifs"])
    goal_fits = [m for m in m_on if m["type"] == MotifType.GOAL_FIT.value]
    assert len(goal_fits) == 1
    assert goal_fits[0]["strength"] == need["strength"]
    assert goal_fits[0]["urgency"] == need["urgency"]

    rest = [m for m in m_on if m["type"] != MotifType.GOAL_FIT.value]
    assert rest == m_off, "twins must share every motif except goal_fit"


def test_mock_serves_both_twins(mock):
    off = mock.get_decision_context(1000041, 2000003)
    on = mock.get_decision_context(1000042, 2000003)
    assert off.scalars.active_need is None
    assert on.scalars.active_need is not None
    assert {m.type for m in on.motifs} - {m.type for m in off.motifs} == {MotifType.GOAL_FIT}
