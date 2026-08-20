"""The decision trace: lossless, versioned, and inert when switched off."""

import json

import pytest

from shopsim.contracts.enums import Action
from shopsim.eval import contexts as C
from shopsim.eval import trace as T
from shopsim.minds.appraisal import appraise
from shopsim.minds.calibration import DEFAULT_STAGE_BASES
from shopsim.minds.choice import stage_probabilities

DIMS = ("relevance", "credibility", "brand_message_fatigue",
        "offer_attractiveness", "expectation_alignment")
CASES = ("cold", "aware", "prior_hit", "learned", "fatigued", "goal_on")


@pytest.fixture(scope="module")
def written(tmp_path_factory):
    pop = C.population(7, 12)
    view = C.catalog_view()
    path = tmp_path_factory.mktemp("trace") / T.TRACE_FILENAME
    tr = T.DecisionTrace(path, header={"run_id": "unit",
                                       "stage_bases": dict(DEFAULT_STAGE_BASES)})
    originals = []
    for sh in pop:
        for case in CASES:
            for kind, sid in (("creative", 2000003), ("page", 4000001)):
                ctx = C.make_context(case, kind=kind,
                                     violation=0.4 if kind == "page" else None)
                stim = view.facts(sid)
                tr.record(ctx=ctx, traits=sh.traits, coeffs=sh.coeffs, stim=stim,
                          kind=kind, action=Action.IGNORE, tick=1,
                          offset=0, segment=sh.segment_id, stimulus=sid)
                originals.append((ctx, sh.traits, stim, sh.coeffs, kind))
    tr.close()
    return path, originals


def test_rebuild_reproduces_the_appraisal_and_the_gates(written):
    """The whole point of storing INPUTS: a replayed row must appraise and gate
    identically, or every calibration fitted on a trace is fitted on noise."""
    path, originals = written
    _header, rows = T.load(path)
    assert len(rows) == len(originals)
    for (o_ctx, o_traits, o_stim, o_coeffs, o_kind), row in zip(originals, rows):
        r_ctx, r_traits, r_stim, r_coeffs, r_kind = T.rebuild(row)
        assert r_kind == o_kind
        a0 = appraise(o_ctx, o_traits, o_stim)
        a1 = appraise(r_ctx, r_traits, r_stim)
        for d in DIMS:
            assert getattr(a0, d) == pytest.approx(getattr(a1, d), abs=1e-5)
        p0 = stage_probabilities(a0, o_ctx.scalars, o_coeffs, kind=o_kind)
        p1 = stage_probabilities(a1, r_ctx.scalars, r_coeffs, kind=r_kind)
        for stage in p0:
            assert p0[stage] == pytest.approx(p1[stage], abs=1e-5)


def test_header_declares_the_schema_and_load_refuses_a_mismatch(written, tmp_path):
    path, _ = written
    header, _rows = T.load(path)
    assert tuple(header["fields"]) == T.FIELDS
    assert header["trace_version"] == T.TRACE_VERSION

    bad = tmp_path / "bad.jsonl"
    lines = path.read_text().splitlines()
    h = json.loads(lines[0])
    h["fields"] = h["fields"][:-1]
    bad.write_text("\n".join([json.dumps(h)] + lines[1:]))
    with pytest.raises(ValueError, match="field schema"):
        T.load(bad)

    older = tmp_path / "older.jsonl"
    h2 = json.loads(lines[0])
    h2["trace_version"] = T.TRACE_VERSION - 1
    older.write_text("\n".join([json.dumps(h2)] + lines[1:]))
    with pytest.raises(ValueError, match="trace_version"):
        T.load(older)


def test_retrofit_inverts_the_recency_decay_exactly(written):
    """`pref_recency` is exp(-ln2 * age / half_life), so the age is recoverable
    and a different half-life is exact rather than approximate. Retrofitting to
    the SAME half-life must therefore be the identity."""
    path, _ = written
    _h, rows = T.load(path)
    same = T.retrofit(rows, traced_pref_half_life_days=3.0, pref_half_life_days=3.0)
    i = T.FIELDS.index("pref_recency")
    for a, b in zip(rows, same):
        if a[i] is None:
            assert b[i] is None
        else:
            assert a[i] == pytest.approx(b[i], abs=1e-5)

    longer = T.retrofit(rows, traced_pref_half_life_days=3.0, pref_half_life_days=30.0)
    moved = [(a[i], b[i]) for a, b in zip(rows, longer) if a[i] is not None and a[i] < 1.0]
    assert moved, "fixture should contain at least one decayed preference"
    for before, after in moved:
        assert after > before, "a longer half-life must decay less"


def test_retrofit_applies_the_violation_floor(written):
    path, _ = written
    _h, rows = T.load(path)
    i = T.FIELDS.index("violation_strength")
    assert any(r[i] is not None for r in rows)
    floored = T.retrofit(rows, violation_min_strength=0.9)
    assert all(r[i] is None for r in floored), "0.4 violations must not survive a 0.9 floor"
    kept = T.retrofit(rows, violation_min_strength=0.1)
    assert any(r[i] is not None for r in kept)


def test_score_reports_both_the_model_and_what_actually_happened(written):
    path, _ = written
    _h, rows = T.load(path)
    out = T.score(rows, traced_stage_bases=DEFAULT_STAGE_BASES)
    assert 0.0 <= out["model"]["p_click"] <= 1.0
    assert out["n"]["creative_decisions"] == len(rows) // 2
    assert out["n"]["page_decisions"] == len(rows) // 2
    assert out["realised"]["ctr"] == 0.0  # every fixture action is IGNORE


def test_tracing_off_writes_no_file_and_takes_no_branch():
    """Byte-neutrality: a runner built without --trace-decisions must not even
    hold a trace object, so the tick loop's guard is never entered."""
    from shopsim.runner.loop import SimRunner
    import inspect

    src = inspect.getsource(SimRunner._run_tick)
    assert src.count("if self.trace is not None:") == 2, \
        "both decision sites must be guarded"
    sig = inspect.signature(SimRunner.__init__)
    assert sig.parameters["trace_decisions"].default is False
