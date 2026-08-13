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

_FAMILIES = {
    "GLIBC": re.compile(r"\bGLIBC_([0-9]+(?:\.[0-9]+)*)\b"),
    "GLIBCXX": re.compile(r"\bGLIBCXX_([0-9]+(?:\.[0-9]+)*)\b"),
    "CXXABI": re.compile(r"\bCXXABI_([0-9]+(?:\.[0-9]+)*)\b"),
}

# libstdc++ symbol versions do not follow glibc numbering, so the declared glibc
# floor implies its own ceilings: the libstdc++ that ships on the oldest distros
# that floor promises (glibc 2.28 = the RHEL 8 / GCC 8 era). Extend this table
# when the floor moves; an unknown floor fails loudly rather than skipping the
# C++ check.
_LIBSTDCXX_CEILINGS: dict[tuple[int, ...], dict[str, tuple[int, ...]]] = {
    (2, 28): {"GLIBCXX": (3, 4, 25), "CXXABI": (1, 3, 11)},
}


def _version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _requirements(path: Path) -> list[tuple[str, str]]:
    result = subprocess.run(
        ["readelf", "--version-info", str(path)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return [
        (family, value)
        for family, pattern in _FAMILIES.items()
        for value in pattern.findall(_needs_sections(result.stdout))
    ]


def _needs_sections(version_info: str) -> str:
    """Only the "Version needs" section of ``readelf --version-info`` output.

    The definition section lists what a library itself EXPORTS — a bundled
    libstdc++ defines every GLIBCXX up to its build toolchain's — and counting
    those as host requirements would reject a self-contained bundle that runs
    fine on the floor.
    """
    keep: list[str] = []
    capture = False
    for line in version_info.splitlines():
        if line.startswith("Version needs section"):
            capture = True
        elif line.startswith("Version") and "section" in line:
            capture = False
        if capture:
            keep.append(line)
    return "\n".join(keep)


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
    if floor not in _LIBSTDCXX_CEILINGS:
        parser.error(
            f"no libstdc++ ceilings recorded for a GLIBC_{args.floor} floor — "
            "extend _LIBSTDCXX_CEILINGS for the new floor"
        )
    ceilings: dict[str, tuple[int, ...]] = {"GLIBC": floor, **_LIBSTDCXX_CEILINGS[floor]}

    found: dict[str, list[tuple[tuple[int, ...], str]]] = {family: [] for family in _FAMILIES}
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
            for family, value in _requirements(path):
                found[family].append((_version(value), label))

    # Every ELF requires glibc, so an empty scan means the scan is broken; a
    # bundle with no C++ objects legitimately has no GLIBCXX/CXXABI entries.
    if not found["GLIBC"]:
        parser.error("no GLIBC requirements found in release artifacts")
    failed = False
    for family, entries in found.items():
        if not entries:
            continue
        required, label = max(entries)
        dotted = ".".join(map(str, required))
        ceiling = ".".join(map(str, ceilings[family]))
        if required > ceilings[family]:
            print(
                f"declared GLIBC_{args.floor} floor allows {family}_{ceiling}, but "
                f"release artifacts require {family}_{dotted} ({label})"
            )
            failed = True
        else:
            print(
                f"{family} ABI OK: maximum requirement is {family}_{dotted} "
                f"({label}), within {family}_{ceiling} for the GLIBC_{args.floor} floor"
            )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
