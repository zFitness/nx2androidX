// SPEC §5 v2 preflight probe (Linux/Turnip): can VkDeviceMemory export dma-buf fds, is that
// memory CPU-cached when mmap'd, and is a MAP_FIXED mapping GPU↔CPU coherent without ioctls?
// Answers SPEC's three questions: (a) export support per memory type, (b) HOST_CACHED read/write
// speed vs malloc (the zc_uncached read_ns method), (c) GPU write → CPU read visibility latency
// through a MAP_FIXED mapping (and CPU write → GPU read, the zc_fill direction).
// Build (container): clang probe/dmabuf_probe.c -o /tmp/dmabuf_probe -lvulkan -O2
// Run:               /tmp/dmabuf_probe   — every phase prints and the probe continues where it can.
#include <vulkan/vulkan.h>
#include <linux/dma-buf.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <sched.h>
#include <errno.h>
#include <unistd.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>

static uint64_t now_ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec; }
static volatile uint64_t sink;
static uint64_t read_ns(const uint8_t *p, size_t n) {   // gfx_vk_core.c read_ns: sum of u64, best of 3
    uint64_t best = UINT64_MAX;
    for (int k = 0; k < 3; k++) {
        uint64_t s = 0; struct timespec t0, t1; clock_gettime(CLOCK_MONOTONIC, &t0);
        for (size_t i = 0; i < n / 8; i++) s += ((const uint64_t *)p)[i];
        clock_gettime(CLOCK_MONOTONIC, &t1); sink += s;
        uint64_t ns = (t1.tv_sec - t0.tv_sec) * 1000000000ull + (t1.tv_nsec - t0.tv_nsec);
        if (ns < best) best = ns;
    }
    return best ? best : 1;
}
static uint64_t write_ns(uint8_t *p, size_t n) {        // sequential + scattered store, best of 3
    uint64_t best = UINT64_MAX;
    for (int k = 0; k < 3; k++) {
        struct timespec t0, t1; clock_gettime(CLOCK_MONOTONIC, &t0);
        memset(p, (int)k + 0x11, n);
        for (size_t i = 0; i < n / 64; i++) p[i * 64] = (uint8_t)(i + k);
        clock_gettime(CLOCK_MONOTONIC, &t1);
        uint64_t ns = (t1.tv_sec - t0.tv_sec) * 1000000000ull + (t1.tv_nsec - t0.tv_nsec);
        if (ns < best) best = ns;
    }
    return best ? best : 1;
}
static double gb_s(uint64_t ns, size_t n) { return ns ? (double)n / (double)ns : 0; }
#define CHECK(x) do { if (!x) { printf("[FAIL] %s at %d\n", #x, __LINE__); return 1; } } while (0)

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    printf("== SPEC §5 v2 dma-buf preflight ==\n");
    // ---- instance + device (Vulkan 1.1: external-memory capabilities are core) ----
    VkApplicationInfo ai = { .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_1 };
    VkInstanceCreateInfo ici = { .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &ai };
    VkInstance inst; CHECK(vkCreateInstance(&ici, NULL, &inst) == VK_SUCCESS);
    VkPhysicalDevice pd[8]; uint32_t npd = 8; CHECK(vkEnumeratePhysicalDevices(inst, &npd, pd) == VK_SUCCESS && npd);
    VkPhysicalDeviceProperties pp; vkGetPhysicalDeviceProperties(pd[0], &pp);
    printf("device: %s (vendor %#x, api %u.%u)\n", pp.deviceName, pp.vendorID, pp.apiVersion >> 22, (pp.apiVersion >> 12) & 0xfff);
    // ---- device extensions we need ----
    uint32_t next = 0; vkEnumerateDeviceExtensionProperties(pd[0], NULL, &next, NULL);
    VkExtensionProperties *ext = malloc(sizeof *ext * next); vkEnumerateDeviceExtensionProperties(pd[0], NULL, &next, ext);
    int has_fd = 0, has_dmabuf = 0;
    for (uint32_t i = 0; i < next; i++) {
        if (!strcmp(ext[i].extensionName, "VK_KHR_external_memory_fd")) has_fd = 1;
        if (!strcmp(ext[i].extensionName, "VK_EXT_external_memory_dma_buf")) has_dmabuf = 1;
    }
    printf("(a0) extensions: external_memory_fd=%d dma_buf=%d\n", has_fd, has_dmabuf);
    const char *devext[] = { "VK_KHR_external_memory_fd", "VK_EXT_external_memory_dma_buf" };
    VkDeviceCreateInfo dci = { .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO };
    float prio = 1.0f; VkDeviceQueueCreateInfo q = { .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueCount = 1, .pQueuePriorities = &prio };
    dci.queueCreateInfoCount = 1; dci.pQueueCreateInfos = &q;
    dci.enabledExtensionCount = has_dmabuf ? 2 : (has_fd ? 1 : 0); dci.ppEnabledExtensionNames = devext;
    if (!dci.enabledExtensionCount) { printf("[FAIL] no external memory extensions\n"); return 1; }
    VkDevice dev; CHECK(vkCreateDevice(pd[0], &dci, NULL, &dev) == VK_SUCCESS);

    // ---- (a) which memory types export dma-buf fds ----
    VkPhysicalDeviceMemoryProperties mp; vkGetPhysicalDeviceMemoryProperties(pd[0], &mp);
    printf("(a1) memory types (%u):\n", mp.memoryTypeCount);
    printf("     idx flags heap  export  note\n");
    int exportable[64] = { 0 }, best_cached = -1, best_visible = -1;
    for (uint32_t t = 0; t < mp.memoryTypeCount; t++) {
        VkMemoryAllocateInfo mai = { .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = 1 << 20, .memoryTypeIndex = t };
        VkExportMemoryAllocateInfo ema = { .sType = VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO, .handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT };
        mai.pNext = &ema;
        VkDeviceMemory m;
        uint32_t fl = mp.memoryTypes[t].propertyFlags;
        if (!(fl & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT)) {   // turnip/kgsl: getFd on a device-only type SIGSEGVs in kgsl_bo_export_dmabuf — skip it (v2 only ever exports host-visible pools)
            printf("     %2u  %#05x  %2u     ?     device-only: getFd SKIPPED (turnip kgsl_bo_export_dmabuf SIGSEGVs here: driver bug, recorded)\n", t, fl, mp.memoryTypes[t].heapIndex);
            continue;
        }
        VkResult r = vkAllocateMemory(dev, &mai, NULL, &m);
        int ok = r == VK_SUCCESS;
        if (ok) { int fd = -1; VkMemoryGetFdInfoKHR gf = { .sType = VK_STRUCTURE_TYPE_MEMORY_GET_FD_INFO_KHR, .memory = m, .handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT };
            PFN_vkGetMemoryFdKHR getFd = (PFN_vkGetMemoryFdKHR)vkGetDeviceProcAddr(dev, "vkGetMemoryFdKHR");
            r = getFd(dev, &gf, &fd); if (r != VK_SUCCESS) ok = 0; else close(fd); vkFreeMemory(dev, m, NULL); }
        const char *note = ok ? (fl & VK_MEMORY_PROPERTY_HOST_CACHED_BIT ? "HOST_CACHED" : fl & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT ? "host-visible (uncached?)" : "device-only") : "no";
        printf("     %2u  %#05x  %2u     %s   %s\n", t, fl, mp.memoryTypes[t].heapIndex, ok ? "yes" : "NO", note);
        if (ok) { exportable[t] = 1; if (fl & VK_MEMORY_PROPERTY_HOST_CACHED_BIT && best_cached < 0) best_cached = (int)t;
                  if (fl & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT && best_visible < 0) best_visible = (int)t; }
    }
    if (!has_dmabuf) printf("[WARN] VK_EXT_external_memory_dma_buf absent: fd exports would be opaque/posix only — dma-buf mmap cannot work\n");
    if (best_cached < 0 && best_visible < 0) { printf("[FAIL] no exportable host-visible memory type → v2 stops here per SPEC\n"); return 1; }
    int pick = best_cached >= 0 ? best_cached : best_visible;
    printf("(a2) picked type %d (cached=%d) for phases b/c\n", pick, best_cached >= 0);

    // ---- (b) CPU speed of the exported memory's mmap vs malloc ----
    const size_t SZ = 8u << 20;
    VkMemoryAllocateInfo mai = { .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = SZ, .memoryTypeIndex = (uint32_t)pick };
    VkExportMemoryAllocateInfo ema = { .sType = VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO, .handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT };
    mai.pNext = &ema;
    VkDeviceMemory m; CHECK(vkAllocateMemory(dev, &mai, NULL, &m) == VK_SUCCESS);
    PFN_vkGetMemoryFdKHR getFd = (PFN_vkGetMemoryFdKHR)vkGetDeviceProcAddr(dev, "vkGetMemoryFdKHR");
    int fd = -1; VkMemoryGetFdInfoKHR gf = { .sType = VK_STRUCTURE_TYPE_MEMORY_GET_FD_INFO_KHR, .memory = m, .handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT };
    CHECK(getFd(dev, &gf, &fd) == VK_SUCCESS && fd >= 0);
    uint8_t *dm = mmap(NULL, SZ, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (dm == MAP_FAILED) { printf("[FAIL] mmap of the exported dma-buf fd failed: errno %d (%s); trying PROT_READ only\n", errno, strerror(errno));
        dm = mmap(NULL, SZ, PROT_READ, MAP_SHARED, fd, 0);
        if (dm == MAP_FAILED) { printf("[FAIL] PROT_READ mmap also failed: errno %d (%s) — the dma-buf is not CPU-mappable → v2 stops here per SPEC\n", errno, strerror(errno)); return 1; }
        printf("     PROT_READ mmap ok at %p (write tests skipped)\n", (void *)dm); }
    uint8_t *mm = malloc(SZ); CHECK(mm);
    uint64_t r_dm = read_ns(dm, SZ), r_mm = read_ns(mm, SZ);
    uint64_t w_dm = write_ns(dm, SZ), w_mm = write_ns(mm, SZ);
    printf("(b1) read : dma-buf mmap %.2f GB/s | malloc %.2f GB/s | ratio %.2f\n", gb_s(r_dm, SZ), gb_s(r_mm, SZ), (double)r_mm / r_dm);
    printf("(b2) write: dma-buf mmap %.2f GB/s | malloc %.2f GB/s | ratio %.2f\n", gb_s(w_dm, SZ), gb_s(w_mm, SZ), (double)w_mm / w_dm);
    printf("(b3) verdict: exportable memory is %s (>=60%% of malloc = cached; ~2 GB/s = uncached/write-combined, v1's RP5 precedent)\n",
           (double)r_mm / r_dm > 0.6 ? "HOST_CACHED in practice" : "effectively UNCACHED on CPU");

    // ---- (c) MAP_FIXED over a live mapping + GPU↔CPU coherence ----
    const size_t CZ = 4u << 20;
    VkMemoryAllocateInfo cmai = { .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = CZ, .memoryTypeIndex = (uint32_t)pick };
    cmai.pNext = &ema;
    VkDeviceMemory cm; CHECK(vkAllocateMemory(dev, &cmai, NULL, &cm) == VK_SUCCESS);
    int cfd = -1; VkMemoryGetFdInfoKHR cgf = { .sType = VK_STRUCTURE_TYPE_MEMORY_GET_FD_INFO_KHR, .memory = cm, .handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT };
    CHECK(getFd(dev, &cgf, &cfd) == VK_SUCCESS);
    // the game's pool region: an anonymous mapping the game has written, then the buffer mapped OVER it (zc_fill's MAP_FIXED step)
    printf("(c0) phase c: %zu bytes, type %d\n", CZ, pick);
    uint8_t *game = mmap(NULL, CZ, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (game == MAP_FAILED) { printf("[FAIL] anon mmap failed: errno %d (%s)\n", errno, strerror(errno)); return 1; }
    memset(game, 0x5A, CZ);
    CHECK(mmap(game, CZ, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_FIXED, cfd, 0) == game);
    printf("(c1) MAP_FIXED over a live anonymous mapping: ok at %p\n", (void *)game);
    VkQueue queue; vkGetDeviceQueue(dev, 0, 0, &queue);
    VkBufferCreateInfo bci = { .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = CZ, .usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT };
    VkBuffer buf, hostbuf;
    VkBindBufferMemoryInfo bm[2] = { { .sType = VK_STRUCTURE_TYPE_BIND_BUFFER_MEMORY_INFO, .buffer = 0 }, { .sType = VK_STRUCTURE_TYPE_BIND_BUFFER_MEMORY_INFO } };
    CHECK(vkCreateBuffer(dev, &bci, NULL, &buf) == VK_SUCCESS);
    bm[0].buffer = buf; bm[0].memory = cm; bm[0].memoryOffset = 0;
    VkMemoryAllocateInfo hmai = { .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = CZ, .memoryTypeIndex = (uint32_t)best_visible >= 0 ? (uint32_t)best_visible : (uint32_t)pick };
    VkMemoryPropertyFlags hflags; VkPhysicalDeviceMemoryProperties mp2; vkGetPhysicalDeviceMemoryProperties(pd[0], &mp2); hflags = mp2.memoryTypes[hmai.memoryTypeIndex].propertyFlags;
    VkDeviceMemory hm; CHECK(vkAllocateMemory(dev, &hmai, NULL, &hm) == VK_SUCCESS);
    CHECK(vkCreateBuffer(dev, &bci, NULL, &hostbuf) == VK_SUCCESS);
    bm[1].buffer = hostbuf; bm[1].memory = hm; bm[1].memoryOffset = 0;
    CHECK(vkBindBufferMemory2(dev, 2, bm) == VK_SUCCESS);
    void *hmap; CHECK(vkMapMemory(dev, hm, 0, CZ, 0, &hmap) == VK_SUCCESS);
    VkCommandPoolCreateInfo pci = { .sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT };
    VkCommandPool pool; CHECK(vkCreateCommandPool(dev, &pci, NULL, &pool) == VK_SUCCESS);
    VkCommandBufferAllocateInfo cbi = { .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .commandPool = pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1 };
    VkCommandBuffer cb; CHECK(vkAllocateCommandBuffers(dev, &cbi, &cb) == VK_SUCCESS);
    VkFenceCreateInfo fci = { .sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO };
    VkFence fence; CHECK(vkCreateFence(dev, &fci, NULL, &fence) == VK_SUCCESS);
    // GPU fill 0xA5 into [game] (the dma-buf memory), fence, then read the CPU mapping: visibility latency without any sync ioctl
    uint64_t vis_best = UINT64_MAX, vis_sum = 0; int vis_ok = 0, vis_n = 20;
    for (int it = 0; it < vis_n; it++) {
        uint8_t pat = (uint8_t)(0xA0 + it);
        uint32_t word = 0x01010101u * pat;
        VkCommandBufferBeginInfo bi = { .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT };
        CHECK(vkBeginCommandBuffer(cb, &bi) == VK_SUCCESS);
        vkCmdFillBuffer(cb, buf, 0, CZ, word);
        CHECK(vkEndCommandBuffer(cb) == VK_SUCCESS);
        CHECK(vkResetFences(dev, 1, &fence) == VK_SUCCESS);
        VkSubmitInfo si = { .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &cb };
        uint64_t t0 = now_ns();
        CHECK(vkQueueSubmit(queue, 1, &si, fence) == VK_SUCCESS);
        // spin the CPU mapping until the pattern is visible (no invalidate, no ioctl — raw mmap read)
        volatile uint8_t *p = (volatile uint8_t *)game; int seen = -1;
        for (uint64_t spin = 0; spin < 200000000ull; spin++) {   // bounded 200M reads (~1 s at 5 GB/s)
            if (p[0] == pat && p[CZ / 2] == pat && p[CZ - 1] == pat) { seen = (int)((now_ns() - t0) / 1000); break; }
            if ((spin & 0xFFFF) == 0) sched_yield();
        }
        uint64_t us = seen >= 0 ? (uint64_t)seen : (now_ns() - t0) / 1000;
        vis_sum += us; if ((uint64_t)us < vis_best) vis_best = us; if (seen >= 0) vis_ok++;
        if (it == 0 || it == vis_n - 1) printf("(c2) GPU fill → CPU MAP_FIXED read: %s in %llu us (it %d)\n", seen >= 0 ? "visible" : "NEVER VISIBLE", (unsigned long long)us, it);
        uint8_t ver[3] = { game[0], game[CZ / 2], game[CZ - 1] };
        (void)ver;
    }
    printf("(c3) visibility: %d/%d iterations saw the GPU write; mean %llu us, best %llu us (no sync ioctl used)\n",
           vis_ok, vis_n, (unsigned long long)(vis_sum / vis_n), (unsigned long long)vis_best);
    // try the dma-buf sync ioctl (what a non-coherent mapping would need)
    struct dma_buf_sync ds = { .flags = DMA_BUF_SYNC_START | DMA_BUF_SYNC_READ };
    int io = ioctl(fd, DMA_BUF_IOCTL_SYNC, &ds); ds.flags = DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ; ioctl(fd, DMA_BUF_IOCTL_SYNC, &ds);
    printf("(c4) DMA_BUF_IOCTL_SYNC: %s (errno %d) — %s\n", io == 0 ? "supported" : "not supported", io == 0 ? 0 : errno,
           io == 0 ? "invalidate path exists if ever needed" : "mmap is expected to be coherent as-is");
    // CPU write → GPU read (the zc_fill direction): write the mapping, GPU copies dma-buf buffer → host buffer, check the bytes
    memset(game, 0x3C, CZ);
    VkCommandBufferBeginInfo bi = { .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT };
    CHECK(vkBeginCommandBuffer(cb, &bi) == VK_SUCCESS);
    VkBufferCopy bc = { .size = CZ }; vkCmdCopyBuffer(cb, buf, hostbuf, 1, &bc);
    CHECK(vkEndCommandBuffer(cb) == VK_SUCCESS);
    CHECK(vkResetFences(dev, 1, &fence) == VK_SUCCESS);
    VkSubmitInfo si = { .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &cb };
    CHECK(vkQueueSubmit(queue, 1, &si, fence) == VK_SUCCESS);
    CHECK(vkWaitForFences(dev, 1, &fence, VK_TRUE, 1e9) == VK_SUCCESS);
    uint8_t *h = hmap; int bad = 0; for (size_t i = 0; i < CZ; i += 4096) if (h[i] != 0x3C) bad++;
    printf("(c5) CPU write → GPU copy → host read: %s (%d bad pages of %zu sampled)\n", bad ? "MISMATCH" : "coherent", bad, CZ / 4096);
    printf("== probe done ==\n");
    return 0;
}
