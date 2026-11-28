# nx2androidX — Agent 指南

> 本文件是本仓库对 AI agent 的**权威上下文**。`CLAUDE.md` 只指向这里，不重复维护内容。
>
> **一句话：本 fork 的主产物是手机 app（APK）**，另有一条并行自有的 ARM Linux 线。
> 看到仓库里的 PC / iOS 相关目录，不要因此以为项目要往那个方向做。ARM Linux 线
> （`launcher/` 图形启动器 + `nxnative/dm/linux/` 运行时）是本线自有的第二个门面：
> 与 APK 并存，运行时已在真机跑通部分游戏，兼容面与收尾仍在做（细节见 §2 与 `launcher/SPEC.md`）。

## 1. 项目身份

**nx2androidX 的主产物是 Android 手机 app（APK）**；另有一条在做的 ARM Linux 线（`launcher/` + `nxnative/dm/linux/`）。

- 血统：`shirai91/nx2android`（桌面工具，在 PC 上移植游戏、产出数据包）→ 本 fork 把移植搬进手机 app，
  移植、游戏运行、数据包管理都在手机上完成，没有电脑在中间；引擎来自 `seedds/nxnative`（Apple/iOS 路线），
  fork 在 `nxnative/`。
- 不存在"PC 版 nx2androidX"这个产品，也没有 PC 版路线图。

仓库里出现 PC / iOS 相关目录，**不等于**项目要往那里做：

| 位置 | 是什么 | 本 fork 的地位 |
|---|---|---|
| `android/` | Gradle + Kotlin 的手机 app | **产品本体** |
| `nxnative/dm/android/` | Android 运行时（Vulkan 后端、Horizon 宿主、输入、覆盖层、暂停菜单） | **产品本体** |
| `nxnative/dm/games/<title ID>/` | 游戏档案；Android 侧的关键是 `android.tsv` | **产品本体** |
| `porter/` | 移植流水线本体（Python） | 活跃代码：玩家桌面工具与手机 app 共用同一套 pipeline |
| `phone_tools/` | 手机上的小工具（Python） | 随 payload 进手机（`tool/tools/`）：助手与玩家按名字调用，与流水线同版本 |
| `gui/` | 桌面壳（PySide/Tk） | 玩家向工具，不是开发重心 |
| `launcher/` | ARM Linux 线的图形启动器（Python + PySide6/Qt；早期 GTK 3 版本已弃用） | 本线自有：库页、构建页、桌面条目与 Steam 条目；调 `porter.phone_cli`，不复制流水线 |
| `nxnative/dm/linux/` | ARM Linux 运行时前端（`front_linux.c`：SDL3 窗口/输入、音频、影片解码路径） | 本线自有：与 Android 共享宿主核心，已在 Droidspaces 容器真机跑通部分游戏（MvDK、13 Sentinels），兼容面未铺开 |
| `nxnative/dm/menu/` | 共享暂停菜单（`dm_menu.c` 功能层 + `dmui.c` ImGui UI 层；`openspec/changes/imgui-overlay-menu` 第一阶段：Linux 已接入两页签菜单，Android 迁移未开始） | 本线自有：Android 仍用旧菜单路径（`dm/android/` 覆盖层）|
| `packaging/` | 玩家桌面 zip + `android-apk/` 出 APK | 桌面 zip 是玩家分发物；**APK 才是本 fork 的产物** |
| `nxnative/`（其余） | 上游引擎 fork | 运行时在 `dm/android/`；`nxnative/AGENTS.md` 与 `nxnative/docs/` 讲的是上游的 Apple/iOS 路线，不是本 fork 的方向 |
| `nxnative/dm/ios/` | 上游 iOS 侧代码 | 上游遗产，本 fork 不动 |

## 2. 问"怎么运行 / 打包 / 发布 / 安装"时，一律指 Android

玩家手机里装的是 **APK**；移植、数据包、游戏运行全在手机上完成。

- ✅ 构建 APK：`bash packaging/android-apk/build_apk.sh [debug|release]`
  （需要 gh CLI 已登录即可；payload 来自公开 release `NixPort/nixport-rootfs`，不需要额外 token；下载缓存在 `packaging/android-apk/.cache`，不入库）
- ✅ CI：`.github/workflows/android-apk.yml` —— **只有打 tag 才构建**（`workflow_dispatch` 手动出构建产物；推分支不构建）。tag 一推，构建就开始，等 release 建好后自动把 APK 附上去
- ✅ 装机与真机调试：adb，设备信息在 `devtools/device.json`；方法见 `.claude/skills/switch-android-port`
- ✅ 宿主/着色器改动后的重编译：`nxnative/dm/android/build.py`
- ❌ 不要用"下载 `nx2android-<version>-windows-x64.zip`、运行桌面版"来回答 Android 上的问题
- ❌ 不要把 `python packaging/build_bundle.py`（玩家桌面 zip）当作本 fork 的"打包/发布"
- ❌ 不要引用上游的 iOS / IPA / Metal 流程（`nxnative/AGENTS.md`、`nxnative/docs/agents/`）当作本 fork 的做法

README 的 "For players" 一节讲桌面工具，那仍是真实存在的玩家分发物 —— 它只是不是本 fork 的开发对象。

### ARM Linux 线（`launcher/` + `nxnative/dm/linux/`）

- 这条线是**本线自有**的，与 APK 并存：图形启动器（库页 / 构建页 / Steam 条目，PySide6/Qt）调 `porter.phone_cli`；玩家文档入口 `launcher/README.md`，已定形态见 `launcher/SPEC.md`
- **运行时已部分跑通，不是"没有 Linux 运行时"**：`nxnative/dm/linux/front_linux.c`（SDL3 窗口/输入）与宿主核心已构建为 Linux ELF（`build.py --os linux`，包内 `host/dmhost`），在 Droidspaces 容器真机跑通 Mario vs. Donkey Kong 与 13 Sentinels（60 fps，v2 dma-buf host，2026-11 证据）。**不能推及全游戏兼容**：其他游戏、手柄虚拟按键、ImGui 菜单收尾项未验证，见 `openspec/changes/imgui-overlay-menu`（进行中）
- **这条线不发版 tag**：APK 仍是本 fork 唯一的发布物。AppImage 是当前测试交付（手工分发），**不要自行宣布改变发布政策**；目标与现状的差距见 `openspec/changes/add-arm-linux-appimage/tasks.md`（§5 真机验证多项未勾）
- 分发形态是 **AppImage**（`packaging/arm-linux/build_appimage.py`）：ARM64 Linux 一个文件，自带流水线、引擎工具与中文字体，不带 glibc；档案走 release 档案包导入或厚包（`--with-profiles`）。另有**打包迁移进行中**：目标是复用 ARM64 容器原生 PyInstaller + appimagetool 链（保留 launcher 入口），由打包会话处理，**未完成前不要写成"已迁移/自包含"**——`packaging/arm-linux/README.md` 以打包会话的已验证事实为准
- 界面是 **PySide6 (Qt)**，跑在**系统 python3** 上：薄包只带代码（机器要装 `python3` + PySide6）；`--with-toolchain` 厚包带 Qt 轮子、clang 工具链与 .NET runtime（要求 python 3.14 跑流水线 ABI 扩展，详见 `packaging/arm-linux/README.md`）。没有 FUSE 的机器用 `APPIMAGE_EXTRACT_AND_RUN=1` 解包运行
- **环境边界**：目标机器是**完整的 ARM64 Linux 容器**（如 Droidspaces），不是 APK 集成 rootfs；编译 sysroot（`usr/toolchain/glibc`）**绝不进游戏运行时全局 `LD_LIBRARY_PATH`**；ADB 只是开发/测试通道，玩家 UI 流程不依赖 ADB/root
- **数据边界**（用户已定，勿回退）：RomFS 持久在 porter work（`~/.local/share/nx2a/work`，运行资源不是可弃缓存），pack 的 `env.txt` 用 `DM_ROMFS` 指向实际资源；压缩 profile（`romfs zstd`）指向构建工作区的实际输出。库里 pack 目录存在决定列表可见，RomFS 等资源齐全决定能否运行（`launcher/library.py` `romfs_ready`）。失败的重建必须保留旧 pack 与引用资源、save 与 settings
- 上游同步时 `launcher/`、`nxnative/dm/linux/`、`nxnative/dm/menu/` 不参与：`porter/`、`gui/`、`nxnative/dm/android/` 各自的规则照旧

## 3. 发布（唯一真相）

本线的版本号是它承载的**上游基版本**：`porter/__init__.py` 持有基版本（`0.MINOR.PATCH`，当前 `0.4.1`）；
发布 tag 是基版本加上本线的预发布阶段：`v<base>-alphaNN`（如 `v0.4.1-alpha02`），或正式版 `v<base>`。

- 逐步操作见 [nx2android-release skill](.claude/skills/nx2android-release/SKILL.md)：发版的命令顺序、构建只看 tag、
  产物怎么核、alpha 怎么变成当前版本、这些坑

- **发版后 QQ 群里会收到公告**：`.github/workflows/android-apk.yml` 在 APK 挂上 release 之后跑
  `devtools/qq_release_announce.py`，把版本号、release 说明里的中文更新日志、release 链接和夸克网盘链接发到群里。
  机器人的票据是仓库 secrets（`QQBOT_APP_ID` / `QQBOT_APP_SECRET` / `QQBOT_GROUP_OPENID`），**不配就只是没有公告，
  发版照常**；**公告失败不算流水线失败**（那一步是 `continue-on-error`），群里的公告漏了不影响发版本身。
  `QQBOT_GROUP_OPENID` 可以写多个群（逗号分隔），**逐群发送、逐群容错**：一个群拒收不影响其它群。
  公告里带链接；平台若拒收链接（`40054010`），脚本自动去掉链接再发一次，公告不会因此丢掉

- **网盘由 release 触发，或由维护者手动触发**：`.github/workflows/netdisk.yml` 在 **release 发布之后**跑
  （`on: release: [published]`）；维护者也可以手动跑（Actions → Netdisk → Run workflow，**只有 `zFitness`
  能跑**）。**推 tag 不会发布到网盘**——那条 workflow（`android-apk.yml`）只管构建。它把 APK 与档案包放进
  夸克网盘的 `我的/nx2AndroidX`，并把里面不是这一版的文件移到 `我的/旧版本`（**只移不删**）。
  release 是推完 tag 紧接着发布的，APK 由那次构建稍后附上，所以流水线会等文件到齐（`--wait`）再发。
  流水线在 `devtools/netdisk/`：每个网盘是一个独立的 target（自己的凭证、自己的工具、自己的线程），
  **一个网盘挂了不影响其它网盘**；默认发"最后切出来的那一版"，`--tag` 指定某一版。
  新增网盘 = `devtools/netdisk/targets/` 里加一个模块 + 注册表加一行。工具是 `kuake` CLI
  （`python3 -m devtools.netdisk install` 装到 `tools/kuake/`），凭证是仓库 secret `NX2A_KUAKE_COOKIE`
  （pan.quark.cn 的整段 cookie），**不配就跳过这个网盘，其它网盘照发**。
  手动的老办法见 [nx2android-quark-upload skill](.claude/skills/nx2android-quark-upload/SKILL.md)

- 预发布用 GitHub **pre-release**（`--prerelease`）；app 的更新检查读 "Latest"，所以正式版玩家不会被推上 alpha。
  **GitHub 不允许预发布成为 "Latest"**（API：drafts and prereleases cannot be set as latest）：要让某个 alpha
  成为当前版本，就去掉它的预发布标记（`gh release edit <tag> --prerelease=false`）——tag 名字里的 `alpha` 不变，
  之后的预发布不会自动抢走这个位置。**只改标记可能不会让 "Latest" 指过去**：GitHub 的 "Latest" 在创建时
  就定了（`make_latest`），事后去标记要另外显式点名：
  `gh api -X PATCH repos/zFitness/nx2androidX/releases/<id> -F make_latest=true`。
  现状：`v0.4.1-alpha02` 是 Latest（2026-11-24 起，所有玩家的更新检查都会看到这一版；此前 `v0.4.1-alpha01` 也曾去掉预发布标记成为 Latest）
- **构建只由 tag 触发**：推分支什么都不构建。tag 一推，构建就开始（产物从那个 tag 的提交来），
  它会等 release 建好后把 APK 附上去（`gh release create` 紧跟着 tag 就行）。**要重新构建就把 tag 重推一次**
  （`git tag -f` + `git push --force`），构建跟着新 tag 走
- **把一个已发布的 release 退回草稿再发布会抹掉它的预发布标记**：发布那一步
  （`--draft=false`）不带 `--prerelease=true`，release 就变成正式版、成了 "Latest"，正式版玩家会被推上 alpha。
  这条命令要写成 `gh release edit <tag> --draft=true --prerelease=true` 再
  `gh release edit <tag> --draft=false --prerelease=true`；改完核对 `gh release view <tag> --json isPrerelease`
  （守卫也会拦不带标记的 `--draft`）
- 步骤：提交 `chore(release): version <x.y.z>` → 打附注 tag `v<base>-alphaNN` → push 两者 →
  `gh release create v<base>-alphaNN --verify-tag --prerelease --notes-file <notes> --repo zFitness/nx2androidX`，**不带 zip**
- **notes 里要有一段 `Community ports`**，点名本版本涉及的社区贡献（谁移植了哪个游戏、谁修了什么）。
  名单用 `python3 devtools/release_contributors.py` 取（上个 tag 之后合并的 PR 与作者），粘进 notes；
  游戏级别的署名同时落在 `docs/PORT_CHECKLIST.md` 的那一行（`ported by @handle`）——
  名单由 `python3 docs/gen_tables.py` 从档案生成，署名取自加入该档案的那次提交的 GitHub 账号
- app 的 `versionName` 在 `android/app/build.gradle.kts`（当前 `0.4.1-alpha02`），与 tag 去掉 `v` 一致
- **一次发布带手机的 APK 和游戏档案包，别无其它**。App 不带游戏档案（几百 MB 的着色器表），玩家自己导入：
  release 的第二个附件 `nx2a-profiles-r<版本>-<commit>.zip`（CI 切，`devtools/profiles_zip.py`），夸克网盘里
  同样放一份。桌面 workflow（`release-windows.yml` / `release-macos.yml`）不发版，
  只在需要时手动触发（Actions → 该 workflow → Run workflow），产物留在该次运行的 artifact 里
- 每个 `gh` 命令都要带 `--repo zFitness/nx2androidX`（本机 gh 默认指向另一个仓库）
- hook `.claude/hooks/release_guard.py`（`.claude/settings.json`）会拦截不合规的 `gh release create|upload|edit`
- **发布不重测旧游戏**：只检查本次新增或修复的游戏；旧游戏后来暴露的问题留给后续补丁版本
- 升级上游基版本时版本号跟着走（`0.4.0` → `v0.4.0-alpha01`）

## 4. 硬约束

- **游戏文件只放 `.gamedump/<App>/`**（主 checkout 内，git 忽略；`<App>` 是 APK 的名字，如 `HadesII`）：
  下载的 NSP / NSZ / XCI 用**硬链接**放进来，禁止复制，禁止写进下载目录；porter 自己解 NSZ / XCZ。
  调试产物（pass dump、帧截图、录屏、端口输出）同样只放这里。做完（移植已提交、测试 app 已卸载）就删掉。
  删之前先确认每个 dump 文件有 2 个以上硬链接（只有一个链接 = 那是唯一副本，先问用户）。
  **worktree 里的 `.gamedump` 同样处理**，不要在会话的临时目录里做移植。
- **会话结束前**：如果这次建过 `.gamedump` 目录，或在任何地方写了超过 1 GB，说明还剩哪些目录、为什么留着。
- **`prod.keys` 与游戏文件不进仓库、不进聊天**；只打印 key 的名字，不打印值。
- **worktree 纪律**：`tools/`（NDK、.NET SDK、platform-tools、prod.keys）只在主 checkout，被 git 忽略，
  porter 的配置按绝对路径指向它。**绝不要在 worktree 里给 `tools/` 建任何链接**（软链也一样）：
  递归删除 worktree 会穿透链接把主 checkout 的真文件删掉 —— 2026-10-31 就这样删光了 NDK、.NET SDK 和 prod.keys。
  删 worktree 前先列出里面的链接，逐个单独删链接本身（**不要带 `-r` / `/s`**），再删 worktree。
- **分支合并后**清理 worktree 并删掉已合并的分支（`git branch -d`）。
- **一个核心改动只影响它真正修的游戏**；通用规则优先于游戏专属规则。
- **手机上的引擎树不是版本库**：`files/tool/nxnative` 是一份会被整体刷新的复制件——上游同步会把它换掉，
  里面的本地改动悄无声息地丢（2026-11-23 晚上就丢了三个修复：MGFX v10 读取器、在线 SDK opt-in、
  compute warm-up）。改在手机上的引擎代码要**同时落到本仓库的分支上**，一个 case 一条
  （`case/<title ID>-<slug>`）；子代理在手机上做的修复，至少要把 diff 写进该局的案例档案
  （`gamespec/<title ID>/files/`）——那是玩家自己的数据，活过每一次更新。
- **移植类改动必须有真机验证**（真机上的实况 / 截图 / 帧率数据），推理和推断不算验证。
- **提交只在被要求时做**，用 checkout 自己的 git 身份；提交信息走 Conventional Commits（英文、小写），
  由 `.githooks/commit-msg` 校验。

## 5. 开发机：macOS

- **硬链接**：`ln <src> <dst>`（必须同一卷；APFS 允许）。查链接数：`ls -l <file>`（第二列）或 `stat -f %l <file>`。
- **没有 junction**；软链是 `ln -s`，危害相同（递归删除会穿透）。查链接：`find <worktree> -maxdepth 2 -type l`；
  删链接本身：`rm <link>`（不带 `-r`；Windows 上是 `cmd /c rmdir <link>`，同样不带 `/s`）。
- **adb**：`tools/platform-tools/adb`（不是 `adb.exe`）；Windows Git Bash 的 `MSYS_NO_PATHCONV` 那条在 macOS 不适用。
- **玩家配置**：`~/Library/Application Support/nx2android/config.json`（`NX2A_HOME` 可覆盖），
  里面是工具链路径、prod.keys、输出目录、设备。
- **Android SDK**（如果有）：`~/Library/Android/sdk`。
- **Python**：`python3`；输出非 ASCII 内容时设 `PYTHONUTF8=1`（porter 内部已设）。
- **zsh 的 heredoc** 会展开变量和反斜杠：需要原样文本时用 `<<'EOF'`（加引号），否则写一个临时 `.py` 文件。
- 工具链缺失时：`python -m porter tools --download`（约 1 GB）。

## 6. 语言

- 对外产物一律英文：README、docs、代码注释、日志与报错、提交信息、脚本输出
- 尚未实现或明显不对的日志行以 `[RED] ` 开头
- 需要匹配游戏自带的非 ASCII 文本时，写转义（`"\xE8\xB5\xB7"`），不写字符本身
- 需求与任务记录用中文

## 7. 深入指南

| 要做的事 | 看这里 |
|---|---|
| 加游戏档案 / 改共享核心（宿主、Vulkan、着色器、输入、覆盖层） | `.claude/skills/nx2android-dev` |
| 真机排障（闪烁、崩溃、掉帧、压测、实况验证） | `.claude/skills/switch-android-port` |
| DroidDeck/Droidspaces 平台调试（binfmt/glycin/属主/双 uid） | `.claude/skills/droiddeck-debug`、`.claude/skills/droidspaces` |
| 推给上游（开 PR、rebase、回 review） | `.claude/skills/nx2android-upstream-pr` |
| 同步上游进来（镜像快进、合并、解冲突、验证） | `.claude/skills/nx2android-upstream-sync` |
| 分层与契约、目录职责 | `docs/ARCHITECTURE.md` |
| 从仓库运行、构建、测试、提交信息 | `docs/DEVELOPMENT_GUIDE.md` |
| 游戏进度清单 | `docs/PORT_CHECKLIST.md`、`docs/PORT_STATUS.md` |
| 同步进来的上游档案（未移植的档案、来源、已知缺口） | `docs/UPSTREAM_PROFILES.md` |
| 档案包（App 不带档案，玩家导入；发版时它也是 release 的附件） | `docs/UPSTREAM_PROFILES.md`、`porter/profiles_layer.py`、`devtools/profiles_zip.py` |
| ARM Linux 线：玩家用法 / 已定形态 / 打包 | `launcher/README.md`、`launcher/SPEC.md`、`packaging/arm-linux/README.md` |
| 历史发现与踩坑记录（带当时环境，不作默认指南） | `my-docs/`（armlinux 专栏等；`00-专栏规划.md` 有读法） |
| 上游引擎（Apple 路线）的档案格式与调查手册 | `nxnative/AGENTS.md`、`nxnative/docs/agents/`（是上游 Apple 线的材料，不是本 fork 的做法） |

## 8. 防漂移约定（轻量）

- **改功能同时更新其契约文档**：动 `launcher/`、`nxnative/dm/linux|menu/`、`packaging/arm-linux/` 的代码，
  同一轮把 `launcher/SPEC.md` / `packaging/arm-linux/README.md` / `docs/ARCHITECTURE.md` 对应段落一起改；
  验收标准落在 `openspec/changes/<change>/tasks.md`，不写进 AGENTS。
- **AGENTS 记稳定事实，不记易变进度**：菜单接到哪一步、哪个包型刚打出来这类瞬态，写进对应 change 的
  tasks.md（勾选 + 日期 + 证据），AGENTS 只写"已完成/进行中/未开始"三态中的稳定结论。
- **单一来源用链接引用**：同一事实只在一份文档里展开（如 AppImage 基线要求只在
  `packaging/arm-linux/README.md`），其余位置写一句话 + 链接，不复制第二份。
- **完成状态需验证证据**：文档写"已支持/已验证"时要么给实现位置（文件/符号），要么给构建/测试记录；
  代码存在、编译成功、真机通过是三种证据，分开写。没有真机证据的写"已实现，真机未验证"。
- **历史记录不作默认指南**：`my-docs/` 是带日期的发现记录，当时结论（根因、修法）不脱离当时环境照搬；
  指南性内容以 `launcher/SPEC.md`、skills 与 `packaging/` 文档为准。
- **易变数字用自动生成或有明确时点**：游戏数由 `python3 docs/gen_tables.py` 生成；版本号、Latest release
  等写明的值以 `porter/__init__.py` / `android/app/build.gradle.kts` / `gh release view` 的实查为准，
  不要凭记忆抄。
