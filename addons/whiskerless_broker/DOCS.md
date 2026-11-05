# Whiskerless robot broker

A TLS MQTT broker for Whisker robots provisioned by whiskerless, bridged into the
Mosquitto add-on. Use it when the robot cannot connect to the Mosquitto add-on
directly: the robot logs in without a username or password, which the Mosquitto
add-on does not allow, or another service already holds port 8883 on this host.

## Setup

1. Run `whiskerless setup --host <home-assistant-ip>` on your computer.
2. Copy `ca.crt`, `server.crt` and `server.key` into this add-on's config folder
   (`addon_configs/<id>_whiskerless_broker/` in the Samba or SSH add-on).
3. Start the add-on, then provision the robot with `whiskerless provision`.

The robot's messages appear in the Mosquitto add-on under `prod/`, where Home
Assistant's MQTT integration and the whiskerless integration pick them up.

## Port 8883 already in use

Change the host port for `8883/tcp` in the **Network** section, then redirect the
robot's 8883 to that port on your router, and give the robot a fixed IP.

Full guide, including the router rule:
https://github.com/SisyphusMD/whiskerless/blob/main/docs/setup/robot-broker.md
