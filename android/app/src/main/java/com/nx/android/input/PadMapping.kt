package com.nx.android.input

/**
 * 查表规则：物理键 → 游戏键。
 *
 * 一只手的键怎么认，是**两个维度**拼出来的：
 *
 * - **上报方式**（手柄的固件说了算）：按位置上报（上面那颗报 307）还是按印字上报
 *   （印着 Y 的那颗报 308——代码名就是它印的字）。两种固件都存在，游戏里都常见。
 * - **模式**（玩家在宿主菜单里选的，全局一个）：按位置（物理的上下左右 → NS 的 X/Y/A/B）还是
 *   按印字（手柄上印的字 → 同名的游戏键）。
 *
 * 两个维度拼出四张面键的表（见下面的四张）。面键之外的那些键（肩键、扳机、加减）
 * 两种上报方式都一样，不必分表。
 *
 * 游戏嘴里的 A/B/X/Y 指的就是 **NS 手柄上的四个位置**：X 在上、Y 在左、A 在右、B 在下。
 * 手柄上印的字只是贴纸——想要「印字说了算」的玩家在宿主菜单里选「按印字」。
 *
 * 没有扫描码的键（十字键）按 Android 的 keyCode 兜底——那上面没有歧义。
 *
 * 这份规则与宿主那边的一份是同一套：宿主按事件的 device 查同一张表（front_android.c 的 pad_labels）。
 */
object PadMapping {

    /** Android 的 keyCode（KeyEvent）：出厂字典用的就是它们。 */
    object Key {
        const val DPAD_UP = 19
        const val DPAD_DOWN = 20
        const val DPAD_LEFT = 21
        const val DPAD_RIGHT = 22
        const val BUTTON_A = 96
        const val BUTTON_B = 97
        const val BUTTON_X = 99
        const val BUTTON_Y = 100
        const val BUTTON_L1 = 102
        const val BUTTON_R1 = 103
        const val BUTTON_L2 = 104
        const val BUTTON_R2 = 105
        const val BUTTON_THUMBL = 106
        const val BUTTON_THUMBR = 107
        const val BUTTON_START = 108
        const val BUTTON_SELECT = 109
    }

    /** Linux 手柄规范的扫描码：BTN_SOUTH 是下面那颗，BTN_EAST 右边，BTN_NORTH 上面，BTN_WEST 左边。 */
    object Scan {
        const val SOUTH = 304
        const val EAST = 305
        const val NORTH = 307
        const val WEST = 308
        const val L1 = 310
        const val R1 = 311
        const val L2 = 312
        const val R2 = 313
        const val SELECT = 314
        const val START = 315
        const val L3 = 317
        const val R3 = 318
    }

    /** 面键之外的那些键：上报方式与模式都不影响它们。 */
    private val TAIL: Map<Int, String> = mapOf(
        Scan.L1 to "l", Scan.R1 to "r", Scan.L2 to "zl", Scan.R2 to "zr",
        Scan.L3 to "ls", Scan.R3 to "rs",
        Scan.SELECT to "minus", Scan.START to "plus",
    )

    /**
     * 面键：按位置上报 · 按位置。上面那颗（307）就是 NS 的 X，左边（308）是 Y。
     *
     * 这是绝大多数手柄的样子（Xbox 的 xpad 驱动、Switch Pro……）。
     */
    private val FACE_POSITIONAL_POSITION: Map<Int, String> = mapOf(
        Scan.SOUTH to "b", Scan.EAST to "a", Scan.NORTH to "x", Scan.WEST to "y",
    )

    /**
     * 面键：按位置上报 · 按印字。上面那颗在 Xbox 布局的手柄上印着 Y，它就是游戏的 Y。
     */
    private val FACE_POSITIONAL_LABEL: Map<Int, String> = mapOf(
        Scan.SOUTH to "a", Scan.EAST to "b", Scan.NORTH to "y", Scan.WEST to "x",
    )

    /**
     * 面键：按印字上报 · 按位置。
     *
     * 这种固件把「印着哪个字」直接编进代码里（印 X 的报 307、印 Y 的报 308），
     * 于是左右那两颗要按 Xbox 布局对调：印 X 的那颗在左边，NS 的左边是 Y。
     */
    private val FACE_CODED_POSITION: Map<Int, String> = mapOf(
        Scan.SOUTH to "b", Scan.EAST to "a", Scan.NORTH to "y", Scan.WEST to "x",
    )

    /**
     * 面键：按印字上报 · 按印字。代码名就是印字，信它：印 X 的报 307 → 游戏的 X。
     */
    private val FACE_CODED_LABEL: Map<Int, String> = mapOf(
        Scan.SOUTH to "a", Scan.EAST to "b", Scan.NORTH to "x", Scan.WEST to "y",
    )

    /** 四张表（面键 + 其余的键）。 */
    private val SCAN_POSITIONAL_POSITION = FACE_POSITIONAL_POSITION + TAIL
    private val SCAN_POSITIONAL_LABEL = FACE_POSITIONAL_LABEL + TAIL
    private val SCAN_CODED_POSITION = FACE_CODED_POSITION + TAIL
    private val SCAN_CODED_LABEL = FACE_CODED_LABEL + TAIL

    /**
     * 没有扫描码时的兜底：**Android 的 keyCode → 游戏键**（按位置上报 · 按位置）。
     *
     * 通用键位表（Generic.kl）按数字顺序起名：304→BUTTON_A、307→BUTTON_X、308→BUTTON_Y，
     * 于是 BUTTON_X 是上面那颗、BUTTON_Y 是左边那颗。
     */
    private val KEY_POSITIONAL_POSITION: Map<Int, String> = mapOf(
        Key.BUTTON_A to "b", Key.BUTTON_B to "a", Key.BUTTON_X to "x", Key.BUTTON_Y to "y",
        Key.BUTTON_L1 to "l", Key.BUTTON_R1 to "r", Key.BUTTON_L2 to "zl", Key.BUTTON_R2 to "zr",
        Key.BUTTON_THUMBL to "ls", Key.BUTTON_THUMBR to "rs",
        Key.BUTTON_START to "plus", Key.BUTTON_SELECT to "minus",
        Key.DPAD_UP to "up", Key.DPAD_DOWN to "down", Key.DPAD_LEFT to "left", Key.DPAD_RIGHT to "right",
    )

    /** 兜底 · 按位置上报 · 按印字。 */
    private val KEY_POSITIONAL_LABEL: Map<Int, String> = KEY_POSITIONAL_POSITION + mapOf(
        Key.BUTTON_A to "a", Key.BUTTON_B to "b", Key.BUTTON_X to "y", Key.BUTTON_Y to "x",
    )

    /** 兜底 · 按印字上报 · 按位置：名字就是印字，按 Xbox 布局换位。 */
    private val KEY_CODED_POSITION: Map<Int, String> = KEY_POSITIONAL_POSITION + mapOf(
        Key.BUTTON_X to "y", Key.BUTTON_Y to "x",
    )

    /** 兜底 · 按印字上报 · 按印字：名字就是印字，信它。 */
    private val KEY_CODED_LABEL: Map<Int, String> = KEY_POSITIONAL_LABEL + mapOf(
        Key.BUTTON_X to "x", Key.BUTTON_Y to "y",
    )

    /**
     * 出厂字典：这个物理键是哪个游戏键（不是手柄键就是 null）。
     *
     * @param scanCode 这个键的扫描码（0：没有）
     * @param keyCode Android 给它起的名字（只在没有扫描码时兜底）
     * @param labels 面键按印字（true）还是按位置（false）
     * @param printCoded 这只手按印字上报（true：代码名就是印字）还是按位置上报（false）
     */
    fun defaultTarget(
        scanCode: Int,
        keyCode: Int,
        labels: Boolean = false,
        printCoded: Boolean = false,
    ): String? {
        if (scanCode > 0) {
            val byScan = if (labels) {
                if (printCoded) SCAN_CODED_LABEL else SCAN_POSITIONAL_LABEL
            } else {
                if (printCoded) SCAN_CODED_POSITION else SCAN_POSITIONAL_POSITION
            }
            val target = byScan[scanCode]
            if (target != null) return target
        }
        val byKey = if (labels) {
            if (printCoded) KEY_CODED_LABEL else KEY_POSITIONAL_LABEL
        } else {
            if (printCoded) KEY_CODED_POSITION else KEY_POSITIONAL_POSITION
        }
        return byKey[keyCode]
    }

    /** 这个物理键是哪个游戏键（出厂字典 + 这只手的两种约定）。 */
    fun resolveButton(
        labels: Boolean,
        printCoded: Boolean,
        scanCode: Int,
        keyCode: Int,
    ): String? = defaultTarget(scanCode, keyCode, labels, printCoded)

    /**
     * 面键的**方位**：手柄上那四颗键各在哪儿。
     *
     * Linux 的扫描码说的是位置（BTN_NORTH 是上面那颗），Android 的 keyCode 说的是它在那儿叫什么
     * （BTN_NORTH 在 Android 那边叫 BUTTON_X）。方位是扫描码的事，所以面板上的菱形按它画。
     */
    object Face {
        /** 上面那颗（打印 Y 的那颗在 Xbox 布局的手柄上）。 */
        const val TOP = Scan.NORTH
        /** 左边那颗。 */
        const val LEFT = Scan.WEST
        /** 右边那颗。 */
        const val RIGHT = Scan.EAST
        /** 下面那颗。 */
        const val BOTTOM = Scan.SOUTH

        /** 四颗面键的扫描码。 */
        val CODES = intArrayOf(TOP, LEFT, RIGHT, BOTTOM)

        /** 这是不是一颗面键。 */
        fun isFace(scanCode: Int): Boolean = scanCode in CODES

        /**
         * 那颗键在 Android 那边通常叫什么 keyCode（通用键位表：扫描码与 keyCode 是一对）。
         *
         * 只是兜底：说了算的是位置（扫描码），而各家手柄的键位表不一定跟通用表一样
         * （任天堂的手柄就把上面那颗叫 BUTTON_Y）。
         */
        fun keyCodeOf(scanCode: Int): Int = when (scanCode) {
            Scan.SOUTH -> Key.BUTTON_A
            Scan.EAST -> Key.BUTTON_B
            Scan.NORTH -> Key.BUTTON_X
            Scan.WEST -> Key.BUTTON_Y
            Scan.L1 -> Key.BUTTON_L1
            Scan.R1 -> Key.BUTTON_R1
            Scan.L2 -> Key.BUTTON_L2
            Scan.R2 -> Key.BUTTON_R2
            Scan.SELECT -> Key.BUTTON_SELECT
            Scan.START -> Key.BUTTON_START
            Scan.L3 -> Key.BUTTON_THUMBL
            Scan.R3 -> Key.BUTTON_THUMBR
            else -> 0
        }
    }
}
