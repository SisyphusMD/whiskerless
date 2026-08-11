# Homebrew cask for the signed, notarized macOS installer.
#
# A cask rather than a formula on purpose: the macOS release artifact is already
# a signed and notarized .pkg, which is the thing Gatekeeper is happy with. A
# formula would have to ship a bare binary, which macOS then quarantines — the
# exact friction the notarization exists to remove.
#
# This file is the source for the tap, NOT something Homebrew reads from here.
# Publishing it needs a tap repository (`SisyphusMD/homebrew-tap`), which does
# not exist yet; see packaging/README.md. Until it does, macOS users download the
# .pkg from the release page, which works and is what the README documents.
#
# Regenerate with:  packaging/homebrew-cask.sh <version>
cask "whiskerless" do
  arch arm: "arm64", intel: "x86_64"

  version "0.0.0"
  # Placeholders. homebrew-cask.sh rewrites these two lines and the version
  # from the published .pkg assets; they are literal strings so that rewrite
  # is a plain substitution and this file stays valid Ruby either way.
  sha256 arm:   "0000000000000000000000000000000000000000000000000000000000000000",
         intel: "0000000000000000000000000000000000000000000000000000000000000000"

  url "https://github.com/SisyphusMD/whiskerless/releases/download/v#{version}/whiskerless-macos-#{arch}.pkg"
  name "whiskerless"
  desc "Fully-local MQTT control and telemetry for the Whisker Litter-Robot 4"
  homepage "https://github.com/SisyphusMD/whiskerless"

  # The release tags prereleases as 0.2.0-rc.1; only stable versions are offered
  # to `brew upgrade`, which is what a cask should do.
  livecheck do
    url :url
    regex(/^v?(\d+(?:\.\d+)+)$/i)
    strategy :github_latest
  end

  pkg "whiskerless-macos-#{arch}.pkg"

  uninstall pkgutil: "com.sisyphusmd.whiskerless",
            delete:  "/usr/local/bin/whiskerless"

  zap trash: "~/Library/Preferences/com.sisyphusmd.whiskerless.plist"
end
