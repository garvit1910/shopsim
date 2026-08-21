#!/usr/bin/env bash
# Assemble the Railway upload tree for infra/railway/Dockerfile.
#
# Why a staging tree instead of `railway up` on the repo: the dashboard's state
# — /runs/ (registry, events, results, experiment run_configs) and the live
# HydraDB store — is gitignored, and `railway up` honours .gitignore. Copying an
# explicit allowlist into a clean directory makes "what ships" a thing you can
# `ls`, and keeps .env.local, .venv, node_modules and the 3.5 GB of store
# archives out by construction rather than by pattern.
#
# Usage: infra/railway/stage.sh [STAGE_DIR]     (default: $TMPDIR/shopsim-railway-stage)
# Then:  railway up "$STAGE_DIR" --path-as-root --service shopsim --ci
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
STAGE="${1:-${TMPDIR:-/tmp}/shopsim-railway-stage}"
case "$STAGE" in
  */shopsim-railway-stage) ;;
  *) echo "refusing to stage into '$STAGE' — the directory is wiped first, so its name must end in shopsim-railway-stage" >&2; exit 2 ;;
esac

cd "$REPO"
for must in runs/registry.json infra/hydradb-data/auth-token infra/hydradb-data/store infra/hydradb-data/cache web/package-lock.json engine/pyproject.toml; do
  [ -e "$must" ] || { echo "missing $must — is this the shopsim repo with a live store?" >&2; exit 1; }
done

rm -rf "$STAGE"
mkdir -p "$STAGE/engine" "$STAGE/infra/railway" "$STAGE/infra/hydradb-data"

X=(--exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store')
rsync -a engine/pyproject.toml "$STAGE/engine/"
rsync -a "${X[@]}" engine/shopsim "$STAGE/engine/"
rsync -a "${X[@]}" fixtures "$STAGE/"
rsync -a "${X[@]}" eval "$STAGE/"
rsync -a "${X[@]}" runs "$STAGE/"
rsync -a "${X[@]}" --exclude node_modules --exclude .next --exclude '*.tsbuildinfo' \
      --exclude next-env.d.ts --exclude .gitignore web "$STAGE/"
rsync -a "${X[@]}" infra/railway/ "$STAGE/infra/railway/"
cp infra/hydradb-data/auth-token "$STAGE/infra/hydradb-data/auth-token"

# ---- the live store: snapshot, then prove the snapshot was stable -----------
# graph-node keeps touching the store after a run (lease renewals, compaction).
# Copy, then dry-run the same copy again: if anything data-bearing would change,
# the first pass straddled a write — stop HydraDB (~10 s), copy at rest, start it.
snap() {
  rsync -a --delete infra/hydradb-data/store/ "$STAGE/infra/hydradb-data/store/"
  rsync -a --delete infra/hydradb-data/cache/ "$STAGE/infra/hydradb-data/cache/"
}
drift() {
  { rsync -a --delete --dry-run --itemize-changes infra/hydradb-data/store/ "$STAGE/infra/hydradb-data/store/"
    rsync -a --delete --dry-run --itemize-changes infra/hydradb-data/cache/ "$STAGE/infra/hydradb-data/cache/"
  } | grep -E '^(>f|\*deleting|cd\+)' | grep -v '_writer_leases' || true
}
snap
CHANGED="$(drift)"
if [ -n "$CHANGED" ]; then
  echo "store changed while copying:"; echo "$CHANGED" | sed 's/^/  /'
  echo "stopping local HydraDB for a consistent copy (restarted right after)"
  docker compose -f infra/docker-compose.yml stop hydradb
  snap
  CHANGED="$(drift)"
  docker compose -f infra/docker-compose.yml start hydradb
  [ -z "$CHANGED" ] || { echo "store still drifting with HydraDB stopped — giving up" >&2; exit 1; }
  echo "store copied at rest; local HydraDB started again"
else
  echo "store snapshot stable (no data-bearing change between passes)"
fi
# the lease file is per-process state; the baked copy is whatever was last written
find "$STAGE/infra/hydradb-data" -name '.DS_Store' -delete

cp infra/railway/Dockerfile "$STAGE/Dockerfile"
cp infra/railway/railway.json "$STAGE/railway.json"

# ---- what ships ------------------------------------------------------------
if find "$STAGE" \( -name '.env*' -o -name '.venv' -o -name 'node_modules' -o -name '*-archive-*' -o -name '.git' \) | grep -q .; then
  echo "refusing: forbidden content found in stage" >&2
  find "$STAGE" \( -name '.env*' -o -name '.venv' -o -name 'node_modules' -o -name '*-archive-*' -o -name '.git' \) >&2
  exit 1
fi
echo
echo "stage: $STAGE"
echo "files: $(find "$STAGE" -type f | wc -l | tr -d ' ')   size: $(du -sh "$STAGE" | cut -f1)"
du -sh "$STAGE"/runs "$STAGE"/fixtures "$STAGE"/eval "$STAGE"/web "$STAGE"/engine "$STAGE"/infra/hydradb-data | sed 's/^/  /'
RUN_DIRS="$(find "$STAGE"/runs -maxdepth 1 -type d -name 'r[0-9]*' | sort)"
echo "runs: $(printf "%s\n" "$RUN_DIRS" | grep -c .) run dirs, newest $(basename "$(printf "%s\n" "$RUN_DIRS" | tail -1)")"
