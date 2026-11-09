#!/bin/sh
# Builds mosquitto.conf from the add-on options and the Supervisor's MQTT service,
# then runs Mosquitto in the foreground.
#
# Listener: TLS on 8883 for robots. With require_client_certificate a robot must
# present a certificate signed by ca.crt, and its common name becomes its username.
# Without it, anonymous clients are accepted but confined by an ACL to
# robot_acl_pattern.
#
# Bridge: every bridge_topics entry is forwarded to the Mosquitto add-on, where
# Home Assistant's MQTT integration (and the whiskerless integration) see it.
set -eu

CERTS=/config
OPTIONS=/data/options.json
CONF=/tmp/mosquitto.conf
ACL=/tmp/acl

for name in ca.crt server.crt server.key; do
  if [ ! -s "$CERTS/$name" ]; then
    printf 'missing %s/%s: copy the broker files written by whiskerless setup into this add-on'"'"'s config folder\n' \
      "$CERTS" "$name" >&2
    exit 1
  fi
done

service=$(curl -fsS -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" http://supervisor/services/mqtt)
mqtt_host=$(printf '%s' "$service" | jq -r '.data.host')
mqtt_port=$(printf '%s' "$service" | jq -r '.data.port')
mqtt_user=$(printf '%s' "$service" | jq -r '.data.username')
mqtt_pass=$(printf '%s' "$service" | jq -r '.data.password')

require_cert=$(jq -r '.require_client_certificate' "$OPTIONS")
log_subs=$(jq -r '.log_subscriptions' "$OPTIONS")
acl_pattern=$(jq -r '.robot_acl_pattern // "prod/#"' "$OPTIONS")

{
  # The container is the boundary; staying root keeps the mapped key readable.
  printf '%s\n' \
    'user root' \
    'per_listener_settings false' \
    'persistence false' \
    'log_dest stdout' \
    'log_type error' \
    'log_type warning' \
    'log_type notice' \
    'log_type information' \
    'connection_messages true' \
    'log_timestamp_format %Y-%m-%dT%H:%M:%S'
  if [ "$log_subs" = "true" ]; then
    printf '%s\n' 'log_type subscribe' 'log_type unsubscribe'
  fi

  printf '\n%s\n' \
    'listener 8883' \
    "cafile $CERTS/ca.crt" \
    "certfile $CERTS/server.crt" \
    "keyfile $CERTS/server.key"
  if [ "$require_cert" = "true" ]; then
    printf '%s\n' \
      'require_certificate true' \
      'use_identity_as_username true' \
      'allow_anonymous false'
  else
    printf '%s\n' \
      'require_certificate false' \
      'allow_anonymous true' \
      "acl_file $ACL"
  fi

  printf '\n%s\n' \
    'connection ha' \
    "address ${mqtt_host}:${mqtt_port}" \
    "remote_username ${mqtt_user}" \
    "remote_password ${mqtt_pass}" \
    'remote_clientid whiskerless-broker-bridge' \
    'local_clientid whiskerless-broker-bridge-local' \
    'bridge_protocol_version mqttv311' \
    'cleansession true'
  jq -r '.bridge_topics[] | "topic " + .' "$OPTIONS"
} >"$CONF"

printf 'pattern readwrite %s\n' "$acl_pattern" >"$ACL"
chmod 0600 "$ACL"

if [ "$require_cert" = "true" ]; then
  cert_mode=required
else
  cert_mode=optional
fi
printf 'robot listener on 8883, client certificate %s; bridging to %s:%s\n' \
  "$cert_mode" "$mqtt_host" "$mqtt_port"

exec mosquitto -c "$CONF"
