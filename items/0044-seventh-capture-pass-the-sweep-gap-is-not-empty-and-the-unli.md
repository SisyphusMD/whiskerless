# #44 Seventh capture pass: the sweep gap is not empty, and the unlisted registers split by board firmware

- Kind: pull, state: closed, by cody, created 2026-08-24T22:38:26-07:00
- Labels: none; milestone: none
- refs/pull/44/head -> main, merged: True

5d07h from Loki (08-19 21:11Z → 08-25 04:52Z): 1,065,899 lines → 47,655 records, 0 malformed → 17,359 readings over 7,322 payload seconds.

**`0x6D` emits from inside the sweep's only silent gap.** `registers.md` records that a paced sweep answered 123 of 128 addresses and that the sole gap is `0x6A`–`0x6E`. `0x6D` is in it — it answered no read, yet pushed six readings in nine minutes. The file already warns that a silent register proves nothing on its own; this is the direct evidence for that warning.

**The unlisted registers split by MAIN-BOARD firmware on identical hardware.** Same `espFirmware=1.1.75`, same `mbHardware`/`mbBom`/`mbSuite`, but `mbRevision` 89/build 1 emits `0x6D`+`0x71` while 93/build 2 emits `0x67`. A clean correlation on n=2, and cheap to test: when a board updates, its registers should switch sets. This corrects #19's open question rather than contradicting it.

**The lead did not advance.** No `0x5F`–`0x63` and no `0x35` in 5d07h, so ~9d05h clean. Consistent with the fault-coupled reading, not support for it — a `0x35` fault *without* the five is what would refute it.

**Three method corrections**, each caught in review after I got it wrong first:
- `kubectl logs --since-time` returned five MINUTES against a 5d23h pod: the container log had rotated. The standing rule needed a third condition.
- Three claims of undocumented registers were wrong because `registers.md` uses RANGES that a literal search for `0x3E` does not match. Only `0x0C` is genuinely missing.
- The canonical METHOD RULE omitted the serial from the dedupe key. For a pass spanning both robots that can collapse two devices into one reading and manufacture the exclusivity this correlation rests on. The analysis did include it; the rule now says so.
