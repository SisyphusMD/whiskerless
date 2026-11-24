# #250 fix(deps): update dependency pytest-homeassistant to v2026.11.3

- Kind: pull, state: closed, by renovate, created 2026-11-23T13:09:34-08:00
- Labels: none; milestone: none
- refs/pull/250/head -> main, merged: True

This PR contains the following updates:

| Package | Change | [Age](https://docs.renovatebot.com/merge-confidence/) | [Confidence](https://docs.renovatebot.com/merge-confidence/) |
|---|---|---|---|
| [pytest-homeassistant](https://github.com/home-assistant/core) | `==2026.11.2` → `==2026.11.3` | ![age](https://developer.mend.io/api/mc/badges/age/pypi/pytest-homeassistant/2026.11.3?slim=true) | ![confidence](https://developer.mend.io/api/mc/badges/confidence/pypi/pytest-homeassistant/2026.11.2/2026.11.3?slim=true) |

---

### Release Notes

<details>
<summary>home-assistant/core (pytest-homeassistant)</summary>

### [`v2026.11.3`](https://github.com/home-assistant/core/releases/tag/2026.11.3)

[Compare Source](https://github.com/home-assistant/core/compare/2026.11.2...2026.11.3)

- Fix add_bonus_time selector range in Nintendo Parental Controls ([@&#8203;theSiegs] - [#&#8203;192891]) ([nintendo_parental_controls docs])
- Re-login Vodafone Station on session expired by the router ([@&#8203;chemelli74] - [#&#8203;193102]) ([vodafone_station docs])
- Bump aioamazondevices to 17.3.2 ([@&#8203;jamesonuk] - [#&#8203;193129]) ([alexa_devices docs]) (dependency)
- Disable UniFi polling for unavailable v2 endpoints ([@&#8203;fermulator] - [#&#8203;188431]) ([unifi docs])
- Clear Shelly RPC update progress when the device reconnects ([@&#8203;thecode] - [#&#8203;193168]) ([shelly docs])
- Revert iometer to 1.0.2 to restore sensor updates ([@&#8203;jukrebs] - [#&#8203;193267]) ([iometer docs]) (dependency)
- Bump earn-e-p1 to 0.4.0 ([@&#8203;Miggets7] - [#&#8203;193283]) ([earn_e_p1 docs]) (dependency)
- Bump earn-e-p1 to 0.4.2 ([@&#8203;Miggets7] - [#&#8203;193292]) ([earn_e_p1 docs]) (dependency)
- Fix Tasmota discovery after a device was removed ([@&#8203;tux1337] - [#&#8203;193290]) ([tasmota docs])
- Check the time zone before other core config changes ([@&#8203;balloob] - [#&#8203;193306])
- Bump hydroquebec_peak to 0.3.0 ([@&#8203;Beat-YT] - [#&#8203;192960]) ([hydroquebec_peak docs]) (dependency)
- Do not log RESTful Command header values ([@&#8203;DCSBL] - [#&#8203;193394]) ([rest_command docs])
- Accept unquoted E.164 phone numbers in twilio_call and clicksend_tts ([@&#8203;frenck] - [#&#8203;193434]) ([clicksend_tts docs]) ([twilio_call docs])
- Keep the resolved Marketplace content when the catalog install falls back ([@&#8203;frenck] - [#&#8203;193438]) ([marketplace docs])
- Give the Marketplace card gzip the same file mode as the card ([@&#8203;frenck] - [#&#8203;193439]) ([marketplace docs])
- Stop re-adding go2rtc streams that have credentials in their URL ([@&#8203;frenck] - [#&#8203;193436]) ([go2rtc docs])
- Add SmartThings air conditioners without a demand response status ([@&#8203;frenck] - [#&#8203;193458]) ([smartthings docs])
- Allow large response headers when fetching the IndieAuth client_id ([@&#8203;frenck] - [#&#8203;193440]) ([auth docs])
- Stop the Tuya MQ thread when Home Assistant stops ([@&#8203;frenck] - [#&#8203;193461]) ([tuya docs])
- Store every Blink token refresh, not only the first one ([@&#8203;frenck] - [#&#8203;193455]) ([blink docs])
- Bump midea-local to 15.2.1 ([@&#8203;chemelli74] - [#&#8203;193567]) ([midea docs]) (dependency)
- Update frontend to [`2026102`](https://github.com/home-assistant/core/commit/20261028).8 ([@&#8203;bramkragten] - [#&#8203;193593]) ([frontend docs]) (dependency)
- Bump vizaio to 0.7.1 ([@&#8203;raman325] - [#&#8203;193637]) ([vizio docs]) (dependency)
- Bump pydrawise to 2026.11.0 ([@&#8203;dknowles2] - [#&#8203;193708]) ([hydrawise docs]) (dependency)
- Keep webOS TV volume set when the TV speaker is active ([@&#8203;thecode] - [#&#8203;193694]) ([webostv docs])
- Bump aiovodafone to 3.3.13 ([@&#8203;chemelli74] - [#&#8203;193730]) ([vodafone_station docs]) (dependency)
- Bump aiowebostv to 1.1.1 ([@&#8203;thecode] - [#&#8203;193731]) ([webostv docs]) (dependency)
- Fix availability of FRITZ!Box tools profile switches ([@&#8203;mib1185] - [#&#8203;193682]) ([fritz docs])
- Skip non-monotonic packets in stream recorder ([@&#8203;chemelli74] - [#&#8203;193668]) ([stream docs])
- Bump modbus-connection to 4.12.8 ([@&#8203;balloob] - [#&#8203;193617]) ([modbus docs]) (dependency)
- Further reduce API calls in FRITZ!Box tools ([@&#8203;mib1185] - [#&#8203;193680]) ([fritz docs])
- Fix initial hvac mode for MQTT climate in optimistic mode ([@&#8203;jbouwh] - [#&#8203;193626]) ([mqtt docs])
- Fix missing SSL option on older FRITZ!Box tools config entries ([@&#8203;mib1185] - [#&#8203;193670]) ([fritz docs])
- Add a note about the credentials docs in the FRITZ!Box tools re-auth flow ([@&#8203;mib1185] - [#&#8203;193673]) ([fritz docs])
- Fix duplicate unique ID during FRITZ!Box Tools switch migration ([@&#8203;ldeutschland] - [#&#8203;185485]) ([fritz docs])
- Redact Switcher credentials in diagnostics ([@&#8203;thecode] - [#&#8203;193835]) ([switcher_kis docs])
- Keep polling manual Sonos hosts when one can not be resolved ([@&#8203;frenck] - [#&#8203;193579]) ([sonos docs])
- Bump aiovodafone to 3.3.14 ([@&#8203;chemelli74] - [#&#8203;193869]) ([vodafone_station docs]) (dependency)
- Remove AC entities for unsupported capabilities ([@&#8203;chemelli74] - [#&#8203;193994]) ([midea docs])
- Handle Shelly virtual components without a view ([@&#8203;frenck] - [#&#8203;193460]) ([shelly docs])

[#&#8203;185485]: https://github.com/home-assistant/core/pull/185485

[#&#8203;188431]: https://github.com/home-assistant/core/pull/188431

[#&#8203;192891]: https://github.com/home-assistant/core/pull/192891

[#&#8203;192960]: https://github.com/home-assistant/core/pull/192960

[#&#8203;193102]: https://github.com/home-assistant/core/pull/193102

[#&#8203;193129]: https://github.com/home-assistant/core/pull/193129

[#&#8203;193168]: https://github.com/home-assistant/core/pull/193168

[#&#8203;193267]: https://github.com/home-assistant/core/pull/193267

[#&#8203;193283]: https://github.com/home-assistant/core/pull/193283

[#&#8203;193290]: https://github.com/home-assistant/core/pull/193290

[#&#8203;193292]: https://github.com/home-assistant/core/pull/193292

[#&#8203;193306]: https://github.com/home-assistant/core/pull/193306

[#&#8203;193394]: https://github.com/home-assistant/core/pull/193394

[#&#8203;193434]: https://github.com/home-assistant/core/pull/193434

[#&#8203;193436]: https://github.com/home-assistant/core/pull/193436

[#&#8203;193438]: https://github.com/home-assistant/core/pull/193438

[#&#8203;193439]: https://github.com/home-assistant/core/pull/193439

[#&#8203;193440]: https://github.com/home-assistant/core/pull/193440

[#&#8203;193455]: https://github.com/home-assistant/core/pull/193455

[#&#8203;193458]: https://github.com/home-assistant/core/pull/193458

[#&#8203;193460]: https://github.com/home-assistant/core/pull/193460

[#&#8203;193461]: https://github.com/home-assistant/core/pull/193461

[#&#8203;193567]: https://github.com/home-assistant/core/pull/193567

[#&#8203;193579]: https://github.com/home-assistant/core/pull/193579

[#&#8203;193593]: https://github.com/home-assistant/core/pull/193593

[#&#8203;193617]: https://github.com/home-assistant/core/pull/193617

[#&#8203;193626]: https://github.com/home-assistant/core/pull/193626

[#&#8203;193637]: https://github.com/home-assistant/core/pull/193637

[#&#8203;193668]: https://github.com/home-assistant/core/pull/193668

[#&#8203;193670]: https://github.com/home-assistant/core/pull/193670

[#&#8203;193673]: https://github.com/home-assistant/core/pull/193673

[#&#8203;193680]: https://github.com/home-assistant/core/pull/193680

[#&#8203;193682]: https://github.com/home-assistant/core/pull/193682

[#&#8203;193694]: https://github.com/home-assistant/core/pull/193694

[#&#8203;193708]: https://github.com/home-assistant/core/pull/193708

[#&#8203;193730]: https://github.com/home-assistant/core/pull/193730

[#&#8203;193731]: https://github.com/home-assistant/core/pull/193731

[#&#8203;193835]: https://github.com/home-assistant/core/pull/193835

[#&#8203;193869]: https://github.com/home-assistant/core/pull/193869

[#&#8203;193994]: https://github.com/home-assistant/core/pull/193994

[@&#8203;Beat-YT]: https://github.com/Beat-YT

[@&#8203;DCSBL]: https://github.com/DCSBL

[@&#8203;Miggets7]: https://github.com/Miggets7

[@&#8203;balloob]: https://github.com/balloob

[@&#8203;bramkragten]: https://github.com/bramkragten

[@&#8203;chemelli74]: https://github.com/chemelli74

[@&#8203;dknowles2]: https://github.com/dknowles2

[@&#8203;fermulator]: https://github.com/fermulator

[@&#8203;frenck]: https://github.com/frenck

[@&#8203;jamesonuk]: https://github.com/jamesonuk

[@&#8203;jbouwh]: https://github.com/jbouwh

[@&#8203;jukrebs]: https://github.com/jukrebs

[@&#8203;ldeutschland]: https://github.com/ldeutschland

[@&#8203;mib1185]: https://github.com/mib1185

[@&#8203;raman325]: https://github.com/raman325

[@&#8203;theSiegs]: https://github.com/theSiegs

[@&#8203;thecode]: https://github.com/thecode

[@&#8203;tux1337]: https://github.com/tux1337

[alexa_devices docs]: https://www.home-assistant.io/integrations/alexa_devices/

[auth docs]: https://www.home-assistant.io/integrations/auth/

[blink docs]: https://www.home-assistant.io/integrations/blink/

[clicksend_tts docs]: https://www.home-assistant.io/integrations/clicksend_tts/

[earn_e_p1 docs]: https://www.home-assistant.io/integrations/earn_e_p1/

[fritz docs]: https://www.home-assistant.io/integrations/fritz/

[frontend docs]: https://www.home-assistant.io/integrations/frontend/

[go2rtc docs]: https://www.home-assistant.io/integrations/go2rtc/

[hydrawise docs]: https://www.home-assistant.io/integrations/hydrawise/

[hydroquebec_peak docs]: https://www.home-assistant.io/integrations/hydroquebec_peak/

[iometer docs]: https://www.home-assistant.io/integrations/iometer/

[marketplace docs]: https://www.home-assistant.io/integrations/marketplace/

[midea docs]: https://www.home-assistant.io/integrations/midea/

[modbus docs]: https://www.home-assistant.io/integrations/modbus/

[mqtt docs]: https://www.home-assistant.io/integrations/mqtt/

[nintendo_parental_controls docs]: https://www.home-assistant.io/integrations/nintendo_parental_controls/

[rest_command docs]: https://www.home-assistant.io/integrations/rest_command/

[shelly docs]: https://www.home-assistant.io/integrations/shelly/

[smartthings docs]: https://www.home-assistant.io/integrations/smartthings/

[sonos docs]: https://www.home-assistant.io/integrations/sonos/

[stream docs]: https://www.home-assistant.io/integrations/stream/

[switcher_kis docs]: https://www.home-assistant.io/integrations/switcher_kis/

[tasmota docs]: https://www.home-assistant.io/integrations/tasmota/

[tuya docs]: https://www.home-assistant.io/integrations/tuya/

[twilio_call docs]: https://www.home-assistant.io/integrations/twilio_call/

[unifi docs]: https://www.home-assistant.io/integrations/unifi/

[vizio docs]: https://www.home-assistant.io/integrations/vizio/

[vodafone_station docs]: https://www.home-assistant.io/integrations/vodafone_station/

[webostv docs]: https://www.home-assistant.io/integrations/webostv/

</details>

---

### Configuration

📅 **Schedule**: (UTC)

- Branch creation
  - At any time (no schedule defined)
- Automerge
  - At any time (no schedule defined)

🚦 **Automerge**: Enabled.

♻ **Rebasing**: Whenever PR is behind base branch, or you tick the rebase/retry checkbox.

🔕 **Ignore**: Close this PR and you won't be reminded about this update again.

---

 - [ ] <!-- rebase-check -->If you want to rebase/retry this PR, check this box

---

Refs #211: standing issue for dependency updates.

No tests: dependency pins and their generated files are checked by the existing build and test jobs.
<!--renovate-debug:eyJjcmVhdGVkSW5WZXIiOiI0NC4yNTguMSIsInVwZGF0ZWRJblZlciI6IjQ0LjI1OC4xIiwidGFyZ2V0QnJhbmNoIjoibWFpbiIsImxhYmVscyI6WyJwYXRjaC11cGRhdGUiXX0=-->


## forgejo-actions, 2026-11-23T13:12:35-08:00

<!-- ai-review -->
**AI review** of `a42ceca5e2`: Single-line patch bump of the test-only dependency `pytest-homeassistant` from 2026.11.2 to 2026.11.3, linked to the standing Renovate issue #211. No issues found.

No findings.

Disagree? Reply on this PR with your reasoning; the reviewer re-reads every reply.
<!-- ai-review-state W10= -->
