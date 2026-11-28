"""The library page: the ported games, in a tight left-aligned grid of covers.

The page is one dark ground: a small headline, then the grid — up to four
covers a row (fewer when the window is narrow, two on a phone-sized screen),
packed from the first column; the remainder stays on the right and the bottom,
never spread to fill the window.  Each card is a rounded cover, its name, and
its state line; the actions live on the quiet action panel at the bottom, only
while a game is picked.

Every size comes from launcher.scale, the one source: the card, the column
count and the scroll bounds are the same numbers by construction.
"""
from __future__ import annotations

from PySide6.QtCore import QUrl, QSize, Qt
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea,
                               QVBoxLayout, QWidget)

from launcher import launch, library, scale, settings, steam
from launcher.ui import clear_layout, dialogs, theme
from launcher.ui.widgets import ActionPanel, CoverTile


class LibraryPage(QWidget):
    """The games in the data directory."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.words = app.words
        self.cards: list[QWidget] = []
        self.selected_id = ''      # the picked card (kept across a refresh)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroller = QScrollArea()
        self.scroller.setWidgetResizable(True)
        self.scroller.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(self.scroller)
        self.inner = QWidget()
        self.scroller.setWidget(self.inner)
        column = QVBoxLayout(self.inner)
        column.setContentsMargins(scale.MARGIN, 18, scale.MARGIN, scale.MARGIN)
        column.setSpacing(2)

        # The headline: the desktop launcher's pageTitle (25px, 800) and its note.
        user = scale.user_scale(self.app.settings.get('ui_scale'))
        self.headline = QLabel(self.words['library_headline'])
        self.headline.setObjectName('pageTitle')
        self.headline.setFont(theme.headline(user))
        self.subline = QLabel(self.words['library_subtitle'])
        self.subline.setObjectName('pageNote')
        self.subline.setFont(theme.subhead(user))
        self.subline.setWordWrap(True)
        column.addWidget(self.headline)
        column.addWidget(self.subline)
        column.addSpacing(10)

        self.grid_host = QWidget()
        column.addWidget(self.grid_host)
        column.addStretch(1)
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, scale.DOCK_RESERVE)
        self.grid.setHorizontalSpacing(scale.gap(user))
        self.grid.setVerticalSpacing(scale.gap(user))
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)   # packed from the first
        # column; the remainder stays on the right, never spread

        # The action panel: the chosen game's actions, at the bottom, in the
        # content's own margins, only while a game is picked.
        self.panel = ActionPanel(self.words, self)
        self.panel.run_button.clicked.connect(self._panel_run)
        self.panel.steam_button.clicked.connect(self._panel_steam)
        self.panel.desktop_button.clicked.connect(self._panel_desktop)
        self.panel.manage_button.clicked.connect(self._show_manage_menu)

        self.refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.reflow(self.content_width())
        self.panel.reposition()

    def content_width(self) -> int:
        """The width the grid lays out in: between the margins, without the bar."""
        return max(0, self.scroller.viewport().width() - 2 * scale.MARGIN)

    # ---- the layout ------------------------------------------------------------------

    def rebuild(self) -> None:
        """The page is built again (the settings changed)."""
        self.words = self.app.words
        self.panel.set_words(self.words)
        self.headline.setText(self.words['library_headline'])
        self.subline.setText(self.words['library_subtitle'])
        user = scale.user_scale(self.app.settings.get('ui_scale'))
        self.headline.setFont(theme.headline(user))
        self.subline.setFont(theme.subhead(user))
        self.grid.setHorizontalSpacing(scale.gap(user))
        self.grid.setVerticalSpacing(scale.gap(user))
        self.refresh()

    def refresh(self) -> None:
        """Read the library again and show what is in it."""
        clear_layout(self.grid)
        self.cards = []
        games = library.scan(settings.library_dir(self.app.settings))
        if not games:
            self.selected_id = ''
            self.panel.hide()
            empty = QLabel(self.words['library_empty'])
            empty.setProperty('dim', True)
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignHCenter)
            holder = QWidget()
            column = QVBoxLayout(holder)
            column.setContentsMargins(24, 24, 24, 24)
            column.addStretch(2)
            column.addWidget(empty, 0, Qt.AlignHCenter)
            column.addStretch(3)
            self.grid.addWidget(holder, 0, 0, 1, 1)
            return
        if self.selected_id not in {game.title_id for game in games}:
            self.selected_id = ''
        for game in games:
            self.cards.append(self.card(game))
        self.reflow(self.content_width())
        self.update_panel()

    def columns(self, content_width: int) -> int:
        """How many cards fit in this content width — the one question scale answers."""
        return scale.columns(content_width, scale.user_scale(self.app.settings.get('ui_scale')),
                             self.app.small)

    def reflow(self, content_width: int) -> None:
        """The cards again, in the columns that fit now (the cards themselves are
        kept: only their places in the grid change)."""
        count = max(1, self.columns(content_width))
        while self.grid.count():
            self.grid.takeAt(0)
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // count, index % count)

    def card(self, game: library.Game) -> QWidget:
        """One game: its rounded cover, its name (up to two lines, the full
        name on hover), and its state line.  The panel has the actions; the
        card is the choice.  Every size is scale's, so the card, the column
        count and the scroll bounds agree by construction."""
        user = scale.user_scale(self.app.settings.get('ui_scale'))
        cover_side = round(scale.COVER * user)
        cell = scale.cell_size(user)

        box = QFrame()
        box.setObjectName('gamecard')
        theme.styled_background(box)
        box.setFocusPolicy(Qt.StrongFocus)
        box.setCursor(Qt.PointingHandCursor)
        box.setProperty('selected', game.title_id == self.selected_id)
        box.setFixedWidth(cell)

        layout = QVBoxLayout(box)
        pad = round(scale.CARD_PAD * user)
        layout.setContentsMargins(pad, pad, pad, max(6, pad - 4))
        layout.setSpacing(5)
        layout.addWidget(self.make_cover(game, cover_side), 0, Qt.AlignHCenter)

        title = QLabel(game.name)
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignHCenter)
        title.setFixedWidth(cover_side)
        title.setToolTip(game.name)   # the full name, whatever the elided line shows

        running = launch.is_running(game)
        word = (self.words['stop'] if running else
                (self.words['ready'] if game.romfs_ready
                 else self.words['resources_missing']))
        tone = theme.READY if game.romfs_ready else theme.DANGER
        dot = QLabel(f'<span style="color:{tone};">●</span>&nbsp;'
                     f'<span style="color:{theme.DIM};">{word}</span>')
        dot.setTextFormat(Qt.RichText)
        dot.setAlignment(Qt.AlignHCenter)
        layout.addWidget(title, 0, Qt.AlignTop)
        layout.addWidget(dot, 0, Qt.AlignTop)
        layout.addStretch(1)
        box._game = game   # type: ignore[attr-defined]  — the card knows its game
        return box

    def make_cover(self, game: library.Game, side: int) -> QWidget:
        """The game's cover in a rounded rectangle — a square, the shape the
        packs' icons carry — or its first letter on the panel shade when the
        icon cannot be read."""
        radius = max(10, min(16, side // 9))
        dpr = self.devicePixelRatioF()
        image = QPixmap(str(game.icon_path)) if game.icon_path.is_file() else QPixmap()
        if not image.isNull():
            pixmap = theme.rounded(image.scaled(side, side, Qt.KeepAspectRatio,
                                                Qt.SmoothTransformation), radius)
        else:
            pixmap = theme.cover_placeholder(QSize(side, side), dpr,
                                             (game.name[:1] or '?').upper(), radius)
        return CoverTile(side, pixmap)

    # ---- picking ------------------------------------------------------------------

    def selected_game(self) -> library.Game | None:
        for card in self.cards:
            game = getattr(card, '_game', None)
            if game is not None and game.title_id == self.selected_id:
                return game
        return None

    def pick(self, card: QWidget) -> None:
        """A click picks the card (a light fill and a cream line) and brings
        the panel up; the same card again puts the panel away."""
        game = getattr(card, '_game', None)
        if game is None:
            return
        self.selected_id = '' if self.selected_id == game.title_id else game.title_id
        for other in self.cards:
            other_game = getattr(other, '_game', None)
            other.setProperty('selected', other_game is not None
                              and other_game.title_id == self.selected_id)
            theme.repolish(other)
        self.update_panel()

    def update_panel(self) -> None:
        """The panel says the chosen game, or goes away."""
        game = self.selected_game()
        if game is None:
            self.panel.hide()
            return
        running = launch.is_running(game)
        state_word = (self.words['stop'] if running else
                      (self.words['ready'] if game.romfs_ready
                       else self.words['resources_missing']))
        tone = theme.READY if game.romfs_ready else theme.DANGER
        version = f'{game.version}&nbsp;&nbsp;·&nbsp;&nbsp;' if game.version else ''
        state_html = f'{version}<span style="color:{tone};">●</span>&nbsp;{state_word}'
        self.panel.show_game(game.name,
                             self.words['stop'] if running else self.words['run'],
                             self.words['remove_steam'] if self.in_steam(game)
                             else self.words['add_steam'],
                             self.words['remove_desktop']
                             if steam.desktop_entry_path(game.title_id).is_file()
                             else self.words['add_desktop'],
                             state_html)

    def mousePressEvent(self, event) -> None:
        card = self.card_at(event.position().toPoint()) if event.button() == Qt.LeftButton else None
        if card is not None:
            self.pick(card)

    def mouseDoubleClickEvent(self, event) -> None:
        card = self.card_at(event.position().toPoint()) if event.button() == Qt.LeftButton else None
        if card is not None:
            self.pick(card)
            game = self.selected_game()
            if game is not None:
                self.toggle_run(game)
            return
        super().mouseDoubleClickEvent(event)

    def card_at(self, position) -> QWidget | None:
        """The card under a point, if the point fell on a card's own ground (its
        covers, its words, the gaps — not the panel, which keeps its click)."""
        target = self.childAt(position)
        while target is not None and target is not self.inner:
            if target in self.cards:
                return target
            target = target.parentWidget()
        return None

    # ---- the panel's buttons -----------------------------------------------------------

    def _panel_run(self) -> None:
        game = self.selected_game()
        if game is not None:
            self.toggle_run(game)

    def _panel_steam(self) -> None:
        game = self.selected_game()
        if game is not None:
            self.toggle_steam(game)

    def _panel_desktop(self) -> None:
        game = self.selected_game()
        if game is not None:
            self.toggle_desktop(game)

    # ---- the manage menu (the desktop launcher's own shape) ----------------------------

    def _show_manage_menu(self) -> None:
        """The chosen game's manage menu: open the folder, remove from the
        library (rename away, nothing deleted), delete the pack for good."""
        from PySide6.QtWidgets import QMenu
        game = self.selected_game()
        if game is None:
            return
        words = self.app.words
        menu = QMenu(self)
        open_act = menu.addAction(words['manage_open_folder'])
        open_act.triggered.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(game.path))))
        menu.addSeparator()
        remove_act = menu.addAction(words['manage_remove'])
        remove_act.triggered.connect(lambda: self._remove_from_library(game))
        delete_act = menu.addAction(words['manage_delete'])
        delete_act.triggered.connect(lambda: self._delete_game(game))
        menu.exec(self.panel.manage_button.mapToGlobal(
            self.panel.manage_button.rect().bottomLeft()))

    def _remove_from_library(self, game: library.Game) -> None:
        """Rename the pack folder to a dot-name the scan passes by — nothing is
        deleted; rename it back and the game is in the library again."""
        import os
        words = self.app.words
        if not dialogs.danger_confirm(self, words['manage_remove'],
                                      words['manage_remove_confirm'].format(name=game.name),
                                      words['manage_remove_note'],
                                      words['manage_remove']):
            return
        hidden = game.path.with_name(f'.ignored-{game.path.name}')
        try:
            os.rename(game.path, hidden)
        except OSError as error:
            dialogs.message(self, words['app_title'],
                            words['manage_delete_failed'].format(error=error), 'error')
            return
        self.refresh()

    def _delete_game(self, game: library.Game) -> None:
        """Delete the pack folder itself, for good — the destructive one, and it
        says so twice before it acts."""
        import shutil
        words = self.app.words
        if not dialogs.danger_confirm(self, words['manage_delete'],
                                      words['manage_delete_confirm'].format(name=game.name),
                                      words['manage_delete_note'].format(path=game.path),
                                      words['manage_delete']):
            return
        try:
            shutil.rmtree(game.path)
        except OSError as error:
            dialogs.message(self, words['app_title'],
                            words['manage_delete_failed'].format(error=error), 'error')
            return
        self.refresh()

    # ---- what a player does -----------------------------------------------------------

    def toggle_run(self, game: library.Game) -> None:
        """The panel's run: Run the game, or Stop it while it is up."""
        if launch.is_running(game):
            self.stop_game(game)
            return
        self.run_game(game)

    def run_game(self, game: library.Game) -> None:
        words = self.app.words
        if not game.romfs_ready:
            missing = game.romfs_path() or self.app.settings.get('work')
            dialogs.message(self, words['app_title'],
                            words['resources_missing_msg'].format(path=missing), 'warning')
            return
        try:
            process = launch.start(game)
        except launch.AlreadyRunning as error:
            dialogs.message(self, words['app_title'], words['already_running'].format(name=game.name))
            return
        except launch.NoExecutable:
            dialogs.message(self, words['app_title'], words['no_executable'])
            return
        except OSError as error:
            dialogs.message(self, words['app_title'], words['game_failed'].format(error=error),
                            'error')
            return
        # The game runs fullscreen on top; the launcher window stays behind it (the
        # desktop's taskbar switches between them). The game runs in a session of its
        # own, so a launcher exit never kills it.
        self.watch(process, game)
        self.refresh()

    def stop_game(self, game: library.Game) -> None:
        """Stop the game (SIGTERM, then SIGKILL): the host exits gracefully and the
        game commits its saves periodically."""
        words = self.app.words
        if not dialogs.confirm(self, words['app_title'],
                               words['stop_confirm'].format(name=game.name)):
            return
        process = launch.running_process(game)
        if process is None:
            return
        process.terminate()
        if not dialogs.wait_or_kill(process, seconds=5):
            process.kill()

    def watch(self, process, game: library.Game) -> None:
        """When the game exits by itself, refresh — the panel flips back to Run."""
        from PySide6.QtCore import QTimer
        timer = QTimer(self)

        def check() -> None:
            if process.poll() is None:
                return
            timer.stop()
            self.refresh()

        timer.timeout.connect(check)
        timer.start(500)

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
