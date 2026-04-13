# Implementation TODO

## Phase 1: CouchDB — LiveSync Hub

- [ ] Create `docker-compose.yml` with `couchdb` service
  - Image: `oleduc/docker-obsidian-livesync-couchdb:master`
  - Port: `5984` exposed to host
  - Volume: `couchdb-data:/opt/couchdb/data`
  - Healthcheck: `curl -f http://localhost:5984/_up`
  - Env: `COUCHDB_USER`, `COUCHDB_PASSWORD`, `COUCHDB_DATABASE`
- [ ] Create `.env.example` with placeholder credentials
- [ ] Create `.gitignore` (ignore `.env`, vault data)
- [ ] Verify: `docker compose up couchdb` passes healthcheck
- [ ] Verify: Obsidian desktop connects via LiveSync plugin and syncs a test vault

## Phase 2: Quartz — Wiki Web UI

- [ ] Add `quartz` service to `docker-compose.yml`
  - Image: `shommey/dockerized-quartz`
  - Port: `8080` exposed to host
  - Volume: `agent-vault:/vault:ro`
  - Env: `BUILD_UPDATE_DELAY=120`, `AUTO_REBUILD=true`
  - Depends on: `couchdb` (healthy)
- [ ] Add `agent-vault` named volume to compose
- [ ] Seed the vault volume with a test markdown file for initial verification
- [ ] Verify: Quartz builds and serves at `localhost:8080`
- [ ] Verify: Changes to vault files trigger rebuild

## Phase 3: Agent — Claude Code Wiki Worker

- [ ] Create `agent/Dockerfile`
  - Base: Alpine + Python 3.12 + uv
  - Install: Node 22 (for livesync-cli and claude code)
  - Install: `livesync-cli` (from `vrtmrz/obsidian-livesync` src/apps/cli/)
  - Install: `@anthropic-ai/claude-code` globally
  - Install: obsidian-wiki skills from `Ar9av/obsidian-wiki`
  - Install: QMD plugin via `claude plugin marketplace add tobi/qmd`
    and `claude plugin install qmd@qmd`
  - Copy: `entrypoint.sh`, seed vault
- [ ] Create `agent/entrypoint.sh`
  - Configure livesync-cli with CouchDB connection from env vars
  - `livesync-cli sync` (pull vault from CouchDB to /vault)
  - `claude -p "$INSTRUCTION"` in /vault working directory
  - `livesync-cli push` (push changes back to CouchDB)
  - Exit
- [ ] Create `agent/settings.json.tmpl` — livesync-cli config template
- [ ] Add `agent` service to `docker-compose.yml`
  - Build: `./agent`
  - Volume: `agent-vault:/vault`
  - Env: `ANTHROPIC_API_KEY`, CouchDB creds, `INSTRUCTION`
  - Depends on: `couchdb` (healthy)
  - Restart: `no` (one-shot)
- [ ] Create `agent/vault-seed/` with minimal wiki skeleton
  - `_index.md`, `_raw/`, `wiki/` directories
- [ ] Verify: `docker compose run agent -p "initialize the wiki"` populates vault
- [ ] Verify: `docker compose run agent -p "query: what is in this wiki?"` returns answer
- [ ] Verify: Agent changes appear in Quartz after rebuild

## Phase 4: Integration & Polish

- [ ] End-to-end test: Obsidian desktop → CouchDB → agent ingest → Quartz display
- [ ] Document LiveSync plugin setup URI generation (oleduc image supports this)
- [ ] Pin image versions in docker-compose.yml
- [ ] Optimize agent Dockerfile (multi-stage build, layer caching)
- [ ] Add CLAUDE.md to repo for project-level Claude Code context

## Future: Helm Chart

- [ ] CouchDB StatefulSet + EBS PV
- [ ] Agent Job/CronJob with per-pod ephemeral vault
- [ ] Quartz Deployment + ALB ingress
- [ ] ExternalSecrets for credentials
- [ ] ArgoCD Application

## Open Questions

1. **livesync-cli maturity** — It's experimental (March 2026). May need fallback
   to headless Obsidian if CLI proves unreliable. Test thoroughly in Phase 3.
2. **Quartz + Obsidian wikilinks** — Need to configure `markdownLinkResolution`
   for `[[wikilink]]` compatibility. Test in Phase 2.
3. **Vault seeding** — First run with empty CouchDB needs initial content.
   Agent vault-seed directory handles this, but need to test the flow.
4. **Write serialization** — Single agent at a time for demo. Production
   multi-agent needs a queue or conflict resolution strategy.
