// The Vulkan backend's C wrapper (see the header; third_party/cimgui/README.md for the layout).
#include "dmui_impl_vulkan_shim.h"
#include "imgui.h"
#include "backends/imgui_impl_vulkan.h"
#include <string.h>
#include <stdio.h>

static VkInstance g_inst;
static void (*g_slock)(void);
static void (*g_sunlock)(void);
static PFN_vkQueueSubmit g_real_submit;
static VkDevice g_dev;
static PFN_vkDeviceWaitIdle g_dev_wait_idle;

static PFN_vkVoidFunction vk_loader(const char *name, void *ud) {
    PFN_vkVoidFunction p = ((PFN_vkGetInstanceProcAddr)ud)(g_inst, name);   // device functions through the instance's too (legal, dispatch only)
    if (p && !strcmp(name, "vkQueueSubmit")) {   // the backend's own submits take the host's queue mutex (the game's render threads share the queue)
        g_real_submit = (PFN_vkQueueSubmit)p;
        return (PFN_vkVoidFunction)+[](VkQueue q, uint32_t n, const VkSubmitInfo *si, VkFence f) -> VkResult {
            if (g_slock) g_slock();
            VkResult r = g_real_submit ? g_real_submit(q, n, si, f) : VK_ERROR_INITIALIZATION_FAILED;
            if (g_sunlock) g_sunlock();
            return r;
        };
    }
    if (p && !strcmp(name, "vkDeviceWaitIdle")) g_dev_wait_idle = (PFN_vkDeviceWaitIdle)p;   // kept for a safe teardown
    return p;
}

extern "C" int dmui_implvk_init(const dmui_implvk_info *ci) {
    g_inst = (VkInstance)ci->instance;
    g_slock = ci->submit_lock;
    g_sunlock = ci->submit_unlock;
    if (!ImGui_ImplVulkan_LoadFunctions(ci->api_version, vk_loader, ci->gipa)) {
        fprintf(stderr, "[RED] [dmui] the Vulkan backend could not load its functions\n");
        return 0;
    }
    ImGui_ImplVulkan_InitInfo ii = {};
    ii.ApiVersion = ci->api_version;
    ii.Instance = (VkInstance)ci->instance;
    ii.PhysicalDevice = (VkPhysicalDevice)ci->physical_device;
    ii.Device = (VkDevice)ci->device;
    ii.QueueFamily = ci->queue_family;
    ii.Queue = (VkQueue)ci->queue;   // required: the backend asserts Queue != nullptr at Init
    ii.DescriptorPoolSize = 16;      // the backend makes its own pool (host makes none for it)
    ii.MinImageCount = 2;
    ii.ImageCount = ci->image_count ? ci->image_count : 3;
    ii.PipelineCache = (VkPipelineCache)ci->pipeline_cache;
    ii.UseDynamicRendering = ci->use_dynamic_rendering != 0;
    if (ii.UseDynamicRendering) {
        ii.PipelineInfoMain.PipelineRenderingCreateInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO_KHR;
        ii.PipelineInfoMain.PipelineRenderingCreateInfo.colorAttachmentCount = 1;
        ii.PipelineInfoMain.PipelineRenderingCreateInfo.pColorAttachmentFormats = (VkFormat *)&ci->color_format;
    } else {
        ii.PipelineInfoMain.RenderPass = (VkRenderPass)ci->render_pass;
    }
    ii.CheckVkResultFn = [](VkResult r) { if (r < 0) fprintf(stderr, "[RED] [dmui] Vulkan backend result %d\n", r); };
    return ImGui_ImplVulkan_Init(&ii) ? 1 : 0;
}

extern "C" void dmui_implvk_new_frame(float w, float h, float dt) {
    ImGui_ImplVulkan_NewFrame();
    ImGuiIO &io = ImGui::GetIO();
    io.DisplaySize = ImVec2(w, h);
    io.DeltaTime = dt > 0.001f && dt < 0.2f ? dt : 1.0f / 60.0f;
}

extern "C" void dmui_implvk_render(void *cmd) {
    ImGui_ImplVulkan_RenderDrawData(ImGui::GetDrawData(), (VkCommandBuffer)cmd);
}

extern "C" void dmui_implvk_shutdown(void) {
    ImGui_ImplVulkan_Shutdown();
}

// imgui_demo.cpp is not vendored (openspec overlay-menu D2): imgui's debug-tools hooks name these
// four demo windows, which nothing in the menu opens — the link still wants them.
namespace ImGui {
void ShowDemoWindow(bool *) {}
void ShowAboutWindow(bool *) {}
void ShowStyleEditor(ImGuiStyle *) {}
bool ShowStyleSelector(const char *) { return false; }
void ShowUserGuide() {}
}
