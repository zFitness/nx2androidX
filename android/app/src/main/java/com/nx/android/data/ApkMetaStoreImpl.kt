package com.nx.android.data

import com.nx.android.core.storage.AppPaths
import com.nx.android.domain.ApkMeta
import com.nx.android.domain.ApkMetaStore
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import org.json.JSONObject
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 导出身份的落盘：`nx2a/apk-meta/<titleId>/meta.json`。包名会跟着数据清单走（作者邮箱描述同路）；
 * App 自己的版本重建不影响它（nx2a/ 目录是玩家的，环境更新不动）。
 */
@Singleton
class ApkMetaStoreImpl @Inject constructor(private val paths: AppPaths) : ApkMetaStore {

    private fun file(titleId: String) = File(paths.nxHome, "apk-meta/$titleId/meta.json")

    override fun read(titleId: String): ApkMeta? = runCatching {
        val f = file(titleId)
        if (!f.isFile) return null
        val o = JSONObject(f.readText())
        val pkg = o.optString("package")
        if (pkg.isEmpty()) return null
        ApkMeta(packageName = pkg,
            versionName = o.optString("version", "1.0.0"),
            author = o.optString("author"), email = o.optString("email"),
            description = o.optString("description"))
    }.getOrNull()

    override fun write(titleId: String, meta: ApkMeta) {
        val f = file(titleId)
        f.parentFile?.mkdirs()
        // 用过的版本历史原样保留（不经由 read 重建——那条路径会失真）
        val previous = runCatching { if (f.isFile) JSONObject(f.readText()) else null }.getOrNull()
        val o = JSONObject()
            .put("package", meta.packageName)
            .put("version", meta.versionName)
            .put("author", meta.author)
            .put("email", meta.email)
            .put("description", meta.description)
        previous?.optJSONArray("used")?.let { o.put("used", it) }
        f.writeText(o.toString(2))
    }

    override fun usedVersions(titleId: String): List<String> = runCatching {
        val arr = JSONObject(file(titleId).readText()).optJSONArray("used") ?: return emptyList()
        (0 until arr.length()).map { arr.optString(it) }.filter { it.isNotEmpty() }
    }.getOrDefault(emptyList())

    override fun recordUsed(titleId: String, versionName: String) {
        if (versionName.isBlank() || !file(titleId).isFile) return   // 还没有身份：等导出完成时一起落盘
        runCatching {
            val o = JSONObject(file(titleId).readText())
            o.put("used", used(titleId, versionName))
            file(titleId).writeText(o.toString(2))
        }
    }

    /** 用过的版本，最近在上（本次排最前），最多留 20 个 */
    private fun used(titleId: String, now: String): org.json.JSONArray {
        val arr = org.json.JSONArray()
        arr.put(now)
        usedVersions(titleId).filter { it != now }.take(19).forEach { arr.put(it) }
        return arr
    }
}

@Module
@InstallIn(SingletonComponent::class)
abstract class ApkMetaStoreModule {
    @Binds
    @Singleton
    abstract fun bindApkMetaStore(impl: ApkMetaStoreImpl): ApkMetaStore
}
