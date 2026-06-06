#!/usr/bin/env bash
# Despliega los archivos de Rocket--MultiBoot en un USB con Ventoy ya instalado.
#
# Uso:
#   sudo ./install.sh              → selección interactiva del dispositivo
#   sudo ./install.sh /dev/sdb    → dispositivo directo
#
# Requisitos: Ventoy debe estar instalado en el USB (Ventoy2Disk.sh o Ventoy2Disk.exe).
#             El script copia los archivos a las dos particiones; no reformatea el disco.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PART1_SRC="$REPO_DIR/Partición 1"

RED='\033[0;31m'
YEL='\033[1;33m'
GRN='\033[0;32m'
CYN='\033[0;36m'
NC='\033[0m'

die()  { echo -e "${RED}ERROR: $*${NC}" >&2; exit 1; }
info() { echo -e "${YEL}>> $*${NC}"; }
ok()   { echo -e "${GRN}✔  $*${NC}"; }
note() { echo -e "${CYN}   $*${NC}"; }

# ── Debe ejecutarse como root ──────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "Ejecuta el script como root:\n  sudo $0 [/dev/sdX]"

# ── Selección de dispositivo ───────────────────────────────────────────────────
if [[ $# -ge 1 ]]; then
    DEVICE="$1"
else
    echo ""
    echo "Dispositivos de almacenamiento disponibles:"
    echo "────────────────────────────────────────────"
    lsblk -o NAME,SIZE,TRAN,MODEL -d -n | awk '{printf "  /dev/%-10s %s  %s  %s\n",$1,$2,$3,$4}'
    echo ""
    read -rp "Introduce el dispositivo USB (ej: /dev/sdb): " DEVICE
fi

[[ -b "$DEVICE" ]] || die "No es un dispositivo de bloque: $DEVICE"

# ── Protección: nunca operar sobre el disco del sistema ───────────────────────
ROOT_PART=$(findmnt -n -o SOURCE / 2>/dev/null || echo "")
if [[ -n "$ROOT_PART" ]]; then
    ROOT_DEV=$(lsblk -no pkname "$ROOT_PART" 2>/dev/null || echo "")
    [[ -n "$ROOT_DEV" && "$DEVICE" == "/dev/$ROOT_DEV" ]] && \
        die "Dispositivo denegado: $DEVICE es el disco del sistema."
fi

# ── Confirmación ───────────────────────────────────────────────────────────────
DEVICE_INFO=$(lsblk -no SIZE,MODEL "$DEVICE" 2>/dev/null | head -1 || echo "")
echo ""
echo -e "${YEL}Dispositivo seleccionado: $DEVICE  ($DEVICE_INFO)${NC}"
echo -e "${RED}ADVERTENCIA: se sobreescribirán los archivos existentes en $DEVICE${NC}"
echo ""
read -rp "¿Continuar? [s/N]: " CONFIRM
[[ "${CONFIRM,,}" == "s" || "${CONFIRM,,}" == "y" ]] || { echo "Cancelado."; exit 0; }

# ── Determinar nombres de particiones ─────────────────────────────────────────
# /dev/sdb  → /dev/sdb1, /dev/sdb2
# /dev/nvme0n1 → /dev/nvme0n1p1, /dev/nvme0n1p2
if [[ "$DEVICE" =~ [0-9]$ ]]; then
    PART1="${DEVICE}p1"
    PART2="${DEVICE}p2"
else
    PART1="${DEVICE}1"
    PART2="${DEVICE}2"
fi

[[ -b "$PART1" ]] || die "Partición 1 no encontrada: $PART1\n   ¿Está Ventoy instalado en este USB?"
[[ -b "$PART2" ]] || die "Partición 2 no encontrada: $PART2\n   ¿Está Ventoy instalado en este USB?"

# ── Montar particiones ─────────────────────────────────────────────────────────
MNT1=$(mktemp -d /tmp/rocket-p1-XXXXXX)
MNT2=$(mktemp -d /tmp/rocket-p2-XXXXXX)

cleanup() {
    umount "$MNT1" 2>/dev/null || true
    umount "$MNT2" 2>/dev/null || true
    rmdir  "$MNT1" "$MNT2" 2>/dev/null || true
}
trap cleanup EXIT

info "Montando Partición 1 (datos)..."
mount "$PART1" "$MNT1" || die "No se pudo montar $PART1"
ok   "Montada en $MNT1"

info "Montando Partición 2 (sistema Ventoy)..."
mount "$PART2" "$MNT2" || die "No se pudo montar $PART2"
ok   "Montada en $MNT2"

# ── Copiar archivos ────────────────────────────────────────────────────────────

echo ""
info "Copiando configuración y tema → Partición 1..."
mkdir -p "$MNT1/ventoy/theme"
cp -a "$PART1_SRC/ventoy/." "$MNT1/ventoy/"
ok "ventoy.json y tema YUMI copiados."

echo ""
info "Copiando arranque EFI → Partición 2..."
mkdir -p "$MNT2/EFI"
cp -a "$REPO_DIR/EFI/." "$MNT2/EFI/"
ok "Archivos EFI copiados."

echo ""
info "Copiando framework Ventoy → Partición 2..."
mkdir -p "$MNT2/ventoy"
cp -a "$REPO_DIR/ventoy/." "$MNT2/ventoy/"
ok "Framework Ventoy copiado."

echo ""
info "Copiando herramientas → Partición 2..."
mkdir -p "$MNT2/tool"
cp -a "$REPO_DIR/tool/." "$MNT2/tool/"
ok "Herramientas copiadas."

# ── Flush ──────────────────────────────────────────────────────────────────────
sync
echo ""
echo -e "${GRN}══════════════════════════════════════════════════${NC}"
echo -e "${GRN}  Despliegue completado con éxito en $DEVICE${NC}"
echo -e "${GRN}══════════════════════════════════════════════════${NC}"
echo ""
note "Siguiente paso: copia tus archivos ISO a la raíz de $PART1"
note "  (o a la carpeta /YUMI/ si usas la búsqueda por directorio)"
echo ""
