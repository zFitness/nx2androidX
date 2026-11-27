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
// DM_VK_TESTCARD=<ms>: the present chain on its own, no guest started -- the window shows the
// test card (vk_testcard_step) a frame every <ms>. DM_VK_TESTCARD_SCRIPT=1 with it: the window is
// minimized, restored, resized and maximized on a timer, so those paths are checked without hands.
//
// Keyboard mapping (v1, no remapper yet): WASD = left stick, arrows = d-pad,
// J=A K=B U=X I=Y, Q=ZL E=ZR, 1=L 2=R, Return=Plus, Backspace=Minus.
// Real controllers: SDL3's gamepad API, standard layout → dm_pad_set_player.
#include "front.h"
#include "dm_input.h"
#include <SDL3/SDL.h>
// The Vulkan types the front names (VkInstance, VkSurfaceKHR, PFN_vkGetInstanceProcAddr): the system <vulkan/vulkan.h>, without a platform and
// without prototypes -- the loader's entry points come to the backend by pointer (dm_front_vk_gipa), nothing here calls Vulkan itself
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <SDL3/SDL_vulkan.h>
#include <stdatomic.h>
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

// ---- what the backend is handed from this thread -------------------------------------------
static SDL_Window *g_win;
static volatile int g_quit;
static PFN_vkGetInstanceProcAddr g_gipa;                  // SDL_Vulkan_GetVkGetInstanceProcAddr: the one loader, loaded here through SDL
static const char *const *g_sext; static Uint32 g_nsext;   // SDL_Vulkan_GetInstanceExtensions: what the video driver needs for a surface
static _Atomic uint64_t g_px;                              // SDL_GetWindowSizeInPixels, (width << 32) | height, re-read on every pass of the loop
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
    g_win = SDL_CreateWindow("nx2android", 1280, 720, SDL_WINDOW_VULKAN | SDL_WINDOW_RESIZABLE);
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
    fprintf(stderr, "[front] window up (1280x720, %s, %d x %d pixels, loader %s)\n", SDL_GetCurrentVideoDriver(), pw, ph, g_gipa ? "loaded through SDL" : "NOT LOADED");
    for (Uint32 i = 0; i < g_nsext; i++) fprintf(stderr, "[front]   instance extension %s\n", g_sext[i]);
    // DM_VK_TESTCARD=<ms>: the present chain on its own -- no guest, the window shows the test card from this loop
    const char *tc = getenv("DM_VK_TESTCARD"); int tc_ms = tc ? atoi(tc) : 0;
    const char *scr = getenv("DM_VK_TESTCARD_SCRIPT"); int script = tc && scr && atoi(scr) > 0;
    if (tc && (!vk_testcard_step || tc_ms <= 0)) { fprintf(stderr, "[RED] [front] DM_VK_TESTCARD wants this build's Vulkan backend and a frame period in ms\n"); tc = NULL; }
    uint64_t t0 = now_ns(); int script_i = 0;
    static const struct { double at; const char *what; } script_steps[] = {{6, "minimize"}, {12, "restore"}, {18, "resize to 800x500"}, {24, "maximize"}};

    pthread_t th;
    if (!tc && pthread_create(&th, NULL, guest_trampoline, &guest)) {
        fprintf(stderr, "[front] guest thread failed — headless fallback\n");
        guest();
        SDL_DestroyWindow(g_win); SDL_Quit();
        return;
    }
    if (tc) fprintf(stderr, "[front] test card: a frame every %d ms, no guest%s\n", tc_ms, script ? ", the window scripted (minimize, restore, resize, maximize)" : "");

    for (;;) {
        SDL_Event ev;
        while (SDL_PollEvent(&ev)) {
            switch (ev.type) {
            case SDL_EVENT_QUIT: g_quit = 1; break;
            case SDL_EVENT_WINDOW_CLOSE_REQUESTED: g_quit = 1; break;   // the title bar's close button
            case SDL_EVENT_WINDOW_MINIMIZED: case SDL_EVENT_WINDOW_RESTORED: case SDL_EVENT_WINDOW_RESIZED: case SDL_EVENT_WINDOW_MAXIMIZED:
                // a resize floods while the window is dragged: the multiples of 240 are enough in the log
                if (ev.window.type != SDL_EVENT_WINDOW_RESIZED || !(ev.window.data1 % 240))
                    fprintf(stderr, "[front] window event %u: %d x %d\n", (unsigned)(ev.window.type - SDL_EVENT_WINDOW_FIRST), (int)ev.window.data1, (int)ev.window.data2);
                break;
            case SDL_EVENT_KEY_DOWN: key_apply(ev.key.key, 1); break;
            case SDL_EVENT_KEY_UP: key_apply(ev.key.key, 0); break;
            case SDL_EVENT_GAMEPAD_ADDED: {
                for (int i = 0; i < MAX_PADS; i++) if (!g_pad[i]) {
                    g_pad[i] = SDL_OpenGamepad(ev.gdevice.which);
                    g_pad_player[i] = i;
                    if (g_pad[i]) { g_pad_mask |= 1u << i; pad_publish(i); }
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
            case SDL_EVENT_GAMEPAD_BUTTON_DOWN: case SDL_EVENT_GAMEPAD_BUTTON_UP:
            case SDL_EVENT_GAMEPAD_AXIS_MOTION: {
                for (int i = 0; i < MAX_PADS; i++) if (g_pad[i] && SDL_GetGamepadID(g_pad[i]) == ev.gdevice.which) { pad_publish(i); break; }
                break;
            }
            default: break;
            }
            if (g_quit) break;
        }
        if (g_quit) break;
        { int pw = 0, ph = 0; SDL_GetWindowSizeInPixels(g_win, &pw, &ph); atomic_store(&g_px, ((uint64_t)(uint32_t)pw << 32) | (uint32_t)ph); }   // what the swapchain is sized to
        if (dm_front_tick) dm_front_tick();   // the surface the Vulkan backend's present thread asked for, and the ones it is done with
        if (script) {
            double el = (double)(now_ns() - t0) / 1e9;
            while (script_i < (int)(sizeof script_steps / sizeof *script_steps) && el >= script_steps[script_i].at) {
                const char *what = script_steps[script_i].what;
                if (!strcmp(what, "minimize")) SDL_MinimizeWindow(g_win);
                else if (!strcmp(what, "restore")) SDL_RestoreWindow(g_win);
                else if (!strcmp(what, "resize to 800x500")) SDL_SetWindowSize(g_win, 800, 500);
                else SDL_MaximizeWindow(g_win);
                fprintf(stderr, "[front] %.1f s: script %s\n", el, what);
                script_i++;
            }
        }
        if (tc) vk_testcard_step(now_ns(), tc_ms);
        SDL_Delay(2);
    }
    fprintf(stderr, "[front] quit: exiting the process (guest thread included; v1 无优雅停机)\n");
    exit(0);
}
