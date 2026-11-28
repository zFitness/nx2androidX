# The launcher's SPEC

The launcher is the ARM Linux line's front door: a desktop app whose library runs the
ported games and whose build page makes new packs from a game dump. The player sees two
tabs — **Library** and **Build** — exactly like the Android app's home.

## The shape we ship (decided 2026-11-28)

- **PySide6 (Qt) on the system python3.** The pages are `launcher/ui/`: library grid,
  build page, settings. Single instance by flock (`launcher.lock` in the config dir) —
  the DroidDeck tablet's gamescope makes a second window look like a shell around the
  first, so a second start must do nothing.
- **One package shape: the THICK AppImage** (with profiles, with toolchain). The thin
  package and the profiles-import flow are dropped; there is no other build to keep true.
- **Target: a plain ARM64 Linux machine.** The DroidDeck tablet's Droidspaces container
  is one of those (a bare Linux userland) and needs no special casing: the launcher is an
  ordinary desktop app, reads and writes its XDG paths directly, and starts games with
  `exec` — no mounts, no bridges, no container awareness.
- **Level of ambition for the library: the two proven games.** Mario vs. Donkey Kong
  (0100B99019412000) and 13 Sentinels: Aegis Rim (01008D7016438000), both 60 fps on the
  v2 dma-buf host. A pack scanned from the library folder shows up; arbitrary dumps are
  the Build page's business, not the Library's.

## The directories on the player's machine (pure XDG, the host owns the data)

```
~/.config/nx2a/
    launcher.json                     # settings (library path, language, ui scale)
    launcher.lock                     # the single-instance flock

~/.local/share/nx2a/
    library/<title ID>/               # the pack is the truth
        nx2a-data.json                # what the game is (name, version, title ID)
        icon.png                      # the library card's icon
        host/dmhost                   # the host binary THE PACK CARRIES (one-click run)
        mods/                         # the rewritten modules with fixups
        env.txt  settings.txt  run.sh # the launcher's entry, as on Android
        romfs/  fonts/                # the game's own data the pack resolves
    cache/
        builds/<run id>/              # build staging: a failed or cancelled build leaves
                                      # nothing in the library, only here until dismissed
        thumbs/                       # generated card thumbnails
```

Rules the whole code holds to:

- The pack **is** the library entry: a folder copied in by hand shows on its own, a folder
  deleted by hand is gone. No index beside it.
- The pack carries its own `host/dmhost`, so **running a game depends on nothing inside
  the AppImage** — the AppImage is the factory that makes packs and the shelf that lists
  them, not a runtime the games need.
- A build writes into `cache/builds/` and moves into the library only when it finished.
- The `DM_VK_DMABUF_ZC` (v2 zero-copy) default ships ON; `env.txt` may override, as on
  Android.

## The four steps (each anchored on: MvDK runs with one click)

| Step | What | Done when |
|---|---|---|
| 1 | The two proven packs land in `~/.local/share/nx2a/library/` (copied from the container's `/opt/nx2a-data/library/`), `runner.py` runs `run.sh` with cwd and `DM_ROOT` on the pack | The launcher's Run puts MvDK on screen at its 60/52 fps baseline |
| 2 | Desktop entries and Steam shortcuts (existing `steam.py`/appmenu code) onto the new layout | A desktop icon starts the game; the game appears in Steam's library |
| 3 | The Build page drives the porter pipeline (dump in → seven stages with times and log → staging → into the library) | A pack built by the launcher runs the game it was built from |
| 4 | `build_appimage.py` thick package proven from zero on the tablet and a bare Linux machine | A fresh machine installs the AppImage, builds and runs MvDK with no step outside it |

## What exists and what is new

Existing, reused: `ui/` (five pages), `runner.py`, `library.py`, `settings.py`,
`steam.py`, `appimage.py`, the single-instance lock, `packaging/arm-linux/build_appimage.py`.

New: `buildjob.py` (the pipeline driver for the Build page: process handle, stage events,
staging-then-move, cancel). Everything else is adjustment to the layout above and the
usual Qt polish of the library grid.

## Out of scope (deliberately)

- The thin AppImage and the profiles-import settings flow — the thick package carries the
  profiles.
- FUSE bridging of any kind — the launcher reads host paths directly.
- Container lifecycle management — if the player's machine happens to run its Linux
  inside Droidspaces, that is the machine's business, not the launcher's.
- Window management experiments (maximize/drag-resize): games run fullscreen, as on
  Android.
