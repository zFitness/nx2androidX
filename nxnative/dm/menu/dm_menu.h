// The pause menu's shared functionality (overlay-menu, openspec/changes/imgui-overlay-menu):
// what a menu does, apart from drawing — hold and release the game, quit, and the player's
// settings. Nothing here knows about ImGui, SDL or JNI: the UI module (dmui.c) and each
// platform's front end call this, and each platform keeps its own input and lifecycle.
//
// Settings are the player's settings.txt (KEY=VALUE lines, the app's existing format, so an
// old install's values survive the menu's rewrite). There is one store and no second runtime
// copy: gets read the file, sets rewrite it (tmp + rename). Phase 1 writes it next to the
// game's root (DM_ROOT); Android passes its files folder through dm_menu_set_dir when the
// same menu lands there.
#pragma once

// Hold or release the game while the menu is open: the guest clock freezes, the audio output
// and the movie decoders suspend — the app front end's hold_sync order (hle_movie, hle_audio,
// hle_os). Release runs the three in reverse.
void dm_menu_hold(int on);

// Quit to the launcher: the host's orderly stop (audio suspended, graphics drained, exit 0) —
// the same path the window's close button takes. Never blocks on the caller's own thread.
void dm_menu_quit(void);

// The player's settings: one int per key, missing or malformed reads as def (the hot-path "fps"
// key defaults to 0 at cache load — a custom def on it is ignored, the cache is authoritative).
// The file lives in dm_menu_set_dir()'s folder (default: DM_ROOT), written through on every set.
// unknown line (including over-4KB ones) is preserved via getline, and a failed read/write/
// close/rename leaves the original file untouched. The hot-path "fps" key is served from a
// cross-thread atomic cache (present-thread poller reads it every frame): loaded lazily on the
// first get, refreshed after each successful save, invalidated by dm_menu_settings_reload().
int  dm_menu_setting_get(const char *key, int def);
void dm_menu_setting_set(const char *key, int value);
void dm_menu_settings_reload(void);   // re-read settings.txt from disk on the next hot-key get

// Where settings.txt lives. Call once at front start-up; Android hands over its files folder
// (phase 2), Linux keeps the default.
void dm_menu_set_dir(const char *dir);
