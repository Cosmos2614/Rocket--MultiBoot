#!/usr/bin/env python3
"""
Rocket MultiBoot Installer
Particiona un USB, copia los archivos de arranque y permite gestionar ISOs.
Requiere Windows 10/11 y permisos de Administrador.
"""

import os
import sys
import shutil
import subprocess
import threading
import ctypes
import tempfile
import time
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError:
    print("ERROR: tkinter no disponible. Instala Python con soporte Tk.")
    sys.exit(1)


# ─── Rutas de recursos ────────────────────────────────────────────────────────
# Funciona tanto al ejecutar el .py directamente como el .exe compilado.

def res(*parts):
    """Devuelve la ruta absoluta a un recurso empaquetado."""
    if hasattr(sys, '_MEIPASS'):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent.parent  # src/../ = raíz del repo
    return str(base.joinpath(*parts))


# ─── Privilegios de administrador ────────────────────────────────────────────

def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate():
    """Re-lanza el proceso solicitando elevación UAC."""
    params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    sys.exit(0)


# ─── Operaciones de disco ─────────────────────────────────────────────────────

def _ps(cmd, timeout=20):
    """Ejecuta un comando PowerShell y devuelve stdout limpio."""
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    return r.stdout.strip()


def get_usb_disks():
    """Devuelve lista de discos USB: [{number, name, size}]."""
    out = _ps(
        "Get-Disk | Where-Object BusType -eq 'USB' | "
        "ForEach-Object { \"$($_.Number)|$($_.FriendlyName)|"
        "$([math]::Round($_.Size/1GB,1))\" }"
    )
    disks = []
    for line in out.splitlines():
        p = line.strip().split("|")
        if len(p) == 3 and p[0].isdigit():
            disks.append({"number": p[0], "name": p[1], "size": p[2]})
    return disks


def _find_volume(label, retries=12, delay=2.0):
    """Busca un volumen por etiqueta con reintentos, devuelve letra o None."""
    for _ in range(retries):
        letter = _ps(
            f"Get-Volume | Where-Object FileSystemLabel -eq '{label}' "
            "| Select-Object -First 1 -ExpandProperty DriveLetter"
        )
        if letter and letter.strip():
            return letter.strip()
        time.sleep(delay)
    return None


def install_to_disk(disk_number, log_cb, progress_cb):
    """
    1. Particiona el USB:  P1 = exFAT (datos/ISOs),  P2 = FAT32 32MB (arranque EFI)
    2. Copia EFI/, ventoy/, tool/ → P2
    3. Copia config + tema       → P1/ventoy/
    4. Crea P1/YUMI/ para los ISOs
    Devuelve la letra de P1 (unidad de datos).
    """
    # — Tamaño del disco —
    log_cb("Leyendo tamaño del disco...")
    raw = _ps(f"(Get-Disk -Number {disk_number}).Size", timeout=15)
    if not raw.isdigit():
        raise RuntimeError(f"No se pudo leer el tamaño del disco {disk_number}.")
    size_mb = int(raw) // (1024 * 1024)
    p2_mb   = 32
    p1_mb   = size_mb - p2_mb - 2
    log_cb(f"Disco: {size_mb} MB  →  P1={p1_mb} MB (exFAT), P2={p2_mb} MB (FAT32)")

    if p1_mb < 100:
        raise RuntimeError("El disco es demasiado pequeño (mínimo ~500 MB).")

    # — diskpart: limpiar, particionar, formatear —
    script = "\n".join([
        f"select disk {disk_number}",
        "clean",
        "convert mbr",
        f"create partition primary size={p1_mb}",
        "format quick fs=exfat label=Ventoy",
        "assign",
        "create partition primary",
        "format quick fs=fat32 label=VTOYEFI",
        "assign",
        "active",
        "exit",
    ])
    log_cb("Particionando y formateando (puede tardar 1-2 min)...")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="ascii") as f:
        f.write(script)
        tmp = f.name

    try:
        r = subprocess.run(
            ["diskpart", "/s", tmp], capture_output=True, text=True, timeout=180
        )
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

    if r.returncode != 0:
        raise RuntimeError(f"diskpart falló:\n{(r.stderr or r.stdout).strip()}")

    progress_cb(25)

    # — Esperar montaje de particiones —
    log_cb("Esperando asignación de unidades...")
    p1 = _find_volume("Ventoy")
    p2 = _find_volume("VTOYEFI")

    if not p1 or not p2:
        raise RuntimeError(
            f"Particiones no encontradas (Ventoy={p1!r}, VTOYEFI={p2!r}).\n"
            "Desconecta y reconecta el USB, y vuelve a intentarlo."
        )

    log_cb(f"Partición de datos (ISOs) : {p1}:\\")
    log_cb(f"Partición de arranque EFI : {p2}:\\")
    progress_cb(35)

    # — Copiar archivos de arranque → P2 —
    log_cb(f"Copiando EFI + framework Ventoy → {p2}:\\")
    for folder in ("EFI", "ventoy", "tool"):
        src = res(folder)
        dst = f"{p2}:\\{folder}"
        if os.path.isdir(src):
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            log_cb(f"  ✔ {folder}/")
        else:
            log_cb(f"  ⚠ {folder}/ no encontrado en el instalador")
    progress_cb(70)

    # — Copiar configuración + tema → P1 —
    log_cb(f"Copiando configuración y tema → {p1}:\\ventoy\\")
    src_conf = res("config")
    dst_conf = f"{p1}:\\ventoy"
    if os.path.isdir(src_conf):
        if os.path.exists(dst_conf):
            shutil.rmtree(dst_conf)
        shutil.copytree(src_conf, dst_conf)
        log_cb("  ✔ ventoy.json + tema YUMI")
    else:
        log_cb("  ⚠ Configuración no encontrada")
    progress_cb(90)

    # — Crear carpeta YUMI para los ISOs —
    yumi = f"{p1}:\\YUMI"
    os.makedirs(yumi, exist_ok=True)
    log_cb(f"  ✔ Carpeta YUMI creada")

    progress_cb(100)
    log_cb(f"✔ ¡Instalación completada! Unidad de datos: {p1}:\\")
    return p1


def copy_iso_file(src_path, drive_letter, log_cb, progress_cb):
    """Copia un ISO a [drive]:\\YUMI\\ con barra de progreso."""
    dst_dir  = f"{drive_letter}:\\YUMI"
    dst_file = os.path.join(dst_dir, os.path.basename(src_path))
    os.makedirs(dst_dir, exist_ok=True)

    total = os.path.getsize(src_path)
    done  = 0
    chunk = 4 * 1024 * 1024  # 4 MB por lectura
    name  = os.path.basename(src_path)

    log_cb(f"Copiando {name}  ({total // (1024 ** 2)} MB)...")
    with open(src_path, "rb") as s, open(dst_file, "wb") as d:
        while True:
            buf = s.read(chunk)
            if not buf:
                break
            d.write(buf)
            done += len(buf)
            progress_cb(int(done * 100 / total))
    log_cb(f"  ✔ {name}")


# ─── Paleta y fuentes ─────────────────────────────────────────────────────────

BG      = "#1a1a1a"
BG2     = "#111111"
FG      = "#f0f0f0"
ACCENT  = "#ffcc00"
BTN_BG  = "#2d2d2d"
FONT    = ("Segoe UI", 10)
FONTB   = ("Segoe UI", 10, "bold")
FONTH   = ("Segoe UI", 13, "bold")
MONO    = ("Consolas",  9)


# ─── Aplicación principal ─────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Rocket MultiBoot Installer")
        self.geometry("720x560")
        self.resizable(False, False)
        self.configure(bg=BG)

        self._disks       = []
        self._data_letter = tk.StringVar(value="")

        self._apply_styles()
        self._build_ui()
        self.after(200, self._refresh_disks)

    # ── Estilos ───────────────────────────────────────────────────────────────

    def _apply_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TNotebook",     background=BG,  borderwidth=0, tabmargins=[2, 5, 0, 0])
        s.configure("TNotebook.Tab", background=BTN_BG, foreground=FG,
                    padding=[18, 7], font=FONT)
        s.map("TNotebook.Tab",
              background=[("selected", ACCENT)],
              foreground=[("selected", "#000000")])
        s.configure("Y.Horizontal.TProgressbar",
                    troughcolor=BTN_BG, background=ACCENT,
                    lightcolor=ACCENT, darkcolor=ACCENT, borderwidth=0)
        s.configure("TCombobox",
                    fieldbackground=BTN_BG, background=BTN_BG,
                    foreground=FG, selectbackground=ACCENT)
        s.map("TCombobox",
              fieldbackground=[("readonly", BTN_BG)],
              foreground=[("readonly", FG)])

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Cabecera
        hdr = tk.Frame(self, bg="#0d0d0d", height=64)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="\U0001F680  Rocket MultiBoot Installer",
                 font=FONTH, bg="#0d0d0d", fg=ACCENT).pack(side="left", padx=22, pady=16)

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=10)

        self._build_install_tab()
        self._build_isos_tab()

    # ── Pestaña Instalar ──────────────────────────────────────────────────────

    def _build_install_tab(self):
        tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(tab, text="  Instalar  ")

        # Fila USB
        row = tk.Frame(tab, bg=BG)
        row.pack(fill="x", padx=20, pady=(18, 4))
        tk.Label(row, text="Dispositivo USB:", font=FONT, bg=BG, fg=FG).pack(side="left")
        self._disk_var   = tk.StringVar()
        self._disk_combo = ttk.Combobox(row, textvariable=self._disk_var,
                                         state="readonly", width=46)
        self._disk_combo.pack(side="left", padx=8)
        tk.Button(row, text="↺", font=FONTB, bg=BTN_BG, fg=ACCENT,
                  bd=0, padx=8, cursor="hand2",
                  command=self._refresh_disks).pack(side="left")

        # Log
        self._install_log = tk.Text(
            tab, bg=BG2, fg=FG, font=MONO, relief="flat",
            padx=8, pady=6, state="disabled", height=14, wrap="word",
        )
        self._install_log.pack(fill="x", padx=20, pady=(4, 4))
        self._install_log.tag_config("ok",   foreground="#55dd55")
        self._install_log.tag_config("err",  foreground="#ff5555")
        self._install_log.tag_config("warn", foreground=ACCENT)

        # Barra de progreso
        self._install_prog = ttk.Progressbar(
            tab, style="Y.Horizontal.TProgressbar", mode="determinate"
        )
        self._install_prog.pack(fill="x", padx=20, pady=(0, 4))

        # Botón instalar
        self._install_btn = tk.Button(
            tab, text="▶  INSTALAR EN USB",
            font=("Segoe UI", 11, "bold"), bg=ACCENT, fg="#000000",
            relief="flat", padx=24, pady=10, cursor="hand2",
            command=self._start_install,
        )
        self._install_btn.pack(pady=8)

    # ── Pestaña Gestionar ISOs ────────────────────────────────────────────────

    def _build_isos_tab(self):
        tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(tab, text="  Gestionar ISOs  ")

        # Fila unidad
        row = tk.Frame(tab, bg=BG)
        row.pack(fill="x", padx=20, pady=(18, 4))
        tk.Label(row, text="Unidad Ventoy:", font=FONT, bg=BG, fg=FG).pack(side="left")
        tk.Entry(row, textvariable=self._data_letter, width=4,
                 font=FONTB, bg=BTN_BG, fg=ACCENT,
                 insertbackground=ACCENT, relief="flat",
                 justify="center").pack(side="left", padx=(6, 0))
        tk.Label(row, text=":", font=FONTB, bg=BG, fg=FG).pack(side="left")
        tk.Button(row, text="↺ Actualizar", font=FONT, bg=BTN_BG, fg=FG,
                  relief="flat", padx=10, cursor="hand2",
                  command=self._refresh_isos).pack(side="left", padx=10)

        # Lista de ISOs
        frm = tk.Frame(tab, bg=BG)
        frm.pack(fill="both", expand=True, padx=20, pady=(0, 4))
        sb = tk.Scrollbar(frm, bg=BTN_BG, troughcolor=BG2)
        sb.pack(side="right", fill="y")
        self._iso_lb = tk.Listbox(
            frm, font=MONO, bg=BG2, fg=FG, relief="flat",
            selectbackground=ACCENT, selectforeground="#000000",
            yscrollcommand=sb.set,
        )
        self._iso_lb.pack(fill="both", expand=True)
        sb.config(command=self._iso_lb.yview)

        # Log ISOs
        self._iso_log = tk.Text(
            tab, bg=BG2, fg=FG, font=MONO, relief="flat",
            padx=8, pady=4, state="disabled", height=3,
        )
        self._iso_log.pack(fill="x", padx=20, pady=(0, 2))

        # Progreso ISOs
        self._iso_prog = ttk.Progressbar(
            tab, style="Y.Horizontal.TProgressbar", mode="determinate"
        )
        self._iso_prog.pack(fill="x", padx=20, pady=(0, 4))

        # Botones
        brow = tk.Frame(tab, bg=BG)
        brow.pack(pady=6)
        tk.Button(brow, text="+ Añadir ISO", font=FONT, bg=ACCENT, fg="#000000",
                  relief="flat", padx=16, pady=7, cursor="hand2",
                  command=self._add_iso).pack(side="left", padx=8)
        tk.Button(brow, text="✕ Eliminar seleccionado", font=FONT,
                  bg="#3a1111", fg="#ff8888", relief="flat",
                  padx=16, pady=7, cursor="hand2",
                  command=self._remove_iso).pack(side="left", padx=8)

    # ── Lógica: instalar ──────────────────────────────────────────────────────

    def _refresh_disks(self):
        self._log_install("Buscando USBs conectados...", "warn")
        self._disks = get_usb_disks()
        if not self._disks:
            self._disk_combo["values"] = ["(sin USB detectado)"]
            self._disk_var.set("(sin USB detectado)")
            self._log_install("No se detectó ningún USB. Conecta uno y pulsa ↺.")
        else:
            vals = [f"Disco {d['number']} — {d['name']}  ({d['size']} GB)"
                    for d in self._disks]
            self._disk_combo["values"] = vals
            self._disk_combo.current(0)
            self._log_install(f"{len(self._disks)} USB(s) detectado(s).", "ok")

    def _start_install(self):
        if not self._disks:
            messagebox.showerror("Sin USB", "No hay ningún USB conectado.")
            return
        idx = self._disk_combo.current()
        if idx < 0:
            messagebox.showerror("Selección", "Selecciona un dispositivo USB.")
            return

        disk = self._disks[idx]
        if not messagebox.askyesno(
            "⚠ Confirmar instalación",
            f"Se BORRARÁN TODOS los datos del disco:\n\n"
            f"  Disco {disk['number']} — {disk['name']}  ({disk['size']} GB)\n\n"
            f"¿Continuar con la instalación?",
            icon="warning",
        ):
            return

        self._install_btn.config(state="disabled", text="Instalando...")
        self._install_prog["value"] = 0
        self._log_install("Iniciando instalación...", "warn")

        def run():
            try:
                letter = install_to_disk(
                    disk["number"],
                    lambda m: self.after(0, self._log_install, m),
                    lambda p: self.after(0, self._set_install_prog, p),
                )
                self.after(0, self._on_install_done, True, letter)
            except Exception as e:
                self.after(0, self._log_install, f"ERROR: {e}", "err")
                self.after(0, self._on_install_done, False, None)

        threading.Thread(target=run, daemon=True).start()

    def _on_install_done(self, success, letter):
        self._install_btn.config(state="normal", text="▶  INSTALAR EN USB")
        if success and letter:
            self._data_letter.set(letter)
            self.nb.select(1)
            self._refresh_isos()
            messagebox.showinfo(
                "✔ Instalación completada",
                f"Rocket MultiBoot instalado correctamente.\n\n"
                f"Unidad de datos (ISOs): {letter}:\\\n"
                f"Los ISOs se guardan en:  {letter}:\\YUMI\\\n\n"
                "Ahora añade tus ISOs desde la pestaña 'Gestionar ISOs'.",
            )
        elif not success:
            messagebox.showerror("Error de instalación",
                                 "La instalación falló. Revisa el log para más detalles.")

    def _set_install_prog(self, val):
        self._install_prog["value"] = val

    def _log_install(self, msg, tag=""):
        w = self._install_log
        w.config(state="normal")
        w.insert("end", msg + "\n", tag)
        w.see("end")
        w.config(state="disabled")

    # ── Lógica: ISOs ──────────────────────────────────────────────────────────

    def _refresh_isos(self):
        letter = self._data_letter.get().strip().upper().rstrip(":")
        self._iso_lb.delete(0, "end")
        if not letter:
            self._log_iso("Introduce la letra de la unidad Ventoy.")
            return
        drive = f"{letter}:\\"
        if not os.path.exists(drive):
            self._log_iso(f"Unidad {drive} no encontrada.")
            return
        isos = sorted(Path(drive).rglob("*.iso"))
        if not isos:
            self._iso_lb.insert("end", f"  (sin ISOs en {letter}:\\)")
        else:
            for iso in isos:
                self._iso_lb.insert("end", str(iso))
        self._log_iso(f"{len(isos)} ISO(s) encontrado(s) en {drive}")

    def _add_iso(self):
        letter = self._data_letter.get().strip().upper().rstrip(":")
        if not letter or not os.path.exists(f"{letter}:\\"):
            messagebox.showerror(
                "Sin unidad",
                f"La unidad '{letter}:\\' no está disponible.\n"
                "Instala primero o introduce la letra correcta.",
            )
            return

        paths = filedialog.askopenfilenames(
            title="Selecciona archivos ISO",
            filetypes=[("Imágenes ISO", "*.iso"), ("Todos los archivos", "*.*")],
        )
        if not paths:
            return

        self._iso_prog["value"] = 0

        def run():
            for path in paths:
                try:
                    copy_iso_file(
                        path, letter,
                        lambda m: self.after(0, self._log_iso, m),
                        lambda p: self.after(0, self._set_iso_prog, p),
                    )
                except Exception as e:
                    self.after(0, self._log_iso, f"ERROR: {e}")
            self.after(0, self._refresh_isos)
            self.after(0, self._set_iso_prog, 0)

        threading.Thread(target=run, daemon=True).start()

    def _remove_iso(self):
        sel = self._iso_lb.curselection()
        if not sel:
            return
        path = self._iso_lb.get(sel[0]).strip()
        if not os.path.isfile(path):
            return
        if messagebox.askyesno("Eliminar ISO",
                                f"¿Eliminar {os.path.basename(path)}?"):
            try:
                os.remove(path)
                self._refresh_isos()
                self._log_iso(f"✔ {os.path.basename(path)} eliminado.")
            except Exception as e:
                self._log_iso(f"ERROR al eliminar: {e}")

    def _set_iso_prog(self, val):
        self._iso_prog["value"] = val

    def _log_iso(self, msg):
        w = self._iso_log
        w.config(state="normal")
        w.insert("end", msg + "\n")
        w.see("end")
        w.config(state="disabled")


# ─── Punto de entrada ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    if sys.platform == "win32" and not is_admin():
        # Mostrar diálogo antes de crear la ventana principal
        root = tk.Tk()
        root.withdraw()
        ans = messagebox.askyesno(
            "Permisos requeridos",
            "Este instalador necesita permisos de Administrador\n"
            "para formatear el USB.\n\n"
            "¿Reiniciar como administrador?",
        )
        root.destroy()
        if ans:
            elevate()
        sys.exit(0)

    App().mainloop()
