"""PyInstaller entry point — produces the standalone `whiskerless` binary.

Lets non-technical users run the BLE re-provisioner with no Python install:
download the binary for their OS and run `whiskerless provision`.
"""

from __future__ import annotations

import sys

from whiskerless.cli import main

if __name__ == "__main__":
    sys.exit(main())
