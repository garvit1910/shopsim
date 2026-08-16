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
- One transient `mutation engine` rejection was observed once right after
  restart-heavy probing and did not reproduce; if a write 50N42s spuriously,
  retry once before digging.
