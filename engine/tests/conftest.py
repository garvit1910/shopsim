import json
import os
import sys
from pathlib import Path

import pytest

from shopsim.hydramem.mock import MockHydraMem

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "fixtures"

# SHOPSIM_HYDRAMEM=real runs the same contract suite against the real
# HydraMem on a live HydraDB (story graph seeded on demand). Default stays
# byte-identical: the fixture-backed mock.
REAL_BACKEND = os.environ.get("SHOPSIM_HYDRAMEM") == "real"


def pytest_collection_modifyitems(config, items):
    if REAL_BACKEND:
        return
    skip = pytest.mark.skip(reason="needs SHOPSIM_HYDRAMEM=real + live HydraDB")
    for item in items:
        if "real" in item.keywords:
            item.add_marker(skip)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real: integration test against the real HydraMem (live DB)")


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def context_wrappers() -> list[tuple[str, dict]]:
    """Every canned context fixture file as (filename, wrapper dict)."""
    files = sorted((FIXTURES_DIR / "contexts").glob("*.json"))
    assert files, "no context fixtures found"
    return [(p.name, json.loads(p.read_text())) for p in files]


@pytest.fixture(scope="session")
def mock():
    if REAL_BACKEND:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from real_adapter import StoryHydraMem

        return StoryHydraMem()
    return MockHydraMem(FIXTURES_DIR)
