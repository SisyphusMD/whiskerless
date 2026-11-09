# Cloud bridge examples

A dashboard for a [cloud bridge](../../docs/setup/cloud-bridge.md): the toggle, its
connection state, the last message, a traffic log, and a form for sending a message.

Entity IDs assume a bridge for serial `LR4C000001`, whose device is named
`Cloud bridge LR4C000001`; replace `lr4c000001` with your robot's serial in lower case.

## The send form

Add this script (Settings → Automations & scenes → Scripts → ⋮ → Edit in YAML, or
your `scripts.yaml` without the top-level `script:` key). Running it from the
dashboard opens a form with its fields.

```yaml
script:
  whiskerless_bridge_send:
    alias: Send through the cloud bridge
    icon: mdi:send
    fields:
      bridge:
        name: Cloud bridge
        required: true
        selector:
          config_entry:
            integration: whiskerless
      direction:
        name: Direction
        required: true
        default: to_robot
        selector:
          select:
            options:
              - label: To robot (command topic)
                value: to_robot
              - label: To cloud, as the robot (activity topic)
                value: to_cloud
      payload:
        name: Payload
        required: true
        example: '{"serial": "LR4C000001", "data": ["0x02A00000"]}'
        selector:
          text:
            multiline: true
      allow_untraced:
        name: Allow commands the safety guard cannot classify
        default: false
        selector:
          boolean:
    sequence:
      - action: whiskerless.send_bridge_message
        data:
          config_entry_id: "{{ bridge }}"
          direction: "{{ direction }}"
          payload: "{{ payload }}"
          allow_untraced: "{{ allow_untraced }}"
```

## Dashboard

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Cloud bridge
    entities:
      - entity: switch.cloud_bridge_lr4c000001_cloud_bridge
      - entity: sensor.cloud_bridge_lr4c000001_cloud_bridge_state
        secondary_info: last-changed
      - entity: script.whiskerless_bridge_send
        name: Send a message
  - type: markdown
    title: Last message
    content: >-
      {% set e = 'event.cloud_bridge_lr4c000001_cloud_bridge_traffic' %}
      {% if state_attr(e, 'topic') %}
      **{{ state_attr(e, 'event_type') | replace('_', ' ') }}**
      {{ '(sent by hand)' if state_attr(e, 'injected') }}
      at {{ as_timestamp(states(e)) | timestamp_custom('%H:%M:%S') }}

      `{{ state_attr(e, 'topic') }}`

      ```
      {{ state_attr(e, 'payload') }}
      ```
      {% else %}
      Nothing relayed yet.
      {% endif %}
  - type: logbook
    title: Traffic
    hours_to_show: 6
    target:
      entity_id: event.cloud_bridge_lr4c000001_cloud_bridge_traffic
```

Each relayed message is one change of the traffic event entity, so the logbook
lists them in order, and its history keeps them for as long as the recorder does.
The payload in the event is cut at 2048 characters; the `truncated` attribute says
when it was.
