package com.nx.android.input

import android.view.InputDevice
import android.view.MotionEvent

/**
 * 轴事件的集合与轴角色的推断。
 *
 * App 把一只手柄的轴压成**定长的数组**推给宿主（jni 的 dm_java_event.axis），顺序这里说了算：
 * X Y Z RZ LTRIGGER RTRIGGER HAT_X HAT_Y BRAKE GAS RX RY——前 10 个是老顺序，RX/RY 是后补的
 * （老宿主只读前 10 个，追加不破坏它们）。
 *
 * 摇杆与扳机在哪几根轴上**因手柄而异**：NS 手柄与老式安卓约定是右摇杆在 Z/RZ、扳机在 LTRIGGER/RTRIGGER；
 * Xbox 族（USB 的 xpad、蓝牙的 XInput 式）恰恰相反——扳机在 Z/RZ（单向：从 0 起），右摇杆在 RX/RY。
 * [rolesOf] 按设备上报的量程判断它属于哪种：单向的 Z/RZ 是扳机的特征。认不出的手柄不给任何角色，
 * 宿主按老规矩消费（与以前逐字节一致）。
 */
object PadAxes {

    /** 事件轴数组的长度（宿主那边 struct 的 axis[12] 与它对齐）。 */
    const val COUNT = 12

    /** 事件轴数组的顺序：第 i 个槽是这根 Android 轴。 */
    val SLOT_AXES = intArrayOf(
        MotionEvent.AXIS_X, MotionEvent.AXIS_Y, MotionEvent.AXIS_Z, MotionEvent.AXIS_RZ,
        MotionEvent.AXIS_LTRIGGER, MotionEvent.AXIS_RTRIGGER, MotionEvent.AXIS_HAT_X, MotionEvent.AXIS_HAT_Y,
        MotionEvent.AXIS_BRAKE, MotionEvent.AXIS_GAS, MotionEvent.AXIS_RX, MotionEvent.AXIS_RY,
    )

    /** 从事件里读出整组轴（游戏页与库页共用这一个构造，两边看到的是同一份）。 */
    fun read(event: MotionEvent): FloatArray = read { event.getAxisValue(it) }

    /** 读法的本体（注入取值，测试不用构造 MotionEvent）。 */
    fun read(read: (Int) -> Float): FloatArray = FloatArray(COUNT) { i -> read(SLOT_AXES[i]) }

    /**
     * 一只手柄的轴角色：它的扳机与右摇杆在哪几根轴上。都不给 = 按老规矩（Z/RZ 当右摇杆，
     * 扳机走 LTRIGGER/RTRIGGER，0 值退 BRAKE/GAS）。
     */
    data class Roles(
        val zTrig: Boolean = false,   // 扳机在 Z/RZ（单向）：宿主从这两根轴取 ZL/ZR
        val rxStick: Boolean = false, // 右摇杆在 RX/RY：宿主的右摇杆改吃这两根轴
    )

    /** Android 的 axis id（MotionEvent 的常量）：角色推断只关心这四根。 */
    private const val AXIS_Z = 11
    private const val AXIS_RX = 12
    private const val AXIS_RY = 13
    private const val AXIS_RZ = 14

    /** 一根轴的量程（框架归一化之后的空间：摇杆 -1..1，单向的扳机 0..1）。 */
    data class Range(val axis: Int, val min: Float, val max: Float)

    /**
     * 从量程推断角色：入参是每根轴的（id, 下限, 上限）。
     *
     * Z/RZ **两根都单向**（下限 ≥ 0 且上限 ≤ 1）才算扳机——摇杆永远是双向的（-1..1），
     * 这是两种拓扑之间最硬的区别。上限这一半的判据不能省：有些手柄的内核量程是 0..255
     * （中心在 128），框架若照原样报出来，下限也是 0，只看下限会把**右摇杆**误当成扳机；
     * 限死上限 1，宁可漏认（老路照旧）也不误认。
     * RX/RY 存在且双向 → 右摇杆在那两根轴上。
     */
    fun rolesOf(ranges: List<Range>): Roles {
        val byAxis = ranges.associateBy { it.axis }
        val rxStick = (byAxis[AXIS_RX]?.let { it.min < 0f } == true) &&
            (byAxis[AXIS_RY]?.let { it.min < 0f } == true)
        val zTrig = (byAxis[AXIS_Z]?.let { it.min >= 0f && it.max <= 1f } == true) &&
            (byAxis[AXIS_RZ]?.let { it.min >= 0f && it.max <= 1f } == true)
        return Roles(zTrig = zTrig, rxStick = rxStick)
    }

    /** 从设备推断（只看摇杆来源的量程）。 */
    fun rolesOf(device: InputDevice): Roles = rolesOf(
        device.motionRanges
            .filter { it.isFromSource(InputDevice.SOURCE_JOYSTICK) }
            .map { Range(it.axis, it.min, it.max) },
    )
}
