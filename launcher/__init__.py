"""The launcher for the games ported to this machine.

A small desktop shell: a library of the ported games, a build page that runs the same
pipeline the phone app runs, and the settings that say where the data directory is and
how the interface should look.  The interface is GTK (PyGObject), so the machine needs
python3-gi; the rest is the standard library.
"""

__version__ = '0.1.0'
