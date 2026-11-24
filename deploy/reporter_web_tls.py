#!/usr/bin/python3 -I
"""Holds the certificate for the web interface and nothing else. Standard library only.

Takes HTTPS connections on port 8444 and passes the plain bytes on to the web interface
over a local socket, after one line with the visitor's address. It understands nothing of
what it passes on. So the program that does has neither a network nor the key, which also
protects the calendar drop box.

Started by reporter-web-tls.socket when something connects, and exits when idle.
"""

import asyncio
import ipaddress
import os
import socket
import ssl
import time
from collections import Counter
from pathlib import Path

MAX_CLIENTS, PER_ADDRESS = 32, 6
HANDSHAKE, LIFETIME = 8, 40  # seconds
MAX_UP, CHUNK = 65536, 16384
IDLE_EXIT = 90

CREDENTIALS = Path(os.environ.get("CREDENTIALS_DIRECTORY", "/nonexistent"))


async def pump(source: asyncio.StreamReader, target: asyncio.StreamWriter, limit: int = 0) -> None:
    total = 0
    while data := await source.read(CHUNK):
        total += len(data)
        if limit and total > limit:
            return
        target.write(data)
        await target.drain()


async def upward(source: asyncio.StreamReader, target: asyncio.StreamWriter) -> None:
    try:
        await pump(source, target, MAX_UP)
    except (OSError, RuntimeError):
        pass
    try:
        target.write_eof()  # always, or the pages wait for the rest
    except (OSError, RuntimeError):
        pass


def group(address: str) -> str:
    """One device can have any number of IPv6 addresses with the same first half."""
    ip = ipaddress.ip_address(address.split("%")[0])
    return str(ipaddress.ip_network((ip, 64), strict=False)) if ip.version == 6 else str(ip)


class Proxy:
    def __init__(self, listener: socket.socket, context: ssl.SSLContext, app: str) -> None:
        listener.setblocking(False)
        self.listener, self.context, self.app = listener, context, app
        self.clients: Counter = Counter()
        self.tasks: set = set()
        self.last_used = time.monotonic()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda loop, context: None)  # port scans, dropped connections
        idle = loop.create_task(self.until_idle())
        while True:
            accepting = loop.create_task(loop.sock_accept(self.listener))
            await asyncio.wait({accepting, idle}, return_when=asyncio.FIRST_COMPLETED)
            if not accepting.done():
                accepting.cancel()
                return
            try:
                connection, address = accepting.result()
            except OSError:  # too many open files
                await asyncio.sleep(0.5)
                continue
            self.last_used = time.monotonic()
            name = address[0].removeprefix("::ffff:")
            device = group(name)
            if len(self.tasks) >= MAX_CLIENTS or self.clients[device] >= PER_ADDRESS:
                connection.close()
                continue
            self.clients[device] += 1
            task = loop.create_task(self.serve(connection, name, device))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def until_idle(self) -> None:
        while self.tasks or time.monotonic() - self.last_used < IDLE_EXIT:
            await asyncio.sleep(5)

    async def serve(self, connection: socket.socket, name: str, device: str) -> None:
        opened = []
        try:
            async with asyncio.timeout(LIFETIME):
                await self.relay(connection, name, opened)
        except (OSError, ssl.SSLError, TimeoutError):
            pass
        finally:
            for transport in opened:
                transport.abort()
            connection.close()
            self.clients[device] -= 1
            if not self.clients[device]:
                del self.clients[device]
            self.last_used = time.monotonic()

    async def relay(self, connection: socket.socket, name: str, opened: list) -> None:
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=CHUNK)
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await loop.connect_accepted_socket(lambda: protocol, connection, ssl=self.context,
                                                          ssl_handshake_timeout=HANDSHAKE)
        opened.append(transport)
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        from_app, to_app = await asyncio.open_unix_connection(self.app, limit=CHUNK)
        opened.append(to_app.transport)
        to_app.write(f"{name}\n".encode())
        up = loop.create_task(upward(reader, to_app))
        try:
            await pump(from_app, writer)
        finally:
            up.cancel()
        writer.close()
        await writer.wait_closed()


def main() -> None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(CREDENTIALS / "cert.pem", CREDENTIALS / "key.pem")
    if os.environ.get("LISTEN_FDS"):
        listener = socket.socket(fileno=3)
    else:  # tests only
        listener = socket.create_server(("127.0.0.1", 0))
        print(listener.getsockname()[1], flush=True)
    asyncio.run(Proxy(listener, context, os.environ["WEB_SOCKET"]).run())


if __name__ == "__main__":
    main()
