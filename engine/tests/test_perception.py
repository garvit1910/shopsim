"""Phase 2.2 — perception: schema validity, closed-enum discipline, exact
claimed_pct capture, cache stability, one call per unique stimulus.

The committed cache (fixtures/perception-cache/, gpt-4o-mini, prompt p1) is
the frozen perception of the five demo creatives. The authored claims in
creatives.json remain the seed/story ground truth; perception may read MORE
assertions out of the ad copy than the authored minimum (e.g. Apex
Performance's own "10% off" is a DISCOUNT claim the authored list omits), so
the golden condition is authored ⊆ perceived + exact claimed_pct — never a
missing core claim, never an out-of-enum concept, never an invented offer.
"""

import json

import pytest

from shopsim.contracts.enums import Concept
from shopsim.minds.objective_view import ObjectiveView
from shopsim.perception.cache import cache_dir_hash, default_cache_dir, perceived_maps
from shopsim.perception.perceive import perceive_catalog
from shopsim.perception.schema import parse_output
from shopsim.perception.writer import stimulus_statements


def _fail_call(descriptor, model):
    raise AssertionError(f"LLM called for {descriptor['creative_id']} — cache miss")


@pytest.fixture(scope="module")
def demo_dir(fixtures_dir):
    return fixtures_dir / "demo-brand"


@pytest.fixture(scope="module")
def authored(demo_dir):
    return {c["creative_id"]: c
            for c in json.loads((demo_dir / "creatives.json").read_text())["creatives"]}


@pytest.fixture(scope="module")
def perceived(demo_dir):
    out, calls = perceive_catalog(demo_dir, call=_fail_call)
    assert calls == 0, "committed cache must serve every demo creative"
    return out


def test_every_claim_in_closed_enum(perceived):
    valid = {int(c) for c in Concept}
    for p in perceived.values():
        assert p.claims, p.creative_id
        for concept_id, strength in p.claims:
            assert concept_id in valid
            assert 0.0 <= strength <= 1.0


def test_claimed_pct_captured_exactly(perceived, authored):
    for cid, cr in authored.items():
        expected = {o["product_id"]: o["claimed_pct"] for o in cr["offers"]}
        assert perceived[cid].offers_dict == expected, cid


def test_authored_core_claims_all_found(perceived, authored):
    for cid, cr in authored.items():
        core = {c["concept_id"] for c in cr["claims"]}
        got = set(perceived[cid].claims_dict)
        assert core <= got, (cid, core - got)


def test_cache_rerun_stable(demo_dir):
    h1 = cache_dir_hash(default_cache_dir())
    again, calls = perceive_catalog(demo_dir, call=_fail_call)
    assert calls == 0
    assert cache_dir_hash(default_cache_dir()) == h1  # rerun rewrites nothing


def test_one_call_per_unique_stimulus(demo_dir, tmp_path, authored):
    calls_made = []

    def counting_call(descriptor, model):
        calls_made.append(descriptor["creative_id"])
        return {"claims": [{"concept": "OTHER", "strength": 0.5}],
                "claimed_discounts": []}

    _, calls = perceive_catalog(demo_dir, cache_dir=tmp_path, call=counting_call)
    assert calls == len(authored)
    assert sorted(calls_made) == sorted(authored)  # exactly once each
    _, again = perceive_catalog(demo_dir, cache_dir=tmp_path, call=counting_call)
    assert again == 0  # second run = pure cache


def test_parse_output_maps_unknowns_and_guards_offers():
    p = parse_output(2000001, 6001, [3000001], {
        "claims": [{"concept": "PERFORMANCE", "strength": 1.7},
                   {"concept": "NOT_A_CONCEPT", "strength": 0.4}],
        "claimed_discounts": [{"product_id": 3000001, "claimed_pct": 0.2},
                              {"product_id": 999, "claimed_pct": 0.9}],
    })
    assert p.claims_dict[int(Concept.PERFORMANCE)] == 1.0  # clamped
    assert p.claims_dict[int(Concept.OTHER)] == 0.4  # unknown -> OTHER (Law 11)
    assert p.offers_dict == {3000001: 0.2}  # invented offer dropped


def test_writer_statements_carry_perceived_facts(demo_dir, perceived):
    stmts = stimulus_statements(demo_dir, perceived)
    text = " ".join(q for q, _ in stmts)
    # every write is a whitelisted single-statement template
    assert "CLAIMS" in text and "OFFERS" in text and "SHOWS" in text
    n_claims = sum(1 for q, _ in stmts if ":CLAIMS" in q)
    assert n_claims == sum(len(p.claims) for p in perceived.values())
    with pytest.raises(KeyError):
        stimulus_statements(demo_dir, {})  # perceive first — no silent fallback


def test_objective_view_prefers_perception(demo_dir, perceived):
    claims, offers = perceived_maps(perceived)
    view = ObjectiveView.from_catalog(demo_dir, claims, offers)
    for cid, p in perceived.items():
        assert view.facts(cid).claims == p.claims_dict
        assert view.facts(cid).offers == p.offers_dict
    # catalog truth stays catalog truth (never the LLM)
    assert view.product_attrs[3000001] == frozenset({5001, 5003, 5004, 5005})
