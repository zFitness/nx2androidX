package com.nx.android.data.library

import com.nx.android.domain.PortablePack
import org.json.JSONObject
import java.io.File
import java.util.zip.CRC32
import java.util.zip.ZipEntry
import java.util.zip.ZipFile
import java.util.zip.ZipOutputStream

/**
 * A container pack as one zip: the backup a phone leaves with, and takes in again.
 *
 * A container pack (manifest `container: true`) reads the player's own game file, so it is small:
 * mods, shaders, the host, the settings — no `RomFS/`, and the DLC copies stay out too (a relink
 * copies them back from the player's own files). What must not travel are the paths of the phone
 * that wrote it: the env rows naming its game file and keys are dropped, and the rows pointing
 * inside the pack are rewritten for the folder the backup lands in.
 *
 * The zip is written as `<name>.zip.partial` and renamed when complete; an import unzips into
 * `<name>.partial` and renames too, so the library scanner never sees a half-made pack.
 *
 * Pure file work: no Android, so the tests run on the JVM.
 */
object PortablePackZip {

    /** How often the progress is reported (every few megabytes). */
    private const val CHUNK_REPORT = 4L * 1024 * 1024

    /** The entries a zip of a backup must not carry, and an import must not accept. */
    private val UNSAFE = Regex("""(^/|(^|/)\.\.(/|$)|^[A-Za-z]:|\\)""")

    /**
     * Writes a container pack into `<targetDir>/<name>.zip`.
     *
     * @param pack the data pack to export (a container pack)
     * @param name the game's name: the zip and its folder are named after it
     */
    fun export(pack: File, targetDir: File, name: String,
               onProgress: (PortablePack.Progress) -> Unit = {}): PortablePack.Result {
        if (!pack.isDirectory) return PortablePack.Result.fail("no_pack")
        val manifest = PortablePack.readManifest(pack) ?: return PortablePack.Result.fail("no_manifest")
        // a pack that carries the game's files is exported as a folder: a zip would only add a copy step
        if (!manifest.optBoolean("container", false)) return PortablePack.Result.fail("not_container")
        val folder = PortablePack.folderName(name.ifBlank { pack.name.removeSuffix("-data") })
        val zip = File(targetDir, "$folder.zip")
        if (zip.exists()) return PortablePack.Result.fail("exists")
        val tmp = File(targetDir, "$folder.zip.partial")
        tmp.delete()
        tmp.parentFile?.mkdirs()
        val files = ArrayList<File>()
        val bytes = longArrayOf(0)
        collect(pack, pack, files, bytes)
        val progress = PortablePack.Progress(0, files.size + 2, 0L, bytes[0])
        onProgress(progress)
        try {
            var done = 0L
            val copied = intArrayOf(0)
            ZipOutputStream(tmp.outputStream().buffered()).use { out ->
                for (file in files) {
                    val rel = file.relativeTo(pack).invariantSeparatorsPath
                    val entry = ZipEntry("$folder/$rel")
                    val crc = CRC32()
                    entry.method = ZipEntry.STORED
                    entry.size = file.length()
                    copyRaw(file, out, entry, crc) { sofar ->
                        onProgress(progress.copy(files = copied[0], bytes = done + sofar))
                    }
                    copied[0]++
                    done += file.length()
                    onProgress(progress.copy(files = copied[0], bytes = done))
                }
                // the two management files, rewritten for the backup
                val man = PortablePack.manifestForZip(manifest, files.size + 2, bytes[0])
                writeEntry(out, "$folder/${PortablePack.MANIFEST}", man.toString(2).toByteArray())
                val env = File(pack, PortablePack.ENV).takeIf { it.isFile }?.readText().orEmpty()
                writeEntry(out, "$folder/${PortablePack.ENV}", PortablePack.envForZip(env).toByteArray())
            }
            if (!tmp.renameTo(zip)) { tmp.delete(); return PortablePack.Result.fail("cannot_place") }
            return PortablePack.Result.ok(zip.absolutePath, files.size + 2, bytes[0])
        } catch (e: Exception) {
            tmp.delete()
            return PortablePack.Result.fail(e.message ?: e.javaClass.simpleName)
        }
    }

    /**
     * Takes a backup into [portsDir]: unzips it under `<name>.partial`, validates the container
     * manifest, points its own rows at the folder and renames it.
     *
     * The pack it lands runs once the player relinks their own game file (the env rows that named
     * the exporting phone's file are gone).
     */
    fun import(zip: File, portsDir: File,
               onProgress: (PortablePack.Progress) -> Unit = {}): PortablePack.Validation {
        if (!zip.isFile) return PortablePack.Validation(false, "not_a_file")
        var tmp: File? = null
        try {
            ZipFile(zip).use { zf ->
                val entries = zf.entries().toList().filter { !it.isDirectory && !it.name.startsWith("__MACOSX/") }
                if (entries.isEmpty()) return PortablePack.Validation(false, "not_a_zip")
                if (entries.any { UNSAFE.containsMatchIn(it.name) || it.name.startsWith("/") }) {
                    return PortablePack.Validation(false, "bad_zip")
                }
                // the manifest is at the root, or inside the one folder the zip holds
                val manifestEntry = entries.filter { it.name.endsWith(PortablePack.MANIFEST) }
                    .minByOrNull { it.name.count { c -> c == '/' } }
                    ?: return PortablePack.Validation(false, "no_manifest")
                val prefix = manifestEntry.name.removeSuffix(PortablePack.MANIFEST)
                val inside = entries.filter { it.name.startsWith(prefix) }
                val manifest = JSONObject(zf.getInputStream(manifestEntry).reader().readText())
                if (!manifest.optBoolean("container", false)) return PortablePack.Validation(false, "not_container")
                val titleId = manifest.optString("title_id")
                if (!titleId.matches(Regex("[0-9A-Fa-f]{16}"))) return PortablePack.Validation(false, "bad_title_id")
                val root = prefix.trimEnd('/').substringAfterLast('/')
                    .ifBlank { PortablePack.folderName(manifest.optString("name")) }
                // the library only sees packs named `*-data` (the scanner's test): a zip's root folder is the game's plain name
                val folder = PortablePack.folderName(root)
                val final = File(portsDir, if (folder.endsWith("-data")) folder else "$folder-data")
                if (final.exists()) return PortablePack.Validation(false, "exists", pack = final)
                val total = inside.sumOf { it.size.coerceAtLeast(0) }
                if (portsDir.usableSpace in 1 until total + (64L shl 20)) {
                    return PortablePack.Validation(false, "no_space", pack = final)
                }
                val part = File(portsDir, final.name + ".partial")
                part.deleteRecursively()
                tmp = part
                val progress = PortablePack.Progress(0, inside.size, 0L, total)
                onProgress(progress)
                var done = 0L
                val files = intArrayOf(0)
                for (e in inside) {
                    val rel = e.name.removePrefix(prefix)
                    if (rel.isEmpty()) continue
                    val out = File(part, rel)
                    out.parentFile?.mkdirs()
                    zf.getInputStream(e).use { input ->
                        out.outputStream().buffered().use { output ->
                            val buffer = ByteArray(1 shl 16)
                            var reported = 0L
                            while (true) {
                                val n = input.read(buffer)
                                if (n < 0) break
                                output.write(buffer, 0, n)
                                done += n
                                if (done - reported >= CHUNK_REPORT) {
                                    reported = done
                                    onProgress(progress.copy(files = files[0], bytes = done))
                                }
                            }
                        }
                    }
                    files[0]++
                    onProgress(progress.copy(files = files[0], bytes = done))
                }
                // the rows that point inside the pack follow the folder it lands in
                val env = File(part, PortablePack.ENV)
                if (env.isFile) {
                    val text = env.readText()
                    env.writeText(PortablePack.envForZip(text, final))
                }
                val validation = PortablePack.validateContainer(part)
                if (!validation.ok) { part.deleteRecursively(); return validation }
                if (!part.renameTo(final)) { part.deleteRecursively(); return PortablePack.Validation(false, "cannot_place", pack = final) }
                return validation.copy(pack = final)
            }
        } catch (e: Exception) {
            tmp?.deleteRecursively()
            return PortablePack.Validation(false, e.message ?: e.javaClass.simpleName)
        }
    }

    /** The files of a pack a backup carries: no saves (the player's own), no DLC copies (a relink restores them). */
    private fun collect(root: File, dir: File, out: MutableList<File>, bytes: LongArray) {
        val children = dir.listFiles() ?: return
        for (child in children) {
            if (dir == root && (child.name == PortablePack.SAVES || child.name == PortablePack.AOC)) continue
            if (child.name == PortablePack.MANIFEST || child.name == PortablePack.ENV) continue   // written rewritten
            if (child.isDirectory) collect(root, child, out, bytes)
            else { out.add(child); bytes[0] += child.length() }
        }
    }

    /** One STORED entry, streamed so a 1 GB shader file is not held in memory. */
    private fun copyRaw(file: File, out: ZipOutputStream, entry: ZipEntry, crc: CRC32, onChunk: (Long) -> Unit) {
        var sofar = 0L
        var reported = 0L
        file.inputStream().buffered().use { input ->
            val buffer = ByteArray(1 shl 16)
            while (true) {
                val n = input.read(buffer)
                if (n < 0) break
                crc.update(buffer, 0, n)
                sofar += n
                if (sofar - reported >= CHUNK_REPORT) { reported = sofar; onChunk(sofar) }
            }
        }
        entry.crc = crc.value
        out.putNextEntry(entry)
        file.inputStream().buffered().use { input -> input.copyTo(out) }
        out.closeEntry()
        onChunk(sofar)
    }

    /** A small rewritten management file (the manifest, env.txt). */
    private fun writeEntry(out: ZipOutputStream, name: String, body: ByteArray) {
        val entry = ZipEntry(name)
        entry.method = ZipEntry.STORED
        entry.size = body.size.toLong()
        entry.crc = CRC32().apply { update(body) }.value
        out.putNextEntry(entry)
        out.write(body)
        out.closeEntry()
    }

    /** The manifest inside a zip, for a caller that wants to know the game before extracting it. */
    fun manifestIn(zip: File): JSONObject? = try {
        ZipFile(zip).use { zf ->
            val e = zf.entries().toList().filter { !it.isDirectory && it.name.endsWith(PortablePack.MANIFEST) }
                .minByOrNull { it.name.count { c -> c == '/' } }
            e?.let { JSONObject(zf.getInputStream(it).reader().readText()) }
        }
    } catch (e: Exception) {
        null
    }
}