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
    if (strcmp(argv[1], "get") == 0) {   // print the file/cache fps value
        printf("%d\n", dm_menu_setting_get("fps", 0));
        return 0;
    }
    if (strcmp(argv[1], "set") == 0) {   // set the file (and cache on success)
        if (argc < 3) return 2;
        dm_menu_setting_set("fps", atoi(argv[2]));
        return 0;
    }
    if (strcmp(argv[1], "cycle") == 0) {   // set then get in one process: proves the cache updated on save
        if (argc < 3) return 2;
        int v = atoi(argv[2]);
        dm_menu_setting_set("fps", v);
        printf("%d\n", dm_menu_setting_get("fps", 0));
        return 0;
    }
    return 2;
}
