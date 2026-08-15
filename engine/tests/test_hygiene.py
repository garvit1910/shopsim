"""Law 15: latent objective params never reach a mind. No omniscient shoppers."""

import csv

from shopsim.contracts.types import FORBIDDEN_PAYLOAD_KEYS


def _assert_no_forbidden_keys(node, where):
    if isinstance(node, dict):
        for k, v in node.items():
            assert not any(bad in str(k) for bad in FORBIDDEN_PAYLOAD_KEYS), (
                f"latent key '{k}' leaked into {where}"
            )
            _assert_no_forbidden_keys(v, where)
    elif isinstance(node, list):
        for item in node:
            _assert_no_forbidden_keys(item, where)


def test_no_latent_keys_in_any_fixture_context(context_wrappers):
    for name, wrapper in context_wrappers:
        _assert_no_forbidden_keys(wrapper["context"], name)


def test_no_latent_keys_in_any_mock_payload(mock):
    for name, (shopper_id, stimulus_id) in mock.cases.items():
        payload = mock.get_decision_context(shopper_id, stimulus_id).to_dict()
        _assert_no_forbidden_keys(payload, f"mock payload {name}")


def test_latent_table_exists_but_only_in_the_hidden_layer(fixtures_dir):
    """The latent table must exist (fulfillment needs it) — as a separate
    engine-side file, never referenced by any context fixture."""
    path = fixtures_dir / "demo-brand" / "latent_quality.csv"
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows and all(
        set(r) == {"product_id", "latent_quality", "ship_reliability"} for r in rows
    )
    assert all(0.0 <= float(r["latent_quality"]) <= 1.0 for r in rows)
