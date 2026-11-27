// Linux port: the host front end (dm/host/front.h's third implementation, beside the Mac's
// front_mac.m and the Android's front_android.c).
//
// Headless (this file today): the guest runs on the calling thread, like the Android dmhost
// executable under adb shell — no window, no input, no text entry. It is the build the
// launcher's tools use (build.py --gfx null: the game's own Oodle decoder) and the first
// shape that compiles and links on a glibc system.
//
// The windowed form (SDL3: a window, its Vulkan surface, keyboard and controllers, ALSA
// audio) grows in this folder: the data root comes from the pack's folder as on Android
// (cwd + DM_ROOT), main.c calls front_run(guest_main), and the input a windowed front
// feeds in through dm_input_set / dm_pad_set_player (dm/host/dm_input.h), the same plain
// data the Mac's GameController path and the Android's front core produce.
#include "front.h"

void front_run(void (*guest)(void)) { guest(); }
void *front_metal_layer(void) { return NULL; }
int front_screen_max_fps(void) { return 0; }
void front_screen_match(int fps) { (void)fps; }
// The game's software keyboard (hle_swkbd.c): with no window nothing is shown, and -1 is
// the contract's "no window" answer — the caller logs and carries on.
int front_text_input(const char *title, const char *sub, const char *guide,
                     const char *initial, int max_chars, char *out, int out_cap) {
    (void)title; (void)sub; (void)guide; (void)initial; (void)max_chars; (void)out; (void)out_cap;
    return -1;
}
