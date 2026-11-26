<h1 align="center">
  <img alt="nx2android" src="docs/images/logo-badge.svg" height="140">
</h1>

> **中文文档**。English: [README.md](README.md)

[![Contributors](https://img.shields.io/github/contributors/zFitness/nx2androidX?style=flat&label=contributors)](https://github.com/zFitness/nx2androidX/graphs/contributors)
[![Release](https://img.shields.io/github/v/release/zFitness/nx2androidX?style=flat&label=release)](https://github.com/zFitness/nx2androidX/releases/latest)
[![License](https://img.shields.io/github/license/zFitness/nx2androidX?style=flat&label=license)](LICENSE)

| 🎮 **已移植游戏** | 🗂️ **游戏画廊** | 🤖 **内置AI助手** | 📚 **移植文档** |
|:---:|:---:|:---:|:---:|
| **<!-- count:ported -->90 / 201<!-- /count -->**<br><!-- count:playable -->69<!-- /count --> 款可玩 · <!-- count:experimental -->13<!-- /count --> 款实验 · <!-- count:wip -->5<!-- /count --> 款进行中 · <!-- count:boots -->3<!-- /count --> 款能启动<br>[看清单](docs/PORT_CHECKLIST.md) | **<!-- count:gallery -->82<!-- /count -->** 款收录<br>[看画廊](#游戏列表) | 跑在手机自己身上<br>[看助手](#内置ai助手) | 从 dump 到 PR 的完整路径<br>[看指南](docs/PORTING_GUIDE.md) |

把你的 Switch 游戏原生移植到安卓手机上：游戏自己的 arm64 代码在设备上直接跑，Switch 的系统服务由一个宿主程序顶替，NVN 图形调用重放到 Vulkan 上。选好游戏文件，点 **移植**，得到游戏的数据包，手机上的 nx2androidX App 负责运行它。

**自带游戏文件和密钥；本仓库不含任何游戏内容与密钥。**

本仓库是 nx2androidX，基于 nx2android——PC 端把 Switch 游戏移植打包成 APK 的工具。nx2androidX 把这件事搬到了手机上：游戏文件给它，它在手机上自己编译、自己运行，全程不开电脑。

手机上的 App 就是完整的工具：它在设备上完成移植，也运行自己产出的数据包。你在库里看到的游戏文件，都是你自己的。

![App 的四个界面：构建页发起移植、助手在游戏库旁边作答、游戏内抽屉的帧生成、设置页](docs/images/app-screens.png)

*左上：构建页选文件发起移植；右上：助手在游戏库旁边作答，库里是它修好的《荒野大镖客》；左下：游戏内抽屉的帧生成；右下：设置页（语言、环境、密钥、Vulkan 驱动）。*

**本仓库的发布页上只有手机 App 本身**（APK，文件名带版本号）；PC 端工具由上游 nx2android 发布，两条路线都在[玩家指南](#玩家指南不用写代码也能移植)里。

---

## 这个安卓分支最近改了什么

这条分支把「手机上直接玩」这件事做成了闭环，App 从一个播放器变成了完整的移植工具。

### 手机 App 现在是完整工具

以前移植要在电脑上做：装工具、选文件、点移植、把数据包传回手机。现在手机上就能发起移植 —— 构建页选一个游戏文件，点 **开始移植**（英文界面是 ▶ Start a port），移植在后台跑（系统通知栏有「移植进度」，英文界面是 Port progress），跑完数据包落到 App 自己的私有目录，游戏库里直接就能运行。

游戏库也简化了：以前要挑一个文件夹当库，背后的扫描是递归的，点错一个根目录就是一次长时间卡死。现在**游戏库只收构建页登记过的游戏**，整段扫盘逻辑删掉了；库空的时候只给一句指路提示，不再有按钮。

### 当前版本新加的东西

<details>
<summary>这一版新加的功能</summary>

| 功能 | 说明 |
|---|---|
| **手机自编译** | 构建页选文件即发起移植，后台跑完进库即玩，全程不开电脑 |
| **glibc rootfs 环境** | App 自带一套打过补丁的 glibc rootfs，移植工具是 Linux 二进制，直接在设备上原生执行：不用 proot，不需要 root，中间没有兼容层 |
| **引导流程修好** | 能走完了、进度不丢，密钥一步到位 |
| **游戏是 App 里的一个页面** | 退出游戏回到游戏库，不再跳桌面、最近任务里只有一条 |
| **App 自己的语言** | 中英随时切换（游戏自己的语言仍在库页抽屉里，一个游戏一个） |
| **存档打包分享** | 导出成一个包，走系统分享面板；导入从任意来源收；导入前自动备份 |
| **游戏内抽屉** | ☰ 菜单按钮直接点开，暂停菜单里能调帧生成和画面与操作 |
| **帧生成** | 游戏运行中开抽屉即可用，倍率和目标帧率即时生效 |
| **Vulkan 驱动管理** | 设置页下载（Turnip 构建）/ 从文件导入 / 删除；内置 Adreno 8xx 的 Turnip |
| **启动即查更新** | 静默检查发布页，有新版就在首页提示；设置页也能手动查 |
| **日志可分享** | 游戏库的抽屉里直接分享运行日志，设置页可以清空 |
| **APK 460MB → 272MB** | 手机上的 .NET 从 SDK 换成 runtime：那两个 C# 工具是预编译的，手机只运行不构建 |

</details>

### 引导流程

首次启动走四步：存储访问 → 环境 → 密钥 → 完成。环境（rootfs、编译工具和 .NET runtime，约 700 MB）只解压一次，之后更新 App 只带新的小工具，不再重复这一步。跳过的步骤也不要紧，随时能在设置里补，库里的入口会提醒缺什么。

### 存档能打包分享

库页面板里的存档操作变成了「备份 + 分享」：导出把存档打包写进下载目录，面板把它交给系统分享面板；导入从任意来源收包 —— 另一台手机、云盘、控制台存档工具都行。导入会覆盖游戏当前的存档，App 会先自动导出一份备份（目录名以 `-before-import` 结尾），面板里列着所有包和备份，可以恢复、分享或删除。

导入不是来者不拒：包名里带着别的游戏 ID 的包会被拒绝，包里路径越界也会被拒绝，解开后的大小有上限。

### 游戏内抽屉与帧生成

☰ 菜单按钮点开就是游戏内抽屉，两个页签：**帧生成**和**画面与操作**。

帧生成用 Lossless.dll：每游戏帧倍率、目标帧率、光流质量都能调，开关与倍率即时生效，DLL 的更新会自动拷到私有目录。Lossless Scaling 的资源不会被内置，也不会被下载；Lossless.dll 由玩家自备，本项目不分发它，也不提供它的下载来源。

画面与操作页签里有虚拟手柄：布局编辑器（拖动按键位置、双指缩放、网格吸附）、手柄不透明度、震动、帧率计数、底座模式。

### 手机上的 Vulkan 驱动

驱动是玩家的，不是数据包的：设置页的 **Vulkan 驱动** 分区里可以下载（Mesa 的 Turnip 构建，从它们自己的地址）、从文件导入、删除。其中一个 Turnip 构建 —— Adreno 8xx 那个 —— 是内置在 App 里的，App 启动时自己展开到私有目录（不联网、不点击），并标记为内置，不归玩家删。

游戏运行时用哪个驱动，在游戏库页的抽屉里选（**Vulkan 驱动**），设备自带驱动排在第一个。选中的驱动写进数据包的 `env.txt`，所以会一直有效，下次启动游戏时生效。

---

## 内置AI助手

App 里自带一个助手。它跑在手机自己的 Linux 环境里 —— 就是移植工具跑的那个环境：它自己去读游戏日志、构建输出和游戏库的状态，用 App 当前的语言回答。它随 App 一起装好，你只需要给它一个模型（设置页填厂商、模型和 key，key 留在你自己的手机上）。

问它游戏为什么闪退、移植为什么构建不出来、游戏库里都有什么。它自己去看，不用你截图。

### 多 Agent 架构

助手是一个主会话，下面挂着子代理。出问题的游戏交给「案例工」—— 它负责那一局的案例档案：症状、原因、打算怎么修、改了哪些文件。探索型的子代理只读不写；代码改动要等玩家确认方案之后才动手。它加载的技能是写下来的，随 App 一起发：

![助手是怎么搭起来的：App 通过 JSONL 与环境里长驻的 pi 进程对话，环境经由 App 内置代理连到玩家自己的模型 API，知识库被加载进 agent](docs/images/agent-architecture.png)

| 技能 | 干什么 |
|---|---|
| `port-failures` | 上游的 PR 读了一遍，整理成一份诊断 |
| `inspect-game` | 读游戏自己的文件，看它是什么 |
| `card-unpack` | 移植包里带的游戏卡 |
| `environment-check` | 手机上的环境准备好了没有 |
| `cheats`、`cheat-crash` | 游戏吃不吃金手指，以及吃了会不会崩 |

### 它带着的知识

`port-failures` 最值得一说：**387 个上游 PR**，整理成一份诊断 —— 构建卡在哪一步、着色器分割为什么只找到这么点、崩溃、黑屏、花屏、卡住。每个案例都带着「是什么证据认出了它」和「该由哪一层来修」（引擎里的通用规则，还是某个游戏自己的档案）。它是离线的：手机的网络常常根本连不上 GitHub，所以知识放在设备上。

这些知识本来不稀缺 —— 它散在几百个 PR 里，也就一直留在那儿。bring up 一个游戏意味着读崩溃日志、找到那一层、把修复写出来：一个人、一款游戏、一个晚上。现在这些案例写下来了、能搜了，而且每台装了 App 的手机上都有。

这就是「科技平权」落到实处的样子：过去要靠逆向专家才跨得过去的坎，现在由一个装在手机里的助手带着几百个 PR 攒下的经验，先替每个愿意试的人走一遍。

### 助手修好的游戏

| 游戏 | 修了什么 | 证据 | 状态 |
|---|---|---|---|
| 忍者小龟（Teenage Mutant Ninja Turtles: Shredder's Revenge，`0100BB8017F24000`） | 游戏开局就调 Epic 的在线 SDK，而宿主一律拒绝 SDK 模块，它解了个空指针就崩了；现在档案点头，SDK 就照常加载 | [案例分支](https://github.com/zFitness/nx2androidX/tree/case/0100BB8017F24000-tmnt) | 能玩；已毕业进正式适配列表 |
| 空之轨迹 2 代（Trails in the Sky 2nd Chapter，韩版，`0100E8B028B54000`） | 纹理构建器没有回答「这块存储是谁的」，色调映射读到一片零，`fmod(colour, 0)` 出来 NaN，整个场景全黑 | [案例分支](https://github.com/zFitness/nx2androidX/tree/case/0100E8B028B54000-sky2nd) | 画面不再全黑；已毕业进正式适配列表 |
| 荒野大镖客（Red Dead Redemption，`01007820196A6000`） | 游戏的着色器藏在 Rockstar 加密的 RPF6 归档里，分割工具读不了（0 个着色器）；游戏的电影又另开了一个音频渲染器，宿主不驱动它，片头之后画面就一直黑着 | [案例分支](https://github.com/zFitness/nx2androidX/tree/case/01007820196A6000-rdr) | 着色器分割过了，3,628 个着色器；标题画面回来了 |

其中两个已经「毕业」：档案与修复都进了主线，因此它们算进本页顶部的数字里（表里留着这一行，是为了说明这个游戏是谁修好的）。荒野大镖客还在案例分支上 —— 档案与修复都还没落地。

你的游戏也一样？游戏库抽屉 → 助手 → **贡献上游**，那一局的案例档案会打成一个 zip。把它挂到[案例档案 issue](https://github.com/zFitness/nx2androidX/issues/new?template=case_file.yml)上，这个修复就能被人读、被人落进仓库。

### 它指向的那些文档

助手读的就是本仓库自己的文档，你也一样可以读：

| 文档 | 装了什么 |
|---|---|
| [docs/PORTING_GUIDE.md](docs/PORTING_GUIDE.md) | 完整流程，手机上或电脑上，六步 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 它是怎么搭起来的：宿主、着色器链、游戏档案 |
| [docs/PORT_CHECKLIST.md](docs/PORT_CHECKLIST.md) | 移植器知道的每一个档案，附状态与署名 |
| [上游的调查手册](nxnative/docs/agents/README.md) | 提取、测绘、攻关、图形、调试 |
| [docs/NIER_AUTOMATA_ANDROID_PORT.md](docs/NIER_AUTOMATA_ANDROID_PORT.md) | 一篇从头写到尾的移植记录 |
| [docs/PICROSS_S_PLUS.md](docs/PICROSS_S_PLUS.md) | 另一篇 |

---

## 运行要求

- **安卓 8.0（API 26）以上**。
- **空闲空间 1.5 GB 起**：APK 约 272 MB，首次启动的环境约 700 MB，再加上你自己的游戏文件和数据包。
- **GPU 要能读 BC 压缩纹理**：App 只在**高通 Adreno**（骁龙）上开发和测试 —— 实测设备是联想拯救者 Y700（骁龙 8 Elite，Adreno 830）。Xclipse（Exynos 2200 及以后）按理也能读 BC 纹理，但没有在 Xclipse 设备上实测过。
- **其它 GPU（天玑的 Mali/Immortalis、PowerVR）**：没有实测。它们读不了 BC 纹理，运行时改用 CPU 解码 —— 更慢，也更占内存。桌面工具的安装步骤仍会按 GPU 名称拒绝它们，手机那条路不拦。自己的实验场：跑通了告诉我们是什么设备。
- **自己的游戏文件和 `prod.keys`**：从你自己的 Switch 导出，工具不会替你下载。

## 游戏列表

<!-- games table: made by docs/gen_tables.py from the readme_* rows of each android.tsv; edit those, not this table -->
| | |
|:---:|:---:|
| 13 Sentinels: Aegis Rim<br><sub>`v0.1.3` · update 1.10 · 60 fps</sub> | 13 Sentinels: Aegis Rim (Asia)<br><sub>`v0.4.0` · base game 1.00 · 60 fps · the Asian release (Japanese, Korean, Chinese) · tested on the Xiaomi 23117RK66C (Android 16)</sub> |
| Advance Wars 1+2: Re-Boot Camp<br><sub>`v0.1.3` · base game 1.0.0 · 60 fps (30 in battle on Switch)</sub> | Animal Crossing: New Horizons<br><sub>`v0.4.0` · update 3.0.3 · 30 fps (as on Switch) · local play over Wi-Fi with Switches that run ldn_mitm (Atmosphère 1.11.2 needs ldn_mitm 1.21.2)</sub> |
| Apollo Justice: Ace Attorney Trilogy<br><sub>`v0.4.0` · </sub> | Blasphemous 2<br><sub>`v0.1.3` · update 1.0.8 · 60 fps</sub> |
| Captain Toad: Treasure Tracker<br><sub>`v0.1.3` · update 1.4.2 · 60 fps</sub> | Cardfight!! Vanguard Dear Days 2<br><sub>`v0.4.0` · update 1.7.2 · 30 fps, 60 with the 60 fps box · tested on the AYN Odin 2 with a Turnip driver</sub> |
| Castlevania: Belmont's Curse<br><sub>`v0.2.0` · update 1.1.0 · 60 fps</sub> | Celeste<br><sub>`v0.1.3` · update 1.4.1.1 · 60 fps</sub> |
| Dark Souls: Remastered<br><sub>`v0.4.0` · update 1.0.3 · 30 fps</sub> | Digimon Story: Time Stranger<br><sub>`v0.5.0` · </sub> |
| Disco Elysium - The Final Cut<br><sub>`v0.4.0` · base game 1.0.7 · 30 fps (as on Switch) · tested on the Sony XQ-DQ72 and the OnePlus 15</sub> | Divinity: Original Sin 2 - Definitive Edition<br><sub>`v0.5.0` · </sub> |
| Donkey Kong Country Returns HD<br><sub>`v0.1.3` · update 1.1.0 · 60 fps</sub> | DRAGON QUEST VII Reimagined<br><sub>`v0.5.0` · </sub> |
| DRAGON QUEST XI S: Echoes of an Elusive Age – Definitive Edition<br><sub>`v0.5.0` · </sub> | Final Fantasy Resonance<br><sub>`v0.4.0` · update 1.0.1 · 60 fps · Asian release: tested on the Legion Y700 TB321FU (Adreno 750) with a Turnip Vulkan driver</sub> |
| Fire Emblem Engage<br><sub>`v0.4.0` · update 2.0.0 · 60 fps (30 on Switch) · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver; Qualcomm's own driver mis-draws Engage Attacks (#122)</sub> | Fire Emblem: Three Houses<br><sub>`v0.5.0` · </sub> |
| FM24 Touch<br><sub>`v0.4.0` · update 1.0.1 · 60 fps · OpenGL ES · touch or controller</sub> | Football Manager 26 Touch<br><sub>`v0.4.0` · update 1.0.2 · 30 fps (as on Switch) · played by touch · port with a Turnip Vulkan driver (the crowd glitches on Qualcomm's driver)</sub> |
| Graveyard Keeper 2<br><sub>`v0.1.2` · update 1.0.4 · 60 fps (30 on Switch)</sub> | Hades II<br><sub>`v0.1.2` · update 1.0 · 60 fps</sub> |
| Hollow Knight: Silksong<br><sub>`v0.1.3` · update 1.0.30000 · 60 fps</sub> | Kirby and the Forgotten Land<br><sub>`v0.4.0` · update 1.1.0 · 30 fps (as on Switch) · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver</sub> |
| Kirby's Return to Dream Land Deluxe<br><sub>`v0.4.0` · 60 fps · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver · needs your console's firmware for its fonts (`--firmware`)</sub> | Layton's Mystery Journey: Katrielle and the Millionaires' Conspiracy DX+<br><sub>`v0.4.0` · </sub> |
| Lonely Mountains: Downhill<br><sub>`v0.4.0` · base game 1.0.5 · 60 fps on Retroid Pocket 6 with PurpleVK · **work in progress**: brief transition glitch and occasional black/white flashes</sub> | Luigi's Mansion 3<br><sub>`v0.5.0` · </sub> |
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
| Rune Factory 3 Special<br><sub>`v0.5.0` · </sub> | Rune Factory 5<br><sub>`v0.4.0` · </sub> |
| Rune Factory: Guardians of Azuma<br><sub>`v0.5.0` · </sub> | South Park: The Stick of Truth<br><sub>`v0.4.0` · base game 1.0.0 · 30 fps · a Vulkan 1.3 driver is needed (Turnip packed on the Adreno 640)</sub> |
| Super Mario 3D World + Bowser's Fury<br><sub>`v0.4.0` · update 1.2.2 · 60 fps · tested on the AYN Thor (Adreno 740) with a Turnip Vulkan driver</sub> | Super Mario Bros. Wonder<br><sub>`v0.1.3` · update 1.2.1 · 60 fps, dips to 40</sub> |
| Super Mario Odyssey<br><sub>`v0.2.0` · update 1.4.1 · 60 fps · shake the device to throw Cappy</sub> | Super Robot Wars 30<br><sub>`v0.5.0` · </sub> |
| Tales of Berseria Remastered<br><sub>`v0.5.0` · </sub> | Tales of Eternia Remastered<br><sub>`v0.1.2` · update 2.0.0 · 60 fps</sub> |
| Teenage Mutant Ninja Turtles: Shredder's Revenge<br><sub>`v0.4.1` · </sub> | The Binding of Isaac: Afterbirth+<br><sub>`v0.5.0` · </sub> |
| The Great Ace Attorney Chronicles<br><sub>`v0.4.0` · </sub> | The Legend of Zelda: Breath of the Wild<br><sub>`v0.4.0` · update 1.9.0 · 60 fps in the open world and shrines; about 30 in the busiest villages, which hold 60 while the phone is cool (30 on Switch) · the profile turns on `DM_GPU_TURBO=1` (the GPU at its highest clock: the phone runs hot, 67-76 °C; `DM_GPU_TURBO=0` in env.txt turns it off) · tested on the Galaxy S25 Ultra (Adreno 830) with Turnip (Stable Turnip v2, Mesa 26.2.3) · **work in progress**: tested on the Great Plateau, in shrines, villages and teleports</sub> |
| The Legend of Zelda: Echoes of Wisdom<br><sub>`v0.4.0` · version 1.1.0 · playable on Retroid Pocket 6 with PurpleVK · **work in progress**: minor transparency artifacts around rifts</sub> | The Legend of Zelda: Link's Awakening<br><sub>`v0.4.0` · update 1.1.0 · 60 fps (drops to 30 on slow frames by default; uncomment the two NOPs in `patches.py` to hold 60 on fast chips — may cause judder and slow-motion on older devices) · tested on the Lenovo TB323FU (Snapdragon 8 Elite Gen 5, Adreno 840) · needs your console's firmware for its fonts (`--firmware`): without them the game crashes at startup because the fallback font lacks `U+25A1` · a new area can hitch while it loads</sub> |
| The Legend of Zelda: Tears of the Kingdom<br><sub>`v0.3.0` · update 1.4.3 · 30 fps, 60 in caves and shrines · smoothest with a Turnip Vulkan driver · **work in progress**: 60 fps in the open world</sub> | The World Ends with You -Final Remix-<br><sub>`v0.4.0` · base game 1.0.0 · 60 fps · played by touch</sub> |
| Tomodachi Life: Living the Dream<br><sub>`v0.4.0` · update 1.0.4 · 60 fps</sub> | Toy Story 3 Complete Edition<br><sub>`v0.5.0` · </sub> |
| Trails in the Sky the 2nd (Korean release)<br><sub>`v0.4.1` · update 1.0.3a · 60 fps in the opening scene · tested on the Xiaomi 23117RK66C (Android 16, Adreno 750) with a Turnip Vulkan driver</sub> | Ultra Kaiju Monster Rancher<br><sub>`v0.4.0` · update 1.0.1 · 30 fps (60 runs the game twice as fast) · tested on the AYN Odin 2 (Adreno 740) with a Turnip Vulkan driver · handheld 3D resolution by default, docked in the app menu · tested through the tutorials and battles</sub> |
| UNDER NIGHT IN-BIRTH Exe:Late[cl-r]<br><sub>`v0.2.0` · update 1.0.3 · 60 fps</sub> | UNDER NIGHT IN-BIRTH II Sys:Celes<br><sub>`v0.2.0` · update 1.42 · 60 fps</sub> |
| Unicorn Overlord<br><sub>`v0.1.3` · update 1.05 · 60 fps · **boots**: saving and a full battle not tested yet</sub> | Unpacking<br><sub>`v0.1.2` · update 2.01 · 60 fps · played by touch</sub> |
| Untitled Goose Game<br><sub>`v0.4.0` · update 1.1.2 · 60 fps</sub> | Viractal: Will You Trust Your Party?<br><sub>`v0.1.0` · update 1.4.5</sub> |
| Xenoblade Chronicles 3<br><sub>`v0.1.0` · update 2.2.0 · 30 fps · **work in progress**: some effects and models don't draw yet</sub> | Xenoblade Chronicles: Definitive Edition<br><sub>`v0.4.0` · update 2.0.0 · 30 fps · tested on the AYN Odin 2 with a Turnip driver · **tested to Colony 9**, the pause menu and saving: later maps not checked yet · the scene drops to 896x504 in heavy fights · rarely crashes at boot (restart)</sub> |
<!-- end of the games table -->

移植器知道的每一个游戏 —— 已移植的、进行中的、只有档案的 —— 都在 [docs/PORT_CHECKLIST.md](docs/PORT_CHECKLIST.md) 里，附状态、实测设备与署名。能在安卓上跑的游戏上游也有一份，附每个游戏测试时用的 nx2android 版本：[Games](https://github.com/shirai91/nx2android#games)。

## 玩家指南：不用写代码也能移植

### 路线一：在手机上直接移植（推荐）

1. **装 App**：从 [Releases](https://github.com/zFitness/nx2androidX/releases/latest) 下载 `nx2android-<版本>.apk`，用系统自带的安装器装到手机上。
2. **首次启动**：走一遍引导（存储访问 → 环境 → 密钥 → 完成），环境那一步要下载并解压约 700 MB。
3. **构建页**：点 **选择游戏文件**，选本体（旁边的更新和 DLC 会一起带上），再点 **开始移植**。移植在后台跑，通知栏里能看到进度。
4. **游戏库页**：移植完成，数据包就出现在库里，点 **运行** 开始玩。

移植的选项也在构建页上：**Touch game**（屏幕手柄一开始隐藏）、**60 fps**、**Experimental port**（还没适配的游戏）。

### 路线二：在电脑上移植

PC 端工具由上游 nx2android 发布，本仓库的发布页上只有 APK。

1. 从上游 [nx2android Releases](https://github.com/shirai91/nx2android/releases/latest) 下载 `nx2android-<版本>-windows-x64.zip`（Windows）或 `nx2android-<版本>-macos-arm64.zip`（Apple 芯片的 Mac），解压后启动 **nx2android**（Mac 上先看 [packaging/INSTALL.md](packaging/INSTALL.md#1-start-the-app)）。
2. **Setup** 页：点 **Download missing tools**（Android NDK、.NET SDK 和 platform-tools，约 1 GB，来自 Google 和微软），然后设置你的 **prod.keys**。每一行都会变绿。
3. **Port** 页：选择放着游戏 NSP、XCI、NSZ 或 XCZ 文件的文件夹（本体、更新、DLC），点 **Port**。
4. 移植会把游戏数据包（`<游戏名>-data/`）留在游戏文件夹里。手机 App 的数据包放在它自己的私有目录里，不读那一份 —— 想在手机上玩，就在手机上移植（路线一）。

   其实完全不用电脑：App 自己就能移植，走路线一。

### 一些常见的开关

- **触屏玩的游戏**：手机端在构建页勾 **Touch game**，PC 端在 Port 页勾 **Touch game**（`--touch`）。屏幕手柄一开始是隐藏的，除了菜单按钮以外的触摸都交给游戏；暂停菜单里可以再把手柄叫出来。
- **热闹场景里被绘制调用拖慢的游戏**：PC 端在 Port 页勾 **Multithread replay**（`--mt-replay`），游戏的 Vulkan 命令会改到单独的线程上记录。下次不带这个选项重新移植之前，它会一直生效。
- **想摆弄屏幕按键**：暂停菜单的 **Gamepad** 页签 → **Edit layout**，拖动可以移动，双指或 **− / +** 可以缩放。**Save** 存下布局下次启动继续用，**Cancel** 丢掉这次改动。**Snap to grid**（默认关，会记住）会显示方格网格，拖动时把控件中心吸附上去。
- **游戏从 App 的游戏库页打开**：那里写着这是哪个游戏、文件在哪、用哪种语言和哪个 Vulkan 驱动来跑。主按钮就是开始游戏，这些选择会写进数据包的 `env.txt`，所以会一直有效。
- **想在设备自带驱动之外用别的 Vulkan 驱动（比如 Adreno 上的 Mesa Turnip）**：PC 端在 Port 页设置 **Vulkan driver folder**（`--vulkan-driver-dir`），数据包会把它们都带上，App 里让玩家自己选，设备自带的排第一个。在手机上直接管理驱动：设置页的 **Vulkan 驱动** 分区，见上面[手机上的 Vulkan 驱动](#手机上的-vulkan-驱动)。
- **游戏日志里有 "AllocateAddressRegion … refused (0x1803)"**：这个游戏需要更大的地址空间，PC 端在 Port 页把 **Extra address space** 调大（命令行是 `--alias-headroom`），比如 16 GB，再不行 24 GB。[packaging/INSTALL.md](packaging/INSTALL.md#when-something-goes-wrong) 里说得更细。
- **App 会顺带看一眼有没有新版本**：启动时它安静地检查一次发布页，有新版就在首页告诉你。**设置** 页里有个 **检查更新**，可以随时手动再查一次。App 自己不下载任何东西 —— 提示只是把你带到发布页，APK 在那儿。
- **《宝可梦传说 阿尔宙斯》和《宝可梦传说 Z-A》的着色器**在 Oodle 压缩包里，只有游戏自己的解码器能打开。在手机上移植时，移植就在手机本机解 —— 手机就是那台跑得动游戏自己代码的机器 —— 不用再准备什么。用桌面工具移植同一款游戏时，这一步跑在你连着的设备上：请备好 Setup 页下载的 platform-tools（adb），点 **Port** 之前先用 USB 调试连上设备。

## 存档

**手机上**：游戏库页 → 抽屉 → **存档**。**导出存档**让系统文件管理器选地方，把存档打成 zip 写进去；**导入存档…** 从文件管理器能看到的任何地方收包。

导入会替换游戏当前的存档，所以 App 会先问一遍：包叫什么、换进去之后现在的进度找不回来。包名里带着别的游戏 ID 的包会被拒绝，解开后的大小有上限。卸载 App 会连存档一起删掉，先拷出来。

**电脑上**（桌面工具的 **Saves** 页签）：用 adb 连上设备，在设备和 PC 之间搬运存档。导出得到的是设备上 `Android/data/<包名>/files/saves/` 里的一个文件夹，存档文件与控制台存档工具导出的格式一致，所以控制台的存档也能同样导入。

## 开发者

从零开始看这份：**[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)** —— 要装哪些工具、两个开发循环（桌面工具和手机 App）、测试怎么跑、发布怎么走。

从仓库跑起来、命令行、仓库结构、打包、测试和提交信息规范：[docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md)。它是怎么搭起来的：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

这个仓库的产品是手机 App，APK 的构建是 `bash packaging/android-apk/build_apk.sh`（加 `release` 参数出发布用的包），各部分和手机端的能力边界见 [packaging/android-apk/README.md](packaging/android-apk/README.md)。

## 参与贡献

欢迎贡献，而且第一个贡献不必是代码。

- **某个游戏在你设备上能跑了？** 提一个 **Game report**（游戏报告）issue：游戏、你的设备、版本和帧率。它会把游戏写进清单，并署上你的名字。
- **某个游戏还跑不起来？** 提一个 **Port request**（移植请求）issue。有些游戏根本没法移植，issue 里会写明是哪些，下一个人就不用再白忙一晚上。
- **想移植一个游戏？** [docs/PORTING_GUIDE.md](docs/PORTING_GUIDE.md) —— 完整流程，在手机上或电脑上都能做，而且全程其实用不上电脑。
- **想改代码、文档或做翻译？** [CONTRIBUTING.md](CONTRIBUTING.md) —— 规则、仓库结构、测试和提交信息规范。

没有合适模板的问题也欢迎：开一个 issue，打上 `question` 标签即可。能跑的游戏走 **Game report** 表单，跑不起来的走 **Port request** 表单。

## 密钥与游戏文件

nx2android 移植时读取你的游戏文件，需要你自己的 `prod.keys` —— 你的主机自己使用的密钥。本仓库和它的发布包里没有密钥、没有游戏文件、没有固件、没有任何从游戏里提取出来的东西，工具也从不下载这些，本项目不提供任何获取密钥的方法或链接。两者都从你自己的 Switch 导出，不要把它们或者用它们做出来的数据包分享出去。

本工具用于运行你自己拥有之游戏的个人备份。你如何获取游戏文件与密钥、在你所在的地方这样做是否合法，由你自行判断并承担。

`nxnative/dm/games/` 下的游戏 profile 只存互通用的元数据：用来识别游戏着色器的哈希、模块内部的偏移、还有几个字节的机器码补丁桩（让某个游戏版本能跑起来）。这些是宿主程序跟游戏打交道需要的信息，不是游戏本身。


## 贡献者

这个仓库历史里的每一个人，以及以后带着 PR 来的人：移植一个游戏、修一个设备上的 bug、改一处文档，都算。一份"某个游戏在我这儿能跑"的报告也算。

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

## 许可

本仓库自己拥有并维护的代码 —— 移植器、桌面工具、手机 App、打包、文档，以及本 fork 维护的 nxnative 引擎树 —— 是 GPL-3.0-or-later：[LICENSE](LICENSE)。[NOTICE.md](NOTICE.md) 说明这些条款覆盖什么、各项的版权归谁、以及本仓库延续了哪些上游代码。树里的第三方代码保留各自的许可，每个组件都列在 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

手机 App 的帧生成（[nxnative/dm/android/lsfg/](nxnative/dm/android/lsfg/)）同样是 GPL-3.0-or-later，与整棵树一致。构建时可以不带上它，但那不会改变构建所用代码的协议。这对 App 意味着什么，见 [android/NOTICE.md](android/NOTICE.md)。

## 致谢

这条分支是一个家族里的一支，它脚下是别人的地基：

- **[nx2android](https://github.com/shirai91/nx2android)** —— 本仓库基于的项目：PC 端把游戏移植打包成 APK；本仓库是它的手机端。它的维护者与贡献者是助手那份知识库的来源：他们几百个 PR，蒸馏成随 App 一起发的诊断。
- **[seedds/nxnative](https://github.com/seedds/nxnative)** —— 它底下的引擎：顶替主机系统服务的宿主程序、NVN 到 Vulkan 的图形回放、着色器翻译器，以及这些移植大多参照过的游戏 profile。上游是 MIT 许可；我们的 fork（`nxnative/`）与本仓库其余部分一样是 GPL-3.0-or-later。
- **nxnative 的各位贡献者** —— 引擎、工具链和 profile 都是他们写的。
- **两个上游的维护者们** —— 审陌生人递来的 PR，并且给像这条分支一样的来路留一扇门。
- **[NX2Apple](https://github.com/LNPANDY/NX2Apple)** —— 同一条引擎的苹果路线：macOS 构建器和 iPhone/iPad 共享的游戏库。谢谢他们让这条路在苹果设备上一直活着。
- **[BananaNative](https://github.com/Raphix91/BananaNative)** —— 把引擎带到安卓、让几款 Switch 2 游戏在手机上原生跑起来的分支。谢谢他们走到比我们更远的地方。
- **[Mesa](https://www.mesa3d.org/)** —— Turnip，安卓 App 可下载的 Adreno Vulkan 驱动。
- **Lossless Scaling** —— Lossless.dll，App 可选的帧生成器；它的资源这里既不内置也不代下载。
- **所有提 issue、投补丁、写游戏 profile、翻译文档的人** —— 这条分支也站在他们的工作上。

树里每个组件保留自己的许可，清单见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 商标

Switch、NVN 以及这份 README 里出现的游戏名称，是任天堂和各自发行商与开发者的商标；这里只用它们来标明本工具兼容哪些游戏，以及解释技术细节。截图是 App 本身，跑的是玩家自己的游戏文件。本项目与它们没有任何关联，也未得到它们的认可或赞助。
