# Obsidian LLM Wiki — LiveSync Infrastructure

A docker-compose development environment that runs a self-hosted Obsidian vault
as a shared LLM wiki. CouchDB acts as the durable sync hub (via the LiveSync
protocol), a static site viewer provides the web UI, and a one-shot agent
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
│  │   agent       │────────►│   viewer      │                  │
│  │              │ shared  │              │                   │
│  │  livesync-cli│ volume  │  Quartz v4    │                  │
│  │  claude code │ (r/w)   │  :8080        │                  │
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
5. **Viewer** mounts `vault` read-only and rebuilds the static site (Quartz v4)
   when files change.

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

### viewer — Wiki Web UI

**Image:** Custom Dockerfile (Quartz v4 + Node 22)

Watches the vault directory for changes and rebuilds the static site. Serves
via the Quartz dev server.

- Port: `8080`
- Volume: `vault` mounted read-only at `/vault`

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

6. **Start sync + viewer** (optional — renders vault content as a web wiki):
   ```bash
   docker compose up -d sync viewer
   # Browse at http://localhost:8080
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
docker compose run agent -p "initialize the wiki"
docker compose run agent -p "query: what is in this wiki?"
```

## Kubernetes Deployment

Raw manifests in `chart/` target an EKS sandbox cluster:

- **CouchDB** — StatefulSet with EBS (gp3) persistent volume
- **Sync** — Deployment writing to EFS-backed shared volume
- **Viewer** — Deployment + LoadBalancer Service reading from EFS
- **Agent** — Job template mounting EFS

```bash
kubectl apply -k chart/
```

See `chart/` for details. Assumes EBS CSI and EFS CSI drivers are installed.

## Implementation Order

1. **CouchDB** — get LiveSync hub running, verify Obsidian desktop can connect
2. **Sync + Viewer** — vault sync sidecar + web UI reading from shared volume
3. **Agent** — livesync-cli + Claude Code one-shot worker
4. **K8s** — deploy to sandbox EKS cluster

See [TODO.md](TODO.md) for the detailed implementation checklist.
