"""How big the interface is.

One source of every grid number: the cover's side, the card's frame around it,
the gap between two cards, the page's margins.  The pages ask by they want (a
tight left-aligned grid of at most four covers a row); nothing else in the
interface re-derives a size from its own constants, so the card, the column
count and the scroll math can never disagree.

DPR is Qt's business (a physical-pixel affair); the player's multiplier applies
once, here, through `user_scale`.
"""
from __future__ import annotations

SMALL_SCREEN_MAX = 600     # the short side of the screen, logical pixels

# The library grid, logical pixels at ui scale 1 — a compact left-aligned grid,
# the size band the review asked for (cover 112–128, card 144–152, gap 12–16).
COVER = 120                # a cover's side
CARD_PAD = 15              # the card's frame on each side of the cover
GAP = 14                   # the gap between two cards, across and down
MARGIN = 22                # the page's margins, all around
MAX_COLUMNS = 4            # four a row at the most; a narrow window shows fewer
DOCK_RESERVE = 84          # the air under the last row for the action panel


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


def cell_size(scale: float = 1.0) -> int:
    """A card's outer width: the cover, its frame on both sides — the one number
    every grid question starts from."""
    return round((COVER + 2 * CARD_PAD) * scale)


def gap(scale: float = 1.0) -> int:
    """The gap between two cards at the player's scale."""
    return round(GAP * scale)


def columns(content_width: int, scale: float, small: bool = False) -> int:
    """How many cards fit in a content width (the width between the page's own
    margins, not the window's): at most four, two on a phone-sized screen.  The
    remainder stays on the right and the bottom — the grid is left-aligned and
    never spreads its cards to fill the window."""
    cell = cell_size(scale)
    usable = max(cell, content_width)
    count = (usable + gap(scale)) // (cell + gap(scale))
    count = min(int(count), MAX_COLUMNS)
    return min(count, 2) if small else count
