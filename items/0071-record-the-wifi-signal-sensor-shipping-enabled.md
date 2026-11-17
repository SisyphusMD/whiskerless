# #71 Record the WiFi signal sensor shipping enabled

- Kind: pull, state: closed, by cody, created 2026-08-28T11:57:25-07:00
- Labels: none; milestone: none
- refs/pull/71/head -> main, merged: True

The sensor now ships enabled and is promoted on existing installs, and the heartbeat timeout names the last reported signal. Both are user-visible and were missing from [Unreleased] ahead of 0.2.0.

Deliberately worded as context rather than guidance: the recurring dropout investigated in #21 turned out to be a wedged MQTT client on a healthy network, so the notes must not send users to RSSI as a first check.
