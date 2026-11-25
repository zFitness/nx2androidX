<h1 align="center">
  <img alt="nx2android" src="docs/images/logo-badge.svg" height="140">
</h1>

> **English**. 中文文档：[README.zh.md](README.zh.md)

[![Contributors](https://img.shields.io/github/contributors/zFitness/nx2androidX?style=flat&label=contributors)](https://github.com/zFitness/nx2androidX/graphs/contributors)
[![Release](https://img.shields.io/github/v/release/zFitness/nx2androidX?style=flat&label=release)](https://github.com/zFitness/nx2androidX/releases/latest)
[![License](https://img.shields.io/github/license/zFitness/nx2androidX?style=flat&label=license)](LICENSE)

| 🎮 **Games ported** | 🗂️ **Games gallery** | 🤖 **AI assistant** | 📚 **Porting docs** |
|:---:|:---:|:---:|:---:|
| **<!-- count:ported -->81 / 194<!-- /count -->**<br><!-- count:playable -->66<!-- /count --> playable · <!-- count:experimental -->8<!-- /count --> experimental · <!-- count:wip -->4<!-- /count --> in progress · <!-- count:boots -->3<!-- /count --> boots<br>[the list](docs/PORT_CHECKLIST.md) | **<!-- count:gallery -->73<!-- /count -->** games shown<br>[the gallery](#games) | Runs on the phone itself<br>[the assistant](#the-assistant-is-in-the-app) | From the dump to the pull request<br>[the guide](docs/PORTING_GUIDE.md) |

Port your own Switch games to Android, natively: the game's own arm64 code runs on the device, with the Switch's system services stood in for by a host and NVN graphics replayed on Vulkan. Pick the game's file, click **Port**, and get the game's data pack, which the nx2androidX app on the phone runs. Bring your own game files and keys; this repository holds no game content and no keys.

This repository is nx2androidX, built on nx2android — the PC tool that ports a Switch game and packages the APK. nx2androidX moves that to the phone: give it the game's files and it compiles and runs them on the device itself, with no computer in the loop.

The app is the whole tool on the phone: it ports the game on the device and plays the pack it makes. The game files it shows are the player's own.

![Four screens of the app: starting a port on the Builds tab, the assistant answering beside the game library, the in-game drawer's frame generation, and the Settings tab](docs/images/app-screens.png)

*Top left: starting a port on the Builds tab; top right: the assistant answering beside the library — Red Dead Redemption, the game it fixed, is in it; bottom left: the in-game drawer's frame generation; bottom right: the Settings tab (language, environment, keys, Vulkan drivers).*

**This repository's releases hold the phone app itself** (the APK, its file named after the version). The PC tool is released upstream, by nx2android; both routes are in [For players](#for-players-port-a-game-without-programming).

---

## What changed on this Android branch

This branch closed the loop on "playing it on the phone": the app went from a player to the whole porting tool.

### The app is now the whole tool

Porting used to happen on the computer: install the tools, pick the file, click Port, copy the data pack back to the phone. Now the phone starts the port itself — pick a game file on the **Builds** tab, tap **Start a port**, the port runs in the background (the notification bar shows "Port progress"), the data pack lands in the app's own folder, and the game is playable from the library.

The library got simpler too: it used to take a folder to be the library, and the scan behind it was recursive — one root directory was a long freeze. Now **the library only holds the games registered on the Builds tab**, the whole folder scan is gone, and an empty library shows one line of guidance instead of buttons.

### What the current release added

<details>
<summary>The features this release added</summary>

| Feature | What it is |
|---|---|
| **Porting on the phone** | Pick a file on the Builds tab and the port starts; it runs in the background and the game is playable when it is done — no computer in the loop |
| **A glibc rootfs** | The app carries a glibc rootfs of its own, and the porting tools are Linux binaries that execute on the device itself: no proot, no root, no compatibility layer in between |
| **Renamed nx2androidX** | The phone app carries the new name; the releases live in `zFitness/nx2androidX` |
| **Onboarding fixed** | It can be finished now, the progress is not lost, and the keys picked in step three are the ones the port uses |
| **The game is a page of the app** | Ending the game falls back to the library instead of the home screen, and the recents hold one entry |
| **The app's own language** | Chinese and English, switchable at any time (the game's own language stays in the library's drawer, one game at a time) |
| **Saves you can share** | An export becomes a package handed to the system share sheet; an import takes one in from anywhere; the save it replaces is backed up first |
| **An in-game drawer** | The ☰ menu button opens it: performance, HUD, frame generation and controls in the pause menu |
| **Frame generation** | Available while the game runs; the multiplier and the target frame rate take effect at once |
| **A steady frame rate** | The drawer's performance page holds the frame rate step (60, 40 or 30 instead of a rate that wanders) and the docked mode |
| **Vulkan driver management** | Download (Turnip builds), import from a file or remove, in the Settings tab; one Turnip build ships inside the app |
| **Update check on start** | The release page is checked quietly; a newer version says so on the home page, and the Settings tab can check again on demand |
| **Shareable logs** | The library's drawer shares the game's runtime log; the Settings tab clears it |
| **APK 460 MB → 272 MB** | The .NET on the phone went from the SDK to the runtime: the two C# tools are pre-built, so the phone only runs them, never builds them |

</details>

### Onboarding

The first launch walks four steps: storage access → environment → keys → done. The environment (rootfs, the build tools and the .NET runtime, about 700 MB) is unpacked once; later updates of the app only carry the new small tools, and that step does not repeat. Skipped steps are not fatal either: they can be made up in the Settings at any time, and the library's entry says what is missing.

### Saves you can share

The save actions in the library panel became a backup-and-share affair: an export writes the save as a package into the downloads folder and hands it to the system share sheet; an import takes a package in from anywhere — another phone, a cloud drive, a console's save tools. An import replaces the save the game has, so the app exports that one first (a folder ending `-before-import`), and the panel lists every package and backup, to restore, share or delete.

An import is not taken on trust: a package carrying another game's title ID is refused, a path pointing out of the folder is refused, and the unpacked size is capped.

### The in-game drawer and frame generation

The ☰ menu button opens the in-game drawer, with four tabs: **performance**, **HUD**, **frame generation** and **controls**.

The performance tab holds the two trade-offs: the **frame rate step** — *follow the game* leaves the rate to step between 60, 40 and 30 fps on its own, while 60, 40 or 30 hold that step, so the rate stays steady where the device can hold it (the pick is kept per game and takes effect at once) — and the **docked mode**, which renders at the TV's resolution: a sharper picture that costs more power, and a higher frame rate without it.

Frame generation uses Lossless.dll: the frames-per-game multiplier, the target frame rate and the optical flow quality are all adjustable, and the switch and the multiplier take effect at once; an updated DLL is copied to the private folder by itself. Lossless Scaling's resources are neither bundled nor downloaded, and the DLL is the player's own file: we do not distribute it and do not link to a download.

The HUD tab has the on-screen information: the performance line (the frame rate counter), the device line, the fields the line shows and the temperature's unit.

The controls tab has the virtual gamepad: the layout editor (drag a control, pinch to resize, snap to grid), the pad's opacity and the rumble.

### Vulkan drivers on the phone

The drivers are the player's, not the pack's: the **Vulkan driver** section of the Settings tab can download them (Mesa's Turnip builds, from their own addresses), import one from a file, and remove one. One Turnip build — the Adreno 8xx one — ships inside the app: it unpacks itself into the app's own folder when the app starts (no network, no click) and is marked as the built-in one, so it is not the player's to remove.

The driver a game runs with is picked in the library's drawer (**Vulkan driver**), the device's own driver first. The choice is kept in the data pack's `env.txt`, so it lasts, and it takes effect the next time the game starts.

---

## The assistant is in the app

The app carries an assistant. It runs on the phone itself, inside the same Linux environment the porting tools run in: it reads the game's log, the build's output and the library's state by itself, and it answers in the language the app is set to. It comes with the app — the only thing it needs from you is a model (the Settings tab takes a provider, a model and a key, and the key stays on the phone).

Ask it why a game crashed, why a port would not build, or what is in the library. It goes and looks; it does not ask you for a screenshot.

### More than one agent

The assistant is a main session with sub-agents under it. A game that misbehaves is handed to a case worker, which owns that game's case file: the symptom, the cause, the proposed fix, and the files the fix touched. The workers that explore only read; a code change waits until the player confirms the plan. The skills it loads are written down, and they ship with the app:

![How the assistant is put together: the app talks to a long-lived pi process over JSONL inside the app's own Linux environment, the environment reaches the player's own model API through an in-app proxy, and the knowledge base is loaded into the agent](docs/images/agent-architecture.png)

| Skill | What it is for |
|---|---|
| `port-failures` | the upstream's pull requests, read and sorted into a diagnosis |
| `inspect-game` | what a game's own files say about it |
| `card-unpack` | the game cards the ports carry |
| `environment-check` | whether the phone's environment is ready |
| `cheats`, `cheat-crash` | the cheats a game takes, and the ones that crash it |

### The knowledge it carries

`port-failures` is the one worth knowing about: **over 400 upstream pull requests**, sorted into a diagnosis — the build that stops at a stage, the shader split that finds too few shaders, the crash, the black screen, the garbled picture, the freeze. Each case carries the evidence that named it and the layer that owns the fix (a rule in the engine, or one game's profile). It is offline: the phone's network often cannot reach GitHub at all, so the knowledge is on the device.

That knowledge was never rare — it was scattered across hundreds of pull requests, and it stayed there. Bringing a game up meant reading the crash, finding the layer and writing the fix: an evening of reverse engineering, per game, per person. The cases are written down now, searchable, and on every phone that installs the app.

### Games the assistant fixed

| Game | What it fixed | Evidence | State |
|---|---|---|---|
| Teenage Mutant Ninja Turtles: Shredder's Revenge (`0100BB8017F24000`) | the game calls Epic's online SDK at start-up, and the host refused every SDK module — it died with a null online object; the SDK is now loaded when the profile asks for it | [the case branch](https://github.com/zFitness/nx2androidX/tree/case/0100BB8017F24000-tmnt) | playable; the profile is still the survey's provisional one |
| Trails in the Sky 2nd Chapter (`0100E8B028B54000`) | the texture builder did not answer which storage it was given, so the tone map read zeros, `fmod(colour, 0)` was NaN, and the whole scene was black | [the case branch](https://github.com/zFitness/nx2androidX/tree/case/0100E8B028B54000-sky2nd) | the scene is not black any more |
| Red Dead Redemption (`01007820196A6000`) | the game keeps its shaders in Rockstar's encrypted RPF6 archives, which the shader split could not read (0 shaders); and the game's movies open a second audio renderer, which the host did not drive, so the screen stayed black after the intro | [the case branch](https://github.com/zFitness/nx2androidX/tree/case/01007820196A6000-rdr) | the shader split passes with 3,628 shaders and the title screen comes back |

None of them is in the ported list yet: the profile and the fix live on a case branch, not in the main line. A game that graduates — profile, `android.tsv` and the row in the checklist — moves into the count at the top of this page.

Your game too? The library's drawer → the assistant → **Contribute upstream** packs that game's case file into a zip. Attach it to a [case file issue](https://github.com/zFitness/nx2androidX/issues/new?template=case_file.yml) and the fix can be read, applied and landed.

### The documents it points at

The assistant reads this repository's own documents, and so can you:

| Document | What it holds |
|---|---|
| [docs/PORTING_GUIDE.md](docs/PORTING_GUIDE.md) | the whole flow, on the phone or on a computer, in six steps |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | how it is put together: the host, the shader chain, the profiles |
| [docs/PORT_CHECKLIST.md](docs/PORT_CHECKLIST.md) | every profile the porter knows, with the state of each and the credit of whoever brought it up |
| [the investigation manual](nxnative/docs/agents/README.md) | the upstream engine's manual: extract, survey, bring up, graphics, debugging |
| [docs/NIER_AUTOMATA_ANDROID_PORT.md](docs/NIER_AUTOMATA_ANDROID_PORT.md) | one port written down, start to finish |
| [docs/PICROSS_S_PLUS.md](docs/PICROSS_S_PLUS.md) | another one |

---

## Requirements

- **Android 8.0 (API 26) or newer**.
- **1.5 GB of free space to start**: the APK is about 272 MB, the environment unpacked on the first launch about 700 MB, on top of your own game files and the data packs.
- **A GPU that reads BC-compressed textures**: the app is developed and tested on Qualcomm **Adreno** (Snapdragon) — the tested device is a Lenovo Legion Y700 (Snapdragon 8 Elite, Adreno 830). Xclipse (Exynos 2200 and later) should read BC textures too, but no Xclipse device has been tested.
- **Other GPUs (Mali/Immortalis on Dimensity, PowerVR)**: untested. They do not read BC textures, so the runtime decodes them on the CPU — slower, and more memory. The desktop tool's install step still refuses them by name; the phone route does not. Your own experiment: if a game runs, tell us the device.
- **Your own game files and `prod.keys`**, dumped from your own Switch: the tool never downloads either.

## Games

<!-- games table: made by docs/gen_tables.py from the readme_* rows of each android.tsv; edit those, not this table -->
| | |
|:---:|:---:|
| 13 Sentinels: Aegis Rim<br><sub>`v0.1.3` · update 1.10 · 60 fps</sub> | 13 Sentinels: Aegis Rim (Asia)<br><sub>`v0.4.0` · base game 1.00 · 60 fps · the Asian release (Japanese, Korean, Chinese) · tested on the Xiaomi 23117RK66C (Android 16)</sub> |
| Advance Wars 1+2: Re-Boot Camp<br><sub>`v0.1.3` · base game 1.0.0 · 60 fps (30 in battle on Switch)</sub> | Animal Crossing: New Horizons<br><sub>`v0.4.0` · update 3.0.3 · 30 fps (as on Switch) · local play over Wi-Fi with Switches that run ldn_mitm (Atmosphère 1.11.2 needs ldn_mitm 1.21.2)</sub> |
| Apollo Justice: Ace Attorney Trilogy<br><sub>`v0.4.0` · </sub> | Blasphemous 2<br><sub>`v0.1.3` · update 1.0.8 · 60 fps</sub> |
| Captain Toad: Treasure Tracker<br><sub>`v0.1.3` · update 1.4.2 · 60 fps</sub> | Cardfight!! Vanguard Dear Days 2<br><sub>`v0.4.0` · update 1.7.2 · 30 fps, 60 with the 60 fps box · tested on the AYN Odin 2 with a Turnip driver</sub> |
| Castlevania: Belmont's Curse<br><sub>`v0.2.0` · update 1.1.0 · 60 fps</sub> | Celeste<br><sub>`v0.1.3` · update 1.4.1.1 · 60 fps</sub> |
| Dark Souls: Remastered<br><sub>`v0.4.0` · update 1.0.3 · 30 fps</sub> | Disco Elysium - The Final Cut<br><sub>`v0.4.0` · base game 1.0.7 · 30 fps (as on Switch) · tested on the Sony XQ-DQ72 and the OnePlus 15</sub> |
| Divinity: Original Sin 2 - Definitive Edition<br><sub>`v0.5.0` · </sub> | Donkey Kong Country Returns HD<br><sub>`v0.1.3` · update 1.1.0 · 60 fps</sub> |
| Final Fantasy Resonance<br><sub>`v0.4.0` · update 1.0.1 · 60 fps · Asian release: tested on the Legion Y700 TB321FU (Adreno 750) with a Turnip Vulkan driver</sub> | Fire Emblem Engage<br><sub>`v0.4.0` · update 2.0.0 · 60 fps (30 on Switch) · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver; Qualcomm's own driver mis-draws Engage Attacks (#122)</sub> |
| Fire Emblem: Three Houses<br><sub>`v0.5.0` · </sub> | FM24 Touch<br><sub>`v0.4.0` · update 1.0.1 · 60 fps · OpenGL ES · touch or controller</sub> |
| Football Manager 26 Touch<br><sub>`v0.4.0` · update 1.0.2 · 30 fps (as on Switch) · played by touch · port with a Turnip Vulkan driver (the crowd glitches on Qualcomm's driver)</sub> | Graveyard Keeper 2<br><sub>`v0.1.2` · update 1.0.4 · 60 fps (30 on Switch)</sub> |
| Hades II<br><sub>`v0.1.2` · update 1.0 · 60 fps</sub> | Hollow Knight: Silksong<br><sub>`v0.1.3` · update 1.0.30000 · 60 fps</sub> |
| Kirby and the Forgotten Land<br><sub>`v0.4.0` · update 1.1.0 · 30 fps (as on Switch) · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver</sub> | Kirby's Return to Dream Land Deluxe<br><sub>`v0.4.0` · 60 fps · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver · needs your console's firmware for its fonts (`--firmware`)</sub> |
| Layton's Mystery Journey: Katrielle and the Millionaires' Conspiracy DX+<br><sub>`v0.4.0` · </sub> | Lonely Mountains: Downhill<br><sub>`v0.4.0` · base game 1.0.5 · 60 fps on Retroid Pocket 6 with PurpleVK · **work in progress**: brief transition glitch and occasional black/white flashes</sub> |
| Mario vs. Donkey Kong<br><sub>`v0.1.3` · update 1.0.1 · 60 fps</sub> | Mega Man Battle Network Legacy Collection Vol. 1<br><sub>`v0.4.0` · update 1.0.2 · 60 fps, held · tested on the AYN Odin 2 (Adreno 740) with a Turnip Vulkan driver (Qualcomm's driver crashes or runs at 30) · Battle Network 1, 2 and 3 played: saves, battles, maps, gallery · the launcher's menus draw fully from the second port with the device connected after a first run (it builds some shaders at run time)</sub> |
| Mega Man Battle Network Legacy Collection Vol. 2<br><sub>`v0.4.0` · update 1.0.3 · 60 fps, held · tested on the AYN Odin 2 (Adreno 740) with a Turnip Vulkan driver · Battle Network 4, 5 and 6 played: saving, loading, battles, gallery · the launcher's menus draw fully from the second port with the device connected after a first run (it builds some shaders at run time)</sub> | Metroid Dread<br><sub>`v0.3.0` · update 2.1.0 · 60 fps</sub> |
| NEO: The World Ends with You<br><sub>`v0.1.2` · update 1.03</sub> | NOBUNAGA'S AMBITION: Shinsei<br><sub>`v0.5.0` · </sub> |
| OCTOPATH TRAVELER 0<br><sub>`v0.4.0` · update 1.0.5 · 60 fps · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver</sub> | OCTOPATH TRAVELER 0 (Chinese release)<br><sub>`v0.4.0` · update 1.0.5 · 60 fps · the Chinese and Korean release · tested on the Xiaomi 23117RK66C (Android 16) · port with Game language: Chinese (Simplified) (`--language zh-Hans`)</sub> |
| OCTOPATH TRAVELER II<br><sub>`v0.4.1` · update 1.1.1 · 30 fps (the game's own cap) · tested on the Xiaomi 23117RK66C (Android 16, Adreno 750) with a Turnip Vulkan driver</sub> | Paper Mario: The Origami King<br><sub>`v0.2.0` · update 1.0.1 · 60 fps (30 on Switch)</sub> |
| Paper Mario: The Thousand-Year Door<br><sub>`v0.2.0` · update 1.0.1 · 60 fps (30 on Switch) · **work in progress**: playable, but lighting flickers (walls go black for single frames after a fall)</sub> | Picross S+<br><sub>`v0.4.0` · update 1.0.1 · Retroid Pocket 6 / PurpleVK · menu and puzzle verified; **Mali rendering issues**</sub> |
| Pokémon Brilliant Diamond<br><sub>`v0.4.0` · update 1.3.0 · 60 fps (30 on Switch) · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver</sub> | Pokémon Legends: Arceus<br><sub>`v0.4.0` · update 1.1.1 · 30 fps (as on Switch) · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver</sub> |
| Pokémon Legends: Z-A<br><sub>`v0.3.0` · update 2.0.2 · 30 fps (as on Switch) · **tested to Lumiose station**: the city and battles not checked yet</sub> | Pokémon Mystery Dungeon Rescue Team DX<br><sub>`v0.4.0` · update 1.0.2 · 30 fps (as on Switch), 60 with the 60 fps option · tested on the AYN Odin 2 (Adreno 740) with a Turnip Vulkan driver</sub> |
| Pokémon Scarlet<br><sub>`v0.4.0` · update 4.0.0 · 50–60 fps (30 on Switch) · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver · **work in progress**: tested in the opening and the South Province fields</sub> | Pokémon Shield<br><sub>`v0.4.0` · update 1.3.2 · 30 fps (as on Switch; 60 runs the game twice as fast) · tested on the AYN Odin 2 (Adreno 740) with a Turnip Vulkan driver · **tested to Postwick** and in wild battles</sub> |
| Pokémon Sword<br><sub>`v0.4.0` · update 1.3.2 · 30 fps (as on Switch; 60 runs the game twice as fast) · tested on the AYN Odin 2 (Adreno 740) with a Turnip Vulkan driver · **tested to the Wild Area**, wild battles included; handheld mode draws blurred (docked is the default)</sub> | Pokémon Violet<br><sub>`v0.4.0` · </sub> |
| Rhythm Heaven Groove<br><sub>`v0.4.0` · base game 1.0.0 · 60 fps · tested on the Xiaomi 15 (Adreno 830)</sub> | ROMANCE OF THE THREE KINGDOMS XIV<br><sub>`v0.4.0` · </sub> |
| Rune Factory 3 Special<br><sub>`v0.5.0` · </sub> | South Park: The Stick of Truth<br><sub>`v0.4.0` · base game 1.0.0 · 30 fps · a Vulkan 1.3 driver is needed (Turnip packed on the Adreno 640)</sub> |
| Super Mario 3D World + Bowser's Fury<br><sub>`v0.4.0` · update 1.2.2 · 60 fps · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver</sub> | Super Mario Bros. Wonder<br><sub>`v0.1.3` · update 1.2.1 · 60 fps, dips to 40</sub> |
| Super Mario Odyssey<br><sub>`v0.2.0` · update 1.4.1 · 60 fps · shake the device to throw Cappy</sub> | Super Robot Wars 30<br><sub>`v0.5.0` · </sub> |
| Tales of Berseria Remastered<br><sub>`v0.5.0` · </sub> | Tales of Eternia Remastered<br><sub>`v0.1.2` · update 2.0.0 · 60 fps</sub> |
| Teenage Mutant Ninja Turtles: Shredder's Revenge<br><sub>`v0.4.1` · </sub> | The Great Ace Attorney Chronicles<br><sub>`v0.4.0` · </sub> |
| The Legend of Zelda: Breath of the Wild<br><sub>`v0.4.0` · update 1.9.0 · 60 fps in the open world and shrines; about 30 in the busiest villages, which hold 60 while the phone is cool (30 on Switch) · the profile turns on `DM_GPU_TURBO=1` (the GPU at its highest clock: the phone runs hot, 67-76 °C; `DM_GPU_TURBO=0` in env.txt turns it off) · tested on the Galaxy S25 Ultra (Adreno 830) with Turnip (Stable Turnip v2, Mesa 26.2.3) · **work in progress**: tested on the Great Plateau, in shrines, villages and teleports</sub> | The Legend of Zelda: Echoes of Wisdom<br><sub>`v0.4.0` · version 1.1.0 · playable on Retroid Pocket 6 with PurpleVK · **work in progress**: minor transparency artifacts around rifts</sub> |
| The Legend of Zelda: Link's Awakening<br><sub>`v0.4.0` · update 1.1.0 · 60 fps (drops to 30 on slow frames by default; uncomment the two NOPs in `patches.py` to hold 60 on fast chips — may cause judder and slow-motion on older devices) · tested on the Lenovo TB323FU (Snapdragon 8 Elite Gen 5, Adreno 840) · needs your console's firmware for its fonts (`--firmware`): without them the game crashes at startup because the fallback font lacks `U+25A1` · a new area can hitch while it loads</sub> | The Legend of Zelda: Tears of the Kingdom<br><sub>`v0.3.0` · update 1.4.3 · 30 fps, 60 in caves and shrines · smoothest with a Turnip Vulkan driver · **work in progress**: 60 fps in the open world</sub> |
| The World Ends with You -Final Remix-<br><sub>`v0.4.0` · base game 1.0.0 · 60 fps · played by touch</sub> | Tomodachi Life: Living the Dream<br><sub>`v0.4.0` · update 1.0.4 · 60 fps</sub> |
| Ultra Kaiju Monster Rancher<br><sub>`v0.4.0` · update 1.0.1 · 30 fps (60 runs the game twice as fast) · tested on the AYN Odin 2 (Adreno 740) with a Turnip Vulkan driver · handheld 3D resolution by default, docked in the app menu · tested through the tutorials and battles</sub> | UNDER NIGHT IN-BIRTH Exe:Late[cl-r]<br><sub>`v0.2.0` · update 1.0.3 · 60 fps</sub> |
| UNDER NIGHT IN-BIRTH II Sys:Celes<br><sub>`v0.2.0` · update 1.42 · 60 fps</sub> | Unicorn Overlord<br><sub>`v0.1.3` · update 1.05 · 60 fps · **boots**: saving and a full battle not tested yet</sub> |
| Unpacking<br><sub>`v0.1.2` · update 2.01 · 60 fps · played by touch</sub> | Untitled Goose Game<br><sub>`v0.4.0` · update 1.1.2 · 60 fps</sub> |
| Viractal: Will You Trust Your Party?<br><sub>`v0.1.0` · update 1.4.5</sub> | Xenoblade Chronicles 3<br><sub>`v0.1.0` · update 2.2.0 · 30 fps · **work in progress**: some effects and models don't draw yet</sub> |
| Xenoblade Chronicles: Definitive Edition<br><sub>`v0.4.0` · update 2.0.0 · 30 fps · tested on the AYN Odin 2 with a Turnip driver · **tested to Colony 9**, the pause menu and saving: later maps not checked yet · the scene drops to 896x504 in heavy fights · rarely crashes at boot (restart)</sub> | |
<!-- end of the games table -->

Every game the porter knows — the ones ported, the ones still in progress, and the ones with a profile only — is in [docs/PORT_CHECKLIST.md](docs/PORT_CHECKLIST.md), with the state of each, the device it was tested on and the credit of whoever brought it up. The games that play on Android are listed upstream as well, with the nx2android version each was tested on: [Games](https://github.com/shirai91/nx2android#games).

## For players: port a game without programming

### Route one: port on the phone (recommended)

1. **Install the app**: download `nx2android-<version>.apk` from [Releases](https://github.com/zFitness/nx2androidX/releases/latest) and install it with the system's own installer.
2. **First start**: walk the onboarding (storage access → environment → keys → done); the environment step downloads and unpacks about 700 MB.
3. **Builds tab**: tap **Choose a game file**, pick the base game (the updates and the DLC next to it are taken along), then tap **Start a port**. The port runs in the background; the notification bar keeps the progress.
4. **Library tab**: when the port is done the data pack is in the library — tap **Run** and play.

The port's own options sit on the Builds tab too: **Touch game** (the on-screen gamepad starts hidden), **60 fps**, **Experimental port** (a game that is not adapted yet) and **Read the game file in place** (the game's own NSP/XCI is read where it is, with no unpacked copy: keep the file there, or the game will not start; NSP and XCI, not NSZ/XCZ).

### Route two: port on a computer

The PC tool is released upstream, by nx2android; this repository's releases hold the APK only.

1. Download `nx2android-<version>-windows-x64.zip` (Windows), `nx2android-<version>-macos-arm64.zip` (Mac with Apple silicon), `nx2android-<version>-linux-x64.zip` (Linux on a PC) or `nx2android-<version>-linux-arm64.zip` (Linux on ARM) from the upstream [nx2android Releases](https://github.com/shirai91/nx2android/releases/latest), unzip it and start **nx2android** (on a Mac, see [packaging/INSTALL.md](packaging/INSTALL.md#1-start-the-app) first).
2. **Setup** tab: click **Download missing tools** (the Android NDK, the .NET SDK and platform-tools, about 1 GB, from Google and Microsoft), then set your **prod.keys**. Every line turns green.
3. **Port** tab: choose the folder with the game's NSP, XCI, NSZ or XCZ files (base game, update, DLC) and click **Port**.
4. The port leaves the game's data pack (`<Game>-data/`) in the game folder. The phone app keeps its own data packs in its own private folder and does not read that one — to play on the phone, port the game on the phone (route one).

   A computer is not needed at all: the app ports the game itself, see route one.

### Common switches

- **A game played by touch**: tick **Touch game** on the Builds tab (phone) or the Port tab (PC, `--touch`). The on-screen gamepad then starts hidden and every touch but one on the menu button goes to the game; the pause menu shows the gamepad again.
- **A game slowed by its draw calls in busy scenes**: tick **Multithread replay** on the Port tab (`--mt-replay`). The game's Vulkan commands are then recorded on a thread of their own. It stays on until you port the game again without it.
- **To arrange the on-screen controls**: open the pause menu's **Gamepad** tab and choose **Edit layout**: drag a control to move it, pinch or use **− / +** to resize it. **Save** keeps the layout for the next launch and **Cancel** discards your edits. **Snap to grid** (off at first, and remembered) shows a square grid and snaps each control's center to it as you drag.
- **The game opens from the app's library page**: it shows the game, where its files are, and the language and the Vulkan driver to run it with. The main action starts the game, and the choices are kept in the data pack's `env.txt`, so they last.
- **To run a game with a Vulkan driver the device's own does not** (Mesa's Turnip on Adreno GPUs): set **Vulkan driver folder** on the Port tab (`--vulkan-driver-dir`); the pack carries them all and the app lets the player pick one, the device's own driver being the first choice. On the phone the drivers are managed in the app's own **Vulkan driver** section — see [Vulkan drivers on the phone](#vulkan-drivers-on-the-phone) above.
- **A game that crashes with "AllocateAddressRegion … refused (0x1803)" in its log** needs more address space: raise **Extra address space** on the Port tab (`--alias-headroom` on the command line), for example 16 GB, then 24 GB. [packaging/INSTALL.md](packaging/INSTALL.md#when-something-goes-wrong) says more.
- **The app looks for a newer release too**: when it starts, it checks the release page quietly, and if there is a newer version it opens a popup that says which version is out and what changed in it. **Later** puts it away until the next start; the **Settings** tab has a **Check for updates** entry that checks again on demand. The app downloads nothing by itself — the popup leads to the release page, where the APK is.
- **Pokémon Legends: Arceus and Pokémon Legends: Z-A keep their shaders in Oodle-compressed archives**, which only the game's own decoder can open. On the phone the port decodes them here — the phone is the ARM64 machine that runs the game's own code — so nothing else is needed. On the desktop tool the same decode runs on a device you plug in: have platform-tools (adb) from the Setup tab, and connect the device with USB debugging on before you click **Port**.
- **Chinese or Korean text drawn as `???`** (the PC tool): choose a TrueType font with those characters as **System font** on the Port tab (`--shared-font`, a single `.ttf`, not a `.ttc`). It goes in the data pack; the tool ships none. The font needs Latin letters too, and a static one is safest: Super Mario Odyssey crashed at start with a phone's Hangul-only variable font. `devtools/make_shared_font.py` merges fonts you have into one such font, for example your Android phone's own Roboto and Korean font with `--adb` (`python devtools/make_shared_font.py --adb -o korean.ttf`).
- **A game that reads system data from the console's firmware** (`sysdata` in its profile; Mario Kart 8 Deluxe builds its Mii heads from MiiModel; a profile that lists the shared font titles 0100000000000811 and 0100000000000810 needs the same folder for its text and button icons): the PC tool cannot ship the console's own system content files. Copy them (`.nca`) to a folder on the PC and give it with `--firmware <folder>` (or `porter config firmware <folder>` once). Without it the host's empty stand-in is used (the fonts: Android's own font and generated icons).
- **The game is already on the device for an emulator** (the PC tool): the app can read the game's files (its RomFS, most of its size) from that dump's folder instead of a second copy: type the dump's RomFS folder in the app's **RomFS on the device** field (or give it to `--romfs-at`) before you install, which must be the same game version as the port.
- **A data pack that reads your own game files in place** (the PC tool): port with `--romfs-container` and the data pack keeps no copy of the game at all. Its manifest lists your own game image — the base game as its NSP or XCI, its update and the DLC — and `porter install` pushes them to the device as they are (from the folder you ported from, or from beside the pack), with your `prod.keys` pushed the same way, never into the pack. The app reads the game's files straight out of them at run time, the update layered over the base game as its maker distributed it (an NSZ or XCZ is decompressed once during the port). A single **integrated XCI** that carries the base game, its update and its DLC needs no separate files: the app layers the bundled update NCA and mounts each bundled DLC over the same image. Install as usual: `--romfs-at` is not needed.

## Saves

**On the phone**: the library page → the drawer → **Saves**. **Export the saves** asks the system file manager where the package goes and writes the save there as a zip; **Import the saves…** takes a zip from anywhere the file manager can see.

An import replaces the save the game has, so the app asks before it does it: the package's name, and the fact that the progress it replaces cannot be brought back. A package carrying another game's title ID is refused, and the unpacked size is capped. Uninstalling the app deletes its saves: copy them out first.

**On a computer** (the desktop tool's **Saves** tab): the saves travel between the device and the PC over adb. An export is a folder in `Android/data/<package>/files/saves/` on the device, the save's files as a console's save tools copy them, so a save from a console imports the same way.

## For developers

Start here: [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) — the tools to install, the two working loops (the desktop tool and the phone app), the tests and the release steps.

Running from the repository, the command line, the repository layout, building the bundle, tests and commit messages: [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md). How it is put together: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Contributing

Contributions are welcome, and the first one does not have to be code.

- **A game runs on your device?** Open a **Game report** issue: the game, your device, the version and the frame rate. It puts the game on the list, with your name on it.
- **A game does not run yet?** Open a **Port request** issue. Some games cannot be ported at all; the issue says which ones, so the next person does not lose an evening over it.
- **A game to port?** [docs/PORTING_GUIDE.md](docs/PORTING_GUIDE.md) — the whole flow, on the phone or on a computer, and no computer is needed at all.
- **Code, docs or translations?** [CONTRIBUTING.md](CONTRIBUTING.md) — the rules, the repository map, the tests and the commit messages.

A question that fits no template is welcome too: the **Question** form is the way in. A game that runs goes through the **Game report** form, a game that does not through the **Port request** form.

Every issue starts from a form: an issue with nothing in it is closed by a bot, and the comment on it points back at the forms.

## Keys and game files

Reading your game files while it ports them needs your `prod.keys` — the keys your own console uses. This repository and its releases contain no keys, no game files, no firmware and nothing extracted from them; the tool never downloads any of them, and this project provides no method or link to obtain keys. Dump both from your own Switch, and don't share them or the data packs built from them.

The tool is for running personal backups of the games you own. How you obtain the game files and the keys, and whether that is legal where you live, is for you to judge and to answer for.

The game profiles under `nxnative/dm/games/` hold interoperation metadata only: the hashes that identify a game's shaders, the offsets inside a module, and patch stubs of a few bytes of machine code that make a particular game build run. They are the information the host needs to work with a game, not the game itself.

## Contributors

Everyone who is in this repository's history, and everyone who comes with a pull request: a game brought up, a device bug fixed, a document corrected. A report that a game runs counts too.

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/shirai91"><img src="https://avatars.githubusercontent.com/u/8848513?v=4&size=100" width="100px" height="100px" alt="Tung Pham"/><br /><sub><b>Tung Pham</b></sub></a><br /><a href="https://github.com/zFitness/nx2androidX/commits?author=shirai91" title="Code">💻</a> <a href="https://github.com/zFitness/nx2androidX/commits?author=shirai91" title="Documentation">📖</a> <a href="https://github.com/zFitness/nx2androidX/commits?author=shirai91" title="Tests">⚠️</a> <a href="https://github.com/zFitness/nx2androidX/pulls?q=is%3Apr+reviewed-by%3Ashirai91" title="Reviewed Pull Requests">👀</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/zFitness"><img src="https://avatars.githubusercontent.com/u/41500499?v=4&size=100" width="100px" height="100px" alt="zfitness"/><br /><sub><b>zfitness</b></sub></a><br /><a href="https://github.com/zFitness/nx2androidX/commits?author=zFitness" title="Code">💻</a> <a href="https://github.com/zFitness/nx2androidX/commits?author=zFitness" title="Documentation">📖</a> <a href="https://github.com/zFitness/nx2androidX/commits?author=zFitness" title="Tests">⚠️</a> <a href="https://github.com/zFitness/nx2androidX/pulls?q=is%3Apr+reviewed-by%3AzFitness" title="Reviewed Pull Requests">👀</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/15622162922"><img src="https://avatars.githubusercontent.com/u/49612681?v=4&size=100" width="100px" height="100px" alt="15622162922"/><br /><sub><b>15622162922</b></sub></a><br /><a href="https://github.com/zFitness/nx2androidX/commits?author=15622162922" title="Code">💻</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/mijuu"><img src="https://avatars.githubusercontent.com/u/3092175?v=4&size=100" width="100px" height="100px" alt="Raymond"/><br /><sub><b>Raymond</b></sub></a><br /><a href="https://github.com/zFitness/nx2androidX/commits?author=mijuu" title="Code">💻</a> <a href="https://github.com/zFitness/nx2androidX/commits?author=mijuu" title="Tests">⚠️</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->

## License

The code this repository owns and maintains — the porter, the desktop app, the phone app, the packaging, the docs and the nxnative engine tree this fork maintains — is GPL-3.0-or-later: [LICENSE](LICENSE). [NOTICE.md](NOTICE.md) says what those terms cover, who holds the copyright on what, and which upstream code this repository continues. The third-party code in the tree keeps its own license; every component is listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The phone app's frame generation ([nxnative/dm/android/lsfg/](nxnative/dm/android/lsfg/)) is GPL-3.0-or-later as well, the same terms as the rest of the tree. It can be left out of a build, but that does not change the license of the code the build was made from. What that means for the app is in [android/NOTICE.md](android/NOTICE.md).

## Acknowledgements

This project is one branch of a family, and it stands on other people's work:

- **[nx2android](https://github.com/shirai91/nx2android)** — the project this repository is built on: it ports a game on the PC and packages the APK; this repository is its phone side. Its maintainers and contributors are where the assistant's knowledge base comes from: several hundred of their pull requests, distilled into a diagnosis that ships with the app.
- **[seedds/nxnative](https://github.com/seedds/nxnative)** — the engine underneath it: the host that stands in for the console's services, the NVN-on-Vulkan replay, the shader translator, and the game profiles that many of these ports were brought up against. MIT licensed upstream; our fork of it, which lives in `nxnative/`, is GPL-3.0-or-later like the rest of this repository.
- **The nxnative contributors** — for the engine, the tooling and the profiles.
- **The maintainers of both upstreams** — for reviewing pull requests from strangers and keeping the door open for a branch like this one.
- **[NX2Apple](https://github.com/LNPANDY/NX2Apple)** — the Apple route of the same engine: the macOS builder and the shared iPhone/iPad library. Thanks for keeping the line alive on Apple devices.
- **[BananaNative](https://github.com/Raphix91/BananaNative)** — the branch that takes the engine to Android and runs a few Switch 2 games natively on a phone. Thanks for taking it further than we did.
- **[Mesa](https://www.mesa3d.org/)** — for Turnip, the Vulkan driver the app can download for Adreno GPUs.
- **Lossless Scaling** — for Lossless.dll, the frame generator the app can use; its resources are neither bundled here nor downloaded by us.
- **Everyone who filed an issue, sent a patch, wrote a game profile or translated the docs** — this branch stands on their work too.

Everything shipped in the tree keeps its own license; the index is [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Trademarks

Switch, NVN and the game names in this README are trademarks of Nintendo and of the respective publishers and developers; they are used here only to identify the games this tool is compatible with and to explain technical details. The screenshot is of the app itself, running the player's own game files. This project is not affiliated with, endorsed by or sponsored by them.
