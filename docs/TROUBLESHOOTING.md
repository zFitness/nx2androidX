# Troubleshooting

Pitfalls hit while converging the fork onto the upstream front (November 2026), kept as recipes: the symptom, the cause, the fix, and how the cause was actually found. Everything here was a real bug that shipped to a phone and cost a debugging session.

## The runtime's saves live in per-game subfolders

`DM_SAVE` is `<app files>/save/<title id>` — not the flat `<app files>/save` upstream uses. Upstream hosts one game per APK, so its flat layout is fine there; the app hosts many games in one process, and the old front kept each game's saves apart by appending the title id (`DM_GAME_ID`, set by the app's JNI adapter from the launch call's title id, read by the boot). The convergence onto the neutral boot dropped both halves: the adapter ignored the title-id parameter (`(void)title_id;`) and the boot took upstream's flat `setenv("DM_SAVE", ...)`. Every game then shared one save root and saw nobody's old saves.

Two traps inside the fix:

- **`setenv(name, value, 0)` does not overwrite.** The boot sets the flat `DM_SAVE` first (upstream's line), so the per-game adjustment must pass overwrite = 1, or the flat value silently wins. The old front never hit this because it setenv'd the per-game value once, with nothing before it.
- **`DM_GAME_ID` was deleted from `dm/settings.tsv` as "dead"** during the merge — a row with no reader in the tree is a symptom of a lost reader, not of a dead feature. Before deleting a settings row, check the history of who read it.

## A renamed file must be renamed on both sides of the boundary

The host library was renamed `libdmplay.so` → `libdmhost.so` on the porter side (writer), but the app's loader (`RuntimeStorage`) still looked for the old name (reader). Every game kept loading the stale pre-rename library sitting beside the freshly rebuilt one: no menu, no input, nothing of the new front. When renaming anything that crosses the porter/app boundary, grep both trees for both names, and delete the stale file at the same time (a same-path stale copy would even win over `dlopen` in a long-lived process — see the next entry).

## A long-lived process never reloads a library from the same path

The `:play` process survives across launches. A rebuild overwrites `runtimes/<id>/libdmhost.so` on disk, but a process that had already loaded that path keeps its old mapping: `System.load` of the same path returns the existing handle, so the "new" runtime never runs — the session quietly continues on the mixed old code. A rebuild that must take effect requires the process to actually die first (the manage-menu rebuild with the game still running only resumes it; the run gate resumes instead of restarting). Symptom worth remembering: a rebuilt runtime whose log keeps showing the old behavior, with no errors anywhere.

## The neutral boot takes ownership of its jobject arguments

`dm_front_boot` stores the activity jobject for the lifetime of the process (watch threads and menu callbacks use it). The NativeActivity shell hands it a long-lived reference; the app's JNI adapter hands it a local one that dies when `start` returns — the first Java callback on a watch thread then aborts the whole runtime (`JNI DETECTED ERROR: jobject is an invalid JNI transition frame reference`, only under the debug build's strict JNI checks). The boot therefore makes its own global ref up front. Rule for every shell of the neutral core: references the core stores must be globalized by the core, not trusted from the caller.

## The overlay's font is an APK asset, and CJK needs it

The front reads its menu font from `assets/font/ui.bin` (the fusion-pixel pack, staged by `build_assets.py` into the APK). Without it the menu falls back to built-in Latin-1 and every Chinese/Japanese/Korean label draws as boxes — the game itself still renders fine (its fonts are its own), which makes it look like a text-encoding bug when it is purely a missing asset. `select_game_language` (following the device locale) is what switches the menu to Chinese and exposes the missing font.

## build.py compiles exactly `GL_SRC`, never the folder

The shader list is filtered by suffix (`.vert/.frag/.comp`) because `dm/android/shaders/` also holds a third-party license file. A glob over the folder compiles the license with glslc and fails the whole runtime build (upstream added `sgsr1.LICENSE`; the fork's glob was the merge residue). When upstream adds files beside code, expect a glob over that folder to pick them up.

## Never refresh the tool tree while a rebuild is compiling

Installing an APK re-extracts the payload over `files/tool/`. If a rebuild is compiling at that moment, its later sources read the new tree and its earlier ones the old — the output is a mixed-vintage binary that md5s differently from every build you meant to make, and the sources you think it built are not the sources it built. Finish or kill the rebuild before installing; verify which binary a session actually loaded via `/proc/<pid>/maps` (the path is not enough — note the inode and compare mtimes).

## The save manager: what Export/Import actually do

The pause menu's entries drive `saves_android.c`: **Export** copies the committed save (never `.work`: a transaction in flight is not a save) byte for byte into the pack folder's `saves/<YYYYMMDD-HHMMSS>/` — the console's native layout, so console saves import as they are. **Import** lists those folders, applies the pick at the **next start** (the current save is exported first as `<stamp>-before-import`, so an import can be taken back), and swaps atomically. It is a snapshot/restore of the game's own save files, not a savestate, and not a file manager — browsing and deleting snapshots happens through the file manager in the pack folder.

## The transactional save: `.work` is a scratch copy, the committed dir is the truth

During play the game writes into `<DM_SAVE>.work`; a save commit clones-and-swaps it over `<DM_SAVE>` atomically. On mount, a leftover `.work` is **cleared and re-cloned from the committed directory** — the committed dir is always the source of truth, a stale `.work` holds nothing unique unless a session died mid-transaction. So: never hand-delete `.work` while a session may still commit into it, but do not treat it as a backup either. The log's mount line (`fs mount save: → <path>.work`) names the mount's actual base directory — reading it is the fastest way to see which save root a session really used.

## The log's elapsed timestamps are not for dating things

`dm_log_elapsed()` derives the process start time through a sysctl shim reading `/proc`; on some devices the values it prints are garbage (a boot line reading days of "elapsed" for a minutes-old process). Reason about sessions by **which log file** (`log.txt` is the latest boot's, rotated by each boot, `log.prev.txt` the one before) and by **file mtimes**, never by the `[dm] <seconds>` column.

## `setenv(name, value, 0)` does not overwrite — and the flat default was set first

The boot set the flat `DM_SAVE` (upstream's layout) before the per-game adjustment ran, and the adjustment used
`setenv(..., 0)` — overwrite disabled — so the flat value silently won and every game kept seeing the shared root:
no old saves, no error anywhere. The third argument of `setenv` is part of the contract; when a value must win,
pass 1, or set only the winner once. The diagnostic log lines that pinned it down (`DM_GAME_ID=…, DM_SAVE=…` at
boot) stayed in the tree for exactly this kind of hunt.

## `python -m pkg.module` needs its own `__main__` guard

`-m porter` works because the package carries `__main__.py`; `-m porter.phone_cli` executes the module itself,
which defined `main()` and exited silently — the app's rebuild button then saw a process with no output and
reported "the runtime rebuild did not report this pack". A new entry module needs its own
`if __name__ == "__main__": sys.exit(main(sys.argv[1:]))`.

## Debugging recipes that found the bugs above

- **Which library is the process really running**: `run-as com.nx.android grep -m1 libdm /proc/<pid>/maps` — the path plus the inode; compare against the file's mtime on disk. A same-path stale mapping is invisible anywhere else.
- **Two artifacts the same?** md5 them. Byte-identical rebuilds mean the compiler never saw your change (a cache, a reused stage, or a stale staged copy) — go find the cache, not the code.
- **Does the shipped binary contain the fix?** The runtime is stripped, but JNI entries stay in the dynamic symbol table: `llvm-nm -D` gives the address, `llvm-objdump -d --start-address/--stop-address` disassembles the function — a missing `bl` to the expected PLT entry is proof (mind that objdump separates fields with tabs, and that identical string literals merge across objects, so counting strings is not evidence).
- **Test a source change without rebuilding the APK**: `adb push` the changed file to `/sdcard`, then `adb shell "cat /sdcard/<file> | run-as com.nx.android sh -c 'cat > files/tool/<path>'"` — the next rebuild from the manage menu compiles it. Note the tool tree is re-extracted from the APK's payload on every app update, so the durable fix still needs an APK.
- **The game log only starts at the boot's stderr redirect**: anything logged before `dm_front_boot`'s `freopen` (the JNI adapter's own lines) goes to logcat, not `log.txt`.
