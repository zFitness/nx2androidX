// The in-game menu's UI module (overlay-menu, openspec/changes/imgui-overlay-menu): Dear ImGui
// behind cimgui, driven by a declarative item table, drawn into the host's present command
// buffer after the game's picture. Android and ARM Linux share this module; the platform front
// ends feed it events and perform its actions.
//
// Threads (design D4): one ImGui context, owned by the thread that calls dmui_frame (the
// present thread). The front end's thread(s) only push events and poll — the queue below keeps
// the context single-owner. Platform actions (quit) travel back through dmui_poll_action: the
// menu never blocks on its drawing thread to run them.
//
// GPU lifecycle: dmui_vk_ensure lazily initializes the Vulkan backend (the font atlas' uploads
// go through the submit-lock callbacks the host hands over); dmui_vk_invalidate after a
// swapchain rebuild re-forms the backend's pipeline on the next frame. While the menu is
// closed dmui_wants_frame() is 0 and the host submits nothing for it.
#pragma once
#include <stdint.h>

// Semantic menu keys (the front ends' adapters map their own events onto these; the mapping to
// the UI library's keys lives inside dmui.c)
enum {
    DMUI_KEY_UP, DMUI_KEY_DOWN, DMUI_KEY_LEFT, DMUI_KEY_RIGHT,   // d-pad, arrows, stick past half travel
    DMUI_KEY_OK, DMUI_KEY_BACK,                                  // confirm; back (top level: close the menu)
    DMUI_KEY_TAB_PREV, DMUI_KEY_TAB_NEXT,                        // the shoulders (L1/ZL, R1/ZR)
    DMUI_KEY_START, DMUI_KEY_SELECT,                             // + / − (reserved)
};
enum { DMUI_ACT_QUIT = 1 };                                      // dmui_poll_action's actions

// Events (front thread; queued, consumed on the context thread at the next frame)
void dmui_input_key(int key, int down);          // keyboard-shaped
void dmui_input_pad(int key, int down);          // gamepad-shaped
void dmui_input_mouse(float x, float y);         // window pixels (scaled to the real display size)
void dmui_input_mouse_btn(int btn, int down);    // 0 = left
void dmui_input_wheel(float x, float y);

// Menu state (front thread)
int  dmui_open(void);                            // 1 while the menu is open (the game is held)
void dmui_toggle(void);
int  dmui_poll_action(void);                     // 0 none, DMUI_ACT_* (drains one)

// Rendering (the ImGui context's thread)
int  dmui_wants_frame(void);                     // the menu is open: the frame wants a UI pass
void dmui_frame(void *cmd, float w, float h);    // inside the host's begun rendering scope

// Vulkan backend lifecycle (the context's thread, from the present path). info's handles are
// the raw Vulkan objects as void *: instance / physical device / device / queue / pipeline
// cache / gipa loader, api_version, image_count, use_dynamic_rendering + color_format, or
// render_pass, submit_lock + submit_unlock (the host's queue mutex for the backend's own
// submits), font_file (a TTF; NULL keeps the built-in Latin one) and font_size_px.
typedef struct dmui_vk_info {
    void *instance, *physical_device, *device, *queue;
    uint32_t queue_family;
    void *pipeline_cache, *gipa;
    uint32_t api_version, image_count;
    int use_dynamic_rendering, color_format;
    void *render_pass;
    void (*submit_lock)(void), (*submit_unlock)(void);
    const char *font_file;
    float font_size_px;
} dmui_vk_info;
void dmui_vk_ensure(const dmui_vk_info *info);
void dmui_vk_invalidate(void);                   // the swapchain's format or size changed under us

// Where the font file lives (Linux: <root>/font/ui.ttf; Android hands over its assets copy in
// phase 2). Call before the first frame; the default reads DM_ROOT at first use.
void dmui_set_font(const char *path);
