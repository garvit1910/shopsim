# /infra — HydraDB & compose (Phase 0.2 / Phase 9, owner: Atishay)

To land here per the master plan:

- Exact HydraDB run command (pinned image digest), with:
  - pre-created `store/` + `cache/` dirs, `--user "$(id -u):$(id -g)"`
  - `GRAPH_ALLOW_PLAINTEXT=true` locally, auth token file
  - ports 7687 (Bolt) / 8443 (HTTP) / 9090
- Bolt + HTTP round-trip smoke script; durability check across `docker restart`
- `/readyz` health check
- Final `docker compose up` (hydradb + engine + web) for Phase 9

Phase 0.2 checkpoints (Atishay): CREATE→MATCH round-trips over Bolt and HTTP;
survives restart; run command saved here.
