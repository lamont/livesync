# Obsidian LLM Wiki — LiveSync Infrastructure

A docker-compose development environment that runs a self-hosted Obsidian vault
as a shared LLM wiki. CouchDB acts as the durable sync hub (via the LiveSync
protocol), the portal renders vaults as static wikis (Quartz v5), and a
one-shot agent container runs Claude Code to perform wiki operations.

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
│  │   agent       │────────►│   portal      │                  │
│  │              │ shared  │              │                   │
│  │  livesync-cli│ volume  │  Quartz v5    │                  │
│  │  claude code │ (r/w)   │  :8000        │                  │
│  │              │         │              │                   │
│  └──────────────┘         └──────────────┘                   │
│         │                        │                           │
│         └─── vault (named volume)┘                           │
│                                                              │
│  ┌──────────────┐                                            │
│  │   sync        │  livesync-cli sidecar                     │
│  │              │  volume: vault (r/w)                       │
│  └──────────────┘                                            │
└──────────────────────────────────────────────────────────────┘

External:
  Obsidian desktop ──LiveSync plugin──► couchdb:5984
```

### Data flow

1. **CouchDB** is the single source of truth. It stores vault state in
   LiveSync's chunk-level document format.
2. **Obsidian desktop** clients connect directly to CouchDB via the LiveSync
   plugin for real-time sync.
3. **Sync** uses `livesync-cli` to periodically pull the vault from CouchDB
   into a local filesystem (`vault` volume).
4. **Agent** uses `livesync-cli` to pull the vault from CouchDB into its own
   volume (`agent-vault`), runs Claude Code against it, then pushes changes
   back to CouchDB.
5. **Portal** mounts the vaults volume read-only and rebuilds per-vault static
   sites (Quartz v5) when files change, serving them at `/vaults/<name>/`.

## Services

### couchdb — LiveSync Hub

**Image:** `oleduc/docker-obsidian-livesync-couchdb:master`

Pre-configured CouchDB 3.x with LiveSync init script, CORS headers, and
required settings (`max_document_size`, `require_valid_user`, etc.) baked in.

- Port: `5984`
- Volume: `couchdb-data` (persistent)
- Healthcheck: `GET /_up`

### sync — Vault Sync Sidecar

**Image:** Custom Dockerfile (livesync-cli + Deno)

Periodically pulls vault state from CouchDB to the shared filesystem volume.

- Volume: `vault` at `/data` (read-write)
- Sync interval: configurable (default 60s)

### Wiki rendering (inside portal)

Quartz v5 is embedded in the portal image (pinned release + vendored
`quartz.config.yaml` / `quartz.lock.json` under `portal/quartz-template/`).
A background task watches vault directories and rebuilds each vault's static
site on change; the portal serves the output at `/vaults/<name>/` with access
control. The standalone `viewer` container was removed in favor of this.

### agent — Claude Code Wiki Worker

**Image:** Custom Dockerfile (Node 22 + livesync-cli + Claude Code CLI)

One-shot container. Syncs vault from CouchDB, runs a Claude Code prompt against
it, pushes results back. Exits on completion.

- Volume: `agent-vault` at `/data` (read-write)
- Entrypoint: `sync → claude -p "$INSTRUCTION" → push → exit`

## Quick Start

```bash
cp .env.example .env
# Edit .env with your credentials

# Start CouchDB + Portal
docker compose up -d couchdb portal
docker compose run --rm couchdb-init

# Portal is at http://localhost:8000 (login: admin@localhost / admin)
# CouchDB admin UI at http://localhost:5984/_utils/
```

### Create a vault and connect Obsidian

1. **Create the vault in the portal** (provisions the CouchDB database):
   ```bash
   curl -u admin@localhost:admin -X POST \
     -H "Content-Type: application/json" \
     -d '{"name":"my-wiki"}' \
     http://localhost:8000/api/vaults
   ```

2. **Get the Setup URI** (includes CouchDB credentials + encryption passphrase):
   ```bash
   curl -u admin@localhost:admin \
     http://localhost:8000/api/vaults/my-wiki/setup-uri
   ```
   This returns `setup_uri` and `uri_passphrase`. Save both.

3. **Create a matching vault in Obsidian** (this is a separate step — the Setup
   URI configures sync but does not create the Obsidian vault):

   > **WARNING:** The Setup URI reconfigures LiveSync in *whichever vault is
   > currently open*. If you apply it in an existing vault (e.g. one already
   > syncing elsewhere), it **will overwrite that vault's LiveSync settings**.
   > Always create or switch to the intended vault first.

   - In Obsidian: **File menu → Open another vault → Create new vault**
   - Name it anything you like (the name is local-only; the CouchDB database
     name comes from the portal, not from Obsidian)
   - Obsidian opens the new empty vault

4. **Install and configure LiveSync** in the new vault:
   - Settings → Community plugins → Browse → install **Self-hosted LiveSync**
   - Enable the plugin, then open its settings
   - Choose **"Use the copied setup URI"**
   - Paste the `setup_uri` value, enter the `uri_passphrase` when prompted

5. **Choose the setup mode** on the decision page:

   | Scenario | Choose |
   |---|---|
   | First device connecting to a new vault | **"Setting up for the first time"** |
   | Joining a vault another device already pushed to | **"My remote server is already setup"** |
   | Re-configuring a device that was already syncing | **"Setup already and compatible"** |

   For a brand-new vault, choose **"Setting up for the first time"**. This
   pushes your (empty) local state to the server and establishes the sync
   relationship. Future devices joining the same vault use option 2.

6. **Start sync** (optional — renders vault content as a web wiki via the
   portal):
   ```bash
   docker compose up -d sync-multi portal
   # Browse at http://localhost:8000/vaults/<name>/
   ```

#### Multiple vaults

Each Obsidian vault has independent LiveSync settings (stored in
`.obsidian/plugins/obsidian-livesync/`). You can sync different vaults to
different CouchDB databases and switch between them freely using Obsidian's
vault switcher. The Setup URI only affects the vault that is open when you
apply it.

### Local users

Edit `portal/users.yaml` to add or remove users (changes take effect
immediately, no restart needed):

```yaml
- email: alice@example.com
  password: changeme
  groups: [livesync-admin]
- email: bob@example.com
  password: changeme
  groups: [eng]
```

### Run the agent

```bash
# Legacy single-vault agent
docker compose run agent -p "initialize the wiki"

# Multi-vault agent (targets a specific vault from the registry)
docker compose run -e VAULT_NAME=my-wiki -e INSTRUCTION="query: what is in this wiki?" agent-multi
```

### Headless sync (no Obsidian needed)

You can keep a local directory of markdown files in sync with CouchDB without
Obsidian. This is useful for editors, scripts, CI pipelines, or any machine
that needs access to vault content as plain files.

#### Single vault — one-way (CouchDB → local)

```bash
docker run -d --restart unless-stopped \
  -v ~/wiki:/data \
  -e COUCHDB_URI=http://your-couchdb:5984 \
  -e COUCHDB_USER=admin \
  -e COUCHDB_PASSWORD=changeme \
  -e COUCHDB_DATABASE=my-wiki \
  -e LIVESYNC_PASSPHRASE=your-e2ee-passphrase \
  -e SYNC_INTERVAL=30 \
  livesync-sync
```

Your `~/wiki/` directory will contain the vault's markdown files, updated
every 30 seconds. The passphrase is the E2EE passphrase generated when the
vault was created (available via `GET /api/vaults/{name}/setup-uri`).

#### Single vault — bidirectional

Add `SYNC_BIDIRECTIONAL=true` to also push local file changes back to CouchDB.
Edits you make in `~/wiki/` will appear in Obsidian on other devices:

```bash
docker run -d --restart unless-stopped \
  -v ~/wiki:/data \
  -e COUCHDB_URI=http://your-couchdb:5984 \
  -e COUCHDB_USER=admin \
  -e COUCHDB_PASSWORD=changeme \
  -e COUCHDB_DATABASE=my-wiki \
  -e LIVESYNC_PASSPHRASE=your-e2ee-passphrase \
  -e SYNC_INTERVAL=30 \
  -e SYNC_BIDIRECTIONAL=true \
  livesync-sync
```

#### Multi-vault — all vaults from the registry

```bash
docker run -d --restart unless-stopped \
  -v ~/vaults:/data/vaults \
  -e SYNC_MODE=multi \
  -e COUCHDB_URI=http://your-couchdb:5984 \
  -e COUCHDB_USER=admin \
  -e COUCHDB_PASSWORD=changeme \
  -e SYNC_INTERVAL=60 \
  -e SYNC_BIDIRECTIONAL=true \
  livesync-sync
```

This syncs all non-encrypted-only vaults to `~/vaults/my-wiki/`,
`~/vaults/team-notes/`, etc. New vaults are picked up automatically.

#### Using docker-compose

If you're running the full stack, use the existing services with a bind mount:

```bash
# One-way sync of a single vault
docker compose run -v ~/wiki:/data sync

# Bidirectional multi-vault sync
docker compose run -v ~/vaults:/data/vaults \
  -e SYNC_BIDIRECTIONAL=true sync-multi
```

#### How it works

The sync container uses `livesync-cli` (the headless LiveSync client):

1. **Bootstrap** — on first run, generates a Setup URI and configures
   `livesync-cli` against your CouchDB database (same protocol Obsidian uses)
2. **Pull cycle** — `sync` (CouchDB ↔ local DB replication) then `mirror`
   (local DB → plain .md files on disk)
3. **Push cycle** (bidirectional only) — `mirror` (detect filesystem changes →
   local DB) then `sync` (local DB → CouchDB)
4. **Loop** — repeats every `SYNC_INTERVAL` seconds

The container is stateless beyond the bind-mounted directory. If you delete
the container, the local files remain. Restarting picks up where it left off
(the `.livesync/` subdirectory inside the mount stores the bootstrap config
and local DB).

## Kubernetes Deployment

Raw manifests in `chart/` target an EKS sandbox cluster:

- **CouchDB** — StatefulSet with EBS (gp3) persistent volume
- **Portal** — Deployment with EFS-backed vaults + static volumes, OIDC auth
- **Sync** — Deployment writing to EFS (multi-vault, registry-driven)
- **Agent** — Job template with VAULT_NAME targeting
- **Ingress** — Single ALB with dual listeners: HTTPS/443 (portal, OIDC via
  Okta) + HTTPS/5984 (CouchDB, no OIDC)

```bash
kubectl apply -k chart/
```

See `chart/` for details. Assumes EBS CSI and EFS CSI drivers are installed.
The ingress requires an ACM certificate and Okta OIDC app registration
(see `chart/ingress.yaml` for placeholder values to replace).

### OIDC testing without Okta

For staging or dev clusters, set `JWT_SKIP_VERIFY=1` in the portal configmap
and use `scripts/fake-jwt.py` to generate test tokens:

```bash
TOKEN=$(python scripts/fake-jwt.py --email test@co.com --groups livesync-admin | head -2 | tail -1)
curl -H "x-amzn-oidc-data: $TOKEN" https://portal-staging.example.com/api/vaults
```

See [TODO.md](TODO.md) for the detailed implementation checklist.
