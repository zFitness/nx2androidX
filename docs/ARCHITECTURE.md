# Architecture

nx2android turns a player's own Switch game files into a data pack the phone app runs. The player picks the game's file, clicks **Port**, and gets the pack; the app runs the game from it, with no per-game app of its own. Every game the tool supports is a **game profile**; everything all games share is the **core**.

```
gui/  (PySide6 desktop app)
  │  runs `python -m porter port … --progress json`, draws the JSON events
  ▼
porter/  (headless port pipeline, also a CLI)
  │  inputs → extract → rewrite → shaders → host → data pack   (the legacy --game-apk adds the apk stage)
  │  reuses nxnative/scripts/build_ipa_from_nsp.py's steps (imported, not copied)
  ▼
nxnative/  (our fork of seedds/nxnative + the Android port)
  ├─ dm/host, dm/gfx, dm/tools        core: Horizon host, NVN layer, rewriter, shader split   (shared with iOS)
  ├─ dm/android                       core: Android runtime (Vulkan backend, front end, build.py, mkapk.py)
  └─ dm/games/<title ID>/             profiles: game.tsv + shader tables (+ patches.py) + android.tsv
```

## Layers and their rules

| Layer | Where | Holds | Must not hold |
|---|---|---|---|
| **Core, shared** | `nxnative/dm/{host,gfx,tools,third_party}` | What every game and both platforms need. Android differences behind `DM_ANDROID` / `__APPLE__` / `DM_TARGET`. | Game-specific branches. |
| **Core, Android runtime** | `nxnative/dm/android/` | Vulkan replay backend (`gfx_vk_*`), the OpenGL ES layer for GL games (`gl_android.c`: the device's EGL and GLES driver), the two front ends (`front_player.c` for the app's `:play` process: the machine parts only — the window, the lifecycle, the hold, the physical controller, the settings, the gamepad's layout, the save manager's export and import, the haptics, shaking the device as shaking the controller, the audio, the performance hints; the app draws the gamepad and every panel, the host draws none. `front_android.c` is upstream's APK front: a standalone game APK (a NativeActivity of its own) runs on it — it draws the gamepad itself and reads the game from its own external directory. `build.py` links one of them per shape: `--play` the player's, `--lib` the APK one), the NDK build (`build.py`), the APK writer (`apk/mkapk.py`), the Vulkan shader bundle (`tools/shader_vk.py` makes it; `tools/dmsv.py` holds its format, writes it with each shader's SPIR-V zstd-compressed, and converts a bundle between version 1 and 2; `gfx_vk_shader.c` decompresses a shader when it is first made, with zstd's decompressor in `dm/third_party/zstd`), the profile's Android header (`tools/android_profile.py`), the gamepad's layouts (`overlay_default.tsv`: tablet and phone) and its themes (`themes/`: a sprite pack per design, and `themes.tsv`, the table of which game wears which; `themes/README.md`). | Code that depends on a game: no title IDs, game names or per-game branches in code (comments may name the game a rule was found with, as upstream's do). A game that needs something different gets a profile key. |
| **Game profile** | `nxnative/dm/games/<title ID>/` | Data only: `game.tsv` (upstream keys), shader tables, `patches.py` (per-build rewriter cuts), per-build host rows (`fps_locks.tsv`: engine frame limits in game memory, `hle_fpslock.c`; `ue_malloc.tsv`: Unreal's allocator on a host zone, `hle_uemalloc.c`; `dm/games/game.py` writes them into the profile header), and `android.tsv` (Android keys, below). | Code paths; and the core holds no per-build rows (`tests/arch_rules.py`: no main build ID in core code). |
| **Port pipeline** | `porter/` | The stages that turn game files into the data pack; the toolchain check; the profile registry. Runs headless. | UI. |
| **GUI** | `gui/` | Screens over `porter`: setup check, game file, profile status, options, progress. | Pipeline logic: everything it does, the CLI does too. |
| **ARM Linux launcher** | `launcher/` | The desktop shell of a machine that runs the games itself: the library of the ported games, the build page over `porter.phone_cli`, the settings, and the entries that put a game in Steam's library. Python with GTK 3 (PyGObject), no other dependency. | Pipeline logic (it calls the pipeline) and the runtime (a Linux front end is a separate matter). |
| **Distribution** | `packaging/` | The player's bundle (`build_bundle.py`, PyInstaller): one executable that is the GUI and the Python the pipeline runs the engine's tools with (`nx2android.py`), the committed `nxnative/` beside it, the install guide (`INSTALL.md`). | Pipeline logic or toolchains. |
| **Dev tools** | `devtools/` | Scripts for bringing up a game on a connected device (pushing files, screen recording, soak tests, pass traces), a merged system font for Chinese or Korean text (`make_shared_font.py`), the shader corpus (`shader_corpus.py`: which games' shaders a translator change touches), and the pipeline that publishes a release to the netdisks (`devtools/netdisk/`: one target per netdisk, each with its own credentials and its own thread, so one netdisk that is down does not hold the others back). The device comes from `devtools/device.json` or `NX2A_DEVICE`. | Anything the port needs. |

The game profile is compiled into the host (`game_profile.h` and `android_profile.h`, generated by `build.py`), as upstream does: porting a game builds its host with the player's NDK, which takes seconds.

Vulkan RGBA8/RGBX8 and BGRA8/BGRX8 linear/sRGB textures can share one linear
image per format family over the same storage. New families require memory-backed,
nonvirtual, single-sample 2D or 2D-array textures without explicit layouts,
packaged initialization data or linear-storage flags. Exact descriptions take
priority: same-format plain and packaged/layout peers share in either creation
order. A metadata peer can join an existing family only if its format already
belongs to it; it then closes that family to new formats. Previously established
aliases remain shared, including when their metadata peers arrive later.
Description fields such as packaged block height, dimensions and storage flags
still have to match. Each image has one cache owner for eviction and pool cleanup.
Later CPU-write marks control uploads without changing storage identity. Each
image view keeps the texture's format and alpha mapping.
Texture transfers use the logical texture format: equal-format copies preserve
bytes, sRGB MSAA resolves use a matching-format temporary image before copying
into shared backing, and blits use logical-format temporaries where needed.
Temporaries use the image memory pool (or its dedicated allocation path) and retire
after submission completion. Unavailable temporary storage diagnoses and skips
the transfer; device loss reported by image creation or binding remains fatal. Full clears of shared backing use the format override
when a view supplies one: sRGB clears encode RGB before clearing UNORM backing;
alpha remains linear. Unsupported resolve format mismatches are diagnosed and skipped.

The Vulkan pipeline cache is a writable driver product under `DM_ROOT`, separate
from portable shader assets. Its envelope validates renderer ABI, device/driver
identity, length and digest before driver creation. Legacy raw files retain the
Vulkan version-one vendor/device/UUID check and migrate at the next save. Saves
serialize through one I/O lock and fixed temporary name, publish atomically, and
skip identical content by digest; incomplete snapshots and publication failures
remain retryable. The legacy path cannot provide integrity guarantees absent from
the old format.

Vulkan colour attachments outside the fragment shader's reflected output map
have writes and blending disabled, so undefined outputs cannot overwrite them.
The replacement flat diagnostic fragment shader writes all eight outputs and
keeps those targets eligible; guest channel masks still apply. A draw without a
fragment shader writes no colour.

Vulkan descriptor collection checks each image binding against its 384-entry
scratch array before writing it. A binding that would exceed capacity stops the
host with a diagnostic; valid arrays keep their full reflected counts, including
the existing 32-entry default for a zero count.

The Vulkan descriptor-content cache (`g_setc`) reuses a set within one submission
only when its hash and complete static key match. The key owns explicit layout,
binding, array position, descriptor type/count and every buffer, image and texel-view field, without C
padding. Dynamic buffer offsets stay in the bind command. A bounded 16 MiB CPU
arena holds these keys and resets at the next submission epoch; exhausted storage
or an oversized key bypasses reuse and allocates/updates a fresh set. No pointer
into descriptor-building scratch is retained. The separate per-stage memo
(`set_memo_get`) reuses sets by shader and resource-generation counters, without
constructing or comparing a descriptor-content key.

Immutable Vulkan driver segments share submission scratch only when both their
hash and exact content match in the current epoch. Equality reads a CPU snapshot
of the live c0/c2 prefix (0x648/0x968 bytes), avoiding reads from mapped GPU memory.
A cross-bank hash collision compares the longer prefix, including the shorter
bank's implicit zeros. The 1,024 CPU snapshots cost about 2.35 MiB of content;
GPU-written segments must not enter this cache. This is a correctness guarantee,
not a measured device performance result.

CPU-decoded Vulkan descriptors preflight tracked GPU writes before allocating command scratch or descriptor sets. Later deferred inline updates can cover dependencies from either the open or a prior submission without a wait. GPU-write records stay fence ordered and checks visit only the live suffix, newest first; the newest uncovered dependency determines the one completion wait or internal submission cut. A wait includes copied-pool readback. `DM_VK_CPU_READY=0` disables this readiness path, including linear-target pass endings, for live diagnostic comparisons; it defaults on and is refreshed each submission. This control can expose stale CPU reads and is not a game-profile optimization.

Vulkan pools that cannot use zero-copy keep a CPU snapshot of their synchronized GPU buffer. At completion only bytes changed by the GPU against that snapshot are merged back, preserving independent CPU writes made after synchronization, including writes in the same page. Mapped results are read through a 4 KB CPU buffer before byte comparisons, avoiding repeated byte reads from GPU-mapped memory. The existing cached/uncached pool coverage rules stay in place; a device-to-host memory barrier precedes completion. After a full completion merge, the next incremental sync refreshes only the snapshot blocks it uploads; initialization and untracked pools retain full snapshots. NVN CPU_UNCACHED pools merge only their tracked GPU-write ranges and keep the baseline complete after every merge, as they trusted those ranges before the baseline: an untracked GPU write stays in the GPU copy until a later tracked range over it merges it. A full snapshot at the next sync instead would copy the whole pool before every submission (Unicorn Overlord's 860 MB CPU_UNCACHED pool). The snapshot costs one extra byte of RAM per copied-pool byte and is freed with the pool; zero-copy pools need no snapshot. Games still have to synchronize CPU and GPU writes to the same bytes.

Copied pools can opt into host-cached memory with `DM_VK_POOL_CACHED=1` (off by default). A cached allocation is published only after allocation, mapping and binding succeed; failed attempts release their resources and fall back to the existing host-coherent path (device loss remains fatal). Non-coherent pools flush once per uploaded pool before any submission part is sent: initialization covers the whole mapping, while incremental uploads flush the interval from the first changed block to the last, rounded outward to `nonCoherentAtomSize`. Clean gaps between changed blocks may remain in that interval. A range that reaches the pool tail uses `VK_WHOLE_SIZE` from its aligned start to avoid exceeding the allocation. After the GPU-to-host barrier and completion wait, they invalidate before merging results. With eligible range readback, each pool invalidates one atom-aligned interval spanning its clipped GPU-write ranges, or skips invalidation if none intersect. Other submissions invalidate the whole mapping. Each pool owns and maps its whole allocation; a tail range uses `VK_WHOLE_SIZE` from its aligned offset. Cache-maintenance failure stops the host rather than continuing with stale data. Zero-copy pools and other buffer allocations retain their existing paths.

Zero-copy pools can be lazy (`DM_VK_ZEROCOPY_LAZY`: `0` none; `1` also the 256 MB chunks of larger pools; `2` every page-aligned pool on any device). A lazy pool's pages stay the game's anonymous, swappable memory until the GPU first uses the pool; it then gets its hardware buffer through the slabs and kept buffers as at creation, its pages swapped under the dirty-page tracker 16 MB at a time with no write lost (`nvn_dirty_swap`). Only whole host pages the tracker holds qualify. A pool over memory that another pool covers is never lazy: it is made at once, as pools inside pools are (`gfx_vk_core.c`, "Pools inside pools"); and a lazy pool given its buffer maps it only around the pools inside it, which keep their own pages, as the outer pool's remap does. A pool the host wrote into in the last second (a file read may still be writing into it) is tried again a second later, not counted as a try; that is checked before a slab's slot, a kept buffer or a new one is taken, so it costs no allocation. A failed try is made again a second later, up to 8 in all; meanwhile its draws are drawn with a zero buffer or skipped (`[RED]` lines). A swap that fails part way, or an import that fails after the copy, puts the pages back on anonymous memory before the hardware buffer is dropped (what cannot go back yet is copied back when the game removes the pool). Unset, the choice depends on the device: at the first pool of one chunk the host reads 1 MB of a new hardware buffer and of malloc memory, best of 3 (`zc_uncached`, logged as "hardware buffers: the CPU reads one at …"), and where the hardware buffer reads more than 4 times slower, as every BLOB hardware buffer on a Retroid Pocket 5 (Adreno 650: 1.7–1.9 GB/s against 16–21 GB/s), pools of one chunk are lazy, so pools the GPU never uses (command memory, shader code, descriptors the replay reads) keep cached pages; where it reads at malloc speed (an AYN Thor) none are. `DM_VK_ZEROCOPY_LAZY=0` turns off both the check and lazy pools, and `DM_VK_NO_ZEROCOPY` (every pool copied) skips them too.

`DM_VK_POOL_READBACK_RANGES=1` independently opts cached guest pools into range-limited completion merges for submissions containing only known transfer writes and read-only shader descriptors. Writable/unknown shader descriptors (checked before descriptor memo returns), transform feedback and texture-to-guest-buffer writes disable the mode for the whole submission. Uncertain submissions keep full cached-pool merging and whole-mapping invalidation. Eligible ranges keep the baseline complete for both cached and NVN CPU_UNCACHED guest pools because all device writes are covered. Outside the covered writes the GPU copy and baseline stay unchanged; their next tracked sync overwrites whole dirty blocks from guest memory before refreshing those baseline blocks. Uncertain CPU_UNCACHED submissions merge their tracked ranges, as with the switch off, and initialization/untracked pools still copy whole. Both switches are off by default. New GPU buffer-write paths must either register their full destination or force the conservative fallback.

Vulkan indirect compute dispatches copy their three GPU-written group counts into submission scratch memory in command order. A shader that reads c0 gets a private driver segment, outside the immutable segment cache, with the counts at `c0 + 0x200`; the dispatch reads that same record. Without c0, only a 12-byte record is allocated. Argument records may cross chunks of the same pool, with each chunk's buffer offset preserved. All words are validated before any argument copy, and a transfer barrier makes the record visible to both uniform reads and indirect dispatch. Scratch storage is retained until the submission completes. Direct compute dispatches and other driver segments retain their existing content caching.

The Vulkan backend supplies disabled generic vertex attributes as Maxwell's `(0, 0, 0, 1)`, keeping the float register bit pattern when a shader reads integers. This has separate storage from zero-filled unbound uniform buffers. Enabled attributes with an invalid format or missing buffer retain the conservative zero fallback. The distinction matters when a depth pre-pass uses an absent attribute's W as a displacement weight: a zero weight can disagree with the material pass, fail depth equality and retain colour from older frames.

NVN CPU replay records normally occupy guest command memory. A recording with an empty GPU command pool can reserve a distinct 16-byte lifetime identity in the guest's control storage; its records and opaque handle stay in host storage, and command-byte accounting remains unchanged. Reserved control bytes are reported separately, so the game does not re-grant another live handle's identity. Overflow segments inherit the recording's guest range or control identity and are reused only when the game grants overlapping storage again. Cached handles remain valid after their command-buffer object is finalized; frame age is not a reclamation rule. Control-owned recordings start at 4 KiB even for zero-byte requests and grow only when required by the request or recorded commands.

Android AVC output is copied from MediaCodec into compact NV12 pictures with
ceil-sized chroma planes, preserving odd visible dimensions. Format 19 is I420;
other formats keep the existing NV12 interpretation, with one warning for an
unknown format. Missing/undersized stride and slice height use the frame size,
and invalid crop bounds use the full frame. Layout and last-byte checks still
precede the copy; unsafe geometry and short buffers produce a once-only drop
diagnostic. Picture-allocation failure stops with the AVC allocation diagnostic.
Codec-config buffers are excluded and buffer offsets/lengths are
checked before pointer formation. These checks do not change the decoder choice
or timestamp/queue policy. The manual [AVC probe](../probes/avc_frame_layout.md)
checks synthetic planes and padding; physical-device qualification is separate.

The Android AVC adapter snapshots matrix and range with each queued picture.
MediaCodec color metadata is accepted only for fields declared in the stream's
SPS VUI. Without a colour description with a specified matrix it uses BT.709 at 720 lines and above,
BT.601 below. Without a video signal type it uses limited range. Malformed or
unsupported SPS data uses both defaults.

Stopping a started guest AudioOut returns all pending buffers in queue order,
including any partly played buffer, and wakes the guest's release event even if
the pending queue is empty. Capacity covers all buffers accepted and yet to be
reclaimed. A stop on an already stopped output preserves buffers queued for its
next start. The front end's suspend path still hands playback to the silent sink.
Backend state is atomic because the device callback and silent sink read it
without the lock that serializes lifecycle changes.

The shader translator's existing native-perspective compensation rule accepts either outer operand order in `(input * FragCoord.w) * (1 / FragCoord.w)`. Both alpha depth and material variants must reach the same native interpolated input; leaving the multiply/divide round trip in only one variant can change alpha coverage and retain old HDR colour. The FP32, input-load, FragCoord.w and constant-one guards remain in place.

Opaque NVN sampler objects keep all sampler parameters after an eight-byte header, within the smallest public object's storage. Engines may hash the bytes after that header before calling `SamplerCompare`. Putting filtering or wrap parameters in the skipped header makes different sampler states collide, defeats cache reuse and can exhaust the game's descriptor pool. In Odyssey, duplicate entries accumulated during extended play and repeated scene loads, exhausted the sampler pool and returned sampler ID 0, producing ground grid artifacts. The builder, initializer, comparison, getters and both graphics backends share the same parameter structure; this layout rule does not change filtering defaults.

On Adreno, eligible direct geometry draws separate buffer effects from rasterization
(`gfx_vk_gs_split.c`, `gfx_vk_shader.c`, `gfx_vk_exec.c`). A discarded, single-output
point shader runs the guest memory writes with singleton subgroups; a second shader
retains the original primitive output but removes buffer stores and atomic writes.
A pass boundary and memory barrier separate them. This avoids repeated index-buffer
appends observed with three-output software geometry passthrough on both Turnip and
Qualcomm's driver. The SPIR-V analysis rejects mutable data reaching raster outputs
or control flow, including through local memory, helper parameters/returns and
subgroup operations. Unsupported pointer aliases, extension instructions, XFB,
images and user UBOs retain the original path, as do indirect draws, captured command
blocks, single-output geometry and vertex shaders with memory effects. Devices
without geometry PointSize support also retain the original path. Both immutable shader modules must
exist before either pass is selected. Pipeline keys distinguish the two phases;
the GS buffers must not overlap vertex/index fetch or the VS's direct buffer reads,
and VS textures or indirect handles conservatively retain the original path.
PPE3 invalidates older prewarm records. The effects shader writes PointSize, and
discarded pipelines invalidate cached stencil state before the next raster draw.
The split is off unless a profile sets `env DM_VK_GS_SPLIT=1` (NieR:Automata), and runs only on
Adreno (vendor 0x5143, Qualcomm's driver or Turnip); `DM_VK_GS_SPLIT=0` restores the original path live
for diagnosis. The first-use upload of CPU-filled uncompressed 2D textures in CPU-accessible pools
needs `env DM_NVN_CPU_TEX2D_FIRST_USE=1`. With `env DM_NVN_CPU_NO_ACCESS_IMAGE_FIRST_USE=1`, an
uncompressed 2D colour `IMAGE` can upload initial data from `CPU_NO_ACCESS` storage once without
CPU write tracking. Both paths check for GPU-written aliases.

**Super resolution** (the pause menu's Game tab, `settings.txt` `sr=`; off by default): a window texture whose picture grows by at least a sixteenth when it is fitted to the window (a Switch game's 1920x1080 picture on a 2560x1600 tablet) is drawn into the swapchain image (or the pre-rotated copy) by Snapdragon Game Super Resolution 1.0's edge-direction fragment shader (`dm/android/shaders/sr.frag`: the base bilinear sample, its 12 taps as four `textureGather` reads, a fast-Lanczos kernel stretched along the direction the taps vote for, and the sharpening step, all in one pass; its taps clamp to the picture's crop, so a window or vi crop never reads the texels beside it) instead of the hardware blit, which only bilinearly enlarges. The upscale is one draw in the present's own submission: it reads the game's picture once and writes the composited image once, the overlay draws in the same rendering scope after it, and no intermediate image holds the upscaled frame. It needs dynamic rendering, a 2D single-sample window texture and a view, sampler and pipeline the device grants, and falls back to the blit (with one `[RED]` line) when any is missing. `DM_VK_SR=0/1` overrides the setting for a device run. The filter works on the stored values of a UNORM window texture and on the linear values of an sRGB one. Its Sharpness slider (the pause menu's row, `sharpness=`; 0 by default) moves the three values the published shader fixes: the edge threshold falls from 8/255 to 2/255, so near-flat texture is refined too, the sharpen multiplier rises from 2.0 to 8.0, and its step may pass the neighbouring texels' range (by up to 35 percent of the overshoot) and widen from 23/255 to 70/255. At 0 none of them moves and the shader is as published, with no halo at an edge; at 100 edges ring the way an emulator's sharpness at 100 does. The shader is BSD-3-Clause (`dm/android/shaders/sgsr1.LICENSE`).

## Settings

Every `DM_*` switch the core reads has one row in `nxnative/dm/settings.tsv`, the settings registry: its type (`bool`, `int`, `float`, `hex`, `str`), its default, its scope, when it is read and what it does. Rows are kept in name order.

| Scope | Who may set it |
|---|---|
| `profile` | a game profile's `android.tsv` `env` rows (and the porter) |
| `porter` | the porter, in the data pack's `env.txt` (folders, fonts, `--fps60`, `--no-menu-button`, ...) |
| `app` | the Android app itself (its folders, the player's pause-menu settings) |
| `debug` | bring-up and diagnosis only: `env.txt` by hand or a `ctl.txt` `env` line. A profile that needs one gets the row's scope changed to `profile` first, as a decision in review |

- **Checks.** `android_profile.py` refuses a profile `env` row whose switch has no row, has another scope or a value of the wrong type (`nxnative/dm/android/tools/settings_registry.py`); the data pack refuses such an `env.txt` row from the porter. `tests/test_settings.py` checks that every `"DM_..."` name in the core has a row, that every row is still read, and that the `,ios` mark (read only by the iOS host) is true.
- **At run time** (Android build). `build.py` force-includes `dm/android/dm_settings.h` into every core source. The sources keep plain `getenv("DM_...")` and `setenv` calls; in this build a literal `getenv` reads a per-call-site cache that searches the environment again only after a `setenv` changed a value (`dm/android/dm_settings.c`), and `setenv` logs a `[RED]` line once for a `DM_` name with no row: a typo in `env.txt` or a `ctl.txt` line no longer does nothing silently. The replay thread reads about 50 switches at every submission; each read was a scan of the whole environment. Test harnesses that cut blocks out of core sources, and the iOS host, keep the plain libc calls with the same results.
- **Adding a switch.** Add its row with the code that reads it. New behaviour starts off by default; a profile turns it on; it becomes the default only after the games it reaches were checked.

## GPU driver quirks

A workaround that one vendor's hardware or one driver needs is a row in the quirk table (`nxnative/dm/android/gfx_vk_quirks.c`), not a vendor check where it is used. The table is decided once when the device is made, from the vendor, the driver (`VkDriverId`: Qualcomm's own, Mesa's Turnip, Arm's Mali, ...) and its version, and the log names the driver and every quirk (`[vk] driver qualcomm (...); quirks: lrz_touch on, gs_split on`). Code asks `vk_quirk(VQ_...)`. Each row has a debug switch `DM_VK_QUIRK_<NAME>=0/1` that forces it, to try it on another GPU. A new row stays off for the GPUs no device has shown to need it.

A profile that was tested with Mesa's Turnip says so with `vulkan_driver turnip` in its `android.tsv` (below); the port then packs Turnip as `--vulkan-driver` would.

The command replay is one translation unit, `gfx_vk_exec.c`, kept in one file a section (`gfx_vk_exec_<section>.inc`: state, render_cond, passes, formats, pipelines, descriptors, draws, xfb, copies, walker) so that changes to different sections do not meet in one file. Test harnesses read it with `tests/csrc.py` `unit()`, which puts the sections back in place.

Graphics pipeline creation checks vertex-buffer support for each final Vulkan
attribute format, including integer remaps and formats from prewarm records.
Unsupported core formats are reported once per format across replay and prewarm
workers; out-of-range formats are still reported without indexing the diagnostic
array. Every unsupported pipeline is cached as failed, so draws that need it are
skipped before Vulkan can receive an invalid pipeline. A profile that sets
`DM_VK_SCALED_FETCH=1` (off by default) has one exception: a USCALED / SSCALED
format read by a float input is fetched as the UINT / SINT format of the same
layout and the vertex shader converts each load to float (`vk_spv_vertex.h`,
OpConvertUToF / OpConvertSToF), which gives the same values. Toy Story 3 Complete
Edition sets it: the Adreno 740 has no R8G8B8A8_USCALED, the bone indices of its
skinned characters, which were all skipped. Without the switch, and for formats
the device fetches, pipelines are built exactly as before.

## Frame pacing

How a game's frames are paced is decided in one module, `nxnative/dm/host/dm_pacing.c`: the frame-rate target (`game.tsv` `fps_target`, `DM_FPS_TARGET`), the 30 fps ceiling (`fps_ceiling`, `DM_FPS_CEILING`), the frame step's hold (`fps_hold`, `DM_FPS_HOLD`), presents on the display's ticks (`present_interval`, `DM_PRESENT_INTERVAL`), the Android governor (`DM_ADAPTIVE_FPS`, `DM_FPS_PIN`, `DM_ADAPT_UP_PCT`), the window's rate vote (`DM_VK_WINDOW_GAME_RATE`) and GPU turbo (`DM_GPU_TURBO`). The mechanisms stay where they run (the frame step in `loader.c` and `nvn_fstep.h`, the 60 fps writes in `hle_fpslock.c`, the present interval in `hle_nvn.c`, presents and the rate vote in `gfx_vk_present.c`, the governor in `perf_android.c`) and ask it. At start-up the log has the whole policy in one line (`pacing: target 60 fps (game profile fps_target), ceiling 0, hold on ...`). A profile chooses its policy with one `android.tsv` row, `pacing <preset>` (below). Test harnesses that cut the governor out of `perf_android.c` compile the real `dm_pacing.c` with it (`tests/csrc.py` `pacing_files`).

## Descriptor cache hashing

The Android backend's descriptor caches (`gfx_vk_exec_descriptors.inc`) find candidates by hash. Two kinds of path decide reuse differently:

- **Exact.** The content-keyed set cache (`set_key`) and driver segments built and hashed (`drv_shared`'s content path) compare every byte of a candidate before reusing it, so a collision only costs a miss. Long inputs use a four-lane hash so the replay thread does not wait on one dependent multiply chain.
- **Hash only.** Two paths reuse on a 64-bit hash alone, to avoid collecting or building anything:
  - a stage set found again by its bindings (`rmemo_take`, keyed by order-free hashes of the stage's slots, the shader and its constant buffers' buffers);
  - a c2 driver segment found by the hash of its slots (`drv_shared` with `DM_VK_C2_FAST`).

  `DM_VK_X_SETVERIFY=1` collects one memo hit in 64 anyway and compares it, builds every c2 segment found by hash again and compares its bytes, and logs a `[RED]` line on any difference; its `memo verify` line counts both checks. `DM_VK_X_NOSETMEMO=1` and `DM_VK_C2_FAST=0` turn the two paths off for an A/B.

These hashes stay in the process: they are not persisted and do not change the Vulkan pipeline-cache identity.

## Game profiles on Android

A profile is offered for Android when it has an `android.tsv`; the profiles without one (upstream's games, synced in bulk) show as "not ported": an experimental port can still try them ([UPSTREAM_PROFILES.md](UPSTREAM_PROFILES.md)). The app does not carry the profiles - they are half a gigabyte of shader tables - so the player imports a package of them into their own folder (the environment check has the button), and the porter finds them there (porter.profiles asks the layer for the profiles the tree does not have). The tools that look in `dm/games` find nothing on the phone: the rewriter reads a profile's `patches.py` (its cuts, without which a game runs on the wrong allocator) only there, and so does the host's profile header. A port therefore copies the imported profile into `dm/games` before it reads the profile and removes the copy when the port is done, so `dm/games` keeps only the profiles the tree itself has. `android.tsv` holds, one `key<TAB>value` row each:

| Key | Meaning |
|---|---|
| `status` | `playable` (tested end to end on a device), `wip` (plays on a device, but parts are missing: README.md's Games table says which), `boots` (starts, not playable yet) or `experimental` |
| `tested` | `<version> <device>`: the version and device the status was checked on |
| `package` | The app's package name (default `org.nx2a.t<title ID in lowercase>`) |
| `orientation` | `landscape` (default) or `any` |
Shaders captured on the device: a game can set shaders whose code is in no game file (Xenoblade Chronicles 3, hundreds: effects and model materials), which the split cannot find. When a draw needs a shader the bundle lacks, the app saves it to `captured_shaders/<key>.bin` in its files folder (`gfx_vk_shader.c` `vk_shader_missing`; the draw is skipped this time). A port first pulls that folder into `<build folder>/android/captured_shaders/` — in the app the porter reads the app's own files folder (no adb needed), on a PC it reaches the device over adb, with or without `--install` — which is kept from port to port, and `shader_vk.py --capture` translates it into the bundle. These shaders are not in the profile's tables: the tables stay what the game files give. So such a game draws everything only after it has been played that far once and ported again.
| `romfs` | `raw` (default) or `zstd`: the data pack's RomFS files that compress are stored zstd-compressed and read back by the host ("Compressed RomFS" below) |
| `vulkan_driver` | `system` (default) or `turnip`: the Vulkan driver the profile was tested with. With `turnip` the port packs Mesa's Turnip (`porter config turnip <libvulkan_freedreno.so>`, else a build under `tools/turnip`) as `--vulkan-driver` would, and says so in red when it finds none; `--vulkan-driver system` keeps the device's driver |
| `pacing` | the frame-pacing policy in one row: `adaptive` (default: the profile's `fps_target`, the governor steps between 60, 40 and 30), `steady` (no governor steps), `fixed60`, `fixed30`, `game` (the game's own limit, no governor). Each is `env` rows before the profile's own (`android_profile.py` `PACING`); a profile may not also set one of them (Frame pacing, above) |
| `readme_image`, `readme_tag`, `readme_note` (`readme_name`) | the game's cell in README.md's Games table: its device frame shot (`docs/images/`), the nx2android version it was tested on (`v0.4.0`), the line under the name; `readme_name` when the table names the game otherwise than `game.tsv`. `python docs/gen_tables.py` makes the table (and the checklist's marks and count) from these rows; `tests/test_docs_tables.py` fails when the files differ |
| `env` | `<KEY>=<VALUE>`: a host switch the game needs on Android, written to the data pack's `env.txt`; only switches of scope `profile` in the settings registry (Settings, above) |
| `overlay` | `<tablet\|phone> <control> <x> <y>`: moves one on-screen control of that layout (`dm/android/overlay_default.tsv`) to x, y as fractions of the window, compiled into `android_profile.h` |

Per-build knowledge stays where upstream keeps it: the rewriter's cuts in `patches.py` / `dm/tools/sdk_patches.py`, keyed by build ID.

The rewrite warns when an external (including provisional) profile contains a
`patches.py` that the rewriter will not load. The warning also appears on cache
reuse. Registered `dm/games/*/patches.py` files and explicitly supplied
`DM_PATCHES_EXTRA` files retain their existing behavior; external files are not
executed automatically. The standalone rewriter's `DM_PATCHES_EXTRA` accepts
`CUTS` only; the Android porter replaces it with its generated FPSLocker cuts.
The warning directs porter users to register their build-specific patches.

## Cheats

The host runs the Atmosphère-format cheat codes (the dmnt cheat VM of Atmosphère 1.12.1) that the cheat sites share: the file of a build is named by the first 16 hex digits of main's build ID, and the host loads the file of the build it runs (`dm/host/hle_cheats.c`).

The files are not ours: the app carries none. They come to the phone two ways, and both land in the app's own folder (`files/cheats/<title ID>/<build ID>.txt`, the app's private storage - a rebuilt data pack does not touch it):

- **downloaded** from the community libraries, one build at a time (the drawer's download row). Two libraries are asked, in order, and the first one with a usable file wins (nothing is merged across them: two files that patch the same place would fight):
  - **switch-cheats-db** (the aggregator): one JSON file per game (`cheats/<title ID>.json`) with one section per build; the app picks that section and writes the cheats out as one Atmosphère file.
  - **MyNXCheats** (one author's own collection): the files are already in the Atmosphère format, but the folders are named by the game, so the repository's file tree (the CDN's index) says which file belongs to which game and build; the file is written out as it is.
- **imported** from a zip the player picked (**Settings -> Environment -> Cheats -> Import zip**), the same way the game profiles are imported. The zip holds one file per build, and the files are found by their names (the file is named after the build, the game's title ID is a folder in the path), so the community's own package layouts (`titles/<title ID>/cheats/<build ID>.txt`) are imported as they are. Our own repository (`zFitness/nx2a-cheats`) collects the community's files and cuts such a package; the scripts that do it live in this repository (`devtools/cheats_pull.py`, `devtools/cheats_zip.py`).

The app asks the host for the running build (`dm_cheats_build`), so the file is the one of the build the game runs. A cheat file belongs to one build, so a file of another build is never used (it would write the wrong places). The file's own credit (who wrote it) is shown under the list.

The resolution patches are skipped: the app has its own render scale (the drawer's), and a community patch of the same setting would fight it. A file that holds nothing else is not written at all - the player sees that the library (or the imported package) has nothing usable for that build.

The player turns the cheats on in the game's drawer (the "Cheats" tab); the app then points the host at the folder (`DM_CHEATS`) and the host loads the file of the build it runs. The host runs the enabled cheats once per game frame (at the game's own present, `hle_nvn.c`), and it remembers each cheat's switch in `<build ID>.enabled` beside the file.

A cheat may write the game's own code (a community cheat that patches an instruction). The host seals the code pages read+execute after loading them, so the write path opens the write bit on the pages it needs, writes, and flushes the instruction cache - the execution bit never goes off, because a thread that is executing there would fault and take the game with it. Two places stay off limits: the host's own pages (the key page, the patch area with its stubs) and the words the rewriter changed or hooked (`sites.tsv` / `cuts.tsv` / `obs.tsv`, read into the module's table: the observation gates are in a table of their own, the rewriter keeps their sites out of `sites.tsv`): writing there would break the game's own code in a way nobody can undo, so such a cheat is refused and turned off with the reason. Everything else follows the reference: a failed access is ignored and retried (a pointer the game has not set yet), the registers reset once per pass, and one cheat that cannot run does not stop the others.

## The port

`python -m porter port <game file> -k <prod.keys>` (the phone app's **Port** action) runs these stages. The slow ones (extraction, rewrite, shader split, the translator build, the Vulkan shaders) keep their output with a key of their inputs and are skipped on the next run when the key is unchanged; the host build is incremental (`build.py`), and the data pack is made again each time. The pack records `player_api_revision`, the manual APK/player interface revision from `porter/revision.py`. Gradle generates the Android constant from the same file. Increment it only for incompatible APK/runtime interface changes; ordinary engine fixes, game patches, shaders, APK versions and payload changes do not invalidate installed games. The manifest also records `profile_h` (the hash of the `game_profile.h` the host was built from — the alias headroom is in there) and `no_lsfg`: together with the interface revision this is the pack's **build fingerprint**; the runtimes folder's `build.json` carries the same three. The app rebuilds the runtime itself when they stop matching, during the game page's loading phase - there is no separate update button or foreground service any more. Completed packs run without source files or a build workspace.

`python -m porter rebuild-runtime <pack>` compiles the current player runtime using the final `profile/<titleId>/game.tsv` and `android.tsv` saved during the original port. It does not read keys or source games, or regenerate mods, shaders or RomFS. Compiler switches follow the current APK policy. With `NX2A_RUNTIMES` set (the phone app) a fresh runtime and its managed hooks are written into the runtimes folder, one folder per title ID, each with one atomic rename, and the build marker goes in last - a runtime without its marker is rebuilt, never loaded half-known; the manifest's `host` key comes out (the pack reads as the new layout) while the management fields (`profile_h`, `player_api_revision`) still come back. Without the folder (the desktop tool, the upstream engine) the runtime goes back into the pack's own places as before. Failed or interrupted attempts leave the previous runtime and game data intact. The rebuild runs from the app's own game page now: there is no separate modal state or foreground service, and the profile pairing rules are unchanged (a changed profile asks before it rebuilds, `--allow-profile-drift` is the player's own "use the current profile").

Legacy packs without saved profiles cannot use this path and receive a clear suggestion to port again. Compilation failure offers retry or a full re-port; load failures and identifiable native crashes also suggest a full re-port without claiming that old data caused the error. Full re-port still requires source game files and keys, so keeping a backup is useful. Saves, user settings and selected drivers are retained during runtime updates.


Module rewriting uses the porter's `--jobs` count, passed as `J` to the shared
NSO/NRO rewrite scheduler. It must be a positive integer: `--jobs=1` runs one
module at a time. Direct callers that omit `J` retain the CPU-based default
(at least two workers, or four if the CPU count is unavailable). This limits
concurrent processes, not the memory used by one module. Changing the count
does not invalidate completed rewrite outputs.

Shader reuse checks the generated bundle against its receipt. Windows uses size
and modification time for the fast path. POSIX also checks change time and file
identity. A metadata change triggers a digest check. On Windows, a same-size
edit that preserves the original modification time can pass the fast path.
Translator output trees are checked by relative name, size and hash, including
dependencies. The exporter records expected keys and stages and failed keys and
reasons in `android/shaders.dmsv.report.json`. Individually valid products from
interrupted batches can still be included. The porter accounts for every
expected shader and requires at least one emitted shader before publication.
Partial bundles are reused when their inputs are unchanged, with the failure
count in the receipt note. The report is published before the receipt and its
digest is checked on reuse. A changed input or missing or changed report
triggers translation. The shader key covers the three Android export helpers
(`shader_vk.py`, `dmsv.py`, `shader_products.py`), the shared shader tools, profile,
captures and translator. The new receipt format rebuilds existing ports once.

Shader bundle export keeps validated SPIR-V modules in their translation files
and loads at most one compression batch of `jobs` modules at a time. Each batch
is written before the next is loaded; uncompressed export reads one module at
a time. The sorted entry table and reflection remain in memory; payload memory
depends on individual module sizes and the job count, rather than the aggregate
SPIR-V. The private staged bundle is read back one module at a time before atomic
publication. Version 1/2 layout, compression settings and byte comparison are
unchanged.

| Stage | What | Output (in `<game folder>/<title ID>_build/`) |
|---|---|---|
| inputs | Find the base game, updates and DLC (NSP / XCI / NSZ / XCZ files, regardless of extension case) next to the file that was picked, match the profile, pick the version; check the game folder's drive has room (about twice the picked game's files, the other games in the folder not counted, NSZ / XCZ counted decompressed and once more for their NSP, less an earlier port's build folder; the app's mode asks for once: its pack holds no RomFS, it points at the build folder's own) | |
| decompress | Only with NSZ / XCZ files that a stage below will read (a reused extraction reads none): each becomes an NSP (an XCZ: an NSP of its secure partition, with or without the leading 0x1000-byte card key area), its NCZs expanded and encrypted again with the keys their section tables carry, every NCA checked against its SHA-256 name (`porter/dumps.py`). Deleted once the DLC are extracted, or when the port fails | `tmp/dumps/` (temporary) |
| extract | `nx_extract` (built with the .NET SDK); XCI cards may also retain their leading 0x1000-byte key area, and an NSP's PFS0 header takes precedence over card-magic bytes in its payload | `extract/<version>/{ExeFS,RomFS}`, `aoc/` |
| system data | Only for a profile with `sysdata` and a `--firmware` folder (the player's own system content files, `.nca`): `nx_extract --sysdata` writes each title's RomFS; without the folder the port says so in red and the host's stand-in is used (for the font titles, the host's own stand-in fonts) | `sysdata/<title ID>/` |
| 60 fps | Only with `--fps60` (below): the profile's own cap, or the build's FPSLocker-Warehouse config converted for the host | `android/fpslock/{fpslock.tsv,patches.py,<build ID>.yaml}` |
| rewrite | `patch_nso.py` with `DM_TARGET=android` | `android/patched_<version>/` |
| shaders | `shader_split.py` (the DLC's own shaders too, `aoc/` given as `DM_SPLIT_AOC`), then `shader_vk.py` (SPIR-V, each module zstd-compressed in the bundle: 3.5x smaller; `tools/dmsv.py` holds the format) with the translator built from the repository's source (`dm/gfx/tools/dmsh_xlate` over `dm/third_party/ryujinx`, once per player in their nx2android folder), plus the shaders captured on the device (below). Shaders in Oodle-compressed archives (Pokémon Legends) are decoded first, with the game's own decoder: on the device the port already uses, or on the phone itself when the porter runs there | `shader/pkg`, `android/shaders.dmsv`, `android/captured_shaders/` |
| host | `dm/android/build.py --release` with the player's NDK (`--debug`: a development build, debug information and `DM_CTL`) | `android/host/libdmhost.so` (`android/host-debug/`); with `--app`: `libdmplay.so` instead (the host statically linked with the player's JNI entry, the app's `:play` process loads it) |
| apk | The legacy path only (`--game-apk`): `dm/android/apk/mkapk.py`, signed with the player's own key, with the game's gamepad theme only (`dm/android/themes/themes.tsv`: its pack, else the ergo pack) as `assets/overlay/` | `<out>/<App>.apk` — unmaintained in this fork, and it has no launcher page any more (the game is the entry) |
| data | The files the app reads from the pack's own folder | `<out>/<App>-data/{mods,RomFS,aoc,sysdata,shaders.dmsv,nintendo_ext.ttf,env.txt,settings.txt,nx2a-data.json}` (+ `fpslock.tsv` with `--fps60`); the button-icon font is made in `android/font/`; the app's mode (`NX2A_RUNTIMES` set) puts **no runtime in the pack** — the host and the loader's four hooks go into the app's private runtimes folder with their `build.json` marker instead, and the manifest carries no `host` key (that key is what marks a pack as the older layout); the gamepad's theme (`overlay/`) and the icon (`icon.png`) are named in the manifest. Without the runtimes folder (the desktop tool, the upstream engine) the runtime stays in the pack as before (`host/libdmplay.so`, the hooks beside `drivers/`) The manifest (`nx2a-data.json`) names the game, its package, the version, the device features it needs and the profile's own `status` (`playable` / `wip` / `boots` / `experimental`): the app shows an experimental port as such, so a player is told it was never brought up on Android. The game's Chinese and Korean text needs the console's shared fonts 1-4, which the host has none of: the shared font is the one the tools ship (`dm/tools/shared_cjk.ttf`, built by `dm/tools/cjk_font.py`) or the player's own (`--shared-font`), and `env.txt` points at it (`DM_SHARED_FONT`); with `--app` that is the file in the payload, so the pack does not carry it, and the desktop's mode puts it in the pack, which the install copies into the app's files folder. With `--app` the pack holds no RomFS: `env.txt` points at the build folder's own (`DM_ROMFS=<path>`) and the manifest says the same (`romfs_at`), so the same game is not stored twice on the phone; the app then needs that folder to run the game, and the work folder cannot be cleared on its own. With `android.tsv romfs zstd` the RomFS is stored zstd-compressed instead of raw (the packer writes the packed files into the build folder, `env.txt` says `DM_ROMFS_ZSTD=1`, and the host reads them back) |
| install | The legacy path only (`--game-apk`): `adb install`, the profile's `requires` checked against the device, the data pack pushed (optional); the PC tool's `--romfs-at` reads the RomFS from a folder already on the device | |

An NSP or XCI contains NCA entries. If LibHac cannot open an entry's header,
`nx_extract` names both the input container and the NCA entry, includes LibHac's
reason, and stops with exit code 4. This diagnostic does not establish whether
the input or the keys caused the rejection. `--allow-damaged` does not bypass
header failures; filesystem integrity errors keep their existing handling.

The shader split orders each RomFS and the DLC by their forward-slash source
labels. When several files contain the same shader, Windows and POSIX now
choose the same first source for the shader map (issue #461).

RomFS in the data pack is hard-linked to the extraction when the volume allows it, so it takes no extra space. On the phone it is not copied at all: the pack points at the build folder's own copy (`DM_ROMFS`), so a game is stored once, not twice.

Generated NVN APKs declare Android Performance Game Mode through `android.game_mode_config`
and the Android 12 metadata fallback (`mkapk.py --game-mode-performance`, selected
by the porter's existing graphics classification). GL ports and standalone APK
writer calls without that flag retain OEM interventions and make no opt-in claim.
The native activity reads the selected mode
on every resume (API 31+). Performance keeps the game's requested presentation
period instead of the host's adaptive 60/40/30 downshift, still bounded by the
profile's `fps_ceiling` (lifted by `--fps60`); Standard restores the
default policy with fresh frame history. Explicit `DM_ADAPTIVE_FPS` or a valid
`DM_FPS_PIN` takes precedence. The presenting thread samples both overrides on its first frame and every 30 frames afterward. Guest frame acquisition reads the cached atomic policy. Mode changes take effect on the next presenting frame using the cached overrides, with fresh adaptive history. A profile ceiling keeps its pacing step so ADPF load hints exclude the present-thread wait imposed by the cap. The mode does not
unlock an engine cap, force GPU/CPU clocks or override thermal limits; device
performance still needs measurement. Declaring support disables OEM interventions
for that mode, as required by the [Android Game Mode API](https://developer.android.com/games/optimize/adpf/gamemode/gamemode-api).
Battery mode is not declared supported. Older Android or an unavailable service
retains the default policy. A re-port/reinstall is needed to add the declaration
to an existing APK; selecting a mode does not rewrite an old APK.

`--vulkan-driver <lib.so>` packs a Vulkan driver (Mesa's Turnip) in the APK under a `lib*.so` name, beside libadrenotools and its hook libraries, and the data pack's `env.txt` names it (`DM_VK_DRIVER`; `gfx_vk_core.c` loads it through adrenotools, and falls back to the device's driver when it does not load). `python -m porter driver <lib.so> [--package …]` changes the driver of a port already on the device without the game's files (`porter/driver.py`): the installed APK is pulled, written again by `dm/android/apk/apkdriver.py` with the new library in place of the old (every other entry kept, page-aligned and signed again with the player's key by `apksign.py`, the ZIP writer and v2 signer `mkapk.py` uses), installed over the app (its saves stay), and `env.txt`'s `DM_VK_DRIVER` row names it; `--system` drops the library and the row (the device's driver). An APK ported without `--vulkan-driver` has no libadrenotools and is refused: it needs one port with a driver first.

`python -m porter host [--package …]` brings a port on the device to this checkout's host without the game's files (`porter/host.py`): `libdmhost.so` is built again by `dm/android/build.py` from the repository's profile (the title ID from the data pack's `nx2a-data.json`; a debug build for a debuggable app) and put in the installed APK by `apkdriver.py --host`, the driver library kept, with the overlay's font and its license files (`assets/font/`, `pipeline.ui_font_assets`; `--asset` replaces or adds them), which an APK ported before the font came lacks. The game's rewritten modules on the device must fit it: `mods/build_src.sha256` (patch_nso.py) holds the hashes of the rewriter and the patch files that made them, and when any of them differs from this checkout's (the rewriter, `sdk_patches.py`, the game's own `patches.py`, or patches registered for it since) the update is refused and the game needs a port again; other games' patch files are keyed by their own build IDs and do not count, and a changed `sdk_patches.py` does not either when it and the game's `patches.py` still give each of the port's modules (by the build ID in `mods/<module>.cuts.tsv`) the cuts and observation gates its `.cuts.tsv` and `.obs.tsv` list, as after a cut added for another SDK build. The port must also have been made from the repository's profile, since `DM_GAME_MEM_ALIAS` and the rest of `game_profile.h` are compiled into `libdmhost.so`: its version (`nx2a-data.json` `version`) must be one the profile's `build` rows register, and `nx2a-data.json` `profile_h` (the sha256 of the `game_profile.h` the port's host was built with, which `porter port` writes) must equal this checkout's, or differ from it only by defines added to `game_profile.h` since then (`ADDED_DEFINES` in `porter/host.py`) that are at their off value, which change neither the layout nor the data pack (a new define that is off by default goes in that list); a port made on Windows before game.py wrote the header as bytes hashed the same header with CRLF newlines (still UTF-8), and that form is accepted too; a derived profile's port (a version the profile does not register, with its automatic alias headroom, issue #26), an `--alias-headroom` port, any other profile change since and a pack from before `profile_h` are refused, and the game needs a port again. The title ID must be 16 hexadecimal digits. Nothing else in the data pack changes (`env.txt`, `shaders.dmsv`): a new shader translator or profile row needs a port again.

## The ARM Linux launcher

`launcher/` is a small desktop shell for a machine that runs the games itself: a library
of the ported games, a build page that runs the same pipeline the phone app runs, and the
settings that say where the runtime and the library are. It is Python with GTK 3
(PyGObject) and nothing else, so a machine needs only its `python3` and `python3-gi`
packages; the interface is sized by the screen it finds (a phone-sized one gets bigger
controls and at most two cards in a row).

- **The library** is a folder of data packs, one folder per game (`<data folder>/<title ID>/`).
  The pack is the truth: its `nx2a-data.json` says what the game is, its `icon.png` is
  the icon, and the game's own executable lives beside them. There is no index beside
  it, so a pack copied in by hand shows up on its own and a folder deleted by hand is
  simply gone. A game that cannot be read (a broken manifest, an icon that is not an
  image) still shows its name and version. A build writes into a staging folder under
  the data directory and the finished pack is moved in; a build that fails or is
  cancelled leaves nothing behind, so only a finished game is in the library.
- **The build page** runs `python -m porter.phone_cli` — the pipeline the phone app runs,
  this machine being the device — and reads its JSON event stream: the stages, the
  progress, the log. Its layout follows the desktop tool's build tab (`gui/app.py`):
  the game file and the card that says what it holds, the same options (the phone's
  install, device, SD card and package fields and the Vulkan driver are not needed
  here), the stage list with the time each stage took, and the log.
- **Running a game** starts the game's own executable with the pack's folder as the
  working directory and `DM_ROOT` pointing at it; the pack's own `env.txt` and
  `settings.txt` are read from there, as on Android. The pack is self-sufficient: it
  carries the executable, so copying a game folder copies the game.
- **The app menu and Steam**: the desktop entry (written by the player's button, so the
  system's application menu shows the game) and Steam's own shortcuts file (the binary
  key-values format, read and written here without a dependency) both point at a small
  script in the pack's folder that sets the environment and starts the game. Steam keeps
  that file in memory and writes it back when it quits, so nothing is written while
  Steam is running.

## The ARM Linux package

`packaging/arm-linux/build_appimage.py` packs the ARM64 Linux line into one file: the
launcher, the port pipeline and the engine tools. The interface is GTK, so the package
runs on the machine's own Python with PyGObject (`python3-gi`): the package carries the
code, not the toolkit. The machine needs `python3` and `python3-gi` installed, nothing
more of ours.

- **`usr/` is a trimmed repository root** (`launcher/ porter/ nxnative/ phone_tools/`),
  which is what makes the pipeline behave inside the package exactly as in a checkout: it
  finds its own root and the engine beside it.
- **The package carries no glibc, no Python and no display stack**: those are the system's
  (the interpreter, the GTK libraries, the X11/Wayland session, the Vulkan driver, the
  fonts). The pinned downloads (the AppImage runtime) are fetched once and kept in
  `.cache/`, each checked against its SHA-256.
- **A font travels with the package** (Noto Sans SC, plus a monospace face): a machine
  may have no fonts at all, and `AppRun` writes a fontconfig configuration that points
  at them while keeping the machine's own fonts in use.
- **The game profiles are not in the thin package** (600 MB raw): the player imports the
  release's profile package from the launcher's settings, the way the phone app takes
  them. The full package (`--with-profiles`) carries them.
- **The package is read-only** (it is mounted at a new path on every run), and the builds
  write beside their sources, so the launcher copies the engine tree to the player's own
  folder on the first run (the profiles stay linked to the ones in the package) and points
  the pipeline at that copy (`NX2A_NXNATIVE`).
- **The player's data stays outside**: the library, the settings and the imported profiles
  live in the user's own directories.

## Android text input

`hle_swkbd.c` handles the guest's encodings and length limits. The Android front end dispatches Java keyboard requests through `keyboard_android.inc`. Each request runs JNI on a short-lived host pthread because a non-main guest thread can run on a stack outside its pthread stack range. The guest joins the worker before using the result or falling back to the controller keyboard when the optional Java method is absent.

## Saves

The app keeps the game's save in its internal storage (`$DM_SAVE`, and `<DM_SAVE>_device` for a game that mounts a device save too: `hle_fs.c`), which a reinstall keeps, an uninstall deletes, and adb cannot read in a release build (it is not debuggable). The save manager (`dm/android/saves_android.c`) copies it in and out through the app's files folder, which adb, porter and the PC reach without a permission:

- `saves/<YYYYMMDD-HHMMSS>/`: one export, the save's files byte for byte, as a console's save tools copy them (so a console's save folder imports as it is, and an export goes back to a console the same way); `saves/<name>.device/` beside it holds the device save.
- **Export save** (the pause menu's Game tab) copies the committed save (never `.work`: a transaction in flight is not a save) on a thread of its own, through a hidden `.part` folder renamed when whole, and starts again if the game commits meanwhile.
- **Import save** opens a picker of the folders in `saves/`, newest first. The import is applied at the next start, before the host mounts anything (`ANativeActivity_onCreate` → `dm_saves_start`), so it never meets a commit: the menu writes `saves/import.txt` and the app ends. At the start the save it replaces is exported first (`<stamp>-before-import`), the folder is copied to `<DM_SAVE>.import` and swapped in with one `renameat2(RENAME_EXCHANGE)`.
- `porter saves` (the GUI's **Saves** tab) does the same from the PC: `apps`, `list`, `export [dest] [--name …]` (a fresh export: the app is stopped and started with `saves/export.txt`, exports and ends without starting the game, then the folder is pulled), `import <folder or .zip>` (pushed under a hidden name, renamed, named in `saves/import.txt`, and the app started to apply it). Each request carries a token the app writes back in `saves/result.txt` with its outcome.
- The files are not changed. A save made on a console belongs to that console's user; a game that keeps its user's id inside its own files (Animal Crossing: New Horizons, issue #16) reads it as another user's, since the host's one user (`hle_account.c`) is not mapped into it.

**The library panel's saves** (`SaveBackup.kt`, `SaveShare.kt`): the panel does not go through the save manager's requests. In the player's mode the host runs inside the app (`dm_java_start` is given the app's own files folder and the title ID), so the live save is the app's own file and the panel works on it directly - an export writes a package, an import applies one, and neither starts the game.

- A package is a zip in `Download/nx2android/`, named `<game>-<titleId>-<stamp>.zip`: the save's files under one folder (the layout the save manager copies out, so a console's save folder is the same thing), with the device save beside it as `<name>.device/` when the game has one. The panel lists the packages and shares one through the system share sheet (a `FileProvider` URI; a `file://` URI is refused since Android 7).
- An import picks a package from anywhere (the built-in file picker), and a package whose name carries another title ID is refused. A package from elsewhere is not trusted: an entry whose path points out of the folder is refused, and the unpacked size is capped.
- The save an import replaces is kept first, as `<stamp>-before-import` in the data pack's `saves/` folder - the name the save manager gives its own backup, so one folder holds every snapshot of the game. The panel lists those backups and can restore, share or delete one.
- The game has to be closed before the save is touched: the host writes it while it runs (the `:play` process's presence is polled).

The save manager keeps its own path for the two callers that cannot work on the save themselves: the host's pause menu and the PC. Its requests (`saves/export.txt`, `saves/import.txt`) and its answers (`saves/result.txt`) are unchanged.

An Android shader profile can set `android_dynamic_slots` to `on` in `game.tsv` to bind separate texture, sampler and texel buffer arrays from the driver slots (requires `tex_dyn_slots on`; FINAL FANTASY RESONANCE's Niagara particle parameters are texel buffer arrays). `android_subgroup_size` selects the translator's subgroup size; its default is 128. For a packed texture handle read directly from game memory, `android_shader_handles.tsv` gives the shader key, guest handle, replacement slot handle and expected number of sites. The shader builder applies these rules to the translated game shader and checks the site count. Paper Mario: The Thousand-Year Door uses this for the animated save block on Adreno 840.

