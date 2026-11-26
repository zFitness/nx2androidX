package com.nx.android.domain

import java.io.File

/**
 * 导出需要知道的游戏身份：数据包在哪、散装游戏文件在哪、叫什么。用基础类型说话，是为了让前台服务能从
 * Intent 的 extra 里把它拼回来（导出跑在前台服务里，Activity 的对象过不去）。
 */
data class GameRef(
    val titleId: String,   // 游戏的 title ID（versionCode 的偏移按它记）
    val label: String,     // 游戏的名字（APK 与通知都用它）
    val pack: File,        // 数据包文件夹（清单、图标、主题、env.txt 都在里面）
    val romfsAt: String,   // 散装游戏文件在哪：构建工作区；空 = 包自带 RomFS/
)

/**
 * The export of a finished port as a game of its own: an APK that gets installed on this phone, and the data
 * that game reads.
 *
 * The interface lives here so the interface layer does not depend on Android; the work is in
 * `data/GameApkExportServiceImpl.kt`, and it runs inside the foreground `ExportService` (a transfer of many
 * minutes must not die because the player left the app).
 */
interface GameApkExportService {

    /**
     * Exports the game, in one go: the APK is built into [targetDir] (that folder holds nothing else — the
     * data is not written into the player's storage), installed on this phone over the App's ADB channel, and
     * the data is streamed into the exported game's own directory over the same channel. The data exists
     * twice when this returns: in the pack it came from, and in the game's own directory.
     *
     * The channel has to be there before this is called ([paired]); the caller asks the player to pair first.
     *
     * @param onProgress how far it has come (the build, the install, the data)
     * @param log the guest's own lines (the last one is what the player reads)
     */
    fun export(game: GameRef, targetDir: File,
               onProgress: (GameApkExport.Progress) -> Unit = {},
               log: (String) -> Unit = {}): GameApkExport.Result

    /**
     * Whether the App's key is paired with this phone's adbd (the channel the install and the data ride on).
     * False when wireless debugging is off, or the player has never paired.
     */
    fun paired(): Boolean

    /**
     * The data only, again: the game is installed but its data did not make it (the channel dropped
     * mid-transfer). Streams the pack into the exported game's own directory once more — the tar overwrites
     * whatever of the last attempt landed.
     *
     * @param onProgress how far the transfer has come
     */
    fun moveData(game: GameRef, packageName: String,
                 onProgress: (GameApkExport.Progress) -> Unit = {},
                 log: (String) -> Unit = {}): Boolean
}
