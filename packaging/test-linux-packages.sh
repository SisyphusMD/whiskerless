#!/usr/bin/env bash
# Install the exact CI-built packages in real distro userspaces, upgrade them, run the installed
# smoke against the frozen binary, then prove uninstall removes only package-owned files.
#
# The twin of dreame-valetudo's script of the same name. What differs is the layout: whiskerless
# ships one onefile binary, so there is no bundle tree to check and no pre-onedir transition case.
set -euo pipefail

fail() {
  echo "package smoke FAIL: $*" >&2
  exit 1
}

installed_smoke() {
  local manager=$1 expect=$2 old_package=$3 new_package=${4:-}
  local old_version new_version installed owned upgrade=true

  if [ -z "$new_package" ]; then
    new_package=$old_package
    upgrade=false
  fi

  # The store is user data. Uninstall must leave it exactly where it was.
  export HOME=/tmp/whiskerless-package-smoke
  mkdir -p "$HOME/whiskerless"
  printf 'keep\n' > "$HOME/whiskerless/uninstall-must-preserve"

  case "$manager" in
    apt)
      export DEBIAN_FRONTEND=noninteractive
      apt-get update -qq
      apt-get install -y -qq openssl >/dev/null
      old_version=$(dpkg-deb -f "$old_package" Version)
      new_version=$(dpkg-deb -f "$new_package" Version)
      if [ "$upgrade" = true ]; then
        dpkg --compare-versions "$new_version" gt "$old_version" \
          || fail "$new_version is not newer than $old_version"
      fi
      apt-get install -y -qq "$old_package"
      installed=$(dpkg-query -W -f='${Version}' whiskerless)
      [ "$installed" = "$old_version" ] || fail "apt installed $installed, expected $old_version"
      if [ "$upgrade" = true ]; then
        apt-get install -y -qq "$new_package"
        installed=$(dpkg-query -W -f='${Version}' whiskerless)
        [ "$installed" = "$new_version" ] \
          || fail "apt upgraded to $installed, expected $new_version"
      fi
      ;;
    dnf)
      old_version=$(rpm -qp --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}' "$old_package")
      new_version=$(rpm -qp --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}' "$new_package")
      [ "$upgrade" = false ] || [ "$old_version" != "$new_version" ] \
        || fail "old and new RPM metadata are identical"
      dnf install -y -q openssl >/dev/null
      dnf install -y --nogpgcheck "$old_package"
      installed=$(rpm -q --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}' whiskerless)
      [ "$installed" = "$old_version" ] || fail "dnf installed $installed, expected $old_version"
      if [ "$upgrade" = true ]; then
        dnf upgrade -y --nogpgcheck "$new_package"
        installed=$(rpm -q --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}' whiskerless)
        [ "$installed" = "$new_version" ] \
          || fail "dnf upgraded to $installed, expected $new_version"
      fi
      ;;
    zypper)
      old_version=$(rpm -qp --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}' "$old_package")
      new_version=$(rpm -qp --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}' "$new_package")
      [ "$upgrade" = false ] || [ "$old_version" != "$new_version" ] \
        || fail "old and new RPM metadata are identical"
      zypper --non-interactive install openssl >/dev/null
      zypper --non-interactive --no-gpg-checks install "$old_package"
      installed=$(rpm -q --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}' whiskerless)
      [ "$installed" = "$old_version" ] \
        || fail "zypper installed $installed, expected $old_version"
      if [ "$upgrade" = true ]; then
        zypper --non-interactive --no-gpg-checks install "$new_package"
        installed=$(rpm -q --qf '%{EPOCHNUM}:%{VERSION}-%{RELEASE}' whiskerless)
        [ "$installed" = "$new_version" ] \
          || fail "zypper upgraded to $installed, expected $new_version"
      fi
      ;;
    *)
      fail "unknown package manager $manager"
      ;;
  esac

  test -x /usr/bin/whiskerless
  # Asked of the package database, not the disk: the Debian and Ubuntu container images tell dpkg
  # to skip /usr/share/man and /usr/share/doc, so a test -f there fails for a reason that has
  # nothing to do with the package.
  case "$manager" in
    apt) owned=$(dpkg-query -L whiskerless) ;;
    *) owned=$(rpm -ql whiskerless) ;;
  esac
  for path in /usr/bin/whiskerless \
              /usr/share/man/man1/whiskerless.1.gz \
              /usr/share/doc/whiskerless/LICENSE; do
    grep -Fxq "$path" <<<"$owned" || fail "the package does not own $path"
  done
  # The same definition of "works" every other install channel uses, with openssl installed above
  # so its certificate half runs rather than skipping. `expect` is the version the
  # binary was frozen at, which is not the package version: CI packages one binary twice under
  # throwaway versions so that the upgrade above is a real one.
  bash /tmp/installed-smoke.sh /usr/bin/whiskerless "$expect"

  case "$manager" in
    apt) apt-get remove -y -qq whiskerless ;;
    dnf) dnf remove -y whiskerless ;;
    zypper) zypper --non-interactive remove whiskerless ;;
  esac

  # -e is FALSE for a dangling symlink; -L is what catches a leftover link.
  for path in /usr/bin/whiskerless \
              /usr/share/man/man1/whiskerless.1.gz \
              /usr/share/doc/whiskerless/LICENSE \
              /usr/share/doc/whiskerless/README.md; do
    { [ ! -e "$path" ] && [ ! -L "$path" ]; } || fail "uninstall left $path behind"
  done
  test -f "$HOME/whiskerless/uninstall-must-preserve" \
    || fail "uninstall removed the user's store"
  if [ "$upgrade" = true ]; then
    echo "package smoke PASS: $manager ($old_version -> $new_version -> removed)"
  else
    echo "package smoke PASS: $manager ($old_version -> removed)"
  fi
}

if [ "${1:-}" = "--inside" ]; then
  [ "$#" -eq 5 ] || fail "inside usage: --inside <apt|dnf|zypper> <version> <old> <new>"
  installed_smoke "$2" "$3" "$4" "$5"
  exit 0
fi

if [ "${1:-}" = "--inside-single" ]; then
  [ "$#" -eq 4 ] || fail "inside usage: --inside-single <apt|dnf|zypper> <version> <package>"
  installed_smoke "$2" "$3" "$4"
  exit 0
fi

[ "$#" -eq 5 ] \
  || fail "usage: $0 <binary-version> <old.deb> <new.deb> <old.rpm> <new.rpm>"
: "${DEBIAN_FLOOR_IMAGE:?set DEBIAN_FLOOR_IMAGE to a pinned image}"
: "${DEBIAN_CURRENT_IMAGE:?set DEBIAN_CURRENT_IMAGE to a pinned image}"
: "${UBUNTU_FLOOR_IMAGE:?set UBUNTU_FLOOR_IMAGE to a pinned image}"
: "${UBUNTU_CURRENT_IMAGE:?set UBUNTU_CURRENT_IMAGE to a pinned image}"
: "${FEDORA_FLOOR_IMAGE:?set FEDORA_FLOOR_IMAGE to a pinned image}"
: "${FEDORA_CURRENT_IMAGE:?set FEDORA_CURRENT_IMAGE to a pinned image}"
: "${RHEL_FLOOR_IMAGE:?set RHEL_FLOOR_IMAGE to a pinned image}"
: "${RHEL_CURRENT_IMAGE:?set RHEL_CURRENT_IMAGE to a pinned image}"
: "${OPENSUSE_IMAGE:?set OPENSUSE_IMAGE to a pinned image}"

expect=$1
old_deb=$(cd "$(dirname "$2")" && pwd)/$(basename "$2")
new_deb=$(cd "$(dirname "$3")" && pwd)/$(basename "$3")
old_rpm=$(cd "$(dirname "$4")" && pwd)/$(basename "$4")
new_rpm=$(cd "$(dirname "$5")" && pwd)/$(basename "$5")
for package in "$old_deb" "$new_deb" "$old_rpm" "$new_rpm"; do
  [ -s "$package" ] || fail "missing or empty package: $package"
done
here=$(cd "$(dirname "$0")" && pwd)

containers=()
images=()
cleanup() {
  if ((${#containers[@]})); then
    docker rm -f "${containers[@]}" >/dev/null 2>&1 || true
  fi
  if ((${#images[@]})); then
    docker image rm "${images[@]}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

run_case() {
  local label=$1 image=$2 manager=$3 old_package=$4 new_package=$5 cid extension
  echo "== package smoke: $label =="
  extension=rpm
  [ "$manager" = apt ] && extension=deb
  cid=$(docker create --platform linux/amd64 "$image" \
    /bin/bash /tmp/test-linux-packages.sh --inside "$manager" "$expect" \
    "/tmp/old-package.$extension" "/tmp/new-package.$extension")
  containers+=("$cid")
  images+=("$image")
  docker cp "$0" "$cid":/tmp/test-linux-packages.sh
  docker cp "$here/installed-smoke.sh" "$cid":/tmp/installed-smoke.sh
  docker cp "$old_package" "$cid":"/tmp/old-package.$extension"
  docker cp "$new_package" "$cid":"/tmp/new-package.$extension"
  docker start -a "$cid"
  docker rm "$cid" >/dev/null
  docker image rm "$image" >/dev/null 2>&1 || true
}

run_case "Debian 12 (oldstable floor)" "$DEBIAN_FLOOR_IMAGE" apt "$old_deb" "$new_deb"
run_case "Debian 13 (current stable)" "$DEBIAN_CURRENT_IMAGE" apt "$old_deb" "$new_deb"
run_case "Ubuntu 22.04 (glibc floor)" "$UBUNTU_FLOOR_IMAGE" apt "$old_deb" "$new_deb"
run_case "Ubuntu 26.04 (current LTS)" "$UBUNTU_CURRENT_IMAGE" apt "$old_deb" "$new_deb"
run_case "Fedora 43 (supported floor)" "$FEDORA_FLOOR_IMAGE" dnf "$old_rpm" "$new_rpm"
run_case "Fedora 44 (current)" "$FEDORA_CURRENT_IMAGE" dnf "$old_rpm" "$new_rpm"
run_case "Rocky Linux 8 (RHEL-compatible glibc floor)" "$RHEL_FLOOR_IMAGE" dnf "$old_rpm" "$new_rpm"
run_case "Rocky Linux 10 (RHEL-compatible current)" "$RHEL_CURRENT_IMAGE" dnf "$old_rpm" "$new_rpm"
run_case "openSUSE Leap 16.0" "$OPENSUSE_IMAGE" zypper "$old_rpm" "$new_rpm"
