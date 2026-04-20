#!/bin/sh
# Periodically sync the vault from CouchDB and mirror it to the filesystem.
# First run bootstraps settings via the upstream setup URI flow (same as Obsidian).
set -eu

SETTINGS=/data/.livesync/settings.json
SYNC_INTERVAL="${SYNC_INTERVAL:-60}"
CLI="node /app/dist/index.cjs /data"

if [ ! -f "$SETTINGS" ]; then
  echo "[init] generating setup URI"
  mkdir -p /data/.livesync
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

  # Ignore livesync-cli's own leveldb dirs and other local-only metadata so
  # mirror doesn't upload them to CouchDB as "vault content". Uses the
  # plugin's "|[]|" regex separator.
  echo "[init] patching syncIgnoreRegEx"
  node -e '
    const fs=require("fs");
    const p="'"$SETTINGS"'";
    const s=JSON.parse(fs.readFileSync(p,"utf8"));
    s.syncIgnoreRegEx=["^.*-livesync-v2(/|$)","^.*-headless-app-livesync-v2(/|$)","^\\\\.livesync(/|$)","^\\\\.livesync-snapshot\\\\.json$"].join("|[]|");
    // Desktop-set tweaks (chunk size, etc.) don'"'"'t have to match our CLI defaults
    s.disableCheckingConfigMismatch=true;
    fs.writeFileSync(p,JSON.stringify(s,null,2));
    console.log("[init] syncIgnoreRegEx set");
  '
fi

BIDIRECTIONAL="${SYNC_BIDIRECTIONAL:-false}"

echo "[boot] initial sync + mirror (bidirectional=${BIDIRECTIONAL})"
$CLI sync || echo "[warn] initial sync failed"
$CLI mirror || echo "[warn] initial mirror failed"

echo "[loop] syncing every ${SYNC_INTERVAL}s"
while true; do
  sleep "$SYNC_INTERVAL"

  # Bidirectional: push local filesystem changes to CouchDB first
  if [ "$BIDIRECTIONAL" = "true" ]; then
    $CLI mirror || echo "[warn] mirror (push) failed at $(date)"
    $CLI sync   || echo "[warn] sync (push) failed at $(date)"
  fi

  # Pull remote changes from CouchDB to filesystem
  $CLI sync  || echo "[warn] sync failed at $(date)"
  $CLI mirror || echo "[warn] mirror failed at $(date)"
done
