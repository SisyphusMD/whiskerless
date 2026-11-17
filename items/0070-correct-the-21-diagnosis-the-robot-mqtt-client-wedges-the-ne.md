# #70 Correct the #21 diagnosis: the robot MQTT client wedges, the network is fine

- Kind: pull, state: closed, by cody, created 2026-08-28T09:11:36-07:00
- Labels: none; milestone: none
- refs/pull/70/head -> main, merged: True

The earlier answer to #21 blamed a marginal WiFi link. That was wrong, and a confident wrong answer in the permanent record is worse than the blocked state it replaced.

The broker log shows the robot dropped on keepalive timeout, retried twice, aborted both retries mid-TLS-handshake, then stopped trying for ten hours — while answering ICMP with 0% loss. Robot-side, not broker-side: the sibling robot handshook against the same broker three hours later, and the cert is valid into 2036.

wifiRssi is bimodal on both robots and resamples per MQTT session, but inter-message cadence is identical in both clusters, so it did not explain this incident. The text is careful not to overcorrect into claiming the field is meaningless — it is a real measurement that is not a diagnosis on its own.

Also adds #90: telling a robot that has left the broker apart from one merely not answering, with the inference direction hedged (silence alone cannot prove it).
