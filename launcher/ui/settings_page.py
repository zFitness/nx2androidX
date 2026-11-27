"""The settings page: where the data directory and prod.keys are, how the interface looks."""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from launcher import runner, settings
from launcher.ui import clear_layout, dialogs
from porter import config as porter_config


class SettingsPage(QWidget):
    """The settings: the data folder, prod.keys, the language, the size, the profiles."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.words = app.words
        self.importing = False
        QVBoxLayout(self)   # the page's own column; build() fills it (again)
        self.build()

    def build(self) -> None:
        clear_layout(self.layout())   # a rebuild starts from an empty page
        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QScrollArea.NoFrame)
        self.layout().addWidget(scroller)
        body = QWidget()
        scroller.setWidget(body)
        grid = QGridLayout(body)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        self.library = QLineEdit(str(self.app.settings.get('library') or ''))
        grid.addWidget(QLabel(self.words['set_data_dir']), 0, 0)
        grid.addWidget(self.library, 0, 1)
        browse = QPushButton(self.words['browse'])
        browse.clicked.connect(self.pick_library)
        grid.addWidget(browse, 0, 2)
        hint = QLabel(self.words['set_data_dir_hint'])
        hint.setWordWrap(True)
        grid.addWidget(hint, 1, 1, 1, 2)

        # Building: prod.keys.  It lives in the porter's own config (shared with the
        # desktop tool and the CLI), and the port cannot start without it.
        group = QLabel(self.words['set_build'])
        group.setStyleSheet('color: #757575')
        grid.addWidget(group, 2, 0, 1, 3)
        self.keys = QLineEdit(str(porter_config.load().get('keys') or ''))
        grid.addWidget(QLabel(self.words['set_keys']), 3, 0)
        grid.addWidget(self.keys, 3, 1)
        keys_browse = QPushButton(self.words['browse'])
        keys_browse.clicked.connect(self.pick_keys)
        grid.addWidget(keys_browse, 3, 2)
        keys_hint = QLabel(self.words['set_keys_hint'])
        keys_hint.setWordWrap(True)
        grid.addWidget(keys_hint, 4, 1, 1, 2)

        self.language = QComboBox()
        self.language.addItem(self.words['language_zh'])
        self.language.addItem(self.words['language_en'])
        self.language.setCurrentIndex(0 if self.app.settings.get('language') == 'zh' else 1)
        grid.addWidget(QLabel(self.words['set_language']), 5, 0)
        grid.addWidget(self.language, 5, 1)

        self.ui_scale = QDoubleSpinBox()
        self.ui_scale.setRange(0.5, 3.0)
        self.ui_scale.setSingleStep(0.1)
        self.ui_scale.setValue(float(self.app.settings.get('ui_scale') or 1.0))
        grid.addWidget(QLabel(self.words['set_scale']), 6, 0)
        grid.addWidget(self.ui_scale, 6, 1)

        grid.addWidget(QLabel(self.words['set_profiles']), 7, 0)
        self.profiles_button = QPushButton(self.words['browse'])
        self.profiles_button.clicked.connect(self.pick_profiles)
        grid.addWidget(self.profiles_button, 7, 1)
        profiles_hint = QLabel(self.words['set_profiles_hint'])
        profiles_hint.setWordWrap(True)
        grid.addWidget(profiles_hint, 8, 1, 1, 2)

        save = QPushButton(self.words['set_save'])
        save.clicked.connect(self.save)
        grid.addWidget(save, 9, 0)

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
        dialogs.message(self, words['app_title'], words['set_saved'])
