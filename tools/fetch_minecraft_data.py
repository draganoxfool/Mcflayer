#!/usr/bin/env python3
"""Vendor the files PyFlayer needs from PrismarineJS/minecraft-data.

The loader only reads a small subset of ``minecraft-data``.  This tool flattens
the per-version inheritance in ``dataPaths.json`` into ``data/pc/<version>`` and
updates ``data/dataPaths.json`` so every requested version is self-contained.

Examples:
    # Vendor the latest protocol plus the configuration-state reference version
    python tools/fetch_minecraft_data.py 1.20.4 26.1

    # Vendor every version advertised in dataPaths.json (large checkout)
    python tools/fetch_minecraft_data.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = "https://raw.githubusercontent.com/PrismarineJS/minecraft-data/master/data"

#: Files consumed by pyflayer.data.loader.
FILES = (
    "blocks",
    "items",
    "entities",
    "biomes",
    "effects",
    "foods",
    "blockCollisionShapes",
    "protocol",
    "version",
)


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - fixed host
        return response.read()


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def download_version(version: str, paths: dict[str, object]) -> None:
    entries = paths["pc"]
    if not isinstance(entries, dict) or version not in entries:
        raise SystemExit(f"minecraft-data has no pc version {version!r}")
    mapping = entries[version]
    if not isinstance(mapping, dict):
        raise SystemExit(f"malformed dataPaths entry for {version!r}")

    target = DATA / "pc" / version
    target.mkdir(parents=True, exist_ok=True)
    flat: dict[str, str] = {}
    for file_key in FILES:
        relative = mapping.get(file_key)
        if not isinstance(relative, str):
            raise SystemExit(f"{version}: dataPaths has no {file_key!r} entry")
        source = f"{RAW}/{relative}/{file_key}.json"
        print(f"  {version}: {file_key} <- {relative}")
        (target / f"{file_key}.json").write_bytes(fetch(source))
        flat[file_key] = f"pc/{version}"
    # The loader only reads these keys; other historical keys are intentionally omitted.
    entries[version] = flat


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("versions", nargs="*", help="Minecraft versions to vendor")
    parser.add_argument("--all", action="store_true", help="vendor every pc version")
    args = parser.parse_args(argv)

    paths_file = DATA / "dataPaths.json"
    paths = load_json(paths_file)
    if not isinstance(paths, dict):
        raise SystemExit("dataPaths.json must contain an object")

    # Always start from the upstream list so newly released versions are visible.
    upstream = json.loads(fetch(f"{RAW}/dataPaths.json"))
    if not isinstance(upstream, dict):
        raise SystemExit("upstream dataPaths.json must contain an object")
    upstream_pc = upstream["pc"]
    if not isinstance(upstream_pc, dict):
        raise SystemExit("upstream dataPaths.json has no pc map")

    versions = list(upstream_pc) if args.all else args.versions
    if not versions:
        parser.error("pass at least one version or --all")
    missing = [version for version in versions if version not in upstream_pc]
    if missing:
        raise SystemExit(f"unknown versions: {', '.join(missing)}")

    paths["pc"] = dict(paths.get("pc", {}))
    for version in versions:
        download_version(version, upstream)
        flat = flat = upstream["pc"][version]  # noqa: F841 - kept for clarity
        # ``download_version`` mutates ``upstream``; copy the flattened map across.
        paths["pc"][version] = upstream["pc"][version]

    paths_file.write_text(json.dumps(paths, indent=2) + "\n", encoding="utf-8")
    print(f"updated {paths_file.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
