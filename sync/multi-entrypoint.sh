#!/bin/sh
# Multi-vault sync: discover all vaults from the registry, bootstrap each,
# and sync them to /data/vaults/<name>/ on a loop.
#
# Requires admin CouchDB credentials (reads registry + passphrases DBs).
# Each vault gets its own livesync-cli working directory under /data/vaults/.
set -eu

SYNC_INTERVAL="${SYNC_INTERVAL:-60}"
COUCH_URL="${COUCHDB_URI:?COUCHDB_URI required}"
COUCH_USER="${COUCHDB_USER:?COUCHDB_USER required}"
COUCH_PASS="${COUCHDB_PASSWORD:?COUCHDB_PASSWORD required}"
COUCH_AUTH_URL="$(echo "$COUCH_URL" | sed "s|://|://${COUCH_USER}:${COUCH_PASS}@|")"
VAULTS_DIR="/data/vaults"

mkdir -p "$VAULTS_DIR"

# ── Helpers ──────────────────────────────────────────────────────────────────

get_vaults() {
  # Fetch all vault docs from the registry, return non-encrypted-only names
  curl -sf "${COUCH_AUTH_URL}/livesync-registry/_all_docs?include_docs=true" \
    | jq -r '.rows[].doc | select(.encrypted_only != true) | .name'
}

get_passphrase() {
  # Fetch E2EE passphrase for a vault from the passphrases DB
  local vault_name="$1"
  curl -sf "${COUCH_AUTH_URL}/livesync-passphrases/${vault_name}" \
    | jq -r '.passphrase'
}

bootstrap_vault() {
  # Bootstrap livesync-cli settings for a vault if not already done.
  local vault_name="$1"
  local vault_dir="${VAULTS_DIR}/${vault_name}"
  local settings="${vault_dir}/.livesync/settings.json"

  if [ -f "$settings" ]; then
    return 0
  fi

  echo "[init] bootstrapping vault: ${vault_name}"
  mkdir -p "${vault_dir}/.livesync"

  # Get the E2EE passphrase from the passphrases DB
  local passphrase
  passphrase=$(get_passphrase "$vault_name")
  if [ -z "$passphrase" ] || [ "$passphrase" = "null" ]; then
    echo "[error] no passphrase found for vault: ${vault_name}"
    return 1
  fi

  # Generate setup URI
  local output
  output=$(hostname="${COUCH_URL}" \
           username="${COUCH_USER}" \
           password="${COUCH_PASS}" \
           database="${vault_name}" \
           passphrase="${passphrase}" \
           deno -A /scripts/generate_setupuri.ts 2>&1)

  local setup_uri
  setup_uri=$(echo "$output" | grep "^obsidian://")
  local setup_pass
  setup_pass=$(echo "$output" | grep "passphrase of Setup-URI" | awk -F: '{print $2}' | xargs)

  if [ -z "$setup_uri" ]; then
    echo "[error] could not generate setup URI for ${vault_name}"
    echo "$output"
    return 1
  fi

  local cli="node /app/dist/index.cjs ${vault_dir}"

  echo "[init] applying setup URI for ${vault_name}"
  printf '%s\n' "$setup_pass" | $cli setup "$setup_uri"

  # Patch settings: ignore LevelDB dirs + disable config mismatch check
  echo "[init] patching settings for ${vault_name}"
  node -e '
    const fs=require("fs");
    const p="'"$settings"'";
    const s=JSON.parse(fs.readFileSync(p,"utf8"));
    s.syncIgnoreRegEx=["^data-.*-livesync-v2(/|$)","^\\\\.livesync(/|$)","^\\\\.livesync-snapshot\\\\.json$"].join("|[]|");
    s.disableCheckingConfigMismatch=true;
    fs.writeFileSync(p,JSON.stringify(s,null,2));
  '

  echo "[init] vault ${vault_name} bootstrapped"
}

sync_vault() {
  local vault_name="$1"
  local vault_dir="${VAULTS_DIR}/${vault_name}"
  local cli="node /app/dist/index.cjs ${vault_dir}"

  $cli sync  || echo "[warn] sync failed for ${vault_name}"
  $cli mirror || echo "[warn] mirror failed for ${vault_name}"
}

# ── Main loop ────────────────────────────────────────────────────────────────

echo "[boot] multi-vault sync starting"
echo "[boot] registry: ${COUCH_URL}/livesync-registry"
echo "[boot] vaults dir: ${VAULTS_DIR}"

while true; do
  echo "[loop] discovering vaults from registry..."
  VAULT_NAMES=$(get_vaults 2>/dev/null || echo "")

  if [ -z "$VAULT_NAMES" ]; then
    echo "[loop] no vaults found in registry (or registry not yet created)"
  else
    for name in $VAULT_NAMES; do
      bootstrap_vault "$name" || continue
      sync_vault "$name"
    done
  fi

  echo "[loop] sleeping ${SYNC_INTERVAL}s"
  sleep "$SYNC_INTERVAL"
done
