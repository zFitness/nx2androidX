"""The window's own top bar, and the frame a frameless window needs.

The bar is the NX2Apple shape: a balanced three-column row — the brand on the
left, the segmented pages capsule dead centre (library and build, each with its
icon), the settings gear and the three window controls on the right — so the
navigation stays centred on a wide window and never crowds the edges on a
narrow one.

Moving and resizing go through the system wherever the platform allows it:
Qt's startSystemMove / startSystemResize, which on Wayland are the only way (a
client may not set its own geometry there).  Where the system call is refused,
and the platform does allow a client to move itself (X11, the ordinary desktops),
we fall back to doing it by hand; under a compositor that refuses both there is
simply nothing to do, and the bar stays a bar — nothing assumes a window
manager's behaviour from absolute coordinates.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout,
                               QLabel, QPushButton, QSizePolicy, QWidget)

from launcher.ui import theme
from launcher.ui.widgets import FlatSegmented, IconButton, SettingsButton

MIN_RESIZE = (520, 400)       # when resizing by hand, never make the window smaller than this
GRIP = 5                      # the edge band that means "resize", in pixels
CORNER = 14                   # the corner squares, a little wider


def _manual_frame_allowed() -> bool:
    """Whether a window may set its own geometry here.  Wayland's compositor owns
    the placement: setGeometry/move do nothing (worse, some builds warn), so under
    Wayland the system call above is the only attempt."""
    return QApplication.platformName() != 'wayland'


class TitleBar(QFrame):
    """The bar: the brand left, the pages centre, the gear and the controls
    right — one row, three balanced columns."""

    def __init__(self, parent: QWidget, words: dict):
        super().__init__(parent)
        self.setObjectName('titlebar')
        self._words = words
        self._drag_offset: QPoint | None = None
        self.setFixedHeight(64)

        row = QHBoxLayout(self)
        row.setContentsMargins(20, 0, 14, 0)
        row.setSpacing(12)

        # Left column: the brand, stretchable, so the centre holds its place.
        left = QWidget(self)
        left.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        left_lay = QHBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(10)
        self.icon = QLabel()
        self.icon.setPixmap(theme.brand_pixmap(26, self.devicePixelRatioF()))
        left_lay.addWidget(self.icon)
        self.title = QLabel('nx2Arm')
        font = self.title.font()
        font.setWeight(font.weight().DemiBold)
        self.title.setFont(font)
        self.title.setStyleSheet('color: #FFFFFF; background: transparent; font-size: 15px;')
        left_lay.addWidget(self.title)
        left_lay.addStretch(1)
        row.addWidget(left, 1)

        # Centre column: the segmented capsule — 'Library' and 'Build', each
        # with its icon, the chosen one a cream pill (NX2Apple's own control).
        self.nav_seg = FlatSegmented([
            ('library', words['tab_library'], 'library'),
            ('build', words['tab_build'], 'build'),
        ], selected='library')
        row.addWidget(self.nav_seg, 0, Qt.AlignCenter)
        # Right column: the settings gear, then the window controls —
        # stretchable like the left one, so the capsule holds the centre and
        # the controls sit hard against the right edge.
        right = QWidget(self)
        right.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        right_lay = QHBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(8)
        right_lay.addStretch(1)

        self.settings_button = SettingsButton(words['tab_settings'])
        self.settings_button.clicked.connect(lambda: None)   # wired by the window
        right_lay.addWidget(self.settings_button)

        self.min_button = IconButton('min')
        self.max_button = IconButton('max')
        self.close_button = IconButton('close')
        right_lay.addWidget(self.min_button)
        right_lay.addWidget(self.max_button)
        right_lay.addWidget(self.close_button)
        row.addWidget(right, 1)

        # The window speaks to the capsule directly: titlebar.nav_seg.changed.
        self.nav_buttons = []   # retired: the capsule owns the pages now

    # ---- words -------------------------------------------------------------------------

    def refresh(self, words: dict) -> None:
        """The words again (the settings changed and the language with them)."""
        self._words = words
        self.nav_seg.set_items([
            ('library', words['tab_library'], 'library'),
            ('build', words['tab_build'], 'build'),
        ], selected=self.nav_seg.selected())
        self.settings_button.setToolTip(words['tab_settings'])
        self.settings_button.setAccessibleName(words['tab_settings'])
        self.set_maximized(self._maximized)

    # ---- the window controls ------------------------------------------------------------

    _maximized = False

    def set_maximized(self, maximized: bool) -> None:
        """The maximize control shows the state the window is in."""
        self._maximized = maximized
        self.max_button.set_glyph('restore' if maximized else 'max')
        self.max_button.setToolTip(self._words['win_restore'] if maximized
                                   else self._words['win_max'])
        self.min_button.setToolTip(self._words['win_min'])
        self.close_button.setToolTip(self._words['win_close'])

    def toggle_maximized(self) -> None:
        window = self.window()
        if window is None:
            return
        if window.windowState() & Qt.WindowMaximized:
            window.showNormal()
        else:
            window.showMaximized()

    # ---- dragging ----------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        window = self.window()
        handle = window.windowHandle() if window is not None else None
        if handle is not None and handle.startSystemMove():
            return   # the system owns the drag from here (Wayland's only way)
        if window is None or not _manual_frame_allowed():
            return
        if window.windowState() & Qt.WindowMaximized:
            return   # dragging a maximized window by hand is a mess on every WM
        self._drag_offset = (event.globalPosition().toPoint()
                             - window.frameGeometry().topLeft())
        self.grabMouse()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and self.window() is not None:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self.releaseMouse()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.toggle_maximized()
            return
        super().mouseDoubleClickEvent(event)


class EdgeGrip(QWidget):
    """A transparent band on the window's edge: pressing it starts a resize, by
    the system's own protocol where there is one, otherwise by hand."""

    def __init__(self, window: QWidget, edges: Qt.Edges):
        super().__init__(window)
        self._edges = edges
        self._start_pos: QPoint | None = None
        self._start_rect: QRect | None = None
        cursor = Qt.ArrowCursor
        left = bool(edges & Qt.LeftEdge)
        right = bool(edges & Qt.RightEdge)
        top = bool(edges & Qt.TopEdge)
        bottom = bool(edges & Qt.BottomEdge)
        if left and not top and not bottom:
            cursor = Qt.SizeHorCursor
        elif right and not top and not bottom:
            cursor = Qt.SizeHorCursor
        elif top and not left and not right:
            cursor = Qt.SizeVerCursor
        elif bottom and not left and not right:
            cursor = Qt.SizeVerCursor
        elif (top and left) or (bottom and right):
            cursor = Qt.SizeFDiagCursor
        else:
            cursor = Qt.SizeBDiagCursor
        self.setCursor(cursor)
        self.setFocusPolicy(Qt.NoFocus)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return
        window = self.window()
        handle = window.windowHandle() if window is not None else None
        if handle is not None and handle.startSystemResize(self._edges):
            return
        if window is None or not _manual_frame_allowed():
            return
        if window.windowState() & Qt.WindowMaximized:
            return
        self._start_pos = event.globalPosition().toPoint()
        self._start_rect = window.geometry()
        self.grabMouse()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._start_rect is None or self._start_pos is None or self.window() is None:
            return
        delta = event.globalPosition().toPoint() - self._start_pos
        rect = QRect(self._start_rect)
        min_w, min_h = MIN_RESIZE
        if self._edges & Qt.LeftEdge:
            rect.setLeft(min(rect.left() + delta.x(), rect.right() - min_w + 1))
        if self._edges & Qt.TopEdge:
            rect.setTop(min(rect.top() + delta.y(), rect.bottom() - min_h + 1))
        if self._edges & Qt.RightEdge:
            rect.setRight(max(rect.right() + delta.x(), rect.left() + min_w - 1))
        if self._edges & Qt.BottomEdge:
            rect.setBottom(max(rect.bottom() + delta.y(), rect.top() + min_h - 1))
        self.window().setGeometry(rect)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._start_rect is not None:
            self._start_rect = None
            self._start_pos = None
            self.releaseMouse()
            return
        super().mouseReleaseEvent(event)


class WindowGrips(QWidget):
    """The eight bands around the window, kept on the edges and out of the way."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self.top = EdgeGrip(window, Qt.Edges(Qt.TopEdge))
        self.bottom = EdgeGrip(window, Qt.Edges(Qt.BottomEdge))
        self.left = EdgeGrip(window, Qt.Edges(Qt.LeftEdge))
        self.right = EdgeGrip(window, Qt.Edges(Qt.RightEdge))
        self.top_left = EdgeGrip(window, Qt.Edges(Qt.TopEdge | Qt.LeftEdge))
        self.top_right = EdgeGrip(window, Qt.Edges(Qt.TopEdge | Qt.RightEdge))
        self.bottom_left = EdgeGrip(window, Qt.Edges(Qt.BottomEdge | Qt.LeftEdge))
        self.bottom_right = EdgeGrip(window, Qt.Edges(Qt.BottomEdge | Qt.RightEdge))
        self._all = (self.top, self.bottom, self.left, self.right,
                     self.top_left, self.top_right, self.bottom_left, self.bottom_right)
        for grip in self._all:
            grip.setAttribute(Qt.WA_TransparentForMouseEvents, False)
            grip.raise_()
        window.installEventFilter(self)
        self.reposition()

    def reposition(self) -> None:
        width, height = self._window.width(), self._window.height()
        self.top.setGeometry(QRect(QPoint(GRIP, 0), QPoint(width - GRIP, GRIP)))
        self.bottom.setGeometry(QRect(QPoint(GRIP, height - GRIP),
                                      QPoint(width - GRIP, height)))
        self.left.setGeometry(QRect(QPoint(0, GRIP), QPoint(GRIP, height - GRIP)))
        self.right.setGeometry(QRect(QPoint(width - GRIP, GRIP),
                                     QPoint(width, height - GRIP)))
        self.top_left.setGeometry(QRect(QPoint(0, 0), QPoint(CORNER, CORNER)))
        self.top_right.setGeometry(QRect(QPoint(width - CORNER, 0), QPoint(width, CORNER)))
        self.bottom_left.setGeometry(QRect(QPoint(0, height - CORNER),
                                           QPoint(CORNER, height)))
        self.bottom_right.setGeometry(QRect(QPoint(width - CORNER, height - CORNER),
                                            QPoint(width, height)))
        for grip in self._all:
            grip.raise_()

    def eventFilter(self, watched, event) -> bool:
        if watched is self._window and event.type() == event.Type.Resize:
            self.reposition()
        return False
