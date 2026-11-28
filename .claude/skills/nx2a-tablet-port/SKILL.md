# nx2a 平板移植流程（GUI 走查 + 取证）

> 面向 DroidDeck 会话树（proot）部署的启动器 GUI（部署见 nx2a-tablet-gui SKILL）。
> 2026-11-28 实测：GUI 全量构建 maliao1.xci（Mario vs Donkey Kong）成功。

## 0. 前置检查（一次）

| 检查 | 位置 | 已知状态（2026-11-28） |
|---|---|---|
| prod.keys | 设置页（存 `$XDG_CONFIG_HOME/nx2a/porter/config.json` 的 keys 行） | `/root/Storage/Download/games/test/prod.keys` ✓ |
| 游戏源文件 | 构建页选文件（文件管理器 `/root/Storage/Download/...`） | `.../games/test/maliao1.xci` |
| firmware | porter config.json 的 firmware 行（有 Mii/系统数据的游戏要） | `/root/.local/share/nx2a/firmware` |
| 档案包 | 设置页「游戏档案包」导入 `nx2a-profiles-r*.zip` | 厚包自带仓库档案树,导入了更新档案的玩家层在 `$NX2A_HOME/profiles` |
| 磁盘 | work 与 library 各要 1–2× 游戏体积 | 会话 rootfs 所在分区（Android /data） |
| 工具链 | porter 会按 NX2A_TOOLCHAIN 找 clang/glslc；缺了 `porter doctor` 会说 | 厚包工具链导入区 ✓ |

## 1. 构建页走查

```
选文件 → 识别卡片（title ID / 主包+update+DLC / 是否支持 / pack 记忆）
  → 选项（60fps / 触摸 / 语言 / headroom / 字体 / 实验）
  → 开始构建 → 阶段表 + 日志 + 进度条
  → 完成: pack 原子落进 library（NX2A_PACK_DIR），库页刷新「就绪」
```

- **识别的竞态保护**：换文件/改路径后旧识别结果会被丢弃重读；迟到结果不覆盖当前卡片（测试覆盖）。
- **实验性**：无档案的游戏勾「实验」才能构建（`--experimental`，卡片会提示）。
- **一次一个**：构建中按钮置灰；设置保存**不会**杀构建（页面在构建结束后才重建）。
- **取消**：SIGTERM 整进程组（dotnet/clang 子进程一起死）；pack 原子性保证库里没有半成品。
- 阶段缓存：重跑同游戏时 nx_extract/着色器秒过是**正常**的（增量复用），不代表没干活。

## 2. 构建成功的判据（不要看按钮收尾就下结论）

```sh
# 会话内验证（adb → guest.sh python3）:
pack=/root/.local/share/nx2a/library/<App>-data
1. manifest: nx2a-data.json 有 "exe": "host/dmhost" 且 host/dmhost 存在、X 位在
2. env.txt: DM_ROMFS= 指向 work 的真实 RomFS（构建后必须存在）
3. mods/main.fixups.tsv 在（重写模块表）
4. 库页该卡显示「就绪」（= RomFS 就绪 + pack 原子落盘）
5. manifest 的 player_api_revision 与 launcher 部署的 porter/revision.py 一致
```

## 3. 库页操作

- **运行**（双击卡 / 面板按钮）：`launch.start` → run.sh 起包；游戏 env 剥掉 pylibs/PYTHONPATH（系统 SDL3/Vulkan）。
- **重建运行库**（管理菜单）：`rebuild-runtime`，不碰游戏数据/存档/env；**档案漂移**（profile-drift 事件）会问"用当前档案重建吗"——接受则 `--allow-profile-drift` 重试。
- **重新移植**（管理菜单）：按 sources.json 记忆的源文件+选项重放（构建成功才会记）；源文件不在了会明说。
- **从库中移出**：pack 目录改隐藏名（可逆）；**删除**：真删（确认两次）。
- 缺 RomFS 的卡显示「资源缺失」且拒绝运行——那是包与 work 的对应关系断了，不是 bug。

## 4. 失败取证（问题报告要带什么）

```
1. 构建页日志全文（或 /root/.config/nx2a/... 的 launcher 日志）
2. 失败阶段名 + 阶段日志文件: work/<TID>_build/logs/*.log
3. manifest 的 profile_h / player_api_revision（重建失败时）
4. adb 侧: dmesg | grep -iE 'segfault|sigsys|sigbus'（怀疑 seccomp/崩溃时）
5. 移植器自己的 [RED] 行——绝大多数失败它已说清原因（缺 keys/缺档案/版本不符）
```

诊断入口：

```sh
# 会话内直接跑 porter doctor（不依赖 GUI）:
$ADB -s "$T" shell "sh /data/local/tmp/guest.sh sh -c \
  'PYTHONPATH=$U:$U/pylibs LD_LIBRARY_PATH=$U/pylibs NX2A_HOST_OS=linux DM_TARGET=linux \
   NX2A_TOOLCHAIN=$U/toolchain NX2A_HOME=/root/.local/share/nx2a/nxhome \
   python3 -m porter.phone_cli doctor'"
```

## 5. 两线数据不互通（重要）

- 会话树的 library/work 在 `/root/.local/share/nx2a/`；Droidspaces 容器线在 `/opt/nx2a-data/`。
- 把一边的 pack 复制到另一边，env.txt 里的 DM_ROMFS 路径仍是原线的 work → 显示「资源缺失」属**预期**。
  修法只在目标线重新移植（GUI「重新移植」记忆了源文件），或手改 env.txt 的绝对路径指向本线 work。
- 2026-11-28 清理记录:会话树曾有一份指向容器 work 的 MarioVsDonkeyKong-data (+work 1.5G) 已删除。

## 6. 已知边界

- 语言:GUI 构建时选的语言进 env.txt（DM_LANG）;运行期 env 里已有的值赢过 env.txt（`nxnative/dm/host/main.c:87`）——即语言是构建期选择,当前无运行期切换 UI。
- 桌面/Steam 快捷方式：写 ~ 下的 .desktop/shortcuts（会话树里可用,Steam 需真装了）。
- 手柄: SDL3 路径在会话树已实证（pad_relay 历史）。
