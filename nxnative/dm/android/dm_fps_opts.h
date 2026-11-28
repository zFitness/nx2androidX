// The frame rate counter's options: the encoding contract shared by the backend that draws the
// counter (gfx_vk_present.c), the app's menu (overlay_layout.h) and the ImGui menu (menu/dmui.c)
// with its Linux front (linux/front_linux.c). One int packs the five settings.txt values
// (fps_rows, fps_pos, fps_colour, fps_outline, fps_size); dm_fps_opts() returns it, the backend
// unpacks it. Only the encoding lives here — the display names stay with each menu (overlay_layout.h
// for the app's, dmui.c for the ImGui one), so the ImGui menu does not inherit the old menu's geometry.
#pragma once
enum { FPSO_FPS = 1, FPSO_SOC = 2, FPSO_BAT = 4, FPSO_DRV = 8, FPSO_GRAPH = 16, FPSO_ALL = 31, FPSO_ROWS_DEFAULT = FPSO_FPS | FPSO_SOC | FPSO_BAT };   // fps_rows: the rows shown, a bit each (the driver row: the Vulkan driver in use; the graph: the frame times, one bar a frame); by default FPS, SOC and BAT, the counter before these options (the driver row and the graph would make it reach the - button or L and ZL on a 1920x1080 window)
enum { FPSO_TL, FPSO_TR, FPSO_BL, FPSO_BR, FPSO_POS_N };   // fps_pos: the corner (top left, top right, bottom left, bottom right)
enum { FPSO_WHITE, FPSO_YELLOW, FPSO_GREEN, FPSO_CYAN, FPSO_MAGENTA, FPSO_COLOUR_N };   // fps_colour: the text (a temperature too hot stays red)
enum { FPSO_BOX, FPSO_NONE, FPSO_THIN, FPSO_MEDIUM, FPSO_THICK, FPSO_OUTLINE_N };   // fps_outline: the dark block behind the rows; nothing; a black outline round each letter, 1, 2 or 3 font texels
enum { FPSO_SMALL, FPSO_NORMAL, FPSO_LARGE, FPSO_XL, FPSO_SIZE_N };   // fps_size: the letters' scale = base - 1, base, base + 1, 2 * base (base: 2.2% of the window's height / PF_CAP, at least 2)
#define FPSO_DEFAULT (FPSO_ROWS_DEFAULT | FPSO_TL << 5 | FPSO_WHITE << 7 | FPSO_BOX << 10 | FPSO_NORMAL << 13)
static inline int fpso_rows(int o) { return o & 31; }
static inline int fpso_pos(int o) { return o >> 5 & 3; }
static inline int fpso_colour(int o) { return o >> 7 & 7; }
static inline int fpso_outline(int o) { return o >> 10 & 7; }
static inline int fpso_size(int o) { return o >> 13 & 3; }
static inline int fpso_pack(int rows, int pos, int colour, int outline, int size) { return rows | pos << 5 | colour << 7 | outline << 10 | size << 13; }
static inline int fpso_scale(int base, int size) { return size == FPSO_SMALL ? (base > 1 ? base - 1 : 1) : size == FPSO_LARGE ? base + 1 : size == FPSO_XL ? 2 * base : base; }
