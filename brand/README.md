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

So: a cat over a drawer, in a teal chosen to sit nowhere near Whisker's orange,
and deliberately **not** shaped like Home Assistant's house, which the brands
rules ask custom integrations to avoid.

**The bar under the cat is the machine.** A cat alone says "pets", not "litter
box", and the LR4's signature is a globe over a waste drawer. Three other ways
of referencing the robot were drawn: a porthole opening with a face inside (lost
the cat — reads as an owl), a ring around the head (ears collide with it, mush
at 32 px), and a full front elevation (too much for an icon). The head reads as
the globe, the bar as the drawer, and at 32 px both survive — which is the only
test that matters, because that is the size Home Assistant lists integrations
at.

**There are no whiskers anywhere, and that was the hard call.** Six ways of
showing their absence were drawn and rejected:

| tried | why it failed |
|---|---|
| severed stubs | grit on the lens at 32 px |
| stub, gap, nothing | same, and ambiguous at full size |
| whisker *roots*, nothing growing | mush at 32 px |
| ghosted whiskers, faded | reads as whiskers, in a lighter colour |
| whiskers as VOIDS cut into the cheeks (the FedEx-arrow trick) | backfires — cut into a white face they read as whiskers *drawn on* it |
| whiskers drawn and struck through (*sous rature*) | legible at full size, noise at 32 px |

Absence cannot be drawn without drawing the thing, and an icon that is unusable
at 32 pixels is unusable. So the symbol has none, and the WORD carries it: the
wordmark sets "whisker" in a tint and "less" at full strength, which says which
half of the name is the point. Striking "whisker" through was drawn too and
dropped — crossing out a company's name is a different statement from declining
to wear its logo, and this project is making the second one.

**One symbol, four files.** The logo is the icon plus the wordmark — the same
tile, the same cat, the same geometry, verified pixel-for-pixel by cropping the
lockup's first 256 px and comparing it to the icon. **The dark pair follows Apple's rule, after breaking it twice.** The first two
attempts made the dark variant *brighter* than the light one, which is backwards
and read as barely a variant at all. Apple's guidance for dark app icons is to
drop the background so a dark backdrop shows through, and to avoid bright
artwork in favour of a palette complementary to the light icon
([HIG summary](https://median.co/blog/what-are-apples-ui-guidelines-for-app-icons)).
Home Assistant composites onto its own dark card rather than supplying a
backdrop, so the equivalent here is a dark tile with the artwork inverted into
light teal — not white, which glares against near-black exactly as Apple warns.
`dark_icon` exists so the tile still matches its own lockup on that theme.

## Rendering

```bash
./render.sh          # writes dist/
```

Needs `rsvg-convert` and ImageMagick (`brew install librsvg imagemagick`). The
sizes are the brands repo's rules, not ours: icons exactly 256×256 and 512×512,
a logo whose *shortest* side falls in 128–256 (256–512 for `@2x`), PNG, prefer
transparency, and trimmed so there is minimal empty space around the artwork.
`dist/` is generated and not committed — the PR carries the files.
