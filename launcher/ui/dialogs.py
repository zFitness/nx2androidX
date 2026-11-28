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


def confirm(parent, title: str, text: str) -> bool:
    """Ask a yes/no question; True when the player accepted."""
    box = QMessageBox(QMessageBox.Question, title, text,
                      QMessageBox.Yes | QMessageBox.No, window_of(parent))
    return box.exec() == QMessageBox.Yes


def danger_confirm(parent, title: str, text: str, note: str, accept_label: str) -> bool:
    """A destructive question, the desktop launcher's shape: the words say what
    happens, the note says the price, and the destructive button never stands as
    the default."""
    box = QMessageBox(QMessageBox.Warning, title, text, QMessageBox.NoButton,
                      window_of(parent))
    box.setInformativeText(note)
    accept = box.addButton(accept_label, QMessageBox.DestructiveRole)
    cancel = box.addButton(QMessageBox.Cancel)
    box.setDefaultButton(cancel)
    box.exec()
    return box.clickedButton() is accept


def wait_or_kill(process, seconds: int = 5) -> bool:
    """Wait for a process to exit on its own; kill it when the wait runs out."""
    import time
    limit = time.monotonic() + seconds
    while time.monotonic() < limit:
        if process.poll() is not None:
            return True
        time.sleep(0.2)
    return process.poll() is not None


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
