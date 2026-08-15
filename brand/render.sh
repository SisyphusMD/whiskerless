#!/usr/bin/env bash
# Render the brand PNGs that home-assistant/brands wants, from the SVG sources.
#
# The four files go to custom_integrations/whiskerless/ in a PR against that
# repo; nothing here is used at runtime. Sizes are theirs, not ours: icons are
# exactly 256 and 512 square, and a logo's SHORTEST side must land in 128-256
# (and 256-512 for @2x), which is why the logo is rendered wide and then
# trimmed — the rules also require minimal empty space around the artwork.
#
# Needs rsvg-convert and ImageMagick (brew install librsvg imagemagick).
set -euo pipefail
cd "$(dirname "$0")"
out="${1:-dist}"
mkdir -p "$out"

rsvg-convert -w 256 -h 256 icon.svg -o "$out/icon.png"
rsvg-convert -w 512 -h 512 icon.svg -o "$out/icon@2x.png"
# Height only: -w would scale the axes independently and squash the tile out
# of square, quietly making the logo's symbol a different drawing from the icon's.
rsvg-convert -h 256 logo.svg | magick png:- -trim +repage "$out/logo.png"
rsvg-convert -h 512 logo.svg | magick png:- -trim +repage "$out/logo@2x.png"
# Dark theme gets a lighter wordmark; the tile and cat are unchanged, so it is
# the same lockup rather than a second design.
rsvg-convert -h 256 dark_logo.svg | magick png:- -trim +repage "$out/dark_logo.png"
rsvg-convert -h 512 dark_logo.svg | magick png:- -trim +repage "$out/dark_logo@2x.png"

for f in "$out"/*.png; do
    # Interlaced (progressive) and stripped of metadata, both of which the
    # brands checks prefer. Lossless: no quantisation, no colour reduction.
    magick "$f" -strip -interlace PNG -define png:compression-level=9 "$f"
done
magick identify -format '%f  %wx%h  %b\n' "$out"/*.png
