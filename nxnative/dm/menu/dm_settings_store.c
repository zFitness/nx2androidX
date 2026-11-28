// The pause menu's settings storage (menu/dm_menu.h contract): the player's settings.txt in
// KEY=VALUE lines — the app's existing format, so an old install's values survive the menu's
// rewrite. One store, no second runtime copy of unknown lines.
//
// Safety rules:
//  * reads use getline(): lines of any length survive the rewrite, unknown keys are carried
//    over verbatim, so no fixed-size buffer can silently truncate the file;
//  * writes go to settings.txt.new, then rename() over the original — a failure at any step
//    (fopen / read / fwrite / flush / close / rename) leaves the original untouched;
//  * an existing file that cannot be read (anything other than ENOENT) is never overwritten.
//
// Caching / cross-thread policy: the settings the render thread and the menu read every frame
// live in a small table (g_sets) of C11 _Atomic ints, so a reader never opens the file or takes
// the lock. Each entry carries its default and its legal range; a loaded or stored value is
// clamped to the range. Writers hold g_set_mu; a value is published to its atomic only after the
// file really holds it. A cache is populated lazily on the first get, refreshed after every
// successful save, and invalidated by dm_menu_set_dir() / dm_menu_settings_reload() (an external
// edit to settings.txt takes effect then). A key not in the table is a cold key: read from the
// file on each get, written through on each set, never cached.
#include "dm_menu.h"
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char g_dir[512];   // the settings file's folder; DM_ROOT until dm_menu_set_dir says otherwise
static pthread_mutex_t g_set_mu = PTHREAD_MUTEX_INITIALIZER;   // serializes loads, saves and cache updates

// One hot setting: its settings.txt key, the value when the key is missing or malformed, the legal
// range (loaded and stored values are clamped to it), and the cross-thread cache.
typedef struct {
    const char *key;
    int def, lo, hi;
    _Atomic int cache;    // the thread-safe current value
    _Atomic int valid;    // cache holds the file's (clamped) value
} dm_set_t;

static dm_set_t g_sets[] = {
    { "fps",         0, 0, 1,   0, 0 },   // the frame-rate counter's master switch
    { "sr",          0, 0, 1,   0, 0 },   // super resolution (SGSR 1.0 in the present pass)
    { "sharpness",   0, 0, 100, 0, 0 },   // its sharpness, percent (the menu steps it by 25)
    // the counter's options (dm_fps_opts.h's FPSO_* encoding; the defaults match FPSO_DEFAULT's parts)
    { "fps_rows",    7, 0, 31,  0, 0 },   // the rows shown, a bit each (FPSO_ROWS_DEFAULT = FPS|SOC|BAT)
    { "fps_pos",     0, 0, 3,   0, 0 },   // the corner (FPSO_TL .. FPSO_BR)
    { "fps_colour",  0, 0, 4,   0, 0 },   // the text colour (FPSO_WHITE .. FPSO_MAGENTA)
    { "fps_outline", 0, 0, 4,   0, 0 },   // the block / outline (FPSO_BOX .. FPSO_THICK)
    { "fps_size",    1, 0, 3,   0, 0 },   // the letters' scale (FPSO_NORMAL by default)
};
#define N_SETS (sizeof g_sets / sizeof *g_sets)

static dm_set_t *set_find(const char *key) {
    for (size_t i = 0; i < N_SETS; i++) if (!strcmp(g_sets[i].key, key)) return &g_sets[i];
    return NULL;
}

static int clampi(int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }

void dm_menu_set_dir(const char *dir) {
    pthread_mutex_lock(&g_set_mu);
    snprintf(g_dir, sizeof g_dir, "%s", dir ? dir : "");
    for (size_t i = 0; i < N_SETS; i++) atomic_store(&g_sets[i].valid, 0);   // the new folder's file is read fresh
    pthread_mutex_unlock(&g_set_mu);
}

static void settings_path(char *out, int cap) {
    const char *dir = g_dir[0] ? g_dir : getenv("DM_ROOT");
    if (!dir || !*dir) dir = ".";
    snprintf(out, (size_t)cap, "%s/settings.txt", dir);
}

// growable append; returns 0 when out of memory
static int buf_append(char **buf, size_t *cap, size_t *len, const char *s, size_t slen) {
    if (*len + slen + 1 > *cap) {
        size_t ncap = *cap ? *cap * 2 : 512;
        while (ncap < *len + slen + 1) ncap *= 2;
        char *nb = realloc(*buf, ncap);
        if (!nb) return 0;
        *buf = nb;
        *cap = ncap;
    }
    memcpy(*buf + *len, s, slen);
    *len += slen;
    (*buf)[*len] = 0;
    return 1;
}

// line matches "key=..." at line start (matching the app's parser: keys sit flush left)
static int line_is_key(const char *line, ssize_t ll, const char *key, size_t klen) {
    return ll > (ssize_t)klen && strncmp(line, key, klen) == 0 && line[klen] == '=';
}

// the int after "key=", sscanf("%d") semantics: leading blanks skipped, at least one digit required
// (a malformed or empty value reads as def, not as 0)
static int parse_value(const char *s, int def) {
    while (*s == ' ' || *s == '\t') s++;
    char *end;
    long v = strtol(s, &end, 10);
    return end == s ? def : (int)v;
}

static int read_key_from_file(const char *key, int def) {
    char p[600];
    settings_path(p, (int)sizeof p);
    FILE *f = fopen(p, "r");
    if (!f) return def;
    char *line = NULL;
    size_t linecap = 0;
    ssize_t ll;
    size_t klen = strlen(key);
    int got = def;
    while ((ll = getline(&line, &linecap, f)) != -1) {
        if (line_is_key(line, ll, key, klen)) {
            got = parse_value(line + klen + 1, def);
            break;
        }
    }
    int err = ferror(f) != 0;
    free(line);
    if (fclose(f) != 0) err = 1;
    return err ? def : got;
}

// Loads (or reloads) one entry's cache from the file, clamped to its range: called lazily by the
// first get, after every successful save, and on dm_menu_settings_reload() / dm_menu_set_dir().
static void set_load_locked(dm_set_t *s) {
    int v = clampi(read_key_from_file(s->key, s->def), s->lo, s->hi);
    atomic_store(&s->cache, v);
    atomic_store(&s->valid, 1);
}

void dm_menu_settings_reload(void) {
    pthread_mutex_lock(&g_set_mu);
    for (size_t i = 0; i < N_SETS; i++) atomic_store(&g_sets[i].valid, 0);   // the next get re-reads the file
    pthread_mutex_unlock(&g_set_mu);
}

int dm_menu_setting_get(const char *key, int def) {
    dm_set_t *s = set_find(key);
    if (!s) return read_key_from_file(key, def);   // a cold key: read the file directly
    if (atomic_load(&s->valid)) return atomic_load(&s->cache);
    pthread_mutex_lock(&g_set_mu);
    if (!atomic_load(&s->valid)) set_load_locked(s);
    pthread_mutex_unlock(&g_set_mu);
    return atomic_load(&s->cache);
}

// Returns 0 when the file really holds the new value, -1 when it does not (the original is kept and
// the menu must not show the change as saved).
int dm_menu_setting_set(const char *key, int value) {
    dm_set_t *s = set_find(key);
    if (s) value = clampi(value, s->lo, s->hi);   // a stored value is always in range
    char p[600], tmp[640];
    settings_path(p, (int)sizeof p);
    if (snprintf(tmp, sizeof tmp, "%s.new", p) >= (int)sizeof tmp) return -1;
    size_t klen = strlen(key);
    char newline[96];
    int nl = snprintf(newline, sizeof newline, "%s=%d\n", key, value);
    if (nl < 0 || (size_t)nl >= sizeof newline) {
        fprintf(stderr, "[RED] [menu] settings key too long: %s\n", key);
        return -1;
    }

    pthread_mutex_lock(&g_set_mu);
    // Read the whole file into a growable buffer, copying every line verbatim (unknown keys,
    // lines longer than any fixed buffer) and swapping this key's line in.
    char *body = NULL;
    size_t bcap = 0, blen = 0;
    int replaced = 0, keep = 1;
    FILE *f = fopen(p, "r");
    if (f) {
        char *line = NULL;
        size_t linecap = 0;
        ssize_t ll;
        while ((ll = getline(&line, &linecap, f)) != -1) {
            if (!replaced && line_is_key(line, ll, key, klen)) {
                replaced = 1;
                if (!buf_append(&body, &bcap, &blen, newline, (size_t)nl)) { keep = 0; break; }
            } else if (!buf_append(&body, &bcap, &blen, line, (size_t)ll)) {
                keep = 0;
                break;
            }
        }
        int rerr = ferror(f) != 0;
        free(line);
        if (fclose(f) != 0) rerr = 1;
        if (rerr) keep = 0;
    } else if (errno != ENOENT) {   // an existing file we cannot read is never overwritten
        keep = 0;
    }
    if (!keep) {
        fprintf(stderr, "[RED] [menu] cannot read %s: refusing to overwrite it\n", p);
    }
    if (keep && !replaced) {   // new key: keep every existing byte, then append one clean line
        if (body && blen && body[blen - 1] != '\n')
            if (!buf_append(&body, &bcap, &blen, "\n", 1)) keep = 0;
        if (keep && !buf_append(&body, &bcap, &blen, newline, (size_t)nl)) keep = 0;
    }
    if (keep) {
        FILE *o = fopen(tmp, "w");
        if (!o) {
            fprintf(stderr, "[RED] [menu] cannot write %s: original %s kept\n", tmp, p);
            keep = 0;
        } else {
            size_t w = blen ? fwrite(body, 1, blen, o) : 0;
            int werr = (blen && w != blen) || fflush(o) != 0 || fclose(o) != 0;
            if (werr) {
                fprintf(stderr, "[RED] [menu] wrote an incomplete %s: original %s kept\n", tmp, p);
                keep = 0;
            }
        }
    }
    if (keep && rename(tmp, p) != 0) {
        fprintf(stderr, "[RED] [menu] cannot move %s over %s: original kept\n", tmp, p);
        keep = 0;
    }
    if (!keep) {
        remove(tmp);   // drop the temp only; the player's original settings.txt is untouched
        pthread_mutex_unlock(&g_set_mu);
        return -1;
    }
    free(body);
    if (s) {   // publish the new value only after the file really holds it
        atomic_store(&s->cache, value);
        atomic_store(&s->valid, 1);
    }
    pthread_mutex_unlock(&g_set_mu);
    return 0;
}
