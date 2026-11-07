# Litter-Robot EVO examples

- **[`automations.yaml`](automations.yaml)** — the panel brightness schedule from
  the blueprint, and a waste drawer alert.
- **[`scripts.yaml`](scripts.yaml)** — set the screen and status LED to any pair
  of levels in one go.

Entity IDs assume the default device name (`litter_robot_evo`); adjust if you
renamed the device.

The integration reads the robot's settings when it starts and whenever the robot
reconnects, so both brightness levels are known before the blueprint runs. If the
robot was unreachable at that moment and a level still reads unknown, pick a
**Panel brightness** preset once: a single level cannot be changed until the other
is known.

## Panel brightness

The Whisker app offers Low (8), Medium (20) and High (40) for the screen and status
LED together. The **Screen brightness** and **Status LED brightness** controls take
each from 1 to 100 on its own, and the **Panel brightness** preset adds Off (both
at 1). 1 is the dimmest: the robot turns 0 into 50.

The [panel brightness blueprint](../../blueprints/automation/whiskerless/litter_robot_evo_panel_brightness.yaml)
sets a night level and a day level at each end of the window, when Home Assistant
starts, and after the robot reconnects, when the cloud resends the app's preset. A
level you change by hand is left alone until the next of those.

## Dashboard card

```yaml
type: entities
title: Litter-Robot EVO
entities:
  - entity: sensor.litter_robot_evo_status
  - entity: binary_sensor.litter_robot_evo_waste_drawer_removed
  - entity: binary_sensor.litter_robot_evo_bonnet_removed
  - entity: select.litter_robot_evo_panel_brightness
  - entity: number.litter_robot_evo_screen_brightness
  - entity: number.litter_robot_evo_status_led_brightness
  - entity: select.litter_robot_evo_cycle_delay
  - entity: switch.litter_robot_evo_control_lock
  - entity: button.litter_robot_evo_clean_cycle
```
