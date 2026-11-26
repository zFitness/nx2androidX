# Adding a game profile

A profile is data only: `nxnative/dm/games/<base game's title ID>/` with upstream's `game.tsv` and shader tables (`shader_map.tsv` + `.conflicts.tsv`, `shader_facts.tsv`, `shader_pairs.tsv`, `pso_manifest.tsv`, `bf_want.tsv`), an optional `patches.py`, and nx2android's `android.tsv`. Upstream's key reference is `nxnative/dm/games/README.md`; Android keys are in docs/ARCHITECTURE.md "Game profiles on Android". Viractal (`0100FD501F95A000`) was brought up this way and is the worked example.

## 0. Can it be ported at all?

Run `python -m porter inspect "<game folder>"`. The port refuses:
- a game whose `main` renders with Vulkan (the Android host replays NVN and OpenGL ES only so far);
- one whose shaders need a step upstream runs by booting the game on a Mac (legacy Unreal paks, PKZ archives). GLSLC captures, Oodle archives and Unreal shader archives are made on the Android device instead (docs/ARCHITECTURE.md), so those ports need adb and the device — and nothing more when the porter runs on the phone app, which is the device itself.
The game folder for any port, test or check is `.gamedump/<App>/` in the main checkout (git-ignored; `<App>` is the APK's name, e.g. `HadesII`), also from a worktree, and never a folder elsewhere on the PC: hard-link the downloaded NSP / NSZ / XCI files into it (`ln`, no copy; porter decompresses NSZ and XCZ itself), and never write into the downloaded game's folder. The port's `_build`/`_survey` folders, APK and data pack then land there too, and the folder is deleted when the work is done (§5). If the game has an iOS profile in `dm/games/` (52 do), its constants are already proven: start from it.

## 1. Experimental port

```
python -m porter port "<game folder>" --experimental --debug -k <prod.keys>
```

- No profile: upstream's survey writes `<game folder>/<id>_survey/survey.md` (modules, build IDs, SDK, engine markers, RomFS containers, rewrite-site census, imports vs host hooks) and a provisional profile guessed from the files.
- iOS-only profile: it is copied.
- Either way the profile lands in `<game folder>/<id>_build/profile/<id>/` with an `android.tsv` of status `experimental`, found by every tool through `DM_GAMES_DIR`. Nothing in the repository changes yet.
- Read survey.md before going further, and the stage logs in `<id>_build/logs/` when a stage fails.

Then install it under a test package (ask the user first) and follow [device-loop.md](device-loop.md):

```
python -m porter port "<game folder>" --experimental --debug --install --package org.nx2a.<short>.test --device <serial>
```

## 2. Bring it up

Iterate: read `log.txt`, find the first `[RED]` line or crash, fix, port again (only changed stages rerun). Typical first failures and where they are fixed:

| Symptom | Where |
|---|---|
| A stub named in a `[RED]` line (an SDK / NVN function the host lacks) | Implement it in the core by its semantics (`dm/host/hle_*.c`, `dm/gfx/nvn/hle_nvn.c`) — see [core-changes.md](core-changes.md) |
| `program shader … is not in the bundle` / shaders failing to translate | The shader split's readers (`dm/gfx/tools/shader_split.py`, `unityfs.py` …) or the translator (`dm/gfx/tools/dmsh_xlate`, `dm/third_party/ryujinx`) |
| Wrong rendering | The Vulkan backend `dm/android/gfx_vk_*.c`; diagnostics in [device-loop.md](device-loop.md) |
| Crash in the game's own code on one build | Upstream's bring-up catalogue `nxnative/docs/agents/03-bringup.md`; a per-build cut in the profile's `patches.py` only when no general rule fits |
| Memory / address-space layout | `game.tsv` keys (upstream README), checked against the survey |

Upstream's agent guide (`nxnative/docs/agents/`: 01-extract, 02-survey, 03-bringup, 04-graphics, 05-debugging) is written for the Mac host but its failure catalogue and survey method apply; the Mac-only steps (lldb, the Mac host, Metal) do not run here.

Play past the title into real gameplay before calling it more than `boots`: Viractal's first two "soft-locks" were the game's own responses to wrong inputs, and its name entry needed a core feature (the overlay keyboard).

## 3. Move the profile into the repository

When the game boots on the device:

1. Copy the profile files (not the build folder's other contents) into `nxnative/dm/games/<id>/`: `game.tsv`, `shader_map.tsv`, `shader_map.tsv.conflicts.tsv`, `shader_facts.tsv`, `shader_pairs.tsv`, `pso_manifest.tsv`, `bf_want.tsv` (and `patches.py` if one was written).
2. Check `game.tsv` by hand against survey.md (the survey's values are guesses where the README says so); scrub any local path from its comments.
3. Write `android.tsv`: a comment header (game, engine, SDK, what was tested on which device and date, known gaps), then rows. Only these keys exist:
   ```
   status       playable | boots | experimental
   tested       <version> <device>
   package      org.nx2a.<name>            (default org.nx2a.t<title id>)
   orientation  landscape | any
   requires     bcn                        (BC textures; the installer checks)
   setting      overlay=1 / rumble=1 / docked=0   (pause-menu defaults → settings.txt)
   env          KEY=VALUE                  (a host switch the game needs → env.txt)
   overlay      <control> <x> <y> [<r>]    (moves one control of dm/android/overlay_default.tsv)
   ```
   `android.tsv` is not part of the shader keys: editing it re-translates nothing.
4. Port again without `--experimental`; it must reuse or rebuild cleanly from the repository profile.

**Shader tables after a reader or translator fix.** For a profile in `dm/games`, the split refuses when the tables it makes differ from the profile's ("the split shader tables differ from game profile …"), so a change that finds more shaders stops the next port. The new tables are left in `<id>_build/shader/pkg.partial/tables/`: diff them against the profile's (more rows, none lost, the shaders that were missing now present), copy the three tables in, port again. Check the same for every other profile the change could touch (port NEO too).

## 4. Playable

- Play it on the device: title, menus, gameplay, a save, the pause menu, the on-screen gamepad, a controller if the game uses one, text entry if it asks for names, a few minutes of steady frame rate (`[perf]` lines) and no new `[RED]` lines.
- Set `status playable` and `tested <version> <device>`; update the header comment. A gameplay frame is worth capturing while porting, and the gallery's cell needs one in the repository (`readme_image`, the checklist bullet below) — a frame of the game on the device, not of the app around it: a `DM_CTL` line `env DM_VK_SHOTS=1` writes the next present as `frame_000123.ppm` into `DM_VK_SHOT_DIR` (default: the run's `DM_ROOT`) with no overlay, while `adb shell screencap` carries the app's drawer and perf lines, and the host's `shot <path>` line is a no-op on Android (`dm/android/gfx_common.c`). `devtools/ppm2png.py` turns the PPM into a PNG; the gallery's files are 1280×720 JPEGs in `docs/images/`.
- The nx2android version the game was tested on goes in the profile's `tested <version> <device>` row and in PORT_CHECKLIST.md's line. A port on the development checkout takes the next release's version: the patch after the latest tag if `main` has only new games and bug fixes since it, else the next minor (docs/DEVELOPMENT_GUIDE.md, Releases and version numbers). This is not the profile's `tested <version> <device>`, which names the game's update.
- Add the game's line to docs/PORT_CHECKLIST.md: ``- [x] <name> · `<title ID>` `` with the "profile here" / "upstream profile" note dropped (add the line in alphabetical order if the game is not listed), then run `python docs/gen_tables.py`: the game has an `android.tsv`, so the generator ticks it, recounts the `N / M ported` line and adds the gallery cell (tests/test_docs_tables.py checks). The gallery cell is the `android.tsv` rows `readme_tag` (the release the port ships in), `readme_note` (one line: the update, the frame rate, the device and driver), `readme_image` (the picture above — the table shows no picture; the generator takes its presence as the cell's membership) and, only when the gallery names the game otherwise than `game.tsv`, `readme_name`. The credit `ported by @handle` is the GitHub account of the commit that added `android.tsv` (`docs/gen_tables.py` `credit_of()`): an unpushed commit has none, the generator caches that miss as an empty credit in `.cache/gen_tables_credits.json`, so write the credit into the checklist line by hand, regenerate, and `git checkout -- .cache/gen_tables_credits.json` rather than commit the empty entry. The doc goes in the profile's commit; a port is not done until it shows the game.
- Run `python -m unittest discover tests`; uninstall the test app; commit when asked.

## The frame rate a port ships with

Four switches decide it, and each one overrides the one above it:

| Where | What it does |
|---|---|
| `game.tsv` `fps_target` | the rate the profile registers (a 60 target the governor may step down from). The porter writes `DM_FPS_TARGET=60` into the pack only when the build asked for 60 (`--fps60`, `porter/pipeline.py` `fps_unlock`); a profile carrying `fps_target 60` built without the option writes no row of its own |
| `android.tsv` `pacing` | one preset — `adaptive` (the profile's target, the governor steps 60/40/30), `steady`, `fixed60`, `fixed30`, `game` — turned into env rows (`dm/android/tools/android_profile.py` `PACING`) |
| the pack's `env.txt` | the profile's rows first, then the build's own (`porter/datapack.py`), read by the host with `setenv(…, 1)`: a later row wins (`dm/android/front_player.c` `env_file`), which is how `--fps60` beats `pacing game` |
| the player's drawer (rate pin) | `DM_FPS_PIN` after start: overrides all of it (`GameActivity.kt`, `dm/android/perf_android.c`) |

So a profile whose `fps_target` is 60 still runs at the game's own 30 fps when its `android.tsv` says `pacing game` (`DM_FPS_TARGET=0`): that row is the answer, not a build that forgot an option. Check the log's one `pacing:` line and the pack's `env.txt` before chasing a rate — Octopath Traveler II is the worked example.

## 5. Clean up

The machine has little disk space. Once the port is committed and the test app uninstalled, delete `.gamedump/<App>/`: first check that each dump file in it has a link count of 2 or more (`ls -l <file>` on macOS — the second column), so the downloaded copy remains; a file with one link is the only copy, so stop and ask. Keep a folder that other work still uses, and say so. A test or check that is not a port ends the same way.
