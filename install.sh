#!/usr/bin/env bash
# =============================================================================
# Aura Package Hub - Automated User Installer
# Supports Arch Linux, CachyOS, EndeavourOS, Manjaro, and generic Arch systems
# =============================================================================

set -e

BOLD="\033[1m"
GREEN="\033[1;32m"
BLUE="\033[1;34m"
YELLOW="\033[1;33m"
RED="\033[1;31m"
RESET="\033[0m"

echo -e "${BLUE}${BOLD}"
echo "    ___                          "
echo "   /   | __  ___________ _       "
echo "  / /| |/ / / / ___/ __ \`/       "
echo " / ___ / /_/ / /  / /_/ /        "
echo "/_/  |_\__,_/_/   \__,_/         "
echo -e "${RESET}"
echo -e "${BOLD}Aura App Store - Installer (Hyprland / Arch Linux)${RESET}\n"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "")"

# Support running directly via: curl -fsSL ... | bash
if [ -z "${SCRIPT_DIR}" ] || [ ! -f "${SCRIPT_DIR}/aura.py" ]; then
    echo -e "${BLUE}==>${RESET} Downloading Aura App Store repository..."
    TMP_DIR=$(mktemp -d)
    trap 'rm -rf "${TMP_DIR}"' EXIT
    git clone --depth 1 https://github.com/Desplicableme/aura-store.git "${TMP_DIR}/aura-store"
    cd "${TMP_DIR}/aura-store"
    exec ./install.sh "$@"
fi
INSTALL_DIR="${HOME}/.local/share/aura"
BIN_DIR="${HOME}/.local/bin"
APPLICATIONS_DIR="${HOME}/.local/share/applications"
ICONS_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"

# 1. Dependency Check
echo -e "${BLUE}==>${RESET} Checking system dependencies..."
MISSING_DEPS=()

for dep in python python-gobject gtk4 libadwaita pacman-contrib libarchive zstd; do
    if ! pacman -Q "$dep" &>/dev/null; then
        MISSING_DEPS+=("$dep")
    fi
done

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo -e "${YELLOW}Notice: Installing missing dependencies:${RESET} ${MISSING_DEPS[*]}"
    if command -v sudo &>/dev/null; then
        sudo pacman -S --needed --noconfirm "${MISSING_DEPS[@]}"
    else
        echo -e "${RED}Error: sudo required to install dependencies.${RESET}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ All core dependencies found.${RESET}"
fi

# Check for AUR helper
if command -v paru &>/dev/null; then
    echo -e "${GREEN}✓ Found AUR helper: paru${RESET}"
elif command -v yay &>/dev/null; then
    echo -e "${GREEN}✓ Found AUR helper: yay${RESET}"
else
    echo -e "${YELLOW}Notice: Neither paru nor yay found. Official Arch repositories will be supported, but AUR search requires paru/yay.${RESET}"
fi

# Check for Docker
if command -v docker &>/dev/null; then
    echo -e "${GREEN}✓ Found Docker container runtime.${RESET}"
else
    echo -e "${YELLOW}Notice: Docker is not installed. Native container app isolation will be disabled until Docker is available.${RESET}"
fi

# 2. Prepare Directories
echo -e "${BLUE}==>${RESET} Preparing target directories..."
mkdir -p "${INSTALL_DIR}"
mkdir -p "${BIN_DIR}"
mkdir -p "${APPLICATIONS_DIR}"
mkdir -p "${ICONS_DIR}"

# 3. Copy Application Files
echo -e "${BLUE}==>${RESET} Installing Aura application files..."
cp "${SCRIPT_DIR}/aura.py" "${INSTALL_DIR}/aura.py"
cp "${SCRIPT_DIR}/aura_backend.py" "${INSTALL_DIR}/aura_backend.py"
cp "${SCRIPT_DIR}/aura_ui.py" "${INSTALL_DIR}/aura_ui.py"
cp "${SCRIPT_DIR}/aura-askpass" "${INSTALL_DIR}/aura-askpass"
chmod +x "${INSTALL_DIR}/aura.py"
chmod +x "${INSTALL_DIR}/aura-askpass"

# 4. Install Icons
echo -e "${BLUE}==>${RESET} Installing desktop and status icons..."
mkdir -p "${INSTALL_DIR}/data/icons"
for icon in "${SCRIPT_DIR}"/data/icons/*.svg; do
    if [ -f "$icon" ]; then
        cp "$icon" "${ICONS_DIR}/"
        cp "$icon" "${INSTALL_DIR}/data/icons/"
    fi
done

# 5. Install Desktop Entry & Hyprland config
echo -e "${BLUE}==>${RESET} Installing desktop launcher and window rules..."
cp "${SCRIPT_DIR}/data/io.github.aura.desktop" "${APPLICATIONS_DIR}/io.github.aura.desktop"
sed -i "s|^Exec=aura|Exec=${BIN_DIR}/aura|g" "${APPLICATIONS_DIR}/io.github.aura.desktop"
mkdir -p "${INSTALL_DIR}/data"
if [ -f "${SCRIPT_DIR}/data/hyprland-aura.conf" ]; then
    cp "${SCRIPT_DIR}/data/hyprland-aura.conf" "${INSTALL_DIR}/data/hyprland-aura.conf"
fi

# 6. Binary Symlink
echo -e "${BLUE}==>${RESET} Linking executable to ${BIN_DIR}/aura..."
ln -sf "${INSTALL_DIR}/aura.py" "${BIN_DIR}/aura"

# 7. Update Desktop and Icon Caches
echo -e "${BLUE}==>${RESET} Updating desktop and icon database..."
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "${APPLICATIONS_DIR}" &>/dev/null || true
fi
if command -v gtk-update-icon-cache &>/dev/null; then
    gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" &>/dev/null || true
fi

echo -e "\n${GREEN}${BOLD}✓ Aura has been successfully installed!${RESET}"
echo -e "You can launch it anytime by running:"
echo -e "  ${BOLD}aura${RESET} (or from your application launcher)\n"

# Hyprland integration notice
if [ -d "${HOME}/.config/hypr" ]; then
    echo -e "${BLUE}${BOLD}🪟 Hyprland Tip:${RESET} To enable native floating rules and shortcut in Hyprland, add:"
    echo -e "  ${BOLD}source = ~/.local/share/aura/data/hyprland-aura.conf${RESET}"
    echo -e "to your ${BOLD}~/.config/hypr/hyprland.conf${RESET}\n"
fi

# Verify PATH
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo -e "${YELLOW}Note: Make sure '${BIN_DIR}' is in your PATH:${RESET}"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
