# installer.spec — PyInstaller spec para Rocket MultiBoot Installer
#
# Uso (desde la raíz del repo):
#   pyinstaller src/installer.spec
#
# Genera:  dist/RocketMultiBoot-Installer.exe
# El .exe es autocontenido: incluye Python, tkinter y todos los archivos
# de arranque (EFI/, ventoy/, tool/, config/).

import os
from pathlib import Path

repo = Path(SPECPATH).parent          # SPECPATH = src/  →  repo = raíz del repo
block_cipher = None

a = Analysis(
    [str(repo / "src" / "installer.py")],
    pathex=[str(repo / "src")],
    binaries=[],
    datas=[
        # Archivos de arranque que se copiarán a la Partición 2 del USB (FAT32)
        (str(repo / "EFI"),                       "EFI"),
        (str(repo / "ventoy"),                    "ventoy"),
        (str(repo / "tool"),                      "tool"),
        # Configuración y tema que se copiarán a la Partición 1 del USB (exFAT)
        # Empaquetado como "config" para evitar problemas con caracteres especiales
        (str(repo / "Partición 1" / "ventoy"), "config"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy", "pandas", "matplotlib", "scipy"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="RocketMultiBoot-Installer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,        # Aplicación GUI pura (sin ventana de consola)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,       # Solicita elevación UAC al iniciar
)
