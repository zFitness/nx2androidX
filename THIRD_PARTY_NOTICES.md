# Third-party notices

The components below are written by others and shipped with this repository or
with its published bundles. Each keeps its own license, and the license text
sits next to the code it covers. This file is the index: for each component it
gives the license, the version, where it came from and where the full license
text is.

The license of this repository's own code is GPL-3.0-or-later, in
[LICENSE](LICENSE); [NOTICE.md](NOTICE.md) says what it covers and who holds the
copyright on what. What is *not* covered by it is listed here.

## In the source tree (`nxnative/dm/third_party/`)

Each directory holds the component's own license file; `nxnative/dm/third_party/README.md`
describes what every one of them is, which version it is and where it is used.

| Component | License | Version | Origin | License text |
|---|---|---|---|---|
| `ryujinx/` | MIT | Ryujinx 1.3.2 (local changes in `ryujinx/README.md`) | https://github.com/Ryujinx/Ryujinx | `ryujinx/LICENSE.txt`, and `ryujinx/src/Spv.Generator/LICENSE` for that subproject |
| `libvpx/` | BSD 3-Clause + patent grant | v1.17.0 | https://chromium.googlesource.com/webm/libvpx | `libvpx/LICENSE`, patent grant in `libvpx/PATENTS` |
| `libadrenotools/` | BSD 2-Clause | — | https://github.com/bylaws/libadrenotools | `libadrenotools/LICENSE` |
| `vulkan-headers/` | Apache-2.0 or MIT (your choice) | Vulkan-Headers 1.4.363 | https://github.com/KhronosGroup/Vulkan-Headers | `vulkan-headers/LICENSE.md` |
| `bcdec/` | MIT or the Unlicense (your choice) | 0.985 | https://github.com/iOrange/bcdec | `bcdec/LICENSE` |
| `stb_vorbis/` | MIT or public domain (your choice) | 1.22 | https://github.com/nothings/stb | `stb_vorbis/LICENSE` |
| `flip/` | BSD 3-Clause | — | https://github.com/NVlabs/flip | `flip/LICENSE` |
| `macnativegames/` | MIT | — | MacNativeGames contributors | `macnativegames/LICENSE` |

## In the source tree, outside `third_party/`

| Component | License | Where | License text |
|---|---|---|---|
| `nvn.h` (the NVN API declarations) | MIT, Copyright (c) 2020 h1k421 | `nxnative/dm/gfx/nvn/include/nvn.h` | in the file header |
| The layout size algorithm ported from deko3d | zlib, Copyright (C) 2018-2020 fincs | `nxnative/dm/gfx/nvn/nvn_tex.c` | in the file header |
| Two adaptations from MacNativeGames (MIT) | MIT | `nxnative/dm/gfx/nvn/nvn_mtl.m`, `nxnative/dm/gfx/tools/dmsh_xlate/Program.cs` | `nxnative/dm/third_party/macnativegames/LICENSE` |
| `stb_image.h` (2.23), `stb_image_write.h` (1.13), `tinyexr.h` | MIT / public domain | `nxnative/dm/third_party/flip/tool/` | in each file's header |
| DroidSansFallbackFull | Apache-2.0 | `nxnative/dm/tools/DroidSansFallbackFull.ttf` | `nxnative/dm/tools/DroidSansFallbackFull.NOTICE` |
| OpenSans-Regular | Apache-2.0 | `nxnative/dm/tools/OpenSans-Regular.ttf` | `nxnative/dm/tools/OpenSans-Regular.NOTICE` |
| The shared font the app ships (`shared_cjk.ttf`, built from the two above by `dm/tools/cjk_font.py`) | Apache-2.0 | `nxnative/dm/tools/shared_cjk.ttf` | the two NOTICE files above |
| The SGSR upscaler (the host's super resolution pass, from Qualcomm) | BSD-3-Clause | `nxnative/dm/android/shaders/` | `nxnative/dm/android/shaders/sgsr1.LICENSE` |

The frame generation is not in this build: the port of the Eden emulator's
frame generation is gone, and with it the copyleft component the phone APK used
to link. The APK as a whole is still distributed under GPL-3.0-or-later, because
that is the license of the repository's own code. See
[android/NOTICE.md](android/NOTICE.md).

## Shipped as binaries

These are redistributed as compiled binaries, so their license text travels
with them.

| Component | License | Where it ships | License text |
|---|---|---|---|
| The shader translation tool `dmsh_xlate` and its .NET dependencies (Humanizer, MessagePack, Gommon, Microsoft.IO.RecyclableMemoryStream, System.CodeDom) | MIT | `nxnative/dm/gfx/tools/dmsh_xlate_bin/` | `nxnative/dm/gfx/tools/dmsh_xlate_bin/NOTICE.md` and `LICENSES/` beside it |
| `nx_extract` (the NSP reader) and LibHac 0.19.0 | GPL-3.0-or-later (its own code); LibHac is MIT | built from `nxnative/dm/tools/nx_extract/`, restored from NuGet | the repository's [LICENSE](LICENSE); the LibHac package is MIT |
| The .NET runtime the phone app ships | MIT | the app's environment archive (`payload.pkg`, at `tool/toolchain/dotnet`) | the .NET runtime's own terms, fetched from Microsoft |

## Fetched at run time or imported by the player, never shipped

| Component | License | Note |
|---|---|---|
| The Vulkan driver a player picks (Mesa Turnip and others) | their own | The player supplies the driver; the app never ships one it does not have the rights to. |
| The Android NDK, the .NET SDK and platform-tools | their own terms (Apache-2.0, MIT, Apache-2.0) | Downloaded by the Setup tab from Google and Microsoft. |
| The Python modules the phone app ships (lz4, capstone, pillow, fonttools, pyyaml, pycryptodome, backports.zstd) | permissive (BSD, MIT, Apache-2.0) | Fetched as wheels at build time into the APK's payload. |
| The `kuake` CLI (the Quark drive's file manager) | AGPL-3.0-or-later | Fetched by the release pipeline when it publishes a version to the netdisks (`python3 -m devtools.netdisk install`, into `tools/kuake/`, which is not committed). It is run as a program, not linked into anything here, and it is not in this repository, in any bundle or in the APK. Upstream: https://github.com/zhangjingwei/kuake_cli |

## The game's own content

None of it is here. The repository holds no game files, no keys, no firmware
and no extracted game assets, and the tool never downloads them. The game
profiles hold interoperation metadata only: shader key hashes, offsets inside a
module, and patch stubs of at most a few bytes of machine code. The README
says what each of them is.
