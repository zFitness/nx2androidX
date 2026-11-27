"""The little dialogues: something to say, a file to pick.

Qt's own message box and file dialog are all we need: a message with a kind
(information, a warning, an error) and a file chooser.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

KINDS = {
    'info': QMessageBox.Information,
    'warning': QMessageBox.Warning,
    'error': QMessageBox.Critical,
}


def window_of(widget):
    """The window a widget belongs to (a page widget is not a window: the dialog
    is shown against the toplevel, the way Wayland wants it)."""
    return widget.window() if widget is not None else None


def message(parent, title: str, text: str, kind: str = 'info', words: dict | None = None) -> None:
    """Say something and wait for the answer."""
    box = QMessageBox(KINDS.get(kind, QMessageBox.Information), title, text,
                      QMessageBox.Ok, window_of(parent))
    box.exec()


def choose_file(parent, title: str, words: dict, patterns: list[tuple[str, str]] | None = None,
                folder: bool = False) -> str:
    """Ask for a file (or a folder).  An empty string when the player cancels.

    The words carry the buttons' labels, but Qt's dialog speaks the system's own
    language for them; the patterns turn into the filters."""
    owner = window_of(parent)
    if folder:
        return QFileDialog.getExistingDirectory(owner, title, str(Path.home()))
    filters = ';;'.join(f'{name} ({pattern})' for name, pattern in patterns) if patterns else ''
    chosen, _filter = QFileDialog.getOpenFileName(owner, title, str(Path.home()), filters)
    return chosen
