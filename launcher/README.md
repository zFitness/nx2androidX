# The ARM Linux launcher

A small desktop shell for a machine that runs the ported games itself: a library of the
games, a build page that runs the same pipeline the phone app runs, and the entries that
put a game in the system's app menu or in Steam's library.

It is Python with GTK 3 (PyGObject) and nothing else, so a machine needs only its
`python3` and `python3-gi` packages.

## Running it

```sh
python -m launcher            # the window
python -m launcher --check    # what this machine has, without a window
```

The launcher finds the port pipeline next to itself (a checkout), in `NX2A_PORTER_DIR`,
or in the setting of the same name.

## The three pages

- **Library** — the ported games, in a grid: the icon, the name, the version. Each card
  has **Run**, **Add to Steam** and **Add to the app menu**. The grid's width decides
  how many cards fit; on a phone-sized screen it never shows more than two, and the
  fonts and the touch targets are bigger there.
- **Build** — the pipeline the phone app runs, on this machine, laid out like the desktop
  tool's build tab: pick a game file (it is read right away, and the card says what it
  holds and whether it can be ported), set the options, and build. The options are the
  game name, the game language, the extra address space, the system font, 60 fps, a game
  played by touch, no on-screen menu button, the multithreaded replay, a development
  build, and trying a game that has no profile yet. The stages come in with their times,
  the log under them. The pack it makes is put in the data directory when it is done; a
  build that fails or is cancelled leaves nothing behind — only a finished one is in the
  library.
- **Settings** — where the data directory is, the interface language and the interface
  scale. A change is in force from the next action on; nothing has to be restarted.

## The data directory

A folder of data packs, one folder per game (`<data folder>/<title ID>/`). The pack is
the truth: `nx2a-data.json` says what the game is, `icon.png` is its icon, and the
game's own executable lives beside them. There is no index beside it, so a pack copied
in by hand shows up on its own and a folder deleted by hand is gone.

The default data directory is `~/.local/share/nx2a/library`. A build writes into a
staging folder under it and moves the finished pack in.

## Running a game

Every game has its own executable, in its own folder. **Run** starts it with that folder
as its working directory and `DM_ROOT` pointing at it; the pack's own `env.txt` and
`settings.txt` are read from there, as on Android. A game without an executable of its
own (the Linux runtime is not built yet) says so instead of failing quietly.

## The app menu and Steam

- **Add to the app menu** writes a desktop entry, so the game shows up in the system's
  application menu (and can be picked by hand in Steam's "add a non-Steam game"). The
  entry points at a small script in the game's folder that sets the environment and
  starts the game. The same button removes it again.
- **Add to Steam** writes Steam's own shortcuts file (the binary key-values format, read
  and written here without a dependency), pointing at the same script. Steam keeps that
  file in memory and writes it back when it quits, so the launcher does not write it
  while Steam is running — it asks the player to close Steam first.

Neither of them touches the game itself.

## The ARM64 Linux package

The launcher ships as an AppImage: one file for ARM64 Linux, with the pipeline and the
engine tools, running on the machine's own Python with PyGObject — nothing of ours to
install beyond `python3-gi`. See `packaging/arm-linux/README.md` for the build and for
what the machine needs.

Inside the package the engine tree is copied to the player's own folder on the first run
(the package is read-only and the builds write beside their sources); the library, the
settings and the imported profiles stay in the user's own directories.

## The tests

```sh
python -m unittest discover tests -p "test_launcher_*.py"
```

The window's tests need a display and are skipped without one (and without PyGObject
with GTK 3).
