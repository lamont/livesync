"""Prometheus metrics for the LiveSync portal.

Exposes counters, gauges, and histograms covering:
- HTTP request volume and latency
- Quartz build success/failure and duration
- Sync/mirror success/failure from status files written by sync-multi
- Vault and user counts from the CouchDB registry
- Per-vault CouchDB document counts
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from .couch import CouchClient

log = logging.getLogger(__name__)

# Use the default registry so all metrics are automatically included.
# ── HTTP metrics ────────────────────────────────────────────────────────────

HTTP_REQUESTS = Counter(
    "livesync_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

HTTP_DURATION = Histogram(
    "livesync_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# ── Quartz build metrics ───────────────────────────────────────────────────

QUARTZ_BUILDS = Counter(
    "livesync_quartz_builds_total",
    "Quartz static-site builds",
    ["vault", "status"],
)

QUARTZ_BUILD_DURATION = Histogram(
    "livesync_quartz_build_duration_seconds",
    "Quartz build wall-clock time",
    ["vault"],
    buckets=(1, 2, 5, 10, 20, 30, 60, 120),
)

# ── Sync metrics (populated from .sync-status.json files) ──────────────────

SYNC_RUNS = Gauge(
    "livesync_sync_total",
    "Cumulative sync/mirror runs reported by the sync service",
    ["vault", "op", "status"],
)

SYNC_LAST_SUCCESS = Gauge(
    "livesync_sync_last_success_seconds",
    "Unix timestamp of last successful sync/mirror",
    ["vault", "op"],
)

# ── Registry / CouchDB gauges ──────────────────────────────────────────────

VAULTS_TOTAL = Gauge("livesync_vaults_total", "Total registered vaults")
VAULTS_ENCRYPTED = Gauge("livesync_vaults_encrypted_total", "Encrypted-only vaults")
VAULT_DOCS = Gauge(
    "livesync_vault_docs_total",
    "CouchDB document count per vault database",
    ["vault"],
)

# ── Settings ────────────────────────────────────────────────────────────────

VAULTS_DIR = Path(os.environ.get("VAULTS_DIR", "/vaults"))
GAUGE_REFRESH_INTERVAL = int(os.environ.get("METRICS_REFRESH_INTERVAL", "30"))

# Paths that should not be individually labeled (collapse to pattern)
_PARAMETRIC_PREFIXES = ("/vaults/", "/api/vaults/")


def _normalize_endpoint(path: str) -> str:
    """Collapse per-resource paths into label-friendly patterns."""
    for prefix in _PARAMETRIC_PREFIXES:
        if path.startswith(prefix):
            rest = path[len(prefix):]
            if "/" in rest:
                return prefix + "{name}/{path}"
            if rest:
                return prefix + "{name}"
    return path


def metrics_output() -> bytes:
    """Generate Prometheus exposition format output."""
    return generate_latest()


def _read_sync_status_files() -> None:
    """Read .sync-status.json from each vault dir and update gauges."""
    if not VAULTS_DIR.exists():
        return
    for entry in VAULTS_DIR.iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        status_file = entry / ".sync-status.json"
        if not status_file.exists():
            continue
        try:
            data = json.loads(status_file.read_text())
            vault = entry.name
            for op in ("sync", "mirror"):
                ok = data.get(f"{op}_ok_count", 0)
                fail = data.get(f"{op}_fail_count", 0)
                SYNC_RUNS.labels(vault=vault, op=op, status="success").set(ok)
                SYNC_RUNS.labels(vault=vault, op=op, status="failure").set(fail)
                last_ok = data.get(f"last_{op}_ok", 0)
                if last_ok:
                    SYNC_LAST_SUCCESS.labels(vault=vault, op=op).set(last_ok)
        except Exception:
            log.debug("Could not read sync status for %s", entry.name)


async def _refresh_couch_gauges(couch: CouchClient) -> None:
    """Update vault-count and per-vault doc-count gauges from CouchDB."""
    try:
        registry = await couch.get_registry()
        total = len(registry)
        encrypted = sum(1 for d in registry if d.get("encrypted_only"))
        VAULTS_TOTAL.set(total)
        VAULTS_ENCRYPTED.set(encrypted)

        for doc in registry:
            name = doc.get("name")
            if not name:
                continue
            try:
                resp = await couch._http.get(f"/{name}")
                if resp.status_code == 200:
                    info = resp.json()
                    VAULT_DOCS.labels(vault=name).set(info.get("doc_count", 0))
            except Exception:
                pass
    except Exception:
        log.debug("Could not refresh CouchDB gauges")


async def gauge_refresh_loop(couch: CouchClient) -> None:
    """Periodically refresh gauges from CouchDB + sync status files."""
    log.info("Metrics gauge collector started (interval=%ds)", GAUGE_REFRESH_INTERVAL)
    while True:
        try:
            await _refresh_couch_gauges(couch)
            _read_sync_status_files()
        except Exception:
            log.exception("Gauge refresh error")
        await asyncio.sleep(GAUGE_REFRESH_INTERVAL)
