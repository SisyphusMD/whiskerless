"""Read an HCI capture from either phone platform.

iOS produces Apple PacketLogger (``.pklg``) files; Android produces BTSnoop
(``btsnoop_hci.log``). :func:`records` sniffs the format and yields the same
``(seconds, type, payload)`` tuples for both — see :mod:`pklg` for the type codes.
"""
from __future__ import annotations

import pathlib

import btsnoop
import pklg


def records(path):
    with pathlib.Path(path).open("rb") as fh:
        magic = fh.read(len(btsnoop.MAGIC))
    if magic == btsnoop.MAGIC:
        return btsnoop.records(path)
    return pklg.records(path)
