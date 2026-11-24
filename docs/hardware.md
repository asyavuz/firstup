# Hardware

Built with Adafruit's "Internet of Things Printer for Raspberry Pi"
([guide](https://learn.adafruit.com/pi-thermal-printer), no longer sold), a Raspberry Pi 3B+
and a CSN-A2 printer: TTL serial at 19200 baud, 384 dots wide, 5 to 9 V. Pi and printer share
one 5 V 4 A supply, so here it is **5 V and never more**: it also goes straight into the Pi.

Unplug everything before touching a wire. Pin 1 is at the SD card's end, in the inner row; odd
pins are in that row, even ones opposite, along the edge. The supply's plug must be
centre-positive.

| Pi pin | Wire |
|---|---|
| 2 (5 V) | red, from the power jack |
| 20 (ground) | black, from the power jack |
| 6 (ground) | printer data, black |
| 8 (GPIO14, sends) | printer data, yellow (RX) |
| 10 (GPIO15, receives) | printer data, green (TX) |
| 12 (GPIO18) | button LED + |
| 14 (ground) | button common and LED − |
| 16 (GPIO23) | button switch (normally open) |

The printer's thick red and black wires go to the jack, not to the Pi. Connect nothing to the
Pi's own power socket (micro-USB, USB-C on a 4) while pin 2 is in use. Colours differ between makers: go by the labels.
The CSN-A2 speaks 3.3 V; check that yours does, or the Pi's pin 10 can be damaged. Another
button's LED may need a resistor. The button and LED pins can be changed in
`config.local.toml`.

## Power

Printing takes a lot of current for a short time. Put a capacitor of 4700 µF, 10 V or
more, across the jack: the side with the stripe, or the short leg, to **black**. Backwards it can burst.

`vcgencmd get_throttled` on the Pi should say `throttled=0x0`, also while printing
(`0x50000` means it happened since the Pi started: restart it and look again). If it does not,
suspect the joints at the jack, the capacitor's joints, and the jumpers on pins 2 and 20, in
that order: pressed-on wires work loose. A guided test (three minutes, half a metre of paper)
has the printer say which wire to nudge, measures while you do, and prints OK or LOW. Use
plastic, never metal.

    cd ~/reporter && .venv/bin/python deploy/power_check.py

Without soldering: a barrel jack with screw terminals. Or power the Pi from its own USB
supply after taking the **red** wire off pin 2 (leave the black ones; never both at once).

## Serial port

The printer must be on the full UART: `/dev/serial0` pointing to `ttyAMA0`, with
`dtoverlay=disable-bt`, which switches Bluetooth off. Provisioning does this. On the Pi's
smaller serial port the speed follows the processor's, which drops when it is hot or short of
power. Measured here under load: 0 of 14 replies, against 377 of 377 after the change.

## Print quality

- `heat_time` is the one to change: 45 to 85 in steps of 5. Contrast rises from 45 to 75.
  Here 90 smudged, and 110 and above squashed the print to about half its length, which is
  why more than 85 is not offered. Why it squashes is not known: the printer's own self-test
  is hotter and perfect. Low voltage and the speed of sending were both ruled out.
- Rows are sent without waiting for each to be printed. Waiting takes 50 ms instead of the
  27 ms a row needs, stops the motor every time and ghosts the text.
- Thin strokes print pale: nothing lighter than semibold, nothing below 18 px, and text stays
  clear of the last 12 dots on the right.
- The printer's reply only says whether there is paper. It answers normally after dropping
  half a page.
- Self-test, without the Pi: hold the printer's feed button while connecting power. It shows
  the baud rate and the voltage it sees.
