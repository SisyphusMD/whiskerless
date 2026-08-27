# Homebrew formula for a personal tap (SisyphusMD/homebrew-tap).
#
# A source install of the Python package into an isolated virtualenv on the user's machine — so
# there is NO Apple notarization requirement (that applies only to the separate signed .pkg). It is
# arch-agnostic: the package is pure Python, so a single `brew install` covers macOS (Apple Silicon
# or Intel) AND Linux (amd64/arm64). Self-contained from the user's side: Homebrew provides
# python@3.14 + the venv; no user-managed Python. (The .pkg/.deb ship a PyInstaller-frozen bundle
# instead, for machines without one.)
#
# The BLE extra is included: `whiskerless provision` is the one command a new user runs, and it is
# the only one that needs bleak. A formula that installed the CLI but not the provisioner would be
# the wrong half.
#
# The release workflow fills in url/sha per version.
#
# Install:  brew install sisyphusmd/tap/whiskerless
class Whiskerless < Formula
  include Language::Python::Virtualenv

  desc "Fully-local MQTT control and telemetry for the Whisker Litter-Robot 4"
  homepage "https://forgejo.bryantserver.com/SisyphusMD/whiskerless"
  url "https://files.pythonhosted.org/packages/source/w/whiskerless/whiskerless-REPLACE_VERSION.tar.gz"
  sha256 "REPLACE_SDIST_SHA256"
  license "MIT"
REPLACE_BOTTLE_BLOCK
  # matches the interpreter the .pkg/.deb bundles freeze; bump by hand with each CPython minor —
  # no Renovate manager covers this formula.
  depends_on "python@3.14"
  depends_on "openssl@3"
  # Certificates are core function (the robot cannot send a username or password, so nothing else
  # authenticates it), but this does NOT have to be a resource. As a resource it is built from its
  # sdist like every other one, and its sdist is a Rust extension: ~21 minutes per platform per
  # release, plus rust and llvm poured purely as build tooling, plus a workaround for the stripped
  # Mach-O that dyld then refuses. Homebrew bottles cryptography for every platform this formula
  # targets, so that compile is one somebody else has already done and users pour it in seconds.
  # `:no_linkage` because nothing here links against it — the venv imports it, via the
  # homebrew_deps.pth that virtualenv_create writes for every non-build dependency. It must
  # therefore NOT become a `=> :build` dep, which that walk prunes.
  depends_on "cryptography" => :no_linkage

  # BEGIN RESOURCES — generated, never hand-edited. `virtualenv_install_with_resources` installs each
  # resource with pip's --no-deps, so this must be the COMPLETE closure; bleak's dependencies differ
  # by platform, hence the on_macos/on_linux split. Regenerate after any dependency change:
  #     packaging/homebrew-resources.py <version>
  resource "aiomqtt" do
    url "https://files.pythonhosted.org/packages/70/44/cfc58272783a11729462dc6df5adbfeabd084f840f609054ac772ae98c19/aiomqtt-2.5.1.tar.gz"
    sha256 "25a0a47d157e8f158d2da1110ea4786c0615518751e94f7b04976c977a8ff20d"
  end
  resource "bleak" do
    url "https://files.pythonhosted.org/packages/45/8a/5acbd4da6a5a301fab56ff6d6e9e6b6945e6e4a2d1d213898c21b1d3a19b/bleak-2.1.1.tar.gz"
    sha256 "4600cc5852f2392ce886547e127623f188e689489c5946d422172adf80635cf9"
  end
  resource "paho-mqtt" do
    url "https://files.pythonhosted.org/packages/39/15/0a6214e76d4d32e7f663b109cf71fb22561c2be0f701d67f93950cd40542/paho_mqtt-2.1.0.tar.gz"
    sha256 "12d6e7511d4137555a3f6ea167ae846af2c7357b10bc6fa4f7c3968fc1723834"
  end
  on_macos do
    resource "pyobjc-core" do
      url "https://files.pythonhosted.org/packages/a5/78/abc4ce5920305780aeb36b4067a86253378b36e29ba96673a3deb02eb03a/pyobjc_core-12.2.2.tar.gz"
      sha256 "3906452339cd06a3bb07df103c2511d4cb0f7a22d8771c0b802eba15d9a642b6"
    end
    resource "pyobjc-framework-cocoa" do
      url "https://files.pythonhosted.org/packages/75/76/49c6da2c6a831020b4854ba20079d5a1030474bffc776b7b73c2eeff8c15/pyobjc_framework_cocoa-12.2.2.tar.gz"
      sha256 "c96c0ef69a71afbbb0e6a7d594b455c5fe47d62e0db376ee7a2b4b828c16ace9"
    end
    resource "pyobjc-framework-corebluetooth" do
      url "https://files.pythonhosted.org/packages/53/f6/424a21392b3290dab0e8a78bddbe4e71754b9f1cf70d0e1584c03d6df987/pyobjc_framework_corebluetooth-12.2.2.tar.gz"
      sha256 "75aa13f5355be549252d3192864bb3b82eb74c1f667d0527c1388117efffd688"
    end
    resource "pyobjc-framework-libdispatch" do
      url "https://files.pythonhosted.org/packages/f0/76/e40db30142b551790e5ab208e74de04cfc70823177a702c8c9e3f5e73034/pyobjc_framework_libdispatch-12.2.2.tar.gz"
      sha256 "7cb799a7c5766cc1b68b68655a02c950646adfd2a743b7cbe8e4a04a51c44ecb"
    end
  end
  on_linux do
    resource "dbus-fast" do
      url "https://files.pythonhosted.org/packages/aa/db/b621610e50b1bc46ff63534d75239553c1bf33256de6096b58214fd9808a/dbus_fast-5.0.22.tar.gz"
      sha256 "34dc67d7d21a12399828dd13e63b352750580beea54ea7c729e708f2d2905fef"
    end
  end
  # END RESOURCES


  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      whiskerless talks to a Litter-Robot 4 on YOUR broker, never Whisker's cloud. Two things have
      to happen before the Home Assistant integration sees anything:

        1. Stand up an MQTT broker the robot can reach over TLS.
        2. Re-provision the robot onto it, once, over Bluetooth:
             whiskerless provision

      Provisioning is reversible through the Whisker app, but it is the step that moves the robot
      off the cloud — read the setup guide first:
        https://github.com/SisyphusMD/whiskerless/tree/main/docs/setup
    EOS
  end

  test do
    assert_match "whiskerless", shell_output("#{bin}/whiskerless --help")
    # Deliberately not `whiskerless send <never-send opcode>`: the CLI opens the broker connection
    # before the guard runs, so on a test host with nothing listening that exits 1 for the refused
    # connection and never reaches the safety check it looks like it is asserting. Import the guard
    # directly instead — it is the one thing that must survive packaging.
    python = "#{libexec}/bin/python"
    script = 'from whiskerless.safety import classify_code; print(classify_code("0x02A30000"))'
    output = shell_output("#{python} -c #{script.shellescape}")
    assert_match(/never/i, output)
  end
end
