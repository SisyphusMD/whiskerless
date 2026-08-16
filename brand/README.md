# Brand

The mark, and why it is not Whisker's.

The four SVGs here are the sources. `render.sh` produces the eight PNGs that
ship **inside the integration**, at `custom_components/whiskerless/brand/`,
where Home Assistant serves them from `/api/brands/integration/whiskerless/…`.

**There is no pull request to [home-assistant/brands](https://github.com/home-assistant/brands),
and there must not be one.** That was the route until HA 2026.3; it is now
closed. The brands PR template states that pull requests adding new custom
components are no longer accepted, its type-of-change list no longer offers the
custom-integration option, and the repository's own README labels
`custom_integrations/` a legacy folder, pointing at the
[Brands Proxy API announcement](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api).
Local images take priority over the CDN and are cached with
stale-while-revalidate, so they survive an internet outage.

The file names and sizes are unchanged from the brands rules, because the proxy
API adopted them wholesale. Installs older than HA 2026.3 simply ignore the
folder and show no icon, which is what they show today.

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

**The box in front of the cat is the machine, and the overlap is why it works.**
A cat alone says "pets", not "litter box". The first attempt put a bar under the
head, which read as the cat's shoulders; adding a handle to that bar made it a
bow tie. Both failed for the same reason — anything sitting directly beneath a
head, at head width, is a body.

What fixes it is occlusion. The box is drawn OVER the head so the chin
disappears behind it, and nothing can pass in front of the body it belongs to.
That single overlap turns one animal into two objects, one behind the other, and
the handle then reads as a drawer pull because it is on an object that is
plainly a container. A thin gap of tile colour around the box keeps the overlap
reading as depth instead of a welded shape.

Four other ways of referencing the machine were drawn and dropped: a full-width
plinth (reads as a shelf), a drawer shown pulled open (reads as stacked trays),
a panelled unit with a seam (a torso with a belt), and, in an earlier round, a
porthole, a bare product silhouette, a curled cat and a rotation arc — all
either lost the cat or collapsed at 32 px, which is the size Home Assistant
lists integrations at and therefore the only test that counts.

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

**`banner.svg` is the fifth source and deliberately not part of the brand set.**
The logo puts the wordmark on transparency, which is why it needs a light and a
dark file — and a README is the one surface that cannot pick between them: it
renders on GitHub in either theme, on PyPI always light, and in HACS usually
dark, all from a single `<img>`. Neither logo survives that: the light
wordmark's `#0E7C7B` drops to about 2.4:1 on a dark page, and the dark
wordmark's `#4FC3C0` to about 2:1 on a white one. The banner paints the same
artwork onto the tile colour so it carries its own background and the page
theme stops mattering. It renders to `brand/banner.png`, **not** into the
integration — that directory is served as the brand set and its filenames are
the ones the brands rules define.

`<picture>` was the first attempt and is why this exists: GitHub honours it,
PyPI strips the `<source>` but keeps the `<img>`, and HACS drops the `<img>`
entirely and shows the alt text. One image that needs no theme negotiation is
the only thing all three agree on.

## Rendering

```bash
./render.sh          # writes ../custom_components/whiskerless/brand/
```

Needs `rsvg-convert` and ImageMagick (`brew install librsvg imagemagick`). The
sizes are the brands repo's rules, not ours: icons exactly 256×256 and 512×512,
a logo whose *shortest* side falls in 128–256 (256–512 for `@2x`), PNG, prefer
transparency, and trimmed so there is minimal empty space around the artwork.
The output is COMMITTED, because it ships with the integration — so the render
is byte-reproducible (ImageMagick's `tIME` chunk is excluded explicitly; without
that, an unchanged SVG produced a new hash on every run and a permanently dirty
tree).
