package com.nx.android.input

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 谁玩谁：这个游戏里哪只手柄是几号玩家。
 *
 * 玩家 1 永远是手机（触屏的虚拟按键 + 体感），它再接手柄；默认「自动」——没被指派走的手柄都是它的
 * （跟今天一样：单人游戏插两只手柄都能玩）。锁死某一只之后，别的就闲置了。
 */
class PadAssignmentTest {

    private val a = "device:aaaa"
    private val b = "device:bbbb"
    private val c = "device:cccc"

    @Test
    fun `by default every controller plays player 1`() {
        val assignment = PadAssignment()
        assertEquals(0, assignment.playerOf(a))
        assertEquals(0, assignment.playerOf(b))
        assertEquals(0, assignment.playerOf(c))
    }

    @Test
    fun `the assigned controller plays its player and the rest stay with player 1`() {
        val assignment = PadAssignment().assign(1, b)
        assertEquals(1, assignment.playerOf(b))
        assertEquals(0, assignment.playerOf(a))
        assertEquals(0, assignment.playerOf(c))
    }

    @Test
    fun `a controller plays one player only, it moves when it is assigned elsewhere`() {
        val assignment = PadAssignment().assign(1, b).assign(2, b)
        assertEquals(2, assignment.playerOf(b))
        assertEquals("", assignment.p1)
        assertEquals("", assignment.p2)
    }

    @Test
    fun `locking player 1 to one controller sets the others aside`() {
        val assignment = PadAssignment().assign(0, a)
        assertEquals(0, assignment.playerOf(a))
        assertEquals(-1, assignment.playerOf(b))
        assertEquals(-1, assignment.playerOf(c))
    }

    @Test
    fun `a locked player 1 does not take a controller another player has`() {
        val assignment = PadAssignment().assign(1, b).assign(0, a)
        assertEquals(0, assignment.playerOf(a))
        assertEquals(1, assignment.playerOf(b))
        assertEquals(-1, assignment.playerOf(c))
    }

    @Test
    fun `clearing a player gives its controller back to player 1`() {
        val assignment = PadAssignment().assign(1, b).assign(1, "")
        assertEquals(0, assignment.playerOf(b))
    }

    @Test
    fun `player 1 is taken while a controller in use plays it`() {
        // 自动：没被指派走的手柄都算玩家 1 → 触屏的虚拟按键让位
        assertTrue(PadAssignment().player1Taken(listOf(a)))
        // 指派给玩家 2 之后玩家 1 空出来 → 虚拟按键回来（它是玩家 1 的那份）
        assertFalse(PadAssignment().assign(1, a).player1Taken(listOf(a)))
        // 锁死玩家 1 给另一只：这一只就闲置了，不再占玩家 1
        assertFalse(PadAssignment().assign(0, b).player1Taken(listOf(a)))
        // 两只都在用：玩家 1 那只占着
        assertTrue(PadAssignment().assign(1, b).player1Taken(listOf(a, b)))
        // 没有手柄在用：玩家 1 空着
        assertFalse(PadAssignment().player1Taken(emptyList()))
    }
}
