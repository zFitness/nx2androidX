# NOTICE

nx2androidX — the phone port of Nintendo Switch games

Copyright (C) 2026 zFitness
Copyright (C) 2026 seedds (the vendored upstream engine tree under `nxnative/`)
Copyright (C) 2026 shirai91 (the upstream desktop tool this repository continues)
Copyright (C) 2026 Tung Pham

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program.  If not, see <https://www.gnu.org/licenses/>.

The license text itself is [LICENSE](LICENSE). This file says what those terms
cover, who holds the copyright on what, and which parts keep a license of their
own.

## What this covers

The code this repository owns and maintains — the porter (`porter/`), the
desktop GUI (`gui/`), the phone app (`android/`), the packaging scripts
(`packaging/`), the documentation (`docs/`, `README.md`) and the vendored
upstream engine tree (`nxnative/`) — is under those terms.

Parts of the tree are written by others and are NOT covered by them. They keep
the license file in their own directory, and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) lists all of them:

| Path | License | License file |
|---|---|---|
| `nxnative/dm/third_party/*` | each its own (MIT, BSD, Apache-2.0, zlib) | in each directory, listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) |
| `nxnative/dm/gfx/tools/dmsh_xlate_bin/` | the prebuilt binaries carry the licenses of the components they are built from | [`nxnative/dm/gfx/tools/dmsh_xlate_bin/NOTICE.md`](nxnative/dm/gfx/tools/dmsh_xlate_bin/NOTICE.md) |

Every binary built from this repository — the phone APK, the desktop zip, the
host and the per-game APK — is distributed under GPL-3.0-or-later. What that
means for the app is in [android/NOTICE.md](android/NOTICE.md).

## The upstream code this repository continues

Two upstreams are vendored here, and both were MIT licensed:

- **the engine tree under `nxnative/`** — from
  [seedds/nxnative](https://github.com/seedds/nxnative), which ships an MIT
  license file.
- **the desktop tool the porter and the GUI continue** — from
  [shirai91/nx2android](https://github.com/shirai91/nx2android), whose README
  states "MIT, as nxnative". That repository ships no license file, so the MIT
  text is quoted for it here too.

Both are relicensed here as GPL-3.0-or-later under the sublicense clause of the
MIT license they carried ("to use, copy, modify, merge, publish, distribute,
sublicense, and/or sell copies"), with their copyright notices kept. The MIT
text is reproduced in full at the end of this file.

### The original MIT license of the upstream code

MIT License

Copyright (c) 2026 seedds
Copyright (c) 2026 shirai91

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Game files and trademarks

This repository contains no game files, no keys, no firmware and nothing
extracted from them, and the tool never downloads any of those. The game
profiles hold interoperation metadata only (shader key hashes, offsets inside
a module and small patch stubs), which the README explains in full.

Nintendo Switch, the game names and the trademarks and game artwork shown in
this repository identify the games this tool is compatible with. They belong to
Nintendo and to the respective publishers and developers. This project is not
affiliated with or endorsed by them.
