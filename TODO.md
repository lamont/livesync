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

### Phase 6: Portal Skeleton + Fake JWT Auth (done)

- [x] FastAPI portal with dual auth: OIDC (x-amzn-oidc-data JWT) + local
      (HTTP Basic + users.yaml). `AUTH_MODE=oidc|local` env var.
- [x] `scripts/fake-jwt.py` for curl-based testing
- [x] `scripts/smoke-test.sh` for docker compose integration tests
- [x] 26 pytest unit tests (auth, models, routes)
- [x] **Checkpoint**: ✅ both auth modes working, 401 on missing/bad auth

### Phase 7: CouchDB User Provisioning + Vault Registry (done)

- [x] `portal/app/couch.py` — async CouchDB client (httpx)
- [x] `portal/app/vault_service.py` — vault CRUD, Setup URI generation
- [x] `portal/app/routes/api.py` — POST/GET /api/vaults, setup-uri endpoint
- [x] `livesync-registry` + `livesync-passphrases` CouchDB databases
- [x] Vault name uniqueness check (409 on duplicate)
- [x] `COUCHDB_EXTERNAL_URI` for host-reachable Setup URIs
- [x] `disableCheckingConfigMismatch` + `liveSync` baked into Setup URI defaults
- [x] **Checkpoint**: ✅ end-to-end vault creation + Obsidian desktop connected

### Phase 8: Multi-Vault Sync (done)

- [x] `sync/multi-entrypoint.sh` — registry-driven vault discovery + sync
- [x] `SYNC_MODE=multi|single` selects entrypoint
- [x] `sync-multi` docker-compose service with `vaults` volume
- [x] Dynamic vault discovery (new vaults picked up each cycle)
- [x] **Checkpoint**: ✅ two vaults bootstrapped + synced in smoke test

### Phase 9: Per-Vault Quartz Builds + Portal Viewer (done)

- [x] `portal/app/quartz_builder.py` — background asyncio task: per-vault
      `npx quartz build`, mtime tracking, skips encrypted-only, fallback index
- [x] `portal/app/routes/vaults.py` — `GET /vaults/{name}/{path}` serves
      static Quartz output with path-traversal protection + access checks
- [x] `portal/templates/home.html` — vault list with links, badges, access info
- [x] `portal/app/routes/home.py` — renders Jinja2 template with user's vaults
- [x] `portal/Dockerfile` — multi-stage: Node.js 22 + Quartz v4 + Python 3.12
- [x] `docker-compose.yml` — `vaults:ro` + `static` volumes on portal;
      old `viewer` service commented out
- [x] `portal/app/main.py` — lifespan-based startup for Quartz builder
- [x] **Checkpoint**: ✅ markdown synced → Quartz build → browse
      `localhost:8000/vaults/my-wiki/` → rendered wiki; non-member → 403

### Phase 10: Observability — Prometheus Metrics (done)

- [x] `prometheus_client` added to portal dependencies
- [x] `portal/app/metrics.py` — metric definitions + periodic gauge collector
- [x] `GET /metrics` endpoint (unauthenticated, Prometheus exposition format)
- [x] HTTP request middleware: `livesync_http_requests_total{method,endpoint,status}`,
      `livesync_http_request_duration_seconds{method,endpoint}` histogram
- [x] Quartz builder instrumentation: `livesync_quartz_builds_total{vault,status}`,
      `livesync_quartz_build_duration_seconds{vault}` histogram
- [x] Sync status files: `sync/multi-entrypoint.sh` writes `.sync-status.json`
      per vault (cumulative counts + timestamps for sync/mirror ok/fail)
- [x] Portal reads sync status from `vaults` volume:
      `livesync_sync_total{vault,op,status}`,
      `livesync_sync_last_success_seconds{vault,op}`
- [x] Periodic gauge refresh: `livesync_vaults_total`,
      `livesync_vaults_encrypted_total`, `livesync_vault_docs_total{vault}`
      (CouchDB doc counts per vault)
- [x] **Checkpoint**: ✅ `curl localhost:8000/metrics` returns valid Prometheus
      exposition with all 9 metric families populated

### Phase 11: Vault Sharing + First-Login Flow (done)

- [x] `portal/templates/base.html` — shared Tailwind layout with nav
- [x] `portal/templates/welcome.html` — first-login page with server-side
      form POST (`POST /welcome` → redirect to /)
- [x] `portal/templates/vault_detail.html` — vault metadata, member management
      (add/remove), Setup URI generation with copy buttons
- [x] `portal/templates/admin.html` — read-only all-vaults table
- [x] `portal/templates/home.html` — refactored to extend base.html with
      Tailwind, "Create Vault" button, vault detail links
- [x] `portal/app/routes/welcome.py` — `GET /welcome` + `POST /welcome`
      (server-side form, works with HTTP Basic Auth)
- [x] `portal/app/routes/admin.py` — `GET /admin/` dashboard (403 if not admin)
- [x] `portal/app/routes/vaults.py` — `GET /vaults/{name}/detail` vault detail
      page with access control (above catch-all route); `.html` suffix fallback
      for Quartz explorer's extension-less links
- [x] `portal/app/vault_service.py` — `share_vault()`, `unshare_vault()`,
      `list_all_vaults()`, `_sync_security()`, `_vault_info_from_doc()` helper;
      server-side vault name validation (CouchDB lowercase requirement)
- [x] `portal/app/couch.py` — `get_registry_doc()` for single-doc fetch
- [x] `portal/app/models.py` — `MembersUpdate(add, remove)` model
- [x] `PUT /api/vaults/{name}/members` — owner or admin can add/remove members
- [x] Home route redirects to `/welcome` when user has no vaults (302)
- [x] Per-vault Quartz `pageTitle` — sidebar title shows vault name, not "Quartz 4"
- [x] Dark-mode fallback index (matches Quartz dark theme colors)
- [x] `python-multipart` added to dependencies for form handling
- [x] 81 pytest unit tests (27 new: sharing, members API, routes, form POST)
- [x] **Checkpoint**: ✅ new user → `/welcome` → creates vault → shares with
      email → second user sees it; admin → `/admin/` shows all vaults;
      Quartz viewer links resolve correctly; vault names validated server-side

### Phase 12: Encrypted-Only Vaults + Agent Multi-Vault (done)

- [x] Vault creation accepts `encrypted_only` flag (already in Phase 7+11)
- [x] `VaultUpdate` model + `PATCH /api/vaults/{name}` — owner/admin can
      toggle `encrypted_only`; `update_vault()` service method
- [x] Sync + Quartz builder skip encrypted-only vaults (already in Phase 8+9)
- [x] `agent/entrypoint.sh` — dual-mode: `VAULT_NAME` env var for multi-vault
      (fetches passphrase from registry, skips encrypted-only) or legacy
      single-vault (`COUCHDB_DATABASE` + `LIVESYNC_PASSPHRASE`)
- [x] `agent-multi` docker-compose service with admin credentials + `VAULT_NAME`;
      legacy `agent` service and `agent-vault` volume preserved
- [x] `POST /api/vaults/{name}/agent` stub (501 + CLI instructions)
- [x] 89 pytest unit tests (8 new: PATCH settings, 403/404/401, agent stub,
      vault service update)
- [x] **Checkpoint**: ✅ `PATCH /api/vaults/name {"encrypted_only":true}` →
      sync-multi + Quartz skip it; agent-multi targets vault by name;
      encrypted-only agent exits cleanly

### Phase 13: Kubernetes Manifests (done)

- [x] `chart/portal-deployment.yaml` — Portal Deployment with EFS vaults (ro)
      + static (rw) volumes, AUTH_MODE=oidc, readiness/liveness on /healthz
- [x] `chart/portal-service.yaml` — ClusterIP service on port 8000
- [x] `chart/ingress.yaml` — single ALB with dual listeners: HTTPS/443 → portal
      (OIDC via Okta), HTTPS/5984 → CouchDB (no OIDC, CouchDB auth);
      ALB group.name shares one ALB; placeholder OIDC config for Okta
- [x] `chart/couchdb-init-job.yaml` — creates registry + passphrases DBs with
      admin-only `_security` lockdown; removed legacy `$COUCHDB_DATABASE`
- [x] `chart/sync-deployment.yaml` — multi-vault mode (SYNC_MODE=multi,
      `vaults` PVC at /data/vaults)
- [x] `chart/agent-job.yaml` — multi-vault mode (VAULT_NAME env var,
      `agent-data` PVC)
- [x] Removed `chart/viewer-deployment.yaml` + `chart/viewer-service.yaml`
- [x] `chart/pvc-vaults.yaml` (renamed from pvc-vault.yaml), `pvc-static.yaml`,
      `pvc-agent.yaml` — EFS PVCs for vaults, Quartz output, agent data
- [x] `chart/configmap.yaml` — added COUCHDB_EXTERNAL_URI, removed COUCHDB_DATABASE
- [x] `chart/secret.yaml` — added JWT_SIGNING_KEY + okta-oidc-secret placeholder
- [x] `chart/kustomization.yaml` — portal + ingress + new PVCs, removed viewer
- [x] `build-push.sh` — replaced viewer with portal in build targets
- [x] **Checkpoint**: ✅ `kubectl kustomize chart/` renders 18 resources cleanly;
      images correctly rewritten to ECR; dry-run blocked only by expired SSO token

### Phase 14: Production Hardening + Documentation

- [ ] Create `scripts/test-e2e.sh` — automated acceptance tests
- [ ] Create `scripts/migrate-single-to-multi.sh` — migration for existing vaults
- [ ] Create `CLAUDE.md` — project-level context
- [ ] Rewrite `README.md` for multi-tenant architecture
- [ ] Add docker-compose profiles: default, legacy, agent
- [ ] **Checkpoint**: `./scripts/test-e2e.sh` passes green

## Phase 16: S3 Vault Persistence + Read-Only Publish Store

Goal: every vault's publishable markdown lives in one S3 bucket that consumers
(Quartz builds, agents, other services) can mount as a filesystem and refer to
by plain path. CouchDB remains the source of truth; the bucket is a derived,
read-only projection.

### Local test chain (branch `s3-publish`)

- [x] `publish/` service — Python + boto3 sidecar that mirrors
      `/data/vaults/<name>/` (written by sync-multi) to `s3://vaults/<name>/`
      each cycle: uploads changed files (md5 vs ETag), deletes objects that are
      no longer publishable
- [x] Per-page "do not publish" flag — markdown with `publish: false` in YAML
      frontmatter is excluded from the bucket (and removed if published
      earlier); everything still syncs to CouchDB/desktop as usual
- [x] `minio` service — local S3-compatible store (console at :9001) so the
      chain runs without AWS credentials; `S3_ENDPOINT_URL` unset = real AWS
- [ ] **Checkpoint**: markdown pushed through the LiveSync endpoint (CouchDB)
      appears in the bucket; a `publish: false` page does not

### Production direction (not deployed)

- [ ] Real S3 bucket per environment (e.g. `livesync-vaults-<env>`), publisher
      Deployment with IRSA instead of MinIO creds
- [ ] Mount the bucket on EKS via **Amazon S3 Files** — the managed NFS layer
      over S3 that reuses the `aws-efs-csi-driver` (v3.0.0+): consumers get
      POSIX paths (`/vaults/<name>/...`) backed by the bucket. Recipe already
      in the wiki: `eks-s3-files-deployment` (two IRSA roles, `aws_s3files_*`
      Terraform resources, dynamic-provisioning StorageClass via
      `efs.csi.aws.com`)
- [ ] Decide whether Quartz builds read from the S3 Files mount instead of the
      EFS `vaults` PVC (would make published HTML honor `publish: false` for
      free, since flagged pages never reach the mount)
- [ ] Sweep for stale prefixes: publisher only prunes objects inside vaults it
      still sees on disk — a deleted vault's prefix lingers until cleaned up

## Open Questions

1. **livesync-cli maturity** — Experimental (March 2026). May need fallback to
   headless Obsidian if CLI proves unreliable.
2. ~~**Quartz + Obsidian wikilinks**~~ — Resolved by the Quartz v5 upgrade:
   `portal/quartz-template/quartz.config.yaml` sets
   `markdownLinkResolution: shortest` on the crawl-links plugin.
3. **Write serialization** — Single agent at a time for now. Production
   multi-agent needs a queue or conflict resolution strategy.
4. **CouchDB `couch_peruser`** — Auto-creates per-user databases. Could simplify
   private vault provisioning but uses ugly hex database names. Evaluate later.
