# The symptoms on the device: crash, black screen, garbled picture, freeze

What the player sees, and what it turned out to be. Every case carries the pull request it
came from (`#NNN`), the evidence that named it, and where the fix belongs.

**Read this when**: the game crashes, shows a black screen, draws garbage, freezes, or the
port stops at a stage.

The triage table comes first: it is the fastest way from a symptom to the two or three causes
that account for most of them, and to the evidence that tells them apart.

**This file is the upstream's cases**: what was fixed, and where the fix lives. The other
half - what the symptom looks like on a phone, what the first move is, and the dead ends
that were ruled out - is in **device-findings.md**. When a symptom here has no cause yet,
look there before theorising: it may already be a known shape.

The switches are the ones in `nxnative/dm/settings.tsv`; a switch marked **upstream only** is
in the upstream but not in this fork yet. The full list of them is in
`switch-android-port`'s `references/switches.md`.

## Triage

| The player sees | The likely causes, in order | What tells them apart | The first thing to do |
|---|---|---|---|
| **Crash at boot, 1-3 s** | 1) a shared-font glyph is missing (U+25A1) `#287` `#311`; 2) a read past the end of a module `#419`; 3) a Horizon service the host does not serve (`hid`, `bt`, `pdm`, `nfc`, `vi`, `time`) `#286` `#159` `#157` `#391` `#125` `#413`; 4) the address space is too small `#451` `#535` `#303`; 5) the host refused the game's own online SDK and the game dereferenced the stub (fork `974a538b`) | `CRASH sig=11 addr=0x38 x1=0x25a1` is the font; a fault address megabytes past `main` is the read; `[RED] sf: the game connects to service X itself` names the service; `[mem] AllocateAddressRegion ... refused` is the memory; `SIGSEGV addr=0x10` right after the start, in a game that loads an online SDK, is the SDK | grep `CRASH\|SIGSEGV\|addr=\|\[RED\] sf:\|AllocateAddressRegion` in `log.txt`; map the address with `main+<offset>` |
| **Crash later, in a movie or after a load** | 1) the fence replay wrote into a freed sync `#284`; 2) the heap was freed before the replay reached it `#5`; 3) the audio work buffer size is wrong `#436`; 4) a pool remap left pages read-only `#263` | `CRASH sig=11 pc=sdk+0x31ced8` in `TlsHeapCache` is the sync; `unknown record op` is the heap; a step returning `-51` with no error line is the audio size | `DM_HLECOUNT` around the crash; `DM_CTL threads` for a parked thread |
| **Crash in the middle of play** | 1) the command memory ran out `#60` `#152`; 2) the driver refused a format and the pipeline creation crashed `#466`; 3) the game's own allocator `#303` | `FATAL NVN command memory` is the memory; `FATAL [vk] vkAllocateMemory ... failed: -2` is the prewarm or the pressure | `DM_VK_MEMLOG=1`; `DM_VK_VALIDATE=1` |
| **The whole screen is black and the game runs** | 1) the shaders are not in the bundle and every draw is skipped `#286` `#505`; 2) a draw with no target was skipped `#194`; 3) a multi-layer target drawn with one layer `#77`; 4) a CPU-filled texture was never uploaded `#231` `#314` `#531`; 5) a cube view narrowed to one face `#530`; 6) the front-face rule culled the ground `#275`; 7) a texture builder did not say which storage its second texture shares (fork `37d903d1`) | `draw with a program whose shaders are not in the bundle` is 1; `draw with no usable render target: skipped` is 2; the depth is there but the colour is black is 3 or 4; a NaN (`fmod(colour, 0)`) in the tone map is 7 | `DM_VK_PASSDUMP=1`: is the depth there? `DM_VK_TRACE_PASS=-2`: which pass is empty? |
| **Black only after the logo, or in a movie** | 1) no VP8 decoder `#133`; 2) the end-of-stream picture was never fetched `#418` `#443`; 3) every packet has the time 0 `#443` | `[RED] movie: decoder type 2 (VP8) is not decoded by the host` is 1; the thread parked in the decode with 380 pictures for 381 packets is 2 | `DM_MOVIE_TRACE=1`; `DM_CTL threads` |
| **Black textures: lakes, roads, the UI atlas** | 1) the first-use upload skipped a compressed or uncached texture `#314` `#531` `#303` `#456`; 2) a narrowed cube view `#530`; 3) a GPU-written texture re-uploaded as zeros `#55`; 4) a block-compressed draw with the wrong format or size `#393` `#310` | `its bytes are as uploaded and the GPU wrote it: kept` is 3; `tex_cpu_uncached` in the profile is 1 | `DM_VK_LOG_UPLOADS=1`; `DM_VK_TEXBIND=<key>`; `DM_VK_TEXDUMP=<pool>+<offset>` |
| **Missing geometry or characters** | 1) the pool lookup returned the outer pool `#365`; 2) a vertex stream across a chunk's end `#451`; 3) a constant buffer cut at a chunk's end `#103`; 4) the geometry storage addresses were not reflected `#231` `#237`; 5) the backend fakes the SAMPLES_PASSED counter, and the game takes the difference of two reports, so it reads 0 and hides what is far away (fork `case-01007820196A6000-occlusion`) | `DM_VK_VATTR_LOG` for the format; the `pool +0x...` lines for the chunks; a black G-buffer albedo is 4; a figure that appears only when the player walks up to it is 5 | `DM_VK_PASSDUMP=1` with `DM_VK_PASSDUMP_DEPTH=1`; `DM_VK_PIPE_LOG=1` |
| **Garbage pixels, or noise on one material** | 1) a 1D integer fetch over a texture buffer with no answer `#268` `#486`; 2) a vertex input typed an integer `#269`; 3) a NaN from a min, max or clamp `#121`; 4) an image that was never uploaded `#107`; 5) the one-lane subgroup rewrite `#106` `#520` | `reads texture slot N as 2D rows ... a texture buffer is bound there` is 1; `DM_VK_VATTR_LOG` showing `R8G8B8A8_SINT` for a UNORM is 2; `shader ... subgroups of one invocation` is 5 | `DM_VK_X_FLAT_VS=<key>:1` to confirm the draw; `DM_VK_PASSDUMP=1` to find the first wrong pass |
| **The wrong colours: red and blue swapped, cyan, magenta** | 1) the RGB565 packed order `#87`; 2) a view's swizzle against its parent's selector `#89`; 3) a float output into an integer attachment `#411` | the format table's RGB565 row is 1 | `DM_VK_TEXBIND` for the NVN format per slot; `DM_VK_PIPE_LOG=1` for the colour formats |
| **A flicker or a one-frame glitch** | 1) a stale low-resolution depth at a cut or a reload; 2) a duplicate attachment's store `#86`; 3) a re-uploaded GPU-written texture `#55`; 4) a sampler resolved to a newer registration `#5`; 5) a Mali coherence fault `#524` | `DM_VK_CB_DRAWS=0` clears it, so it is 1; `DM_VK_X_NOSETC=1` is 2; `DM_NVN_SAMP_SNAP=0` is 4 | record it and count the bad frames: a screenshot misses it |
| **A frozen old picture under a new one** | 1) the draws were skipped because the shader was not translated yet `#505`; 2) the frame step holds the previous frame; 3) the present wait never completes | `46,356 draws` skipped is 1 | look at `captured_shaders/`; port again with `--install` |
| **Black only on one device** | 1) the Mali multi-fd hardware buffer `#523` `#524`; 2) the gralloc refusing a big blob `#492`; 3) a driver without timeline semaphores `#37` | `hardware buffer handle (3 fds)` is 1; `this gralloc refuses 0x100 MB` is 2; `FATAL ... no timeline semaphores` is 3 | `DM_VK_MEMLOG=1`; `DM_VK_NO_ZEROCOPY=1`; try the Turnip driver |
| **Frozen, no frames, the sound goes on** | 1) a sync wait that timed out `#436` `#510`; 2) a movie wait `#418` `#443`; 3) a GPU wait that never woke `#226`; 4) the replay behind the game `#438`; 5) the game's own busy-wait limiter `#303` | `DM_NVN_SEQ=N` shows what the render thread waits for | `DM_CTL threads`; `DM_NVN_SEQ=120` |
| **A stutter when an asset loads** | 1) the pool lock held across the buffer allocation `#168`; 2) the SVC lock convoy `#169` | the `memory pools in the last N s: ... made (MB, ms ...)` line | `DM_VK_PROF=1`; `DM_SVC_SPIN=0` as an A/B |
| **The frame rate is stuck at 30 or 40** | 1) the governor latched `#40`; 2) the display dropped to 30 Hz `#312`; 3) the swapchain not pre-rotated `#129`; 4) a non-whole vsync period snapped up `#130`; 5) the game asks for 30 by design | `the game sets present interval`; `display timing: refresh 33.3 ms` | `DM_FPS_PIN=60` to see whether the port can hold 60; `DM_VK_PACE_LOG=1` |
| **The frame rate collapses for a second and recovers by itself** | 1) the engine's own dynamic resolution running up to native; 2) an effect chain that only appears there; 3) real work (an enemy, a spawn) | `new pipelines 0` and `texture uploads 0` on the burst frames, with the GPU time stepping with the render size (the engine is caught calling `nvnCommandBufferSetViewports` at the big size) | `DM_VK_PASS_TIMES=1` (the costliest passes and their size) and `DM_NVN_VIEWPORT_CALLER=<w>x<h>` (who resized); `DM_DYN_SCALE=high` makes the engine read the GPU clock 4x as fast, so it stops taking the top rungs |
| **The UI is drawn but its text is not** | 1) a CPU-filled glyph atlas was never uploaded; 2) the atlas is an image the game wrote through a shader | `TextureBuilderSetSwizzle not identity (0 0 0 2)` is a glyph atlas read as alpha from R; the first-use upload list has no uncompressed 2D texture in it | `DM_VK_LOG_UPLOADS=1` and `DM_NVN_TEXINFO=<w>x<h>`; `DM_NVN_CPU_TEX2D_FIRST_USE=1` |
| **The game dies minutes in, after a load, with the GPU device lost** | 1) one frame too long for one submission; 2) an empty colour slot 0 `#257`; 3) a BC image drawn through an uncompressed view `#68` | `DM_VK_CRUMBS` names the pass the GPU finished and the one it never finished; the frame's draws over passes in one part (no `part ... sent early` line) | `DM_VK_CRUMBS=1`, then `DM_VK_LOG_FS=<key>` and `DM_VK_PIPE_LOG=1` for that pass |

## Crash

| The player sees | The evidence | The cause | Layer | PR | The fix |
|---|---|---|---|---|---|
| A random crash about a second after the start, half of the launches | `SIGSEGV` at `main+0x1c180`, a read megabytes past the image | an index of `0xFFFF` ("none") used without a bounds check; the memory layout decides between a fault and garbage | host (`loader.c`) | `#419`, `#401` | map 16 MB of readable zero pages behind each module; bound the index |
| A crash at the start with `x1 = 0x25a1` | `SIGSEGV addr=0x38 pc=main+0x111e000` | the shared font has no U+25A1, the fallback glyph, and the lookup dereferenced a null | host (`hle_sdk16.c`) | `#287`, `#311`, `#422` | serve the console's own font from the system data; `DM_SHARED_FONT` in the profile (on this fork the app port always sets `DM_SHARED_FONT`, which outranks system data for types 0-4 - device-findings.md, The shared fonts) |
| A crash about 15 s in, during the second movie | `CRASH sig=11 pc=sdk+0x31ced8` in `TlsHeapCache::AllocFunc` | the fence replay wrote into a freed sync; the sync is exactly 64 bytes, the size of the free list's word | nvn (`nvn_obj.h`) | `#284`, `#285` | write the fence only while the sync's magic is intact |
| A boot abort, or frames that stop while the sound goes on | `SIGILL` at `main+0x38e610` | a sync no fence had reached answered as timed out, and the guest read that as a failure | nvn (`hle_nvn.c`) | `#436`, `#510` | signal a fence-less sync |
| A crash right after the first account object | `sig=11 addr=0x8` | an empty stub took over a polymorphic constructor; the SDK's own constructor writes the vtable, so it stayed 0 | host (`hle_account.c`) | `#385` | do not take over the polymorphic constructor |
| A crash at the boot after `[RED] sf: the game connects to service hid itself` | `sdk+0x238eb0` | the Palma calls reach a service the host does not serve | host (`hle_hid.c`) | `#286`, `#159` | take the calls over as "no Poké Ball Plus" |
| A crash at the boot | an abort at `sdk+0x251cdc` | the Bluetooth service is not served | host (`hle_offline.c`) | `#159` | take the calls over: init does nothing, the events never fire |
| A crash right after the save is mounted | `SIGSEGV addr=0` | the play statistics service is not served | host (`hle_offline.c`) | `#157` | answer "never played" |
| A crash after the NFC tutorial | `Break 0xe15` | the NFC service is not served | host (`hle_sdk16.c`) | `#391` | the NFC hooks: no reader, no device |
| A crash in `nnMain` | `SIGSEGV` at `sdk+0x1d2f30` | only `OpenDefaultDisplay` was hooked; this SDK calls the named overload | host (`hle_vi.c`) | `#125` | hook the named overload |
| A crash right after `nnMain` | `sdk+0x211a7c`, `ldr x8,[x0]` with `x0=0` | `nn::time::Initialize` was a no-op, so the service object was never made | host (`hle_time.c`) | `#413` | dispatch by SDK |
| A clean exit with **no error line at all** | the audio step returns `-51` | the work buffer size answered with the CPU size instead of the service's | host audio (`hle_audren.c`) | `#436` | answer the service's own formula |
| No sound, the game updates once and waits | every render returns `0x40299` | the renderer sits at `+0x50` on this SDK, the host read `+0x60` | host audio (`hle_audren.c`) | `#403`, `#79` | read the offset off the SDK's own code |
| A crash before the title screen | `SIGSEGV` in `ev_check` | the renderer event check runs on an SDK that does not have it | host audio (`hle_audren.c`) | `#148` | the event layout stays off on the old SDKs |
| The process dies before the first frame | `[mem] AllocateAddressRegion ... refused (0x1803)` | the profile's address space is too small | profile + host | `#451`, `#535`, `#303`, `#436` | `mem_reserve`, `mem_alias`, `mem_stack`, `app_pool`, `sys_resource` in the profile |
| A crash at the boot or as a battle starts | `CRASH sig=11 addr=0x50 pc=main+0x385201c` | the command memory size was summed on every call, while another thread recorded into a pool | nvn | `#233` | return the byte count that was last added |
| A crash when the mode is switched between handheld and docked | the log shows only the two-argument hook | the host intercepted `nn::oe::SetPerformanceConfiguration(PerformanceMode, int)` but left the one-argument overload to the guest SDK, and the SDK's own one crashed | host (`hle_oe.c`) | `#533` | register the one-argument overload too: log the requested configuration, leave the host clocks alone (OPEN, not in this fork) |
| A fatal stop entering a region | `FATAL NVN command memory ... reached 1024 MB` | every empty-pool grant took a whole 256 KB segment | nvn | `#60`, `#350`, `#152` | lend the length that was asked for |
| The driver crashes while making a pipeline | the log names a format the driver does not support | the pipeline builder did not check the final attribute formats | vk | `#466` | check the formats before the driver call |
| Per-instance attributes advance every instance | invalid-usage warnings | the vertex attribute divisor extension was never enabled | vk (`gfx_vk_core.c`) | `#253` | enable the extension and its feature |
| A fault on a page the tracker never protected | the fault handler says "not ours" | a remap that failed partway left earlier chunks read-only | vk + `nvn_dirty.c` | `#263` | make the writable runs writable again |
| A hang in the relocation loop, or files reloaded in an older state | `dirty-page tracking: 1 pool(s) mapped again in one piece` | a pool inside another pool lost its pages to the outer pool's remap | vk | `#239` | restore the pages into the containing pool's buffer |
| 0.7 fps and a black screen on a MediaTek device | `memory pool 0x70ce000000 +0x10000000 could not be zero-copy (-1)` | the gralloc sends three fds; the code took fd 0 as the dma-buf, which is only true on Adreno | vk | `#523` | probe the fds and pick the mappable one (**upstream only**) |
| The screen flickers, the video worse | `zero-copy 1201.4 MB, copied 0.0 MB` | on Mali the CPU's data cache is not cleaned, so the GPU reads what was written back | vk (`gfx_vk_core.c`) | `#524` | clean the dirty lines before the consuming submission |
| A thread dump leaves the game frozen | a futex wait on `g_park[0].state` | the dump took the same slot the released thread was waiting for | host | `#193` | set the state to 0 on the way out and wait for it |
| An abort in `MapAliasStack` | the FFR abort in `dm_ue_heap_owns` | Android tags Scudo pointers and `/proc/self/maps` does not | `compat/darwin_compat.c` | `#251` | compare without the top byte |
| `CRASH sig=11 pc=0` in `wait_fence` | the device reports the feature but exports no entry point | the feature query was taken as proof | vk | `#125`, `#33` | ask the device for the entry points; use the fence ring |
| A stack overflow in the audio call on Android 17 | the Binder stack overflowed | AAudio's stream start ran on a small guest thread stack | host audio | `#444` | run it through the big-stack entry |
| An assert in the JPEG decoder | the SDK's `Analyze` fails on an empty image | the game handed the decoder an empty image | host (`hle_image.c`) | `#273` | serve the decoder with stb_image |
| The low-memory killer ends the game in a minute or two | Android kills the process | the backend held every image and pipeline | android | `#392`, `#437` | give the memory back under pressure |
| `FATAL [vk] vkAllocateMemory(...) failed: -2` | about 10 700 mappings | the compute prewarm built a pipeline for every compute shader in the bundle | vk | `#53` | skip the prewarm above `DM_VK_COMPUTE_WARM_MAX` |
| A fatal start on a 2021 Adreno | `the device has no timeline semaphores` | a Vulkan 1.1 driver without them or without BC | vk | `#37` | a fence ring of 16 and a CPU BC decode |
| `VK_ERROR_DEVICE_LOST` on the load | `DM_VK_CRUMBS` names the same pass every time | a BC image with no colour-attachment usage, and a pass sized in texels instead of blocks | vk | `#68` | add the usage; size the pass in blocks |
| The device is lost every frame | a target in slot 5 with slots 0-4 empty | an empty colour slot 0 hung the GPU | vk | `#257` | `DM_VK_SLOT0_FILL=1` |
| A GPU hang about 35 s into the title | `vkQueueSubmit -4` | the driver's subgroup support is narrower than the shader's | shader | `#106` | rewrite the module as subgroups of one invocation |
| A crash on its renderer thread | Frostpunk sizes its table to `min(0x5E, 0x5F)` | the host answered 128 for a per-stage sampler count | nvn | `#256` | answer 32 per stage |
| A stack overflow in the replay | `exec_ops` nested on `OP_CALL` | host-lent command segments were returned at finalize | nvn | `#152` | reclaim only after two scans find nothing |
| The rewriter aborts before writing anything | `AssertionError: jump table 1eb2e0` | a 32-bit zero-extension was matched as the mask | rewriter (`patch_nso.py`) | `#413`, `#79` | treat it as a copy of the index |
| The replay reads garbage | `unknown record op` | the game freed the command memory before the replay reached it | nvn | `#5` | snapshot each submission's records at submit time |
| A stack-buffer overflow in the descriptor scratch | the scratch holds 384 entries | no capacity check before an image binding wrote | vk | `#289` | check the capacity before each write |
| A crash at the start, and the game wanted its own online SDK | `SIGSEGV addr=0x10 at main+0x6d1b4c` | the host refuses every NRO that exports Epic Online Services' entry points (it cannot serve them, so the game plays offline), and the game dereferences the stub's null online object a moment later | host (`hle_ro.c`) | fork `974a538b` | the profile opts in: `online_sdk 1` in `game.tsv` and `DM_ONLINE_SDK=1` in `android.tsv`'s `env` (the switch comes with the case branch); the host then loads the SDK's code (its network calls fail, the game carries on) and the packer keeps the NRO |
| A crash one page below the guest's own stack | the fault address sits just under a guest thread's stack | the gate (the rewriter's svc / cntpct replacement) ran on the guest thread's stack, and the host's own printf frame ran off its end: a thread with a 4 KB stack and 1.8 KB left | host (`entry.S`) | fork `784ccc9d` | the dispatch runs on the thread's **host** stack (the take-over functions' `dm_gate_stack`, 512 KB); the gate's own frame stays on the guest's, because the handler writes the guest's registers back into it |
| The game dies silently: no `CRASH` line at all | `[RED] crash: the SIGSEGV handler is not ours after the Vulkan device was made` | the Vulkan driver reset the app's signal handlers to the default action right after the device was made, so a fault was a silent kill | vk (`gfx_vk_core.c`) | fork `d278d283` | the host puts its handlers back right after the driver is done, and checks again that they are its own |
| The process dies 1.5 s after the launch, before the title screen | the driver's shader compiler faults with `SIGSEGV`, `NULL+0x48`, on one compute shader | the compute warm-up built a pipeline for every compute shader in the bundle, but a bundle holds many more than a game dispatches (147 for this game), and the driver's compiler can die on one of them | vk (`gfx_vk_exec_xfb.inc`) | fork `8ecd28c4` | the warm-up builds only the shaders the game dispatched: the replay thread records every key it builds (`vk_compute_pipes.bin`) and the warm-up reads them back |
| A crash in the middle of play, with a float or a block-compressed texture drawn through an integer view | the blend enable and the clear encoding read the texture's format, while the pipeline takes the attachment view's | the two formats differ: a float or BC texture drawn through a UINT view can get blending on an integer attachment, and a clear of 1.0 is written as the bits `0x3f800000`; an integer texture drawn through a float view loses its blending and gets an integer clear | vk (`gfx_vk_exec_*.inc`) | `#565` | `rt_view_fmt`: the view's format, for blending, masked clears and full clears (**upstream only**, and it wants a device check) |

## Black screen

| The player sees | The evidence | The cause | Layer | PR | The fix |
|---|---|---|---|---|---|
| Black, and the game runs at 60 fps | `draw with a program whose shaders are not in the bundle` | the split read the wrong container form | shader | `#386`, `#157`, `#479`, `#431` | the per-format readers |
| Black with the sound on | `draw with no usable render target: skipped` | a draw with no target was skipped instead of getting a pass of its own | vk (`begin_pass`) | `#194` | give it an attachment-less pass, sized from the viewport |
| Text over a black scene | a 32-layer colour LUT target, the pass used one layer | the render pass never rendered the attachment views' layers | vk | `#77` | use the least layer count of the active views |
| The title and the map are black, silhouettes only | the CPU-filled colour LUT was never uploaded | the first-use upload skipped uncompressed 2D textures | vk | `#231`, `#237`, `#456` | `DM_NVN_CPU_TEX2D_FIRST_USE=1` |
| The scene is black, the sound goes on | 380 pictures for 381 packets | the end-of-stream picture was never fetched | host movie (`hle_movie.c`) | `#418`, `#443` | `DM_MOVIE_EOS_SEPARATE=1` (**upstream only**) |
| The opening movie is black frames | `[RED] movie: decoder type 2 (VP8) is not decoded by the host` | no VP8 decoder | host movie | `#133` | a libvpx VP8 decoder |
| The opening movie freezes on its first frame | every packet has the time 0 | the codec's time was mapped back to the game's, so the game sees no progress | host movie | `#443` | keep the mapping only where the game's own time moves |
| The water, the lakes and the rivers are flat black | a 16x16 reflection probe through a cube view narrowed to one face | the view was refused, so the sampler read the dummy texture | vk (`gfx_vk_tex.c`) | `#530` | `DM_VK_CUBE_WIDEN=1` (**upstream only**) |
| A washed-out picture: white asphalt, white sparkles | an attachment view kept the image's block-compressed format | rendering into it was invalid; Adreno wrote junk into all six faces | vk | `#146`, `#393` | an attachment view of the same block size keeps the format the game asked for |
| A character vanishes in a teleport | a 32x32x32 BC4 texture read back as zeros | a 3D BC image drawn into through an uncompressed view had no stand-in | vk | `#310` | `DM_VK_BC_DRAW=1`: draw into a stand-in, then copy back |
| The title background and the in-game backgrounds are black | BC7 textures in uncached pools | the first-use upload skipped compressed textures | vk | `#314` | the upload applies to compressed textures too |
| One chapter title card is black | `f->compressed` is 0 for a CPU-decoded texture | the test asked the Vulkan format's flag, not whether the guest memory is compressed | vk | `#531` | `int guest_comp = f->compressed \|\| f->dec;` |
| No text anywhere, the labels are missing | the fonts are BC7 arrays in uncached pools | the first-use upload skipped them and the data was never flushed | vk | `#303` | `tex_cpu_uncached` in the profile |
| The particles are invisible | the sprites were images of zeros | the upload did not follow the Mac backend's rule | vk | `#107` | upload a compressed or 3D texture whose storage holds data at first use |
| Some library geometry is missing in the intro | the vertex pool was split at the chunk boundary | the vertex bindings crossed the chunk's end | vk | `#451` | `DM_VK_ZEROCOPY_CHUNK_MB=512` (**upstream only**) |
| A character is never drawn; every triangle collapses to a point | the model's buffers sit in a separate dma-buf inside the outer pool | the pool lookup returned the outer pool | vk | `#365` | `DM_VK_POOL_INNERMOST=1` (**upstream only**) |
| The scene is black with white shapes; the player and the HUD are right | a constant buffer range crossed a chunk's end | the range was bound cut at the chunk's end, so the GPU read zeros | vk | `#103` | bind the range whole, from a copy |
| The scene is black, the game runs, fog everywhere | the pass dumps show an empty depth buffer | the front-face winding culled the ground | vk | `#275` | `DM_VK_FRONT=2` |
| Only the spot-lit faces are black | `its bytes are as uploaded and the GPU wrote it: kept` | a GPU-written packaged texture was re-uploaded with the CPU's stale zeros | vk | `#55` | a hash of the guest's bytes |
| The scene behind the battle menu turns black | `CommandBufferClearTexture` with the mask `0x8` | the masked clear wrote every channel | vk | `#179` | the masked clear uses the masked-clear draw |
| A frozen old shot under the new shot's flares for 8-12 s | 46 356 draws skipped | the Vfx programs are assembled at run time and are in no file | shader | `#505`, `#291` | `runtime_shaders on` (**upstream only**), or capture and port again |
| The menu backgrounds are black until the second port | `shader ... is not in the bundle` | the launcher builds whole GLSLC outputs in the heap | shader | `#107`, `#159`, `#286` | capture them, then port again with `--install` |
| The black screen is really 0.7 fps | `NVN submit+present p50 1343.50 ms` | the Mali multi-fd hardware buffer | vk | `#523` | pick the mappable fd |
| The first launch is black for 65 s | about 2 100 pipelines compiled in the first frame | the pipeline prewarm | vk | `#41`, `#250` | cache the pipelines; save the cache after a burst |
| The whole scene is black because a float output went into an integer attachment | the G-buffer outputs 1-3 are integer targets | no PC shader to pair with, so no facts about the outputs | shader | `#411`, `#519` | correct the facts; `android_discard demote` in the profile |
| The UI is yellow and white instead of translucent | the UI composites by storing into the window image | no integer storage view over a float texture | vk | `#194` | `DM_VK_UBWC` bit 4 |
| A road, a floor or a patch of the ground draws black with sparkly noise | the decal's fragment shader draws into an RGB10A2 normal G-buffer and reads the same image as an `r32ui` storage image | with `DM_VK_UBWC=3` the image's format list has no integer format, so the storage view fell back to RGB10A2 UNORM; the shader read garbage, the normals came out as per-pixel noise, and the lighting turned them black | vk | `#459` | `DM_VK_UBWC=7` in the profile (bit 4 adds the uint/sint formats of the texel size). Measured on an Adreno 740: 22.6 ms a frame before, 20.6-22.9 ms after |
| A cube request is served with a 2D view | the shader asked for a cube the selected image could not form | the request fell back to the original 2D view and was cached, so the shader sampled a 2D image as a cube | vk | `#204` | reject the request and use the typed dummy; the creation flag now also goes to square single-sample 2D arrays with 7, 8 or 14 layers |
| The wrong textures are bound, and it looks like noise on one material | the descriptor cache accepted a matching hash without comparing the contents | a hash collision would reuse another draw's descriptor set | vk | `#297` | compare an owned, padding-free key byte for byte before a cache hit (hardening; no natural collision or device symptom is known) |
| A compressed texture shows the contents of an older frame | the CPU BC fallback decodes the blocks straight from the guest CPU address | earlier GPU commands had written those blocks, and the CPU read missed them | vk | `#140` | `DM_VK_X_BC_GPU_READBACK=1` takes a GPU snapshot before decoding (off by default, cached on the first CPU BC upload: restart the app after changing it. OPEN, not in this fork) |
| Black after the intro movie: the sound goes on, the game runs at 60 fps, and the draws per frame fall from 131 to 2 | `[RED] audren: a second renderer (the host drives only one)` | the game opens a **second** `nn::audio` renderer for its movies; the host drives one, so the second renderer gets no render thread, its renderer event never fires, and the game waits for that event inside the logo movie: it keeps presenting frames but stops drawing the scene | host audio (`hle_audren.c`) | fork `case/01007820196A6000-rdr` (the upstream's patch is `#486`) | the second renderer gets its own host thread, its own output and its own frame; the host logs `audren: second renderer driven by a host thread` |
| The whole scene is black, and the tone map's exposure texture is zero | `fmod(colour, 0) = NaN` in the tone map | the game makes a second texture on a texture's storage (one to write as an image, one to sample); with no pool in the builder the second texture was not known to share the first one's storage, so the sampler read what nothing had written | nvn (`hle_nvn.c`) | fork `37d903d1` | the builder's pool and offset are answered (the pointer goes back in `x0`), and the ZCull compression switch is a no-op: the host does no ZCull |
| One frame in sixteen of a static menu comes out black | the swapchain is cleared and the game image blitted into it, both as transfer writes, with no barrier between | a driver free to reorder transfers can run the blit first and the clear after it, which puts a black frame on screen (the Mali-G68) | vk (`gfx_vk_present.c`) | `#552` | a memory barrier between the two transfer writes, and the acquire wait's `waitDstStageMask` at `ALL_COMMANDS_BIT` |
| Black frames after a movie was stopped, with `[RED] movie: AVC has no SPS / PPS, outputting black frames` | the decoder is rebuilt after the Stop, and the packets the game had already queued arrive after it | the AVC parameter sets live inside the decoder and `h_movie_Stop` releases it, so the rebuilt decoder has no SPS/PPS | host movie (`hle_movie.c`) | `#553` | copy csd-0, csd-1 and the avcC at Configure and apply them when the decoder is rebuilt (**upstream only**) |

## Garbled picture

| The player sees | The evidence | The cause | Layer | PR | The fix |
|---|---|---|---|---|---|
| Gold cup borders and yellow icons come out cyan | the cup screen | NVN's RGB565 puts red in bits 0-4, Vulkan's `R5G6B5` the other way round | vk (`gfx_vk_tex.c`) | `#87` | map NVN RGB565 to `B5G6R5_UNORM_PACK16` |
| The wrong shadows | a view against its parent | the texture's selectors were applied and then the view's, so a view asking for green read the parent's replicated red | vk | `#89` | the view's selectors win |
| Some objects are overbright while the scene looks normal | a texture-size query reflected as the combined texture slots | those slots read the texture array even when the overlapping image slot was bound | vk | `#143` | resolve the binding from the overlapping image slot |
| The moon glow flashes in 3-10 of 780 frames | `DM_NVN_SAMP_SNAP=0` clears it | a bound sampler resolved to its newest registration | nvn | `#5` | resolve it to the registration it had when it was bound |
| The lighting flickers | the normal image was entirely zero in 9 of 16 frames | inactive duplicate attachments made separate load and store operations for one image | vk | `#86` | remove the inactive duplicates |
| The whole sea is black | `DM_VK_VATTR_LOG` gives the attribute's format | a vertex input that only moved through bit casts was declared an integer | shader | `#269` | a cast whose integer only goes back to a float is a raw move |
| The fur is a soft smear over the faces | the velocity target had full-speed pixels where the Mac had none | `FMin` / `FMax` / `FClamp` are NaN-undefined in GLSL.std.450 | shader | `#121` | rewrite them as `NMin` / `NMax` / `NClamp` |
| Grid lines on the ground after a long session | 3 838 live sampler-cache entries for 139 parameter sets | the host's sampler layout put the filters outside the header the game hashes | nvn (`nvn_obj.h`) | `#318` | the whole sampler state goes after the eight-byte header |
| The geometry is black silhouettes | the G-buffer albedo is black | the geometry storage addresses were not reflected | vk | `#231`, `#237` | reflect and populate them |
| The room is upside down for 7 frames | the copy carries `NVN_COPY_FLAGS_MIRROR_Y` | the copy only read the linear-filter bit | vk | `#286` | a mirrored copy is a blit with the offsets swapped |
| The picture sits in one corner | `vi::SetLayerCrop` and no window crop | the present read only the window's own crop | android present | `#293` | fall back to the layer crop |
| Textures and video show stale or half-written content | `DM_VK_NO_ZEROCOPY=1` hides it | the Mali zero-copy path without a cache clean | vk | `#524` | clean the dirty ranges |
| Every frame with a decoded movie frame flashes black | a 1920x1080 luma plane across a chunk boundary | the copy read past the chunk's buffer | vk | `#179` | copy a range that crosses a boundary through scratch |
| The save pictures are noise | a copy into a linear texture was never written back | the copy wrote only the Vulkan image | vk | `#226` | write a linear copy back to its storage |
| The village's palisade disappears once the multi-draw count is honoured | the compute merges the draw records through shared memory with no barrier | it relies on 32 lanes in lockstep, which a one-lane rewrite breaks | shader | `#151`, `#106`, `#367` | honour the indirect count; fix the compute's assumptions |
| Pieces of scenery come and go | 45 056 bytes of workgroup-shared memory on a device with 32 KB | the culling compute asks for more shared memory than the device has | shader | `#411` | reduce the shared memory |
| A tree's crown disappears at every LOD change | the discard happens before the texture is sampled | after a discard the other pixels have no derivatives and read the smallest mip | shader | `#411` | `android_discard demote` in the profile |
| The water turns opaque brown | the pending render-condition table was full | the occlusion reports overflowed it, so a later report was not noted | vk | `#378` | an occlusion report only updates an existing entry |
| Byleth's irises are white with blue specks | `reads texture slot N as 2D rows ... a texture buffer is bound there` | a 1D integer fetch with no type answer became 2D rows | shader + profile | `#268`, `#486` | answer the slot in `shader_facts_manual.tsv` |
| The ground is culled and the cars show their backs | `DM_VK_VATTR_LOG` | the game winds against the host's front-face rule | vk | `#275` | `DM_VK_FRONT=2` |
| The launcher menu is mirrored | `[RED] NVN unimplemented function called: nvnDeviceGetWindowOriginMode` | the stub's 0 (lower-left, GL) made the game draw its layer flipped | nvn | `#284`, `#286`, `#159` | the getter returns what the setter stored |
| Jagged white steps on the hair's edges | the shader reads a UBO component chosen at run time | the driver did not give each invocation its own component | vk | `#451` | `DM_VK_UBO_COMPONENT=1` |
| Blocks of near objects vanish for a frame | `DM_VK_CB_DRAWS=0` clears it | a stale low-resolution depth at a cut or a reload | vk | - | `DM_VK_LRZ_TOUCH` |
| Thin black slivers over the cliffs in a few percent of frames | `DM_VK_X_SKIPVS` found them in 4 rounds | vertex shaders with a rasterizer discard write into the G-buffer pass | vk | - | `DM_VK_X_RDKEEP=1` |
| Whole blades of grass are black in some frames | depth with no albedo in the pass dumps | the barriers did not stop Adreno's next passes from reading unwritten memory | vk | - | `DM_VK_RD_TOUCH=0` |
| Whole triangles of one draw go missing | the pass dumps with a `gl_PrimitiveID` shader | Adreno applied another depth buffer's low-resolution depth | vk | - | `DM_VK_LRZ_TOUCH` |
| The lights go out for a few frames at a steady rhythm | `DM_VK_FDZ=0` clears it | Adreno's early culling on a depth buffer a shader wrote through `gl_FragDepth` | vk | - | the shader writes `gl_FragDepth = gl_FragCoord.z` |

## Frozen

| The player sees | The evidence | The cause | Layer | PR | The fix |
|---|---|---|---|---|---|
| The frames stop, the sound goes on | the guest's audio task is two stages short | a sync no fence had reached timed out | nvn | `#436` | signal a fence-less sync |
| The movie never ends | 380 pictures for 381 packets | the end-of-stream picture was never fetched | host movie | `#418`, `#443` | `DM_MOVIE_EOS_SEPARATE=1` |
| The GPU hangs and the device is lost | `DM_VK_CRUMBS` names the last pass the GPU finished | an empty colour slot 0, or a block-compressed draw with the wrong pass size | vk | `#257`, `#68` | `DM_VK_SLOT0_FILL=1`; size the pass in blocks |
| The game hangs for 414 s | a wait that a signal interrupted never woke | one unlimited GPU-timeline wait | vk | `#226` | wait a second at a time, and log every ten |
| Black, the sound goes on | `unknown record op` | the game freed the command memory before the replay reached it | nvn | `#5` | snapshot the records at submit time |
| Every present waits a second | the present ticket must complete on every path | an early return in a present path | android present | - | audit every present return |
| A one-second stutter each time an asset loads | the replay thread nearly idle, the GPU idle | the pool lock was held across the hardware buffer's allocation | vk | `#168` | take the buffer outside the lock; small pools take a slab slot |
| The threads block 350-430 ms every three seconds | 84 µs per contended acquire | the guest's threads hand work to each other thousands of times a second | host (`hle_thread.c`) | `#169` | spin a few microseconds before sleeping (`DM_SVC_SPIN_US`) |
| One core at 100 %, the fan at full speed | the limiter yields 3.8 million times a second | the game's own frame limiter | rewriter | `#303`, `#386` | a patch: the yield becomes a short sleep |
| Two threads spin on a core each, the phone runs hot, and the battery drains | `top` shows "nvn replay" and "vk record" at 42-54 % of a core, with 35-65 % of the app's CPU time in the kernel | the two-stage replay queue's threads hand work to each other: the recorder's read position sat in the producers' cache line, and a wait was up to 2,000 `sched_yield` calls that return at once when there is nothing else to run | vk (`gfx_vk_dq.c`) | `#568` | each thread's position on a cache line of its own; spin briefly, then sleep (`DM_VK_MT_REPLAY=1` is the two-stage replay, `DM_VK_PROF=1` shows it) |
| The title holds 30 fps with 1 ms of GPU work | the governor counted the present wait as frame work | the acquire wait is the longer period's own pacing | android perf | `#40`, `#20` | pass the present wait apart |
| 30 fps on screen although the game runs at 25 ms a frame | the cadence snapped each frame's target to the vsync grid | `pace_desired` rounded every non-whole period up | android present | `#130` | advance the cadence unsnapped |
| The game stays at 30 fps although it could hold 60 | `display timing: refresh 33.3 ms` | a frame-step hold made the window ask for 30 fps | android present | `#312` | `DM_VK_WINDOW_GAME_RATE=1` |
| 30 fps on screen, the compositor did the work | the layer table says `ROT_90` | the swapchain did not pre-rotate | android present | `#129` | take the surface's rotation as the swapchain's `preTransform` |
| Two one-second freezes in five minutes | `[RED] drain waits over 1 s` | the two-stage replay's draining flag was a 0/1 | vk replay (`gfx_vk_dq.c`) | `#146` | count the waiters instead of using a flag |
| The pause menu freezes for a second per interaction | the panel's fence wait was a second | unbounded waits in the overlay's redraw path | android present | `#494` | the panel's fence waits at most 20 ms |
| Every menu tap re-rasterizes the whole panel | 410-552 ms | the raster wrote into a write-combined staging buffer | android present | `#493`, `#525` | raster into cacheable memory, copy out the uploaded rows |
| The game never ends a movie | a second audio renderer was undriven | FMOD and Bink both open | host audio | `#486` | run the second renderer on its own thread |
| The app is killed by the low-memory killer in a minute or two | the process holds 1.9 GB | the backend never gave the memory back | android | `#392`, `#437` | trim under pressure and on `onLowMemory` |
| `[RED] virtual pool remap ... failed: 46` | Unreal's sparse pools | a private memory alias is not possible on Android | host (`darwin_compat.c`) | `#76` | keep the sparse pool's mappings in the page table |
| A game that waits for the GPU never overlaps the two | BotW's next frame is a handle to a body recorded during this frame's replay | there is no replay ahead | nvn | `#438`, `#392` | `DM_NVN_AHEAD=1` (**upstream only**) |
| A held frame rate never comes back up after a heavy load clears | the frame step stays at 20 or 30 fps (`k = 2` or `3`) | the frame-step cost counted the queued surface wait, so it never stepped back to 60 | nvn (`hle_nvn.c`) | `#545` | track the present-queue wait and the replay cost separately, and give back a little slack only while a hold is active. Verified on a OnePlus 11 with Breath of the Wild 1.9.0 |
| The GPU stays at its highest clock after the game is paused or has ended | the other apps in the background run hot | the turbo property was given back before `go_background()`, which waits for the presents, so a present already inside the frame timer could set it again; and a game that ended itself never released it (the property is device-wide and outlives the process) | android | `#307` | release the clock after `dm_gfx_suspend(1)`, and in the host thread just before the exit. Verified on a Galaxy Z Fold7 |

## Where the fix belongs

| Directory | What it owns | The symptoms it answers |
|---|---|---|
| `nxnative/dm/host/` | the Horizon services: files, audio, the movie, input, the offline services, the display, time, the shared fonts, the module loader, the threads | a boot crash from an unserved service, the font crash, an audio hang, a movie hang, a read past a module, a parked thread |
| `nxnative/dm/gfx/nvn/` | the NVN shim: the API surface, the builders, the getters, the sync, the command memory, the guest-visible layouts, the dirty-page tracking | a sync that times out, `FATAL NVN command memory`, the sampler cache running out, a remap that loses pages |
| `nxnative/dm/gfx/tex/` | the block-linear addressing and the CPU BC decode | a garbled texture, a BC decode that differs from the GPU's |
| `nxnative/dm/android/` | the Vulkan backend, the front end, the overlay, the governor, the compatibility layer | a black scene, a garbled picture, a lost device, a hang, a frame-rate stall |
| `nxnative/dm/gfx/tools/` | the split and the readers beside it | the shaders that are missing |
| `nxnative/dm/android/tools/` | the Vulkan exporter and the bundle writer | a vertex input typed wrong, a NaN min or max, a bundle that will not load |
| `nxnative/dm/games/<title ID>/` | the profile: `game.tsv`, `android.tsv`, `patches.py`, `shader_facts_manual.tsv` | everything that is one game's own |
| `porter/` | the pipeline: the stages, the data pack, the install, the driver | the port stops at a stage, the split's tables differ from the profile's |

**Core or profile.** A core change is a rule in shared code, on by default or behind a
general switch, and it must not change any other game's behaviour. A profile change is a row
in the game's own folder. When a symptom is a game's own, the upstream pattern is: add a
general switch, default off, then set it in the profile. `DM_VK_CUBE_WIDEN=1` `#530`,
`DM_VK_LIN_COPY_BACK=1` `#451`, `DM_VK_BC_DRAW=1` `#310`, `tex_cpu_uncached` `#303`,
`DM_VK_POOL_INNERMOST=1` `#365` are all that shape.

## How to work a symptom

1. **Make it countable.** "It flickers sometimes" becomes "58 of 118 frames bad" with a
   recording; a screenshot misses it. Count the draws the log says were skipped.
2. **Find the first wrong pass.** `DM_VK_PASSDUMP=1` over several frames
   (`DM_VK_PASSDUMP_FRAMES=16`), then `DM_VK_TRACE_PASS=-2` for the pass list and `=n` for
   one pass's draws. The depth is there but the colour is black means the fragment shader
   or its bindings; the depth is empty means the geometry.
3. **Bisect by shader.** `DM_VK_X_SKIPFS=<key>`, `DM_VK_X_CUTFS=<key>`, `DM_VK_X_SKIPVS=<key>`.
   `DM_VK_X_FLAT_VS=<key>:1` paints a draw magenta: if the artefact goes, that draw wrote it.
4. **A/B the switch of the layer you suspect.** `DM_VK_NOCULL=1` for the winding,
   `DM_VK_FRONT=2` for the origin rule, `DM_VK_LRZ_TOUCH=0` for the low-resolution depth,
   `DM_VK_FDZ=0` for the early culling, `DM_VK_X_NOSETC=1` for the descriptor reuse,
   `DM_VK_MDI=0` for the indirect count, `DM_NVN_SAMP_SNAP=0` for the sampler.
5. **Watch what the tool hides.** A pass dump adds barriers and depth reads and can hide the
   bug. `DM_VK_PROF` crashed a game in its own data code: arm it after the load, not at the
   start.
6. **The crash.** Take the fault address: a small constant (null plus an offset) is a
   missing vtable or an object nobody created; a font codepoint is the missing glyph; far
   past a module is a read without a bounds check. Then `DM_CTL threads` and `DM_HLECOUNT`.
7. **The freeze.** `DM_CTL threads` names the parked thread; `DM_NVN_SEQ=120` names what the
   render thread waits for; `DM_VK_CRUMBS=1` names the last pass the GPU finished.

## The switches by symptom

Every switch below is in this fork's registry. The ones that are not are listed at the end.

- **Black and missing**: `DM_VK_BC_DRAW=1|2` (#310), `DM_NVN_CPU_TEX2D_FIRST_USE=1` (#237),
  `DM_VK_UBWC=3` (bit 4), `DM_VK_X_NOTARGET=0` (#194), `DM_VK_SLOT0_FILL=1` (#257),
  `DM_VK_NO_ZEROCOPY=1` (#524), `DM_VK_MEMLOG=1`.
- **Garbled**: `DM_VK_FRONT=0|1|2` (#275), `DM_VK_NOCULL=1`, `DM_VK_MIP_MAX=<n>`,
  `DM_VK_NAN_MINMAX=0` (#121), `DM_VK_SUBGROUP_ONE_LANE=0` (#106),
  `DM_VK_SUBGROUP_PIN=64`, `DM_VK_SPV_DIR` with `DM_VK_SPV_ALT=1`, `DM_VK_X_FLAT_VS`,
  `DM_VK_X_SKIPFS`, `DM_VK_X_SKIPVS`, `DM_VK_X_CUTFS`, `DM_VK_LOG_FS`, `DM_VK_SAMP_LOG`,
  `DM_VK_PIXEL_HISTORY`, `DM_VK_LRZ_TOUCH`, `DM_VK_FDZ=0`, `DM_VK_MDI=0|2|3`,
  `DM_NVN_SAMP_SNAP=0`, `DM_VK_LIN_BACK=0`, `DM_VK_RD_TOUCH=0`,
  `DM_VK_UBO_COMPONENT=1` (#451) - jagged white steps on the hair's edges.
- **Crash**: `DM_VK_VALIDATE=1`, `DM_VK_CRUMBS=1`, `DM_HLECOUNT`, `DM_CTL threads`,
  `DM_PROBE`, `DM_PROBE_WATCH=main:<offset>`, `DM_YIELD_WATCH`, `DM_SHARED_FONT`,
  `DM_MOVIE_TRACE=1`, `DM_AUDIO_DUMP=<file>`, `DM_AUDREN_TRACE=1`.
- **Frozen**: `DM_NVN_SEQ=120`, `DM_NVN_ASYNC=1`, `DM_VK_MT_REPLAY=1`, `DM_VK_PROF=1`,
  `DM_VK_PROF_SLOW=1`, `DM_SLOWFRAME=1`, `DM_SVC_SPIN=0`, `DM_SVC_SPIN_US`,
  `DM_VK_COMPUTE_WARM_MAX`, `DM_VK_NOPREWARM=1`, `DM_VK_POOL_SLABS=0`, `DM_VK_POOL_REUSE=0`.

Upstream only, not in this fork yet:

- `DM_VK_CUBE_WIDEN=1` (#530) - black water, lakes and rivers
- `runtime_shaders on` / `DM_VK_RUNTIME_SHADERS=1` (#505) - shaders assembled at run time
- `DM_VK_POOL_INNERMOST=1` (#365) - a character collapsed to a point
- `DM_VK_LIN_COPY_BACK=1` (#451) - a black portrait on the enrollment paper
- `DM_NVN_AHEAD=1` (#438) - a game that waits for the GPU
- `DM_VK_ZEROCOPY_CHUNK_MB=512` (#451) - the library geometry missing in an intro
- `DM_MOVIE_EOS_SEPARATE=1` (#443) - a movie that never ends
- `DM_VK_DQ_SPIN=1` (#568) - the replay queue's threads spin on a core each, and the phone runs hot

## This fork's own cases

These are this product's own: a case worked out on a phone, with the fix on a branch under
`case/`. The index carries them with the source `nx2androidX` - `memory_search.py search --source
nx2androidX` finds them, and `--symptom` and `--layer` narrow them like the upstream's.
A case whose fix is still only in a case file says so: it is a case without a branch yet.

| The player saw | What it was | The fix | Where it lives |
|---|---|---|---|
| The game dies at the start with `SIGSEGV addr=0x10` | the host refuses the game's own online SDK (it cannot serve Epic's services, so the game plays offline), and the game dereferences the stub's null online object | the profile opts in (`online_sdk 1`, `DM_ONLINE_SDK=1`); the host loads the SDK's code and the packer keeps the NRO | `case/0100BB8017F24000-tmnt` |
| The process dies a second and a half after the launch, before the title screen | the compute warm-up built a pipeline for every compute shader in the bundle, and the driver's shader compiler died on one of the 147 the game never dispatches | the warm-up builds only the dispatched shaders (`vk_compute_pipes.bin`), and a shader that killed the compiler is skipped at the next start | `case/010055D009F78000-fe3h` |
| The game dies with no `CRASH` line at all | the Vulkan driver reset the app's signal handlers, so a fault was a silent kill | the host puts its handlers back right after the driver is done | `case/010055D009F78000-fe3h` |
| A crash one page below the guest's own stack | the gate (the rewriter's svc replacement) ran on the guest thread's stack, and the host's printf frame ran off its end | the dispatch runs on the thread's host stack; the gate's own frame stays on the guest's | `case/010055D009F78000-fe3h` |
| A copy over a chunk's end is dropped, silently | the copy paths asked a pool for a whole range that has no single buffer, found none, and dropped the copy | the copies, the fills and the uniform updates are done in pieces, one per chunk; the three paths that need one buffer are reported instead of dropped | `case/010055D009F78000-fe3h` |
| The whole scene is black, with a NaN in the tone map | a texture builder did not say that its second texture shares the first one's storage, so the sampler read what nothing had written | the builder's pool and offset are answered; the ZCull switch is a no-op | `case/0100E8B028B54000-sky2nd` |
| The game dies at the intro video, in two runs out of three | the guest's own member lookup answered null (the Paris engine's per-type member table has no entry for `RenderTarget2D`), and the game called through it without a check | two 4-byte cuts in the game's own module turn the missing null check into a clean failure, so the video context fails and the game goes on to its menu | `case/0100BB8017F24000-tmnt` |
| Black after the intro movie, the draws per frame falling from 131 to 2 | the game opens a second audio renderer for its movies; the host drives one, so the second renderer's event never fires and the game waits for it | the second renderer gets its own host thread, its own output and its own frame | the phone's case file (Red Dead Redemption) |
| The characters far from the camera are not drawn at all | the backend fakes the SAMPLES_PASSED counter with a constant, and the game takes the difference of two reports: it reads 0 and hides what is far away | **not fixed yet** - the plan waits for the player; the engine upstream fixed the same case | the phone's case file (Red Dead Redemption) |
| The frame rate collapses at an enemy spawn and recovers by itself, and the player is left on a lower step | the engine's own dynamic resolution ran up to native: the game was fast at a low resolution, so it spent the headroom on more pixels (0 new pipelines, 0 texture uploads, the GPU time stepping with the size, and the engine caught calling `nvnCommandBufferSetViewports` at the big size) | `DM_DYN_SCALE=high` in the profile's env rows: the engine reads the GPU clock 4x as fast, believes the GPU is slow, and stops taking the top rungs (the host's own floor still applies) | the phone's case file (Bayonetta 3) |
| The main menu is laid out, but no label carries its text, and a timestamp draws as an empty box | the CPU-filled single-channel glyph atlas was never uploaded: the Vulkan first-use path covers compressed, packaged and linear textures only, so an uncompressed 2D texture needs `DM_NVN_CPU_TEX2D_FIRST_USE=1`. The box is another texture, one that does upload | the same switch, as a profile row (`env`), so it survives a rebuild of the data pack | the phone's case file (STAR OCEAN THE SECOND STORY R) |
| The game aborts 4-5 minutes into the main menu with `FATAL [vk] GPU timeline wait did not complete: -4` | the frame reached the GPU as one submission: the cut waits for the depth attachment to change, and this title keeps one depth buffer for the whole scene, so 1213 draws over 97 passes went into one command buffer - the shape the GPU refuses at that size | the cut stops waiting for the depth change (`DM_VK_X_CUTANY=1` in the profile, so the core default is untouched), and the parts are bounded (`DM_VK_ORD_PARTS` for a frame heavier than 15 x 128 draws) | `case/0100C5601A2E2000-device-lost` |
| A PlatinumGames game (a PKZ archive) is refused at the extract stage | the porter treated "Oodle-compressed" as a GFPAK or a Trinity pack only, so the PKZ pack was sent to the Mac host, although the game's own decoder is in the tree and already runs on the phone | the PKZ entries are decoded one entry at a time through the game's own decoder, over a pipe (a job file over every entry would be the size of the whole RomFS) | `case/01004A4010FEA000-pkz` |
| Unreal's allocator put a small block in the host allocator's tiny class | the allocator asked for the size it was given; the host's smallest class is 8-byte aligned and the engine reads such a block as 16-byte aligned (PhysX faults on it in a long play) | the allocator never asks for less than 16 bytes, and a shrink does not move a live block into the tiny class | `case/0100A3501946E000-uealloc` |
| The build stops at "UE shader decode": the game has no shader code archive | the game cooks with the shared material shader code off, so its shaders are inline in the cooked packages (LZ4 records in the `.uexp`), and the split reads only whole files for a version-8 pak or skips a version-11 one | the reader for a version-11 pak with inline shaders (the layout is read from the pak index alone), and the gate that lets it through without a shader code archive | `case/0100A3501946E000-ue-v11` |
| The game asks for a 62 GB engine region at boot and the host refuses it (`AllocateAddressRegion ... refused`, `0x1803`) | the profile was synced with the engine-wide rules that cap the region (`ue_region`, `ue_malloc`) and this tree has neither; the per-game configuration this tree does support was dropped with the newer profile | the region's size in the profile (`game_args`), the build-keyed allocator cut and gate, the SDK's node-area cut, and the rewriter's boundary test for a gate after a cut call | `case/0100A3501946E000-ue-region` |
