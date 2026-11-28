// The engine's C wrapper over the vendored ImGui Vulkan backend (the one hand-written C++ file
// of the overlay-menu UI module; see third_party/cimgui/README.md). C++ stays in this folder:
// this file only translates the backend's C++ objects into plain values for dm/linux/dmui.c.
//
// Threading: init, NewFrame and RenderDrawData run on the thread that owns the ImGui context
// (the host's present thread). The backend's own queue submits (the font atlas' uploads) are
// routed through the host's submit-lock callbacks — the game's render threads submit on the
// same queue under one mutex the backend cannot know about.
#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct dmui_implvk_info {
    void *instance;         // VkInstance
    void *physical_device;  // VkPhysicalDevice
    void *device;           // VkDevice
    void *queue;            // VkQueue
    uint32_t queue_family;
    void *pipeline_cache;   // VkPipelineCache (NULL fine)
    void *gipa;             // PFN_vkGetInstanceProcAddr: the one loader the host resolved (gfx_vk_core.c)
    uint32_t api_version;   // the instance's VkApplicationInfo::apiVersion
    uint32_t image_count;   // swapchain image count (>= 2)
    int use_dynamic_rendering;  // 1: dynamic rendering with color_format below; 0: render_pass below
    int color_format;           // VkFormat of the swapchain (dynamic rendering)
    void *render_pass;          // VkRenderPass the menu renders inside (compat path)
    void (*submit_lock)(void);  // the host's queue mutex, for the backend's own submits
    void (*submit_unlock)(void);
    const char *font_file;      // a TTF for the menu's words (NULL: the built-in one, Latin only)
    float font_size_px;
} dmui_implvk_info;

int  dmui_implvk_init(const dmui_implvk_info *info);   // 1 = the backend is ready
void dmui_implvk_new_frame(float w, float h, float dt);
void dmui_implvk_render(void *cmd);                    // inside the host's begun rendering scope
void dmui_implvk_shutdown(void);

#ifdef __cplusplus
}
#endif
