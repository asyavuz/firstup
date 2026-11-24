"""A sudoku, made here. The same one all day, with exactly one solution."""

from datetime import datetime
from random import Random
from typing import List, Optional

from PIL import Image

from ..pictograms import pictogram
from ..render import WIDTH, Canvas, font

CLUES, CELL = {"easy": 40, "medium": 32, "hard": 26}, 40  # hard ones may keep a few more
ALL = 0b111111111


def _solutions(grid: List[int], limit: int, rng: Optional[Random] = None) -> List[List[int]]:
    """Up to `limit` solutions, always filling the cell with the fewest choices first."""
    rows, cols, boxes = [0] * 9, [0] * 9, [0] * 9
    for i, value in enumerate(grid):
        if value:
            bit = 1 << (value - 1)
            rows[i // 9] |= bit
            cols[i % 9] |= bit
            boxes[i // 27 * 3 + i % 9 // 3] |= bit
    found: List[List[int]] = []

    def fill() -> None:
        best, choices = -1, 0
        fewest = 10
        for i in range(81):
            if not grid[i]:
                free = ALL & ~(rows[i // 9] | cols[i % 9] | boxes[i // 27 * 3 + i % 9 // 3])
                count = bin(free).count("1")
                if count < fewest:
                    best, choices, fewest = i, free, count
                    if count < 2:
                        break
        if best < 0:
            found.append(list(grid))
            return
        values = [v for v in range(1, 10) if choices >> (v - 1) & 1]
        if rng:
            rng.shuffle(values)
        r, c, b = best // 9, best % 9, best // 27 * 3 + best % 9 // 3
        for value in values:
            bit = 1 << (value - 1)
            grid[best] = value
            rows[r] |= bit
            cols[c] |= bit
            boxes[b] |= bit
            fill()
            grid[best] = 0
            rows[r] &= ~bit
            cols[c] &= ~bit
            boxes[b] &= ~bit
            if len(found) >= limit:
                return
    fill()
    return found


def make(seed: int, level: str = "medium") -> List[int]:
    rng = Random(seed)
    grid = _solutions([0] * 81, 1, rng)[0]
    left = 81
    for place in rng.sample(range(81), 81):
        if left == CLUES[level]:
            break
        kept, grid[place] = grid[place], 0
        if len(_solutions(list(grid), 2)) == 1:
            left -= 1
        else:
            grid[place] = kept
    return grid


def fetch(cfg, session, now: datetime) -> List[int]:
    return make(now.date().toordinal(), cfg.sudoku.level)


def render(data: List[int], now: datetime) -> Image.Image:
    canvas = Canvas()
    digit = font("bold", 28)
    canvas.heading("Sudoku", pictogram("grid", 34))
    top, x0 = round(canvas.y) + 6, (WIDTH - 9 * CELL) // 2
    for i in range(10):
        thick = 4 if i % 3 == 0 else 2
        for box in ([x0 + i * CELL - thick // 2, top, x0 + i * CELL + thick // 2 - 1, top + 9 * CELL],
                    [x0, top + i * CELL - thick // 2, x0 + 9 * CELL, top + i * CELL + thick // 2 - 1]):
            canvas.draw.rectangle(box, fill=0)
    for i, value in enumerate(data):
        if value:
            canvas.text(x0 + (i % 9 + .5) * CELL, top + (i // 9 + .5) * CELL, str(value), digit, "mm")
    canvas.y = top + 9 * CELL + 8
    return canvas.finish()
