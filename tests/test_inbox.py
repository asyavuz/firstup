import hashlib
import importlib.util
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
from datetime import date, timedelta
from http.client import HTTPSConnection

import pytest

from reporter import config
from reporter.sections import events

SCRIPT = config.ROOT / "deploy/receipt_inbox.py"
TOKEN = "correct-horse-battery-staple-0123456789"
spec = importlib.util.spec_from_file_location("receipt_inbox", SCRIPT)
inbox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inbox)
TODAY = date(2026, 11, 24)


def body(text):
    return json.dumps({"list": text}).encode()


def test_accepts_today_and_tomorrow():
    assert inbox.accept(body("2026-11-24\n09:00 X"), TODAY) == "2026-11-24\n09:00 X\n"
    assert inbox.accept(body("2026-11-25"), TODAY) == "2026-11-25\n"


@pytest.mark.parametrize("raw", [
    b"", b"not json", b"[]", b'"x"', b"{}", b'{"list": 5}', b'{"list": null}', b"[" * 8000, b"\xff\xfe",
    body(""), body("no date"), body("2026-11-23\nyesterday"), body("2026-12-24\ntoo far"), body("2026-11-24\x00"),
])
def test_refuses_everything_else(raw):
    with pytest.raises(inbox.Rejected):
        inbox.accept(raw, TODAY)


@pytest.mark.parametrize("text, said", [
    ("2026-11-24", "Stored no events for Tuesday 24 November"),
    ("2026-11-24\n09:00 X\n\n", "Stored 1 event for Tuesday 24 November"),
    ("2026-11-25\n09:00 X\nAll day Y", "Stored 2 events for Wednesday 25 November"),
])
def test_summary_counts_but_never_quotes(text, said):
    assert inbox.summary(text) == said


@pytest.mark.parametrize("header, ok", [
    (f"Bearer {TOKEN}", True), (f"bearer {TOKEN}", True), (None, False), ("", False), ("Bearer ", False),
    (TOKEN, False), (f"Basic {TOKEN}", False), (f"Bearer {TOKEN}x", False),
])
def test_authorised(header, ok):
    assert inbox.authorised(header, hashlib.sha256(TOKEN.encode()).hexdigest()) is ok


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = tmp_path_factory.mktemp("inbox")
    cred, drop = root / "cred", root / "drop"
    cred.mkdir(), drop.mkdir()
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=localhost",
                    "-keyout", str(cred / "key.pem"), "-out", str(cred / "cert.pem")], check=True, capture_output=True)
    (cred / "token.sha256").write_text(hashlib.sha256(TOKEN.encode()).hexdigest() + "\n")
    env = {"PATH": os.environ["PATH"], "CREDENTIALS_DIRECTORY": str(cred), "INBOX_DROP": str(drop)}
    proc = subprocess.Popen([sys.executable, str(SCRIPT)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    port = int(proc.stdout.readline())
    yield port, drop, proc
    proc.kill()


def call(port, method="POST", path="/calendar", token=TOKEN, data=b"", headers=None):
    context = ssl._create_unverified_context()
    conn = HTTPSConnection("127.0.0.1", port, timeout=15, context=context)
    head = dict(headers or {})
    if token:
        head["Authorization"] = f"Bearer {token}"
    conn.request(method, path, body=data, headers=head)
    reply = conn.getresponse()
    return reply.status, reply.read()


def test_stores_and_the_receipt_reads_it(server):
    port, drop, _ = server
    text = f"{date.today()}\n09:30-10:00 Dentist\nAll day Café à Noël"
    assert call(port, data=body(text)) == (200, f"Stored 2 events for {date.today():%A} {date.today().day} {date.today():%B}".encode())
    assert [p.name for p in drop.iterdir()] == ["events.txt"]
    got = events.parse((drop / "events.txt").read_text(), date.today())
    assert [(e.when, e.title) for e in got] == [("All day", "Café à Noël"), ("09:30–10:00", "Dentist")]


def test_reminders_go_beside_the_calendar(server):
    port, drop, _ = server
    text = f"{date.today()}\nPut the bins out\nCall the dentist"
    said = f"Stored 2 reminders for {date.today():%A} {date.today().day} {date.today():%B}"
    before = (drop / "events.txt").read_text() if (drop / "events.txt").exists() else None
    assert call(port, path="/reminders", data=body(text)) == (200, said.encode())
    assert (drop / "reminders.txt").read_text() == text + "\n"
    assert ((drop / "events.txt").read_text() if (drop / "events.txt").exists() else None) == before
    assert call(port, path="/reminders", token="wrong", data=body(text))[0] == 401
    (drop / "reminders.txt").unlink()


@pytest.mark.parametrize("kwargs, status", [
    ({"token": "wrong"}, 401), ({"token": None}, 401), ({"path": "/"}, 404), ({"path": "/calendar?x=1"}, 404),
    ({"path": "/../etc/passwd"}, 404), ({"method": "GET"}, 405), ({"method": "PUT"}, 405), ({"method": "DELETE"}, 405),
    ({"data": b"x" * 9000}, 413), ({"data": body("nonsense")}, 400),
])
def test_refusals_echo_nothing_and_change_nothing(server, kwargs, status):
    port, drop, _ = server
    before = sorted((p.name, p.read_text()) for p in drop.iterdir())
    kwargs.setdefault("data", body(f"{date.today() + timedelta(days=1)}\n10:00 Should not be stored"))
    got, reply = call(port, **kwargs)
    assert got == status and reply.startswith(b"Refused") and b"Should not" not in reply
    assert sorted((p.name, p.read_text()) for p in drop.iterdir()) == before


def test_plain_http_garbage_and_idle_clients_do_not_break_it(server):
    port, _, proc = server
    for payload in (b"GET / HTTP/1.0\r\n\r\n", b"\x00" * 500, b""):
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            raw.sendall(payload)
    time.sleep(0.5)  # let those be dropped: only four are served at a time
    idle = [socket.create_connection(("127.0.0.1", port), timeout=5) for _ in range(3)]  # below the limit
    assert call(port, data=body(f"{date.today()}\n"))[0] == 200
    for raw in idle:
        raw.close()
    assert proc.poll() is None


def test_a_token_made_in_the_web_interface_counts_instead_of_the_first(tmp_path, monkeypatch):
    newer, first, other = tmp_path / "token.sha256", "a" * 64, hashlib.sha256(b"other").hexdigest()
    monkeypatch.setattr(inbox, "NEWER", newer)
    assert inbox.token_hash(first) == first
    newer.write_text(other + "\n")
    assert inbox.token_hash(first) == other and inbox.authorised("Bearer other", inbox.token_hash(first))
    for damaged in ("", "x", "A" * 64, other + "0"):
        newer.write_text(damaged)
        assert inbox.token_hash(first) == "" and not inbox.authorised("Bearer ", inbox.token_hash(first))
    newer.unlink()
    newer.symlink_to("/etc/hosts")
    assert inbox.token_hash(first) == ""


def test_slow_devices_cannot_keep_others_out(tmp_path, server):
    """In-process, to choose the limits: the rest is the same program."""
    _, drop, _ = server
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(drop.parent / "cred/cert.pem", drop.parent / "cred/key.pem")
    inbox.PER_ADDRESS, inbox.LIFETIME, before = 3, 1, (inbox.PER_ADDRESS, inbox.LIFETIME)
    listener = socket.create_server(("127.0.0.1", 0))
    served = inbox.Server(listener, context, "0" * 64)
    threading.Thread(target=served.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
    try:
        slow = [socket.create_connection(listener.getsockname()[:2], timeout=5) for _ in range(5)]
        time.sleep(0.4)
        assert len(served.clients) == 3  # one device has only so many
        for _ in range(8):  # a byte now and then does not buy more time
            time.sleep(0.2)
            for each in slow:
                try:
                    each.sendall(b"\x16")
                except OSError:
                    pass
        time.sleep(0.5)
        assert served.clients == {}
    finally:
        inbox.PER_ADDRESS, inbox.LIFETIME = before
        served.shutdown()


@pytest.mark.parametrize("one, other, same", [("192.168.1.5", "::ffff:192.168.1.5", True), ("192.168.1.5", "192.168.1.6", False),
                                              ("fe80::1%eth0", "fe80::2%eth0", True), ("2001:db8:1:2::1", "2001:db8:1:3::1", False)])
def test_devices_are_told_apart(one, other, same):
    assert (inbox.group(one) == inbox.group(other)) is same


def test_old_tls_is_refused(server):
    context = ssl._create_unverified_context()
    context.maximum_version = ssl.TLSVersion.TLSv1_1
    with pytest.raises((ssl.SSLError, OSError)):
        with socket.create_connection(("127.0.0.1", server[0]), timeout=5) as raw:
            context.wrap_socket(raw)


def test_unit_stays_locked_down():
    unit = (config.ROOT / "deploy/receipt-inbox.service").read_text()
    for line in ("User=receipt-inbox", "ProtectSystem=strict", "ProtectHome=yes", "NoNewPrivileges=yes",
                 "CapabilityBoundingSet=\n", "IPAddressDeny=any", "InaccessiblePaths=/tmp /var/tmp", "LimitFSIZE=", "ReadWritePaths=/var/lib/receipt-inbox/drop"):
        assert line in unit
    for port, name in ((8443, "receipt-inbox"), (8444, "reporter-web-tls")):  # a service's list does not count for a socket it is handed
        unit = (config.ROOT / f"deploy/{name}.socket").read_text()
        assert f"ListenStream={port}\n" in unit and "IPAddressDeny=any\n" in unit


@pytest.mark.parametrize("host", ["", "localhost", "bad host.com", "a.com;reboot", "$(id).com", "-x.com", "UPPER.com"])
def test_setup_refuses_odd_hostnames(host):
    out = subprocess.run(["bash", str(config.ROOT / "deploy/setup-calendar.sh"), host], capture_output=True, text=True, timeout=20)
    assert out.returncode != 0 and "== certificate" not in out.stdout
