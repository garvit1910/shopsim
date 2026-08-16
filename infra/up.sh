#!/usr/bin/env sh
# Phase 0.2: bring up HydraDB with pre-created dirs + auth token (PLAN decision 9).
set -eu
cd "$(dirname "$0")"
mkdir -p hydradb-data/store hydradb-data/cache
[ -f hydradb-data/auth-token ] || printf '%s\n' 'local-development-token-32-bytes' > hydradb-data/auth-token
DOCKER_UID="$(id -u)" DOCKER_GID="$(id -g)" docker compose up -d "$@"
