"""Reads RSS in one pass that keeps nothing but the texts asked for. Building a tree would
let a small feed take minutes or hundreds of megabytes: entities, defaults and namespaces
multiply."""

import html
from typing import Dict, List, Sequence
from xml.parsers import expat

from .render import clean

MAX_ITEMS, MAX_TEXT, MAX_DEPTH = 100, 1000, 50


class Enough(Exception):
    pass


def _refuse(*args) -> None:
    raise ValueError("the feed declares things of its own")  # they can blow up to anything


def items(content: bytes, wanted: Sequence[str]) -> List[Dict[str, str]]:
    """The `wanted` texts of each item; items that miss the first one are left out."""
    found: List[Dict[str, str]] = []
    path: List[str] = []
    text: List[str] = []
    item: Dict[str, str] = {}

    def inside() -> bool:
        return len(path) == 4 and path[1:3] == ["channel", "item"] and path[3] in wanted

    def start(name, attributes) -> None:
        path.append(name)
        if len(path) > MAX_DEPTH:
            raise ValueError("the feed is nested too deeply")
        if len(path) == 3:
            item.clear()
        if inside():
            text.clear()

    def data(piece) -> None:
        if inside() and len(text) < MAX_TEXT:
            text.append(piece[:MAX_TEXT])

    def end(name) -> None:
        if inside():
            item[name] = clean(html.unescape("".join(text)[:MAX_TEXT]))
        elif len(path) == 3 and path[1:] == ["channel", "item"] and item.get(wanted[0]):
            found.append(dict(item))
            if len(found) == MAX_ITEMS:
                raise Enough
        path.pop()

    parser = expat.ParserCreate()  # without namespaces
    parser.EntityDeclHandler = parser.AttlistDeclHandler = _refuse
    parser.StartElementHandler, parser.CharacterDataHandler, parser.EndElementHandler = start, data, end
    try:
        parser.Parse(content, True)
    except Enough:
        pass
    return found
