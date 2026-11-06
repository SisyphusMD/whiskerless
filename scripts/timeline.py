"""Merge a robot MQTT capture with a cloud-state log into one local-time timeline.

The MQTT capture is ``mosquitto_sub -F '%J'`` output (one JSON object per
message, with ``tst``); the cloud log is ``cloud_poll.py`` output. Lines read:

    HH:MM:SS C <elements>        command to the robot
    HH:MM:SS A <elements>        activity from the robot
    HH:MM:SS E <elements> {…}    event from the robot
    HH:MM:SS * field: old -> new cloud state change

usage: python scripts/timeline.py MQTT.jsonl CLOUD.jsonl
       (capture: mosquitto_sub -t 'prod/#' -F '%J' … >> MQTT.jsonl)
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

TAGS = {"command": "C", "activity": "A", "event": "E"}


def mqtt_rows(path):
    with Path(path).open() as fh:
        lines = fh.readlines()
    for line in lines:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        stamp = datetime.datetime.fromisoformat(message["tst"]).astimezone()
        leaf = message["topic"].rsplit("/", 1)[-1]
        payload = message.get("payload")
        if isinstance(payload, dict):
            data = " ".join(d if isinstance(d, str) else json.dumps(d) for d in payload.get("data", []))
            extra = {k: v for k, v in payload.items() if k not in ("timestamp", "serial", "data")}
            if extra.get("type") in ("activity", "query"):
                extra.pop("type")
            text = data + (f"  {json.dumps(extra)}" if extra else "")
        else:
            text = str(payload)
        yield stamp, f"{TAGS.get(leaf, leaf)} {text}"


def cloud_rows(path):
    with Path(path).open() as fh:
        lines = fh.readlines()
    for line in lines:
        entry = json.loads(line)
        if "changed" not in entry:
            continue
        stamp = datetime.datetime.fromisoformat(entry["t"]).astimezone()
        for key, (old, new) in sorted(entry["changed"].items()):
            yield stamp, f"* {key}: {old} -> {new}"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(f"usage: {sys.argv[0]} <mqtt.jsonl> <cloud.jsonl>")
    rows = sorted([*mqtt_rows(sys.argv[1]), *cloud_rows(sys.argv[2])], key=lambda r: r[0])
    for stamp, text in rows:
        print(stamp.strftime("%H:%M:%S"), text[:200])
