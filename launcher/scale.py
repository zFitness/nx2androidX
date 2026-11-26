"""How big the interface is.

GTK draws with the system's own size: the Xft DPI (a phone-sized screen already has a
high one) and the theme's touch targets.  What is left for us is the player's own
multiplier, and the rule that a phone-sized screen never shows more than two cards.
"""
from __future__ import annotations

SMALL_SCREEN_MAX = 600     # the short side of the screen, logical pixels
BASE_CELL = 168            # a card's width at scale 1
SPACING = 16               # the gap between two cards


def is_small(short_side: int) -> bool:
    """A screen whose short side is at most 600 logical pixels is a phone-sized one."""
    return short_side <= SMALL_SCREEN_MAX


def user_scale(value) -> float:
    """The player's own multiplier, when it makes sense."""
    try:
        factor = float(value)
    except (TypeError, ValueError):
        return 1.0
    return factor if factor > 0 else 1.0


def cell_size(scale: float) -> int:
    """The width of a card in the library grid."""
    return max(80, round(BASE_CELL * scale))


def columns(width: int, scale: float, small: bool = False) -> int:
    """How many cards fit in this width.  A phone-sized screen never shows more than two."""
    cell = cell_size(scale)
    usable = max(cell, width - SPACING)
    count = max(1, (usable + SPACING) // (cell + SPACING))
    return min(count, 2) if small else int(count)
