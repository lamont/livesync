#!/bin/sh
# One-shot agent: bootstrap → sync → run Claude Code → push changes back.
#
# Two modes:
#   Multi-vault:  set VAULT_NAME — fetches passphrase from registry.
#   Legacy:       set COUCHDB_DATABASE + LIVESYNC_PASSPHRASE (original behavior).
set -eu

# ── Resolve vault target ─────────────────────────────────────────────────
if [ -n "${VAULT_NAME:-}" ]; then
  # ── Multi-vault mode: fetch config from registry ──────────────────────
  echo "[init] multi-vault mode: vault=${VAULT_NAME}"
  COUCH_AUTH_URL="$(echo "${COUCHDB_URI}" | sed "s|://|://${COUCHDB_USER}:${COUCHDB_PASSWORD}@|")"

  # Check encrypted-only flag
  ENCRYPTED=$(curl -sf "${COUCH_AUTH_URL}/livesync-registry/vault:${VAULT_NAME}" \
    | jq -r '.encrypted_only // false')
  if [ "$ENCRYPTED" = "true" ]; then
    echo "[skip] vault '${VAULT_NAME}' is encrypted-only — agent cannot operate on it"
    exit 0
  fi

  # Fetch passphrase
  LIVESYNC_PASSPHRASE=$(curl -sf "${COUCH_AUTH_URL}/livesync-passphrases/${VAULT_NAME}" \
    | jq -r '.passphrase')
  if [ -z "$LIVESYNC_PASSPHRASE" ] || [ "$LIVESYNC_PASSPHRASE" = "null" ]; then
    echo "[fatal] no passphrase found for vault: ${VAULT_NAME}"
    exit 1
  fi

  COUCHDB_DATABASE="$VAULT_NAME"
  VAULT="/data/vaults/${VAULT_NAME}"
  mkdir -p "$VAULT"
else
  # ── Legacy single-vault mode ──────────────────────────────────────────
  echo "[init] single-vault mode: database=${COUCHDB_DATABASE}"
  VAULT=/data
fi

SETTINGS="$VAULT/.livesync/settings.json"
CLI="node /app/dist/index.cjs $VAULT"

# ── Bootstrap livesync settings on first run ──────────────────────────────
if [ ! -f "$SETTINGS" ]; then
  echo "[init] generating setup URI"
  mkdir -p "$VAULT/.livesync"
  OUTPUT=$(hostname="${COUCHDB_URI}" \
           username="${COUCHDB_USER}" \
           password="${COUCHDB_PASSWORD}" \
           database="${COUCHDB_DATABASE}" \
           passphrase="${LIVESYNC_PASSPHRASE}" \
           deno -A /scripts/generate_setupuri.ts 2>&1)
  SETUP_URI=$(echo "$OUTPUT" | grep "^obsidian://")
  SETUP_PASS=$(echo "$OUTPUT" | grep "passphrase of Setup-URI" | awk -F: '{print $2}' | xargs)

  if [ -z "$SETUP_URI" ]; then
    echo "[fatal] could not generate setup URI"
    echo "$OUTPUT"
    exit 1
  fi

  echo "[init] applying setup URI (URI passphrase: $SETUP_PASS)"
  printf '%s\n' "$SETUP_PASS" | $CLI setup "$SETUP_URI"

  # Ignore livesync internal files (same pattern as quartz-sync)
  echo "[init] patching syncIgnoreRegEx"
  node -e '
    const fs=require("fs");
    const p="'"$SETTINGS"'";
    const s=JSON.parse(fs.readFileSync(p,"utf8"));
    s.syncIgnoreRegEx=["^.*-livesync-v2(/|$)","^.*-headless-app-livesync-v2(/|$)","^\\\\.livesync(/|$)","^\\\\.livesync-snapshot\\\\.json$"].join("|[]|");
    s.disableCheckingConfigMismatch=true;
    fs.writeFileSync(p,JSON.stringify(s,null,2));
    console.log("[init] syncIgnoreRegEx set");
  '
fi

# ── Pull latest from CouchDB ─────────────────────────────────────────────
echo "[sync] pulling from CouchDB"
$CLI sync  || echo "[warn] sync failed"
$CLI mirror || echo "[warn] mirror failed"

# ── Run Claude Code ───────────────────────────────────────────────────────
INSTRUCTION="${INSTRUCTION:-Describe the contents of this vault.}"
echo "[agent] running: claude -p \"$INSTRUCTION\""
cd "$VAULT"
claude -p "$INSTRUCTION" --verbose
CLAUDE_EXIT=$?

if [ "$CLAUDE_EXIT" -ne 0 ]; then
  echo "[error] claude exited $CLAUDE_EXIT"
fi

# ── Push changes back to CouchDB ─────────────────────────────────────────
echo "[sync] pushing changes to CouchDB"
$CLI mirror || echo "[warn] mirror failed"
$CLI sync   || echo "[warn] sync failed"

echo "[done] agent finished (claude exit=$CLAUDE_EXIT)"
exit "$CLAUDE_EXIT"
