"""CLI: python -m shopsim.experiments <run|compare|ingest-ads|perceive-catalog> ...

    run              --spec SPEC [--out DIR] [--verbose]
    compare          --dir EXP_DIR
    ingest-ads       --spec ADS [--name NAME]   (image/text ad ingestion, 4.1)
    perceive-catalog --catalog DIR --cache DIR  (freeze a committed brand, 5.8)
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


def cmd_perceive_catalog(args) -> int:
    """Perceive a whole committed catalog once and freeze it.

    ingest_ads is the wrong tool for a brand fixture — it materializes a copy
    of demo-brand and APPENDS to it, which would drag the demo products and ads
    into the new catalog. This perceives a catalog in place. Re-running with
    the cache present makes zero calls; the printout is there so a human can
    check what the eye actually read before committing."""
    from ..perception.perceive import perceive_catalog, resolve_api_key

    catalog, cache = Path(args.catalog), Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    if not resolve_api_key():
        print("error: OPENAI_API_KEY unset (checked env and <repo>/.env.local) — "
              "perception runs live, once, then freezes", file=sys.stderr)
        return 1

    from ..contracts.enums import Concept
    from ..perception.perceive import DEFAULT_MODEL

    def cname(cid: int) -> str:
        try:
            return Concept(cid).name
        except ValueError:
            return str(cid)

    perceived, calls = perceive_catalog(catalog, cache,
                                        model=args.model or DEFAULT_MODEL)
    print(f"{calls} live call(s); {len(perceived)} creative(s) in {cache}\n")
    for cid in sorted(perceived):
        p = perceived[cid]
        claims = ", ".join(f"{cname(c)}:{s:.2f}" for c, s in p.claims) or "—"
        discounts = ", ".join(f"{pid}:{pct:.0%}" for pid, pct in p.offers if pct) or "—"
        print(f"  {cid}  claims   {claims}")
        print(f"          discount {discounts}")
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

    sp = sub.add_parser("perceive-catalog")
    sp.add_argument("--catalog", required=True)
    sp.add_argument("--cache", required=True)
    sp.add_argument("--model", default=None)
    sp.set_defaults(fn=cmd_perceive_catalog)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (ValueError, RuntimeError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
