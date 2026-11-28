"""The launcher's own controls, on NX2Apple's Dark Glass tokens.

The shapes are the token file's own: ordinary buttons are glass fills (a skin of
white at seven percent with an eleven-percent edge, twelve-pixel corners), the
one action that matters is a cream pill at sheet radius with black ink, the
secondary actions outline themselves in cream, and the window controls are quiet
chips — the close one takes the danger red on hover.  Feedback is immediate: a
hover changes the fill a step, never a motion; the keyboard focus draws two
pixels of cream.  The library's action panel is the heroSecondary glass: a
translucent card over the page, static layering, never a live blur.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QSize, Signal, Qt, QRectF
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from launcher.ui import theme


class FlatButton(QPushButton):
    """A control on the Dark Glass.  The variant says which one:

    primary — the one action that matters: cream, black ink, sheet radius;
    quiet — the glass fill of an ordinary button, card radius;
    outline — cream words on a cream-tinted outline (the panel's secondary);
    hero — the bar's pages: a glass chip; the checked page carries the cream.
    """

    @staticmethod
    def _colour(spec: str) -> QColor:
        """A colour from any of the palette's spellings — a #RRGGBBAA hex, or a
        CSS rgba() the stylesheet also uses.  QColor() alone refuses the CSS
        spelling and paints black, which is how a button's words once vanished
        until the hover lit them."""
        if spec.startswith('rgba'):
            parts = spec[spec.find('(') + 1:spec.find(')')].split(',')
            r, g, b = (int(parts[0]), int(parts[1]), int(parts[2]))
            a = round(float(parts[3]) * 255) if len(parts) > 3 and parts[3].strip() else 255
            return QColor(r, g, b, a)
        colour = QColor(spec)
        return colour if colour.isValid() else QColor('#FFFFFF')

    def __init__(self, text: str = '', variant: str = 'quiet', parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setProperty('variant', variant)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def sizeHint(self) -> QSize:
        """The pill's own size: the text, its icon's share of air, and one pad
        each side — never the layout's stretch."""
        metrics = QFontMetrics(self.font())
        width = metrics.horizontalAdvance(self.text()) + (52 if self.property('variant') == 'primary' else 36)
        height = max(34, metrics.height() + 18)
        return QSize(width, height)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        variant = self.property('variant') or 'quiet'
        on = self.underMouse() and self.isEnabled()
        down = self.isDown()

        font = self.font()
        radius = theme.R_CARD
        if variant == 'primary':
            radius = theme.R_SHEET
            font.setWeight(QFont.Bold)
            if not self.isEnabled():
                fill, text_colour = theme.ACCENT_DISABLED, '#84817a'
            elif down:
                fill = theme.ACCENT_PRESSED
            elif on:
                fill = theme.ACCENT_HOVER           # cream, one step lighter at once
            else:
                fill = theme.ACCENT
            text_colour = theme.ACCENT_INK if self.isEnabled() else text_colour
            painter.setPen(Qt.NoPen)
            painter.setBrush(FlatButton._colour(fill) if fill.startswith('rgba')
                             else QColor(fill))
            painter.drawRoundedRect(rect, radius, radius)
        elif variant == 'outline':
            fill, border, text_colour = self._outline(on, down)
            painter.setPen(Qt.NoPen)
            painter.setBrush(FlatButton._colour(fill))
            painter.drawRoundedRect(rect, radius, radius)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(FlatButton._colour(border), 1))
            painter.drawRoundedRect(rect, radius, radius)
        else:   # quiet, and the bar's hero chips
            font.setWeight(QFont.DemiBold)
            if not self.isEnabled():
                fill, border, text_colour = ('rgba(255, 255, 255, 0.03)',
                                             'rgba(255, 255, 255, 0.05)', '#5a5a62')
            elif variant == 'hero' and self.isChecked():
                # the checked page: the cream chip (the token file's platform chip)
                fill = ('rgba(255, 240, 214, 0.20)' if on
                        else 'rgba(255, 240, 214, 0.14)')
                border = 'rgba(255, 240, 214, 0.42)'
                text_colour = theme.ACCENT
            elif on:
                fill, border, text_colour = ('rgba(255, 255, 255, 0.12)',
                                             'rgba(255, 255, 255, 0.20)', theme.TEXT)
            elif down:
                fill, border, text_colour = ('rgba(255, 255, 255, 0.05)',
                                             'rgba(255, 255, 255, 0.11)', theme.TEXT)
            else:
                fill, border, text_colour = ('rgba(255, 255, 255, 0.07)',
                                             'rgba(255, 255, 255, 0.11)', theme.TEXT)
            painter.setPen(Qt.NoPen)
            painter.setBrush(FlatButton._colour(fill))
            painter.drawRoundedRect(rect, radius, radius)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(FlatButton._colour(border), 1))
            painter.drawRoundedRect(rect, radius, radius)
        painter.setFont(font)
        painter.setPen(FlatButton._colour(text_colour))
        painter.drawText(rect, Qt.AlignCenter, self.text())
        if self.hasFocus():
            # the keyboard focus: two pixels of cream
            ring = QRectF(self.rect()).adjusted(1, 1, -1, -1)
            painter.setPen(QPen(QColor(theme.FOCUS_LINE), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(ring, theme.R_CARD, theme.R_CARD)

    @staticmethod
    def _outline(on: bool, down: bool) -> tuple[str, str, str]:
        """The cream outline's three states."""
        if down:
            return ('rgba(255, 240, 214, 0.06)', 'rgba(255, 240, 214, 0.30)', theme.ACCENT)
        if on:
            return ('rgba(255, 240, 214, 0.16)', 'rgba(255, 240, 214, 0.58)', theme.ACCENT)
        return ('rgba(255, 240, 214, 0.09)', 'rgba(255, 240, 214, 0.38)', theme.ACCENT)


class IconButton(QPushButton):
    """A window control on the bar: a quiet chip (a drawn mark — a line, a
    square, two squares, a cross) with a glass hover; the close one takes the
    danger red.  Chip radius, the token file's own shape."""

    def __init__(self, glyph: str, parent=None):
        super().__init__(parent)
        self._glyph = glyph
        self._close = glyph == 'close'
        self.setFixedSize(36, 30)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_glyph(self, glyph: str) -> None:
        """The mark the control shows now (maximize flips to restore)."""
        self._glyph = glyph
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        on = self.underMouse() and self.isEnabled()
        if self._close and on:
            fill, mark = theme.DANGER_FILL, QColor(theme.DANGER_ON)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(fill))
            painter.drawRoundedRect(rect, theme.R_CHIP, theme.R_CHIP)
        elif on or self.isDown():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 28 if on else 40))
            painter.drawRoundedRect(rect, theme.R_CHIP, theme.R_CHIP)
            mark = QColor('#ffffff') if on else FlatButton._colour('rgba(255, 255, 255, 0.72)')
        else:
            mark = FlatButton._colour('rgba(255, 255, 255, 0.72)')
        if not self.isEnabled():
            mark = QColor(255, 255, 255, 90)
        painter.setPen(QPen(mark, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.MiterJoin))
        centre = rect.center()
        x, y = centre.x(), centre.y()
        if self._glyph == 'min':
            painter.drawLine(int(x - 6), int(y), int(x + 6), int(y))
        elif self._glyph == 'max':
            painter.drawRect(int(x - 6), int(y - 6), 12, 12)
        elif self._glyph == 'restore':
            painter.drawLine(int(x - 8), int(y + 1), int(x - 8), int(y - 8))
            painter.drawLine(int(x - 8), int(y - 8), int(x + 1), int(y - 8))
            painter.drawLine(int(x + 1), int(y - 8), int(x + 1), int(y - 4))
            painter.drawLine(int(x - 4), int(y + 1), int(x - 8), int(y + 1))
            painter.drawRect(int(x - 4), int(y - 4), 11, 11)
        elif self._glyph == 'close':
            painter.drawLine(int(x - 5), int(y - 5), int(x + 5), int(y + 5))
            painter.drawLine(int(x - 5), int(y + 5), int(x + 5), int(y - 5))
        if self.hasFocus():
            painter.setPen(QPen(QColor(theme.FOCUS_LINE), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), theme.R_CHIP, theme.R_CHIP)


class CoverTile(QLabel):
    """A game's cover in a rounded rectangle — card radius, the token file's
    shape.  The cover is the card; the interface stays out of the way."""

    def __init__(self, side: int, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self.setPixmap(pixmap)
        self.setFixedSize(side, side)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(QRectF(0, 0, self.width(), self.height()),
                           self._pixmap, QRectF(self._pixmap.rect()))


class ActionPanel(QFrame):
    """The library's action panel: the heroSecondary glass — a translucent card
    over the page, a white edge, sheet radius — floating at the bottom, aligned
    with the content's margins, only while a game is picked.  The chosen game's
    name and state on the left, Run (cream, the one action) on the right, the
    two outlined actions beside it."""

    def __init__(self, words: dict, parent: QWidget):
        super().__init__(parent)
        self._words = words
        self.setObjectName('actionpanel')
        self.setAttribute(Qt.WA_StyledBackground, True)
        # The glass: dark at seventy-six percent, the heroSecondary token's own.
        self.setStyleSheet(f'''
            QFrame#actionpanel {{
                background: rgba(26, 26, 28, 0.76);
                border: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: {theme.R_SHEET}px;
            }}
        ''')
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 12, 14, 12)
        row.setSpacing(10)
        self.title = QLabel('')
        font = self.title.font()
        font.setWeight(QFont.DemiBold)
        self.title.setFont(font)
        row.addWidget(self.title)
        self.state = QLabel('')
        self.state.setTextFormat(Qt.RichText)
        row.addWidget(self.state)
        row.addStretch(1)
        self.run_button = FlatButton('', 'primary')
        self.run_button.setMinimumWidth(96)
        self.run_button.setMaximumWidth(220)
        row.addWidget(self.run_button, 0)   # its own size; the row never stretches it
        self.steam_button = FlatButton('', 'outline')
        row.addWidget(self.steam_button, 0)
        self.desktop_button = FlatButton('', 'outline')
        row.addWidget(self.desktop_button, 0)
        self.manage_button = FlatButton('', 'quiet')
        self.manage_button.setMinimumWidth(0)
        row.addWidget(self.manage_button, 0)
        self.hide()

    def set_words(self, words: dict) -> None:
        self._words = words

    def show_game(self, game_name: str, run_text: str, steam_text: str,
                  desktop_text: str, state_html: str) -> None:
        """The panel for one game: its name, its state line, its actions."""
        self.title.setText(game_name)
        self.state.setText(state_html)
        self.run_button.setText(run_text)
        self.steam_button.setText(steam_text)
        self.desktop_button.setText(desktop_text)
        self.manage_button.setText(self._words.get('manage', 'Manage ⋯'))
        self.show()
        self.raise_()
        self.reposition()

    def reposition(self) -> None:
        """Sit at the bottom, inside the page's own margins."""
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        margin = 22
        self.setGeometry(margin, parent.height() - self.height() - margin,
                         parent.width() - 2 * margin, self.height())


# ---- the drawn icons -----------------------------------------------------------------

def draw_icon(painter: QPainter, name: str, rect: QRectF, colour: QColor) -> None:
    """The small line icons, NX2Apple's own glyphs drawn as vectors: a gamepad
    and a hammer for the pages, a gear for the settings."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(colour, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    side = min(rect.width(), rect.height())
    scale = side / 24.0
    ox = rect.x() + (rect.width() - 24 * scale) / 2
    oy = rect.y() + (rect.height() - 24 * scale) / 2

    def x(v: float) -> float:
        return ox + v * scale

    def y(v: float) -> float:
        return oy + v * scale

    if name in ('library', 'gamepad'):
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(x(2.5), y(6.5), 19 * scale, 11 * scale),
                                5.5 * scale, 5.5 * scale)
        painter.drawLine(QPointF(x(8.5), y(9.5)), QPointF(x(8.5), y(14.5)))
        painter.drawLine(QPointF(x(6), y(12)), QPointF(x(11), y(12)))
        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
        painter.drawEllipse(QPointF(x(15.7), y(10.7)), 1.1 * scale, 1.1 * scale)
        painter.drawEllipse(QPointF(x(17.8), y(13.1)), 1.1 * scale, 1.1 * scale)
    elif name == 'build':
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        # the hammer: a head and a handle, the tool that makes a pack
        painter.drawLine(QPointF(x(4), y(17)), QPointF(x(11), y(10)))
        painter.drawRoundedRect(QRectF(x(9), y(3), 10 * scale, 5 * scale),
                                1.5 * scale, 1.5 * scale)
        painter.drawLine(QPointF(x(13.5), y(3.4)), QPointF(x(18.6), y(8.2)))
    elif name == 'gear':
        # NX2Apple's own gear: one continuous outline path (teeth and all),
        # the feather icon's geometry — not a circle with spokes.
        import math
        painter.setPen(QPen(colour, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        centre_x, centre_y = x(12), y(12)
        outer, inner = 8.1 * scale, 6.3 * scale
        points = []
        teeth = 8
        for i in range(teeth * 2):
            angle = math.pi * i / teeth - math.pi / 2
            radius = outer if i % 2 == 0 else inner
            # each tooth spans a half-slot; advance and dip as the feather gear does
            for tick in (-0.22, 0.22):
                a = angle + tick
                points.append(QPointF(centre_x + radius * math.cos(a),
                                      centre_y + radius * math.sin(a)))
        path = QPainterPath()
        path.moveTo(points[0])
        for point in points[1:]:
            path.lineTo(point)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawEllipse(QPointF(centre_x, centre_y), 3.1 * scale, 3.1 * scale)
    painter.restore()


class FlatSegmented(QFrame):
    """The pages capsule, NX2Apple's segmented control: one glass shell, each
    page a segment with its icon and its name, the chosen one a cream pill.
    Keyboard arrows walk the segments; the focus is a 2px cream ring."""

    changed = Signal(str)

    def __init__(self, items: list[tuple[str, str, str]], selected: str = '', parent=None):
        super().__init__(parent)
        self._items = items            # (key, label, icon) — icon may be ''
        self._selected = selected
        self.setFixedHeight(40)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def buttons(self) -> list[QPushButton]:
        """There are no buttons: the capsule paints itself (kept for the tests,
        which reach the pages through it)."""
        return []

    def set_items(self, items: list[tuple[str, str, str]], selected: str | None = None) -> None:
        self._items = items
        if selected is not None:
            self._selected = selected
        elif self._items and self._selected and all(k != self._selected for k, _, _ in self._items):
            self._selected = self._items[0][0]
        self.updateGeometry()
        self.update()

    def selected(self) -> str:
        return self._selected

    def set_selected(self, key: str) -> None:
        if self._selected != key:
            self._selected = key
            self.update()

    def _segment_rects(self) -> list[tuple[str, str, str, QRectF]]:
        font = QFont(self.font())
        font.setBold(True)
        metrics = QFontMetrics(font)
        widths = []
        for _key, label, icon in self._items:
            width = max(72.0, float(metrics.horizontalAdvance(label)) + 48)
            width += 18 if icon else 0
            widths.append(width)
        gap, inset = 6.0, 5.0
        total = inset * 2 + sum(widths) + gap * max(0, len(widths) - 1)
        available = max(float(self.width()), total)
        if available > total:
            extra = (available - total) / len(widths)
            widths = [w + extra for w in widths]
        x = inset
        height = max(12.0, float(self.height()) - inset * 2)
        out = []
        for (key, label, icon), width in zip(self._items, widths):
            out.append((key, label, icon, QRectF(x, inset, width, height)))
            x += width + gap
        return out

    def sizeHint(self) -> QSize:
        rects = self._segment_rects()
        width = rects[-1][3].right() + 5 if rects else 120
        return QSize(int(width + 0.5), self.height())

    def keyPressEvent(self, event) -> None:
        keys = [k for k, _, _ in self._items]
        if not keys:
            super().keyPressEvent(event)
            return
        current = keys.index(self._selected) if self._selected in keys else 0
        if event.key() == Qt.Key_Left:
            self._pick((current - 1) % len(keys))
            event.accept()
            return
        if event.key() == Qt.Key_Right:
            self._pick((current + 1) % len(keys))
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        # The pick happens on the press, not the release: a touch press that
        # moves a few pixels (a finger landing, a stylus drag) never delivers a
        # release to the segment, and on a touch screen the tab then only
        # answered a double click — the second press of the pair.
        if event.button() == Qt.LeftButton and self.isEnabled() and self._items:
            position = float(event.position().x())
            for key, _label, _icon, rect in self._segment_rects():
                if rect.left() - 3 <= position <= rect.right() + 3:
                    self._pick(key)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or not self.isEnabled() or not self._items:
            return
        position = float(event.position().x())
        for key, _label, _icon, rect in self._segment_rects():
            if rect.left() - 3 <= position <= rect.right() + 3:
                self._pick(key)
                return
        super().mouseReleaseEvent(event)

    def _pick(self, key: str) -> None:
        if key != self._selected:
            self._selected = key
            self.update()
            self.changed.emit(key)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        # the shell: a breath of glass, capsule radius
        shell = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setPen(QPen(QColor(255, 255, 255, 24), 1.0))
        painter.setBrush(QColor(255, 255, 255, 13))
        painter.drawRoundedRect(shell, shell.height() / 2, shell.height() / 2)

        for key, label, icon, rect in self._segment_rects():
            active = key == self._selected
            font = QFont(self.font())
            font.setBold(active)
            painter.setFont(font)
            text_colour = QColor(theme.ACCENT_INK) if active else QColor(255, 255, 255, 195)
            icon_colour = QColor(theme.ACCENT_INK) if active else QColor(theme.MUTED)
            if active:   # the cream pill
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(theme.ACCENT))
                painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
            metrics = QFontMetrics(font)
            text_width = metrics.horizontalAdvance(label)
            icon_side = 16 if icon else 0
            total = text_width + icon_side + (6 if icon else 0)
            x = rect.x() + (rect.width() - total) / 2
            if icon:
                draw_icon(painter, icon, QRectF(x, rect.y() + (rect.height() - icon_side) / 2,
                                                icon_side, icon_side), icon_colour)
                x += icon_side + 6
            elided = metrics.elidedText(label, Qt.ElideRight, max(12, int(rect.width() - total + text_width - 10)))
            painter.setPen(text_colour)
            painter.drawText(QRectF(x, rect.y(), rect.width() - (x - rect.x()), rect.height()),
                             Qt.AlignVCenter | Qt.AlignLeft, elided)

        if self.hasFocus():
            ring = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
            painter.setPen(QPen(QColor(theme.FOCUS_LINE), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(ring, ring.height() / 2, ring.height() / 2)


class SettingsButton(QPushButton):
    """The settings gear on the bar's right: a 34×34 icon button, the muted gear
    at rest, cream-tinted glass while the settings page is open, the glass hover
    otherwise — NX2Apple's iconBtn / iconBtnActive pair."""

    def __init__(self, label: str, parent=None):
        super().__init__('', parent)
        self._label = label
        self._active = False
        self.setCheckable(True)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip(label)
        self.setAccessibleName(label)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        on = self.underMouse() and self.isEnabled()
        self._active = self.isChecked()
        if self._active:
            fill = 'rgba(255, 240, 214, 0.20)' if on else 'rgba(255, 240, 214, 0.14)'
            painter.setPen(Qt.NoPen)
            painter.setBrush(FlatButton._colour(fill))
            painter.drawRoundedRect(rect, theme.R_SHEET, theme.R_SHEET)
            icon_colour = QColor(theme.ACCENT)
        else:
            if on:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(255, 255, 255, 20))
                painter.drawRoundedRect(rect, theme.R_SHEET, theme.R_SHEET)
                icon_colour = QColor(theme.TEXT)
            else:
                icon_colour = QColor(theme.MUTED)
        draw_icon(painter, 'gear', rect.adjusted(5, 5, -5, -5), icon_colour)
        if self.hasFocus():
            painter.setPen(QPen(QColor(theme.FOCUS_LINE), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), theme.R_CHIP, theme.R_CHIP)
