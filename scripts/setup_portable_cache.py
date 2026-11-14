"""Recreate the portable-build cache (embeddable Python + pinned wheels).

The portable build needs two inputs that are not stored in git:

  .release_cache/python-3.11.9-embed-amd64/   official CPython Windows embed files
  .release_cache/wheels/                      win_amd64 wheels for the deps

Downloading python.org directly is not always possible (some sandboxes block it),
so the embeddable runtime can also be reassembled from a public GitHub mirror:
each file is fetched through the GitHub blob API and its git object id is
verified against the tree, which pins the exact bytes.

Usage:
    python scripts/setup_portable_cache.py            # both inputs
    python scripts/setup_portable_cache.py --embed     # embeddable Python only
    python scripts/setup_portable_cache.py --wheels    # wheels only
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".release_cache"

MIRROR_REPO = "jacklinquan/portable_llama_chatbot"
MIRROR_PREFIX = "portable_llama_chatbot/python-3.11.9-embed-amd64/"
# The mirror also contains an added Lib/site-packages tree; only the runtime
# files that belong to the official embed archive are copied.
SKIP_DIRS = ("Lib/", "Scripts/")

WHEELS = (
    "pyside6-essentials==6.12.0",
    "shiboken6==6.12.0",
    "cryptography>=46",
    "certifi",
    "httpx[http2]",
    "pydivert>=3.1.1",
    "pypresence",
    "h2",
    "hpack",
    "hyperframe",
    "httpcore",
    "h11",
    "anyio",
    "sniffio",
    "idna",
    "cffi",
    "pycparser",
    "typing_extensions",
)


def _gh(*args: str) -> bytes:
    result = subprocess.run(["gh", *args], capture_output=True, check=True)
    return result.stdout


def _fetch_embed(target: Path) -> None:
    tree = json.loads(_gh("api", f"repos/{MIRROR_REPO}/git/trees/HEAD?recursive=1"))
    if tree.get("truncated"):
        raise SystemExit("mirror tree is truncated; cannot verify object ids")
    entries = [
        (item["path"][len(MIRROR_PREFIX):], item["sha"], item.get("size"))
        for item in tree["tree"]
        if item["type"] == "blob"
        and item["path"].startswith(MIRROR_PREFIX)
        and not item["path"][len(MIRROR_PREFIX):].startswith(SKIP_DIRS)
    ]
    if not entries:
        raise SystemExit("mirror layout changed: no runtime files found")

    target.mkdir(parents=True, exist_ok=True)

    def fetch(item: tuple[str, str, int]) -> tuple[str, int]:
        name, sha, _size = item
        payload = json.loads(_gh("api", "--method", "GET", f"repos/{MIRROR_REPO}/git/blobs/{sha}"))
        raw = base64.b64decode(payload["content"])
        header = b"blob %d\0" % len(raw)
        if hashlib.sha1(header + raw).hexdigest() != sha:
            raise SystemExit(f"git object verification failed for {name}")
        (target / name).write_bytes(raw)
        return name, len(raw)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(fetch, entries))
    print(f"embeddable python: {len(results)} files, {sum(size for _n, size in results)} bytes -> {target}")


def _fetch_wheels(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--no-deps",
        "--platform", "win_amd64", "--python-version", "311", "--implementation", "cp",
        "--abi", "cp311", "-d", str(target), *WHEELS,
    ]
    subprocess.run(command, check=True)
    print(f"wheels -> {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embed", action="store_true")
    parser.add_argument("--wheels", action="store_true")
    args = parser.parse_args(argv)
    want_embed = args.embed or not (args.embed or args.wheels)
    want_wheels = args.wheels or not (args.embed or args.wheels)
    if want_embed:
        _fetch_embed(CACHE / "python-3.11.9-embed-amd64")
    if want_wheels:
        _fetch_wheels(CACHE / "wheels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
