package com.nx.android.domain

/**
 * 每个游戏一份导出身份（包名、作者、邮箱、描述）的存取：`nx2a/apk-meta/<titleId>/meta.json`。
 * 弹框下次打开自动预填——填一次就够了。接口在域层（ViewModel/界面只见它），实现在 data 层。
 */
interface ApkMetaStore {

    /** 这款游戏上次的身份；没填过就是 null（包名让调用方回退到数据包清单里的现值） */
    fun read(titleId: String): ApkMeta?

    fun write(titleId: String, meta: ApkMeta)

    /** 这个游戏导出用过的版本名（最近在上）：弹框里提示「版本号已用过」 */
    fun usedVersions(titleId: String): List<String>

    /** 记一笔用过的版本名（导出开工时写） */
    fun recordUsed(titleId: String, versionName: String)
}
