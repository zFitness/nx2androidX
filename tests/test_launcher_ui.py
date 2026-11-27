"""The window: three pages, the library in them, and the build page's fields.

The tests run on Qt's offscreen platform: no display is needed, only PySide6.
QT_QPA_PLATFORM has to be set before PySide6 is imported, so it happens first thing.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from PySide6.QtCore import Qt                     # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton   # noqa: E402

from launcher import runner, scale, settings      # noqa: E402
from launcher.ui import dialogs                   # noqa: E402
from launcher.ui.app import LauncherApp           # noqa: E402
from porter import config as porter_config        # noqa: E402


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
    return [label.text() for label in widget.findChildren(QLabel)]


def card_of(page, index=0):
    """One card of the grid (a refresh rebuilds them all)."""
    return page.cards[index]


class Window(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # One QApplication for the whole run: Qt wants a single instance.
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        original = settings.SETTINGS_FILE
        settings.SETTINGS_FILE = Path(self.folder.name) / 'launcher.json'
        self.addCleanup(lambda: setattr(settings, 'SETTINGS_FILE', original))
        # The porter's own config (prod.keys and friends) goes to NX2A_HOME; a private
        # one here, so the tests never read (or write) the player's real config.
        self.nx2a_home = tempfile.TemporaryDirectory()
        self.addCleanup(self.nx2a_home.cleanup)
        original_home = os.environ.get('NX2A_HOME')
        os.environ['NX2A_HOME'] = self.nx2a_home.name
        self.addCleanup(lambda: (os.environ.pop('NX2A_HOME', None) if original_home is None
                                 else os.environ.__setitem__('NX2A_HOME', original_home)))
        keys = Path(self.nx2a_home.name) / 'prod.keys'
        keys.write_text('', encoding='utf-8')
        porter_config.set_value('keys', str(keys))   # the default state passes the keys gate
        self.app = LauncherApp()
        self.app.show()
        self.addCleanup(self.app.close)

    def test_the_way_out_is_at_the_right_end_of_the_tabs(self):
        notebook = self.app.notebook
        self.assertIs(notebook.cornerWidget(Qt.TopRightCorner), self.app.quit_button)
        self.assertEqual(self.app.quit_button.text(), self.app.words['quit'])
        self.assertTrue(self.app.quit_button.isVisibleTo(notebook))

    def test_the_way_out_closes_the_window(self):
        self.app.quit()
        self.assertFalse(self.app.isVisible())

    def test_closing_the_window_stops_everything(self):
        """The WM's close button closes the window: the porter stops with it, or the
        process would run on invisibly, holding its instance lock."""
        stopped = []
        self.app.build_page.stop_porter = lambda: stopped.append(1)
        self.app.close()
        self.assertTrue(stopped)

    def test_there_are_three_pages_in_a_fixed_order(self):
        notebook = self.app.notebook
        tabs = [notebook.tabText(index) for index in range(notebook.count())]
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
        page.app.small = True
        self.assertLessEqual(page.columns(480), 2)

    def test_a_wide_screen_gets_the_columns_it_can_hold(self):
        page = self.app.library_page
        page.app.small = False
        self.assertGreater(page.columns(1400), 2)

    def test_the_cards_rearrange_when_the_width_changes(self):
        library_dir = Path(self.folder.name) / 'library'
        for title_id in ('0100000000010000', '0100000000010001', '0100000000010002'):
            make_pack(library_dir, title_id, f'Game {title_id[-1]}')
        self.app.settings['library'] = str(library_dir)
        page = self.app.library_page
        page.refresh()
        self.assertEqual(page.grid.count(), 3)
        page.app.small = True
        page.reflow(480)   # two columns at most: the third card wraps to the next row
        row, column = page.grid.getItemPosition(2)[:2]
        self.assertEqual((row, column), (1, 0))

    def test_an_icon_that_cannot_be_read_falls_back_to_the_first_letter(self):
        library_dir = Path(self.folder.name) / 'library'
        pack = make_pack(library_dir, '0100000000010000', 'Mario')
        (pack / 'icon.png').write_bytes(b'not an image at all')
        self.app.settings['library'] = str(library_dir)
        self.app.library_page.refresh()
        card = card_of(self.app.library_page)
        self.assertIsInstance(card.layout().itemAt(0).widget(), QFrame)
        self.assertIn('Mario', labels_of(self.app.library_page))

    def test_a_card_has_the_three_actions(self):
        library_dir = Path(self.folder.name) / 'library'
        make_pack(library_dir, '0100000000010000', 'Mario')
        self.app.settings['library'] = str(library_dir)
        self.app.library_page.refresh()
        card = card_of(self.app.library_page)
        labels = [button.text() for button in card.findChildren(QPushButton)]
        self.assertEqual(labels, [self.app.words['run'], self.app.words['add_steam'],
                                  self.app.words['add_desktop']])

    def test_the_build_page_wants_a_data_directory(self):
        shown = []
        original = dialogs.message
        dialogs.message = lambda *args, **kwargs: shown.append(args)
        try:
            self.app.settings['library'] = ''
            self.app.build_page.folder.setText(str(Path(self.folder.name) / 'game.nsp'))
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

    def test_the_build_page_wants_prod_keys(self):
        shown = []
        original = dialogs.message
        dialogs.message = lambda *args, **kwargs: shown.append(args)
        configured = porter_config.load()['keys']
        porter_config.set_value('keys', '')
        self.addCleanup(porter_config.set_value, 'keys', configured)
        try:
            self.app.settings['library'] = str(Path(self.folder.name) / 'library')
            self.app.build_page.folder.setText(str(Path(self.folder.name) / 'game.nsp'))
            self.app.build_page.start_build()
        finally:
            dialogs.message = original
        self.assertTrue(shown)
        self.assertIn(self.app.words['build_need_keys'], shown[-1][2])
        # the dialog says where to fix it, and the window is already there
        self.assertIs(self.app.notebook.currentWidget(), self.app.settings_page)

    def test_the_settings_page_holds_the_keys_and_saves_them_back(self):
        page = self.app.settings_page
        keys = str(Path(self.nx2a_home.name) / 'other.keys')
        page.keys.setText(keys)
        shown = []
        original = dialogs.message
        dialogs.message = lambda *args, **kwargs: shown.append(args)
        try:
            page.save()
        finally:
            dialogs.message = original
        self.assertEqual(porter_config.load()['keys'], keys)

    def test_an_inspect_runs_off_the_interface_thread(self):
        page = self.app.build_page
        folder = Path(self.folder.name) / 'game'
        folder.mkdir()
        calls = []
        original = runner.run_json_async
        runner.run_json_async = lambda root, args, callback, **kw: calls.append((root, args, callback))
        self.addCleanup(setattr, runner, 'run_json_async', original)
        page.folder.setText(str(folder))
        page.inspect()
        self.assertEqual(len(calls), 1)
        _, args, callback = calls[0]
        self.assertEqual(args[:2], ['inspect', str(folder)])
        self.assertFalse(page.inspect_button.isEnabled())   # one look in flight
        callback({'name': 'Mario', 'title_id': '0100000000010000', 'supported': True}, 0, '')
        self.assertTrue(page.inspect_button.isEnabled())
        self.assertIn('Mario', page.card.text())
        self.assertEqual((page.info or {}).get('name'), 'Mario')

    def test_a_stale_inspect_is_thrown_away(self):
        page = self.app.build_page
        folder = Path(self.folder.name) / 'game'
        folder.mkdir()
        calls = []
        original = runner.run_json_async
        runner.run_json_async = lambda root, args, callback, **kw: calls.append((root, args, callback))
        self.addCleanup(setattr, runner, 'run_json_async', original)
        page.folder.setText(str(folder))
        page.inspect()
        page.folder.setText(str(Path(self.folder.name) / 'other.nsp'))   # edited meanwhile
        _, _, callback = calls[0]
        callback({'name': 'Mario', 'title_id': '0100000000010000', 'supported': True}, 0, '')
        self.assertIsNone(page.info)   # the answer to the old path never touches the card
        self.assertNotIn('Mario', page.card.text())
        self.assertTrue(page.inspect_button.isEnabled())

    def test_a_profile_import_runs_off_the_interface_thread(self):
        page = self.app.settings_page
        calls = []
        original = runner.run_text_async
        runner.run_text_async = lambda root, args, callback, **kw: calls.append((root, args, callback))
        self.addCleanup(setattr, runner, 'run_text_async', original)
        page.import_profiles('/tmp/profiles.zip')
        self.assertEqual(len(calls), 1)
        _, args, _ = calls[0]
        self.assertEqual(args, ['profiles', 'import', '/tmp/profiles.zip'])
        self.assertFalse(page.profiles_button.isEnabled())   # asleep while importing
        shown = []
        original_dialog = dialogs.message
        dialogs.message = lambda *args, **kwargs: shown.append(args)
        try:
            calls[0][2](0, '3 profiles imported', '')
        finally:
            dialogs.message = original_dialog
        self.assertTrue(page.profiles_button.isEnabled())
        self.assertIn('3 profiles imported', shown[-1][2])

    def test_the_port_button_waits_for_the_game(self):
        page = self.app.build_page
        self.assertFalse(page.start_button.isEnabled())
        page.info = {'supported': True, 'title_id': '0100000000010000', 'name': 'Mario'}
        page.update_port_button()
        self.assertTrue(page.start_button.isEnabled())

    def test_a_game_without_a_profile_needs_the_ticket(self):
        page = self.app.build_page
        page.info = {'supported': False, 'experimental': True}
        page.update_port_button()
        self.assertFalse(page.start_button.isEnabled())
        page.experimental.setChecked(True)   # the ticket lights the button by itself
        self.assertTrue(page.start_button.isEnabled())

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
        self.assertIn('Mario', page.name_label.text())
        page.set_name_label('')
        self.assertNotIn('Mario', page.name_label.text())

    def test_the_extra_address_space_is_automatic_by_default(self):
        page = self.app.build_page
        self.assertIsNone(page.headroom_value())
        page.headroom.setText('16')
        self.assertEqual(page.headroom_value(), 16)
        page.headroom.setText('999')
        self.assertIsNone(page.headroom_value())

    def test_the_stages_table_has_its_columns(self):
        page = self.app.build_page
        self.assertEqual(page.stage_view.columnCount(), 4)
        titles = [page.stage_view.headerItem().text(index)
                  for index in range(page.stage_view.columnCount())]
        self.assertEqual(titles[1:], [self.app.words['build_stages'], self.app.words['build_result'],
                                      self.app.words['build_time']])

    def test_a_stage_becomes_a_row_and_its_end_updates_the_row(self):
        page = self.app.build_page
        page.handle({'ev': 'stage', 'k': 'build', 'n': 3, 'name': 'the host'})
        self.assertEqual(page.stage_view.topLevelItemCount(), 1)
        item = page.stage_view.topLevelItem(0)
        self.assertEqual(item.text(0), '▶')
        page.handle({'ev': 'stage_end', 'k': 'build', 'name': 'the host', 'ok': True,
                     'summary': 'done', 'elapsed': 95})
        self.assertEqual(item.text(0), '✓')
        self.assertEqual(item.text(1), 'the host')
        self.assertEqual(item.text(2), 'done')
        self.assertEqual(item.text(3), '1:35')

    def test_a_log_line_is_appended(self):
        page = self.app.build_page
        page.append('rewriting the game')
        self.assertIn('rewriting the game', page.log.toPlainText())


class SmallScreen(unittest.TestCase):
    """The rules of a phone-sized screen, without a phone."""

    def test_a_small_screen_shows_two_columns_at_most(self):
        for width in (320, 480, 600):
            self.assertLessEqual(scale.columns(width, 1.0, small=True), 2)

    def test_a_wide_screen_shows_more(self):
        self.assertGreaterEqual(scale.columns(1400, 1.0, small=False), 4)


if __name__ == '__main__':
    unittest.main()
