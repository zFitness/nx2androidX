# The device's command line

The app ships a glibc environment (the payload): the porter, the build tools and the host all run **on the
phone**. Everything a walkthrough needs can be done from the command line — no tapping, no `input tap`.

## What a walkthrough is

A change is walked through on the device in three levels, and each one answers a different question:

1. **The deployed code, by itself.** The test that covers the change, run on the phone against the phone's own
   copy of the sources (the upstream's C tests cut the production code out of the file and compile it: the
   phone's own compiler does that). This is the level that says the change does what it says.
2. **The whole thing, headlessly.** The game runs without the app's window (the headless host above): the
   boot, the first scenes, the frame rate, the red lines. This is the level that says the change does not break
   the game.
3. **The difference, visible.** What the player sees: the game's own time (the picture's timestamp), the
   animation's timing, the screen. This is the level that says the change was worth making — and it needs the
   app (the window), so it is the one step the player does.

A walkthrough that only runs the tests proves the code; a walkthrough that only plays the game proves nothing
about the code. Say which level each check is on.

## The environment the app gives the tools

The app unpacks the payload into its own files folder:

| What | Where |
|---|---|
| the rootfs (a Debian userland with the patched glibc) | `files/rootfs/` |
| the tool's tree (the porter, the engine, the Python modules) | `files/tool/` |
| the build tools (the NDK, the ARM64 LLVM, the .NET runtime) | `files/tool/toolchain/` |

A guest program is started **through the rootfs's loader** (`files/rootfs/usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1`):
Android has no `/lib` and the guest is not a chroot. The app's own `/system/bin/sh` cannot load them.

The environment variables are the app's `guestEnv()` (`android/app/src/main/java/com/nx/android/data/Env.kt`).
A missing one makes the tools miss their own libraries or their tree: `LD_LIBRARY_PATH` (the rootfs's and the
toolchain's), `NX2A_REPO` (the tree), `NX2A_NDK`, `NX2A_TOOLCHAIN`, `NX2A_HOME`, `NX2A_WORK`, `NX2A_RUNTIMES`.

## The helper

```bash
python3 devtools/device_cli.py env                 # the environment it runs with
python3 devtools/device_cli.py python -m porter doctor -k <path>   # the porter, on the phone
python3 devtools/device_cli.py guest <bin> <args...>              # any guest program
python3 devtools/device_cli.py raw <adb args...>                  # plain adb shell (no guest environment)
python3 devtools/device_cli.py launch <title ID>                 # start a game in the app (no tapping)
python3 devtools/device_cli.py ctl <title ID> <line>...          # key presses to the running game
python3 devtools/device_cli.py shot <local path>                 # the phone's screen into a PNG
```

It writes the command as a script into the app's temp folder and runs it with `run-as com.nx.android`.
**Do not build the command line by hand**: adb shell's nested quoting breaks easily (a `cat > f` once wrote a
file to the wrong place and broke the phone's compiler).

## The game without tapping

The app starts a game from its own intent (the home-screen icon and the library card use the same door):
`am start -a com.nx.android.action.LAUNCH_GAME -n com.nx.android/.MainActivity --es shortcut_title_id <title ID>`.

The running game reads its key presses from a file the host polls every 100 ms (`files/ctl-<title ID>.txt`):
a line is a key press ("A", "Down+Right", "T0.5x0.5" a touch, "B~0.15" a longer hold), "shot <path>", "passdump
<n>", "env KEY=VALUE" and more (the host's own list: `nxnative/dm/host/hle_hid.c`). The file outlives the run:
only the lines appended from now on are read, so a walkthrough can drive the game step by step.

`adb shell screencap -p` is the picture (the app's window with the game in it); a frame of the game alone is the section below.

## A frame of the game alone

`adb shell screencap -p` (and `device_cli shot`) is the whole window: the game plus the app's drawer, its perf line and the menu button. A picture of the game for the repository is a frame of the swapchain instead, which the Vulkan backend writes itself:

```
env DM_VK_SHOTS=1        # a ctl line, or the same row in env.txt
# → <DM_VK_SHOT_DIR, else DM_ROOT>/frame_000123.ppm — one PPM per present, numbered by frame
```

`DM_VK_SHOT=<n>[,<n>…]` picks single presents instead of a run of them. The file lands in the app's own folder: pull it as the app (`run-as com.nx.android`), and convert it with `devtools/ppm2png.py` (then resize and save as JPEG: the repository's pictures are 1280×720).

The host's `shot <path>` line is a **no-op on Android** — `dm_gfx_shot_at` is an empty stub in `dm/android/gfx_common.c` — though the ctl reader still logs `screenshot of the next frame → <path>`. Nothing appears at that path; a frame lying in the app's folder is a leftover of an earlier `DM_VK_SHOTS` run, so check its date before using it.

## The headless host

`nxnative/dm/android/build.py` builds three things: `dmhost` (an executable for adb shell runs: headless, no
window), `libdmhost.so` (the app's NativeActivity) and, with `--play`, `libdmplay.so` (the app's per-game runtime).

```bash
python3 devtools/device_cli.py python nxnative/dm/android/build.py --game <title ID> \
    --ndk <files>/tool/toolchain/ndk --out <files>/tmp/host --jobs 8
```

The game profile is **not** in the tree (the player imports it): point the build at the pack's own copy, the way
`porter rebuild-runtime` does — `DM_GAMES_DIR=<pack>/profile` and `DM_GAMES_FIRST=1`.

Running it headlessly needs the environment the app gives the host (`front_player.c`'s `host_start_common`):

| What | Where it comes from |
|---|---|
| `DM_ROOT` | the run's root: a **scratch copy** of the pack (mods/, shaders.dmsv, save/, temp/) |
| `DM_ROMFS` | the pack's own `env.txt` row |
| `DM_SAVE`, `DM_TEMP` | the scratch copy's folders |
| `DM_VK_SHADERS` | the scratch copy's shaders.dmsv |
| the rest (`DM_LANG`, the fonts, `DM_VK_DRIVER`) | the pack's `env.txt` rows |
| the command | `dmhost <root>/mods` |

**Never point it at the player's pack**: the host writes there (the pipeline caches, the save). Copy the pack's
`mods/` and `shaders.dmsv` into a scratch folder first.

A headless run has no input (the app's front end feeds the pad): it gets through the boot and the first scenes,
but not past a screen that waits for a press.

## The C tests on the phone

The upstream's tests cut the production C out of the source file and compile it with the host compiler (`cc`).
On the phone the compiler is the payload's ARM64 clang (`files/tool/toolchain/clang/bin/clang`, an ELF whose
interpreter path the app has rewritten), and the tests ask for `cc`: put a wrapper of your own in a folder on the
PATH. The wrapper execs the payload's clang (which is already a patched ELF) — not the loader plus the binary.

## The traps

- **Do not write into the phone's toolchain.** `files/tool/` is replaced by the next environment rebuild, and the
  compiler there is a patched ELF: a shell script in its place breaks every build on the phone ("invalid ELF
  header" from the loader). To restore it, push the payload's copy
  (`packaging/android-apk/.cache/assets/toolchain/clang/bin/clang`) and run the app's own patch
  (`files/tool/tools/patch_interp.py <dir> <interp path>`), or rebuild the environment in the app.
- **Compile with the phone idle.** A game at 60 fps leaves the phone with ~600 MB free; the compiler then
  thrashes in the swap for tens of minutes and looks like a hang. Kill the game first.
- **`files/tmp/` holds the earlier rounds' leftovers.** A stale `dis.py` there shadows the stdlib's `dis` (the
  script's own folder is first on `sys.path`): put your scripts in a folder of their own.
- **The app's own files are only reachable as the app** (`run-as com.nx.android`); the shell cannot read
  `/sdcard/Android/data/<pkg>/files`.
- **The player's pack is the player's**: the host writes there (the pipeline's caches, the save). A walkthrough
  copies the pack into a scratch folder first and runs against the copy.
- **The picture's time is what the game sees**: the host logs it as the output buffer's time
  (`AcquireOutputBufferIndex → index 0 time 7`). A game that advances its clock with it (Catherine: Full Body
  stops feeding the decoder when the picture's time does not move) needs a time that moves.
