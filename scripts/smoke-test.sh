#!/usr/bin/env bash
# Smoke test: build the stack, verify core services are healthy, test portal auth.
# Usage: ./scripts/smoke-test.sh
# Requires: docker compose, curl, python3 with python-jose
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

COMPOSE="docker compose"
PASS=0
FAIL=0
TESTS=()

pass() { PASS=$((PASS + 1)); TESTS+=("PASS: $1"); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); TESTS+=("FAIL: $1"); echo "  FAIL: $1"; }

cleanup() {
    echo
    echo "==> Tearing down..."
    $COMPOSE down --volumes --remove-orphans --timeout 5 2>/dev/null || true
}
trap cleanup EXIT

# ── Build + Start core services ──────────────────────────────────────────────
echo "==> Building and starting couchdb + portal..."
$COMPOSE up -d --build couchdb portal

# ── Wait for CouchDB health ─────────────────────────────────────────────────
echo "==> Waiting for CouchDB healthcheck..."
COUCHDB_READY=false
for i in $(seq 1 30); do
    if $COMPOSE exec -T couchdb curl -fsu "${COUCHDB_USER:-admin}:${COUCHDB_PASSWORD:-livesync-dev-2026}" http://localhost:5984/_up >/dev/null 2>&1; then
        COUCHDB_READY=true
        break
    fi
    sleep 2
done

echo
echo "=== Test Results ==="

if $COUCHDB_READY; then
    pass "CouchDB is healthy"
else
    fail "CouchDB did not become healthy within 60s"
fi

# ── Wait for Portal health ───────────────────────────────────────────────────
echo -n "  Waiting for portal..."
PORTAL_READY=false
for i in $(seq 1 15); do
    if curl -sf http://localhost:8000/healthz >/dev/null 2>&1; then
        PORTAL_READY=true
        break
    fi
    sleep 2
done
echo

if $PORTAL_READY; then
    pass "Portal healthcheck responds"
else
    fail "Portal did not become healthy within 30s"
fi

# ── Portal auth tests ───────────────────────────────────────────────────────
# Test: no auth header → 401
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/)
if [ "$HTTP_CODE" = "401" ]; then
    pass "Portal returns 401 without auth header"
else
    fail "Portal returned $HTTP_CODE without auth header (expected 401)"
fi

# Create databases (registry + passphrases) before any authenticated portal
# request — on a fresh CouchDB, / queries the registry and 500s without them,
# which aborts the whole script under set -e.
echo "==> Running couchdb-init..."
$COMPOSE run --rm couchdb-init 2>/dev/null

# Generate a fake JWT using our script
TOKEN=$(python3 "$SCRIPT_DIR/fake-jwt.py" --email test@example.com --groups eng,livesync-admin 2>/dev/null | head -2 | tail -1)

if [ -n "$TOKEN" ]; then
    pass "fake-jwt.py generates a token"
else
    fail "fake-jwt.py did not produce a token"
fi

# Test: valid JWT is accepted. / renders the dashboard (200) or redirects
# first-login users to /welcome (302) — either proves the JWT was honored.
if [ -n "$TOKEN" ]; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "x-amzn-oidc-data: $TOKEN" http://localhost:8000/api/vaults)
    if [ "$HTTP_CODE" = "200" ]; then
        pass "Portal accepts valid JWT (api/vaults 200)"
    else
        fail "Portal returned $HTTP_CODE for valid JWT (expected 200)"
    fi

    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "x-amzn-oidc-data: $TOKEN" http://localhost:8000/admin/)
    if [ "$HTTP_CODE" = "200" ]; then
        pass "Portal detects livesync-admin group (admin page 200)"
    else
        fail "Admin page returned $HTTP_CODE for livesync-admin JWT (expected 200)"
    fi
fi

# Test: non-admin user
TOKEN_USER=$(python3 "$SCRIPT_DIR/fake-jwt.py" --email regular@example.com --groups eng 2>/dev/null | head -2 | tail -1)
if [ -n "$TOKEN_USER" ]; then
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "x-amzn-oidc-data: $TOKEN_USER" http://localhost:8000/admin/)
    if [ "$HTTP_CODE" = "403" ]; then
        pass "Non-admin user denied admin page (403)"
    else
        fail "Admin page returned $HTTP_CODE for non-admin JWT (expected 403)"
    fi
fi

# Test: invalid token → 401
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "x-amzn-oidc-data: garbage" http://localhost:8000/)
if [ "$HTTP_CODE" = "401" ]; then
    pass "Portal returns 401 for invalid token"
else
    fail "Portal returned $HTTP_CODE for invalid token (expected 401)"
fi

# ── Local auth (HTTP Basic) tests ────────────────────────────────────────────
# The portal defaults to AUTH_MODE=local in docker-compose with users.yaml mounted.

# Test: valid local admin via HTTP Basic Auth
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -u "admin@localhost:admin" http://localhost:8000/api/vaults)
if [ "$HTTP_CODE" = "200" ]; then
    pass "Local auth: admin login via HTTP Basic"
else
    fail "Local auth: api/vaults returned $HTTP_CODE for admin (expected 200)"
fi

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -u "admin@localhost:admin" http://localhost:8000/admin/)
if [ "$HTTP_CODE" = "200" ]; then
    pass "Local auth: admin can access admin page"
else
    fail "Local auth: admin page returned $HTTP_CODE for admin (expected 200)"
fi

# Test: valid local regular user
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -u "user@localhost:user" http://localhost:8000/admin/)
if [ "$HTTP_CODE" = "403" ]; then
    pass "Local auth: regular user not admin (403 on admin page)"
else
    fail "Local auth: admin page returned $HTTP_CODE for regular user (expected 403)"
fi

# Test: wrong password → 401
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -u "admin@localhost:wrong" http://localhost:8000/)
if [ "$HTTP_CODE" = "401" ]; then
    pass "Local auth: wrong password returns 401"
else
    fail "Local auth: wrong password returned $HTTP_CODE (expected 401)"
fi

# ── CouchDB init check ──────────────────────────────────────────────────────
COUCH_URL="http://${COUCHDB_USER:-admin}:${COUCHDB_PASSWORD:-livesync-dev-2026}@localhost:5984"
for db in _users _replicator obsidian-wiki livesync-registry livesync-passphrases livesync-passwords; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$COUCH_URL/$db")
    if [ "$HTTP_CODE" = "200" ]; then
        pass "CouchDB database '$db' exists"
    else
        fail "CouchDB database '$db' returned $HTTP_CODE (expected 200)"
    fi
done

# ── Phase 7: Vault API tests ────────────────────────────────────────────────
# Create a vault via the API
RESPONSE=$(curl -s -u "admin@localhost:admin" -X POST \
    -H "Content-Type: application/json" \
    -d '{"name":"smoketest"}' \
    http://localhost:8000/api/vaults)
VAULT_NAME=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('name',''))" 2>/dev/null)
if [ "$VAULT_NAME" = "obsidian_admin_smoketest" ]; then
    pass "Vault API: created vault 'obsidian_admin_smoketest'"
else
    fail "Vault API: create returned name='$VAULT_NAME' (expected obsidian_admin_smoketest). Response: $RESPONSE"
fi

# Verify the CouchDB database was created
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$COUCH_URL/obsidian_admin_smoketest")
if [ "$HTTP_CODE" = "200" ]; then
    pass "Vault API: CouchDB database 'obsidian_admin_smoketest' exists"
else
    fail "Vault API: CouchDB database 'obsidian_admin_smoketest' returned $HTTP_CODE"
fi

# Verify _security was set on the vault
SECURITY=$(curl -s "$COUCH_URL/obsidian_admin_smoketest/_security")
SEC_ADMIN=$(echo "$SECURITY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('admins',{}).get('names',[]))" 2>/dev/null)
if echo "$SEC_ADMIN" | grep -q "admin@localhost"; then
    pass "Vault API: _security has owner as admin"
else
    fail "Vault API: _security admins='$SEC_ADMIN' (expected admin@localhost)"
fi

# List vaults — should include the one we just created
RESPONSE=$(curl -s -u "admin@localhost:admin" http://localhost:8000/api/vaults)
VAULT_COUNT=$(echo "$RESPONSE" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null)
if [ "$VAULT_COUNT" -ge 1 ]; then
    pass "Vault API: list returns $VAULT_COUNT vault(s)"
else
    fail "Vault API: list returned $VAULT_COUNT vaults (expected >= 1)"
fi

# Get vault detail
RESPONSE=$(curl -s -u "admin@localhost:admin" http://localhost:8000/api/vaults/obsidian_admin_smoketest)
OWNER=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('owner',''))" 2>/dev/null)
if [ "$OWNER" = "admin@localhost" ]; then
    pass "Vault API: detail shows correct owner"
else
    fail "Vault API: detail returned owner='$OWNER'"
fi

# Get setup URI
RESPONSE=$(curl -s -u "admin@localhost:admin" http://localhost:8000/api/vaults/obsidian_admin_smoketest/setup-uri)
SETUP_URI=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('setup_uri',''))" 2>/dev/null)
if echo "$SETUP_URI" | grep -q "^obsidian://setuplivesync?"; then
    pass "Vault API: setup URI starts with obsidian://setuplivesync?"
else
    fail "Vault API: setup URI='$SETUP_URI'"
fi

# Get nonexistent vault → 404
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -u "admin@localhost:admin" http://localhost:8000/api/vaults/nonexistent)
if [ "$HTTP_CODE" = "404" ]; then
    pass "Vault API: nonexistent vault returns 404"
else
    fail "Vault API: nonexistent vault returned $HTTP_CODE (expected 404)"
fi

# ── Phase 8: Multi-vault sync ────────────────────────────────────────────────
# The obsidian_admin_smoketest created above should be discovered by sync-multi and synced
# to /data/vaults/obsidian_admin_smoketest/. Since the CouchDB database is empty (no Obsidian
# client pushed content), we verify that sync-multi at least bootstraps the
# vault directory and creates settings.

# Reuse an existing livesync-cli:local image unless missing or REBUILD_CLI=1.
# (The from-scratch build currently fails on upstream npm drift in the
# vendored obsidian-livesync submodule.)
if [ "${REBUILD_CLI:-0}" = "1" ] || ! docker image inspect livesync-cli:local >/dev/null 2>&1; then
    echo "==> Building livesync-cli base image..."
    docker buildx build --platform linux/$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/') \
        -f livesync-cli.Dockerfile \
        -t livesync-cli:local --load \
        vendor/obsidian-livesync 2>&1 | tail -3
else
    echo "==> Using existing livesync-cli:local image (REBUILD_CLI=1 to rebuild)"
fi

echo "==> Starting sync-multi..."
$COMPOSE up -d --build sync-multi 2>/dev/null

# Wait for sync-multi to complete at least one cycle
echo -n "  Waiting for sync-multi bootstrap..."
SYNC_OK=false
for i in $(seq 1 20); do
    # Check if the vault directory was created inside the container
    if $COMPOSE exec -T sync-multi test -f "/data/vaults/obsidian_admin_smoketest/.livesync/settings.json" 2>/dev/null; then
        SYNC_OK=true
        break
    fi
    sleep 3
    echo -n "."
done
echo

if $SYNC_OK; then
    pass "Multi-vault sync: bootstrapped obsidian_admin_smoketest settings"
else
    fail "Multi-vault sync: obsidian_admin_smoketest settings not found after 60s"
    # Show logs for debugging
    echo "  --- sync-multi logs ---"
    $COMPOSE logs --tail=20 sync-multi 2>/dev/null || true
    echo "  ---"
fi

# Verify the vault directory exists
if $COMPOSE exec -T sync-multi test -d "/data/vaults/obsidian_admin_smoketest" 2>/dev/null; then
    pass "Multi-vault sync: vault directory exists at /data/vaults/obsidian_admin_smoketest"
else
    fail "Multi-vault sync: vault directory not found"
fi

# Create a second vault and verify sync-multi picks it up on next cycle
RESPONSE=$(curl -s -u "admin@localhost:admin" -X POST \
    -H "Content-Type: application/json" \
    -d '{"name":"smoketest2"}' \
    http://localhost:8000/api/vaults)
VAULT2_NAME=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('name',''))" 2>/dev/null)
if [ "$VAULT2_NAME" = "obsidian_admin_smoketest2" ]; then
    pass "Multi-vault sync: created second vault 'obsidian_admin_smoketest2'"
else
    fail "Multi-vault sync: could not create second vault"
fi

# Wait for sync-multi to discover and bootstrap the second vault
echo -n "  Waiting for sync-multi to discover obsidian_admin_smoketest2..."
SYNC2_OK=false
for i in $(seq 1 25); do
    if $COMPOSE exec -T sync-multi test -d "/data/vaults/obsidian_admin_smoketest2" 2>/dev/null; then
        SYNC2_OK=true
        break
    fi
    sleep 3
    echo -n "."
done
echo

if $SYNC2_OK; then
    pass "Multi-vault sync: discovered and bootstrapped obsidian_admin_smoketest2"
else
    fail "Multi-vault sync: obsidian_admin_smoketest2 not discovered after 75s"
    echo "  --- sync-multi logs ---"
    $COMPOSE logs --tail=30 sync-multi 2>/dev/null || true
    echo "  ---"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo
echo "=== Summary ==="
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo

if [ "$FAIL" -gt 0 ]; then
    echo "FAILED"
    exit 1
fi
echo "ALL TESTS PASSED"
