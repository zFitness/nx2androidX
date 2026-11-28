"""The build page: the same pipeline the phone app runs, on the desktop
launcher's card column.

The page is one column of cards that fills the window (with its own margins on
the sides): the page heading, then cards — the game file, the options (the
everyday ones; the debug ones behind one quiet advanced toggle), the action
bar, the stages, the log.  Same porter calls, same events, same stages and the
same results as before; only the arrangement changed.
"""
from __future__ import annotations

import html
import queue
import time
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QColor, QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QScrollArea,
                               QSizePolicy, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from launcher import runner, scale, settings
from launcher.ui import clear_layout, dialogs, theme
from launcher.ui.cards import CardGroup, CenteredColumn, page_note_font, page_title_font
from launcher.ui.widgets import FlatButton
from porter import config as porter_config

GAME_LANGUAGES = [
    ('', 'English (default)'), ('ja', 'Japanese'), ('fr', 'French'), ('de', 'German'),
    ('it', 'Italian'), ('es', 'Spanish'), ('nl', 'Dutch'), ('pt', 'Portuguese'),
    ('ru', 'Russian'), ('ko', 'Korean'), ('zh-Hans', 'Chinese (Simplified)'),
    ('zh-Hant', 'Chinese (Traditional)'), ('system', 'Follow the system'),
]

# The tone of the state line: one colour per state of a build.
STEP_TONES = {'busy': 'busy', 'done': 'ready', 'bad': 'bad', 'dim': 'dim'}


def hms(seconds) -> str:
    """A duration the way the desktop tool writes it."""
    seconds = int(seconds or 0)
    return f'{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}' if seconds >= 3600 \
        else f'{seconds // 60}:{seconds % 60:02d}'


def open_folder(path: Path) -> None:
    """Show a folder in the system's file manager."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class BuildPage(QWidget):
    """The build page: the game file, the options, the stages and the log."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.words = app.words
        self.porter: runner.Porter | None = None
        self.result: dict | None = None
        self.info: dict | None = None
        self.cancelled = False
        self.stages: dict = {}
        self.inspected = ''
        self.inspecting = False
        self.started_at = 0.0
        self.last_title_id = ''      # whose options the form holds (P2-1: they belong to the game)
        self.built_from = ''         # the file this port reads (the re-port memory's source)
        self.built_options: dict = {}
        self.rebuild_pack: Path | None = None   # the pack a runtime rebuild is about (the drift retry)
        self.profile_drift = ''      # the porter's profile-drift answer, shown as a question
        self.pending_rebuild = False  # the settings changed mid-build: the page waits for the end
        QVBoxLayout(self)   # the page's own column; build() fills it (again)
        self.build()

    # ---- the layout ------------------------------------------------------------------

    def build(self) -> None:
        words = self.words

        clear_layout(self.layout())   # a rebuild starts from an empty page
        outer = self.layout()
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QScrollArea.NoFrame)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroller)
        body = CenteredColumn()   # the cards fill the window, margins on the sides
        scroller.setWidget(body)
        column = body.body_col

        # The page heading.
        self.headline = QLabel(words['tab_build'])
        self.headline.setObjectName('pageTitle')
        self.headline.setFont(page_title_font(scale.user_scale(self.app.settings.get('ui_scale'))))
        self.subline = QLabel(words['build_subtitle'])
        self.subline.setObjectName('pageNote')
        self.subline.setFont(page_note_font(scale.user_scale(self.app.settings.get('ui_scale'))))
        self.subline.setWordWrap(True)
        column.addWidget(self.headline)
        column.addWidget(self.subline)

        # Card 1: the game file.  The hint says the rule (updates and DLC come
        # along) once, on the card's own footer; the field's placeholder stays
        # a short instruction — the same words are never said twice on screen.
        files = CardGroup(title=words['build_game_file'], footer=words['build_game_file_hint'])
        column.addWidget(files)
        self.files_card = files
        row = QHBoxLayout()
        row.setSpacing(8)
        self.folder = QLineEdit()
        self.folder.setPlaceholderText(words['build_pick_file'])
        self.folder.returnPressed.connect(self.inspect)
        self.folder.editingFinished.connect(self.inspect_if_changed)
        row.addWidget(self.folder, 1)
        browse = FlatButton(words['browse'], 'quiet')
        browse.clicked.connect(self.pick_folder)
        row.addWidget(browse)
        inspect = FlatButton(words['build_inspect'], 'quiet')
        inspect.clicked.connect(self.inspect)
        row.addWidget(inspect)
        self.inspect_button = inspect
        files.add_row(row)

        # What the game is: a quiet card under the file's.
        info_card = QFrame()
        info_card.setObjectName('nxcard')
        info_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        theme.styled_background(info_card)
        info_col = QVBoxLayout(info_card)
        info_col.setContentsMargins(18, 13, 18, 13)
        self.card = QLabel()
        self.card.setObjectName('rowTitle')
        self.card.setWordWrap(True)
        self.card.setTextFormat(Qt.RichText)
        self.card.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_col.addWidget(self.card)
        column.addWidget(info_card)

        # Card 2: the options (the everyday ones).
        options = CardGroup(title=words['build_options'])
        column.addWidget(options)
        self.options_card = options
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.name_label = QLabel(words['opt_name'])
        self.name_label.setObjectName('rowTitle')
        self.name = QLineEdit()
        self.language = QComboBox()
        for _code, language_name in GAME_LANGUAGES:
            self.language.addItem(language_name)
        self.language.setCurrentIndex(0)
        self.headroom = QLineEdit()
        self.headroom.setPlaceholderText(words['headroom_auto'])
        for index, (label, widget) in enumerate((
                (self.name_label, self.name), (QLabel(words['opt_language']), self.language),
                (QLabel(words['opt_headroom']), self.headroom))):
            grid.addWidget(label, index, 0)
            grid.addWidget(widget, index, 1)
        headroom_hint = QLabel(words['opt_headroom_hint'])
        headroom_hint.setProperty('dim', True)
        headroom_hint.setWordWrap(True)
        grid.addWidget(headroom_hint, 3, 1, 1, 2)
        self.fps60 = QCheckBox(words['opt_fps60'])
        self.touch = QCheckBox(words['opt_touch'])
        checks = QHBoxLayout()
        checks.setSpacing(18)
        checks.addWidget(self.fps60)
        checks.addWidget(self.touch)
        checks.addStretch(1)
        grid.addLayout(checks, 4, 0, 1, 2)
        options.card.layout().addLayout(grid)

        # The advanced options: behind one quiet toggle.
        advanced = CardGroup(title=words['build_advanced'])
        column.addWidget(advanced)
        self._advanced_group = advanced
        adv = QGridLayout()
        adv.setContentsMargins(0, 0, 0, 0)
        adv.setHorizontalSpacing(10)
        adv.setVerticalSpacing(8)
        self.font = QLineEdit()
        self.font.setPlaceholderText(words['opt_font'])
        font_browse = FlatButton(words['browse'], 'quiet')
        font_browse.clicked.connect(self.pick_font)
        adv.addWidget(QLabel(words['opt_font']), 0, 0)
        adv.addWidget(self.font, 0, 1)
        adv.addWidget(font_browse, 0, 2)
        self.no_menu = QCheckBox(words['opt_no_menu'])
        self.mt_replay = QCheckBox(words['opt_mt_replay'])
        self.debug = QCheckBox(words['opt_debug'])
        self.experimental = QCheckBox(words['opt_experimental'])
        self.experimental.toggled.connect(lambda _on: self.update_port_button())
        for index, check in enumerate((self.no_menu, self.mt_replay, self.debug,
                                       self.experimental)):
            adv.addWidget(check, index + 1, 0, 1, 2)
        advanced.card.layout().addLayout(adv)
        advanced.hide()

        self.advanced_toggle = FlatButton(words['build_advanced_show'], 'outline')
        self.advanced_toggle.clicked.connect(self.toggle_advanced)
        adv_row = QHBoxLayout()
        adv_row.addStretch(1)
        adv_row.addWidget(self.advanced_toggle)
        column.addLayout(adv_row)

        # Card 3: the action bar.
        action = CardGroup()
        column.addWidget(action)
        self.action_card = action
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.start_button = FlatButton(words['build_start'], 'primary')
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_build)
        bar.addWidget(self.start_button)
        self.cancel_button = FlatButton(words['build_cancel'], 'outline')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        bar.addWidget(self.cancel_button)
        self.open_button = FlatButton(words['build_open'], 'quiet')
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_out)
        bar.addWidget(self.open_button)
        bar.addSpacing(12)
        self.step = QLabel('')
        self.set_step('', 'dim')
        bar.addWidget(self.step, 1)
        action.add_row(bar)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        action.add_row(self.progress)

        # Card 4: the stages.
        stages = CardGroup(title=words['build_stages'])
        column.addWidget(stages)
        self.stage_view = QTreeWidget()
        self.stage_view.setColumnCount(4)
        self.stage_view.setHeaderLabels(['', words['build_stages'], words['build_result'],
                                         words['build_time']])
        self.stage_view.setRootIsDecorated(False)
        self.stage_view.setAlternatingRowColors(False)
        stages.card.layout().addWidget(self.stage_view)

        # Card 5: the log.
        log = CardGroup(title=words['build_log'])
        column.addWidget(log)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.log.setMaximumBlockCount(20000)
        log.card.layout().addWidget(self.log)

        column.addStretch(1)

        self.set_card([[(words['build_card_idle'], 'dim')]])
        # The porter's events come in on a queue the interface drains; the tick keeps
        # the running stage's time (both run only while their work is on).
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(100)
        self.poll_timer.timeout.connect(self.poll)
        self.tick = QTimer(self)
        self.tick.setInterval(1000)
        self.tick.timeout.connect(self.on_tick)
        self.tick.start()

    def toggle_advanced(self) -> None:
        """The debug options come out (or go away); the everyday page is quiet."""
        shown = self._advanced_group.isHidden()
        self._advanced_group.setVisible(shown)
        self.advanced_toggle.setText(self.words['build_advanced_hide'] if shown
                                     else self.words['build_advanced_show'])

    def rebuild(self) -> None:
        """The page is built again (the settings changed).

        A running port keeps its page: the stages, the log and the result belong to the
        port, and the porter already runs with the settings it was started with (its root
        and its environment were taken when it began). The rebuild waits for the end
        (finish); the words and the scale of a running page stay as they were until then."""
        if self.porter is not None and self.porter.running:
            self.pending_rebuild = True
            return
        self.words = self.app.words   # the language may have changed with the settings
        user = scale.user_scale(self.app.settings.get('ui_scale'))
        self.headline.setText(self.words['tab_build'])
        self.headline.setFont(page_title_font(user))
        self.subline.setText(self.words['build_subtitle'])
        self.subline.setFont(page_note_font(user))
        self.files_card.set_title(self.words['build_game_file'])
        self.files_card.set_footer(self.words['build_game_file_hint'])
        self.options_card.set_title(self.words['build_options'])
        self._advanced_group.set_title(self.words['build_advanced'])
        self.stop_porter()
        for timer in (self.poll_timer, self.tick):
            timer.stop()
            timer.deleteLater()
        self.result = None
        self.info = None
        self.stages.clear()
        self.inspected = ''
        self.inspecting = False
        self.build()

    # ---- the card ---------------------------------------------------------------------

    def set_card(self, lines: list[list[tuple[str, str]]]) -> None:
        """The card: what the game is.  Rich text on a label; the tags are the same
        ones the desktop tool colours with."""
        markup = []
        for parts in lines:
            for content, tag in parts:
                colour = theme.TAGS.get(tag, theme.INK)
                weight = ' font-weight: bold;' if tag == 'name' else ''
                markup.append(f'<span style="color:{colour};{weight}">{html.escape(content)}</span>')
            markup.append('<br>')
        self.card.setText(''.join(markup))

    def set_step(self, text: str, tone: str) -> None:
        """The state line: the words of the state and its one colour (busy, done,
        failed, gone)."""
        self.step.setText(text)
        self.step.setProperty('status', STEP_TONES.get(tone, 'dim'))
        theme.repolish(self.step)

    # ---- what a player picks ----------------------------------------------------------

    def pick_folder(self) -> None:
        chosen = dialogs.choose_file(self, self.words['build_game_file'], self.words,
                                     [('Switch games', '*.nsp *.xci *.nsz *.xcz'),
                                      ('All files', '*.*')])
        if chosen:
            self.folder.setText(chosen)
            self.inspect()

    def pick_font(self) -> None:
        chosen = dialogs.choose_file(self, self.words['opt_font'], self.words,
                                     [('TrueType font', '*.ttf'), ('All files', '*.*')])
        if chosen:
            self.font.setText(chosen)

    def porter_root(self) -> Path | None:
        return runner.porter_root(str(self.app.settings.get('porter_dir') or ''))

    # ---- looking at a game ------------------------------------------------------------

    def inspect_if_changed(self) -> None:
        """The path was edited: read the game again when it is a different one."""
        folder = self.folder.text().strip()
        if folder != self.inspected:
            self.inspect()

    # The game files the porter reads (compressed ones included — it unpacks them).
    GAME_SUFFIXES = ('.nsp', '.xci', '.nsz', '.xcz')

    def inspect(self) -> None:
        """Look at what the entry points at — the entry itself first (a wrong
        path or a wrong kind of file fails at once, before the porter is ever
        asked), then the porter's own reading of the game."""
        words = self.words
        folder = self.folder.text().strip()
        self.info = None
        self.inspected = folder
        self.update_port_button()
        if not folder:
            self.set_card([[(words['build_card_idle'], 'dim')]])
            return
        path = Path(folder).expanduser()
        if not path.exists():
            self.set_card([[(words['card_not_found'].format(path=folder), 'bad')]])
            return
        if path.is_dir():
            # A folder of files is the Switch 2 shape on the desktop; here the
            # porter reads one file.  Say which kind, and where they are.
            self.set_card([[(words['card_wants_file'].format(path=folder), 'bad')]])
            return
        if path.suffix.lower() not in self.GAME_SUFFIXES:
            self.set_card([[(words['card_bad_suffix'].format(
                suffix=path.suffix or path.name, kind='/'.join(self.GAME_SUFFIXES)), 'bad')]])
            return
        root = self.porter_root()
        if not root:
            self.set_card([[(words['build_no_porter'].format(path=str(path)), 'bad')]])
            return
        if self.inspecting:
            return   # one look at a time; a stale answer re-reads what the entry shows
        self.set_card([[(words['card_reading'], 'dim')]])
        self.inspecting = True
        self.inspect_button.setEnabled(False)
        runner.run_json_async(root, ['inspect', str(path), '--json'],
                              lambda document, code, error: self.inspect_done(folder, document, code, error))

    def inspect_done(self, folder: str, document: dict | None, code: int, error: str) -> None:
        """The inspect came back (on the interface's loop).  A stale one — the entry
        shows a different path by now — is thrown away and the shown path is read
        instead."""
        self.inspecting = False
        self.inspect_button.setEnabled(True)
        if folder != self.folder.text().strip():
            QTimer.singleShot(0, self.inspect_if_changed)
            return
        words = self.words
        if document is None:
            message = error or words['card_no_game']
            self.set_card([[(words['card_error'].format(message=message), 'bad')]])
            return
        if document.get('error'):   # the porter answers errors as JSON on stdout, exit 2
            self.set_card([[(words['card_error'].format(message=str(document['error'])), 'bad')]])
            return
        self.info = document
        self.adopt_game_options(document)
        self.set_card(self.card_lines(document))
        self.set_name_label(str(document.get('name') or ''))
        self.update_port_button()

    def adopt_game_options(self, document: dict) -> None:
        """The form's per-game options belong to the game: another game in the file field starts
        clean, so one game's name, font or headroom never builds another's pack. The same game
        re-read keeps what the player typed.
        """
        title_id = str(document.get('title_id') or '')
        if not title_id or title_id == self.last_title_id:
            return
        if self.last_title_id:
            self.name.clear()
            self.font.clear()
            self.headroom.clear()
        self.last_title_id = title_id

    def set_name_label(self, game_name: str) -> None:
        """The name row says which name the game carries by itself."""
        words = self.words
        self.name_label.setText(words['opt_name_with'].format(name=game_name) if game_name
                                else words['opt_name'])

    def card_lines(self, info: dict) -> list[list[tuple[str, str]]]:
        """The card's lines, the way the desktop tool writes them."""
        words = self.words
        android = info.get('android') or {}
        status = android.get('status') or ('not ported' if info.get('profile') else 'not supported')
        colour = theme.STATUS_COLOUR.get(status, theme.DANGER)
        head: list[tuple[str, str]] = []
        head.append((str(info.get('name') or info.get('title_id') or ''), 'name'))
        head.append((f"  {info.get('title_id') or ''}", 'dim'))
        head.append((f"  {status}", 'ok' if colour == theme.READY
                     else ('dim' if colour == theme.UNBUILT else 'warn')))
        lines = [head]
        files = ['base game'] + [f"update {u.get('version')}" for u in info.get('updates') or []]
        if info.get('dlc'):
            files.append(f"{len(info['dlc'])} DLC")
        row = [('In the folder: ' + ', '.join(files), 'dim')]
        if info.get('pack'):
            row.append((f" — packs {info['pack']}", 'dim'))
        lines.append(row)
        if info.get('compressed'):
            lines.append([(words['card_compressed'].format(count=len(info['compressed'])), 'dim')])
        if android.get('tested'):
            lines.append([(f"Tested: {android['tested']}", 'dim')])
        if info.get('reason'):
            lines.append([(str(info['reason']), 'ok' if info.get('supported') else 'bad')])
        return lines

    def update_port_button(self) -> None:
        """The port button: a game that can be ported, or one the player wants to try.
        Never lit while a build is running (a second porter would orphan the first)."""
        info = self.info or {}
        ready = bool(info.get('supported')
                     or (info.get('experimental') and self.experimental.isChecked()))
        running = self.porter is not None and self.porter.running
        self.start_button.setEnabled(ready and bool(self.porter_root()) and not running)

    # ---- the build --------------------------------------------------------------------

    def start_build(self) -> bool:
        words = self.words
        if self.porter is not None and self.porter.running:
            return False   # a build is running; editing the game path must not orphan it
        folder = self.folder.text().strip()
        if not folder:
            dialogs.message(self, words['app_title'], words['build_need_file'])
            return False
        if not settings.library_set(self.app.settings):
            dialogs.message(self, words['app_title'], words['build_need_data_dir'])
            return False
        # The keys are the porter's own setting (shared with the desktop tool and the
        # CLI); without them the port would fail deep inside the pipeline.
        if not porter_config.load().get('keys'):
            dialogs.message(self, words['app_title'], words['build_need_keys'])
            self.app.goto_settings()
            return False
        root = self.porter_root()
        if not root:
            dialogs.message(self, words['app_title'], words['build_no_porter'].format(path=folder),
                            'error')
            return False
        # --app: the app's mode — the pack is the only artifact (no APK), it carries the
        # host, the icon and the gamepad's theme.  The porter writes it straight into the
        # library (NX2A_PACK_DIR): an atomic rename that replaces an older pack of the
        # same game, so a failed or cancelled build leaves nothing half-made behind.
        library_dir = settings.library_dir(self.app.settings)
        args = ['port', folder, '--progress', 'json', '--app']
        name = self.name.text().strip()
        if name:
            args += ['--app-name', name]
        index = self.language.currentIndex()
        language = GAME_LANGUAGES[index][0] if index >= 0 else ''
        if language:
            args += ['--language', language]
        headroom = self.headroom_value()
        if headroom is not None:
            args += ['--alias-headroom', str(headroom)]
        if self.font.text().strip():
            args += ['--shared-font', self.font.text().strip()]
        if self.fps60.isChecked():
            args.append('--fps60')
        if self.touch.isChecked():
            args.append('--touch')
        if self.no_menu.isChecked():
            args.append('--no-menu-button')
        if self.mt_replay.isChecked():
            args.append('--mt-replay')
        if self.debug.isChecked():
            args.append('--debug')
        if self.experimental.isChecked() and not (self.info or {}).get('supported'):
            args.append('--experimental')
        # What this port reads and the options it runs with: the library's re-port button
        # replays exactly this (settings.remember_port / prefill_for_port).
        self.built_from = folder
        self.built_options = {
            'name': name, 'language': language, 'headroom': headroom,
            'font': self.font.text().strip(),
            'fps60': self.fps60.isChecked(), 'touch': self.touch.isChecked(),
            'no_menu': self.no_menu.isChecked(), 'mt_replay': self.mt_replay.isChecked(),
            'debug': self.debug.isChecked(), 'experimental': self.experimental.isChecked(),
        }
        self._run_porter(root, args)
        return True

    def start_rebuild_runtime(self, pack: Path, allow_drift: bool = False) -> bool:
        """Rebuild a pack's runtime without the original game files (the porter's
        rebuild-runtime): the same stages, log and cancel as a port, on this page. The
        pack's game data, its env.txt and its saves are untouched — only the host (and
        the manifest's fingerprint rows) changes, each by an atomic rename."""
        words = self.words
        if self.porter is not None and self.porter.running:
            return False
        root = self.porter_root()
        if not root:
            dialogs.message(self, words['app_title'], words['build_no_porter'].format(path=str(pack)),
                            'error')
            return False
        args = ['rebuild-runtime', str(pack), '--progress', 'json']
        if allow_drift:
            args.append('--allow-profile-drift')
        self.built_from = ''   # not a port: the re-port memory keeps what the last port wrote
        self._run_porter(root, args)
        self.rebuild_pack = Path(pack)
        return True

    def prefill_for_port(self, source: str, options: dict) -> None:
        """The library's re-port puts the remembered file and the last port's options back on
        the form (start_build builds from the form, so the form says what will run)."""
        self.folder.setText(source)
        self.name.setText(str(options.get('name') or ''))
        for index, (code, _label) in enumerate(GAME_LANGUAGES):
            if code == str(options.get('language') or ''):
                self.language.setCurrentIndex(index)
                break
        else:
            self.language.setCurrentIndex(0)
        headroom = options.get('headroom')
        self.headroom.setText('' if headroom is None else str(headroom))
        self.font.setText(str(options.get('font') or ''))
        for box, key in ((self.fps60, 'fps60'), (self.touch, 'touch'), (self.no_menu, 'no_menu'),
                         (self.mt_replay, 'mt_replay'), (self.debug, 'debug'),
                         (self.experimental, 'experimental')):
            box.setChecked(bool(options.get(key)))

    def _run_porter(self, root: Path, args: list[str]) -> None:
        """One porter command on this page — a port or a runtime rebuild, the same machinery:
        the stages, the log and the buttons all follow it."""
        words = self.words
        self.result = None
        self.cancelled = False
        self.profile_drift = ''
        self.rebuild_pack = None
        self.started_at = time.time()
        self.clear_stages()
        self.log.clear()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.set_step(words['build_running'], 'busy')
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.open_button.setEnabled(False)
        self.porter = runner.Porter(root, settings.library_dir(self.app.settings))
        self.porter.start(args)
        self.poll_timer.start()

    def headroom_value(self) -> int | None:
        """The extra address space in GB; None when it is left on automatic."""
        raw = self.headroom.text().strip()
        if not raw or raw == str(self.words['headroom_auto']):
            return None
        try:
            value = int(raw)
        except ValueError:
            return None
        return value if 0 <= value <= 48 else None

    def cancel(self) -> None:
        if self.porter:
            self.cancelled = True
            self.porter.cancel()

    def stop_porter(self) -> None:
        self.poll_timer.stop()
        if self.porter:
            self.porter.cancel()
            self.porter = None

    def open_out(self) -> None:
        if self.result and self.result.get('data'):
            open_folder(Path(str(self.result['data'])))

    def poll(self) -> None:
        """Take the events that came in and show them.

        A timer drives this while a porter runs (it stops when the porter is gone):
        each pass drains the queue until it is empty, and a `done` event ends the
        build."""
        if self.porter is None:
            return
        while True:
            try:
                event = self.porter.events.get_nowait()
            except queue.Empty:
                return
            self.handle(event)
            if event.get('ev') == runner.DONE:
                self.finish(int(event.get('code') or 0))
                return

    # ---- the stages -------------------------------------------------------------------

    def clear_stages(self) -> None:
        self.stages.clear()
        self.stage_view.clear()

    def stage_item(self, key, name: str):
        item = self.stages.get(key)
        if item is None:
            item = QTreeWidgetItem(['▶', name, '', ''])
            item.setForeground(0, QColor(theme.BUILDING))
            self.stage_view.addTopLevelItem(item)
            self.stages[key] = item
        return item

    def handle(self, event: dict) -> None:
        kind = event.get('ev')
        if kind == 'stage':
            item = self.stage_item(event.get('k'), str(event.get('name') or ''))
            item.setText(0, '▶')
            item.setForeground(0, QColor(theme.BUILDING))
            self.set_step(f"[{event.get('k')}/{event.get('n')}] {event.get('name')}"
                          + (f" · {event['step']}" if event.get('step') else ''), 'busy')
            self.progress.setRange(0, 0)   # no number yet: the busy indicator
        elif kind == 'step':
            self.set_step(f"{event.get('name')}"
                          + (f" · {event.get('step')}" if event.get('step') else ''), 'busy')
        elif kind == 'progress':
            done, total = event.get('done'), event.get('total')
            count = ''
            if done is not None:
                count = f'{done:,}' + (f' / {total:,}' if total else '')
                if event.get('unit'):
                    count += f' {event["unit"]}'
            self.set_step(f"{event.get('name')}"
                          + (f" · {event.get('step')}" if event.get('step') else '')
                          + (f' · {count}' if count else ''), 'busy')
            if event.get('frac') is not None:
                self.progress.setRange(0, 100)
                self.progress.setValue(round(max(0.0, min(1.0, float(event['frac']))) * 100))
            else:
                self.progress.setRange(0, 0)
        elif kind == 'stage_end':
            item = self.stage_item(event.get('k'), str(event.get('name') or ''))
            ok = event.get('ok', True)
            item.setText(0, '✓' if ok else '✗')
            item.setForeground(0, QColor(theme.READY if ok else theme.DANGER))
            item.setText(2, str(event.get('summary') or ''))
            item.setText(3, hms(event.get('elapsed')))
            self.progress.setRange(0, 100)
            self.progress.setValue(100 if ok else 0)
        elif kind == 'say':
            self.append(str(event.get('msg') or ''))
        elif kind == 'result':
            self.result = event
        elif kind == 'profile-drift':
            # the runtime rebuild's answer: the pack was built with a profile that has
            # changed; finish asks the player what to do with it
            self.profile_drift = str(event.get('msg') or 'the game profile changed')

    def append(self, message: str) -> None:
        self.log.appendPlainText(message)
        bar = self.log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def on_tick(self) -> None:
        """The running stage's time."""
        for index in range(self.stage_view.topLevelItemCount()):
            item = self.stage_view.topLevelItem(index)
            if item.text(0) == '▶':
                item.setText(3, hms(time.time() - self.started_at))
                return

    # ---- the end ----------------------------------------------------------------------

    def finish(self, code: int) -> None:
        words = self.words
        self.porter = None
        self.poll_timer.stop()
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if self.cancelled or code == 130:
            self.set_step(words['build_cancelled'], 'dim')
        elif code != 0:
            self.set_step(words['build_failed'], 'bad')
            pack = self.rebuild_pack
            if self.profile_drift and pack is not None and dialogs.confirm(
                    self, words['rebuild_drift_title'], words['rebuild_drift_msg']):
                # the profile the game has now — the same one a full re-port would use
                self.start_rebuild_runtime(pack, allow_drift=True)
        elif not (self.result or {}).get('data'):
            self.set_step(words['build_failed'], 'bad')
        else:
            self.set_step(words['build_done'], 'done')
            self.open_button.setEnabled(True)
            title_id = str((self.result or {}).get('title_id') or '')
            if title_id and self.built_from:
                settings.remember_port(title_id, self.built_from, self.built_options or {})
            self.app.refresh_library()
        if self.pending_rebuild:
            # the settings changed while this porter ran: the page rebuilds now that its
            # stages and its log are history
            self.pending_rebuild = False
            self.rebuild()
