"""The little dialogues: something to say, a file to pick.

GTK has no `messagebox` like Tk has, so these are the few we need: a message with a
kind (information, a warning, an error) and a file chooser.
"""
from __future__ import annotations

from gi.repository import Gtk

KINDS = {
    'info': Gtk.MessageType.INFO,
    'warning': Gtk.MessageType.WARNING,
    'error': Gtk.MessageType.ERROR,
}


def message(parent, title: str, text: str, kind: str = 'info', words: dict | None = None) -> None:
    """Say something and wait for the answer."""
    dialog = Gtk.MessageDialog(
        transient_for=parent, modal=True,
        message_type=KINDS.get(kind, Gtk.MessageType.INFO),
        buttons=Gtk.ButtonsType.OK, text=title)
    dialog.format_secondary_text(text)
    dialog.run()
    dialog.destroy()


def choose_file(parent, title: str, words: dict, patterns: list[tuple[str, str]] | None = None,
                folder: bool = False) -> str:
    """Ask for a file (or a folder).  An empty string when the player cancels."""
    action = Gtk.FileChooserAction.SELECT_FOLDER if folder else Gtk.FileChooserAction.OPEN
    dialog = Gtk.FileChooserDialog(title=title, transient_for=parent, action=action)
    dialog.add_button(words.get('cancel', 'Cancel'), Gtk.ResponseType.CANCEL)
    dialog.add_button(words.get('open', 'Open'), Gtk.ResponseType.OK)
    if patterns:
        for name, pattern in patterns:
            filter_ = Gtk.FileFilter()
            filter_.set_name(name)
            filter_.add_pattern(pattern)
            dialog.add_filter(filter_)
    answer = dialog.run()
    chosen = dialog.get_filename() or ''
    dialog.destroy()
    return chosen if answer == Gtk.ResponseType.OK else ''
