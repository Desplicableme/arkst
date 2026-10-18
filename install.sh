#!/usr/bin/env bash
#
# ArkST — Standalone Universal Linux App Store Installer
# Automatically uninstalls any previous Aura / Ark installation, removes old
# aura-box containers & Aura Hyprland rules, and installs ArkST + arkst-box + Hyprland rules.
#

set -eo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ OK ]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERR ]${NC}  $*" >&2; }

PREFIX="${PREFIX:-/usr}"
LIBDIR="$PREFIX/lib/arkst"
BINDIR="$PREFIX/bin"
DATADIR="$PREFIX/share"
REAL_USER="${SUDO_USER:-${USER:-$(id -un)}}"
REAL_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6 2>/dev/null || echo "$HOME")"
REAL_UID="$(id -u "$REAL_USER" 2>/dev/null || id -u)"

echo ""
echo -e "${CYAN}${BOLD}  ╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}${BOLD}  ║   ▲  ArkST — Universal Linux App Store           ║${NC}"
echo -e "${CYAN}${BOLD}  ║      Pacman · AUR · Flathub · Snap · Containers  ║${NC}"
echo -e "${CYAN}${BOLD}  ╚══════════════════════════════════════════════════╝${NC}"
echo ""

if ! command -v pacman &>/dev/null; then
    err "This installer is designed for Arch-based distributions (requires pacman)."
    exit 1
fi

purge_previous_aura_or_ark() {
    info "Checking for previous Aura Store or Ark installations to remove..."
    local removed_any=0

    # Stop any running aura / ark processes
    pkill -f "/usr/lib/aura/aura.py" 2>/dev/null || true
    pkill -f "/usr/lib/ark/ark.py" 2>/dev/null || true
    pkill -f ".local/share/aura/aura.py" 2>/dev/null || true
    pkill -f "aura-askpass" 2>/dev/null || true
    pkill -f "ark-askpass" 2>/dev/null || true

    # Uninstall pacman package if previously installed via PKGBUILD
    for pkg in aura-store aura-store-git ark-store ark-store-git; do
        if pacman -Qi "$pkg" &>/dev/null; then
            warn "Removing previous package '$pkg' via pacman..."
            sudo pacman -Rns --noconfirm "$pkg" || sudo pacman -R --noconfirm "$pkg" || true
            removed_any=1
        fi
    done

    # Remove system-wide legacy files
    for sys_path in \
        "$PREFIX/lib/aura" \
        "$PREFIX/lib/ark" \
        "$PREFIX/share/aura" \
        "$PREFIX/share/ark" \
        "$BINDIR/aura" \
        "$BINDIR/ark" \
        "/usr/local/bin/aura" \
        "/usr/local/bin/ark" \
        "$DATADIR/applications/io.github.aura.desktop" \
        "$DATADIR/applications/aura.desktop" \
        "$DATADIR/applications/io.github.ark.desktop" \
        "$DATADIR/metainfo/io.github.aura.metainfo.xml" \
        "$DATADIR/metainfo/io.github.ark.metainfo.xml" \
        "$DATADIR/icons/hicolor/scalable/apps/io.github.aura.svg" \
        "$DATADIR/icons/hicolor/scalable/apps/aura-icon.svg" \
        "$DATADIR/icons/hicolor/scalable/apps/io.github.ark.svg" \
        "$DATADIR/pixmaps/io.github.aura.png" \
        "$DATADIR/pixmaps/aura.png" \
        "/etc/sudoers.d/99-aura-pacman"; do
        if [ -e "$sys_path" ] || [ -L "$sys_path" ]; then
            sudo rm -rf "$sys_path"
            removed_any=1
        fi
    done

    # Remove user-level legacy files in ~/.local, ~/.cache, ~/.config
    if [ -n "$REAL_HOME" ] && [ -d "$REAL_HOME" ]; then
        for usr_path in \
            "$REAL_HOME/.local/bin/aura" \
            "$REAL_HOME/.local/bin/ark" \
            "$REAL_HOME/.local/share/aura" \
            "$REAL_HOME/.local/share/ark" \
            "$REAL_HOME/.local/share/applications/io.github.aura.desktop" \
            "$REAL_HOME/.local/share/applications/aura.desktop" \
            "$REAL_HOME/.local/share/applications/io.github.ark.desktop" \
            "$REAL_HOME/.local/share/icons/hicolor/scalable/apps/io.github.aura.svg" \
            "$REAL_HOME/.local/share/icons/hicolor/scalable/apps/aura-icon.svg" \
            "$REAL_HOME/.local/share/icons/hicolor/scalable/apps/io.github.ark.svg" \
            "$REAL_HOME/.cache/aura" \
            "$REAL_HOME/.config/aura" \
            "$REAL_HOME/.config/hypr/hyprland-aura.conf" \
            "$REAL_HOME/.config/hypr/hyprland-ark.conf"; do
            if [ -e "$usr_path" ] || [ -L "$usr_path" ]; then
                rm -rf "$usr_path" 2>/dev/null || sudo rm -rf "$usr_path"
                removed_any=1
            fi
        done

        # Remove any old aura-box-*.desktop or ark-box-*.desktop shortcuts (by name or content)
        if [ -d "$REAL_HOME/.local/share/applications" ]; then
            for dt in "$REAL_HOME/.local/share/applications/"*.desktop; do
                [ -e "$dt" ] || continue
                case "$(basename "$dt")" in
                    *aura*|*ark-box*|io.github.ark.desktop)
                        rm -f "$dt" 2>/dev/null || sudo rm -f "$dt"
                        removed_any=1
                        continue
                        ;;
                esac
                if grep -qiE "aura-box|ark-box|io\.github\.aura|X-Aura-Docker" "$dt" 2>/dev/null; then
                    rm -f "$dt" 2>/dev/null || sudo rm -f "$dt"
                    removed_any=1
                fi
            done
        fi
    fi

    if [ "$removed_any" -eq 1 ]; then
        ok "Previous Aura / Ark installation completely removed."
    else
        ok "No previous Aura installation found — performing clean ArkST install."
    fi
}

check_deps() {
    local missing=()
    python3 -c "import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk" 2>/dev/null || missing+=("gtk4" "python-gobject")
    python3 -c "import gi; gi.require_version('Adw', '1'); from gi.repository import Adw" 2>/dev/null || missing+=("libadwaita")
    command -v checkupdates &>/dev/null || missing+=("pacman-contrib")
    command -v flatpak &>/dev/null || missing+=("flatpak")
    command -v xhost &>/dev/null || missing+=("xorg-xhost")
    pacman -Qi librsvg &>/dev/null || missing+=("librsvg")

    if [ ${#missing[@]} -gt 0 ]; then
        local unique_deps=($(printf "%s\n" "${missing[@]}" | sort -u))
        warn "Installing required dependencies: ${unique_deps[*]}"
        sudo pacman -S --needed --noconfirm "${unique_deps[@]}"
    fi
    ok "All dependencies satisfied."
}

install_files() {
    local SRC_DIR
    SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    info "Installing ArkST application files to $LIBDIR ..."
    sudo rm -rf "$LIBDIR"
    sudo install -dm755 "$LIBDIR"
    sudo install -Dm755 "$SRC_DIR/arkst.py"          "$LIBDIR/arkst.py"
    sudo install -Dm644 "$SRC_DIR/arkst_ui.py"       "$LIBDIR/arkst_ui.py"
    sudo install -Dm644 "$SRC_DIR/arkst_backend.py"  "$LIBDIR/arkst_backend.py"
    sudo install -Dm644 "$SRC_DIR/arkst_gtk_shim.py" "$LIBDIR/arkst_gtk_shim.py"
    sudo install -Dm755 "$SRC_DIR/arkst-askpass"     "$LIBDIR/arkst-askpass"
    sudo install -Dm644 "$SRC_DIR/arkst-icon.png"    "$LIBDIR/arkst-icon.png"
    sudo install -Dm644 "$SRC_DIR/arkst-icon.svg"    "$LIBDIR/arkst-icon.svg"

    # Install data and data/icons preserving directory layout so APP_DIR/data/icons/* always resolves
    sudo install -dm755 "$LIBDIR/data/icons"
    for f in "$SRC_DIR/data/icons/"*; do
        if [ -f "$f" ]; then
            sudo install -Dm644 "$f" "$LIBDIR/data/icons/$(basename "$f")"
        fi
    done
    sudo install -Dm644 "$SRC_DIR/data/hyprland-arkst.conf" "$LIBDIR/data/hyprland-arkst.conf"
    sudo install -Dm644 "$SRC_DIR/data/hyprland-arkst.conf" "$DATADIR/arkst/hyprland-arkst.conf"

    info "Creating standalone launcher at $BINDIR/arkst ..."
    sudo tee "$BINDIR/arkst" > /dev/null <<WRAPPER
#!/usr/bin/env bash
export PYTHONPATH="$LIBDIR:\${PYTHONPATH:-}"
exec python3 "$LIBDIR/arkst.py" "\$@"
WRAPPER
    sudo chmod 755 "$BINDIR/arkst"

    info "Installing desktop entry and multi-resolution launcher icons..."
    sudo install -Dm644 "$SRC_DIR/data/io.github.arkst.desktop" \
        "$DATADIR/applications/io.github.arkst.desktop"
    sudo install -Dm644 "$SRC_DIR/data/io.github.arkst.metainfo.xml" \
        "$DATADIR/metainfo/io.github.arkst.metainfo.xml"

    # Install PNG icons across all standard hicolor resolutions + /usr/share/pixmaps for universal launcher support
    sudo install -Dm644 "$SRC_DIR/arkst-icon.png"           "$DATADIR/icons/hicolor/512x512/apps/io.github.arkst.png"
    sudo install -Dm644 "$SRC_DIR/arkst-icon.png"           "$DATADIR/icons/hicolor/512x512/apps/arkst.png"
    sudo install -Dm644 "$SRC_DIR/data/icons/arkst-256.png" "$DATADIR/icons/hicolor/256x256/apps/io.github.arkst.png"
    sudo install -Dm644 "$SRC_DIR/data/icons/arkst-256.png" "$DATADIR/icons/hicolor/256x256/apps/arkst.png"
    sudo install -Dm644 "$SRC_DIR/data/icons/arkst-128.png" "$DATADIR/icons/hicolor/128x128/apps/io.github.arkst.png"
    sudo install -Dm644 "$SRC_DIR/data/icons/arkst-128.png" "$DATADIR/icons/hicolor/128x128/apps/arkst.png"
    sudo install -Dm644 "$SRC_DIR/data/icons/arkst-64.png"  "$DATADIR/icons/hicolor/64x64/apps/io.github.arkst.png"
    sudo install -Dm644 "$SRC_DIR/data/icons/arkst-64.png"  "$DATADIR/icons/hicolor/64x64/apps/arkst.png"
    sudo install -Dm644 "$SRC_DIR/data/icons/arkst-48.png"  "$DATADIR/icons/hicolor/48x48/apps/io.github.arkst.png"
    sudo install -Dm644 "$SRC_DIR/data/icons/arkst-48.png"  "$DATADIR/icons/hicolor/48x48/apps/arkst.png"
    sudo install -Dm644 "$SRC_DIR/arkst-icon.svg"           "$DATADIR/icons/hicolor/scalable/apps/io.github.arkst.svg"
    sudo install -Dm644 "$SRC_DIR/arkst-icon.svg"           "$DATADIR/icons/hicolor/scalable/apps/arkst.svg"
    sudo install -Dm644 "$SRC_DIR/arkst-icon.png"           "$DATADIR/pixmaps/io.github.arkst.png"
    sudo install -Dm644 "$SRC_DIR/arkst-icon.png"           "$DATADIR/pixmaps/arkst.png"

    if command -v gtk-update-icon-cache &>/dev/null; then
        sudo gtk-update-icon-cache -q -t -f "$DATADIR/icons/hicolor" 2>/dev/null || true
    fi
    if command -v update-desktop-database &>/dev/null; then
        sudo update-desktop-database -q "$DATADIR/applications" 2>/dev/null || true
    fi

    ok "ArkST application files installed!"
}

configure_hyprland_rules() {
    info "Configuring Hyprland floating window rules & Super+A shortcut (and removing old Aura rules)..."
    sudo -u "$REAL_USER" env HOME="$REAL_HOME" XDG_RUNTIME_DIR="/run/user/$REAL_UID" PYTHONPATH="$LIBDIR" \
        python3 -c "
import sys
from pathlib import Path
from arkst_backend import HyprlandManager
hm = HyprlandManager()
hm.HYPR_CONF_PATH = Path('$REAL_HOME') / '.config' / 'hypr' / 'hyprland.conf'
ok, msg = hm.configure_window_rules(enable=True)
print(msg)
" 2>/dev/null || python3 -c "
import sys
sys.path.insert(0, '$LIBDIR')
from pathlib import Path
from arkst_backend import HyprlandManager
hm = HyprlandManager()
hm.HYPR_CONF_PATH = Path('$REAL_HOME') / '.config' / 'hypr' / 'hyprland.conf'
ok, msg = hm.configure_window_rules(enable=True)
print(msg)
" || true
    sudo chown -R "$REAL_USER" "$REAL_HOME/.config/hypr" "$REAL_HOME/.local/share/arkst" 2>/dev/null || true
    ok "Hyprland rules configured and reloaded!"
}

setup_arkst_box_container() {
    info "Setting up ArkST Box ('arkst-box') Docker sandbox and removing legacy 'aura-box'..."
    if ! command -v docker &>/dev/null; then
        warn "Docker is not installed yet — installing docker via pacman..."
        sudo pacman -S --needed --noconfirm docker || true
    fi

    if command -v docker &>/dev/null; then
        sudo systemctl enable --now docker.service 2>/dev/null || sudo systemctl start docker.service 2>/dev/null || true
        sudo usermod -aG docker "$REAL_USER" 2>/dev/null || true
        if [ -S /var/run/docker.sock ]; then
            sudo chmod 666 /var/run/docker.sock 2>/dev/null || true
        fi

        # Remove any legacy aura-box / ark-box containers across docker, podman, and distrobox
        for cname in aura-box ark-box aura-sandbox $(sudo docker ps -a --format '{{.Names}}' 2>/dev/null | grep -iE 'aura|ark-box' || true); do
            sudo docker rm -f "$cname" 2>/dev/null || true
        done
        if command -v podman &>/dev/null; then
            for cname in aura-box ark-box aura-sandbox; do
                podman rm -f "$cname" 2>/dev/null || sudo -u "$REAL_USER" podman rm -f "$cname" 2>/dev/null || true
            done
        fi
        if command -v distrobox &>/dev/null; then
            distrobox rm -f aura-box 2>/dev/null || sudo -u "$REAL_USER" distrobox rm -f aura-box 2>/dev/null || true
            distrobox rm -f ark-box 2>/dev/null || sudo -u "$REAL_USER" distrobox rm -f ark-box 2>/dev/null || true
        fi

        local APP_DATA_DIR="$REAL_HOME/.local/share/arkst/containers"
        mkdir -p "$APP_DATA_DIR" 2>/dev/null || sudo mkdir -p "$APP_DATA_DIR"
        sudo chown -R "$REAL_USER" "$REAL_HOME/.local/share/arkst" 2>/dev/null || true

        # Authorize local container GUI connections if XWayland/X11 is active
        if command -v xhost &>/dev/null; then
            sudo -u "$REAL_USER" xhost +local: 2>/dev/null || xhost +local: 2>/dev/null || true
        fi

        # Create/upgrade arkst-box via ContainerManager as REAL_USER and repair any installed container apps (e.g. VLC)
        sudo -u "$REAL_USER" env HOME="$REAL_HOME" XDG_RUNTIME_DIR="/run/user/$REAL_UID" PYTHONPATH="$LIBDIR" python3 -c "
import os, sys, subprocess
from pathlib import Path
os.environ['HOME'] = '$REAL_HOME'
os.environ['XDG_RUNTIME_DIR'] = '/run/user/$REAL_UID'
from arkst_backend import ContainerManager
cm = ContainerManager()
cm.SHORTCUTS_DIR = Path('$REAL_HOME') / '.local' / 'share' / 'applications'
cm.LAUNCHER_BIN_DIR = Path('$REAL_HOME') / '.local' / 'share' / 'arkst' / 'bin'
cm.LAUNCHER_SCRIPT = cm.LAUNCHER_BIN_DIR / 'arkst-box-launch'

# Collect any already-installed arkst-box apps from existing shortcuts before upgrading container mounts
existing_apps = []
if cm.SHORTCUTS_DIR.exists():
    for dt in cm.SHORTCUTS_DIR.glob('arkst-box-*.desktop'):
        aid = dt.stem[len('arkst-box-'):]
        if aid and aid not in existing_apps:
            existing_apps.append(aid)

# Remove old arkst-box if it lacks QT_X11_NO_MITSHM=1 or full /run/user mount
insp = subprocess.run(['docker', 'inspect', '-f', '{{json .Config.Env}}', cm.CONTAINER_NAME], capture_output=True, text=True)
if insp.returncode == 0 and 'QT_X11_NO_MITSHM=1' not in (insp.stdout or ''):
    print('  -> Upgrading existing arkst-box container with full Wayland/X11/Audio socket passthrough...')
    subprocess.run(['docker', 'rm', '-f', cm.CONTAINER_NAME], capture_output=True)
    cm.invalidate_cache()

cm.migrate_legacy_containers()
ok, msg = cm.ensure_container_configured(progress_callback=lambda s: print('  ->', s))
print('  -> Container status:', ok, msg)
cm._ensure_launcher_script()
cm.repair_existing_shortcuts()

# Re-verify and repair any previously installed container apps (such as VLC -> vlc-qt + root check patch)
for aid in existing_apps:
    print(f'  -> Repairing & upgrading container app: {aid} ...')
    done = []
    cm.install_app(aid, progress_callback=lambda m: print('     ', m), completion_callback=lambda o, m: done.append((o, m)))
    import time
    for _ in range(180):
        if done:
            break
        time.sleep(1)
" || true
        sudo chown -R "$REAL_USER" "$REAL_HOME/.local/share/arkst" "$REAL_HOME/.local/share/applications" 2>/dev/null || true
        if sudo docker inspect -f '{{.State.Running}}' arkst-box 2>/dev/null | grep -q true; then
            ok "ArkST Box ('arkst-box') container is installed and ACTIVE!"
        else
            warn "Docker container 'arkst-box' will finish initializing on first launch."
        fi
    fi
}

purge_previous_aura_or_ark
check_deps
install_files
configure_hyprland_rules
setup_arkst_box_container

echo ""
echo -e "${GREEN}${BOLD}  Installation complete!${NC}"
echo -e "  Run ${CYAN}arkst${NC} from your terminal, press ${BOLD}Super + A${NC}, or launch ${BOLD}ArkST${NC} from your app launcher."
echo ""
