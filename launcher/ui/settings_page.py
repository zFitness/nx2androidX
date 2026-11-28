"""The settings page: where the data directory and prod.keys are, how the interface looks.

The page is laid out in panels (the data folder, the build's keys and profile package,
the interface's language and scale); the fields, their pickers and the saving are the
existing ones, unchanged.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QScrollArea,
                               QVBoxLayout, QWidget)

from launcher import runner, settings
from launcher.ui import clear_layout, dialogs, theme
from launcher.ui.widgets import FlatButton
from porter import config as porter_config


class SettingsPage(QWidget):
    """The settings: the data folder, prod.keys, the language, the size, the profiles."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.words = app.words
        self.importing = False
        self.save_button = None   # set by build(); the save flash speaks on it
        QVBoxLayout(self)   # the page's own column; build() fills it (again)
        self.build()

    def build(self) -> None:
        clear_layout(self.layout())   # a rebuild starts from an empty page
        words = self.words
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QScrollArea.NoFrame)
        self.layout().addWidget(scroller)
        body = QWidget()
        scroller.setWidget(body)
        column = QVBoxLayout(body)
        column.setContentsMargins(16, 16, 16, 16)
        column.setSpacing(12)

        def grid_of(group: QGroupBox) -> QGridLayout:
            grid = QGridLayout(group)
            grid.setContentsMargins(14, 8, 14, 12)
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(6)
            return grid

        # The data folder.
        data = QGroupBox(words['set_data_dir'])
        column.addWidget(data)
        grid = grid_of(data)
        self.library = QLineEdit(str(self.app.settings.get('library') or ''))
        grid.addWidget(self.library, 0, 0)
        browse = FlatButton(words['browse'], 'quiet')
        browse.clicked.connect(self.pick_library)
        grid.addWidget(browse, 0, 1)
        hint = QLabel(words['set_data_dir_hint'])
        hint.setProperty('dim', True)
        hint.setWordWrap(True)
        grid.addWidget(hint, 1, 0, 1, 2)

        # Building: prod.keys.  It lives in the porter's own config (shared with the
        # desktop tool and the CLI), and the port cannot start without it.
        build = QGroupBox(words['set_build'])
        column.addWidget(build)
        grid = grid_of(build)
        self.keys = QLineEdit(str(porter_config.load().get('keys') or ''))
        grid.addWidget(QLabel(words['set_keys']), 0, 0)
        grid.addWidget(self.keys, 0, 1)
        keys_browse = FlatButton(words['browse'], 'quiet')
        keys_browse.clicked.connect(self.pick_keys)
        grid.addWidget(keys_browse, 0, 2)
        keys_hint = QLabel(words['set_keys_hint'])
        keys_hint.setProperty('dim', True)
        keys_hint.setWordWrap(True)
        grid.addWidget(keys_hint, 1, 1, 1, 2)
        grid.addWidget(QLabel(words['set_profiles']), 2, 0)
        self.profiles_button = FlatButton(words['browse'], 'quiet')
        self.profiles_button.clicked.connect(self.pick_profiles)
        grid.addWidget(self.profiles_button, 2, 1)
        profiles_hint = QLabel(words['set_profiles_hint'])
        profiles_hint.setProperty('dim', True)
        profiles_hint.setWordWrap(True)
        grid.addWidget(profiles_hint, 3, 1, 1, 2)

        # The interface: the language and the scale.
        face = QGroupBox(words['set_ui'])
        column.addWidget(face)
        grid = grid_of(face)
        self.language = QComboBox()
        self.language.addItem(self.words['language_zh'])
        self.language.addItem(self.words['language_en'])
        self.language.setCurrentIndex(0 if self.app.settings.get('language') == 'zh' else 1)
        grid.addWidget(QLabel(self.words['set_language']), 0, 0)
        grid.addWidget(self.language, 0, 1)
        self.ui_scale = QDoubleSpinBox()
        self.ui_scale.setRange(0.5, 3.0)
        self.ui_scale.setSingleStep(0.1)
        self.ui_scale.setValue(float(self.app.settings.get('ui_scale') or 1.0))
        grid.addWidget(QLabel(self.words['set_scale']), 1, 0)
        grid.addWidget(self.ui_scale, 1, 1)

        column.addStretch(1)
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save = FlatButton(words['set_save'], 'primary')
        save.clicked.connect(self.save)
        save_row.addWidget(save)
        column.addLayout(save_row)
        self.save_button = save

    def rebuild(self) -> None:
        """The page is built again (the settings changed)."""
        self.words = self.app.words   # the language may have changed with the settings
        self.importing = False
        self.build()

    # ---- what the player picks --------------------------------------------------------

    def pick_library(self) -> None:
        chosen = dialogs.choose_file(self, self.words['set_data_dir'], self.words, folder=True)
        if chosen:
            self.library.setText(chosen)

    def pick_keys(self) -> None:
        chosen = dialogs.choose_file(self, self.words['set_keys'], self.words,
                                     [('All files', '*')])
        if chosen:
            self.keys.setText(chosen)

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
        if self.importing:
            return   # one import at a time; the button is asleep meanwhile
        self.importing = True
        self.profiles_button.setEnabled(False)
        runner.run_text_async(root, ['profiles', 'import', path],
                              lambda code, out, err: self.import_done(path, code, out, err))

    def import_done(self, path: str, code: int, out: str, err: str) -> None:
        """The import came back (on the interface's loop)."""
        self.importing = False
        self.profiles_button.setEnabled(True)
        words = self.words
        if code != 0:
            dialogs.message(self, words['app_title'],
                            words['profiles_failed'].format(message=err or out), 'error')
            return
        dialogs.message(self, words['app_title'], out or words['profiles_imported'])

    def save(self) -> None:
        """Save the settings: the values go in, the page says so on the button
        itself (a quiet flash, not a dialog); failures still speak up."""
        words = self.words
        current = dict(self.app.settings)
        current['library'] = self.library.text().strip()
        current['language'] = 'zh' if self.language.currentIndex() == 0 else 'en'
        try:
            current['ui_scale'] = float(self.ui_scale.value())
        except ValueError:
            current['ui_scale'] = 1.0
        if current['ui_scale'] <= 0:
            current['ui_scale'] = 1.0
        settings.save(current)
        try:
            porter_config.set_value('keys', self.keys.text().strip())
        except OSError as error:
            dialogs.message(self, words['app_title'],
                            words['set_keys_failed'].format(error=error), 'error')
            return
        self.app.reload_settings()
        # Saved: the button says so for a moment, then goes back to its word.
        if self.save_button is not None:
            from PySide6.QtCore import QTimer
            original = words['set_save']
            self.save_button.setText(words['set_saved'])
            self.save_button.setEnabled(False)
            QTimer.singleShot(1200, lambda: (self.save_button.setText(original),
                                             self.save_button.setEnabled(True)))
