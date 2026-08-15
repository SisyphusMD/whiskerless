# Concepts

Directions that were drawn and shown, kept because the reasoning is worth more
than the files. The one in use lives a directory up; these are the alternatives
it was chosen against, each with what it does well and where it breaks.

Render any of them:

```bash
rsvg-convert -w 256 -h 256 concepts/void.svg -o /tmp/void.png     # full size
rsvg-convert -w 32 -h 32 concepts/void.svg -o /tmp/void32.png     # the size that decides
```

**The 32-pixel row is the test.** Home Assistant lists integrations at roughly
that size, and every idea here that fails does so there rather than on the
artboard.

## porthole.svg

The globe opening as the hero — a heavy ring with the cat inside it. The ring
genuinely reads as an appliance aperture. It breaks because the ears sit outside
the ring, disconnected, and read as horns; merging them into the ring fixes that
and costs the clean circle that made it work.

## product.svg

The machine alone, no face: sphere with a dark opening, tapered base, drawer
handle. The most device-like of the set and it survives small sizes. Two
problems — it reads as a webcam or a robot vacuum on its dock, and it discards
the cat, which is the warmth and the whole joke in the name.

## curled.svg

A cat curled into the globe's circle. **This one failed.** The tail arc reads as
a bite out of a circle: it is Pac-Man, not a cat. Kept because the idea is sound
and a redraw might land it; what is in the file is not defensible.

## cycle.svg

A rotation arrow wrapping the face, referencing what the machine *does* — the
globe turns to sift. Works at full size. At 32 px the arrowhead collapses into a
blob and the face shrinks past legibility; it would need a thicker arc and a
bigger face, which then crowds the tile.

## void.svg

The box is solid and the cat is the hole cut out of it, drawer handle below.
This is the negative-space idea working properly — it reads as a mark first and
the cat arrives a beat later, which is the whole principle. Holds at 32 px, and
nothing else in the brands registry looks like it.
