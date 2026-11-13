# Notifications

Going local loses every push notification the Whisker app sent. whiskerless replaces
them in two parts:

- **The integration decides when.** Every alert arrives on Home Assistant's event bus as
  one `whiskerless_alert` event, with hold times and thresholds already applied, so a
  bonnet lifted for a quick scoop never pages anyone.
- **A blueprint decides who hears about it.** Import it once, pick phones and robots,
  and tick the alerts you want.

## Install the blueprint

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FSisyphusMD%2Fwhiskerless%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fwhiskerless%2Flitter_robot_notifications.yaml)

Or import it by hand under **Settings → Automations & scenes → Blueprints → Import
blueprint**, with this URL:

```text
https://github.com/SisyphusMD/whiskerless/blob/main/blueprints/automation/whiskerless/litter_robot_notifications.yaml
```

Then **Create automation** from it. Use it once for every robot (leave **Robots** empty),
or once per robot when different people care about different boxes.

What it does:

- The title is the robot's name as you see it in Home Assistant, renames included. The
  message says what to do. On iPhone a small "whiskerless" line sits between them;
  Android has no such line, and tints the corner icon whiskerless teal instead.
- Faults, a full-drawer lockout, an offline robot and an integration that failed to
  start are **time-sensitive** on iOS
  (they break through Focus) and high priority on Android. They also ignore quiet hours.
- In **quiet hours** everything else still arrives, silently, and reminders are not sent.
  On Android the silent ones use their own notification channel, `whiskerless_quiet`,
  which you can tune in the phone's settings.
- An alert left alone is announced again: an urgent one every 6 hours, the rest at 7:00
  and 19:00 once they are 6 hours old, until the alert clears. The reminder replaces the
  earlier notification rather than adding another.
- Every alert and reminder has a **Silence** button. It stops the reminders on that phone
  only, until the alert clears; everyone else keeps getting them, and the next time the
  same thing happens everyone hears about it again.
- A newer alert of the same kind replaces the older one, and an alert is removed from
  the phone when its condition clears (turn that off under **Quiet hours, reminders
  and clearing**, where reminders can be turned off too). An offline robot coming back says "Back online." instead, and
  an integration that failed to start says "Whiskerless is running again." once it does. On iPhone the
  removal can lag by a couple of minutes, because iOS chooses when to wake the app for it.
- Tapping a notification opens the robot's device page.
- **Picture** is optional and shows full width when you expand a notification. Copy an
  image into your `config/www` folder and give its path, such as `/local/litterbox.png`.
  A notification with a picture also gets an **Open** button, because Companion for iOS
  2026.9.3 and later show no picture without one. The small corner icon is always Home
  Assistant's; nothing a blueprint sends can change that.
- **Other notify action** takes any `notify.*` action (a group, Telegram, a TV) and
  sends it the title and message only.

## Thresholds

The integration's **Configure** button (Settings → Devices & services → whiskerless)
opens **Alert thresholds**: the drawer level, low litter, the no-visit window, long and
frequent visits, the weight change, and how often the deep clean, carbon filter and
globe clean fall due. Whisker recommends a deep clean at least every 3 months and a new
carbon filter monthly. The same page sets how often an urgent alert is reminded about (0
for never) and the two hours of the day for every other reminder.

A drawer level or low litter alert clears only once the level is 10 points back past its
threshold: low litter at 30% clears at 40%. The gauges wander a few points on a box nobody
has touched, and without that gap each wander was a new alert. Low litter is only judged on
a settled robot, so a visit or the countdown after it neither raises nor clears it.

The robot only measures the hopper when it dispenses, and a full globe does not dispense. A
hopper refilled on its own clears the alert at the next dispense, which can be days away. Topping
up the globe at the same time clears it within the hour, and the hopper level shows
unknown until the next dispense measures it. If the hopper is in fact still empty, that dispense
raises the alert again.

The maintenance alerts count from the **Last deep clean**, **Last carbon filter change** and
**Last globe clean** dates on the device page. Nothing is due until you set one.

## The `whiskerless_alert` event

Any automation can trigger on it. Its data:

| Key | Value |
| --- | --- |
| `device_id` | The robot's Home Assistant device |
| `serial` | The robot's serial |
| `robot` | The robot's name as shown in Home Assistant |
| `alert` | One of the keys below |
| `event` | `raised` or `cleared` for a condition, `reminder` for one still active, `moment` for something that just happened |
| `urgent` | `true` for the time-sensitive alerts |
| `message` | The English text the blueprint sends |
| `details` | Extra values, per alert (below) |
| `silenced` | On a reminder, the phones (device IDs) that tapped Silence; empty otherwise |

A condition is raised once and cleared once, with reminders between while it lasts. One
that was active before a restart is not announced again, and its reminder clock and
silences carry over.

The Silence button's action is `WHISKERLESS_SILENCE|<serial>|<alert>|<phone device ID>`.
The integration listens for the Companion app's `mobile_app_notification_action` event, so
a notification of your own can carry the same button.

| `alert` | Kind | Raised when | `details` |
| --- | --- | --- | --- |
| `globe_fault` | condition, urgent | The globe motor reports a fault | `cause` |
| `bonnet_removed` | condition, urgent | Bonnet off for 5 minutes | |
| `drawer_full_lockout` | condition, urgent | The robot stops on a full drawer | |
| `cat_sensor_blocked` | condition, urgent | Cat sensor blocked for 30 minutes | |
| `excess_weight` | condition, urgent | Something on the scale for 30 minutes | |
| `stuck_cycle` | condition, urgent | A clean cycle stuck for 30 minutes | |
| `offline` | condition, urgent | No answer for 15 minutes | |
| `setup_failed` | urgent | Home Assistant could not set the integration up (anything but an unreachable robot, which is `offline`); clears when a later setup succeeds. Never reminded, and has no Silence button | `error` (the exception's type) |
| `drawer_full` | condition | The drawer-full sensor trips | |
| `drawer_level` | condition | The drawer reaches the threshold; clears 10 points below it | `level` |
| `litter_low` | condition | Litter at or below the threshold; clears 10 points above it | `level` |
| `hopper_empty` | condition | The hopper runs out; clears at a dispense that finds litter, or when the globe is topped up by hand | |
| `hopper_disconnected` | condition | A hopper seen before is unplugged | |
| `no_visit` | condition | No visit for the set number of hours | `hours`, `last_visit` |
| `deep_clean_due`, `filter_due`, `globe_clean_due` | condition | The interval since the recorded date has passed | `last_done`, `due` |
| `visit` | moment | A cat visit ended | `duration_s`, `weight_lb` |
| `long_visit` | moment | A visit lasted at least the threshold | `duration_s`, `weight_lb` |
| `frequent_visits` | moment | The threshold number of visits within an hour | `visits` |
| `weight_change` | moment | A weighed visit far from the usual weight | `weight_lb`, `usual_lb`, `change_percent` |
| `cycle_completed` | moment | A clean cycle finished | `cycle_count`, `waste_drawer_level` |
| `panel_lock_changed` | moment | Control lock turned on or off | `locked` |

`weight_lb` is `null` when the visit was too short for the robot to weigh. The usual
weight is the median of the last ten weighed visits on that robot, and the alert waits
for three. It mixes every cat that uses the box, which is why the blueprint ships it off:
in a two-cat home the median is nobody's weight.

## What the Whisker app sent that this cannot

Pinch detect, a jammed globe and low voltage arrive as the globe fault's `cause` rather
than alerts of their own. Laser board faults, a dirty sensor and motion in the drawer
have no local signal yet, and firmware-update notices are left out on purpose, because
whiskerless refuses updates by design.
