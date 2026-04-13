# Obsidian LLM Wiki — LiveSync Infrastructure

A docker-compose development environment that runs a self-hosted Obsidian vault
as a shared LLM wiki. CouchDB acts as the durable sync hub (via the LiveSync
protocol), a Quartz static site provides the web UI, and a one-shot agent
container runs Claude Code to perform wiki operations.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  docker-compose                                              │
│                                                              │
│  ┌──────────────┐                                            │
│  │   couchdb     │  oleduc/docker-obsidian-livesync-couchdb  │
│  │   :5984       │  volume: couchdb-data                     │
│  └──────┬───────┘                                            │
│         │                                                    │
│         │  LiveSync replication                               │
│         │                                                    │
│  ┌──────┴───────┐         ┌──────────────┐                   │
│  │   agent       │────────►│   quartz      │                  │
│  │              │ shared  │              │                   │
│  │  livesync-cli│ volume  │  dockerized-  │                  │
│  │  claude code │ (r/w)   │  quartz       │                  │
│  │              │         │  :8080        │                  │
│  └──────────────┘         └──────────────┘                   │
│         │                        │                           │
│         └── agent-vault ─────────┘                           │
│             (named volume)                                   │
└──────────────────────────────────────────────────────────────┘

External:
  Obsidian desktop ──LiveSync plugin──► couchdb:5984
```

### Data flow

1. **CouchDB** is the single source of truth. It stores vault state in
   LiveSync's chunk-level document format.
2. **Obsidian desktop** clients connect directly to CouchDB via the LiveSync
   plugin for real-time sync.
3. **Agent** uses `livesync-cli` to pull the vault from CouchDB into a local
   filesystem (`agent-vault` volume), runs Claude Code against it, then pushes
   changes back to CouchDB.
4. **Quartz** mounts `agent-vault` read-only and rebuilds the static site when
   files change.

## Services

### couchdb — LiveSync Hub

**Image:** `oleduc/docker-obsidian-livesync-couchdb:master`

Pre-configured CouchDB 3.x with LiveSync init script, CORS headers, and
required settings (`max_document_size`, `require_valid_user`, etc.) baked in.

- Port: `5984`
- Volume: `couchdb-data` (persistent)
- Healthcheck: `GET /_up`

### quartz — Wiki Web UI

**Image:** `shommey/dockerized-quartz`

Watches the vault directory for changes and rebuilds the Quartz v4 static site.
Serves via nginx.

- Port: `8080`
- Volume: `agent-vault` mounted read-only at `/vault`
- Rebuild delay: configurable (default 120s)

### agent — Claude Code Wiki Worker

**Image:** Custom Dockerfile (Node 22 + livesync-cli + Claude Code CLI)

One-shot container. Syncs vault from CouchDB, runs a Claude Code prompt against
it, pushes results back. Exits on completion.

- Volume: `agent-vault` at `/vault` (read-write)
- Entrypoint: `sync → claude -p "$INSTRUCTION" → push → exit`

## Quick Start

```bash
cp .env.example .env
# Edit .env with your credentials

# Phase 1: Start CouchDB
docker compose up -d couchdb
# Connect Obsidian desktop via LiveSync plugin to localhost:5984

# Phase 2: Start Quartz
docker compose up -d quartz
# Browse wiki at http://localhost:8080

# Phase 3: Run agent
docker compose run agent -p "initialize the wiki"
docker compose run agent -p "query: what is in this wiki?"
```

## Implementation Order

1. **CouchDB** — get LiveSync hub running, verify Obsidian desktop can connect
2. **Quartz** — web UI reading from shared volume
3. **Agent** — livesync-cli + Claude Code one-shot worker

See [TODO.md](TODO.md) for the detailed implementation checklist.
