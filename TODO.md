# Implementation TODO

## Phase 1: CouchDB — LiveSync Hub (done)

- [x] Create `docker-compose.yml` with `couchdb` service
- [x] Create `.env.example` with placeholder credentials
- [x] Create `.gitignore` (ignore `.env`, vault data)
- [x] Verify: `docker compose up couchdb` passes healthcheck
- [x] Verify: Obsidian desktop connects via LiveSync plugin and syncs a test vault

## Phase 2: Sync + Viewer — Wiki Web UI (done)

- [x] Add `sync` service to `docker-compose.yml`
- [x] Add `viewer` service to `docker-compose.yml`
- [x] Add `vault` named volume to compose
- [x] Verify: Viewer builds and serves at `localhost:8080`

## Phase 3: Agent — Claude Code Wiki Worker (done)

- [x] Create `agent/Dockerfile` and `agent/entrypoint.sh`
- [x] Add `agent` service to `docker-compose.yml`
- [x] Smoke-test agent bootstrap, sync, and mirror

## Phase 4: Kubernetes — Sandbox EKS Deployment (done)

- [x] Create `chart/` with raw K8s manifests + kustomization.yaml
- [x] CouchDB StatefulSet + EBS PV, Sync Deployment + EFS, Viewer + LB, Agent Job
- [x] Verify: `kubectl apply -k chart/ --dry-run=client` passes

## Phase 5: Integration & Polish

- [ ] End-to-end test: Obsidian desktop → CouchDB → sync → viewer display
- [ ] Pin image versions in docker-compose.yml
- [ ] Optimize Dockerfiles (multi-stage build, layer caching)

---

## Multi-Tenant Vault Platform (Phases 6–13)

### Phase 6: Portal Skeleton + Fake JWT Auth

- [ ] Create `portal/pyproject.toml` — FastAPI, uvicorn, python-jose, httpx, jinja2
- [ ] Create `portal/Dockerfile` — Python 3.12-slim + uv, runs uvicorn on :8000
- [ ] Create `portal/app/main.py` — FastAPI app with lifespan, middleware
- [ ] Create `portal/app/auth.py` — JWT middleware: reads `x-amzn-oidc-data`,
      extracts email + groups, sets `request.state.user`, `is_admin` from
      `livesync-admin` group
- [ ] Create `portal/app/models.py` — Pydantic: User, VaultInfo, VaultCreate
- [ ] Create `portal/app/routes/health.py` — `GET /healthz`
- [ ] Create `portal/app/routes/home.py` — `GET /` returns user info JSON
- [ ] Create `scripts/fake-jwt.py` — generates signed JWT with email + groups
- [ ] Update `docker-compose.yml` — add `portal` service on :8000
- [ ] Update `.env.example` — add `JWT_SIGNING_KEY`
- [ ] **Checkpoint**: fake JWT → `curl localhost:8000/` → user info; no header → 401

### Phase 7: CouchDB User Provisioning + Vault Registry

- [ ] Create `portal/app/couch.py` — async CouchDB client (httpx):
      `ensure_user()`, `create_database()`, `set_security()`, registry CRUD,
      passphrase storage
- [ ] Create `portal/app/vault_service.py` — business logic: `provision_user()`,
      `create_vault()`, `list_vaults_for_user()`, `get_setup_uri()` (shells out
      to Deno `generate_setupuri.ts`)
- [ ] Create `portal/app/routes/api.py` — `POST /api/vaults`, `GET /api/vaults`,
      `GET /api/vaults/{name}`, `GET /api/vaults/{name}/setup-uri`
- [ ] Update `portal/Dockerfile` — add Deno + copy `generate_setupuri.ts`
- [ ] Update `couchdb-init` — create `_livesync_registry` +
      `_livesync_passphrases` databases with admin-only `_security`
- [ ] **Checkpoint**: create vault via API → CouchDB DB exists with `_security`;
      get Setup URI → valid `obsidian://setuplivesync?...` URL

### Phase 8: Multi-Vault Sync

- [ ] Create `sync/multi-entrypoint.sh` — queries `_livesync_registry`, bootstraps
      + syncs each vault to `/data/vaults/<name>/`
- [ ] Update `sync/Dockerfile` — add `curl`, `jq`; `SYNC_MODE=multi|single`
      selects entrypoint
- [ ] Update `docker-compose.yml` — sync uses `SYNC_MODE=multi`, volume
      `vaults:/data/vaults`, admin creds
- [ ] **Checkpoint**: create vault via API → connect Obsidian → push notes →
      files appear at `/data/vaults/<name>/` after sync cycle

### Phase 9: Per-Vault Quartz Builds + Portal Viewer

- [ ] Create `portal/app/quartz_builder.py` — background task: per-vault
      `npx quartz build`, mtime tracking, skips encrypted-only
- [ ] Create `portal/app/routes/vaults.py` — `GET /vaults/{name}/{path}` serves
      static Quartz output with access checks (403 for non-members)
- [ ] Create `portal/templates/home.html` — vault list with links
- [ ] Update `portal/Dockerfile` — add Node.js 22 + Quartz
- [ ] Update `docker-compose.yml` — mount `vaults` + `static` into portal;
      comment out old `viewer` service
- [ ] **Checkpoint**: push markdown → sync → Quartz build → browse
      `localhost:8000/vaults/<name>/` → rendered wiki; non-member → 403

### Phase 10: Vault Sharing + First-Login Flow

- [ ] Create `portal/templates/` — base.html, welcome.html, vault_detail.html,
      admin.html
- [ ] Create `portal/app/routes/welcome.py` — `GET /welcome` first-login flow
- [ ] Create `portal/app/routes/admin.py` — `GET /admin/` dashboard (admin only)
- [ ] Add `share_vault()` / `unshare_vault()` to vault_service.py
- [ ] Add `PUT /api/vaults/{name}/members` to API routes
- [ ] Redirect first-time users (no vaults) to `/welcome`
- [ ] **Checkpoint**: new user → `/welcome` → creates vault → shares with email →
      second user sees it; admin → `/admin/` shows all vaults

### Phase 11: Encrypted-Only Vaults + Agent Multi-Vault

- [ ] Vault creation accepts `encrypted_only` flag
- [ ] `PATCH /api/vaults/{name}` for settings updates
- [ ] Verify sync + Quartz builder skip encrypted-only vaults
- [ ] Update `agent/entrypoint.sh` — accept `VAULT_NAME` env var, multi-vault paths
- [ ] Stub `POST /api/vaults/{name}/agent` (501 + CLI instructions)
- [ ] **Checkpoint**: encrypted-only vault skipped by sync/viewer; agent targets
      specific vault via `VAULT_NAME`

### Phase 12: Kubernetes Manifests

- [ ] Create `chart/portal-deployment.yaml` + `chart/portal-service.yaml`
- [ ] Create `chart/ingress.yaml` — ALB with OIDC on portal paths, passthrough
      on CouchDB (:5984 or `/couchdb/`)
- [ ] Update `chart/couchdb-init-job.yaml` — create registry + passphrases DBs
- [ ] Update `chart/sync-deployment.yaml` — multi-vault EFS paths
- [ ] Remove `chart/viewer-deployment.yaml` + `chart/viewer-service.yaml`
- [ ] Update `chart/kustomization.yaml` + `build-push.sh`
- [ ] **Checkpoint**: `kubectl apply -k chart/ --dry-run=client` passes

### Phase 13: Production Hardening + Documentation

- [ ] Create `scripts/test-e2e.sh` — automated acceptance tests
- [ ] Create `scripts/migrate-single-to-multi.sh` — migration for existing vaults
- [ ] Create `CLAUDE.md` — project-level context
- [ ] Rewrite `README.md` for multi-tenant architecture
- [ ] Add docker-compose profiles: default, legacy, agent
- [ ] **Checkpoint**: `./scripts/test-e2e.sh` passes green

## Open Questions

1. **livesync-cli maturity** — Experimental (March 2026). May need fallback to
   headless Obsidian if CLI proves unreliable.
2. **Quartz + Obsidian wikilinks** — Need `markdownLinkResolution` config for
   `[[wikilink]]` compatibility.
3. **Write serialization** — Single agent at a time for now. Production
   multi-agent needs a queue or conflict resolution strategy.
4. **CouchDB `couch_peruser`** — Auto-creates per-user databases. Could simplify
   private vault provisioning but uses ugly hex database names. Evaluate later.
