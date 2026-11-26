"""The window: three pages, the library in them, and the build page's fields.

The tests need a display; they are skipped when there is none (or when this Python
has no PyGObject with GTK 3, which is the case without python3-gi).
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk   # noqa: F401
    HAVE_GTK = True
except (ImportError, ValueError):      # a Python without PyGObject
    HAVE_GTK = False

from launcher import scale, settings   # noqa: E402

if HAVE_GTK:
    from launcher.ui import dialogs                     # noqa: E402
    from launcher.ui.app import LauncherApp             # noqa: E402


def make_pack(root, title_id, name, version='1.0', icon=False):
    folder = Path(root) / title_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'nx2a-data.json').write_text(json.dumps({
        'title_id': title_id, 'name': name, 'version': version,
    }), encoding='utf-8')
    if icon:
        (folder / 'icon.png').write_bytes(b'\x89PNG\r\n\x1a\n')
    return folder


def labels_of(widget):
    """The text of every label under a widget."""
    out = []
    if isinstance(widget, Gtk.Label):
        out.append(widget.get_text())
    if HAVE_GTK and isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            out.extend(labels_of(child))
    return out


def card_of(page, index=0):
    """The card itself (the FlowBox wraps every child in a FlowBoxChild)."""
    return page.inner.get_children()[index].get_child()


@unittest.skipUnless(HAVE_GTK, 'no PyGObject with GTK 3')
class Window(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        original = settings.SETTINGS_FILE
        settings.SETTINGS_FILE = Path(self.folder.name) / 'launcher.json'
        self.addCleanup(lambda: setattr(settings, 'SETTINGS_FILE', original))
        try:
            self.app = LauncherApp()
        except RuntimeError as error:       # no display
            self.skipTest(f'no display: {error}')
        self.app.show_all()
        self.addCleanup(self.app.destroy)

    def test_the_way_out_is_at_the_right_end_of_the_tabs(self):
        notebook = self.app.notebook
        self.assertIs(self.app.quit_button.get_parent(), notebook)
        self.assertIs(notebook.get_action_widget(Gtk.PackType.END), self.app.quit_button)
        self.assertEqual(self.app.quit_button.get_label(), self.app.words['quit'])
        self.assertTrue(self.app.quit_button.get_visible())

    def test_the_way_out_closes_the_window(self):
        self.app.quit()
        self.assertFalse(self.app.get_visible())

    def test_there_are_three_pages_in_a_fixed_order(self):
        notebook = self.app.notebook
        tabs = [notebook.get_tab_label_text(notebook.get_nth_page(index))
                for index in range(notebook.get_n_pages())]
        self.assertEqual(tabs, [self.app.words['tab_library'], self.app.words['tab_build'],
                                self.app.words['tab_settings']])

    def test_the_library_page_shows_the_games(self):
        library_dir = Path(self.folder.name) / 'library'
        make_pack(library_dir, '0100000000010000', 'Mario')
        self.app.settings['library'] = str(library_dir)
        self.app.library_page.refresh()
        self.assertIn('Mario', labels_of(self.app.library_page))

    def test_an_empty_library_says_so(self):
        self.app.settings['library'] = str(Path(self.folder.name) / 'empty')
        self.app.library_page.refresh()
        self.assertIn(self.app.words['library_empty'], labels_of(self.app.library_page))

    def test_a_phone_sized_screen_keeps_two_columns_at_most(self):
        page = self.app.library_page
        page._on_size(None, SimpleNamespace(width=480))
        self.assertLessEqual(page.inner.get_max_children_per_line(), 2)

    def test_a_wide_screen_gets_the_columns_it_can_hold(self):
        page = self.app.library_page
        page._on_size(None, SimpleNamespace(width=1400))
        self.assertGreater(page.inner.get_max_children_per_line(), 2)

    def test_an_icon_that_cannot_be_read_falls_back_to_the_first_letter(self):
        library_dir = Path(self.folder.name) / 'library'
        pack = make_pack(library_dir, '0100000000010000', 'Mario')
        (pack / 'icon.png').write_bytes(b'not an image at all')
        self.app.settings['library'] = str(library_dir)
        self.app.library_page.refresh()
        card = card_of(self.app.library_page)
        self.assertIsInstance(card.get_children()[0], Gtk.Frame)
        self.assertIn('Mario', labels_of(self.app.library_page))

    def test_a_card_has_the_three_actions(self):
        library_dir = Path(self.folder.name) / 'library'
        make_pack(library_dir, '0100000000010000', 'Mario')
        self.app.settings['library'] = str(library_dir)
        self.app.library_page.refresh()
        card = card_of(self.app.library_page)
        buttons = [child for child in card.get_children() if isinstance(child, Gtk.Box)][-1]
        labels = [b.get_label() for b in buttons.get_children() if isinstance(b, Gtk.Button)]
        self.assertEqual(labels, [self.app.words['run'], self.app.words['add_steam'],
                                  self.app.words['add_desktop']])

    def test_the_build_page_wants_a_data_directory(self):
        shown = []
        original = dialogs.message
        dialogs.message = lambda *args, **kwargs: shown.append(args)
        try:
            self.app.settings['library'] = ''
            self.app.build_page.folder.set_text(str(Path(self.folder.name) / 'game.nsp'))
            self.app.build_page.start_build()
        finally:
            dialogs.message = original
        self.assertTrue(shown)
        self.assertIn(self.app.words['build_need_data_dir'], shown[-1][2])

    def test_the_build_page_wants_a_game_file(self):
        shown = []
        original = dialogs.message
        dialogs.message = lambda *args, **kwargs: shown.append(args)
        try:
            self.app.settings['library'] = str(Path(self.folder.name) / 'library')
            self.app.build_page.start_build()
        finally:
            dialogs.message = original
        self.assertTrue(shown)
        self.assertIn(self.app.words['build_need_file'], shown[-1][2])

    def test_the_port_button_waits_for_the_game(self):
        page = self.app.build_page
        self.assertFalse(page.start_button.get_sensitive())
        page.info = {'supported': True, 'title_id': '0100000000010000', 'name': 'Mario'}
        page.update_port_button()
        self.assertTrue(page.start_button.get_sensitive())

    def test_a_game_without_a_profile_needs_the_ticket(self):
        page = self.app.build_page
        page.info = {'supported': False, 'experimental': True}
        page.update_port_button()
        self.assertFalse(page.start_button.get_sensitive())
        page.experimental.set_active(True)
        page.update_port_button()
        self.assertTrue(page.start_button.get_sensitive())

    def test_the_card_shows_the_game(self):
        page = self.app.build_page
        lines = page.card_lines({'name': 'Mario', 'title_id': '0100000000010000', 'supported': True,
                                 'android': {'status': 'playable'},
                                 'updates': [{'version': '1.2.1'}], 'dlc': []})
        content = ''.join(part for parts in lines for part, _ in parts)
        self.assertIn('Mario', content)
        self.assertIn('0100000000010000', content)
        self.assertIn('playable', content)
        self.assertIn('update 1.2.1', content)

    def test_the_name_row_says_the_games_own_name(self):
        page = self.app.build_page
        page.set_name_label('Mario')
        self.assertIn('Mario', page.name_label.get_text())
        page.set_name_label('')
        self.assertNotIn('Mario', page.name_label.get_text())

    def test_the_extra_address_space_is_automatic_by_default(self):
        page = self.app.build_page
        self.assertIsNone(page.headroom_value())
        page.headroom.set_text('16')
        self.assertEqual(page.headroom_value(), 16)
        page.headroom.set_text('999')
        self.assertIsNone(page.headroom_value())

    def test_the_stages_table_has_its_columns(self):
        page = self.app.build_page
        self.assertEqual(page.stage_store.get_n_columns(), 4)
        titles = [column.get_title() for column in page.stage_view.get_columns()]
        self.assertEqual(titles[1:], [self.app.words['build_stages'], self.app.words['build_result'],
                                     self.app.words['build_time']])


class SmallScreen(unittest.TestCase):
    """The rules of a phone-sized screen, without a phone."""

    def test_a_small_screen_shows_two_columns_at_most(self):
        for width in (320, 480, 600):
            self.assertLessEqual(scale.columns(width, 1.0, small=True), 2)

    def test_a_wide_screen_shows_more(self):
        self.assertGreaterEqual(scale.columns(1400, 1.0, small=False), 4)


if __name__ == '__main__':
    unittest.main()
