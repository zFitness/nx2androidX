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

// The player's settings: one int per key. The file lives in dm_menu_set_dir()'s folder (default:
// DM_ROOT), written through on every set; any unknown line (including over-4KB ones) is preserved
// via getline, and a failed read/write/close/rename leaves the original file untouched.
//
// The settings the render thread and the menu read every frame ("fps", "sr", "sharpness") are
// cached in cross-thread atomics: a get is served from the cache (loaded lazily on the first get,
// refreshed after each successful save, invalidated by dm_menu_set_dir / dm_menu_settings_reload),
// so the present-thread poller never opens the file. Each cached key has a fixed default and legal
// range (loaded and stored values are clamped to it); a get on a cached key ignores the passed def.
// A key not in the cache is cold: read from the file on each get.
//
// dm_menu_setting_set returns 0 when the file really holds the new value, -1 on any failure (the
// original is kept) — the menu must not show a change as saved when it returns -1.
int  dm_menu_setting_get(const char *key, int def);
int  dm_menu_setting_set(const char *key, int value);
void dm_menu_settings_reload(void);   // re-read settings.txt from disk on the next cached-key get

// Where settings.txt lives. Call once at front start-up; Android hands over its files folder
// (phase 2), Linux keeps the default.
void dm_menu_set_dir(const char *dir);
