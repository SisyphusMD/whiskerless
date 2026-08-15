#!/usr/bin/env bash
# Render the brand PNGs that home-assistant/brands wants, from the SVG sources.
#
# The files land in custom_components/whiskerless/brand/, which Home Assistant
# serves at /api/brands/integration/whiskerless/<image>. Sizes are the brands
# project's, not ours: icons are
# exactly 256 and 512 square, and a logo's SHORTEST side must land in 128-256
# (and 256-512 for @2x), which is why the logo is rendered wide and then
# trimmed — the rules also require minimal empty space around the artwork.
#
# Needs rsvg-convert and ImageMagick (brew install librsvg imagemagick).
set -euo pipefail
cd "$(dirname "$0")"
# Shipped, not built: since Home Assistant 2026.3 a custom integration serves
# its own brand images from inside itself, so these files live in the
# integration and are committed. See README.md for why there is no longer a
# pull request to home-assistant/brands.
out="${1:-../custom_components/whiskerless/brand}"
mkdir -p "$out"

rsvg-convert -w 256 -h 256 icon.svg -o "$out/icon.png"
rsvg-convert -w 512 -h 512 icon.svg -o "$out/icon@2x.png"
rsvg-convert -w 256 -h 256 dark_icon.svg -o "$out/dark_icon.png"
rsvg-convert -w 512 -h 512 dark_icon.svg -o "$out/dark_icon@2x.png"
# Height only: -w would scale the axes independently and squash the tile out of
# square, quietly making a lockup's symbol a different drawing from the icon's.
for variant in logo dark_logo; do
    rsvg-convert -h 256 "$variant.svg" | magick png:- -trim +repage "$out/$variant.png"
    rsvg-convert -h 512 "$variant.svg" | magick png:- -trim +repage "$out/$variant@2x.png"
done

for f in "$out"/*.png; do
    # Interlaced (progressive) and stripped of metadata, both of which the
    # brands checks prefer. Lossless: no quantisation, no colour reduction.
    # exclude-chunk=time: ImageMagick stamps a tIME chunk that -strip leaves
    # behind, so an unchanged SVG would still produce a new hash and a dirty
    # tree every time anyone ran this. These files are committed; they have to
    # be reproducible.
    magick "$f" -strip -interlace PNG -define png:compression-level=9 \
        -define png:exclude-chunk=time,date "$f"
done
magick identify -format '%f  %wx%h  %b\n' "$out"/*.png
