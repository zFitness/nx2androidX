// The menu's UI frame: Dear ImGui (through cimgui) drawing the declarative item table. C on
// this side; the library's C++ and its Vulkan backend stay inside third_party/cimgui/ (the shim
// exposes exactly what the header needs). See dmui.h for the threading and lifecycle contract.
#include "dmui.h"
#include "dm_menu.h"
#define CIMGUI_DEFINE_ENUMS_AND_STRUCTS
#include "../third_party/cimgui/cimgui.h"
#include "../third_party/cimgui/dmui_impl_vulkan_shim.h"
#include <stdatomic.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

uint64_t now_ns(void);

// ---- state: the context lives where dmui_frame runs; events queue across the threads ----
static _Atomic int g_open, g_action, g_frame_wanted, g_flush;
static int g_ctx;                 // igCreateContext done (the context thread sets it; only it reads)
static int g_vk_ready, g_vk_format, g_vk_dynamic, g_vk_init_tried;
static int g_tab, g_tab_flip;     // the open tab; a switch this frame (focus goes to the first row)
static int g_zh = 1;              // the words: Chinese once the TTF loads (Latin-only default keeps English)
static char g_font[600];
static uint64_t g_last_ns;
static int g_drawn;               // set once the first non-empty DrawData is logged (real drawing evidence)

typedef struct { int type, a, b; float x, y; } ev;
enum { EV_KEY, EV_PAD, EV_MOUSE_POS, EV_MOUSE_BTN, EV_WHEEL };
#define EV_N 256
static ev g_ev[EV_N];
static unsigned g_ev_head, g_ev_tail;   // single producer at a time per source... several front threads may
                                        // push: the mutex keeps the ring whole
static pthread_mutex_t g_ev_mu = PTHREAD_MUTEX_INITIALIZER;

static void ev_push(int type, int a, int b, float x, float y) {
    pthread_mutex_lock(&g_ev_mu);
    unsigned next = (g_ev_head + 1) % EV_N;
    if (next != g_ev_tail) { g_ev[g_ev_head] = (ev){type, a, b, x, y}; g_ev_head = next; }
    pthread_mutex_unlock(&g_ev_mu);
}

void dmui_input_key(int key, int down)      { ev_push(EV_KEY, key, down, 0, 0); }
void dmui_input_pad(int key, int down)      { ev_push(EV_PAD, key, down, 0, 0); }
void dmui_input_mouse(float x, float y)     { ev_push(EV_MOUSE_POS, 0, 0, x, y); }
void dmui_input_mouse_btn(int btn, int down){ ev_push(EV_MOUSE_BTN, btn, down, 0, 0); }
void dmui_input_wheel(float x, float y)     { ev_push(EV_WHEEL, 0, 0, x, y); }

void dmui_set_font(const char *path) { snprintf(g_font, sizeof g_font, "%s", path ? path : ""); }

// ---- the item table (design D5): rows carry their words and their action; adding one is a line here ----
enum { IT_FPS, IT_RESUME, IT_QUIT, IT_N };
enum { TAB_GAME, TAB_SYSTEM, TAB_N };
static const struct { int tab; const char *zh, *en; } g_items[IT_N] = {
    {TAB_GAME,   "显示帧率",     "Show FPS"},
    {TAB_SYSTEM, "继续游戏",     "Resume"},
    {TAB_SYSTEM, "退出到启动器", "Quit to the launcher"},
};
static const char *const g_tab_zh[TAB_N] = {"游戏", "系统"}, *const g_tab_en[TAB_N] = {"Game", "System"};
#define L(i) (g_zh ? g_items[i].zh : g_items[i].en)
#define LT(t) (g_zh ? g_tab_zh[t] : g_tab_en[t])

int dmui_open(void)    { return atomic_load(&g_open); }
void dmui_toggle(void) {
    atomic_store(&g_open, !atomic_load(&g_open));
    // 每次开关边缘都标记一次输入冲刷：菜单关闭期间前端不转发键事件，某些按下的键
    // （比如手柄按住时被切走焦点）会永远收不到对应 keyup。冲刷在下一个会话的首帧
    // 消费掉，防止"再次打开后某个方向键持续按着"的幽灵连按。
    atomic_store(&g_flush, 1);
}
int dmui_wants_frame(void) { return atomic_load(&g_open); }

int dmui_poll_action(void) { int a = atomic_exchange(&g_action, 0); return a; }

// ---- context + backend (the context thread only) -----------------------------------------------
static dmui_vk_info g_vk_want; static int g_vk_want_new;
void dmui_vk_ensure(const dmui_vk_info *info) { g_vk_want = *info; g_vk_want_new = 1; }   // copy by value: the caller may pass a stack-allocated info
void dmui_vk_invalidate(void) { if (g_vk_ready) { dmui_implvk_shutdown(); g_vk_ready = 0; } }

static void ctx_ensure(void) {
    if (g_ctx) return;
    g_ctx = 1;   // set before creating anything below to prevent concurrent re-entry creating two contexts
    igCreateContext(NULL);
    ImGuiIO *io = igGetIO_Nil();
    io->ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard | ImGuiConfigFlags_NavEnableGamepad;
    io->IniFilename = NULL;   // no imgui.ini beside the game
    igStyleColorsDark(NULL);
    igGetStyle()->WindowRounding = 0.0f; igGetStyle()->FrameRounding = 0.0f; igGetStyle()->GrabRounding = 0.0f;
    const char *file = NULL;
    char path[700]; path[0] = 0;
    if (g_font[0]) {
        file = g_font;
    } else {
        const char *root = getenv("DM_ROOT");
        if (root && *root) { snprintf(path, sizeof path, "%s/font/ui.ttf", root); file = path; }
    }
    ImFont *f = NULL;
    if (file && *file) {
        // Missing font files must allow the built-in English fallback.
        ImFontConfig *cfg = ImFontConfig_ImFontConfig();
        cfg->Flags |= ImFontFlags_NoLoadError;
        f = ImFontAtlas_AddFontFromFileTTF(io->Fonts, file, 22.0f, cfg, NULL);
        ImFontConfig_destroy(cfg);
    }
    g_zh = f != NULL;   // without a CJK-capable font the menu keeps its English words
    fprintf(stderr, "[dmui] font: %s -> %s\n", (file && *file) ? file : "none",
            f ? "loaded" : "fallback (default Latin, English words)");
}

static void vk_ensure_frame(void) {
    if (!g_vk_want_new) return;
    g_vk_want_new = 0;
    const dmui_vk_info *w = &g_vk_want;
    int format = w->use_dynamic_rendering ? w->color_format : (int)(intptr_t)w->render_pass;
    if (g_vk_ready && format == g_vk_format && g_vk_dynamic == w->use_dynamic_rendering) return;
    if (g_vk_ready) dmui_implvk_shutdown();   // the swapchain's format changed under us: re-form the pipeline
    dmui_implvk_info ci = {};
    ci.instance = w->instance; ci.physical_device = w->physical_device; ci.device = w->device;
    ci.queue = w->queue; ci.queue_family = w->queue_family; ci.pipeline_cache = w->pipeline_cache;
    ci.gipa = w->gipa; ci.api_version = w->api_version; ci.image_count = w->image_count;
    ci.use_dynamic_rendering = w->use_dynamic_rendering; ci.color_format = w->color_format;
    ci.render_pass = w->render_pass;
    ci.submit_lock = w->submit_lock; ci.submit_unlock = w->submit_unlock;
    // the font: the atlas loaded it at ctx_ensure — the backend reads the atlas, not the file
    g_vk_ready = dmui_implvk_init(&ci) ? 1 : 0;
    g_vk_format = format; g_vk_dynamic = w->use_dynamic_rendering;
    fprintf(stderr, "[dmui] backend init: dynamic %d, format %d, image count %u -> %s\n", g_vk_dynamic, g_vk_format, ci.image_count, g_vk_ready ? "ready" : "FAILED");
    if (!g_vk_ready) fprintf(stderr, "[RED] [dmui] the Vulkan backend did not start (the menu stays dark)\n");
    g_vk_init_tried = 1;
}

// ---- the frame ----------------------------------------------------------------------------------
void dmui_frame(void *cmd, float w, float h) {
    ctx_ensure();
    vk_ensure_frame();
    if (!g_vk_ready) { atomic_store(&g_frame_wanted, 0); return; }
    static int said; if (!said++) fprintf(stderr, "[dmui] first frame %.0fx%.0f (the menu draws)\n", w, h);
    uint64_t now = now_ns();
    float dt = g_last_ns ? (float)((double)(now - g_last_ns) / 1e9) : 1.0f / 60.0f;
    g_last_ns = now;
    dmui_implvk_new_frame(w, h, dt);
    ImGuiIO *io = igGetIO_Nil();
    // 事件清空：重开会话时把 IO 里残留的按键/鼠标状态清掉。菜单关闭期间前端不转发
    // 键事件，按住不放的键可能永远收不到 keyup，若不冲刷会在重新打开后表现为幽灵连按。
    if (atomic_exchange(&g_flush, 0)) {
        ImGuiIO_ClearInputKeys(io);
        ImGuiIO_ClearInputMouse(io);
        fprintf(stderr, "[dmui] input state cleared (stale keys flushed)\n");
    }

    int esc = 0, back = 0, tab_prev = 0, tab_next = 0;
    for (;;) {   // drain the queue: the context thread is the only one touching the io
        pthread_mutex_lock(&g_ev_mu);
        if (g_ev_tail == g_ev_head) { pthread_mutex_unlock(&g_ev_mu); break; }
        ev e = g_ev[g_ev_tail]; g_ev_tail = (g_ev_tail + 1) % EV_N;
        pthread_mutex_unlock(&g_ev_mu);
        switch (e.type) {
        case EV_KEY:
            if (e.a == DMUI_KEY_BACK) { if (e.b) back = 1; break; }
            if (e.a == DMUI_KEY_TAB_PREV) { if (e.b) tab_prev = 1; break; }
            if (e.a == DMUI_KEY_TAB_NEXT) { if (e.b) tab_next = 1; break; }
            if (e.a >= DMUI_KEY_UP && e.a <= DMUI_KEY_OK)
                ImGuiIO_AddKeyEvent(io,
                    e.a == DMUI_KEY_UP ? ImGuiKey_UpArrow : e.a == DMUI_KEY_DOWN ? ImGuiKey_DownArrow
                  : e.a == DMUI_KEY_LEFT ? ImGuiKey_LeftArrow : e.a == DMUI_KEY_RIGHT ? ImGuiKey_RightArrow
                  : ImGuiKey_Enter, e.b != 0);
            break;
        case EV_PAD:
            if (e.a == DMUI_KEY_BACK) { if (e.b) back = 1; break; }   // 手柄 B 键与键盘 Esc/K 同语义：回到上一级/关闭
            if (e.a == DMUI_KEY_TAB_PREV) { if (e.b) tab_prev = 1; break; }
            if (e.a == DMUI_KEY_TAB_NEXT) { if (e.b) tab_next = 1; break; }
            if (e.a >= DMUI_KEY_UP && e.a <= DMUI_KEY_OK)
                ImGuiIO_AddKeyEvent(io,
                    e.a == DMUI_KEY_UP ? ImGuiKey_GamepadDpadUp : e.a == DMUI_KEY_DOWN ? ImGuiKey_GamepadDpadDown
                  : e.a == DMUI_KEY_LEFT ? ImGuiKey_GamepadDpadLeft : e.a == DMUI_KEY_RIGHT ? ImGuiKey_GamepadDpadRight
                  : ImGuiKey_GamepadFaceDown, e.b != 0);
            break;
        case EV_MOUSE_POS: ImGuiIO_AddMousePosEvent(io, e.x, e.y); break;
        case EV_MOUSE_BTN: ImGuiIO_AddMouseButtonEvent(io, e.a, e.b != 0); break;
        case EV_WHEEL: ImGuiIO_AddMouseWheelEvent(io, e.x, e.y); break;
        }
    }
    if (tab_prev) { g_tab = (g_tab + TAB_N - 1) % TAB_N; g_tab_flip = 1; }
    if (tab_next) { g_tab = (g_tab + 1) % TAB_N; g_tab_flip = 1; }

    igNewFrame();   // start the ImGui frame after all input events are queued

    // the dim, then the panel: the dim's window takes clicks outside the panel (it closes the menu)
    ImGuiWindowFlags dimf = ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoSavedSettings |
                            ImGuiWindowFlags_NoNav | ImGuiWindowFlags_NoBringToFrontOnFocus | ImGuiWindowFlags_NoBackground;
    igSetNextWindowPos((ImVec2){0, 0}, ImGuiCond_Always, (ImVec2){0, 0});
    igSetNextWindowSize((ImVec2){w, h}, ImGuiCond_Always);
    igBegin("##dim", NULL, dimf);
    ImDrawList_AddRectFilled(igGetWindowDrawList(), (ImVec2){0, 0}, (ImVec2){w, h}, ((ImU32)170u << 24), 0.0f, 0);
    if (igIsWindowHovered(ImGuiHoveredFlags_None) && igIsMouseClicked_Bool(ImGuiMouseButton_Left, false)) atomic_store(&g_open, 0);
    igEnd();

    float pw = w < h * 1.2f ? w * 0.86f : 560.0f, ph = 260.0f;
    if (pw > w * 0.94f) pw = w * 0.94f;
    ImGuiWindowFlags pf = ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoSavedSettings |
                          (ImGuiWindowFlags)4096 | ImGuiWindowFlags_NoBackground;
    igSetNextWindowPos((ImVec2){(w - pw) / 2, (h - ph) / 2}, ImGuiCond_Always, (ImVec2){0, 0});
    igSetNextWindowSize((ImVec2){pw, ph}, ImGuiCond_Always);
    igBegin("##menu", NULL, pf);
    ImVec2 wp = igGetWindowPos(); (void)wp;
    ImDrawList *dl = igGetWindowDrawList();
    ImDrawList_AddRectFilled(dl, (ImVec2){wp.x, wp.y}, (ImVec2){wp.x + pw, wp.y + ph}, ((ImU32)242u << 24 | 14u | 14u << 8 | 20u << 16), 10.0f, 0);
    igSetCursorScreenPos((ImVec2){wp.x + 16, wp.y + 14});

    for (int t = 0; t < TAB_N; t++) {   // the tabs: two buttons, the open one filled (the shoulders switch)
        if (t) igSameLine(0.0f, 10.0f);
        char lbl[64]; snprintf(lbl, sizeof lbl, "%s%s", LT(t), t == g_tab ? " ##t" : " ##t");
        (void)sizeof lbl;
        _Bool selected = (t == g_tab);   // cache the selection state at the start of this iteration
        if (selected) { igPushStyleColor_U32(ImGuiCol_Button, ((ImU32)255u << 24 | 255u | 60u << 8 | 142u << 16)); igPushStyleColor_U32(ImGuiCol_ButtonHovered, ((ImU32)255u << 24 | 255u | 60u << 8 | 142u << 16)); igPushStyleColor_U32(ImGuiCol_ButtonActive, ((ImU32)255u << 24 | 255u | 60u << 8 | 142u << 16)); }
        if (igButton(LT(t), (ImVec2){pw / TAB_N - 32.0f, 0.0f}) && t != g_tab) { g_tab = t; g_tab_flip = 1; }
        if (selected) igPopStyleColor(3);
    }
    igSeparator();
    if (g_tab_flip) { igSetKeyboardFocusHere(0); g_tab_flip = 0; }
    for (int i = 0; i < IT_N; i++) {
        if (g_items[i].tab != g_tab) continue;
        if (i == IT_FPS) {
            int v = dm_menu_setting_get("fps", 0);
            _Bool b = v != 0;
            if (igCheckbox(L(i), &b) && b != (v != 0)) dm_menu_setting_set("fps", b ? 1 : 0);   // writes through: the restart keeps it
        } else if (i == IT_RESUME) {
            if (igButton(L(i), (ImVec2){pw - 48.0f, 0.0f})) atomic_store(&g_open, 0);   // the front's poll of dmui_open releases the game
        } else if (i == IT_QUIT) {
            igPushStyleColor_U32(ImGuiCol_Text, ((ImU32)255u << 24 | 255u | 64u << 8 | 48u << 16));
            if (igButton(L(i), (ImVec2){pw - 48.0f, 0.0f})) atomic_store(&g_action, DMUI_ACT_QUIT);
            igPopStyleColor(1);
        }
    }
    igSetCursorPosY(igGetWindowHeight() - 34.0f);
    igTextUnformatted(g_zh ? "↑↓ 选择  Enter/空格 确认  Esc/B 关闭  L1/R1 切页  F8/Insert 开关"
                           : "Up/Down move  Enter/Space confirm  Esc/B close  L1/R1 tabs  F8/Insert toggle", NULL);
    igEnd();

    if ((esc || back) && !atomic_load(&g_action)) atomic_store(&g_open, 0);   // top level: back closes the menu
    igRender();
    {   // honest drawing evidence: the actual sizes of the first non-empty DrawData
        ImDrawData *dd = igGetDrawData();
        if (dd && dd->Valid && dd->TotalVtxCount > 0) {
            if (!g_drawn++) fprintf(stderr, "[dmui] draw data %d vertices, %d indices, over %d lists\n",
                dd->TotalVtxCount, dd->TotalIdxCount, dd->CmdLists.Size);
        }
    }
    dmui_implvk_render(cmd);
}
