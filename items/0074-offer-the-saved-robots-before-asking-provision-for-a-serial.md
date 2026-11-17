# #74 Offer the saved robots before asking provision for a serial

- Kind: pull, state: closed, by cody, created 2026-08-28T13:36:04-07:00
- Labels: none; milestone: none
- refs/pull/74/head -> main, merged: True

provision asked for a raw serial even when the store already knew the robot. Entering pairing mode wipes the robot WiFi and only a completed provision restores it, so this prompt is reached most often mid-outage by someone least able to recall a serial.

Mirrors the siblings resume-or-start-fresh list in dreame-valetudo: saved robots numbered, with a final NEW robot entry that falls through to typing a serial. --serial still skips the list, and a non-interactive run is unchanged.

Offered from ONE saved robot, unlike _pick_saved_robot which needs two: that one disambiguates, this one saves typing, so the single-robot case benefits most.
