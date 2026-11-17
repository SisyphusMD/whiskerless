# #69 Surface the WiFi signal behind the recurring dropout

- Kind: pull, state: closed, by cody, created 2026-08-28T06:53:34-07:00
- Labels: none; milestone: none
- refs/pull/69/head -> main, merged: True

Answers #21. The recurring "did not respond to a state request" dropout is a marginal, flapping WiFi link on one robot (bimodal RSSI, 0% of samples in the -70..-80 band, 15-20 minute regime blocks), not a firmware or integration fault — the integration stays loaded and subscribed throughout and recovers on the first pushed state.

What the code can do is say so: the timeout message now names the last-known RSSI, and the wifi_rssi sensor ships enabled (with the existing-install promotion, without which the change would be inert exactly where it matters).
