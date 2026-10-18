#!/usr/bin/env bash
#
# ArkST Uninstaller (also cleans any leftover Aura/Ark files)
#

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

PREFIX="${PREFIX:-/usr}"

echo -e "${BLUE}[INFO]${NC}  Removing ArkST..."

sudo rm -rf "$PREFIX/lib/arkst" "$PREFIX/lib/ark" "$PREFIX/lib/aura"
sudo rm -f  "$PREFIX/bin/arkst" "$PREFIX/bin/ark" "$PREFIX/bin/aura"
sudo rm -f  "$PREFIX/share/applications/io.github.arkst.desktop" "$PREFIX/share/applications/io.github.ark.desktop" "$PREFIX/share/applications/io.github.aura.desktop"
sudo rm -f  "$PREFIX/share/metainfo/io.github.arkst.metainfo.xml"
sudo rm -f  "$PREFIX/share/icons/hicolor/"*/apps/io.github.arkst.* "$PREFIX/share/icons/hicolor/"*/apps/arkst.*
sudo rm -f  "$PREFIX/share/pixmaps/io.github.arkst.png" "$PREFIX/share/pixmaps/arkst.png"
sudo rm -f  "/etc/sudoers.d/99-arkst-pacman" "/etc/sudoers.d/99-aura-pacman"

if command -v gtk-update-icon-cache &>/dev/null; then
    sudo gtk-update-icon-cache -q -t -f "$PREFIX/share/icons/hicolor" 2>/dev/null || true
fi
if command -v update-desktop-database &>/dev/null; then
    sudo update-desktop-database -q "$PREFIX/share/applications" 2>/dev/null || true
fi

echo -e "${GREEN}[ OK ]${NC}  ArkST has been uninstalled."
