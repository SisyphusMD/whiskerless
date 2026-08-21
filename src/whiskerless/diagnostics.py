"""Scrub identifying values out of shareable diagnostic text.

`--debug` output is the thing a person pastes into a bug report, so it is the one surface where
this project's identifiers reliably leave the machine. It used to carry them and *warn* about it,
which puts the work on the reader at exactly the moment they are least likely to do it.

What counts as identifying here is project-specific — robot serials, the network the robot joins,
the broker it authenticates to, the home directory path — so this is not a copy of
dreame-valetudo's `log.scrub()`. It is the same contract over a different set of values: text in,
shareable text out, no exceptions, and nothing that was already public is destroyed.
"""

from __future__ import annotations

import re
from pathlib import Path

#: The Litter-Robot 4 serial as it appears on the label and in every topic segment. Redacted
#: because it is the robot's identity to the broker, and because it appears in URLs and filenames
#: where a reader would not think to look for it.
#: Any LR3/LR4 model letter, not `LR4C` alone: provisioning accepts the whole shape, so a
#: future `LR4D…` was logged by the DEVICE_ID_SET step and survived a scrubber the CLI had
#: just promised redacts robot serials.
_SERIAL = re.compile(r"\bLR[34][A-Z][A-Za-z0-9]{4,}\b")
#: A WiFi SSID as this tool prints it, QUOTED — `ssid="HomeNet"`.
_SSID_QUOTED = re.compile(r"((?:SSID|ssid|network)\s*[=:]?\s*)(['\"])([^'\"]{1,64})\2")
#: The same, UNQUOTED — `ssid=HomeNet`, which is how most of this project's own output prints
#: it. The quoted pattern alone let the network name straight through, which is most of what a
#: person is trying not to publish when they redact a log at all.
# Runs to a DELIMITER, not to the first space: plenty of networks are called "My Home", and
# stopping at the space redacted "My" and published " Home".
_SSID_BARE = re.compile(r"((?:SSID|ssid|network)\s*[=:]\s*)([^,;'\"\n]{1,64}?)(?=\s*(?:[,;\n]|$))")
#: Any bare IPv4 literal. A broker address is a home network's shape.
_HOST = re.compile(r"\b(?:mqtts?://)?(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b")
#: An IPv6 literal, bracketed or bare. `_HOST` is IPv4-only and `_HOST_LABELLED` stops at the
#: first colon, so `host=2001:db8::1234` published everything after `2001` out of a log the tool
#: had just called redacted. Matched only in the two shapes that cannot be something else: a
#: compressed form (containing `::`) or the full eight groups. A three-group run is left alone
#: because that is what a timestamp looks like, and no valid IPv6 address has that shape.
_IPV6 = re.compile(
    r"\[[0-9A-Fa-f:.]{2,45}\](?::\d{1,5})?"
    r"|(?<![\w:.])(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}(?![\w:])"
    r"|(?<![\w:.])[0-9A-Fa-f:]*::[0-9A-Fa-f:]*(?![\w])"
)
#: A HOSTNAME, but only where it is labelled as one. Deliberately not a bare domain pattern: that
#: would redact `github.com` out of a URL in the same log and make the output less readable while
#: protecting nothing.
_HOST_LABELLED = re.compile(
    r"((?:host|hostname|broker|server)\s*[=:]\s*)(?:mqtts?://)?([A-Za-z0-9][A-Za-z0-9.\-]{0,252})"
)
#: A MAC address. The robot's hardware address identifies the device as durably as its serial and
#: is not something a person expects to be publishing when they paste a debug log.
_MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")
#: A certificate common name, which this project sets to the robot's serial.
_CN = re.compile(r"(\bCN\s*=\s*)([^,\s/]{1,64})")


def scrub(text: str, home: Path | None = None) -> str:
    """Redact identifying values from one line of diagnostic text.

    Never raises: a scrubber that can fail is a scrubber that gets bypassed at the worst moment.
    """
    if home is not None:
        rendered = str(home)
        if len(rendered) > 1:  # never blank out "/"
            text = text.replace(rendered, "~")
    text = _SERIAL.sub("<redacted-serial>", text)
    text = _SSID_QUOTED.sub(r"\1\2<redacted-network>\2", text)
    text = _SSID_BARE.sub(r"\1<redacted-network>", text)
    text = _MAC.sub("<redacted-mac>", text)
    text = _HOST.sub("<redacted-address>", text)
    # After _MAC, which would otherwise be eaten by the eight-group form, and before
    # _HOST_LABELLED, which stops at the first colon and would leave the rest of the address.
    text = _IPV6.sub("<redacted-address>", text)
    text = _HOST_LABELLED.sub(r"\1<redacted-address>", text)
    text = _CN.sub(r"\1<redacted-identity>", text)
    return text
