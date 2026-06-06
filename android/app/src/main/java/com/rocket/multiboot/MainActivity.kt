package com.rocket.multiboot

import android.app.AlertDialog
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.widget.ArrayAdapter
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.documentfile.provider.DocumentFile
import com.rocket.multiboot.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var installer: UsbInstaller

    private var hasRoot    = false
    private var usbDisks   = listOf<UsbDisk>()
    private var usbTreeUri: Uri? = null   // URI SAF de la unidad USB seleccionada

    // ── ActivityResult launchers ──────────────────────────────────────────────

    /** Selector de unidad USB (Storage Access Framework) */
    private val pickUsbTree = registerForActivityResult(
        ActivityResultContracts.OpenDocumentTree()
    ) { uri ->
        if (uri != null) {
            contentResolver.takePersistableUriPermission(
                uri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
            )
            usbTreeUri = uri
            val label = DocumentFile.fromTreeUri(this, uri)?.name ?: uri.lastPathSegment
            binding.tvSelectedUsb.text = "Unidad: $label"
            refreshIsoList()
        }
    }

    /** Selector de archivos ISO desde el almacenamiento del teléfono */
    private val pickIsos = registerForActivityResult(
        ActivityResultContracts.GetMultipleContents()
    ) { uris ->
        if (uris.isNotEmpty()) copyIsosToUsb(uris)
    }

    // ── Ciclo de vida ─────────────────────────────────────────────────────────

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        installer = UsbInstaller(this)

        setupBottomNav()
        setupInstallButtons()
        setupIsoButtons()

        // Verificar root y USBs en hilo de fondo
        Thread {
            hasRoot = installer.isRootAvailable()
            runOnUiThread { applyRootState() }
            refreshUsbDevices()
        }.start()
    }

    // ── Navegación inferior ───────────────────────────────────────────────────

    private fun setupBottomNav() {
        binding.bottomNav.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.nav_install -> {
                    binding.installSection.visibility = View.VISIBLE
                    binding.isosSection.visibility    = View.GONE
                    true
                }
                R.id.nav_isos -> {
                    binding.installSection.visibility = View.GONE
                    binding.isosSection.visibility    = View.VISIBLE
                    true
                }
                else -> false
            }
        }
        binding.bottomNav.selectedItemId = R.id.nav_install
    }

    // ── Sección Instalar ──────────────────────────────────────────────────────

    private fun applyRootState() {
        if (hasRoot) {
            binding.tvRootStatus.apply {
                text = "✔ Root disponible — instalación completa habilitada"
                setTextColor(getColor(R.color.ok))
            }
            binding.spinnerDisk.visibility = View.VISIBLE
            binding.btnInstall.visibility  = View.VISIBLE
            binding.tvNoRoot.visibility    = View.GONE
        } else {
            binding.tvRootStatus.apply {
                text = "⚠ Sin root — modo copia de configuración"
                setTextColor(getColor(R.color.warn))
            }
            binding.spinnerDisk.visibility  = View.GONE
            binding.btnInstall.visibility   = View.GONE
            binding.tvNoRoot.visibility     = View.VISIBLE
            binding.btnCopyConfig.visibility = View.VISIBLE
        }
    }

    private fun setupInstallButtons() {
        binding.btnRefreshUsb.setOnClickListener {
            Thread { refreshUsbDevices() }.start()
        }
        binding.btnInstall.setOnClickListener { confirmAndInstall() }
        binding.btnCopyConfig.setOnClickListener {
            pickUsbTree.launch(null)  // Abre el selector SAF
        }
    }

    private fun refreshUsbDevices() {
        if (!hasRoot) {
            runOnUiThread {
                binding.tvUsbStatus.text = "Conecta el USB y pulsa 'Seleccionar unidad USB'"
                binding.tvUsbStatus.setTextColor(getColor(R.color.text_dim))
            }
            return
        }
        usbDisks = installer.findUsbDisks()
        runOnUiThread {
            if (usbDisks.isEmpty()) {
                binding.tvUsbStatus.apply {
                    text = "⚠ Sin USB detectado. Conecta el USB y pulsa ↺"
                    setTextColor(getColor(R.color.warn))
                }
                binding.spinnerDisk.adapter = null
            } else {
                binding.tvUsbStatus.apply {
                    text = "✔ ${usbDisks.size} USB(s) detectado(s)"
                    setTextColor(getColor(R.color.ok))
                }
                binding.spinnerDisk.adapter = ArrayAdapter(
                    this, android.R.layout.simple_spinner_item, usbDisks
                ).also { it.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item) }
            }
        }
    }

    private fun confirmAndInstall() {
        val idx = binding.spinnerDisk.selectedItemPosition
        if (usbDisks.isEmpty() || idx < 0) {
            logInstall("⚠ No hay USB seleccionado")
            return
        }
        val disk = usbDisks[idx]
        AlertDialog.Builder(this)
            .setTitle(getString(R.string.confirm_install_title))
            .setMessage(getString(R.string.confirm_install_msg, disk.toString()))
            .setPositiveButton(R.string.yes) { _, _ -> startInstall(disk) }
            .setNegativeButton(R.string.cancel, null)
            .show()
    }

    private fun startInstall(disk: UsbDisk) {
        binding.btnInstall.isEnabled      = false
        binding.btnRefreshUsb.isEnabled   = false
        binding.progressInstall.progress  = 0
        logInstall("Iniciando instalación en ${disk.name}…")

        Thread {
            try {
                installer.installWithRoot(
                    disk,
                    onLog      = { msg -> runOnUiThread { logInstall(msg) } },
                    onProgress = { p   -> runOnUiThread { binding.progressInstall.progress = p } }
                )
                runOnUiThread { onInstallDone(true) }
            } catch (e: Exception) {
                runOnUiThread {
                    logInstall("ERROR: ${e.message}")
                    onInstallDone(false)
                }
            }
        }.start()
    }

    private fun onInstallDone(success: Boolean) {
        binding.btnInstall.isEnabled    = true
        binding.btnRefreshUsb.isEnabled = true
        if (success) {
            AlertDialog.Builder(this)
                .setTitle("✔ Instalación completada")
                .setMessage(
                    "Rocket MultiBoot instalado correctamente.\n\n" +
                    "Ahora ve a la pestaña 'ISOs', selecciona la unidad USB " +
                    "y añade tus archivos ISO."
                )
                .setPositiveButton("OK") { _, _ ->
                    binding.bottomNav.selectedItemId = R.id.nav_isos
                }
                .show()
        } else {
            AlertDialog.Builder(this)
                .setTitle("Error de instalación")
                .setMessage("La instalación falló. Revisa el log y asegúrate de " +
                    "que el dispositivo está conectado correctamente.")
                .setPositiveButton("OK", null)
                .show()
        }
    }

    private fun logInstall(msg: String) {
        val tv = binding.tvInstallLog
        tv.append(msg + "\n")
        // Auto-scroll: mover el ScrollView hacia abajo
        binding.installSection.post {
            binding.installSection.smoothScrollTo(0, tv.bottom)
        }
    }

    // ── Sección ISOs ──────────────────────────────────────────────────────────

    private fun setupIsoButtons() {
        binding.btnSelectUsb.setOnClickListener { pickUsbTree.launch(null) }
        binding.btnAddIso.setOnClickListener {
            if (usbTreeUri == null) {
                logIso("Selecciona primero la unidad USB")
                return@setOnClickListener
            }
            pickIsos.launch("*/*")
        }
        binding.btnRemoveIso.setOnClickListener { removeSelectedIso() }
    }

    private fun refreshIsoList() {
        val uri = usbTreeUri ?: return
        val isos = installer.listIsos(uri)
        val names = isos.map { it.name ?: "(sin nombre)" }.toTypedArray()
        runOnUiThread {
            binding.listIsos.adapter = ArrayAdapter(
                this, android.R.layout.simple_list_item_1, names
            )
            logIso("${isos.size} ISO(s) encontrado(s)")
        }
    }

    private fun copyIsosToUsb(uris: List<Uri>) {
        val treeUri = usbTreeUri ?: return
        binding.progressIso.progress = 0

        Thread {
            for (uri in uris) {
                try {
                    installer.copyIsoSaf(
                        isoUri   = uri,
                        treeUri  = treeUri,
                        onLog    = { msg -> runOnUiThread { logIso(msg) } },
                        onProgress = { p -> runOnUiThread { binding.progressIso.progress = p } }
                    )
                } catch (e: Exception) {
                    runOnUiThread { logIso("ERROR: ${e.message}") }
                }
            }
            runOnUiThread {
                binding.progressIso.progress = 0
                refreshIsoList()
            }
        }.start()
    }

    private fun removeSelectedIso() {
        val pos = binding.listIsos.checkedItemPosition
        if (pos < 0) {
            logIso("Selecciona un ISO de la lista")
            return
        }
        val uri = usbTreeUri ?: return
        val isos = installer.listIsos(uri)
        if (pos >= isos.size) return

        val file = isos[pos]
        AlertDialog.Builder(this)
            .setTitle("Eliminar ISO")
            .setMessage("¿Eliminar ${file.name}?")
            .setPositiveButton("Eliminar") { _, _ ->
                if (file.delete()) {
                    logIso("✔ ${file.name} eliminado")
                    refreshIsoList()
                } else {
                    logIso("ERROR: No se pudo eliminar ${file.name}")
                }
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    private fun logIso(msg: String) {
        binding.tvIsoLog.append(msg + "\n")
    }
}
