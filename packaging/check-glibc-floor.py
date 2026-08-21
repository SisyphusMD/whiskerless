#!/usr/bin/env python3
"""Refuse a release artifact that needs a newer glibc/libstdc++ than the declared floor.

    check-glibc-floor.py <floor> <artifact>...

An artifact may be a plain ELF, a PyInstaller onefile bundle (whose payload is scanned by extracting
its archive), or a onedir bundle directory (walked for every ELF inside it). All three shapes ship
across these projects, so all three are handled here.

Three symbol families are checked, not one. A bundle that satisfies the glibc floor can still fail on
an old host through libstdc++: `GLIBCXX` and `CXXABI` version independently of glibc, so the declared
glibc floor implies its own ceilings for them.
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

# libstdc++ symbol versions do not follow glibc numbering, so the declared glibc floor implies its
# own ceilings: the libstdc++ that ships on the oldest distros that floor promises (glibc 2.28 =
# the RHEL 8 / GCC 8 era). Extend this table when the floor moves; an unknown floor fails loudly
# rather than skipping the C++ check.
_LIBSTDCXX_CEILINGS: dict[tuple[int, ...], dict[str, tuple[int, ...]]] = {
    (2, 28): {"GLIBCXX": (3, 4, 25), "CXXABI": (1, 3, 11)},
}


def _version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _needs_sections(version_info: str) -> str:
    """Only the "Version needs" section of ``readelf --version-info`` output.

    The definition section lists what a library itself EXPORTS — a bundled libstdc++ defines every
    GLIBCXX up to its build toolchain's — and counting those as host requirements would reject a
    self-contained bundle that runs fine on the floor.
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


def _requirements(path: Path) -> list[tuple[str, str]]:
    result = subprocess.run(
        ["readelf", "--version-info", str(path)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    needs = _needs_sections(result.stdout)
    return [
        (family, value)
        for family, pattern in _FAMILIES.items()
        for value in pattern.findall(needs)
    ]


def _is_elf(path: Path) -> bool:
    with path.open("rb") as stream:
        return stream.read(4) == b"\x7fELF"


def _tree_elfs(root: Path) -> list[tuple[str, Path]]:
    """Every ELF inside a onedir bundle. Symlinks are skipped: their target is walked anyway, and
    auditing the same file twice would only make the reported label arbitrary."""
    found: list[tuple[str, Path]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file() or not _is_elf(path):
            continue
        found.append((f"{root.name}/{path.relative_to(root).as_posix()}", path))
    return found


def _embedded_elfs(bundle: Path, destination: Path) -> list[tuple[str, Path]]:
    # PyInstaller is deliberately a release-build dependency, not a project runtime dependency.
    #
    # Its absence is fatal rather than a skip, deliberately. Whether a given ELF is a onefile bundle
    # is only knowable by trying to read its archive, so "PyInstaller missing" and "not a bundle"
    # are indistinguishable here — and quietly treating the first as the second would let a onefile
    # payload through this gate entirely unscanned.
    try:
        from PyInstaller.archive.readers import ArchiveReadError, CArchiveReader
    except ImportError as exc:  # pragma: no cover - environment error, not a code path
        raise SystemExit(
            f"cannot scan {bundle.name}: PyInstaller is not importable, so a onefile bundle's "
            "payload could not be checked. Install the release build dependencies before running "
            "this gate."
        ) from exc

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
            # A mistyped path is a one-line error, not a traceback: this runs in a release gate
            # where the failure needs to name what is wrong, not where Python noticed.
            if not artifact.exists():
                parser.error(f"no such release artifact: {artifact}")
            # A onedir bundle arrives as a directory; a onefile bundle and a plain helper both
            # arrive as a single ELF, the first of which also carries its payload inside itself.
            if artifact.is_dir():
                candidates.extend(_tree_elfs(artifact))
                continue
            if _is_elf(artifact):
                candidates.append((artifact.name, artifact))
            candidates.extend(_embedded_elfs(artifact, destination / str(artifact_index)))

        for label, path in candidates:
            for family, value in _requirements(path):
                found[family].append((_version(value), label))

    # Every ELF requires glibc, so an empty scan means the scan is broken; a bundle with no C++
    # objects legitimately has no GLIBCXX/CXXABI entries.
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
