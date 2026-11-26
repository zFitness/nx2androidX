---
name: nx2android-dev
description: How to add a new game profile to nx2android (port another Switch game to Android) or improve the shared core (the Android runtime, the Vulkan backend, the Horizon host, the rewriter, the shader tools, the porter or the GUI). Use whenever the task is to port or bring up a game on Android, add or edit a profile under nxnative/dm/games/ or an android.tsv, decide whether a fix belongs in a profile or the core, make a core change (missing SDK/NVN functions, shader readers or the translator, input, the overlay, the pause menu), install a build on the device, or change porter/, gui/, packaging/ or nxnative/dm/android/ — even if the user only says "make <game> work" or "port <game>". Chasing a symptom on the device (flicker, crashes in the app, refused submissions, stutter) or measuring speed and stability is the switch-android-port skill's; it sends the fix back here.
---

# nx2android: game profiles and the core

nx2android turns a player's own Switch game files into an Android app: `porter` runs the port stages, `gui` draws them, `nxnative/` (our own fork of seedds/nxnative since 2026-10-29; no `upstream` remote, never pulled from) holds the engine. Every supported game is a **profile**; everything shared is the **core**. The contract is [docs/ARCHITECTURE.md](../../../docs/ARCHITECTURE.md): read it before changing anything, and keep it true.

**Scope: Android only.** The product is the phone app (APK) — the port, the data pack and the game itself all run on the device. `porter` and `gui` are the player's desktop path into the same pipeline: keep them working, but a change is not "the port" until it ships in the app. The repository root's `AGENTS.md` holds the scope, the build and release rules and the dev machine's platform: read it first.

## First decide: profile or core?

| The problem | Where the change goes |
|---|---|
| A game-specific constant, setting default, package name, device need, gamepad position, env switch | The profile: `nxnative/dm/games/<title ID>/android.tsv` (or upstream's `game.tsv`) |
| A fix in the game's own binary for one build (a cut, a gate) | The profile's `patches.py`, keyed by build ID (upstream's mechanism) |
| Anything that is true of Horizon, NVN, Vulkan, an engine version or the device | The core, as a **general rule** that holds for every game |

A fix that only one game needs today is still a core fix when it follows the semantics (Viractal brought `nvnTextureViewCompare`, NVN advanced blend modes, Unity 6.3's ComputeShader layout and a shader-translator fix: all general). A per-game branch in code is never the answer: a game that needs different behaviour gets a profile key. Comments may name the game a rule was found with.

- New game → [references/new-game-profile.md](references/new-game-profile.md)
- Core change → [references/core-changes.md](references/core-changes.md)
- Either way, testing on the device → [references/device-loop.md](references/device-loop.md)
- Chasing a symptom on the device (flicker, crashes in the app, refused submissions, stutter), measuring speed or stability → the **switch-android-port** skill ([.claude/skills/switch-android-port](../switch-android-port/SKILL.md)): playbooks, every debug switch, the NEO case study and device scripts.

## Rules that always hold

- **Ask before installing on the user's device.** Name the package and size; install test builds under another package (`--package org.nx2a.<name>.test`) beside the user's own app, and uninstall them afterwards. Someone at the tablet once removed an unannounced test app by hand. Never uninstall or overwrite the user's own install (`org.nx2a.neo` etc.) without being told to.
- **Keys and game files never enter the repository or the chat.** Print key names, never values.
- **Game files go only in `.gamedump/<App>/`** (the main checkout's, git-ignored), as hard links to the downloads, for every port, test or check: never a folder elsewhere on the machine (`C:\nx2a-test` on the upstream author's Windows box once kept 263 GB that nobody deleted). Delete the folder when the work is done: references/new-game-profile.md §0 and §5.
- **Measure, then change.** Every fix starts from evidence (a log line, a crash address, a census, a screen recording), and the evidence goes in the comment beside the fix, as the existing code does.
- **English everywhere; log lines for something unimplemented or wrong start with `[RED] `.**
- **Keep the shared core shared.** Changes in `nxnative/dm/{host,gfx,tools,third_party}` keep the iOS paths working and platform differences go behind `__APPLE__` / `__ANDROID__` / `DM_TARGET`. Android-only code belongs in `nxnative/dm/android/`.
- **Match the surrounding code**: its comment density, naming and dense one-line style.
- **Tests before committing**: `python -m unittest discover tests` (includes `tests/arch_rules.py`, which enforces ARCHITECTURE.md's layer rules: no game IDs, names or packages in core code, data-only profiles, GUI only over `python -m porter`…). Commit and push only when the user asks; end commit messages with the attribution line the session gives. Messages are Conventional Commits (`fix(vk): …`, `feat(profile): …`, `docs(status): …`; docs/DEVELOPMENT_GUIDE.md's Commit messages), checked by `.githooks/commit-msg`.
- **Update the docs with the code**: ARCHITECTURE.md when a layer, key or stage changes; the profile's `android.tsv` comment header with what was tested.
- **Every finished port updates the game list, in the same commit as the profile**: docs/PORT_CHECKLIST.md — add its line in alphabetical order if it is missing, drop "profile here" / "upstream profile", then `python docs/gen_tables.py` (the game has an `android.tsv`, so the generator ticks it, recounts the `N / M ported` line and adds the game to the READMEs' gallery; tests/test_docs_tables.py checks the file is what the profiles make). The gallery is read from the profiles, never written by hand: a game's cell comes from its `android.tsv` rows `readme_tag` (the release the port ships in), `readme_note` (one line of facts) and `readme_image` (a picture of the game itself, a file in the repository — the table shows no picture, and `docs/gen_tables.py` `cells()` takes the file's presence as the cell's membership), plus `readme_name` when the gallery names the game otherwise than `game.tsv`. Its credit, `ported by @handle`, is the GitHub account of the commit that **added** `android.tsv` (`credit_of()`): land the profile and its `android.tsv` in one commit whose author has a linked account. A commit that is not pushed yet has no account, and the generator caches that miss as an empty credit in `.cache/gen_tables_credits.json` — write `ported by @handle` into the checklist line by hand and regenerate, then `git checkout -- .cache/gen_tables_credits.json` so the lookup happens again once the commit is pushed.
- **Releases do not re-test older games** (since 2026-10-31): a release checks only the games it adds or fixes; a break in an older game is fixed by a later patch release. Version `0.MINOR.PATCH`: patch for new games and bug fixes only, minor for any other core change, major stays 0 (docs/DEVELOPMENT_GUIDE.md, Releases and version numbers).

## Dev machine gotchas (macOS)

- The engine's tools need `PYTHONUTF8=1` (porter sets it); `python3` with `PYTHONUTF8=1` also avoids UnicodeEncodeError when printing.
- Heredocs expand variables and backslashes: quote the delimiter (`<<'EOF'`) for literal text, or write a scratch `.py` file instead of a one-off heredoc.
- Toolchains for development are in the repo's untracked `tools/` (NDK r27c, .NET SDK 10, platform-tools, the Vulkan validation layer in `tools/vvl`); the player's settings are in `~/Library/Application Support/nx2android/config.json` (`NX2A_HOME` overrides the folder, which also holds the APK signing key and the built shader translator).
- adb: `tools/platform-tools/adb` (no `.exe`); the device is in `devtools/device.json` (serial and package). Big pushes go through `devtools/push_chunked.py` / porter (adb compression off, `-Z`), or adbd wedges.
- Hard links for the game files: `ln <src> <dst>` (same volume); check the link count with `ls -l <file>` (second column) before deleting a dump.
- Windows notes that do not apply here: Git Bash's `MSYS_NO_PATHCONV` (macOS paths are not mangled), `adb.exe`, `%APPDATA%`, and junctions — macOS has symlinks, and a recursive delete goes through a symlink just the same, so never link `tools/` into a worktree.
