# The ARM64 Linux package

One file that runs on a supported ARM64 Linux: the launcher, the port pipeline and the
engine tools. The interface is **PySide6 (Qt)** — earlier docs described a GTK/PyGObject
build; that description is outdated and the rest of this file reflects the current code.

    python packaging/arm-linux/build_appimage.py                     # the thin package
    python packaging/arm-linux/build_appimage.py --with-profiles     # the full package
    python packaging/arm-linux/build_appimage.py --with-toolchain    # + toolchain & Qt
    python packaging/arm-linux/build_appimage.py --with-toolchain --with-profiles \
        --label candidate                                            # a candidate test package

| Package | Contains |
|---|---|
| `nx2androidX-arm64.AppImage` | Launcher, pipeline, engine tools, Chinese + monospace fonts. No profiles, no Qt. |
| `nx2androidX-arm64-full.AppImage` | The thin plus all game profiles. |
| `nx2androidX-arm64-toolchain.AppImage` | The thin plus Qt (PySide6 wheels), the build toolchain (clang, lld, glslc), the .NET runtime with prebuilt C# tools, and the pipeline's Python modules. |
| `nx2androidX-arm64-toolchain-full.AppImage` | Everything: toolchain + profiles. |

Profiles are a separate download either way: the thin package needs the release's
profile package (`nx2a-profiles-r<version>-<commit>.zip`) imported once from the
launcher's Settings page — the same way the phone app takes them.

## Supported baseline (read before promising "it just runs")

- **OS**: Linux on **ARM64 only** — every engine binary we ship is an aarch64 Linux
  ELF. There is no x86-64 build of the launcher target.
- **glibc ≥ 2.39** for the bundled PySide6 wheels (Ubuntu 24.04+, Debian 13+, Fedora 40+).
  Older distros must use the *thin* package with a distro `python3-pyside6`, if the
  distro ships one.
- **python ≥ 3.10** to load the interface (abi3 wheels); the *port pipeline* modules
  (`lz4`, `PIL`, `yaml`, `capstone`) ship as cpython-314 extensions, so **python 3.14 is
  required to run the pipeline** from the --with-toolchain package. `AppRun`
  warns if the interpreter is not 3.14.
- **an X11 or Wayland session** (Qt needs one) — the display stack is the system's, not
  the package's.
- **a Vulkan driver** for the games; the launcher itself does not need it.
- **with `--with-toolchain`, no compiler is needed**: the package carries clang, lld,
  glslc and a glibc prefix; `nxnative/dm/android/build.py --os linux` uses the bundled one
  automatically (`NX2A_TOOLCHAIN`, set by `AppRun`).

We do not promise "runs anywhere, any distro, double-click".

## What the build machine needs

- `mksquashfs` — macOS: `brew install squashfs`; Debian: `apt install squashfs-tools`
- Python 3.11 or later, and `curl`/`ar`/`tar` (the pinned downloads are fetched and
  checked against their SHA-256)

No cross compiler and no sysroot of our own: the package carries no code of ours that
has to be compiled. The AppImage runtime and the fonts are fetched.

## How the package is put together

```
nx2androidX-arm64.AppDir/
├── AppRun                    the entry: the system's python3, pointed at this package
├── nx2androidX.desktop       the application menu entry
├── .DirIcon → nx2androidX.png
└── usr/
    ├── launcher/             the launcher
    ├── porter/               the port pipeline (the phone's, run on this machine)
    ├── nxnative/             the engine: the host, the tools, the profiles (the full package)
    ├── phone_tools/          the payload's own small tools, driven by name
    ├── pylibs/               porter's Python modules (+ Qt when --with-toolchain)
    ├── toolchain/            clang, glslc and the glibc prefix (--with-toolchain)
    ├── dotnet/               the .NET runtime (--with-toolchain)
    ├── cs-tools/             nx_extract, dmsh_xlate (--with-toolchain)
    └── share/fonts/          a Chinese font and a monospace face
```

`usr/` being a repository root is what makes the pipeline behave inside the package
exactly as it does in a checkout: the pipeline finds its own root and the engine beside
it.

The package is mounted read-only, and the builds write beside their sources, so the
launcher copies the engine tree to the player's own folder the first time it runs (the
profiles stay linked to the ones in the package) and points the pipeline at that copy.

## Environment separation

- The compile sysroot (`usr/toolchain/glibc`) is **never** put on `LD_LIBRARY_PATH`.
  Only `usr/pylibs` is on it, and only because the port pipeline's ABI extensions
  (`liblz4`, `libyaml`, `libcapstone`, ...) need it to import.
- The system Vulkan loader, ICDs and display stack remain the system's — the package
  stages the dev symlink for linking only.
- Known caveat, pending coordination: game processes started by the launcher
  inherit `LD_LIBRARY_PATH` (they are children of the same python); the clean fix is a
  scrub in `launcher/launch.py environment()`, which is outside this packaging scope.

## Where the player's data lives (and why a package update can't hurt it)

The player's data is never in the package and is never cleaned by a package upgrade or
removal:

| Purpose | Location |
|---|---|
| Settings | `~/.config/nx2a/launcher.json` |
| Single-instance lock | `~/.config/nx2a/launcher.lock` |
| Porter config (incl. prod.keys reference) | `~/.config/nx2a/porter/config.json` |
| Library of ported games | `~/.local/share/nx2a/library` |
| Porter working resources | `~/.local/share/nx2a/work` |
| Caches | `~/.local/share/nx2a/cache` |
| Logs (one per game run) | `~/.local/state/nx2a/logs` |

`work` is a running resource, **not** a disposable cache — a pack's `env.txt` sets
`DM_ROMFS` to a real path inside `work`, and games read their RomFS from there on every
launch. Replacing or removing the AppImage does not touch any of the above.

## Provenance manifest

Alongside each built artifact the build writes `<artifact>.manifest.json` with:

- the artifact name, size and SHA-256;
- HEAD and branch of the repository at staging time, plus the full `git status
  --porcelain` listing — staged and unstaged files named, because only HEAD is
  not enough to say what a parallel-workspace build carries;
- a per-file SHA-256 inventory (path, bytes, sha256, symlink targets) of the staged
  tree, per component, with an aggregate digest per component;
- the pinned downloads (runtime, fonts) and their hashes; the bundled PySide6 wheel
  names, version and hashes; and the resolved Debian/Ubuntu deb versions + hashes.

Reproducing a candidate package exactly: check out the recorded HEAD, add the
recorded dirty-file state, keep the recorded dependency set, and the staged
inventory should hash identically.

## What the host machine needs

- glibc (the package does not carry it; that is the system's)
- `python3` (≥ 3.10; **3.14 for the port pipeline**, see the ABI note above)
- **thin package**: PySide6 for the system python3 —
  `apt install python3-pyside6` or `python3 -m pip install PySide6`
- an X11 or Wayland session (Qt needs one)
- a Vulkan driver (the games need it; the launcher does not)
- **with `--with-toolchain`, no compiler is needed**: the package carries clang, lld,
  glslc and a glibc prefix; `nxnative/dm/android/build.py --os linux` uses the bundled one
  automatically (`NX2A_TOOLCHAIN`, set by `AppRun`)

## The packaging migration (in progress — do not rely on it yet)

The shapes this README documents are built by the current `build_appimage.py` AppDir +
runtime + SquashFS line. A parallel effort is moving the package onto the same
PyInstaller + appimagetool chain the desktop GUI bundle uses (built natively in an ARM64
Linux container, keeping the launcher as the entry), so the package stops carrying a
repository tree. Until that lands and this README is updated by the session that finished
it, treat everything above as the current, working truth — and no claim of "self-contained
Python" or "runs on any Linux" may be made for the new chain yet.

## Running it

    ./nx2androidX-arm64.AppImage

On a machine without FUSE (an Android proot, for instance) the package has to be
unpacked instead of mounted:

    APPIMAGE_EXTRACT_AND_RUN=1 ./nx2androidX-arm64.AppImage

The player's data — the library, the settings, the imported profiles — stays in the
user's own directories (`~/.local/share/nx2a`, `~/.config/nx2a`), never in the package.
Upgrading or removing the AppImage does not delete any of it.

What the machine has can be asked without a window:

    ./nx2androidX-arm64.AppImage --check     # the data folder, the porter, Steam, Qt
    ./nx2androidX-arm64.AppImage --fonts     # the font families the interface can use
