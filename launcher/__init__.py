"""The launcher for the games ported to this machine.

A small desktop shell: a library of the ported games, a build page that runs the same
pipeline the phone app runs, and the settings that say where the data directory is and
how the interface should look.  The interface is Qt (PySide6).
"""
import os


def _porter_home() -> None:
    """One porter config for the launcher itself and the porter children it starts:
    NX2A_HOME points the porter's settings (prod.keys among them) at the launcher's own
    config folder, so a key saved in the settings page is the key a port reads.  Without
    this the in-process settings read the desktop tool's config while the porter child
    read another, and no port could start.  setdefault: a player (or a test) that names
    another home keeps theirs."""
    from launcher import settings
    os.environ.setdefault('NX2A_HOME', str(settings.CONFIG_DIR / 'porter'))


_porter_home()

__version__ = '0.1.0'
