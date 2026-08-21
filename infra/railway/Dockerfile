# syntax=docker/dockerfile:1
# ShopSim on Railway — ONE container, three processes: HydraDB (graph-node) +
# the engine API (uvicorn on 127.0.0.1:8000) + Next (on $PORT). It mirrors the
# laptop's localhost layout exactly, so every default in the code holds
# (bolt://127.0.0.1:7687, SIM_API_URL -> 127.0.0.1:8000, the auth-token path).
#
# The build context is NOT the repo: it is the staging tree assembled by
# infra/railway/stage.sh, because the state that makes the dashboard non-empty
# (/runs/ and infra/hydradb-data/{store,cache}) is gitignored and `railway up`
# honours .gitignore. The store is baked into the image on purpose: a restart
# or redeploy resets to this exact snapshot — no volume, no seeding, no run.

# ---- web: build on glibc so @next/swc-linux-x64-gnu matches the runtime ----
FROM node:22-bookworm-slim AS webbuild
WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ---- runtime: the pinned HydraDB image (infra/docker-compose.yml) + python + node ----
FROM ghcr.io/hydra-db/hydradb@sha256:db78309a233be54662db29744047e985a39b51c45a270d1a1f47c31a62cdb709
USER root
ENV DEBIAN_FRONTEND=noninteractive
# procps: the engine's /engine/busy and stale-run sweep shell out to `ps`
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-venv procps curl ca-certificates bash \
 && rm -rf /var/lib/apt/lists/*
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node

# /repo/{engine,fixtures,eval,runs,infra,web}: find_repo_root() looks for
# fixtures/ + engine/ siblings, and run configs resolve against that root.
WORKDIR /repo
COPY engine/pyproject.toml /repo/engine/pyproject.toml
COPY engine/shopsim /repo/engine/shopsim
COPY infra/railway/requirements.txt /repo/infra/railway/requirements.txt
RUN python3 -m venv /repo/engine/.venv \
 && /repo/engine/.venv/bin/pip install --no-cache-dir -r /repo/infra/railway/requirements.txt \
 && /repo/engine/.venv/bin/pip install --no-cache-dir --no-deps /repo/engine

COPY fixtures /repo/fixtures
COPY eval /repo/eval
COPY runs /repo/runs
COPY infra/hydradb-data /repo/infra/hydradb-data

COPY --from=webbuild /app/.next /repo/web/.next
COPY --from=webbuild /app/node_modules /repo/web/node_modules
COPY --from=webbuild /app/package.json /app/next.config.mjs /repo/web/
# `next start` serves public/ from disk — without this the 05 Mind head is a 404
COPY --from=webbuild /app/public /repo/web/public

COPY infra/railway/entrypoint.sh /repo/infra/railway/entrypoint.sh
RUN chmod +x /repo/infra/railway/entrypoint.sh

# HydraDB flags: the docker-compose.yml block verbatim, paths moved under /repo.
ENV CLOUD_PROVIDER=local \
    LOCAL_PATH=/repo/infra/hydradb-data/store \
    GRAPH_DATA_CACHE_DIR=/repo/infra/hydradb-data/cache \
    GRAPH_AUTH_TOKEN_FILE=/repo/infra/hydradb-data/auth-token \
    GRAPH_NAMESPACE=default \
    GRAPH_ID=default \
    GRAPH_CELL_ID=cell-0 \
    GRAPH_CELLS=cell-0 \
    GRAPH_NODE_ID=node-0 \
    GRAPH_BOLT_NODE_ADDRESSES=node-0=127.0.0.1:7687 \
    GRAPH_ADVERTISED_BOLT_ADDR=127.0.0.1:7687 \
    GRAPH_ALLOW_PLAINTEXT=true \
    RUST_MIN_STACK=33554432 \
    RUST_LOG=info
# Engine + web. The token-file override is needed because a non-editable pip
# install cannot walk up from site-packages to /repo/infra (hydramem/config.py).
ENV SHOPSIM_HYDRA_URI=bolt://127.0.0.1:7687 \
    SHOPSIM_HYDRA_TOKEN_FILE=/repo/infra/hydradb-data/auth-token \
    SIM_API_URL=http://127.0.0.1:8000 \
    NODE_ENV=production \
    PORT=3000

EXPOSE 3000
ENTRYPOINT ["/repo/infra/railway/entrypoint.sh"]
