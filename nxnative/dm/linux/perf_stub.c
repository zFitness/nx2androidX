// Linux stand-ins for the Android performance hints (android/perf_android.c: the ADPF hint manager, the frame-cost report, the window's
// rate for the frame graph). Nothing to hint on a Wayland session; the frame graph reads dm_perf_period_ms, whose weak default is in
// android/gfx_vk_present.c. On Linux builds only (android/build.py takes dm/linux/*.c).
#include "dm.h"
#include <stdint.h>
#include <android/native_window.h>
void dm_perf_frame(double period) { (void)period; }
void dm_perf_window(ANativeWindow *w, double fps) { (void)w; (void)fps; }
void dm_perf_frame_cost(int64_t replay_ns, int64_t gpu_ns) { (void)replay_ns; (void)gpu_ns; }
