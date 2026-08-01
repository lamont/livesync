#!/usr/bin/env bash
# Chain test: LiveSync endpoint (CouchDB) -> sync-multi -> publisher -> S3 (MinIO).
#
# Proves that markdown pushed through the LiveSync protocol lands in the S3
# bucket, and that pages flagged `publish: false` in frontmatter sync to disk
# but are withheld from the bucket.
#
# Run from a git worktree, NOT the main checkout — the cleanup trap runs
# `down --volumes` and would destroy the dev stack's synced vaults.
# Usage: ./scripts/chain-test.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Hard guard: never run against the dev stack's compose project. The cleanup
# trap removes this project's volumes, which must only ever be the throwaway
# test namespace of a worktree (e.g. livesync-quartz5), never `livesync`.
COMPOSE_PROJECT="$(basename "$PROJECT_DIR")"
if [ "$COMPOSE_PROJECT" = "livesync" ]; then
    echo "REFUSING to run from the main checkout ($PROJECT_DIR):" >&2
    echo "teardown would destroy the dev stack's synced vault volumes." >&2
    echo "Run from a git worktree instead." >&2
    exit 1
fi

export SYNC_INTERVAL="${SYNC_INTERVAL:-10}"
export PUBLISH_INTERVAL="${PUBLISH_INTERVAL:-10}"

COMPOSE="docker compose"
VAULT="obsidian_admin_chaintest"
PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

cleanup() {
    echo
    echo "==> Tearing down..."
    $COMPOSE down --volumes --remove-orphans --timeout 5 2>/dev/null || true
}
# KEEP_UP=1 leaves the stack running for inspection; tear down manually with
#   docker compose down --volumes --remove-orphans   (from this worktree)
if [ "${KEEP_UP:-0}" != "1" ]; then
    trap cleanup EXIT
fi

# ── Start the stack ──────────────────────────────────────────────────────────
echo "==> Building and starting couchdb + portal + minio + publisher..."
$COMPOSE up -d --build couchdb portal minio publisher

echo "==> Waiting for CouchDB..."
for i in $(seq 1 30); do
    $COMPOSE exec -T couchdb curl -fsu "${COUCHDB_USER:-admin}:${COUCHDB_PASSWORD:-livesync-dev-2026}" \
        http://localhost:5984/_up >/dev/null 2>&1 && break
    sleep 2
done

echo "==> Running couchdb-init..."
$COMPOSE up couchdb-init >/dev/null 2>&1 || true

echo "==> Waiting for portal..."
for i in $(seq 1 15); do
    curl -sf http://localhost:8000/healthz >/dev/null 2>&1 && break
    sleep 2
done

# ── Create a vault via the portal API ────────────────────────────────────────
RESPONSE=$(curl -s -u "admin@localhost:admin" -X POST \
    -H "Content-Type: application/json" \
    -d '{"name":"chaintest"}' \
    http://localhost:8000/api/vaults)
NAME=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('name',''))" 2>/dev/null)
if [ "$NAME" = "$VAULT" ]; then
    pass "Vault '$VAULT' created via portal API"
else
    fail "Vault creation returned '$NAME' (response: $RESPONSE)"
fi

# ── Start sync-multi and wait for bootstrap ──────────────────────────────────
if [ "${REBUILD_CLI:-0}" = "1" ] || ! docker image inspect livesync-cli:local >/dev/null 2>&1; then
    echo "==> Building livesync-cli base image..."
    docker build -f vendor/obsidian-livesync/src/apps/cli/Dockerfile \
        -t livesync-cli:local --load vendor/obsidian-livesync 2>&1 | tail -3
fi
echo "==> Starting sync-multi..."
$COMPOSE up -d --build sync-multi

echo -n "  Waiting for sync-multi to bootstrap $VAULT..."
BOOTSTRAPPED=false
for i in $(seq 1 25); do
    if $COMPOSE exec -T sync-multi test -f "/data/vaults/$VAULT/.livesync/settings.json" 2>/dev/null; then
        BOOTSTRAPPED=true
        break
    fi
    sleep 3
    echo -n "."
done
echo
if $BOOTSTRAPPED; then
    pass "sync-multi bootstrapped $VAULT"
else
    fail "sync-multi did not bootstrap $VAULT in 75s"
    $COMPOSE logs --tail=20 sync-multi || true
fi

# ── Push markdown through the LiveSync endpoint as a separate client ─────────
# A second livesync-cli working dir inside the sync-multi container acts as
# the "Obsidian desktop": files exist only there, get pushed to CouchDB, and
# must round-trip through CouchDB into /data/vaults/$VAULT/ to reach S3.
echo "==> Pushing test pages through CouchDB from a client working dir..."
$COMPOSE exec -T sync-multi sh -c '
    set -e
    V='"$VAULT"'
    mkdir -p /tmp/client/.livesync
    cp "/data/vaults/$V/.livesync/settings.json" /tmp/client/.livesync/

    cat > /tmp/client/hello.md <<EOF
# Hello from the chain test

This page rode LiveSync -> CouchDB -> sync-multi -> publisher -> S3.
EOF

    cat > /tmp/client/secret.md <<EOF
---
publish: false
---
# Secret page

Syncs everywhere, but must never appear in the S3 bucket.
EOF

    cli="node /app/dist/index.cjs /tmp/client"
    $cli mirror
    # First sync may fail while the milestone lock is unaccepted; retry.
    for i in 1 2 3; do
        if $cli sync; then exit 0; fi
        sleep 5
    done
    echo "client push failed" >&2
    exit 1
' && pass "Client pushed hello.md + secret.md to CouchDB" \
  || fail "Client push through LiveSync endpoint failed"

# ── Wait for round-trip to the vaults volume ─────────────────────────────────
echo -n "  Waiting for CouchDB -> disk round-trip..."
SYNCED=false
for i in $(seq 1 25); do
    if $COMPOSE exec -T sync-multi test -f "/data/vaults/$VAULT/hello.md" 2>/dev/null; then
        SYNCED=true
        break
    fi
    sleep 3
    echo -n "."
done
echo
if $SYNCED; then
    pass "hello.md round-tripped through CouchDB to /data/vaults/$VAULT/"
else
    fail "hello.md never appeared on the vaults volume"
    $COMPOSE logs --tail=30 sync-multi || true
fi

if $COMPOSE exec -T sync-multi test -f "/data/vaults/$VAULT/secret.md" 2>/dev/null; then
    pass "secret.md synced to disk (whole vault still syncs)"
else
    fail "secret.md missing from disk — publish flag must not affect sync"
fi

# ── Verify the S3 bucket contents ────────────────────────────────────────────
echo -n "  Waiting for publisher -> S3..."
S3_KEYS=""
for i in $(seq 1 20); do
    S3_KEYS=$($COMPOSE exec -T publisher uv run --no-sync python -c "
import boto3, os
s3 = boto3.client('s3', endpoint_url=os.environ.get('S3_ENDPOINT_URL'))
resp = s3.list_objects_v2(Bucket=os.environ.get('S3_BUCKET', 'vaults'), Prefix='$VAULT/')
print('\n'.join(o['Key'] for o in resp.get('Contents', [])))
" 2>/dev/null) || true
    if echo "$S3_KEYS" | grep -q "^$VAULT/hello.md$"; then
        break
    fi
    sleep 3
    echo -n "."
done
echo

if echo "$S3_KEYS" | grep -q "^$VAULT/hello.md$"; then
    pass "hello.md published to s3://vaults/$VAULT/"
else
    fail "hello.md not found in bucket. Keys: $S3_KEYS"
    $COMPOSE logs --tail=20 publisher || true
fi

if echo "$S3_KEYS" | grep -q "^$VAULT/secret.md$"; then
    fail "secret.md leaked into the bucket despite publish: false"
else
    pass "secret.md withheld from bucket (publish: false honored)"
fi

# ── Flip the flag: unpublish hello.md and verify deletion ────────────────────
echo "==> Flipping hello.md to publish: false and re-pushing..."
$COMPOSE exec -T sync-multi sh -c '
    set -e
    printf -- "---\npublish: false\n---\n# Hello, now unpublished\n" > /tmp/client/hello.md
    cli="node /app/dist/index.cjs /tmp/client"
    $cli mirror && $cli sync
' >/dev/null 2>&1 || echo "  (re-push warning — continuing)"

echo -n "  Waiting for hello.md to be deleted from the bucket..."
GONE=false
for i in $(seq 1 20); do
    S3_KEYS=$($COMPOSE exec -T publisher uv run --no-sync python -c "
import boto3, os
s3 = boto3.client('s3', endpoint_url=os.environ.get('S3_ENDPOINT_URL'))
resp = s3.list_objects_v2(Bucket=os.environ.get('S3_BUCKET', 'vaults'), Prefix='$VAULT/')
print('\n'.join(o['Key'] for o in resp.get('Contents', [])))
" 2>/dev/null) || true
    if ! echo "$S3_KEYS" | grep -q "^$VAULT/hello.md$"; then
        GONE=true
        break
    fi
    sleep 3
    echo -n "."
done
echo
if $GONE; then
    pass "hello.md removed from bucket after flag flip"
else
    fail "hello.md still in bucket after publish: false"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo
echo "=== Summary ==="
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
[ "$FAIL" -gt 0 ] && { echo "FAILED"; exit 1; }
echo "ALL TESTS PASSED"

if [ "${KEEP_UP:-0}" = "1" ]; then
    echo
    echo "Stack left running (KEEP_UP=1):"
    echo "  Rendered wiki:  http://localhost:8000/vaults/$VAULT/  (admin@localhost / admin)"
    echo "  MinIO console:  http://localhost:9001  (minioadmin / minioadmin)"
    echo "  Tear down:      docker compose down --volumes --remove-orphans"
fi
