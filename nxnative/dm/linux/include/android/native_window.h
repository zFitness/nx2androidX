// Linux stand-in for Android's <android/native_window.h>: the Vulkan backend takes whatever dm_front_window() returns for its window, and on
// Linux that is the SDL3 window (dm/linux/front_linux.c). Its size comes from SDL_GetWindowSize there, and the surface is SDL's.
// On the include path for Linux builds only (android/build.py): Android uses its own header.
#pragma once
struct SDL_Window;
typedef struct SDL_Window ANativeWindow;
