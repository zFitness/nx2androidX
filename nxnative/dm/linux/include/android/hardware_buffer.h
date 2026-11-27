// Linux stand-in for Android's <android/hardware_buffer.h>. The Vulkan backend's zero-copy memory (android/gfx_vk_core.c: AHardwareBuffer
// slabs imported as VkBuffers) compiles against it unchanged and is never taken on Linux -- there DM_LINUX makes zc_off() always set, so
// every pool is a plain copied one -- and the system <vulkan/vulkan_android.h> needs the type. The functions fail, so a path that reached
// one would stop instead of pretending. On the include path for Linux builds only (android/build.py): Android uses its own header.
#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct AHardwareBuffer AHardwareBuffer;
enum { AHARDWAREBUFFER_FORMAT_BLOB = 0x21 };
enum { AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN = 3, AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN = 0x30, AHARDWAREBUFFER_USAGE_GPU_DATA_BUFFER = 0x100 };
typedef struct AHardwareBuffer_Desc { uint32_t width, height, layers, format; uint64_t usage; uint32_t stride, rfu0; uint64_t rfu1; } AHardwareBuffer_Desc;
static inline int AHardwareBuffer_allocate(const AHardwareBuffer_Desc *desc, AHardwareBuffer **out) { (void)desc; *out = NULL; return -1; }
static inline void AHardwareBuffer_release(AHardwareBuffer *buf) { (void)buf; }
static inline int AHardwareBuffer_sendHandleToUnixSocket(const AHardwareBuffer *buf, int sock) { (void)buf; (void)sock; return -1; }
#ifdef __cplusplus
}
#endif
