"""Phase-1 perf checkpoints (PLAN.md):
    (1) 10k-event batch          <= ~10s
    (2) one context, warm cache  <= ~250ms
    (3) 200 shoppers x 1 stim    <= ~3s

Run:  cd engine && uv run python bench/bench_phase1.py [--events N]

Opt-in only — never wired into pytest. Exits nonzero on a miss so it can
gate manually. Uses scratch ids (900_07x_xxx) + the demo catalog; cleans up
its episodic writes afterwards so reruns measure the same graph.
"""

from __future__ import annotations

import argparse
import sys
import time

from shopsim.contracts.enums import EventType
from shopsim.contracts.types import Event
from shopsim.hydramem import cypher, story
from shopsim.hydramem.real import HydraMem

SHOPPER_BLOCK = 900_070_000
N_SHOPPERS = 200
NOW = story.STORY_NOW

# realistic event mix for the 10k batch
MIX = [
    (EventType.SAW, 0.62), (EventType.CLICKED, 0.08), (EventType.VISITED, 0.08),
    (EventType.BROWSED, 0.07), (EventType.BOUNCED, 0.04), (EventType.PRICE_SEEN, 0.05),
    (EventType.CARTED, 0.03), (EventType.ABANDONED, 0.02), (EventType.BOUGHT, 0.005),
    (EventType.EXPERIENCED, 0.005),
]


def make_events(n: int) -> list[Event]:
    out: list[Event] = []
    cum, kinds = 0.0, []
    for et, share in MIX:
        cum += share
        kinds.append((cum, et))
    for i in range(n):
        frac = (i % 1000) / 1000.0
        et = next(e for c, e in kinds if frac < c or c == kinds[-1][0])
        sid = SHOPPER_BLOCK + i % N_SHOPPERS
        if et in (EventType.SAW, EventType.CLICKED):
            subject = story.STIM_AD if i % 3 else story.ECO_AD
        elif et in (EventType.VISITED, EventType.BROWSED, EventType.BOUNCED):
            subject = story.PAGE_OK
        else:
            subject = story.PRODUCT
        props: tuple = ()
        if et in (EventType.BOUGHT, EventType.PRICE_SEEN):
            props = (("price", 39.0),)
        elif et is EventType.EXPERIENCED:
            props = (("sat", 0.9),)
        out.append(Event(type=et, shopper_id=sid, t=NOW - 3600 + i % 3600, run=0,
                         subject=subject, props=props))
    return out


def cleanup(mem: HydraMem) -> None:
    for rel in ("SAW", "CLICKED", "VISITED", "BROWSED", "BOUNCED", "PRICE_SEEN",
                "CARTED", "ABANDONED", "BOUGHT", "EXPERIENCED"):
        targets = {story.STIM_AD, story.ECO_AD, story.PAGE_OK, story.PRODUCT}
        pairs = [(SHOPPER_BLOCK + i, tgt) for i in range(N_SHOPPERS) for tgt in targets]
        mem.client.run_stmt(cypher.delete_edges_batch(rel, pairs))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=int, default=10_000)
    ap.add_argument("--keep", action="store_true", help="skip cleanup")
    args = ap.parse_args()

    mem = HydraMem()
    story.ensure_seeded(mem)
    results: list[tuple[str, float, float, bool]] = []

    # (1) 10k-event batch
    events = make_events(args.events)
    t0 = time.perf_counter()
    n = mem.record_events(events)
    dt1 = time.perf_counter() - t0
    results.append((f"{args.events}-event batch ({n} edges)", dt1, 10.0, dt1 <= 10.0))
    print(f"[1] {n} episodic edges in {dt1:.1f}s  ({n/dt1:.0f}/s)")

    # (2) one context, warm stimulus cache
    mem.set_tick(tick=story.STORY_TICK, now=NOW, tick_start=story.STORY_TICK_START)
    mem.get_decision_context(story.TWIN_ON, story.STIM_AD)  # warm objective cache
    t0 = time.perf_counter()
    mem.get_decision_context(story.TWIN_ON, story.STIM_AD)
    dt2 = time.perf_counter() - t0
    results.append(("single context (warm)", dt2, 0.250, dt2 <= 0.250))
    print(f"[2] single context in {dt2*1000:.1f}ms")

    # (3) 200 shoppers x 1 stimulus, batched
    shoppers = [SHOPPER_BLOCK + i for i in range(N_SHOPPERS)]
    t0 = time.perf_counter()
    ctxs = mem.get_decision_contexts(shoppers, story.STIM_AD)
    dt3 = time.perf_counter() - t0
    assert len(ctxs) == N_SHOPPERS
    results.append((f"{N_SHOPPERS} shoppers x 1 stimulus", dt3, 3.0, dt3 <= 3.0))
    print(f"[3] {N_SHOPPERS} contexts in {dt3:.2f}s  ({dt3/N_SHOPPERS*1000:.1f}ms each)")

    if not args.keep:
        print("cleaning up bench edges ...")
        cleanup(mem)
    mem.close()

    print("\n== targets ==")
    ok = True
    for label, got, target, passed in results:
        ok &= passed
        unit_got = f"{got:.2f}s" if target >= 1 else f"{got*1000:.0f}ms"
        unit_tgt = f"{target:.0f}s" if target >= 1 else f"{target*1000:.0f}ms"
        print(f"  {'PASS' if passed else 'MISS'}  {label}: {unit_got} (target <= {unit_tgt})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
