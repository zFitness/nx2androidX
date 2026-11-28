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

from pathlib import Path

from PySide6.QtCore import QUrl, QSize, Qt, QRectF
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from launcher import launch, library, runner, scale, settings, steam
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
        self.scroller.viewport().setAutoFillBackground(True)   # the viewport
        # paints the ground itself — QSS on a QScrollArea does not reach it
        self.scroller.setWidgetResizable(True)
        self.scroller.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(self.scroller)
        self.inner = QWidget()
        self.scroller.setWidget(self.inner)
        column = QVBoxLayout(self.inner)
        column.setContentsMargins(scale.MARGIN, 18, scale.MARGIN, scale.MARGIN)
        column.setSpacing(2)

        # The headline: hidden on the empty library (the welcome badge IS the
        # page then); shown once games exist.
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
        self.grid_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        column.addWidget(self.grid_host, 1)   # takes the room the cards or the
        # empty state live in — a fixed-height host once clipped the empty
        # welcome to a sliver that read as "a line of grey text"
        column.addStretch(0)
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
        if self.cards:   # the empty state holds the whole page; only a grid of
            self.reflow(self.content_width())   # cards follows the width
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
        empty = not games
        # The page title yields to the welcome: the badge, the word and the
        # one action are the page when there is nothing to list.
        self.headline.setVisible(not empty)
        self.subline.setVisible(not empty)
        if empty:
            self.selected_id = ''
            self.panel.hide()
            self.grid.setContentsMargins(0, 0, 0, 0)   # no dock reserve: the
            # welcome centres in the whole page; the reserve exists for cards
            # that the panel could overlap — there are none here
            self.grid.addWidget(self.empty_state(), 0, 0, 1, 1)
            self.grid.setRowStretch(0, 1)
            self.grid.setColumnStretch(0, 1)
            return
        self.grid.setContentsMargins(0, 0, 0, scale.DOCK_RESERVE)
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

    def empty_state(self) -> QWidget:
        """The empty library, the desktop launcher's own welcome: a round cream
        badge with the gamepad, the welcome title, the note, and the one
        action — centred in the air, saying what to do first."""
        words = self.words
        page = QWidget()
        page.setStyleSheet('background: transparent;')
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        column = QVBoxLayout(page)
        column.setContentsMargins(40, 40, 40, 40)
        column.setSpacing(12)
        column.addStretch(10)   # the welcome floats dead-centre in the page

        # The badge: a circle of faint cream holding the brand's gamepad.
        badge = QFrame()
        badge.setObjectName('emptyBadge')
        badge.setFixedSize(84, 84)
        badge.setStyleSheet(
            '#emptyBadge { background: rgba(255, 240, 214, 0.08);'
            ' border: 1px solid rgba(255, 240, 214, 0.22);'
            ' border-radius: 42px; }')
        badge.setAttribute(Qt.WA_StyledBackground, True)
        badge_layout = QVBoxLayout(badge)
        badge_layout.setContentsMargins(0, 0, 0, 0)
        mark = QLabel()
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet('background: transparent; border: none;')
        mark.setPixmap(self.gamepad_mark(42))
        badge_layout.addWidget(mark)
        column.addWidget(badge, 0, Qt.AlignHCenter)

        # The welcome: large and centred, the note under it.
        user = scale.user_scale(self.app.settings.get('ui_scale'))
        title = QLabel(words['library_welcome'])
        title.setAlignment(Qt.AlignHCenter)
        title.setFont(theme.headline(user))
        note = QLabel(words['library_empty'])
        note.setProperty('dim', True)
        note.setAlignment(Qt.AlignHCenter)
        note.setWordWrap(True)
        note.setFont(theme.subhead(user))
        column.addWidget(title, 0, Qt.AlignHCenter)
        column.addWidget(note, 0, Qt.AlignHCenter)
        column.addSpacing(8)

        # The one action: go and build the first game.
        row = QHBoxLayout()
        row.addStretch(1)
        from launcher.ui.widgets import FlatButton
        first = FlatButton(words['library_first_build'], 'primary')
        first.clicked.connect(self._goto_build)
        row.addWidget(first)
        row.addStretch(1)
        column.addLayout(row)
        column.addStretch(10)   # mirrors the top: the block sits dead-centre
        return page

    def gamepad_mark(self, side: int) -> QPixmap:
        """The gamepad mark of the badge, drawn on the cream accent."""
        pixmap = QPixmap(side, side)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        from launcher.ui.widgets import draw_icon
        draw_icon(painter, 'gamepad', QRectF(0, 0, side, side), QColor(theme.ACCENT))
        painter.end()
        return pixmap

    def _goto_build(self) -> None:
        """The empty library's one action: over to the Build page."""
        self.app.goto_build()

    def reflow(self, content_width: int) -> None:
        """The cards again, in the columns that fit now (the cards themselves are
        kept: only their places in the grid change)."""
        count = max(1, self.columns(content_width))
        while self.grid.count():
            self.grid.takeAt(0)
        self.grid.setRowStretch(0, 0)
        self.grid.setColumnStretch(0, 0)
        self.grid.setRowStretch(1, 0)   # no row grows: a card keeps its own height
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // count, index % count,
                                Qt.AlignTop | Qt.AlignHCenter)

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
        # The card's height is its content's (cover + name + state), not whatever
        # the grid's row was stretched to: a stretched frame drew a selection box
        # far taller than the card itself (the tablet's tall rows made it plain).
        box.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)

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
        """The chosen game's manage menu: the runtime and the game again (the two ways an old
        pack follows a new engine), the folder, the removal from the library (rename away,
        nothing deleted), the pack's deletion for good."""
        from PySide6.QtWidgets import QMenu
        game = self.selected_game()
        if game is None:
            return
        words = self.app.words
        menu = QMenu(self)
        if runner.porter_root(str(self.app.settings.get('porter_dir') or '')) is not None:
            busy = self.build_page_busy() is not None
            runtime_act = menu.addAction(words['manage_rebuild_runtime'])
            runtime_act.setEnabled(not busy)
            runtime_act.triggered.connect(lambda: self.rebuild_runtime(game))
            again_act = menu.addAction(words['manage_report'])
            again_act.setEnabled(not busy)
            again_act.triggered.connect(lambda: self.rebuild_game(game))
            menu.addSeparator()
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

    def build_page_busy(self) -> str | None:
        """The message when a porter command already runs (one at a time), or None."""
        page = self.app.build_page
        if page.porter is not None and page.porter.running:
            return self.app.words['build_busy']
        return None

    def rebuild_runtime(self, game: library.Game) -> None:
        """The pack's runtime, built again without the game's files (the engine or the game's
        profile moved on). The run itself is the build page's, so over there."""
        busy = self.build_page_busy()
        if busy:
            dialogs.message(self, self.app.words['app_title'], busy)
            return
        if self.app.build_page.start_rebuild_runtime(game.path):
            self.app.goto_build()

    def rebuild_game(self, game: library.Game) -> None:
        """The game, ported again from the file it was ported from, with the options the last
        port used; the build page shows the run. A pack that was imported (not ported here)
        has no remembered file: the player is sent to pick one."""
        words = self.app.words
        busy = self.build_page_busy()
        if busy:
            dialogs.message(self, words['app_title'], busy)
            return
        remembered = settings.port_source_of(game.title_id)
        if not remembered:
            dialogs.message(self, words['app_title'], words['report_no_source'])
            return
        source = Path(str(remembered.get('source') or ''))
        if not source.is_file():
            dialogs.message(self, words['app_title'], words['report_source_gone'].format(path=source))
            return
        if not dialogs.danger_confirm(self, words['manage_report'],
                                      words['report_confirm'].format(name=game.name),
                                      words['report_note'].format(path=source),
                                      words['manage_report']):
            return
        page = self.app.build_page
        page.prefill_for_port(str(source), remembered)
        if page.start_build():
            self.app.goto_build()

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
        # Steam on this device is run by the desktop itself (DroidDeck keeps it
        # alive): asking the player to close it does not apply here. The shortcut
        # is written anyway — Steam reads the file when it starts (a restart of
        # the desktop, or of Steam on an ordinary machine, brings it in) — and the
        # player is told that, exactly as the desktop Steam's own behaviour is.
        steam_later = steam.steam_running()
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
        dialogs.message(self, words['app_title'],
                        words['steam_added_later'] if steam_later else words['steam_added'])
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
