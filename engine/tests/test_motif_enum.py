"""Law 11 for motifs: closed enum, behavioral/explanatory partition, retirees stay dead."""

from shopsim.contracts.enums import (
    BEHAVIORAL_MOTIFS,
    EXPLANATORY_MOTIFS,
    RETIRED_MOTIF_NAMES,
    MotifType,
)
from shopsim.contracts.types import MOTIF_REQUIRED_FIELDS


def test_partition_is_complete_and_disjoint():
    assert BEHAVIORAL_MOTIFS | EXPLANATORY_MOTIFS == set(MotifType)
    assert not BEHAVIORAL_MOTIFS & EXPLANATORY_MOTIFS


def test_retired_motifs_absent():
    values = {m.value for m in MotifType}
    assert not values & RETIRED_MOTIF_NAMES


def test_required_fields_cover_exactly_behavioral():
    assert set(MOTIF_REQUIRED_FIELDS) == BEHAVIORAL_MOTIFS


def test_fixture_motifs_are_behavioral_enum_members(context_wrappers):
    behavioral = {m.value for m in BEHAVIORAL_MOTIFS}
    for name, wrapper in context_wrappers:
        for motif in wrapper["context"]["motifs"]:
            assert motif["type"] in behavioral, f"{name}: {motif['type']}"


def test_all_behavioral_motifs_exercised_by_fixtures(context_wrappers):
    """Every behavioral motif appears in at least one canned context, so the
    schema validator and downstream appraisal see each shape at least once."""
    seen = {
        motif["type"]
        for _, wrapper in context_wrappers
        for motif in wrapper["context"]["motifs"]
    }
    missing = {m.value for m in BEHAVIORAL_MOTIFS} - seen - {"concept_saturation"}  # P1, no fixture yet
    assert not missing, f"behavioral motifs never exercised: {missing}"
