#!/usr/bin/env python3
"""Generate the Homebrew resource blocks for the formula templates.

`virtualenv_install_with_resources` installs every resource with pip's --no-deps,
so the list has to be the COMPLETE closure. A partial list installs cleanly and
then fails on the first import, which is the worst outcome available: the formula
looks fine until a user runs it.

bleak's dependencies are platform-conditional (pyobjc on macOS, dbus-fast on
Linux), so the closure is resolved per platform and the difference is emitted as
`on_macos` / `on_linux` blocks. Installing pyobjc on Linux would simply fail.

Resolved from the LOCAL pyproject, not from a published release: resources are
regenerated when dependencies change, which is before any release carries that
change, so the version to resolve against does not exist on PyPI yet. (And the
version in pyproject is only ever moved by the Release workflow, so there is no
pre-release version to name either.)

Run after any dependency change, and paste the output between the RESOURCES
markers in both formula templates:

    packaging/homebrew-resources.py
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile
import urllib.request

PLATFORMS = ("macos", "linux")

# Formula-only constraints, laid over pyproject's floors. Homebrew's
# virtualenv_install_with_resources builds every resource from sdist with
# --no-binary :all:, and bleak 3.x declares uv_build as its PEP 517 backend —
# which pip then tries to build from source (pulling maturin and a Rust
# toolchain) and fails. bleak 2.x satisfies pyproject's >=0.22 floor and uses a
# backend Homebrew can build, so the FORMULA pins <3 while pyproject does not.
_FORMULA_CONSTRAINTS = "bleak<3\n"


def _closure(platform: str) -> dict[str, str]:
    """name -> pinned version for this checkout's [ble] extra, on one platform."""
    root = pathlib.Path(__file__).resolve().parent.parent
    with tempfile.NamedTemporaryFile("w", suffix=".txt") as constraints:
        constraints.write(_FORMULA_CONSTRAINTS)
        constraints.flush()
        result = subprocess.run(
            [
                "uv", "pip", "compile", "--quiet", "--no-header",
                "--python-platform", platform, "--python-version", "3.14",
                "--extra", "ble", "--constraint", constraints.name,
                str(root / "pyproject.toml"),
            ],
            text=True,
            capture_output=True,
            check=True,
        )
    found = {}
    for raw in result.stdout.splitlines():
        line = raw.split("#")[0].strip()
        if "==" in line:
            name, _, pinned = line.partition("==")
            found[name.strip()] = pinned.strip()
    # The package itself is the formula's `url`, not one of its resources.
    found.pop("whiskerless", None)
    return found


def _sdist(name: str, version: str) -> tuple[str, str]:
    """The sdist URL and sha256 PyPI publishes for one pinned release."""
    with urllib.request.urlopen(
        f"https://pypi.org/pypi/{name}/{version}/json", timeout=30
    ) as response:
        data = json.load(response)
    for entry in data["urls"]:
        if entry["packagetype"] == "sdist":
            return entry["url"], entry["digests"]["sha256"]
    raise SystemExit(f"{name} {version} publishes no sdist; Homebrew needs one")


def _block(name: str, version: str, indent: str) -> str:
    url, sha = _sdist(name, version)
    return (
        f'{indent}resource "{name}" do\n'
        f'{indent}  url "{url}"\n'
        f'{indent}  sha256 "{sha}"\n'
        f"{indent}end\n"
    )


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()

    per_platform = {name: _closure(name) for name in PLATFORMS}
    shared = {
        name: version
        for name, version in per_platform["macos"].items()
        if per_platform["linux"].get(name) == version
    }

    out = [_block(name, version, "  ") for name, version in sorted(shared.items())]
    for platform in PLATFORMS:
        only = {
            name: version
            for name, version in per_platform[platform].items()
            if name not in shared
        }
        if not only:
            continue
        out.append(f"  on_{platform} do\n")
        out.extend(_block(name, version, "    ") for name, version in sorted(only.items()))
        out.append("  end\n")

    sys.stdout.write("\n".join(part.rstrip("\n") for part in out) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
