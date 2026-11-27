// DM_OBSTRACE: the boot-comparison capture for the Mario vs Donkey Kong linux crash. The game's
// patches.py inserts observation gates on the failing allocation's call chain; this host side logs the
// registers at each gate on whichever host runs, so the two logs diff line for line and the first
// differing value is the answer. Read-only: the gates pass the saved registers and run the original
// instruction.
//
// What the saved frame holds (entry.S _dm_gate): regs[0..30] = the guest's x0..x30 at the gate, with
// regs[30] = the gate block's own return point; regs[96] = NZCV; regs[100] / regs[101] = the guest's
// x29 / x30 as the trampoline saved them before anything was clobbered (regs[101] = the game's
// original caller LR); and the guest's sp at the gate = (uint8_t *)regs + 816.
#include "dm.h"
#include <stdlib.h>
#include <stdio.h>

static const char *const k_name[] = { "", "pre-alloc", "post-alloc", "ctor-entry", "pre-ctor-call", "heap-ctx-entry",
    "create-block-entry", "post-create-block", "pre-ctx-virtual", "", "", "", "query-entry", "post-query",
    "zero-path", "post-create-block-2", "post-first-call", "lookup-helper", "last-helper" };

static int obs_on(void) { static int on = -1; if (on < 0) on = !!getenv("DM_OBSTRACE"); return on; }

static void log_line(int id, const uint64_t *regs, const char *extra) {
    uint32_t thr_cur_handle(void);
    char b[192], olr[192], ofp[32];
    crash_addr_str(b, sizeof b, regs[30]);
    crash_addr_str(olr, sizeof olr, regs[101]);
    snprintf(ofp, sizeof ofp, "%#llx", (unsigned long long)regs[100]);
    LOG("[obs] %s thr=%#x x0=%#llx x1=%#llx x2=%#llx x3=%#llx x4=%#llx x8=%#llx lr=%s oLR=%s oFP=%s nzcv=%#llx%s%s",
        k_name[id], thr_cur_handle(), (unsigned long long)regs[0], (unsigned long long)regs[1], (unsigned long long)regs[2],
        (unsigned long long)regs[3], (unsigned long long)regs[4], (unsigned long long)regs[8], b, olr, ofp,
        (unsigned long long)regs[96], extra ? " " : "", extra ? extra : "");
}

static void log_one(int id, const uint64_t *regs) { if (obs_on()) log_line(id, regs, NULL); }

// The query's caller reads its result struct off its own frame: [sp+0x28] = the size, [sp+0x30] = the flag byte
static void o13(const uint64_t *regs) {
    if (!obs_on()) return;
    uint8_t *sp = (uint8_t *)regs + 816;
    char extra[160];
    snprintf(extra, sizeof extra, "ret.size=%#llx ret.flag=%u", (unsigned long long)*(uint64_t *)(sp + 0x28), (unsigned)*(sp + 0x30));
    log_line(13, regs, extra);
}

static void o1(const uint64_t *r) { log_one(1, r); }
static void o2(const uint64_t *r) { log_one(2, r); }
static void o3(const uint64_t *r) { log_one(3, r); }
static void o4(const uint64_t *r) { log_one(4, r); }
static void o5(const uint64_t *r) { log_one(5, r); }
static void o6(const uint64_t *r) { log_one(6, r); }
static void o7(const uint64_t *r) { log_one(7, r); }
static void o8(const uint64_t *r) { log_one(8, r); }
static void o12(const uint64_t *r) { log_one(12, r); }
static void o14(const uint64_t *r) { log_one(14, r); }
static void o15(const uint64_t *r) { log_one(15, r); }
static void o16(const uint64_t *r) { log_one(16, r); }
static void o17(const uint64_t *r) { log_one(17, r); }
static void o18(const uint64_t *r) { log_one(18, r); }

__attribute__((constructor)) static void obs_trace_install(void) {
    gate_obs_set(1, o1); gate_obs_set(2, o2); gate_obs_set(3, o3); gate_obs_set(4, o4);
    gate_obs_set(5, o5); gate_obs_set(6, o6); gate_obs_set(7, o7); gate_obs_set(8, o8);
    gate_obs_set(12, o12); gate_obs_set(13, o13); gate_obs_set(14, o14); gate_obs_set(15, o15); gate_obs_set(16, o16);
    gate_obs_set(17, o17); gate_obs_set(18, o18);
}
