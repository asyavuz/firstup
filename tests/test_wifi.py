import stat

import pytest

from reporter import render, wifi


def test_saved_privately_and_read_back(tmp_path):
    path = tmp_path / "sub" / "wifi.json"
    assert wifi.load(path) is None
    saved = wifi.Wifi("Café Zoë", 'p;a:s,s\\w"ord  two spaces')
    wifi.save(saved, path)
    assert wifi.load(path) == saved
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    path.write_text("rubbish")
    assert wifi.load(path) is None


@pytest.mark.parametrize("bad", [wifi.Wifi("", "longenough"), wifi.Wifi("x" * 33, "longenough"), wifi.Wifi("x", "short"), wifi.Wifi("x", "y" * 64)])
def test_impossible_details_are_refused(bad, tmp_path):
    with pytest.raises(ValueError):
        wifi.save(bad, tmp_path / "w.json")


@pytest.mark.parametrize("details", [wifi.Wifi("Home", "correct horse"), wifi.Wifi("N" * 32, "p" * 63), wifi.Wifi("Open", ""), None])
def test_page_fits_the_paper(details):
    img = wifi.page(details)
    assert img.mode == "1" and img.width == render.WIDTH and img.height < 900
    if details:
        size = len(list(wifi.code(details).matrix))
        assert (render.WIDTH - 24) // (size + 8) >= 4  # dots per square: fewer would not scan


def test_password_is_split_without_changing_it():
    fnt = render.font("bold", 28)
    text = "  two  spaces " + "W" * 60
    parts = wifi._pieces(text, fnt, 360)
    assert "".join(parts) == text and all(fnt.getlength(p) <= 360 for p in parts)


@pytest.mark.parametrize("out, expected", [
    ("Home\nsecret: with\\ odd\n", wifi.Wifi("Home", "secret: with\\ odd")),
    ("Open\n", wifi.Wifi("Open", "")),
    ("Home\n" + "a1" * 32 + "\n", None),          # Imager's scrambled form
    ("\n\n", None),
])
def test_details_from_the_pi_itself(monkeypatch, out, expected):
    monkeypatch.setattr(wifi, "_run", lambda *c: out if c[0] == "sudo" else "netplan-wlan0-Home\n")
    assert wifi.from_system() == expected


def test_setup_falls_back_to_typing(monkeypatch, tmp_path):
    monkeypatch.setattr(wifi, "save", lambda w: saved.append(w))
    monkeypatch.setattr(wifi, "from_system", lambda: None)
    monkeypatch.setattr("builtins.input", lambda p: " Guest ")
    monkeypatch.setattr(wifi.getpass, "getpass", lambda p: "longenough")
    saved = []
    assert wifi.setup() == 0 and saved == [wifi.Wifi("Guest", "longenough")]
