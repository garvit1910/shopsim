#!/usr/bin/env bash
# ShopSim on Railway — process supervisor for the one-container deploy.
#
# Order matters only for HydraDB readiness: the engine opens the store lazily
# per request, so it starts regardless, but waiting for /readyz first means the
# very first Inspector click after a deploy does not race the store's startup.
#
# Failure policy: engine or web dying is fatal (exit 1 -> Railway restarts the
# trio). HydraDB dying is NOT fatal: everything on the Market, Graph, Mind and
# Learnings pages is a disk read; only the shopper drill-down needs the store,
# and the UI already renders its 503 as "HydraDB unreachable".
set -u
cd /repo

log() { printf '[entrypoint] %s\n' "$*"; }

HYDRA="" ENGINE="" WEB=""
shutdown() {
  log "signal received — stopping children"
  kill $HYDRA $ENGINE $WEB 2>/dev/null
  wait
  exit 0
}
trap shutdown TERM INT

log "starting HydraDB (graph-node), store=$LOCAL_PATH"
/usr/local/bin/graph-node &
HYDRA=$!

for i in $(seq 1 120); do
  if curl -fsS http://127.0.0.1:9090/readyz >/dev/null 2>&1; then
    log "HydraDB ready after ${i}s"
    break
  fi
  if ! kill -0 "$HYDRA" 2>/dev/null; then
    log "WARNING: graph-node exited during startup — continuing without the store"
    break
  fi
  if [ "$i" -eq 120 ]; then
    log "WARNING: HydraDB not ready after 120s — continuing; shopper reads will 503"
  fi
  sleep 1
done

log "starting engine API on 127.0.0.1:8000"
( cd /repo/engine && exec .venv/bin/python -m shopsim.runner serve \
    --config ../fixtures/run-configs/scripted-run-1.json --port 8000 ) &
ENGINE=$!

log "starting web on :${PORT:-3000}"
( cd /repo/web && exec node node_modules/next/dist/bin/next start -p "${PORT:-3000}" ) &
WEB=$!

# Block until something exits. A HydraDB exit is logged and the other two keep
# serving; an engine/web exit takes the container down so the platform restarts it.
wait -n $HYDRA $ENGINE $WEB 2>/dev/null
if kill -0 "$ENGINE" 2>/dev/null && kill -0 "$WEB" 2>/dev/null; then
  log "WARNING: HydraDB exited; web + engine continue (Inspector will 503)"
  wait -n $ENGINE $WEB 2>/dev/null
fi
log "engine or web exited — stopping the rest so the platform restarts the trio"
kill $HYDRA $ENGINE $WEB 2>/dev/null
wait
exit 1
