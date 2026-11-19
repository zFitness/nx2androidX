# IT TAKES TWO (010092A0172E4000): the rewriter's patches of this game's own builds. dm/tools/patch_nso.py loads every profile's patches.py and applies those of a module's NSO build ID;
# CUTS, OBS and FRAME_STEP as described there ("Registered patches"). Patches of Nintendo SDK module builds are in dm/tools/sdk_patches.py
CUTS = {
  # IT TAKES TWO 1.0.4 main: Unreal Engine 4.26's (EA's "Nuts" branch) FMallocBinned3 takes 36 GB of the engine's address region (nninitStartup reserves one region of 62 GB at
  # main+0x349e9cc unless -SwitchVirtualAddressSpaceSize= caps it; the allocator's constructor asks the OS for 0x900000000 bytes at main+0x34fea2c), so a capped region would starve it.
  # Here the allocator is made at run time: GCreateMalloc (main+0x349fad8) mallocs 0x1c38 bytes with operator new, the object in x19, and constructs it (main+0x349faf0 → main+0x34fe3b8).
  # The constructor call is cut, and observation gate OBS_UE_MALLOC (OBS below) puts the host allocator's vtable into the new object, which is still in x19 (dm/host/hle_uemalloc.c).
  # No code outside the allocator reads its pool base (the 36 GB it reserves, main+0x34fea50) or calls its methods directly: every FMemory call goes through the vtable
  'ddd039e882dbcd1ca9509763dda7596b': [
    (0x349faf0, '327a0194', '1f2003d5', "GCreateMalloc: bl 0x34fe3b8 (FMallocBinned3 constructor, 36 GB of address space) → nop; the host allocator's vtable is put in at the gate after it (hle_uemalloc.c)"),
    # The engine's address region: nninitStartup (main+0x349e9cc) reads -SwitchVirtualAddressSpaceSize= into the size at main+0xae98a60 and reserves the region only when that
    # size is still 0 (main+0x349f2e8 → the default 62 GB at main+0x349f2ec, the reservation at main+0x349f304). With the argument the size is set, so nothing is reserved: the region's
    # base stays 0, the pools are set up in [0, size) and the game aborts (nn::diag Break, main+0x3495b58). The branch now skips only the default, and the reservation takes the size
    # from the global, so the argument sizes the region (as in the other Unreal games' profiles) and the default path is unchanged
    (0x349f2e8, '080100b5', '480000b5', 'nninitStartup: cbnz x8, #0x349f308 → cbnz x8, #0x349f2f0 (skip only the 62 GB default, not the reservation)'),
    (0x349f300, 'e11361b2', 'e10308aa', 'nninitStartup: mov x1, #0xf80000000 → mov x1, x8 (the region is reserved with the size the argument gave)'),
  ],
}
OBS = {
  # IT TAKES TWO 1.0.4 main: right after the cut FMallocBinned3 constructor call (CUTS above), x19 = the new allocator object; the host writes its vtable there (hle_uemalloc.c)
  'ddd039e882dbcd1ca9509763dda7596b': [
    (0x349faf4, 21, 'aa1303e0', 'GCreateMalloc: the allocator object is in x19, before it is used: the host puts its vtable in; orig mov x0, x19'),
  ],
}
