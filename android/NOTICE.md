# NOTICE: the phone app's license

The nx2android phone app (the APK) is a combination of this project's own
code and of third-party components. This notice says which, and what the
app's license is. The repository's [NOTICE.md](../NOTICE.md) has the full
statement: the copyright holders, what the license covers, and the upstream
code this project continues.

## The license: GPL-3.0-or-later

The app is distributed under GPL-3.0-or-later, because that is the license of
the project's own code (see the repository's [LICENSE](../LICENSE)).

The app's native host carries no copyleft component beyond this repository's
own code: the frame generation is not in this build, so the host is covered by
the repository's license alone. The third-party components the host does use
are permissive, and each one is listed in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) with its license text
beside it — the Qualcomm SGSR upscaler's BSD-3-Clause text is at
`nxnative/dm/android/shaders/sgsr1.LICENSE`.

## What the app ships besides its own code

- **Third-party components and their licenses**: [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md),
  the index of everything the app redistributes. The MIT components shipped as
  binaries carry their license text next to them, in
  `nxnative/dm/gfx/tools/dmsh_xlate_bin/NOTICE.md` and its `LICENSES/` folder.
- **Python modules** (lz4, capstone, pillow, fonttools, pyyaml, pycryptodome,
  backports.zstd) and **the .NET runtime**, fetched at build time into the
  app's payload.
- **No game content**: the app ships no game files, no keys, no firmware and
  nothing extracted from them. It ports the player's own game files, which the
  player supplies.

## Lossless Scaling's `Lossless.dll`

The frame generation is not in this build, so nothing reads that file at run
time. It was proprietary and is not in this repository, not in any bundle and
not in the APK.
