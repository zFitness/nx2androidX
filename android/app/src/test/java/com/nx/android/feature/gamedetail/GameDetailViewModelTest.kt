package com.nx.android.feature.gamedetail

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelStore
import android.net.Uri
import com.nx.android.data.saves.SaveIo
import com.nx.android.domain.GameApkExport
import com.nx.android.domain.GameApkExportService
import com.nx.android.domain.GameRef
import com.nx.android.domain.GameEntry
import com.nx.android.domain.playback.RunOptionsRepository
import com.nx.android.domain.playback.RunOptionsSnapshot
import com.nx.android.domain.saves.SaveRepository
import com.nx.android.domain.saves.SaveSource
import com.nx.android.domain.saves.SaveTarget
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.io.File

class GameDetailViewModelTest {
    @OptIn(ExperimentalCoroutinesApi::class)
    @Test
    fun `title keyed details keep per game options separate and clear on close`() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val options = FakeRunOptionsRepository()
        val store = ViewModelStore()
        try {
            val first = GameDetailViewModel(SavedStateHandle(), FakeSaveRepository(), FakeSaveIo(), options, FakeExportService(), com.nx.android.appstate.ExportState(), FakeApkMetaStore())
            val second = GameDetailViewModel(SavedStateHandle(), FakeSaveRepository(), FakeSaveIo(), options, FakeExportService(), com.nx.android.appstate.ExportState(), FakeApkMetaStore())
            store.put("detail-one", first)
            store.put("detail-two", second)
            val firstPack = File("/games/one")
            val secondPack = File("/games/two")

            first.open(TITLE_ONE, firstPack)
            second.open(TITLE_TWO, secondPack)
            advanceUntilIdle()

            assertEquals(TITLE_ONE, first.uiState.value.titleId)
            assertEquals("/games/one", options.readPacks[0].path)
            assertEquals(TITLE_TWO, second.uiState.value.titleId)
            assertEquals("/games/two", options.readPacks[1].path)

            first.selectLanguage("ja")
            advanceUntilIdle()
            assertEquals("ja", first.uiState.value.runOptions?.language)
            assertNull(second.uiState.value.runOptions?.language)

            first.close(TITLE_ONE)
            assertNull(first.uiState.value.titleId)
            assertEquals(TITLE_TWO, second.uiState.value.titleId)
        } finally {
            store.clear()
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    private class FakeRunOptionsRepository : RunOptionsRepository {
        val readPacks = mutableListOf<File>()
        private val values = mutableMapOf<String, RunOptionsSnapshot>()
        override suspend fun read(pack: File): RunOptionsSnapshot {
            readPacks += pack
            return values.getOrPut(pack.path) { RunOptionsSnapshot(language = null, driver = null) }
        }
        override suspend fun update(pack: File, language: String?, driver: String?): RunOptionsSnapshot =
            RunOptionsSnapshot(language = language, driver = driver).also { values[pack.path] = it }
    }

    private class FakeSaveRepository : SaveRepository {
        override fun titleIdInPackage(name: String): String? = null
        override fun suggestedPackageName(titleId: String, gameName: String): String = "save.zip"
        override suspend fun export(titleId: String, gameName: String, target: SaveTarget): Result<Unit> =
            Result.failure(UnsupportedOperationException())
        override suspend fun import(titleId: String, source: SaveSource): Result<Unit> =
            Result.failure(UnsupportedOperationException())
        override suspend fun erase(titleId: String): Result<Boolean> =
            Result.failure(UnsupportedOperationException())
    }

    private class FakeSaveIo : SaveIo {
        override fun target(uri: Uri): SaveTarget = throw UnsupportedOperationException()
        override fun source(uri: Uri): SaveSource = throw UnsupportedOperationException()
    }

    /** The export is not what this test is about: it only has to be there. */
    private class FakeExportService : GameApkExportService {
        override fun export(game: GameRef, meta: com.nx.android.domain.ApkMeta,
                            onProgress: (GameApkExport.Progress) -> Unit,
                            log: (String) -> Unit): GameApkExport.Result = GameApkExport.Result(false, "not_used")
        override fun channel(): com.nx.android.domain.ChannelState = com.nx.android.domain.ChannelState.OFF
        override fun moveData(game: GameRef, packageName: String,
                              onProgress: (GameApkExport.Progress) -> Unit,
                              log: (String) -> Unit): Boolean = false
    }

    /** 导出身份的假存取：内存里一份，够预填与保存的用例 */
    private class FakeApkMetaStore : com.nx.android.domain.ApkMetaStore {
        private var saved: com.nx.android.domain.ApkMeta? = null
        private val used = mutableListOf<String>()
        override fun read(titleId: String): com.nx.android.domain.ApkMeta? = saved
        override fun write(titleId: String, meta: com.nx.android.domain.ApkMeta) { saved = meta }
        override fun usedVersions(titleId: String): List<String> = used
        override fun recordUsed(titleId: String, versionName: String) { used.add(0, versionName) }
    }

    private companion object {
        const val TITLE_ONE = "0100000000010000"
        const val TITLE_TWO = "0100000000018000"
    }
}
