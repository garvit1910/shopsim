"""Law 12: the ENTRY_POINTS registry is complete, single-entry, and stage-separated."""

from collections import Counter
from dataclasses import fields

from shopsim.contracts.enums import BEHAVIORAL_MOTIFS, EXPLANATORY_MOTIFS
from shopsim.contracts.registry import (
    ENTRY_POINTS,
    EXEMPT_SCALARS,
    SANCTIONED_DUAL_READS,
    consumed,
)
from shopsim.contracts.types import AppraisalTraits, ChoiceCoeffs, Scalars


def test_row_numbers_unique():
    rows = [r.row for r in ENTRY_POINTS]
    assert len(rows) == len(set(rows))


def test_every_trait_enters_exactly_once_in_appraise():
    trait_fields = {f.name for f in fields(AppraisalTraits)}
    counts = Counter(consumed("trait"))
    assert set(counts) == trait_fields
    assert all(n == 1 for n in counts.values()), counts
    for row in ENTRY_POINTS:
        if any(c.startswith("trait:") for c in row.consumes):
            assert row.stage == "appraise", f"row {row.row}: trait outside appraise"


def test_every_coeff_enters_exactly_once_in_decide():
    coeff_fields = {f.name for f in fields(ChoiceCoeffs)}
    counts = Counter(consumed("coeff"))
    assert set(counts) == coeff_fields
    assert all(n == 1 for n in counts.values()), counts
    for row in ENTRY_POINTS:
        if any(c.startswith("coeff:") for c in row.consumes):
            assert row.stage == "decide", f"row {row.row}: coeff outside decide"


def test_every_scalar_enters_once_unless_sanctioned():
    scalar_fields = {f.name for f in fields(Scalars)} - EXEMPT_SCALARS
    counts = Counter(consumed("scalar"))
    assert set(counts) == scalar_fields, (
        f"unregistered scalars: {scalar_fields - set(counts)}; "
        f"unknown scalars in registry: {set(counts) - scalar_fields}"
    )
    for name, n in counts.items():
        allowed = SANCTIONED_DUAL_READS.get(f"scalar:{name}", 1)
        assert n == allowed, f"scalar {name} consumed {n}x (allowed {allowed})"


def test_every_behavioral_motif_enters_exactly_once():
    counts = Counter(consumed("motif"))
    assert set(counts) == {m.value for m in BEHAVIORAL_MOTIFS}
    assert all(n == 1 for n in counts.values()), counts


def test_explanatory_motifs_never_enter():
    assert not set(consumed("motif")) & {m.value for m in EXPLANATORY_MOTIFS}


def test_decide_signature_has_no_traits():
    """decide(a, s, coeffs, rng) — no AppraisalTraits parameter, by signature
    (Phase-2 checkpoint, asserted against the real FormulaMind)."""
    import inspect

    from shopsim.minds import choice
    from shopsim.minds.formula import FormulaMind

    for fn in (choice.decide, FormulaMind.decide):
        params = inspect.signature(fn).parameters
        assert "traits" not in params, fn
        assert all("Traits" not in str(p.annotation) for p in params.values()), fn


def test_import_graph_traits_isolation():
    """Law-12 separation, source-scanned (agreed 2026-08-17: AppraisalTraits
    stays in contracts/types.py — the shared contract — so isolation is
    enforced on the implementation modules' sources instead of import paths):
    the choice module never names the traits type, the appraisal module never
    names the coeffs type, and consolidation names neither."""
    import inspect

    from shopsim.minds import appraisal, choice, consolidation

    assert "AppraisalTraits" not in inspect.getsource(choice)
    assert "ChoiceCoeffs" not in inspect.getsource(appraisal)
    src = inspect.getsource(consolidation)
    assert "AppraisalTraits" not in src and "ChoiceCoeffs" not in src
