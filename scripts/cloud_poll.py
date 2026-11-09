"""Log Whisker's cloud view of a robot as JSON lines, one line per change.

The cloud decodes the robot's telemetry into named fields (``catDetect``,
``dfiLevelPercent``, ``displayCode``, …). Logged next to a capture of the robot's
MQTT traffic and merged with ``timeline.py``, those names label the raw values.
Useful while the cloud bridge keeps the robot visible to the cloud.

Credentials come from WHISKER_USERNAME / WHISKER_PASSWORD. Each line is
``{"t": ISO-8601 UTC, "changed": {"dotted.key": [old, new]}}``; the first holds the
whole flattened state as ``{"t": …, "full": {…}}``.

usage: WHISKER_USERNAME=… WHISKER_PASSWORD=… \\
       uv run --with pylitterbot python scripts/cloud_poll.py OUT.jsonl [SECONDS] [SERIAL]
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys
from pathlib import Path

from pylitterbot import Account

#: Bookkeeping fields that change on every poll and label nothing.
IGNORE = ("updatedAt", "state.lastSeen", "state.isOnlineUpdatedAt")


def flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}{k}."))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}{i}."))
    else:
        out[prefix[:-1]] = obj
    return out


def now():
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


async def main(fh, every, serial):
    account = Account()
    try:
        await account.connect(
            username=os.environ["WHISKER_USERNAME"],
            password=os.environ["WHISKER_PASSWORD"],
            load_robots=True,
        )
        robots = [r for r in account.robots if serial in (None, r.serial)]
        if len(robots) != 1:
            names = ", ".join(r.serial for r in account.robots)
            raise SystemExit(f"pick one robot by serial: {names}")
        robot, prev = robots[0], None
        while True:
            try:
                await robot.refresh()
            except Exception as exc:  # noqa: BLE001 - keep polling through transient errors
                fh.write(json.dumps({"t": now(), "error": repr(exc)}) + "\n")
                await asyncio.sleep(every)
                continue
            cur = {k: v for k, v in flatten(robot._data).items() if not k.startswith(IGNORE)}
            if prev is None:
                fh.write(json.dumps({"t": now(), "full": cur}, default=str) + "\n")
            else:
                changed = {
                    k: [prev.get(k), cur.get(k)]
                    for k in set(prev) | set(cur)
                    if prev.get(k) != cur.get(k)
                }
                if changed:
                    fh.write(json.dumps({"t": now(), "changed": changed}, default=str) + "\n")
            prev = cur
            await asyncio.sleep(every)
    finally:
        await account.disconnect()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(f"usage: {sys.argv[0]} <out.jsonl> [seconds] [serial]")
    with Path(sys.argv[1]).open("a", buffering=1) as out:
        asyncio.run(main(
            out,
            float(sys.argv[2]) if len(sys.argv) > 2 else 30.0,
            sys.argv[3] if len(sys.argv) > 3 else None,
        ))
