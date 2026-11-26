"""The window: three pages and the settings they share."""
from __future__ import annotations

import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gtk   # noqa: E402

from launcher import scale, settings   # noqa: E402
from launcher.ui import text           # noqa: E402
from launcher.ui.build_page import BuildPage      # noqa: E402
from launcher.ui.library_page import LibraryPage  # noqa: E402
from launcher.ui.settings_page import SettingsPage  # noqa: E402

BASE_DPI = 96.0     # what a scale of 1.0 means


class LauncherApp(Gtk.Window):
    """The main window: the three pages under one row of tabs."""

    def __init__(self, current: dict | None = None):
        super().__init__()
        self.settings = current if current is not None else settings.load()
        self.words = text.strings(self.settings.get('language') or 'zh')
        self.set_title(self.words['app_title'])
        # Defaults for a screen we never got to measure (no display, a headless test):
        # the pages ask for these the moment they are built.
        self.short_side = 0
        self.small = False
        self._fit_to_screen()

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(box)

        self.notebook = Gtk.Notebook()
        self.notebook.set_vexpand(True)
        # The tabs on the left, the way out on the right — the two ends of one row.
        self.quit_button = Gtk.Button(label=self.words['quit'])
        self.quit_button.set_margin_start(8)
        self.quit_button.set_margin_end(8)
        self.quit_button.set_margin_top(4)
        self.quit_button.set_margin_bottom(4)
        self.quit_button.connect('clicked', lambda _button: self.quit())
        self.notebook.set_action_widget(self.quit_button, Gtk.PackType.END)
        # show_all() does not reach an action widget (it sits in the notebook's own
        # box), so the button is shown here or it never appears.
        self.quit_button.show()
        box.pack_start(self.notebook, True, True, 0)

        self.library_page = LibraryPage(self)
        self.build_page = BuildPage(self)
        self.settings_page = SettingsPage(self)
        self.pages = ((self.library_page, 'tab_library'), (self.build_page, 'tab_build'),
                      (self.settings_page, 'tab_settings'))
        for page, key in self.pages:
            self.notebook.append_page(page, Gtk.Label(label=self.words[key]))

        self._apply_scale()

    # ---- the window -------------------------------------------------------------------

    def _fit_to_screen(self) -> None:
        """The window takes the screen.

        A window bigger than the screen is not just ugly: a compositor that scales what
        it gets (gamescope does) stretches it, and the text ends up distorted.  The pages
        scroll, so the screen is enough.
        """
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() if display else None
        if monitor is None:
            return
        area = monitor.get_geometry()
        self.set_default_size(area.width, area.height)
        self.short_side = min(area.width, area.height)
        self.small = scale.is_small(self.short_side)

    def _apply_scale(self) -> None:
        """The interface's own size, as the player set it.

        GTK draws with the Xft DPI, so the player's multiplier is that: everything
        (the fonts, and with them the touch targets) grows with it.
        """
        factor = scale.user_scale(self.settings.get('ui_scale'))
        gtk_settings = Gtk.Settings.get_default()
        if gtk_settings is not None:
            # The property counts in 1024ths of a DPI (the XSETTINGS convention):
            # plain96 would mean a resolution of 0.09 DPI and the text would shrink
            # to nothing.
            gtk_settings.set_property('gtk-xft-dpi', int(BASE_DPI * factor * 1024))

    def quit(self) -> None:
        """Leave the launcher."""
        self.build_page.stop_porter()
        self.destroy()

    # ---- what the pages ask for -------------------------------------------------------

    def refresh_library(self) -> None:
        self.library_page.refresh()

    def reload_settings(self) -> None:
        """The settings were saved: the new values are in force from now on."""
        self.settings = settings.load()
        self.words = text.strings(self.settings.get('language') or 'zh')
        self.set_title(self.words['app_title'])
        self.quit_button.set_label(self.words['quit'])
        self._apply_scale()
        for page, key in self.pages:
            self.notebook.set_tab_label_text(page, self.words[key])
        self.library_page.rebuild()
        self.build_page.rebuild()
        self.settings_page.rebuild()
