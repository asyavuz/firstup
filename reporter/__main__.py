"""First Up: draws and prints the daily receipt."""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# The timer runs this every five minutes, nearly always to do nothing. So the parts that
# draw, fetch and print are imported only by the commands that need them.
from . import config, lists, schedule

log = logging.getLogger("reporter")

EXIT_RETRY = 75  # EX_TEMPFAIL: systemd runs us again in a couple of minutes


class JournalFormatter(logging.Formatter):
    """Tells the journal how important a line is; the units drop what systemd says about
    starting and stopping every five minutes (LogLevelMax=notice)."""

    LEVELS = {logging.DEBUG: 7, logging.INFO: 5, logging.WARNING: 4, logging.ERROR: 3, logging.CRITICAL: 2}

    def format(self, record: logging.LogRecord) -> str:
        mark = f"<{self.LEVELS.get(record.levelno, 5)}>"
        return "\n".join(mark + line for line in super().format(record).splitlines())


def _print(cfg, image) -> int:
    from . import printer
    return 0 if printer.print_receipt(cfg.printer, image) else 1


def cmd_render(cfg, args) -> int:
    from . import report
    result = report.build(cfg, datetime.now(cfg.tz), on_screen=True, names=args.blocks or None, asked=args.blocks)
    result.image.save(args.output)
    log.info("wrote %s (%dx%d), failed blocks: %s", args.output, *result.image.size, result.failed or "none")
    return 0


def cmd_print(cfg, args) -> int:
    from . import report
    return _print(cfg, report.build(cfg, datetime.now(cfg.tz)).image)


def cmd_check(cfg, args) -> int:
    """Run by deploy/install.sh. The files could be read, or this would not run; does
    everything start, and does the web interface allow it all?"""
    from . import button, jobs, printer, report  # noqa: F401
    for problem in config.not_offered():
        print(f"!! not allowed: {problem}. Put it right in config.local.toml: something may not print, and the web interface, if installed, stays closed")
    for problem in cfg.problems:
        print(f"!! ignored, from the web interface: {problem}")
    print("settings read")
    return 0


def cmd_status(cfg, args) -> int:
    from . import printer
    with printer.ThermalPrinter(cfg.printer) as device:
        device.check_ready()
    print("printer ready, paper ok")
    return 0


def cmd_health(cfg, args) -> int:
    from . import health
    return _print(cfg, health.page(cfg, datetime.now(cfg.tz)))


def cmd_wifi(cfg, args) -> int:
    from . import wifi
    return _print(cfg, wifi.page(wifi.load()))


def cmd_wifi_setup(cfg, args) -> int:
    from . import wifi
    return wifi.setup(other=args.other)


def cmd_trains(cfg, args) -> int:
    from . import trains
    image = trains.build(cfg.trains, datetime.now(cfg.tz))
    if args.output:
        image.save(args.output)
        return 0
    return _print(cfg, image)


def cmd_poster(cfg, args) -> int:
    from . import poster
    return _print(cfg, poster.page(datetime.now(cfg.tz)))


def cmd_rail_setup(cfg, args) -> int:
    from . import trains
    return trains.setup(cfg.trains, datetime.now(cfg.tz))


def cmd_calibrate(cfg, args) -> int:
    from . import calibrate
    return 0 if calibrate.run(cfg.printer) else 1


def cmd_scheduled(cfg, args) -> int:
    stamp = config.state_dir() / "last-scheduled-print"

    def due() -> bool:
        decision = schedule.decide(datetime.now(cfg.tz), cfg.schedule, schedule.read_stamp(stamp))
        if not decision.run and sys.stderr.isatty():
            log.info("not printing: %s", decision.reason)
        return decision.run

    if lists.clear_old(cfg, datetime.now(cfg.tz).date()):
        log.info("deleted a list whose day is over")
    # First by whatever the clock says. If that is wrong, the next run puts it right.
    if not due():
        return 0
    if not schedule.wait_for_clock():
        log.error("clock is not synchronised, will retry")
        return EXIT_RETRY
    if not due():
        return 0
    from . import http, printer, report
    with printer.ThermalPrinter(cfg.printer) as device:
        device.check_ready()  # find out about empty paper before doing any work
    http.wait_for_network()   # prints what it can even if this times out
    if not due():  # that can take minutes, even past midnight
        return 0
    now = datetime.now(cfg.tz)
    result = report.build(cfg, now)
    # Marked before the paper moves: if the connection or the power fails halfway, the
    # retry must not start the receipt again. Not ready or out of paper still retries.
    printer.print_receipt(cfg.printer, result.image,
                          on_start=lambda: schedule.write_stamp(stamp, now.date()))
    log.info("daily report sent to printer, failed blocks: %s", result.failed or "none")
    return 0


def cmd_button(cfg, args) -> int:
    from . import button
    button.run(cfg)
    return 0


def cmd_requests(cfg, args) -> int:
    from . import jobs
    return jobs.run()


def main() -> int:
    parser = argparse.ArgumentParser(prog="reporter", description=__doc__)
    parser.add_argument("--config", type=Path, default=config.ROOT / "config.toml")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func, text in (
        ("render", cmd_render, "draw the receipt into a PNG, with an example calendar, no printing"),
        ("print", cmd_print, "print a receipt now"),
        ("status", cmd_status, "check the printer answers and has paper"),
        ("check", cmd_check, "check the settings files"),
        ("health", cmd_health, "print a page about the printer itself"),
        ("trains", cmd_trains, "print the next hour's trains"),
        ("poster", cmd_poster, "print the First Up poster"),
        ("rail-setup", cmd_rail_setup, "store the token for train times (kept private)"),
        ("wifi", cmd_wifi, "print the Wi-Fi name, password and QR code"),
        ("wifi-setup", cmd_wifi_setup, "copy this Pi's Wi-Fi details for printing (kept private)"),
        ("calibrate", cmd_calibrate, "print a strip of heat settings to choose from"),
        ("scheduled", cmd_scheduled, "print only if today's receipt is due (used by the timer)"),
        ("button", cmd_button, "watch the front-panel button"),
        ("requests", cmd_requests, "do what the web interface has asked for"),
    ):
        command = sub.add_parser(name, help=text)
        command.set_defaults(func=func)
        if name == "render":
            command.add_argument("blocks", nargs="*", help="only these, instead of the whole receipt")
            command.add_argument("-o", "--output", default="receipt.preview.png")
        if name == "trains":
            command.add_argument("-o", "--output", help="write a PNG instead of printing")
        if name == "wifi-setup":
            command.add_argument("--other", action="store_true", help="type in another network, such as a guest one")
    args = parser.parse_args()

    handler = logging.StreamHandler()  # journald adds timestamps itself
    formatter = JournalFormatter if os.environ.get("JOURNAL_STREAM") else logging.Formatter
    handler.setFormatter(formatter("%(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    logging.getLogger("urllib3").setLevel(logging.ERROR)  # its warnings hold whole addresses
    try:
        cfg = config.load(args.config)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        log.error("the settings cannot be used: %s", exc)
        if args.command == "scheduled":  # old lists must go all the same
            lists.clear_old(config.Config("UTC", (), ()), datetime.now().date())
        if args.command == "requests":
            from . import jobs
            jobs.refuse("The settings files have a mistake; the log says which")
        return 1
    try:
        return args.func(cfg, args)
    except Exception as exc:
        printer = sys.modules.get("reporter.printer")
        if printer is None or not isinstance(exc, printer.PrinterError):
            raise
        log.error("%s", exc)
        return EXIT_RETRY


if __name__ == "__main__":
    sys.exit(main())
