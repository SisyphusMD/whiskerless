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

  # matches the interpreter the .pkg/.deb bundles freeze; bump by hand with each CPython minor —
  # no Renovate manager covers this formula.
  depends_on "python@3.14"

  # BEGIN RESOURCES — generated, never hand-edited. `virtualenv_install_with_resources` installs each
  # resource with pip's --no-deps, so this must be the COMPLETE closure; bleak's dependencies differ
  # by platform, hence the on_macos/on_linux split. Regenerate after any dependency change:
  #     packaging/homebrew-resources.py <version>
  resource "aiomqtt" do
    url "https://files.pythonhosted.org/packages/70/44/cfc58272783a11729462dc6df5adbfeabd084f840f609054ac772ae98c19/aiomqtt-2.5.1.tar.gz"
    sha256 "25a0a47d157e8f158d2da1110ea4786c0615518751e94f7b04976c977a8ff20d"
  end
  resource "bleak" do
    url "https://files.pythonhosted.org/packages/16/df/05a3f80ca8e3f7f5b0dba68a9e618147c909ccdba1468f07487dc8d72a9d/bleak-3.0.2.tar.gz"
    sha256 "c2229cb8238d5876b4bd05c74bf7a1aea1f88da39d2e51ac9dfd5cc319d5265f"
  end
  resource "paho-mqtt" do
    url "https://files.pythonhosted.org/packages/39/15/0a6214e76d4d32e7f663b109cf71fb22561c2be0f701d67f93950cd40542/paho_mqtt-2.1.0.tar.gz"
    sha256 "12d6e7511d4137555a3f6ea167ae846af2c7357b10bc6fa4f7c3968fc1723834"
  end
  on_macos do
    resource "pyobjc-core" do
      url "https://files.pythonhosted.org/packages/b4/b1/729f7458a63758bd21716648a8abcd9a0c8f2d2e9897763c8a1a1c7fd31b/pyobjc_core-12.2.1.tar.gz"
      sha256 "7a7b9b018402342cf32bf1956366896350fbe5c0478cb3ef59778f77abed7f07"
    end
    resource "pyobjc-framework-cocoa" do
      url "https://files.pythonhosted.org/packages/51/34/fbe38a204643aa4e1b91391cdce07a34da565a69171ebcad08de7438a556/pyobjc_framework_cocoa-12.2.1.tar.gz"
      sha256 "b94b37fe5730e5ae1fb0052912cd174e6ec329b0bfba4a012ae5db1014b5864b"
    end
    resource "pyobjc-framework-corebluetooth" do
      url "https://files.pythonhosted.org/packages/d4/91/c76f3c5e8e80c7047e43c4c05b3e6fda9a7cefad5aae85487007674c966c/pyobjc_framework_corebluetooth-12.2.1.tar.gz"
      sha256 "7dbb285295097205bebbcb11f55161e5faa02111108fb7b17536176e31971eb0"
    end
    resource "pyobjc-framework-libdispatch" do
      url "https://files.pythonhosted.org/packages/d9/3f/561653aff3f19873457c95c053f0298da517be89fdfc0ec35115ed5b7030/pyobjc_framework_libdispatch-12.2.1.tar.gz"
      sha256 "0d24eda41c6c258135077f60d410e704bc7b5a67adcb2ca463918896c7363795"
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
    output = shell_output("#{python} -c #{Utils.shell_quote(script)}")
    assert_match(/never/i, output)
  end
end
