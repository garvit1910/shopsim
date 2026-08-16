"""Law 15, structurally: the latent objective params may be named by exactly
one Cypher template (the ingest writer) and by no read projection. Runs in
the default suite — no database needed."""

import ast
import inspect
import re

from shopsim.hydramem import cypher, schema
from shopsim.contracts.types import FORBIDDEN_PAYLOAD_KEYS


def test_latent_props_named_only_in_the_ingest_writer():
    source = inspect.getsource(cypher)
    # the module docstring documents the rule — exclude it from the scan
    doc = ast.get_docstring(ast.parse(source))
    if doc:
        source = source.replace(doc, "", 1)
    for key in FORBIDDEN_PAYLOAD_KEYS:
        hits = [m.start() for m in re.finditer(key, source)]
        assert hits, f"{key} must appear in the single ingest template"
        # every mention must sit inside the INGEST_LATENT_PROPS block
        block_start = source.index("INGEST_LATENT_PROPS")
        block_end = source.index("def create_edge")
        for pos in hits:
            assert block_start <= pos < block_end, (
                f"'{key}' escapes the sanctioned ingest block in cypher.py")


def test_node_prop_whitelists_exclude_latent_props():
    for family, props in schema.NODE_PROPS.items():
        for key in FORBIDDEN_PAYLOAD_KEYS:
            assert key not in props, f"{key} whitelisted on {family} nodes"


def test_generic_builders_refuse_latent_props():
    import pytest

    for key in FORBIDDEN_PAYLOAD_KEYS:
        with pytest.raises(cypher.CypherTemplateError):
            cypher.set_node_props("product", 3000001, {key: 0.5})
        with pytest.raises(cypher.CypherTemplateError):
            cypher.node_props("product", 3000001, (key,))
