package com.nx.android.core.ui.nav

import android.view.KeyEvent
import kotlin.math.abs

/**
 * 手柄在 App 自己的界面里能做的事。
 *
 * 这一套含义只在这里定义一次：页面订阅它，不自己解释按键。
 *
 * 按**位置**解释——底部的面键是确认，右侧面键是返回。这与游戏里手柄默认映射的约定一致
 * （见 controller-center 的 D14：出厂字典按位置判定），提示条上画的也是这个位置。
 *
 * 它**不**读玩家在「手柄中心」里改的键位档案：那是「手柄 → 游戏」的路，这里是「手柄 → 界面」，
 * 两件事的方向不同，别接错。
 */
enum class NavKey { Up, Down, Left, Right, Confirm, Back }

/**
 * 按键码与摇杆 → [NavKey] 的换算。
 *
 * 纯函数，没有 Android UI 的依赖：JVM 里可直接测。
 */
object NavKeys {

    /** 摇杆推到底才算方向（十字键帽与左摇杆各一份，帽子优先）。 */
    const val STICK_THRESHOLD = 0.6f

    /** 按住不放时的连发节流：首键立即，之后每 [REPEAT_EVERY] 次重复发一次。 */
    const val REPEAT_EVERY = 3

    /** 按键码 → 导航动作。不是导航用的键返回 null。 */
    fun fromKeyCode(keyCode: Int): NavKey? = when (keyCode) {
        KeyEvent.KEYCODE_DPAD_UP -> NavKey.Up
        KeyEvent.KEYCODE_DPAD_DOWN -> NavKey.Down
        KeyEvent.KEYCODE_DPAD_LEFT -> NavKey.Left
        KeyEvent.KEYCODE_DPAD_RIGHT -> NavKey.Right
        KeyEvent.KEYCODE_DPAD_CENTER -> NavKey.Confirm
        KeyEvent.KEYCODE_BUTTON_A -> NavKey.Confirm   // 底部的面键
        KeyEvent.KEYCODE_BUTTON_B -> NavKey.Back       // 右侧的面键
        KeyEvent.KEYCODE_BACK -> NavKey.Back           // 手柄自己的返回键（Home 键等）
        else -> null
    }

    /**
     * 调试用的注入口子（`adb shell input keyevent`）能带进来的键。
     *
     * 只认十字键与两个面键：**不带**系统返回键，也别把软键盘的键吃了——
     * 调试的时候软键盘还要用（PhantomFix 那个对话框要输码）。
     */
    fun fromInjectedKeyCode(keyCode: Int): NavKey? = when (keyCode) {
        KeyEvent.KEYCODE_DPAD_UP, KeyEvent.KEYCODE_DPAD_DOWN,
        KeyEvent.KEYCODE_DPAD_LEFT, KeyEvent.KEYCODE_DPAD_RIGHT,
        KeyEvent.KEYCODE_DPAD_CENTER,
        KeyEvent.KEYCODE_BUTTON_A, KeyEvent.KEYCODE_BUTTON_B -> fromKeyCode(keyCode)
        else -> null
    }

    /**
     * 摇杆推到底的方向。
     *
     * x 往右是正，y 往下是正（Android 的坐标就是这样：上负下正）。
     * 两个方向都推到底时取更大的那个。
     */
    fun fromAxis(x: Float, y: Float, threshold: Float = STICK_THRESHOLD): NavKey? {
        val ax = abs(x)
        val ay = abs(y)
        return when {
            ax < threshold && ay < threshold -> null
            ax >= ay -> if (x > 0f) NavKey.Right else NavKey.Left
            else -> if (y > 0f) NavKey.Down else NavKey.Up
        }
    }

    /** 按住不放时该不该发：首键立即，之后按 [every] 的节奏发。 */
    fun repeatAllowed(repeatCount: Int, every: Int = REPEAT_EVERY): Boolean =
        repeatCount == 0 || repeatCount % every == 0
}
