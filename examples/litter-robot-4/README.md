# Litter-Robot 4 examples

- **[`automations.yaml`](automations.yaml)** — ready-to-copy automation examples
  (drawer-full alert, fault alerts, pet-weight logging, night-light scheduling).

Entity IDs assume the default device name (`litter_robot_4`); adjust if you
renamed the device.

## Dashboard card

A simple entities card for the device page.

```yaml
type: entities
title: Litter-Robot 4
entities:
  - entity: sensor.litter_robot_4_status
  - entity: sensor.litter_robot_4_waste_drawer_level
  - entity: sensor.litter_robot_4_litter_level
  - entity: sensor.litter_robot_4_pet_weight
  - entity: binary_sensor.litter_robot_4_cat_detected
  - entity: binary_sensor.litter_robot_4_waste_drawer_full
  - entity: select.litter_robot_4_night_light
  - entity: select.litter_robot_4_clean_cycle_wait_time
  - entity: switch.litter_robot_4_control_lock
  - entity: number.litter_robot_4_night_light_brightness
```

A compact glance card for an overview dashboard:

```yaml
type: glance
title: Litter-Robot 4
entities:
  - entity: sensor.litter_robot_4_status
  - entity: sensor.litter_robot_4_waste_drawer_level
  - entity: sensor.litter_robot_4_litter_level
  - entity: binary_sensor.litter_robot_4_cat_detected
```
