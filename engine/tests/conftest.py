import json
from pathlib import Path

import pytest

from shopsim.hydramem.mock import MockHydraMem

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "fixtures"


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
def mock() -> MockHydraMem:
    return MockHydraMem(FIXTURES_DIR)
