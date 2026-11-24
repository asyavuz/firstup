"""Builds HTML. Everything that is not already Html is escaped, so nothing typed in or read
from a file can become markup."""

from html import escape
from typing import Iterable


class Html(str):
    """Text that is already safe to put in a page."""


def h(template: str, **values: object) -> Html:
    """Fill in a template that is written in this program, never one that is read."""
    return Html(template.format(**{name: value if isinstance(value, Html) else escape(str(value), quote=True)
                                   for name, value in values.items()}))


def join(parts: Iterable[Html]) -> Html:
    parts = list(parts)
    if not all(isinstance(part, Html) for part in parts):
        raise TypeError("only Html can be joined")
    return Html("".join(parts))


def flag(name: str, on: bool) -> Html:
    return Html(f" {name}") if on else Html("")


def options(choices: Iterable, chosen: object) -> Html:
    """`choices` are (value, label) pairs."""
    return join(h('<option value="{value}"{sel}>{label}</option>', value=value, label=label,
                  sel=flag("selected", str(value) == str(chosen))) for value, label in choices)
