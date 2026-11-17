# #176 fix(deps): update dependency pytest-homeassistant to v2026.11.2

- Kind: pull, state: closed, by renovate, created 2026-11-16T13:09:45-08:00
- Labels: none; milestone: none
- refs/pull/176/head -> main, merged: True

This PR contains the following updates:

| Package | Change | [Age](https://docs.renovatebot.com/merge-confidence/) | [Confidence](https://docs.renovatebot.com/merge-confidence/) |
|---|---|---|---|
| [pytest-homeassistant](https://github.com/home-assistant/core) | `==2026.11.1` → `==2026.11.2` | ![age](https://developer.mend.io/api/mc/badges/age/pypi/pytest-homeassistant/2026.11.2?slim=true) | ![confidence](https://developer.mend.io/api/mc/badges/confidence/pypi/pytest-homeassistant/2026.11.1/2026.11.2?slim=true) |

---

### Release Notes

<details>
<summary>home-assistant/core (pytest-homeassistant)</summary>

### [`v2026.11.2`](https://github.com/home-assistant/core/releases/tag/2026.11.2)

[Compare Source](https://github.com/home-assistant/core/compare/2026.11.1...2026.11.2)

- Bump midea-local to v15.1.0 ([@&#8203;chemelli74] - [#&#8203;191702]) ([midea docs]) (dependency)
- Fix UniFi options flow for unloaded entries ([@&#8203;Kane610] - [#&#8203;191684]) ([unifi docs])
- indi_allsky: Bump aioindiallsky to 0.1.8 ([@&#8203;TN-1] - [#&#8203;191797]) ([indi_allsky docs]) (dependency)
- Bump iometer to 1.0.3 ([@&#8203;torben-iometer] - [#&#8203;191801]) ([iometer docs]) (dependency)
- Bump rapt-ble to 2.0.1 ([@&#8203;sairon] - [#&#8203;191777]) ([rapt_ble docs]) (dependency)
- Bump reolink_aio to 0.23.0 ([@&#8203;starkillerOG] - [#&#8203;191779]) ([reolink docs]) (dependency)
- Bump velbus-aio to 2026.11.3 ([@&#8203;cereal2nd] - [#&#8203;191783]) ([velbus docs]) (dependency)
- Don't subscribe to ONVIF webhook notifications without a URL ([@&#8203;MartinHjelmare] - [#&#8203;191846]) ([onvif docs])
- Redact the Solar-Log password in diagnostics ([@&#8203;Dhairya-007] - [#&#8203;191582]) ([solarlog docs])
- Fix Hue migration failing for multi-channel Zigbee devices ([@&#8203;jaeminbird] - [#&#8203;191719]) ([hue docs])
- Bump trmnl to 0.2.0 ([@&#8203;joostlek] - [#&#8203;191919]) ([trmnl docs]) (dependency)
- Fix webostv going unavailable when the TV resets the connection ([@&#8203;thecode] - [#&#8203;191905]) ([webostv docs])
- Fix Axis camera basic auth support ([@&#8203;Kane610] - [#&#8203;191972]) ([axis docs])
- Bump arcam-fmj to 3.1.2 ([@&#8203;elupus] - [#&#8203;191963]) ([arcam_fmj docs]) (dependency)
- Bump aiowebostv to 1.0.2 ([@&#8203;thecode] - [#&#8203;192042]) ([webostv docs]) (dependency)
- Apply the Tedee auth failure grace period during setup ([@&#8203;zweckj] - [#&#8203;192058]) ([tedee docs])
- Add priority sensor to myuplink SMO20 devices ([@&#8203;astrandb] - [#&#8203;192061]) ([myuplink docs])
- Bump egauge-async to 0.6.0 to support virtual registers ([@&#8203;altontoth] - [#&#8203;192004]) ([egauge docs]) (dependency)
- Fix Reolink playback for NVRs and Hubs ([@&#8203;starkillerOG] - [#&#8203;191946]) ([reolink docs])
- Add translations for humidifier modes in Midea ([@&#8203;chemelli74] - [#&#8203;191844]) ([midea docs])
- Bump aiowebostv to 1.1.0 ([@&#8203;thecode] - [#&#8203;192121]) ([webostv docs]) (dependency)
- Reject input_text.set_value values that violate the pattern ([@&#8203;surajvelip] - [#&#8203;192100]) ([input_text docs])
- Fix SmartThings Do Not Disturb time entities with missing value ([@&#8203;joostlek] - [#&#8203;192071]) ([smartthings docs])
- Hide webOS TV volume set when the TV reports it is not supported ([@&#8203;thecode] - [#&#8203;192203]) ([webostv docs])
- fix FRITZ!OS version parsing ([@&#8203;mib1185] - [#&#8203;192332]) ([fritz docs])
- Fix diagnostics for (older) FRITZ!Repeaters ([@&#8203;mib1185] - [#&#8203;192328]) ([fritz docs])
- Update frontend to [`2026102`](https://github.com/home-assistant/core/commit/20261028).6 ([@&#8203;bramkragten] - [#&#8203;192530]) ([frontend docs]) (dependency)
- Bump Todoist SDK to fix project view style deserialization ([@&#8203;nats12] - [#&#8203;192431]) ([todoist docs]) (dependency)
- Fix MQTT reload loop on duplicate unique ID of a disabled entity ([@&#8203;jbouwh] - [#&#8203;192176]) ([mqtt docs])
- Fix MQTT unsubscribe callback after the MQTT entry is reloaded ([@&#8203;jbouwh] - [#&#8203;192440]) ([mqtt docs])
- Prevent voice event from replaying last command after reload in Alexa Devices ([@&#8203;chemelli74] - [#&#8203;192463]) ([alexa_devices docs])
- Redact account identifiers in Alexa Devices ([@&#8203;chemelli74] - [#&#8203;192518]) ([alexa_devices docs])
- Handle Proxmox HTTP skipping nodes that return 596 ([@&#8203;Kevin-Tamayose] - [#&#8203;190487]) ([proxmoxve docs])
- Bump midea-local to 15.2.0 ([@&#8203;chemelli74] - [#&#8203;192648]) ([midea docs]) (dependency)
- Bump axis to 75 ([@&#8203;Kane610] - [#&#8203;192662]) ([axis docs])
- Set ephember iot_class to cloud_polling ([@&#8203;roberty99] - [#&#8203;192811]) ([ephember docs])
- Respect device volume support in Spotify media player ([@&#8203;FrancescoEsk] - [#&#8203;192778]) ([spotify docs])
- ViCare: use temperature delta (K) for heating curve shift and dhw hysteresis ([@&#8203;plata] - [#&#8203;191179]) ([vicare docs])
- Update LG webOS TV device info when the TV connects ([@&#8203;thecode] - [#&#8203;192823]) ([webostv docs])
- Fix dropping of selected regions in NINA config flow ([@&#8203;Shivansh-S17] - [#&#8203;192587]) ([nina docs])
- Bump airOS fixing firmware install ([@&#8203;CoMPaTech] - [#&#8203;192777]) ([airos docs])
- Upgrade aioftp to 0.28.3 (security) ([@&#8203;scop] - [#&#8203;192780]) ([yi docs]) (dependency)
- Ignore a self-referencing MQTT via_device ([@&#8203;jbouwh] - [#&#8203;192776]) ([mqtt docs])
- Fix Jellyfin media source showing no albums for artists ([@&#8203;RunC0deRun] - [#&#8203;192822]) ([jellyfin docs])
- Retry fetching the ONVIF stream URI after a failure ([@&#8203;Glockner00] - [#&#8203;192768]) ([onvif docs])
- Do not log configuration values in empty_config_schema ([@&#8203;jlapenna] - [#&#8203;191715])
- Fix Axis camera stream cleanup on unload ([@&#8203;Kane610] - [#&#8203;192098]) ([axis docs])
- Set SolarEdge Modbus read timeout before probing ([@&#8203;tronikos] - [#&#8203;191780]) ([solaredge_modbus docs])

[#&#8203;190487]: https://github.com/home-assistant/core/pull/190487

[#&#8203;191179]: https://github.com/home-assistant/core/pull/191179

[#&#8203;191582]: https://github.com/home-assistant/core/pull/191582

[#&#8203;191684]: https://github.com/home-assistant/core/pull/191684

[#&#8203;191702]: https://github.com/home-assistant/core/pull/191702

[#&#8203;191715]: https://github.com/home-assistant/core/pull/191715

[#&#8203;191719]: https://github.com/home-assistant/core/pull/191719

[#&#8203;191777]: https://github.com/home-assistant/core/pull/191777

[#&#8203;191779]: https://github.com/home-assistant/core/pull/191779

[#&#8203;191780]: https://github.com/home-assistant/core/pull/191780

[#&#8203;191783]: https://github.com/home-assistant/core/pull/191783

[#&#8203;191797]: https://github.com/home-assistant/core/pull/191797

[#&#8203;191801]: https://github.com/home-assistant/core/pull/191801

[#&#8203;191844]: https://github.com/home-assistant/core/pull/191844

[#&#8203;191846]: https://github.com/home-assistant/core/pull/191846

[#&#8203;191905]: https://github.com/home-assistant/core/pull/191905

[#&#8203;191919]: https://github.com/home-assistant/core/pull/191919

[#&#8203;191946]: https://github.com/home-assistant/core/pull/191946

[#&#8203;191963]: https://github.com/home-assistant/core/pull/191963

[#&#8203;191972]: https://github.com/home-assistant/core/pull/191972

[#&#8203;192004]: https://github.com/home-assistant/core/pull/192004

[#&#8203;192042]: https://github.com/home-assistant/core/pull/192042

[#&#8203;192058]: https://github.com/home-assistant/core/pull/192058

[#&#8203;192061]: https://github.com/home-assistant/core/pull/192061

[#&#8203;192071]: https://github.com/home-assistant/core/pull/192071

[#&#8203;192098]: https://github.com/home-assistant/core/pull/192098

[#&#8203;192100]: https://github.com/home-assistant/core/pull/192100

[#&#8203;192121]: https://github.com/home-assistant/core/pull/192121

[#&#8203;192176]: https://github.com/home-assistant/core/pull/192176

[#&#8203;192203]: https://github.com/home-assistant/core/pull/192203

[#&#8203;192328]: https://github.com/home-assistant/core/pull/192328

[#&#8203;192332]: https://github.com/home-assistant/core/pull/192332

[#&#8203;192431]: https://github.com/home-assistant/core/pull/192431

[#&#8203;192440]: https://github.com/home-assistant/core/pull/192440

[#&#8203;192463]: https://github.com/home-assistant/core/pull/192463

[#&#8203;192518]: https://github.com/home-assistant/core/pull/192518

[#&#8203;192530]: https://github.com/home-assistant/core/pull/192530

[#&#8203;192587]: https://github.com/home-assistant/core/pull/192587

[#&#8203;192648]: https://github.com/home-assistant/core/pull/192648

[#&#8203;192662]: https://github.com/home-assistant/core/pull/192662

[#&#8203;192768]: https://github.com/home-assistant/core/pull/192768

[#&#8203;192776]: https://github.com/home-assistant/core/pull/192776

[#&#8203;192777]: https://github.com/home-assistant/core/pull/192777

[#&#8203;192778]: https://github.com/home-assistant/core/pull/192778

[#&#8203;192780]: https://github.com/home-assistant/core/pull/192780

[#&#8203;192811]: https://github.com/home-assistant/core/pull/192811

[#&#8203;192822]: https://github.com/home-assistant/core/pull/192822

[#&#8203;192823]: https://github.com/home-assistant/core/pull/192823

[@&#8203;CoMPaTech]: https://github.com/CoMPaTech

[@&#8203;Dhairya-007]: https://github.com/Dhairya-007

[@&#8203;FrancescoEsk]: https://github.com/FrancescoEsk

[@&#8203;Glockner00]: https://github.com/Glockner00

[@&#8203;Kane610]: https://github.com/Kane610

[@&#8203;Kevin-Tamayose]: https://github.com/Kevin-Tamayose

[@&#8203;MartinHjelmare]: https://github.com/MartinHjelmare

[@&#8203;RunC0deRun]: https://github.com/RunC0deRun

[@&#8203;Shivansh-S17]: https://github.com/Shivansh-S17

[@&#8203;TN-1]: https://github.com/TN-1

[@&#8203;altontoth]: https://github.com/altontoth

[@&#8203;astrandb]: https://github.com/astrandb

[@&#8203;bramkragten]: https://github.com/bramkragten

[@&#8203;cereal2nd]: https://github.com/cereal2nd

[@&#8203;chemelli74]: https://github.com/chemelli74

[@&#8203;elupus]: https://github.com/elupus

[@&#8203;jaeminbird]: https://github.com/jaeminbird

[@&#8203;jbouwh]: https://github.com/jbouwh

[@&#8203;jlapenna]: https://github.com/jlapenna

[@&#8203;joostlek]: https://github.com/joostlek

[@&#8203;mib1185]: https://github.com/mib1185

[@&#8203;nats12]: https://github.com/nats12

[@&#8203;plata]: https://github.com/plata

[@&#8203;roberty99]: https://github.com/roberty99

[@&#8203;sairon]: https://github.com/sairon

[@&#8203;scop]: https://github.com/scop

[@&#8203;starkillerOG]: https://github.com/starkillerOG

[@&#8203;surajvelip]: https://github.com/surajvelip

[@&#8203;thecode]: https://github.com/thecode

[@&#8203;torben-iometer]: https://github.com/torben-iometer

[@&#8203;tronikos]: https://github.com/tronikos

[@&#8203;zweckj]: https://github.com/zweckj

[airos docs]: https://www.home-assistant.io/integrations/airos/

[alexa_devices docs]: https://www.home-assistant.io/integrations/alexa_devices/

[arcam_fmj docs]: https://www.home-assistant.io/integrations/arcam_fmj/

[axis docs]: https://www.home-assistant.io/integrations/axis/

[egauge docs]: https://www.home-assistant.io/integrations/egauge/

[ephember docs]: https://www.home-assistant.io/integrations/ephember/

[fritz docs]: https://www.home-assistant.io/integrations/fritz/

[frontend docs]: https://www.home-assistant.io/integrations/frontend/

[hue docs]: https://www.home-assistant.io/integrations/hue/

[indi_allsky docs]: https://www.home-assistant.io/integrations/indi_allsky/

[input_text docs]: https://www.home-assistant.io/integrations/input_text/

[iometer docs]: https://www.home-assistant.io/integrations/iometer/

[jellyfin docs]: https://www.home-assistant.io/integrations/jellyfin/

[midea docs]: https://www.home-assistant.io/integrations/midea/

[mqtt docs]: https://www.home-assistant.io/integrations/mqtt/

[myuplink docs]: https://www.home-assistant.io/integrations/myuplink/

[nina docs]: https://www.home-assistant.io/integrations/nina/

[onvif docs]: https://www.home-assistant.io/integrations/onvif/

[proxmoxve docs]: https://www.home-assistant.io/integrations/proxmoxve/

[rapt_ble docs]: https://www.home-assistant.io/integrations/rapt_ble/

[reolink docs]: https://www.home-assistant.io/integrations/reolink/

[smartthings docs]: https://www.home-assistant.io/integrations/smartthings/

[solaredge_modbus docs]: https://www.home-assistant.io/integrations/solaredge_modbus/

[solarlog docs]: https://www.home-assistant.io/integrations/solarlog/

[spotify docs]: https://www.home-assistant.io/integrations/spotify/

[tedee docs]: https://www.home-assistant.io/integrations/tedee/

[todoist docs]: https://www.home-assistant.io/integrations/todoist/

[trmnl docs]: https://www.home-assistant.io/integrations/trmnl/

[unifi docs]: https://www.home-assistant.io/integrations/unifi/

[velbus docs]: https://www.home-assistant.io/integrations/velbus/

[vicare docs]: https://www.home-assistant.io/integrations/vicare/

[webostv docs]: https://www.home-assistant.io/integrations/webostv/

[yi docs]: https://www.home-assistant.io/integrations/yi/

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

This PR has been generated by [Mend Renovate CLI](https://github.com/renovatebot/renovate).
<!--renovate-debug:eyJjcmVhdGVkSW5WZXIiOiI0NC4yNDcuMCIsInVwZGF0ZWRJblZlciI6IjQ0LjI0Ny4wIiwidGFyZ2V0QnJhbmNoIjoibWFpbiIsImxhYmVscyI6WyJwYXRjaC11cGRhdGUiXX0=-->
