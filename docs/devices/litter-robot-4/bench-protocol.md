# At the robot: what to do while you are standing there

Written to be followed at the machine, in order, with a phone or laptop in hand.
Every step exists because something in this repo is currently **guessed**, and
each one says what would make it known. Narrate the times — the capture is
matched by the payload's own timestamps, so "about ten past" is not enough.

Before you start: note the wall-clock time and the robot you are at. The rolling
capture is already running (`lr4-capture` in namespace `homeassistant`), and its
history is read out of Loki afterwards, so nothing needs arming.

---

## 1. Panel sleep, by hand — closes #45 and #22 (2 minutes)

The only thing standing between `0x32` and PROVEN. Ten emissions across five
nights have matched ten `sleepStatus` edges, each leading by 2-3 seconds, but
every one of them was the SCHEDULE firing on its own. Nobody has ever watched
the register while a person caused the change, and the whole point of the
schedule test is that it cannot separate "tracks sleep" from "tracks the clock".

1. Note the time. On the panel, put the robot into sleep mode by hand.
2. Wait ~30 s. Note the time again, and wake it by hand.
3. Tell me both times.

**What answers it:** a `0x320001` within a few seconds of your sleep press and a
`0x320000` within a few seconds of your wake press, neither of them near a
scheduled boundary. That is the register following a human rather than a clock.

**Same trip, #22:** while you are in the panel menus, set the sleep *time* by
hand to something you will recognise (say 03:33), then tell me. The integration
writes the per-day registers and verifies them by read-back; what has never been
checked is that a change made at the PANEL shows up the same way.

---

## 2. The Connect hold, timed — closes half of #39 (1 minute)

Every document here says "hold for a few seconds, until the light pulses
yellow". Nobody has timed it, and "a few seconds" is the instruction a user
follows before deciding the tool is broken.

1. Start counting, press and hold **Connect**.
2. Say when the light changes, and what it does — colour, pulse or steady.
3. Release. Does it stay in pairing mode, and for how long before it gives up?

**What answers it:** a number to put in the README and `docs/recovery.md`, plus
the exact appearance to expect. Then press Connect *briefly* once and confirm the
documented "a short press does nothing" is still true.

---

## 2b. While it is still in pairing mode — advances #52, does not close it (1 minute)

**Prepare the command BEFORE pressing Connect.** `provision` prompts for the
serial, broker, CA, username and WiFi answers *before* it scans, and the pairing
window is short — spend it typing and the robot stops advertising mid-answer.
Pass every answer as a flag so it goes straight to the scan, then press Connect
and run it:

```bash
whiskerless provision --dry-run --yes \
  --serial LR4Cxxxxxx --host-ip <broker-ip> --ca ~/certs/ca.crt \
  --wifi-ssid <ssid> --wifi-pass '<passphrase>' --username <broker-user>
```

Every one of those is prompted when omitted, `--username` included, so leaving
any of them off puts a prompt between you and the scan. Drop `--username` only if
you are willing to press enter once.

Read the `(MAC …)` line back to me. Nothing is written — the dry run does the BLE
connect, the endpoint discovery and the reads, then stops.

**What this can settle:** the docs contradict each other about what
`read_device_mac` returns (the provisioning README says serial, `recovery.md` and
the code say MAC). `read_device_mac` renders 6 bytes as a hex MAC and anything
else as UTF-8, so one reading says which of those our robots answer with, and
whether the value printed as "(MAC …)" is misnamed.

**What it cannot settle, and why #52 stays open.** `provision` writes
`DEVICE_ID_SET <serial>` as its *first* step, and both robots here have been
provisioned — so whatever comes back is what whiskerless previously stored, not
the factory value. That makes it useless for the auto-fill half of #52, which
needs the id an *untouched* LR4 reports. Verifying a typed `--serial` against the
read is still worth having, but only as a re-provisioning check.

**Not tonight (#51):** probing whether the config endpoints answer *reads* needs
a message-type sweep script that does not exist yet. Worth writing before the
next pairing window — a read would expose Whisker's own AWS endpoint hostname,
the one value still blocking a self-contained `restore-cloud`.

## 3. The globe's fill markings — the rest of #39 (1 minute)

`calibrate full` used to tell people to "fill the globe to the line". No one here
has confirmed such a line exists, so the wording now avoids it. Look inside the
globe: is there a moulded line, a MAX marking, anything? Tell me what you see
(a photo is ideal). If there is one, the instruction can name it; if there is
not, the current wording stands and stops implying a marking that is not there.

While the bonnet is off, the same for the **filter**: is there a mark, a date
tab, or anything a user could be told to look at?

---

## 4. The waste drawer — the last of #39 (1 minute)

Three rounds of narrated pulls have failed to separate removal from insertion
(`0x56` codes 10, 11, 13-17 and 28 all appear for both). That question is
parked. What is still worth knowing is what a USER should be told:

1. Pull the drawer fully out. Note the time.
2. Does the panel show anything? Does the robot refuse to cycle?
3. Push it back until it seats. Note the time, and whether seating it took a
   deliberate push or clicked on its own.

**What answers it:** the "what the robot does when it worked" line that
`docs/setup/home-assistant.md` currently cannot write for the drawer.

---

## 5. Optional, and only if you feel like it

**#13 — the empty cycle.** Costs a full litter refill, which is why it has never
been run. If you are changing the litter anyway, this is the moment: press
**Empty cycle (danger)** in Home Assistant (it ships disabled; enable it first)
and note the time. It confirms the captured `0x02010801` and — with the capture
running — finally shows which `robotStatus` integer an empty cycle reports, which
is #14 and the reason `empty_cycle` currently has no local int.

**#23 — the cat weights.** If the other two cats can be weighed on a bathroom
scale the same evening, the `catWeight` divisor question becomes answerable. The
known-weight method has already failed three times (divisors 72.4, 84.8, 88.5,
because an inert object sheds load against the globe wall), so it needs real
cats and a same-evening household weigh-in.

**Not on the list, deliberately:** the Power button. It toggles, and a robot
switched off leaves the network — nothing over MQTT brings it back. There is
nothing to learn from it that is worth a trip downstairs to undo.
