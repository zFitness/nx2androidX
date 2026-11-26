"""The settings page: where the data directory is, how the interface looks."""
from __future__ import annotations

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk   # noqa: E402

from launcher import runner, settings   # noqa: E402
from launcher.ui import dialogs         # noqa: E402


class SettingsPage(Gtk.Box):
    """The settings: the data folder, the language, the size, the profiles."""

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.words = app.words
        self.build()

    def build(self) -> None:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        self.add(scroller)

        grid = Gtk.Grid(column_spacing=10, row_spacing=6)
        grid.set_margin_start(16)
        grid.set_margin_end(16)
        grid.set_margin_top(16)
        grid.set_margin_bottom(16)
        scroller.add(grid)

        self.library = Gtk.Entry()
        self.library.set_hexpand(True)
        self.library.set_text(str(self.app.settings.get('library') or ''))
        data_dir = Gtk.Label(label=self.words['set_data_dir'])
        data_dir.set_xalign(0)
        grid.attach(data_dir, 0, 0, 1, 1)
        grid.attach(self.library, 1, 0, 1, 1)
        browse = Gtk.Button(label=self.words['browse'])
        browse.connect('clicked', lambda _b: self.pick_library())
        grid.attach(browse, 2, 0, 1, 1)
        hint = Gtk.Label(label=self.words['set_data_dir_hint'])
        hint.set_xalign(0)
        grid.attach(hint, 1, 1, 2, 1)

        language = Gtk.Label(label=self.words['set_language'])
        language.set_xalign(0)
        self.language = Gtk.ComboBoxText()
        self.language.append_text(self.words['language_zh'])
        self.language.append_text(self.words['language_en'])
        self.language.set_active(0 if self.app.settings.get('language') == 'zh' else 1)
        grid.attach(language, 0, 2, 1, 1)
        grid.attach(self.language, 1, 2, 1, 1)

        scale_label = Gtk.Label(label=self.words['set_scale'])
        scale_label.set_xalign(0)
        self.ui_scale = Gtk.SpinButton.new_with_range(0.5, 3.0, 0.1)
        self.ui_scale.set_value(float(self.app.settings.get('ui_scale') or 1.0))
        grid.attach(scale_label, 0, 3, 1, 1)
        grid.attach(self.ui_scale, 1, 3, 1, 1)

        profiles = Gtk.Label(label=self.words['set_profiles'])
        profiles.set_xalign(0)
        import_profiles = Gtk.Button(label=self.words['browse'])
        import_profiles.connect('clicked', lambda _b: self.pick_profiles())
        grid.attach(profiles, 0, 4, 1, 1)
        grid.attach(import_profiles, 1, 4, 1, 1)
        profiles_hint = Gtk.Label(label=self.words['set_profiles_hint'])
        profiles_hint.set_xalign(0)
        profiles_hint.set_line_wrap(True)
        profiles_hint.set_max_width_chars(60)      # a wrapping label in a scrolled
        # window asks for its own width; without a bound the two never stop asking
        grid.attach(profiles_hint, 1, 5, 2, 1)

        save = Gtk.Button(label=self.words['set_save'])
        save.connect('clicked', lambda _b: self.save())
        grid.attach(save, 0, 6, 1, 1)

    def rebuild(self) -> None:
        """The page is built again (the settings changed)."""
        for child in self.get_children():
            self.remove(child)
        self.build()

    # ---- what the player picks --------------------------------------------------------

    def pick_library(self) -> None:
        chosen = dialogs.choose_file(self, self.words['set_data_dir'], self.words, folder=True)
        if chosen:
            self.library.set_text(chosen)

    def pick_profiles(self) -> None:
        """Import a package of game profiles (the thin package needs them to port)."""
        chosen = dialogs.choose_file(self, self.words['set_profiles'], self.words,
                                     [('Profile package', '*.zip'), ('All files', '*.*')])
        if chosen:
            self.import_profiles(chosen)

    def import_profiles(self, path: str) -> None:
        words = self.words
        root = runner.porter_root(str(self.app.settings.get('porter_dir') or ''))
        if not root:
            dialogs.message(self, words['app_title'], words['build_no_porter'].format(path=path),
                            'error')
            return
        code, out, err = runner.run_text(root, ['profiles', 'import', path])
        if code != 0:
            dialogs.message(self, words['app_title'],
                            words['profiles_failed'].format(message=err or out), 'error')
            return
        dialogs.message(self, words['app_title'], out or words['profiles_imported'])

    def save(self) -> None:
        words = self.words
        current = dict(self.app.settings)
        current['library'] = self.library.get_text().strip()
        current['language'] = 'zh' if self.language.get_active() == 0 else 'en'
        try:
            current['ui_scale'] = float(self.ui_scale.get_value())
        except ValueError:
            current['ui_scale'] = 1.0
        if current['ui_scale'] <= 0:
            current['ui_scale'] = 1.0
        settings.save(current)
        self.app.reload_settings()
        dialogs.message(self, words['app_title'], words['set_saved'])
