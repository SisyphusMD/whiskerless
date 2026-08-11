# Homebrew formula for the PRERELEASE (release-candidate) channel of the personal tap.
#
# A SEPARATE formula from the stable `whiskerless`, so `brew install sisyphusmd/tap/whiskerless-rc`
# tracks the newest `-rc.N` while the stable formula stays on the last real release. It exists so a
# candidate can be validated on a real robot through the same Homebrew path users take, without ever
# pointing the stable formula at a candidate build. Same source-venv install as the stable formula
# (see whiskerless.rb for the design notes).
#
# The prerelease workflow fills in url/sha per rc.
#
# Install:  brew install sisyphusmd/tap/whiskerless-rc
class WhiskerlessRc < Formula
  include Language::Python::Virtualenv

  desc "Fully-local MQTT control and telemetry for the Litter-Robot 4 (release candidate)"
  homepage "https://forgejo.bryantserver.com/SisyphusMD/whiskerless"
  url "https://forgejo.bryantserver.com/SisyphusMD/whiskerless/archive/v0.0.0-rc.0.tar.gz"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "MIT"

  # matches the interpreter the .pkg/.deb bundles freeze; bump by hand with each CPython minor —
  # no Renovate manager covers this formula.
  depends_on "python@3.14"

  # Same `whiskerless` binary as the stable formula, so the two cannot coexist.
  conflicts_with "whiskerless", because: "both install the same whiskerless binary"

  # RESOURCES ARE NOT WRITTEN YET. `virtualenv_install_with_resources` installs each resource with
  # pip's --no-deps, so the list has to be the COMPLETE closure — aiomqtt pulls paho-mqtt, and bleak
  # pulls pyobjc-* on macOS and dbus-fast on Linux. A partial list installs cleanly and then fails on
  # the first import, which is the worst possible outcome. Generate them, do not hand-write them:
  #
  #     brew update-python-resources Formula/whiskerless.rb
  #
  # See packaging/README.md; this formula is not publishable until that has run.

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
