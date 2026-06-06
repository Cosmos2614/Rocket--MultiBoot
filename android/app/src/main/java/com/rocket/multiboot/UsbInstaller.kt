package com.rocket.multiboot

import android.content.Context
import android.net.Uri
import androidx.documentfile.provider.DocumentFile
import java.io.File
import java.io.IOException

/** Operaciones de instalación: modo root (fdisk + mount) y modo SAF (sin root). */
class UsbInstaller(private val context: Context) {

    // ── Detección de root ─────────────────────────────────────────────────────

    fun isRootAvailable(): Boolean = try {
        val p = Runtime.getRuntime().exec(arrayOf("su", "-c", "echo ok"))
        val out = p.inputStream.bufferedReader().readText().trim()
        p.waitFor() == 0 && out == "ok"
    } catch (_: Exception) {
        false
    }

    // ── Comandos root ─────────────────────────────────────────────────────────

    private fun root(cmd: String): List<String> {
        val p = Runtime.getRuntime().exec(arrayOf("su", "-c", cmd))
        val lines = p.inputStream.bufferedReader().readLines()
        p.waitFor()
        return lines
    }

    // ── Detección de discos USB extraíbles (requiere root) ────────────────────

    fun findUsbDisks(): List<UsbDisk> {
        val out = root(
            "for d in /sys/block/sd*; do " +
            "[ -f \"\$d/removable\" ] && [ \"\$(cat \$d/removable)\" = '1' ] || continue; " +
            "n=\$(basename \$d); " +
            "s=\$(cat \$d/size 2>/dev/null || echo 0); " +
            "v=\$(cat \$d/device/vendor 2>/dev/null | tr -d ' '); " +
            "m=\$(cat \$d/device/model 2>/dev/null | tr -d ' '); " +
            "echo \"\$n|\$v \$m|\$((s*512/1024/1024))\"; " +
            "done"
        )
        return out.mapNotNull { line ->
            val p = line.split("|")
            if (p.size == 3) UsbDisk("/dev/block/${p[0].trim()}", p[1].trim(), "${p[2].trim()} MB")
            else null
        }
    }

    // ── Instalación completa con root ─────────────────────────────────────────

    fun installWithRoot(
        disk: UsbDisk,
        onLog: (String) -> Unit,
        onProgress: (Int) -> Unit
    ) {
        val path   = disk.path                              // p.ej. /dev/block/sdb
        val diskId = File(path).name                        // p.ej. sdb
        val p1     = "${path}1"
        val p2     = "${path}2"
        val mp1    = "/data/local/tmp/rocket_p1"
        val mp2    = "/data/local/tmp/rocket_p2"

        // — Tamaño del disco —
        val sectors = root("cat /sys/block/$diskId/size").firstOrNull()?.trim()?.toLongOrNull()
            ?: throw RuntimeException("No se puede leer el tamaño de $path")
        val sizeMb  = (sectors * 512L / (1024 * 1024)).toInt()
        val p2Mb    = 32
        val p1Mb    = sizeMb - p2Mb - 2

        onLog("Disco: ${sizeMb} MB  →  P1=${p1Mb} MB exFAT, P2=${p2Mb} MB FAT32")
        if (p1Mb < 100) throw RuntimeException("Disco demasiado pequeño (mínimo ~500 MB).")

        // — fdisk: crear tabla MBR —
        onLog("Particionando con fdisk…")
        val fdiskInput = "o\nn\np\n1\n\n+${p1Mb}M\nn\np\n2\n\n\na\n2\nw\n"
        root("printf '$fdiskInput' | fdisk $path")
        root("partprobe $path 2>/dev/null; blockdev --rereadpt $path 2>/dev/null; true")
        Thread.sleep(2000)
        onProgress(15)

        // — Formatear P1 exFAT —
        onLog("Formateando P1 como exFAT…")
        val fmtP1 = root("mkexfatfs -n Ventoy $p1 2>&1 || mkfs.exfat -n Ventoy $p1 2>&1")
        onLog("  ${fmtP1.lastOrNull() ?: "ok"}")
        onProgress(25)

        // — Formatear P2 FAT32 —
        onLog("Formateando P2 como FAT32…")
        val fmtP2 = root("mkfs.fat -F32 -n VTOYEFI $p2 2>&1")
        onLog("  ${fmtP2.lastOrNull() ?: "ok"}")
        onProgress(35)

        // — Montar particiones —
        onLog("Montando particiones…")
        root("mkdir -p $mp1 $mp2")
        root("mount -t exfat $p1 $mp1 2>/dev/null || mount $p1 $mp1")
        root("mount -t vfat  $p2 $mp2 2>/dev/null || mount $p2 $mp2")
        onProgress(40)

        // — Extraer assets al directorio de caché —
        onLog("Extrayendo archivos de arranque…")
        val tmp = File(context.cacheDir, "rocket_assets").also { it.deleteRecursively(); it.mkdirs() }
        for (folder in listOf("EFI", "ventoy", "tool", "config")) {
            extractAsset(folder, File(tmp, folder))
        }
        onProgress(60)

        // — Copiar EFI/ventoy/tool → P2 —
        onLog("Copiando archivos de arranque → P2…")
        for (folder in listOf("EFI", "ventoy", "tool")) {
            root("cp -r ${tmp}/$folder/ $mp2/")
            onLog("  ✔ $folder/")
        }
        onProgress(80)

        // — Copiar config → P1/ventoy/ —
        onLog("Copiando configuración y tema → P1…")
        root("cp -r ${tmp}/config/ $mp1/ventoy")
        root("mkdir -p $mp1/YUMI")
        onLog("  ✔ ventoy.json + tema YUMI + carpeta YUMI/")
        onProgress(95)

        // — Desmontaje y limpieza —
        root("sync")
        root("umount $mp1 $mp2")
        root("rm -rf $mp1 $mp2")
        tmp.deleteRecursively()

        onProgress(100)
        onLog("✔ ¡Instalación completada!")
        onLog("  Copia tus ISOs a la carpeta YUMI/ del USB")
    }

    // ── Copiar solo config/tema a USB existente (SAF, sin root) ──────────────

    fun copyConfigSaf(
        treeUri: Uri,
        onLog: (String) -> Unit,
        onProgress: (Int) -> Unit
    ) {
        val root = DocumentFile.fromTreeUri(context, treeUri)
            ?: throw RuntimeException("No se puede acceder a la unidad seleccionada")

        val ventoyDir = root.findFile("ventoy") ?: root.createDirectory("ventoy")
            ?: throw RuntimeException("No se puede crear la carpeta ventoy/ en la unidad")

        onLog("Copiando configuración y tema YUMI…")
        copyAssetToDocFile("config", ventoyDir, onLog, onProgress)

        // Crear carpeta YUMI para los ISOs
        root.findFile("YUMI") ?: root.createDirectory("YUMI")
        onLog("  ✔ Carpeta YUMI/ creada")

        onProgress(100)
        onLog("✔ Configuración copiada al USB")
    }

    // ── Copiar ISO al USB mediante SAF ────────────────────────────────────────

    fun copyIsoSaf(
        isoUri: Uri,
        treeUri: Uri,
        onLog: (String) -> Unit,
        onProgress: (Int) -> Unit
    ) {
        val rootDoc = DocumentFile.fromTreeUri(context, treeUri)
            ?: throw IOException("Unidad USB no accesible")
        val yumiDir = rootDoc.findFile("YUMI") ?: rootDoc.createDirectory("YUMI")
            ?: throw IOException("No se puede crear YUMI/")

        val srcName = context.contentResolver.query(isoUri, null, null, null, null)?.use { c ->
            val idx = c.getColumnIndexOrThrow(android.provider.OpenableColumns.DISPLAY_NAME)
            c.moveToFirst(); c.getString(idx)
        } ?: "archivo.iso"

        val destFile = yumiDir.findFile(srcName) ?: yumiDir.createFile("application/octet-stream", srcName)
            ?: throw IOException("No se puede crear $srcName en YUMI/")

        val total = context.contentResolver.openFileDescriptor(isoUri, "r")?.statSize ?: 1L
        var done  = 0L
        val chunk = 4 * 1024 * 1024  // 4 MB

        onLog("Copiando $srcName (${total / (1024 * 1024)} MB)…")

        context.contentResolver.openInputStream(isoUri)!!.use { inp ->
            context.contentResolver.openOutputStream(destFile.uri)!!.use { out ->
                val buf = ByteArray(chunk)
                var read: Int
                while (inp.read(buf).also { read = it } != -1) {
                    out.write(buf, 0, read)
                    done += read
                    onProgress((done * 100 / total).toInt())
                }
            }
        }
        onLog("  ✔ $srcName")
    }

    // ── Listar ISOs en el URI SAF ─────────────────────────────────────────────

    fun listIsos(treeUri: Uri): List<DocumentFile> {
        val root = DocumentFile.fromTreeUri(context, treeUri) ?: return emptyList()
        return root.listFiles()
            .filter { it.isDirectory || it.name?.endsWith(".iso", ignoreCase = true) == true }
            .flatMap { if (it.isDirectory) it.listFiles().toList() else listOf(it) }
            .filter { it.name?.endsWith(".iso", ignoreCase = true) == true }
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private fun extractAsset(assetPath: String, dest: File) {
        val entries = context.assets.list(assetPath)
        if (entries.isNullOrEmpty()) {
            dest.parentFile?.mkdirs()
            context.assets.open(assetPath).use { it.copyTo(dest.outputStream()) }
        } else {
            dest.mkdirs()
            for (e in entries) extractAsset("$assetPath/$e", File(dest, e))
        }
    }

    private fun copyAssetToDocFile(
        assetPath: String,
        destDir: DocumentFile,
        onLog: (String) -> Unit,
        onProgress: (Int) -> Unit
    ) {
        val entries = context.assets.list(assetPath)
        if (entries.isNullOrEmpty()) {
            val name = assetPath.substringAfterLast("/")
            val file = destDir.findFile(name) ?: destDir.createFile("application/octet-stream", name)
                ?: return
            context.assets.open(assetPath).use { inp ->
                context.contentResolver.openOutputStream(file.uri)?.use { inp.copyTo(it) }
            }
        } else {
            val dirName = assetPath.substringAfterLast("/")
            val dir = destDir.findFile(dirName) ?: destDir.createDirectory(dirName) ?: return
            for (e in entries) copyAssetToDocFile("$assetPath/$e", dir, onLog, onProgress)
        }
    }
}

data class UsbDisk(val path: String, val name: String, val sizeStr: String) {
    override fun toString() = "$name  ($sizeStr)"
}
