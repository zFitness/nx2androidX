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

from PySide6.QtWidgets import QApplication, QLabel, QSizePolicy   # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt   # noqa: E402
from PySide6.QtGui import QMouseEvent   # noqa: E402

from launcher import packenv, runner, scale, settings      # noqa: E402
from launcher.ui import dialogs, theme, widgets   # noqa: E402
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

    def test_the_way_out_is_the_bars_last_control(self):
        """The window draws its own chrome: the three circles sit at the bar's right
        end, and the way out of them closes the window."""
        bar = self.app.titlebar
        self.assertEqual(bar.close_button._glyph, 'close')
        self.assertEqual(bar.max_button._glyph, 'max')
        self.assertEqual(bar.min_button._glyph, 'min')
        self.assertTrue(bar.close_button.isVisibleTo(bar))
        bar.close_button.click()
        self.assertFalse(self.app.isVisible())

    def test_the_panel_speaks_for_the_chosen_game(self):
        """The action panel carries the chosen game's actions and only exists
        while a game is picked; picking the same card again puts it away."""
        library_dir = Path(self.folder.name) / 'library'
        make_pack(library_dir, '0100000000010000', 'Mario')
        self.app.settings['library'] = str(library_dir)
        self.app.library_page.refresh()
        page = self.app.library_page
        page.pick(page.cards[0])
        self.assertTrue(page.panel.isVisible())
        self.assertEqual(page.panel.title.text(), 'Mario')
        labels = [page.panel.run_button.text(), page.panel.steam_button.text(),
                  page.panel.desktop_button.text()]
        self.assertEqual(labels, [self.app.words['run'], self.app.words['add_steam'],
                                  self.app.words['add_desktop']])
        page.pick(page.cards[0])   # the same card again: the panel goes away
        self.assertFalse(page.panel.isVisible())

    def test_the_grid_packs_from_the_first_column(self):
        """A tight left-aligned grid: the cards sit next to each other (the gap,
        not a spread-out column), and the empty library says so."""
        library_dir = Path(self.folder.name) / 'library'
        for title_id in ('0100000000010000', '0100000000010001'):
            make_pack(library_dir, title_id, f'Game {title_id[-1]}')
        self.app.settings['library'] = str(library_dir)
        page = self.app.library_page
        page.refresh()
        page.reflow(1400)   # a wide window: four columns, the two games sit side by side
        row0, col0 = page.grid.getItemPosition(0)[:2]
        row1, col1 = page.grid.getItemPosition(1)[:2]
        self.assertEqual((row0, row1), (0, 0))       # both on the first row
        self.assertEqual(col1, 1)                    # the second right beside the first
        first = page.grid.cellRect(0, 0)
        second = page.grid.cellRect(0, 1)
        self.assertLess(second.x() - first.x(), 400)  # neighbours, not half a window apart

    def test_a_card_does_not_stretch_to_the_row(self):
        """The selection frame hugs the card. The grid's rows used to stretch the
        card's frame far past its content (the tablet's tall rows made the box
        much longer than the card it marked)."""
        library_dir = Path(self.folder.name) / 'library'
        make_pack(library_dir, '0100000000010000', 'Game')
        self.app.settings['library'] = str(library_dir)
        page = self.app.library_page
        page.refresh()
        page.reflow(1400)
        card = page.cards[0]
        self.assertEqual(card.sizePolicy().verticalPolicy(), QSizePolicy.Maximum)
        item = page.grid.itemAtPosition(0, 0)
        self.assertTrue(item.alignment() & Qt.AlignTop)   # top-anchored, never stretched

    def test_the_pages_capsule_answers_the_press(self):
        """One press switches the page. On a touch screen a release often never
        arrives (the finger moved), and the tab only answered a double click."""
        capsule = widgets.FlatSegmented(
            [('library', 'Library', ''), ('build', 'Build', '')], selected='library')
        capsule.resize(int(capsule.sizeHint().width()), 40)
        picked = []
        capsule.changed.connect(picked.append)
        rect = capsule._segment_rects()[1][3]
        point = QPointF(rect.center().x(), rect.center().y())
        capsule.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, point, point,
                                            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        self.assertEqual(picked, ['build'])
        self.assertEqual(capsule.selected(), 'build')

    def test_the_experimental_port_sits_with_the_everyday_options(self):
        """Not behind the advanced toggle: the Android build page's own order."""
        page = self.app.build_page
        self.assertFalse(page._advanced_group.isAncestorOf(page.experimental))
        self.assertFalse(page._advanced_group.isVisible())
        self.assertTrue(page.experimental.isVisibleTo(page))

    def test_a_game_without_a_profile_gets_the_experimental_port_ticked(self):
        """The porter has no profile for the game: the option is ticked for the player
        and the card says why (the Android build page does the same)."""
        page = self.app.build_page
        folder = str(Path(self.folder.name) / 'game.nsp')
        page.folder.setText(folder)
        self.assertFalse(page.experimental.isChecked())
        page.inspect_done(folder, {'title_id': '0100000000010000', 'name': 'Game',
                                   'supported': False, 'experimental': True,
                                   'android': {'status': 'not supported'}}, 0, '')
        self.assertTrue(page.experimental.isChecked())
        self.assertIn(self.app.words['build_experimental_auto'], page.card.text())
        self.assertTrue(page.start_button.isEnabled())   # ticked: the port may be tried

    def test_the_library_picks_a_games_language_into_its_pack(self):
        """The manage menu's language choice is written into the pack's env.txt (DM_LANG),
        the row the host reads at its start; the pack's other rows stay."""
        library_dir = Path(self.folder.name) / 'library'
        pack = make_pack(library_dir, '0100000000010000', 'Game')
        (pack / 'languages.txt').write_text('ja\tJapanese\nzh-Hans\tChinese (Simplified)\n',
                                            encoding='utf-8')
        (pack / 'env.txt').write_text('DM_ROMFS=/x\nDM_LANG=system\n', encoding='utf-8')
        self.app.settings['library'] = str(library_dir)
        page = self.app.library_page
        page.refresh()
        page.pick(page.cards[0])
        game = page.selected_game()
        self.assertEqual(packenv.languages(game.path),
                         [('ja', 'Japanese'), ('zh-Hans', 'Chinese (Simplified)')])
        self.assertEqual(packenv.current_language(game.path), 'system')
        page._pick_language(game, 'zh-Hans')
        self.assertEqual(packenv.current_language(game.path), 'zh-Hans')
        text = (game.path / 'env.txt').read_text(encoding='utf-8')
        self.assertIn('DM_ROMFS=/x', text)   # the pack's other rows stay
        page._pick_language(game, packenv.SYSTEM)
        self.assertEqual(packenv.current_language(game.path), 'system')

    def test_zero_one_two_and_many_games_all_lay_out(self):
        """0, 1, 2, 4 and 8 games: the count changes, the formula does not."""
        page = self.app.library_page
        for count in (0, 1, 2, 4, 8):
            library_dir = Path(self.folder.name) / f'library{count}'
            for index in range(count):
                make_pack(library_dir, f'01000000000100{count:02d}{index:02d}',
                          f'Game {index}')
            self.app.settings['library'] = str(library_dir)
            page.refresh()
            page.reflow(1400)
            if count == 0:
                self.assertFalse(page.cards)
                self.assertIn(self.app.words['library_empty'], labels_of(page))
                self.assertFalse(page.panel.isVisible())
                continue
            self.assertEqual(len(page.cards), count)
            columns = page.columns(1400)
            for index in range(count):
                row, col = page.grid.getItemPosition(index)[:2]
                self.assertEqual((row, col), (index // columns, index % columns))
                self.assertTrue(page.grid.itemAtPosition(row, col).widget() is page.cards[index])

    def test_every_button_is_legible_at_rest(self):
        """A button's words must be there before the hover: at rest the text
        colour parses and is bright enough to read on the dark (once, a CSS
        rgba() spelling fell through QColor and painted black-on-black)."""
        from launcher.ui.widgets import FlatButton
        for variant in ('primary', 'quiet', 'outline', 'hero'):
            button = FlatButton('x', variant)
            colour = FlatButton._colour(theme.DIM) if variant != 'primary' else FlatButton._colour('#141416')
            self.assertTrue(colour.isValid())
            self.assertNotEqual((colour.red(), colour.green(), colour.blue()), (0, 0, 0))
            if variant != 'primary':
                self.assertGreater(colour.lightness(), 120)   # readable on #0E0E0F
        button = FlatButton('库', 'hero')
        button.setChecked(True)
        self.assertTrue(FlatButton._colour(theme.INK).lightness() > 200)

    def test_every_page_icon_really_draws(self):
        """Every icon name the capsule and the gear are given must draw pixels
        (once the capsule passed 'library' where the painter knew 'gamepad',
        and the tab showed no icon at all)."""
        from PySide6.QtGui import QColor, QPainter, QPixmap
        from PySide6.QtCore import QRectF
        from launcher.ui.widgets import draw_icon
        from launcher.ui import theme as th
        for name in ('library', 'gamepad', 'build', 'gear'):
            pixmap = QPixmap(24, 24)
            pixmap.fill(QColor(0, 0, 0, 0))
            painter = QPainter(pixmap)
            draw_icon(painter, name, QRectF(0, 0, 24, 24), QColor(th.MUTED))
            painter.end()
            image = pixmap.toImage()
            drawn = sum(1 for y in range(24) for x in range(24)
                        if image.pixelColor(x, y).alpha() > 40)
            self.assertGreater(drawn, 15, f'icon {name!r} drew nothing')

    def test_the_build_page_hides_its_debug_options_until_asked(self):
        """The advanced options start away; the toggle brings them out."""
        page = self.app.build_page
        self.assertTrue(page._advanced_group.isHidden())
        page.toggle_advanced()
        self.assertFalse(page._advanced_group.isHidden())
        self.assertEqual(page.advanced_toggle.text(), self.app.words['build_advanced_hide'])
        page.toggle_advanced()
        self.assertTrue(page._advanced_group.isHidden())

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

    def test_the_bar_holds_the_two_pages_and_the_settings(self):
        """The bar is the home screen's: the capsule centre, the gear right."""
        bar = self.app.titlebar
        seg = bar.nav_seg
        self.assertEqual([label for _k, label, _i in seg._items],
                         [self.app.words['tab_library'], self.app.words['tab_build']])
        self.assertEqual(seg.selected(), 'library')
        self.assertEqual(bar.settings_button.toolTip(), self.app.words['tab_settings'])

    def test_the_settings_dialog_opens_again_and_again(self):
        """The settings page must survive its dialog: handed its freedom before
        the dialog dies (once the parented page died with it, and the dialog
        could never be opened again)."""
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QDialog
        for round_index in range(3):
            opened = []

            def close_soon():
                for dialog in self.app.findChildren(QDialog):
                    if dialog.isVisible():
                        dialog.reject()
                        break

            original_exec = QDialog.exec
            QDialog.exec = lambda self=None: opened.append(1) or self.reject()
            try:
                self.app.open_settings()
            finally:
                QDialog.exec = original_exec
            self.assertEqual(len(opened), 1)
            self.assertIsNone(self.app.settings_page.parentWidget())   # free again

    def test_the_two_pages_sit_in_the_stack_in_a_fixed_order(self):
        stack = self.app.stack
        self.assertEqual([stack.widget(index) for index in range(stack.count())],
                         [self.app.library_page, self.app.build_page])
        # the capsule switches the stack
        bar = self.app.titlebar
        bar.nav_seg._pick('build')
        self.assertIs(stack.currentWidget(), self.app.build_page)
        bar.nav_seg._pick('library')
        self.assertIs(stack.currentWidget(), self.app.library_page)

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

    def test_a_wide_screen_gets_four_columns_at_most(self):
        page = self.app.library_page
        page.app.small = False
        self.assertEqual(page.columns(1400), 4)

    def test_the_cards_rearrange_when_the_width_changes(self):
        library_dir = Path(self.folder.name) / 'library'
        for title_id in ('0100000000010000', '0100000000010001', '0100000000010002'):
            make_pack(library_dir, title_id, f'Game {title_id[-1]}')
        self.app.settings['library'] = str(library_dir)
        page = self.app.library_page
        page.refresh()
        self.assertEqual(page.grid.count(), 3)
        # a content width that fits exactly two columns: the third card wraps
        user = scale.user_scale(self.app.settings.get('ui_scale'))
        cell, gap = scale.cell_size(user), scale.gap(user)
        page.reflow(2 * cell + gap)
        row, column = page.grid.getItemPosition(2)[:2]
        self.assertEqual((row, column), (1, 0))

    def test_an_icon_that_cannot_be_read_falls_back_to_the_first_letter(self):
        library_dir = Path(self.folder.name) / 'library'
        pack = make_pack(library_dir, '0100000000010000', 'Mario')
        (pack / 'icon.png').write_bytes(b'not an image at all')
        self.app.settings['library'] = str(library_dir)
        self.app.library_page.refresh()
        card = card_of(self.app.library_page)
        cover = card.layout().itemAt(0).widget()
        self.assertIsInstance(cover, QLabel)
        self.assertFalse(cover.pixmap().isNull() if cover.pixmap() else True)   # the letter tile
        self.assertIn('Mario', labels_of(self.app.library_page))

    def test_a_card_has_the_three_actions(self):
        """The three actions live on the panel of the chosen card."""
        library_dir = Path(self.folder.name) / 'library'
        make_pack(library_dir, '0100000000010000', 'Mario')
        self.app.settings['library'] = str(library_dir)
        self.app.library_page.refresh()
        page = self.app.library_page
        page.pick(page.cards[0])
        self.assertEqual([page.panel.run_button.text(), page.panel.steam_button.text(),
                          page.panel.desktop_button.text(), page.panel.manage_button.text()],
                         [self.app.words['run'], self.app.words['add_steam'],
                          self.app.words['add_desktop'], self.app.words['manage']])

    def test_remove_hides_the_pack_without_deleting_it(self):
        """'Remove from the library' renames the folder away — the scan passes it
        by, the files stay."""
        library_dir = Path(self.folder.name) / 'library'
        pack = make_pack(library_dir, '0100000000010000', 'Mario')
        self.app.settings['library'] = str(library_dir)
        page = self.app.library_page
        page.refresh()
        page.pick(page.cards[0])
        confirmed = []
        original = dialogs.danger_confirm
        dialogs.danger_confirm = lambda *a, **k: confirmed.append(a) or True
        try:
            page._remove_from_library(page.selected_game())
        finally:
            dialogs.danger_confirm = original
        self.assertTrue(confirmed)
        self.assertFalse(pack.exists())                    # gone from its place
        self.assertTrue(pack.with_name('.ignored-' + pack.name).is_dir())   # not deleted
        self.app.settings['library'] = str(library_dir)
        page.refresh()
        names = [getattr(c, '_game').title_id for c in page.cards]
        self.assertNotIn('0100000000010000', names)        # the library says so

    def test_delete_removes_the_pack_for_good(self):
        """'Delete the game data' removes the folder itself, after the question."""
        library_dir = Path(self.folder.name) / 'library'
        pack = make_pack(library_dir, '0100000000010000', 'Mario')
        self.app.settings['library'] = str(library_dir)
        page = self.app.library_page
        page.refresh()
        page.pick(page.cards[0])
        original = dialogs.danger_confirm
        dialogs.danger_confirm = lambda *a, **k: True
        try:
            page._delete_game(page.selected_game())
        finally:
            dialogs.danger_confirm = original
        self.assertFalse(pack.exists())
        self.assertFalse(pack.parent.joinpath(pack.name + '.ignored').exists())

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
        opened = []
        original = dialogs.message
        dialogs.message = lambda *args, **kwargs: shown.append(args)

        def fake_open_settings() -> None:
            opened.append(())

        original_open = self.app.open_settings
        self.app.open_settings = fake_open_settings
        self.addCleanup(lambda: setattr(self.app, 'open_settings', original_open))
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
        # the dialog says where to fix it, and the window opens it by itself (the
        # dialog itself is modal, so the test only checks the door was opened)
        self.assertEqual(opened, [()])

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
        self.assertFalse(shown)   # a quiet flash on the button, no dialog
        self.assertEqual(page.save_button.text(), self.app.words['set_saved'])

    def test_a_folder_is_refused_before_the_porter_is_asked(self):
        """A folder in the entry fails at once, with the words that say what
        belongs there — the porter is never woken for it."""
        page = self.app.build_page
        folder = Path(self.folder.name) / 'game'
        folder.mkdir()
        calls = []
        original = runner.run_json_async
        runner.run_json_async = lambda root, args, callback, **kw: calls.append(1)
        self.addCleanup(setattr, runner, 'run_json_async', original)
        page.folder.setText(str(folder))
        page.inspect()
        self.assertFalse(calls)                       # never asked
        self.assertIn(self.app.words['card_wants_file'].split('{')[0],
                      page.card.text().replace(folder.name, folder.name))   # says why

    def test_a_wrong_suffix_is_refused_with_the_kinds_named(self):
        page = self.app.build_page
        target = Path(self.folder.name) / 'game.zip'
        target.write_bytes(b'x')
        calls = []
        original = runner.run_json_async
        runner.run_json_async = lambda root, args, callback, **kw: calls.append(1)
        self.addCleanup(setattr, runner, 'run_json_async', original)
        page.folder.setText(str(target))
        page.inspect()
        self.assertFalse(calls)
        self.assertIn('.zip', page.card.text())
        self.assertIn('.nsp', page.card.text())       # the kinds are named

    def test_a_compressed_game_is_accepted(self):
        """NSZ counts: the porter unpacks it, the entry lets it through."""
        page = self.app.build_page
        target = Path(self.folder.name) / 'game.nsz'
        target.write_bytes(b'x')
        calls = []
        original = runner.run_json_async
        runner.run_json_async = lambda root, args, callback, **kw: calls.append((root, args, callback))
        self.addCleanup(setattr, runner, 'run_json_async', original)
        page.folder.setText(str(target))
        page.inspect()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1][1], str(target))

    def test_an_inspect_runs_off_the_interface_thread(self):
        page = self.app.build_page
        folder = Path(self.folder.name) / 'game.nsp'
        folder.write_bytes(b'not a game, but the shape is the porter\'s business')
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
        folder = Path(self.folder.name) / 'game.nsp'
        folder.write_bytes(b'not a game, but the shape is the porter\'s business')
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

    def test_saving_the_settings_does_not_stop_a_running_build(self):
        """A port runs with the settings it started with: saving the settings rebuilds the
        page only after the build has ended (it used to kill the porter silently)."""
        page = self.app.build_page
        cancelled = []

        class Running:
            running = True

            def cancel(self):
                cancelled.append(1)

        running = Running()
        page.porter = running
        self.app.reload_settings()
        self.assertIs(page.porter, running)   # the build keeps its porter
        self.assertFalse(cancelled)
        self.assertTrue(page.pending_rebuild)   # the page waits for the end
        page.finish(0)   # no result event: a failed run
        self.assertFalse(cancelled)   # the build ended, it was never cancelled
        self.assertFalse(page.pending_rebuild)   # the deferred rebuild ran
        self.assertIsNone(page.porter)

    def test_the_form_options_belong_to_the_game(self):
        """One game's name, font or headroom never builds another's pack: another game in
        the file field starts clean; the same game re-read keeps what the player typed."""
        page = self.app.build_page
        game_a = {'title_id': '0100000000010000', 'supported': True, 'name': 'A'}
        game_b = {'title_id': '0100000000010001', 'supported': True, 'name': 'B'}
        page.folder.setText('/games/a.nsp')
        page.inspect_done('/games/a.nsp', game_a, 0, '')
        page.name.setText('My build')
        page.font.setText('/tmp/font.ttf')
        page.headroom.setText('8')
        page.folder.setText('/games/b.nsp')
        page.inspect_done('/games/b.nsp', game_b, 0, '')
        self.assertEqual(page.name.text(), '')
        self.assertEqual(page.font.text(), '')
        self.assertEqual(page.headroom.text(), '')
        page.name.setText('Kept')
        page.inspect_done('/games/b.nsp', game_b, 0, '')
        self.assertEqual(page.name.text(), 'Kept')   # the same game keeps the edits

    def test_the_remembered_port_replays_on_the_form(self):
        """The library's re-port: the remembered file and the options of the last port go
        back on the form, and start_build builds exactly that."""
        page = self.app.build_page
        self.app.settings['library'] = str(Path(self.folder.name) / 'library')
        started = []

        class FakePorter:
            running = False

            def __init__(self, root, pack_dir=None):
                pass

            def start(self, args):
                started.append(list(args))

            def cancel(self):
                pass

        original = runner.Porter
        runner.Porter = FakePorter
        self.addCleanup(setattr, runner, 'Porter', original)
        page.prefill_for_port('/games/mario.nsp', {
            'source': '/games/mario.nsp', 'name': 'Mario', 'language': 'zh-Hans',
            'headroom': 8, 'font': '/tmp/f.ttf', 'fps60': True, 'touch': True,
            'no_menu': True, 'mt_replay': True, 'debug': True, 'experimental': True})
        self.assertEqual(page.folder.text(), '/games/mario.nsp')
        self.assertTrue(page.start_build())
        args = started[0]
        self.assertEqual(args[:4], ['port', '/games/mario.nsp', '--progress', 'json'])
        self.assertIn('--app', args)
        self.assertEqual(args[args.index('--app-name') + 1], 'Mario')
        # The game's language is not a build option any more: it lives in the pack and is
        # picked per game in the library (a remembered 'language' from an old port is ignored).
        self.assertNotIn('--language', args)
        self.assertEqual(args[args.index('--alias-headroom') + 1], '8')
        self.assertEqual(args[args.index('--shared-font') + 1], '/tmp/f.ttf')
        for flag in ('--fps60', '--touch', '--no-menu-button', '--mt-replay', '--debug', '--experimental'):
            self.assertIn(flag, args)

    def test_a_finished_port_is_remembered_for_the_re_port(self):
        original = settings.SOURCES_FILE
        settings.SOURCES_FILE = Path(self.folder.name) / 'sources.json'
        self.addCleanup(lambda: setattr(settings, 'SOURCES_FILE', original))
        self.app.settings['library'] = str(Path(self.folder.name) / 'library')
        page = self.app.build_page
        page.built_from = '/games/mario.nsp'
        page.built_options = {'name': 'Mario', 'headroom': None,
                              'font': '', 'fps60': False, 'touch': True, 'no_menu': False,
                              'mt_replay': False, 'debug': False, 'experimental': False}
        page.result = {'data': str(Path(self.folder.name) / 'library/Game-data'),
                       'title_id': '0100000000010000'}
        page.finish(0)   # the porter said done
        remembered = settings.port_source_of('0100000000010000')
        self.assertIsNotNone(remembered)
        self.assertEqual(remembered['source'], '/games/mario.nsp')
        self.assertEqual(remembered['name'], 'Mario')
        self.assertNotIn('language', remembered)   # the pack owns the language now
        self.assertEqual(remembered['touch'], True)

    def test_a_runtime_rebuild_and_its_drift_retry(self):
        """The library's runtime rebuild: the same porter machinery on the build page, and a
        drifted profile comes back as a question, not a dead end."""
        page = self.app.build_page
        started = []

        class FakePorter:
            running = False

            def __init__(self, root, pack_dir=None):
                pass

            def start(self, args):
                started.append(list(args))

            def cancel(self):
                pass

        original_porter, original_confirm = runner.Porter, dialogs.confirm
        runner.Porter = FakePorter
        dialogs.confirm = lambda *a, **k: True
        self.addCleanup(setattr, runner, 'Porter', original_porter)
        self.addCleanup(setattr, dialogs, 'confirm', original_confirm)
        self.assertTrue(page.start_rebuild_runtime(Path('/lib/Game-data')))
        self.assertEqual(started[0][:3], ['rebuild-runtime', '/lib/Game-data', '--progress'])
        self.assertNotIn('--allow-profile-drift', started[0])
        page.handle({'ev': 'profile-drift', 'msg': 'the game profile changed'})
        self.assertEqual(page.profile_drift, 'the game profile changed')
        page.finish(1)   # the porter answered an error: the drift question goes out
        self.assertEqual(len(started), 2)
        self.assertIn('--allow-profile-drift', started[1])   # the retry uses the profile the game has now


class SmallScreen(unittest.TestCase):
    """The rules of a phone-sized screen, without a phone."""

    def test_a_small_screen_shows_two_columns_at_most(self):
        for width in (320, 480, 600):
            self.assertLessEqual(scale.columns(width, 1.0, small=True), 2)

    def test_a_wide_screen_shows_more(self):
        self.assertGreaterEqual(scale.columns(1400, 1.0, small=False), 4)


if __name__ == '__main__':
    unittest.main()
