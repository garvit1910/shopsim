"""CLI: python -m shopsim.experiments <run|compare|ingest-ads> ...

    run         --spec SPEC [--out DIR] [--verbose]
    compare     --dir EXP_DIR
    ingest-ads  --spec ADS [--name NAME]     (image/text ad ingestion, 4.1)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cmd_run(args) -> int:
    from .orchestrate import run_experiment
    exp_dir = run_experiment(args.spec, out_dir=args.out, quiet=not args.verbose)
    print(f"experiment complete: {exp_dir / 'comparison.json'}")
    return 0


def cmd_compare(args) -> int:
    from ..runner.runstore import write_json_atomic
    from .compare import compare_dir
    comparison = compare_dir(args.dir)
    out = Path(args.dir) / "comparison.json"
    write_json_atomic(out, comparison)
    print(json.dumps(comparison["experiment"], indent=2))
    print(f"written: {out}")
    return 0


def cmd_ingest_ads(args) -> int:
    from .ingest import ingest_ads
    exp_dir = ingest_ads(args.spec, name=args.name)
    print(f"ads ingested: {exp_dir}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="shopsim.experiments")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("run")
    sp.add_argument("--spec", required=True)
    sp.add_argument("--out")
    sp.add_argument("--verbose", action="store_true")
    sp.set_defaults(fn=cmd_run)

    sp = sub.add_parser("compare")
    sp.add_argument("--dir", required=True)
    sp.set_defaults(fn=cmd_compare)

    sp = sub.add_parser("ingest-ads")
    sp.add_argument("--spec", required=True)
    sp.add_argument("--name")
    sp.set_defaults(fn=cmd_ingest_ads)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (ValueError, RuntimeError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
