// The container's pad-state relay, reading RAW JOYSTICK events (SDL3 with a Wayland window loses gamepad button events in this
// environment; a GAMEPAD/JOYSTICK-only SDL context receives every one). Raw evdev button indexes of devtools/uinput_pad.c
// (the device's key codes ascending): 0 BTN_SOUTH 1 BTN_EAST 2 BTN_WEST 3 BTN_NORTH 4 BTN_TL 5 BTN_TR 6 BTN_TL2 7 BTN_TR2
// 8 BTN_SELECT 9 BTN_START 10 BTN_MODE 11/12 thumbs; axis indexes: 0 X 1 Y 2 RX 3 RY 4 LTRIGGER 5 RTRIGGER.
// State file (tmp+rename, 10 Hz): buttons=<hex> lx=<n> ly=<n> rx=<n> ry=<n>; bits: 1 A 2 B 4 X 8 Y 16 L 32 R 64 PLUS 128 MINUS
// 4096 ZL (LTRIGGER>10%) 8192 ZR; the sticks are SDL's raw values (up negative — the front flips Y). Build: gcc -O2 -lSDL3.
#include <SDL3/SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
    const char *out = argc > 1 ? argv[1] : "/opt/nx2a-data/dev/pad.state";
    if (!SDL_Init(SDL_INIT_JOYSTICK)) { fprintf(stderr, "pad_relay: SDL_Init: %s\n", SDL_GetError()); return 1; }
    SDL_Joystick *js[4] = {0}; int njs = 0;
    { int n = 0; SDL_JoystickID *ids = SDL_GetJoysticks(&n);
      for (int i = 0; i < n && njs < 4; i++) { SDL_Joystick *j = SDL_OpenJoystick(ids[i]); if (j) js[njs++] = j; }
      if (ids) SDL_free(ids); }
    fprintf(stderr, "pad_relay: %d joystick(s) opened, state → %s\n", njs, out);
    unsigned buttons = 0; int lx = 0, ly = 0, rx = 0, ry = 0, lt = 0, rt = 0;
    for (;;) {
        SDL_Event ev;
        while (SDL_PollEvent(&ev)) {
            if (ev.type == SDL_EVENT_JOYSTICK_ADDED) { SDL_Joystick *j = SDL_OpenJoystick(ev.jdevice.which); if (j && njs < 4) js[njs++] = j; }
            else if (ev.type == SDL_EVENT_JOYSTICK_REMOVED) { for (int i = 0; i < njs; i++) if (SDL_GetJoystickID(js[i]) == ev.jdevice.which) { SDL_CloseJoystick(js[i]); js[i] = js[--njs]; } }
            else if (ev.type == SDL_EVENT_JOYSTICK_BUTTON_DOWN || ev.type == SDL_EVENT_JOYSTICK_BUTTON_UP) {
                int on = ev.type == SDL_EVENT_JOYSTICK_BUTTON_DOWN, b = ev.jbutton.button;
                unsigned bit = b == 0 ? 1u : b == 1 ? 2u : b == 2 ? 4u : b == 3 ? 8u : b == 4 ? 16u : b == 5 ? 32u : b == 8 ? 64u : b == 9 ? 128u : 0u;
                buttons = on ? (buttons | bit) : (buttons & ~bit);
            } else if (ev.type == SDL_EVENT_JOYSTICK_AXIS_MOTION) {
                if (ev.jaxis.axis == 0) lx = ev.jaxis.value;
                else if (ev.jaxis.axis == 1) ly = ev.jaxis.value;
                else if (ev.jaxis.axis == 2) rx = ev.jaxis.value;
                else if (ev.jaxis.axis == 3) ry = ev.jaxis.value;
                else if (ev.jaxis.axis == 4) lt = ev.jaxis.value;
                else if (ev.jaxis.axis == 5) rt = ev.jaxis.value;
            }
        }
        unsigned mask = buttons | (unsigned)(lt > 3000 ? 4096u : 0u) | (unsigned)(rt > 3000 ? 8192u : 0u);
        char tmp[512]; snprintf(tmp, sizeof tmp, "%s.tmp", out);
        FILE *f = fopen(tmp, "w");
        if (f) { fprintf(f, "buttons=%x lx=%d ly=%d rx=%d ry=%d\n", mask, lx, ly, rx, ry); fclose(f); rename(tmp, out); }
        SDL_Delay(100);
    }
}
