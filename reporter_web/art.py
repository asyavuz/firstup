"""The drawings: one poster for each page, and the icons. All shapes are written here; only
numbers and names from this program are ever put into them. Colours come from style.css, so
the sky can follow the sun and the engine the highlighted line."""

from math import cos, pi, sin
from typing import Dict, List, Sequence

from .markup import Html, h, join

# --- icons, on a 30 x 30 grid ---

_PATHS: Dict[str, str] = {
    "today": "M4 21a11 11 0 0 1 22 0M1 21h28M15 4v4M5 8l2.500 2.500M25 8l-2.500 2.500M7 26h16",
    "receipt": "M7 3l2.700 2L12.300 3 15 5l2.700-2 2.600 2L23 3v24l-2.700-2-2.600 2L15 25l-2.700 2-2.600-2L7 27zM11 11h8M11 16h8M11 21h5",
    "times": "M15 4a11.500 11.500 0 1 0 .01 0M15 8.500v7l4.500 3",
    "content": "M14 28V3M14 5h10l3 3-3 3H14M14 14H6l-3 3 3 3h8M9 28h10",
    "button": "M15 4a11 11 0 1 0 .01 0M15 11a4 4 0 1 0 .01 0",
    "heat": "M15 3c1 6 8 8 8 15a8 8 0 0 1-16 0c0-4 3-5 3-9 3 1 4 4 4 6 2-3 2-8 1-12z",
    "print": "M8 11V3h14v8M8 22H3V11h24v11h-5M8 17h14v10H8z",
    "trains": "M9 4h12a3 3 0 0 1 3 3v12a3 3 0 0 1-3 3H9a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3zM6 14h18M15 4v10M10.500 18h.01M19.500 18h.01M9 27l3-5M21 27l-3-5",
    "wifi": "M3 12a18 18 0 0 1 24 0M7.500 17a12 12 0 0 1 15 0M11.500 21.500a6 6 0 0 1 7 0M15 25.500h.01",
    "health": "M3 16h6l3-8 5 14 3-6h7",
    "nothing": "M15 4a11 11 0 1 0 .01 0M7.500 22.500l15-15",
    "preview": "M2 15s5-8 13-8 13 8 13 8-5 8-13 8-13-8-13-8zM15 11.500a3.500 3.500 0 1 0 .01 0",
    "weather": "M11 5v-3M5 8L3 6M17 8l2-2M6.500 13a4.500 4.500 0 1 1 9-.500M10 26h12a5 5 0 0 0 .500-10 7.500 7.500 0 0 0-14.300 1.500A4.300 4.300 0 0 0 10 26z",
    "events": "M4 6h22v20H4zM4 12h22M10 3v5M20 3v5M10 19l3.500 3.500 6-6.500",
    "pollen": "M15 12.500a2.500 2.500 0 1 0 .01 0M15 12.500c-3-3-3-8 0-9.500 3 1.500 3 6.500 0 9.500M17.200 14c1.200-4 5.800-6.200 8.300-4 .500 3.300-3.800 6-8.300 5M12.800 14c-1.200-4-5.800-6.200-8.300-4-.500 3.300 3.800 6 8.300 5M16.500 17c4.200.500 7 4.600 5.200 7.300-3.200.600-6-3-5.700-7M13.500 17c-4.200.500-7 4.600-5.200 7.300 3.200.600 6-3 5.700-7",
    "warnings": "M15 4L28 26H2zM15 12v7M15 22.500h.01",
    "reminders": "M5 5h20v20H5zM9.500 15l4 4 7.500-8.500",
    "ahead": "M4 6h22v20H4zM4 12h22M10 3v5M20 3v5M15 14.500l1.400 2.900 3.200.400-2.400 2.200.700 3.200-2.900-1.600-2.900 1.600.700-3.200-2.400-2.200 3.200-.400z",
    "departures": "M9 4h12a3 3 0 0 1 3 3v12a3 3 0 0 1-3 3H9a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3zM6 14h18M15 4v10M9 27l3-5M21 27l-3-5",
    "history": "M8 3h14M8 27h14M9 3c0 7 5 8 6 12-1 4-6 5-6 12M21 3c0 7-5 8-6 12 1 4 6 5 6 12",
    "sudoku": "M4 4h22v22H4zM11.300 4v22M18.600 4v22M4 11.300h22M4 18.600h22",
    "poster": "M5 3h20v24H5zM8 20h14M8 20c0-9 14-9 14 0M15 8v3M9.500 10l1.500 2M20.500 10l-1.500 2M10 23.500h10",
    "tube": "M3 27V15a12 12 0 0 1 24 0v12M8 27V16a7 7 0 0 1 14 0v11M8 20h14M11.500 24h.01M18.500 24h.01",
    "weekend": "M3 9h24v7H3zM7 16v11M23 16v11M7 9V5M23 9V5M9 16l5-7M17 16l5-7",
    "news": "M4 5h18v21H7a3 3 0 0 1-3-3zM22 12h4v11a3 3 0 0 1-3 3M8 10h10M8 15h10M8 20h6",
    "quote": "M12 8c-4 1-6 4-6 8v6h7v-7H8.500M24 8c-4 1-6 4-6 8v6h7v-7h-4.500",
    "closing": "M15 4a11 11 0 1 0 .01 0M10 17.500c1.200 2.300 3 3.500 5 3.500s3.800-1.200 5-3.500M11 12h.01M19 12h.01",
    "header": "M5 5h20v21H5zM5 11h20M12.500 16.500l3-1.500v8M12.500 23h5.500",
    "check": "M4 16l7 7L26 7",
    "power": "M17 2L6 17h8l-2 11 12-16h-8z",
    "temperature": "M12 5a3 3 0 0 1 6 0v12a6 6 0 1 1-6 0zM15 12v10",
    "uptime": "M8 3h14M8 27h14M9 3c0 7 5 8 6 12-1 4-6 5-6 12M21 3c0 7-5 8-6 12 1 4 6 5 6 12",
    "storage": "M5 8c0-5 20-5 20 0v14c0 5-20 5-20 0zM5 8c0 5 20 5 20 0M5 15c0 5 20 5 20 0",
    "services": "M9 28V3M9 6h14l4 4-4 4H9M5 28h8",
    "certificate": "M15 3l10 4v8c0 6-4 10-10 12C9 25 5 21 5 15V7zM10 15l4 4 7-7",
    "address": "M15 28s9-9 9-15a9 9 0 0 0-18 0c0 6 9 15 9 15zM15 9.500a3.500 3.500 0 1 0 .01 0",
    "settings": "M4 9h12M22 9h4M4 21h4M14 21h12M19 5.500a3.500 3.500 0 1 0 .01 0M11 17.500a3.500 3.500 0 1 0 .01 0",
    "up": "M15 25V6M7 13l8-8 8 8", "down": "M15 5v19M7 17l8 8 8-8",
    "out": "M12 4H5v22h7M12 15h15M21 9l6 6-6 6", "key": "M10 11a6 6 0 1 0 .01 0M15 17h13M23 17v6",
    "sun": "M15 10a5 5 0 1 0 .01 0M15 2v4M15 24v4M2 15h4M24 15h4M6 6l2.800 2.800M21.200 21.200L24 24M24 6l-2.800 2.800M8.800 21.200L6 24",
    "back": "M5 13h14a6 6 0 0 1 0 12h-6M5 13l6-6M5 13l6 6", "phone": "M10 3h10a2 2 0 0 1 2 2v20a2 2 0 0 1-2 2H10a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM13.500 23.500h3",
}


def icon(name: str) -> Html:
    return h('<svg class="icon" width="30" height="30" viewBox="0 0 30 30" aria-hidden="true"><path d="{d}"/></svg>', d=_PATHS[name])


# --- pieces ---

_SKY = Html('''<rect class="s1" width="1280" height="520"/><path class="s2" d="M0 150Q200 118 420 158T860 140T1280 168V520H0Z"/>
<path class="s3" d="M0 306Q260 300 440 272T1000 222T1280 244V520H0Z"/><path class="s4" d="M0 338Q300 330 640 306T1280 288V520H0Z"/>''')
_LOW_SKY = Html('''<rect class="s1" y="200" width="1280" height="320"/><path class="s2" d="M0 300Q240 276 520 304T1000 292T1280 306V520H0Z"/>
<path class="s3" d="M0 332Q240 314 560 334T1000 324T1280 336V520H0Z"/><path class="s4" d="M0 354Q300 342 640 356T1280 352V520H0Z"/>''')
# Lettering stands on this; what is drawn after it passes in front.
_BANNER = Html('<g class="banner"><path class="s1" d="M0 200H650L540 520H0Z"/><path class="linee" d="M650 200h30L570 520h-30Z"/></g>')
_LOW_STARS = Html('<path class="stars" d="M720 250h.1M790 300h.1M850 236h.1M930 276h.1M1010 240h.1M1080 290h.1M1150 246h.1M1230 284h.1"/>')
_STARS = Html('''<path class="stars" d="M90 60h.1M210 110h.1M330 40h.1M468 96h.1M540 30h.1M700 70h.1M816 24h.1M884 118h.1M968 58h.1M1060 96h.1M1150 40h.1M1230 120h.1M60 170h.1M400 180h.1M760 160h.1M1010 170h.1M1180 200h.1M260 200h.1"/>''')
_RAYS = Html('<g class="rays"><path class="faint" d="M600 372L-936 -233L-936 -521L-768 -521ZM600 372L-240 -521L48 -521Z"/><path d="M600 372L408 -521L696 -521ZM600 372L1056 -521L1392 -521ZM600 372L1872 -521L2256 -521L2256 -425ZM600 372L2256 -113L2256 175Z"/></g>')  # they go on above the picture
_SUN = Html('''<g class="orb"><circle class="sun" cx="600" cy="372" r="118"/><circle class="bite" cx="650" cy="340" r="104"/></g>''')
_CITY = Html('''<g class="far"><path d="M0 372H40V340H58V372H120V318L132 296L144 318V372H214V350H260V372H330V372Z"/>
<path d="M408 372V346H432V316H452V300Q452 262 486 252V236H482V230H490V214H494V230H502V236H498V252Q532 262 532 300V316H552V346H576V372Z"/>
<path d="M590 372V330L600 306L610 330V372ZM770 372V262H790V244L796 222L802 244V262H822V372ZM860 372V292H868V372H890V292H898V372H930V292H938V372H960V292H968V372ZM996 372V350H1052V338H1080V372H1180V356H1280V372Z"/></g>''')
_HILLS = Html('''<rect class="hill" y="366" width="1280" height="154"/><path class="land" d="M0 388Q220 360 470 384T960 378T1280 390V520H0Z"/>''')
_HOUSES = Html('''<g class="roof"><path d="M20 412L70 384L120 412V450H20ZM150 420L190 398L230 420V450H150ZM1010 404L1070 376L1130 404V450H1010ZM1150 414L1194 392L1238 414V450H1150Z"/></g>
<g class="chimney"><path d="M84 378h12v26H84zM204 392h10v24h-10zM1084 370h12v28h-12zM1208 386h10v24h-10z"/></g>
<path class="lamp" d="M50 420h14v14H50zM88 420h14v14H88zM180 426h12v12h-12zM1040 414h14v14h-14zM1090 414h14v14h-14zM1186 422h12v12h-12z"/>''')
_WHEEL = '<g class="wheel" transform="translate({x} {y})"><g><circle r="{r}"/><path d="M-{r} 0H{r}M0 -{r}V{r}"/></g></g>'


def _wheels(*places) -> Html:
    return join(h(_WHEEL, x=x, y=y, r=r) for x, y, r in places)


def _steam(x: float, y: float) -> Html:
    return h('''<g class="steam" transform="translate({x} {y})"><g><path class="puff" d="M0 14Q-18 -30 -58 -22Q-78 -54 -120 -38Q-158 -66 -190 -34Q-244 -52 -272 -20Q-324 -34 -358 -4Q-398 -10 -414 12Q-364 6 -324 14Q-244 0 -194 12Q-104 -4 0 14Z"/>
<path class="puff2" d="M0 17Q-44 2 -94 6Q-144 -6 -194 8Q-264 0 -324 14Q-284 20 -234 16Q-124 10 0 17Z"/></g></g>''', x=x, y=y)


def _engine(x: float, y: float) -> Html:
    """A streamlined engine and tender facing right; (x, y) is under its tail, on the rail."""
    return h('''<g transform="translate({x} {y})"><path class="lined" d="M-114 0V-42Q-114 -50 -106 -50H-14Q-6 -50 -6 -42V0Z"/><path class="linedd" d="M-114 -38H-6V-44H-114Z"/>
<path class="linee" d="M0 0V-48Q0 -54 8 -54H286Q338 -54 378 -16Q386 -8 387 0Z"/><path class="linel" d="M0 -48Q0 -54 8 -54H286Q308 -54 328 -47Q308 -44 286 -44H0Z"/>
<path class="linedd" d="M26 0Q106 -36 206 -20Q296 -8 387 0Z"/><path class="lamp" d="M18 -46h22v18H18zM46 -46h14v18H46z"/><path class="black" d="M286 -54q10 -9 24 -7l8 8q-14 -2 -32 -1z"/>
<path class="lining" d="M26 -26H266"/>{wheels}<g class="rod"><path d="M110 -2h104"/></g><circle class="lamp" cx="374" cy="-10" r="5"/></g>''', x=x, y=y,
             wheels=_wheels((-84, 0, 8), (-58, 0, 8), (-32, 0, 8), (66, 0, 10), (118, -2, 16), (162, -2, 16), (206, -2, 16), (286, 0, 9), (314, 0, 9)))


def _coach(x: float, y: float, width: int = 220) -> Html:
    windows = join(h('<path class="lamp" d="M{x} -38h30v16h-30z"/>', x=20 + i * 42) for i in range((width - 40) // 42 + 1))
    return h('''<g transform="translate({x} {y})"><path class="coach" d="M0 0V-44Q0 -52 8 -52H{w8}Q{w} -52 {w} -44V0Z"/><path class="cream" d="M0 -44Q0 -52 8 -52H{w8}Q{w} -52 {w} -44Z"/>{windows}{wheels}</g>''',
             x=x, y=y, w=width, w8=width - 8, windows=windows, wheels=_wheels((30, 0, 7), (56, 0, 7), (width - 56, 0, 7), (width - 30, 0, 7)))


def _viaduct(y: int) -> Html:
    arches = join(h('<path class="arch" d="M{x} {b}V{s}a44 44 0 0 1 88 0V{b}Z"/>', x=30 + i * 140, b=y + 80, s=y + 60) for i in range(11))
    return h('<rect class="stone" y="{y}" width="1280" height="90"/><g class="passing">{arches}</g><rect class="rail" y="{r}" width="1280" height="9"/>', y=y + 6, r=y, arches=arches)


def poster(name: str, label: str, body: Html, height: int = 520) -> Html:
    fit = "xMaxYMax" if height < 520 else "xMidYMax"  # on a phone, the part right of the lettering
    return h('<svg class="scene scene-{name}{low}" width="640" height="{tall}" viewBox="0 {top} 1280 {height}" preserveAspectRatio="{fit} slice" role="img" aria-label="{label}">{body}</svg>',
             tall=height // 2, name=name, top=520 - height, height=height, fit=fit, label=label, body=body, low=" low" if height < 520 else "")


def backdrop() -> Html:
    return join([_SKY, _STARS, _RAYS, _SUN])


def low(sun_x: int) -> Html:
    """The sky of the shorter posters."""
    return h('{sky}{stars}<g transform="translate({dx} 0)">{rays}{sun}</g>', sky=_LOW_SKY, stars=_LOW_STARS, rays=_RAYS, sun=_SUN, dx=sun_x - 600)


# --- posters ---

def today() -> Html:
    train = h('<g class="train">{steam}{coaches}{engine}</g>', steam=_steam(774, 372), coaches=join([_coach(-150, 440), _coach(80, 440)]), engine=_engine(424, 440))
    return poster("today", "A train crossing a viaduct into London", join([backdrop(), _CITY, _HILLS, _HOUSES, _viaduct(440), train]))


def receipt(sections: Sequence[str]) -> Html:
    """The sections as a train: the first one right behind the engine."""
    coaches = []
    size = round(min(1, 8 / max(1, len(sections))), 3)  # a long train has smaller carriages
    for i, name in enumerate(sections):
        coaches.append(h('''<g class="car car-{name}" transform="translate({x} 486) scale({size})"><path class="coach" d="M0 0V-66Q0 -74 8 -74H88Q96 -74 96 -66V0Z"/><path class="cream" d="M0 -66Q0 -74 8 -74H88Q96 -74 96 -66V-62H0Z"/>
<path class="panel" d="M27 -56h42v42H27z"/><g class="sign" transform="translate(33 -50)"><path d="{d}"/></g>{wheels}<path class="black" d="M-8 -14h8v5h-8z"/></g>''',
                         name=name, x=round(720 + 96 * (1 - size) - i * 104 * size), size=size, d=_PATHS[name], wheels=_wheels((22, 0, 9), (74, 0, 9))))
    train = h('<g class="train">{steam}{cars}{engine}</g>', steam=_steam(1172, 418), cars=join(coaches), engine=_engine(940, 486))
    ground = Html('<rect class="stone" x="-1400" y="492" width="2680" height="28"/><rect class="rail" x="-1400" y="486" width="2680" height="8"/>')
    return poster("receipt", "A train made up of the chosen sections", join([low(1010), _HILLS, _HOUSES, _BANNER, ground, train]), 300)


def times(hour: int, minute: int, words: str) -> Html:
    """`words` say the same as the clock; "" if no receipt is due."""
    marks = join(h('<path d="M0 -104V{y}" transform="rotate({a})"/>', y=-84 if i % 3 == 0 else -93, a=i * 30) for i in range(12))
    hands = h('<path class="hand" d="M0 14V-58" transform="rotate({a})"/><path class="hand thin" d="M0 18V-88" transform="rotate({b})"/><circle class="boss" r="9"/>',
              a=round(hour % 12 * 30 + minute / 2, 1), b=minute * 6) if words else Html("")
    teeth = join(h('<path class="valance" d="M{x} 262h40v26l-20 18l-20 -18z"/>', x=i * 40) for i in range(17, 32))
    return poster("times", f"A station clock showing the next print, {words}" if words else "A station clock without hands", h('''{sky}{hills}{banner}<path class="stone" d="M-1400 486H1280V520H-1400Z"/><path class="edge" d="M-1400 478H1280V488H-1400Z"/>
<g class="iron"><path d="M1120 262h18v218h-18zM1112 462h34v18h-34zM716 262h18v218h-18zM708 462h34v18h-34z"/><path d="M734 300q44 0 60 -38h-14q-12 26 -46 26zM716 300q-44 0 -60 -38h14q12 26 46 26zM1138 300q44 0 60 -38h-14q-12 26 -46 26zM1120 300q-44 0 -60 -38h14q12 26 46 26z"/></g>
<path class="roofing" d="M684 200H1280V264H662Z"/>{teeth}<path class="iron" d="M922 250h16v40h-16z"/><g transform="translate(930 376) scale(.8)"><circle class="rim" r="126"/><circle class="face" r="112"/><g class="marks">{marks}</g>{hands}</g>
<g class="bench"><path d="M1150 446h130v8h-130zM1150 426h130v8h-130zM1150 408h130v8h-130zM1160 400h8v86h-8z"/></g>''',
                  sky=low(680), hills=_HILLS, banner=_BANNER, teeth=teeth, marks=marks, hands=hands), 300)


def content(signals: Sequence[tuple]) -> Html:
    """`signals` are (icon, name, in use): the arm drops when the line is clear."""
    posts = []
    for i, (name, _, clear) in enumerate(signals):
        posts.append(h('''<g transform="translate({x} 486) scale(.74)"><path class="iron" d="M-6 0V-196h12V0z"/><path class="iron" d="M0 -214l9 18h-18z"/><g transform="translate(0 -170) rotate({a})"><path class="arm {c}" d="M-12 -13H92V13H-12z"/><path class="chevron" d="M70 -13l12 13l-12 13h-9l12 -13l-12 -13z"/></g>
<circle class="glow {c}" cx="-16" cy="-170" r="9"/><rect class="plate" x="-26" y="-118" width="52" height="52" rx="3"/><g class="sign" transform="translate(-15 -107)"><path d="{d}"/></g></g>''',
                      x=654 + i * 92, a=42 if clear else 0, c="clear" if clear else "stop", d=_PATHS[name]))
    track = Html('<rect class="stone" x="-1400" y="490" width="2680" height="30"/><rect class="rail" x="-1400" y="484" width="2680" height="8"/>')
    lowered = ", ".join(label for _, label, clear in signals if clear) or "none"
    return poster("content", f"Signals, lowered for what is in use: {lowered}", join([low(1120), _CITY, _HILLS, _BANNER, track, join(posts)]), 300)


def _beats(size: int, held: bool) -> Html:
    """A dot for each tap; a bar for holding, longer for longer."""
    if held:
        return h('<rect class="beat" x="{x}" y="-32" width="{w}" height="16" rx="8"/>', x=-8 - size * 7, w=16 + size * 14)
    rows = [size] if size <= 4 else [(size + 1) // 2, size // 2]
    r, step = (8, 24) if size <= 3 else (6, 17)
    return join(h('<circle class="beat" cx="{x}" cy="{y}" r="{r}"/>', x=round((i - (n - 1) / 2) * step, 1), y=-25 if len(rows) == 1 else -34 + row * 18, r=r)
                for row, n in enumerate(rows) for i in range(n))


BELLS = 5  # more do not fit on the shelf


def button(taps: Dict[str, int], holds: Dict[str, int]) -> Html:
    """A bell for each press that prints something."""
    presses = [(n, False) for n in sorted(set(taps.values()))] + [(n, True) for n in sorted(set(holds.values()))]
    words = ", ".join(f"hold {n} second{'s' * (n > 1)}" if held else f"{n} tap{'s' * (n > 1)}" for n, held in presses) or "none"
    shown = presses[:BELLS]
    step = 150 if len(shown) < 5 else 122
    levers = join(h('<g transform="translate({x} 524) scale(.76)"><path class="lever l{c}" d="M-9 0L-7 -104h14L9 0z"/><path class="grip" d="M-6 -150q6 -10 12 0l1 48h-14z"/><circle class="tag" cy="-62" r="11"/></g>',
                    x=640 + i * 48, c=(i * 5) % 4) for i in range(14))
    window = Html('''<g><path class="frame" d="M0 220H1280V404H0Z"/></g><g class="panes"><path class="frame" d="M0 290H1280V298H0ZM120 220h8v184h-8zM260 220h8v184h-8zM400 220h8v184h-8zM540 220h8v184h-8zM680 220h8v184h-8zM820 220h8v184h-8zM960 220h8v184h-8zM1100 220h8v184h-8zM1240 220h8v184h-8z"/></g>''')
    bells = join(h('''<g transform="translate({x} 404)"><path class="wood" d="M-44 0V-50h88V0z"/><path class="woodd" d="M-50 -56h100v8h-100z"/><path class="brass" d="M-34 -60a34 34 0 0 1 68 0z"/><path class="brassd" d="M-5 -100h10v8h-10z"/>{beats}</g>''',
                       x=724 + i * step, beats=_beats(n, held)) for i, (n, held) in enumerate(shown))
    return poster("button", f"Block bells in a signal box, for: {words}", h('''{sky}{city}{hills}<path class="cabin" d="M0 404H1280V520H0Z"/>{window}{banner}<path class="shelf" d="M640 404H1280V416H640Z"/>{bells}{levers}''',
                  sky=low(1010), city=_CITY, hills=_HILLS, window=window, banner=_BANNER, bells=bells, levers=levers), 300)


GAUGE_FROM, GAUGE_TO = 40, 100  # heat at the two ends of the scale


def gauge_angle(heat: int) -> float:
    return round((heat - GAUGE_FROM) / (GAUGE_TO - GAUGE_FROM) * 270 - 135, 1)


def _arc(start: int, end: int, r: int) -> str:
    a, b = ((gauge_angle(v) - 90) * pi / 180 for v in (start, end))
    return f"M{r * cos(a):.1f} {r * sin(a):.1f}A{r} {r} 0 {int(gauge_angle(end) - gauge_angle(start) > 180)} 1 {r * cos(b):.1f} {r * sin(b):.1f}"


def heat(value: int) -> Html:
    marks: List[Html] = []
    for v in range(GAUGE_FROM, GAUGE_TO + 1, 5):
        a = (gauge_angle(v) - 90) * pi / 180
        marks.append(h('<path d="M0 -100V{y}" transform="rotate({a})"/>', y=-84 if v % 10 == 0 else -92, a=gauge_angle(v)))
        if v % 20 == 0:
            marks.append(h('<text x="{x}" y="{y}">{v}</text>', x=round(62 * cos(a), 1), y=round(62 * sin(a) + 8, 1), v=v))
    rivets = join(h('<circle class="rivet" cx="{x}" cy="{y}" r="4"/>', x=20 + i * 54, y=y) for i in range(24) for y in (236, 506))
    return poster("heat", "A firebox and its pressure gauge", h('''<rect class="plate1" y="200" width="1280" height="320"/><path class="plate2" d="M0 220H1280V226H0ZM0 516H1280V520H0Z"/>{rivets}{banner}
<g transform="translate(790 392)"><path class="door" d="M-150 -118h300v236h-300z"/><path class="mouth" d="M-118 96V-30a118 74 0 0 1 236 0V96z"/>
<g class="fire"><path class="f1" d="M-112 96Q-104 20 -76 34Q-70 -24 -34 -34Q-34 4 -14 14Q8 -52 24 -66Q36 -16 54 -2Q62 -22 76 -24Q104 30 112 96z"/><path class="f2" d="M-84 96Q-72 46 -54 52Q-44 12 -22 10Q-14 40 2 44Q16 6 24 -14Q36 28 52 40Q76 52 84 96z"/><path class="f3" d="M-50 96Q-38 66 -22 66Q-8 44 2 60Q16 40 24 34Q32 64 50 96z"/></g></g>
<g class="pipe"><path d="M1066 200V270M1240 200v120q0 40 40 40h40"/></g>
<g transform="translate(1066 394) scale(.94)"><circle class="rim" r="126"/><circle class="face" r="112"/><path class="good" d="{good}"/><path class="hot" d="{hot}"/><g class="marks">{marks}</g><g class="needle" transform="rotate({a})"><g><path class="hand" d="M0 22V-84"/></g></g><circle class="boss" r="10"/></g>''',
                  rivets=rivets, banner=_BANNER, good=_arc(65, 75, 92), hot=_arc(85, 100, 92), marks=join(marks), a=gauge_angle(value)), 300)


def token(keys: Sequence[tuple]) -> Html:
    """The brass tokens of single-line working, hanging in their rack; a missing one is a shadow."""
    hung = join(h('<g class="bag {c}" transform="translate({x} 330)"><circle class="hoop" r="46"/><path class="brass" d="M-9 44h18v96h-18z"/><path class="brass" d="M9 104h26v14H9zM9 124h18v14H9z"/><path class="brassd" d="M-15 40h30v12h-30z"/></g>',
                  x=800 + i * 160, c="full" if held else "empty") for i, (_, held) in enumerate(keys))
    words = ", ".join(f"{name} {'is here' if held else 'is missing'}" for name, held in keys)
    return poster("token", f"Brass tokens in a signal box: {words}", h('{sky}{city}{hills}<path class="cabin" d="M0 200H1280V520H0z"/><path class="woodd" d="M0 250H1280V276H0z"/>{banner}<path class="shelf" d="M640 506H1280V520H640Z"/>{keys}',
                  sky=low(1010), city=_CITY, hills=_HILLS, banner=_BANNER, keys=hung), 300)


def post(bags: Sequence[tuple]) -> Html:
    """Mailbags beside the line, as for a travelling post office: (icon, name, whether it has come)."""
    hung = join(h('''<g transform="translate({x} 486) scale(.8)"><path class="iron" d="M-7 0V-236h14V0zM-7 -236H86v9H-7zM-7 -190l60 -46h14l-74 58z"/><g class="bag {c}"><path class="iron" d="M66 -228h6v22h-6z"/>
<path class="wood" d="M44 -206h50q22 70 12 112q-37 22 -74 0q-10 -42 12 -112z"/><path class="woodd" d="M44 -206h50l3 12h-56z"/></g><g class="sign" transform="translate(54 -164)"><path d="{d}"/></g></g>''',
                  x=720 + i * 250, c="full" if come else "empty", d=_PATHS[name]) for i, (name, _, come) in enumerate(bags))
    words = ", ".join(f"{label} {'has come' if come else 'has not come'}" for _, label, come in bags)
    ground = Html('<rect class="stone" x="-1400" y="490" width="2680" height="30"/><rect class="rail" x="-1400" y="484" width="2680" height="8"/>')
    return poster("post", f"Mailbags beside the line: {words}", join([low(1120), _CITY, _HILLS, _BANNER, ground, hung]), 300)


def app_icon() -> Html:
    """Standalone picture for browser tabs and the home screen, with its own colours."""
    return Html('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 180"><path fill="#1f5269" d="M0 0h180v180H0z"/><path fill="#3d7f8c" d="M0 58q50-14 96 2t84-4v124H0z"/><path fill="#f3b676" d="M0 96q50-10 96 2t84-2v84H0z"/><circle cx="104" cy="128" r="46" fill="#fbe193"/><path fill="#5f7799" d="M28 128v-14h10v-12h8v-8q0-18 16-24v-9h-3v-5h3v-9h4v9h3v5h-3v9q16 6 16 24v8h8v12h10v14z"/><path fill="#0f5b48" d="M0 126h180v54H0z"/><path fill="#14232f" d="M0 152h180v28H0z"/><path fill="#0091cc" d="M0 148v-22q0-4 4-4h104q34 0 56 22l4 4z"/><path fill="#35aee0" d="M0 126q0-4 4-4h104q16 0 30 6-14 2-30 2H0z"/><path fill="#14437a" d="M8 148q34-18 80-10t80 10z"/><g fill="#a23e2c" stroke="#14232f" stroke-width="4"><circle cx="46" cy="148" r="12"/><circle cx="78" cy="148" r="12"/><circle cx="110" cy="148" r="12"/></g><path stroke="#f7efe0" stroke-width="3" d="M40 148h76"/><path fill="#fbe193" d="M6 128h14v11H6z"/></svg>''')
