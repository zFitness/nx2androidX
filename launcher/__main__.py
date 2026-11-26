"""The launcher's entry point.

    python -m launcher            the window
    python -m launcher --check    what this machine has (no window)
    python -m launcher --help     this text

The interface is GTK: the machine needs `python3-gi` (Debian/Ubuntu: `apt install
python3-gi`, Fedora: `python3-gobject`), and the launcher runs on the system's python3.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent   # the trimmed repository root inside the package


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if '--help' in argv or '-h' in argv:
        print(__doc__)
        return 0
    if '--check' in argv:
        return check()
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk
    except (ImportError, ValueError) as error:
        print(f'the launcher needs PyGObject with GTK 3: {error}')
        print('Debian/Ubuntu: apt install python3-gi   Fedora: dnf install python3-gobject')
        return 1
    from launcher import appimage, settings
    appimage.prepare(REPO, settings.DATA_DIR)   # inside an AppImage: the engine tree must be writable
    from launcher.ui.app import LauncherApp
    window = LauncherApp()
    window.show_all()
    Gtk.main()
    return 0


def check() -> int:
    """What this machine has: the data folder, the porter, Steam."""
    from launcher import runner, settings, steam
    current = settings.load()
    print(f'data dir: {settings.library_dir(current)}'
          + ('' if settings.library_set(current) else ' (not set yet)'))
    root = runner.porter_root(str(current.get('porter_dir') or ''))
    print(f'porter:   {root if root else "(not found)"}')
    steam_root = steam.steam_root()
    print(f'steam:    {steam_root if steam_root else "(not installed)"}')
    shortcuts = steam.shortcuts_file(steam_root) if steam_root else None
    print(f'shortcuts: {shortcuts if shortcuts and shortcuts.is_file() else "(no file yet)"}')
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk
        print(f'gtk:      {Gtk.get_major_version()}.{Gtk.get_minor_version()}.'
              f'{Gtk.get_micro_version()}')
    except (ImportError, ValueError) as error:
        print(f'gtk:      (not there: {error})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
