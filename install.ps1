# install.ps1 — Despliega Rocket--MultiBoot en un USB con Ventoy en Windows
#
# Uso:
#   .\install.ps1              → selección interactiva de la unidad
#   .\install.ps1 -Letra E     → letra de unidad directa
#
# Requisitos: Ventoy debe estar instalado en el USB (Ventoy2Disk.exe).
#             Windows sólo accede directamente a la Partición 1 (datos).
#             La Partición 2 (sistema Ventoy) se gestiona con Ventoy2Disk.exe.

param(
    [Alias("d")]
    [string]$Letra
)

$ErrorActionPreference = "Stop"
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$Part1Src   = Join-Path $ScriptDir "Partición 1"

function Write-Info  { param($m) Write-Host ">> $m"   -ForegroundColor Yellow }
function Write-Ok    { param($m) Write-Host "✔  $m"   -ForegroundColor Green  }
function Write-Note  { param($m) Write-Host "   $m"   -ForegroundColor Cyan   }
function Write-Err   { param($m) Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }

# ── Selección de unidad ────────────────────────────────────────────────────────
if (-not $Letra) {
    Write-Host ""
    Write-Host "Unidades extraíbles disponibles:" -ForegroundColor Yellow
    Write-Host "─────────────────────────────────"
    Get-WmiObject Win32_LogicalDisk | Where-Object { $_.DriveType -eq 2 } | ForEach-Object {
        $gb = if ($_.Size) { "{0:N1} GB" -f ($_.Size / 1GB) } else { "?" }
        Write-Host ("  {0}  {1,-20}  {2}" -f $_.DeviceID, $_.VolumeName, $gb)
    }
    Write-Host ""
    $Letra = Read-Host "Introduce la letra de la unidad (ej: E)"
}

$Letra  = $Letra.Trim().TrimEnd(':').ToUpper()
$Unidad = "${Letra}:"

if (-not (Test-Path $Unidad)) { Write-Err "No se encontró la unidad: $Unidad" }

# ── Protección: no operar sobre la unidad del sistema ─────────────────────────
if ($Unidad -eq $env:SystemDrive) { Write-Err "Denegado: $Unidad es la unidad del sistema." }

# ── Confirmación ───────────────────────────────────────────────────────────────
$info = Get-WmiObject Win32_LogicalDisk | Where-Object { $_.DeviceID -eq $Unidad }
$gb   = if ($info.Size) { "{0:N1} GB" -f ($info.Size / 1GB) } else { "?" }
Write-Host ""
Write-Host ("Unidad seleccionada: {0}  ({1}, {2})" -f $Unidad, $info.VolumeName, $gb) -ForegroundColor Yellow
Write-Host "ADVERTENCIA: se sobreescribirán los archivos de configuración en $Unidad" -ForegroundColor Red
Write-Host ""
$confirm = Read-Host "¿Continuar? [s/N]"
if ($confirm -notmatch '^[sSyY]$') { Write-Host "Cancelado."; exit 0 }

# ── Copiar configuración y tema → Partición 1 ─────────────────────────────────
$destVentoy = Join-Path $Unidad "ventoy"
Write-Host ""
Write-Info "Copiando configuración y tema → $Unidad\ventoy\"

New-Item -ItemType Directory -Force -Path "$destVentoy\theme" | Out-Null
Copy-Item -Recurse -Force (Join-Path $Part1Src "ventoy\*") "$destVentoy\"

Write-Ok "ventoy.json y tema YUMI copiados."

# ── Nota sobre Partición 2 ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "══════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  Despliegue de configuración completado en $Unidad"    -ForegroundColor Green
Write-Host "══════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Note "NOTA sobre la Partición 2 (sistema de arranque EFI/Ventoy):"
Write-Note "  Windows no puede acceder directamente a la partición 2 del USB."
Write-Note "  Los archivos EFI/, ventoy/ y tool/ se gestionan mediante"
Write-Note "  el instalador oficial: Ventoy2Disk.exe"
Write-Note "  Descárgalo en: https://www.ventoy.net/en/download.html"
Write-Host ""
Write-Note "Siguiente paso: copia tus archivos ISO a la raíz de $Unidad"
Write-Note "  (o a la carpeta $Unidad\YUMI\ si usas búsqueda por directorio)"
Write-Host ""
