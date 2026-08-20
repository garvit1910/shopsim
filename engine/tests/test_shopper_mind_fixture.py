"""The committed 05 Mind capture — `fixtures/shopper-mind/mind.json`.

No database required (the golden-run pattern, same as the frozen social-graph
tests): these pin the SHAPE of the capture the Mind page depends on, so a bad
regeneration cannot ship silently. CONTRACT v3.12-draft.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

STAGES_CREATIVE = {"CLICK"}
STAGES_PAGE = {"BROWSE", "CART", "BUY"}

# Law 12/15 regression insurance: none of these may appear as a key anywhere
# in the payload. Appraisal dims and gate probabilities are already-served
# HTTP shapes; the inputs below never leave the engine.
FORBIDDEN_KEYS = {
    "latent_quality", "ship_reliability",
    "novelty_seeking", "trust_orientation", "deal_proneness",
    "impulsivity", "price_sensitivity",
}


@pytest.fixture(scope="module")
def frozen():
    path = (Path(__file__).resolve().parents[2]
            / "fixtures" / "shopper-mind" / "mind.json")
    assert path.exists(), (
        "fixtures/shopper-mind/mind.json is missing — regenerate with "
        "`python -m shopsim.runner export-graph --config "
        "runs/experiments/shopper-mind-demo/run_config.json --run RUN_ID "
        "--out fixtures/shopper-mind/mind.json --previews` "
        "(see the README beside it)")
    return json.loads(path.read_text())


def test_the_capture_says_what_it_is_a_photograph_of(frozen):
    """A frozen mind that does not name its source reads as live state."""
    cap = frozen["captured"]
    assert cap["run_id"] and isinstance(cap["run_index"], int)
    assert 0 <= cap["head_tick"] < frozen["ticks"]
    assert frozen["head_tick"] == cap["head_tick"]
    assert "frozen capture" in frozen["comment"].lower()
    assert "export-graph" in frozen["comment"]


def test_the_mind_keys_are_present(frozen):
    assert frozen["catalog_key"] == "nisolo"
    assert isinstance(frozen["demo_stimuli"], list) and frozen["demo_stimuli"]
    assert isinstance(frozen["previews"], dict) and frozen["previews"]


def test_the_demo_stimuli_are_the_five_nisolo_ads(frozen):
    cids = sorted(row["creative_id"] for row in frozen["demo_stimuli"])
    assert cids == [2000101, 2000102, 2000103, 2000104, 2000105]
    for row in frozen["demo_stimuli"]:
        assert row["page_id"] is not None, row


def test_every_frozen_edge_resolves_to_a_node(frozen):
    """One dangling edge blanks the canvas — the check a bad regen must fail."""
    ids = {n["id"] for n in frozen["nodes"]}
    dangling = [e["id"] for e in frozen["edges"]
                if e["source"] not in ids or e["target"] not in ids]
    assert not dangling, dangling[:5]


def test_the_focus_offsets_are_real_shopper_nodes(frozen):
    by_offset = {n["props"].get("offset"): n for n in frozen["nodes"]
                 if n["kind"] == "shopper"}
    assert frozen["focus"], "no focus shoppers"
    for off in frozen["focus"]:
        assert off in by_offset, off
        assert by_offset[off]["props"]["focus"] is True


def test_previews_are_keyed_by_the_pinned_shopper(frozen):
    assert list(frozen["previews"].keys()) == [str(frozen["focus"][0])]


def test_every_demo_stimulus_has_a_creative_and_a_page_preview(frozen):
    pv = frozen["previews"][str(frozen["focus"][0])]
    for row in frozen["demo_stimuli"]:
        cre = pv[str(row["creative_id"])]
        assert cre["stimulus"]["kind"] == "creative"
        assert cre["stimulus"]["page_id"] == row["page_id"]
        assert set(cre["probabilities"]) == STAGES_CREATIVE
        pg = pv[str(row["page_id"])]
        assert pg["stimulus"]["kind"] == "page"
        assert set(pg["probabilities"]) == STAGES_PAGE
        for p in (*cre["probabilities"].values(), *pg["probabilities"].values()):
            assert 0.0 <= p <= 1.0, p


def test_previews_carry_the_full_decision_preview_envelope(frozen):
    pv = frozen["previews"][str(frozen["focus"][0])]
    for body in pv.values():
        assert {"tick", "stimulus", "scalars", "motifs", "appraisal",
                "probabilities", "counterfactual_need_off"} <= set(body)
        for dim in ("relevance", "credibility", "brand_message_fatigue",
                    "offer_attractiveness", "expectation_alignment"):
            v = body["appraisal"][dim]
            assert v is not None and 0.0 <= v <= 1.0, (dim, v)


def test_every_previewed_stimulus_has_a_trace_with_on_screen_paths(frozen):
    """This is what `extra_stimuli` exists to guarantee: the retrieval path
    for an ad the shopper never met still walks nodes the canvas can draw."""
    offset0 = str(frozen["focus"][0])
    traces = frozen["traces"][offset0]
    on_screen = {n["id"] for n in frozen["nodes"]}
    for stim in frozen["previews"][offset0]:
        assert stim in traces, f"no trace for previewed stimulus {stim}"
        for motif in traces[stim]["motifs"]:
            for hop in motif["path"]:
                if isinstance(hop, int):
                    assert hop in on_screen, (motif["type"], hop)


def test_no_forbidden_keys_anywhere(frozen):
    def scan(obj, where="$"):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert k not in FORBIDDEN_KEYS, f"{where}.{k}"
                scan(v, f"{where}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                scan(v, f"{where}[{i}]")
    scan(frozen)
