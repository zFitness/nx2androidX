# nx2a 平板 GUI：DroidDeck 会话树（proot 模式）部署与运维

> 2026-11-28 实证：**proot 模式下会话树构建/运行全线可用**。
> 此前的"会话树三件套必死"结论（droiddeck-debug SKILL §15，2026-11-27）只适用于
> **native userland 模式**——用户当时开的是 linux userland 原生模式，seccomp 补丁
> 差异导致 Bad system call / Bus error；proot 模式下无此问题（本章实测证据见 §3）。

## 0. 最高守则

- 会话（用户点击 app / 桌面图标）属主 **10284**；agent 经 adb 进 proot 属主是
  **uid 0（adb root）**。agent 推的文件在会话里可能读不动（属主不对时 chown 10284:10284 归位）。
- agent 直接把包/文件推到 `/root/`（proot 的 rootfs 里，Android 侧路径为
  `$D/files/linuxfs/root/...`，$D=/data/data/com.droiddeck.launcher）。
- 不要动 Droidspaces 容器线（`/data/local/Droidspaces`，另一条部署线，由容器会话管理）。
- **GUI 会在环境列表（GUI 图标）和游戏模式（启动器从游戏库启动）两处跑**：环境列表是
  桌面会话（Wayland，XDG_RUNTIME_DIR=/run/droiddeck），游戏模式同链路。入口统一走
  桌面/启动器的 `.desktop` 或 `.sh`，不直接进容器。

## 1. 进入会话（adb → proot）

```sh
ADB=~/Library/Android/sdk/platform-tools/adb    # 开发机
# 无线序列号会变：先 adb devices，别写死
T=$($ADB devices | awk '/device$/{print $1; exit}')
# 只读/普通命令
$ADB -s "$T" shell "sh /data/local/tmp/guest.sh sh -c '<cmd>'"
# python 脚本（一切文本处理用 python，rootfs 里 coreutils 不全）
$ADB -s "$T" shell "sh /data/local/tmp/guest.sh python3 -" <<'PYEOF'
...PYEOF
```

guest.sh 的环境: `PATH=/usr/local/bin:/usr/bin:/bin`, `HOME=/root`, `DISPLAY=:0`,
proot 包裹 `$D/files/linuxfs`，`/sdcard ↔ /root/Storage`。

## 2. 平板上的布局（2026-11-28 实查）

```
/root/.local/share/nx2a/
  library/          移植的 pack（GUI 的库页 = NX2A_PACK_DIR）
  work/             porter work（RomFS 引用源；删包必须连 work 一起清）
  nxhome/           porter 配置 config.json（keys/firmware，已配好）
  import/           桌面 AppImage 解包（start-nx2androidX.sh 的工作区，1.13G）
  engine/           打包线的可写引擎副本（KEY + nxnative）
/opt/appimages/user/
  nx2androidx-arm64-toolchain-full/app/usr/    # 工具链导入区（10284 属主，执行位完好）
    toolchain/clang/bin/clang  toolchain/bin/glslc  dotnet/  cs-tools/nx_extract
    pylibs/         # PySide6 6.12 + lz4/capstone/PIL/yaml ABI 轮子（Ubuntu 2.43 匹配）
    porter/ nxnative/ launcher/   # ← 部署目标：把主仓库这三棵树替换为所需 commit
  nx2android-v0-4-0-linux-arm64/               # 玩家从 GUI 导入的 v0.4.0 包（参照物）
/root/Storage/Download/games/test/            # 游戏源文件（maliao1.xci / prod.keys / Firmware）
/root/.config/nx2a/launcher.json              # GUI 设置（用户已设 ui_scale 等，合并勿覆盖）
  nx2android/config.json                       # 旧路径（P0 修复前的残留，可清）
/root/Desktop/start-nx2androidX.sh            # 玩家点击入口：解 AppImage → 会话直启
```

GPU 栈：`libvulkan.so.1.4.341` + `libSDL3.so.0.4.2` + `/dev/dri/renderD128`（全在会话 rootfs）。

## 3. 会话树可用性探针（部署前跑一次）

```python
# 三件套死刑测试（native 模式死，proot 模式全活——2026-11-28 实测：3 全过）
subprocess.run([sys.executable, '-c', 'print("child-ok")'])   # fork+exec
ThreadPoolExecutor(4)                                          # 线程池
os.makedirs/写/读 300 个文件                                    # 文件风暴
# PySide6 从厚包 pylibs import（PYTHONPATH/LD_LIBRARY_PATH 指过去）
```

proot 模式实证结果：Seccomp=2 但 proot 拦截层不再触发补丁差异, fork+exec ✓ 线程池 ✓ 文件风暴 ✓, PySide6 6.12 ✓。

## 4. 部署流程（commit → 会话树）

```sh
# 1) 开发机: git archive 出三棵树（porter/ launcher/ nxnative/），带上执行的 commit
git archive <commit> porter launcher nxnative | gzip > /tmp/nx2a-deploy-<sha>.tar.gz

# 2) 推进平板共享存储（adb push 自动 chown 归 0:0 —— agent 侧推的；进 proot 后再归位）
$ADB push /tmp/nx2a-deploy-<sha>.tar.gz /sdcard/Download/nx2a-dev/

# 3) 会话内解包替换（目标=/opt/appimages/user/nx2androidx-arm64-toolchain-full/app/usr）
$ADB -s "$T" shell "sh /data/local/tmp/guest.sh python3 -" <<'PYEOF'
import tarfile, os, stat
SRC = '/root/Storage/Download/nx2a-dev/nx2a-deploy-<sha>.tar.gz'
USR = '/opt/appimages/user/nx2androidx-arm64-toolchain-full/app/usr'
stage = '/tmp/nx2a-stage'
os.makedirs(stage, exist_ok=True)
with tarfile.open(SRC) as t: t.extractall(stage)
for tree in ('porter', 'launcher', 'nxnative'):
    dst = f'{USR}/{tree}'
    if os.path.exists(dst): __import__('shutil').rmtree(dst)
    os.rename(f'{stage}/{tree}', dst)
# 关键：rootfs tar 解包丢执行位 → 按 git 权限时还原（git ls-tree 100755 清单）
for root, dirs, files in os.walk(USR):
    for f in files:
        p = os.path.join(root, f)
        # （简化：build.py/*.sh/c1_guard.py/dmsh_xlate_bin 等可执行见 exec-list）
PYEOF

# 4) 执行位清单（本地生成，随包推送）:
git ls-tree -r <commit> -- porter launcher nxnative | awk '$1=="100755"{print $4}' > exec-list.txt
# 容器内: while read f; do chmod 755 "$USR/$f"; done < exec-list.txt

# 5) 配置（只写键，不整体覆盖——用户的 nx2a/launcher.json 保留 ui_scale/language）:
#    library/work/nxhome 已在位不动；P0 起 NX2A_HOME=$XDG_CONFIG_HOME/nx2a/porter
#    部署后核对 /root/.config/nx2a/porter/config.json 的 keys 行指向有效 prod.keys

# 6) 冒烟：--check（porter 找到、PySide6 版本）+ 起一次窗口看 Wayland/GL 正常
```

## 5. GUI 的启动环境（会话树 GUI 的 env 契约）

```sh
NX2A 工具链导入区: /opt/appimages/user/nx2androidx-arm64-toolchain-full/app/usr
export PYTHONPATH=$U:$U/pylibs
export LD_LIBRARY_PATH=$U/pylibs          # 仅此容器/会话安全（glibc 同 2.43）；游戏运行 env 必须剥掉
export PATH=$U/toolchain/clang/bin:$U/toolchain/bin:$U/dotnet:$PATH
export NX2A_TOOLCHAIN=$U/toolchain
export NX2A_HOST_OS=linux  NX2A_ON_DEVICE=1  DM_TARGET=linux
export NX2A_NX_EXTRACT=$U/cs-tools/nx_extract  NX2A_DMSH_XLATE=$U/cs-tools/dmsh_xlate
export NX2A_PLAYER_API_REVISION=9
export XDG_RUNTIME_DIR=/run/droiddeck  DISPLAY=:0   # 会话自己的 Wayland socket
```

入口脚本模板 = `/root/Desktop/start-nx2a-gui.sh`（见 §7 部署物），点它直启。

## 6. 更新循环（改代码 → 平板见效）

```sh
# 单文件热更最快（部署物只有三棵树，其余不变）:
git show <commit>:launcher/runner.py > runner.py
$ADB push runner.py /sdcard/Download/nx2a-dev/
$ADB -s "$T" shell "sh /data/local/tmp/guest.sh sh -c \
  'cp /root/Storage/Download/nx2a-dev/runner.py $U/launcher/ && ls -la $U/launcher/runner.py'"
# 整树更新: 重跑 §4
# 杀会话内旧 GUI 再点桌面图标（flock 单实例会拒绝双开）
```

## 7. 坑（全部实测）

| 坑 | 事实与修法 |
|---|---|
| native userland 模式构建必死 | 三件套死刑（§15 老结论的适用条件）；**开 proot 模式全活**。判断：`ps -A | grep libproot` 见 `libproot.so` 进程 |
| tar 解包丢执行位 | rootfs 的 exec 位在 tar/解包链路被剥；**部署必附 exec-list.txt**（`git ls-tree` 755 清单），解包后 chmod 还原。FUSE 桥同样丢 |
| `/data/local/tmp` 会被清 | agent 侧临时物放 `/sdcard`（=会话 `/root/Storage`），不放 `/data/local/tmp` |
| adb push 的属主 | agent 推的文件归 uid 0；会话用户读到失败时 `chown 10284:10284` 归位（Linux 侧路径 `$D/files/linuxfs/root/...`） |
| 坏 pack（env.txt 指容器路径） | 显示"资源缺失"是**正确行为**；要么重移植、要么删掉 pack+work。删除清单：`library/<App>-data` + `work/<TID>_build` |
| coreutils 缺 | rootfs 没有 head/tail/cut/ps；文本处理一律 python3；探针脚本经 stdin 传（引号嵌套会炸） |
| 双开 | app flock 单实例；重复点击第二个静默退出（正常） |
| glycin/bwrap abort | Ubuntu 26.04 GTK 图标加载地雷（droiddeck-debug §11）：`setcap cap_setuid,cap_setgid,cap_sys_admin,cap_sys_chroot=+ep /usr/bin/bwrap`（root 一次性） |
| 运行环境污染 | 游戏 dmhost 的 env **不带** pylibs/PYTHONPATH（launcher launch.environment() 已剥；手工跑 nx2a-run.sh 同理） |

## 8. 与其它线的关系

- **droiddeck-debug SKILL**：会话树机制、属主/seccomp、appimage 启动链——继续有效；§15 的"会话内构建不可解"已被本章推翻（native 限定）。
- **droidspaces SKILL**：容器线（`/opt/nx2a`）的部署与数据在它那边；两线的 library/work 不互通（会话坏包就是这么来的——容器路径写进了 env.txt）。
- 主仓库 `launcher/` 的构建/行为契约见 `launcher/SPEC.md`；porter CLI 见 `porter/phone_cli.py` 的 docstring。
