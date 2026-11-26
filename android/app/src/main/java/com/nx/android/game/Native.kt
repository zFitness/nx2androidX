package com.nx.android.game

import android.content.Context
import android.view.Surface

/**
 * The game's JNI surface (one libdmplay.so per game: the host statically linked with its entry, see
 * nxnative/dm/android/jni_android.c). Loaded with System.load of the copy in the app's private folder
 * (sdcard is noexec), started once per process — the host ends the process with the game, a second
 * start in one process is refused on the native side.
 */
object Native {
    /** 能力位：玩家前端（App 画虚拟手柄，宿主不画自己的面板） */
    const val FRONT_CAPS_PLAYER = 1
    /** 能力位：宿主为 App 的性能 HUD 数帧（老宿主还在画面上自己画帧率计数器） */
    const val FRONT_CAPS_PERF = 2
    /** 能力位：宿主能接第二个窗口（游戏到外接屏上，手机当手柄） */
    const val FRONT_CAPS_EXTERNAL = 4
    /** 能力位：呈现通路带超分（性能页的「超级分辨率」与「锐度」，存进数据包的 settings.txt） */
    const val FRONT_CAPS_SR = 8

    @JvmStatic external fun start(pack: String, internal: String, titleId: String?, dpi: Int, env: Array<String>, ctx: Context): Boolean
    @JvmStatic external fun setSurface(surface: Surface?)

    /**
     * 外接屏的画面：App 在接上的显示器（USB-C 的 DP 输出、扩展坞）上开一个 presentation，
     * 把它的 surface 交给宿主——游戏画到那里，手机（平板）自己变成手柄。
     * 传 null 表示那块屏没了：游戏回到手机自己的画面。
     */
    @JvmStatic external fun externalSurface(surface: Surface?)

    /**
     * Android 的游戏模式（系统的 GameManager）：2 = 性能档，1 = 标准，0 = 不知道。
     * 宿主那边（perf_android.c）据此换节奏策略：性能档里游戏自己的周期说话，系统的干预退场
     * （上游 #294 的原生策略）。
     */
    @JvmStatic external fun perfGameMode(mode: Int)
    @JvmStatic external fun motion(source: Int, device: Int, action: Int, ids: IntArray, xs: FloatArray, ys: FloatArray, axis: FloatArray): Boolean
    @JvmStatic external fun key(device: Int, source: Int, code: Int, action: Int, meta: Int, repeat: Int): Boolean

    /**
     * 按键事件，带它的物理扫描码（手柄中心的绑定按它认键）。
     * 老运行时的宿主没有这个入口（那边只有 [key]），所以 App 先看宿主有没有那几个新的入口，
     * 有才用这个 —— 老包照旧能用，输入不会断。
     */
    @JvmStatic external fun keyScan(device: Int, source: Int, code: Int, scan: Int, action: Int, meta: Int, repeat: Int): Boolean
    @JvmStatic external fun lifecycle(ev: Int)

    /**
     * 实体手柄的映射表：手柄中心推给宿主的行式文本（pad_map.h 读它）。
     * 一只设备一段：面键的翻法（labels）、摇杆死区（dz）、扳机阈值（tr），下面跟着它的绑定。
     * 游戏启动时推一次，玩家改了键再推一次。
     */
    @JvmStatic external fun padMapping(spec: String)

    /** 手柄上所有的键松开（手柄中心开着的时候输入是静音的：按住的键不能留在游戏里） */
    @JvmStatic external fun padReleaseAll()

    /** 运行中抽屉的帧生成：即时下发（DM_CTL 的 env 行走不到 JNI，这里直达宿主）；"<state> <reason>" 见 dm_framegen.h */
    @JvmStatic external fun frameGenSet(on: Boolean, mult: Int, target: Int, flow: Int)
    @JvmStatic external fun frameGenStatus(): String

    /**
     * 运行中抽屉的帧率档位：0 跟随游戏（自适应自由升降），60/40/30 钉住那一档。
     * 宿主那边是 perf_android.c 的 fps_pin，它每 30 帧重读一次环境变量，所以即时生效。
     */
    @JvmStatic external fun perfPinSet(fps: Int)

    /** 宿主现在的档位（它读 DM_FPS_PIN；0 = 自由自适应） */
    @JvmStatic external fun perfPinGet(): Int

    /**
     * 运行中抽屉的体感开关：设备的转动带动游戏里的六轴传感器（王国之泪的弓）。
     * 即时下发：宿主那边每 250 ms 重读一次环境变量（front_player.c 的 motion poll），所以改完立刻生效。
     */
    @JvmStatic external fun motionSet(on: Boolean, raw: Boolean)

    /** 宿主现在的体感开关：位 1 = 体感开着，位 2 = 保留甩动方向 */
    @JvmStatic external fun motionGet(): Int

    /**
     * 运行中抽屉的音频输出：游戏的声音走哪个设备（蓝牙耳机、USB 声卡…）。
     * 宿主那边立刻换（hle_audio.c 把在播的流停掉、在新设备上重启），不用重启游戏。
     * 0 = 跟随系统自己选。
     */
    @JvmStatic external fun audioSet(id: Int)

    /** 宿主现在的音频输出设备（0 = 跟随系统） */
    @JvmStatic external fun audioGet(): Int

    /**
     * 运行中抽屉的 GPU 提频："0" 关（用调频器自己的频率）、"1" 一直跑最高频、
     * "auto" 只在掉帧时拉高。宿主每 60 帧重读一次这个环境变量，所以即时生效。
     */
    @JvmStatic external fun gpuTurboSet(mode: String)

    /** 宿主现在的 GPU 提频档："0" / "1" / "auto" */
    @JvmStatic external fun gpuTurboGet(): String

    /** 运行中抽屉的宿主菜单行（画面与操作/存档）：what 0 overlay 1 opacity 2 rumble 4 docked 8 超分 16 锐度 */
    @JvmStatic external fun menuGet(what: Int): Int
    @JvmStatic external fun menuSet(what: Int, v: Double)
    @JvmStatic external fun menuState(): String
    @JvmStatic external fun menuEditOpen()
    @JvmStatic external fun menuSaves(): String
    @JvmStatic external fun menuExport()
    @JvmStatic external fun menuImport(name: String): Boolean
    @JvmStatic external fun menuExportNote(): String

    /**
     * 性能 HUD 的计数（gfx_vk_present.c 的 dm_present_sample）：0 游戏帧数、1 帧生成帧数、2 帧间隔之和(纳秒)、
     * 3 帧间隔的个数、4 屏幕的刷新周期(纳秒)。App 隔一秒读两次，自己算帧率与帧时间。
     */
    @JvmStatic external fun perfSample(): LongArray

    /** 虚拟手柄（App 绘制层）：布局（JSON，见 front_player.c 的 dm_pad_layout_json）：控件的位置与大小 */
    @JvmStatic external fun padLayout(): String

    /**
     * 虚拟手柄的输入：App 自己判定了每个手指落在哪个控件上，把结果告诉宿主——按键位、两个摇杆，
     * 以及属于游戏触摸屏的那些触点（窗口坐标，宿主自己换算到画面里）。
     */
    @JvmStatic external fun padInput(buttons: Long, lx: Int, ly: Int, rx: Int, ry: Int,
                                     ids: IntArray, xs: FloatArray, ys: FloatArray)

    /** 布局编辑（App 的编辑器）：控件的新位置与大小系数、恢复默认、保存进数据包的 settings.txt */
    @JvmStatic external fun padLayoutSet(ctl: Int, x: Float, y: Float, size: Float)
    @JvmStatic external fun padLayoutReset()
    @JvmStatic external fun padLayoutSave()

    /** App 自己的面板开着（布局编辑器）：游戏先等着 */
    @JvmStatic external fun hold(on: Boolean)

    /**
     * 手柄的显示与浓淡：App 的偏好是唯一真值，宿主只留运行时的副本（settings.txt 不再写这两项）。
     */
    @JvmStatic external fun padPrefs(shown: Boolean, opacity: Int)

    /** 正在使用的物理手柄个数（App 监听系统的输入设备后告诉宿主；宿主不再自己轮询设备列表） */
    @JvmStatic external fun padDevices(count: Int)

    /**
     * 游戏的文本输入：宿主挂起游戏的线程并通知 App，App 用系统输入法问玩家，再把文字交回宿主
     * （textResult 唤醒游戏的线程）。textRequest 是要问的内容（JSON：title/text/max）。
     */
    @JvmStatic external fun textRequest(): String
    @JvmStatic external fun textResult(ok: Boolean, text: String)

    /**
     * 宿主的前端版本（能力位）：旧前端的宿主没有这个入口（调用即抛 UnsatisfiedLinkError），App 据此
     * 认出「这个数据包是用旧前端编的」，请玩家重新移植。位：1 = 玩家前端（App 画手柄，宿主不画面板）。
     */
    @JvmStatic external fun frontCaps(): Int

    /**
     * 金手指：宿主那边这个游戏的金手指，JSON 数组（每条：名字 name、是否开着 on、不能跑的原因 why）。
     * 老宿主的宿主没有这个入口（调用即抛 UnsatisfiedLinkError），App 据此不显示这一页。
     */
    @JvmStatic external fun cheatsList(): String

    /**
     * 这个 build 的编号（金手指文件按它命名：main 的 build ID 的前 16 位十六进制，大写）。
     * App 用它去社区库里挑这个 build 的那一份（每个 build 一份文件，写错 build 会改坏游戏）。
     */
    @JvmStatic external fun cheatsBuild(): String

    /** 开关一条金手指：1 = 成功，-1 = 这条不能跑（要改游戏的代码之类），0 = 没有这条 */
    @JvmStatic external fun cheatsSet(index: Int, on: Boolean): Int

    /** 加载金手指（总开关打开时）：目录 = App 自己的金手指目录（下载来的文件在那里）；返回条目数（0 = 这个 build 没有金手指） */
    @JvmStatic external fun cheatsOpen(dir: String): Int

    /** 关掉金手指：宿主不再加载也不再执行 */
    @JvmStatic external fun cheatsClose()
}
