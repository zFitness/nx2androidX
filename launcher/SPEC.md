# The launcher's SPEC

The launcher is the ARM Linux line's front door: a desktop app whose library runs the
ported games and whose build page makes new packs from a game dump. The player sees two
tabs — **Library** and **Build** — exactly like the Android app's home.

## The shape we ship (decided 2026-11-28)

- **PySide6 (Qt) on the system python3.** The pages are `launcher/ui/`: library grid,
  build page, settings. Single instance by flock (`launcher.lock` in the config dir) —
  the DroidDeck tablet's gamescope makes a second window look like a shell around the
  first, so a second start must do nothing.
- **Package shapes: thin / full / toolchain / toolchain-full** (the build's switches
  decide). The 2026-11-28 decision to ship one thick AppImage recorded below was reversed
  after the profiles-import flow came back: the package line builds all four today, and
  [packaging/arm-linux/README.md](../packaging/arm-linux/README.md) documents them.
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
        romfs/                        # only when the profile keeps its RomFS in the pack;
                                      # the app's mode points at the work folder instead
                                      # (env.txt DM_ROMFS) — see the rules below
    work/                             # the porter's running resources (NOT a cache):
        <title>_build/extract/<v>/RomFS/   # what a pack's DM_ROMFS usually points at
        romfs_zstd/<v>/                    # the zstd-packed copy, when the profile asks
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
- **One thing sits outside the pack by decision**: the RomFS. It stays persistent in the
  porter work folder (`~/.local/share/nx2a/work`), and the pack's `env.txt` points at the
  real thing with `DM_ROMFS` (a profile with `romfs zstd` points at the packed folder the
  build actually produced). The library therefore has two truths: the pack's presence
  decides the list, the referenced resources decide runnability (`romfs_ready`). The work
  folder is a running resource, **not** a disposable cache.
- A build writes the pack through a `.partial` staging folder and an atomic rename into
  the library, replacing an older pack of the same game only at the end. **A failed or
  cancelled rebuild keeps the previous pack, the referenced resources, the saves and the
  settings.**
- The `DM_VK_DMABUF_ZC` (v2 zero-copy) default ships ON; `env.txt` may override, as on
  Android.
- **Touch-first interaction rules** (the tablet is the target machine): a page tab switches
  on the press (a finger's release often never arrives), a card's selection frame is the
  card's own height, and a Steam shortcut is written even while Steam runs — on the tablet
  the desktop keeps Steam alive, so refusing would mean never being able to add a game; the
  player is told it appears at Steam's next start (Steam reads `shortcuts.vdf` when it
  quits/starts).

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

- The thin AppImage and the profiles-import settings flow — decided against, then
  re-decided: the thin package and the profiles import are back (the shipped shapes are
  thin / full / toolchain / toolchain-full, see
  [packaging/arm-linux/README.md](../packaging/arm-linux/README.md)). The original
  "one thick AppImage" decision below is kept as the record of 2026-11-28's intent; the
  package README is the authority for what is built today.
- FUSE bridging of any kind — the launcher reads host paths directly.
- Container lifecycle management — if the player's machine happens to run its Linux
  inside Droidspaces, that is the machine's business, not the launcher's.
- Window management experiments (maximize/drag-resize): games run fullscreen, as on
  Android.

## Where the line stands (checked 2026-11-28; the day-by-day truth is the change's tasks)

- **Runs the two proven games** (MvDK, 13 Sentinels, 60 fps, Droidspaces container,
  v2 dma-buf host). Other games are unverified.
- The **shared pause menu** (`nxnative/dm/menu/`, ImGui) is on Linux only in its first
  phase — two tabs, the FPS switch, resume and quit, device-tested (build
  B20261128T060816Z-798e6ad3); the panel migration, the settings store's finishing work and
  the Android migration are open (`openspec/changes/imgui-overlay-menu`). The Android app
  keeps its existing menu until that change lands.
- The **virtual on-screen gamepad on Linux is not verified**.
- The **AppImage's packaging migration** (native PyInstaller + appimagetool chain) is in
  progress in a parallel session; the current shipped shape is what
  [packaging/arm-linux/README.md](../packaging/arm-linux/README.md) documents.
