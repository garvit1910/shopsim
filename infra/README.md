# /infra — HydraDB local dev (Phase 0.2 ✅, owner: Atishay)

All §0.2 checkpoints proven on 2026-08-16: CREATE→MATCH round-trips over Bolt
**and** HTTP, survives `docker compose restart`, `/readyz` healthy.

## Run it

```sh
infra/up.sh        # pre-creates hydradb-data/{store,cache} + auth token, then docker compose up -d
curl -fsS http://127.0.0.1:9090/readyz    # ready when this returns 200
```

Pinned image (PLAN decision 9 — bump deliberately, never implicitly):

```
ghcr.io/hydra-db/hydradb@sha256:db78309a233be54662db29744047e985a39b51c45a270d1a1f47c31a62cdb709
```

The full flag set lives in [docker-compose.yml](docker-compose.yml) (auth token
file, `GRAPH_ALLOW_PLAINTEXT=true`, `--user $(id -u):$(id -g)` via
`DOCKER_UID`/`DOCKER_GID`, `RUST_MIN_STACK=33554432`). Data + the local token
live in `infra/hydradb-data/` (gitignored). This compose file is the seed of
Phase 9's (add engine + web services).

| Port | What | Notes |
|---|---|---|
| 7687 | Bolt | neo4j Python driver, `bolt://127.0.0.1:7687` |
| 8443 | HTTP query API | **plain http** locally (ALLOW_PLAINTEXT); `/healthz` |
| 9090 | Admin | `/readyz`, `/metrics` |

## Auth (verified)

- **Bolt: `neo4j.bearer_auth(token)`** — first scheme in the try-chain worked;
  this is what HydraMem (Phase 1) should use.
- **HTTP**: `POST http://127.0.0.1:8443/v1/graphs/default/query` with headers
  `Authorization: Bearer <token>`, `X-Graph-Namespace: default`,
  `Content-Type: application/json` and body
  `{"cell_id": "cell-0", "query": "<cypher>", "consistency": "causal"|"strong"}`.
  A `params` body key is accepted. Response doc:
  `{"columns": [...], "rows": [[{"type": ..., "value": ...}]], "bookmark": ...}`.
- Token: `local-development-token-32-bytes` (in `hydradb-data/auth-token`).

```sh
curl -fsS http://127.0.0.1:8443/v1/graphs/default/query \
  -H "Authorization: Bearer local-development-token-32-bytes" \
  -H "X-Graph-Namespace: default" -H "Content-Type: application/json" \
  -d '{"cell_id":"cell-0","query":"MATCH (n {id: 900000001}) RETURN n.v","consistency":"strong"}'
```

## Smoke & durability procedure

```sh
cd engine
uv run python ../infra/smoke.py all --probe-sppaths   # write+verify both protocols
docker compose -f ../infra/docker-compose.yml restart hydradb
until curl -fsS http://127.0.0.1:9090/readyz; do sleep 2; done
uv run python ../infra/smoke.py verify                # durability: all data intact
```

## Cypher subset — discovered live (input to Phase 1.2 templates)

Beyond PLAN decisions 1–7, probing found:

- **No bare-node CREATE/MERGE** ("only one-hop edge patterns are executable").
  Nodes exist **implicitly by integer id**: `MATCH (n {id: X})` succeeds on any
  id (props null until set). Write node props via `MATCH (n {id}) SET ...`.
  ⚠ Consequence for Phase 1: "node absent" is not observable — abstention
  checks must key off **null props / absent edges**, never node existence.
- **Edges**: `CREATE`/`MERGE` one-hop patterns anchored on ids, inline props OK:
  `MERGE (a {id: $a})-[:REL {t: $t}]->(b {id: $b})`.
- **No compound write statements**: `MERGE ... SET` and `MATCH ... MERGE` are
  both rejected — sequence multi-step writes client-side (decision 3 confirmed).
- **`algo.SPpaths` works** (Phase 1.1 probe (a) = YES): bare CALL only, integer
  ids in the config map, no MATCH prefix:
  `CALL algo.SPpaths({sourceNode: $a, targetNode: $b, relTypes: ['R'], maxLen: 4}) YIELD path RETURN path`
  — returns real Path objects. relTypes list accepted. (Latency + heterogeneous
  relTypes/direction measurements = Phase 1.1 proper.)
- Variable-length reads work: `MATCH (a {id: $a})-[:R*1..2]->(b) RETURN b.id`.
- **UNWIND batching is narrow** (probed): batched edge CREATE takes one fixed
  relationship type with **no properties**; `UNWIND … MATCH` must end in RETURN
  or DELETE (no batched SET); the only batch-read shape is
  `UNWIND $rows AS row MATCH (s {id: row.sid})-[e:TYPE]->(x) RETURN row.sid, x.id`
  — exactly two unsorted projections, second must be `destination.id`, the
  destination pattern unconstrained. Adjacency only — edge props need per-row
  singles. Node ids in UNWIND patterns must read a row-map field (`row.sid`,
  never a bare scalar).
- **Edge supersession round-trips as designed**: `MATCH (s {id})-[n:NEEDS]->(c {id})
  WHERE n.valid_to > $now SET n.valid_to = $now` works; live-edge reads filter it
  out; history reads (no WHERE) still see it.
- One transient `mutation engine` rejection was observed once right after
  restart-heavy probing and did not reproduce; if a write 50N42s spuriously,
  retry once before digging.

## Phase 1.1 probe results (2026-08-16, `engine/bench/probe11.py`)

Everything below was measured live against the pinned image; the 0.2 findings
above all still hold.

**Now verified working (upgrades over the 0.2 assumptions):**

- Multi-assignment `SET`: `MATCH (n {id}) SET n.a = $a, n.b = $b, …` — one
  statement per node-prop write, not one per prop.
- Compound `WHERE` with `AND` (e.g. `e.valid_to > $now AND e.about = $b`).
- `WHERE` on destination-node props (`… WHERE x.valid_to > $now`).
- Destination-node props in one-hop RETURNs (4–7 projections fine):
  `MATCH (s {id})-[e:HOLDS]->(x) RETURN x.id, x.value, x.evidence, …`.
- `ORDER BY e.t DESC LIMIT 1` and `EXPLAIN` prefixes.

**Now verified NOT working:**

- Aggregates: `count(x)` is rejected — decision 2's "aggregates only
  count/sum/avg/collect" is optimistic; ALL counting/summing lives in Python.
- `algo.SPpaths` heterogeneous relTypes lists are *accepted* but the traversal
  is strictly direction-following: any path with a reversed hop (all of our
  motifs, e.g. `PREFERS→concept←CLAIMS`) returns 0 paths. Swapped-end calls on
  a directed edge also return 0. → **Route B everywhere** (CONTRACT.md §Routing).
- Multi-pattern `CREATE` with props (comma-separated patterns) and repeated
  `CREATE` clauses: both rejected. Batched UNWIND CREATE stays propless-only.
- Batched `UNWIND … DELETE` requires BOTH endpoints anchored
  (`MATCH (s {id: row.a})-[e:R]->(x {id: row.b}) DELETE e`); source-only
  anchoring is rejected ("UNWIND batch node requires an id property").

**Write throughput (the one hard limit — architectural, closed):**
prop-carrying single-statement writes commit at **~200–230/s** regardless of
transport (Bolt/HTTP), parallelism (1 vs 16 sessions), or consistency level —
each mutation goes through the single admitted writer's commit path
(~4–5ms/commit). Propless UNWIND batches commit ~20,000 edges/s (one commit
per statement), so the cost is per-STATEMENT, not per-edge. Reads are ~0.3ms
and parallelize fine.

`SLATEDB_AWAIT_DURABLE_WRITES=false` was tried (container recreated with the
env var, re-measured 2026-08-16): **inert**. The startup log's slatedb
settings dump shows `flush_interval: 1ms` and no `await_durable_writes` key —
in slatedb that flag is per-write `WriteOptions` chosen by graph-node's code,
not an env-configurable Setting. The compose file keeps a comment noting this
so nobody re-tries it.

Consequence for PLAN Phase-1's "10k-event batch ≤ ~10s": measured **~47s**;
the target predates this probing and is amended in PLAN.md. Real per-tick
load (~300–500 events ≈ 2s/tick) fits the Phase-3 (≤1.5 min) and S1 (≤4 min)
wall-clock budgets. Pre-agreed escalations if Phase 3 measures over budget:
(1) write-behind overlap — pipeline episodic writes during the mind/
consolidate compute of the same tick, flush barrier at tick end; (2) last
resort, tick-partitioned relationship types (e.g. `SAW_T7`) for the
{t,run}-only episodic edges, batched propless at 20k/s, with t recovered
from the rel name and payload-carrying events (BOUGHT/PRICE_SEEN/EXPERIENCED)
staying as singles — ~90% of volume batches, ≈5s per 10k.
