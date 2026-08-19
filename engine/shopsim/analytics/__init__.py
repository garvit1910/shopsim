"""Phase-6 analytics: the C3 MetricsReport's statistical half.

Deliberately import-free at package level: `runner/results.py` imports
`analytics.metrics` (pure, numpy only) while `analytics.report` imports
`runner.results` back. Keeping this file empty of imports means those two
directions never meet in a cycle.

    metrics.py   pure functions over accumulator state (no DB, no clock)
    report.py    finalize + post-hoc assembly (reads the graph, reads run dirs)
    __main__.py  `python -m shopsim.analytics report --run <id|dir>`
"""
