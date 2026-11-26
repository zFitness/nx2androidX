# The port does not build: what stopped it, and where

The porter runs the stages in `porter/pipeline.py`. Each one has its own failure, and most of
them say in one line what is wrong. This is the list of them, in the order the port runs.

**Read this when**: a build fails, the port refuses to start, or the port stops at a stage.

The case index (`case-index.tsv`) has the upstream pull requests behind these; the numbers in
brackets are those.

## The stages

| Stage | What it does | The log says |
|---|---|---|
| inspect | reads the dump, finds the title and its version | `not the builds the provisional profile registers` |
| extract | `nx_extract` unpacks the NCA into the RomFS and the ExeFS | `build nx_extract` |
| DLC | unpacks the add-on content | `extract DLC` |
| decompress | the NSZ and the XCZ | `decompress NSZ / XCZ` |
| system data | the console's own data (the fonts, the shared fonts) | `extract system data` |
| graphics check | decides what the port needs: the Oodle decoder, the UE decoder, the GLSLC capture | fails here, before anything is built |
| GLSLC capture | boots the game on the device to capture the shaders it compiles at run time | `GLSLC capture` |
| UE shader decode | the game's own Oodle decodes the Unreal shader code archives | `UE shader decode` |
| 60 fps | the profile's own patch for the frame rate | `60 fps` |
| rewrite | the rewriter patches the game's own binary | `rewrite` |
| shader split | `shader_split.py` finds the shaders | `shader split` |
| Vulkan shaders | the translator turns them into the bundle | `Vulkan shaders` |
| host | the NDK builds the host for the device | `host` |
| APK | the app is packed | `APK` |
| data pack | the game's files and the settings | `data pack` |
| install | the app is installed and started | `install` |

The shaders have their own document: **shader-split.md**.

## Before anything is built

### The dump is not the build the profile registers

```
not the builds the provisional profile registers: <builds>
```

The dump carries another build. A regional release is its own binary with its own build ID:
it needs its own profile, its own host rows and its own shaders. Port the version the
profile registers, or register the patches for this build (`nxnative/dm/tools/nso_fnmap.py`
carries the addresses over).

The same message appears in another shape when the game's own decoder needs the tested build's
patches:

```
<game>: this dump is not the build the game profile registers, and the game's own decoder
(its shaders are Oodle-compressed) needs the patches of the tested build: <builds>
```

### The game renders with something the Android host cannot replay

```
<game> renders with <gfx>: the Android host replays NVN or OpenGL ES only so far
```

OpenGL ES is fine: the device's own driver runs it (`nxnative/dm/android/gl_android.c`), and
there are no shaders to translate. Anything else is not ported yet.

### The port needs a step that boots the game in the Mac host

```
<game> needs a step that boots the game in the Mac host (<what>), which the Android port
cannot run yet
```

Three kinds need a step this fork cannot run on the phone: a legacy Unreal pak with LZ5
blocks, an Oodle entry the split cannot read without the game's own decoder, and the PKZ
packs. Upstream moved the Unreal and GFPAK and Trinity work onto the device (`#41`, `#76`,
`#79`); this fork has that too.

### The shaders are in Oodle-compressed archives and the device is not connected

```
<game>'s shaders are in Oodle-compressed archives (<what>): the port decodes them with the
game's own decoder on the Android device, so connect it (adb) and port again
```

The game's own decoder is the only one that reads those entries. The phone app's porter
**is** the device, so it decodes them there with no adb; a porter on a desktop needs the
device connected even without installing.

### The game compiles its shaders at run time and the device is not connected

```
<game> compiles some shaders at run time (<what>): the port boots the game on the Android
device to capture them, so it needs adb and the device even without installing
```

Fire Emblem: Three Houses, Catherine: Full Body, Crash Team Racing, Let's Go Pikachu, MMBN
Legacy and Portal 2 are like this. The outputs are in no game file, so the port runs the
game's own compiler to get them. **The first port of such a game is not the final one**: the
capture comes in with the next `--install`.

### The environment does not match the app

```
The porting environment does not match this app. Refresh the environment before porting.
```

The environment capsule in the top bar installs it. The payload carries a stamp the app
compares.

### There is no `prod.keys`, or not enough room

```
no prod.keys: give -k / --keys, or set it once with `porter config keys <path>`
```

```
not enough disk space on <where> for the build folder: the port needs about <n> GB more,
<n> GB is free
```

The build folder wants several GB (a game's shaders alone are hundreds of MB), and the data
pack is as big as the game. The check is on the volume of the build folder, not only on the
phone's own.

## The rewriter

The rewriter (`nxnative/dm/tools/patch_nso.py`) patches the game's own binary: the jump
tables the compiler used, the atomic windows, the stack alignment, the relative relocations.
It stops with an assertion when it meets a shape it does not know:

```
AssertionError: jump table <address>
```

**The full catalogue is in `nxnative/docs/agents/03-bringup.md`** (upstream's own failure
catalogue, written for the Mac but the rewriter is the same; a checkout path, so it is not
on the phone). It names every shape that has come up, the game it came from and the rule
that handles it: the offset table, the byte table, the table relative to an `adr`, the table
whose base was set far back, the halfword table, the indirect tail call, the branch into the
patch area, the observation gate, the data block at the start of the text.

Two rules from it that save the most time:

- **Census before you fix.** A copy of the rewriter whose assert prints and continues finds
  every site of a shape in one run, instead of one run per site. A module with 25 508 `x18`
  sites was found this way.
- **Every other module must come out byte-identical.** Rewrite every extracted module of
  every game with the old and the new rewriter and compare: only the rewriter's own hash may
  differ, for the titles the change is not meant for.

The rewriter's own memory can be the problem: a stretch without unwind entries is one
function, and the detailed disassembly costs about 880 bytes an instruction. A function over
256 KB is now analysed in pieces.

## The profile

The profile is the game's own data (`nxnative/dm/games/<title ID>/`): `game.tsv` (the
identity, the versions, the memory layout), `android.tsv` (the package, the settings, the
`env` rows), `patches.py` (the code cuts, keyed by the build ID), and the shader tables.

| The problem | Where it is fixed |
|---|---|
| The version is a placeholder (`v1`) | `game.tsv`'s `build` and `package` rows: the real version, and where it came from |
| The memory layout is too small | `game.tsv`: `mem_reserve`, `mem_alias`, `mem_stack`, `app_pool`, `sys_resource` |
| The address space runs out at the boot | the same keys, and the engine's own allocator (`nxnative/dm/host/hle_uemalloc.c`) |
| A code cut for one build | `patches.py`, keyed by the `main` build ID |
| A switch for one game | `android.tsv`'s `env` rows (a `DM_*` row) |
| An answer the translator could not work out | `shader_facts_manual.tsv` |
| The host rows for a regional release | `nxnative/dm/host/hle_*.c`: a regional release is its own binary, so it needs its own rows |

The memory layout is the one that bites hardest on a phone. A game that uses virtual address
memory reserves a region for the engine at boot - Unreal asks for 62 GB by default - and the
phone has about 5 GB to give. The upstream pattern: cut the engine's allocator out and put
the host's own in its place, and give the region a capped size in the profile.

The upstream pull requests behind the memory work: `#451`, `#535`, `#303`, `#436` (the alias
region), `#466`, `#213` (the rewriter), `#79` (the Unity type trees).

## The shaders

Two failures of the shader stage have their own messages:

```
invalid shader export: <what> (see <log>)
no shader translated (see <log>)
```

and, from the split, the one that means the game files and the profile do not match:

```
[RED] the split shader tables differ from game profile <title ID>'s: shader_map.tsv
```

The rest of the shader stage is in **shader-split.md**.

## The host, the APK and the data pack

| The message | What it means |
|---|---|
| `build.py made no <lib>` | the NDK build of the host failed; the log is in the build folder |
| `the translator built without dmsh_xlate.dll` | the .NET build of the translator failed; the log is beside it |
| `the prebuilt shader translator is missing and the packages cannot be restored` | the phone has no network: the NuGet packages must be in the cache |
| `--external-display / --native-keyboard needs javac and an Android SDK with a platform and build-tools (set ANDROID_HOME)` | those two features are built on the computer; the rest does not need them |
| `the version to pack must be one the provisional profile registers` | the APK is packed for a version the profile does not know |
| `the version to pack (<n>) is not in the folder` | the folder does not hold that version |

## Rebuilding the host after a fix (on the phone)

A fix in the host (`dm/host/…`, `dm/android/…`) is worth nothing until the phone builds it
again. The phone is the porter: it compiles the host with the player's own NDK.

```sh
# the host of a game that is already ported: its libdmhost.so is built again from the
# profile, the saves and the game's data stay. The package is in the pack's
# nx2a-data.json ("package": "org.nx2a.t<title id>")
python3 -m porter host --package org.nx2a.t010078d000f88000 --jobs 8

# the game's own runtime (the shaders and the game binary) instead:
python3 -m porter rebuild-runtime <the pack folder> --jobs 8
```

The build lands in `files/runtimes/<title id>/`; the next run of the game uses it. Read the
run's log to see what the new code did (`log.txt` is the last run, `log.prev.txt` the one
before it). A build that dies mid-way is cached stage by stage: start it again and it picks
up where it stopped.

Do not go looking for the build command in the porter's Python: the two commands above are
the ones. (`porter --help` lists them all; `porter host` is the one for a host fix.)

## The build dies on the phone

The app disappears mid-build and the history says "Interrupted". That is the system killing
it, for one of three reasons: the battery manager clears "abnormal power drain" (a heavy app
is force-stopped, on MIUI even in the foreground); there is not enough free memory (a build
peaks at several GB); the battery is low (below a threshold the system throttles the CPU and
clears the backgrounds, so builds die earlier and run slower).

In order: clear the memory of the games and video players before the build; keep the battery
healthy and the power saver off; set the app's battery policy to "No restrictions"; allow the
background run and the autostart; lock the app's card in the recents screen; keep the screen
on.

**Every finished stage is cached.** A build that dies can be started again and it catches up
in seconds.

## How to work a build failure

1. **Read the stage and the first error.** `builds.py` gives the stage the port stopped at and
   the first error of the failed build; the full log is in `$NX2A_HOME/builds/<id>/log.txt`.
2. **Do not read the game files.** The profile, the dump and the logs are enough; the game's
   own files stay in the player's own folder.
3. **Check the version first.** Most stops are a dump that is not the build the profile
   registers.
4. **Check the device.** Two stages need the phone: the GLSLC capture and the game's own
   Oodle decoder. The phone app's porter is the device; a desktop porter needs adb.
5. **A shader count that is too low** is a container format nobody read yet: shader-split.md.
6. **A rewriter assertion** is a new instruction shape: `nxnative/docs/agents/03-bringup.md`,
   and census the sites before fixing one.
