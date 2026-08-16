"""Phase 0.2 smoke: CREATE->MATCH round-trip over Bolt AND HTTP, plus durability.

Usage (from /engine so the neo4j driver is importable):
    uv run python ../infra/smoke.py write            # MERGE one node per protocol
    uv run python ../infra/smoke.py verify           # MATCH both back over BOTH protocols
    uv run python ../infra/smoke.py all              # write + verify
    uv run python ../infra/smoke.py all --probe-sppaths   # + Phase 1.1 pre-probe (a)

Durability proof: `all` -> `docker compose restart hydradb` -> readyz -> `verify`.

Constraints honored so this doubles as an API probe (PLAN decisions 1-7):
one statement per request; MERGE on id only, then SET; integer ids in the
scratch range 900_000_000+ (outside every Appendix-A block).
"""

from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.request

import neo4j

HERE = pathlib.Path(__file__).resolve().parent
TOKEN = (HERE / "hydradb-data" / "auth-token").read_text().strip()

BOLT_URI = "bolt://127.0.0.1:7687"
HTTP_URL = "http://127.0.0.1:8443/v1/graphs/default/query"  # plain http: GRAPH_ALLOW_PLAINTEXT
NAMESPACE = "default"
CELL = "cell-0"

BOLT_NODE_ID = 900_000_001  # written via Bolt
HTTP_NODE_ID = 900_000_002  # written via HTTP

# Try-chain for the undocumented Bolt token scheme; the winner is recorded in
# infra/README.md and is what HydraMem (Phase 1) will use.
AUTH_CANDIDATES = [
    ("bearer_auth(token)", lambda: neo4j.bearer_auth(TOKEN)),
    ('basic_auth("", token)', lambda: neo4j.basic_auth("", TOKEN)),
    ("basic_auth(token, token)", lambda: neo4j.basic_auth(TOKEN, TOKEN)),
]


def bolt_driver() -> tuple[neo4j.Driver, str]:
    last: Exception | None = None
    for name, make in AUTH_CANDIDATES:
        driver = neo4j.GraphDatabase.driver(BOLT_URI, auth=make())
        try:
            driver.verify_connectivity()
            return driver, name
        except Exception as exc:  # try the next scheme
            last = exc
            driver.close()
    raise SystemExit(f"FAIL bolt auth: no scheme in try-chain worked; last error: {last}")


def bolt_run(driver: neo4j.Driver, query: str, **params) -> list[dict]:
    with driver.session() as session:
        return [dict(r) for r in session.run(query, **params)]


def http_run(query: str, params: dict | None = None, consistency: str = "strong") -> list:
    """One statement per request. Tries a `params` body key once; on rejection
    falls back to inlining literals (ints only in our scratch queries)."""
    body: dict = {"cell_id": CELL, "query": query, "consistency": consistency}
    if params:
        body["params"] = params
    req = urllib.request.Request(
        HTTP_URL,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "X-Graph-Namespace": NAMESPACE,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as exc:
        if params:  # params key may be unsupported: inline and retry once
            inlined = query
            for k, v in params.items():
                inlined = inlined.replace(f"${k}", json.dumps(v))
            return http_run(inlined, None, consistency)
        raise SystemExit(f"FAIL http: {exc.code} {exc.read().decode()[:500]}")
    # response may be a JSON document or NDJSON lines
    try:
        doc = json.loads(raw)
        return doc if isinstance(doc, list) else [doc]
    except json.JSONDecodeError:
        return [json.loads(line) for line in raw.splitlines() if line.strip()]


def write() -> None:
    # HydraDB write model, discovered live (record of Phase 0.2 probing):
    #  - bare-node CREATE/MERGE is unsupported ("only one-hop edge patterns are
    #    executable"); nodes exist implicitly by integer id
    #  - node props are written via MATCH (n {id}) SET ...
    #  - MERGE/CREATE work only on one-hop edge patterns (inline props OK)
    #  - MERGE followed by SET in one statement is rejected: sequence client-side
    driver, scheme = bolt_driver()
    bolt_run(driver, "MATCH (n {id: $id}) SET n.v = $v", id=BOLT_NODE_ID, v=1)
    bolt_run(
        driver,
        "MERGE (a {id: $a})-[:SMOKE_EDGE {t: $t}]->(b {id: $b})",
        a=BOLT_NODE_ID,
        b=HTTP_NODE_ID,
        t=42,
    )
    driver.close()
    print(f"PASS write/bolt: SET node {BOLT_NODE_ID} + MERGE edge (auth scheme: {scheme})")
    http_run("MATCH (n {id: $id}) SET n.v = $v", {"id": HTTP_NODE_ID, "v": 2})
    print(f"PASS write/http: SET node {HTTP_NODE_ID}")


def verify() -> None:
    driver, scheme = bolt_driver()
    ok = True
    for nid in (BOLT_NODE_ID, HTTP_NODE_ID):
        rows = bolt_run(driver, "MATCH (n {id: $id}) RETURN n.v AS v", id=nid)
        got = bool(rows) and rows[0]["v"] is not None
        ok &= got
        print(f"{'PASS' if got else 'FAIL'} verify/bolt: node {nid} -> {rows}")
    edge = bolt_run(
        driver,
        "MATCH (a {id: $a})-[e:SMOKE_EDGE]->(b) RETURN e.t AS t, b.id AS bid",
        a=BOLT_NODE_ID,
    )
    got = bool(edge) and edge[0]["t"] == 42
    ok &= got
    print(f"{'PASS' if got else 'FAIL'} verify/bolt: SMOKE_EDGE with props -> {edge}")
    driver.close()
    for nid in (BOLT_NODE_ID, HTTP_NODE_ID):
        docs = http_run(f"MATCH (n {{id: {nid}}}) RETURN n.v AS v")
        # response doc shape: {"columns": ["v"], "rows": [[{"type": ..., "value": ...}]], ...}
        values = [
            cell.get("value")
            for doc in docs
            for row in doc.get("rows", [])
            for cell in row
            if isinstance(cell, dict)
        ]
        got = bool(values) and values[0] is not None
        ok &= got
        print(f"{'PASS' if got else 'FAIL'} verify/http: node {nid} -> v = {values}")
    if not ok:
        raise SystemExit("FAIL verify: at least one round-trip missing")
    print(f"PASS verify: both nodes visible over both protocols (bolt auth: {scheme})")


def probe_sppaths() -> None:
    """Phase 1.1 pre-probe (a): does algo.SPpaths exist and accept relTypes?
    Existence/shape only — latency measurement belongs to Phase 1.1 proper."""
    driver, _ = bolt_driver()
    # NOTE: "MATCH ... MERGE ..." compounds are rejected ("write query is not
    # executable by the mutation engine") — writes must be self-contained
    # one-hop patterns anchored on id.
    bolt_run(
        driver,
        "MERGE (a {id: $a})-[:SMOKE_EDGE]->(b {id: $b})",
        a=BOLT_NODE_ID,
        b=HTTP_NODE_ID,
    )
    try:
        # Working form, discovered live: bare CALL with integer node ids in the
        # config map. Any MATCH prefix before CALL is rejected ("query transport
        # cannot authorize an unsupported Cypher clause").
        rows = bolt_run(
            driver,
            "CALL algo.SPpaths({sourceNode: $a, targetNode: $b, "
            "relTypes: ['SMOKE_EDGE'], maxLen: 4}) YIELD path RETURN path",
            a=BOLT_NODE_ID,
            b=HTTP_NODE_ID,
        )
        print(f"PROBE SPpaths: OK — returned {len(rows)} path(s)")
    except Exception as exc:
        print(f"PROBE SPpaths: rejected -> {type(exc).__name__}: {exc}")
    finally:
        driver.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    phase = args[0] if args else "all"
    if phase in ("write", "all"):
        write()
    if phase in ("verify", "all"):
        verify()
    if "--probe-sppaths" in args:
        probe_sppaths()
