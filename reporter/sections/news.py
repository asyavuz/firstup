import logging
from datetime import datetime
from typing import Dict, List, NamedTuple

from PIL import Image

from .. import feeds, http
from ..render import PAD, RIGHT, WIDTH, Canvas, fit, font, line_height, wrap

log = logging.getLogger(__name__)

MAX_LINES = 4
FEED_SECONDS = 25


class Headlines(list):
    """With the names of the feeds that gave nothing."""

    missing: List[str] = []


class Headline(NamedTuple):
    title: str
    source: str


def parse_feed(content: bytes) -> List[str]:
    return [item["title"] for item in feeds.items(content, ("title",))]


def pick(by_source: Dict[str, List[str]], count: int) -> List[Headline]:
    """Take headlines in turn from each feed, skipping exact repeats."""
    queues = [(name, list(titles)) for name, titles in by_source.items()]
    seen = set()
    chosen: List[Headline] = []
    while len(chosen) < count and any(titles for _, titles in queues):
        for name, titles in queues:
            while titles:
                title = titles.pop(0)
                if title.lower() not in seen:
                    seen.add(title.lower())
                    chosen.append(Headline(title, name))
                    break
            if len(chosen) == count:
                break
    return chosen


def fetch(cfg, session, now) -> Headlines:
    by_source: Dict[str, List[str]] = {}
    for number, feed in enumerate(cfg.news.feeds, 1):
        try:
            by_source[feed.name] = parse_feed(http.get_public(session, feed.url, FEED_SECONDS).content)
        except Exception as exc:  # one dead feed must not cost us the others
            log.warning("news feed %d failed: %s", number, http.trace(exc))
    headlines = Headlines(pick(by_source, cfg.news.count))
    headlines.missing = [feed.name for feed in cfg.news.feeds if not by_source.get(feed.name)]
    if not headlines:
        raise RuntimeError("no headlines from any feed")
    return headlines


def render(data: List[Headline], now: datetime) -> Image.Image:
    canvas = Canvas()
    canvas.heading("Headlines")
    body, source = font("semibold", 20), font("bold", 20)
    indent = PAD + body.getlength("• ")
    for item in data:
        canvas.text(PAD, canvas.y, "•", body)
        lines = wrap(item.title, body, RIGHT - indent, MAX_LINES)
        for line in lines:
            canvas.text(indent, canvas.y, line, body)
            canvas.y += line_height(body)
        # The source shares the last line when there is room for it.
        label = fit(item.source, source, WIDTH / 2)
        if indent + body.getlength(lines[-1]) + 14 + source.getlength(label) <= RIGHT:
            canvas.y -= line_height(body)
        canvas.text(RIGHT, canvas.y + line_height(body) / 2, label, source, "rm")
        canvas.y += line_height(body) + 8
    return canvas.finish()
