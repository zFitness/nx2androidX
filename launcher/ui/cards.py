"""The launcher's shared card scaffolding, NX2Apple's own shapes.

`CardGroup` is the desktop launcher's rounded dark card with its quiet section
title above it; `CenteredColumn` is the page host that keeps a readable maximum
width and centres itself when the window is wider.  The pages are built from
these two, the way the Qt front end of the desktop launcher builds its own.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
                               QWidget)

from launcher.ui import theme


class CardGroup(QWidget):
    """A rounded dark card with an optional section title above and a footer
    note under it (sectionTitle / card / sectionFoot, the token stylesheet's
    own object names)."""

    def __init__(self, title: str = '', footer: str = '', parent: QWidget | None = None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        self.header_row = QHBoxLayout()
        self.header_row.setContentsMargins(4, 0, 4, 0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName('sectionTitle')
        self.header_row.addWidget(self.title_label)
        self.header_row.addStretch(1)
        outer.addLayout(self.header_row)
        self.title_label.setVisible(bool(title))

        self.card = QFrame()
        self.card.setObjectName('nxcard')
        theme.styled_background(self.card)
        self.body_layout = QVBoxLayout(self.card)
        self.body_layout.setContentsMargins(18, 13, 18, 13)
        self.body_layout.setSpacing(10)
        outer.addWidget(self.card)

        self.footer_label = QLabel(footer)
        self.footer_label.setObjectName('sectionFoot')
        self.footer_label.setWordWrap(True)
        self.footer_label.setContentsMargins(4, 0, 4, 0)
        outer.addWidget(self.footer_label)
        self.footer_label.setVisible(bool(footer))

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)
        self.title_label.setVisible(bool(title))

    def set_footer(self, footer: str) -> None:
        self.footer_label.setText(footer)
        self.footer_label.setVisible(bool(footer))

    def add_row(self, item) -> None:
        """A row into the card: a widget, or a whole layout."""
        if isinstance(item, QWidget):
            self.body_layout.addWidget(item)
        else:
            self.body_layout.addLayout(item)


class CenteredColumn(QWidget):
    """A page host that holds one column of content: it grows with the window
    and keeps at least `min_h_margin` on each side; an ordinary window is fully
    used, and the `max_width` (when one is given) only caps an unusually wide
    one."""

    def __init__(self, max_width: int = 0, min_h_margin: int = 28,
                 top_margin: int = 28, bottom_margin: int = 36, spacing: int = 20,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.max_width = max_width
        outer = QHBoxLayout(self)
        outer.setContentsMargins(min_h_margin, top_margin, min_h_margin, bottom_margin)
        outer.setSpacing(0)
        column_host = QWidget()
        column_host.setMinimumWidth(0)
        if max_width > 0:
            column_host.setMaximumWidth(max_width)
        column_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.body_col = QVBoxLayout(column_host)
        self.body_col.setContentsMargins(0, 0, 0, 0)
        self.body_col.setSpacing(spacing)
        outer.addWidget(column_host, 1)   # takes the stretch: the column IS the page


def page_title_font(scale: float) -> QFont:
    """The page heading: the desktop launcher's pageTitle (25pt 800; a hair
    smaller here so the 22–24 band the review set still holds)."""
    font = QFont()
    font.setWeight(QFont.Black)
    font.setPixelSize(max(24, round(25 * max(1.0, scale))))
    return font


def page_note_font(scale: float) -> QFont:
    """The note under a page heading (pageNote)."""
    font = QFont()
    font.setPixelSize(max(12, round(13.5 * max(1.0, scale))))
    return font
