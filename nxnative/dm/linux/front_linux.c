// Linux port: the host front end (dm/host/front.h's third implementation, beside the Mac's
// front_mac.m and the Android's front_android.c).
//
// Windowed (this file today): an SDL3 Wayland window, the guest on its own thread, the main
// thread pumping events into dm_input_set / dm_pad_set_player (dm/host/dm_input.h) — the same
// plain data the Mac's GameController path and the Android's front core produce. The window's
// Vulkan surface goes to the Vulkan backend's swapchain through dm_front_window (M2/M3).
//
// Keyboard mapping (v1, no remapper yet): WASD = left stick, arrows = d-pad,
// J=A K=B U=X I=Y, Q=ZL E=ZR, 1=L 2=R, Return=Plus, Backspace=Minus.
// Real controllers: SDL3's gamepad API, standard layout → dm_pad_set_player.
#include "front.h"
#include "dm_input.h"
#include <SDL3/SDL.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// gfx_vk_present（DM_LINUX）把窗口当 opaque 的 ANativeWindow 用：同一 opaque 类型对接
typedef struct SDL_Window ANativeWindow;
ANativeWindow *dm_front_window(void);
// The Vulkan backend's work on the window's thread: the surface (android/gfx_vk_present.c, DM_LINUX). Weak: the null-device build has none
__attribute__((weak)) void dm_front_tick(void);

static SDL_Window *g_win;
static volatile int g_quit;

// ---- 键盘 → 玩家 1（dm_input_set）--------------------------------------------
static uint64_t g_kbd_btn;
static int32_t g_kbd_lx, g_kbd_ly;
static int k_up, k_down, k_left, k_right;
static void stick_recompute(void) {
    g_kbd_lx = (k_right - k_left) * DM_STICK_MAX;
    g_kbd_ly = (k_down - k_up) * DM_STICK_MAX;
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
    if (!p) { dm_pad_set_player(g_pad_player[i], 0, 0, 0, 0); dm_pad_players(g_pad_mask); return; }
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
    float lx = SDL_GetGamepadAxis(p, SDL_GAMEPAD_AXIS_LEFTX);
    float ly = SDL_GetGamepadAxis(p, SDL_GAMEPAD_AXIS_LEFTY);
    float rx = SDL_GetGamepadAxis(p, SDL_GAMEPAD_AXIS_RIGHTX);
    float ry = SDL_GetGamepadAxis(p, SDL_GAMEPAD_AXIS_RIGHTY);
    float zl = SDL_GetGamepadAxis(p, SDL_GAMEPAD_AXIS_LEFT_TRIGGER);
    float zr = SDL_GetGamepadAxis(p, SDL_GAMEPAD_AXIS_RIGHT_TRIGGER);
    if (zl > 0.05f) b |= DM_BTN_ZL;
    if (zr > 0.05f) b |= DM_BTN_ZR;
    dm_pad_set_player(g_pad_player[i], b,
                      (int32_t)(lx * DM_STICK_MAX), (int32_t)(ly * DM_STICK_MAX),
                      (int32_t)(rx * DM_STICK_MAX), (int32_t)(ry * DM_STICK_MAX));
    dm_pad_players(g_pad_mask);
}

// ---- front.h 契约 --------------------------------------------------------------
static void *guest_trampoline(void *guest) { void (**fn)(void) = guest; (*fn)(); return NULL; }

void *dm_front_window(void) { return g_win; }
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
    // The Vulkan loader SDL makes the surface with: the same libvulkan the backend's own pointers come from
    if (!SDL_Vulkan_LoadLibrary(NULL)) fprintf(stderr, "[front] SDL_Vulkan_LoadLibrary failed: %s (the backend loads libvulkan itself)\n", SDL_GetError());
    fprintf(stderr, "[front] window up (1280x720, %s)\n", SDL_GetCurrentVideoDriver());

    pthread_t th;
    if (pthread_create(&th, NULL, guest_trampoline, &guest)) {
        fprintf(stderr, "[front] guest thread failed — headless fallback\n");
        guest();
        SDL_DestroyWindow(g_win); SDL_Quit();
        return;
    }

    for (;;) {
        SDL_Event ev;
        while (SDL_PollEvent(&ev)) {
            switch (ev.type) {
            case SDL_EVENT_QUIT: g_quit = 1; break;
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
        if (dm_front_tick) dm_front_tick();   // the surface the Vulkan backend's present thread asked for
        SDL_Delay(4);
    }
    fprintf(stderr, "[front] quit: exiting the process (guest thread included; v1 无优雅停机)\n");
    exit(0);
}
