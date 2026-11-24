"""Guided power test: the printer says what to nudge, prints stripes while the voltage is
sampled, then prints the result. Use plastic, never metal. See docs/hardware.md."""
import subprocess, sys, threading, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image, ImageDraw
from reporter import config, printer, render
STEPS = [('START', 'Hands off'), ('1', 'Press the CAPACITOR'), ('2', 'Nudge BLACK wires at jack'), ('3', 'Nudge RED wires at jack'),
         ('4', 'Wiggle the power PLUG'), ('5', 'Nudge RED jumper on Pi'), ('6', 'Nudge BLACK jumper on Pi'), ('END', 'Hands off')]
READY, ROWS = 6.0, 150
def low(): return int(subprocess.run(['vcgencmd', 'get_throttled'], capture_output=True, text=True).stdout.strip().split('=')[1], 16) & 1
samples, stop = [], threading.Event()
def sampler():
    while not stop.is_set():
        samples.append((time.monotonic(), low())); stop.wait(0.08)
def label(tag, text, small=''):
    c = render.Canvas(); c.y = 6
    c.text(0, c.y, tag, render.font('title', 34 if len(tag) < 3 else 24)); c.text(90, c.y + 6, text, render.font('bold', 20))
    c.y += 44
    if small: c.text(90, c.y - 12, small, render.font('semibold', 18)); c.y += 14
    return render.to_bitmap(c.finish())
def pattern():
    img = Image.new('1', (384, ROWS), 1); d = ImageDraw.Draw(img)
    for x in range(-ROWS, 384, 22): d.line([(x, 0), (x + ROWS, ROWS)], fill=0, width=9)   # slanted: no solid blocks to jam on
    return img
cfg = config.load(); results = []
threading.Thread(target=sampler, daemon=True).start()
with printer.ThermalPrinter(cfg.printer) as p:
    p.check_ready(); pat = pattern()
    p.print_image(label('TEST', 'Power check', 'Use plastic, not metal'), feed_lines=5); time.sleep(5)
    for tag, text in STEPS:
        p.print_image(label(tag, text, 'starting in %d seconds' % READY), feed_lines=5)   # feed: so it can be read
        time.sleep(READY)
        t0 = time.monotonic(); p.print_image(pat, feed_lines=0); p.status(timeout=6); t1 = time.monotonic()
        s = [v for t, v in samples if t0 + 0.5 <= t <= t1]; pct = 100 * sum(s) / max(1, len(s))
        verdict = 'OK' if pct == 0 else 'LOW %d%%' % round(pct)
        results.append((tag, text, sum(s), len(s))); print('%-6s %-28s low in %2d of %2d  -> %s' % (tag, text, sum(s), len(s), verdict), flush=True)
        p.print_image(label('=', verdict), feed_lines=1)
    p.feed(5)
stop.set()
