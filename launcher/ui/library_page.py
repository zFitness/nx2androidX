"""The library page: the ported games, in a grid of cards.

The grid's width decides how many cards fit; on a phone-sized screen it never shows
more than two.  The cards show the game's icon, its name and its version, and the
things a player does with a game: run it, or put it in Steam's library and the
system's app menu.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from launcher import launch, library, scale, settings, steam
from launcher.ui import clear_layout, dialogs

ICON_SIZE = 96


class LibraryPage(QWidget):
    """The games in the data directory."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.words = app.words
        self.cards: list[QWidget] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroller = QScrollArea()
        self.scroller.setWidgetResizable(True)
        self.scroller.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(self.scroller)
        self.inner = QWidget()
        self.scroller.setWidget(self.inner)
        self.grid = QGridLayout(self.inner)
        self.grid.setContentsMargins(16, 16, 16, 16)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(12)

        self.refresh()

    def resizeEvent(self, event) -> None:
        """The width decides how many cards fit; a phone-sized screen never gets more
        than two (the rule a free-flowing grid would break on a wide window)."""
        super().resizeEvent(event)
        self.reflow(self.scroller.viewport().width())

    # ---- the layout ------------------------------------------------------------------

    def rebuild(self) -> None:
        """The page is built again (the settings changed)."""
        self.words = self.app.words   # the language may have changed with the settings
        self.refresh()

    def refresh(self) -> None:
        """Read the library again and show what is in it."""
        clear_layout(self.grid)
        self.cards = []
        games = library.scan(settings.library_dir(self.app.settings))
        if not games:
            label = QLabel(self.words['library_empty'])
            label.setWordWrap(True)
            self.grid.addWidget(label, 0, 0, 1, 1, Qt.AlignTop | Qt.AlignHCenter)
            return
        for game in games:
            self.cards.append(self.card(game))
        self.reflow(self.scroller.viewport().width())

    def columns(self, width: int) -> int:
        """How many cards fit in this width."""
        return scale.columns(width, 1.0, self.app.small)

    def reflow(self, width: int) -> None:
        """The cards again, in the columns that fit now (the cards themselves are
        kept: only their places in the grid change)."""
        count = self.columns(width)
        while self.grid.count():
            self.grid.takeAt(0)
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // count, index % count)

    def card(self, game: library.Game) -> QWidget:
        """One game: its icon, its name, and what a player can do with it."""
        box = QWidget()
        box.setMinimumWidth(220)
        layout = QVBoxLayout(box)
        layout.setSpacing(6)

        layout.addWidget(self.make_icon(game), 0, Qt.AlignLeft | Qt.AlignTop)

        title = QLabel(game.name)
        title.setWordWrap(True)
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title, 0, Qt.AlignLeft | Qt.AlignTop)

        if game.version:
            version = QLabel(game.version)
            version.setStyleSheet('color: #757575')
            layout.addWidget(version, 0, Qt.AlignLeft | Qt.AlignTop)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        run = QPushButton(self.words['run'])
        run.clicked.connect(lambda _checked=False, g=game: self.run_game(g))
        buttons.addWidget(run)
        steam_button = QPushButton(self.words['remove_steam'] if self.in_steam(game)
                                   else self.words['add_steam'])
        steam_button.clicked.connect(lambda _checked=False, g=game: self.toggle_steam(g))
        buttons.addWidget(steam_button)
        has_desktop = steam.desktop_entry_path(game.title_id).is_file()
        desktop_button = QPushButton(self.words['remove_desktop'] if has_desktop
                                     else self.words['add_desktop'])
        desktop_button.clicked.connect(lambda _checked=False, g=game: self.toggle_desktop(g))
        buttons.addWidget(desktop_button)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return box

    def make_icon(self, game: library.Game) -> QWidget:
        """The game's icon, or its first letter when the icon cannot be read."""
        image = QPixmap(str(game.icon_path)) if game.icon_path.is_file() else QPixmap()
        if not image.isNull():
            icon = QLabel()
            icon.setPixmap(image.scaled(ICON_SIZE, ICON_SIZE, Qt.KeepAspectRatio,
                                        Qt.SmoothTransformation))
            icon.setFixedSize(QSize(ICON_SIZE, ICON_SIZE))
            return icon
        frame = QFrame()
        frame.setFixedSize(QSize(ICON_SIZE, ICON_SIZE))
        letter = QLabel((game.name[:1] or '?').upper())
        letter_font = letter.font()
        if letter_font.pointSize() > 0:
            letter_font.setPointSize(letter_font.pointSize() * 2)
            letter.setFont(letter_font)
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.addWidget(letter, 0, Qt.AlignCenter)
        return frame

    # ---- what a player does -----------------------------------------------------------

    def run_game(self, game: library.Game) -> None:
        words = self.app.words
        try:
            launch.start(game)
        except launch.NoExecutable:
            dialogs.message(self, words['app_title'], words['no_executable'])
            return
        except OSError as error:
            dialogs.message(self, words['app_title'], words['game_failed'].format(error=error),
                            'error')
            return
        dialogs.message(self, words['app_title'], words['game_started'].format(name=game.name))

    def in_steam(self, game: library.Game) -> bool:
        return steam.find_shortcut(game.name) is not None

    def toggle_steam(self, game: library.Game) -> None:
        words = self.app.words
        if self.in_steam(game):
            try:
                removed = steam.remove_shortcut(game.name)
            except (OSError, ValueError) as error:
                dialogs.message(self, words['app_title'], words['steam_failed'].format(error=error),
                                'error')
                return
            dialogs.message(self, words['app_title'],
                            words['steam_removed'] if removed else words['steam_no_shortcuts'])
            self.refresh()
            return
        if steam.steam_root() is None:
            dialogs.message(self, words['app_title'], words['steam_missing'])
            return
        if steam.steam_running():
            dialogs.message(self, words['app_title'], words['steam_running'], 'warning')
            return
        try:
            script = launch.write_script(game)
            entry = steam.shortcut_entry(game.name, str(script), str(game.path),
                                         icon=str(game.icon_path) if game.icon_path.is_file() else '')
            steam.add_shortcut(entry)
        except launch.NoExecutable:
            dialogs.message(self, words['app_title'], words['no_executable'])
            return
        except (OSError, ValueError) as error:
            dialogs.message(self, words['app_title'], words['steam_failed'].format(error=error),
                            'error')
            return
        dialogs.message(self, words['app_title'], words['steam_added'])
        self.refresh()

    def toggle_desktop(self, game: library.Game) -> None:
        """The desktop entry: the game shows up in the system's app menu."""
        words = self.app.words
        path = steam.desktop_entry_path(game.title_id)
        if path.is_file():
            steam.remove_desktop_entry(game.title_id)
            dialogs.message(self, words['app_title'], words['desktop_removed'])
            self.refresh()
            return
        try:
            script = launch.write_script(game)
            steam.write_desktop_entry(game.title_id, game.name, script,
                                      game.icon_path if game.icon_path.is_file() else None)
        except launch.NoExecutable:
            dialogs.message(self, words['app_title'], words['no_executable'])
            return
        except (OSError, ValueError) as error:
            dialogs.message(self, words['app_title'], words['desktop_failed'].format(error=error),
                            'error')
            return
        dialogs.message(self, words['app_title'], words['desktop_added'])
        self.refresh()
