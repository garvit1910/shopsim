"""Phase 4: seeded 50/50 page-variant assignment (CONTRACT v3.4-draft).

steps.page_for is the ONE resolver used at click time, state rebuild, and
replay — assignment is drawn from (seed, "page", offset, creative), tick-free,
never logged, and re-derivable anywhere.
"""

from shopsim.runner.loop import RunnerState
from shopsim.runner.steps import page_for

SEED = 57
PAGES = {2000001: 4000001, 2000003: 4000001}
SPLITS = {2000003: (4000001, 4000002)}


def test_non_split_is_identity_with_static_map():
    for creative in (2000001, 2000005, 0):
        for offset in range(20):
            assert page_for(SEED, SPLITS, PAGES, offset, creative) == \
                PAGES.get(creative)


def test_split_assignment_stable_and_seeded():
    a = [page_for(SEED, SPLITS, PAGES, o, 2000003) for o in range(50)]
    b = [page_for(SEED, SPLITS, PAGES, o, 2000003) for o in range(50)]
    assert a == b  # re-derivable: same seed, same assignment, forever
    assert set(a) <= {4000001, 4000002}
    other = [page_for(SEED + 1, SPLITS, PAGES, o, 2000003) for o in range(50)]
    assert other != a  # the seed matters


def test_split_is_roughly_half_half():
    got = [page_for(SEED, SPLITS, PAGES, o, 2000003) for o in range(200)]
    share = got.count(4000001) / len(got)
    assert 0.35 < share < 0.65


def test_split_independent_per_creative():
    splits = {2000003: (4000001, 4000002), 2000004: (4000001, 4000002)}
    a = [page_for(SEED, splits, PAGES, o, 2000003) for o in range(100)]
    b = [page_for(SEED, splits, PAGES, o, 2000004) for o in range(100)]
    assert a != b  # creative id is in the substream key


def test_rebuild_uses_the_same_resolver():
    """RunnerState.rebuild_from_records must derive the same cart page the
    live loop assigned — through the identical pure resolver."""
    def resolver(offset, creative):
        return page_for(SEED, SPLITS, PAGES, offset, creative)

    t0, day = 1_755_000_000, 86_400
    # offset 7 carted product 3000001 at tick 2, cause = the split creative
    sid = 1_000_000 + 7
    records = [{"type": "CARTED", "shopper_id": sid, "subject": 3000001,
                "t": t0 + 2 * day, "run": 0, "cause_creative": 2000003}]
    state = RunnerState()
    state.rebuild_from_records(records, t0, day, resolver)
    assert state.carts[7] == (3000001, resolver(7, 2000003), 2000003, 2)
