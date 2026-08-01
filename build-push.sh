#!/usr/bin/env bash
# Build all custom images (linux/amd64) and push to the eqincubatingimages
# ECR repo in eq-shared-services, tagged per component.
#
# Usage:
#   ./build-push.sh                # build + push all
#   ./build-push.sh sync portal    # build + push specific images
#
# Prerequisites:
#   - docker with buildx
#   - aws sso login --profile eq-shared-services
set -euo pipefail

ACCOUNT_ID=497689819904
REGION=us-east-1
AWS_PROFILE="${AWS_PROFILE:-eq-shared-services}"
REPO=eqincubatingimages
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
IMAGE_BASE="${REGISTRY}/${REPO}"
PLATFORM=linux/amd64
GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "dev")

# Components and their build contexts / Dockerfiles
declare -A CONTEXTS=(
  [livesync-cli]="vendor/obsidian-livesync"
  [sync]="sync"
  [portal]="portal"
  [agent]="agent"
  [publish]="publish"
)
# livesync-cli uses a patched copy of the vendored Dockerfile (npm ci against
# the lockfile; upstream's npm install breaks on a phantom @smithy dep)
declare -A DOCKERFILES=(
  [livesync-cli]="livesync-cli.Dockerfile"
  [sync]="sync/Dockerfile"
  [portal]="portal/Dockerfile"
  [agent]="agent/Dockerfile"
  [publish]="publish/Dockerfile"
)

# livesync-cli is a build dependency, not pushed separately by default
PUSHABLE=(sync portal agent publish)

# If args given, only build+push those (but always build livesync-cli first)
TARGETS=("${@:-${PUSHABLE[@]}}")

log() { echo "==> $*"; }

# ── ECR auth ─────────────────────────────────────────────────────────────────
if ! aws sts get-caller-identity --profile "${AWS_PROFILE}" >/dev/null 2>&1; then
  echo "ERROR: no valid AWS session for profile '${AWS_PROFILE}'." >&2
  echo "Run: aws sso login --profile ${AWS_PROFILE}" >&2
  exit 1
fi
export AWS_PROFILE
if grep -qs "\"${REGISTRY}\": \"ecr-login\"" ~/.docker/config.json; then
  # amazon-ecr-credential-helper fetches tokens per push using AWS_PROFILE;
  # `docker login` would fail against it (the helper can't *store* creds)
  log "ECR auth via amazon-ecr-credential-helper (profile ${AWS_PROFILE})"
else
  log "Logging in to ECR (${REGISTRY}) with profile ${AWS_PROFILE}"
  aws ecr get-login-password --region "${REGION}" \
    | docker login --username AWS --password-stdin "${REGISTRY}"
fi

# ── Build livesync-cli base image (always needed) ───────────────────────────
log "Building livesync-cli:local (base image)"
docker buildx build \
  --platform "${PLATFORM}" \
  -f "${DOCKERFILES[livesync-cli]}" \
  -t livesync-cli:local \
  --load \
  "${CONTEXTS[livesync-cli]}"

# ── Build and push requested images ─────────────────────────────────────────
for name in "${TARGETS[@]}"; do
  if [[ -z "${CONTEXTS[$name]+x}" ]]; then
    echo "ERROR: unknown component '${name}'" >&2
    echo "Valid components: ${!CONTEXTS[*]}" >&2
    exit 1
  fi

  tag="${IMAGE_BASE}:${name}-${GIT_SHA}"
  tag_latest="${IMAGE_BASE}:${name}-latest"

  log "Building ${name} → ${tag}"
  docker buildx build \
    --platform "${PLATFORM}" \
    -f "${DOCKERFILES[$name]}" \
    -t "${tag}" \
    -t "${tag_latest}" \
    --load \
    "${CONTEXTS[$name]}"

  log "Pushing ${tag}"
  docker push "${tag}"
  docker push "${tag_latest}"

  log "Pushed ${name}: ${tag_latest}"
done

log "Done. Images:"
for name in "${TARGETS[@]}"; do
  echo "  ${IMAGE_BASE}:${name}-latest"
  echo "  ${IMAGE_BASE}:${name}-${GIT_SHA}"
done
