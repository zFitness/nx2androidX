# cimgui — Dear ImGui for the in-game menu (overlay-menu, openspec/changes/imgui-overlay-menu)

C bindings for Dear ImGui, vendored so the engine's own UI code stays C. The C++
code is confined to this folder: the vendored core + backend below, plus one
hand-written shim (`dmui_impl_vulkan_shim.*`) that exposes the Vulkan backend
and the frame rendering to the engine's C module (`dm/linux/dmui.c`).

- ImGui: **v1.92.9** (ocornut/imgui, MIT, `imgui/LICENSE.txt`) — core files only;
  `imgui_demo.cpp` is deliberately not vendored.
- cimgui: **1.92.9** (cimgui/cimgui, MIT, `LICENSE`) — generated against
  ImGui v1.92.9 (`cimgui.h` / `cimgui.cpp`).
- Vulkan backend: `backends/imgui_impl_vulkan.*` from the same ImGui tag,
  compiled with `IMGUI_IMPL_VULKAN_NO_PROTOTYPES` (the host loads every Vulkan
  entry point itself; the backend gets them through
  `ImGui_ImplVulkan_LoadFunctions` with the loader taken from
  `android/gfx_vk_core.c`'s instance proc addr).

Updating: pick a cimgui tag, take the matching ocornut/imgui tag (cimgui's tag
pins the ImGui submodule), replace `cimgui.*`, `imgui/`, `backends/`, and
re-check the shim against the backend's header.

`dmui_impl_vulkan_shim.cpp` (not upstream) — C wrapper over the backend:
init with the host's device/queue/format (dynamic rendering or render pass),
submit locking callback (the host guards queue submits with one mutex the
backend cannot know about), font file loading, NewFrame/RenderDrawData,
shutdown. Kept to the smallest surface that `dmui.c` needs.
