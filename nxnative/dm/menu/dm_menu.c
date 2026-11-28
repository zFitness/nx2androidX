// The pause menu's shared functionality (dm_menu.h). Host-level calls only — no ImGui, no
// SDL, no JNI, nothing platform-specific beyond what dm.h already abstracts.
#include "dm_menu.h"
#include "dm.h"          // dm_movie_hold, guest_clock_freeze_for, dm_host_shutdown
#include <stdio.h>

void dm_audio_suspend(int on);   // hle_audio.c (hle.h)

void dm_menu_hold(int on) {
    if (on) {   // hold_sync (front_android.c), the same order and the same release order
        dm_movie_hold(1);
        dm_audio_suspend(1);
        guest_clock_freeze_for(1, 1);
    } else {
        guest_clock_freeze_for(1, 0);
        dm_audio_suspend(0);
        dm_movie_hold(0);
    }
}

void dm_menu_quit(void) {
    dm_host_shutdown("the pause menu's Quit");
}
