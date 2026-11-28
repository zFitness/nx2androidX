# DroidSpaces：DroidDeck 平板上的 root Linux 容器（构建/运行的干净环境）

> **2026-11-28**：proot 模式开启后，**会话树线已可用**（见 `nx2a-tablet-gui` SKILL）——
> 启动器 GUI 的主部署线转为会话树；容器线保留作对比/后备（`droidspaces run` 曾出现
> 全命令 ENOENT，容器 init 活着、原因未查——用前先 `droidspaces run -- /bin/echo ok` 验活）。

DroidSpaces = 第三方 root Linux 容器运行时（OSS：github.com/ravindu644/Droidspaces-OSS），
装在 `/data/local/Droidspaces`。容器 `ubuntu26` = Ubuntu 26.04（glibc 2.43、python 3.14、
root 权限、systemd）。**与 DroidDeck 会话树是两个环境**：会话树的 hook + 安卓 app
seccomp 问题（见 droiddeck-debug SKILL §15）在这里**全部不存在**——普通 Linux 语义。
nx2androidX 的 Linux 构建线（payload 构建、host 编译、移植、运行）应在这里做。

## CLI（root；KernelSU 环境会话内亦可 su 调用）

```sh
/data/local/Droidspaces/bin/droidspaces run -- <命令>     # 在运行中的容器里执行
/data/local/Droidspaces/bin/droidspaces enter [user]      # 交互进入
/data/local/Droidspaces/bin/droidspaces show|info|pid     # 状态
data/local/Droidspaces/bin/droidspaces start|stop         # 生命周期
```

容器：`Containers/ubuntu26/rootfs.img`（ext4 镜像挂到 /，写入持久）；配置
`container.config`（enable_android_storage=1 → FUSE 存储可见）。

## 文件进出（FUSE 桥）

- Android `/sdcard/Download` ↔ 容器 `/storage/emulated/0/Download`（双向 ✓，
  root 直写 /data/media/0 也会出现在 FUSE 视图 ✓）
- **坑**：容器有自己的 `/data/local`（与 Android 的 `/data/local` 无关）；
  `/data/local/tmp` 会被清理（分钟级）；`droidspaces run` 的 stdin 转发不完整
  （大文件截断）——传文件一律走 FUSE 桥落文件
- **坑（2026-11-28 实测）**：`droidspaces run -- <cmd> args` 只吃**单命令**——
  管道/分号/引号会被 Android shell 抢先解释、报 "Failed to execute command: No such file or directory"。
  一律 `/bin/bash -c '<整段>'`；复杂脚本走 FUSE 桥落文件再执行
- **坑（2026-11-28 实测）**：容器 rootfs 的**默认 ACL 剥文件执行位**——tar 解包/FUSE
  传入的可执行文件变 664/666。部署后按 `git ls-tree <commit> | awk '$1=="100755"'`
  清单 chmod 755 还原（62 个文件在 nx2a 三棵树里）
- 桥上传的文件**丢执行位**：解包后 `chmod 755` 补

## nx2androidX 的 Linux 构建线（payload = nx2a-dd-payload 仓库）

payload 装在容器 `/opt/nx2a`；数据在 `/opt/nx2a-data/{work,library,nxhome,firmware,tmp}`；
keys 配置 = `/opt/nx2a-data/nxhome/config.json`（keys 指向 FUSE 路径的 prod.keys）。

```sh
droidspaces run -- sh -c 'NX2A_PAYLOAD=/opt/nx2a . /opt/nx2a/bin/nx2a-env.sh && \
  /opt/nx2a/bin/nx2a-build.sh 0100B99019412000'          # 重编 host（约 1 分钟）
droidspaces run -- sh -c 'NX2A_PAYLOAD=/opt/nx2a . /opt/nx2a/bin/nx2a-env.sh && \
  /opt/nx2a/bin/nx2a-run.sh /opt/nx2a-data/library/<游戏>-data'   # 运行（窗口 + 游戏）
droidspaces run -- sh -c 'NX2A_PAYLOAD=/opt/nx2a . /opt/nx2a/bin/nx2a-env.sh && \
  /opt/nx2a/bin/nx2a-probe.sh /storage/emulated/0/Download/games/test/<游戏>'  # 全 7 阶段
```

移植全 7 阶段原生全速（maliao1 全新无缓存 ≈ 60 秒：extract 1.3GB / rewrite /
12,691 着色器翻译 / clang 181 源 / pack）。产物经 FUSE 桥回启动器库页
（chown 10284:10284 归位）。

## 图形（已实证）

- GPU：`/dev/dri/renderD128` + Mesa freedreno ICD（Adreno 原生渲染，非 virgl）
- 显示：anland Wayland 桥（`WAYLAND_DISPLAY=wayland-0`，
  `XDG_RUNTIME_DIR=/run/user/1000`）——SDL3 窗口直接上 DroidDeck 屏幕
  （`probe/sdl3_vk_clear.c`：SDL3+Vulkan swapchain 180 帧 ✓）
- Vulkan 头：用 nxnative vendored 的（注意缺
  `VK_STRUCTURE_TYPE_SURFACE_CAPABILITIES_KHR` = 公开值 1000000000，需补 define；
  Ubuntu 26.04 的 libvulkan-dev 头同样缺——新 Vulkan-Headers 的拆分行为）
- 编译器：payload 的 clang 做 port 构建 ✓；临时编译用容器 gcc（payload clang
  的 cc1 在容器内单跑会崩，走 build.py 的完整构建不受影响）

## 开发闭环工具（devtools/droidspaces_dev.py，2026-11-27）

`python3 devtools/droidspaces_dev.py sync|build|run|collect|stop|status|selftest`：
本仓库 → 容器 `/opt/nx2a-data/dev/src`（只同步变化的源文件，含未提交修改）→
build.py 增量构建 → 整包原子装入 `<包>/host/dmhost` → 经 `<包>/run.sh`（启动器
自己的入口）跑测试图或游戏 → 证据（manifest/build.log/run.log/validation.log/
截图/退出状态）落在 `.gamedump/<App>/linux-dev/<测试号>/`。构建在容器里后台跑、
短连接轮询；`stop` 只结束本工具登记的进程（诱饵同名进程不受影响，selftest 9/9）。
构建环境 = 扁平 payload 的 clang/glslc + 容器自己的库；**运行环境 = 容器自己的
loader/libc/SDL3/Vulkan/Wayland，不要带 /opt/nx2a/rootfs 的 LD_LIBRARY_PATH**
（会让 libc 从 pylibs 加载，混搭系统库，§16 的教训在容器里同样成立）。
