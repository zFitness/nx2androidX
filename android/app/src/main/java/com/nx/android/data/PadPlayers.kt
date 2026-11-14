package com.nx.android.data

import com.nx.android.input.PadAssignment

/**
 * 谁玩谁：这个游戏里哪只手柄是几号玩家（**每个游戏一份**，跟抽屉里的其它行一样：
 * 帧率档位、帧生成、体感都是每个游戏各一份）。
 *
 * 存的是手柄的指纹（不认设备 id）：拔了再插，指纹不变，还是那个玩家。
 */
class PadPlayers(private val prefs: PrefsStore, private val titleId: String) {

    private val base = "players.${titleId.lowercase()}"

    fun load(): PadAssignment = PadAssignment(
        p1 = prefs.str("$base.1"),
        p2 = prefs.str("$base.2"),
        p3 = prefs.str("$base.3"),
        p4 = prefs.str("$base.4"),
    )

    fun save(a: PadAssignment) {
        prefs.put("$base.1", a.p1)
        prefs.put("$base.2", a.p2)
        prefs.put("$base.3", a.p3)
        prefs.put("$base.4", a.p4)
    }
}
