# fixtures/golden-run — the Phase 6.2 golden

PLAN.md Phase 6.2: *"tiny golden run (5 shoppers, 3 ticks, one full evidence
chain) with hand-checked numbers asserted in tests."* This directory is that
run, frozen.

| file | what it is |
|---|---|
| `run_config.json` | the run, top-to-bottom rationale in its `comment` |
| `goal_config.json` | seeded arrivals switched OFF — offset 1's scripted need is the only need in the run |
| `events.jsonl` | the replay source of truth for the whole run |
| `manifest.json` | the five Law-13 hashes + run identity |
| `results.json` | the full C3 MetricsReport, finalize included |
| `results_state_2.json` | the tick-2 accumulator snapshot the report recomputes from |

Reproduce (needs a live HydraDB):

```
cd engine
uv run python -m shopsim.runner run --config ../fixtures/golden-run/run_config.json
uv run python -m shopsim.analytics report --run <the run id> \
    --config ../fixtures/golden-run/run_config.json
```

`tests/test_golden_run.py` checks the committed artifacts with **no database**
— it re-derives the funnel from `events.jsonl`, recomputes every pure metric
from `results_state_2.json`, and pins the hand-checked numbers.
`tests/real/test_golden_run_real.py` re-runs the config on the live store and
asserts the report comes back identical under the run-block normalization.

**The run block is not part of the fixture.** `run_manifest.run_index` is the
one key that legitimately differs between reproductions; everything else is
byte-identical for the same seed, which the two runs behind this fixture
(blocks 42 and 43) proved.
