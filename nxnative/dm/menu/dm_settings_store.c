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
// Caching / cross-thread policy: the "fps" key is a hot-path setting — the present thread
// polls dm_overlay_fps() every frame and dmui.c's checkbox reads it every menu frame — so its
// value lives in a C11 _Atomic int. Writers hold g_set_mu; readers read the atomic without a
// lock. The cache is populated lazily on the first fps get and refreshed on every successful
// save. External edits to settings.txt take effect after dm_menu_settings_reload() (or a restart).
#include "dm_menu.h"
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char g_dir[512];   // the settings file's folder; DM_ROOT until dm_menu_set_dir says otherwise
static pthread_mutex_t g_set_mu = PTHREAD_MUTEX_INITIALIZER;   // serializes loads, saves and cache updates
static _Atomic int g_fps_cache;        // cached "fps" value, published to reader threads only on success
static _Atomic int g_fps_cache_valid;

void dm_menu_set_dir(const char *dir) {
    pthread_mutex_lock(&g_set_mu);
    snprintf(g_dir, sizeof g_dir, "%s", dir ? dir : "");
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
            got = (int)strtol(line + klen + 1, NULL, 10);
            break;
        }
    }
    int err = ferror(f) != 0;
    free(line);
    if (fclose(f) != 0) err = 1;
    return err ? def : got;
}

// Loads (or reloads) the hot-path cache from the file: called lazily by the first fps get,
// after every successful save, and explicitly by dm_menu_settings_reload().
static void fps_cache_load_locked(void) {
    int v = read_key_from_file("fps", 0);
    atomic_store(&g_fps_cache, v);
    atomic_store(&g_fps_cache_valid, 1);
}

void dm_menu_settings_reload(void) {
    pthread_mutex_lock(&g_set_mu);
    atomic_store(&g_fps_cache_valid, 0);   // the next fps get re-reads the file
    pthread_mutex_unlock(&g_set_mu);
}

int dm_menu_setting_get(const char *key, int def) {
    if (strcmp(key, "fps") == 0) {   // hot path: polled per present frame — served from the atomic cache
        if (atomic_load(&g_fps_cache_valid)) return atomic_load(&g_fps_cache);
        pthread_mutex_lock(&g_set_mu);
        if (!atomic_load(&g_fps_cache_valid)) fps_cache_load_locked();
        pthread_mutex_unlock(&g_set_mu);
        return atomic_load(&g_fps_cache);
    }
    return read_key_from_file(key, def);   // cold-path keys read the file directly
}

void dm_menu_setting_set(const char *key, int value) {
    char p[600], tmp[640];
    settings_path(p, (int)sizeof p);
    if (snprintf(tmp, sizeof tmp, "%s.new", p) >= (int)sizeof tmp) return;
    size_t klen = strlen(key);
    char newline[96];
    int nl = snprintf(newline, sizeof newline, "%s=%d\n", key, value);
    if (nl < 0 || (size_t)nl >= sizeof newline) {
        fprintf(stderr, "[RED] [menu] settings key too long: %s\n", key);
        return;
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
        return;
    }
    free(body);
    if (strcmp(key, "fps") == 0) {   // publish the new value only after the file really holds it
        atomic_store(&g_fps_cache, value);
        atomic_store(&g_fps_cache_valid, 1);
    }
    pthread_mutex_unlock(&g_set_mu);
}
