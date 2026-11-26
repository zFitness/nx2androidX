# The shader split: where a game's shaders are, and what goes wrong

The shaders a port needs are not one file. They sit in a dozen container formats, each with
its own compression, its own index and its own trick; the split finds them, the translator
turns them into SPIR-V, and the bundle carries them to the phone. Every historical failure
below was one of those three steps not knowing a container format.

**Read this when**: the port reports a shader count that is too low; the screen is black and
the log says a program is not in the bundle; a material draws wrong; the split and the
profile's tables disagree.

Upstream pull requests are cited as `#NNN`; look one up with `memory_search.py` or on GitHub.
The case index (`case-index.tsv`) has all 387 of them.

## The pipeline, stage by stage

| Stage | What runs | What it produces | Where it fails |
|---|---|---|---|
| 1. extract | `nx_extract` (LibHac) or the RomFS read in place | the game's files | the dump is not the build the profile registers |
| 2. decode | the game's own Oodle (`DM_OODLE_JOB`), the UE shader decoder (`DM_OODLE_SERVE`), the split's own readers | decoded shader archives | the archive is a shape nobody has read yet |
| 3. split | `nxnative/dm/gfx/tools/shader_split.py` | `shader_map.tsv`, `shader_facts.tsv`, `shader_pairs.tsv` | a container format the split does not know |
| 4. translate | `nxnative/dm/android/tools/shader_vk.py` into the C# translator (`nxnative/dm/gfx/tools/dmsh_xlate/`) | SPIR-V per key and stage | the translator gets a type, a capability or a feature flag wrong |
| 5. bundle | `nxnative/dm/android/tools/dmsv.py` | `shaders.dmsv` (version 1 plain, version 2 zstd) | a malformed index or reflection |
| 6. load | `nxnative/dm/android/gfx_vk_shader.c` | the pipeline | a module the device refuses |

The porter runs them: `nxnative/dm/gfx/tools/shader_split.py` then the Vulkan shader stage
(`porter/pipeline.py`). The phone's own translator for the shaders a game compiles at run
time is not in this fork yet (upstream `#505`).

## The container formats

The reader column says whether **this fork** has the reader. The upstream pull request that
added it is the one to read for the details.

| Format | How it is found | Reader here | Upstream |
|---|---|---|---|
| BNSH, loose | the `BNSH` magic in a file, or a `#BNSH@0x...#var0` suffix | yes | - |
| BAHS (agl / gsys) | the `Secred` pack's `GameAglShader` | yes | - |
| MSHD (MercurySteam) | `system/shd/*.bshdat` | yes | - |
| Unity (UnityFS) | the bundles under `Data`, and the game's own serialized files | yes | `#155` (no type trees, 2020.3), `#385` (the built-in resources), `#392` (2017.4, no type trees at all), `#431` |
| Unity Addressables | the addressables container set | yes | `#346` |
| G2S / SPKG (Koei Tecmo) | the `IDRK` entries of the RDB files, zlib in chunks | yes | `#391` (a 128 KB chunk, not only 64 KB), `#352` (the Gust chunked zlib), `#501` (the newer `.fdata`) |
| SDF (Capcom RE Engine) | the KPKA archives, zstd or deflate entries | yes | - |
| LSPK (Larian) | the `.bshd` members, zlib or LZ4 | yes | - |
| Trinity packs (Game Freak) | `arc/data.trpfs`, Oodle Mermaid | yes | `#528` |
| SPK (Capcom MT) | the shader package in an ARC archive | yes | - |
| BEA (NintendoWare Bezel) | the `.bfsha` entries of the archives, zstd | yes | - |
| GFPAK (Game Freak) | the archives under `bin/archive`, Oodle Kraken | yes | `#41` |
| PKZ (PlatinumGames) | the DAT archives of the PKZ entries, Oodle Kraken | yes | `#319` (version 1, `0x10000`, not only `0x20000`) |
| Monolith (Xenoblade) | `bf3.arh` plus `bf3.ard`, and the loose `.wishp` / `.wismt` files | yes | `#386` (the loose files, `shader_loose_monolith`), `#107` (the `cmp\0zlib` streams), `#403` |
| CRI CPK | the plain and masked tables, the `CRILAYLA` entries | yes | `#179` (the GFD `HNSHV002` shader caches) |
| Criterion bnd2 | the bundle's resource blocks | yes | `#274` |
| EA `.big` | the BIG4 / BIGF archives, AES-CBC, chunkzip | yes (in `nxnative/dm/gfx/tools/eabig.py`) | `#444` |
| HAL `.cmp` | a u32 size and one zstd or LZ4 frame | yes (`unsized()`) | `#157` |
| Heaps PAK | the archive index, the shader caches in the `//BIN=` comments | yes (`heaps_shaders`) | `#353` |
| MVGL (Media.Vision) | the wide archive layout | yes (`mvgl_nvn_shaders`) | `#479` |
| Octane (Toy Story 3) | a zip whose end-of-central-directory record has no CRCs | **no** | `#537` |
| Snowdrop | the older bare zlib slices | **no** | `#226` |
| Unreal pak v4 (legacy) | the footer version 4 | yes (`ue_legacy_shaders`) | `#76` (only the paks that need the device decoder count) |
| Unreal pak v8 | the footer version 8 | yes | `#472` |
| Unreal pak v11 (modern) | the footer version 11 | yes, and it is **skipped** (`ue_modern_pack`) unless its index says the shaders are inline in the cooked packages | `#402` |
| Unreal pak v11 with the shaders inline in the cooked packages | the footer version 11, no `.ushaderbytecode` in the index, and `.uexp` and `globalshadercache-*.bin` entries | **yes** - the layout is read from the pak index alone (`uepak.Pak.shader_layout`), the members are read one by one (zlib and LZ4 blocks are decoded in Python) and the LZ4 records are scanned for the UE 4.27 entries | `#484`, `case/0100A3501946E000-ue-v11` |
| IoStore `.utoc` / `.ucas` | the extension, TOC version 3 | yes (`ue_inline_shaders`) | `#429` (the inline LZ4 blocks), `#473` (an IoStore-only shader library is not "no Unreal step") |
| NintendoWare Vfx | **nowhere** | no | `#286`, `#505` |
| RPF6 (Rockstar) | the `RPF6` magic: the game's RomFS is nothing but RPF6 archives | **no** - the reader is in the phone's case file (`nxnative/dm/gfx/tools/rpf6.py`), not in this checkout | the engine's `seedds/nxnative#2005` |
| RAGE effects (`rgxd`) | inside an RPF6 resource: the name starts with `rgxd`, and the record holds the GLSLC outputs | **no** - with the RPF6 reader | the engine's `seedds/nxnative#2005` |
| Double Eleven packs | `langselect.pkdswitch` with its `langselect.pkiswitch` index beside it | **no** - with the RPF6 reader | the engine's `seedds/nxnative#2005` |
| MGFX 10 effects and `.zxnb` assets | the effect's own header, and the `.zxnb` container | yes, on the case branch `case/0100BB8017F24000-tmnt` | fork `00d3c8bd` |

Two rules from the long tail of these:

- **"The split found no shaders" is nearly always a container format nobody read yet.** Every
  instance above was a new archive shape, not a bug in the scanner. When the count is far
  too low (121 against 27 297, 209 against 672, 6 against 15 328, 0 against 3 628), walk the
  table above.
- **A format the split reads whole kills the port.** The v11 pak and the `.ucas` together
  were read as one 8.9 GB buffer: 15.7 GB resident, 40 s, killed by the low-memory killer
  with **no error line** (`#402`). The split skips them now and says so.
- **A format that hides behind a cipher needs the key, and the key is in the game.** Rockstar's
  RPF6 archives keep their entry and name tables AES-256 ECB encrypted and their resources
  zstd-compressed, so the split's magic scan sees nothing at all: the split found 0 shaders
  where the game has 3 628. The key is never written to disk - it is searched for in `main`,
  where the key setup code keeps the eight key words as four 16-byte constants.
- **An entry nothing decodes is counted, not a stop.** A GFPAK, a Trinity pack and a PKZ
  entry that no decoder answers are left out with a red line and a count, so the rest of the
  game's shaders are still found. The split stops only when the container itself cannot be
  read.

## What the split gets wrong

| Symptom | Cause | Upstream |
|---|---|---|
| The tables differ from the profile's, on Windows only | the source path was written with the platform's separator | `#12` |
| The tables differ, the paths are the same | two sources with the same name (`Part/` and `Part2/`) sorted by the native path pick a different first one | `#469` |
| The whole file's shaders are lost | an empty Unity compute kernel raises a 96-byte header unpack error | `#351` |
| The whole file's shaders are lost | a Monolith stage 5 with no code header (a compute shader) aborts the file | `#386`, `#403` |
| The count is far too low | the container's reader is missing or wrong (see the table above) | - |
| Nothing at all, and no error | the split was killed while reading a big archive | `#402` |

The tables the split writes are the profile's own: `shader_map.tsv` (the key and where the
shader came from), `shader_facts.tsv` (per shader: the stage, the workgroup size, the shared
memory, the fragment outputs), `shader_pairs.tsv` (the vertex and pixel pair of each
program), `pso_manifest.tsv`, `bf_want.tsv`. `shader_facts_manual.tsv` holds the answers a
person gave the translator, and `shader_map.tsv.conflicts.tsv` the names two sources share.

The porter refuses the port when the split and the profile disagree, and says so:

```
[RED] the split shader tables differ from game profile <title ID>'s: shader_map.tsv
```

That line means the game files are not the versions the profile registers, or the split
changed what it writes.

## What the translator gets wrong

The shader is found and the picture is still wrong. The cause is nearly always one of five
things: a type, a NaN rule, a capability, a feature flag, or a reflection bit.

| What the player sees | The real cause | Upstream |
|---|---|---|
| A whole sea, or a whole surface, draws **black** | a vertex input that only moves through bit casts was declared an integer, so RGBA8 became `R8G8B8A8_SINT`, every byte above 0x7f went negative, and read as a float it is a NaN | `#269` |
| Fur is a soft smear over the faces | `FMin` / `FMax` / `FClamp` are NaN-undefined in GLSL.std.450; Maxwell's FMNMX drops a NaN | `#121` (`DM_VK_NAN_MINMAX=0` is the A/B) |
| The water, the lake or the road is flat black | a cube view narrowed to one face was refused, so the sampler read the dummy texture | `#530` (`DM_VK_CUBE_WIDEN=1`, upstream only) |
| Purple and red bands over the scene | a format-less storage image was missing `StorageImageRead/WriteWithoutFormat` | `#79` |
| Every occlusion box costs its fragments | `layout(early_fragment_tests)` was dropped | `#54` |
| Particles, item orbs and cutscene effects do not draw at all | the geometry shader was translated for triangles only, and the CPU-filled textures were never uploaded | `#107` |
| Fire and smoke collapse to a point | the bindless handles merged through phis were removed and returned 0 | `#41` |
| The menu is invisible, or one material is noise | a 1D integer fetch over a texture buffer with no answer was translated as 2D rows | `#268`, `#486` (answer it in `shader_facts_manual.tsv`) |
| Buildings and walls are missing | the draw parameters were not substituted | `#25` |
| The module is refused by the driver | a capability was declared that the shader does not use, or a texture-size query asked about an axis that is not there | `#372`, `#373` |
| A buffer that the shader writes is serialized as if it were read-only | the reflection bit was taken from the wrong constant | `#182` |
| The device reports the wrong subgroup support | the shader used a subgroup operation its stage does not have | `#106` (`DM_VK_SUBGROUP_ONE_LANE=0` is the A/B) |

Two of these are worth remembering because they look like everything else:

- **"The geometry is wrong" is usually a type.** `#269` made an entire ocean black because a
  vertex attribute was typed an integer. `DM_VK_VATTR_LOG=<vertex shader key>` prints the
  format the draw really has.
- **"The shading is wrong" is usually a NaN.** `#121` smeared fur across the faces because
  a `max(0, sqrt(1-x²-y²))` went NaN and the min/max did not drop it.

## The shaders a game compiles at run time

Some games build their shaders while they run: NintendoWare Vfx assembles 46 effect programs
in the opening of Pokémon Sword and Shield, and they are in no game file (`#286`, `#291`).
Others compile with their own GLSLC at boot (Fire Emblem: Three Houses, Crash Team Racing,
Catherine, Let's Go Pikachu, MMBN Legacy, Portal 2).

The way it works in this fork:

1. The app captures a missing shader when the guest asks for one and writes it to
   `captured_shaders/`.
2. The **next** `porter port --install` translates the capture into the bundle.

So a first port of such a game shows a black screen until it is ported a second time. That
is the expected way round, not a bug.

Upstream `#505` removes the second port: the app translates the missing shader on the device
(`runtime_shaders on`, `DM_VK_RUNTIME_SHADERS=1`), and a draw whose shader is still being
translated is skipped so it does not write depth over the new picture. **That switch is not
in this fork yet.**

A captured compute shader may have no code header at all; the workgroup size and the shared
memory come from the control section at `+0x748` and `+0x754` (`#91`).

## Where are this game's shaders?

1. **Read the game's `main`.** Shaders embedded in the executable are found there, by their
   declared offsets and lengths. A backward `ADRP` page displacement that was not
   sign-extended hid every one of them (`#202`).
2. **Grep the RomFS** for `BNSH`, `SLCT`, `//BIN=`, `.GSC`, `.wishp`, `.cmp`, `.big`,
   `.ushaderbytecode`, `.utoc`, `.ucas`, `.pak`.
3. **Unreal?** Read the pak footer version. Version 4 is the legacy zlib route; version 8
   is `#472`; **version 11 is read when its layout says so** - find the shader code archives
   instead (`#402`) unless the pak holds its shaders inline. A pak with no `.ushaderbytecode`
   carries its shaders inline, LZ4, in the IoStore export bundles (`#429`); a game cooked with
   the shared material shader code off keeps them inline in the cooked packages of its one pak
   (`#484`, read here as `case/0100A3501946E000-ue-v11`). The layout is read from the pak index
   alone, so a 3 GB pak is never read whole.
4. **Does `main` import `glslc*`?** Then the game has no shader files at all and the bundle
   is capture-only. A classifier that says GL for such a game skips every draw (`#483`).
5. **Unity?** Check the version and whether the type trees are there; compare the type hash
   against the known set (`#155`, `#385`, `#392`).
6. **Count.** A count that is a fraction of the game's usual one names the format to look at.
   Some reference counts: Link's Awakening 9 698; FINAL FANTASY RESONANCE 73 496 split;
   Xenoblade Chronicles 3 29 532 before the `cmp` streams and 35 013 after (`#107`);
   Xenoblade Chronicles DE 15 328; Persona 5 Royal 30 646; 三國志14 55 391.

## The checklists

### The split's tables do not match the profile's

1. Read the `[RED]` line: which table differs.
2. **Windows?** The source path was written with the platform's separator (`#12`). The fix
   is in the split: the relative path with forward slashes.
3. Same paths, different first source? Two sources with the same name, sorted by the native
   path (`#469`).
4. The count is far too low? Walk the format table above.
5. The split crashed? An empty Unity compute kernel (`#351`) or a headerless Monolith stage
   (`#386`, `#403`) takes the whole file with it.
6. The split was killed? Look for the line that says the modern pak was skipped (`#402`).

### Shaders are missing at run time

1. The log says `draw with a program whose shaders are not in the bundle`. Count the skipped
   draws.
2. NintendoWare Vfx effects? They are in no file: use the capture, then port again with
   `--install` (`#286`), or turn on the device-side translation when this fork has it.
3. The game imports `glslc*`? Expect a capture-only bundle (`#483`).
4. The game compiles with its own GLSLC? The port must not refuse it, and the captures come
   in with the next `--install` (`#486`, `#443`, `#142`).
5. A captured compute shader is still missing? It may have no code header (`#91`).

### The shaders are there and the picture is wrong

1. Black geometry or black surfaces? The SINT vertex input (`#269`) and the missing group
   uniform variants (`#519`). `DM_VK_VATTR_LOG=<key>` for the format.
2. Black water or black reflections? The cube view narrowed to one face (`#530`).
3. A NaN smear? `FMin` / `FMax` / `FClamp` against `NMin` / `NMax` / `NClamp` (`#121`).
   `DM_VK_NAN_MINMAX=0` is the A/B.
4. Purple bands, or `spirv-val` refusing a compute shader? The format-less storage image
   (`#79`).
5. Effects missing entirely? The geometry shader's topology and the CPU-filled textures
   (`#107`). `DM_VK_X_FLAT_VS=<key>` confirms the draw.
6. Silhouettes only? The geometry storage addresses at `0x410 + 16*slot` (`#231`, `#237`).
7. The device's own shader compiler crashes? The Adreno 750's stock driver crashes on a
   game with 70 subgroup-ballot compute shaders: use Turnip (`#521`). The start-up line
   `subgroups: ...` says what the device supports.

### The bundle is stale or refused

1. Version 1 or version 2 of `shaders.dmsv`? The reader takes both; an APK from before
   version 2 given a version 2 bundle would hand compressed bytes to the driver (`#105`).
2. `shaders.dmsv.report.json` lists what was missing and what failed. The porter checks
   the expected, the emitted and the failed inventory and refuses a bundle with nothing in it
   (`#212`).
3. A malformed bundle: the index is checked when it is opened, the reflection and the SPIR-V
   when a shader is first asked for, and a bad shader is logged and remembered as missing so
   its neighbours keep working (`#173`; the layout is in `docs/SHADER_BUNDLE_VALIDATION.md`,
   a checkout path).
4. A bundle that is broken on disk: the export wrote `shaders.dmsv` on its final path, so a
   failed disk write truncated the previous usable bundle and the app then read a broken one.
   Every writer now stages into a sibling directory, flushes, reads the payloads back and
   compares them, and only then replaces the destination (`#171`).
5. The cache: on Windows only the size and the time are compared, so an edit that keeps
   both reuses the old bundle; POSIX also compares the inode and the time, and falls back
   to a digest (`#212`).

## The tools

- `nxnative/dm/gfx/tools/shader_split.py` - the split, and the readers of every format.
  Its own header names each format, the game that uses it and the trap in it: the most
  accurate description of the format table above.
- `nxnative/dm/gfx/tools/uepak.py` - the Unreal paks; `unityfs.py` - Unity;
  `mvgl.py` - Media.Vision; `cpk.py` - CRI; `trinity.py` - Game Freak; `eabig.py` - EA.
- `nxnative/dm/android/tools/shader_vk.py` - the Vulkan exporter; `dmsv.py` - the bundle.
- `devtools/shader_corpus.py` - compares two translations of the same shaders.
- `devtools/dmsv_extract.py` - takes a bundle apart.
