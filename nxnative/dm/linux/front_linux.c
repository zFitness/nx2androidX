// Linux port: the host front end (dm/host/front.h's third implementation, beside the Mac's
// front_mac.m and the Android's front_android.c).
//
// Windowed (this file today): an SDL3 Wayland window, the guest on its own thread, the main
// thread pumping events into dm_input_set / dm_pad_set_player (dm/host/dm_input.h) — the same
// plain data the Mac's GameController path and the Android's front core produce. The window's
// Vulkan surface goes to the Vulkan backend's swapchain through dm_front_window (M2/M3).
//
// The window is this thread's (Wayland's display is): everything that touches it stays here, and
// the backend is handed plain values -- the loader's vkGetInstanceProcAddr, the instance
// extensions the video driver needs, the size in pixels, and the surface it asks for (served by
// dm_front_tick from the event loop; dm/android/gfx_vk_present.c has the other end).
//
// The game runs fullscreen: the window is created fullscreen and is never resized, maximized or
// dragged. DM_VK_TESTCARD=<ms> starts the present chain on its own, no guest -- the test card
// (vk_testcard_step), a frame every <ms>. DM_VK_TESTCARD_SCRIPT=1 with it: the window is minimized
// at 6 s, and the script waits for the compositor to bring it back (from outside: its task bar's
// entry), which is how the backgrounded-and-back path is checked without hands.
//
// Nothing is presented while the window is not seen -- minimized, hidden, or suspended by the
// compositor: the backend is handed a 0 x 0 window then, and the swapchain again once it is back.
// The window being closed ends the process through the host's orderly stop (dm_host_shutdown).
//
// Keyboard mapping (v1, no remapper yet): WASD = left stick, arrows = d-pad,
// J=A K=B U=X I=Y, Q=ZL E=ZR, 1=L 2=R, Return=Plus, Backspace=Minus.
// Real controllers: SDL3's gamepad API, standard layout → dm_pad_set_player.
#include "front.h"
#include "dm.h"          // dm_host_shutdown: the orderly stop the window's close goes through
#include "dm_input.h"
#include <SDL3/SDL.h>
// The Vulkan types the front names (VkInstance, VkSurfaceKHR, PFN_vkGetInstanceProcAddr): the system <vulkan/vulkan.h>, without a platform and
// without prototypes -- the loader's entry points come to the backend by pointer (dm_front_vk_gipa), nothing here calls Vulkan itself
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <SDL3/SDL_vulkan.h>
#include <stdatomic.h>
#include <sys/stat.h>
uint64_t now_ns(void);
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// gfx_vk_present（DM_LINUX）把窗口当 opaque 的 ANativeWindow 用：同一 opaque 类型对接
typedef struct SDL_Window ANativeWindow;
ANativeWindow *dm_front_window(void);
// The Vulkan backend's work on the window's thread (android/gfx_vk_present.c, DM_LINUX): the surface it asked for, and surfaces to destroy. Weak: the null-device build has none
__attribute__((weak)) void dm_front_tick(void);
__attribute__((weak)) int vk_testcard_step(uint64_t now_ns, int period_ms);
__attribute__((weak)) void dm_front_vk_window_thread(void);   // gfx_vk_present.c, DM_LINUX: this thread, registered before anything else runs
void dm_observe_tick(void);                              // linux/observe.c: the once-a-second counters, under DM_OBSERVE=1

// ---- what the backend is handed from this thread -------------------------------------------
static SDL_Window *g_win;
static volatile int g_quit;
static PFN_vkGetInstanceProcAddr g_gipa;                  // SDL_Vulkan_GetVkGetInstanceProcAddr: the one loader, loaded here through SDL
static const char *const *g_sext; static Uint32 g_nsext;   // SDL_Vulkan_GetInstanceExtensions: what the video driver needs for a surface
static _Atomic uint64_t g_px;                              // the window's size in pixels, (width << 32) | height, re-read on every pass of the loop -- 0 x 0 while the user cannot see it (px_publish)
static uint64_t g_resized_logged;                          // the last "window resized" line: a drag floods them
// Not seen by the user: minimized, hidden, or suspended by the compositor (SDL_WINDOW_OCCLUDED: xdg-shell's suspended state, which KWin sets
// for a minimized window and for one on a hidden desk). Nothing is presented then; the backend drops its swapchain and makes it again when a
// size returns. The flags are SDL's, kept from the compositor's configure events: minimized lasts until the compositor brings the window back
// and activates it -- SDL_RestoreWindow does nothing for a window that is only minimized (Wayland has no un-minimize request)
#define UNSEEN (SDL_WINDOW_MINIMIZED | SDL_WINDOW_HIDDEN | SDL_WINDOW_OCCLUDED)
static int unseen(void) { return (int)(SDL_GetWindowFlags(g_win) & UNSEEN); }
static void px_publish(void) {
    int pw = 0, ph = 0; SDL_GetWindowSizeInPixels(g_win, &pw, &ph);
    static int was; int why = unseen();
    atomic_store(&g_px, why ? 0 : ((uint64_t)(uint32_t)pw << 32) | (uint32_t)ph);
    if (why != was) { fprintf(stderr, "[front] %s (%d x %d pixels)\n", why ? "the window is not seen (minimized, hidden or occluded): presenting is paused" : "the window is seen again: presenting goes on", pw, ph); was = why; }
}
static const char *wev(unsigned t) {   // a window event's name, for the log
    switch (t) {
    case SDL_EVENT_WINDOW_SHOWN: return "shown"; case SDL_EVENT_WINDOW_HIDDEN: return "hidden"; case SDL_EVENT_WINDOW_EXPOSED: return "exposed";
    case SDL_EVENT_WINDOW_MINIMIZED: return "minimized"; case SDL_EVENT_WINDOW_MAXIMIZED: return "maximized"; case SDL_EVENT_WINDOW_RESTORED: return "restored";
    case SDL_EVENT_WINDOW_OCCLUDED: return "occluded"; case SDL_EVENT_WINDOW_CLOSE_REQUESTED: return "close requested";
    case SDL_EVENT_WINDOW_FOCUS_GAINED: return "focus gained"; case SDL_EVENT_WINDOW_FOCUS_LOST: return "focus lost";
    case SDL_EVENT_WINDOW_RESIZED: return "resized"; case SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED: return "pixel size changed"; default: return "other";
    }
}
void *dm_front_vk_gipa(void) { return (void *)g_gipa; }
int dm_front_vk_extensions(unsigned *n, const char *const **ext) { if (!g_sext) return 0; *n = g_nsext; *ext = g_sext; return 1; }
uint64_t dm_front_vk_px(void) { return atomic_load(&g_px); }

// ---- 键盘 → 玩家 1（dm_input_set）--------------------------------------------
static uint64_t g_kbd_btn;
static int32_t g_kbd_lx, g_kbd_ly;
static int k_up, k_down, k_left, k_right;
static void stick_recompute(void) {
    g_kbd_lx = (k_right - k_left) * DM_STICK_MAX;
    g_kbd_ly = (k_up - k_down) * DM_STICK_MAX;   // the host reads a positive y as up (hle_hid.c: ly > thresh is LUp)
}
static void key_apply(SDL_Keycode k, int down) {
    uint64_t b = g_kbd_btn;
    switch (k) {
    case SDLK_J: case SDLK_SPACE:      b = down ? b | DM_BTN_A : b & ~DM_BTN_A; break;
    case SDLK_K: case SDLK_LSHIFT:     b = down ? b | DM_BTN_B : b & ~DM_BTN_B; break;
    case SDLK_U:                       b = down ? b | DM_BTN_X : b & ~DM_BTN_X; break;
    case SDLK_I:                       b = down ? b | DM_BTN_Y : b & ~DM_BTN_Y; break;
    case SDLK_Q:                       b = down ? b | DM_BTN_ZL : b & ~DM_BTN_ZL; break;
    case SDLK_E:                       b = down ? b | DM_BTN_ZR : b & ~DM_BTN_ZR; break;
    case SDLK_1:                       b = down ? b | DM_BTN_L : b & ~DM_BTN_L; break;
    case SDLK_2:                       b = down ? b | DM_BTN_R : b & ~DM_BTN_R; break;
    case SDLK_RETURN: case SDLK_KP_ENTER: b = down ? b | DM_BTN_PLUS : b & ~DM_BTN_PLUS; break;
    case SDLK_BACKSPACE:               b = down ? b | DM_BTN_MINUS : b & ~DM_BTN_MINUS; break;
    case SDLK_UP:    k_up = down;    break;
    case SDLK_DOWN:  k_down = down;  break;
    case SDLK_LEFT:  k_left = down;  break;
    case SDLK_RIGHT: k_right = down; break;
    case SDLK_W:     k_up = down;    break;
    case SDLK_S:     k_down = down;  break;
    case SDLK_A:     k_left = down;  break;
    case SDLK_D:     k_right = down; break;
    default: return;
    }
    g_kbd_btn = b;
    stick_recompute();
    dm_input_set(g_kbd_btn, g_kbd_lx, g_kbd_ly, 0, 0);
}

// ---- 手柄 → dm_pad_set_player（标准布局）--------------------------------------
#define MAX_PADS 4
static SDL_Gamepad *g_pad[MAX_PADS];
static int g_pad_player[MAX_PADS];   // 0 = player 1
static uint32_t g_pad_mask;

static void pad_publish(int i) {
    SDL_Gamepad *p = g_pad[i];
    if (!p) { dm_pad_set_player(g_pad_player[i], 0, 0, 0, 0, 0); dm_pad_players(g_pad_mask); return; }
    uint64_t b = 0;
    if (SDL_GetGamepadButton(p, SDL_GAMEPAD_BUTTON_SOUTH))             b |= DM_BTN_A;
    if (SDL_GetGamepadButton(p, SDL_GAMEPAD_BUTTON_EAST))              b |= DM_BTN_B;
    if (SDL_GetGamepadButton(p, SDL_GAMEPAD_BUTTON_WEST))              b |= DM_BTN_X;
    if (SDL_GetGamepadButton(p, SDL_GAMEPAD_BUTTON_NORTH))             b |= DM_BTN_Y;
    if (SDL_GetGamepadButton(p, SDL_GAMEPAD_BUTTON_LEFT_SHOULDER))     b |= DM_BTN_L;
    if (SDL_GetGamepadButton(p, SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER))    b |= DM_BTN_R;
    if (SDL_GetGamepadButton(p, SDL_GAMEPAD_BUTTON_START))             b |= DM_BTN_PLUS;
    if (SDL_GetGamepadButton(p, SDL_GAMEPAD_BUTTON_BACK))              b |= DM_BTN_MINUS;
    if (SDL_GetGamepadButton(p, SDL_GAMEPAD_BUTTON_DPAD_LEFT))         b |= DM_BTN_LEFT;
    if (SDL_GetGamepadButton(p, SDL_GAMEPAD_BUTTON_DPAD_RIGHT))        b |= DM_BTN_RIGHT;
    if (SDL_GetGamepadButton(p, SDL_GAMEPAD_BUTTON_DPAD_UP))           b |= DM_BTN_UP;
    if (SDL_GetGamepadButton(p, SDL_GAMEPAD_BUTTON_DPAD_DOWN))         b |= DM_BTN_DOWN;
    // SDL3 reports an axis as an integer -32768..32767 already (the host's range is DM_STICK_MAX = 32767: no scaling, only the one
    // endpoint beyond it clamped) and a trigger as 0..32767. A thumbstick's up is negative there; the host reads a positive y as up
    int32_t ax[4];
    static const SDL_GamepadAxis A[4] = {SDL_GAMEPAD_AXIS_LEFTX, SDL_GAMEPAD_AXIS_LEFTY, SDL_GAMEPAD_AXIS_RIGHTX, SDL_GAMEPAD_AXIS_RIGHTY};
    for (int k = 0; k < 4; k++) { int32_t v = SDL_GetGamepadAxis(p, A[k]); ax[k] = v < -DM_STICK_MAX ? -DM_STICK_MAX : v; }
    int32_t zl = SDL_GetGamepadAxis(p, SDL_GAMEPAD_AXIS_LEFT_TRIGGER), zr = SDL_GetGamepadAxis(p, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER);
    if (zl > DM_STICK_MAX / 20) b |= DM_BTN_ZL;   // pressed past 5 % of its travel
    if (zr > DM_STICK_MAX / 20) b |= DM_BTN_ZR;
    dm_pad_set_player(g_pad_player[i], b, ax[0], -ax[1], ax[2], -ax[3]);
    dm_pad_players(g_pad_mask);
}
static void pad_publish_pub(void) { for (int i = 0; i < MAX_PADS; i++) if (g_pad[i]) pad_publish(i); }

// DM_PAD_CMD=<file>: the game's pad input as kernel-style lines appended to a file — "key <code> <v>" with the uinput button codes
// (304 A 305 B 306 X 307 Y 310 L 311 R 312 ZL 313 ZR 314 minus 315 plus) and "axis <code> <v>" (0 left-x 1 left-y 2 right-x
// 3 right-y, y up-negative like SDL). The host reads the appended lines each frame and drives player 0: no kernel input device,
// no compositor, no focus — the injection path works whatever holds the screen (the same shape as the Android touch injection)
static int padcmd_on = -1; static char padcmd_path[512];
static long long padcmd_mtime;
static unsigned padcmd_btn; static unsigned padcmd_logged; static int padcmd_ax[4];
static unsigned padcmd_bit(int code) {
    switch (code) {
    case 304: return DM_BTN_A; case 305: return DM_BTN_B; case 306: return DM_BTN_X; case 307: return DM_BTN_Y;
    case 310: return DM_BTN_L; case 311: return DM_BTN_R; case 312: return DM_BTN_ZL; case 313: return DM_BTN_ZR;
    case 314: return DM_BTN_MINUS; case 315: return DM_BTN_PLUS;
    default: return 0;
    }
}
static void padcmd_tick(void) {
    if (padcmd_on < 0) {
        const char *e = getenv("DM_PAD_CMD");
        if (!e || !*e) { padcmd_on = 0; return; }
        padcmd_on = 1;
        snprintf(padcmd_path, sizeof padcmd_path, "%s", e);
        fprintf(stderr, "[front] pad commands: %s (the file IS the current pad state; rewrite it to change the pad)\n", padcmd_path);
    }
    if (!padcmd_on) return;
    struct stat st;
    if (stat(padcmd_path, &st) != 0) return;
    if ((long long)st.st_mtime == padcmd_mtime) return;   // the state is unchanged
    padcmd_mtime = (long long)st.st_mtime;
    // The file is the pad's state snapshot, whole and current: re-read it from the top on every change and make the pad match
    FILE *f = fopen(padcmd_path, "r");
    if (!f) return;
    unsigned btn = 0; int ax[4] = {0};
    char line[128];
    while (fgets(line, sizeof line, f)) {
        char cmd[16] = {0}; int a = 0, v = 0;
        if (sscanf(line, "%15s %d %d", cmd, &a, &v) < 1) continue;
        if (!strcmp(cmd, "key")) {
            unsigned bit = padcmd_bit(a);
            if (bit) { if (v) btn |= bit; else btn &= ~bit; }   // the file replays press(1)/release(0): a 0 must CLEAR the bit
        } else if (!strcmp(cmd, "axis")) {
            if (a >= 0 && a < 4) ax[a] = v;
        }
    }
    fclose(f);
    padcmd_btn = btn;
    memcpy(padcmd_ax, ax, sizeof ax);
    if (padcmd_btn != padcmd_logged || memcmp(padcmd_ax, ax, sizeof ax) != 0) {
        padcmd_logged = padcmd_btn;
        fprintf(stderr, "[front] pad state: buttons %#x sticks %d %d %d %d\n", padcmd_btn, ax[0], -ax[1], ax[2], -ax[3]);
    }
    dm_pad_set_player(0, padcmd_btn, padcmd_ax[0], -padcmd_ax[1], padcmd_ax[2], -padcmd_ax[3]); dm_pad_players(1);
}

// DM_PAD_RELAY=1: player 0 is driven by the pad state the container's pad_relay helper writes (devtools/pad_relay.c). SDL3 with a
// Wayland window loses gamepad button events in this environment (the events stop right after init; a GAMEPAD-only SDL context
// receives every one), so the relay keeps such a context and writes the combined state; the front reads it here each frame.
static int pad_relay_on = -1; static char pad_relay_path[512]; static long long pad_relay_mtime; static int pad_relay_missing;
static void pad_relay_tick(void) {
    if (pad_relay_on < 0) {
        const char *e = getenv("DM_PAD_RELAY");
        pad_relay_on = e && *e ? 1 : 0;
        const char *ps = getenv("DM_PAD_STATE");
        snprintf(pad_relay_path, sizeof pad_relay_path, "%s", ps && *ps ? ps : "/opt/nx2a-data/dev/pad.state");
    }
    if (!pad_relay_on) return;
    struct stat st;
    if (stat(pad_relay_path, &st) != 0) { if (++pad_relay_missing == 60) fprintf(stderr, "[front] pad relay state %s is not there yet\n", pad_relay_path); return; }
    if ((long long)st.st_mtime == pad_relay_mtime) return;   // the relay rewrites it at 10 Hz: read on change only
    pad_relay_mtime = (long long)st.st_mtime;
    FILE *f = fopen(pad_relay_path, "r");
    if (!f) return;
    unsigned mask = 0; int lx = 0, ly = 0, rx = 0, ry = 0;
    int ok = fscanf(f, "buttons=%x lx=%d ly=%d rx=%d ry=%d", &mask, &lx, &ly, &rx, &ry) == 5;
    fclose(f);
    if (!ok) return;
    uint64_t b = 0;
    if (mask & 1u) b |= DM_BTN_A;      if (mask & 2u) b |= DM_BTN_B;
    if (mask & 4u) b |= DM_BTN_X;      if (mask & 8u) b |= DM_BTN_Y;
    if (mask & 16u) b |= DM_BTN_L;     if (mask & 32u) b |= DM_BTN_R;
    if (mask & 64u) b |= DM_BTN_PLUS;  if (mask & 128u) b |= DM_BTN_MINUS;
    if (mask & 4096u) b |= DM_BTN_ZL;  if (mask & 8192u) b |= DM_BTN_ZR;
    dm_pad_set_player(0, b, lx, -ly, rx, -ry);   // the relay's Y is SDL's (up negative); the host reads a positive y as up
    dm_pad_players(1);
}

// ---- front.h 契约 --------------------------------------------------------------
static void *guest_trampoline(void *guest) { void (**fn)(void) = guest; (*fn)(); return NULL; }

ANativeWindow *dm_front_window(void) { return g_win; }
void *front_metal_layer(void) { return NULL; }   // Vulkan 线不用 Metal 层
int front_screen_max_fps(void) { return 60; }
void front_screen_match(int fps) { (void)fps; }
int front_text_input(const char *title, const char *sub, const char *guide,
                     const char *initial, int max_chars, char *out, int out_cap) {
    (void)title; (void)sub; (void)guide; (void)initial; (void)max_chars; (void)out; (void)out_cap;
    fprintf(stderr, "[front] text input requested (SDL dialog 未接): %s\n", title ? title : "");
    return -1;
}

void front_run(void (*guest)(void)) {
    if (!SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMEPAD)) {
        fprintf(stderr, "[front] SDL_Init failed: %s — headless fallback\n", SDL_GetError());
        guest();
        return;
    }
    // The game runs fullscreen: one window over the whole output (Wayland fullscreen; the compositor sizes it). There is no resize and no
    // maximize in this product: the window is not made resizable, and the script below only ever minimizes it and waits for the compositor
    // to bring it back
    g_win = SDL_CreateWindow("nx2android", 1280, 720, SDL_WINDOW_VULKAN | SDL_WINDOW_FULLSCREEN);
    if (!g_win) {
        fprintf(stderr, "[front] window failed: %s — headless fallback\n", SDL_GetError());
        guest();
        return;
    }
    // The loader SDL makes the surface with is the backend's too: its vkGetInstanceProcAddr is handed over (dm_front_vk_gipa), and the
    // instance extensions are the video driver's -- both read here, on the thread that owns the window
    if (!SDL_Vulkan_LoadLibrary(NULL)) fprintf(stderr, "[RED] [front] SDL_Vulkan_LoadLibrary failed: %s\n", SDL_GetError());
    else g_gipa = (PFN_vkGetInstanceProcAddr)SDL_Vulkan_GetVkGetInstanceProcAddr();
    g_sext = g_gipa ? SDL_Vulkan_GetInstanceExtensions(&g_nsext) : NULL;
    if (!g_sext) g_nsext = 0;
    int pw = 0, ph = 0; SDL_GetWindowSizeInPixels(g_win, &pw, &ph); atomic_store(&g_px, ((uint64_t)(uint32_t)pw << 32) | (uint32_t)ph);
    fprintf(stderr, "[front] window up (fullscreen, %s, %d x %d pixels, loader %s)\n", SDL_GetCurrentVideoDriver(), pw, ph,
            g_gipa ? "loaded through SDL" : "NOT LOADED");
    for (Uint32 i = 0; i < g_nsext; i++) fprintf(stderr, "[front]   instance extension %s\n", g_sext[i]);
    if (dm_front_vk_window_thread) dm_front_vk_window_thread();   // this thread owns the window: said before the guest starts, whose present
                                                                  // thread -- and the surface handshake with it -- both come out of that
    // DM_VK_TESTCARD=<ms>: the present chain on its own -- no guest, the window shows the test card from this loop
    const char *tc = getenv("DM_VK_TESTCARD"); int tc_ms = tc ? atoi(tc) : 0;
    const char *scr = getenv("DM_VK_TESTCARD_SCRIPT"); int script = tc && scr && atoi(scr) > 0;
    if (tc && (!vk_testcard_step || tc_ms <= 0)) { fprintf(stderr, "[RED] [front] DM_VK_TESTCARD wants this build's Vulkan backend and a frame period in ms\n"); tc = NULL; }
    uint64_t t0 = now_ns();
    // DM_VK_TESTCARD_SCRIPT=1 (with the card): the window is put through what a player does with it, each step once the one before has settled --
    // minimized at 6 s; brought back by the compositor, which only the compositor can do (its task bar's entry, tapped from outside this
    // process), and waited for here; then 3 s on made 800x500, 4 s on maximized, 4 s on taken off maximized. The log names each step
    enum { SC_MINIMIZE, SC_WAIT_RESTORE, SC_DONE } sc = script ? SC_MINIMIZE : SC_DONE;
    uint64_t sc_since = t0;

    pthread_t th;
    if (!tc && pthread_create(&th, NULL, guest_trampoline, &guest)) {
        fprintf(stderr, "[front] guest thread failed — headless fallback\n");
        guest();
        SDL_DestroyWindow(g_win); SDL_Quit();
        return;
    }
    if (tc) fprintf(stderr, "[front] test card: a frame every %d ms, no guest%s\n", tc_ms,
                    script ? "; the window scripted: minimized at 6 s, brought back by the compositor, waited for" : "");

    for (;;) {
        SDL_Event ev;
        while (SDL_PollEvent(&ev)) {
            switch (ev.type) {
            case SDL_EVENT_QUIT: g_quit = 1; break;
            case SDL_EVENT_WINDOW_CLOSE_REQUESTED: g_quit = 1; break;   // the title bar's close button
            case SDL_EVENT_WINDOW_SHOWN: case SDL_EVENT_WINDOW_HIDDEN: case SDL_EVENT_WINDOW_EXPOSED: case SDL_EVENT_WINDOW_MINIMIZED: case SDL_EVENT_WINDOW_MAXIMIZED:
            case SDL_EVENT_WINDOW_RESTORED: case SDL_EVENT_WINDOW_OCCLUDED: case SDL_EVENT_WINDOW_FOCUS_GAINED: case SDL_EVENT_WINDOW_FOCUS_LOST: case SDL_EVENT_WINDOW_RESIZED:
                // a resize floods while the window is dragged: one line in 200 ms is enough then
                if (ev.window.type != SDL_EVENT_WINDOW_RESIZED || now_ns() - g_resized_logged > 200000000ull) {
                    if (ev.window.type == SDL_EVENT_WINDOW_RESIZED) g_resized_logged = now_ns();
                    fprintf(stderr, "[front] window %s: %d x %d%s\n", wev(ev.window.type), (int)ev.window.data1, (int)ev.window.data2, unseen() ? " (not seen)" : "");
                }
                break;
            case SDL_EVENT_KEY_DOWN: fprintf(stderr, "[front] key down %d\n", (int)ev.key.key); key_apply(ev.key.key, 1); break;
            case SDL_EVENT_KEY_UP: key_apply(ev.key.key, 0); break;
            case SDL_EVENT_GAMEPAD_ADDED: {
                for (int i = 0; i < MAX_PADS; i++) if (!g_pad[i]) {
                    g_pad[i] = SDL_OpenGamepad(ev.gdevice.which);
                    g_pad_player[i] = i;
                    if (g_pad[i]) { g_pad_mask |= 1u << i; pad_publish(i);
                        fprintf(stderr, "[front] gamepad %d: %s\n", ev.gdevice.which, SDL_GetGamepadName(g_pad[i])); }
                    break;
                }
                break;
            }
            case SDL_EVENT_GAMEPAD_REMOVED: {
                for (int i = 0; i < MAX_PADS; i++) if (g_pad[i] && SDL_GetGamepadID(g_pad[i]) == ev.gdevice.which) {
                    SDL_CloseGamepad(g_pad[i]); g_pad[i] = NULL;
                    g_pad_mask &= ~(1u << i); pad_publish(i);
                    break;
                }
                break;
            }
            case SDL_EVENT_GAMEPAD_BUTTON_DOWN: fprintf(stderr, "[front] pad button %d down\n", (int)ev.gbutton.button); pad_publish_pub();
            case SDL_EVENT_GAMEPAD_BUTTON_UP: fprintf(stderr, "[front] pad button %d up\n", (int)ev.gbutton.button); pad_publish_pub();
            case SDL_EVENT_GAMEPAD_AXIS_MOTION: {
                for (int i = 0; i < MAX_PADS; i++) if (g_pad[i] && SDL_GetGamepadID(g_pad[i]) == ev.gdevice.which) { pad_publish(i); break; }
                break;
            }
            default: break;
            }
            if (g_quit) break;
        }
        if (g_quit) break;
        px_publish();   // what the swapchain is sized to, or nothing while the window is not seen
        dm_observe_tick();
        padcmd_tick();   // the pad relay (SDL gamepad context) is unused in this environment: its state never varies here
        if (dm_front_tick) dm_front_tick();   // the surface the Vulkan backend's present thread asked for, and the ones it is done with
        if (sc != SC_DONE) {
            double el = (double)(now_ns() - t0) / 1e9, here = (double)(now_ns() - sc_since) / 1e9;
            const char *did = NULL;
            if (sc == SC_MINIMIZE && el >= 6) { SDL_MinimizeWindow(g_win); did = "minimized (the bringing back is the compositor's)"; sc = SC_WAIT_RESTORE; }
            else if (sc == SC_WAIT_RESTORE && here >= 60) { fprintf(stderr, "[RED] [front] %.1f s: the window was not brought back in 60 s: the rest of the script is dropped\n", el); sc = SC_DONE; }
            else if (sc == SC_WAIT_RESTORE && !unseen() && here >= 1) { did = "seen again: the compositor brought the window back"; sc = SC_DONE; }
            if (did) { fprintf(stderr, "[front] %.1f s: script %s\n", el, did); sc_since = now_ns(); }
        }
        if (tc) vk_testcard_step(now_ns(), tc_ms);
        SDL_Delay(2);
    }
    // The window was closed (its close button, or SDL's quit): the host's orderly stop, the one SIGTERM gets -- audio suspended, the graphics
    // drained, _exit(0)
    dm_host_shutdown("the window closed");
}
