"""The pages. No scripts and nothing from outside: forms, links, one style sheet and the
drawings in art.py. What reacts at once does so in style.css."""

import time
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from reporter import settings, stations

from . import art, forms, sun
from .art import icon
from .auth import MIN_LENGTH
from .markup import Html, flag, h, join, options
from .store import PAPER, Result, Store

NAME = "First Up"
NAV = (("/", "Today", "today"), ("/receipt", "Receipt", "receipt"), ("/times", "Times", "times"),
       ("/content", "Content", "content"), ("/button", "Button", "button"), ("/printer", "Heat", "heat"))
REFRESH = 8  # seconds, only on Today and only while something is under way: forms would be lost
PRINTS = (("receipt", "Print the receipt", "print"), ("trains", "Print train times", "trains"), ("health", "Print printer health", "health"))
DONE = {"receipt": "Receipt", "trains": "Train times", "health": "Printer health", "calibrate": "Heat strip"}
SIGNS = {"Address": "address", "Wi-Fi": "wifi", "Power": "power", "Temperature": "temperature", "Running for": "uptime",
         "Storage": "storage", "Services": "services", "Last daily print": "receipt", "Calendar": "events",
         "Certificate": "certificate", "Web settings": "settings", "Reminders": "reminders"}
FIRST_SIGNS = ("Services", "Power", "Wi-Fi", "Calendar")
TROUBLE = ("failed", "LOW", "RENEW", "cannot tell", "ignored", "not connected", "dips", "no list")
DAYS = dict(zip(settings.DAYS, ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"), strict=True))
# Which settings are on which page; a form names those it holds.
GROUPS = {"sections": "/receipt", "schedule": "/times", "weather": "/content", "warnings": "/content", "pollen": "/content", "tube": "/content",
          "news": "/content", "trains": "/content", "sudoku": "/content", "button": "/button", "printer": "/printer"}
DROP = "printer.example.com:8443"  # where the phone sends to; set by the server
STILL = ("/password", "/phone")  # what can be shown even before the printer program has reported
VERSION = ""  # set by the server, so that browsers notice a new style sheet

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
{refresh}<title>{title}</title><link rel="stylesheet" href="/style.css?{v}"><link rel="icon" href="/icon.svg?{v}" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png?{v}"><link rel="manifest" href="/manifest.webmanifest"><meta name="theme-color" content="#1f5269"></head>
<body class="{kind}">{body}</body></html>"""


def now() -> datetime:
    return datetime.now().astimezone()


def document(title: str, body: Html, kind: str, refresh: bool = False) -> Html:
    again = h('<meta http-equiv="refresh" content="{s};url=/">', s=REFRESH) if refresh else Html("")
    return h(PAGE, title=f"{title}, {NAME}", body=body, kind=kind, refresh=again, v=VERSION)


def block_rules() -> str:
    """Style that fades a coach when its block is switched off; made here so that a new block
    needs nothing in style.css."""
    return ",".join(f"body:has(#on-{name}:not(:checked)) .car-{name}" for name in settings.SECTIONS) + "{opacity:.18}" + \
        ",".join(f"body:has(#on-{name}:not(:checked)) .strip-{name}" for name in settings.SECTIONS) + "{display:none}"


def line_class(name: str) -> str:
    return "line-" + "".join(c for c in name.lower() if c.isascii() and c.isalpha()) if name in settings.LINES else "line-none"


def _kind(current: Dict[str, Any], extra: str = "") -> str:
    place = current.get("weather") or {"latitude": 51.5085, "longitude": -0.1257}
    favourite = (current.get("tube") or {}).get("favourite") or ""
    return f"{line_class(favourite)} sky-{sun.sky(now(), place['latitude'], place['longitude'])} {extra}".strip()


def _note(note: Optional[tuple], extra: str = "") -> Html:
    """What to say about what was just done: ("good" or "bad", text)."""
    return h('<p class="flash {kind} {extra}" role="{role}">{i}<span>{text}</span></p>', kind=note[0], extra=extra, text=note[1], i=icon("services" if note[0] == "bad" else "check"),
             role="alert" if note[0] == "bad" else "status") if note else Html("")


LOCKED = "Too many tries. Wait two minutes."


def login(note: str = "", back: str = "/") -> Html:
    """Shows nothing of the settings: anybody at home can open it."""
    body = h("""<header class="poster hero">{scene}<h1>First<br>Up</h1></header><main class="booking">
<form class="ticket" method="post" action="/login">{note}<input type="text" name="user" value="printer" autocomplete="username" hidden><input type="hidden" name="back" value="{back}">
<label for="password">Password</label>
<input type="password" id="password" name="password" autocomplete="current-password" required autofocus maxlength="200">
<button class="go">{key}Sign in</button>
<details><summary>Forgotten it?</summary><p>On your computer, in a terminal, with your own names for “user” and “printer.local”:</p><p><code>ssh -t user@printer.local 'bash reporter/deploy/setup-web.sh --new-password'</code></p>
<p>It asks for the Pi's own password. Settings and tokens stay as they are.</p></details></form></main>""", scene=art.today(), note=_note(("bad", note)) if note else Html(""), key=icon("key"), back=back)
    return document("Sign in", body, _kind({}, "signing-in"))


def when(moment: Optional[datetime]) -> str:
    return f"{moment:%a} {moment.day} {moment:%b}, {moment:%H:%M}" if moment else ""


def next_due(slots: Iterable[dict], last: str, moment: datetime) -> Optional[datetime]:
    """When the next receipt is due by these settings; `last` is the day of the last one. Worked
    out here, so that it is right as soon as something is saved."""
    for ahead in range(8):
        day = moment.date() + timedelta(days=ahead)
        slot = next((s for s in slots if settings.DAYS[day.weekday()] in s["days"]), None)
        if slot is None or str(day) == last:
            continue
        start, end = (datetime.combine(day, datetime.strptime(slot[key], "%H:%M").time()).astimezone() for key in ("time", "catch_up_until"))
        if ahead or moment <= end:
            return max(start, moment)
    return None


class View:
    """One request for one page: what there is, what to say, and what was typed if something
    was refused."""

    def __init__(self, store: Store, session, path: str) -> None:
        self.store, self.session, self.path = store, session, path
        self.current, self.busy, self.status = store.current(), store.busy(), store.status()
        self.refresh = path == "/" and bool(self.busy)
        self.notes, kept = dict(session.notes), session.draft
        self.said = [text for _, text in self.notes.values()]  # goes first in the title, to be heard as well as seen
        if kept and kept.path == path:
            session.draft = None
        if not self.refresh:  # or they would be gone in a moment
            session.notes = {}
        self.draft = kept if kept and kept.path == path else None

    def typed(self, group: str) -> Optional[Dict[str, List[str]]]:
        return self.draft.form if self.draft and group in self.draft.groups else None

    def take(self, group: str) -> Html:
        return _note(self.notes.pop(group, None), "here")


def csrf(session) -> Html:
    return h('<input type="hidden" name="csrf" value="{t}">', t=session.csrf)


def _ask(view: View, kind: str, label: str, sign: str, back: str, off: bool = False, main: bool = False) -> Html:
    return h('<form method="post" action="/do">{csrf}<input type="hidden" name="back" value="{back}">'
             '<button name="kind" value="{kind}" class="{cls}"{off}>{sign}{label}</button></form>',
             csrf=csrf(view.session), back=back, kind=kind, label=label, sign=icon(sign), off=flag("disabled", off or kind in view.busy), cls="go" if main else "also boxed")


def shell(view: View, title: str, sub: str, scene: Html, body: Html, slip: Html = Html("")) -> Html:
    path, hero = view.path, view.path == "/"
    nav = join(h('<a href="{href}"{here}>{sign}<span>{label}</span></a>', href=href, label=label, sign=icon(sign),
                 here=Html(' aria-current="page"') if href == path else Html("")) for href, label, sign in NAV)
    problems = [] if view.current else view.status["problems"]
    older = not view.current and not problems and view.store.fresh(view.status)
    waiting = not view.current and not problems and not older and path not in STILL
    if not view.current and path not in STILL:
        view.store.ask_if_stale()
        head, text = ("Settings to put right", "The printer program cannot use these pages until this is corrected: " + "; ".join(problems) + ".") if problems else \
            ("An update is needed", "These pages are older than the printer program. On your computer, run ./deploy.sh --web") if older else \
            ("One moment", "Waiting for the printer program to report. This takes a few seconds.")
        body, slip = h("<h2>{t}</h2><p>{p}</p>", t=head, p=text), Html("")
    note = join(_note(n) for n in view.notes.values())
    doing = [f"{DONE[kind]} {'waiting' if view.store.result(kind).state == 'waiting' else 'printing'}" for kind in PAPER if kind in view.busy]
    head = Html("<h1>First<br>Up</h1>") if hero else h('<p class="mark"><a href="/">{n}</a></p><h1>{t}</h1>', n=NAME, t=title)
    page = h("""<a class="skip" href="#main">To the content</a><header class="poster {hero}">{scene}{head}<p class="sub">{sub}</p>
<div class="leave"><a href="/phone">{phone}<span>Phone</span></a><a href="/password">{key}<span>Keys</span></a><form method="post" action="/logout">{csrf}<button>{out}<span>Sign out</span></button></form></div></header>
<nav aria-label="Pages">{nav}</nav><main id="main" tabindex="-1" class="{layout}">{note}<div class="body">{body}</div>{slip}</main>""",
             hero="hero" if hero else "", scene=scene, head=head, sub=sub, csrf=csrf(view.session), out=icon("out"), key=icon("key"), phone=icon("phone"), nav=nav, note=note,
             layout="with-slip" if slip else "", body=body, slip=slip)
    kind = _kind(view.current, "busy" if view.busy else "")
    return document(": ".join((view.said or doing)[:1] + [title]), page, kind, refresh=waiting or view.refresh)


def _again(view: View, anchor: str, words: str) -> Html:
    """A link to this page that is never the one that is open, or nothing would happen."""
    return h(' <a href="{path}?{n}{anchor}">{words}</a>', path=view.path, n=int(time.time()), anchor=anchor, words=words)


def _strips(view: View, order: List[str], made: int) -> Html:
    """The paper, put together from the pictures of the blocks: style.css hides a strip as
    soon as its block is switched off, and they follow the order on the page."""
    known = view.store.blocks()
    strips = join(h('<svg class="strip strip-{name}" viewBox="0 {top} 384 {tall}" width="384" height="{tall}"><image href="/blocks.png?{made}" width="384" height="{all}"/></svg>',
                    name=name, top=known["places"][name][0], tall=known["places"][name][1], all=known["height"], made=made) for name in order if name in known.get("places", {}))
    return h('<div class="paper" role="img" aria-label="The receipt with the blocks that are switched on">{s}</div>', s=strips) if strips else Html("")


def _paper(view: View, kind: str = "preview", image: str = "preview.png", title: str = "Preview", what: str = "The receipt", group: str = "", order: Optional[List[str]] = None) -> Html:
    """With a `group`, the button saves the page's form first: what was typed must not be lost.
    While a new one is made the picture waits for it, so nothing has to be reloaded."""
    store, result, made = view.store, view.store.result(kind), view.store.image_time(image)
    stamp = datetime.fromtimestamp(made) if made else None
    if result.busy:
        n = int(time.time())
        picture = h('<div class="paper coming"><p>{t}</p><img src="/{image}?wait{n}" alt="{what}, as it would print now" width="384"></div>', t="Drawing the new one", image=image, n=n, what=what)
        note = "The new one appears here by itself, usually within ten seconds."
    else:
        picture = (_strips(view, order, made) if order and made else Html("")) or (
            h('<div class="paper"><img src="/{image}?{made}" alt="{what}, as it would have printed on {when}" width="384"></div>', image=image, made=made, what=what, when=when(stamp)) if made else
            h('<div class="paper blank"><p>{t}</p></div>', t="Make a preview to see it here, without using paper."))
        said = "" if result.text in ("", "Ready") else f" {result.text}."
        note = result.text if result.state == "failed" else f"Made {when(stamp)}.{said}" + (" Switching and moving blocks shows at once." if order else " That was before your last change." if made < store.changed() else "") if made else ""
    ask = h('<button form="settings" name="preview" value="{group}" class="also boxed"{off}>{i}Save and draw it anew</button>', group=group, i=icon("preview"), off=flag("disabled", result.busy)) \
        if group else _ask(view, kind, "Draw it anew" if made else "Make a preview", "preview", view.path)
    return h('<section class="slip" id="{kind}"><h2 class="quiet">{title}</h2>{said}{picture}<div class="under">{ask}<p class="note">{note}</p></div></section>',
             kind=kind, title=title, said=view.take(kind), picture=picture, ask=ask, note=note)


def _aside(*parts: Html) -> Html:
    return h("<aside>{parts}</aside>", parts=join(parts))


ORIGINAL = "This undoes what was chosen here. What config.toml and config.local.toml say counts again."


def _sheet(view: View, group: str, title: str, sign: str, fields: Html, preview: bool = False, used: Optional[bool] = None) -> Html:
    """One group of settings, inside the page's form."""
    reset = h('<details class="original"><summary>Go back to the original</summary><p class="note">{o}</p><button name="reset" value="{group}" class="also boxed" formnovalidate>{i}Go back</button></details>',
              i=icon("back"), o=ORIGINAL, group=group) if group in view.store.stored() else Html("")
    head = h("<h2>{i}{t}</h2>", i=icon(sign), t=title) if title else Html("")
    if used is False:
        fields = h('{f}<p class="note unused">Not on the receipt or the button. Switch it on under <a href="/receipt">Receipt</a> or <a href="/button">Button</a>.</p>', f=fields)
    also = h('<button name="preview" value="{group}" class="also boxed">{i}Save and look</button>', i=icon("preview"), group=group) if preview else Html("")
    return h('<section class="sheet" id="{group}"><input type="hidden" name="group" value="{group}"><input type="hidden" name="was-{group}" value="{was}">{note}{head}{fields}'
             '<p class="row"><button class="go" name="save" value="{group}">{i}Save</button>{also}<span class="unsaved">Not saved yet</span></p>{reset}</section>',
             group=group, was=forms.fingerprint(view.current.get(group)), head=head, note=view.take(group), fields=fields, also=also, reset=reset, i=icon("check"))


def _form(view: View, *sheets: Html) -> Html:
    # The first button is what Enter in a box presses.
    return h('<form class="sheets" id="settings" method="post" action="{path}">{csrf}<button class="enter" name="save" value="" tabindex="-1" aria-hidden="true">Save</button>{sheets}</form>', path=view.path, csrf=csrf(view.session), sheets=join(sheets))


def _pick(name: str, value: object, label: str, chosen: object, cls: str = "", sign: str = "") -> Html:
    return h('<label class="pick {cls}"><input type="radio" id="{name}-{id}" name="{name}" value="{value}"{on}><span>{sign}{label}</span></label>',
             cls=cls, name=name, id="".join(c for c in str(value).lower() if c.isascii() and c.isalnum()) or "none", value=value, label=label,
             sign=icon(sign) if sign else Html(""), on=flag("checked", str(value) == str(chosen)))


def _chips(name: str, choices: Iterable[tuple], chosen: List[str]) -> Html:
    return join(h('<label class="pick chip"><input type="checkbox" name="{name}" value="{value}"{on}><span>{label}</span></label>',
                  name=name, value=value, label=label, on=flag("checked", value in chosen)) for value, label in choices)


# --- Today ---

def _outcome(kind: str, result: Result) -> Html:
    if result.state == "failed":
        words = f"not printed: {result.text}"
    else:
        words = {"waiting": "is waiting", "working": "is printing now"}.get(result.state) or result.text[:1].lower() + result.text[1:]
    sign = "check" if result.state == "done" else "nothing" if result.state == "failed" else "print"
    return h('<li class="{state}">{i}<span><b>{name}</b> {words}{at}</span></li>', state=result.state, i=icon(sign), name=DONE[kind],
             words=words, at="" if result.busy or not result.at else f" ({when(result.at)})")


def _trouble(value: str) -> bool:
    return any(word in value for word in TROUBLE)


def _reading(label: str, value: str) -> Html:
    return h('<div class="{cls}">{i}<dt>{k}</dt><dd>{v}</dd></div>', i=icon(SIGNS.get(label, "health")), k=label, v=value, cls="trouble" if _trouble(value) else "")


def today(store: Store, session) -> Html:
    store.ask_if_stale()
    view = View(store, session, "/")
    status, current, place = view.status, view.current, view.current.get("weather")
    due = next_due(current.get("schedule", []), status["last_print"], now())
    if due:
        head = f"Next up at {due:%H:%M}"
        beside = sun.beside_sunrise(due, place["latitude"], place["longitude"]) if place else ""
        line = f"{DAYS[settings.DAYS[due.weekday()]]} {due.day} {due:%B}" + (f", {beside}" if beside else "")
    else:
        head, line = "Nothing is due", "No day is ticked under Times."
    results = [(kind, store.result(kind)) for kind in PAPER]
    outcomes = join(_outcome(kind, result) for kind, result in results if result.state)
    warning = _note(("bad", "Some settings were ignored: " + "; ".join(status["problems"]))) if status["problems"] else Html("")
    rows = sorted(status["health"], key=lambda row: (not _trouble(row[1]), FIRST_SIGNS.index(row[0]) if row[0] in FIRST_SIGNS else len(FIRST_SIGNS)))
    first = max(len(FIRST_SIGNS), sum(_trouble(value) for _, value in rows))  # trouble is never folded away
    why = Html("") if status["rail_key"] else h('<p class="note">{t}</p>', t="Train times need a token first: see Keys.")
    body = h("""<h2 class="due">{head}</h2><p class="when">{line}</p>{warning}<div class="row">{buttons}</div>{why}<ul class="outcomes">{outcomes}</ul>
<dl class="board">{first}</dl><details><summary>All readings</summary><dl class="board">{rest}</dl></details><p class="note">Checked {checked}</p>""",
             head=head, line=line, warning=warning, outcomes=outcomes, why=why, checked=when(status["at"]) or "not yet",
             first=join(_reading(*row) for row in rows[:first]), rest=join(_reading(*row) for row in rows[first:]),
             buttons=join(_ask(view, kind, label, sign, "/", kind == "trains" and not status["rail_key"], kind == "receipt") for kind, label, sign in PRINTS))
    return shell(view, "Today", "The day ahead, by the first train in.", art.today(), body, _aside(_paper(view)))


# --- Receipt ---

def _places(chosen: List[str], reference: List[str]) -> List[str]:
    """Every block: those chosen in their order, each of the others after whatever it follows
    in the original, so that switching it on again brings it back there."""
    order = list(chosen)
    for i, name in enumerate(reference):
        if name not in order:
            before = next((other for other in reversed(reference[:i]) if other in order), None)
            order.insert(order.index(before) + 1 if before else 0, name)
    return order


def receipt(store: Store, session) -> Html:
    view = View(store, session, "/receipt")
    original = view.store.defaults().get("sections", [])
    reference = original + [name for name in settings.SECTIONS if name not in original]
    chosen = view.current.get("sections", [])
    order = _places(chosen, reference)
    typed = view.typed("sections")
    if typed:
        chosen = typed.get("on", [])
        order = [name for name in typed.get("order", []) if name in settings.SECTIONS] or order
    rows = []
    for name in order:
        on, label = name in chosen, settings.SECTIONS[name]
        move = join(h('<button name="move" value="{way}:{name}" id="{way}-{name}" class="move" aria-label="Move {label} {way}"{off}>{sign}</button>',
                      way=way, name=name, label=label, sign=icon(way), off=flag("disabled", not on or name == chosen[edge]))
                    for way, edge in (("up", 0), ("down", -1))) if chosen else Html("")
        rows.append(h('<li><input type="hidden" name="order" value="{name}"><label><input type="checkbox" id="on-{name}" name="on" value="{name}"{on}>'
                      '{i}<span>{label}</span></label>{moved}<span class="moves">{move}</span></li>',
                      moved=h('<span class="moved" role="status">{t}</span>', t=view.notes.pop(f"row-{name}")[1]) if f"row-{name}" in view.notes else Html(""), name=name, label=label, on=flag("checked", on), move=move, i=icon(name)))
    fields = h('<ol class="sections">{rows}</ol><p class="flash bad wifi-on">{i}<span>{t}</span></p>', rows=join(rows), i=icon("wifi"),
               t="Every receipt will show the Wi-Fi password, to whoever sees the paper.")
    body = h("""{form}<p class="note">Calendar and reminder titles only ever go on paper. The preview shows examples instead.
They come from your iPhone: <a href="/phone">how to set that up</a>.</p>""",
             form=_form(view, _sheet(view, "sections", "", "receipt", fields, preview=True)))
    return shell(view, "Receipt", "Couple up what you want. The first one rides behind the engine and prints at the top.",
                 art.receipt(view.current.get("sections", [])), body, _aside(_paper(view, group="sections", order=order)))


# --- Times ---

def _keep(value: int) -> str:
    if value % 60:
        return f"{value} minutes"
    return "1 hour" if value == 60 else f"{value // 60} hours"


def times(store: Store, session) -> Html:
    view = View(store, session, "/times")
    slots = {day: slot for slot in view.current.get("schedule", []) for day in slot["days"]}
    typed = view.typed("schedule")
    rows = []
    for day in settings.DAYS:
        slot = slots.get(day)
        start = forms.minutes(slot["time"]) if slot else 8 * 60
        keep = forms.minutes(slot["catch_up_until"]) - start if slot else 120
        on, hour, minute = bool(slot), start // 60, start % 60
        if typed:
            on = bool(typed.get(f"on-{day}"))
            hour, minute, keep = (forms.shown(typed, f"{part}-{day}", value) for part, value in (("hour", hour), ("minute", minute), ("keep", keep)))
        keeps = sorted(set(forms.KEEP) | {keep})
        rows.append(h("""<tr><th scope="row"><label><input type="checkbox" name="on-{day}" value="1"{on}><span>{day}<span class="rest">{rest}</span></span></label></th>
<td class="flaps"><select name="hour-{day}" aria-label="{name}, hour">{hours}</select><b>:</b><select name="minute-{day}" aria-label="{name}, minutes">{mins}</select></td>
<td><select name="keep-{day}" aria-label="{name}, keep trying for">{keeps}</select></td></tr>""",
                      day=day, name=DAYS[day], rest=DAYS[day][3:], on=flag("checked", on), hours=options(((n, f"{n:02d}") for n in range(24)), hour),
                      mins=options(((n, f"{n:02d}") for n in range(0, 60, settings.STEP)), minute), keeps=options(((n, _keep(n)) for n in keeps), keep)))
    table = h('<table class="week"><thead><tr><th scope="col">Day</th><th scope="col">Prints at</th><th scope="col">Keep trying for</th></tr></thead>'
              "<tbody>{rows}</tbody></table>", rows=join(rows))
    several = h("""<details class="several"><summary>Set several days at once</summary><fieldset class="chips"><legend>These days</legend>{days}</fieldset>
<p class="flaps"><select name="all-hour" aria-label="These days, hour">{hours}</select><b>:</b><select name="all-minute" aria-label="These days, minutes">{mins}</select></p>
<p class="note">Save gives them this time and switches them on.</p></details>""", days=_chips("all", ((d, d) for d in settings.DAYS), []),
                hours=options(((n, f"{n:02d}") for n in range(24)), 8), mins=options(((n, f"{n:02d}") for n in range(0, 60, settings.STEP)), 0))
    body = h("""{form}<p class="note">If the printer is off or out of paper, it keeps trying for as long as you choose.
A receipt printed before your phone has sent the day's calendar says “Calendar not received”.
Untick every day to stop automatic prints, for example while you are away.</p>""",
             form=_form(view, _sheet(view, "schedule", "", "times", h("{t}{s}", t=table, s=several))))
    due = next_due(view.current.get("schedule", []), view.status["last_print"], now())
    words = f"{DAYS[settings.DAYS[due.weekday()]]} at {due:%H:%M}" if due else ""
    return shell(view, "Times", f"One receipt a day. The clock shows the next, {words}." if due else "One receipt a day, on the days you tick.",
                 art.times(due.hour if due else 0, due.minute if due else 0, words), body)


# --- Content ---

def _label(code: str) -> str:
    station = stations.all_stations().get(code)
    return station.label if station else code


SHEETS = {"weather": "Weather", "warnings": "Weather warnings", "pollen": "Pollen", "tube": "Underground", "news": "Headlines", "trains": "Trains", "sudoku": "Sudoku"}
LISTS = {"tube": "modes", "pollen": "kinds", "trains": "days"}  # boxes of which none may be ticked


def _fields(view: View) -> Dict[str, Any]:
    """What the content page's boxes hold, as text."""
    current = view.current
    feeds = current["news"]["feeds"]
    fields = {"weather": {"place": current["weather"]["place"], "uv_from": current["weather"]["uv_from"]},
              "pollen": {"level": current["pollen"]["level"], "kinds": current["pollen"]["kinds"]},
              "tube": {"favourite": current["tube"]["favourite"], "modes": current["tube"]["modes"]},
              "news": {"count": current["news"]["count"]},
              "trains": {"station": _label(current["trains"]["station"]), "towards": _label(current["trains"]["towards"]), "offset": current["trains"]["offset"],
                         "trains": current["trains"]["count"], "days": current["trains"]["days"]},
              "warnings": {"region": current["warnings"]["region"]}, "sudoku": {"sudoku": current["sudoku"]["level"]}}
    for i in range(settings.MAX_FEEDS):
        feed = feeds[i] if i < len(feeds) else {"name": "", "url": ""}
        fields["news"][f"name-{i}"], fields["news"][f"url-{i}"] = feed["name"], feed["url"]
    for group, values in fields.items():  # something was refused: show what was typed, not what is saved
        typed = view.typed(group)
        if typed is not None:
            values.update({k: (typed.get(k, []) if k == LISTS.get(group) else typed[k][0]) for k in values if k in typed or k == LISTS.get(group)})
    return {name: value for values in fields.values() for name, value in values.items()}


def _in_use(current: Dict[str, Any], *blocks: str) -> bool:
    button = current.get("button", {"taps": {}, "holds": {}})
    return any(name in current.get("sections", []) or name in button["taps"] or name in button["holds"] for name in blocks)


def content(store: Store, session) -> Html:
    view = View(store, session, "/content")
    current, key_set = view.current, view.status["rail_key"]
    signals = [("weather", _in_use(current, "weather")), ("warnings", _in_use(current, "warnings")), ("pollen", _in_use(current, "pollen")),
               ("tube", _in_use(current, "tube", "weekend")), ("news", _in_use(current, "news")), ("trains", key_set and _in_use(current, "trains", "departures")),
               ("sudoku", _in_use(current, "sudoku"))]
    scene = art.content([(name, SHEETS[name], use) for name, use in signals])
    sub = "Where it looks things up. A lowered arm: in use, on the receipt or the button."
    if not current:
        return shell(view, "Content", sub, scene, Html(""))
    f = _fields(view)
    weather = h("""<label for="place">Place</label><input id="place" name="place" list="stations" value="{place}" maxlength="80" required autocomplete="off">
<p class="note">A railway station nearby, or a position like 51.51, -0.13</p>
<fieldset class="scale"><legend>Warn about the sun from UV</legend>{uv}</fieldset><p class="note">3 is the usual advice. Below that no protection is needed.</p>""",
                place=f["place"], uv=join(_pick("uv_from", n, str(n), f["uv_from"], f"uv uv{n}") for n in range(settings.UV[0], settings.UV[1] + 1)))
    warnings = h("""<label for="region">Region</label><select id="region" name="region">{regions}</select><p class="note">Met Office warnings. Nothing is printed when there are none.</p>""",
                 regions=options(settings.REGIONS.items(), f["region"]))
    pollen = h("""<fieldset class="scale"><legend>Print it from</legend>{levels}</fieldset><fieldset class="chips"><legend>Which</legend>{kinds}</fieldset>
<p class="note">Nothing is printed on days without it. Grass comes in June and July, birch in spring, alder in late winter, mugwort in summer.</p>""",
               levels=join(_pick("level", value, label, f["level"]) for value, label in settings.POLLEN_LEVELS.items()), kinds=_chips("kinds", settings.POLLENS.items(), f["kinds"]))
    plates = join([_pick("favourite", "", "None", f["favourite"], "plate")] +
                  [_pick("favourite", name, name, f["favourite"], f"plate {line_class(name)}") for name in settings.LINES])
    tube = h("""<fieldset class="plates"><legend>Highlighted line</legend>{plates}</fieldset><fieldset class="chips"><legend>Show</legend>{modes}</fieldset>""",
             plates=plates, modes=_chips("modes", settings.MODES.items(), f["modes"]))
    refused = view.notes.get("news", ("", ""))[1]
    feeds = join(h("""<div class="feed"><span aria-hidden="true">{n}</span><input name="name-{i}" value="{name}" maxlength="20" placeholder="Name" aria-label="Feed {n} name"{bad}>
<input name="url-{i}" value="{url}" maxlength="300"{bad} placeholder="https://" inputmode="url" autocapitalize="off" spellcheck="false" aria-label="Feed {n} address"></div>""",
                   i=i, n=i + 1, bad=flag('aria-invalid="true"', f"feed {i + 1}:" in refused), name=f[f"name-{i}"], url=f[f"url-{i}"]) for i in range(settings.MAX_FEEDS))
    news = h("""<fieldset class="scale"><legend>How many</legend>{counts}</fieldset><fieldset><legend>RSS feeds</legend>{feeds}</fieldset>
<p class="note">Clear both boxes to remove a feed.</p>""", feeds=feeds,
             counts=join(_pick("count", n, str(n), f["count"]) for n in range(settings.COUNT[0], settings.COUNT[1] + 1)))
    key = Html("") if key_set else _note(("bad", "Train times need a free Realtime Trains token. Enter it under Keys, at the top of this page."))
    trains = h("""{key}<label for="station">Station</label><input id="station" name="station" list="stations" value="{station}" maxlength="80" required autocomplete="off">
<label for="towards">Only trains calling at</label><input id="towards" name="towards" list="stations" value="{towards}" maxlength="80" placeholder="Anywhere" autocomplete="off">
<label for="offset">On the receipt, skip trains leaving in the next</label><select id="offset" name="offset">{offsets}</select>
<p class="note">The time you need to get to the station.</p><fieldset class="scale"><legend>Show this many</legend>{counts}</fieldset>
<fieldset class="chips"><legend>On these days</legend>{days}</fieldset>""",
               counts=join(_pick("trains", n, str(n), f["trains"]) for n in range(settings.TRAINS[0], settings.TRAINS[1] + 1)),
               offsets=options(((n, f"{n} minutes") for n in range(settings.OFFSET[0], settings.OFFSET[1] + 1, settings.STEP)), f["offset"]),
               days=_chips("days", ((d, d) for d in settings.DAYS), f["days"]), key=key, station=f["station"], towards=f["towards"])
    sudoku = h('<fieldset class="scale"><legend>Difficulty</legend>{picks}</fieldset>', picks=join(_pick("sudoku", value, label, f["sudoku"]) for value, label in settings.SUDOKU.items()))
    every = join(h('<option value="{label}">', label=station.label) for station in stations.all_stations().values())
    used = {name: use for name, use in signals}
    jump = join(h('<a href="#{name}">{i}<span>{label}</span></a>', name=name, label=label, i=icon(name)) for name, label in SHEETS.items())
    body = h("""<nav class="jump" aria-label="On this page">{jump}</nav><datalist id="stations">{every}</datalist>{form}""", every=every, jump=jump, form=_form(
        view, *(_sheet(view, name, SHEETS[name], name, content, True, used[name]) for name, content in (
            ("weather", weather), ("warnings", warnings), ("pollen", pollen), ("tube", tube), ("news", news), ("trains", trains), ("sudoku", sudoku)))))
    return shell(view, "Content", sub, scene, body, _aside(_paper(view, group="weather"), _paper(view, "preview-trains", "trains.png", "Train times", "The train times", group="trains")))


# --- Button and heat ---

def button(store: Store, session) -> Html:
    view = View(store, session, "/button")
    current = view.current.get("button", {"taps": {}, "holds": {}})
    typed = view.typed("button")

    def chosen(kind: str, name: str) -> int:
        saved = current["taps" if kind == "taps" else "holds"].get(name, 0)
        return forms.shown(typed, f"{kind}-{name}", saved) if typed else saved
    rows = join(h("""<tr><th scope="row"><span class="what">{i}{label}</span></th><td><select name="taps-{name}" aria-label="{label}, taps">{taps}</select></td>
<td><select name="hold-{name}" aria-label="{label}, hold">{holds}</select></td></tr>""", name=name, label=label, i=icon(name),
                  taps=options([(0, "None")] + [(n, f"{n} tap{'s' if n > 1 else ''}") for n in range(settings.TAPS[0], settings.TAPS[1] + 1)], chosen("taps", name)),
                  holds=options([(0, "None")] + [(n, f"{n} second{'s' if n > 1 else ''}") for n in range(settings.HOLDS[0], settings.HOLDS[1] + 1)], chosen("hold", name)))
                for name, label in settings.PRESSABLE.items())
    table = h('<table class="presses"><thead><tr><th scope="col">Print</th><th scope="col">On</th><th scope="col">Or hold</th></tr></thead><tbody>{rows}</tbody></table>', rows=rows)
    body = h("""{form}<p class="note">Give several things the same press and they come out together. What the daily receipt holds is chosen under Receipt.
Holding for 5 seconds always shuts the Pi down safely; that cannot be changed here. Four seconds is close to it: let go in time.</p>""",
             form=_form(view, _sheet(view, "button", "", "button", table)))
    return shell(view, "Button", "Signal boxes spoke to each other in bell beats. This one answers to you.", art.button(current["taps"], current["holds"]), body)


def printer(store: Store, session) -> Html:
    view = View(store, session, "/printer")
    value, typed = view.current.get("printer", {}).get("heat_time", 70), view.typed("printer")
    shown = forms.shown(typed, "heat_time", value) if typed else value
    choices = sorted(set(range(settings.HEAT[0], settings.HEAT[1] + 1, 5)) | {value})
    fields = h('<fieldset class="scale heats"><legend>Heat</legend>{picks}</fieldset><p class="note">Higher is darker. The green part of the gauge, 65 to 75, '
               'looked best on the printer this was made with. Hotter than 85 smudges, so it is not offered.</p>',
               picks=join(_pick("heat_time", n, str(n), shown, f"shade shade{n}") for n in choices))
    result = store.result("calibrate")
    body = h("""{form}<section class="sheet plain"><h2>{i}Not sure?</h2><p>Print a short strip with several heats, one below the other, then pick the number that looks best.</p>
<div class="row">{ask}</div><ul class="outcomes">{outcome}</ul></section>""", i=icon("preview"),
             form=_form(view, _sheet(view, "printer", "", "heat", fields)), ask=_ask(view, "calibrate", "Print the heat strip", "print", "/printer"),
             outcome=h("{o}{again}", o=_outcome("calibrate", result), again=h("<li>{a}</li>", a=_again(view, "", "Look again")) if result.busy else Html("")) if result.state else Html(""))
    return shell(view, "Heat", "How hard the fire burns, and so how dark it prints.", art.heat(value), body)


def password(store: Store, session) -> Html:
    view = View(store, session, "/password")
    secret, session.secret = session.secret, ""
    made, ready, rail = store.phone_changed(), store.phone_ready(), view.status["rail_key"]

    def key(what: str, label: str, cls: str = "also boxed", fields: Html = Html(""), off: bool = False) -> Html:
        return h('<form method="post" action="/keys">{csrf}{fields}<p class="row"><button name="what" value="{what}" class="{cls}"{off}>{i}{label}</button></p></form>',
                 csrf=csrf(session), fields=fields, what=what, cls=cls, off=flag("disabled", off), i=icon("key"), label=label)
    shown = h('<div class="guide"><p><b>Copy it now, it is not shown again:</b></p><p><code>{s}</code></p><p class="note">In the shortcut, the header <code>Authorization</code> becomes “Bearer”, a space and this.</p></div>', s=secret) if secret else Html("")
    phone = h("<p>{now}</p>{shown}{form}", shown=shown, form=key("phone", "Make a new phone token", off=not ready),
              now="The phone sends its lists with this token. " + (f"The one in force was made here on {when(datetime.fromtimestamp(made))}." if made else
                                                                  "The one in force is from setting up the drop box." if ready else "The drop box is not set up yet: see Phone."))
    field = h('<label for="rail-token">Realtime Trains token</label><input type="password" id="rail-token" name="token" autocomplete="off" required minlength="16" maxlength="4096">')
    trains = h("<p>{now}</p>{form}{forget}<p class=\"note\">Free for personal use, from api-portal.rtt.io. It is tried before it is kept, and never shown again.</p>",
               now="A token is stored." if rail else "No token is stored, so there are no train times.", form=key("rail", "Try it and keep it", "go", field),
               forget=key("rail-forget", "Forget the stored one") if rail else Html(""))
    sheets = join(h('<section class="sheet" id="{id}">{note}<h2>{i}{t}</h2>{b}</section>', id=name, note=view.take(name), i=icon(sign), t=title, b=content)
                  for name, sign, title, content in (("phone", "phone", "Phone token", phone), ("rail", "trains", "Train token", trains)))
    body = h("""<div class="sheets"><form class="sheet" method="post" action="/password">{csrf}<h2>{key}Password</h2><input type="text" name="user" value="printer" autocomplete="username" hidden>
<label for="current">Current password</label><input type="password" id="current" name="current" autocomplete="current-password" required maxlength="200">
<label for="new">New password</label><input type="password" id="new" name="new" autocomplete="new-password" required minlength="{least}" maxlength="200">
<label for="again">New password again</label><input type="password" id="again" name="again" autocomplete="new-password" required minlength="{least}" maxlength="200">
<p class="row"><button class="go">{key}Change password</button></p></form>{sheets}</div>
<p class="note">A password needs at least {least} characters; changing it signs every other device out. All of this can also be done on the Pi: <code>setup-web.sh --new-password</code>, <code>setup-calendar.sh --new-token</code>, <code>rail-setup</code>.
The Cloudflare token is only there: it could change every record of your domain.</p>""",
             csrf=csrf(session), least=MIN_LENGTH, key=icon("key"), sheets=sheets)
    scene = art.token([("the password", True), ("the phone token", ready), ("the train token", rail)])
    return shell(view, "Keys", "On a single line no driver may pass without the token. These are yours.", scene, body)


GUIDE = """<div class="guide"><section class="sheet"><h2>{i1}Now</h2><p>Calendar: <b>{calendar}</b>. Reminders: <b>{reminders}</b>.</p>
<p class="note">The phone sends one day's list, over your own Wi-Fi. The Pi keeps it until that day is over and never has a login. If it says “not set up” here,
do sections 1 to 3 of docs/calendar.md first: they give the Pi its name, its certificate and your phone token.</p></section>
<section class="sheet" id="calendar"><h2>{i2}Calendar</h2><p>In the Shortcuts app, make a new shortcut with these actions, in this order.</p><ol>
<li><b>Get Network Details</b>: Network Name of Wi-Fi.</li><li><b>If</b> Network Name <b>is</b> your home Wi-Fi. Everything below goes inside; leave Otherwise empty.</li>
<li><b>Adjust Date</b>: add 0 days to Current Date.</li><li><b>Format Date</b> (Adjusted Date): Custom <code>yyyy-MM-dd</code>. Then <b>Set Variable</b> <code>Day</code>.</li>
<li><b>Find Calendar Events</b>: Start Date <b>is today</b>; sort by Start Date, Oldest First; no limit.</li>
<li><b>Repeat with Each</b> Calendar Event:<ul><li><b>Format Date</b>: the Repeat Item's Start Date, Custom <code>yyyy-MM-dd</code>.</li><li><b>If</b> Formatted Date <b>is</b> <code>Day</code>:<ul>
<li><b>If</b> the Repeat Item's Is All Day is Yes: <b>Text</b> “All day [Title]”.</li><li><b>Otherwise</b>: <b>Text</b> “[Start Date]-[End Date] [Title]”, both dates Custom <code>HH:mm</code>.</li></ul></li></ul></li>
<li><b>Combine Text</b>: Repeat Results, with New Lines.</li><li><b>Text</b>: [Day], and [Combined Text] on the next line.</li><li><b>URL</b>: <code>https://{drop}/calendar</code></li>
<li><b>Get Contents of URL</b>: Method POST; a header <code>Authorization</code> with “Bearer”, a space and your phone token (a new one is made under <a href="/password#phone">Keys</a>); Request Body JSON with one Text field <code>list</code>, the Text from step 8.</li>
<li><b>Show Notification</b>: Contents of URL.</li></ol><p class="note">Run it once by hand and allow everything, with Always Allow. It should say “Stored 3 events for Wednesday 25 November”.</p></section>
<section class="sheet" id="reminders"><h2>{i3}Reminders</h2><p>Add these to the end of the same shortcut, still inside the If.</p><ol>
<li><b>Find Reminders</b>: <b>Is Not Completed</b>, and <b>List</b> is the one you want on paper; no limit. Leave the due date out of it: the printer chooses by that.</li>
<li><b>Repeat with Each</b> Reminder: <b>Text</b> “[Due Date] [Title]”: Repeat Item twice, with a space between.<ul><li>Tap the first: <b>Due Date</b>, with the date format Custom <code>yyyy-MM-dd HH:mm</code>.</li>
<li>Tap the second: <b>Title</b>.</li></ul></li>
<li><b>Combine Text</b>: Repeat Results, with New Lines.</li><li><b>Text</b>: [Day], and [Combined Text] on the next line.</li><li><b>URL</b>: <code>https://{drop}/reminders</code></li>
<li><b>Get Contents of URL</b>: as in step 10 above, with the Text from step 4.</li><li><b>Show Notification</b>: Contents of URL.</li></ol><p class="note">Run it once more by hand: it asks to see your reminders, and should say “Stored 4 reminders”. That counts all it sent. On paper: overdue ones first, then today's, then those without a date, up to 12. Later ones wait for their day. With none, the block is left out.</p></section>
<section class="sheet" id="every-day"><h2>{i4}Every day</h2><p>In Shortcuts, Automation: Time of Day, a while before the receipt and once more to be sure (07:00 and 07:30 for 08:00). Every day, Run Immediately. Sending twice is harmless.</p>
<p class="note">The shortcut holds your phone token, so do not share it.</p></section>
<section class="sheet" id="trouble"><h2>{i5}If it does not work</h2><dl><dt>“bad URL”, or a timeout</dt><dd>The phone cannot find the Pi. Settings, Wi-Fi, (i), Configure DNS, Manual: <code>1.1.1.1</code>. If it worked before, the Pi's address may have changed.</dd>
<dt>Refused: wrong token</dt><dd>Make a new one under <a href="/password#phone">Keys</a>, then put it into the shortcut.</dd>
<dt>Refused: the first line must be the date</dt><dd>Step 4 must be <code>yyyy-MM-dd</code>, and step 10 must send the Text from step 8.</dd><dt>“Stored no events” on a busy day</dt><dd>A filter in step 5, or step 6 does not use the Start Date.</dd>
<dt>It runs by hand but not by itself</dt><dd>Run it by hand once with Always Allow. After a restart of the phone, unlock it once.</dd></dl></section></div>"""


def phone(store: Store, session) -> Html:
    view = View(store, session, "/phone")
    readings = dict(view.status["health"])
    calendar, reminders = readings.get("Calendar", "not known yet"), readings.get("Reminders", "not known yet")
    body = h(GUIDE, calendar=calendar, reminders=reminders, drop=DROP,
             i1=icon("phone"), i2=icon("events"), i3=icon("reminders"), i4=icon("times"), i5=icon("services"))
    scene = art.post([("events", "the calendar", calendar.startswith("list at")), ("reminders", "the list of reminders", reminders.startswith("list at"))])
    return shell(view, "Phone", "How the calendar and the reminders get from your iPhone to the paper. A full bag: today's list has come.", scene, body)


def missing() -> Html:
    return document("Not here", h('<main class="nowhere"><h1>Not here</h1><p>There is no page at this address. <a href="/">Back to Today</a></p></main>'), _kind({}))


SHOW = {"/phone": phone, "/password": password, "/": today, "/receipt": receipt, "/times": times, "/content": content, "/button": button, "/printer": printer}
CHANGE = tuple(dict.fromkeys(GROUPS.values()))  # the pages whose forms change settings
