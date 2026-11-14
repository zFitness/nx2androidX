# BOTW lighting and Vulkan replay staging report

This draft preserves a tested portion of the Snapdragon 865 / Adreno 650 investigation.
It does **not** establish stable native 30 FPS or fix `VK_ERROR_DEVICE_LOST`.
The runtime changes are based on `zFitness/nx2androidX` Android commit `f4ffbbf`.

## Included changes

- Enable the existing CPU texture flush/dirty upload tracking for BOTW. A CPU-filled
  256 x 32 x 16 RGBA16F lighting volume was sampled before its first GPU upload.
- Preserve the BOTW depth-clamp fallback on devices without depth-clip control,
  check AHardwareBuffer import support, and propagate image-view usage to framebuffers.
- Order overlapping deferred uniform copies and the presentation clear/blit writes.
- Conservatively bound constant-buffer reads using SPIR-V analysis, index ordered
  deferred updates, and reuse uniform shadows with overlapping-write invalidation.
  Unknown shader access patterns retain the full bound range.
- Prefer cached coherent scratch memory when available, with the existing fallback.
- Add opt-in `DM_VK_UPLOAD_SNAPSHOT=1`: snapshot 4 KiB to 64 MiB texture sources before
  hashing/deswizzling. Allocation failure uses direct reads; all mips/layers are kept.
  Upstream sparse textures keep their page-table copy path.
- Correct non-mipmapped sampler minimum LOD and command-part budget accounting.
- Add optional bounded frame/fence timelines, upload/first-use probes, synchronization
  labels, recorder profiling, and device-fault reports. Diagnostic modes remain off
  unless explicitly enabled. Diagnostic timing must not be compared with clean runs.

The latest upstream implementation of block-compressed attachment stand-ins and
padding-independent descriptor hashing is retained rather than replaced.

## Explicitly excluded

The latest UBO/SSBO binding snapshot candidate (`DM_VK_BIND_SNAPSHOT`) is absent.
Its small static gain was not qualified in movement, and a movement run faulted.
That association does not establish causation. Whole-command copies, asynchronous
replay trials, forced recorder sleep, draw-skipping guards and continue-after-loss
experiments are also excluded. No game binaries, keys, saves or GPU dumps are included.

## Historical evidence (before the upstream rebase)

| Measurement | Result | Interpretation |
| --- | --- | --- |
| 169 content-matched textures, at least 64 KiB each | Sum of per-texture median CPU preparation times: 253.868 to 79.414 ms | About 69% less preparation time in this sample; not a frame-rate gain or per-frame saving |
| Clean 1.0-scale turning windows | p50 33.71-34.51 ms; p95 37.45-39.37 ms; max 48.34 ms | Near 30 in that scene, not stable 30 |
| Clean 1.0-scale movement windows | p50 33.15-33.56 ms; p95 36.23-37.71 ms; max 45.94 ms | Route-specific result |
| Later demanding distant view | p50 38.75-39.48 ms; p95 42.69-45.15 ms; max 79.47 ms | Remaining view-dependent workload and long frames |
| Synchronization validation after copy/clear barriers | Observed WAW reports removed; RAW/WAR reports remain | Partial synchronization repair, not a validation-clean claim |

The lighting-volume upload repair removed the observed severe cold-start overexposure.
Full character lighting accuracy has not been qualified against a reference renderer.

## Final branch validation

Source commits: `c54c971` and `4d3d1e8`. The latter adapts upstream test harnesses
and braces an interval-index guard for strict host compiler warnings; it does not
change the guard's behavior. Device runs and binary hashes are distinguished below.
All three `build.py --game <ID> --play` builds succeeded with 198 sources and zero
compile failures: BOTW `01007EF00011E000`, NEO `010043B013C5C000`, and Viractal
`0100FD501F95A000`.

Device: Snapdragon 865 / Adreno 650 handheld, Turnip 27 R2, render scale 1.0,
`DM_FPS_TARGET=30`, `DM_LSFG=0`, `DM_VK_UPLOAD_SNAPSHOT=1`,
`DM_VK_MT_REPLAY=1`, `DM_VK_PASS_SPLIT=128`, `DM_VK_PASS_SPLIT_DEPTH=1`,
`DM_VK_CMD_PARTS=64`, `DM_VK_FDZ=0`. Validation and detailed upload/timeline
logging were disabled. The rebuilt host loaded the existing pack and reached the
Great Plateau from a cold process start. The observed field image did not show the
previous severe overexposure; this is not a reference-image accuracy qualification.

| Final staged runtime smoke test | Observed result |
| --- | --- |
| 70.4 s, ten left/right camera-turn pairs | Complete 300-frame windows: p50 33.91-34.61 ms, p95 37.62-44.76 ms, maximum 72.16 ms |
| 94.1 s, eight movement/turn actions | Complete windows: p50 33.13-33.37 ms, p95 36.23-37.56 ms, maximum 48.38 ms |
| 60 s, open distant view | p50 33.65-34.11 ms; p95 36.13-36.86 ms; maximum 46.92 ms |
| GPU fault counter across these tests | 4 to 4; no new crash observed |

The first mixed window is excluded from each timing summary. The movement route
ended against a rock and does not qualify distant-view performance. These short
smoke tests neither reproduce every earlier workload nor establish fault freedom.
Earlier measurements above must not be attributed to an isolated A/B against the
new upstream. Initial loading also produced a 1354.98 ms maximum frame; it is not
included in the warmed turning/movement summaries.

First staged BOTW host SHA-256 (`c54c971`):
`004c6cc4b34c6327e03500dae6b2446f8dfd51aad6667063e37d46ca236469cd`.

Final rebuilt BOTW host SHA-256 (`4d3d1e8`):
`a7bbe04a7dce7e480fc31d91a66eb65c703cd80d526d013c135efaff7fa3c2e1`.
It completed a second cold start and 99.2 s of eight movement/turn actions.
Complete windows: p50 33.13-33.34 ms, p95 37.07-38.54 ms,
maximum 48.47 ms. GPU fault count remained 4, and no crash was observed.
The final host is left installed with render scale 1.0 and frame generation off.

Full suite: `python3 -m unittest discover -s tests -v` with the NDK environment
loaded: **447 tests, OK, 9 skipped** (desktop GUI tests require PySide6). The shader-cache test's mocked
build now also mocks its network prerequisite, avoiding a real DNS lookup before
a synthetic build; this changes test isolation only.

## Open work before promotion

- `DEVICE_LOST` remains unresolved. Earlier evidence includes the 896 x 896 shadow
  path; a later failure snapshot contains a 1280 x 720 main MRT command stream.
  A captured command buffer is not an exact faulting instruction or proof of cause.
- Native 30 FPS at render scale 1.0 with frame generation disabled is still a target.
  Distant views, turning, movement and occasional long frames remain relevant.
- Repeat cold starts, validate remaining lighting differences, investigate RAW/WAR
  hazards, and complete extended outdoor/thermal soak tests.
- NEO and Viractal are compile checks only in this environment; their runtime packs
  are unavailable. Cross-game runtime regression and a 30-minute stability qualification
  remain outstanding. This PR stays a draft.
