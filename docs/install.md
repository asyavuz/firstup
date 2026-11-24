# Installing First Up

From bare parts to the first receipt: an evening to wire it, half an hour to install it.
Sections 1 to 6 give you a daily receipt and a working button. Everything in section 7 is
optional.

The examples use `user@printer.local` for the Pi, `192.168.1.50` for its address and
`printer.example.com` for its name. Put your own in their place.

## 1. Parts

| Part | Notes |
|---|---|
| Raspberry Pi | Built and tested on a 3B+. A 3, 4 or Zero 2 W should do. Not the first Zero W (it cannot run the 64-bit system) and not a 5 (its serial port is elsewhere). |
| SD card | 8 GB or more |
| Thermal printer, 58 mm | With a **TTL serial** port, 3.3 V: search for *CSN-A2* or *58 mm TTL thermal printer*. Not one with only USB or RS-232. |
| Power supply, 5 V 4 A | For the printer and the Pi together, with a capacitor of 4700 µF, 10 V or more, across it. Never a 9 or 12 V supply. |
| Push button with an LED | Optional, but the handiest part of it |
| Thermal paper, 58 mm wide | A roll small enough for the printer |

Adafruit no longer sells its printers or its kit with all of these but the Pi, the
[Internet of Things Printer](https://learn.adafruit.com/pi-thermal-printer). Its guide is
still the best description of the case and the assembly.

## 2. Wiring

Follow the table in [hardware.md](hardware.md). Then, before connecting the Pi, let the
printer test itself: hold its feed button while connecting the power. It should print crisply
and show `Baudrate 19200` (if it says 9600, see section 4).

## 3. SD card

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/) and choose your Pi,
   then *Raspberry Pi OS (other) > Raspberry Pi OS Lite (64-bit)*, then your card. Check
   twice that it is the right card: everything on it goes.
2. Under customisation: a hostname (`printer`), your time zone, a user name **with a
   password** (installing asks for it), your Wi-Fi, and SSH **on, with your public key**. If
   you have no key yet: `ssh-keygen -t ed25519` (press Enter at each question), then paste
   the line that `cat ~/.ssh/id_ed25519.pub` shows.
3. Put the card in and start the Pi **with the printer's lid open**: a fresh system can send
   its startup text to the printer. Give it five minutes.
4. Try it: `ssh user@printer.local` (the first time, type `yes`), then `exit`.

## 4. Your settings

On your computer (a Mac or Linux, with git and rsync):

    git clone https://github.com/asyavuz/firstup.git first-up
    cd first-up
    echo user@printer.local > .printer

`.printer` says where to install. Your own values go in `config.local.toml`, which is laid
over `config.toml`. Git ignores both, so nothing about your home ends up in it. For example:

    timezone = "Europe/London"
    # The blocks, in order. Here without the Underground.
    sections = ["header", "warnings", "weather", "pollen", "events", "reminders", "ahead",
                "trains", "news", "history", "quote", "closing"]

    [weather]
    place = "Leeds"          # a label only
    latitude = 53.80         # a place nearby will do, to two decimals
    longitude = -1.55

    [warnings]
    region = "yh"            # Yorkshire & Humber

    [trains]
    station = "LDS"          # three-letter code

    [printer]
    baudrate = 19200         # or 9600, if the self-test says so: slower, and text may ghost

Leave out whatever you do not want to change. `config.toml` lists what there is, with
explanations. Outside Britain, take `warnings`, `ahead` (English bank holidays, but also
clock changes), `trains`, `tube`, `weekend` and, outside Europe, `pollen` out of `sections`,
and `departures` out of `taps`. Lines such as `timezone` and `sections` must come before
the first `[...]`.

| Where | What it is for | Order |
|---|---|---|
| `config.toml` | the originals, the same for everybody | 1, weakest |
| `config.local.toml` | your home | 2 |
| web interface, if installed | everyday choices, kept on the Pi | 3, wins |

A list (`sections`, `[[schedule]]`, `[[news.feeds]]`, `taps`, `holds`) replaces the one
before it, so give all of it. Once a group, say the weather, is saved in the web interface,
what that page offers is taken from there until you choose *Go back to the original*; the rest
(`baudrate`, pins, `minutes`) still comes from the files. A deploy names mistakes: one that
cannot be read, or a misspelt setting, stops it; a value the web interface would refuse gives
a line with `!!`; the rest (`baudrate`, pins) is not checked.

Fonts: receipts use Nunito, which is included. If you have a licence to use Apple's SF
fonts, put the four files named in `reporter/render.py` into `assets/fonts/` and they are
used instead; they may not be passed on, so git ignores that folder.

## 5. Install

    ./deploy.sh --provision

It asks for the Pi's password, perhaps more than once, so stay near. It takes 10 to 20
minutes and restarts the Pi: "all done" and a closed connection at the end are right; wait two
minutes. It is safe to run again. It does this:

- installs updates, and has the system's security updates install themselves from then on
  (the few Python packages are pinned and change only with a deploy)
- gives the printer the Pi's full serial port, and nothing else (Bluetooth goes off)
- sets the time zone from your settings, limits the log to 100 MB and a month, and turns off
  Wi-Fi power saving
- allows SSH **with keys only**, if a key is installed, and **from private addresses only**
  (10.x, 172.16 to 31.x, 192.168.x and their IPv6 equivalents; not from a VPN that uses
  others), closes all else with a firewall, and blocks repeated wrong logins (fail2ban)
- allows this account two commands without a password: shutting down and restarting the
  button service (systems older than Raspberry Pi OS 6.2 allow every command; newer ask)
- installs the program, its timer and the button service

## 6. The first receipt

Close the lid. Then, on the Pi (`ssh user@printer.local`):

    cd reporter
    .venv/bin/python -m reporter status      # "printer ready, paper ok"
    .venv/bin/python -m reporter print

Tap the button once: it should print again. If the print is pale or smudged, print a strip
of heats with `.venv/bin/python -m reporter calibrate`. Put the best number under `[printer]`
as `heat_time` in `config.local.toml` on your computer and run `./deploy.sh` (or choose it in
the web interface, under Heat).

The daily receipt comes at 08:00 on weekdays and 10:00 at weekends. Change `[[schedule]]` in
`config.local.toml`, or use the web interface.

At first the button does this, which can also be changed in either place:

| Press | Prints |
|---|---|
| 1 tap | the receipt |
| 2 taps | Wi-Fi details ("not set up" until section 7) |
| 3 taps | train times for the next hour ("not set up" until section 7) |
| 5 taps | the First Up poster |
| hold 2 seconds | printer health |
| hold 5 seconds | shuts the Pi down safely (fixed). To start it again, unplug it and plug it in. |

## 7. Extras, in this order

**Wi-Fi details.** Copies the Pi's own Wi-Fi name and password, or any other network's with
`--other`, into `~/.config/reporter/wifi.json`, which only this account can read:

    ssh -t user@printer.local 'cd reporter && .venv/bin/python -m reporter wifi-setup'

**Train times.** Realtime Trains is free for personal use. Sign in at
[api-portal.rtt.io](https://api-portal.rtt.io/), request a token, then give it to

    ssh -t user@printer.local 'cd reporter && .venv/bin/python -m reporter rail-setup'

It tries the token before keeping it, in `~/.config/reporter/rail.json`. With the web
interface, it can also be entered under *Keys*. "–" instead of a
time means there is no live information about that train yet.

**Calendar and reminders** from an iPhone: [calendar.md](calendar.md). Needs a domain name.

**Web interface:** [web.md](web.md). Needs the certificate made for the calendar.

## Everyday

On the Pi, in `~/reporter`:

    .venv/bin/python -m reporter check       # are the settings in order?
    .venv/bin/python -m reporter render      # draws receipt.preview.png, with an example calendar
    .venv/bin/python -m reporter print       # prints now
    .venv/bin/python -m reporter --help      # everything else
    systemctl list-timers reporter.timer     # next check
    journalctl -u reporter                   # what happened and why
    journalctl -u reporter-button            # the same for the button

On your computer, after changing a file or pulling a newer version:

    ./deploy.sh          # or ./deploy.sh --web, if the web interface is installed

Change files only on your computer: a deploy overwrites the Pi's. To go back to an older
version: `git checkout <version>`, then deploy.

To stop it:

    sudo systemctl disable --now reporter.timer reporter-button.service
    sudo systemctl disable --now receipt-inbox.socket      # if the calendar is set up
    rm -f /var/lib/receipt-inbox/drop/*.txt                # the last lists

Without the last two the phone could still leave lists, which nothing would delete. To start
it again, the same with `enable`; a deploy starts the button again, and perhaps the timer. While you are
away, unticking every day in the web interface is simpler.

## When something is wrong

| What you see | What to do |
|---|---|
| `printer does not answer` | Power and the three data wires; `ls -l /dev/serial0` must point to `ttyAMA0`; the baud rate |
| `printer is out of paper` | Paper in, lid shut |
| Garbled characters | The serial port ([hardware.md](hardware.md)) or the baud rate |
| Pale, smudged or squashed | Heat, then power ([hardware.md](hardware.md)) |
| Nothing at eight | `journalctl -u reporter --since today`; `.venv/bin/python -m reporter check` |
| "... unavailable" on paper | That source was down or has changed: the log says why |
| The button does nothing | `systemctl status reporter-button`; the wires on pins 14 and 16 |
| Locked out of SSH | With a screen and keyboard on the Pi, sign in with the password: `sudo rm /etc/ssh/sshd_config.d/10-hardening.conf && sudo systemctl reload ssh && sudo ufw disable`. Put your key in, then provision again |
| The web interface's password is forgotten | [web.md](web.md), *Setting it up*: one command on your computer |
| Cannot reach `printer.local` | Use the address (`ssh user@192.168.1.50`), from the router's list of devices |
