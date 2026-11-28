"""The window: the top bar, the two pages under it, and the settings they share.

The window carries no system chrome of its own — the bar at the top is ours, with
the brand, the two pages, the settings and the window controls (see titlebar.py
for how the frameless window is dragged and resized).  Everything visual comes
from theme.py: this file only puts the pieces in their places.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QMainWindow, QStackedWidget,
                               QVBoxLayout, QWidget)

from launcher import runner, scale, settings
from launcher.ui import text, theme
from launcher.ui.build_page import BuildPage
from launcher.ui.library_page import LibraryPage
from launcher.ui.settings_page import SettingsPage
from launcher.ui.titlebar import TitleBar, WindowGrips


class _IdleBridge(QObject):
    """The runner's async results, delivered on Qt's own loop.

    runner.run_json_async / run_text_async hand their results to the interface
    through GLib's idle loop; a Qt program runs no GLib loop, so the bridge turns
    that delivery into a signal: emitted from the worker thread, it arrives as a
    queued call on the main thread, where the interface may be touched.
    """
    call = Signal(object, object)

    def __init__(self):
        super().__init__()
        self.call.connect(lambda callback, args: callback(*args))


_BRIDGE: _IdleBridge | None = None
_BASE_FONT_SIZE = 0.0    # the application font's size before the player's multiplier


def install_idle() -> None:
    """Point the runner's idle delivery at Qt.  runner.py itself stays toolkit-free:
    the interface owns the way its results come home."""
    global _BRIDGE
    if _BRIDGE is not None:
        return
    _BRIDGE = _IdleBridge()
    runner._idle = lambda callback, *args: _BRIDGE.call.emit(callback, args)


class LauncherApp(QMainWindow):
    """The main window: our own top bar, and the two pages under it."""

    def __init__(self, current: dict | None = None):
        super().__init__()
        install_idle()
        self.settings = current if current is not None else settings.load()
        self.words = text.strings(self.settings.get('language') or 'zh')
        self.setWindowTitle(self.words['app_title'])
        self.setWindowIcon(theme.brand_icon(64))
        # The frame is ours everywhere — inside a gamescope container (the DroidDeck
        # tablet runs every AppImage through one) as on an ordinary desktop: one
        # bar, one look, no second title bar from the system.
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        # Defaults for a screen we never got to measure (no display, a headless test):
        # the pages ask for these the moment they are built.
        self.short_side = 0
        self.small = False
        self._fit_to_screen()

        application = QApplication.instance()
        if application is not None:
            theme.apply(application)   # the look goes on before the first widget

        self.titlebar = TitleBar(self, self.words)
        self.library_page = LibraryPage(self)
        self.build_page = BuildPage(self)
        self.settings_page = SettingsPage(self)   # lives in the settings dialog
        self.pages = ((self.library_page, 'library'), (self.build_page, 'build'))
        for page, _key in self.pages:
            page.setObjectName('page')
            # Every page paints its own opaque ground (the stylesheet's
            # QWidget#page rule): a plain child QWidget does not paint a QSS
            # background on its own, so the attribute goes on each page —
            # verified by rendering, not assumed.
            page.setAttribute(Qt.WA_StyledBackground, True)

        # One persistent stack, both pages created once.  A flip is Qt's own
        # setCurrentIndex and nothing else — no rebuild, no hide/show of the
        # window, no forced repaints: Qt merges the update into the next frame
        # on its own.
        self.stack = QStackedWidget()
        for page, _key in self.pages:
            self.stack.addWidget(page)

        shell = theme.styled_background(QWidget())
        shell.setObjectName('shell')
        shell.setAutoFillBackground(True)
        column = QVBoxLayout(shell)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.titlebar)
        column.addWidget(self.stack, 1)
        self.setCentralWidget(shell)

        # The pages' capsule switches the stack; the window controls close it.
        # The settings gear stays lit while its dialog is up.
        bar = self.titlebar
        bar.nav_seg.changed.connect(self._goto_page)
        bar.settings_button.clicked.disconnect()
        bar.settings_button.clicked.connect(self.open_settings)
        bar.min_button.clicked.connect(self.showMinimized)
        bar.max_button.clicked.connect(bar.toggle_maximized)
        bar.close_button.clicked.connect(self.quit)

        self.grips = WindowGrips(self)
        bar.set_maximized(False)   # the controls start with their tooltips
        self._apply_scale()

    def _goto_page(self, key: str) -> None:
        """The stack follows the capsule: setCurrentIndex, and nothing else —
        the pages are persistent, their state (form inputs, logs, scroll)
        survives every flip, and Qt schedules the paint its own way."""
        index = {'library': 0, 'build': 1}.get(key, 0)
        if index == self.stack.currentIndex():
            return
        self.stack.setCurrentIndex(index)

    def open_settings(self) -> None:
        """The settings in their own dialog: the page is the existing one, embedded.
        The gear stays lit (checked) while the dialog is up.  The page is handed
        its freedom *before* the dialog goes away (a parented widget dies with
        its parent — once that took the page with it, and the dialog could
        never be opened again)."""
        self.titlebar.settings_button.setChecked(True)
        dialog = QDialog(self)
        dialog.setWindowTitle(self.words['tab_settings'])
        row = QVBoxLayout(dialog)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.settings_page)
        # A size that follows the screen (the page scrolls inside it).
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            dialog.resize(min(760, area.width() * 4 // 5), min(640, area.height() * 4 // 5))
        else:
            dialog.resize(640, 520)
        dialog.exec()
        row.removeWidget(self.settings_page)
        self.settings_page.setParent(None)   # off the dying dialog before it dies
        dialog.close()
        dialog.deleteLater()
        self.titlebar.settings_button.setChecked(False)

    # ---- the window -------------------------------------------------------------------

    def _fit_to_screen(self) -> None:
        """The window opens maximized -- the desktop's own maximize, not a screen-sized
        window: a compositor that scales what it gets (DroidDeck's does) stretches a
        window whose size equals the screen, and the text with it. A regular default
        size covers a WM that refuses the maximize; `small` still keys off the screen's
        short side, so a phone-sized screen gets its bigger controls either way."""
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1024, 640)
            return
        area = screen.availableGeometry()
        self.resize(min(1280, max(1024, area.width() * 3 // 4)),
                    min(800, max(600, area.height() * 3 // 4)))
        self.short_side = min(area.width(), area.height())
        self.small = scale.is_small(self.short_side)

    def _apply_scale(self) -> None:
        """The interface's own size, as the player set it.

        GTK drew with the Xft DPI; Qt has no per-application DPI to turn, so the
        player's multiplier goes on the application font: every widget's size
        follows the font, and with it the touch targets.
        """
        global _BASE_FONT_SIZE
        application = QApplication.instance()
        if application is None:
            return
        font = application.font()
        if _BASE_FONT_SIZE <= 0:
            size = font.pointSizeF() if font.pointSizeF() > 0 else font.pointSize()
            _BASE_FONT_SIZE = size if size > 0 else 10.0
        font.setPointSizeF(_BASE_FONT_SIZE * scale.user_scale(self.settings.get('ui_scale')))
        application.setFont(font)
        self.titlebar.icon.setPixmap(theme.brand_pixmap(26, self.devicePixelRatioF()))

    def changeEvent(self, event) -> None:
        """The maximize control mirrors the state the window is in, however the
        state changed (our button, the bar's double-click, a WM key)."""
        if event.type() == event.Type.WindowStateChange:
            self.titlebar.set_maximized(bool(self.windowState() & Qt.WindowMaximized))
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        """The window went away (the way out, or the WM's close button): stop the
        porter.  Qt ends itself when the last window closes, so there is no main
        loop to stop here -- the process, and with it the single-instance lock,
        goes on its own."""
        self.build_page.stop_porter()
        super().closeEvent(event)

    def quit(self) -> None:
        """Leave the launcher: close the window (the close handler stops the porter,
        and the last window's close ends the application)."""
        self.close()

    # ---- what the pages ask for -------------------------------------------------------

    def refresh_library(self) -> None:
        self.library_page.refresh()

    def goto_build(self) -> None:
        """Over to the build page: the library's runtime rebuild and re-port run there,
        where the stages and the log live."""
        self.titlebar.nav_seg.set_selected('build')
        self._goto_page('build')

    def goto_settings(self) -> None:
        """Open the settings dialog: a prerequisite is missing and the dialog names it.
        The settings come back in force when the dialog closes."""
        self.open_settings()
        self.reload_settings()

    def reload_settings(self) -> None:
        """The settings were saved: the new values are in force from now on."""
        self.settings = settings.load()
        self.words = text.strings(self.settings.get('language') or 'zh')
        self.setWindowTitle(self.words['app_title'])
        self.titlebar.refresh(self.words)
        self._apply_scale()
        self.library_page.rebuild()
        self.build_page.rebuild()
        self.settings_page.rebuild()
