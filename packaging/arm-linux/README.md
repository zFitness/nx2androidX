# The ARM64 Linux package

One file that runs on an ordinary ARM64 Linux: the launcher, the port pipeline and the
engine tools. The interface is GTK, so it runs on the machine's own Python with
PyGObject — the package carries the code, not the toolkit.

    python packaging/arm-linux/build_appimage.py                    # the thin package
    python packaging/arm-linux/build_appimage.py --with-profiles     # the full one

| Package | Size | What it carries |
|---|---|---|
| `nx2androidX-arm64.AppImage` | ~33 MB | The launcher, the pipeline, the engine tools and a Chinese font. The game profiles are not in it. |
| `nx2androidX-arm64-full.AppImage` | ~126 MB | The same, with all the game profiles (600 MB raw, ~100 MB packed). |

The profiles are a separate download either way: the thin package needs the release's
profile package (`nx2a-profiles-r<version>-<commit>.zip`) imported once, from the
launcher's Settings page — the same way the phone app takes them.

## What the build machine needs

- `mksquashfs` — macOS: `brew install squashfs`; Debian: `apt install squashfs-tools`
- Python 3.11 or later, and `curl`/`ar`/`tar` (the pinned downloads are fetched and
  checked against their SHA-256)

No cross compiler and no sysroot: the package carries no code of our own that has to be
compiled. The AppImage runtime and the fonts are fetched.

## What the machine needs

- glibc (the package does not carry it; that is the system's)
- `python3` and `python3-gi` (PyGObject with GTK 3) — Debian/Ubuntu:
  `apt install python3 python3-gi`
- an X11 or Wayland session (GTK needs one)
- a Vulkan driver (the games need it; the launcher does not)
- **with `--with-toolchain`, no compiler is needed**: the package carries clang, lld,
  glslc and a glibc prefix; `build.py --os linux` uses the bundled one automatically
  (`NX2A_TOOLCHAIN`, set by `AppRun`)

## How the package is put together

```
nx2androidX-arm64.AppDir/
├── AppRun                    the entry: the system's python3, pointed at this package
├── nx2androidX.desktop       the application menu entry
├── .DirIcon → nx2androidX.png
└── usr/                      a trimmed repository root
    ├── launcher/             the launcher
    ├── porter/               the port pipeline (the phone's, run on this machine)
    ├── nxnative/             the engine: the host, the tools, the profiles (the full package)
    ├── share/fonts/          a Chinese font and a monospace face
    └── phone_tools/
```

`usr/` being a repository root is what makes the pipeline behave inside the package
exactly as it does in a checkout: the pipeline finds its own root and the engine beside
it.

The package is mounted read-only, and the builds write beside their sources, so the
launcher copies the engine tree to the player's own folder the first time it runs (the
profiles stay linked to the ones in the package) and points the pipeline at that copy.

## The text has to be readable

A machine may have no fonts at all (a bare proot, for instance), and then the interface
shows random glyphs instead of Chinese. The package carries Noto Sans SC and DejaVu Sans
Mono, and `AppRun` writes a fontconfig configuration that points at them (the machine's
own fonts stay in use as well).

`AppRun` uses nothing but shell builtins: on a minimal system even `readlink`,
`dirname` and `cat` may be missing or broken. The only external program it runs is the
Python it ends up exec'ing.

## Running it

    ./nx2androidX-arm64.AppImage

On a machine without FUSE (an Android proot, for instance) the package has to be
unpacked instead of mounted:

    APPIMAGE_EXTRACT_AND_RUN=1 ./nx2androidX-arm64.AppImage

The player's data — the library, the settings, the imported profiles — stays in the
user's own directories (`~/.local/share/nx2a`, `~/.config/nx2a`), never in the package.

What the machine has can be asked without a window:

    ./nx2androidX-arm64.AppImage --check     # the data folder, the porter, Steam, the fonts
    ./nx2androidX-arm64.AppImage --fonts     # the font families the interface can use
