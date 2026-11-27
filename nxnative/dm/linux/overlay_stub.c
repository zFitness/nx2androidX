// Linux stand-ins for the Android overlay theme loader (android/overlay_theme.c: the app's assets through AAssetManager, and the theme's PNG sprites).
// v1 draws the theme-less overlay -- the backend's own shapes and labels: dm_overlay_theme answers NULL -- and the overlay's font is the pack's own file
// when it has one (overlay/font/ui.bin, or font/ui.bin, beside the data: what the Android app ships as assets/font/ui.bin), else the Latin-1 one the
// backend has built in. On Linux builds only (android/build.py takes dm/linux/*.c).
#include "dm.h"
#include "overlay_layout.h"
#include "pixel_font.h"
#include "pixel_font_latin1.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

const uint8_t *dm_overlay_font(void) {
    static int tried; static const uint8_t *f; if (tried) return f;
    tried = 1;
    const char *root = getenv("DM_ROOT");
    static const char *const rel[] = {"overlay/font/ui.bin", "font/ui.bin"};
    for (int i = 0; i < 2 && root && *root && !f; i++) {
        char p[1024]; if (snprintf(p, sizeof p, "%s/%s", root, rel[i]) >= (int)sizeof p) continue;
        FILE *fp = fopen(p, "rb"); if (!fp) continue;
        if (fseek(fp, 0, SEEK_END)) { fclose(fp); continue; }
        long n = ftell(fp); rewind(fp);
        if (n >= 8) {
            uint8_t *b = malloc((size_t)n);
            if (b && fread(b, 1, (size_t)n, fp) == (size_t)n) { if (!memcmp(b, "NXPF", 4)) f = b; else free(b); } else free(b);
        }
        fclose(fp);
    }
    if (f) LOG("overlay font: the pack's own"); else LOG("overlay font: the built-in Latin-1 one (the pack has no font/ui.bin)");
    if (!f) f = PF_LATIN1;
    return f;
}
const ov_theme *dm_overlay_theme(int layout) { (void)layout; return NULL; }
void dm_overlay_theme_done(const ov_theme *t) { (void)t; }
