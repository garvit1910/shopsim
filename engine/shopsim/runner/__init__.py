"""Phase 3 — the world runner: tick loop, event pipeline, replay/branch/resume.

The runner is the single admitted writer (constraint 8): minds return Actions
and EvidenceDeltas; every graph write goes through HydraMem from here.
"""

from .config import RunConfig
from .loop import SimRunner

__all__ = ["RunConfig", "SimRunner"]
