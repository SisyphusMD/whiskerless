# #197 Litter level %: the cloud's percent is relative to a per-robot optimalLitterLevel — the local mm→% curve can't match without that anchor

- Kind: issue, state: closed, by cody, created 2026-11-17T08:59:27-08:00
- Labels: none; milestone: none

_Recreated from GitHub issue [#7](https://github.com/SisyphusMD/whiskerless/issues/7), opened by @CryingPecan on 2026-08-08, when the GitHub copy became read-only._

---

Cross-robot evidence (one robot on whiskerless, one still on cloud for ground truth):

- Cloud robot: `optimalLitterLevel` = **450**, litterLevel 451-452 mm → litterLevelPercentage 0.9, state OPTIMAL
- Whiskerless robot: idles at **459-460 mm** at its own maintain target (LitterHopper, ~90% setting); whiskerless's absolute mm→% curve reads this as ~70%, while the cloud called the equivalent state 90%

So the cloud % is computed **relative to a per-robot optimal**, not from an absolute curve — no universal mm→% formula can be correct. Also confirmed directionality during a deliberate hopper run-dry: litterLevel mm RISES as litter drops (it's a distance measurement).

**The missing piece is where optimalLitterLevel lives locally.** It's not in the state document. Plan on our second robot's conversion day: a full safe-read register sweep on a robot whose optimal we know is exactly 450, hunting the register that holds it. Possibly related: activity reg 0x5E (fires at cycle start/end, value ÷4 ≈ litter mm at level attitude — see PR #2's phase notes).

## cody, 2026-11-17T08:59:27-08:00

_@SisyphusMD on GitHub, 2026-08-12:_

Confirmed from this side: `optimalLitterLevel` is not in the local state document. 69 distinct state fields across 50 hours on two robots, and `litterLevel` is the only litter-related one.

The approach here went sideways rather than hunting the anchor. Percentage is calibrated per robot now: one button press with the globe filled to the line pins it, otherwise it learns the extremes over time. That sidesteps the missing optimal instead of solving it.

A register sweep on the 450 robot is still the thing that would actually answer it.

## cody, 2026-11-17T08:59:27-08:00

_@SisyphusMD on GitHub, 2026-08-16:_

The calibrated scale has now been checked against a human eye at the machine, on both
robots, from photographs taken at the same minute as the readings:

| Signal | Robot said | Eye said | Verdict |
|---|---|---|---|
| waste drawer | `DFILevelPercent` 78 | ~78 % | accurate |
| globe litter | `litterLevel` ~445 | ~67 % | accurate |
| hopper | ~half | mostly full | **under-reports** |

So the missing anchor is not costing the globe percentage anything measurable. The one
signal that is out is the hopper gauge, and that is a learned-scale problem rather than
a decode problem — it has fewer extremes to learn from and had not yet seen a full one.

Two smaller corrections from the same session, both of which touch the calibrate-to-the-
line workflow: the globe **does** have a moulded fill line (this repo had stopped
claiming it for want of evidence, and it is there), and the filter has no date tab,
printed mark or indicator of any kind, with no register reporting its state either.

A register sweep on the 450 robot is still the thing that would answer the original
question rather than sidestep it.
