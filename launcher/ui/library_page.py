"""The library page: the ported games, in a grid of cards.

The grid's width decides how many cards fit; on a phone-sized screen it never shows
more than two.  The cards show the game's icon, its name and its version, and the two
things a player does with a game: run it, or put it in Steam's library.
"""
from __future__ import annotations

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import GdkPixbuf, GLib, Gtk   # noqa: E402

from launcher import launch, library, scale, settings, steam   # noqa: E402
from launcher.ui import dialogs   # noqa: E402

ICON_SIZE = 96


class LibraryPage(Gtk.Box):
    """The games in the data directory."""

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.words = app.words

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        self.add(scroller)

        self.inner = Gtk.FlowBox()
        self.inner.set_selection_mode(Gtk.SelectionMode.NONE)
        self.inner.set_row_spacing(12)
        self.inner.set_column_spacing(12)
        self.inner.set_margin_start(16)
        self.inner.set_margin_end(16)
        self.inner.set_margin_top(16)
        self.inner.set_margin_bottom(16)
        scroller.add(self.inner)
        # The width decides how many cards fit; a phone-sized screen never gets more
        # than two (the rule the FlowBox would otherwise break on a wide window).
        self.inner.connect('size-allocate', self._on_size)

        self.refresh()

    def _on_size(self, _flowbox, allocation) -> None:
        limit = self.columns(allocation.width)
        if self.inner.get_max_children_per_line() != limit:
            self.inner.set_max_children_per_line(limit)

    # ---- the layout ------------------------------------------------------------------

    def rebuild(self) -> None:
        """The page is built again (the settings changed)."""
        self.refresh()

    def refresh(self) -> None:
        """Read the library again and show what is in it."""
        for child in self.inner.get_children():
            self.inner.remove(child)
        games = library.scan(settings.library_dir(self.app.settings))
        if not games:
            label = Gtk.Label(label=self.words['library_empty'])
            label.set_line_wrap(True)
            label.set_max_width_chars(60)
            label.set_halign(Gtk.Align.CENTER)
            self.inner.add(label)
            return
        for game in games:
            self.inner.add(self.card(game))

    def columns(self, width: int) -> int:
        """How many cards fit in this width."""
        return scale.columns(width, 1.0, self.app.small)

    def card(self, game: library.Game) -> Gtk.Box:
        """One game: its icon, its name, and what a player can do with it."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_size_request(220, -1)

        image = self.make_icon(game)
        image.set_halign(Gtk.Align.START)
        box.pack_start(image, False, False, 0)

        title = Gtk.Label(label=game.name)
        title.set_xalign(0)
        title.set_line_wrap(True)
        title.set_max_width_chars(20)
        title.get_style_context().add_class('heading')
        box.pack_start(title, False, False, 0)

        if game.version:
            version = Gtk.Label(label=game.version)
            version.set_xalign(0)
            version.get_style_context().add_class('dim-label')
            box.pack_start(version, False, False, 0)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        run = Gtk.Button(label=self.words['run'])
        run.connect('clicked', lambda _b, g=game: self.run_game(g))
        buttons.pack_start(run, False, False, 0)

        in_steam = self.in_steam(game)
        steam_button = Gtk.Button(label=self.words['remove_steam'] if in_steam
                                  else self.words['add_steam'])
        steam_button.connect('clicked', lambda _b, g=game: self.toggle_steam(g))
        buttons.pack_start(steam_button, False, False, 0)

        has_desktop = steam.desktop_entry_path(game.title_id).is_file()
        desktop_button = Gtk.Button(label=self.words['remove_desktop'] if has_desktop
                                    else self.words['add_desktop'])
        desktop_button.connect('clicked', lambda _b, g=game: self.toggle_desktop(g))
        buttons.pack_start(desktop_button, False, False, 0)
        box.pack_start(buttons, False, False, 0)
        return box

    def make_icon(self, game: library.Game) -> Gtk.Widget:
        """The game's icon, or its first letter when the icon cannot be read."""
        if game.icon_path.is_file():
            try:
                # new_from_file() on a Gtk.Image only warns about a broken file and
                # shows nothing; loading the pixbuf ourselves is what can fail.
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(game.icon_path))
                scaled = pixbuf.scale_simple(ICON_SIZE, ICON_SIZE,
                                             GdkPixbuf.InterpType.BILINEAR)
                image = Gtk.Image.new_from_pixbuf(scaled or pixbuf)
                return image
            except GLib.Error:
                pass
        frame = Gtk.Frame()
        frame.set_size_request(ICON_SIZE, ICON_SIZE)
        label = Gtk.Label(label=(game.name[:1] or '?').upper())
        label.get_style_context().add_class('title-1')
        frame.add(label)
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
