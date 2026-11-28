# The ARM Linux launcher

The front door of the ARM Linux line: a desktop app whose **Library** tab runs the ported
games and whose **Build** tab makes a new game pack from a dump — the same two pages as
the Android app's home. See [SPEC.md](SPEC.md) for the decided shape; this file is the
short user-facing view.

## Running it

```sh
python -m launcher            # the window
python -m launcher --check    # what this machine has, without a window
```

The interface is **Qt (PySide6)** on the system's python3: Debian/Ubuntu
`apt install python3-pyside6` (or `python3 -m pip install PySide6`). A second start does
nothing while one runs (a flock in the config directory).

The window draws its own chrome on one dark ground: the bar at the top — the
brand left, the segmented pages capsule dead centre (Library and Build, each
with its icon, the chosen one a cream pill), the settings gear and the three
window controls right — and the pages under it. The look is the desktop
launcher's own **Dark Glass** (NX2Apple's design tokens, `launcher/ui/theme.py`):
a five-step ladder of near-black surfaces, hairlines at six percent, cream as
the one accent with its hover/pressed states, white text in three strengths,
and four corner radii (chip 6 / card 12 / sheet 16 / control 18) that shape
every card, pill and field. On the library the games are a tight left-aligned
grid, up to four covers a row from the first column; the chosen game's actions
(Run in cream, Steam and the app menu outlined beside it) sit on a translucent
glass panel at the bottom, only while a game is picked. Feedback is immediate —
a hover changes the fill a step, the keyboard focus draws two pixels of cream —
and every grid size comes from one place, `launcher/scale.py` (`widgets.py`
holds the controls). Dragging the bar and pulling the edges go through the
system's own move/resize protocols where the platform has them (on Wayland they
are the only way), with a plain fallback elsewhere.

## The Library tab

The ported games as a grid of cards — icon, name, version, **Run**, **Add to Steam** and
**Add to the app menu**. The library is a plain folder of packs
(`~/.local/share/nx2a/library/<title ID>/` by default, changeable in Settings): a pack
copied in by hand shows up on its own, a folder deleted by hand is gone. The pack is the
truth.

**Run** starts the pack's own `run.sh` with the pack as its working directory and
`DM_ROOT`: the pack carries its own host binary, its modules and its environment
(`env.txt`, `settings.txt`), so a game runs with one click and needs nothing else — not
even the AppImage it may have been built with.

## The Build tab

The port pipeline the phone app runs, laid out locally: pick a game file (read right
away — the card says what it holds and whether it can be ported), set the options, build.
The stages come in with their times, the log under them. A build writes into the cache
and moves into the library only when it finished; a failed or cancelled build leaves
nothing behind.

## The Settings dialog

The data directory, the interface language and the interface scale. Its own entry on
the top bar opens it.

## The app menu and Steam

**Add to the app menu** writes a desktop entry; **Add to Steam** writes Steam's own
shortcuts file (its binary key-values format, handled without a dependency — Steam keeps
that file in memory, so the launcher asks the player to close Steam first). Neither
touches the game itself.

## The package

The launcher ships as ONE AppImage: the thick one, with the pipeline, the engine tools,
the game profiles, the toolchain and a Chinese font. See
[packaging/arm-linux/README.md](../packaging/arm-linux/README.md) for the build.
