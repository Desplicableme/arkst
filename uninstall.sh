#!/usr/bin/env bash
# =============================================================================
# Aura Package Hub - Complete Clean Uninstaller
# =============================================================================

set -e

BOLD="\033[1m"
GREEN="\033[1;32m"
BLUE="\033[1;34m"
YELLOW="\033[1;33m"
RESET="\033[0m"

echo -e "${BOLD}Aura Package Hub - Clean Uninstaller${RESET}\n"

if [[ "${1:-}" != "--yes" && "${1:-}" != "-y" ]]; then
    read -p "Are you sure you want to completely uninstall Aura and clean all caches? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
fi

# 1. Remove sudoers passwordless policy if installed
if [ -f "/etc/sudoers.d/99-aura-pacman" ]; then
    echo -e "${BLUE}==>${RESET} Removing passwordless sudoers policy (/etc/sudoers.d/99-aura-pacman)..."
    if sudo -n true 2>/dev/null; then
        sudo rm -f "/etc/sudoers.d/99-aura-pacman" || true
    else
        sudo rm -f "/etc/sudoers.d/99-aura-pacman" 2>/dev/null || true
    fi
fi

# 2. Clean Hyprland config source line so Hyprland doesn't throw a missing file error
HYPR_CONF="${HOME}/.config/hypr/hyprland.conf"
if [ -f "${HYPR_CONF}" ]; then
    if grep -q "hyprland-aura.conf" "${HYPR_CONF}" 2>/dev/null; then
        echo -e "${BLUE}==>${RESET} Cleaning Aura window rules reference from ${HYPR_CONF}..."
        sed -i '/Aura Store Hyprland Integration/d' "${HYPR_CONF}" 2>/dev/null || true
        sed -i '/hyprland-aura\.conf/d' "${HYPR_CONF}" 2>/dev/null || true
        if command -v hyprctl &>/dev/null && [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]; then
            hyprctl reload &>/dev/null || true
        fi
    fi
fi

# 3. Clean up Docker sandbox container and desktop shortcuts if present
if command -v docker &>/dev/null; then
    if docker inspect aura-box &>/dev/null; then
        echo -e "${BLUE}==>${RESET} Removing 'aura-box' Docker sandbox container..."
        docker rm -f aura-box &>/dev/null || true
    fi
fi
rm -f "${HOME}/.local/share/applications"/aura-box-*.desktop 2>/dev/null || true

# 4. Remove application files, caches, and icons
echo -e "${BLUE}==>${RESET} Removing Aura application files, caches, and icons..."
rm -rf "${HOME}/.local/share/aura"
rm -rf "${HOME}/.cache/aura"
rm -f "${HOME}/.local/bin/aura"
rm -f "${HOME}/.local/share/applications/io.github.aura.desktop"
rm -f "${HOME}/.local/share/icons/hicolor/scalable/apps/io.github.aura.svg"
rm -f "${HOME}/.local/share/icons/hicolor/scalable/apps/aura-icon.svg"
rm -f "${HOME}/.local/share/icons/hicolor/scalable/apps/docker-symbolic.svg"
rm -f "${HOME}/.local/share/icons/hicolor/scalable/apps/docker-brand.svg"
rm -f "${HOME}/.local/share/icons/hicolor/scalable/apps/docker-desktop.svg"
rm -f "${HOME}/.local/share/icons/hicolor/scalable/apps/snap-brand.svg"

# 5. Clean up credentials or session tokens
rm -f "${HOME}/.aura_vault" 2>/dev/null || true
rm -f "/run/user/$(id -u)/aura_auth.token" 2>/dev/null || true
rm -f "/run/user/$(id -u)/.aura_session_pass" 2>/dev/null || true

# 6. Update desktop & icon databases
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "${HOME}/.local/share/applications" &>/dev/null || true
fi
if command -v gtk-update-icon-cache &>/dev/null; then
    gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" &>/dev/null || true
fi

echo -e "\n${GREEN}${BOLD}✓ Aura has been completely and cleanly uninstalled.${RESET}"
