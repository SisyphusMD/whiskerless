"""Where copies of this tool are installed, and how to remove each one.

Two problems share this answer. A user can end up with more than one install — Homebrew and the
macOS `.pkg` both provide `whiskerless`, and nothing has ever noticed — and which one runs comes
down to PATH order, so `whiskerless --version` can disagree with what the user believes they have.
And when it is time to remove the tool, the right command depends on which of these it is: five
channels, five different removals, and nobody remembers a year later which one they used.

Detected from marker paths rather than from the running executable, because the question is "what
is on this machine" and not "how did this process start". `root` is injectable so the whole table
can be exercised against a fake filesystem, with no install of anything.

Ported from the sibling dreame-valetudo project, which had this first. The channel list differs;
the shape does not.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

__all__ = ["Install", "find_installs"]

#: The receipt `pkgbuild --identifier` writes. Forgetting it is what stops macOS believing a
#: removed package is still installed, which otherwise blocks a later reinstall from repairing it.
PKG_IDENTIFIER = "com.sisyphusmd.whiskerless"


@dataclass(frozen=True)
class Install:
    kind: str            # human label, shown to the user
    marker: Path         # the path that proves it is installed
    removal: list[str]   # argv to remove it; empty when only the user can (a source checkout)
    note: str = ""


def _brew_prefixes(env: Mapping[str, str]) -> list[Path]:
    """Every prefix a Homebrew install could be under, the configured one first.

    The configured prefix is ADDED to the defaults, never substituted for them. An Apple Silicon
    machine that kept its Intel Homebrew has installs under both, and it exports
    HOMEBREW_PREFIX=/opt/homebrew as a matter of course — so honouring only that skipped
    /usr/local entirely, and `uninstall` missed the second copy it exists to find.
    """
    # Apple Silicon and Intel defaults. /usr/local is ALSO where the .pkg lands, which is why brew
    # is identified by its Cellar and never by a bare bin/ entry.
    # Apple Silicon, Intel, and Linuxbrew. The Linux prefix matters because this project ships a
    # Linux Homebrew formula and bottles for it: without it, `uninstall` could not find the very
    # install the tap had just put there whenever HOMEBREW_PREFIX was not exported.
    prefixes = [Path("/opt/homebrew"), Path("/usr/local"), Path("/home/linuxbrew/.linuxbrew")]
    given = env.get("HOMEBREW_PREFIX")
    if given:
        prefixes.insert(0, Path(given))
    return list(dict.fromkeys(prefixes))


def _installed_as_editable() -> bool:
    """Whether this import is backed by an installed distribution rather than a bare checkout.

    An editable install leaves the code in the checkout, so no path tells the two apart. The
    metadata does: pip writes a `whiskerless` distribution either way, and a plain `git clone` on
    `sys.path` has none.
    """

    try:
        distribution("whiskerless")
    except PackageNotFoundError:
        return False
    return True


def find_installs(env: Mapping[str, str], root: Path = Path("/")) -> list[Install]:
    """Every install of this tool found on the system.

    `root` is injectable so the whole table can be exercised against a fake filesystem, from
    whichever machine happens to be running the tests.
    """
    home = Path(env.get("HOME", "~")).expanduser()
    found: list[Install] = []

    for prefix in _brew_prefixes(env):
        cellar = root / prefix.relative_to("/") / "Cellar" / "whiskerless"
        cellar_rc = root / prefix.relative_to("/") / "Cellar" / "whiskerless-rc"
        # THAT prefix's brew, not whichever one PATH happens to pick. With installs under both
        # prefixes, a bare `brew` sent both removals to the same Homebrew: the first succeeded and
        # the second failed against a formula it had never installed, leaving the other copy in
        # place — the exact situation this command exists to clear up.
        brew = str(prefix / "bin" / "brew")
        if cellar.is_dir():
            found.append(Install("Homebrew", cellar, [brew, "uninstall", "whiskerless"]))
        if cellar_rc.is_dir():
            found.append(Install("Homebrew (release candidate)", cellar_rc,
                                 [brew, "uninstall", "whiskerless-rc"]))

    # The .pkg drops a single binary at /usr/local/bin — which on Intel is ALSO where Homebrew
    # symlinks its own. A symlink there is brew's and was already reported above from its Cellar;
    # only a real file is the package's, so this cannot double-count one install as two.
    #
    # Confirmed by the RECEIPT, not by the path. /usr/local/bin/whiskerless is an ordinary place
    # for a system-wide pip console script or a hand-copied release binary to sit, on Linux and on
    # macOS alike — and calling either one a `.pkg` offers `sudo rm` on a file the package manager
    # does not own, then tells the user to forget a receipt that was never written. The receipt is
    # a real file macOS writes at install time, so asking for it costs no subprocess and stays
    # testable against a fake root.
    pkg_bin = root / "usr/local/bin/whiskerless"
    receipt = root / "var/db/receipts" / f"{PKG_IDENTIFIER}.plist"
    if receipt.is_file() and pkg_bin.is_file() and not pkg_bin.is_symlink():
        found.append(Install(
            "macOS .pkg", pkg_bin,
            ["sudo", "rm", "-f", str(pkg_bin)],
            f"then run: sudo pkgutil --forget {PKG_IDENTIFIER}"))

    # /usr/share/doc/<name>, not /usr/bin/<name>: the binary alone cannot tell a package install
    # from someone who copied a release binary onto their PATH by hand, and removing the latter
    # with apt would report a package that is not installed.
    deb_doc = root / "usr/share/doc/whiskerless"
    if deb_doc.is_dir():
        apt = (root / "usr/bin/apt-get").exists()
        if apt:
            removal = ["sudo", "apt-get", "remove", "-y", "whiskerless"]
        elif (root / "usr/bin/zypper").exists():
            removal = ["sudo", "zypper", "remove", "-y", "whiskerless"]
        elif (root / "usr/bin/dnf").exists():
            removal = ["sudo", "dnf", "remove", "-y", "whiskerless"]
        elif (root / "usr/bin/yum").exists():
            removal = ["sudo", "yum", "remove", "-y", "whiskerless"]
        else:
            removal = ["sudo", "rpm", "-e", "whiskerless"]
        found.append(Install(".deb package" if apt else ".rpm package", deb_doc, removal))

    uv_tool = home / ".local/share/uv/tools/whiskerless"
    if uv_tool.is_dir():
        found.append(Install("uv tool", uv_tool, ["uv", "tool", "uninstall", "whiskerless"]))

    # Every pipx home, in the order pipx itself resolves them. The modern POSIX default moved
    # under ~/.local/share, Windows puts it at ~/pipx, and PIPX_HOME relocates it anywhere on any
    # platform. Probing one path made a normal install invisible: `uninstall` reported no pipx
    # copy, then found the same venv through the pip rule below and offered to run pip INSIDE
    # pipx's managed environment — which leaves pipx's shim and metadata behind while reporting
    # success. The README documents the Windows install, so this is not hypothetical.
    pipx_homes = []
    configured = env.get("PIPX_HOME")
    if configured:
        pipx_homes.append(Path(configured))
    pipx_homes += [home / ".local/share/pipx", home / ".local/pipx", home / "pipx"]
    for pipx_home in dict.fromkeys(pipx_homes):
        pipx = pipx_home / "venvs" / "whiskerless"
        if pipx.is_dir():
            found.append(Install("pipx", pipx, ["pipx", "uninstall", "whiskerless"]))
            break

    # A plain `pip install` into the interpreter running this very process — the route the README
    # advertises alongside pipx. Detected from the package's own location rather than a marker
    # path, because that is the only thing that identifies an arbitrary virtualenv. Skipped when it
    # resolves inside one of the homes already reported above, so a pipx or uv install is not
    # counted twice.
    #
    # `dist-packages` as well as `site-packages`: Debian and Ubuntu rename the directory, so
    # matching only the one name missed an ordinary pip install on the distributions this project
    # ships packages for. And an EDITABLE install (`pip install -e .`, what CONTRIBUTING tells a
    # contributor to run) puts the package in the checkout instead, where the name matches neither
    # — so that one is found from its installed METADATA, which exists wherever pip recorded it.
    # Without this the command reported only a source checkout it will not remove, and deleting
    # the clone by hand leaves the console script and the metadata behind.
    site = Path(__file__).resolve().parent.parent
    already = [i.marker.resolve() for i in found]
    fresh = not any(site == home or home in site.parents for home in already)
    if site.name in {"site-packages", "dist-packages"} and fresh:
        found.append(Install(
            "pip (this interpreter)", site,
            [str(Path(sys.executable)), "-m", "pip", "uninstall", "-y", "whiskerless"]))
    elif fresh and _installed_as_editable():
        found.append(Install(
            "pip (editable, this interpreter)", site,
            [str(Path(sys.executable)), "-m", "pip", "uninstall", "-y", "whiskerless"],
            "the checkout itself stays; this removes the link and the metadata pip recorded"))

    # The Home Assistant integration. Reported, never removed: it is a different machine as often
    # as not, HACS owns its lifecycle, and deleting the directory behind HACS's back leaves a
    # config entry pointing at nothing. The paths are the two conventional layouts — a container
    # install at /config and a venv install under $HOME.
    for ha_root in (root / "config", home / ".homeassistant"):
        component = ha_root / "custom_components" / "whiskerless"
        if component.is_dir():
            found.append(Install(
                "Home Assistant integration", component, [],
                "remove it through HACS, then delete the integration from Settings → Devices "
                "& services — a CLI cannot do this safely"))

    checkout = Path(__file__).resolve().parent.parent.parent
    if (checkout / ".git").exists():
        found.append(Install("source checkout", checkout, [],
                             "delete the clone yourself when you're done with it"))

    return found
