// The standalone test harness for the pause-menu settings storage. It includes
// menu/dm_settings_store.c directly: the store is deliberately self-contained (no dm.h,
// no ImGui, no platform headers beyond pthread/stdio/stdlib/string/errno/stdatomic), so
// this compiles with any clang/gcc without a game profile or toolchain. Compiled and
// driven by tests/test_menu_settings.py; not part of any product build.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../nxnative/dm/menu/dm_settings_store.c"

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    if (strcmp(argv[1], "get") == 0) {   // get <key> [def]: print the file/cache value
        if (argc < 3) return 2;
        printf("%d\n", dm_menu_setting_get(argv[2], argc > 3 ? atoi(argv[3]) : 0));
        return 0;
    }
    if (strcmp(argv[1], "set") == 0) {   // set <key> <value>: write; exit 0 saved, 1 failed
        if (argc < 4) return 2;
        return dm_menu_setting_set(argv[2], atoi(argv[3])) == 0 ? 0 : 1;
    }
    if (strcmp(argv[1], "cycle") == 0) {   // set then get in one process: proves the cache updated on save
        if (argc < 4) return 2;
        int rc = dm_menu_setting_set(argv[2], atoi(argv[3]));
        printf("%d %d\n", rc, dm_menu_setting_get(argv[2], 0));
        return 0;
    }
    if (strcmp(argv[1], "reload") == 0) {   // reload then get: proves an external edit is picked up
        if (argc < 3) return 2;
        dm_menu_settings_reload();
        printf("%d\n", dm_menu_setting_get(argv[2], 0));
        return 0;
    }
    return 2;
}
