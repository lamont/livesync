#!/bin/sh
# One-shot agent: bootstrap → sync → run Claude Code → push changes back.
set -eu

VAULT=/data
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
    s.syncIgnoreRegEx=["^data-.*-livesync-v2(/|$)","^\\\\.livesync(/|$)","^\\\\.livesync-snapshot\\\\.json$"].join("|[]|");
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
