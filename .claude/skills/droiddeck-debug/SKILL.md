---
name: droiddeck-debug
description: Debug and operate the DroidDeck tablet (ARM64 Ubuntu, proot / native userland dual mode) for the ARM Linux launcher line - adb connection quirks, the two-uid ownership rule (adb vs app), the minimal rootfs without coreutils, apt/dpkg repair, process inspection without ps, AppImage launch chains (binfmt hijack, gamescope, glycin/bwrap icon loading), which execution mode a session runs in and how to switch it back to proot, and what the agent must never do from the adb side. Use when working on the tablet over adb, running anything inside the guest rootfs, fixing a broken dpkg/apt state, launching or packaging AppImages on DroidDeck, choosing between proot and the native userland, or diagnosing "permission denied" / "unable to create" / "Bad system call" / SIGSYS / SIGABRT-in-GTK / stuck-installer symptoms there.
---

# DroidDeck 平板调试与操作守则

这台平板（DroidDeck，ARM64 Ubuntu 26.04，proot / native userland 双模式）是 ARM Linux 线（`launcher/`）的目标机器。
本文件是踩坑之后的守则：**每一条都对应一次真实事故**。

## 0. 最高守则（违反过，代价惨重）

**两条 uid 世界，绝不混用。**

- 用户点桌面/终端里的 proot，进程属主是 **app uid（10284）**，SELinux 标签带类别
  （`u:object_r:app_data_file:s0:c28,c257,c512,c768`）。
- agent 经 adb 进的 proot，进程属主是 **adb 侧 uid（10000 或 0）**。
- adb 侧写的文件对 app 是"别人家的"：dpkg 报 `unable to create /var/lib/dpkg/updates/tmp.i`、
  改不了自己的锁、修复脚本互相残杀。

因此：

| 动作 | 谁做 |
|---|---|
| apt / dpkg / 任何系统级安装、改包状态 | **只由用户在平板自己的终端里做** |
| agent 经 adb 推文件进 rootfs | 推完**立刻** `chown` + `chcon` 归位（见 §3） |
| agent 经 adb 做 | 只读诊断（读 /proc、读文件）、推 launcher 自己的数据 |

一旦发现属主污染，整树归还（先从树上读真实 uid 和标签，不要背数字）：

```sh
ls -lnZ /data/data/com.droiddeck.launcher/files/linuxfs | head   # 读出 uid/gid 和标签
chown -R <uid>:<gid>  /data/data/com.droiddeck.launcher/files/linuxfs
chcon -R <完整标签>   /data/data/com.droiddeck.launcher/files/linuxfs
```

## 1. adb 连接

- 序列号会变：无线调试是 `adb-HA2EFNGR-6xLiLL (2)._adb-tls-connect._tcp` 之类，USB/重连后
  变成 `HA2EFNGR`。**先 `adb devices` 再干活**，不要把序列号写死在长命令里。
- 无线调试会掉（一次黑屏/锁屏就断）。掉了让用户重新开 开发者选项 → 无线调试。
- 断线时被打断的命令**在平板上留孤儿进程**（apt/dpkg 继续跑、持锁）。恢复连接后先清孤儿（§5）。

## 2. 进 guest rootfs

```sh
# 只读/普通命令（非 GUI 时 XAUTHORITY_FILE 可省）
adb -s "$T" shell "sh /data/local/tmp/guest.sh sh -c '<cmd>'"
# GUI 程序要先取 xauth（文件名轮换，每次重新取）
adb -s "$T" shell "XAUTHORITY_FILE=$(ls /data/data/com.droiddeck.launcher/files/.wayland-rt/xauth_* | head -1 | xargs -n1 basename) sh /data/local/tmp/guest.sh <gui-cmd>"
```

- guest.sh 里的环境：`PATH=/usr/local/bin:/usr/bin:/bin`、`HOME=/root`、`DISPLAY=:0`、`LANG=C.UTF-8`
- 桌面是 `/root/Desktop`（用户看得到，别留垃圾文件；日志要放桌面就明说）
- **长活儿（apt、dpkg、configure）挂后台跑，别前台干等**；前台超时被杀＝留孤儿

## 3. 推文件的固定三连（缺一就是下次事故）

```sh
adb -s "$T" push <local> "$L/<guest-path>"
adb -s "$T" shell "chown 10284:10284 $L/<guest-path>"        # uid 从 §0 的 ls -lnZ 现场读
adb -s "$T" shell "chcon u:object_r:app_data_file:s0:c28,c257,c512,c768 $L/<guest-path>"
```

## 4. 这个 rootfs 是极简 Ubuntu：没有 coreutils

`cat`、`tail`、`head`、`chmod`、`uname`、`readlink`、`id`、`cut`、`env`、`ps` **全都没有**。
替代：

- 一切文本处理/进程查看用 **python3**（3.14，带 `gi`，是这台机器的瑞士军刀）
- chmod 用 `python3 -c "import os; os.chmod(p, 0o755)"`
- 引号嵌套会爆炸：**python 脚本走 stdin 传**，不要内联转义：

```sh
adb -s "$T" shell "sh /data/local/tmp/guest.sh python3 -" <<'PYEOF'
import os
print(sorted(os.listdir('/root/Desktop')))
PYEOF
```

- Android 侧（proot 外）有 **toybox**（`ls -lnZ`、`chown`、`chcon`、`rm -rf`、`find` 都能用），
  修属主/删垃圾在 Android 侧做。

## 5. 没有进程管理工具：/proc 扫描是唯一手段

找/杀 apt、dpkg 孤儿（argv[0] 的 basename 判断，别拿整条 cmdline 匹配——会误杀自己）：

```sh
adb -s "$T" shell "sh /data/local/tmp/guest.sh python3 -" <<'PYEOF'
import os, signal
for p in os.listdir('/proc'):
    if not p.isdigit(): continue
    try:
        argv = open(f'/proc/{p}/cmdline','rb').read().split(b'\0')
        base = os.path.basename(argv[0].decode()) if argv and argv[0] else ''
    except Exception: continue
    if base in ('apt-get','apt','dpkg','frontend'):
        print('kill', p, base); os.kill(int(p), signal.SIGKILL)
PYEOF
```

- apt/dpkg 的锁是 **flock**：进程死了锁自动释放，**不需要删锁文件**
- dpkg 在 `do_wait` 等子进程；判断"卡死还是在干活"看子进程的
  `/proc/<pid>/stat` CPU 是否上涨、`/proc/<pid>/io` rchar 是否增长（这是"还在推进"的硬证据）
- dpkg 打出 `Setting up xxx` 后**这一行会停很久**——postinst 没跑完就不打下一行。
  log 不动 ≠ 卡死。libc6 的 configure 里 ldconfig 要扫 ~7.5 万个文件
  （usrmerge 让 /lib 和 /usr/lib 是同一棵树，被走两遍），proot ptrace 放大十倍，
  **十几分钟 CPU 属正常**。杀它只会前功尽弃。

## 6. apt/dpkg 的坑（都已踩过）

| 坑 | 事实/解法 |
|---|---|
| `apt-get`、`sudo` 在 /usr/local/bin 是 DroidDeck 包装器 | 依赖 `id`/`cut`/`sudo`——rootfs 里没有。**用 `/usr/bin/apt-get` 直呼**（proot 内已是 root） |
| dpkg 维护脚本 PATH 固定 `/usr/sbin:/usr/bin:/sbin:/bin` | 垫片放 /usr/local/bin 没用；要放 **/usr/bin** |
| libc6 preinst 要 `uname`、`readlink` | rootfs 没有 → 垫片（uname 读 `/proc/sys/kernel/osrelease`；readlink 用 python3 realpath） |
| libc6 postinst exec `/usr/share/debconf/frontend` | rootfs 没有 debconf → 垫片：`script="$1"; shift; exec "$script" "$@"` |
| PackageKit Post-Invoke 钩子必炸（没有 dbus） | `/etc/apt/apt.conf.d/99proot-no-dbus` 写一行 `#clear DPkg::Post-Invoke;` |
| conffile 询问挂死 | 一律 `DEBIAN_FRONTEND=noninteractive` + `dpkg --force-confold` |
| 双击修复脚本 → 两个 dpkg 互杀 | 脚本必须带锁（`mkdir /root/.repair.lock || exit 0`），且**先等 20 秒再杀**陈旧进程 |

## 7. 工具链清单（原生编译 Linux ELF 所需，工具链装在平板本机）

```sh
apt install clang glslc zlib1g-dev python3-lz4 python3-capstone
# M2 加：libsdl3-dev libvulkan-dev
```

Ubuntu 26.04 源里都有（clang 21、glslc 2026.1、libsdl3 3.4.2）。dotnet 走 `dotnet-sdk-10.0`。
`build.py --os linux` 用系统 clang/gcc 出 glibc ELF（`nxnative/dm/linux/` 前端），
**不需要 NDK、不需要 sysroot**。

> 2026-11-27 更新：这条"平板本机装工具链"的路线已被**包内工具链**取代——
> AppImage 厚包自带 clang/glibc 前缀/链接件，平板零安装，见 §14。本节保留给
> 开发机上手动搭环境时参考。

## 8. 桌面点击脚本（repair.sh 模式）

- 日志**永远保留且放桌面**（用户要看得见；"成功删日志"是蠢设计，已废除）
- 失败时日志留着，成功也留着——用户随时点开看
- 一键脚本的输出文件名固定，别让用户猜

## 9. 出事时的顺序

1. `adb devices` 确认连接（§1）
2. 扫 /proc 找孤儿 apt/dpkg，杀掉（§5）
3. `ls -lnZ` 抽查属主/标签是否被 adb 侧污染（§0）
4. 有污染 → 整树 chown/chcon 归位（§0）
5. 系统级修复（dpkg --configure 等）→ **让用户在自己终端里跑**，或给出桌面一键脚本（§8）
6. 复盘写回本文件

## 10. AppImage 在 DroidDeck 上的三条启动路径

执行任何 AppImage 文件都会被 **binfmt 劫持**进 DroidDeck 的导入链
（`droiddeck-appimage-run` → 导入 → 游戏 GPU 管道）。三条路径：

| 路径 | 入口 | 经过 | 结果 |
|---|---|---|---|
| 点 AppImage 文件 | 桌面/文件管理器 | 导入 → `droiddeck-appimage-run` → `droiddeck-game-gpu` → `droiddeck-gpu` → **gamescope**（嵌套 Wayland）→ AppRun | 游戏模式：嵌套屏默认 **1280x720**（`DD_WIDTH/HEIGHT`），桌面应用会被挤压+双标题栏 |
| 应用菜单 .desktop | `droiddeck-appimage-*.desktop` | 同上（`Exec=droiddeck-gpu /usr/local/bin/droiddeck-appimage-run /opt/appimages/user/<导入>`） | 同上；`droiddeck-window` Action = 无 `droiddeck-gpu` 的桌面窗口模式 |
| 直启脚本 | 桌面 .sh / 应用菜单自建项 | unsquashfs 直解 AppImage（**不执行本体**）→ 会话原生直启 AppRun | 桌面应用正解：一根标题栏（KWin）、原生最大化、无 gamescope |

- 导入区三处：`/root/.cache/droiddeck/appimages`（**易失**，会话重启清空）、
  `/opt/appimages/user/`（DroidDeck 界面导入的持久区）、`~/.local/share/nx2a/`（我们自己的）。
- 修复脚本级的启动问题，优先"直启"路径；gamescope 链路的分辨率/双栏由 DroidDeck 侧决定，包内改不了。

## 11. glycin/bwrap abort（Ubuntu 26.04 GTK 的地雷）

症状：应用**静默死亡**（SIGABRT，无 traceback），或文件选择弹窗尺寸错乱/按钮不可见。
dmesg/日志深处：`Gtk:ERROR: gtkiconhelper.c ... assertion failed: Failed to load
image-missing.svg: Loader process exited early`，Command 一行是 bwrap 全家桶。

根因链：Ubuntu 26.04 的 GTK 图标/图片加载走 **glycin 加载器 + bwrap 沙箱**；
DroidDeck rootfs 把 `/usr/bin/bwrap` 的文件 capabilities 剥了，且桌面会话 uid
执行时 caps 再被剥 → 沙箱起不来 → 加载器退出 → **Ubuntu 的 GTK 补丁对图标加载
失败直接 abort 整个进程**。库为空时（如第一次启动、无游戏图标）不触发，
所以"之前能跑"——一个图标加载就引爆。

修复（root，一行，可逆 `setcap -r`）：

```sh
setcap cap_setuid,cap_setgid,cap_sys_admin,cap_sys_chroot=+ep /usr/bin/bwrap
```

- `GLYCIN_SANDBOX_MECHANISM=none` 在这台构建上**无效**（strings 无此开关），别再试。
- 桌面应用的正解是 §10 的直启路径（不经过 gamescope 也就不经过部分沙箱层），
  但图标加载仍走 glycin → **setcap 是治本**。

## 12. 桌面一键脚本的坑（start-*.sh 模式）

| 坑 | 事实/解法 |
|---|---|
| `mkdir 锁 || exit 0` + 末尾 `exec` | exec 替换进程后 `rmdir` 锁是死代码 → **锁永久残留 → 之后每次点击静默退出**。修法：去掉脚本级锁（应用自己的 flock 足够），或不用 exec 而以前台子进程跑、退出后删锁 |
| 双击竞争 | 两个实例同时 `rm -rf` + `unsquashfs` 互相拆台（一次失败一次成功，最终能跑但日志混乱）。应用内 flock 会拒绝第二个实例，竞争只伤导入步骤——可接受，但要知道 |
| unsquashfs 保留包内 mtime | "桌面 AppImage 是否比已装的新"的 **mtime 对比恒为过期**（解出的文件 mtime 是打包机的时间）。改用包内版本号文件，或每次都重新解包 |
| 日志 | 一切输出重定向进桌面 .txt/.log（终端点击看不到 stdout）；成败都保留 |

## 13. guest 屏幕分辨率：1280x720 逻辑屏

- guest 里一切查询（Gdk/X/ctypes）得到的都是 **1280x720**；Android 侧把它放大到
  物理 2000x1250 面板。**"应用窗口和桌面大小不一样"的定位从这里开始**：
  先分清是"guest 内没铺满"还是"Android 层缩放"——前者是应用/容器的窗口状态问题，
  后者是 DroidDeck 平台行为（包内改不了）。
- 复现/诊断手法：抓一个活的桌面进程（plasmashell）的 `/proc/<pid>/environ` 当会话 env，
  root setuid 降权（`os.setgid/setuid(10284)`）后用该 env 复现用户点击的完整条件；
  SIGSYS/崩溃时在 python 里装 `signal.signal(SIGSYS, 打栈handler)` +
  `faulthandler.enable()`，死亡现场直接进日志。

## 14. 构建线（2026-11-27 点亮：root 树跑移植，包自包含）

AppImage 厚包自带整套构建工具链（clang + glslc + glibc 前缀 + dotnet runtime +
预编译 C# 工具 + pylibs），平板上**零安装**。构建不跑在桌面会话树（§10 的
seccomp 杀 dotnet），跑在 **adb root 树**：

```sh
# 判别实验（3 秒）：root 树有没有 seccomp
adb shell "sh /data/local/tmp/guest.sh sh -c 'dotnet --info'"   # 活 = 这棵树干净

# 脱离启动（setsid 从 Android 侧进，不随 adb 断连死；日志重定向必须在 guest 内）
adb shell "setsid sh /data/local/tmp/guest.sh sh -c 'sh <launch-env.sh> > /root/Desktop/port-run.log 2>&1' < /dev/null > /dev/null 2>&1 &"
```

launch-env.sh 的规矩（因果见专栏 05）：

- **env 必须在 python 启动前 export**——`os.environ.update()` 设 PYTHONPATH/
  LD_LIBRARY_PATH 无效（解释器/加载器启动时读）。逐项对照 `Env.kt guestEnv()`
  （权威模板）：PYTHONHOME/PYTHONPATH/LD_LIBRARY_PATH/PATH/TMPDIR/NX2A_* 全套
- `python3 -u`（进度实时落盘，否则死前缓冲区丢光）
- `NX2A_PACK_DIR` 直指库目录，包落库后 `chown -R 10284:10284` 归位，启动器库页即显

包内 glibc 前缀必须带**链接件**（build_appimage.py deb 清单已进）：
gcc 的 `crtbegin/crtend` + `libgcc`（clang 编译不用 gcc，但 gnu 三元组链接要；
放进 `<sysroot>/usr/lib/gcc/<三元组>/<版本>/` clang 自动认）、`libvulkan.so`
dev 符号链接、usrmerge 的 `lib → usr/lib` 符号链接（glibc 链接脚本写绝对路径）。

linux 线主机构建 = `--gfx null`（phone_port.py build_cmd 统一加）：
dm/linux 是 headless 线（null 图形/音频/影片），VK-on-linux 的窗口故事还不存在，
别在包里开 VK 构建。

坑：porter 的阶段缓存有效（nx_extract/着色器秒过），构建迭代只花在失败的那一阶段；
每次 `port` 重跑前**先删旧日志**（build-test-log.txt 会滚成几百 KB）。

## 15. DroidDeck 执行模型（读源码定案）与会话树结论（2026-11-27 深夜；2026-11-28 重大更新）

> **2026-11-28 更新：§15 的"会话内构建不可解"已被推翻——它只适用于 native userland 模式。**
> 用户开启 **proot 模式**后会话树构建/运行全线可用（fork+exec / 线程池 / 文件风暴三件套
> 探针全过，PySide6/厚包工具链正常，GUI 全量移植实测成功、host 205 源 0 失败、
> 游戏可跑）。部署与流程见 `.claude/skills/nx2a-tablet-gui` 与 `nx2a-tablet-port`
> SKILL（含会话 rootfs 的构建依赖包清单）。以下原文保留作 native 模式的踩坑记录。

**执行模型（tools/nativeguest 源码实证，因果见专栏 06）**：DroidDeck **没有 proot**——
与手机线同构：rootfs 的 glibc loader 直启 + LD_PRELOAD hook（libddnatv-hook）翻译
路径/exec/被禁系统调用。会话树带**安卓 app seccomp**，致命三件套
`set_robust_list`/`rseq`/`clone3`：DroidDeck 在会话启动时**二进制补丁自家 ld.so/libc**
（ElfSeccompPatch.kt）；nixport rootfs 是**源码级补丁**（patches/glibc/0001）——两家补丁
覆盖面不同，这是全部会话树怪象的根源。

**会话命名空间事实**：`/lib`、`/usr`、`/opt`、`/root` 可见且都指向 linuxfs。推论：
- payload 二进制的 PT_INTERP=`/lib/ld-linux` 在会话里解析到 **linuxfs 的 ld.so（2.43）**；
  `LD_LIBRARY_PATH` 喂 nixport libc（2.41）= **loader/libc 错配 → SIGBUS**。
  LD_LIBRARY_PATH 只给 pylibs（libc 走默认 = linuxfs 2.43）→ 一致配对 → 能跑。
- rootfs loader 显式调用**树内**程序 ✓（porter = rootfs python 全程 ✓）；调用**树外**
  程序被 fxd 守卫拒绝（"cannot execute X when renamed to ld-linux"，FXD_EXEC_ROOT
  前缀检查）。apphost 族（dotnet/nx_extract）另有 `/proc/self/exe = 自己` 的硬检查，
  显式 loader 形态必死——**apphost 只能走内核解析的 PT_INTERP，且路径必须内核可见**。

**hook + python 组合缺陷（DroidDeck 侧 bug，证据已备提 issue）**：
- 系统 python（DroidDeck 自家 3.14）+ hook：porter stage 1 文件操作 "Bad system call"
  （hook off 也死——linuxfs libc 层有未被 hook 模拟/补丁覆盖的被禁调用）
- 系统 python + hook + 线程池：**Bus error**（自家 python 也中招）
- nixport rootfs python（老 glibc，源码补丁）+ hook：stage 1–5 全过 ✓
⇒ **会话内点击构建当前不可解**（三个变体全灭）， porter 必须跑在 rootfs python 上、
  且构建整体走 adb root 树。修复指望：DroidDeck 修 hook（证据链已备）或常驻构建服务。

**FEX/x64 .NET 备份路线（已验证一半，记录备查）**：x64 dotnet --info 经 FEX 会话内
✓（droiddeck-open 自动路由 + FEX 自动安装）；FEX 进程的系统调用由 FEX 自己发 =
对 seccomp 天然免疫。坑：cs-tools DLL 是 **aarch64 R2R**，x64 runtime 加载不了 →
需 IL-only 重编（`dotnet publish` 默认产物）。性能：JIT 套娃，C# 段慢 10×+。
放弃原因：python 侧仍需 rootfs python + 显式 loader（见上），混合栈复杂度 > 收益。

**探针方法论坑（每条都烧过一轮）**：
- `export LD_LIBRARY_PATH` 全局设置会毒化测试脚本**自己的** head/env/cat
  （linuxfs 二进制吃到外来 libc）→ 探针层零污染：每条命令 `env VAR=… cmd` 单点
  注入；输出落 /tmp 文件、最后统一干净读取；**exit code 紧跟目标命令**（管道后
  `$?` 是 head 的）
- 对照实验要成对：hook on/off × libc 栈，一次点击出全矩阵（dd-matrix 模式）
- 内核审计（dmesg type=1326）抓 seccomp 调用号：厂商日志刷屏 + 限流 → 基本抓不到，
  别指望；SIGSYS handler（ctypes sigaction SA_SIGINFO，si_syscall@偏移 16）只在
  TRAP 类过滤器下有效，KILL_PROCESS 类静默死
- pylibs 不能进 LD_LIBRARY_PATH 全局（会遮蔽宿主 libc）；capstone 的裸名 dlopen
  用绝对路径 RTLD_GLOBAL 预载解决

## 16. 会话内构建的正解 = DroidSpaces 容器（2026-11-27 实证）

平板上的 **DroidSpaces**（root Linux 容器运行时，`/data/local/Droidspaces`）无
app seccomp 问题：构建/移植/运行在容器里原生全速（全 7 阶段 ≈ 60 秒，窗口也能
经 anland Wayland 桥上屏）。CLI、FUSE 桥的坑、payload 构建线的入口与验证阶梯，
**见 droidspaces SKILL**。本文件其余章节的会话树问题（§10/§15）不适用于容器。
教训（2026-11-27 深夜的弯路）：**容器环境不要搬 rootfs**——宿主已有完整 userland
（python/glibc/Vulkan），payload 只带宿主缺的（clang 工具链 + 编译期 sysroot +
dotnet + cs-tools）；给容器塞第二套 glibc 生态 = loader/libc 错配 + PT_INTERP
改写 + fxd 守卫三层新死因（全部实证过）。
