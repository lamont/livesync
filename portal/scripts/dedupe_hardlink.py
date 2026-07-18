"""Hardlink-dedupe identical files under a directory tree.

Quartz v5 community plugins each vendor their own node_modules, so the same
toolchain files (typescript, esbuild, rollup, ...) appear ~30 times. Running
this in the image build stage collapses identical files into hardlinks before
the tree is COPY'd into the final image.

Usage: python3 dedupe_hardlink.py <root> [<root>...]
"""

import hashlib
import os
import sys

MIN_SIZE = 4096


def dedupe(roots: list[str]) -> None:
    by_hash: dict[str, str] = {}
    saved = 0
    count = 0
    for root in roots:
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                path = os.path.join(dirpath, fn)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                if not os.path.isfile(path) or os.path.islink(path):
                    continue
                if st.st_size < MIN_SIZE or st.st_nlink > 1:
                    continue
                with open(path, "rb") as f:
                    digest = hashlib.sha256(f.read()).hexdigest()
                key = f"{digest}:{st.st_size}"
                original = by_hash.get(key)
                if original is None:
                    by_hash[key] = path
                    continue
                tmp = path + ".dedupe-tmp"
                os.link(original, tmp)
                os.replace(tmp, path)
                saved += st.st_size
                count += 1
    print(f"deduped {count} files, saved {saved / 1e6:.0f} MB")


if __name__ == "__main__":
    dedupe(sys.argv[1:] or ["."])
