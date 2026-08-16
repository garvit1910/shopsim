"""Real-backend stand-in for MockHydraMem in the contract tests.

Activated by SHOPSIM_HYDRAMEM=real (see conftest.py). Connects to the live
HydraDB, seeds the story graph once per story.py content hash, and serves
the same case names / (shopper, stimulus) keys as the canned fixtures — so
the contract suite runs unchanged against the real implementation.
"""

from __future__ import annotations

from shopsim.contracts.types import DecisionContext
from shopsim.hydramem import story
from shopsim.hydramem.real import HydraMem


class StoryHydraMem:
    def __init__(self):
        self._mem = HydraMem()  # fails loudly if the container is down
        story.ensure_seeded(self._mem)

    def get_decision_context(self, shopper_id: int, stimulus_id: int) -> DecisionContext:
        return self._mem.get_decision_context(shopper_id, stimulus_id)

    def by_name(self, name: str) -> DecisionContext:
        return self.get_decision_context(*story.CASES[name])

    @property
    def cases(self) -> dict[str, tuple[int, int]]:
        return dict(story.CASES)

    @property
    def mem(self) -> HydraMem:
        """The underlying HydraMem, for integration tests."""
        return self._mem
