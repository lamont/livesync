"""S3 vault publisher: mirror synced vaults to an S3 bucket on a loop.

Reads every vault under VAULTS_DIR (written by sync-multi) and mirrors the
publishable files to s3://S3_BUCKET/<vault>/<relpath>. Markdown pages with
`publish: false` in their YAML frontmatter are excluded — and removed from
the bucket if they were published before the flag was set.

The bucket is the read-only projection of the vaults: objects the mirror no
longer considers publishable are deleted from the vault's prefix.
"""

import hashlib
import logging
import mimetypes
import os
import time
from pathlib import Path

import boto3
import yaml
from boto3.s3.transfer import TransferConfig

log = logging.getLogger("publish")

VAULTS_DIR = Path(os.environ.get("VAULTS_DIR", "/data/vaults"))
S3_BUCKET = os.environ.get("S3_BUCKET", "vaults")
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL") or None
S3_PREFIX = os.environ.get("S3_PREFIX", "").strip("/")
PUBLISH_INTERVAL = int(os.environ.get("PUBLISH_INTERVAL", "60"))

# livesync-cli working state that must never be published
SKIP_DIR_SUFFIXES = ("-livesync-v2",)
FRONTMATTER_SCAN_BYTES = 64 * 1024

# keep uploads single-part so the ETag stays an md5 we can diff against
TRANSFER_CONFIG = TransferConfig(multipart_threshold=256 * 1024 * 1024)


def is_publishable_markdown(path: Path) -> bool:
    """False only when the page's frontmatter explicitly sets publish: false."""
    try:
        head = path.open("rb").read(FRONTMATTER_SCAN_BYTES).decode("utf-8", "replace")
    except OSError as exc:
        log.warning("unreadable %s (%s) — skipping", path, exc)
        return False
    if not head.startswith("---\n"):
        return True
    end = head.find("\n---", 4)
    if end == -1:
        return True
    try:
        fm = yaml.safe_load(head[4:end])
    except yaml.YAMLError:
        log.warning("unparseable frontmatter in %s — publishing anyway", path)
        return True
    return not (isinstance(fm, dict) and fm.get("publish") is False)


def eligible_files(vault_dir: Path):
    """Yield (relative_posix_path, absolute_path) for publishable files."""
    for root, dirs, files in os.walk(vault_dir):
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".") and not d.endswith(SKIP_DIR_SUFFIXES)
        ]
        for name in files:
            if name.startswith("."):
                continue
            path = Path(root) / name
            if name.endswith(".md") and not is_publishable_markdown(path):
                continue
            yield path.relative_to(vault_dir).as_posix(), path


def md5_hex(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def remote_objects(s3, prefix: str) -> dict[str, str]:
    """Map key -> etag for every object under prefix."""
    found = {}
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=S3_BUCKET, Prefix=prefix
    ):
        for obj in page.get("Contents", []):
            found[obj["Key"]] = obj["ETag"].strip('"')
    return found


def publish_vault(s3, vault_dir: Path) -> tuple[int, int]:
    prefix = "/".join(p for p in (S3_PREFIX, vault_dir.name) if p) + "/"
    remote = remote_objects(s3, prefix)
    uploaded = 0

    local_keys = set()
    for rel, path in eligible_files(vault_dir):
        key = prefix + rel
        local_keys.add(key)
        # single-part upload etag == md5, so this skips unchanged files
        if remote.get(key) != md5_hex(path):
            content_type = (
                "text/markdown" if rel.endswith(".md")
                else mimetypes.guess_type(rel)[0] or "application/octet-stream"
            )
            s3.upload_file(
                str(path), S3_BUCKET, key,
                ExtraArgs={"ContentType": content_type},
                Config=TRANSFER_CONFIG,
            )
            log.info("uploaded %s", key)
            uploaded += 1

    stale = [k for k in remote if k not in local_keys]
    for key in stale:
        s3.delete_object(Bucket=S3_BUCKET, Key=key)
        log.info("deleted %s (no longer publishable)", key)
    return uploaded, len(stale)


def ensure_bucket(s3):
    try:
        s3.head_bucket(Bucket=S3_BUCKET)
    except s3.exceptions.ClientError:
        log.info("creating bucket %s", S3_BUCKET)
        s3.create_bucket(Bucket=S3_BUCKET)


def main():
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    s3 = boto3.client("s3", endpoint_url=S3_ENDPOINT_URL)
    log.info(
        "publishing %s -> s3://%s/%s (endpoint=%s) every %ss",
        VAULTS_DIR, S3_BUCKET, S3_PREFIX, S3_ENDPOINT_URL or "aws", PUBLISH_INTERVAL,
    )
    ensure_bucket(s3)
    while True:
        try:
            for vault_dir in sorted(p for p in VAULTS_DIR.iterdir() if p.is_dir()):
                uploaded, deleted = publish_vault(s3, vault_dir)
                if uploaded or deleted:
                    log.info(
                        "%s: %d uploaded, %d deleted", vault_dir.name, uploaded, deleted
                    )
        except Exception:
            log.exception("publish cycle failed")
        time.sleep(PUBLISH_INTERVAL)


if __name__ == "__main__":
    main()
