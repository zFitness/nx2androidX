# dm/linux · Linux 运行时规格（SPEC）

> 目标：Switch 游戏以**原生 aarch64 Linux 进程**直接运行（DroidSpaces 容器 / 任何
> glibc ≥ 2.41 的 aarch64 Linux）。构建与运行环境 = DroidSpaces 容器
> （Ubuntu 26.04，python 3.14，glibc 2.43，Mesa freedreno Vulkan，anland Wayland 桥）。
> 开发循环入口：payload 的 `bin/nx2a-{env,build,run,probe}.sh`。

## 1. 已实证的事实（2026-11-27，全部一次点击/一条命令实测）

| 事实 | 证据 |
|---|---|
| porter 全 7 阶段在容器内原生全速 ✓ ×2 | `/opt/port-run.log`（extract 1.3GB、12,691 着色器、clang 181 源、pack）|
| 容器无 app seccomp 问题（线程池 1957 文件 ✓）| pool 测试 |
| SDL3 wayland 窗口 + Vulkan swapchain 上屏 ✓（180 帧）| `probe/sdl3_vk_clear.c`，GPU = Adreno 830v1（Mesa freedreno）|
| payload 二进制（trixie 2.41 构建）在容器 glibc 2.43 上直接运行 ✓ | 全程 |
| dmhost（linux 构建）启动即 FATAL `bionic's TLS_SLOT_APP is already in use` | 本 spec 的核心问题（§3）|

## 2. 架构总览：共享资产 + 三道缝

**共享（Android 线与 Linux 线同一份代码，一行不改）**：
- gfx_vk 全族渲染核心（gfx_vk_core/exec/dq/shader/tex/subgroup/quirks/ubo_comp）
  ——NVN 仿真 → Vulkan，跑在 **Mesa freedreno** 上（手机 = 同家族 Turnip/freedreno，
  同一颗 Adreno）
- 12,691 个翻译好的着色器 bundle（数据）
- hle 层主体、nvn_dirty 脏页跟踪、音频/影片的 hle 契约

**缝（平台差异，Linux 线的全部平台代码）**：

| 缝 | Android 侧 | Linux 侧 |
|---|---|---|
| S1 呈现/窗口 | ANativeWindow → VK_KHR_android_surface | SDL3 wayland 窗口 → SDL_Vulkan_CreateSurface |
| S2 内存 | 游戏内存页 → AHardwareBuffer(BLOB) → dma-buf → VkBuffer 导入 | memfd → udmabuf（或直接 VkDeviceMemory mmap）→ 同页 MAP_FIXED |
| S3 TLS 槽位 | bionic TLS_SLOT_APP 块 | loader 的 IE-TLS 数组（§3）|

## 3. TLS 槽位模式（本 spec 的核心设计）

### 3.1 机制现状（读 patch_nso.py + loader.c 确认）

改写后的代码访问四个特殊槽（K18=游戏的 x18、KTLS=tpidr_el0、KTLR=tpidrro_el0、
KGATE=宿主门入口）的序列是：

```
STP(保存) → emit_tp(T) → emit_key_addr(K) → ADD(base, K) → LDR/STR
```

- `emit_tp`：apple → `MRS tpidrro_el0`；android → `MRS tpidr_el0` + `LDR [t,t,2]`
- **key page**（模块补丁区的一页，loader 填写）：存的是**每键相对 tp 的偏移**
  （loader.c 的 tsd_check/tls 读取实证：`key_page_off + key_idx[kind]*8`）

⇒ **改写器对目标的支持 = emit_tp 一个函数**。apple 的 emit_tp = 裸 `MRS tpidrro_el0`
——Linux 内核的同名寄存器语义相同（线程指针）⇒ **改写器零改动**（DM_TARGET=apple
原样使用）。

### 3.2 Linux 变体的设计：loader 自有的 IE-TLS 数组

**关键洞察**：key page 的内容由 loader 填写 ⇒ 槽位位置由 loader 决定，不依赖任何
libc 布局。

```c
// loader.c（DM_TSD_LINUX 模式）
__thread uint64_t dm_slots[8];            // initial-exec：落在 glibc 静态 TLS 块，
                                          // 每线程一份，tp+固定偏移可达
// 初始化：off[k] = (uint64_t *)(&dm_slots[k]) - tp_now()   // 运行时实测偏移
//   写入模块的 key page（K18/KTLS/KTLR/KGATE 四项）
// dm_tsd_set/get：dm_slots[k] = v / 读 dm_slots[k]
```

- 改写后的代码：`MRS tpidrro_el0`（读 tp ✓ Linux 原生）→ `LDR [tp + off[k]]`
  = dm_slots[k] ✓ —— 落点 = **loader 自己的变量**，不碰 glibc 任何字段 ✓
- `dm.h`：`DM_TSD_APPLE` 下 dm_tsd_set/get 的 pthread 形式在 glibc 同样可用
  （pthread keys 与 tp 布局无关 ✓），但 dm_slots 直读更快更确定 → 统一用数组形式
- `tsd_check`：dm_slots[K18]=0x1234 → 读 `[tp+off[K18]]` 对比 ✓ 按构造成立
- 工作量：loader.c ≈ 50 行 + dm.h ≈ 10 行 + `patch_nso.py` **0 行**

### 3.3 TLS：直接实现 linux 目标（CR 后定案；apple 探针已从代码层面否决）

apple 模式探针**不必跑**：`tsd_check` 读 `tpidrro_el0`——Linux 64 位任务该寄存器内核
不维护（读到 0/残渣），随后按 key*8 小整数对近零地址解引用 = **SIGSEGV 野指针崩溃**
（不是干净的 die）。路线直接定为 `DM_TARGET=linux`（约 100 行，4 个文件）：

1. `patch_nso.py`：`TARGET` assert 加 `'linux'`；`emit_tp`（:118-120）加分支——
   `linux` = `emit(MRS_TPIDR(t))` **一条指令**（比 android 的两条还少）；
   `emit_key_addr/emit_slot_addr`（:122-126）目标无关，零改动；`# TARGET linux` 自动落盘
2. 宿主侧（loader.c）：`__thread uint64_t dm_slots[8]`（initial-exec；dmhost = PIE exe
   → 必然落静态 TLS，无 surplus 风险；若将来以 libdmhost.so dlopen，需
   `-ftls-model=initial-exec` 并验证）；启动时算
   `slot_off = (uint8_t*)&dm_slots[0] - (uint8_t*)__builtin_thread_pointer()`，
   `install_key_page`（:281）改写 `slot_off + key*8`
3. `dm.h`（:91-97）：DM_TSD_LINUX 分支——dm_tsd_set/get 直读数组（**无 pthread key、
   无析构器**：静态 TLS 随线程消亡，比 android 模式的 g_tsd_free 块管理更简单）；
   `read_layout` 的 `want`（:241-246）加 `"linux"`；`tsd_check` 照 android 版改读
   `tpidr_el0` 校验
4. apple 探针若要跑（诊断目的）：预期在 loader.c:44 对近零地址解引用 SIGSEGV，
   不是干净的 die

调用点（thread.c:12-27、hle_thread.c:341,354）在新宏下零改动；`-ffixed-x18`
（build.py:152）保证宿主代码生成不碰 x18。

### 3.3.1 v2（2026-11-27 实证后的重设计）：Horizon 布局复刻块

3.3 的首版（裸 `MRS tpidr_el0` + `slot_off + key*8` key page + 4 槽数组）**实证不够**：
SDK 不只经改写站点用槽，还把 TLS 基址**缓存进自己的全局**再按 Horizon 固定偏移
（如当前 ThreadType 在 TLS区+0x18、TLR 槽 0x1f8）访问——裸 TCB 基址下这些固定偏移
会撞进 glibc 的 TCB 字段或错槽（实证：SDK 把门值当成线程记录，分配器查空 →
`operator new` 返回 0 → 构造函数写空指针 SIGSEGV）。**android 的 TLS_SLOT_APP 块
本就是 Horizon 布局的完整复刻，linux 必须同形**：

1. `loader.c`：`__thread uint64_t dm_slots[512]`（静态 TLS，每线程自动就位；
   覆盖 Horizon 全部固定偏移槽）；`create_keys` 算 `slot_off`（实测 72）不变
2. `patch_nso.py`：`emit_tp`（linux）= `MRS tpidr_el0; ADDI t,t,#0`——imm12=0 占位，
   每个 TLS 站点的 ADDI 偏移写进 fixups.tsv（`# TPBASE_N`（**十六进制**，header
   解析器按 %lx 读）/ `# TPBASE_OFF` 逐条）；main 9875 / subsdk0 10209 / sdk 12969 处
3. `loader.c install_tpbase`：映射后（text 仍 RW）把每条 ADDI 的 imm12 烤成
   `slot_off` → 所有站点基址 = `tpidr_el0 + slot_off = &dm_slots[0]`；
   `install_key_page` 回归 android 形（`key*8`）——key 槽（dm_slots[1..4]）与
   SDK 固定偏移槽（dm_slots[H/8]）同落数组，永不触碰 glibc TCB
4. `dm.h`：`extern _Thread_local uint64_t dm_slots[512]`；dm_tsd_set/get 宏不变
   （dm_slots[k]，k=key 1..4）
5. 宿主每 guest 线程初始化（thread.c guest_thread_init，android/linux 共用）：
   dm_slots[2]=8KB TLS 块（KTLS）、dm_slots[3]=0x200 TLR 复刻（KTLR，tlr+0x1f8=
   宿主线程对象）、dm_slots[4]=dm_gate——语义与 android 完全一致

**实证状态**：tsd_check ✓；33053 个 tp 基址全部烘焙 ✓；SDK 跳板链
（*(base+0x18)=当前 ThreadType → TLR → 0x1f8 → 线程对象 → +504 → 值数组）
逐级解引用全通 ✓；无漏改 mrs/msr 站点（全量扫描 = TPBASE 计数）✓；
游戏启动推进到与 android 相同的位置（nnMain ✓ romfs ✓ NVN 建窗 ✓ HID ✓）。

### 3.3.2 当前阻塞点（M2 尾巴）：游戏的 TLS-2 堆上下文从未注册

崩溃点（确定性，0.4s）：`main+0x65a084`——游戏引擎首个 `operator new`（560B）→
`GetTlsValue(curThread, idx=2)`（idx 来自游戏线程信息 ctx+104=2）→ **entry[2]
从未被写（SDK 静态数组里是原始代码字节）** → 兜底「默认堆描述符
main+0x17584f8」也未写（=0）→ new 返回 null → 构造函数 strb [null+8] 崩。
同版本（v65536=1.0.1）同档案在 android dmhost 上可玩（上游 35 分钟 soak），
⇒ 纯 linux 宿主行为差异，非档案/版本问题。已排除：漏改站点（无）、
TPBASE 未烘焙（全烤）、TLR/ThreadType 链断裂（全通）、msr 切换未落槽
（dm_slots[2] 全程 = 宿主初值，但游戏自己的「当前 TLS 区」全局
main+0x1724738 指向堆上新分配的区域——两条「当前线程」链不一致是**最强线索**：
游戏全局链（堆对象，[+104]=2）vs TLR 链（SDK 静态 ThreadType，其值数组从未被写）。
**已排除**（2026-11-27 深挖）：TLS 管道无罪——SDK 在 0.329s 成功写 entry[2]
（DM_PROBE_WATCH 实证，pc=sdk+0x12c784，值为 ctx 指针）；崩溃时 ctx[0x88]
= ctx+0x30 也非零。分配路径实际返回的是 **第二上下文**（heap+0x220002F0，
= 第一上下文 +0xB0）的 [+0x88]，它 **=0** → 兜底「默认堆块 main+0x17584f8」
也 =0 → new 返回 0 → 构造函数把第二参数（管理器 block，=0）当目标指针
strb [0+8] 崩。

**android 独立基线已建立**（2026-11-27）：用 app 的 on-device NDK
（com.nx.android files/tool/toolchain/ndk，113MB，x86_64 host 工具 +
aarch64 sysroot；glslc 与 libshaderc.so.1 从 app toolchain bin/lib 补）
在容器里构建独立 android dmhost（--exe，/system/bin/linker64），平板上
裸跑 app 的 android 改写模块 + app 的 RomFS——**游戏健康运行 12-25s**
（开场电影解码、audren 音频、NVN 60fps p50 16.69ms、SIGTERM 优雅退出）。
构建命令：`build.py --game <tid> --ndk <app-ndk> --os android --gfx null
--release --exe`（arm64 主机分支：payload clang + NDK sysroot +
`-rtlib=compiler-rt`）。

**DM_HEAPTRACE 双平台时间线**（probe.c 新仪器，50ms 采样、变化才打印）：

| 时刻 | linux | android |
|---|---|---|
| ~0.29/0.33s | default-block=0, second[0x88]=0 | default-block=0, second[0x88]=0 |
| ~0.35s（引擎首个 560B 分配） | **仍全 0 → 崩** | 分配**成功**（default-block 在 0.34-1.33 间被写） |
| ~1.3s | （已死） | default-block=0x704714af38 |
| ~2.1s | — | second[0x88] = 0x704714af38（引擎分配器采纳了默认块）|

SetHeapSize 两平台应答形状一致（0xc9400000 → 32MB 对齐基址）→ 不是宿主
应答差异。**剩余问题唯一且明确：android 上游戏在 ~0.35s 写
default-block（main+0x17584f8）的执行路径，在 linux 上没跑或写失败**。
该字段的写入者不走直接指令偏移（全量反汇编无 #0x4f8/#0x4f0 str/stp 命中
= 经计算指针/成员方法写）。下一步三选一：(a) 从 nn::mem init 的
「默认上下文注册」方法反向 RE（静态构造器路径）；(b) 给宿主加逐 HLE
调用日志，diff 两平台 0.28-0.36s 窗口；(c) 检查游戏按内存布局分支的
输入（nn::oe/GetSystemInfo 类）在两平台的返回差异。仪器已就位：
DM_HEAPTRACE（双平台）、DM_PROBE_WATCH（注意页粒度一次性盲区）、
崩溃探针（crash.c，linux-only 块已守卫）。

### 3.3.3 B 阶段结论（2026-11-27：宿主调用逐条对照 → 转入 A）

对等核验先行：两平台 Build ID、cuts/obs/gates 表、改写器源码哈希、档案
（android.tsv/game.tsv md5）、player_api_revision、--gfx null 全部一致 ✓。

新仪器 `DM_TRACESVC`（hle_svc.c：svc_dispatch 包一层，进出各记一行：
编号、线程句柄、相对化调用点（两平台模块布局一致 → 偏移直接可比）、
x0-x3、返回值；6 万行封顶）+ `DM_TRACETLS`（loader.c：KTLS/KTLR 槽变化
即记，即 guest `msr tpidr_el0` 的区域切换）。

**主线程 SVC 序列逐条对照：前 48 个事件完全一致**——GetInfo 内存布局
爆发（各 region 尺寸/偏移 SAME，绝对基址 DIFF = ASLR，相对化后同一布局，
含 option C 的内存布局与系统信息查询）、SetHeapSize（同尺寸 0xc9400000、
同对齐级别）、线程 0x1004/0x1005 创建与启动、优先级/核掩码设置。
**第 49 个事件起分叉：android 主线程继续 QueryMemory+MapMemory（新线程栈）
→ CreateThread 0x1006 → 引擎线程池（0x1006-0x1024）；linux 主线程在
StartThread(0x1005) 后无任何 SVC，纯 guest 代码 ~60ms 后崩溃。**

⇒ 按方法论：宿主调用一致 → **转 A**：分析游戏在 [StartThread(0x1005) →
CreateThread(0x1006)] 窗口内的代码。崩溃锚点：pc main+0x65a084 ← 0xecf314
← 0x3159f8 ← 0xe85290 ← 0xe843e8 ← 0xe83bd4 ← 0x43cd04 ← 0x43d478 ←
0x439e08 ← 0x438158 ← 0x439690 ← 0x3a8ca4 ← guest_main。A 的任务：找
0x438158/0x439690/0x439e08/0x43d478/0x43cd04 引擎初始化帧里，管理器
block 字段注册被跳过/失败的分支条件（注意：这与「默认堆未注册」是同一
观察的两面，谁因谁果由 A 裁定）。

### 3.3.4 A 阶段首轮（2026-11-27）：tp 基址形状错误（真根因）+ 现状

**真根因确认**：v2 的 linux `emit_tp`（`mrs; addi #slot_off`）形状错了——android 的
`emit_tp`（`mrs; ldr t,[t,#16]`）加载的是 **KTLS 槽里的 TLS 区指针**（dm_slots[2]，
宿主 guest_thread_init 填、guest `msr tpidr_el0` 切换），后续 Horizon 固定偏移索引
**区的内部布局**；v2 却停在 `&dm_slots[0]`，偏移全落在复刻数组上——SDK 经缓存
基址的 TLS 访问（如 [区+0x18] 的当前 ThreadType）读到错误对象。这就是引擎分配
拿到 null 的原因（读链整体错位）。**修复**（4590fa71 + c3d8f9d1）：linux
`emit_tp` = `mrs; ldr t,[t,#0]`，loader `install_tpbase` 烘焙 imm12 =
`(slot_off+16)/8`（ldr x-form 按 8 字节缩放）——与 android 完全同形。

**修复后的新状态**（崩溃前移但性质改变）：旧崩溃（strb [null+8]）消失；游戏
**创建出引擎自己的线程池**（新崩溃线程 = 引擎新建线程），新崩溃 = 引擎线程
入口桩 `sdk+0xe02e6c`（`mrs→区→[区+*(0xddc018)]=当前 ThreadType→blr`）读到 0
→ blr 0。⇒ 新线程的 TLS 区里「当前 ThreadType」字段无人填写——android 上
同一桩能工作，说明 android 上该字段在入口前被填好（填写路径 = guest 经
改写站点的存储，或引擎预填）。**下一步仪器修正**（外部评审 2026-11-27 的
三条批评全部成立，记录在案）：
1. `site_tpidr_write` 是内联 STR 直写槽位，不经 dm_tsd_set_traced →
   DM_TRACETLS 看不到 guest 的区切换；android 侧也无对应仪器。→ 改造
   site_tpidr_write 发 `bl` 到宿主被追踪的 setter（双平台等价），恢复可见性。
2. DM_TRACESVC 的「一致」判据仅 (num, site)：GetInfo 返回值已单独比对一致，
   但 CreateThread 的 w4/w5（现 trace 已扩到 x0-x5）、QueryMemory 应答结构
   （现 trace 已转储）在首轮对照中未覆盖。
3. SVC trace 不覆盖直接 HLE 调用，「无 SVC ≠ 纯 guest」。
已上线的取证工具：游戏 patches.py 的 OBS 观察门（分配调用入参/结果、构造
函数入口、heap-ctx 查找、CreateBlock 入口/返回，7 个门）+ 宿主
hle_obstrace.c（DM_OBSTRACE，双平台寄存器日志）——同链双平台逐行差分。

### 3.4 已否决的路线（记录，防重蹈）

| 路线 | 否决原因 |
|---|---|
| android 模式直接跑（现状）| 放置依赖 bionic 的 TLS_SLOT_APP；glibc 线程无此概念 → create_keys FATAL（实测）|
| apple 模式原样（pthread_setspecific 当 TSD）| glibc 的 pthread_setspecific 写在 specific 数组，不在 tp+key*8；且 Linux 上 tpidrro_el0 读 0 → 探针是野指针 SIGSEGV，非干净失败（CR 定案：跳过探针）|
| FEX + x64 dotnet（C# 工具跑 FEX）| 可行但只解决 C# 工具；python 侧仍需 rootfs python + 显式 loader；混合栈复杂度 > 收益（已放弃，FEX 实证记录在案）|

## 4. 缝 1：呈现（SDL3 + Vulkan surface；CR 后细化）

四个致命/高项（CR F1/F2/F3/H1）：

1. **实例扩展（F1，第一个启动闸门）**：gfx_vk_core.c:183 的 iext 写死
   `VK_KHR_android_surface`，Linux loader 上该扩展不存在 → vkCreateInstance 直接
   die。DM_LINUX 下用 `SDL_Vulkan_GetInstanceExtensions()` 的返回构造 iext
2. **Android 头（F2）**：gfx_vk.h:8-10 的 VK_USE_PLATFORM_ANDROID_KHR +
   android/hardware_buffer.h + android/native_window.h + jni.h——glibc 无这些头。
   补 `android/compat/include/` 的 stub 头（类型/无操作原型返回失败），**不用
   #if 掉 700 行**（diff 最小、Android 路径零风险）
3. **链接缺失符号（F3）**：`dm_perf_frame/cost/window`（perf_android.c，非 weak）与
   `dm_overlay_font/theme`（overlay_theme.c，含 AAssetManager）不在 linux 文件集 →
   链接失败。补 `linux/perf_stub.c`（三个空实现）+ overlay_theme 的 DM_LINUX 读取
   路径（`dm_front_root()` 由 front_linux 提供，asset() 的文件分支现成）
4. **surface 创建线程（H1）**：窗口在主线程创建，swap_make 在 present 专用线程——
   SDL/wayland 的线程亲和坑。surface 只依赖 VkInstance → 由 front 线程在 vk_init 后
   代建，`VkSurfaceKHR` 存全局交 present 线程用

其余（CR M2/M3 确认）：format 选择/compositeAlpha/preTransform（Wayland 恒
IDENTITY）/FIFO/resize+swapchain 重建路径——现有代码已完整覆盖，DM_LINUX 分支
只需把 `ANativeWindow_getWidth/Height`（:180,190）换成 `SDL_GetWindowSize`，
extent 建议 clamp 到 min/maxImageExtent。VK_GOOGLE_display_timing 在 Mesa
wayland 可能没有 → 现有 fallback 顶替（帧率图精度降级，非阻塞）。

## 5. 缝 2：内存（CR 后修正：v1 copied-pool 先行，v2 dma-buf 导出）

**方案原表述的修正**：“host-visible VkDeviceMemory 直接 mmap MAP_FIXED”前提不成立
——VkDeviceMemory 无 fd，须 `VkExportMemoryAllocateInfo` + `vkGetMemoryFdKHR`
（VK_KHR_external_memory_fd / VK_EXT_external_memory_dma_buf）导出后再 mmap——机械
结构与 AHB 路线**同构**（`zc_fill` 消费的本来就只是 fd + VkBuffer），并不更简单；
且 ReBAR（host-visible+device-local 大堆）在 Adreno（UMA SoC）上不存在，
HOST_CACHED 与否须实测。

**v1（1-2 天，先落地能跑的）**：DM_LINUX 编译期强制零拷贝关闭
（`zc_off()`，gfx_vk_core.c:882，现为 opt-out 环境变量），池全走 **copied 层**——
`pool_copied_alloc`（:473-489）+ `vk_pools_sync`（:1126-1199，增量 64KB 脏块）+
`pools_copy_back`（:1260-1293）。这条路径今天就在 Android 上作为兜底运行，纯
Vulkan，freedreno 上必然工作。用 `zc_uncached`（:861-878）的思路测 turnip 的
host-visible 内存是否 CPU-cached，评估成本。

**v2（3-6 天，有设备探测风险）**：零拷贝换水源——`VkExportMemoryAllocateInfo(DMA_BUF)`
+ `vkGetMemoryFdKHR` + mmap MAP_FIXED，接入现有
`zc_fill/zc_unplace/slab/zcf/嵌套池` 机器（它们只消费 fd + VkBuffer，:621-633 实证）。
探测三件事：export 支持、该内存类型 HOST_CACHED 与否、CPU 读速与 malloc 之比
（复用 `zc_uncached`）。任一不满足就停在 v1。

**注意**：860 MB 池逐帧全量拷贝的先例（:1123-1124 “每秒几帧”、:879-880）说明
v1 的性能结论不能靠猜——先拿真机数据再决定 v2 投入。

配套：AHB 头做成 compat stub（无操作原型返回失败）而非 `#if` 掉 700 行；
`DM_VK_NO_ZEROCOPY` 在 DM_LINUX 编译期强制；MODULE_SLACK 的 `#ifdef __ANDROID__`
（loader.c:652-658，Link's Awakening 越界读 4.2MB 的 slack）并入 DM_LINUX。


## 6. 里程碑

| M | 内容 | 验收 |
|---|---|---|
| M1 | payload + 全 7 阶段构建（容器）✓ + front_linux 窗口化 ✓ | ✓ 已达成 |
| M2 | TLS linux 目标（§3.3，~100 行 4 文件）| dmhost 过 tsd_check，进入 guest_main |
| M3 | 缝 1 呈现（§4：F1-F3/H1 四项 + SDL surface，主线程代建）| 游戏画面上 DroidDeck 屏幕 |
| M4 | 缝 2 内存 **v1 copied-pool**（DM_LINUX 强制 zc_off）| 游戏资源加载/帧渲染稳定 |
| M5 | 真实游玩：输入/音频/影片（null）| 可玩性判定 |
| M6 | 缝 2 内存 **v2 零拷贝**（dma-buf 导出，探测驱动支持后）| 性能达标（对照 v1 数据）|

工作量（CR 复核）：M2 ≈ 2-3 天；M3 ≈ 2-3 人日；M4 v1 ≈ 1-2 天；遗漏项 ≈ 1-2 天；
**v1 可玩合计 ≈ 8-15 人日**；v2 零拷贝 +3-6 天（先拿 v1 真机数据再决定）。

## 7. 风险与开放问题

1. anland 桥的 Wayland 协议覆盖（xdg-shell/decoration）——SDL3 清屏已过 ✓，
   全功能窗口（resize/maximize）待验
2. freedreno 对交换链 present mode（FIFO ✓）与格式（BG8R8A8 ✓）已验；
   游戏着色器在 freedreno 上的编译正确性 = M3 后的实测项
3. udmabuf 内核配置未确认（§5 v2 的开关）；缺则 v1 copied-pool 顶上
4. glibc 静态 TLS：dmhost = PIE exe → dm_slots 必落静态 TLS ✓（CR 确认无
   surplus 风险；libdmhost.so 形态需 -ftls-model=initial-exec）
5. 内存池地址空间布局：MAP_FIXED 覆盖已有映射 = 现有机制已处理 ✓
6. turnip/freedreno 的 HOST_CACHED 与导出支持 = v2 前置探测（§5）
7. VK_GOOGLE_display_timing 缺失（Mesa wayland）→ pacing 精度降级，非阻塞
8. adrenotools 分支在 Linux 上 dlopen 失败 → [RED] 噪音日志，可 DM_ANDROID 静音
