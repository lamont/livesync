"""Background task: per-vault Quartz static-site builds.

Scans the vaults directory on a configurable interval, checks mtimes of
markdown files, and rebuilds only vaults whose content has changed.
Encrypted-only vaults (per the CouchDB registry) are skipped.
"""

import asyncio
import logging
import os
import time
from pathlib import Path

from .couch import CouchClient
from .metrics import QUARTZ_BUILD_DURATION, QUARTZ_BUILDS

log = logging.getLogger(__name__)

QUARTZ_DIR = os.environ.get("QUARTZ_DIR", "/quartz")
VAULTS_DIR = os.environ.get("VAULTS_DIR", "/vaults")
STATIC_DIR = os.environ.get("STATIC_DIR", "/static")
BUILD_INTERVAL = int(os.environ.get("QUARTZ_BUILD_INTERVAL", "30"))


def _latest_mtime(vault_path: Path) -> float:
    """Return the most recent mtime of any .md file in a vault directory."""
    latest = 0.0
    for f in vault_path.rglob("*.md"):
        try:
            latest = max(latest, f.stat().st_mtime)
        except OSError:
            continue
    return latest


class QuartzBuilder:
    """Watches vault directories and triggers Quartz builds when content changes."""

    def __init__(self, couch: CouchClient):
        self.couch = couch
        self.vaults_dir = Path(VAULTS_DIR)
        self.static_dir = Path(STATIC_DIR)
        self._mtimes: dict[str, float] = {}

    async def build_all(self) -> None:
        """Scan vaults and rebuild any that have changed."""
        if not self.vaults_dir.exists():
            log.debug("Vaults directory %s does not exist yet", self.vaults_dir)
            return

        # Fetch encrypted-only set from registry
        encrypted: set[str] = set()
        try:
            registry = await self.couch.get_registry()
            encrypted = {d["name"] for d in registry if d.get("encrypted_only")}
        except Exception:
            log.warning("Could not fetch registry; building all non-empty vaults")

        for entry in sorted(self.vaults_dir.iterdir()):
            if not entry.is_dir():
                continue
            name = entry.name
            if name.startswith("."):
                continue
            if name in encrypted:
                log.debug("Skipping encrypted-only vault: %s", name)
                continue

            mtime = _latest_mtime(entry)
            if mtime == 0.0:
                continue  # no markdown files

            if mtime <= self._mtimes.get(name, 0):
                continue  # no changes since last build

            log.info("Building vault: %s (mtime %.0f → %.0f)", name,
                     self._mtimes.get(name, 0), mtime)
            ok = await self._build_vault(name)
            if ok:
                self._mtimes[name] = mtime

    async def _build_vault(self, name: str) -> bool:
        """Run npx quartz build for a single vault. Returns True on success."""
        content_dir = str(self.vaults_dir / name)
        output_dir = str(self.static_dir / name)
        os.makedirs(output_dir, exist_ok=True)

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                "npx", "quartz", "build",
                "--directory", content_dir,
                "--output", output_dir,
                cwd=QUARTZ_DIR,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            elapsed = time.monotonic() - start

            if proc.returncode != 0:
                log.error("Quartz build failed for %s (rc=%d):\n%s",
                          name, proc.returncode, stderr.decode()[-2000:])
                QUARTZ_BUILDS.labels(vault=name, status="failure").inc()
                QUARTZ_BUILD_DURATION.labels(vault=name).observe(elapsed)
                return False

            log.info("Quartz build succeeded for %s (%.1fs)", name, elapsed)
            QUARTZ_BUILDS.labels(vault=name, status="success").inc()
            QUARTZ_BUILD_DURATION.labels(vault=name).observe(elapsed)
            self._ensure_index(name)
            return True

        except Exception:
            log.exception("Quartz build error for %s", name)
            QUARTZ_BUILDS.labels(vault=name, status="failure").inc()
            QUARTZ_BUILD_DURATION.labels(vault=name).observe(time.monotonic() - start)
            return False

    def _ensure_index(self, name: str) -> None:
        """Generate a fallback index.html if Quartz didn't create one."""
        index = self.static_dir / name / "index.html"
        if index.exists():
            return
        output_dir = self.static_dir / name
        pages = sorted(
            f.stem for f in output_dir.glob("*.html")
            if f.stem not in ("404",)
        )
        if not pages:
            return
        links = "\n".join(
            f'      <li><a href="{p}.html">{p.replace("-", " ").replace("_", " ")}</a></li>'
            for p in pages
        )
        index.write_text(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{name}</title>
<style>body{{font-family:sans-serif;max-width:700px;margin:2rem auto;padding:0 1rem}}
a{{color:#1a73e8}}li{{margin:.4rem 0}}</style></head>
<body><h1>{name}</h1><ul>
{links}
</ul></body></html>
""")
        log.info("Generated fallback index.html for %s (%d pages)", name, len(pages))

    async def run_loop(self) -> None:
        """Run builds in a loop forever."""
        log.info("Quartz builder started (interval=%ds, vaults=%s, static=%s)",
                 BUILD_INTERVAL, self.vaults_dir, self.static_dir)
        while True:
            try:
                await self.build_all()
            except Exception:
                log.exception("Quartz builder loop error")
            await asyncio.sleep(BUILD_INTERVAL)
