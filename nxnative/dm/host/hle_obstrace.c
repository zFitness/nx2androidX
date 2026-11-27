// DM_OBSTRACE: the boot-comparison capture for the Mario vs Donkey Kong linux crash. The game's
// patches.py inserts observation gates on the failing allocation's call chain (the alloc call, its
// return, the object constructor, the heap-context lookup, CreateBlock); this host side logs the
// registers at each gate on whichever host runs, so the two logs diff line for line and the first
// differing value is the answer. Read-only: the gates pass the saved registers and run the original
// instruction.
#include "dm.h"
#include <stdlib.h>

static const char *const k_name[] = { "", "pre-alloc", "post-alloc", "ctor-entry", "pre-ctor-call", "heap-ctx-entry", "create-block-entry", "post-create-block" };

static void log_one(int id, const uint64_t *regs) {
    static int on = -1;
    if (on < 0) on = !!getenv("DM_OBSTRACE");
    if (!on) return;
    uint32_t thr_cur_handle(void);
    char b[192]; crash_addr_str(b, sizeof b, regs[30]);
    LOG("[obs] %s thr=%#x x0=%#llx x1=%#llx x2=%#llx x3=%#llx x4=%#llx lr=%s", k_name[id], thr_cur_handle(),
        (unsigned long long)regs[0], (unsigned long long)regs[1], (unsigned long long)regs[2],
        (unsigned long long)regs[3], (unsigned long long)regs[4], b);
}
static void o1(const uint64_t *r) { log_one(1, r); }
static void o2(const uint64_t *r) { log_one(2, r); }
static void o3(const uint64_t *r) { log_one(3, r); }
static void o4(const uint64_t *r) { log_one(4, r); }
static void o5(const uint64_t *r) { log_one(5, r); }
static void o6(const uint64_t *r) { log_one(6, r); }
static void o7(const uint64_t *r) { log_one(7, r); }

__attribute__((constructor)) static void obs_trace_install(void) {
    gate_obs_set(1, o1); gate_obs_set(2, o2); gate_obs_set(3, o3); gate_obs_set(4, o4);
    gate_obs_set(5, o5); gate_obs_set(6, o6); gate_obs_set(7, o7);
}
