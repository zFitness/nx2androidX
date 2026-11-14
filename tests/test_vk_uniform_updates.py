"""Compare runtime deferred uniform reads with an ordered byte-copy oracle."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'nxnative/dm/android/gfx_vk_core.c'


class UniformUpdates(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'a host C compiler is required')
    def test_gpu_landing_orders_overlapping_copies(self):
        src = SOURCE.read_text(encoding='utf8')
        start = src.index('void vk_ubd_land(VkCommandBuffer cb)')
        fn = src[start:src.index('\n}', start) + 2]
        code = r'''
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
typedef uintptr_t VkBuffer, VkCommandBuffer, VkDeviceSize;
typedef struct { int type; void *next; int src, dst; } VkMemoryBarrier;
typedef struct { uint64_t srcOffset, dstOffset, size; } VkBufferCopy;
#define VK_STRUCTURE_TYPE_MEMORY_BARRIER 1
#define VK_ACCESS_TRANSFER_WRITE_BIT 2
#define VK_PIPELINE_STAGE_TRANSFER_BIT 4
#define VKLOG(...) ((void)0)
typedef struct { uint64_t lo, hi; VkBuffer sb; VkDeviceSize so; const uint8_t *p; } ubd_t;
typedef struct { uint64_t lo, hi, fence; const uint8_t *data; } ubd_infl_t;
static ubd_t g_ubd[512]; static int g_nubd, g_ninfl, g_capinfl;
static ubd_infl_t *g_infl; static uint64_t g_fence, g_ubd_landed, g_ubd_gen;
static unsigned char memory[2048], expected[2048], input[512][128];
static struct { const void *src; VkBufferCopy r; } pending[512];
static int np, barriers;
static void flush(void) { while (np) { --np; memcpy(memory+pending[np].r.dstOffset, pending[np].src, pending[np].r.size); } }
static void infl_prune(void) { g_ninfl=0; }
static void ubd_ix_rebuild(void) {}
static void sub_gpu_wrote(uint64_t a, uint64_t n) {}
static int vk_buf_at(uint64_t a, uint64_t n, VkBuffer *b, VkDeviceSize *o) { *b=1; *o=a; return a+n<=sizeof memory; }
static void vk_img_barrier_all(VkCommandBuffer cb) { flush(); }
static void vkCmdPipelineBarrier(VkCommandBuffer cb, int src, int dst, int flags, int n, const VkMemoryBarrier *b, int nb, void *bb, int ni, void *ib) {
    assert(src==4 && dst==4 && n==1 && b->src==2 && b->dst==2); barriers++; flush();
}
static void vkCmdCopyBuffer(VkCommandBuffer cb, VkBuffer src, VkBuffer dst, int n, const VkBufferCopy *r) {
    for (int i=0;i<np;i++) assert(r->dstOffset>=pending[i].r.dstOffset+pending[i].r.size || pending[i].r.dstOffset>=r->dstOffset+r->size);
    pending[np].src=(const unsigned char *)src+r->srcOffset; pending[np++].r=*r;
}
''' + fn + r'''
int main(void) {
    uint32_t seed=77;
    for (int trial=0;trial<1000;trial++) {
        memset(memory,0,sizeof memory); memset(expected,0,sizeof expected); barriers=0;
        g_nubd=trial==0 ? 0 : trial==1 ? 16 : 512;
        int count=g_nubd;
        for (int i=0;i<count;i++) {
            seed=seed*1664525u+1013904223u;
            unsigned off=trial==1 ? i*128 : seed%1920;
            unsigned n=trial==1 ? 128 : 1+(seed>>20)%128;
            memset(input[i],i%255+1,n); memcpy(expected+off,input[i],n);
            g_ubd[i]=(ubd_t){off,off+n,(uintptr_t)input[i],0,input[i]};
        }
        vk_ubd_land(0); assert(!np && !g_nubd); assert(!memcmp(memory,expected,sizeof memory));
        if (trial<2) assert(!barriers); else assert(barriers>0);
    }
    free(g_infl);
}
'''
        with tempfile.TemporaryDirectory(prefix='vk-landing-test-') as tmp:
            c = Path(tmp) / 'test.c'; exe = Path(tmp) / 'test'
            c.write_text(code, encoding='utf8')
            subprocess.run(['cc', '-std=c11', '-O2', str(c), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

    @unittest.skipUnless(shutil.which('cc'), 'a host C compiler is required')
    def test_shadow_range_invalidation(self):
        src=SOURCE.read_text(encoding='utf8')
        start=src.index('static void ubd_shadow_update(')
        fn=src[start:src.index('\n}',start)+2]
        code=r"""
#include <stdint.h>
#include <assert.h>
#include <string.h>
enum { UBD_SHADOW_CACHE=64 };
static struct { uint64_t a,n,gen; } g_ubd_cache[64];
"""+fn+r"""
int main(void) {
    uint32_t seed=71; uint64_t gen=1; unsigned char memory[4096]={0}, cached[64][64]={0};
    for(int trial=0;trial<10000;trial++) {
        seed=seed*1664525u+1013904223u; unsigned k=seed%64;
        unsigned a=(seed>>6)%4032,n=1+(seed>>20)%64;
        g_ubd_cache[k].a=a;g_ubd_cache[k].n=n;g_ubd_cache[k].gen=gen;
        memcpy(cached[k],memory+a,n);
        seed=seed*1664525u+1013904223u; a=seed%4032;n=1+(seed>>20)%64;
        ubd_shadow_update(a,n,gen); gen++;memset(memory+a,trial&255,n);
        for(k=0;k<64;k++) if(g_ubd_cache[k].gen==gen)
            assert(!memcmp(cached[k],memory+g_ubd_cache[k].a,g_ubd_cache[k].n));
        // Landing drops all cached generations; it must not resurrect old slots.
        if(trial%113==0) gen++;
    }
}
"""
        with tempfile.TemporaryDirectory(prefix='vk-shadow-test-') as tmp:
            c=Path(tmp)/'test.c';exe=Path(tmp)/'test';c.write_text(code)
            subprocess.run(['cc','-O2',str(c),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

    @unittest.skipUnless(shutil.which('cc'), 'a host C compiler is required')
    def test_overlapping_updates_and_overflow(self):
        src = SOURCE.read_text(encoding='utf8')
        index = src[src.index('static int32_t g_ubd_ix'):src.index(' uint64_t g_ubd_gen')]
        start = src.index('void vk_ubd_read(')
        read = src[start:src.index('\n}\n', start) + 3]
        code = r'''
#include <stdint.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
#define UBD_MAX 512
#define VKLOG(...) ((void)0)
typedef struct { uint64_t lo, hi; uintptr_t sb, so; const uint8_t *p; } ubd_t;
static ubd_t g_ubd[UBD_MAX]; static int g_nubd;
static struct {uint64_t lo, hi, fence; const uint8_t *data;} g_infl[8];
static int g_ninfl; static uint64_t g_ubd_racy;
static int vk_gpu_pending(uint64_t a, uint64_t n) {(void)a; (void)n; return 0;}
static uint64_t vk_fence_done(void) {return 1;}
''' + index + read + r'''
static uint8_t inflbytes[8][128], mem[2048], updates[512][128], got[2048], expected[2048];
static uint32_t seed=3721;
static unsigned rnd(void) {seed=seed*1664525u+1013904223u; return seed;}
int main(void) {
    for(int trial=0;trial<2000;trial++) {
        memset(mem, 0x5a, sizeof mem); memcpy(expected,mem,sizeof mem);
        g_ninfl=trial%9;
        for(int i=0;i<g_ninfl;i++) {
            unsigned off=64u*i, n=128;
            memset(updates[i],(int)(0xa0+i),n);
            g_infl[i].lo=(uintptr_t)mem+off; g_infl[i].hi=g_infl[i].lo+n;
            g_infl[i].fence=(uint64_t)(i%3); g_infl[i].data=inflbytes[i];
            memset(inflbytes[i],(int)(0xa0+i),n);
            if(g_infl[i].fence>1) memcpy(expected+off,inflbytes[i],n);
        }
        g_nubd=trial < 6 ? (int[]){0,1,63,64,65,512}[trial] : (int)(rnd()%513);
        for(int i=0;i<g_nubd;i++) {
            unsigned off=trial < 6 ? (unsigned)i*2 : rnd()%1920;
            unsigned n=trial < 6 ? 128 : 1+rnd()%128;
            for(unsigned j=0;j<n;j++) updates[i][j]=(uint8_t)rnd();
            g_ubd[i]=(ubd_t){(uintptr_t)mem+off,(uintptr_t)mem+off+n,0,0,updates[i]};
            memcpy(expected+off,updates[i],n);
        }
        ubd_ix_rebuild();
        vk_ubd_read((uintptr_t)mem,sizeof mem,got);
        assert(!memcmp(got,expected,sizeof mem));
        unsigned off=rnd()%1800,n=1+rnd()%248;
        vk_ubd_read((uintptr_t)mem+off,n,got);
        assert(!memcmp(got,expected+off,n));
    }
    puts("2000 ordered overlap cases passed, including 64/65/512 updates");
}
'''
        with tempfile.TemporaryDirectory(prefix='vk-uniform-test-') as tmp:
            c = Path(tmp) / 'test.c'; exe = Path(tmp) / 'test'
            c.write_text(code, encoding='utf8')
            subprocess.run(['cc', '-std=c11', '-O2', str(c), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    unittest.main()
