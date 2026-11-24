"""Starts the web interface. Installed next to it, in a folder only root can change."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reporter_web.server import main  # noqa: E402

main()
