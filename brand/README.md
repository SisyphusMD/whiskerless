# Brand

The mark, and why it is not Whisker's.

`icon.svg` and `logo.svg` are the sources; `render.sh` produces the four PNGs
that [home-assistant/brands](https://github.com/home-assistant/brands) wants
under `custom_integrations/whiskerless/`. Nothing here ships in the package or
the integration — Home Assistant fetches brand images from that repo by domain.

## Why an original mark

Three patterns exist in the brands registry for projects that talk to a vendor's
hardware without the vendor's cloud:

* **the vendor's own mark** — `dreame_vacuum` is Dreame's "D" in Dreame's colours
* **the vendor's mark, remixed** — `localtuya` and `tuya_local` both keep Tuya's "t"
* **something original** — `valetudo`, which looks like nothing Roborock ships

Whiskerless takes the third, for a specific reason rather than a stylistic one:
Home Assistant already has a `litterrobot` integration, and it already wears
Whisker's brand — the orange tile with the white cat-head "W". Wearing the same
mark would make the two indistinguishable in the one list where a user is
choosing between them, and the choice between "through Whisker's servers" and
"not through Whisker's servers" is the entire point. A project that re-points
hardware away from a company's cloud is also the last thing that should be
dressed in that company's trademark, which implies an endorsement nobody gave.

So: a cat, because the device is a litter box and a user should be able to tell
at 32 pixels; in a teal chosen to sit nowhere near Whisker's orange; and
deliberately **not** shaped like Home Assistant's house, which the brands rules
ask custom integrations to avoid.

**There are no whiskers anywhere, and that was the hard call.** Three ways of
showing their absence were drawn and rejected: severed stubs, a stub-and-gap,
and whisker *roots* with nothing growing from them. At 32 pixels all three turn
to grit on the lens, and at logo size a faded ghost of a whisker does not read
as "absent" — it reads as a whisker, in a lighter colour. Absence cannot be
drawn without drawing the thing. So the symbol has none, and the word does the
work.

**One symbol, two lockups.** The logo is the icon plus the wordmark — the same
tile, the same cat, the same geometry, nothing invented for the lockup. An icon
and a logo that share a name but not a drawing are two brands wearing one label.
`dark_logo` differs from `logo` in exactly one value, the colour of the word:
teal type on Home Assistant's dark theme sits at about the contrast of dark grey
on black.

## Rendering

```bash
./render.sh          # writes dist/
```

Needs `rsvg-convert` and ImageMagick (`brew install librsvg imagemagick`). The
sizes are the brands repo's rules, not ours: icons exactly 256×256 and 512×512,
a logo whose *shortest* side falls in 128–256 (256–512 for `@2x`), PNG, prefer
transparency, and trimmed so there is minimal empty space around the artwork.
`dist/` is generated and not committed — the PR carries the files.
