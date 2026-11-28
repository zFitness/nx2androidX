// DM_OBSERVE=1: once a second, from the front thread (which runs whatever the guest is doing), the counters that say which link of a
// running game is moving. The guest's presents (QueuePresentTexture), the frames actually handed to the Vulkan present, and the movie's
// packets in, pictures out, decoders alive. A counter that stops growing while the others go on names the link that stopped -- judged from
// these numbers, not from a conditional log ([longframe] is relative to the recent mean and is written 8 frames late: its absence is not a
// stop). The counters are kept beside what they count (hle_nvn.c, gfx_vk_present.c, hle_movie.c), weak here: the null build has none.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

unsigned long dm_obs_qpt(void) __attribute__((weak));      // gfx/nvn/hle_nvn.c
unsigned long dm_obs_vk_pres(void) __attribute__((weak));  // android/gfx_vk_present.c
unsigned long dm_obs_mov_in(void) __attribute__((weak));   // host/hle_movie.c
unsigned long dm_obs_mov_pic(void) __attribute__((weak));  // host/hle_movie.c
int dm_obs_mov_dec(void) __attribute__((weak));            // host/hle_movie.c
int dm_obs_mov_closed(void) __attribute__((weak));         // host/hle_movie.c
unsigned long dm_obs_tex_w(void) __attribute__((weak));     // gfx/nvn/hle_nvn.c
uint64_t dm_input_samples(void) __attribute__((weak));      // host/hle_hid.c: the game's controller-sample counter
unsigned long dm_obs_hid_reads(void) __attribute__((weak));  // host/hle_hid.c: all npad state fills
unsigned long dm_obs_hid_reads_id(unsigned long) __attribute__((weak));   // per npad id: fills
unsigned long dm_obs_hid_buttons_id(unsigned long) __attribute__((weak));// per npad id: the buttons of the newest fill
unsigned long dm_obs_tex_fail(void) __attribute__((weak)); // gfx/nvn/hle_nvn.c

static int on = -1; static uint64_t t0, last;

static uint64_t ns_now(void) { struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts); return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec; }

void dm_observe_tick(void) {
    if (on < 0) {
        const char *e = getenv("DM_OBSERVE");
        on = e && *e ? 1 : 0;
        t0 = last = ns_now();
        if (on) fprintf(stderr, "[obs] once a second: qpt, vkpres, movie_in/pic/dec/closed, and tex_w/tex_fail = the movie layer's writes into its NVN texture ( successes / rejected)\n");
    }
    if (!on) return;
    uint64_t now = ns_now();
    if (now - last < 1000000000ull) return;
    last = now;
    unsigned long qpt = dm_obs_qpt ? dm_obs_qpt() : 0, vk = dm_obs_vk_pres ? dm_obs_vk_pres() : 0;
    unsigned long min_ = dm_obs_mov_in ? dm_obs_mov_in() : 0, mpic = dm_obs_mov_pic ? dm_obs_mov_pic() : 0;
    int mdec = dm_obs_mov_dec ? dm_obs_mov_dec() : 0, mclosed = dm_obs_mov_closed ? dm_obs_mov_closed() : 0;
    unsigned long tw = dm_obs_tex_w ? dm_obs_tex_w() : 0, tfail = dm_obs_tex_fail ? dm_obs_tex_fail() : 0;
    unsigned long samples = dm_input_samples ? (unsigned long)dm_input_samples() : 0;
    unsigned long hidr = dm_obs_hid_reads ? dm_obs_hid_reads() : 0;
    char hid[128] = "";
    if (dm_obs_hid_reads_id && dm_obs_hid_buttons_id) {
        size_t o = 0;
        for (unsigned id = 0; id < 8; id++) {
            unsigned long n = dm_obs_hid_reads_id(id);
            if (n) o += (size_t)snprintf(hid + o, sizeof hid - o, " %u:%#lx/%lu", id, dm_obs_hid_buttons_id(id), n);
        }
    }
    fprintf(stderr, "[obs] t=%7.1fs qpt=%-8lu vkpres=%-8lu movie_in=%-8lu movie_pic=%-8lu movie_dec=%d closed=%d tex_w=%-8lu tex_fail=%lu samples=%lu hid_reads=%lu hid[%s]\n",
            (double)(now - t0) / 1e9, qpt, vk, min_, mpic, mdec, mclosed, tw, tfail, samples, hidr, hid);
}
