package com.nx.android.data

import java.io.Closeable
import java.io.File
import java.io.OutputStream

/**
 * Streams a tar archive out as it is written: the entries go down [out] as they are read from the disk, so a
 * game's data crosses to its destination without ever sitting in a second copy on the way.
 *
 * ustar headers. A name that does not fit the header goes out as a GNU long-name entry (or as a prefix
 * split), both of which the phone's own tar reads — the app's own unpack reads them too.
 *
 * No Android in it, so it is tested on the JVM: TarTest.
 */
class TarWriter(private val out: OutputStream) : Closeable {

    private val chunk = ByteArray(64 * 1024)
    private var closed = false

    /** A folder entry (the tree's shape survives: an empty folder arrives as an empty folder) */
    fun putDirectory(name: String, mtime: Long = now()) {
        out.write(entryHeader(name, 0L, mtime, MODE_DIR, '5'))
    }

    /**
     * A file's bytes under [name], as they are read. [onBytes] reports how much has gone (the caller turns it
     * into the progress). False when the file is not there — the walk keeps going, the check at the end of
     * the transfer catches what is missing.
     */
    fun putFile(name: String, file: File, mtime: Long = file.lastModified() / 1000,
                onBytes: ((Long) -> Unit)? = null): Boolean {
        if (!file.isFile) return false
        // ustar 的 size 域只有 11 位八进制（8 GiB 上限）：超了宁可让这次导出失败，也不写一个静默损坏的归档
        if (file.length() > MAX_FILE) throw IllegalStateException("file too large for a ustar archive: $name (${file.length()} bytes)")
        out.write(entryHeader(name, file.length(), mtime, MODE_FILE, '0'))
        file.inputStream().use { input ->
            while (true) {
                val n = input.read(chunk)
                if (n < 0) break
                out.write(chunk, 0, n)
                onBytes?.invoke(n.toLong())
            }
        }
        pad(file.length())
        return true
    }

    /** Small bytes that are not a file on the disk (a rewritten manifest, an env) */
    fun putBytes(name: String, bytes: ByteArray, mtime: Long = now()) {
        out.write(entryHeader(name, bytes.size.toLong(), mtime, MODE_FILE, '0'))
        out.write(bytes)
        pad(bytes.size.toLong())
    }

    /** The end of the archive: two zero blocks (the reader stops there) */
    override fun close() {
        if (closed) return
        closed = true
        out.write(ByteArray(BLOCK.toInt()))
        out.write(ByteArray(BLOCK.toInt()))
        out.flush()
    }

    /** The ustar header: the name (a GNU long-name entry when it does not fit), the sizes in octal, the sum */
    private fun entryHeader(name: String, size: Long, mtime: Long, mode: Long, type: Char): ByteArray {
        val bytes = name.toByteArray(Charsets.UTF_8)
        if (bytes.size > 100) {
            // no split fits: a GNU long-name entry carries the name, the real header repeats a truncated one
            val long = (name + "\u0000").toByteArray(Charsets.UTF_8)
            out.write(header("././@LongLink", long.size.toLong(), now(), MODE_FILE, 'L', ""))
            out.write(long)
            pad(long.size.toLong())
            return header(name.take(100), size, mtime, mode, type, "")
        }
        return header(name, size, mtime, mode, type, "")
    }

    private fun header(name: String, size: Long, mtime: Long, mode: Long, type: Char,
                       prefix: String): ByteArray {
        val h = ByteArray(BLOCK.toInt())
        name.toByteArray(Charsets.UTF_8).copyInto(h, 0)
        octal(mode, 8, h, 100)
        octal(0, 8, h, 108)   // uid: the shell's copy is chmod'ed readable at the destination anyway
        octal(0, 8, h, 116)   // gid
        octal(size, 12, h, 124)
        octal(mtime, 12, h, 136)
        // the checksum field is summed as spaces, then written over
        for (i in 148 until 156) h[i] = ' '.code.toByte()
        h[156] = type.code.toByte()
        "ustar".toByteArray(Charsets.UTF_8).copyInto(h, 257); h[262] = 0
        "00".toByteArray(Charsets.UTF_8).copyInto(h, 263)
        "root".toByteArray(Charsets.UTF_8).copyInto(h, 265)
        "root".toByteArray(Charsets.UTF_8).copyInto(h, 297)
        prefix.toByteArray(Charsets.UTF_8).copyInto(h, 345)
        var sum = 0
        for (b in h) sum += b.toInt() and 0xff
        val cs = ByteArray(8)
        digits(sum.toLong(), 6, cs, 0)
        cs[6] = 0
        cs[7] = ' '.code.toByte()
        cs.copyInto(h, 148)
        return h
    }

    /** An octal number in [width] bytes: digits then a NUL */
    private fun octal(value: Long, width: Int, into: ByteArray, at: Int) {
        digits(value, width - 1, into, at)
        into[at + width - 1] = 0
    }

    private fun digits(value: Long, count: Int, into: ByteArray, at: Int) {
        var v = value
        for (i in count - 1 downTo 0) {
            into[at + i] = ('0' + (v and 7).toInt()).code.toByte()
            v = v shr 3
        }
    }

    /** The padding that brings [size] up to a block boundary */
    private fun pad(size: Long) {
        val rest = ((BLOCK - size % BLOCK) % BLOCK).toInt()
        if (rest > 0) out.write(ByteArray(rest))
    }

    private fun now(): Long = System.currentTimeMillis() / 1000

    companion object {
        private const val BLOCK = 512L
        private const val MAX_FILE = (1L shl 33) - 1   // 11 位八进制：8 GiB − 1

        /** 0755（rwxr-xr-x）与 0644（rw-r--r--）：落地的 chmod 反正会把它们理顺，这里只是写进头里 */
        private const val MODE_DIR = 0x1EDL
        private const val MODE_FILE = 0x1A4L
    }
}
