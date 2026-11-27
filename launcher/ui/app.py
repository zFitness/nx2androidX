"""The window: three pages and the settings they share."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QTabWidget

from launcher import appimage, runner, scale, settings
from launcher.ui import text
from launcher.ui.build_page import BuildPage
from launcher.ui.library_page import LibraryPage
from launcher.ui.settings_page import SettingsPage


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
    """The main window: the three pages under one row of tabs."""

    def __init__(self, current: dict | None = None):
        super().__init__()
        install_idle()
        self.settings = current if current is not None else settings.load()
        self.words = text.strings(self.settings.get('language') or 'zh')
        self.setWindowTitle(self.words['app_title'])
        # The frame: inside a gamescope container (the DroidDeck tablet runs every
        # AppImage through one) the container already draws the only title bar --
        # ours would be a second one -- and the maximize in __main__ fills the
        # nested display, which is the whole visible screen there.  An ordinary
        # desktop keeps the window's own decoration and its default size.
        self.setWindowFlag(Qt.FramelessWindowHint, not appimage.wants_frame())
        # Defaults for a screen we never got to measure (no display, a headless test):
        # the pages ask for these the moment they are built.
        self.short_side = 0
        self.small = False
        self._fit_to_screen()

        self.notebook = QTabWidget()
        self.setCentralWidget(self.notebook)
        # The tabs on the left, the way out on the right — the two ends of one row.
        self.quit_button = QPushButton(self.words['quit'])
        self.quit_button.clicked.connect(self.quit)
        self.notebook.setCornerWidget(self.quit_button, Qt.TopRightCorner)

        self.library_page = LibraryPage(self)
        self.build_page = BuildPage(self)
        self.settings_page = SettingsPage(self)
        self.pages = ((self.library_page, 'tab_library'), (self.build_page, 'tab_build'),
                      (self.settings_page, 'tab_settings'))
        for page, key in self.pages:
            self.notebook.addTab(page, self.words[key])

        self._apply_scale()

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

    def goto_settings(self) -> None:
        """Open the settings page: a prerequisite is missing and the dialog names it."""
        self.notebook.setCurrentWidget(self.settings_page)

    def reload_settings(self) -> None:
        """The settings were saved: the new values are in force from now on."""
        self.settings = settings.load()
        self.words = text.strings(self.settings.get('language') or 'zh')
        self.setWindowTitle(self.words['app_title'])
        self.quit_button.setText(self.words['quit'])
        self._apply_scale()
        for page, key in self.pages:
            self.notebook.setTabText(self.notebook.indexOf(page), self.words[key])
        self.library_page.rebuild()
        self.build_page.rebuild()
        self.settings_page.rebuild()
