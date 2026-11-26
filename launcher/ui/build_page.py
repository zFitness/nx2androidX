"""The build page: the same pipeline the phone app runs.

The layout follows the desktop tool's build tab (gui/app.py): the game file and what it
holds, the options, the stages with their times, the log.  What differs is what a phone
does not need (installing an APK, a device, the SD card, the package) and what a Linux
machine does not need (a Vulkan driver in the pack: the driver comes from the system).

The game file is looked at first, the port runs with its stages and its progress, and the
pack it makes goes into the data directory — only when it ends well.
"""
from __future__ import annotations

import queue
import time
from pathlib import Path

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gtk   # noqa: E402

from launcher import library, runner, settings   # noqa: E402
from launcher.ui import dialogs, text            # noqa: E402

GAME_LANGUAGES = [
    ('', 'English (default)'), ('ja', 'Japanese'), ('fr', 'French'), ('de', 'German'),
    ('it', 'Italian'), ('es', 'Spanish'), ('nl', 'Dutch'), ('pt', 'Portuguese'),
    ('ru', 'Russian'), ('ko', 'Korean'), ('zh-Hans', 'Chinese (Simplified)'),
    ('zh-Hant', 'Chinese (Traditional)'), ('system', 'Follow the system'),
]
STATUS_COLOUR = {'playable': '#2e7d32', 'wip': '#ef6c00', 'boots': '#ef6c00',
                 'experimental': '#ef6c00', 'not ported': '#757575'}


def hms(seconds) -> str:
    """A duration the way the desktop tool writes it."""
    seconds = int(seconds or 0)
    return f'{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}' if seconds >= 3600 \
        else f'{seconds // 60}:{seconds % 60:02d}'


def open_folder(path: Path) -> None:
    """Show a folder in the system's file manager."""
    import subprocess
    for command in (['xdg-open', str(path)], ['open', str(path)]):
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue


class BuildPage(Gtk.Box):
    """The build page: the game file, the options, the stages and the log."""

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.words = app.words
        self.porter: runner.Porter | None = None
        self.result: dict | None = None
        self.info: dict | None = None
        self.staging: Path | None = None
        self.cancelled = False
        self.stages: dict = {}
        self.inspected = ''
        self.started_at = 0.0
        self.tick = 0
        self.build()

    # ---- the layout ------------------------------------------------------------------

    def build(self) -> None:
        words = self.words

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        self.add(scroller)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        inner.set_margin_start(16)
        inner.set_margin_end(16)
        inner.set_margin_top(16)
        inner.set_margin_bottom(16)
        scroller.add(inner)

        # The game file.
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(Gtk.Label(label=words['build_game_file']), False, False, 0)
        self.folder = Gtk.Entry()
        self.folder.set_hexpand(True)
        self.folder.connect('activate', lambda _entry: self.inspect())
        self.folder.connect('focus-out-event', lambda _entry, _event: self.inspect_if_changed())
        row.pack_start(self.folder, True, True, 0)
        browse = Gtk.Button(label=words['browse'])
        browse.connect('clicked', lambda _b: self.pick_folder())
        row.pack_start(browse, False, False, 0)
        inspect = Gtk.Button(label=words['build_inspect'])
        inspect.connect('clicked', lambda _b: self.inspect())
        row.pack_start(inspect, False, False, 0)
        inner.pack_start(row, False, False, 0)

        hint = Gtk.Label(label=words['build_game_file_hint'])
        hint.set_xalign(0)
        hint.get_style_context().add_class('dim-label')
        inner.pack_start(hint, False, False, 0)

        # The card: what the game is.
        self.card = Gtk.Label()
        self.card.set_xalign(0)
        self.card.set_line_wrap(True)
        self.card.set_max_width_chars(70)
        self.card.set_selectable(True)
        inner.pack_start(self.card, False, False, 0)

        # The options.
        frame = Gtk.Frame(label=words['build_options'])
        inner.pack_start(frame, False, False, 0)
        grid = Gtk.Grid(column_spacing=10, row_spacing=4)
        grid.set_margin_start(10)
        grid.set_margin_end(10)
        grid.set_margin_top(6)
        grid.set_margin_bottom(6)
        frame.add(grid)

        self.name_label = Gtk.Label(label=words['opt_name'])
        self.name_label.set_xalign(0)
        self.name = Gtk.Entry()
        self.name.set_hexpand(True)
        self.language = Gtk.ComboBoxText()
        for _, name in GAME_LANGUAGES:
            self.language.append_text(name)
        self.language.set_active(0)
        self.headroom = Gtk.Entry()
        self.headroom.set_hexpand(True)
        self.headroom.set_placeholder_text(words['headroom_auto'])
        self.font = Gtk.Entry()
        self.font.set_hexpand(True)
        self.fps60 = Gtk.CheckButton(label=words['opt_fps60'])
        self.touch = Gtk.CheckButton(label=words['opt_touch'])
        self.no_menu = Gtk.CheckButton(label=words['opt_no_menu'])
        self.mt_replay = Gtk.CheckButton(label=words['opt_mt_replay'])
        self.debug = Gtk.CheckButton(label=words['opt_debug'])
        self.experimental = Gtk.CheckButton(label=words['opt_experimental'])

        for index, (label, widget) in enumerate((
                (self.name_label, self.name), (Gtk.Label(label=words['opt_language']), self.language),
                (Gtk.Label(label=words['opt_headroom']), self.headroom),
                (Gtk.Label(label=words['opt_font']), self.font))):
            if isinstance(label, Gtk.Label):
                label.set_xalign(0)
            grid.attach(label, 0, index, 1, 1)
            grid.attach(widget, 1, index, 1, 1)
        font_browse = Gtk.Button(label=words['browse'])
        font_browse.connect('clicked', lambda _b: self.pick_file(self.font))
        grid.attach(font_browse, 2, 3, 1, 1)
        for index, check in enumerate((self.fps60, self.touch, self.no_menu, self.mt_replay,
                                       self.debug, self.experimental), start=4):
            grid.attach(check, 1, index, 1, 1)
        headroom_hint = Gtk.Label(label=words['opt_headroom_hint'])
        headroom_hint.set_xalign(0)
        headroom_hint.set_line_wrap(True)
        headroom_hint.set_max_width_chars(60)
        grid.attach(headroom_hint, 1, 10, 2, 1)

        # The buttons and the progress.
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.start_button = Gtk.Button(label=words['build_start'])
        self.start_button.set_sensitive(False)
        self.start_button.connect('clicked', lambda _b: self.start_build())
        buttons.pack_start(self.start_button, False, False, 0)
        self.cancel_button = Gtk.Button(label=words['build_cancel'])
        self.cancel_button.set_sensitive(False)
        self.cancel_button.connect('clicked', lambda _b: self.cancel())
        buttons.pack_start(self.cancel_button, False, False, 0)
        self.open_button = Gtk.Button(label=words['build_open'])
        self.open_button.set_sensitive(False)
        self.open_button.connect('clicked', lambda _b: self.open_out())
        buttons.pack_end(self.open_button, False, False, 0)
        inner.pack_start(buttons, False, False, 0)

        self.step = Gtk.Label(label='')
        self.step.set_xalign(0)
        inner.pack_start(self.step, False, False, 0)
        self.progress = Gtk.ProgressBar()
        inner.pack_start(self.progress, False, False, 0)

        # The stages and the log.
        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        paned.set_vexpand(True)
        inner.pack_start(paned, True, True, 0)

        stages = Gtk.Frame(label=words['build_stages'])
        self.stage_store = Gtk.ListStore(str, str, str, str)
        self.stage_view = Gtk.TreeView(model=self.stage_store)
        for index, heading in enumerate(('', words['build_stages'], words['build_result'],
                                         words['build_time'])):
            column = Gtk.TreeViewColumn(heading, Gtk.CellRendererText(), text=index)
            column.set_resizable(True)
            self.stage_view.append_column(column)
        stage_scroller = Gtk.ScrolledWindow()
        stage_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        stage_scroller.add(self.stage_view)
        stages.add(stage_scroller)
        paned.pack1(stages, True, False)

        log = Gtk.Frame(label=words['build_log'])
        self.log = Gtk.TextView()
        self.log.set_editable(False)
        self.log.set_monospace(True)
        log_scroller = Gtk.ScrolledWindow()
        log_scroller.add(self.log)
        log.add(log_scroller)
        paned.pack2(log, True, False)

        self.set_card([[(words['build_game_file_hint'], 'dim')]])
        self.tick = GLib.timeout_add(1000, self.on_tick)

    def rebuild(self) -> None:
        """The page is built again (the settings changed)."""
        self.stop_porter()
        if self.tick:
            GLib.source_remove(self.tick)
            self.tick = 0
        for child in self.get_children():
            self.remove(child)
        self.result = None
        self.info = None
        self.staging = None
        self.stages.clear()
        self.build()

    # ---- the card ---------------------------------------------------------------------

    def set_card(self, lines: list[list[tuple[str, str]]]) -> None:
        """The card: what the game is."""
        colours = {'name': '#202124', 'dim': '#757575', 'ok': '#2e7d32',
                   'warn': '#ef6c00', 'bad': '#c62828'}
        markup = []
        for parts in lines:
            for content, tag in parts:
                colour = colours.get(tag, '#202124')
                weight = ' bold' if tag == 'name' else ''
                markup.append(f'<span color="{colour}"{weight}>{GLib.markup_escape_text(content)}</span>')
            markup.append('\n')     # Pango's markup breaks a line with a newline, not <br>
        self.card.set_markup(''.join(markup))

    # ---- what a player picks ----------------------------------------------------------

    def pick_folder(self) -> None:
        chosen = dialogs.choose_file(self, self.words['build_game_file'], self.words,
                                     [('Switch games', '*.nsp *.xci *.nsz *.xcz'),
                                      ('All files', '*.*')])
        if chosen:
            self.folder.set_text(chosen)
            self.inspect()

    def pick_file(self, entry: Gtk.Entry) -> None:
        chosen = dialogs.choose_file(self, self.words['opt_font'], self.words,
                                     [('TrueType font', '*.ttf'), ('All files', '*.*')])
        if chosen:
            entry.set_text(chosen)

    def porter_root(self) -> Path | None:
        return runner.porter_root(str(self.app.settings.get('porter_dir') or ''))

    # ---- looking at a game ------------------------------------------------------------

    def inspect_if_changed(self) -> None:
        """The path was edited: read the game again when it is a different one."""
        folder = self.folder.get_text().strip()
        if folder != self.inspected:
            self.inspect()

    def inspect(self) -> None:
        words = self.words
        folder = self.folder.get_text().strip()
        self.info = None
        self.inspected = folder
        self.update_port_button()
        if not folder:
            return
        if not Path(folder).exists():
            self.set_card([[(words['card_not_found'].format(path=folder), 'bad')]])
            return
        self.set_card([[(words['card_reading'], 'dim')]])
        root = self.porter_root()
        if not root:
            self.set_card([[(words['build_no_porter'].format(path=folder), 'bad')]])
            return
        document, code, error = runner.run_json(root, ['inspect', folder, '--json'])
        if document is None:
            message = error or words['card_no_game']
            self.set_card([[(words['card_error'].format(message=message), 'bad')]])
            return
        self.info = document
        self.set_card(self.card_lines(document))
        self.set_name_label(str(document.get('name') or ''))
        self.update_port_button()

    def set_name_label(self, game_name: str) -> None:
        """The name row says which name the game carries by itself."""
        words = self.words
        self.name_label.set_text(words['opt_name_with'].format(name=game_name) if game_name
                                 else words['opt_name'])

    def card_lines(self, info: dict) -> list[list[tuple[str, str]]]:
        """The card's lines, the way the desktop tool writes them."""
        words = self.words
        android = info.get('android') or {}
        status = android.get('status') or ('not ported' if info.get('profile') else 'not supported')
        colour = STATUS_COLOUR.get(status, '#c62828')
        head: list[tuple[str, str]] = []
        head.append((str(info.get('name') or info.get('title_id') or ''), 'name'))
        head.append((f"  {info.get('title_id') or ''}", 'dim'))
        head.append((f"  {status}", 'ok' if colour == '#2e7d32' else ('dim' if colour == '#757575' else 'warn')))
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
        """The port button: a game that can be ported, or one the player wants to try."""
        info = self.info or {}
        ready = bool(info.get('supported')
                     or (info.get('experimental') and self.experimental.get_active()))
        self.start_button.set_sensitive(ready and bool(self.porter_root()))

    # ---- the build --------------------------------------------------------------------

    def start_build(self) -> None:
        words = self.words
        folder = self.folder.get_text().strip()
        if not folder:
            dialogs.message(self, words['app_title'], words['build_need_file'])
            return
        if not settings.library_set(self.app.settings):
            dialogs.message(self, words['app_title'], words['build_need_data_dir'])
            return
        root = self.porter_root()
        if not root:
            dialogs.message(self, words['app_title'], words['build_no_porter'].format(path=folder),
                            'error')
            return
        # The pack is built in a staging folder; only a build that ends well moves into
        # the data directory, so a failed one leaves nothing behind.
        library_dir = settings.library_dir(self.app.settings)
        title_id = str((self.info or {}).get('title_id') or '').strip().upper()
        self.staging = library.staging_dir(library_dir, title_id or Path(folder).stem)
        library.discard(self.staging)
        args = ['port', folder, '--progress', 'json', '-o', str(self.staging)]
        name = self.name.get_text().strip()
        if name:
            args += ['--app-name', name]
        language = GAME_LANGUAGES[self.language.get_active()][0] if self.language.get_active() >= 0 else ''
        if language:
            args += ['--language', language]
        headroom = self.headroom_value()
        if headroom is not None:
            args += ['--alias-headroom', str(headroom)]
        if self.font.get_text().strip():
            args += ['--shared-font', self.font.get_text().strip()]
        if self.fps60.get_active():
            args.append('--fps60')
        if self.touch.get_active():
            args.append('--touch')
        if self.no_menu.get_active():
            args.append('--no-menu-button')
        if self.mt_replay.get_active():
            args.append('--mt-replay')
        if self.debug.get_active():
            args.append('--debug')
        if self.experimental.get_active() and not (self.info or {}).get('supported'):
            args.append('--experimental')
        self.result = None
        self.cancelled = False
        self.started_at = time.time()
        self.clear_stages()
        self.log.get_buffer().set_text('')
        self.progress.set_fraction(0)
        self.progress.set_show_text(False)
        self.step.set_text(words['build_running'])
        self.start_button.set_sensitive(False)
        self.cancel_button.set_sensitive(True)
        self.open_button.set_sensitive(False)
        self.porter = runner.Porter(root)
        self.porter.start(args)
        self.poll()

    def headroom_value(self) -> int | None:
        """The extra address space in GB; None when it is left on automatic."""
        raw = self.headroom.get_text().strip()
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
        if self.porter:
            self.porter.cancel()
            self.porter = None

    def open_out(self) -> None:
        if self.result and self.result.get('data'):
            open_folder(Path(str(self.result['data'])))

    def poll(self) -> bool:
        """Take the events that came in and show them."""
        if self.porter is None:
            return False
        while True:
            try:
                event = self.porter.events.get_nowait()
            except queue.Empty:
                break
            self.handle(event)
            if event.get('ev') == runner.DONE:
                self.finish(int(event.get('code') or 0))
                return False
        return GLib.timeout_add(80, self.poll)

    # ---- the stages -------------------------------------------------------------------

    def clear_stages(self) -> None:
        self.stages.clear()
        self.stage_store.clear()

    def stage_item(self, key, name: str):
        item = self.stages.get(key)
        if item is None:
            item = self.stage_store.append(('▶', name, '', ''))
            self.stages[key] = item
        return item

    def handle(self, event: dict) -> None:
        kind = event.get('ev')
        if kind == 'stage':
            item = self.stage_item(event.get('k'), str(event.get('name') or ''))
            self.stage_store.set_value(item, 0, '▶')
            self.step.set_text(f"[{event.get('k')}/{event.get('n')}] {event.get('name')}"
                               + (f" · {event['step']}" if event.get('step') else ''))
            self.progress.set_pulse()
        elif kind == 'step':
            self.step.set_text(f"{event.get('name')}"
                               + (f" · {event.get('step')}" if event.get('step') else ''))
        elif kind == 'progress':
            done, total = event.get('done'), event.get('total')
            count = ''
            if done is not None:
                count = f'{done:,}' + (f' / {total:,}' if total else '')
                if event.get('unit'):
                    count += f' {event["unit"]}'
            self.step.set_text(f"{event.get('name')}"
                               + (f" · {event.get('step')}" if event.get('step') else '')
                               + (f' · {count}' if count else ''))
            if event.get('frac') is not None:
                self.progress.set_fraction(max(0.0, min(1.0, float(event['frac']))))
                self.progress.set_show_text(True)
        elif kind == 'stage_end':
            item = self.stage_item(event.get('k'), str(event.get('name') or ''))
            ok = event.get('ok', True)
            self.stage_store.set_value(item, 0, '✓' if ok else '✗')
            self.stage_store.set_value(item, 2, str(event.get('summary') or ''))
            self.stage_store.set_value(item, 3, hms(event.get('elapsed')))
            self.progress.set_fraction(1.0 if ok else 0.0)
            self.progress.set_show_text(True)
        elif kind == 'say':
            self.append(str(event.get('msg') or ''))
        elif kind == 'result':
            self.result = event

    def append(self, message: str) -> None:
        buffer = self.log.get_buffer()
        buffer.insert(buffer.get_end_iter(), message + '\n')
        self.log.scroll_mark_onscreen(buffer.get_end_iter())

    def on_tick(self) -> bool:
        """The running stage's time."""
        for item in self.stage_store:
            if item[0] == '▶':
                item[3] = hms(time.time() - self.started_at)
                break
        return True

    def discard_staging(self) -> None:
        """A build that did not end well leaves nothing behind."""
        if self.staging:
            library.discard(self.staging)
            self.staging = None

    # ---- the end ----------------------------------------------------------------------

    def finish(self, code: int) -> None:
        words = self.words
        self.porter = None
        self.start_button.set_sensitive(True)
        self.cancel_button.set_sensitive(False)
        if self.cancelled or code == 130:
            self.step.set_text(words['build_cancelled'])
            self.discard_staging()
            return
        if code != 0:
            self.step.set_text(words['build_failed'])
            self.discard_staging()
            return
        data = (self.result or {}).get('data')
        if not data:
            self.step.set_text(words['build_failed'])
            self.discard_staging()
            return
        try:
            library.install(Path(str(data)), settings.library_dir(self.app.settings))
        except (OSError, ValueError) as error:
            self.step.set_text(words['build_failed'])
            self.append(f'[RED] {error}')
            self.discard_staging()
            return
        self.step.set_text(words['build_done'])
        self.open_button.set_sensitive(True)
        self.app.refresh_library()
