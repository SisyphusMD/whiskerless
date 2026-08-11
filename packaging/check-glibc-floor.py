#!/usr/bin/env python3
"""Fail the release if a Linux binary needs newer glibc than we promise.

PyInstaller freezes the interpreter but links against the BUILD machine's glibc,
so a bundle built on a current Ubuntu silently requires that glibc and dies with
'version GLIBC_2.39 not found' on Debian 12, RHEL 9, or an older Pi OS — the
machines most likely to be sitting next to a litter box. Nothing else notices:
the binary builds, uploads and runs fine on the runner that made it.

Checks the embedded ELFs too, not just the outer executable: the bundled shared
libraries carry their own requirements and are usually the highest.

    check-glibc-floor.py "2.28" dist/whiskerless
"""
from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

_VERSION = re.compile(r"\bGLIBC_([0-9]+(?:\.[0-9]+)*)\b")


def _version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _requirements(path: Path) -> list[str]:
    result = subprocess.run(
        ["readelf", "--version-info", str(path)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return _VERSION.findall(result.stdout)


def _embedded_elfs(bundle: Path, destination: Path) -> list[tuple[str, Path]]:
    # PyInstaller is deliberately a release-build dependency, not a project runtime dependency.
    from PyInstaller.archive.readers import ArchiveReadError, CArchiveReader

    try:
        archive = CArchiveReader(str(bundle))
    except ArchiveReadError:
        return []

    destination.mkdir(parents=True)
    extracted: list[tuple[str, Path]] = []
    for index, name in enumerate(archive.toc):
        data = archive.extract(name)
        if not isinstance(data, bytes) or not data.startswith(b"\x7fELF"):
            continue
        path = destination / str(index)
        path.write_bytes(data)
        extracted.append((f"{bundle.name}:{name}", path))
    return extracted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("floor")
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()

    floor = _version(args.floor)
    found: list[tuple[tuple[int, ...], str]] = []
    with tempfile.TemporaryDirectory() as temporary:
        destination = Path(temporary)
        candidates: list[tuple[str, Path]] = []
        for artifact_index, artifact in enumerate(args.artifacts):
            with artifact.open("rb") as stream:
                is_elf = stream.read(4) == b"\x7fELF"
            if is_elf:
                candidates.append((artifact.name, artifact))
            candidates.extend(_embedded_elfs(artifact, destination / str(artifact_index)))

        for label, path in candidates:
            found.extend((_version(value), label) for value in _requirements(path))

    if not found:
        parser.error("no GLIBC requirements found in release artifacts")
    required, label = max(found)
    if required > floor:
        print(
            f"declared GLIBC_{args.floor} floor, but release artifacts require "
            f"GLIBC_{'.'.join(map(str, required))} ({label})"
        )
        return 1
    print(
        f"glibc ABI OK: maximum requirement is GLIBC_{'.'.join(map(str, required))} "
        f"({label}), within the declared GLIBC_{args.floor} floor"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
