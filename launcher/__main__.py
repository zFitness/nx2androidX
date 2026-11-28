"""The launcher's entry point.

    python -m launcher            the window
    python -m launcher --check    what this machine has (no window)
    python -m launcher --help     this text

The interface is Qt (PySide6): the machine needs PySide6 for its own python3
(Debian/Ubuntu: `apt install python3-pyside6`, or `python3 -m pip install PySide6`),
and the launcher runs on the system's python3.
"""
from __future__ import annotations

import fcntl
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent   # the trimmed repository root inside the package


_LOCK = None   # the open lock file: kept alive for the process's whole life, the lock dies with it


def single_instance() -> bool:
    """One launcher at a time. The desktop containers the window lives in (gamescope on
    the DroidDeck tablet) make a second instance look like a shell around the first, and
    the player clicks again because nothing seemed to happen. The kernel drops a flock
    when the holder dies -- a crash leaves no stale lock to clean up. The lock lives in
    the config directory: the package itself is a read-only mount. The holder's pid is
    recorded (no truncation on later opens, or the pid would be lost) for diagnostics."""
    from launcher import settings
    settings.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lock = settings.CONFIG_DIR / 'launcher.lock'
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT, 0o644)   # no O_TRUNC: a refused second
    try:                                                  # open must not erase the pid
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return False
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())   # the holder's pid, for diagnostics
    global _LOCK
    _LOCK = fd   # kept open for the process's whole life; closing it releases the lock
    return True


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if '--help' in argv or '-h' in argv:
        print(__doc__)
        return 0
    if '--check' in argv:
        return check()
    try:
        from PySide6 import QtWidgets   # the one import that can fail
    except ImportError as error:
        print(f'the launcher needs PySide6: {error}')
        print('Debian/Ubuntu: apt install python3-pyside6   or: python3 -m pip install PySide6')
        return 1
    from launcher import appimage, settings
    if not single_instance():
        print('the launcher is already running')
        return 0
    appimage.prepare(REPO, settings.DATA_DIR)   # inside an AppImage: the engine tree must be writable
    # SIGSYS（seccomp 违规）是这台设备上唯一的无声死亡方式：打栈到 stderr（launcher.log），
    # 再按默认方式死掉，定位是哪个调用触发了内核过滤。
    import faulthandler, signal, traceback
    faulthandler.enable()

    def _sigsys(signum, frame) -> None:
        sys.stderr.write('=== SIGSYS 命中时的 Python 栈 ===\n')
        traceback.print_stack(frame, file=sys.stderr)
        try:
            sys.stderr.write('目标调用: ' + repr(frame.f_lineno) + ' @ ' + frame.f_code.co_filename + '\n')
        except Exception:
            pass
        sys.stderr.flush()
        signal.signal(signal.SIGSYS, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    signal.signal(signal.SIGSYS, _sigsys)
    from PySide6.QtCore import QTimer
    from launcher.ui.app import LauncherApp
    application = QtWidgets.QApplication([])
    window = LauncherApp()
    window.showMaximized()   # under Qt showing and the maximized state are one call
    # and once more when the loop is up, for compositors that need it late — but
    # only if the first one did not take (a second ask over an already-maximized
    # window made the window shrink and grow again on the tablet's KWin)
    def _ensure_maximized() -> None:
        if not (window.windowState() & Qt.WindowMaximized):
            window.showMaximized()
    QTimer.singleShot(0, _ensure_maximized)
    return application.exec()


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
        import PySide6
        from PySide6 import QtCore
        print(f'qt:       {QtCore.qVersion()} (PySide6 {PySide6.__version__})')
    except ImportError as error:
        print(f'qt:       (not there: {error})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
