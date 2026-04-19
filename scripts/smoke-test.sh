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

# Generate a fake JWT using our script
TOKEN=$(python3 "$SCRIPT_DIR/fake-jwt.py" --email test@example.com --groups eng,livesync-admin 2>/dev/null | head -2 | tail -1)

if [ -n "$TOKEN" ]; then
    pass "fake-jwt.py generates a token"
else
    fail "fake-jwt.py did not produce a token"
fi

# Test: valid JWT → 200 with correct user
if [ -n "$TOKEN" ]; then
    RESPONSE=$(curl -s -H "x-amzn-oidc-data: $TOKEN" http://localhost:8000/)
    EMAIL=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('user',''))" 2>/dev/null)
    IS_ADMIN=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('is_admin',''))" 2>/dev/null)

    if [ "$EMAIL" = "test@example.com" ]; then
        pass "Portal returns correct email from JWT"
    else
        fail "Portal returned email='$EMAIL' (expected test@example.com)"
    fi

    if [ "$IS_ADMIN" = "True" ]; then
        pass "Portal detects livesync-admin group"
    else
        fail "Portal returned is_admin='$IS_ADMIN' (expected True)"
    fi
fi

# Test: non-admin user
TOKEN_USER=$(python3 "$SCRIPT_DIR/fake-jwt.py" --email regular@example.com --groups eng 2>/dev/null | head -2 | tail -1)
if [ -n "$TOKEN_USER" ]; then
    IS_ADMIN_USER=$(curl -s -H "x-amzn-oidc-data: $TOKEN_USER" http://localhost:8000/ | \
        python3 -c "import sys,json; print(json.load(sys.stdin).get('is_admin',''))" 2>/dev/null)
    if [ "$IS_ADMIN_USER" = "False" ]; then
        pass "Non-admin user detected correctly"
    else
        fail "Non-admin user returned is_admin='$IS_ADMIN_USER' (expected False)"
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
RESPONSE=$(curl -s -u "admin@localhost:admin" http://localhost:8000/)
EMAIL=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('user',''))" 2>/dev/null)
IS_ADMIN=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('is_admin',''))" 2>/dev/null)
if [ "$EMAIL" = "admin@localhost" ] && [ "$IS_ADMIN" = "True" ]; then
    pass "Local auth: admin login via HTTP Basic"
else
    fail "Local auth: admin got email='$EMAIL' is_admin='$IS_ADMIN'"
fi

# Test: valid local regular user
RESPONSE=$(curl -s -u "user@localhost:user" http://localhost:8000/)
IS_ADMIN_LOCAL=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('is_admin',''))" 2>/dev/null)
if [ "$IS_ADMIN_LOCAL" = "False" ]; then
    pass "Local auth: regular user not admin"
else
    fail "Local auth: regular user got is_admin='$IS_ADMIN_LOCAL'"
fi

# Test: wrong password → 401
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -u "admin@localhost:wrong" http://localhost:8000/)
if [ "$HTTP_CODE" = "401" ]; then
    pass "Local auth: wrong password returns 401"
else
    fail "Local auth: wrong password returned $HTTP_CODE (expected 401)"
fi

# ── CouchDB init check ──────────────────────────────────────────────────────
# Run couchdb-init to create databases (including registry + passphrases)
$COMPOSE run --rm couchdb-init 2>/dev/null

COUCH_URL="http://${COUCHDB_USER:-admin}:${COUCHDB_PASSWORD:-livesync-dev-2026}@localhost:5984"
for db in _users _replicator obsidian-wiki livesync-registry livesync-passphrases; do
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
    -d '{"name":"test-vault"}' \
    http://localhost:8000/api/vaults)
VAULT_NAME=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('name',''))" 2>/dev/null)
if [ "$VAULT_NAME" = "test-vault" ]; then
    pass "Vault API: created vault 'test-vault'"
else
    fail "Vault API: create returned name='$VAULT_NAME' (expected test-vault). Response: $RESPONSE"
fi

# Verify the CouchDB database was created
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$COUCH_URL/test-vault")
if [ "$HTTP_CODE" = "200" ]; then
    pass "Vault API: CouchDB database 'test-vault' exists"
else
    fail "Vault API: CouchDB database 'test-vault' returned $HTTP_CODE"
fi

# Verify _security was set on the vault
SECURITY=$(curl -s "$COUCH_URL/test-vault/_security")
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
RESPONSE=$(curl -s -u "admin@localhost:admin" http://localhost:8000/api/vaults/test-vault)
OWNER=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('owner',''))" 2>/dev/null)
if [ "$OWNER" = "admin@localhost" ]; then
    pass "Vault API: detail shows correct owner"
else
    fail "Vault API: detail returned owner='$OWNER'"
fi

# Get setup URI
RESPONSE=$(curl -s -u "admin@localhost:admin" http://localhost:8000/api/vaults/test-vault/setup-uri)
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
