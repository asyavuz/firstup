"""Prints the Wi-Fi name, password and a QR code to join it.

`reporter wifi-setup` copies them from the Pi's own connection, which only root can read,
into a file only this account can read. The password is never logged and never in git.
"""

import getpass
import re
import subprocess
from pathlib import Path
from typing import List, NamedTuple, Optional

import segno
from PIL import Image
from segno import helpers

from . import private, render

PATH = private.FOLDER / "wifi.json"
QUIET = 4  # blank modules around the code, as the standard asks
HOW = "To print it, use the button or: .venv/bin/python -m reporter wifi"


class Wifi(NamedTuple):
    name: str
    password: str  # empty for an open network


def check(wifi: Wifi) -> None:
    if not 1 <= len(wifi.name.encode()) <= 32:
        raise ValueError("the name must be 1 to 32 characters")
    if wifi.password and not 8 <= len(wifi.password) <= 63:
        raise ValueError("the password must be 8 to 63 characters")


def load(path: Path = PATH) -> Optional[Wifi]:
    try:
        return Wifi(**private.read(path))
    except TypeError:  # nothing stored, or not what we stored
        return None


def save(wifi: Wifi, path: Path = PATH) -> None:
    check(wifi)
    private.write(path, wifi._asdict())


def _run(*command: str) -> str:
    return subprocess.run(command, stdout=subprocess.PIPE, text=True, check=True).stdout


def from_system() -> Optional[Wifi]:
    """This Pi's own Wi-Fi (asks for the sudo password), or None if it cannot be used."""
    try:
        connection = _run("nmcli", "-g", "GENERAL.CONNECTION", "device", "show", "wlan0").strip()
        fields = "802-11-wireless.ssid,802-11-wireless-security.psk"
        out = _run("sudo", "nmcli", "-s", "-e", "no", "-g", fields, "connection", "show", connection)
    except (OSError, subprocess.CalledProcessError):
        return None
    name, _, password = out.partition("\n")
    wifi = Wifi(name, password.rstrip("\n"))
    if re.fullmatch(r"[0-9a-fA-F]{64}", wifi.password):
        print("The Pi only has a scrambled form of the password, so please type it.")
        return None
    try:
        check(wifi)
    except ValueError:
        return None
    return wifi


def setup(other: bool = False) -> int:
    found = None if other else from_system()
    if found:
        save(found)
        print(f"Copied {found.name} from this Pi. {HOW}")
        return 0
    name = input("Wi-Fi name: ").strip()
    password = getpass.getpass("Password (hidden, empty if open): ")
    if password != getpass.getpass("Password again: "):
        print("They differ; nothing saved.")
        return 1
    try:
        save(Wifi(name, password))
    except ValueError as exc:
        print(f"Not saved: {exc}.")
        return 1
    print(f"Saved. {HOW}")
    return 0


def code(wifi: Wifi) -> segno.QRCode:
    return helpers.make_wifi(ssid=wifi.name, password=wifi.password or None,
                             security="WPA" if wifi.password else "nopass")


def _pieces(text: str, fnt, width: float) -> List[str]:
    """Break exactly as typed: a password's spaces matter, so no word wrapping."""
    parts = []
    while text:
        cut = max(1, render._prefix(text, fnt, width))
        parts.append(text[:cut])
        text = text[cut:]
    return parts


def page(wifi: Optional[Wifi]) -> Image.Image:
    if wifi is None:
        return render.to_bitmap(render.notice("Wi-Fi is not set up"))
    canvas = render.Canvas()
    canvas.heading("Join the Wi-Fi")
    matrix = [list(row) for row in code(wifi).matrix]
    scale = (render.WIDTH - 24) // (len(matrix) + 2 * QUIET)
    left = (render.WIDTH - scale * len(matrix)) // 2
    top = canvas.y + 2 * scale
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                canvas.draw.rectangle([left + x * scale, top + y * scale,
                                       left + (x + 1) * scale - 1, top + (y + 1) * scale - 1], fill=0)
    canvas.y = top + scale * (len(matrix) + QUIET)
    label, value = render.font("semibold", 20), render.font("bold", 28)
    for title, text in (("Network", wifi.name), ("Password", wifi.password or "none needed")):
        canvas.text(render.WIDTH / 2, canvas.y, title, label, "ma")
        canvas.y += render.line_height(label)
        for part in _pieces(text, value, render.RIGHT - render.PAD):
            canvas.text(render.WIDTH / 2, canvas.y, part, value, "ma")
            canvas.y += render.line_height(value)
        canvas.y += 8
    return render.to_bitmap(canvas.finish())
