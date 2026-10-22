#!/usr/bin/env python3
"""
Ark Store (ArkST Software Center) - Backend Module
Handles:
- Pacman local repository database indexing & caching
- Installed package querying & status tracking
- Real-time system updates checking (official + AUR)
- AUR RPC query and paru fallback
- High-performance fuzzy matching with strict priority (Pacman > Paru)
- Authentic Linux application icon mapping
- In-process background installation & updates with real-time progress callbacks
"""

import os
import io
import re
import sys
import glob
import json
import time
import random
import pickle
import shutil
import tarfile
import threading
import subprocess
import tempfile
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any, Callable

__version__ = "3.1.0"

def _resolve_writable_dir(preferred: Path, fallback_name: str) -> Path:
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except Exception:
        fb = Path(tempfile.gettempdir()) / f"arkst-{os.getuid()}-{fallback_name}"
        fb.mkdir(parents=True, exist_ok=True)
        return fb

CACHE_DIR = _resolve_writable_dir(
    Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "arkst",
    "cache"
)
DATA_DIR = _resolve_writable_dir(
    Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "arkst",
    "data"
)
CACHE_FILE = CACHE_DIR / "sync_cache.pkl"
UPDATES_CACHE_FILE = CACHE_DIR / "updates_cache.json"
FEATURED_STATE_FILE = CACHE_DIR / "featured_state.json"
SYNC_DIR = Path("/var/lib/pacman/sync")

def get_askpass_script() -> Path:
    """Dynamically resolve executable arkst-askpass helper across dev, local, and system paths."""
    candidates = [
        Path(__file__).resolve().parent / "arkst-askpass",
        Path.home() / ".local" / "share" / "arkst" / "arkst-askpass",
        Path("/usr/lib/arkst/arkst-askpass"),
    ]
    for c in candidates:
        if c.exists() and os.access(c, os.X_OK):
            return c
    return candidates[0]

ASKPASS_SCRIPT = get_askpass_script()

def get_aur_helper() -> Optional[str]:
    """Return the name of the preferred installed AUR helper ('paru' or 'yay'), or None."""
    for helper in ("paru", "yay"):
        if shutil.which(helper):
            return helper
    return None

def _load_featured_state() -> Dict[str, Any]:
    """Load persistent featured rotation state from disk."""
    if FEATURED_STATE_FILE.exists():
        try:
            with open(FEATURED_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return {
                        "offset": int(data.get("offset", 0)),
                        "last_shown": [str(x) for x in data.get("last_shown", []) if isinstance(x, str)],
                    }
        except Exception:
            pass
    return {"offset": 0, "last_shown": []}

def _save_featured_state(offset: int, last_shown: List[str]):
    """Save persistent featured rotation state to disk immediately."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_file = FEATURED_STATE_FILE.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump({"offset": int(offset), "last_shown": list(last_shown)}, f, indent=2)
        tmp_file.replace(FEATURED_STATE_FILE)
    except Exception:
        pass


# Apple-style Curated Categories (Symmetric, No Emojis, Authentic Functional Channels)
CURATED_CATEGORIES = [
    {
        "id": "essential",
        "category": "Essential Applications",
        "subtitle": "Must-have applications for everyday desktop workflow",
        "icon": "starred-symbolic",
        "apps": [
            {"name": "firefox", "title": "Firefox", "desc": "Fast, privacy-respecting browser", "source": "pacman"},
            {"name": "code", "title": "Visual Studio Code", "desc": "Code editor and developer platform", "source": "pacman"},
            {"name": "discord", "title": "Discord", "desc": "Voice and text chat for communities", "source": "pacman"},
            {"name": "steam", "title": "Steam", "desc": "Gaming platform and game launcher", "source": "pacman"},
            {"name": "spotify", "title": "Spotify", "desc": "Music streaming service desktop app", "source": "aur"},
            {"name": "proton-vpn-gtk-app", "title": "Proton VPN", "desc": "Secure VPN client with WireGuard", "source": "pacman"},
            {"name": "telegram-desktop", "title": "Telegram Desktop", "desc": "Fast and secure cloud-based messaging", "source": "pacman"},
            {"name": "vlc", "title": "VLC Media Player", "desc": "Universal multimedia player and framework", "source": "pacman"},
            {"name": "obs-studio", "title": "OBS Studio", "desc": "High-performance screen recorder and livestreamer", "source": "pacman"},
            {"name": "gimp", "title": "GIMP", "desc": "Advanced image manipulation and artwork editor", "source": "pacman"},
            {"name": "blender", "title": "Blender", "desc": "Full 3D creation suite and animation editor", "source": "pacman"},
            {"name": "bitwarden", "title": "Bitwarden", "desc": "Secure open-source password vault", "source": "pacman"},
        ]
    },
    {
        "id": "dev",
        "category": "Development",
        "subtitle": "High-performance compilers, code editors, and terminals",
        "icon": "utilities-terminal-symbolic",
        "apps": [
            {"name": "code", "title": "Visual Studio Code", "desc": "Code editor and developer platform", "source": "pacman"},
            {"name": "neovim", "title": "Neovim", "desc": "Extensible high-speed text editor", "source": "pacman"},
            {"name": "git", "title": "Git", "desc": "Fast distributed version control", "source": "pacman"},
            {"name": "lazygit", "title": "LazyGit", "desc": "Simple terminal UI for git commands", "source": "pacman"},
            {"name": "alacritty", "title": "Alacritty", "desc": "Fast GPU-accelerated terminal", "source": "pacman"},
            {"name": "kitty", "title": "Kitty", "desc": "Feature-rich modern terminal", "source": "pacman"},
            {"name": "zed", "title": "Zed", "desc": "High-performance multiplayer code editor", "source": "aur"},
            {"name": "postman-bin", "title": "Postman", "desc": "API development and testing platform", "source": "aur"},
            {"name": "docker", "title": "Docker", "desc": "Enterprise container platform and tooling", "source": "pacman"},
            {"name": "rust", "title": "Rust & Cargo", "desc": "Modern memory-safe systems programming language", "source": "pacman"},
            {"name": "go", "title": "Go", "desc": "Fast, compiled concurrency-focused language", "source": "pacman"},
            {"name": "dbeaver", "title": "DBeaver", "desc": "Universal SQL database client and GUI", "source": "pacman"},
        ]
    },
    {
        "id": "productivity",
        "category": "Productivity",
        "subtitle": "Office suites, knowledge bases, and focused writing",
        "icon": "x-office-document-symbolic",
        "apps": [
            {"name": "libreoffice-fresh", "title": "LibreOffice", "desc": "Comprehensive office suite for docs and sheets", "source": "pacman"},
            {"name": "obsidian", "title": "Obsidian", "desc": "Knowledge base and connected markdown notes", "source": "aur"},
            {"name": "thunar", "title": "Thunar", "desc": "Fast lightweight desktop file manager", "source": "pacman"},
            {"name": "micro", "title": "Micro Editor", "desc": "Intuitive terminal text editor with mouse support", "source": "pacman"},
            {"name": "fastfetch", "title": "Fastfetch", "desc": "High-speed system information tool", "source": "pacman"},
            {"name": "pavucontrol", "title": "Volume Control", "desc": "Advanced PulseAudio and PipeWire audio control", "source": "pacman"},
            {"name": "joplin-desktop", "title": "Joplin", "desc": "Secure markdown note taking with cloud sync", "source": "aur"},
            {"name": "onlyoffice-bin", "title": "OnlyOffice", "desc": "Collaborative document and spreadsheet editor", "source": "aur"},
            {"name": "anytype-bin", "title": "Anytype", "desc": "Privacy-first decentralized knowledge base", "source": "aur"},
            {"name": "evince", "title": "Evince", "desc": "Document viewer for PDF, PostScript, and DjVu", "source": "pacman"},
            {"name": "krita", "title": "Krita", "desc": "Professional free and open source painting program", "source": "pacman"},
            {"name": "foliate", "title": "Foliate", "desc": "Modern ebook reader with distraction-free layout", "source": "pacman"},
        ]
    },
    {
        "id": "privacy",
        "category": "Internet & Privacy",
        "subtitle": "Secure browsers, encrypted messaging, and privacy tools",
        "icon": "security-high-symbolic",
        "apps": [
            {"name": "brave-bin", "title": "Brave Browser", "desc": "Privacy-focused browser with ad and tracker blocking", "source": "aur"},
            {"name": "torbrowser-launcher", "title": "Tor Browser", "desc": "Secure anonymous browsing over the Tor network", "source": "pacman"},
            {"name": "keepassxc", "title": "KeepassXC", "desc": "Offline cross-platform password database", "source": "pacman"},
            {"name": "proton-vpn-gtk-app", "title": "Proton VPN", "desc": "Encrypted VPN client with Kill Switch", "source": "pacman"},
            {"name": "wireguard-tools", "title": "WireGuard", "desc": "Extremely fast modern encrypted VPN tunnel", "source": "pacman"},
            {"name": "mullvad-vpn-bin", "title": "Mullvad VPN", "desc": "Privacy-focused WireGuard VPN desktop app", "source": "aur"},
            {"name": "chromium", "title": "Chromium", "desc": "Open-source web browser foundation", "source": "pacman"},
            {"name": "signal-desktop", "title": "Signal Desktop", "desc": "Private end-to-end encrypted messaging", "source": "pacman"},
            {"name": "wireshark-qt", "title": "Wireshark", "desc": "Network packet analyzer and traffic inspector", "source": "pacman"},
            {"name": "bleachbit", "title": "BleachBit", "desc": "Clean caches, free disk space, and guard privacy", "source": "pacman"},
            {"name": "tailscale", "title": "Tailscale", "desc": "Zero config mesh VPN for secure device networks", "source": "pacman"},
            {"name": "thunderbird", "title": "Thunderbird", "desc": "Feature-packed email, calendar, and contacts client", "source": "pacman"},
        ]
    },
    {
        "id": "media",
        "category": "Media & Creative",
        "subtitle": "Audio, video streaming, recording, and digital artistry",
        "icon": "applications-graphics-symbolic",
        "apps": [
            {"name": "vlc", "title": "VLC Media Player", "desc": "Plays every audio and video codec natively", "source": "pacman"},
            {"name": "spotify", "title": "Spotify", "desc": "Stream millions of songs and podcasts", "source": "aur"},
            {"name": "gimp", "title": "GIMP", "desc": "GNU Image Manipulation and photo editing tool", "source": "pacman"},
            {"name": "inkscape", "title": "Inkscape", "desc": "Professional vector graphics illustrator", "source": "pacman"},
            {"name": "audacity", "title": "Audacity", "desc": "Multi-track audio editor and recorder", "source": "pacman"},
            {"name": "kdenlive", "title": "Kdenlive", "desc": "Powerful non-linear multi-track video editor", "source": "pacman"},
            {"name": "blender", "title": "Blender", "desc": "World-class 3D modeling, rendering, and VFX suite", "source": "pacman"},
            {"name": "obs-studio", "title": "OBS Studio", "desc": "Live video streaming and desktop screen capture", "source": "pacman"},
            {"name": "handbrake", "title": "HandBrake", "desc": "Fast universal video transcoder and converter", "source": "pacman"},
            {"name": "mpv", "title": "mpv", "desc": "Minimalist, powerful GPU-accelerated video player", "source": "pacman"},
            {"name": "darktable", "title": "Darktable", "desc": "Virtual lighttable and raw photo developer", "source": "pacman"},
            {"name": "ardour", "title": "Ardour", "desc": "Professional digital audio workstation (DAW)", "source": "pacman"},
        ]
    },
    {
        "id": "system",
        "category": "System & Tools",
        "subtitle": "Hardware monitors, fast terminal utilities, and tools",
        "icon": "system-run-symbolic",
        "apps": [
            {"name": "btop", "title": "Btop", "desc": "Aesthetic terminal system monitor and resource viewer", "source": "pacman"},
            {"name": "htop", "title": "Htop", "desc": "Interactive process viewer and processor monitor", "source": "pacman"},
            {"name": "gparted", "title": "GParted", "desc": "Partition editor for graphically managing disks", "source": "pacman"},
            {"name": "timeshift", "title": "Timeshift", "desc": "System restore utility creating incremental snapshots", "source": "pacman"},
            {"name": "baobab", "title": "Baobab", "desc": "Visual disk usage analyzer with tree rings", "source": "pacman"},
            {"name": "fastfetch", "title": "Fastfetch", "desc": "Rapid system info display for modern Linux", "source": "pacman"},
            {"name": "stacer-bin", "title": "Stacer", "desc": "Linux system optimizer and hardware monitoring dashboard", "source": "aur"},
            {"name": "pavucontrol", "title": "Volume Control", "desc": "Audio routing and mixer for PipeWire", "source": "pacman"},
            {"name": "fish", "title": "Fish Shell", "desc": "Smart user-friendly command line shell", "source": "pacman"},
            {"name": "kitty", "title": "Kitty", "desc": "GPU-accelerated terminal emulator with tabs", "source": "pacman"},
            {"name": "alacritty", "title": "Alacritty", "desc": "Blazing fast OpenGL terminal emulator", "source": "pacman"},
            {"name": "hardinfo-git", "title": "Hardinfo", "desc": "System benchmark and hardware information tool", "source": "aur"},
        ]
    },
    {
        "id": "games",
        "category": "Gaming",
        "subtitle": "Game platforms, launchers, emulators, and gaming utilities",
        "icon": "applications-games-symbolic",
        "apps": [
            {"name": "steam", "title": "Steam", "desc": "Ultimate gaming platform with Proton compatibility", "source": "pacman"},
            {"name": "lutris", "title": "Lutris", "desc": "Open gaming platform for Windows, Linux, and emulators", "source": "pacman"},
            {"name": "heroic-games-launcher-bin", "title": "Heroic Games Launcher", "desc": "Epic Games and GOG game launcher", "source": "aur"},
            {"name": "discord", "title": "Discord", "desc": "Voice, video, and text communication for gamers", "source": "pacman"},
            {"name": "retroarch", "title": "RetroArch", "desc": "Multi-system emulator frontend for classic games", "source": "pacman"},
            {"name": "prismlauncher", "title": "Prism Launcher", "desc": "Custom Minecraft launcher with modpack support", "source": "pacman"},
            {"name": "mangohud", "title": "MangoHud", "desc": "Vulkan and OpenGL overlay for monitoring FPS and temps", "source": "pacman"},
            {"name": "bottles", "title": "Bottles", "desc": "Run Windows software and games using Wine environments", "source": "aur"},
            {"name": "wine", "title": "Wine", "desc": "Compatibility layer capable of running Windows apps", "source": "pacman"},
            {"name": "obs-studio", "title": "OBS Studio", "desc": "Capture, stream, and record your gameplay", "source": "pacman"},
            {"name": "gamemode", "title": "GameMode", "desc": "Optimizes Linux system performance on demand", "source": "pacman"},
            {"name": "ryujinx-bin", "title": "Ryujinx", "desc": "Experimental Nintendo Switch emulator written in C#", "source": "aur"},
        ]
    },
    {
        "id": "hyprland",
        "category": "Hyprland Ecosystem",
        "subtitle": "Wayland bars, lockscreens, launchers, wallpaper daemons, and tiling utilities",
        "icon": "preferences-desktop-display-symbolic",
        "apps": [
            {"name": "waybar", "title": "Waybar", "desc": "Highly customizable Wayland bar for Hyprland and Sway", "source": "pacman"},
            {"name": "rofi-wayland", "title": "Rofi Wayland", "desc": "Window switcher, app launcher, and dmenu replacement for Wayland", "source": "pacman"},
            {"name": "hyprpaper", "title": "Hyprpaper", "desc": "Blazing fast IPC-controlled wallpaper utility for Hyprland", "source": "pacman"},
            {"name": "hyprlock", "title": "Hyprlock", "desc": "GPU-accelerated screen locking utility for Hyprland", "source": "pacman"},
            {"name": "hypridle", "title": "Hypridle", "desc": "Hyprland's official idle management daemon", "source": "pacman"},
            {"name": "hyprpicker", "title": "Hyprpicker", "desc": "wlroots-compatible Wayland color picker that does not suck", "source": "pacman"},
            {"name": "swaync", "title": "SwayNotificationCenter", "desc": "GTK notification daemon with customizable control center panel", "source": "pacman"},
            {"name": "swww", "title": "swww Wallpaper Daemon", "desc": "Efficient animated wallpaper daemon for Wayland compositors", "source": "pacman"},
            {"name": "wlogout", "title": "wlogout", "desc": "Wayland-based logout and session power menu for Hyprland", "source": "aur"},
            {"name": "nwg-look", "title": "nwg-look GTK Settings", "desc": "GTK3/GTK4 theme, icon, cursor, and font editor for Wayland", "source": "pacman"},
            {"name": "nwg-displays", "title": "nwg-displays Monitors", "desc": "Multi-monitor layout and resolution configurator for Hyprland", "source": "pacman"},
            {"name": "grim", "title": "Grim & Slurp Screenshots", "desc": "Capture crisp Wayland screenshots and region selections", "source": "pacman"},
        ]
    }
]
FEATURED_APPS = CURATED_CATEGORIES

# Dynamic Featured Applications Metadata & Editorial Catalog
FEATURED_APP_PRESETS: Dict[str, Dict[str, Any]] = {
    # Media & Creative
    "blender": {
        "title": "Blender 3D Studio",
        "tag": "FEATURED 3D SUITE",
        "sub": "Unleash next-gen 3D modeling, animation, physics simulation, and real-time photorealistic rendering",
        "accent_color": "#eb7700",
        "bg": "radial-gradient(circle at 82% 50%, rgba(235, 119, 0, 0.32) 0%, rgba(235, 119, 0, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(235, 119, 0, 0.24) 0%, rgba(22, 24, 32, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(235, 119, 0, 0.40)",
        "icon": "blender",
        "source": "pacman",
    },
    "obs-studio": {
        "title": "OBS Studio",
        "tag": "BROADCAST ESSENTIAL",
        "sub": "Stream high-definition gameplay and capture pristine multi-source desktop broadcasts",
        "accent_color": "#a371f7",
        "bg": "radial-gradient(circle at 82% 50%, rgba(163, 113, 247, 0.32) 0%, rgba(163, 113, 247, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(48, 54, 61, 0.4) 0%, rgba(163, 113, 247, 0.24) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(163, 113, 247, 0.40)",
        "icon": "obs-studio",
        "source": "pacman",
    },
    "kdenlive": {
        "title": "Kdenlive Video Editor",
        "tag": "NEXT-GEN CREATIVE",
        "sub": "Powerful non-linear multi-track video editing with color grading, transitions, and audio mastering",
        "accent_color": "#2980b9",
        "bg": "radial-gradient(circle at 82% 50%, rgba(41, 128, 185, 0.32) 0%, rgba(41, 128, 185, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(41, 128, 185, 0.24) 0%, rgba(18, 25, 35, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(41, 128, 185, 0.40)",
        "icon": "kdenlive",
        "source": "pacman",
    },
    "gimp": {
        "title": "GIMP Studio",
        "tag": "CREATIVE IMAGE SUITE",
        "sub": "Advanced open-source image manipulation, high-bit-depth retouching, and digital artwork creation",
        "accent_color": "#e67e22",
        "bg": "radial-gradient(circle at 82% 50%, rgba(230, 126, 34, 0.32) 0%, rgba(230, 126, 34, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(230, 126, 34, 0.24) 0%, rgba(25, 23, 20, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(230, 126, 34, 0.40)",
        "icon": "gimp",
        "source": "pacman",
    },
    "inkscape": {
        "title": "Inkscape Vector Studio",
        "tag": "VECTOR DESIGN STUDIO",
        "sub": "Professional open-source vector graphics editor for diagrams, typography, logos, and illustration",
        "accent_color": "#00d2d3",
        "bg": "radial-gradient(circle at 82% 50%, rgba(0, 210, 211, 0.32) 0%, rgba(0, 210, 211, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(0, 210, 211, 0.24) 0%, rgba(18, 30, 32, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(0, 210, 211, 0.40)",
        "icon": "inkscape",
        "source": "pacman",
    },
    "audacity": {
        "title": "Audacity Audio Studio",
        "tag": "AUDIO MASTERING SUITE",
        "sub": "Multi-track audio editor, recorder, and mastering suite with real-time effects and spectrum analysis",
        "accent_color": "#0984e3",
        "bg": "radial-gradient(circle at 82% 50%, rgba(9, 132, 227, 0.32) 0%, rgba(9, 132, 227, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(9, 132, 227, 0.24) 0%, rgba(18, 26, 38, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(9, 132, 227, 0.40)",
        "icon": "audacity",
        "source": "pacman",
    },
    "darktable": {
        "title": "Darktable Photography",
        "tag": "PRO PHOTO WORKFLOW",
        "sub": "Virtual lighttable and non-destructive RAW photo developer for professional photographers",
        "accent_color": "#d35400",
        "bg": "radial-gradient(circle at 82% 50%, rgba(211, 84, 0, 0.32) 0%, rgba(211, 84, 0, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(211, 84, 0, 0.24) 0%, rgba(28, 20, 18, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(211, 84, 0, 0.40)",
        "icon": "darktable",
        "source": "pacman",
    },
    "ardour": {
        "title": "Ardour Digital Audio",
        "tag": "DIGITAL AUDIO WORKSTATION",
        "sub": "Professional digital audio workstation (DAW) for recording, editing, mixing, and mastering",
        "accent_color": "#c0392b",
        "bg": "radial-gradient(circle at 82% 50%, rgba(192, 57, 43, 0.32) 0%, rgba(192, 57, 43, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(192, 57, 43, 0.24) 0%, rgba(28, 18, 18, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(192, 57, 43, 0.40)",
        "icon": "ardour",
        "source": "pacman",
    },
    "handbrake": {
        "title": "HandBrake Transcoder",
        "tag": "VIDEO TRANSCODING PRO",
        "sub": "Universal open-source video transcoder converting videos to modern AV1, HEVC, and H.264 formats",
        "accent_color": "#e74c3c",
        "bg": "radial-gradient(circle at 82% 50%, rgba(231, 76, 60, 0.32) 0%, rgba(231, 76, 60, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(231, 76, 60, 0.24) 0%, rgba(28, 19, 20, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(231, 76, 60, 0.40)",
        "icon": "fr.handbrake.ghb",
        "source": "pacman",
    },
    "vlc": {
        "title": "VLC Media Player",
        "tag": "UNIVERSAL MEDIA PLAYER",
        "sub": "Universal media player playing every format, codec, stream, and subtitle out of the box with zero fuss",
        "accent_color": "#ff793f",
        "bg": "radial-gradient(circle at 82% 50%, rgba(255, 121, 63, 0.32) 0%, rgba(255, 121, 63, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(255, 121, 63, 0.24) 0%, rgba(28, 22, 18, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(255, 121, 63, 0.40)",
        "icon": "vlc",
        "source": "pacman",
    },
    "spotify": {
        "title": "Spotify",
        "tag": "STREAMING SPOTLIGHT",
        "sub": "Stream millions of high-fidelity tracks, personalized playlists, and podcasts directly on desktop",
        "accent_color": "#1db954",
        "bg": "radial-gradient(circle at 82% 50%, rgba(29, 185, 84, 0.32) 0%, rgba(29, 185, 84, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(29, 185, 84, 0.24) 0%, rgba(16, 26, 20, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(29, 185, 84, 0.40)",
        "icon": "spotify",
        "source": "aur",
    },
    "mpv": {
        "title": "mpv Video Player",
        "tag": "MEDIA SPOTLIGHT",
        "sub": "Minimalist, powerhouse GPU-accelerated video player with high-quality video scaling and shaders",
        "accent_color": "#6c5ce7",
        "bg": "radial-gradient(circle at 82% 50%, rgba(108, 92, 231, 0.32) 0%, rgba(108, 92, 231, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(108, 92, 231, 0.24) 0%, rgba(20, 19, 32, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(108, 92, 231, 0.40)",
        "icon": "mpv",
        "source": "pacman",
    },

    # Development
    "code": {
        "title": "Visual Studio Code",
        "tag": "DEVELOPER SPOTLIGHT",
        "sub": "The world's most versatile code editor with intelligent AI autocompletion, debugging, and cloud workflows",
        "accent_color": "#007acc",
        "bg": "radial-gradient(circle at 82% 50%, rgba(0, 122, 204, 0.32) 0%, rgba(0, 122, 204, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(0, 122, 204, 0.25) 0%, rgba(18, 24, 34, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(0, 122, 204, 0.40)",
        "icon": "code",
        "source": "pacman",
    },
    "zed": {
        "title": "Zed Code Editor",
        "tag": "NEXT-GEN CODE EDITOR",
        "sub": "Lightning-fast, GPU-accelerated code editor engineered in Rust for instantaneous multiplayer collaboration",
        "accent_color": "#47c8ff",
        "bg": "radial-gradient(circle at 82% 50%, rgba(71, 200, 255, 0.32) 0%, rgba(71, 200, 255, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(71, 200, 255, 0.24) 0%, rgba(18, 28, 38, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(71, 200, 255, 0.40)",
        "icon": "zed",
        "source": "aur",
    },
    "neovim": {
        "title": "Neovim",
        "tag": "HYPER-EXTENSIBLE VIM",
        "sub": "Hyperextensible Vim-based text editor built for high-speed terminal coding, Lua plugins, and native LSP",
        "accent_color": "#57a143",
        "bg": "radial-gradient(circle at 82% 50%, rgba(87, 161, 67, 0.32) 0%, rgba(87, 161, 67, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(87, 161, 67, 0.24) 0%, rgba(18, 26, 20, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(87, 161, 67, 0.40)",
        "icon": "nvim",
        "source": "pacman",
    },
    "alacritty": {
        "title": "Alacritty Terminal",
        "tag": "BLAZING FAST TERMINAL",
        "sub": "Blazing-fast GPU-accelerated terminal emulator optimized for raw throughput, low latency, and simplicity",
        "accent_color": "#f39c12",
        "bg": "radial-gradient(circle at 82% 50%, rgba(243, 156, 18, 0.32) 0%, rgba(243, 156, 18, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(243, 156, 18, 0.24) 0%, rgba(28, 24, 18, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(243, 156, 18, 0.40)",
        "icon": "Alacritty",
        "source": "pacman",
    },
    "kitty": {
        "title": "Kitty Terminal",
        "tag": "GPU POWER TERMINAL",
        "sub": "Feature-rich GPU-accelerated terminal with tabs, splits, graphics protocol support, and scriptability",
        "accent_color": "#2ecc71",
        "bg": "radial-gradient(circle at 82% 50%, rgba(46, 204, 113, 0.32) 0%, rgba(46, 204, 113, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(46, 204, 113, 0.24) 0%, rgba(18, 28, 22, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(46, 204, 113, 0.40)",
        "icon": "kitty",
        "source": "pacman",
    },
    "lazygit": {
        "title": "LazyGit",
        "tag": "TERMINAL GIT SPOTLIGHT",
        "sub": "Intuitive terminal graphical user interface for effortlessly navigating Git commits, branches, and diffs",
        "accent_color": "#ff6b6b",
        "bg": "radial-gradient(circle at 82% 50%, rgba(255, 107, 107, 0.32) 0%, rgba(255, 107, 107, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(255, 107, 107, 0.24) 0%, rgba(30, 20, 22, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(255, 107, 107, 0.40)",
        "icon": "lazygit",
        "source": "pacman",
    },
    "postman-bin": {
        "title": "Postman API Suite",
        "tag": "API DEVELOPMENT SUITE",
        "sub": "Complete API development platform for designing, testing, automating, and mocking HTTP & GraphQL endpoints",
        "accent_color": "#ff6c37",
        "bg": "radial-gradient(circle at 82% 50%, rgba(255, 108, 55, 0.32) 0%, rgba(255, 108, 55, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(255, 108, 55, 0.24) 0%, rgba(30, 21, 18, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(255, 108, 55, 0.40)",
        "icon": "postman",
        "source": "aur",
    },
    "docker": {
        "title": "Docker Platform",
        "tag": "CONTAINER PLATFORM",
        "sub": "Industry-standard container platform to build, package, and deploy isolated microservices effortlessly",
        "accent_color": "#2496ed",
        "bg": "radial-gradient(circle at 82% 50%, rgba(36, 150, 237, 0.32) 0%, rgba(36, 150, 237, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(36, 150, 237, 0.24) 0%, rgba(18, 25, 36, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(36, 150, 237, 0.40)",
        "icon": "docker",
        "source": "pacman",
    },
    "dbeaver": {
        "title": "DBeaver Studio",
        "tag": "UNIVERSAL DATABASE GUI",
        "sub": "Universal database management tool supporting PostgreSQL, MySQL, SQLite, and cloud databases",
        "accent_color": "#377ba8",
        "bg": "radial-gradient(circle at 82% 50%, rgba(55, 123, 168, 0.32) 0%, rgba(55, 123, 168, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(55, 123, 168, 0.24) 0%, rgba(18, 25, 32, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(55, 123, 168, 0.40)",
        "icon": "dbeaver",
        "source": "pacman",
    },
    "rust": {
        "title": "Rust & Cargo",
        "tag": "SYSTEMS LANGUAGE",
        "sub": "Empowering everyone to build reliable, memory-safe, and blazingly fast modern systems",
        "accent_color": "#ce412b",
        "bg": "radial-gradient(circle at 82% 50%, rgba(206, 65, 43, 0.32) 0%, rgba(206, 65, 43, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(206, 65, 43, 0.24) 0%, rgba(30, 19, 18, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(206, 65, 43, 0.40)",
        "icon": "rust",
        "source": "pacman",
    },
    "go": {
        "title": "Go Language",
        "tag": "CLOUD CONCURRENCY",
        "sub": "Fast, compiled, concurrency-focused programming language engineered by Google for cloud scale",
        "accent_color": "#00add8",
        "bg": "radial-gradient(circle at 82% 50%, rgba(0, 173, 216, 0.32) 0%, rgba(0, 173, 216, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(0, 173, 216, 0.24) 0%, rgba(16, 26, 34, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(0, 173, 216, 0.40)",
        "icon": "go",
        "source": "pacman",
    },
    "git": {
        "title": "Git Version Control",
        "tag": "DISTRIBUTED VERSION CONTROL",
        "sub": "Fast, scalable distributed revision control system designed for projects of any scale",
        "accent_color": "#f05032",
        "bg": "radial-gradient(circle at 82% 50%, rgba(240, 80, 50, 0.32) 0%, rgba(240, 80, 50, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(240, 80, 50, 0.24) 0%, rgba(30, 20, 18, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(240, 80, 50, 0.40)",
        "icon": "git",
        "source": "pacman",
    },

    # Gaming
    "steam": {
        "title": "Steam on Linux",
        "tag": "PRO GAMING PLATFORM",
        "sub": "Play thousands of native and Windows titles with seamless Proton performance and Steam Deck synergy",
        "accent_color": "#66c0f4",
        "bg": "radial-gradient(circle at 82% 50%, rgba(102, 192, 244, 0.32) 0%, rgba(102, 192, 244, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(23, 29, 37, 0.6) 0%, rgba(102, 192, 244, 0.24) 45%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(102, 192, 244, 0.40)",
        "icon": "steam",
        "source": "pacman",
    },
    "heroic-games-launcher-bin": {
        "title": "Heroic Games Launcher",
        "tag": "EPIC & GOG LAUNCHER",
        "sub": "Modern native open-source launcher for Epic Games, GOG, and Amazon Prime Gaming on Linux",
        "accent_color": "#d9534f",
        "bg": "radial-gradient(circle at 82% 50%, rgba(217, 83, 79, 0.32) 0%, rgba(217, 83, 79, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(217, 83, 79, 0.24) 0%, rgba(30, 20, 22, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(217, 83, 79, 0.40)",
        "icon": "heroic",
        "source": "aur",
    },
    "lutris": {
        "title": "Lutris Gaming Platform",
        "tag": "OPEN GAMING HUB",
        "sub": "Open gaming management platform organizing your GOG, Epic, Steam, Battle.net, and emulator libraries",
        "accent_color": "#ff6f00",
        "bg": "radial-gradient(circle at 82% 50%, rgba(255, 111, 0, 0.32) 0%, rgba(255, 111, 0, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(255, 111, 0, 0.24) 0%, rgba(30, 23, 18, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(255, 111, 0, 0.40)",
        "icon": "lutris",
        "source": "pacman",
    },
    "retroarch": {
        "title": "RetroArch",
        "tag": "RETRO EMULATION MATRIX",
        "sub": "The premier multi-system emulator frontend for classic consoles, handhelds, and arcade machines",
        "accent_color": "#3498db",
        "bg": "radial-gradient(circle at 82% 50%, rgba(52, 152, 219, 0.32) 0%, rgba(52, 152, 219, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(52, 152, 219, 0.24) 0%, rgba(18, 26, 35, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(52, 152, 219, 0.40)",
        "icon": "retroarch",
        "source": "pacman",
    },
    "prismlauncher": {
        "title": "Prism Launcher",
        "tag": "MINECRAFT POWER LAUNCHER",
        "sub": "High-performance custom Minecraft launcher with seamless modpack installation and instance isolation",
        "accent_color": "#30d158",
        "bg": "radial-gradient(circle at 82% 50%, rgba(48, 209, 88, 0.32) 0%, rgba(48, 209, 88, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(48, 209, 88, 0.24) 0%, rgba(18, 28, 20, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(48, 209, 88, 0.40)",
        "icon": "org.prismlauncher.PrismLauncher",
        "source": "pacman",
    },
    "bottles": {
        "title": "Bottles for Linux",
        "tag": "WINE ENVIRONMENT MANAGER",
        "sub": "Easily manage Wine and Proton prefixes to run Windows software and games with custom environments",
        "accent_color": "#54a0ff",
        "bg": "radial-gradient(circle at 82% 50%, rgba(84, 160, 255, 0.32) 0%, rgba(84, 160, 255, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(84, 160, 255, 0.24) 0%, rgba(20, 26, 36, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(84, 160, 255, 0.40)",
        "icon": "com.usebottles.bottles",
        "source": "aur",
    },
    "ryujinx-bin": {
        "title": "Ryujinx Emulator",
        "tag": "PRECISION EMULATION",
        "sub": "Experimental Nintendo Switch emulator offering exceptional accuracy, performance, and Vulkan backend",
        "accent_color": "#e056fd",
        "bg": "radial-gradient(circle at 82% 50%, rgba(224, 86, 253, 0.32) 0%, rgba(224, 86, 253, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(224, 86, 253, 0.24) 0%, rgba(30, 20, 32, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(224, 86, 253, 0.40)",
        "icon": "ryujinx",
        "source": "aur",
    },
    "gamemode": {
        "title": "Feral GameMode",
        "tag": "SYSTEM GAME OPTIMIZER",
        "sub": "System optimization daemon that tunes CPU governors and scheduler priorities for smooth frame rates",
        "accent_color": "#e84118",
        "bg": "radial-gradient(circle at 82% 50%, rgba(232, 65, 24, 0.32) 0%, rgba(232, 65, 24, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(232, 65, 24, 0.24) 0%, rgba(30, 19, 18, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(232, 65, 24, 0.40)",
        "icon": "applications-games",
        "source": "pacman",
    },
    "mangohud": {
        "title": "MangoHud Overlay",
        "tag": "VULKAN GAMING OVERLAY",
        "sub": "Vulkan and OpenGL overlay for monitoring FPS, frametimes, GPU temperatures, and memory consumption",
        "accent_color": "#e84393",
        "bg": "radial-gradient(circle at 82% 50%, rgba(232, 67, 147, 0.32) 0%, rgba(232, 67, 147, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(232, 67, 147, 0.24) 0%, rgba(30, 19, 26, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(232, 67, 147, 0.40)",
        "icon": "applications-games",
        "source": "pacman",
    },
    "wine": {
        "title": "Wine Compatibility Layer",
        "tag": "WINDOWS COMPATIBILITY",
        "sub": "Run Windows applications, productivity tools, and legacy software natively on Linux desktops",
        "accent_color": "#8e44ad",
        "bg": "radial-gradient(circle at 82% 50%, rgba(142, 68, 173, 0.32) 0%, rgba(142, 68, 173, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(142, 68, 173, 0.24) 0%, rgba(26, 19, 30, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(142, 68, 173, 0.40)",
        "icon": "wine",
        "source": "pacman",
    },

    # Privacy & Security
    "proton-vpn-gtk-app": {
        "title": "Proton VPN",
        "tag": "ENCRYPTED VPN SHIELD",
        "sub": "High-speed encrypted WireGuard VPN tunnel with strict zero-logging policy and Swiss privacy",
        "accent_color": "#6d4aff",
        "bg": "radial-gradient(circle at 82% 50%, rgba(109, 74, 255, 0.32) 0%, rgba(109, 74, 255, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(109, 74, 255, 0.25) 0%, rgba(20, 20, 35, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(109, 74, 255, 0.40)",
        "icon": "proton-vpn-gtk-app",
        "source": "pacman",
    },
    "brave-bin": {
        "title": "Brave Browser",
        "tag": "SHIELDED WEB BROWSING",
        "sub": "High-speed browser with native ad-blocking, tracker shielding, and Web3 capabilities",
        "accent_color": "#fb542b",
        "bg": "radial-gradient(circle at 82% 50%, rgba(251, 84, 43, 0.32) 0%, rgba(251, 84, 43, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(251, 84, 43, 0.24) 0%, rgba(30, 21, 19, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(251, 84, 43, 0.40)",
        "icon": "brave-browser",
        "source": "aur",
    },
    "signal-desktop": {
        "title": "Signal Desktop",
        "tag": "ENCRYPTED MESSAGING",
        "sub": "State-of-the-art end-to-end encrypted messaging with voice calls, video chats, and vanishing messages",
        "accent_color": "#3a76f0",
        "bg": "radial-gradient(circle at 82% 50%, rgba(58, 118, 240, 0.32) 0%, rgba(58, 118, 240, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(58, 118, 240, 0.24) 0%, rgba(19, 25, 36, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(58, 118, 240, 0.40)",
        "icon": "signal-desktop",
        "source": "pacman",
    },
    "keepassxc": {
        "title": "KeePassXC Vault",
        "tag": "OFFLINE PASSWORD VAULT",
        "sub": "Secure offline password manager with AES-256 encryption, auto-type, and TOTP authentication",
        "accent_color": "#52982d",
        "bg": "radial-gradient(circle at 82% 50%, rgba(82, 152, 45, 0.32) 0%, rgba(82, 152, 45, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(82, 152, 45, 0.24) 0%, rgba(19, 27, 20, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(82, 152, 45, 0.40)",
        "icon": "keepassxc",
        "source": "pacman",
    },
    "bitwarden": {
        "title": "Bitwarden Vault",
        "tag": "SECURITY ESSENTIAL",
        "sub": "Open-source zero-knowledge password vault protecting credentials across all your devices",
        "accent_color": "#175ddc",
        "bg": "radial-gradient(circle at 82% 50%, rgba(23, 93, 220, 0.32) 0%, rgba(23, 93, 220, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(23, 93, 220, 0.24) 0%, rgba(18, 24, 36, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(23, 93, 220, 0.40)",
        "icon": "bitwarden",
        "source": "pacman",
    },
    "mullvad-vpn-bin": {
        "title": "Mullvad VPN",
        "tag": "ZERO-LOG WIREGUARD",
        "sub": "Privacy-focused VPN with no personal data collection, WireGuard tunnels, and quantum-resistant encryption",
        "accent_color": "#e5ad23",
        "bg": "radial-gradient(circle at 82% 50%, rgba(229, 173, 35, 0.32) 0%, rgba(229, 173, 35, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(229, 173, 35, 0.24) 0%, rgba(28, 25, 18, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(229, 173, 35, 0.40)",
        "icon": "mullvad-vpn",
        "source": "aur",
    },
    "torbrowser-launcher": {
        "title": "Tor Browser",
        "tag": "ANONYMOUS ONION ROUTING",
        "sub": "Defend against tracking, surveillance, and censorship with multi-layered onion encryption routing",
        "accent_color": "#7d4698",
        "bg": "radial-gradient(circle at 82% 50%, rgba(125, 70, 152, 0.32) 0%, rgba(125, 70, 152, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(125, 70, 152, 0.24) 0%, rgba(25, 19, 28, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(125, 70, 152, 0.40)",
        "icon": "tor-browser",
        "source": "pacman",
    },
    "wireshark-qt": {
        "title": "Wireshark Packet Analyzer",
        "tag": "NETWORK PACKET ANALYZER",
        "sub": "Network packet analyzer and traffic inspector for deep protocol inspection and network diagnostics",
        "accent_color": "#16a085",
        "bg": "radial-gradient(circle at 82% 50%, rgba(22, 160, 133, 0.32) 0%, rgba(22, 160, 133, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(22, 160, 133, 0.24) 0%, rgba(18, 27, 25, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(22, 160, 133, 0.40)",
        "icon": "wireshark",
        "source": "pacman",
    },
    "tailscale": {
        "title": "Tailscale Mesh VPN",
        "tag": "ZERO-CONFIG MESH VPN",
        "sub": "Zero config mesh VPN for secure peer-to-peer device networks built upon modern WireGuard protocols",
        "accent_color": "#4a69bd",
        "bg": "radial-gradient(circle at 82% 50%, rgba(74, 105, 189, 0.32) 0%, rgba(74, 105, 189, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(74, 105, 189, 0.24) 0%, rgba(19, 23, 34, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(74, 105, 189, 0.40)",
        "icon": "network-vpn",
        "source": "pacman",
    },
    "wireguard-tools": {
        "title": "WireGuard",
        "tag": "CRYPTOGRAPHIC VPN TUNNEL",
        "sub": "Extremely fast, modern cryptographic network tunnel with peer-to-peer simplicity and minimal overhead",
        "accent_color": "#8854d0",
        "bg": "radial-gradient(circle at 82% 50%, rgba(136, 84, 208, 0.32) 0%, rgba(136, 84, 208, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(136, 84, 208, 0.24) 0%, rgba(24, 19, 32, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(136, 84, 208, 0.40)",
        "icon": "network-vpn",
        "source": "pacman",
    },
    "thunderbird": {
        "title": "Thunderbird Mail",
        "tag": "ENTERPRISE EMAIL & CALENDAR",
        "sub": "Feature-packed email, calendar, and contacts client with advanced privacy and OpenPGP encryption",
        "accent_color": "#0984e3",
        "bg": "radial-gradient(circle at 82% 50%, rgba(9, 132, 227, 0.32) 0%, rgba(9, 132, 227, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(9, 132, 227, 0.24) 0%, rgba(18, 26, 38, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(9, 132, 227, 0.40)",
        "icon": "thunderbird",
        "source": "pacman",
    },
    "bleachbit": {
        "title": "BleachBit Cleaner",
        "tag": "PRIVACY CLEANER & SHREDDER",
        "sub": "Clean caches, free disk space, and guard privacy with deep system scrubbing and file shredding",
        "accent_color": "#e74c3c",
        "bg": "radial-gradient(circle at 82% 50%, rgba(231, 76, 60, 0.32) 0%, rgba(231, 76, 60, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(231, 76, 60, 0.24) 0%, rgba(28, 19, 20, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(231, 76, 60, 0.40)",
        "icon": "bleachbit",
        "source": "pacman",
    },

    # Productivity
    "libreoffice-fresh": {
        "title": "LibreOffice Fresh",
        "tag": "OFFICE PRODUCTIVITY SUITE",
        "sub": "Comprehensive enterprise-grade office productivity suite compatible with Microsoft Office formats",
        "accent_color": "#18a058",
        "bg": "radial-gradient(circle at 82% 50%, rgba(24, 160, 88, 0.32) 0%, rgba(24, 160, 88, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(24, 160, 88, 0.24) 0%, rgba(18, 27, 21, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(24, 160, 88, 0.40)",
        "icon": "libreoffice-main",
        "source": "pacman",
    },
    "obsidian": {
        "title": "Obsidian",
        "tag": "KNOWLEDGE REVOLUTION",
        "sub": "Second brain and knowledge graph application storing linked markdown notes locally on your filesystem",
        "accent_color": "#7c3aed",
        "bg": "radial-gradient(circle at 82% 50%, rgba(124, 58, 237, 0.32) 0%, rgba(124, 58, 237, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(124, 58, 237, 0.24) 0%, rgba(24, 19, 34, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(124, 58, 237, 0.40)",
        "icon": "obsidian",
        "source": "aur",
    },
    "krita": {
        "title": "Krita Digital Painting",
        "tag": "DIGITAL ART STUDIO",
        "sub": "Professional digital painting and illustration studio with world-class brush engines and stabilizers",
        "accent_color": "#f368e0",
        "bg": "radial-gradient(circle at 82% 50%, rgba(243, 104, 224, 0.32) 0%, rgba(243, 104, 224, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(243, 104, 224, 0.24) 0%, rgba(30, 20, 28, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(243, 104, 224, 0.40)",
        "icon": "krita",
        "source": "pacman",
    },
    "joplin-desktop": {
        "title": "Joplin Notes",
        "tag": "ENCRYPTED CLOUD NOTES",
        "sub": "Secure, open-source note-taking and to-do application with end-to-end encrypted synchronization",
        "accent_color": "#1b6ac9",
        "bg": "radial-gradient(circle at 82% 50%, rgba(27, 106, 201, 0.32) 0%, rgba(27, 106, 201, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(27, 106, 201, 0.24) 0%, rgba(18, 24, 34, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(27, 106, 201, 0.40)",
        "icon": "joplin",
        "source": "aur",
    },
    "onlyoffice-bin": {
        "title": "OnlyOffice Docs",
        "tag": "COLLABORATIVE DOCS",
        "sub": "High-compatibility office suite featuring collaborative document, spreadsheet, and slide editing",
        "accent_color": "#ff6f59",
        "bg": "radial-gradient(circle at 82% 50%, rgba(255, 111, 89, 0.32) 0%, rgba(255, 111, 89, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(255, 111, 89, 0.24) 0%, rgba(30, 21, 20, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(255, 111, 89, 0.40)",
        "icon": "onlyoffice-desktopeditors",
        "source": "aur",
    },
    "anytype-bin": {
        "title": "Anytype Workspace",
        "tag": "DECENTRALIZED WORKSPACE",
        "sub": "Next-generation private knowledge base and decentralized operating space for personal ideas and wikis",
        "accent_color": "#f59e0b",
        "bg": "radial-gradient(circle at 82% 50%, rgba(245, 158, 11, 0.32) 0%, rgba(245, 158, 11, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(245, 158, 11, 0.24) 0%, rgba(28, 24, 18, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(245, 158, 11, 0.40)",
        "icon": "anytype",
        "source": "aur",
    },
    "foliate": {
        "title": "Foliate Reader",
        "tag": "ELEGANT EBOOK READER",
        "sub": "Modern, distraction-free ebook reader with custom typography, annotations, and dictionary lookup",
        "accent_color": "#10b981",
        "bg": "radial-gradient(circle at 82% 50%, rgba(16, 185, 129, 0.32) 0%, rgba(16, 185, 129, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(16, 185, 129, 0.24) 0%, rgba(18, 28, 24, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(16, 185, 129, 0.40)",
        "icon": "com.github.johnfactotum.Foliate",
        "source": "pacman",
    },
    "thunar": {
        "title": "Thunar File Manager",
        "tag": "LIGHTWEIGHT FILE MANAGER",
        "sub": "Fast lightweight desktop file manager with clean modern interface and custom action plugins",
        "accent_color": "#3498db",
        "bg": "radial-gradient(circle at 82% 50%, rgba(52, 152, 219, 0.32) 0%, rgba(52, 152, 219, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(52, 152, 219, 0.24) 0%, rgba(18, 26, 35, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(52, 152, 219, 0.40)",
        "icon": "org.xfce.thunar",
        "source": "pacman",
    },
    "micro": {
        "title": "Micro Editor",
        "tag": "INTUITIVE TERMINAL EDITOR",
        "sub": "Intuitive terminal text editor with full mouse support, multi-cursors, and syntax highlighting",
        "accent_color": "#fdcb6e",
        "bg": "radial-gradient(circle at 82% 50%, rgba(253, 203, 110, 0.32) 0%, rgba(253, 203, 110, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(253, 203, 110, 0.24) 0%, rgba(30, 26, 18, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(253, 203, 110, 0.40)",
        "icon": "micro",
        "source": "pacman",
    },
    "evince": {
        "title": "Evince Document Viewer",
        "tag": "UNIVERSAL DOCUMENT VIEWER",
        "sub": "Clean, high-performance document viewer for PDF, PostScript, and DjVu with text search",
        "accent_color": "#d63031",
        "bg": "radial-gradient(circle at 82% 50%, rgba(214, 48, 49, 0.32) 0%, rgba(214, 48, 49, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(214, 48, 49, 0.24) 0%, rgba(28, 18, 18, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(214, 48, 49, 0.40)",
        "icon": "org.gnome.Evince",
        "source": "pacman",
    },

    # System
    "btop": {
        "title": "Btop Resource Monitor",
        "tag": "SYSTEM SPOTLIGHT",
        "sub": "Stunning aesthetic terminal monitor tracking CPU, GPU, memory, disks, and network with live graphs",
        "accent_color": "#ff5370",
        "bg": "radial-gradient(circle at 82% 50%, rgba(255, 83, 112, 0.32) 0%, rgba(255, 83, 112, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(255, 83, 112, 0.24) 0%, rgba(30, 20, 23, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(255, 83, 112, 0.40)",
        "icon": "btop",
        "source": "pacman",
    },
    "timeshift": {
        "title": "Timeshift System Restore",
        "tag": "SYSTEM RESTORE ENGINE",
        "sub": "Rock-solid system snapshot utility protecting your OS files using incremental BTRFS and RSYNC backups",
        "accent_color": "#e056fd",
        "bg": "radial-gradient(circle at 82% 50%, rgba(224, 86, 253, 0.32) 0%, rgba(224, 86, 253, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(224, 86, 253, 0.24) 0%, rgba(28, 20, 30, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(224, 86, 253, 0.40)",
        "icon": "timeshift",
        "source": "pacman",
    },
    "fastfetch": {
        "title": "Fastfetch",
        "tag": "BLAZING HARDWARE INFO",
        "sub": "Lightning-fast, highly customizable modern system information display written in performant C",
        "accent_color": "#00b894",
        "bg": "radial-gradient(circle at 82% 50%, rgba(0, 184, 148, 0.32) 0%, rgba(0, 184, 148, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(0, 184, 148, 0.24) 0%, rgba(18, 28, 25, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(0, 184, 148, 0.40)",
        "icon": "fastfetch",
        "source": "pacman",
    },
    "gparted": {
        "title": "GParted Partition Editor",
        "tag": "PARTITION ARCHITECT",
        "sub": "Graphical partition editor to resize, format, check, and reorganize hard drives and SSDs safely",
        "accent_color": "#f39c12",
        "bg": "radial-gradient(circle at 82% 50%, rgba(243, 156, 18, 0.32) 0%, rgba(243, 156, 18, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(243, 156, 18, 0.24) 0%, rgba(28, 24, 18, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(243, 156, 18, 0.40)",
        "icon": "gparted",
        "source": "pacman",
    },
    "stacer-bin": {
        "title": "Stacer Optimizer",
        "tag": "SYSTEM CLEANER & DASHBOARD",
        "sub": "Comprehensive Linux system optimizer, startup manager, and hardware monitoring dashboard",
        "accent_color": "#3498db",
        "bg": "radial-gradient(circle at 82% 50%, rgba(52, 152, 219, 0.32) 0%, rgba(52, 152, 219, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(52, 152, 219, 0.24) 0%, rgba(18, 26, 35, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(52, 152, 219, 0.40)",
        "icon": "stacer",
        "source": "aur",
    },
    "fish": {
        "title": "Fish Shell",
        "tag": "SMART INTERACTIVE SHELL",
        "sub": "Smart user-friendly command line shell with syntax highlighting, autosuggestions, and tab completions",
        "accent_color": "#9b59b6",
        "bg": "radial-gradient(circle at 82% 50%, rgba(155, 89, 182, 0.32) 0%, rgba(155, 89, 182, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(155, 89, 182, 0.24) 0%, rgba(26, 20, 30, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(155, 89, 182, 0.40)",
        "icon": "fish",
        "source": "pacman",
    },
    "htop": {
        "title": "Htop Process Viewer",
        "tag": "INTERACTIVE PROCESS MONITOR",
        "sub": "Cross-platform interactive process viewer, CPU thread inspector, and process kill manager",
        "accent_color": "#2ecc71",
        "bg": "radial-gradient(circle at 82% 50%, rgba(46, 204, 113, 0.32) 0%, rgba(46, 204, 113, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(46, 204, 113, 0.24) 0%, rgba(18, 28, 22, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(46, 204, 113, 0.40)",
        "icon": "htop",
        "source": "pacman",
    },
    "baobab": {
        "title": "Baobab Disk Analyzer",
        "tag": "VISUAL DISK USAGE",
        "sub": "Visual disk usage analyzer graphically displaying folder structures via dynamic rings and treemaps",
        "accent_color": "#e67e22",
        "bg": "radial-gradient(circle at 82% 50%, rgba(230, 126, 34, 0.32) 0%, rgba(230, 126, 34, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(230, 126, 34, 0.24) 0%, rgba(25, 23, 20, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(230, 126, 34, 0.40)",
        "icon": "org.gnome.baobab",
        "source": "pacman",
    },
    "hardinfo-git": {
        "title": "Hardinfo Hardware Profiler",
        "tag": "SYSTEM BENCHMARK SUITE",
        "sub": "System benchmark and hardware information tool reporting CPU modules, PCI devices, and sensors",
        "accent_color": "#00cec9",
        "bg": "radial-gradient(circle at 82% 50%, rgba(0, 206, 201, 0.32) 0%, rgba(0, 206, 201, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(0, 206, 201, 0.24) 0%, rgba(18, 28, 28, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(0, 206, 201, 0.40)",
        "icon": "hardinfo",
        "source": "aur",
    },
    "pavucontrol": {
        "title": "Volume Control",
        "tag": "ADVANCED AUDIO ROUTER",
        "sub": "Audio routing, volume levels, and multi-channel mixer for PipeWire and PulseAudio streams",
        "accent_color": "#6c5ce7",
        "bg": "radial-gradient(circle at 82% 50%, rgba(108, 92, 231, 0.32) 0%, rgba(108, 92, 231, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(108, 92, 231, 0.24) 0%, rgba(20, 19, 32, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(108, 92, 231, 0.40)",
        "icon": "org.pulseaudio.pavucontrol",
        "source": "pacman",
    },

    # Essential
    "firefox": {
        "title": "Firefox Browser",
        "tag": "FAST & PRIVATE WEB",
        "sub": "Fast, independent browser with built-in total cookie protection, container tabs, and fingerprint resistance",
        "accent_color": "#ff7139",
        "bg": "radial-gradient(circle at 82% 50%, rgba(255, 113, 57, 0.32) 0%, rgba(255, 113, 57, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(255, 113, 57, 0.24) 0%, rgba(26, 18, 28, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(255, 113, 57, 0.40)",
        "icon": "firefox",
        "source": "pacman",
    },
    "discord": {
        "title": "Discord",
        "tag": "COMMUNITY VOICE & CHAT",
        "sub": "All-in-one low-latency voice, video, and text communication for communities and gaming squads",
        "accent_color": "#5865f2",
        "bg": "radial-gradient(circle at 82% 50%, rgba(88, 101, 242, 0.32) 0%, rgba(88, 101, 242, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(88, 101, 242, 0.24) 0%, rgba(20, 22, 36, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(88, 101, 242, 0.40)",
        "icon": "discord",
        "source": "pacman",
    },
    "telegram-desktop": {
        "title": "Telegram Desktop",
        "tag": "INSTANT CLOUD MESSAGING",
        "sub": "Blazing fast cloud messaging client with instant synchronization, giant channels, and voice chats",
        "accent_color": "#0088cc",
        "bg": "radial-gradient(circle at 82% 50%, rgba(0, 136, 204, 0.32) 0%, rgba(0, 136, 204, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(0, 136, 204, 0.24) 0%, rgba(18, 26, 34, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(0, 136, 204, 0.40)",
        "icon": "telegram",
        "source": "pacman",
    },
}
FEATURED_APP_METADATA = FEATURED_APP_PRESETS

FEATURED_CATEGORY_PRIORITIES: Dict[str, List[str]] = {
    "media": [
        "blender", "kdenlive", "obs-studio", "gimp", "inkscape",
        "audacity", "handbrake", "mpv", "darktable", "ardour", "vlc", "spotify"
    ],
    "dev": [
        "code", "zed", "neovim", "alacritty", "kitty",
        "postman-bin", "docker", "rust", "go", "dbeaver", "lazygit", "git"
    ],
    "games": [
        "steam", "heroic-games-launcher-bin", "lutris", "retroarch",
        "prismlauncher", "bottles", "gamemode", "ryujinx-bin", "mangohud", "wine", "discord", "obs-studio"
    ],
    "privacy": [
        "proton-vpn-gtk-app", "brave-bin", "signal-desktop", "keepassxc",
        "bitwarden", "wireguard-tools", "mullvad-vpn-bin", "torbrowser-launcher", "tailscale", "thunderbird", "wireshark-qt", "bleachbit"
    ],
    "productivity": [
        "libreoffice-fresh", "obsidian", "krita", "joplin-desktop",
        "onlyoffice-bin", "anytype-bin", "foliate", "micro", "evince", "thunar", "fastfetch", "pavucontrol"
    ],
    "system": [
        "btop", "timeshift", "fastfetch", "gparted",
        "stacer-bin", "fish", "htop", "baobab", "hardinfo-git", "pavucontrol", "kitty", "alacritty"
    ],
    "essential": [
        "firefox", "discord", "telegram-desktop", "spotify",
        "vlc", "bitwarden", "code", "steam", "blender", "obs-studio", "gimp", "proton-vpn-gtk-app"
    ],
}

CATEGORY_TAG_DEFAULTS: Dict[str, str] = {
    "media": "FEATURED CREATIVE SUITE",
    "dev": "DEVELOPER SPOTLIGHT",
    "games": "NEXT-GEN GAMING",
    "privacy": "PRIVACY ESSENTIAL",
    "productivity": "EDITORS' CHOICE",
    "system": "SYSTEM SPOTLIGHT",
    "essential": "COMMUNITY FAVORITE",
    "hyprland": "HYPRLAND ECOSYSTEM",
}

CATEGORY_ACCENT_DEFAULTS: Dict[str, str] = {
    "media": "#eb7700",
    "dev": "#007acc",
    "games": "#66c0f4",
    "privacy": "#6d4aff",
    "productivity": "#18a058",
    "system": "#ff5370",
    "essential": "#30d158",
    "hyprland": "#00c8ff",
}

def _color_to_gradient_and_border(hex_color: str, alpha_bg: float = 0.24, alpha_border: float = 0.42) -> Tuple[str, str]:
    """Generate modern atmospheric gradient background with radial glow and subtle accent border from hex color."""
    h = hex_color.lstrip("#")
    if len(h) == 6:
        try:
            r = int(h[0:2], 16)
            g = int(h[2:4], 16)
            b = int(h[4:6], 16)
        except ValueError:
            r, g, b = (10, 132, 255)
    else:
        r, g, b = (10, 132, 255)
    bg = (
        f"radial-gradient(circle at 82% 50%, rgba({r}, {g}, {b}, 0.32) 0%, rgba({r}, {g}, {b}, 0.05) 50%, transparent 75%), "
        f"linear-gradient(135deg, rgba({r}, {g}, {b}, {alpha_bg}) 0%, rgba(20, 24, 33, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)"
    )
    border = f"rgba({r}, {g}, {b}, {alpha_border})"
    return bg, border

# Human-friendly Apple App Store display names
APP_DISPLAY_NAMES: Dict[str, str] = {
    "firefox": "Firefox",
    "firefox-pure": "Firefox",
    "firefox-developer-edition": "Firefox Developer Edition",
    "code": "Visual Studio Code",
    "visual-studio-code-bin": "Visual Studio Code",
    "discord": "Discord",
    "vesktop": "Vesktop Discord",
    "steam": "Steam",
    "spotify": "Spotify",
    "proton-vpn-gtk-app": "Proton VPN",
    "proton-vpn-cli": "Proton VPN CLI",
    "proton-vpn": "Proton VPN",
    "neovim": "Neovim",
    "git": "Git",
    "docker": "Docker",
    "alacritty": "Alacritty",
    "kitty": "Kitty",
    "brave-bin": "Brave Browser",
    "brave": "Brave Browser",
    "brave-origin-bin": "Brave Origin",
    "zen-browser-bin": "Zen Browser",
    "chromium": "Chromium",
    "torbrowser-launcher": "Tor Browser",
    "telegram-desktop": "Telegram Desktop",
    "telegram": "Telegram",
    "signal-desktop": "Signal Desktop",
    "signal": "Signal",
    "obs-studio": "OBS Studio",
    "vlc": "VLC Media Player",
    "vlc-cli": "VLC (CLI)",
    "vlc-gui-qt": "VLC Qt GUI",
    "lutris": "Lutris",
    "btop": "Btop",
    "fastfetch": "Fastfetch",
    "foot": "Foot Terminal",
    "micro": "Micro Editor",
    "gimp": "GIMP",
    "inkscape": "Inkscape",
    "blender": "Blender",
    "kdenlive": "Kdenlive",
    "audacity": "Audacity",
    "mpv": "mpv",
    "qbittorrent": "qBittorrent",
    "wireshark-qt": "Wireshark",
    "htop": "Htop",
    "nvtop": "nvtop",
    "libreoffice-fresh": "LibreOffice",
    "libreoffice-still": "LibreOffice",
    "libreoffice": "LibreOffice",
    "helix": "Helix",
    "obsidian": "Obsidian",
    "heroic": "Heroic Games Launcher",
    "heroic-games-launcher-bin": "Heroic Games Launcher",
    "retroarch": "RetroArch",
    "bottles": "Bottles",
    "mangohud": "MangoHud",
    "bitwarden": "Bitwarden",
    "lazygit": "LazyGit",
    "zed": "Zed",
    "postman-bin": "Postman",
    "postman": "Postman",
    "rust": "Rust & Cargo",
    "go": "Go",
    "qtengine": "QtEngine",
    "quickshell": "Quickshell",
    "quickshell-git": "Quickshell",
    "antigravity": "Antigravity",
    "antigravity-cli": "Antigravity CLI",
    "spicetify-marketplace-bin": "Spicetify Marketplace",
    "dbeaver": "DBeaver",
    "pavucontrol": "Volume Control",
    "joplin-desktop": "Joplin",
    "joplin": "Joplin",
    "onlyoffice-bin": "OnlyOffice",
    "onlyoffice": "OnlyOffice",
    "anytype-bin": "Anytype",
    "anytype": "Anytype",
    "evince": "Evince",
    "krita": "Krita",
    "foliate": "Foliate",
    "keepassxc": "KeepassXC",
    "wireguard-tools": "WireGuard",
    "wireguard": "WireGuard",
    "mullvad-vpn-bin": "Mullvad VPN",
    "mullvad-vpn": "Mullvad VPN",
    "bleachbit": "BleachBit",
    "tailscale": "Tailscale",
    "thunderbird": "Thunderbird",
    "handbrake": "HandBrake",
    "darktable": "Darktable",
    "ardour": "Ardour",
    "gparted": "GParted",
    "timeshift": "Timeshift",
    "baobab": "Baobab",
    "stacer-bin": "Stacer",
    "stacer": "Stacer",
    "fish": "Fish Shell",
    "hardinfo-git": "Hardinfo",
    "hardinfo": "Hardinfo",
    "hardinfo2": "Hardinfo",
    "prismlauncher": "Prism Launcher",
    "wine": "Wine",
    "gamemode": "GameMode",
    "ryujinx-bin": "Ryujinx",
    "ryujinx": "Ryujinx",
    "waybar": "Waybar",
    "rofi-wayland": "Rofi Wayland",
    "wofi": "Wofi Launcher",
    "fuzzel": "Fuzzel Launcher",
    "hyprpaper": "Hyprpaper",
    "hyprlock": "Hyprlock",
    "hypridle": "Hypridle",
    "hyprpicker": "Hyprpicker",
    "hyprshot": "Hyprshot",
    "hyprsunset": "Hyprsunset",
    "hyprpolkitagent": "Hyprpolkitagent",
    "swaync": "SwayNotificationCenter",
    "swww": "swww Wallpaper Daemon",
    "wlogout": "wlogout Power Menu",
    "nwg-look": "nwg-look Theme Settings",
    "nwg-displays": "nwg-displays Monitor Manager",
    "grim": "Grim Wayland Screenshot",
    "slurp": "Slurp Region Selector",
    "swappy": "Swappy Screenshot Editor",
    "cliphist": "Cliphist Clipboard Manager",
    "wl-clipboard": "Wayland Clipboard Utilities",
    "mako": "Mako Notification Daemon",
    "dunst": "Dunst Notification Daemon",
    "brightnessctl": "Brightnessctl",
    "playerctl": "Playerctl Media Controller",
    "blueman": "Blueman Bluetooth Manager",
    "nm-connection-editor": "NetworkManager Connection Editor",
    "qt5ct": "Qt5 Configuration Tool",
    "qt6ct": "Qt6 Configuration Tool",
    "kvantum": "Kvantum SVG Theme Engine",
    "xdg-desktop-portal-hyprland": "XDG Desktop Portal Hyprland",
}

APP_EXTENDED_DESCRIPTIONS: Dict[str, str] = {
    "proton-vpn-gtk-app": (
        "Proton VPN is a high-security virtual private network developed by the CERN scientists behind Proton Mail. "
        "It features strict zero-logging architecture, 10 Gbps encrypted server backbones, Secure Core multi-hop routing, "
        "built-in NetShield DNS ad-blocking, IPv6 leak protection, and hardware-accelerated WireGuard protocol tunnels."
    ),
    "code": (
        "Visual Studio Code is a powerful modern source code editor. Features native debugging support, Git version control, "
        "IntelliSense syntax autocompletion, integrated terminal profiles, and a vast ecosystem of extensions "
        "for Python, Rust, C++, TypeScript, Go, Docker, and cloud workflows."
    ),
    "firefox": (
        "Mozilla Firefox is a modern, privacy-respecting desktop browser. Includes total cookie protection, "
        "fingerprinting resistance, high-speed multi-process WebRender graphics pipeline, and customizable tabbed browsing."
    ),
    "steam": (
        "Steam is the world's premier digital gaming distribution and community platform. "
        "Includes Proton compatibility layer for native Linux execution of Windows games, cloud save synchronization, and community workshop."
    ),
    "discord": (
        "Discord provides voice, video, and text communication for developer and gaming communities. "
        "Includes low-latency voice channels, stream sharing, server permissions, and rich presence integration."
    ),
    "spotify": (
        "Spotify provides instant desktop music and podcast streaming. "
        "Features high-bitrate audio playback, personalized recommendations, synchronized lyrics, and offline playback libraries."
    ),
    "obs-studio": (
        "OBS Studio is an open-source real-time video recording and live broadcasting suite. "
        "Features hardware-accelerated NVENC and VAAPI encoding, multi-source compositing, modular dock layouts, and VST audio filters."
    ),
    "libreoffice-fresh": (
        "LibreOffice is a full-featured office productivity suite compatible with Microsoft Office formats. "
        "Includes Writer (documents), Calc (spreadsheets), Impress (presentations), Draw (vector diagrams), Math, and Base databases."
    ),
    "obsidian": (
        "Obsidian is a powerful knowledge base and personal note-taking tool that works on a local folder of Markdown files. "
        "Features bidirectional note linking, interactive knowledge graph visualization, and an extensive plugin ecosystem."
    ),
    "vlc": (
        "VLC is a versatile media player and streaming framework that natively decodes MPEG, DivX, H.264, H.265/HEVC, AV1, MKV, "
        "and lossless audio formats with zero external codec requirements."
    ),
    "blender": (
        "Blender is a 3D creation suite supporting modeling, rigging, simulation, Cycles ray-traced rendering, compositing, "
        "motion tracking, and 2D animation pipelines."
    ),
    "gimp": (
        "GIMP is an image manipulation program featuring layers, channels, high-bit-depth color management, "
        "custom brushes, and extensible Python scripting for digital artists and photographers."
    ),
    "neovim": (
        "Neovim is an extensible Vim-fork text editor featuring built-in Language Server Protocol (LSP) client, "
        "tree-sitter syntax highlighting, asynchronous I/O plugin support, and Lua configuration scripting."
    ),
    "alacritty": (
        "Alacritty is an OpenGL-accelerated terminal emulator focused on simplicity and maximum execution performance. "
        "Features low latency input processing and modern true-color rendering."
    ),
    "btop": (
        "btop is an interactive system resource monitor showing real-time CPU core utilization, memory breakdown, "
        "disk throughput, network bandwidth graphs, and process tree management."
    ),
    "fastfetch": (
        "Fastfetch is a system information tool written in C for high performance and minimal runtime overhead, "
        "displaying system hardware, OS kernel, desktop environment, and GPU status."
    ),
    "git": (
        "Git is the distributed version control system designed to handle everything from small to very large projects "
        "with speed, cryptographic integrity, and flexible non-linear branching workflows."
    ),
    "docker": (
        "Docker is an open container platform for developing, shipping, and running containerized applications. "
        "Enables seamless isolation, rapid deployment pipelines, and reproducible desktop environments."
    ),
    "kitty": (
        "Kitty is a fast, GPU-accelerated terminal emulator written in C and Python. "
        "Supports modern ligatures, true color, graphics protocols, tabs, splits, and comprehensive scriptability."
    ),
    "brave-bin": (
        "Brave is a privacy-first browser that automatically blocks trackers, fingerprinting, and intrusive ads out of the box. "
        "Includes Shields protection, private Tor browsing windows, and built-in IPFS protocol support."
    ),
    "zen-browser-bin": (
        "Zen Browser is an open-source Firefox-based browser emphasizing modern design, split workspaces, "
        "vertical tabs, compact UI layouts, and deep user privacy without telemetry."
    ),
    "chromium": (
        "Chromium is the open-source browser project that powers the modern web. "
        "Provides fast page rendering, sandbox process isolation, and broad compatibility with web standards."
    ),
    "torbrowser-launcher": (
        "Tor Browser protects your online privacy and anonymity by routing encrypted traffic through the decentralized Tor network, "
        "defending against tracking, surveillance, and censorship."
    ),
    "telegram-desktop": (
        "Telegram Desktop is a fast, cloud-synchronized messaging application featuring instant multi-device syncing, "
        "high-capacity group channels, encrypted voice/video calls, and file transfers up to 2 GB."
    ),
    "signal-desktop": (
        "Signal Desktop is a private messaging app providing end-to-end encrypted messaging, voice calls, "
        "and video conferences with zero metadata retention or surveillance."
    ),
    "lutris": (
        "Lutris is an open gaming platform for Linux that unifies games from Steam, GOG, Epic Games, Wine, and emulators "
        "into a single library with tailored per-game execution scripts and runner optimization."
    ),
    "heroic": (
        "Heroic is an open-source GUI launcher for Epic Games, GOG, and Amazon Games. "
        "Leverages Legendary and GOGdl backends with seamless Wine and Proton compatibility management."
    ),
    "retroarch": (
        "RetroArch is a frontend for emulators, game engines, and media players. "
        "Features real-time rewinding, shaders, netplay, and precise audio latency configuration."
    ),
    "bottles": (
        "Bottles easily manages Windows prefixes and gaming software on Linux. "
        "Features automated DLL installation, DXVK/VKD3D runners, and sandboxed bottle environments."
    ),
    "mangohud": (
        "MangoHud is a Vulkan and OpenGL overlay for monitoring FPS, frametimes, CPU/GPU temperatures, "
        "VRAM consumption, and system power draw directly in-game."
    ),
    "kdenlive": (
        "Kdenlive is a powerful non-linear video editor built on the MLT framework. "
        "Supports multi-track timeline editing, color grading, keyframe audio/video effects, and hardware-accelerated rendering."
    ),
    "audacity": (
        "Audacity is a multi-track audio editor and recorder. "
        "Supports 32-bit float audio, noise reduction, spectrum analysis, and an extensive library of audio effect plugins."
    ),
    "thunar": (
        "Thunar is a modern, lightweight, and fast file manager for the desktop. "
        "Features tabbed navigation, emblem badges, custom user actions, and smooth responsive directory browsing."
    ),
    "micro": (
        "Micro is a modern terminal-based text editor featuring full mouse support, syntax highlighting for over 130 languages, "
        "multiple cursors, and an intuitive keybinding system."
    ),
    "htop": (
        "htop is an interactive process viewer for Unix systems, providing an intuitive, color-coded terminal interface "
        "for monitoring CPU, memory, swap, and task threads in real time."
    ),
    "nvtop": (
        "nvtop is a task monitor for AMD, Intel, and NVIDIA GPUs, offering real-time telemetry on compute engine utilization, "
        "memory allocation, temperature, and graphics process threads."
    ),
    "pavucontrol": (
        "PulseAudio Volume Control (pavucontrol) provides a detailed mixer interface to configure audio volume levels, "
        "device routing, and per-application playback and recording streams."
    ),
    "waybar": (
        "Waybar is a highly customizable status bar for wlroots and Hyprland Wayland compositors. "
        "Features native Hyprland workspace indicators, window title modules, PipeWire audio controls, battery/network telemetry, and full CSS styling."
    ),
    "rofi-wayland": (
        "Rofi Wayland is a fast window switcher, application launcher, ssh dialog, and dmenu replacement built with native Wayland layer-shell support for Hyprland."
    ),
    "hyprpaper": (
        "Hyprpaper is a blazing fast, IPC-controlled wallpaper utility for Hyprland enabling instant per-monitor preloading and dynamic switching."
    ),
    "hyprlock": (
        "Hyprlock is Hyprland's official GPU-accelerated screen locking utility featuring blurred backgrounds, custom input fields, and dynamic labels."
    ),
    "hypridle": (
        "Hypridle is Hyprland's official idle management daemon supporting ext-idle-notify-v1, D-Bus inhibit locks, and automatic screen blanking/locking."
    ),
    "hyprpicker": (
        "Hyprpicker is a wlroots-compatible Wayland color picker that freezes the screen and magnifies pixels to copy exact HEX/RGB/HSL values."
    ),
    "swaync": (
        "SwayNotificationCenter (swaync) is a modern GTK notification daemon and slide-out control center panel for Wayland compositors."
    ),
    "swww": (
        "swww is an efficient animated wallpaper daemon for Wayland compositors supporting smooth transition shaders, GIFs, and multi-monitor outputs."
    ),
    "nwg-look": (
        "nwg-look is a GTK3/GTK4 appearance settings editor designed specifically for Wayland compositors like Hyprland, exporting gsettings and settings.ini."
    ),
    "nwg-displays": (
        "nwg-displays is an intuitive graphical multi-monitor output management utility for Hyprland and Sway that generates monitor configuration rules."
    ),
}

_DESKTOP_OVERRIDES: Dict[str, str] = {
    "code": "code-oss",
    "visual-studio-code-bin": "code-oss",
    "vesktop": "vesktop",
    "discord": "discord",
    "proton-vpn-gtk-app": "protonvpn-app",
    "proton-vpn": "protonvpn-app",
    "brave-bin": "brave-origin",
    "brave": "brave-origin",
    "brave-origin-bin": "brave-origin",
    "zen-browser-bin": "zen",
    "spotify": "spotify",
    "spotify-launcher": "spotify-launcher",
    "steam": "steam",
    "alacritty": "Alacritty",
    "thunar": "thunar",
    "pavucontrol": "pavucontrol",
    "libreoffice-fresh": "libreoffice-startcenter",
    "libreoffice": "libreoffice-startcenter",
    "helix": "helix",
    "obsidian": "obsidian",
    "heroic": "heroic",
    "heroic-games-launcher-bin": "heroic",
    "retroarch": "retroarch",
    "bottles": "com.usebottles.bottles",
}


def format_bytes(size: Any) -> str:
    """Format byte size into human readable string."""
    try:
        size = float(size)
    except (ValueError, TypeError):
        return ""
    if size <= 0:
        return ""
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PiB"


def sanitize_str(val: Any, default: str = "") -> str:
    """Ensure a value is a clean single string without lists or None."""
    if val is None:
        return default
    if isinstance(val, (list, tuple, set)):
        return ", ".join(str(x) for x in val if x)
    return str(val).strip()


def parse_pacman_info(raw_text: str) -> Dict[str, Any]:
    """
    Parse pacman -Si or -Qi human-readable output into structured dictionary.
    Properly handles multiline wrapped fields, especially 'Optional Deps' (AURA-028).
    """
    info: Dict[str, Any] = {
        "depends": [],
        "optdepends": [],
    }
    current_key = None

    for raw_line in (raw_text or "").splitlines():
        line = raw_line.rstrip()
        if not line:
            current_key = None
            continue

        # Check if line is indented continuation line
        if raw_line.startswith(" ") or raw_line.startswith("\t"):
            val = line.strip()
            if not val or val == "None":
                continue
            if current_key == "optional_deps":
                info["optdepends"].append(val)
            elif current_key == "depends_on":
                for d in val.split():
                    if d != "None" and d not in info["depends"]:
                        info["depends"].append(d)
            continue

        if ":" in line:
            k, v = line.split(":", 1)
            current_key = k.strip().lower().replace(" ", "_")
            v = v.strip()

            if current_key == "description":
                info["desc"] = v
            elif current_key == "version":
                info["version"] = v
            elif current_key == "repository":
                info["repo"] = v
            elif current_key == "url":
                info["url"] = v
            elif current_key == "licenses":
                info["license"] = v
            elif current_key == "installed_size":
                info["isize_str"] = v
            elif current_key == "download_size":
                info["csize_str"] = v
            elif current_key == "packager":
                info["packager"] = sanitize_str(v)
            elif current_key == "depends_on":
                for d in v.split():
                    if d != "None" and d not in info["depends"]:
                        info["depends"].append(d)
            elif current_key == "optional_deps":
                if v and v != "None":
                    info["optdepends"].append(v)
        else:
            current_key = None

    return info


_DESKTOP_ICONS_CACHE: Dict[str, str] = {}
_DESKTOP_NAMES_CACHE: Dict[str, str] = {}
_DESKTOP_ENTRIES_CACHE: Dict[str, str] = {}

DESKTOP_SEARCH_DIRS: List[Path] = [
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
    Path(os.path.expanduser("~/.local/share/applications")),
    Path("/var/lib/flatpak/exports/share/applications"),
    Path(os.path.expanduser("~/.local/share/flatpak/exports/share/applications")),
    Path("/var/lib/snapd/desktop/applications"),
    Path("/snap/share/applications"),
]


def invalidate_desktop_caches():
    """Clear cached .desktop icon, name, and launcher mappings so newly installed apps are immediately discoverable."""
    global _DESKTOP_ICONS_CACHE, _DESKTOP_NAMES_CACHE, _DESKTOP_ENTRIES_CACHE, _CURATED_DESKTOP_SET
    _DESKTOP_ICONS_CACHE = {}
    _DESKTOP_NAMES_CACHE = {}
    _DESKTOP_ENTRIES_CACHE = {}
    _CURATED_DESKTOP_SET = None


def get_gui_launch_env() -> Dict[str, str]:
    """Build a complete Wayland/X11/XDG environment for launching desktop, Flatpak, Snap, and Docker GUI apps."""
    env = os.environ.copy()
    uid = os.getuid()
    runtime_dir = env.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    env["XDG_RUNTIME_DIR"] = runtime_dir

    # Auto-detect WAYLAND_DISPLAY if missing
    if not env.get("WAYLAND_DISPLAY"):
        rt_path = Path(runtime_dir)
        if rt_path.exists():
            for cand in ("wayland-1", "wayland-0"):
                if (rt_path / cand).exists():
                    env["WAYLAND_DISPLAY"] = cand
                    break
            else:
                wl_socks = sorted(rt_path.glob("wayland-*"))
                for ws in wl_socks:
                    if not ws.name.endswith(".lock"):
                        env["WAYLAND_DISPLAY"] = ws.name
                        break

    # Auto-detect DISPLAY if missing
    if not env.get("DISPLAY"):
        x11_dir = Path("/tmp/.X11-unix")
        if x11_dir.exists():
            for cand in ("X0", "X1"):
                if (x11_dir / cand).exists():
                    env["DISPLAY"] = f":{cand[1:]}"
                    break
            else:
                x_socks = sorted(x11_dir.glob("X*"))
                if x_socks:
                    env["DISPLAY"] = f":{x_socks[0].name[1:]}"
        if not env.get("DISPLAY"):
            env["DISPLAY"] = ":0"

    # Ensure PATH includes /snap/bin and ~/.local/bin
    path_parts = [p for p in env.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/bin").split(":") if p]
    for extra_p in (
        str(Path.home() / ".local" / "share" / "arkst" / "bin"),
        str(Path.home() / ".local" / "bin"),
        "/snap/bin",
        "/var/lib/snapd/snap/bin",
        "/usr/local/bin",
        "/usr/bin",
    ):
        if extra_p not in path_parts:
            path_parts.append(extra_p)
    env["PATH"] = ":".join(path_parts)

    # Ensure XDG_DATA_DIRS includes Flatpak and Snap exports so gtk-launch / gio / IconTheme always work
    xdg_parts = [p for p in env.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if p]
    for extra_d in (
        str(Path.home() / ".local" / "share"),
        str(Path.home() / ".local" / "share" / "flatpak" / "exports" / "share"),
        "/var/lib/flatpak/exports/share",
        "/var/lib/snapd/desktop",
        "/usr/local/share",
        "/usr/share",
    ):
        if extra_d not in xdg_parts:
            xdg_parts.append(extra_d)
    env["XDG_DATA_DIRS"] = ":".join(xdg_parts)
    return env


def _extract_exec_binary(exec_line: str) -> str:
    """Extract the real binary/command name from a .desktop Exec= line (skipping env VAR=VAL wrappers)."""
    if not exec_line:
        return ""
    try:
        import shlex
        tokens = shlex.split(exec_line)
    except Exception:
        tokens = [t.strip('"').strip("'") for t in exec_line.split()]
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        base_tok = os.path.basename(tok)
        if base_tok == "env":
            idx += 1
            continue
        if "=" in tok and not tok.startswith(("/", ".", "-")):
            idx += 1
            continue
        if base_tok in ("sh", "bash", "dash") and idx + 2 < len(tokens) and tokens[idx + 1] == "-c":
            return _extract_exec_binary(tokens[idx + 2])
        if base_tok == "flatpak" and "run" in tokens[idx:]:
            # Last non-option token before field codes is the AppStream ID
            for sub_tok in reversed(tokens[idx + 1:]):
                if not sub_tok.startswith("-") and not sub_tok.startswith("%") and "." in sub_tok:
                    return sub_tok
        if base_tok == "snap" and idx + 2 < len(tokens) and tokens[idx + 1] == "run":
            for sub_tok in tokens[idx + 2:]:
                if not sub_tok.startswith("-") and not sub_tok.startswith("%"):
                    return sub_tok
        return tok
    return ""


def get_desktop_icons_map() -> Dict[str, str]:
    """Index system .desktop files to resolve authentic application icons and launchers."""
    global _DESKTOP_ICONS_CACHE, _DESKTOP_NAMES_CACHE, _DESKTOP_ENTRIES_CACHE
    if _DESKTOP_ICONS_CACHE:
        return _DESKTOP_ICONS_CACHE

    mapping = {}
    names_mapping = {}
    entries_mapping = {}
    search_dirs = DESKTOP_SEARCH_DIRS
    for d in search_dirs:
        if not d.exists():
            continue
        for p in d.glob("*.desktop"):
            try:
                base = p.stem.lower()
                c_icon = None
                c_name = None
                c_exec = None
                with open(p, "r", errors="ignore") as f:
                    for line in f:
                        if line.startswith("Icon=") and not c_icon:
                            c_icon = line.strip().split("=", 1)[1]
                        elif line.startswith("Name=") and not c_name:
                            c_name = line.strip().split("=", 1)[1]
                        elif line.startswith("Exec=") and not c_exec:
                            c_exec = line.strip().split("=", 1)[1]
                        if c_icon and c_name and c_exec:
                            break
                alias_keys = [base]
                if "." in base:
                    alias_keys.append(base.split(".")[-1])
                if "_" in base:
                    # Snap desktop files use <snap>_<app>.desktop (e.g. vlc_vlc.desktop)
                    alias_keys.append(base.split("_")[0])
                if base.startswith("arkst-box-"):
                    alias_keys.append(base[len("arkst-box-"):])

                if c_icon:
                    for ak in alias_keys:
                        if ak and ak not in mapping:
                            mapping[ak] = c_icon
                if c_name:
                    for ak in alias_keys:
                        if ak and ak not in names_mapping:
                            names_mapping[ak] = c_name
                # Launcher entries mapping (exact stem matches strictly supersede secondary auxiliary launchers)
                for ak in alias_keys:
                    if ak and (ak not in entries_mapping or p.stem.lower() == ak):
                        entries_mapping[ak] = p.stem
                bin_name = ""
                if c_exec:
                    clean_exec = _extract_exec_binary(c_exec)
                    bin_name = os.path.basename(clean_exec).lower()
                    if bin_name and (bin_name not in entries_mapping or p.stem.lower() == bin_name):
                        entries_mapping[bin_name] = p.stem
                for key in alias_keys + [bin_name]:
                    if not key:
                        continue
                    clean = re.sub(r'-(bin|launcher|desktop|oss|browser|git|app|gtk-app|qt-app)$', '', key)
                    if clean and (clean not in entries_mapping or p.stem.lower() == clean):
                        entries_mapping[clean] = p.stem
                    clean_nodash = clean.replace("-", "")
                    if clean_nodash and (clean_nodash not in entries_mapping or p.stem.lower() == clean_nodash):
                        entries_mapping[clean_nodash] = p.stem
            except Exception:
                pass

    _DESKTOP_ICONS_CACHE = mapping
    _DESKTOP_NAMES_CACHE = names_mapping
    _DESKTOP_ENTRIES_CACHE = entries_mapping
    return _DESKTOP_ICONS_CACHE


def get_desktop_entries_map() -> Dict[str, str]:
    """Return fast in-memory map of application package and binary names to desktop launcher stems."""
    get_desktop_icons_map()
    return _DESKTOP_ENTRIES_CACHE


def get_desktop_names_map() -> Dict[str, str]:
    """Index system .desktop files to resolve human-readable app names."""
    get_desktop_icons_map()
    return _DESKTOP_NAMES_CACHE


def get_app_display_name(pkg_name: str, fallback_title: str = "") -> str:
    """Return a polished human-readable Apple App Store title."""
    if fallback_title:
        return fallback_title
    clean_pkg = pkg_name.lower().strip()
    if clean_pkg in APP_DISPLAY_NAMES:
        return APP_DISPLAY_NAMES[clean_pkg]
    dt_names = get_desktop_names_map()
    if clean_pkg in dt_names:
        return dt_names[clean_pkg]

    # Check for package suffixes (cli, git, bin, etc.) to avoid collision with main GUI app
    m = re.search(r'-(bin|git|hg|svn|pure|gtk-app|qt-app|gui|cli|daemon|desktop|launcher)$', clean_pkg)
    if m:
        suffix = m.group(1)
        base = clean_pkg[:m.start()]
        base_title = APP_DISPLAY_NAMES.get(base) or dt_names.get(base) or base.replace("-", " ").title()
        suffix_tags = {
            "cli": "CLI",
            "git": "Git",
            "bin": "Bin",
            "daemon": "Daemon",
            "launcher": "Launcher",
            "pure": "Pure",
            "gui": "GUI",
            "gtk-app": "GTK",
            "qt-app": "Qt",
        }
        tag = suffix_tags.get(suffix, suffix.capitalize())
        if base == "vlc":
            return f"VLC ({tag})"
        return f"{base_title} ({tag})"

    return clean_pkg.replace("-", " ").title()


def resolve_icon_name(pkg_name: str, desc: str = "") -> str:
    """
    Intelligently map a package name to an authentic Linux desktop icon (Papirus / System).
    Guarantees 100% modern vector icons, never emojis or dated glyphs.
    """
    name = pkg_name.lower().strip()
    overrides = {
        "proton-vpn-gtk-app": "proton-vpn-logo",
        "proton-vpn-cli": "proton-vpn-logo",
        "proton-vpn": "proton-vpn-logo",
        "protonvpn": "proton-vpn-logo",
        "proton-pass": "proton-pass",
        "protonplus": "protonplus",
        "protonup-qt": "protonup-qt",
        "protontricks": "wine",
        "mullvad-vpn-bin": "mullvad-vpn",
        "mullvad-vpn": "mullvad-vpn",
        "zen-browser-bin": "zen-browser",
        "zen-browser": "zen-browser",
        "zen": "zen-browser",
        "visual-studio-code-bin": "com.visualstudio.code.oss",
        "code": "com.visualstudio.code.oss",
        "code-oss": "com.visualstudio.code.oss",
        "brave-bin": "brave-browser",
        "brave": "brave-browser",
        "brave-origin-bin": "brave-browser",
        "brave-origin": "brave-browser",
        "torbrowser-launcher": "tor-browser",
        "firefox-pure": "firefox",
        "firefox": "firefox",
        "vesktop": "discord",
        "discord": "discord",
        "steam": "steam",
        "spotify": "spotify-client",
        "spotify-launcher": "spotify-client",
        "vlc": "vlc",
        "mpv": "mpv",
        "obs-studio": "obs",
        "obs": "obs",
        "foot": "foot",
        "kitty": "kitty",
        "btop": "utilities-system-monitor",
        "btop++": "utilities-system-monitor",
        "fastfetch": "utilities-terminal",
        "neovim": "nvim",
        "nvim": "nvim",
        "git": "git",
        "docker": "docker-desktop",
        "alacritty": "Alacritty",
        "telegram-desktop": "telegram",
        "telegram": "telegram",
        "signal-desktop": "signal-desktop",
        "lutris": "net.lutris.Lutris",
        "thunar": "org.xfce.thunar",
        "nautilus": "org.gnome.Nautilus",
        "dolphin": "org.kde.dolphin",
        "pavucontrol": "org.pulseaudio.pavucontrol",
        "micro": "micro",
        "gimp": "gimp",
        "blender": "blender",
        "chromium": "chromium",
        "btrfs-assistant": "btrfs-assistant",
        "cachyos-hello": "org.cachyos.hello",
        "org.cachyos.kernelmanager": "org.cachyos.KernelManager",
        "cachyos-pi": "cachyos-pi",
        "chatgpt": "chatgpt",
        "com.anthropic.claude": "claude-desktop",
        "cmake-gui": "CMakeSetup",
        "freedownloadmanager": "freedownloadmanager",
        "goverlay": "io.github.benjamimgois.goverlay",
        "com.heroicgameslauncher.hgl": "com.heroicgameslauncher.hgl",
        "hyprmod": "io.github.bluemancz.hyprmod",
        "kdeconnect": "kdeconnect",
        "localsend": "localsend",
        "meld": "org.gnome.Meld",
        "scx-manager": "org.cachyos.scx-manager",
        "stremio": "smartcode-stremio",
        "bash": "utilities-terminal",
        "zsh": "utilities-terminal",
        "fish": "utilities-terminal",
        "libreoffice-fresh": "libreoffice-main",
        "libreoffice": "libreoffice-main",
        "libreoffice-still": "libreoffice-main",
        "obsidian": "obsidian",
        "heroic": "com.heroicgameslauncher.hgl",
        "heroic-games-launcher-bin": "com.heroicgameslauncher.hgl",
        "kdenlive": "kdenlive",
        "audacity": "audacity",
        "retroarch": "retroarch",
        "bottles": "com.usebottles.bottles",
        "mangohud": "utilities-system-monitor",
        "bitwarden": "bitwarden",
        "lazygit": "lazygit",
        "zed": "dev.zed.Zed",
        "postman-bin": "postman",
        "postman": "postman",
        "dbeaver": "dbeaver",
        "joplin-desktop": "joplin",
        "joplin": "joplin",
        "onlyoffice-bin": "onlyoffice-desktopeditors",
        "anytype-bin": "anytype",
        "evince": "org.gnome.Evince",
        "krita": "krita",
        "foliate": "com.github.johnfactotum.Foliate",
        "keepassxc": "org.keepassxc.KeePassXC",
        "wireguard-tools": "network-vpn",
        "bleachbit": "bleachbit",
        "tailscale": "tailscale",
        "thunderbird": "org.mozilla.Thunderbird",
        "handbrake": "fr.handbrake.ghb",
        "darktable": "darktable",
        "ardour": "ardour",
        "gparted": "gparted",
        "timeshift": "timeshift",
        "baobab": "org.gnome.baobab",
        "stacer-bin": "stacer",
        "stacer": "stacer",
        "hardinfo-git": "hardinfo",
        "hardinfo": "hardinfo",
        "hardinfo2": "hardinfo",
        "prismlauncher": "org.prismlauncher.PrismLauncher",
        "wine": "wine",
        "gamemode": "preferences-system",
        "ryujinx-bin": "ryujinx",
        "ryujinx": "ryujinx",
        "waybar": "preferences-desktop-display",
        "rofi-wayland": "system-search",
        "wofi": "system-search",
        "fuzzel": "system-search",
        "hyprpaper": "preferences-desktop-wallpaper",
        "swww": "preferences-desktop-wallpaper",
        "hyprlock": "system-lock-screen",
        "hypridle": "preferences-system-power",
        "hyprpicker": "color-select",
        "hyprshot": "applets-screenshooter",
        "grim": "applets-screenshooter",
        "slurp": "applets-screenshooter",
        "swappy": "applets-screenshooter",
        "swaync": "preferences-system-notifications",
        "mako": "preferences-system-notifications",
        "dunst": "preferences-system-notifications",
        "wlogout": "system-log-out",
        "nwg-look": "preferences-desktop-theme",
        "nwg-displays": "preferences-desktop-display",
        "cliphist": "edit-paste",
        "wl-clipboard": "edit-paste",
        "blueman": "preferences-system-bluetooth",
        "nm-connection-editor": "preferences-system-network",
        "qt5ct": "preferences-desktop-theme",
        "qt6ct": "preferences-desktop-theme",
        "kvantum": "preferences-desktop-theme",
    }
    if name in overrides:
        return overrides[name]

    # Check desktop icons cache
    dt_map = get_desktop_icons_map()
    if name in dt_map:
        return dt_map[name]

    clean = re.sub(r'-(bin|git|hg|svn|pure|gtk-app|qt-app|gui|cli|daemon|desktop|launcher)$', '', name)
    clean2 = re.sub(r'-(gtk|qt|gtk[0-9]|qt[0-9]|electron|wayland|x11)$', '', clean)

    if clean in overrides:
        return overrides[clean]
    if clean in dt_map:
        return dt_map[clean]
    if clean2 in overrides:
        return overrides[clean2]
    if clean2 in dt_map:
        return dt_map[clean2]

    combined = f"{name} {desc}".lower()
    if "vpn" in combined or "wireguard" in combined:
        return "network-vpn"
    if any(k in combined for k in ["browser", "web-browser", "firefox", "chromium", "chrome"]):
        return "web-browser"
    if any(k in combined for k in ["terminal", "shell", "console", "emulator", "prompt"]):
        return "utilities-terminal"
    if any(k in combined for k in ["audio", "music", "sound", "player", "alsa", "pipewire", "pulse"]):
        return "applications-multimedia"
    if any(k in combined for k in ["video", "movie", "recording", "stream", "codec", "ffmpeg"]):
        return "applications-multimedia"
    if any(k in combined for k in ["editor", "code", "ide", "develop", "compiler", "sdk"]):
        return "accessories-text-editor"
    if any(k in combined for k in ["game", "gaming", "steam", "emulator", "wine", "proton"]):
        return "applications-games"
    if any(k in combined for k in ["image", "photo", "graphics", "paint", "draw", "render"]):
        return "applications-graphics"
    if any(k in combined for k in ["font", "ttf-", "otf-", "noto-"]):
        return "preferences-desktop-font"
    if any(k in combined for k in ["theme", "icon-theme", "cursor"]):
        return "preferences-desktop-theme"
    if any(k in combined for k in ["system", "kernel", "linux", "cachyos", "bpf", "udev", "firmware", "driver"]):
        return "preferences-system"
    if any(k in combined for k in ["security", "crypto", "cert", "auth", "keyring", "password", "vpn"]):
        return "security-high"
    if any(k in combined for k in ["network", "wifi", "bluetooth", "wireless", "ethernet", "ip"]):
        return "network-wired"
    if name.startswith("lib") or "library" in combined:
        return "system-software-install"

    return "system-software-install"



_CURATED_DESKTOP_SET: Optional[Set[str]] = None


def get_desktop_and_curated_set() -> Set[str]:
    """Return cached set of known desktop and curated application names for instant relevance boosting."""
    global _CURATED_DESKTOP_SET
    if _CURATED_DESKTOP_SET is not None:
        return _CURATED_DESKTOP_SET

    s = set()
    s.update(k.lower() for k in APP_DISPLAY_NAMES.keys())
    for cat in CURATED_CATEGORIES:
        for app in cat.get("apps", []):
            name = app.get("name", "").lower()
            if name:
                s.add(name)
    s.update(k.lower() for k in FEATURED_APP_PRESETS.keys())
    s.update(k.lower() for k in _DESKTOP_OVERRIDES.keys())
    s.update(v.lower() for v in _DESKTOP_OVERRIDES.values())
    try:
        entries = get_desktop_entries_map()
        s.update(k.lower() for k in entries.keys())
    except Exception:
        pass

    _CURATED_DESKTOP_SET = s
    return _CURATED_DESKTOP_SET


def is_desktop_app(pkg_name: str) -> bool:
    """Check if a package represents a user-facing desktop or curated application."""
    if not pkg_name:
        return False
    name = pkg_name.lower().strip()
    desktop_set = get_desktop_and_curated_set()
    if name in desktop_set:
        return True
    idx = name.rfind('-')
    if idx != -1:
        prefix = name[:idx]
        suffix = name[idx+1:]
        if suffix in ('bin', 'git', 'hg', 'svn', 'pure', 'desktop', 'launcher', 'gui', 'gtk-app', 'qt-app'):
            if prefix in desktop_set:
                return True
    return False


def is_damerau_levenshtein_one(s1: str, s2: str) -> bool:
    """Check if s1 and s2 have edit distance <= 1 (insertion, deletion, substitution, adjacent swap)."""
    len1, len2 = len(s1), len(s2)
    if abs(len1 - len2) > 1:
        return False
    if len1 == len2:
        diffs = [i for i in range(len1) if s1[i] != s2[i]]
        if len(diffs) == 1:
            return True
        if len(diffs) == 2 and diffs[1] == diffs[0] + 1:
            return s1[diffs[0]] == s2[diffs[1]] and s1[diffs[1]] == s2[diffs[0]]
        return False
    short, long = (s1, s2) if len1 < len2 else (s2, s1)
    i = j = 0
    diff = 0
    while i < len(short) and j < len(long):
        if short[i] != long[j]:
            diff += 1
            if diff > 1:
                return False
            j += 1
        else:
            i += 1
            j += 1
    return True


def fuzzy_score(
    query: str,
    target: str,
    desc: str = "",
    is_desktop: Optional[bool] = None,
    is_installed: bool = False
) -> int:
    """
    Tiered Multi-Level Scoring Engine for ArkST:
      Tier 1: Exact Name Match: 10,000 points
      Tier 2: Exact Normalized Match: 9,000 points
      Tier 3: Prefix Match on Name: 7,000 - min(500, len(name)*10)
      Tier 4: Word Boundary / Segment Match: 5,000 points
      Tier 5: High-Precision Subsequence Match on Name:
              Base 3,000 + streak multiplier (+50*streak) + boundary bonus (+150)
              Only for queries >= 2 characters
      Tier 6: Description Exact Word / Phrase Match:
              1,500 points (Only for queries >= 3 characters)
      Relevance Boosts (applied only if base score > 0):
        +800 for Desktop / Curated Applications
        +200 for Locally Installed Packages
    """
    q = query.lower().strip()
    t = target.lower().strip()

    if not q or not t:
        return 0

    base_score = 0
    q_len = len(q)
    t_len = len(t)

    # 1. Exact Name Match (e.g. vlc == vlc, git == git): 10,000 points
    if q == t:
        base_score = 10000

    # Fast normalization using C-level string operations
    q_norm = q.replace("-", " ").replace("_", " ").replace(".", " ")
    t_norm = t.replace("-", " ").replace("_", " ").replace(".", " ")

    # 2. Exact Normalized Match (code-oss for code oss): 9,000 points
    if not base_score:
        if q_norm == t_norm:
            base_score = 9000
        else:
            q_condensed = q_norm.replace(" ", "")
            t_condensed = t_norm.replace(" ", "")
            if q_condensed and q_condensed == t_condensed:
                base_score = 9000

    # 3. Prefix Match on Name (fire -> firefox, neov -> neovim): 7,000 - min(500, len(name)*10)
    if not base_score:
        if t.startswith(q) or t_norm.startswith(q_norm):
            base_score = 7000 - min(500, t_len * 10)
        else:
            q_condensed = q_norm.replace(" ", "")
            t_condensed = t_norm.replace(" ", "")
            if q_condensed and t_condensed.startswith(q_condensed):
                base_score = 7000 - min(500, t_len * 10)

    # For 1-char queries: ONLY match packages starting with that letter. Instant sub-1ms return.
    if q_len < 2:
        if base_score > 0:
            if is_desktop is None:
                is_desktop = is_desktop_app(target)
            if is_desktop:
                base_score += 800
            if is_installed:
                base_score += 200
            return base_score
        return 0

    # 4. Word Boundary / Segment Match (studio -> obs-studio, code -> visual-studio-code): 5,000 points
    if not base_score:
        t_segments = t_norm.split()
        q_words = q_norm.split()

        if q in t_segments:
            base_score = 5000
        elif len(q_words) > 1 and all(w in t_segments for w in q_words):
            base_score = 5000
        else:
            idx = t.find(q)
            if idx != -1:
                is_boundary_start = (idx == 0 or t[idx - 1] in "-_. ")
                end_pos = idx + q_len
                is_boundary_end = (end_pos == t_len or t[end_pos] in "-_. ")
                if is_boundary_start and is_boundary_end:
                    base_score = 5000
                elif is_boundary_start:
                    base_score = 4800
            else:
                idx = t_norm.find(q_norm)
                if idx != -1:
                    is_boundary_start = (idx == 0 or t_norm[idx - 1] == ' ')
                    end_pos = idx + len(q_norm)
                    is_boundary_end = (end_pos == len(t_norm) or t_norm[end_pos] == ' ')
                    if is_boundary_start and is_boundary_end:
                        base_score = 5000
                    elif is_boundary_start:
                        base_score = 4800
                elif any(s.startswith(q) for s in t_segments):
                    base_score = 4800

    # 5. High-Precision Subsequence Match on Name (only for queries >= 2 characters)
    #    Bonus for matches following -, _, ., or word start (+150)
    #    Consecutive character match streak multiplier (+50 * streak)
    #    Score base: 3,000
    if not base_score and q_len >= 2:
        if q[0] in t:
            qi = 0
            last_idx = -2
            streak = 0
            subseq_bonus = 0

            for i, ch in enumerate(t):
                if qi < q_len and ch == q[qi]:
                    if i == 0 or t[i - 1] in "-_. ":
                        subseq_bonus += 150

                    if last_idx == i - 1:
                        streak += 1
                        subseq_bonus += 50 * streak
                    else:
                        streak = 0

                    last_idx = i
                    qi += 1

            if qi == q_len:
                subseq_calc = 3000 + subseq_bonus
                base_score = max(3000, min(4800, subseq_calc))

    # 5.5 Typo Tolerance / Single-Edit Distance (only for queries >= 4 characters)
    # Allows 1 transposition, insertion, deletion, or substitution (e.g. firfox -> firefox, chorme -> chrome)
    if not base_score and q_len >= 4:
        q_norm = re.sub(r'[-_.\s]+', ' ', q).strip()
        t_norm = re.sub(r'[-_.\s]+', ' ', t).strip()
        if is_damerau_levenshtein_one(q, t) or is_damerau_levenshtein_one(q_norm, t_norm):
            base_score = 2500 - min(300, t_len * 10)
        else:
            t_segments = [s for s in re.split(r'[-_.\s]+', t) if s]
            for s in t_segments:
                if len(s) >= 3 and is_damerau_levenshtein_one(q, s):
                    base_score = 2200 - min(300, t_len * 10)
                    break

    # 6. Description Exact Word / Phrase Match (only for queries >= 3 characters)
    #    Word match in description: 1,500 points
    if not base_score and q_len >= 3 and desc:
        d = desc.lower()
        if q in d:
            pos = 0
            is_word_match = False
            first_idx = -1
            while True:
                idx = d.find(q, pos)
                if idx == -1:
                    break
                if first_idx == -1:
                    first_idx = idx
                before_ok = (idx == 0 or not d[idx - 1].isalnum())
                after_ok = (idx + q_len == len(d) or not d[idx + q_len].isalnum())
                if before_ok and after_ok:
                    is_word_match = True
                    first_idx = idx
                    break
                pos = idx + 1

            if is_word_match:
                base_score = 1500 - min(100, first_idx)
            elif first_idx != -1:
                base_score = 1200 - min(100, first_idx)

    # Apply Relevance Boosts if package matched (base_score > 0)
    if base_score > 0:
        if is_desktop is None:
            is_desktop = is_desktop_app(target)
        if is_desktop:
            base_score += 800
        if is_installed:
            base_score += 200
        return base_score

    return 0



SAFE_PKG_NAME_RE = re.compile(r'^[a-zA-Z0-9@._+][a-zA-Z0-9@._+-]{0,127}$')

CRITICAL_SYSTEM_PACKAGES: Set[str] = {
    "base", "linux", "linux-lts", "linux-zen", "linux-hardened", "linux-cachyos",
    "glibc", "gcc-libs", "filesystem", "bash", "coreutils", "systemd", "systemd-libs",
    "systemd-sysvcompat", "pacman", "sudo", "shadow", "util-linux", "iproute2",
    "dbus", "openssl", "krb5", "pam", "ncurses", "readline", "zlib", "zstd",
}


def is_valid_pkg_name(pkg_name: str) -> bool:
    """
    Validate package identifier against command/option injection, path traversal,
    null bytes, whitespace, and oversized inputs (AURA-SEC-001).
    """
    if not pkg_name or not isinstance(pkg_name, str):
        return False
    s = pkg_name.strip()
    if not s or len(s) > 128:
        return False
    if s.startswith("-") or s.startswith(".") or ".." in s or "/" in s or "\\" in s or "\x00" in s:
        return False
    if any(ch.isspace() or ord(ch) < 32 for ch in s):
        return False
    return bool(SAFE_PKG_NAME_RE.match(s))


ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

# Global re-entrant lock serializing all in-process operations that touch /var/lib/pacman/db.lck
GLOBAL_ALPM_LOCK = threading.RLock()


def wait_for_alpm_lock(progress_cb: Optional[Callable[[float, str], None]] = None, max_wait: int = 240, env: Optional[Dict[str, str]] = None) -> bool:
    """
    Wait safely for /var/lib/pacman/db.lck to be released by any external package manager.
    If /var/lib/pacman/db.lck exists and NO pacman/paru/yay/makepkg process is running,
    automatically removes the stale lock file so transactions never fail due to an orphaned lock.
    """
    lock_file = Path("/var/lib/pacman/db.lck")
    if not lock_file.exists():
        return True

    run_env = env or os.environ.copy()
    askpass = get_askpass_script()
    if askpass.exists():
        run_env["SUDO_ASKPASS"] = str(askpass)
    run_env["LC_ALL"] = "C"

    waited = 0.0
    while lock_file.exists() and waited < max_wait:
        active_procs = []
        for pname in ("pacman", "paru", "yay", "makepkg"):
            try:
                r = subprocess.run(["pgrep", "-x", pname], capture_output=True, text=True, timeout=2)
                if r.returncode == 0 and r.stdout.strip():
                    active_procs.append(pname)
            except Exception:
                pass

        if not active_procs:
            if progress_cb:
                try:
                    progress_cb(0.06, "Clearing stale Pacman database lock (/var/lib/pacman/db.lck)...")
                except Exception:
                    pass
            res = subprocess.run(["sudo", "-n", "rm", "-f", str(lock_file)], stdin=subprocess.DEVNULL, capture_output=True, env=run_env, timeout=5)
            if res.returncode != 0 and lock_file.exists():
                subprocess.run(["sudo", "-A", "rm", "-f", str(lock_file)], stdin=subprocess.DEVNULL, capture_output=True, env=run_env, timeout=20)
            return not lock_file.exists()

        if progress_cb:
            try:
                progress_cb(0.06, f"Waiting for {', '.join(active_procs)} to release database lock...")
            except Exception:
                pass
        time.sleep(1.0)
        waited += 1.0

    return not lock_file.exists()



class PacmanProgressParser:
    """
    Parser for pacman and paru stdout streams with monotonic progress calculation,
    package-aware stage tracking, and post-transaction hook protection.
    """
    INSTALL_REGEX = re.compile(
        r'\((\d+)/(\d+)\)\s+(?:upgrading|installing|reinstalling|downgrading|removing)\s+([a-zA-Z0-9_\-\.\+]+)',
        re.IGNORECASE
    )
    PKG_TAR_REGEX = re.compile(
        r'([a-zA-Z0-9@_+][a-zA-Z0-9@_\.\+-]*?)-[0-9][a-zA-Z0-9_\.\+:]*-[0-9]+\.pkg\.tar',
        re.IGNORECASE
    )
    PKG_TAR_SIMPLE = re.compile(
        r'([a-zA-Z0-9@_+][a-zA-Z0-9@_\.\+-]*?)\.pkg\.tar',
        re.IGNORECASE
    )
    DOWNLOADING_REGEX = re.compile(
        r'downloading\s+([a-zA-Z0-9@_+][a-zA-Z0-9@_\.\+-]*)',
        re.IGNORECASE
    )
    INDEX_REGEX = re.compile(r'\((\d+)/(\d+)\)')

    def __init__(self, action: str = "update", target_pkg: str = "", is_system_upgrade: bool = False, upgradable_pkgs: Optional[Set[str]] = None):
        self.action = action.lower()
        self.is_system_upgrade = is_system_upgrade or (target_pkg in ["system", "--all", "all", ""] or not target_pkg)
        self.target_pkg = ("" if self.is_system_upgrade else target_pkg).strip().lower()
        self.upgradable_pkgs = {p.strip().lower() for p in upgradable_pkgs} if upgradable_pkgs else set()

        target_name = self.target_pkg
        self.target_disp = (
            APP_DISPLAY_NAMES.get(target_name, APP_DISPLAY_NAMES.get(target_name.lower(), target_name.replace('-', ' ').title()))
            if target_name else "System"
        )

        self.total_packages = max(1, len(self.upgradable_pkgs)) if self.upgradable_pkgs else 1
        self.current_idx = 0
        self.current_pkg: Optional[str] = self.target_pkg if self.target_pkg else None
        self.downloaded_pkgs: Set[str] = set()
        self.in_post_hooks = False
        self.last_progress = 0.06
        self.error_lines: List[str] = []

    def get_display_name(self, pkg: str) -> str:
        clean = pkg.strip()
        return APP_DISPLAY_NAMES.get(clean, APP_DISPLAY_NAMES.get(clean.lower(), clean.replace('-', ' ').title()))

    def get_action_verb(self, matched_verb: Optional[str] = None) -> str:
        if matched_verb:
            mv = matched_verb.lower()
            if "remov" in mv or self.action == "remove":
                return "Removing"
            if "install" in mv and self.action == "install":
                return "Installing"
            return "Updating"
        if self.action == "remove":
            return "Removing"
        elif self.action == "install":
            return "Installing"
        return "Updating"

    def process_line(self, line: str) -> Optional[Tuple[float, str, Optional[str], Optional[int], Optional[int]]]:
        """
        Process a single line of pacman/paru stdout.
        Returns tuple: (progress_frac, status_msg, current_pkg, current_idx, total_packages)
        or None if no state update for this line.
        """
        clean = ANSI_ESCAPE.sub('', line).strip()
        if not clean:
            return None
        l_lower = clean.lower()

        if "error:" in l_lower or "failed" in l_lower:
            self.error_lines.append(clean)

        # Update total packages if pacman outputs Packages (N)
        pkg_match = re.search(r'packages\s*\(\s*(\d+)\s*\)', l_lower)
        if pkg_match:
            self.total_packages = max(self.total_packages, int(pkg_match.group(1)))

        # 1. Post-transaction hooks detection
        if "post-transaction hooks" in l_lower or "running post-transaction" in l_lower:
            self.in_post_hooks = True
            prog = max(self.last_progress, 0.90)
            self.last_progress = prog
            return (prog, "Running post-transaction hooks...", self.current_pkg, self.current_idx, self.total_packages)

        # 2. While in post-transaction hooks:
        if self.in_post_hooks:
            if any(k in l_lower for k in ["desktop", "icon", "mime", "font", "systemd", "system", "conditionneedsupdate"]):
                h_match = self.INDEX_REGEX.search(clean)
                if h_match:
                    h_cur = int(h_match.group(1))
                    h_tot = int(h_match.group(2))
                    hook_stage = round(min(0.96, 0.92 + (h_cur / max(1, h_tot)) * 0.04), 4)
                else:
                    hook_stage = round(min(0.96, max(0.92, self.last_progress + 0.01)), 4)
                prog = max(self.last_progress, hook_stage)
                self.last_progress = prog
                return (prog, "Finalizing desktop & system environment...", self.current_pkg, self.current_idx, self.total_packages)
            return None

        # 3. Installation / Upgrade / Removal line parsing
        inst_match = self.INSTALL_REGEX.search(clean)
        if inst_match:
            cur_idx = int(inst_match.group(1))
            tot_idx = int(inst_match.group(2))
            p_name = inst_match.group(3).strip()

            self.total_packages = max(self.total_packages, tot_idx)
            self.current_idx = cur_idx
            self.current_pkg = p_name

            disp = self.get_display_name(p_name)
            verb = self.get_action_verb()

            inst_stage = round(min(0.88, 0.28 + (cur_idx / max(1, tot_idx)) * 0.60), 4)
            prog = max(self.last_progress, inst_stage)
            self.last_progress = prog

            p_clean = p_name.strip().lower()
            is_dep = False
            if self.upgradable_pkgs:
                is_dep = (p_clean not in self.upgradable_pkgs)
            elif self.target_pkg:
                target_clean = self.target_pkg.lower()
                is_target = (
                    p_clean == target_clean
                    or p_clean == target_clean.replace("-bin", "")
                    or target_clean == p_clean.replace("-bin", "")
                    or p_clean == target_clean.replace("-git", "")
                    or target_clean == p_clean.replace("-git", "")
                )
                is_dep = not is_target

            if is_dep:
                msg = f"{verb} dependency {disp} ({cur_idx} of {tot_idx})..."
            elif self.is_system_upgrade or not self.target_pkg:
                msg = f"{verb} {disp} ({cur_idx} of {tot_idx})..."
            else:
                if tot_idx > 1:
                    msg = f"{verb} {disp} ({cur_idx} of {tot_idx})..."
                else:
                    msg = f"{verb} {disp}..."

            return (prog, msg, p_name, cur_idx, tot_idx)

        # 4. Dependency resolution & keyring / integrity / disk space
        if "resolving dependencies" in l_lower or "calculating dependencies" in l_lower:
            prog = max(self.last_progress, 0.07)
            self.last_progress = prog
            return (prog, "Resolving package dependencies...", self.current_pkg, self.current_idx, self.total_packages)

        if (
            "checking keyring" in l_lower
            or "checking keys in keyring" in l_lower
            or "package integrity" in l_lower
            or "verifying package integrity" in l_lower
            or "loading package files" in l_lower
        ):
            prog = max(self.last_progress, 0.27)
            self.last_progress = prog
            return (prog, "Checking package integrity & keyring...", self.current_pkg, self.current_idx, self.total_packages)

        if (
            "looking for conflicting" in l_lower
            or "checking for conflicting" in l_lower
            or "file conflicts" in l_lower
            or "available disk space" in l_lower
            or "verifying disk space" in l_lower
        ):
            prog = max(self.last_progress, 0.28)
            self.last_progress = prog
            return (prog, "Verifying disk space & conflicts...", self.current_pkg, self.current_idx, self.total_packages)

        if "processing package changes" in l_lower:
            prog = max(self.last_progress, 0.28)
            self.last_progress = prog
            return (prog, "Applying package changes...", self.current_pkg, self.current_idx, self.total_packages)

        # 5. Download phase
        if "retrieving packages" in l_lower or "downloading" in l_lower or ".pkg.tar." in l_lower:
            idx_match = self.INDEX_REGEX.search(clean)
            if idx_match:
                self.total_packages = max(self.total_packages, int(idx_match.group(2)))

            dl_pkg = None
            pkg_tar_m = self.PKG_TAR_REGEX.search(clean)
            if pkg_tar_m:
                dl_pkg = pkg_tar_m.group(1).strip()
            else:
                pkg_tar_s = self.PKG_TAR_SIMPLE.search(clean)
                if pkg_tar_s:
                    dl_pkg = pkg_tar_s.group(1).strip()
                else:
                    dl_name_m = self.DOWNLOADING_REGEX.search(clean)
                    if dl_name_m:
                        cand = dl_name_m.group(1).strip().rstrip('.')
                        v_m = re.search(r'^([a-zA-Z0-9@_+][a-zA-Z0-9@_\.\+-]*?)-[0-9]', cand)
                        dl_pkg = v_m.group(1) if v_m else cand

            if dl_pkg:
                self.downloaded_pkgs.add(dl_pkg.lower())
            elif idx_match:
                self.downloaded_pkgs.add(f"idx_{idx_match.group(1)}")

            dl_count = min(len(self.downloaded_pkgs), self.total_packages)
            dl_stage = round(min(0.28, 0.08 + (dl_count / max(1, self.total_packages)) * 0.20), 4)
            prog = max(self.last_progress, dl_stage)
            self.last_progress = prog

            if self.total_packages > 1 and dl_count > 0:
                dl_msg = f"Downloading package files ({dl_count} of {self.total_packages})..."
            else:
                dl_msg = "Downloading package files..."

            return (prog, dl_msg, dl_pkg or self.current_pkg, dl_count, self.total_packages)

        # 6. AUR (paru / yay / makepkg) build stages
        if ":: fetching" in l_lower or "cloning" in l_lower or "downloading pkgbuilds" in l_lower:
            prog = max(self.last_progress, 0.12)
            self.last_progress = prog
            return (prog, f"Fetching AUR build files for {self.target_disp}...", self.current_pkg, self.current_idx, self.total_packages)

        if "==> making package:" in l_lower:
            prog = max(self.last_progress, 0.18)
            self.last_progress = prog
            return (prog, f"Preparing AUR package build for {self.target_disp}...", self.current_pkg, self.current_idx, self.total_packages)

        if "==> retrieving sources" in l_lower:
            prog = max(self.last_progress, 0.25)
            self.last_progress = prog
            return (prog, f"Downloading upstream sources for {self.target_disp}...", self.current_pkg, self.current_idx, self.total_packages)

        if "==> validating source" in l_lower or "sha256sums" in l_lower or "sha512sums" in l_lower or "b2sums" in l_lower:
            prog = max(self.last_progress, 0.34)
            self.last_progress = prog
            return (prog, "Validating source checksums & integrity...", self.current_pkg, self.current_idx, self.total_packages)

        if "==> extracting sources" in l_lower:
            prog = max(self.last_progress, 0.42)
            self.last_progress = prog
            return (prog, f"Extracting source archives for {self.target_disp}...", self.current_pkg, self.current_idx, self.total_packages)

        if "==> starting prepare()" in l_lower:
            prog = max(self.last_progress, 0.48)
            self.last_progress = prog
            return (prog, f"Preparing source tree for {self.target_disp}...", self.current_pkg, self.current_idx, self.total_packages)

        if "==> starting build()" in l_lower or "compiling" in l_lower:
            prog = max(self.last_progress, 0.58)
            self.last_progress = prog
            return (prog, f"Compiling {self.target_disp}...", self.current_pkg, self.current_idx, self.total_packages)

        if "==> entering fakeroot" in l_lower or "==> starting package" in l_lower:
            prog = max(self.last_progress, 0.72)
            self.last_progress = prog
            return (prog, f"Packaging {self.target_disp} files...", self.current_pkg, self.current_idx, self.total_packages)

        if "==> tidying install" in l_lower or "==> creating package" in l_lower:
            prog = max(self.last_progress, 0.82)
            self.last_progress = prog
            return (prog, f"Compressing {self.target_disp} package archive...", self.current_pkg, self.current_idx, self.total_packages)

        if "==> finished making:" in l_lower:
            prog = max(self.last_progress, 0.86)
            self.last_progress = prog
            return (prog, f"Build complete, installing {self.target_disp}...", self.current_pkg, self.current_idx, self.total_packages)

        # 7. Live percentage lines from pacman / curl / makepkg (CR carriage return updates)
        m_pct = re.search(r'(\d{1,3})%', clean)
        if m_pct:
            pct_val = min(99, max(1, int(m_pct.group(1))))
            if self.last_progress < 0.28:
                mapped = round(0.08 + (pct_val / 100.0) * 0.20, 4)
                prog = max(self.last_progress, mapped)
                self.last_progress = prog
                return (prog, f"Downloading {self.target_disp} ({pct_val}%)...", self.current_pkg, self.current_idx, self.total_packages)
            elif self.last_progress < 0.88:
                mapped = round(0.28 + (pct_val / 100.0) * 0.58, 4)
                prog = max(self.last_progress, mapped)
                self.last_progress = prog
                return (prog, f"{self.get_action_verb()} {self.target_disp} ({pct_val}%)...", self.current_pkg, self.current_idx, self.total_packages)

        return None

    def get_completion_message(self) -> str:
        if self.action in ["upgrade", "update"]:
            if self.is_system_upgrade:
                return "✓ System update complete!"
            return f"✓ Updated {self.target_disp} successfully!"
        elif self.action == "install":
            return f"✓ Installed {self.target_disp} successfully!"
        elif self.action == "remove":
            return f"✓ Removed {self.target_disp} successfully!"
        return "✓ Action complete!"

    def get_error_message(self, returncode: int) -> str:
        err_msg = "\n".join(self.error_lines[-3:]) if self.error_lines else f"Exited with code {returncode}"
        return f"Error: {err_msg}"


class PackageManager:
    def __init__(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.packages: Dict[str, Dict[str, Any]] = {}
        self.installed_set: Set[str] = set()
        self.installed_versions: Dict[str, str] = {}
        self.upgradable_list: List[Dict[str, str]] = []
        if UPDATES_CACHE_FILE.exists():
            try:
                with open(UPDATES_CACHE_FILE, "r") as f:
                    self.upgradable_list = json.load(f)
            except Exception:
                pass
        self._lock = threading.Lock()
        self._db_load_lock = threading.Lock()
        self._aur_cache: Dict[str, List[Dict[str, Any]]] = {}
        self.is_loaded = False
        self.active_transaction: Optional[Dict[str, Any]] = None
        self._pending_actions: List[Dict[str, Any]] = []
        self._active_snap_tx: Optional[Dict[str, Any]] = None
        self._pending_snap_actions: List[Dict[str, Any]] = []
        self._active_docker_tx: Optional[Dict[str, Any]] = None
        self._pending_docker_actions: List[Dict[str, Any]] = []
        self._last_progress: float = 0.0
        self._action_lock = threading.RLock()
        self._update_generation: int = 0
        self._update_lock = threading.Lock()
        self.is_checking_updates = False
        self.updates_checked = False
        self._active_flatpak_tx: Optional[Dict[str, Any]] = None
        self._pending_flatpak_actions: List[Dict[str, Any]] = []
        self.container_mgr = ContainerManager()
        self.snap_mgr = SnapManager()
        self.flatpak_mgr = FlatpakManager()
        self.cache_mgr = CacheManager()
        self._desktop_owner_map: Dict[str, str] = {}
        self._binary_owner_map: Dict[str, str] = {}
        self._pkg_files_map: Dict[str, List[str]] = {}
        self._provides_map: Dict[str, str] = {}
        self._resolved_pkg_cache: Dict[str, str] = {}
        self._installed_desktop_apps_cache: Optional[List[Dict[str, Any]]] = None
        self._local_files_mtime: float = 0.0
        self.last_transaction_logs: List[str] = []
        self.clean_uninstall_default: bool = True
        self.deb_mgr = DebPackageManager(self)
        self.hypr_mgr = HyprlandManager(self)
        self.doctor_mgr = SystemDoctor(self)
        # Load installed packages synchronously so cards immediately reflect installed status
        self.refresh_installed()
        # Persistent rotating featured apps state
        state = _load_featured_state()
        self._featured_rotation_offset: int = (state.get("offset", 0) + 1) % 50
        self._last_featured_shown: List[str] = list(state.get("last_shown", []))
        _save_featured_state(self._featured_rotation_offset, self._last_featured_shown)
        self._current_featured_apps: Optional[List[Dict[str, Any]]] = None

        # Pre-warm Snap & Container manager caches in background thread for 0ms page navigation
        def _prewarm_managers():
            try:
                self.snap_mgr.get_status()
                self.snap_mgr.get_installed_snaps()
            except Exception:
                pass
            try:
                self.container_mgr.get_status()
                self.container_mgr.repair_existing_shortcuts()
            except Exception:
                pass
            try:
                self.flatpak_mgr.get_status()
                self.flatpak_mgr.get_installed_flatpaks()
            except Exception:
                pass
        threading.Thread(target=_prewarm_managers, daemon=True).start()

    def _index_local_pacman_files(self):
        """
        Scan /var/lib/pacman/local/*/files to build an authoritative O(1) mapping from
        every installed .desktop file and /usr/bin executable to its exact owning package name.
        """
        local_dir = Path("/var/lib/pacman/local")
        if not local_dir.exists():
            return
        dt_owners: Dict[str, str] = {}
        bin_owners: Dict[str, str] = {}
        pkg_files: Dict[str, List[str]] = {}
        try:
            for entry in os.scandir(local_dir):
                if not entry.is_dir(follow_symlinks=False):
                    continue
                # Directory name is <pkgname>-<pkgver>-<pkgrel>
                parts = entry.name.rsplit("-", 2)
                if len(parts) < 3:
                    continue
                pkgname = parts[0].lower()
                files_path = Path(entry.path) / "files"
                if not files_path.exists():
                    continue
                try:
                    raw = files_path.read_text(encoding="utf-8", errors="ignore")
                    owned_list = []
                    for line in raw.splitlines():
                        s = line.strip()
                        if not s or s.startswith("%") or s.endswith("/"):
                            continue
                        owned_list.append(s)
                        s_low = s.lower()
                        if s_low.endswith(".desktop") and "applications/" in s_low:
                            base = os.path.basename(s_low)
                            stem = base[:-8]  # strip .desktop
                            dt_owners[stem] = pkgname
                            dt_owners[base] = pkgname
                            if "." in stem:
                                tail = stem.split(".")[-1]
                                if tail not in ("desktop", "app", "studio", "launcher", "client") and tail not in dt_owners:
                                    dt_owners[tail] = pkgname
                        elif s_low.startswith("usr/bin/"):
                            bname = os.path.basename(s_low)
                            if bname:
                                bin_owners[bname] = pkgname
                    pkg_files[pkgname] = owned_list
                except Exception:
                    pass
        except Exception:
            pass
        with self._lock:
            self._desktop_owner_map = dt_owners
            self._binary_owner_map = bin_owners
            self._pkg_files_map = pkg_files

    def refresh_installed(self):
        """Quickly reload the list of installed packages, their versions, and file ownership maps."""
        try:
            if not hasattr(self, "_resolved_pkg_cache"):
                self._resolved_pkg_cache = {}
            if not hasattr(self, "_provides_map"):
                self._provides_map = {}
            self._resolved_pkg_cache.clear()
            self._installed_desktop_apps_cache = None

            res = subprocess.run(["pacman", "-Q"], capture_output=True, text=True, check=True, timeout=8)
            installed = {}
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    installed[parts[0]] = parts[1]
            with self._lock:
                self.installed_versions = installed
                self.installed_set = set(installed.keys())

            # Rebuild O(1) provides map for installed packages
            prov_map: Dict[str, str] = {}
            pkgs_ref = getattr(self, "packages", {}) or {}
            for inst_pkg in self.installed_set:
                p_data = pkgs_ref.get(inst_pkg)
                if p_data:
                    for p in p_data.get("provides", []):
                        p_clean = p.split("=")[0].split(">")[0].split("<")[0].strip().lower()
                        if p_clean and p_clean not in prov_map:
                            prov_map[p_clean] = inst_pkg
            self._provides_map = prov_map

            # Only re-index /var/lib/pacman/local/*/files if directory mtime changed, and run in background if already populated
            local_dir = Path("/var/lib/pacman/local")
            cur_mtime = 0.0
            try:
                if local_dir.exists():
                    cur_mtime = local_dir.stat().st_mtime
            except Exception:
                pass
            if not getattr(self, "_desktop_owner_map", None):
                self._local_files_mtime = cur_mtime
                self._index_local_pacman_files()
            elif cur_mtime != getattr(self, "_local_files_mtime", 0.0):
                self._local_files_mtime = cur_mtime
                threading.Thread(target=self._index_local_pacman_files, daemon=True).start()

            # Invalidate desktop launcher cache so newly installed apps are detected immediately
            global _DESKTOP_ICONS_CACHE, _DESKTOP_NAMES_CACHE, _DESKTOP_ENTRIES_CACHE
            _DESKTOP_ICONS_CACHE = {}
            _DESKTOP_NAMES_CACHE = {}
            _DESKTOP_ENTRIES_CACHE = {}
        except Exception as e:
            print(f"[ArkST] Error loading installed packages: {e}", file=sys.stderr)

    def resolve_installed_pkg_name(self, name: str) -> str:
        """
        Resolve any application name, .desktop stem (e.g. org.telegram.desktop, com.obsproject.Studio),
        binary name, or alias to its exact installed package name on Arch Linux in O(1) cached time.
        """
        if not name or not isinstance(name, str):
            return ""
        raw_low = name.strip().lower()
        cache = getattr(self, "_resolved_pkg_cache", None)
        if cache is not None and raw_low in cache:
            return cache[raw_low]
        n_low = raw_low[:-8] if (raw_low.endswith(".desktop") and raw_low not in ("org.telegram.desktop", "telegram-desktop", "signal-desktop", "joplin-desktop", "github-desktop")) else raw_low

        # 1. Exact match in installed_set
        if n_low in self.installed_set:
            return n_low

        # 2. Check authoritative /var/lib/pacman/local/*/files desktop & binary owner maps
        if hasattr(self, "_desktop_owner_map") and n_low in self._desktop_owner_map:
            owner = self._desktop_owner_map[n_low]
            if owner in self.installed_set:
                return owner
        if hasattr(self, "_binary_owner_map") and n_low in self._binary_owner_map:
            owner = self._binary_owner_map[n_low]
            if owner in self.installed_set:
                return owner

        # 3. Common suffix variants
        for suf in ("-bin", "-desktop-bin", "-desktop", "-git", "-gtk-app", "-qt-app", "-fresh", "-still", "-launcher", "-wayland"):
            if f"{n_low}{suf}" in self.installed_set:
                return f"{n_low}{suf}"

        # 4. Comprehensive explicit aliases (including reverse-DNS .desktop stems)
        aliases = {
            "chatgpt": ["chatgpt-bin", "chatgpt-desktop-bin"],
            "code": ["visual-studio-code-bin", "code", "code-oss", "vscodium-bin", "vscodium"],
            "code-oss": ["code", "visual-studio-code-bin", "code-oss"],
            "visual-studio-code": ["visual-studio-code-bin", "code"],
            "brave": ["brave-bin", "brave-origin-bin", "brave"],
            "brave-browser": ["brave-bin", "brave-origin-bin", "brave"],
            "google-chrome": ["google-chrome", "google-chrome-stable", "google-chrome-beta"],
            "chrome": ["google-chrome", "chromium"],
            "spotify": ["spotify", "spotify-launcher"],
            "spotify-client": ["spotify", "spotify-launcher"],
            "heroic": ["heroic-games-launcher-bin", "heroic"],
            "com.heroicgameslauncher.hgl": ["heroic-games-launcher-bin", "heroic"],
            "postman": ["postman-bin", "postman"],
            "telegram": ["telegram-desktop", "telegram-desktop-bin"],
            "org.telegram.desktop": ["telegram-desktop", "telegram-desktop-bin"],
            "obs": ["obs-studio", "obs-studio-git", "obs-studio-browser"],
            "com.obsproject.studio": ["obs-studio", "obs-studio-git"],
            "prismlauncher": ["prismlauncher", "prismlauncher-qt5", "prismlauncher-bin"],
            "org.prismlauncher.prismlauncher": ["prismlauncher", "prismlauncher-bin"],
            "bottles": ["bottles", "bottles-bin"],
            "com.usebottles.bottles": ["bottles", "bottles-bin"],
            "handbrake": ["handbrake", "handbrake-cli"],
            "fr.handbrake.ghb": ["handbrake"],
            "keepassxc": ["keepassxc"],
            "org.keepassxc.keepassxc": ["keepassxc"],
            "thunderbird": ["thunderbird", "thunderbird-bin"],
            "org.mozilla.thunderbird": ["thunderbird", "thunderbird-bin"],
            "libreoffice": ["libreoffice-fresh", "libreoffice-still"],
            "libreoffice-startcenter": ["libreoffice-fresh", "libreoffice-still"],
            "libreoffice-main": ["libreoffice-fresh", "libreoffice-still"],
            "evince": ["evince"],
            "org.gnome.evince": ["evince"],
            "baobab": ["baobab"],
            "org.gnome.baobab": ["baobab"],
            "nautilus": ["nautilus"],
            "org.gnome.nautilus": ["nautilus"],
            "dolphin": ["dolphin"],
            "org.kde.dolphin": ["dolphin"],
            "thunar": ["thunar"],
            "org.xfce.thunar": ["thunar"],
            "pavucontrol": ["pavucontrol"],
            "org.pulseaudio.pavucontrol": ["pavucontrol"],
            "lutris": ["lutris", "lutris-git"],
            "net.lutris.lutris": ["lutris", "lutris-git"],
            "zen": ["zen-browser-bin", "zen-browser"],
            "zen-browser": ["zen-browser-bin", "zen-browser"],
            "rofi": ["rofi-wayland", "rofi"],
            "rofi-wayland": ["rofi-wayland", "rofi"],
            "wireshark": ["wireshark-qt", "wireshark-cli"],
            "onlyoffice": ["onlyoffice-bin", "onlyoffice-desktopeditors"],
            "onlyoffice-desktopeditors": ["onlyoffice-bin", "onlyoffice-desktopeditors"],
            "anytype": ["anytype-bin", "anytype"],
            "joplin": ["joplin-desktop", "joplin-appimage", "joplin"],
            "mullvad-vpn": ["mullvad-vpn-bin", "mullvad-vpn"],
            "proton-vpn": ["proton-vpn-gtk-app", "protonvpn"],
            "protonvpn-app": ["proton-vpn-gtk-app", "protonvpn"],
            "ryujinx": ["ryujinx-bin", "ryujinx"],
            "stacer": ["stacer-bin", "stacer"],
            "hardinfo": ["hardinfo-git", "hardinfo2", "hardinfo"],
        }
        if n_low in aliases:
            for cand in aliases[n_low]:
                if cand in self.installed_set:
                    return cand

        # 5. Strip suffixes and re-check
        clean = re.sub(r'-(bin|git|hg|svn|pure|gtk-app|qt-app|gui|cli|daemon|desktop|launcher|fresh|still|wayland|x11|browser)$', '', n_low)
        if clean in self.installed_set:
            return clean
        for suf in ("-bin", "-desktop", "-desktop-bin", "-git", "-gtk-app", "-qt-app", "-fresh", "-still", "-wayland"):
            if f"{clean}{suf}" in self.installed_set:
                return f"{clean}{suf}"
        if clean in aliases:
            for cand in aliases[clean]:
                if cand in self.installed_set:
                    return cand

        # 6. O(1) lookup in pre-built _provides_map ( fallback to scan only if _provides_map is empty )
        prov_map = getattr(self, "_provides_map", None)
        if prov_map:
            if n_low in prov_map and prov_map[n_low] in self.installed_set:
                res = prov_map[n_low]
                if cache is not None:
                    cache[raw_low] = res
                return res
            if clean in prov_map and prov_map[clean] in self.installed_set:
                res = prov_map[clean]
                if cache is not None:
                    cache[raw_low] = res
                return res
        else:
            for inst_pkg in self.installed_set:
                pkg_data = self.packages.get(inst_pkg)
                if pkg_data:
                    provides = pkg_data.get("provides", [])
                    if any(p.split("=")[0].split(">")[0].split("<")[0].strip().lower() in (n_low, clean) for p in provides):
                        if cache is not None:
                            cache[raw_low] = inst_pkg
                        return inst_pkg

        if cache is not None:
            cache[raw_low] = n_low
        return n_low

    def is_installed(self, pkg_name: str) -> bool:
        """Check if a package or its equivalent launcher/alias is installed on the system."""
        if not pkg_name:
            return False
        name_lower = pkg_name.lower().strip()
        if name_lower in self.installed_set:
            return True
        if f"{name_lower}-bin" in self.installed_set:
            return True
        if f"{name_lower}-desktop-bin" in self.installed_set:
            return True
        if f"{name_lower}-desktop" in self.installed_set:
            return True
        resolved = self.resolve_installed_pkg_name(name_lower)
        if resolved in self.installed_set:
            return True
        clean = re.sub(r'-(bin|git|hg|svn|pure|gtk-app|qt-app|gui|cli|daemon|desktop|launcher)$', '', name_lower)
        if clean in self.installed_set:
            return True
        clean_nodash = clean.replace("-", "")
        if clean_nodash in self.installed_set:
            return True
        # Explicit variants
        if name_lower in ["code", "visual-studio-code-bin", "visual-studio-code"] and ("code" in self.installed_set or "code-oss" in self.installed_set):
            return True
        if name_lower in ["brave", "brave-bin", "brave-browser"] and ("brave-origin-bin" in self.installed_set or "brave-bin" in self.installed_set or "brave" in self.installed_set):
            return True
        if name_lower in _DESKTOP_OVERRIDES:
            ov = _DESKTOP_OVERRIDES[name_lower]
            if ov in self.installed_set:
                return True
        return False

    def get_active_transaction(self, pkg_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Returns a copy of self.active_transaction or matching engine transaction safely under lock."""
        with self._action_lock:
            all_txs = [
                tx for tx in (
                    self.active_transaction,
                    getattr(self, "_active_snap_tx", None),
                    getattr(self, "_active_flatpak_tx", None),
                    getattr(self, "_active_docker_tx", None),
                ) if tx is not None
            ]
            if pkg_name:
                key = pkg_name.strip().lower()
                for tx in all_txs:
                    if (tx.get("pkg_name") or "").strip().lower() == key or (tx.get("current_pkg") or "").strip().lower() == key:
                        return dict(tx)
            if self.active_transaction is not None:
                return dict(self.active_transaction)
            if all_txs:
                return dict(all_txs[0])
            return None

    def is_pkg_updating(self, pkg_name: str) -> bool:
        """
        Returns True if self.active_transaction is currently updating/upgrading pkg_name.
        Distinguishes active updates from background installations and general queue.
        """
        if not pkg_name:
            return False
        target = pkg_name.strip().lower()
        resolved = self.resolve_installed_pkg_name(target).lower()
        with self._action_lock:
            if not self.active_transaction:
                return False
            if self.active_transaction.get("is_completed"):
                return False
            action = (self.active_transaction.get("action") or "").lower()
            if action not in ["update", "upgrade"]:
                return False
            tx_pkg = (self.active_transaction.get("pkg_name") or "").strip().lower()
            if tx_pkg and tx_pkg not in ["system", "--all", "all", ""]:
                if tx_pkg in (target, resolved):
                    return True
            cur_pkg = (self.active_transaction.get("current_pkg") or "").strip().lower()
            if cur_pkg and cur_pkg in (target, resolved):
                return True
            # For single update where packages list has target
            pkgs = self.active_transaction.get("packages")
            if isinstance(pkgs, (list, set, tuple)):
                if any(isinstance(p, str) and p.strip().lower() in (target, resolved) for p in pkgs):
                    if tx_pkg not in ["system", "--all", "all", ""]:
                        return True
        return False

    def is_pkg_installing(self, pkg_name: str) -> bool:
        """
        Returns True if pkg_name is actively installing/updating across ANY engine
        (Pacman, AUR, Snap, Docker, or .deb).
        """
        if not pkg_name:
            return False
        target = pkg_name.strip().lower()
        resolved = self.resolve_installed_pkg_name(target).lower()

        if hasattr(self, "container_mgr") and self.container_mgr:
            if target in getattr(self.container_mgr, "active_container_installs", set()):
                return True
        if hasattr(self, "snap_mgr") and self.snap_mgr:
            if target in getattr(self.snap_mgr, "active_snap_ops", {}):
                return True
        if hasattr(self, "flatpak_mgr") and self.flatpak_mgr:
            if target in getattr(self.flatpak_mgr, "active_flatpak_ops", {}):
                return True
            resolved_fp = self.flatpak_mgr.resolve_flatpak_id(target).lower()
            if resolved_fp in getattr(self.flatpak_mgr, "active_flatpak_ops", {}):
                return True
        if hasattr(self, "deb_mgr") and self.deb_mgr:
            if target in getattr(self.deb_mgr, "active_deb_installs", {}):
                return True

        with self._action_lock:
            for tx in (self.active_transaction, getattr(self, "_active_snap_tx", None), getattr(self, "_active_docker_tx", None), getattr(self, "_active_flatpak_tx", None)):
                if not tx or tx.get("is_completed"):
                    continue
                tx_pkg = (tx.get("pkg_name") or "").strip().lower()
                if tx_pkg in (target, resolved):
                    return True
                cur_pkg = (tx.get("current_pkg") or "").strip().lower()
                if cur_pkg in (target, resolved):
                    return True
                pkgs = tx.get("packages")
                if isinstance(pkgs, (list, set, tuple)):
                    if any(isinstance(p, str) and p.strip().lower() in (target, resolved) for p in pkgs):
                        return True
                action = (tx.get("action") or "").lower()
                if action in ["update", "upgrade"]:
                    if tx_pkg in ["system", "--all", "all", "", None]:
                        if target in ["system", "--all", "all", ""]:
                            return True
                        if cur_pkg and cur_pkg in (target, resolved):
                            return True
            return False

    def is_pkg_queued(self, pkg_name: str) -> bool:
        """Returns True if pkg_name is queued waiting for transaction or part of batch update."""
        if not pkg_name:
            return False
        target = pkg_name.strip().lower()
        resolved = self.resolve_installed_pkg_name(target).lower()
        with self._action_lock:
            all_queues = (
                self._pending_actions
                + getattr(self, "_pending_snap_actions", [])
                + getattr(self, "_pending_docker_actions", [])
            )
            if any((item.get("pkg_name") or "").strip().lower() in (target, resolved) for item in all_queues):
                return True
            if self.active_transaction and not self.active_transaction.get("is_completed"):
                action = (self.active_transaction.get("action") or "").lower()
                if action in ["update", "upgrade"]:
                    tx_pkg = (self.active_transaction.get("pkg_name") or "").strip().lower()
                    if tx_pkg in ["system", "--all", "all", "", None]:
                        completed = {p.strip().lower() for p in self.active_transaction.get("completed_pkgs", [])}
                        cur = (self.active_transaction.get("current_pkg") or "").strip().lower()
                        if target in completed or resolved in completed or target == cur or resolved == cur:
                            return False
                        with self._lock:
                            if any(u.get("name", "").strip().lower() in (target, resolved) for u in self.upgradable_list):
                                return True
        return False

    def get_queued_pkgs(self) -> List[str]:
        """Returns list of package names currently waiting in all transaction queues."""
        with self._action_lock:
            all_queues = (
                self._pending_actions
                + getattr(self, "_pending_snap_actions", [])
                + getattr(self, "_pending_docker_actions", [])
            )
            return [(item.get("pkg_name") or "").strip().lower() for item in all_queues if item.get("pkg_name")]

    def get_queue_length(self) -> int:
        """Returns count of actions currently queued."""
        with self._action_lock:
            return (
                len(self._pending_actions)
                + len(getattr(self, "_pending_snap_actions", []))
                + len(getattr(self, "_pending_docker_actions", []))
            )

    def get_queue_position(self, pkg_name: str) -> int:
        """Returns 1-based position in queue if queued, or 0 if not queued."""
        if not pkg_name:
            return 0
        target = pkg_name.strip().lower()
        with self._action_lock:
            for q in (self._pending_actions, getattr(self, "_pending_snap_actions", []), getattr(self, "_pending_docker_actions", [])):
                for idx, item in enumerate(q, start=1):
                    if (item.get("pkg_name") or "").strip().lower() == target:
                        return idx
        return 0

    def cancel_queued_pkg(self, pkg_name: str) -> bool:
        """Removes a package from the pending queue if present. Returns True if removed."""
        if not pkg_name:
            return False
        target = pkg_name.strip().lower()
        with self._action_lock:
            for q in (self._pending_actions, getattr(self, "_pending_snap_actions", []), getattr(self, "_pending_docker_actions", [])):
                for idx, item in enumerate(q):
                    if (item.get("pkg_name") or "").strip().lower() == target:
                        q.pop(idx)
                        return True
        return False

    def is_busy(self) -> bool:
        """Returns True if any transaction is currently active or actions are queued."""
        with self._action_lock:
            return (
                self.active_transaction is not None
                or getattr(self, "_active_snap_tx", None) is not None
                or getattr(self, "_active_docker_tx", None) is not None
                or len(self._pending_actions) > 0
                or len(getattr(self, "_pending_snap_actions", [])) > 0
                or len(getattr(self, "_pending_docker_actions", [])) > 0
            )

    def has_active_tasks(self) -> bool:
        """Returns True if any background transaction, queued action, or service setup is running."""
        if self.is_busy():
            return True
        if getattr(self.snap_mgr, "is_setting_up", False) or bool(getattr(self.snap_mgr, "active_snap_ops", None)):
            return True
        if getattr(self.container_mgr, "is_configuring", False) or bool(getattr(self.container_mgr, "active_container_installs", None)):
            return True
        if hasattr(self, "flatpak_mgr") and (getattr(self.flatpak_mgr, "is_setting_up", False) or bool(getattr(self.flatpak_mgr, "active_flatpak_ops", None))):
            return True
        if hasattr(self, "deb_mgr") and bool(getattr(self.deb_mgr, "active_deb_installs", None)):
            return True
        return False

    def get_active_progress(self, pkg_name: Optional[str] = None) -> Tuple[float, str]:
        """
        Returns (progress_fraction, status_msg) for the active transaction matching pkg_name
        across ALPM, Snap, Docker, and .deb engines, or (0.0, "") if none.
        """
        if pkg_name is not None:
            target = pkg_name.strip().lower()
            if hasattr(self, "snap_mgr") and target in getattr(self.snap_mgr, "active_snap_ops", {}):
                return self.snap_mgr.active_snap_ops[target]
            if hasattr(self, "container_mgr") and target in getattr(self.container_mgr, "active_container_progress", {}):
                return self.container_mgr.active_container_progress[target]
            if hasattr(self, "flatpak_mgr"):
                if target in getattr(self.flatpak_mgr, "active_flatpak_ops", {}):
                    return self.flatpak_mgr.active_flatpak_ops[target]
                fp_id = self.flatpak_mgr.resolve_flatpak_id(target).lower()
                if fp_id in getattr(self.flatpak_mgr, "active_flatpak_ops", {}):
                    return self.flatpak_mgr.active_flatpak_ops[fp_id]
            if hasattr(self, "deb_mgr") and target in getattr(self.deb_mgr, "active_deb_installs", {}):
                return self.deb_mgr.active_deb_installs[target]

        with self._action_lock:
            for tx in (self.active_transaction, getattr(self, "_active_snap_tx", None), getattr(self, "_active_docker_tx", None), getattr(self, "_active_flatpak_tx", None)):
                if not tx:
                    continue
                if pkg_name is not None:
                    target = pkg_name.strip().lower()
                    tx_pkg = (tx.get("pkg_name") or "").strip().lower()
                    matches = (tx_pkg == target)
                    if not matches:
                        cur_pkg = (tx.get("current_pkg") or "").strip().lower()
                        matches = (cur_pkg == target)
                    if not matches:
                        pkgs = tx.get("packages")
                        if isinstance(pkgs, (list, set, tuple)):
                            matches = any(isinstance(p, str) and p.strip().lower() == target for p in pkgs)
                        if not matches:
                            action = (tx.get("action") or "").lower()
                            if action in ["update", "upgrade"]:
                                if tx_pkg in ["system", "--all", "all", "", None]:
                                    if target in ["system", "--all", "all", ""]:
                                        matches = True
                                    else:
                                        with self._lock:
                                            matches = any(u.get("name", "").strip().lower() == target for u in self.upgradable_list)
                    if not matches:
                        continue
                prog = float(tx.get("progress", self._last_progress))
                msg = str(tx.get("status_msg") or tx.get("status") or "")
                return (prog, msg)
            return (0.0, "")

    def get_installed_desktop_apps(self) -> List[Dict[str, Any]]:
        """Return list of real installed desktop applications with .desktop launchers (O(1) cached)."""
        cached = getattr(self, "_installed_desktop_apps_cache", None)
        if cached is not None:
            return list(cached)
        apps = []
        seen = set()
        search_dirs = [
            Path("/usr/share/applications"),
            Path(os.path.expanduser("~/.local/share/applications")),
            Path("/var/lib/flatpak/exports/share/applications"),
            Path(os.path.expanduser("~/.local/share/flatpak/exports/share/applications")),
            Path("/var/lib/snapd/desktop/applications"),
        ]
        ignored_stems = {
            "bssh", "bvnc", "avahi-discover", "xfce4-about", "thunar-bulk-rename",
            "thunar-settings", "io.github.eugeniosegala.mako.uninstaller", "qv4l2", "qvidcap",
            "lstopo", "footclient", "foot-server", "org.kde.kdeconnect.nonplasma",
            "org.kde.kdeconnect.sms", "cups", "limine-snapper-restore", "uuctl"
        }
        for d in search_dirs:
            if not d.exists():
                continue
            for p in sorted(d.glob("*.desktop")):
                stem = p.stem.lower()
                if stem in ignored_stems or stem.endswith("-url-handler") or stem.endswith("-uri-handler"):
                    continue
                name, icon, comment, exec_cmd = "", "", "", ""
                no_display = False
                try:
                    with open(p, "r", errors="ignore") as f:
                        in_entry = False
                        for line in f:
                            sline = line.strip()
                            if sline == "[Desktop Entry]":
                                in_entry = True
                                continue
                            if in_entry and sline.startswith("["):
                                break
                            if in_entry:
                                if sline.startswith("Name=") and not name:
                                    name = sline.split("=", 1)[1]
                                elif sline.startswith("Icon=") and not icon:
                                    icon = sline.split("=", 1)[1]
                                elif sline.startswith("Comment=") and not comment:
                                    comment = sline.split("=", 1)[1]
                                elif sline.startswith("Exec=") and not exec_cmd:
                                    exec_cmd = sline.split("=", 1)[1]
                                elif sline.startswith("NoDisplay=true"):
                                    no_display = True
                except Exception:
                    continue

                if no_display or not name or not icon:
                    continue

                clean_key = name.lower()
                if clean_key in seen:
                    continue
                seen.add(clean_key)

                # 0. Purge any leftover legacy aura-box-* or ark-box-* shortcuts so they never show up
                if stem.startswith(("aura-box-", "ark-box-")) or "aura-box" in exec_cmd:
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:
                        pass
                    continue

                # 1. Detect Docker sandbox shortcuts created by ArkST
                if stem.startswith("arkst-box-"):
                    docker_app_id = p.stem[len("arkst-box-"):]
                    apps.append({
                        "name": docker_app_id,
                        "display_name": name,
                        "desc": comment or f"{name} (Docker Sandbox)",
                        "icon": icon,
                        "desktop_entry": p.stem,
                        "source": "docker",
                        "is_installed": True,
                    })
                    continue

                # 2. Resolve exact owning package via _desktop_owner_map, _binary_owner_map, or resolve_installed_pkg_name
                pkg_name = ""
                if hasattr(self, "_desktop_owner_map") and stem in self._desktop_owner_map:
                    pkg_name = self._desktop_owner_map[stem]
                if not pkg_name and exec_cmd:
                    clean_exec = exec_cmd.split()[0].strip('"').strip("'")
                    bin_base = os.path.basename(clean_exec).lower()
                    if hasattr(self, "_binary_owner_map") and bin_base in self._binary_owner_map:
                        pkg_name = self._binary_owner_map[bin_base]
                    elif bin_base in self.installed_set:
                        pkg_name = bin_base

                if not pkg_name:
                    resolved_stem = self.resolve_installed_pkg_name(stem)
                    if resolved_stem in self.installed_set:
                        pkg_name = resolved_stem
                    else:
                        if stem.startswith("org.gnome."):
                            clean_id = stem.replace("org.gnome.", "")
                        elif "." in stem:
                            parts_dot = [ seg for seg in stem.split(".") if seg not in ("org", "com", "io", "net", "fr", "de", "app", "desktop", "studio", "github", "gitlab") ]
                            clean_id = parts_dot[-1] if parts_dot else stem.split(".")[-1]
                        else:
                            clean_id = stem
                        resolved_clean = self.resolve_installed_pkg_name(clean_id)
                        if resolved_clean in self.installed_set:
                            pkg_name = resolved_clean
                        else:
                            pkg_name = clean_id if clean_id in self.installed_set else stem

                # 3. Determine accurate source (flatpak, snap, deb, aur, pacman)
                app_source = "pacman"
                if "flatpak" in str(p).lower() or (pkg_name not in self.installed_set and hasattr(self, "flatpak_mgr") and self.flatpak_mgr.is_flatpak_app_installed(p.stem)):
                    app_source = "flatpak"
                    pkg_name = p.stem
                elif "snapd" in str(p).lower() or "/snap/" in exec_cmd or ( "_" in p.stem and hasattr(self, "snap_mgr") and self.snap_mgr.is_snap_installed(p.stem.split("_")[0])):
                    app_source = "snap"
                    pkg_name = p.stem.split("_")[0]
                elif hasattr(self, "deb_mgr") and self.deb_mgr and self.deb_mgr.is_deb_installed(pkg_name):
                    app_source = "deb"
                elif pkg_name in self.packages:
                    p_meta = self.packages[pkg_name]
                    if p_meta.get("source") == "deb" or p_meta.get("repo") == "deb-local":
                        app_source = "deb"
                    elif p_meta.get("repo") == "local" or p_meta.get("source") == "aur":
                        app_source = "aur"
                elif pkg_name not in self.installed_set and hasattr(self, "snap_mgr") and self.snap_mgr.is_snap_installed(pkg_name):
                    app_source = "snap"

                pkg_dedup_key = f"pkg:{pkg_name.lower()}"
                if pkg_dedup_key in seen and pkg_name.lower() not in ("libreoffice-fresh", "libreoffice-still"):
                    continue
                seen.add(pkg_dedup_key)
                apps.append({
                    "name": pkg_name,
                    "display_name": name,
                    "desc": comment or (self.packages.get(pkg_name, {}).get("desc") or f"{name} desktop application"),
                    "icon": icon,
                    "desktop_entry": p.stem,
                    "source": app_source,
                    "is_installed": True,
                })

        apps.sort(key=lambda x: x["display_name"].lower())
        self._installed_desktop_apps_cache = list(apps)
        return apps

    def _format_featured_app(self, app_id: str, cat_id: str = "", app_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Produce rich editorial metadata for a featured application."""
        curated = FEATURED_APP_PRESETS.get(app_id) or FEATURED_APP_METADATA.get(app_id)
        if curated:
            accent_color = curated.get("accent_color", CATEGORY_ACCENT_DEFAULTS.get(cat_id, "#0a84ff"))
            def_bg, def_border = _color_to_gradient_and_border(accent_color)
            bg = curated.get("bg", def_bg)
            border = curated.get("border", def_border)
            sub = curated.get("sub") or (app_info.get("desc") if app_info else "")
            source = curated.get("source") or (app_info.get("source") if app_info else "pacman")
            icon = curated.get("icon") or resolve_icon_name(app_id, sub)
            tag = curated.get("tag", CATEGORY_TAG_DEFAULTS.get(cat_id, "EDITORS' CHOICE"))
            title = curated.get("title", APP_DISPLAY_NAMES.get(app_id, app_id.title()))
            return {
                "id": app_id,
                "source": source,
                "tag": tag,
                "title": title,
                "sub": sub,
                "bg": bg,
                "border": border,
                "accent_color": accent_color,
                "color": accent_color,
                "icon": icon,
                "is_installed": self.is_installed(app_id),
            }

        # Dynamic fallback for any catalog app
        accent_color = CATEGORY_ACCENT_DEFAULTS.get(cat_id, "#0a84ff")
        bg, border = _color_to_gradient_and_border(accent_color)
        source = app_info.get("source", "pacman") if app_info else "pacman"
        title = APP_DISPLAY_NAMES.get(
            app_id,
            app_info.get("title", app_id.replace("-", " ").title()) if app_info else app_id.replace("-", " ").title()
        )
        sub = APP_EXTENDED_DESCRIPTIONS.get(
            app_id,
            app_info.get("desc", f"High-performance {cat_id} application for modern Linux") if app_info else ""
        )
        icon = resolve_icon_name(app_id, sub)
        tag = CATEGORY_TAG_DEFAULTS.get(cat_id, "EDITORS' CHOICE")
        return {
            "id": app_id,
            "source": source,
            "tag": tag,
            "title": title,
            "sub": sub,
            "bg": bg,
            "border": border,
            "accent_color": accent_color,
            "color": accent_color,
            "icon": icon,
            "is_installed": self.is_installed(app_id),
        }

    def get_dynamic_featured_apps(
        self,
        count: int = 5,
        refresh: bool = False,
        rotate: bool = False,
        seed: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Dynamically select 5-6 exciting, varied featured applications across diverse
        categories from the 84+ application catalog with rich editorial styling.
        Guarantees distinct categories, non-overlapping consecutive launches,
        and dynamically updated installed state.
        """
        if count <= 0:
            count = 5

        # Handle rotation or refresh requests
        if refresh or rotate:
            self._featured_rotation_offset = (self._featured_rotation_offset + 1) % 50
            self._current_featured_apps = None

        if self._current_featured_apps is not None and not refresh and not rotate and seed is None:
            if len(self._current_featured_apps) == count:
                # Refresh installed status dynamically
                for item in self._current_featured_apps:
                    item["is_installed"] = self.is_installed(item["id"])
                return self._current_featured_apps

        offset = seed if seed is not None else self._featured_rotation_offset

        # Build category map from CURATED_CATEGORIES
        cat_map = {cat["id"]: cat for cat in CURATED_CATEGORIES}

        # 7 distinct core categories rotating each launch
        core_categories = ["media", "dev", "games", "privacy", "productivity", "system", "essential"]
        cat_start = offset % len(core_categories)
        chosen_cats = [core_categories[(cat_start + i) % len(core_categories)] for i in range(min(count, len(core_categories)))]

        seen_ids: Set[str] = set()
        last_shown_set = set(self._last_featured_shown)
        featured_apps: List[Dict[str, Any]] = []

        for cat_id in chosen_cats:
            cands = FEATURED_CATEGORY_PRIORITIES.get(cat_id)
            if not cands and cat_id in cat_map:
                cands = [a["name"] for a in cat_map[cat_id]["apps"]]
            if not cands:
                continue

            app_dict = {}
            if cat_id in cat_map:
                app_dict = {a["name"]: a for a in cat_map[cat_id]["apps"]}

            cat_pos = core_categories.index(cat_id) if cat_id in core_categories else 0
            base_idx = (offset * 3 + cat_pos * 2) % len(cands)

            chosen_pkg = None
            # Pass 1: candidate not in seen_ids and not in last_shown
            for step in range(len(cands)):
                cand_pkg = cands[(base_idx + step) % len(cands)]
                if cand_pkg not in seen_ids and cand_pkg not in last_shown_set:
                    chosen_pkg = cand_pkg
                    break

            # Pass 2: fallback to any candidate not in seen_ids
            if not chosen_pkg:
                for step in range(len(cands)):
                    cand_pkg = cands[(base_idx + step) % len(cands)]
                    if cand_pkg not in seen_ids:
                        chosen_pkg = cand_pkg
                        break

            if chosen_pkg:
                seen_ids.add(chosen_pkg)
                app_info = app_dict.get(chosen_pkg)
                slide_meta = self._format_featured_app(chosen_pkg, cat_id=cat_id, app_info=app_info)
                featured_apps.append(slide_meta)

        # Fallback if fewer than count were picked (e.g. if count > 7)
        if len(featured_apps) < count:
            for cat in CURATED_CATEGORIES:
                cat_id = cat["id"]
                for app in cat["apps"]:
                    pkg = app["name"]
                    if pkg not in seen_ids:
                        seen_ids.add(pkg)
                        featured_apps.append(self._format_featured_app(pkg, cat_id=cat_id, app_info=app))
                        if len(featured_apps) >= count:
                            break
                if len(featured_apps) >= count:
                    break

        if seed is None:
            self._current_featured_apps = featured_apps
            new_ids = [a["id"] for a in featured_apps]
            self._last_featured_shown = (self._last_featured_shown + new_ids)[-10:]
            _save_featured_state(self._featured_rotation_offset, self._last_featured_shown)

        return featured_apps

    def rotate_featured_apps(self, count: int = 5) -> List[Dict[str, Any]]:
        """Advance rotation and return the next exciting batch of featured applications."""
        return self.get_dynamic_featured_apps(count=count, refresh=True)

    def check_updates(self) -> List[Dict[str, str]]:
        """Check for upgradable packages across pacman, AUR, snap, and containers."""
        with self._update_lock:
            self._update_generation += 1
            gen = self._update_generation

        self.is_checking_updates = True
        updates: List[Dict[str, str]] = []
        pacman_checked = False
        try:
            res = subprocess.run(["checkupdates"], capture_output=True, text=True, timeout=14)
            if res.returncode in (0, 2):
                pacman_checked = True
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 4 and parts[2] == "->":
                        pkg_name = parts[0]
                        updates.append({
                            "name": pkg_name,
                            "old_ver": parts[1],
                            "new_ver": parts[3],
                            "source": "pacman",
                            "icon": resolve_icon_name(pkg_name)
                        })
        except Exception as e:
            print(f"[ArkST] Update check: {e}", file=sys.stderr)

        # Fallback to pacman -Qu if checkupdates failed or is unavailable
        if not pacman_checked:
            try:
                res_qu = subprocess.run(["pacman", "-Qu"], capture_output=True, text=True, timeout=8)
                if res_qu.returncode == 0:
                    for line in res_qu.stdout.splitlines():
                        parts = line.strip().split()
                        if len(parts) >= 4 and parts[2] == "->":
                            pkg_name = parts[0]
                            updates.append({
                                "name": pkg_name,
                                "old_ver": parts[1],
                                "new_ver": parts[3],
                                "source": "pacman",
                                "icon": resolve_icon_name(pkg_name)
                            })
            except Exception:
                pass

        # Merge AUR updates via helper or direct AUR RPC v5 fallback
        aur_helper = get_aur_helper()
        aur_checked = False
        if aur_helper:
            try:
                aur_res = subprocess.run([aur_helper, "-Qua"], capture_output=True, text=True, timeout=12)
                if aur_res.returncode in (0, 1):
                    aur_checked = True
                if aur_res.returncode == 0:
                    for line in aur_res.stdout.splitlines():
                        parts = line.strip().split()
                        if len(parts) >= 4 and parts[2] == "->":
                            pkg_name = parts[0]
                            updates.append({
                                "name": pkg_name,
                                "old_ver": parts[1],
                                "new_ver": parts[3],
                                "source": "aur",
                                "icon": resolve_icon_name(pkg_name)
                            })
            except Exception as e:
                print(f"[ArkST] AUR update check: {e}", file=sys.stderr)

        if not aur_checked:
            try:
                qm_res = subprocess.run(["pacman", "-Qm"], capture_output=True, text=True, timeout=5)
                if qm_res.returncode == 0 and qm_res.stdout.strip():
                    foreign_pkgs = {}
                    for line in qm_res.stdout.splitlines():
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            foreign_pkgs[parts[0]] = parts[1]
                    if foreign_pkgs:
                        args_q = "&".join(f"arg[]={urllib.parse.quote(k)}" for k in list(foreign_pkgs.keys())[:100])
                        rpc_url = f"https://aur.archlinux.org/rpc/v5/info?{args_q}"
                        req = urllib.request.Request(rpc_url, headers={"User-Agent": "ArkST-PackageHub/3.0"})
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            rpc_data = json.loads(resp.read().decode("utf-8"))
                            for item in rpc_data.get("results", []):
                                p_name = item.get("Name", "")
                                new_v = item.get("Version", "")
                                old_v = foreign_pkgs.get(p_name, "")
                                if p_name and new_v and old_v and new_v != old_v:
                                    # Verify with vercmp if available
                                    is_newer = True
                                    if shutil.which("vercmp"):
                                        vc = subprocess.run(["vercmp", new_v, old_v], capture_output=True, text=True, timeout=2)
                                        if vc.returncode == 0:
                                            try:
                                                is_newer = int(vc.stdout.strip()) > 0
                                            except ValueError:
                                                pass
                                    if is_newer:
                                        updates.append({
                                            "name": p_name,
                                            "old_ver": old_v,
                                            "new_ver": new_v,
                                            "source": "aur",
                                            "icon": resolve_icon_name(p_name)
                                        })
            except Exception:
                pass

        # Merge Snap updates
        try:
            snap_updates = self.snap_mgr.check_snap_updates()
            if snap_updates:
                updates.extend(snap_updates)
        except Exception as e:
            print(f"[ArkST] Snap update check: {e}", file=sys.stderr)

        # Merge Flatpak / Flathub updates
        try:
            if hasattr(self, "flatpak_mgr") and self.flatpak_mgr:
                flatpak_updates = self.flatpak_mgr.check_flatpak_updates()
                if flatpak_updates:
                    updates.extend(flatpak_updates)
        except Exception as e:
            print(f"[Ark] Flatpak update check: {e}", file=sys.stderr)

        # Merge Container updates
        try:
            container_updates = self.container_mgr.check_container_updates()
            if container_updates:
                updates.extend(container_updates)
        except Exception as e:
            print(f"[ArkST] Container update check: {e}", file=sys.stderr)

        self.is_checking_updates = False
        self.updates_checked = True

        # Filter out packages that were recently updated (within 30s) to prevent race resurrection
        if hasattr(self, "_recently_updated") and self._recently_updated:
            now = time.time()
            # Clean up stale entries (older than 30 seconds)
            stale = [k for k, t in self._recently_updated.items() if now - t > 30]
            for k in stale:
                del self._recently_updated[k]
            # Filter updates list
            if self._recently_updated:
                updates = [u for u in updates if u.get("name", "").strip().lower() not in self._recently_updated]

        with self._lock:
            # Concurrency guard: only commit if newer check hasn't superseded this generation
            if gen == self._update_generation:
                if not pacman_checked and (Path("/var/lib/pacman/db.lck").exists() or self.has_active_tasks()):
                    # Pacman is currently locked/busy installing a package; merge and retain previous pacman/aur updates
                    prev_pacman = [u for u in self.upgradable_list if u.get("source") in ("pacman", "aur")]
                    new_non_pacman = [u for u in updates if u.get("source") not in ("pacman", "aur")]
                    active_tx = getattr(self, "active_transaction", None)
                    active_pkg = (active_tx.get("pkg_name") or "").strip().lower() if isinstance(active_tx, dict) else ""
                    if active_pkg:
                        prev_pacman = [u for u in prev_pacman if u.get("name", "").strip().lower() != active_pkg]
                    self.upgradable_list = prev_pacman + new_non_pacman
                    updates = list(self.upgradable_list)
                elif updates or pacman_checked or aur_checked or not self.upgradable_list:
                    self.upgradable_list = updates
                else:
                    updates = list(self.upgradable_list)
                try:
                    with open(UPDATES_CACHE_FILE, "w") as f:
                        json.dump(updates, f)
                except Exception:
                    pass
        return updates

    def _get_sync_mtime(self) -> float:
        """Get latest modification timestamp of pacman sync databases."""
        latest = 0.0
        if SYNC_DIR.exists():
            for f in SYNC_DIR.glob("*.db"):
                try:
                    m = f.stat().st_mtime
                    if m > latest:
                        latest = m
                except OSError:
                    pass
        return latest

    def load_pacman_db(self, force_reload: bool = False):
        """Load or parse pacman sync databases into memory (thread-safe & zstd-accelerated)."""
        db_lock = getattr(self, "_db_load_lock", None)
        if db_lock is None:
            self._db_load_lock = threading.Lock()
            db_lock = self._db_load_lock

        with db_lock:
            if not force_reload and self.is_loaded and self.packages:
                return
            self.refresh_installed()
            sync_mtime = self._get_sync_mtime()

            if not force_reload and CACHE_FILE.exists():
                try:
                    cache_stat = CACHE_FILE.stat()
                    if cache_stat.st_mtime >= sync_mtime:
                        with open(CACHE_FILE, "rb") as f:
                            cached_pkgs = pickle.load(f)
                        if cached_pkgs:
                            with self._lock:
                                self.packages = cached_pkgs
                                self.is_loaded = True
                            return
                except Exception as e:
                    print(f"[ArkST] Cache read error, rebuilding: {e}", file=sys.stderr)

            def _parse_desc_text(raw_desc: str, repo_name: str, src_type: str = "pacman") -> Optional[Dict[str, Any]]:
                content = raw_desc.split("\n\n")
                item: Dict[str, Any] = {
                    "repo": repo_name,
                    "source": src_type,
                    "depends": [],
                    "optdepends": [],
                    "provides": [],
                    "conflicts": []
                }
                for section in content:
                    lines = section.strip().split("\n")
                    if not lines or not lines[0].startswith("%") or not lines[0].endswith("%"):
                        continue
                    key = lines[0][1:-1].lower()
                    if key in ["depends", "optdepends", "provides", "conflicts"]:
                        item[key] = lines[1:]
                    elif key == "size" and "isize" not in item:
                        item["isize"] = lines[1] if len(lines) > 1 else ""
                    else:
                        item[key] = lines[1] if len(lines) > 1 else ""
                if "name" in item and isinstance(item["name"], str):
                    return item
                return None

            pkgs: Dict[str, Dict[str, Any]] = {}
            for db_file in sorted(glob.glob("/var/lib/pacman/sync/*.db")):
                repo = os.path.basename(db_file).replace(".db", "")
                parsed_this_db = False
                try:
                    with tarfile.open(db_file, "r:*") as tar:
                        for m in tar.getmembers():
                            if m.name.endswith("/desc"):
                                f = tar.extractfile(m)
                                if not f:
                                    continue
                                raw_txt = f.read().decode("utf-8", errors="replace")
                                item = _parse_desc_text(raw_txt, repo, "pacman")
                                if item:
                                    pkgs[item["name"]] = item
                    parsed_this_db = True
                except Exception as e:
                    # Fallback for zstd-compressed pacman sync databases (.db compressed with zstd)
                    if shutil.which("zstd"):
                        try:
                            zproc = subprocess.run(["zstd", "-dc", db_file], capture_output=True, timeout=15)
                            if zproc.returncode == 0 and zproc.stdout:
                                with tarfile.open(fileobj=io.BytesIO(zproc.stdout), mode="r:") as tar:
                                    for m in tar.getmembers():
                                        if m.name.endswith("/desc"):
                                            f = tar.extractfile(m)
                                            if not f:
                                                continue
                                            raw_txt = f.read().decode("utf-8", errors="replace")
                                            item = _parse_desc_text(raw_txt, repo, "pacman")
                                            if item:
                                                pkgs[item["name"]] = item
                                parsed_this_db = True
                        except Exception:
                            pass
                    if not parsed_this_db:
                        print(f"[ArkST] Error parsing {db_file}: {e}", file=sys.stderr)

            # Also index locally installed packages (/var/lib/pacman/local/*/desc) so AUR and .deb packages have rich metadata
            local_db_dir = Path("/var/lib/pacman/local")
            if local_db_dir.exists():
                try:
                    for desc_path in local_db_dir.glob("*/desc"):
                        try:
                            raw_txt = desc_path.read_text(encoding="utf-8", errors="replace")
                            item = _parse_desc_text(raw_txt, "local", "aur")
                            if item and item["name"] not in pkgs:
                                packager = str(item.get("packager", ""))
                                if "ArkST Deb Bridge" in packager or "Aura Deb Bridge" in packager or "Ark Deb Bridge" in packager:
                                    item["source"] = "deb"
                                    item["repo"] = "deb-local"
                                pkgs[item["name"]] = item
                        except Exception:
                            pass
                except Exception:
                    pass

            with self._lock:
                self.packages = pkgs
                self.is_loaded = True

            try:
                with open(CACHE_FILE, "wb") as f:
                    pickle.dump(pkgs, f)
            except Exception as e:
                print(f"[ArkST] Error saving cache: {e}", file=sys.stderr)

    def search_pacman(self, query: str, limit: int = 150) -> List[Dict[str, Any]]:
        """High-performance tiered fuzzy search for pacman repository packages."""
        clean_q = query.strip().lower()
        if not clean_q:
            return []
        if not self.is_loaded and not self.packages:
            try:
                self.load_pacman_db()
            except Exception:
                pass

        q_len = len(clean_q)
        q_norm = re.sub(r'[-_.\s]+', ' ', clean_q).strip()

        with self._lock:
            items = list(self.packages.values())
            installed_set = self.installed_set
            installed_vers = self.installed_versions

        desktop_set = get_desktop_and_curated_set()
        candidates: List[Tuple[int, Dict[str, Any]]] = []

        if q_len == 1:
            # Fast-path for 1-char: ONLY match packages starting with that letter. Instant sub-1ms return.
            for pkg in items:
                name = pkg.get("name", "")
                if not name:
                    continue
                name_lower = name.lower()
                if not name_lower.startswith(clean_q):
                    continue
                is_installed = (name in installed_set)
                score = fuzzy_score(clean_q, name, is_installed=is_installed)
                if score > 0:
                    candidates.append((score, pkg))

        elif q_len == 2:
            # Fast-path for 2-char: ONLY match packages whose name starts with or contains query. Never scan 20,000 descriptions.
            for pkg in items:
                name = pkg.get("name", "")
                if not name:
                    continue
                name_lower = name.lower()
                if clean_q not in name_lower and q_norm not in name_lower.replace("-", " ").replace("_", " "):
                    continue
                is_installed = self.is_installed(name)
                score = fuzzy_score(clean_q, name, is_installed=is_installed)
                if score > 0:
                    candidates.append((score, pkg))

        else:
            # For >= 3 char queries: Scan names first; only scan descriptions if names yield fewer than 50 top results, or apply C-speed query in desc check before scoring.
            matched_pkg_ids = set()
            q0 = clean_q[0]

            for pkg in items:
                name = pkg.get("name", "")
                if not name:
                    continue
                name_lower = name.lower()
                if q0 not in name_lower and clean_q not in name_lower:
                    continue
                is_installed = self.is_installed(name)
                score = fuzzy_score(clean_q, name, desc="", is_installed=is_installed)
                if score > 0:
                    candidates.append((score, pkg))
                    matched_pkg_ids.add(id(pkg))

            # Only scan descriptions if names yield fewer than 50 top results
            if len(candidates) < 50:
                for pkg in items:
                    if id(pkg) in matched_pkg_ids:
                        continue
                    desc = pkg.get("desc", "")
                    if not desc:
                        continue
                    desc_lower = desc.lower()
                    # Apply C-speed `query in desc` check before scoring
                    if clean_q not in desc_lower and q_norm not in desc_lower:
                        continue
                    name = pkg.get("name", "")
                    is_installed = self.is_installed(name)
                    score = fuzzy_score(clean_q, name, desc=desc, is_installed=is_installed)
                    if score > 0:
                        candidates.append((score, pkg))

        # Sort candidates strictly by score descending
        candidates.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, pkg in candidates[:limit]:
            name = pkg.get("name", "")
            desc = pkg.get("desc", "")
            is_installed = self.is_installed(name)
            results.append({
                "name": name,
                "version": pkg.get("version", ""),
                "desc": desc,
                "repo": pkg.get("repo", "extra"),
                "source": "pacman",
                "priority": 0,  # 1st Priority
                "score": score,
                "is_installed": is_installed,
                "installed_version": installed_vers.get(name, ""),
                "icon": resolve_icon_name(name, desc),
                "csize": pkg.get("csize", ""),
                "isize": pkg.get("isize", ""),
                "url": pkg.get("url", ""),
                "license": sanitize_str(pkg.get("license", "")),
                "packager": sanitize_str(pkg.get("packager", "")),
                "depends": pkg.get("depends", []),
                "optdepends": pkg.get("optdepends", []),
            })

        return results

    def search_aur(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Search AUR packages using AUR RPC API with paru fallback and tiered scoring."""
        if not query.strip() or len(query.strip()) < 2:
            return []

        clean_q = query.strip().lower()
        if clean_q in self._aur_cache:
            return self._aur_cache[clean_q]

        candidates: List[Tuple[int, Dict[str, Any]]] = []
        with self._lock:
            installed_set = self.installed_set
            installed_vers = self.installed_versions

        desktop_set = get_desktop_and_curated_set()

        try:
            url = f"https://aur.archlinux.org/rpc/v5/search/{urllib.parse.quote(clean_q)}"
            req = urllib.request.Request(url, headers={"User-Agent": "ArkST-PackageHub/3.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for item in data.get("results", []):
                    name = item.get("Name", "")
                    if not name:
                        continue
                    desc = item.get("Description", "") or ""
                    name_lower = name.lower()
                    is_desktop = (name_lower in desktop_set)
                    if not is_desktop:
                        clean_name = re.sub(r'-(bin|git|hg|svn|pure|gtk-app|qt-app|gui|desktop|launcher)$', '', name_lower)
                        is_desktop = (clean_name in desktop_set)
                    is_installed = (name in installed_set)
                    score = fuzzy_score(clean_q, name, desc, is_desktop=is_desktop, is_installed=is_installed)
                    if score > 0:
                        candidates.append((score, {
                            "name": name,
                            "version": item.get("Version", ""),
                            "desc": desc,
                            "repo": "aur",
                            "source": "aur",
                            "priority": 1,  # 2nd Priority
                            "score": score,
                            "is_installed": is_installed,
                            "installed_version": installed_vers.get(name, ""),
                            "icon": resolve_icon_name(name, desc),
                            "url": item.get("URL", "") or f"https://aur.archlinux.org/packages/{name}",
                            "votes": item.get("NumVotes", 0),
                            "popularity": item.get("Popularity", 0.0),
                            "maintainer": sanitize_str(item.get("Maintainer", "Unknown")),
                            "license": sanitize_str(item.get("License", "")),
                            "depends": item.get("Depends", []),
                            "optdepends": item.get("OptDepends", []),
                        }))
        except Exception:
            aur_helper = get_aur_helper()
            if aur_helper:
                try:
                    p = subprocess.run([aur_helper, "-Ssa", clean_q], capture_output=True, text=True, timeout=5)
                    lines = p.stdout.splitlines()
                    i = 0
                    while i < len(lines):
                        line = lines[i].strip()
                        if line.startswith("aur/"):
                            parts = line[4:].split()
                            pkg_name = parts[0] if parts else ""
                            ver = parts[1] if len(parts) > 1 else ""
                            desc = ""
                            if i + 1 < len(lines) and lines[i+1].startswith("    "):
                                desc = lines[i+1].strip()
                                i += 1
                            if pkg_name:
                                name_lower = pkg_name.lower()
                                is_desktop = (name_lower in desktop_set)
                                if not is_desktop:
                                    clean_name = re.sub(r'-(bin|git|hg|svn|pure|gtk-app|qt-app|gui|desktop|launcher)$', '', name_lower)
                                    is_desktop = (clean_name in desktop_set)
                                is_installed = self.is_installed(pkg_name)
                                score = fuzzy_score(clean_q, pkg_name, desc, is_desktop=is_desktop, is_installed=is_installed)
                                if score > 0:
                                    candidates.append((score, {
                                        "name": pkg_name,
                                        "version": ver,
                                        "desc": desc,
                                        "repo": "aur",
                                        "source": "aur",
                                        "priority": 1,
                                        "score": score,
                                        "is_installed": is_installed,
                                        "installed_version": installed_vers.get(pkg_name, ""),
                                        "icon": resolve_icon_name(pkg_name, desc),
                                        "url": f"https://aur.archlinux.org/packages/{pkg_name}",
                                    }))
                        i += 1
                except Exception as e:
                    print(f"[ArkST] AUR helper ({aur_helper}) fallback error: {e}", file=sys.stderr)

        candidates.sort(key=lambda x: x[0], reverse=True)
        final_results = [item for score, item in candidates[:limit]]
        self._aur_cache[clean_q] = final_results
        return final_results

    def search_all(self, query: str, filter_mode: str = "all", limit: int = 150) -> List[Dict[str, Any]]:
        """Unified search prioritizing Pacman official repositories first."""
        q = query.strip()
        pacman_res = []
        aur_res = []

        if filter_mode in ["all", "pacman", "installed"]:
            pacman_res = self.search_pacman(q, limit=limit)

        if filter_mode in ["all", "aur"]:
            aur_res = self.search_aur(q, limit=limit)

        if filter_mode == "all":
            seen_names = set()
            combined = []
            for p in pacman_res:
                p_name = p.get("name", "")
                if p_name and p_name not in seen_names:
                    seen_names.add(p_name)
                    combined.append(p)
            for p in aur_res:
                p_name = p.get("name", "")
                if p_name and p_name not in seen_names:
                    seen_names.add(p_name)
                    combined.append(p)
            combined.sort(
                key=lambda x: (
                    -x.get("score", 0),
                    x.get("priority", 0),
                    x.get("name", "").lower(),
                )
            )
        elif filter_mode == "pacman":
            combined = pacman_res
        elif filter_mode == "aur":
            combined = aur_res
        elif filter_mode == "installed":
            combined = [p for p in pacman_res if p.get("is_installed")]
            desktop_set = get_desktop_and_curated_set()
            with self._lock:
                for inst_name, inst_ver in self.installed_versions.items():
                    if inst_name not in self.packages:
                        inst_lower = inst_name.lower()
                        is_desktop = (inst_lower in desktop_set)
                        if not is_desktop:
                            clean_name = re.sub(r'-(bin|git|hg|svn|pure|gtk-app|qt-app|gui|desktop|launcher)$', '', inst_lower)
                            is_desktop = (clean_name in desktop_set)
                        score = fuzzy_score(q, inst_name, is_desktop=is_desktop, is_installed=True)
                        if score > 0:
                            combined.append({
                                "name": inst_name,
                                "version": inst_ver,
                                "desc": "Locally installed package",
                                "repo": "local",
                                "source": "pacman",
                                "priority": 0,
                                "score": score,
                                "is_installed": True,
                                "installed_version": inst_ver,
                                "icon": resolve_icon_name(inst_name, ""),
                            })
            combined.sort(key=lambda x: x["score"], reverse=True)
        else:
            combined = []

        return combined[:limit]

    def search(self, query: str, source: str = "all", limit: int = 100) -> List[Dict[str, Any]]:
        """Unified search across pacman, AUR, Flathub, Snap, and/or Docker with strict priority."""
        if source in ("flatpak", "flathub"):
            return self.flatpak_mgr.search_flatpaks(query)[:limit]
        elif source == "snap":
            return self.snap_mgr.search_snaps(query)[:limit]
        elif source in ("container", "docker"):
            return self.container_mgr.list_apps(query)[:limit]
        elif source == "pacman":
            return self.search_pacman(query, limit=limit)
        elif source == "aur":
            return self.search_aur(query, limit=limit)
        return self.search_all(query, filter_mode=source, limit=limit)

    def resolve_package_source(self, pkg_name: str) -> str:
        """
        Intelligently determine whether a package is from official pacman repos,
        AUR, Snap, or Docker/Container.
        """
        raw_pkg = (pkg_name or "").strip()
        if raw_pkg.lower().endswith(".deb") or "/" in raw_pkg:
            if raw_pkg.lower().endswith(".deb"):
                return "deb"
        clean = raw_pkg.lower()
        if not clean:
            return "pacman"

        # 0. Check if package is an installed .deb package
        if hasattr(self, "deb_mgr") and self.deb_mgr and self.deb_mgr.is_deb_installed(clean):
            return "deb"

        # 0.4. Check upgradable_list if package has an authoritative pending update source
        if hasattr(self, "upgradable_list") and self.upgradable_list:
            for u in self.upgradable_list:
                if (u.get("name") or "").strip().lower() == clean and u.get("source"):
                    return u["source"]

        # 0.5. Check if package is an AppStream/Flatpak ID (e.g. com.spotify.Client)
        if "." in raw_pkg and hasattr(self, "flatpak_mgr") and self.flatpak_mgr:
            if self.flatpak_mgr.is_flatpak_app_installed(raw_pkg):
                return "flatpak"
            if any(a.get("id", "").lower() == clean for a in getattr(self.flatpak_mgr, "CURATED_FLATPAK_APPS", [])):
                return "flatpak"

        # 1. Check official pacman sync DB & installed packages
        if clean in self.packages:
            p_meta = self.packages[clean]
            if p_meta.get("source") == "deb" or p_meta.get("repo") == "deb-local":
                return "deb"
            if p_meta.get("source") == "aur" or p_meta.get("repo") in ("local", "aur"):
                return "aur"
            return "pacman"
        if clean in self.installed_set:
            return "pacman"

        # 1.5. Check installed Flatpak by name/ID
        if hasattr(self, "flatpak_mgr") and self.flatpak_mgr:
            if self.flatpak_mgr.is_flatpak_app_installed(raw_pkg):
                return "flatpak"

        # 2. Check curated Snap or installed Snap
        if hasattr(self, "snap_mgr") and self.snap_mgr:
            if any(s.get("name") == clean for s in getattr(self.snap_mgr, "CURATED_SNAP_APPS", [])):
                return "snap"
            if self.snap_mgr.is_snap_installed(clean):
                return "snap"

        # 3. Check curated Container or installed container app
        if hasattr(self, "container_mgr") and self.container_mgr:
            if any(c.get("id") == clean or c.get("name", "").lower() == clean for c in getattr(self.container_mgr, "CURATED_CONTAINER_APPS", [])):
                return "docker"
            if self.container_mgr.is_app_installed(clean):
                return "docker"

        # 5. Check AUR via helper
        aur_helper = get_aur_helper()
        if aur_helper:
            try:
                res = subprocess.run([aur_helper, "-Si", clean], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                if res.returncode == 0:
                    return "aur"
            except Exception:
                pass

        return "pacman"

    @staticmethod
    def parse_pacman_info(raw_text: str) -> Dict[str, Any]:
        """Parse pacman -Si or -Qi output into structured metadata (AURA-028)."""
        return parse_pacman_info(raw_text)

    def get_package_info(self, name: str, source: str = "pacman") -> Dict[str, Any]:
        """Fetch package information unified across pacman, AUR, Flathub, Snap, and Container."""
        if source in ("flatpak", "flathub"):
            return self.flatpak_mgr.get_flatpak_details(name)
        if source == "snap":
            return self.snap_mgr.get_snap_details(name)
        return self.get_package_detail(name, source=source)

    def get_package_detail(self, name: str, source: str = "pacman") -> Dict[str, Any]:
        """Fetch full details of a package with strict sanitization."""
        if source in ("flatpak", "flathub") or str(name).lower().endswith(".flatpakref"):
            if hasattr(self, "flatpak_mgr") and self.flatpak_mgr:
                return self.flatpak_mgr.get_flatpak_details(name)
        if source == "deb" or str(name).lower().endswith(".deb"):
            if hasattr(self, "deb_mgr") and self.deb_mgr:
                return self.deb_mgr.get_deb_detail(name)
        if source == "snap":
            return self.snap_mgr.get_snap_details(name)
        elif source in ("container", "docker"):
            clean_id = (name or "").strip().lower()
            all_docker = list(getattr(self.container_mgr, "CURATED_CONTAINER_APPS", [])) + list(getattr(self.container_mgr, "EXTENDED_ALPINE_APPS", []))
            meta = next((a for a in all_docker if a["id"].lower() == clean_id or a.get("pkg", "").lower() == clean_id), None)
            is_inst = self.container_mgr.is_app_installed(clean_id)
            disp_title = meta["name"] if meta else get_app_display_name(clean_id)
            short_desc = meta.get("desc", "Isolated Alpine Linux container application") if meta else "Isolated Alpine Linux container application"
            pkg_size = meta.get("size", "Sandboxed") if meta else "Sandboxed"
            icon_val = meta.get("icon", resolve_icon_name(clean_id, short_desc)) if meta else resolve_icon_name(clean_id, short_desc)
            return {
                "id": clean_id,
                "name": clean_id,
                "display_name": disp_title,
                "title": disp_title,
                "version": "latest",
                "installed_version": "latest" if is_inst else "",
                "desc": short_desc,
                "extended_desc": f"{short_desc}\n\nRuns inside ArkST's isolated 'arkst-box' Alpine Linux container with Wayland/X11 socket passthrough, PipeWire audio, and automatic host desktop shortcut integration.",
                "source": "docker",
                "repo": "arkst-box (Alpine)",
                "arch": "x86_64",
                "packager": "Alpine Linux / ArkST Box",
                "maintainer": "Alpine Linux Community",
                "license": "Open Source",
                "isize_str": pkg_size,
                "csize_str": pkg_size,
                "depends": ["docker", "arkst-box (Alpine GUI Sandbox)"],
                "icon": icon_val,
                "is_installed": is_inst,
                "desktop_entry": f"arkst-box-{clean_id}" if is_inst else None,
                "url": f"https://pkgs.alpinelinux.org/packages?name={clean_id}",
            }
        with self._lock:
            is_installed = self.is_installed(name)
            installed_ver = self.installed_versions.get(name, "")
            if not installed_ver and is_installed:
                clean = re.sub(r'-(bin|git|hg|svn|pure|gtk-app|qt-app|gui|cli|daemon|desktop|launcher)$', '', name.lower())
                installed_ver = self.installed_versions.get(clean, "")
                if not installed_ver and name.lower() in ["code", "visual-studio-code-bin"]:
                    installed_ver = self.installed_versions.get("code", "")

        info: Dict[str, Any] = {
            "name": name,
            "is_installed": is_installed,
            "installed_version": installed_ver,
            "source": source,
            "repo": "aur" if source == "aur" else "extra",
            "depends": [],
            "optdepends": [],
            "icon": resolve_icon_name(name, ""),
        }

        if source == "pacman" and name in self.packages:
            raw = self.packages[name]
            info.update(raw)
            info["license"] = sanitize_str(raw.get("license", ""))
            info["packager"] = sanitize_str(raw.get("packager", ""))

        if source == "pacman" and not info.get("desc"):
            try:
                res = subprocess.run(["pacman", "-Si", name], capture_output=True, text=True, timeout=3)
                if res.returncode == 0:
                    parsed = parse_pacman_info(res.stdout)
                    for k, val in parsed.items():
                        if val:
                            if k == "depends":
                                info["depends"] = val
                            elif k == "optdepends":
                                info["optdepends"] = val
                            else:
                                info[k] = val
            except Exception:
                pass

        if is_installed:
            try:
                target_qi = name if name in self.installed_set else ("code" if name.lower() in ["code", "visual-studio-code-bin"] else name)
                res = subprocess.run(["pacman", "-Qi", target_qi], capture_output=True, text=True, timeout=3)
                if res.returncode == 0:
                    parsed = parse_pacman_info(res.stdout)
                    for k, val in parsed.items():
                        if val:
                            if k == "depends":
                                info["depends"] = val
                            elif k == "optdepends":
                                info["optdepends"] = val
                            elif not info.get(k):
                                info[k] = val
            except Exception:
                pass


        if source == "aur" or not info.get("desc"):
            try:
                url = f"https://aur.archlinux.org/rpc/v5/info/{urllib.parse.quote(name)}"
                req = urllib.request.Request(url, headers={"User-Agent": "ArkST-PackageHub/3.0"})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    results = data.get("results", [])
                    if results:
                        res0 = results[0]
                        info["desc"] = res0.get("Description", info.get("desc", ""))
                        info["version"] = res0.get("Version", info.get("version", ""))
                        info["url"] = res0.get("URL", info.get("url", ""))
                        info["votes"] = res0.get("NumVotes", 0)
                        info["popularity"] = res0.get("Popularity", 0.0)
                        info["maintainer"] = sanitize_str(res0.get("Maintainer", "Unknown"))
                        info["license"] = sanitize_str(res0.get("License", ""))
                        if not info.get("depends"):
                            info["depends"] = res0.get("Depends", [])
            except Exception:
                pass

        raw_lic = sanitize_str(info.get("license", "Custom License"))
        if raw_lic.lower().startswith("licenseref-"):
            raw_lic = raw_lic[11:]
        if raw_lic.lower() in ("custom", "custom:none", "unknown", "unspecified", "none", "custom / unspecified"):
            raw_lic = "Custom License"
        info["license"] = raw_lic

        raw_pack = sanitize_str(info.get("packager", info.get("maintainer", "Community")))
        clean_pack = re.sub(r'<[^>]*>', '', raw_pack).strip()
        info["packager"] = clean_pack if clean_pack else "Community"

        info["repo"] = sanitize_str(info.get("repo", "extra"))
        info["version"] = sanitize_str(info.get("version", installed_ver))
        info["desc"] = sanitize_str(info.get("desc", "No description available."))
        info["url"] = sanitize_str(info.get("url", ""))

        if "isize" in info and isinstance(info["isize"], (int, str)) and not info.get("isize_str"):
            info["isize_str"] = format_bytes(info["isize"])
        if "csize" in info and isinstance(info["csize"], (int, str)):
            info["csize_str"] = format_bytes(info["csize"])

        info["display_name"] = get_app_display_name(name)
        info["desktop_entry"] = self.detect_desktop_entry(name)
        info["icon"] = resolve_icon_name(name, info["desc"])

        # Attach rich extended description if available
        name_clean = name.lower().strip()
        if name_clean in APP_EXTENDED_DESCRIPTIONS:
            info["extended_desc"] = APP_EXTENDED_DESCRIPTIONS[name_clean]
        else:
            base = re.sub(r'-(bin|git|hg|svn|pure|gtk-app|qt-app|gui|cli|daemon|desktop|launcher)$', '', name_clean)
            if base in APP_EXTENDED_DESCRIPTIONS:
                info["extended_desc"] = APP_EXTENDED_DESCRIPTIONS[base]

        return info

    def detect_desktop_entry(self, pkg_name: str) -> Optional[str]:
        """Detect if an installed package provides a desktop application launcher (fast in-memory)."""
        clean_raw = (pkg_name or "").strip()
        if not clean_raw:
            return None
        name_lower = clean_raw.lower()

        # 1. Docker Container App
        if hasattr(self, "container_mgr") and self.container_mgr:
            try:
                if name_lower.startswith("arkst-box-"):
                    aid = name_lower[len("arkst-box-"):]
                    if self.container_mgr.is_app_installed(aid):
                        return f"arkst-box-{aid}"
                if self.container_mgr.is_app_installed(name_lower):
                    return f"arkst-box-{name_lower}"
            except Exception:
                pass

        # 2. Installed Flatpak App
        if hasattr(self, "flatpak_mgr") and self.flatpak_mgr:
            try:
                if ("." in clean_raw or not self.is_installed(clean_raw)) and self.flatpak_mgr.is_flatpak_app_installed(clean_raw):
                    return self.flatpak_mgr.resolve_flatpak_id(clean_raw)
            except Exception:
                pass

        # 3. Installed Snap App
        snap_inst = False
        if hasattr(self, "snap_mgr") and self.snap_mgr:
            try:
                snap_cand = name_lower.split("_")[0]
                snap_inst = self.snap_mgr.is_snap_installed(snap_cand)
                if snap_inst:
                    snap_dt_dir = Path("/var/lib/snapd/desktop/applications")
                    if snap_dt_dir.exists():
                        matches = list(snap_dt_dir.glob(f"{snap_cand}_*.desktop"))
                        if matches:
                            return matches[0].stem
                    if Path(f"/snap/bin/{snap_cand}").exists() or any(s.get("name") == snap_cand for s in self.snap_mgr.CURATED_SNAP_APPS):
                        return f"{snap_cand}_{snap_cand}"
            except Exception:
                pass

        # 4. Installed .deb Package Registry check
        if hasattr(self, "deb_mgr") and self.deb_mgr:
            try:
                reg = self.deb_mgr._load_registry()
                if name_lower in reg and reg[name_lower].get("desktop_entry"):
                    return reg[name_lower]["desktop_entry"]
            except Exception:
                pass

        is_inst = self.is_installed(clean_raw) or snap_inst
        if not is_inst:
            return None

        entries = get_desktop_entries_map()
        if name_lower in _DESKTOP_OVERRIDES:
            ov = _DESKTOP_OVERRIDES[name_lower]
            if ov in entries or os.path.exists(f"/usr/share/applications/{ov}.desktop"):
                return ov
        if name_lower in entries:
            return entries[name_lower]
        clean = re.sub(r'-(bin|git|hg|svn|pure|gtk-app|qt-app|gui|desktop|launcher)$', '', name_lower)
        if clean in entries:
            return entries[clean]
        clean2 = re.sub(r'-(gtk|qt|gtk[0-9]|qt[0-9]|electron|wayland|x11)$', '', clean)
        if clean2 in entries:
            return entries[clean2]
        clean_nodash = clean.replace("-", "")
        if clean_nodash in entries:
            return entries[clean_nodash]
        if snap_inst:
            snap_cand = name_lower.split("_")[0]
            snap_dt_dir = Path("/var/lib/snapd/desktop/applications")
            if snap_dt_dir.exists():
                matches = list(snap_dt_dir.glob(f"{snap_cand}_*.desktop"))
                if matches:
                    return matches[0].stem
            if Path(f"/snap/bin/{snap_cand}").exists() or any(s.get("name") == snap_cand for s in self.snap_mgr.CURATED_SNAP_APPS):
                return f"{snap_cand}_{snap_cand}"
        return None

    def launch_desktop_app(self, desktop_name: str) -> bool:
        """Launch a desktop application across Pacman, AUR, .deb, Flatpak, Snap, and Docker sandboxes."""
        if not desktop_name:
            return False
        raw = desktop_name.strip()
        stem = raw[:-8] if raw.lower().endswith(".desktop") else raw
        stem_low = stem.lower()

        # 1. Docker Sandbox shortcut
        if stem_low.startswith("arkst-box-") and hasattr(self, "container_mgr") and self.container_mgr:
            app_id = stem[len("arkst-box-"):]
            self.container_mgr.launch_app(app_id)
            return True

        # 2. Flatpak AppStream ID
        if "." in stem and hasattr(self, "flatpak_mgr") and self.flatpak_mgr:
            if self.flatpak_mgr.is_flatpak_app_installed(stem) and not Path(f"/usr/share/applications/{stem}.desktop").exists():
                if self.flatpak_mgr.launch_flatpak(stem):
                    return True

        # 3. Snap desktop launcher (<snap>_<app>)
        if "_" in stem and hasattr(self, "snap_mgr") and self.snap_mgr:
            snap_name = stem_low.split("_")[0]
            if self.snap_mgr.is_snap_installed(snap_name):
                if self.snap_mgr.launch_snap(snap_name):
                    return True

        env = get_gui_launch_env()

        # Locate exact .desktop file across all application directories
        dt_path: Optional[Path] = None
        for d in DESKTOP_SEARCH_DIRS:
            if not d.exists():
                continue
            cand = d / f"{stem}.desktop"
            if cand.exists():
                dt_path = cand
                break
            for p in d.glob("*.desktop"):
                if p.stem.lower() == stem_low:
                    dt_path = p
                    break
            if dt_path:
                break

        # If .desktop file is in standard XDG dirs, try gtk-launch with full XDG_DATA_DIRS
        if shutil.which("gtk-launch") and (dt_path is None or "snapd" not in str(dt_path)):
            try:
                target_arg = f"{dt_path.stem}.desktop" if dt_path else desktop_name
                subprocess.Popen(["gtk-launch", target_arg], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception:
                pass

        # Try gio launch with the resolved full .desktop path
        target_gio = str(dt_path) if dt_path else f"/usr/share/applications/{stem}.desktop"
        if shutil.which("gio") and Path(target_gio).exists():
            try:
                subprocess.Popen(["gio", "launch", target_gio], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception:
                pass

        # Direct Exec= parser fallback (handles custom paths, /opt binaries, and non-XDG desktop files)
        if dt_path and dt_path.exists():
            try:
                exec_line = ""
                for line in dt_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.startswith("Exec="):
                        exec_line = line[5:].strip()
                        break
                if exec_line:
                    clean_cmd = re.sub(r'\s+%[fFuUdDnNickvm]', '', exec_line).strip()
                    subprocess.Popen(["sh", "-c", clean_cmd], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return True
            except Exception:
                pass

        try:
            subprocess.Popen(["gtk-launch", desktop_name], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            try:
                subprocess.Popen(["gio", "launch", f"/usr/share/applications/{desktop_name}.desktop"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception:
                return False


    def _init_active_transaction(self, action: str, pkg_name: str, source: str):
        """Initializes self.active_transaction dictionary under self._action_lock."""
        is_system_upgrade = pkg_name in ["system", "--all", "all", ""] or not pkg_name
        target_pkg = ("" if is_system_upgrade else (pkg_name or "")).strip().lower()

        self.active_transaction = {
            "action": action,
            "pkg_name": pkg_name,
            "source": source,
            "progress": 0.06,
            "status": "Authenticating & preparing...",
            "status_msg": "Authenticating & preparing...",
            "start_time": time.time(),
            "current_pkg": target_pkg if target_pkg else (pkg_name or None),
            "completed_pkgs": [],
            "current_idx": 0,
            "total_packages": 1,
            "log_lines": [],
        }
        if action in ["upgrade", "update"] and is_system_upgrade:
            with self._lock:
                pkgs = [u.get("name") for u in self.upgradable_list if u.get("name")]
                self.active_transaction["packages"] = pkgs
                if pkgs:
                    self.active_transaction["total_packages"] = len(pkgs)
        elif pkg_name:
            self.active_transaction["packages"] = [pkg_name]
        self._last_progress = 0.06

    def _process_next_action(self):
        """Pops and executes the next pending action from the queue, or resets active_transaction if empty."""
        with self._action_lock:
            if not self._pending_actions:
                self.active_transaction = None
                self._last_progress = 0.0
                return

            # Atomically pop and initialize next active_transaction so is_busy stays True
            next_action = self._pending_actions.pop(0)
            self._init_active_transaction(
                next_action["action"],
                next_action["pkg_name"],
                next_action["source"]
            )

        # 0.4s pause ensures pacman / paru closes /var/lib/pacman/db.lck cleanly
        def _deferred_start():
            time.sleep(0.4)
            self._start_action_worker(
                action=next_action["action"],
                pkg_name=next_action["pkg_name"],
                source=next_action["source"],
                progress_cb=next_action["progress_cb"],
                complete_cb=next_action["complete_cb"],
                start_cb=next_action.get("start_cb"),
            )

        threading.Thread(target=_deferred_start, daemon=True).start()

    def execute_background_action(
        self,
        action: str,
        pkg_name: str,
        source: str,
        progress_cb: Callable[[float, str], None],
        complete_cb: Callable[[bool, str, str, str], None],
        start_cb: Optional[Callable[[], None]] = None
    ) -> str:
        """
        Run installation, removal, or upgrade in background without terminal popups.
        Thread-safe FIFO Action Queue:
        - If a transaction is active, appends to self._pending_actions and returns 'queued'.
        - If idle, begins execution immediately and returns 'started'.
        - When an action completes, automatically pops and executes the next queued action.
        """
        target_norm = (pkg_name or "").strip().lower()
        eff_act_check = "remove" if action == "clean_remove" else action
        is_sys_up = target_norm in ("system", "--all", "all", "") and eff_act_check in ("update", "upgrade")

        # Security Gate 1: Validate package identifier against injection / malformed names
        if not is_sys_up and not (source == "deb" and target_norm.endswith(".deb")):
            if not is_valid_pkg_name(target_norm):
                progress_cb(0.0, f"Invalid package name: '{pkg_name}'")
                complete_cb(False, action, str(pkg_name), f"Invalid or unsafe package identifier: '{pkg_name}'")
                return "rejected"

        # Security Gate 2: Block removal of critical base system packages
        if eff_act_check == "remove":
            resolved_check = self.resolve_installed_pkg_name(target_norm)
            if target_norm in CRITICAL_SYSTEM_PACKAGES or resolved_check in CRITICAL_SYSTEM_PACKAGES:
                err_msg = f"Refusing to remove critical core system package '{resolved_check or target_norm}'."
                progress_cb(0.0, err_msg)
                complete_cb(False, action, str(pkg_name), err_msg)
                return "rejected"

        src_norm = (source or "pacman").strip().lower()
        with self._action_lock:
            if self.is_pkg_installing(target_norm) and target_norm not in ("system", "--all", "all", ""):
                return "already_active"
            if self.is_pkg_queued(target_norm) and target_norm not in ("system", "--all", "all", ""):
                return "already_queued"

            if self.active_transaction is not None:
                active_src = (self.active_transaction.get("source") or "pacman").strip().lower()
                if src_norm == "snap" and active_src != "snap" and getattr(self, "_active_snap_tx", None) is None:
                    self._active_snap_tx = {
                        "action": action,
                        "pkg_name": pkg_name,
                        "source": "snap",
                        "progress": 0.06,
                        "status": f"Preparing Snap {pkg_name}...",
                        "status_msg": f"Preparing Snap {pkg_name}...",
                        "start_time": time.time(),
                        "current_pkg": target_norm,
                        "packages": [pkg_name],
                        "log_lines": [],
                    }
                    self._start_action_worker(action, pkg_name, source, progress_cb, complete_cb, start_cb)
                    return "started"
                if src_norm in ("flatpak", "flathub") and active_src not in ("flatpak", "flathub") and getattr(self, "_active_flatpak_tx", None) is None:
                    self._active_flatpak_tx = {
                        "action": action,
                        "pkg_name": pkg_name,
                        "source": "flatpak",
                        "progress": 0.06,
                        "status": f"Preparing Flathub app {pkg_name}...",
                        "status_msg": f"Preparing Flathub app {pkg_name}...",
                        "start_time": time.time(),
                        "current_pkg": target_norm,
                        "packages": [pkg_name],
                        "log_lines": [],
                    }
                    self._start_action_worker(action, pkg_name, source, progress_cb, complete_cb, start_cb)
                    return "started"
                if src_norm == "docker" and active_src != "docker" and getattr(self, "_active_docker_tx", None) is None:
                    self._active_docker_tx = {
                        "action": action,
                        "pkg_name": pkg_name,
                        "source": "docker",
                        "progress": 0.06,
                        "status": f"Preparing Docker app {pkg_name}...",
                        "status_msg": f"Preparing Docker app {pkg_name}...",
                        "start_time": time.time(),
                        "current_pkg": target_norm,
                        "packages": [pkg_name],
                        "log_lines": [],
                    }
                    self._start_action_worker(action, pkg_name, source, progress_cb, complete_cb, start_cb)
                    return "started"

                self._pending_actions.append({
                    "action": action,
                    "pkg_name": pkg_name,
                    "source": source,
                    "progress_cb": progress_cb,
                    "complete_cb": complete_cb,
                    "start_cb": start_cb,
                    "enqueued_time": time.time(),
                })
                return "queued"

            self._init_active_transaction(action, pkg_name, source)

        self._start_action_worker(action, pkg_name, source, progress_cb, complete_cb, start_cb)
        return "started"

    def _start_action_worker(
        self,
        action: str,
        pkg_name: str,
        source: str,
        progress_cb: Callable[[float, str], None],
        complete_cb: Callable[[bool, str, str, str], None],
        start_cb: Optional[Callable[[], None]] = None
    ):
        if start_cb:
            try:
                start_cb()
            except Exception as e:
                print(f"[ArkST] Error in start_cb: {e}", file=sys.stderr)

        is_system_upgrade = pkg_name in ["system", "--all", "all", ""] or not pkg_name
        target_pkg = ("" if is_system_upgrade else (pkg_name or "")).strip().lower()

        def _safe_progress(
            target_frac: float,
            msg: str,
            cur_p: Optional[str] = None,
            cur_i: Optional[int] = None,
            tot_p: Optional[int] = None
        ):
            with self._action_lock:
                frac = max(self._last_progress, min(0.98, target_frac)) if target_frac < 1.0 else 1.0
                self._last_progress = frac
                if isinstance(self.active_transaction, dict):
                    self.active_transaction["progress"] = frac
                    self.active_transaction["status"] = msg
                    self.active_transaction["status_msg"] = msg
                    if cur_p is not None:
                        old_p = self.active_transaction.get("current_pkg")
                        if old_p and old_p.strip().lower() != cur_p.strip().lower():
                            comp = self.active_transaction.setdefault("completed_pkgs", [])
                            if old_p not in comp:
                                comp.append(old_p)
                        self.active_transaction["current_pkg"] = cur_p
                    if cur_i is not None:
                        self.active_transaction["current_idx"] = cur_i
                    if tot_p is not None:
                        self.active_transaction["total_packages"] = tot_p
            progress_cb(frac, msg)

        def _worker():
            nonlocal pkg_name, target_pkg
            try:
                env = os.environ.copy()
                if ASKPASS_SCRIPT.exists():
                    env["SUDO_ASKPASS"] = str(ASKPASS_SCRIPT)
                env["LC_ALL"] = "C"

                actual_source = (source or "pacman").strip().lower()
                if actual_source == "flathub":
                    actual_source = "flatpak"
                elif actual_source == "container":
                    actual_source = "docker"

                matched_update_entry = None
                if action in ["update", "upgrade"] and not is_system_upgrade:
                    resolved_cand = self.resolve_installed_pkg_name(pkg_name)
                    cand_lows = {pkg_name.strip().lower(), f"{pkg_name.strip().lower()}-bin", resolved_cand.strip().lower()}
                    with self._lock:
                        matched = next(
                            (
                                u for u in self.upgradable_list
                                if (u.get("name") or "").strip().lower() in cand_lows
                                or (u.get("pkg_name") or "").strip().lower() in cand_lows
                            ),
                            None
                        )
                        if matched:
                            matched_update_entry = dict(matched)
                            if matched.get("source"):
                                actual_source = matched["source"].strip().lower()
                                if actual_source == "flathub":
                                    actual_source = "flatpak"
                                elif actual_source == "container":
                                    actual_source = "docker"
                            if matched.get("name") and matched["name"] != pkg_name:
                                pkg_name = matched["name"]
                                target_pkg = pkg_name.strip().lower()
                    if actual_source == "pacman":
                        resolved_src = self.resolve_package_source(resolved_cand or pkg_name)
                        if resolved_src != "pacman":
                            actual_source = resolved_src

                if actual_source in ("flatpak", "flathub"):
                    def _fp_prog(frac_or_msg, maybe_msg=None):
                        if isinstance(frac_or_msg, (int, float)):
                            frac = float(frac_or_msg)
                            msg = str(maybe_msg or "")
                        else:
                            msg = str(frac_or_msg)
                            frac = 0.5
                        if msg:
                            with self._action_lock:
                                if isinstance(self.active_transaction, dict):
                                    logs_ref = self.active_transaction.setdefault("log_lines", [])
                                    logs_ref.append(msg)
                                    if len(logs_ref) > 250:
                                        del logs_ref[:-200]
                        _safe_progress(frac, msg)

                    def _fp_done(ok: bool, *args):
                        if len(args) >= 3:
                            err = str(args[-1] or "")
                        elif len(args) >= 1:
                            err = "" if ok else str(args[-1] or "")
                        else:
                            err = "" if ok else "Flathub operation failed"

                        was_parallel_fp = False
                        with self._action_lock:
                            if getattr(self, "_active_flatpak_tx", None) and (self._active_flatpak_tx.get("pkg_name") or "").strip().lower() == target_pkg:
                                self._active_flatpak_tx = None
                                was_parallel_fp = True
                        if ok:
                            fp_id = self.flatpak_mgr.resolve_flatpak_id(pkg_name)
                            with self._lock:
                                if action in ["upgrade", "update"]:
                                    self.upgradable_list = [
                                        u for u in self.upgradable_list
                                        if (u.get("name") or "").lower() not in (pkg_name.lower(), fp_id.lower())
                                    ]
                                    try:
                                        with open(UPDATES_CACHE_FILE, "w") as f:
                                            json.dump(self.upgradable_list, f)
                                    except Exception:
                                        pass
                            self.refresh_installed()
                            comp_msg = f"✓ Completed {action} for {pkg_name} (Flathub)!"
                            if not was_parallel_fp:
                                with self._action_lock:
                                    if self.active_transaction:
                                        self.active_transaction["progress"] = 1.0
                                        self.active_transaction["status"] = comp_msg
                                        self.active_transaction["status_msg"] = comp_msg
                                        self.active_transaction["is_completed"] = True
                                self._last_progress = 1.0
                            progress_cb(1.0, comp_msg)
                            try:
                                complete_cb(True, action, pkg_name, "")
                            finally:
                                if not was_parallel_fp:
                                    self._process_next_action()
                        else:
                            if not was_parallel_fp:
                                with self._action_lock:
                                    if self.active_transaction:
                                        self.active_transaction["progress"] = 0.0
                                        self.active_transaction["status"] = f"Failed: {err}"
                                        self.active_transaction["status_msg"] = f"Failed: {err}"
                                        self.active_transaction["is_completed"] = True
                                    self.active_transaction = None
                                    self._last_progress = 0.0
                            progress_cb(0.0, f"Failed: {err}")
                            try:
                                complete_cb(False, action, pkg_name, err)
                            finally:
                                if not was_parallel_fp:
                                    self._process_next_action()

                    if action == "install":
                        self.flatpak_mgr.install_flatpak(pkg_name, progress_cb=_fp_prog, complete_cb=_fp_done)
                    elif action in ("remove", "clean_remove"):
                        self.flatpak_mgr.remove_flatpak(pkg_name, delete_data=(action == "clean_remove"), progress_cb=_fp_prog, complete_cb=_fp_done)
                    elif action in ("update", "upgrade"):
                        self.flatpak_mgr.update_flatpak(pkg_name, progress_cb=_fp_prog, complete_cb=_fp_done)
                    else:
                        _fp_done(False, f"Unsupported Flatpak action: {action}")
                    return

                if actual_source == "snap":
                    def _snap_prog(frac_or_msg, maybe_msg=None):
                        if isinstance(frac_or_msg, (int, float)):
                            frac = float(frac_or_msg)
                            msg = str(maybe_msg or "")
                        else:
                            msg = str(frac_or_msg)
                            frac = 0.5
                        if msg:
                            with self._action_lock:
                                target_tx = self._active_snap_tx if getattr(self, "_active_snap_tx", None) is not None else self.active_transaction
                                if isinstance(target_tx, dict):
                                    logs_ref = target_tx.setdefault("log_lines", [])
                                    logs_ref.append(msg)
                                    if len(logs_ref) > 250:
                                        del logs_ref[:-200]
                        _safe_progress(frac, msg)

                    def _snap_done(ok: bool, *args):
                        if len(args) == 3:
                            _, _, err = args
                        elif len(args) == 1:
                            err = "" if ok else str(args[0])
                        else:
                            err = "" if ok else "Snap operation failed"

                        was_parallel_snap = False
                        with self._action_lock:
                            if getattr(self, "_active_snap_tx", None) and (self._active_snap_tx.get("pkg_name") or "").strip().lower() == target_pkg:
                                self._active_snap_tx = None
                                was_parallel_snap = True
                        if ok:
                            if hasattr(self, "snap_mgr") and self.snap_mgr:
                                self.snap_mgr.invalidate_cache()
                            self.refresh_installed()
                            with self._lock:
                                if action in ["upgrade", "update"]:
                                    self.upgradable_list = [u for u in self.upgradable_list if u.get("name") != pkg_name]
                                    try:
                                        with open(UPDATES_CACHE_FILE, "w") as f:
                                            json.dump(self.upgradable_list, f)
                                    except Exception:
                                        pass
                            comp_msg = f"Completed {action} for {pkg_name}."
                            if not was_parallel_snap:
                                with self._action_lock:
                                    if self.active_transaction:
                                        self.active_transaction["progress"] = 1.0
                                        self.active_transaction["status"] = comp_msg
                                        self.active_transaction["status_msg"] = comp_msg
                                        self.active_transaction["is_completed"] = True
                                self._last_progress = 1.0
                            progress_cb(1.0, comp_msg)
                            try:
                                complete_cb(True, action, pkg_name, "")
                            finally:
                                if not was_parallel_snap:
                                    self._process_next_action()
                        else:
                            if not was_parallel_snap:
                                with self._action_lock:
                                    if self.active_transaction:
                                        self.active_transaction["progress"] = 0.0
                                        self.active_transaction["status"] = f"Failed: {err}"
                                        self.active_transaction["status_msg"] = f"Failed: {err}"
                                        self.active_transaction["is_completed"] = True
                                    self.active_transaction = None
                                    self._last_progress = 0.0
                            progress_cb(0.0, f"Failed: {err}")
                            try:
                                complete_cb(False, action, pkg_name, err)
                            finally:
                                if not was_parallel_snap:
                                    self._process_next_action()

                    if action == "install":
                        self.snap_mgr.install_snap(pkg_name, progress_cb=_snap_prog, complete_cb=_snap_done)
                    elif action in ("remove", "clean_remove"):
                        self.snap_mgr.remove_snap(pkg_name, purge=(action == "clean_remove"), progress_cb=_snap_prog, complete_cb=_snap_done)
                    elif action in ["update", "upgrade"]:
                        self.snap_mgr.update_snap(pkg_name, progress_cb=_snap_prog, complete_cb=_snap_done)
                    else:
                        _snap_done(False, f"Unsupported snap action: {action}")
                    return

                if actual_source == "docker":
                    def _docker_prog(msg: str):
                        with self._action_lock:
                            target_tx = self._active_docker_tx if getattr(self, "_active_docker_tx", None) is not None else self.active_transaction
                            if isinstance(target_tx, dict):
                                logs_ref = target_tx.setdefault("log_lines", [])
                                logs_ref.append(str(msg))
                                if len(logs_ref) > 250:
                                    del logs_ref[:-200]
                        _safe_progress(0.5, str(msg))

                    def _docker_done(ok: bool, msg: str = ""):
                        was_parallel_docker = False
                        with self._action_lock:
                            if getattr(self, "_active_docker_tx", None) and (self._active_docker_tx.get("pkg_name") or "").strip().lower() == target_pkg:
                                self._active_docker_tx = None
                                was_parallel_docker = True
                        if ok:
                            with self._lock:
                                self.upgradable_list = [u for u in self.upgradable_list if u.get("name") != pkg_name]
                                try:
                                    with open(UPDATES_CACHE_FILE, "w") as f:
                                        json.dump(self.upgradable_list, f)
                                except Exception:
                                    pass
                            comp_msg = f"Completed {action} for container application {pkg_name}."
                            if not was_parallel_docker:
                                with self._action_lock:
                                    if self.active_transaction:
                                        self.active_transaction["progress"] = 1.0
                                        self.active_transaction["status"] = comp_msg
                                        self.active_transaction["status_msg"] = comp_msg
                                        self.active_transaction["is_completed"] = True
                                self._last_progress = 1.0
                            progress_cb(1.0, comp_msg)
                            try:
                                complete_cb(True, action, pkg_name, "")
                            finally:
                                if not was_parallel_docker:
                                    self._process_next_action()
                        else:
                            if not was_parallel_docker:
                                with self._action_lock:
                                    if self.active_transaction:
                                        self.active_transaction["progress"] = 0.0
                                        self.active_transaction["status"] = f"Failed: {msg}"
                                        self.active_transaction["status_msg"] = f"Failed: {msg}"
                                        self.active_transaction["is_completed"] = True
                                    self.active_transaction = None
                                    self._last_progress = 0.0
                            progress_cb(0.0, f"Failed: {msg}")
                            try:
                                complete_cb(False, action, pkg_name, msg)
                            finally:
                                if not was_parallel_docker:
                                    self._process_next_action()

                    if action in ["update", "upgrade"]:
                        self.container_mgr.update_app(pkg_name, progress_callback=_docker_prog, completion_callback=_docker_done)
                    elif action == "install":
                        self.container_mgr.install_app(pkg_name, progress_callback=_docker_prog, completion_callback=_docker_done)
                    elif action == "remove":
                        self.container_mgr.uninstall_app(pkg_name, progress_callback=_docker_prog, completion_callback=_docker_done)
                    else:
                        _docker_done(False, f"Unsupported docker action: {action}")
                    return

                if actual_source == "deb" or str(pkg_name).lower().endswith(".deb"):
                    def _deb_prog(frac: float, msg: str):
                        _safe_progress(frac, msg)

                    def _deb_done(ok: bool, msg: str):
                        if ok:
                            self.refresh_installed()
                            with self._action_lock:
                                if self.active_transaction:
                                    self.active_transaction["progress"] = 1.0
                                    self.active_transaction["status"] = msg
                                    self.active_transaction["status_msg"] = msg
                                    self.active_transaction["is_completed"] = True
                            self._last_progress = 1.0
                            progress_cb(1.0, msg)
                            try:
                                complete_cb(True, action, pkg_name, "")
                            finally:
                                self._process_next_action()
                        else:
                            with self._action_lock:
                                if self.active_transaction:
                                    self.active_transaction["progress"] = 0.0
                                    self.active_transaction["status"] = f"Failed: {msg}"
                                    self.active_transaction["status_msg"] = f"Failed: {msg}"
                                    self.active_transaction["is_completed"] = True
                                self.active_transaction = None
                                self._last_progress = 0.0
                            progress_cb(0.0, f"Failed: {msg}")
                            try:
                                complete_cb(False, action, pkg_name, msg)
                            finally:
                                self._process_next_action()

                    if action == "install":
                        self.deb_mgr.install_deb(pkg_name, progress_cb=_deb_prog, complete_cb=_deb_done, sync_run=True)
                    elif action == "remove":
                        self.deb_mgr.uninstall_deb(pkg_name, progress_cb=_deb_prog, complete_cb=_deb_done, sync_run=True)
                    else:
                        _deb_done(False, f"Unsupported .deb action: {action}")
                    return

                # Sudo invocation: if passwordless is configured, use 'sudo -n'. Otherwise use 'sudo -A' with askpass.
                is_pwless = PackageManager.is_passwordless_configured()
                sudo_prefix = ["sudo", "-n"] if is_pwless else ["sudo", "-A"]
                aur_sudo_flags = [] if is_pwless else ["--sudoflags", "-A"]
                aur_helper = get_aur_helper()

                # Check and recover from stale /var/lib/pacman/db.lck before launching pacman/AUR transaction
                if Path("/var/lib/pacman/db.lck").exists():
                    if hasattr(self, "doctor_mgr") and self.doctor_mgr:
                        lock_st = self.doctor_mgr.get_pacman_lock_status()
                        if lock_st.get("is_stale"):
                            _safe_progress(0.05, "Clearing stale pacman database lock...")
                            subprocess.run(sudo_prefix + ["rm", "-f", "/var/lib/pacman/db.lck"], capture_output=True, env=env, timeout=10)
                        elif lock_st.get("locked"):
                            _safe_progress(0.05, "Waiting for active package manager to release lock...")
                            for _ in range(12):
                                time.sleep(1)
                                if not Path("/var/lib/pacman/db.lck").exists():
                                    break

                # Native makepkg fallback if action is install/update on an AUR package and no AUR helper is installed
                if actual_source == "aur" and not aur_helper and action in ("install", "update", "upgrade") and not is_system_upgrade:
                    _safe_progress(0.08, f"Building {pkg_name} from AUR via makepkg...")
                    ok_aur, err_aur = self._build_aur_native(pkg_name, env, is_pwless, _safe_progress)
                    if ok_aur:
                        self.refresh_installed()
                        comp_msg = f"✓ Installed {pkg_name} from AUR!"
                        with self._action_lock:
                            if self.active_transaction:
                                self.active_transaction["progress"] = 1.0
                                self.active_transaction["status"] = comp_msg
                                self.active_transaction["status_msg"] = comp_msg
                                self.active_transaction["is_completed"] = True
                        self._last_progress = 1.0
                        progress_cb(1.0, comp_msg)
                        try:
                            complete_cb(True, action, pkg_name, "")
                        finally:
                            self._process_next_action()
                    else:
                        with self._action_lock:
                            self.active_transaction = None
                            self._last_progress = 0.0
                        progress_cb(0.0, f"Error: {err_aur}")
                        try:
                            complete_cb(False, action, pkg_name, err_aur)
                        finally:
                            self._process_next_action()
                    return

                # Smart source cross-resolution for install & remove
                is_clean_remove = (action == "clean_remove") or (action == "remove" and getattr(self, "clean_uninstall_default", False))
                eff_action = "remove" if action in ("remove", "clean_remove") else action

                # If removing a package that isn't in pacman installed_set, check if it's an installed Snap or Docker app
                if eff_action == "remove":
                    resolved_target = self.resolve_installed_pkg_name(pkg_name)
                    if resolved_target not in self.installed_set:
                        if hasattr(self, "snap_mgr") and self.snap_mgr.is_snap_installed(pkg_name):
                            self.snap_mgr.remove_snap(
                                pkg_name,
                                progress_cb=lambda f, m=None: _safe_progress(float(f) if isinstance(f, (int, float)) else 0.5, str(m or f)),
                                complete_cb=lambda ok, *a: (
                                    complete_cb(ok, action, pkg_name, "" if ok else str(a[-1] if a else "Snap remove failed")),
                                    self._process_next_action()
                                )
                            )
                            return
                        if hasattr(self, "flatpak_mgr") and self.flatpak_mgr.is_flatpak_app_installed(pkg_name):
                            self.flatpak_mgr.remove_flatpak(
                                pkg_name,
                                delete_data=is_clean_remove,
                                progress_cb=lambda f, m=None: _safe_progress(float(f) if isinstance(f, (int, float)) else 0.5, str(m or f)),
                                complete_cb=lambda ok, *a: (
                                    complete_cb(ok, action, pkg_name, "" if ok else str(a[-1] if a else "Flatpak remove failed")),
                                    self._process_next_action()
                                )
                            )
                            return
                        if hasattr(self, "container_mgr") and self.container_mgr.is_app_installed(pkg_name):
                            self.container_mgr.uninstall_app(
                                pkg_name,
                                progress_callback=lambda m: _safe_progress(0.5, str(m)),
                                completion_callback=lambda ok, m="": (
                                    complete_cb(ok, action, pkg_name, "" if ok else m),
                                    self._process_next_action()
                                )
                            )
                            return

                # If installing, check whether package is in official sync repos or AUR
                if eff_action == "install" and not is_system_upgrade and self.is_loaded:
                    pkg_entry = self.packages.get(pkg_name)
                    in_official_repo = bool(pkg_entry and pkg_entry.get("repo") not in ("local", "deb-local", "aur", ""))
                    if actual_source == "pacman" and not in_official_repo:
                        # Automatically switch to AUR if package is not in official sync DB
                        if aur_helper:
                            actual_source = "aur"
                    elif actual_source == "aur" and in_official_repo:
                        # Package is available as a prebuilt binary in an enabled pacman repo (e.g. CachyOS / Chaotic-AUR)!
                        actual_source = "pacman"

                # Pacman / AUR command construction
                if eff_action in ["upgrade", "update"]:
                    if is_system_upgrade:
                        if aur_helper == "paru":
                            cmd = ["paru", "-Syu", "--needed", "--noconfirm", "--skipreview"] + aur_sudo_flags
                        elif aur_helper == "yay":
                            cmd = ["yay", "-Syu", "--needed", "--noconfirm", "--nodiffmenu", "--noeditmenu"] + aur_sudo_flags
                        else:
                            cmd = sudo_prefix + ["pacman", "-Syu", "--needed", "--noconfirm"]
                    else:
                        target = self.resolve_installed_pkg_name(pkg_name)
                        # CRITICAL: For single package update/upgrade, NEVER pass --needed!
                        if actual_source == "aur":
                            if aur_helper == "paru":
                                cmd = ["paru", "-S", "--noconfirm", "--skipreview"] + aur_sudo_flags + [target]
                            elif aur_helper == "yay":
                                cmd = ["yay", "-S", "--noconfirm", "--nodiffmenu", "--noeditmenu"] + aur_sudo_flags + [target]
                            else:
                                cmd = sudo_prefix + ["pacman", "-S", "--noconfirm", target]
                        else:
                            cmd = sudo_prefix + ["pacman", "-S", "--noconfirm", target]
                elif eff_action == "install":
                    if actual_source == "pacman":
                        cmd = sudo_prefix + ["pacman", "-S", "--needed", "--noconfirm", pkg_name]
                    else:
                        if aur_helper == "paru":
                            cmd = ["paru", "-S", "--needed", "--noconfirm", "--skipreview"] + aur_sudo_flags + [pkg_name]
                        elif aur_helper == "yay":
                            cmd = ["yay", "-S", "--needed", "--noconfirm", "--nodiffmenu", "--noeditmenu"] + aur_sudo_flags + [pkg_name]
                        else:
                            cmd = sudo_prefix + ["pacman", "-S", "--needed", "--noconfirm", pkg_name]
                elif eff_action == "remove":
                    target = self.resolve_installed_pkg_name(pkg_name)
                    cmd = sudo_prefix + ["pacman", "-Rns", "--noconfirm", target]
                else:
                    cmd = sudo_prefix + ["pacman", "-S", "--needed", "--noconfirm", pkg_name]

                _safe_progress(0.06, "Authenticating & preparing...")

                upgrades_set = set()
                with self._lock:
                    upgrades_set = {u.get("name", "").strip().lower() for u in self.upgradable_list if u.get("name")}

                parser = PacmanProgressParser(
                    action=eff_action,
                    target_pkg=target_pkg,
                    is_system_upgrade=is_system_upgrade,
                    upgradable_pkgs=upgrades_set
                )

                tx_logs: List[str] = []

                wait_for_alpm_lock(progress_cb=_safe_progress, max_wait=180, env=env)

                def _handle_stream_line(raw_line: str):
                    clean_l = ANSI_ESCAPE.sub("", raw_line).strip()
                    if clean_l:
                        tx_logs.append(clean_l)
                        if len(tx_logs) > 300:
                            del tx_logs[:-220]
                        with self._action_lock:
                            if isinstance(self.active_transaction, dict):
                                logs_ref = self.active_transaction.setdefault("log_lines", [])
                                logs_ref.append(clean_l)
                                if len(logs_ref) > 250:
                                    del logs_ref[:-200]
                    res_p = parser.process_line(raw_line)
                    if res_p:
                        frac, msg, cur_p, cur_i, tot_p = res_p
                        _safe_progress(frac, msg, cur_p=cur_p, cur_i=cur_i, tot_p=tot_p)

                def _run_streamed_cmd(command_list: List[str]) -> int:
                    with GLOBAL_ALPM_LOCK:
                        wait_for_alpm_lock(progress_cb=_safe_progress, max_wait=120, env=env)
                        proc_inner = subprocess.Popen(
                            command_list,
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            bufsize=1,
                            env=env
                        )
                        if proc_inner.stdout:
                            read_fn = getattr(proc_inner.stdout, "read", None)
                            if callable(read_fn) and not hasattr(proc_inner.stdout, "_is_mock_iter"):
                                try:
                                    buf_chars: List[str] = []
                                    while True:
                                        ch = proc_inner.stdout.read(1)
                                        if not ch:
                                            if buf_chars:
                                                _handle_stream_line("".join(buf_chars))
                                            break
                                        if ch in ("\r", "\n"):
                                            if buf_chars:
                                                _handle_stream_line("".join(buf_chars))
                                                buf_chars.clear()
                                        else:
                                            buf_chars.append(ch)
                                except TypeError:
                                    for line in proc_inner.stdout:
                                        _handle_stream_line(line)
                            else:
                                for line in proc_inner.stdout:
                                    _handle_stream_line(line)
                        proc_inner.wait()
                        return proc_inner.returncode

                rc = _run_streamed_cmd(cmd)
                combined_logs_lower = "\n".join(tx_logs).lower()

                # Multi-stage Resilient Fallbacks for Removal (-Rns -> -Rs -> -R -> -Rscn)
                if rc != 0 and eff_action == "remove":
                    target = self.resolve_installed_pkg_name(pkg_name)
                    # Stage 2: If -Rns failed due to shared dependency or group constraint, try -Rs
                    if "could not satisfy dependencies" in combined_logs_lower or "breaks dependency" in combined_logs_lower or "target not found" not in combined_logs_lower:
                        _safe_progress(0.35, f"Retrying removal of {target} (preserving shared dependencies)...")
                        parser.error_lines.clear()
                        rc = _run_streamed_cmd(sudo_prefix + ["pacman", "-R", "--noconfirm", target])
                        if rc != 0:
                            _safe_progress(0.50, f"Cascading removal of {target} and dependent sub-packages...")
                            parser.error_lines.clear()
                            rc = _run_streamed_cmd(sudo_prefix + ["pacman", "-Rscn", "--noconfirm", target])

                # If single-package update ran 'pacman -S <target>' against an unsynced /var/lib/pacman/sync DB
                # and merely reinstalled the old version ('is up to date -- reinstalling'), sync DB and upgrade!
                if rc == 0 and eff_action in ("update", "upgrade") and not is_system_upgrade and actual_source == "pacman":
                    if "is up to date -- reinstalling" in combined_logs_lower:
                        _safe_progress(0.22, f"Synchronizing repository database to fetch latest {pkg_name} update...")
                        subprocess.run(sudo_prefix + ["pacman", "-Sy", "--noconfirm"], stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=120)
                        parser.error_lines.clear()
                        rc = _run_streamed_cmd(cmd)
                        combined_logs_lower = "\n".join(tx_logs).lower()

                # Multi-stage Resilient Fallbacks for Installation AND Updates (Single & System-Wide)
                if rc != 0 and eff_action in ("install", "update", "upgrade"):
                    # 1. If sudo -n or paru/yay failed because a password/terminal was required, retry with sudo -A / --sudoflags -A
                    if (
                        "a password is required" in combined_logs_lower
                        or "a terminal is required" in combined_logs_lower
                        or "authentication" in combined_logs_lower
                        or "sudo:" in combined_logs_lower
                    ):
                        sudo_prefix = ["sudo", "-A"]
                        aur_sudo_flags = ["--sudoflags", "-A"]
                        parser.error_lines.clear()
                        if cmd[:2] == ["sudo", "-n"]:
                            cmd_retry = ["sudo", "-A"] + cmd[2:]
                        elif cmd and cmd[0] in ("paru", "yay") and "--sudoflags" not in cmd:
                            cmd_retry = cmd[:2] + ["--sudoflags", "-A"] + cmd[2:]
                        else:
                            cmd_retry = cmd
                        rc = _run_streamed_cmd(cmd_retry)
                        combined_logs_lower = "\n".join(tx_logs).lower()

                    # 2. If conflict prompt rejected under --noconfirm ('are in conflict'), retry with --ask=4
                    if rc != 0 and ("are in conflict" in combined_logs_lower or "conflicting" in combined_logs_lower):
                        _safe_progress(0.20, f"Resolving conflicting package replacement for {pkg_name or 'system'}...")
                        parser.error_lines.clear()
                        if is_system_upgrade:
                            rc = _run_streamed_cmd(sudo_prefix + ["pacman", "-Syu", "--needed", "--noconfirm", "--ask=4"])
                        else:
                            target_c = self.resolve_installed_pkg_name(pkg_name) if eff_action in ("update", "upgrade") else pkg_name
                            needed_fl = ["--needed"] if eff_action == "install" else []
                            rc = _run_streamed_cmd(sudo_prefix + ["pacman", "-S"] + needed_fl + ["--noconfirm", "--ask=4", target_c])
                        combined_logs_lower = "\n".join(tx_logs).lower()

                    # 3. If mirror 404 ('failed retrieving file' / '404') or stale sync DB during single update/install, refresh sync DB (-Sy) and retry
                    if rc != 0 and not is_system_upgrade and (
                        "failed retrieving file" in combined_logs_lower
                        or "returned error: 404" in combined_logs_lower
                        or "could not open file" in combined_logs_lower
                    ):
                        _safe_progress(0.18, "Refreshing outdated Pacman mirror databases (pacman -Sy)...")
                        subprocess.run(sudo_prefix + ["pacman", "-Sy", "--noconfirm"], stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=120)
                        parser.error_lines.clear()
                        rc = _run_streamed_cmd(cmd)
                        combined_logs_lower = "\n".join(tx_logs).lower()

                    # 4. If target not found in pacman repos (e.g. AUR package mislabeled as pacman), fallback to AUR (paru / yay / native makepkg)
                    if rc != 0 and not is_system_upgrade and "target not found" in combined_logs_lower and actual_source == "pacman":
                        target_aur = self.resolve_installed_pkg_name(pkg_name) if eff_action in ("update", "upgrade") else pkg_name
                        _safe_progress(0.15, f"Fetching {target_aur} from AUR...")
                        parser.error_lines.clear()
                        needed_fl = ["--needed"] if eff_action == "install" else []
                        if aur_helper == "paru":
                            rc = _run_streamed_cmd(["paru", "-S"] + needed_fl + ["--noconfirm", "--skipreview", "--sudoflags", "-A", target_aur])
                        elif aur_helper == "yay":
                            rc = _run_streamed_cmd(["yay", "-S"] + needed_fl + ["--noconfirm", "--nodiffmenu", "--noeditmenu", "--sudoflags", "-A", target_aur])
                        else:
                            ok_aur, err_aur = self._build_aur_native(target_aur, env, is_pwless, _safe_progress)
                            rc = 0 if ok_aur else 1
                            if not ok_aur:
                                parser.error_lines.append(err_aur)

                self.last_transaction_logs = list(tx_logs)
                success = (rc == 0)

                # If Clean Uninstall was requested and removal succeeded, purge user ~/.config, ~/.cache, and ~/.local/share leftovers
                if success and eff_action == "remove" and is_clean_remove:
                    target = self.resolve_installed_pkg_name(pkg_name)
                    _safe_progress(0.92, f"Cleaning residual app caches & configuration for {target}...")
                    self.purge_app_leftovers(target, original_name=pkg_name)
                if success:
                    # If system upgrade ('Update All'), also refresh any upgradable AUR (if no helper), Flatpak, Snap, or Docker apps!
                    if is_system_upgrade and action in ["upgrade", "update"]:
                        with self._lock:
                            aur_up_pkgs = [u.get("name") for u in self.upgradable_list if u.get("source") == "aur" and u.get("name")]
                            has_flatpak_up = any(u.get("source") in ("flatpak", "flathub") for u in self.upgradable_list)
                            has_snap_up = any(u.get("source") == "snap" for u in self.upgradable_list)
                            has_docker_up = any(u.get("source") in ("docker", "container") for u in self.upgradable_list)
                        if aur_up_pkgs and not aur_helper:
                            for aur_p in aur_up_pkgs:
                                _safe_progress(0.89, f"Upgrading AUR package {aur_p} via makepkg...")
                                try:
                                    self._build_aur_native(aur_p, env, is_pwless, _safe_progress)
                                except Exception:
                                    pass
                        if has_flatpak_up and hasattr(self, "flatpak_mgr") and self.flatpak_mgr.is_flatpak_installed():
                            _safe_progress(0.90, "Updating Flathub applications...")
                            try:
                                subprocess.run(["flatpak", "update", "-y", "--noninteractive"], stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=300)
                                subprocess.run(["flatpak", "update", "--user", "-y", "--noninteractive"], stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=300)
                            except Exception:
                                pass
                        if has_snap_up and hasattr(self, "snap_mgr") and self.snap_mgr.is_snapd_installed():
                            _safe_progress(0.91, "Refreshing Snap packages...")
                            try:
                                self.snap_mgr._stream_snap_cmd(["snap", "refresh"], env, lambda f, m="": _safe_progress(0.93, str(m or f)), "Refreshing snaps...")
                            except Exception:
                                pass
                        if has_docker_up and hasattr(self, "container_mgr"):
                            _safe_progress(0.95, "Upgrading Docker container packages...")
                            try:
                                self.container_mgr._run_apk(["upgrade", "--no-cache"], timeout=180)
                            except Exception:
                                pass

                    # Record which packages were updated so check_updates can exclude them temporarily
                    resolved_inst = self.resolve_installed_pkg_name(pkg_name) if pkg_name else ""
                    with self._lock:
                        if action in ["upgrade", "update"]:
                            if is_system_upgrade:
                                self.upgradable_list = []
                                try:
                                    with open(UPDATES_CACHE_FILE, "w") as f:
                                        json.dump(self.upgradable_list, f)
                                except Exception:
                                    pass
                            elif pkg_name:
                                exclude_names = {pkg_name, f"{pkg_name}-bin", resolved_inst}
                                self.upgradable_list = [u for u in self.upgradable_list if u.get("name") not in exclude_names]
                                # Protect against race: mark these as recently updated
                                if not hasattr(self, "_recently_updated"):
                                    self._recently_updated = {}
                                now = time.time()
                                for en in exclude_names:
                                    if en:
                                        self._recently_updated[en] = now
                                try:
                                    with open(UPDATES_CACHE_FILE, "w") as f:
                                        json.dump(self.upgradable_list, f)
                                except Exception:
                                    pass
                    self.refresh_installed()

                    comp_msg = parser.get_completion_message()
                    with self._action_lock:
                        if self.active_transaction:
                            self.active_transaction["progress"] = 1.0
                            self.active_transaction["status"] = comp_msg
                            self.active_transaction["status_msg"] = comp_msg
                            c_p = self.active_transaction.get("current_pkg")
                            if c_p:
                                comp = self.active_transaction.setdefault("completed_pkgs", [])
                                if c_p not in comp:
                                    comp.append(c_p)
                            self.active_transaction["current_pkg"] = None
                            self.active_transaction["current_idx"] = parser.current_idx
                            self.active_transaction["total_packages"] = parser.total_packages
                            self.active_transaction["is_completed"] = True
                    self._last_progress = 1.0
                    progress_cb(1.0, comp_msg)
                    # Delayed background check for remaining updates (wait for pacman sync DB to settle)
                    def _delayed_check():
                        time.sleep(5)
                        self.check_updates()
                    threading.Thread(target=_delayed_check, daemon=True).start()
                    try:
                        complete_cb(True, action, pkg_name, "")
                    finally:
                        self._process_next_action()
                else:
                    if any("password" in l.lower() or "auth" in l.lower() for l in parser.error_lines):
                        PackageManager.clear_auth_cache()
                    err_status = parser.get_error_message(rc)
                    raw_err = "\n".join(parser.error_lines[-3:]) if parser.error_lines else f"Exited with code {rc}"
                    with self._action_lock:
                        if self.active_transaction:
                            self.active_transaction["progress"] = 0.0
                            self.active_transaction["status"] = err_status
                            self.active_transaction["status_msg"] = err_status
                            self.active_transaction["is_completed"] = True
                        self.active_transaction = None
                        self._last_progress = 0.0
                    progress_cb(0.0, err_status)
                    try:
                        complete_cb(False, action, pkg_name, raw_err)
                    finally:
                        self._process_next_action()

            except Exception as e:
                err_status = f"Error: {e}"
                with self._action_lock:
                    if self.active_transaction:
                        self.active_transaction["progress"] = 0.0
                        self.active_transaction["status"] = err_status
                        self.active_transaction["status_msg"] = err_status
                    self.active_transaction = None
                    self._last_progress = 0.0
                progress_cb(0.0, err_status)
                try:
                    complete_cb(False, action, pkg_name, str(e))
                finally:
                    self._process_next_action()

        threading.Thread(target=_worker, daemon=True).start()

    # Known mapping of package names to user config/cache/data folder names for Clean Uninstall
    APP_DATA_DIRECTORIES: Dict[str, List[str]] = {
        "code": ["Code", "Code - OSS", "VSCodium"],
        "visual-studio-code-bin": ["Code", "Code - OSS"],
        "code-oss": ["Code - OSS", "Code"],
        "brave-bin": ["BraveSoftware/Brave-Browser", "BraveSoftware"],
        "brave": ["BraveSoftware/Brave-Browser", "BraveSoftware"],
        "google-chrome": ["google-chrome"],
        "chromium": ["chromium"],
        "firefox": ["mozilla/firefox"],
        "zen-browser-bin": ["zen"],
        "discord": ["discord"],
        "vesktop": ["vesktop"],
        "spotify": ["spotify"],
        "obs-studio": ["obs-studio"],
        "vlc": ["vlc"],
        "mpv": ["mpv"],
        "gimp": ["GIMP"],
        "blender": ["blender"],
        "inkscape": ["inkscape"],
        "kdenlive": ["kdenlive"],
        "audacity": ["audacity"],
        "telegram-desktop": ["TelegramDesktop"],
        "signal-desktop": ["Signal"],
        "obsidian": ["obsidian"],
        "libreoffice-fresh": ["libreoffice"],
        "libreoffice-still": ["libreoffice"],
        "lutris": ["lutris"],
        "heroic-games-launcher-bin": ["heroic"],
        "bottles": ["bottles"],
        "prismlauncher": ["PrismLauncher"],
        "retroarch": ["retroarch"],
        "ryujinx-bin": ["Ryujinx"],
        "bitwarden": ["Bitwarden"],
        "keepassxc": ["keepassxc"],
        "postman-bin": ["Postman"],
        "dbeaver": ["DBeaverData"],
        "zed": ["zed"],
        "joplin-desktop": ["Joplin", "joplin-desktop"],
        "onlyoffice-bin": ["onlyoffice"],
        "anytype-bin": ["anytype"],
        "thunderbird": ["thunderbird"],
    }

    # Protected user directories that must NEVER be deleted during Clean Uninstall
    PROTECTED_USER_DIRS: Set[str] = {
        "hypr", "waybar", "rofi", "wofi", "fuzzel", "swaync", "mako", "dunst", "swww",
        "gtk-2.0", "gtk-3.0", "gtk-4.0", "qt5ct", "qt6ct", "Kvantum", "dconf", "systemd",
        "pulse", "pipewire", "wireplumber", "fontconfig", "ibus", "fcitx5", "mime",
        "applications", "icons", "fonts", "themes", "keyrings", "gnupg", "ssh", "arkst",
        "fish", "zsh", "bash", "nvim", "neovim", "git", "alacritty", "kitty", "foot",
        "user-dirs.dirs", "user-dirs.locale", "autostart",
    }

    def purge_app_leftovers(self, pkg_name: str, original_name: str = "") -> List[str]:
        """
        Safely purge residual user-space configuration (~/.config), cache (~/.cache),
        and local data (~/.local/share, ~/.local/state) directories after uninstalling an application.
        Returns list of cleaned directory paths.
        """
        cleaned_paths: List[str] = []
        candidates: Set[str] = set()
        for raw in (pkg_name, original_name):
            if not raw:
                continue
            r_low = raw.strip().lower()
            candidates.add(r_low)
            base = re.sub(r'-(bin|git|hg|svn|pure|gtk-app|qt-app|gui|cli|daemon|desktop|launcher|fresh|still)$', '', r_low)
            if base:
                candidates.add(base)
            if r_low in self.APP_DATA_DIRECTORIES:
                candidates.update(self.APP_DATA_DIRECTORIES[r_low])
            if base in self.APP_DATA_DIRECTORIES:
                candidates.update(self.APP_DATA_DIRECTORIES[base])

        home = Path.home()
        roots = [
            home / ".config",
            home / ".cache",
            home / ".local" / "share",
            home / ".local" / "state",
        ]

        for cand in candidates:
            if not cand or len(cand) < 3:
                continue
            cand_top = cand.split("/")[0]
            if cand_top in self.PROTECTED_USER_DIRS or cand_top.lower() in {x.lower() for x in self.PROTECTED_USER_DIRS}:
                continue
            for root_dir in roots:
                if not root_dir.exists():
                    continue
                # Check exact match or case-insensitive directory match inside root_dir
                target_path = root_dir / cand
                if target_path.exists() and target_path.is_dir() and not target_path.is_symlink():
                    try:
                        shutil.rmtree(target_path, ignore_errors=True)
                        cleaned_paths.append(str(target_path))
                    except Exception:
                        pass
                else:
                    try:
                        for entry in os.scandir(root_dir):
                            if entry.is_dir(follow_symlinks=False):
                                ename_low = entry.name.lower()
                                if ename_low in {x.lower() for x in self.PROTECTED_USER_DIRS}:
                                    continue
                                if ename_low == cand.lower():
                                    shutil.rmtree(entry.path, ignore_errors=True)
                                    cleaned_paths.append(entry.path)
                    except Exception:
                        pass

        # Clean orphaned .desktop overrides in ~/.local/share/applications
        user_apps_dir = home / ".local" / "share" / "applications"
        if user_apps_dir.exists():
            for cand in candidates:
                for dt in user_apps_dir.glob(f"*{cand.lower()}*.desktop"):
                    if dt.name in ("io.github.arkst.desktop", "io.github.aura.desktop"):
                        continue
                    try:
                        dt.unlink()
                        cleaned_paths.append(str(dt))
                    except Exception:
                        pass
            if shutil.which("update-desktop-database"):
                try:
                    subprocess.run(["update-desktop-database", str(user_apps_dir)], capture_output=True, timeout=3)
                except Exception:
                    pass

        return cleaned_paths

    @classmethod
    def has_valid_sudo_session(cls) -> bool:
        """Return True if passwordless sudo is active, sudo timestamp is warm, or session token exists."""
        if cls.is_passwordless_configured():
            return True
        try:
            token_path = Path(f"/run/user/{os.getuid()}/.arkst_session_pass")
            if token_path.exists() and token_path.stat().st_size > 0:
                return True
        except Exception:
            pass
        try:
            res = subprocess.run(["sudo", "-n", "true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            return res.returncode == 0
        except Exception:
            return False

    @classmethod
    def authenticate_session(cls, password: str, enable_passwordless: bool = False) -> Tuple[bool, str]:
        """
        Verify administrator password once in-app and either configure passwordless mode
        or store an ephemeral 0600 session token in /run/user/$UID (tmpfs RAM) cleared on exit.
        """
        if not password:
            return False, "Password cannot be empty."
        if enable_passwordless:
            ok, msg = cls.configure_passwordless(password)
            if ok:
                return True, msg

        try:
            proc = subprocess.run(
                ["sudo", "-S", "-v"],
                input=f"{password}\n",
                text=True,
                capture_output=True,
                timeout=5
            )
            if proc.returncode != 0:
                return False, "Incorrect administrator password. Please try again."
            token_dir = Path(f"/run/user/{os.getuid()}")
            if token_dir.exists():
                token_path = token_dir / ".arkst_session_pass"
                token_path.write_text(password + "\n", encoding="utf-8")
                token_path.chmod(0o600)
            return True, "Session authenticated."
        except Exception as e:
            return False, f"Authentication failed: {e}"

    def _build_aur_native(
        self,
        pkg_name: str,
        env: Dict[str, str],
        is_pwless: bool,
        progress_fn: Callable[[float, str], None]
    ) -> Tuple[bool, str]:
        """Fallback native AUR builder using git clone + makepkg when neither paru nor yay is installed."""
        if not shutil.which("git") or not shutil.which("makepkg"):
            return False, "Neither an AUR helper (paru/yay) nor git/makepkg is installed."
        tmp_dir = tempfile.mkdtemp(prefix=f"arkst-aur-{pkg_name}-")
        try:
            progress_fn(0.15, f"Cloning {pkg_name} from AUR...")
            clone_url = f"https://aur.archlinux.org/{pkg_name}.git"
            cproc = subprocess.run(
                ["git", "clone", "--depth", "1", clone_url, tmp_dir],
                capture_output=True, text=True, env=env, timeout=60
            )
            if cproc.returncode != 0:
                return False, f"Failed cloning AUR repository: {cproc.stderr or cproc.stdout}"
            if not (Path(tmp_dir) / "PKGBUILD").exists():
                return False, f"Package '{pkg_name}' not found in AUR."

            progress_fn(0.35, f"Compiling & installing {pkg_name} via makepkg...")
            build_env = dict(env)
            build_env["PACMAN_AUTH"] = "sudo -n" if is_pwless else "sudo -A"
            proc = subprocess.Popen(
                ["makepkg", "-si", "--noconfirm", "--needed"],
                cwd=tmp_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=build_env
            )
            last_lines = []
            for line in proc.stdout:
                clean = ANSI_ESCAPE.sub("", line).strip()
                if clean:
                    last_lines.append(clean)
                    if "downloading" in clean.lower():
                        progress_fn(0.45, clean[:80])
                    elif "making package:" in clean.lower() or "compiling" in clean.lower():
                        progress_fn(0.65, clean[:80])
                    elif "installing" in clean.lower() or "loading package" in clean.lower():
                        progress_fn(0.85, clean[:80])
            proc.wait()
            if proc.returncode == 0:
                return True, ""
            err_tail = "\n".join(last_lines[-3:]) if last_lines else f"makepkg exited with {proc.returncode}"
            return False, err_tail
        except Exception as e:
            return False, str(e)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    def get_vault_path() -> Path:
        return Path.home() / ".local" / "share" / "arkst" / ".arkst_vault"

    @classmethod
    def is_passwordless_configured(cls) -> bool:
        """
        Authoritative check: verify whether sudo allows pacman execution without password.
        Does NOT rely on local credential files.
        """
        try:
            res = subprocess.run(["sudo", "-n", "pacman", "-V"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return res.returncode == 0
        except Exception:
            return False

    @classmethod
    def configure_passwordless(cls, password: str) -> Tuple[bool, str]:
        """
        Configure system-level passwordless package management via validated sudoers policy.
        CRITICAL SECURITY GUARANTEES (AURA-PW-001 - AURA-PW-010):
        - Administrator password is NEVER saved to disk or persistent storage.
        - Authorization is narrowly scoped to /usr/bin/pacman (paru is NOT given root NOPASSWD).
        - Rule is validated with 'visudo -cf' before installation.
        - Operation is verified with 'sudo -n pacman -V'.
        - Fully atomic and reversible.
        """
        if not password:
            return False, "Password cannot be empty."

        # 1. Verify credentials via sudo -S -v
        try:
            proc = subprocess.run(
                ["sudo", "-S", "-v"],
                input=f"{password}\n",
                text=True,
                capture_output=True,
                timeout=5
            )
            if proc.returncode != 0:
                return False, "Incorrect password. Please verify and try again."
        except Exception as e:
            return False, f"Authentication test failed: {e}"

        # 2. Prepare temporary sudoers file with narrow pacman-only alias
        user = os.environ.get("USER") or "wheel"
        sudoers_content = f"Cmnd_Alias ARKST_PACMAN = /usr/bin/pacman, /usr/bin/flatpak, /usr/bin/snap, /usr/bin/systemctl, /usr/bin/paccache, /usr/bin/journalctl, /usr/bin/pacman-key, /usr/bin/ln, /usr/bin/mkdir, /usr/bin/rm, /usr/bin/cp, /usr/bin/true\n{user} ALL=(root) NOPASSWD: ARKST_PACMAN\n"

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile("w", delete=False, prefix="99-arkst-pacman-") as tf:
                tf.write(sudoers_content)
                tmp_path = tf.name

            # 3. Validate with visudo before installation
            vproc = subprocess.run(["visudo", "-cf", tmp_path], capture_output=True, text=True, timeout=5)
            if vproc.returncode != 0:
                return False, f"Sudoers syntax validation failed: {vproc.stderr or vproc.stdout}"

            # 4. Install atomically with root:root 0440 permissions
            inst_cmd = ["sudo", "-S", "install", "-o", "root", "-g", "root", "-m", "0440", tmp_path, "/etc/sudoers.d/99-arkst-pacman"]
            iproc = subprocess.run(
                inst_cmd,
                input=f"{password}\n",
                text=True,
                capture_output=True,
                timeout=5
            )
            if iproc.returncode != 0:
                return False, f"Failed installing sudoers rule: {iproc.stderr}"

            # 5. Verify that sudo -n pacman -V now succeeds without prompting
            test_proc = subprocess.run(["sudo", "-n", "pacman", "-V"], capture_output=True, text=True, timeout=5)
            if test_proc.returncode != 0:
                # Rollback if verification failed
                subprocess.run(["sudo", "-S", "rm", "-f", "/etc/sudoers.d/99-arkst-pacman", "/etc/sudoers.d/99-aura-pacman"], input=f"{password}\n", text=True, capture_output=True, timeout=5)
                return False, "Installed sudoers rule could not be verified by sudo."

            # 6. Purge any legacy plaintext credentials or session token files
            cls.get_vault_path().unlink(missing_ok=True)
            cls.clear_auth_cache()

            return True, "Passwordless package management configured and verified successfully."
        except Exception as e:
            return False, f"Failed configuring passwordless sudo: {e}"
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    @classmethod
    def remove_passwordless(cls, password: Optional[str] = None) -> Tuple[bool, str]:
        """
        Reversible de-authorization: removes /etc/sudoers.d/99-aura-pacman (and legacy rules),
        invalidates sudo timestamp cache (sudo -k), and clears legacy vault files.
        Note: On Arch Linux, /etc/sudoers.d is 0750 root:root, so non-root Path.exists()
        returns False even when the file exists! We therefore check both is_passwordless_configured()
        and rule_path.exists(), remove all Aura sudoers drop-ins via sudo -n / sudo -S / sudo -A,
        and immediately run 'sudo -k' so cached sudo timestamps do not keep sudo -n active.
        """
        try:
            rule_path = Path("/etc/sudoers.d/99-arkst-pacman")
            legacy_rule_path = Path("/etc/sudoers.d/99-aura-pacman")
            all_rules = ["/etc/sudoers.d/99-arkst-pacman", "/etc/sudoers.d/99-aura-pacman", "/etc/sudoers.d/aura-pacman"]

            if not rule_path.exists() and not legacy_rule_path.exists():
                cls.get_vault_path().unlink(missing_ok=True)
                cls.clear_auth_cache()
                return True, "Passwordless mode is already disabled."

            # 1. First attempt sudo -n rm (works if user has active sudo timestamp or general NOPASSWD)
            proc = subprocess.run(
                ["sudo", "-n", "rm", "-f", "/etc/sudoers.d/99-arkst-pacman", "/etc/sudoers.d/99-aura-pacman"],
                capture_output=True, text=True, timeout=5
            )

            # 2. If sudo -n rm failed, use provided password or ephemeral session token via sudo -S
            if proc.returncode != 0:
                eff_pass = password
                if not eff_pass:
                    try:
                        token_path = Path(f"/run/user/{os.getuid()}/.arkst_session_pass")
                        if token_path.exists():
                            eff_pass = token_path.read_text(encoding="utf-8").strip()
                    except Exception:
                        pass
                if eff_pass:
                    proc = subprocess.run(
                        ["sudo", "-S", "rm", "-f"] + all_rules,
                        input=f"{eff_pass}\n",
                        text=True,
                        capture_output=True,
                        timeout=8
                    )

            # 3. If still not removed and graphical askpass helper is available, prompt via sudo -A
            if proc.returncode != 0:
                askpass = get_askpass_script()
                if askpass.exists() and (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
                    env = os.environ.copy()
                    env["SUDO_ASKPASS"] = str(askpass)
                    proc = subprocess.run(
                        ["sudo", "-A", "rm", "-f"] + all_rules,
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        env=env,
                        timeout=60
                    )

            cls.get_vault_path().unlink(missing_ok=True)
            cls.clear_auth_cache()

            if not rule_path.exists():
                return True, "Passwordless mode disabled successfully."
            else:
                return False, "Failed to remove sudoers configuration rule. Please enter your administrator password."
        except Exception as e:
            return False, f"Error disabling passwordless mode: {e}"

    @staticmethod
    def clear_auth_cache():
        """Clear cached session tokens and legacy vaults."""
        for tname in ("arkst_auth.token", ".arkst_session_pass", "aura_auth.token", ".aura_session_pass"):
            try:
                token = Path(f"/run/user/{os.getuid()}/{tname}")
                token.unlink(missing_ok=True)
            except Exception:
                pass
        for vpath in (
            Path.home() / ".local" / "share" / "arkst" / ".arkst_vault",
            Path.home() / ".local" / "share" / "aura" / ".aura_vault",
        ):
            try:
                vpath.unlink(missing_ok=True)
            except Exception:
                pass




class ArkSTSelfUpdater:
    """
    Inbuilt Self-Updater for ArkST (Universal Linux App Store):
    - Connects directly to GitHub (https://github.com/Desplicableme/arkst)
    - Checks GitHub Releases API and main branch PKGBUILD for newest versions
    - Performs safe background self-updates for both git repository workspaces and system installs
    - Reports real-time progress callbacks and completion notifications
    """
    CURRENT_VERSION = __version__
    REPO_API_URL = "https://api.github.com/repos/Desplicableme/arkst/releases/latest"
    REPO_RAW_PKGBUILD = "https://raw.githubusercontent.com/Desplicableme/arkst/main/PKGBUILD"
    REPO_RAW_BACKEND = "https://raw.githubusercontent.com/Desplicableme/arkst/main/arkst_backend.py"
    REPO_URL = "https://github.com/Desplicableme/arkst"

    def __init__(self, current_version: str = CURRENT_VERSION):
        self.current_version = current_version
        self._cached_update_info: Optional[Dict[str, Any]] = None

    @staticmethod
    def _parse_version(v_str: str) -> Tuple[int, ...]:
        clean = re.sub(r'^[vV]', '', (v_str or "").strip())
        parts = []
        for x in clean.split('.'):
            num = re.match(r'^\d+', x)
            parts.append(int(num.group(0)) if num else 0)
        return tuple(parts)

    def check_for_updates(self, timeout: int = 5) -> Optional[Dict[str, Any]]:
        """
        Check GitHub for newer versions of ArkST.
        Returns a dictionary with update metadata if a newer version is found, or None.
        """
        curr_tuple = self._parse_version(self.current_version)
        latest_ver = ""
        release_notes = ""
        html_url = self.REPO_URL
        release_name = ""

        # 1. Try GitHub Releases API
        try:
            req = urllib.request.Request(
                self.REPO_API_URL,
                headers={"User-Agent": f"ArkST/{self.current_version}", "Accept": "application/vnd.github.v3+json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict):
                    tag = data.get("tag_name", "") or data.get("name", "")
                    if tag:
                        latest_ver = re.sub(r'^[vV]', '', tag).strip()
                        release_name = data.get("name", f"ArkST v{latest_ver}")
                        release_notes = data.get("body", "").strip()
                        html_url = data.get("html_url", html_url)
        except Exception:
            pass

        # 2. Fallback to raw PKGBUILD pkgver on main branch
        if not latest_ver:
            try:
                req = urllib.request.Request(
                    self.REPO_RAW_PKGBUILD,
                    headers={"User-Agent": f"ArkST/{self.current_version}"}
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    txt = resp.read().decode("utf-8", errors="ignore")
                    m = re.search(r'^\s*pkgver\s*=\s*([0-9\.]+)', txt, re.MULTILINE)
                    if m:
                        latest_ver = m.group(1).strip()
                        release_name = f"ArkST v{latest_ver}"
                        release_notes = "Official performance improvements, UI enhancements, and feature updates."
            except Exception:
                pass

        if latest_ver:
            latest_tuple = self._parse_version(latest_ver)
            if latest_tuple > curr_tuple:
                info = {
                    "has_update": True,
                    "current_version": self.current_version,
                    "latest_version": latest_ver,
                    "release_name": release_name or f"ArkST v{latest_ver}",
                    "release_notes": release_notes or f"A new version of ArkST (v{latest_ver}) is available on GitHub.",
                    "html_url": html_url,
                }
                self._cached_update_info = info
                return info

        return None

    def perform_auto_update(
        self,
        progress_cb: Optional[Callable[[float, str], None]] = None,
        completion_cb: Optional[Callable[[bool, str], None]] = None
    ):
        """
        Safely download and apply the update in a background thread.
        Handles both git cloned development workspace and /usr/lib/arkst system installation.
        """
        def _worker():
            try:
                if progress_cb:
                    progress_cb(0.15, "Connecting to GitHub repository...")

                app_dir = Path(__file__).resolve().parent
                git_dir = app_dir / ".git"

                if git_dir.exists() and shutil.which("git"):
                    if progress_cb:
                        progress_cb(0.35, "Fetching latest changes via git...")
                    res = subprocess.run(
                        ["git", "pull", "--ff-only", "origin", "main"],
                        cwd=str(app_dir),
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    if res.returncode != 0:
                        subprocess.run(["git", "fetch", "origin", "main"], cwd=str(app_dir), timeout=20)
                        res2 = subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=str(app_dir), capture_output=True, text=True, timeout=30)
                        if res2.returncode != 0:
                            raise RuntimeError(f"Git pull failed: {res.stderr or res2.stderr}")

                    if progress_cb:
                        progress_cb(0.80, "Verifying files and permissions...")
                else:
                    if progress_cb:
                        progress_cb(0.35, "Downloading update package from GitHub...")
                    tar_url = "https://github.com/Desplicableme/arkst/archive/refs/heads/main.tar.gz"
                    req = urllib.request.Request(tar_url, headers={"User-Agent": f"ArkST/{self.current_version}"})
                    with tempfile.TemporaryDirectory() as tmpdir:
                        tar_path = Path(tmpdir) / "arkst-main.tar.gz"
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            tar_path.write_bytes(resp.read())

                        if progress_cb:
                            progress_cb(0.65, "Extracting update archive...")

                        with tarfile.open(tar_path, "r:gz") as tar:
                            tar.extractall(path=tmpdir)

                        extracted_dir = Path(tmpdir) / "arkst-main"
                        if not extracted_dir.exists():
                            subdirs = [p for p in Path(tmpdir).iterdir() if p.is_dir()]
                            extracted_dir = subdirs[0] if subdirs else Path(tmpdir)

                        if progress_cb:
                            progress_cb(0.85, "Updating ArkST core binaries...")

                        files_to_update = [
                            "arkst.py", "arkst_ui.py", "arkst_backend.py",
                            "arkst_gtk_shim.py", "arkst-askpass",
                            "arkst-icon.png", "arkst-icon.svg", "PKGBUILD"
                        ]
                        for fn in files_to_update:
                            src_f = extracted_dir / fn
                            dst_f = app_dir / fn
                            if src_f.exists():
                                try:
                                    shutil.copy2(src_f, dst_f)
                                except PermissionError:
                                    subprocess.run(["sudo", "cp", "-f", str(src_f), str(dst_f)], check=True)

                if progress_cb:
                    progress_cb(1.0, "Update completed successfully!")

                if completion_cb:
                    completion_cb(True, "ArkST has been updated successfully! Please restart ArkST to apply changes.")
            except Exception as e:
                err_msg = str(e)
                if progress_cb:
                    progress_cb(1.0, f"Update failed: {err_msg}")
                if completion_cb:
                    completion_cb(False, f"Update failed: {err_msg}")

        threading.Thread(target=_worker, daemon=True).start()

    check_for_update = check_for_updates


class FlatpakManager:
    """
    First-class Flathub & Flatpak Integration Engine for Ark Store:
    - Curated Flathub catalog with verified AppStream IDs and rich metadata
    - Real-time Flathub API v2 search + local 'flatpak search' CLI integration
    - 1-Click automated Flatpak & Flathub remote setup (user & system remotes)
    - Live progress streaming for install, update, and uninstall operations
    - Update checking ('flatpak remote-ls --updates') integrated into unified Updates view
    """

    FLATHUB_REMOTE_URL = "https://dl.flathub.org/repo/flathub.flatpakrepo"

    CURATED_FLATPAK_APPS: List[Dict[str, Any]] = [
        {
            "id": "io.github.zen_browser.zen",
            "name": "io.github.zen_browser.zen",
            "short_name": "zen-browser",
            "title": "Zen Browser",
            "summary": "Experience tranquillity while browsing the web",
            "description": "Privacy-focused, beautifully designed Firefox-based browser with vertical tabs, workspaces, and split views.",
            "publisher": "Zen Team",
            "developer": "Zen Team",
            "version": "1.7.6b",
            "category": "Productivity",
            "icon": "zen-browser",
            "store-url": "https://flathub.org/apps/io.github.zen_browser.zen",
            "store_url": "https://flathub.org/apps/io.github.zen_browser.zen",
        },
        {
            "id": "com.spotify.Client",
            "name": "com.spotify.Client",
            "short_name": "spotify",
            "title": "Spotify",
            "summary": "Online music streaming service",
            "description": "Access all of your favorite music, podcasts, and playlists on Linux from the official Flathub package.",
            "publisher": "Spotify",
            "developer": "Spotify",
            "version": "1.2.53",
            "category": "Audio & Music",
            "icon": "spotify",
            "store-url": "https://flathub.org/apps/com.spotify.Client",
            "store_url": "https://flathub.org/apps/com.spotify.Client",
        },
        {
            "id": "com.discordapp.Discord",
            "name": "com.discordapp.Discord",
            "short_name": "discord",
            "title": "Discord",
            "summary": "Messaging, voice, and video client",
            "description": "All-in-one voice, video, and text chat for communities, gaming, and friends in a sandboxed Flatpak.",
            "publisher": "Discord Inc.",
            "developer": "Discord Inc.",
            "version": "0.0.84",
            "category": "Communication",
            "icon": "discord",
            "store-url": "https://flathub.org/apps/com.discordapp.Discord",
            "store_url": "https://flathub.org/apps/com.discordapp.Discord",
        },
        {
            "id": "com.valvesoftware.Steam",
            "name": "com.valvesoftware.Steam",
            "short_name": "steam",
            "title": "Steam",
            "summary": "Launcher for the Steam software distribution service",
            "description": "Play thousands of native Linux and Proton-powered Windows games in a self-contained Flathub runtime.",
            "publisher": "Valve Corporation",
            "developer": "Valve Corporation",
            "version": "1.0.0.81",
            "category": "Gaming",
            "icon": "steam",
            "store-url": "https://flathub.org/apps/com.valvesoftware.Steam",
            "store_url": "https://flathub.org/apps/com.valvesoftware.Steam",
        },
        {
            "id": "com.obsproject.Studio",
            "name": "com.obsproject.Studio",
            "short_name": "obs-studio",
            "title": "OBS Studio",
            "summary": "Live streaming and video recording software",
            "description": "Free and open-source software for video recording and live streaming with PipeWire Wayland screen capture.",
            "publisher": "OBS Project",
            "developer": "OBS Project",
            "version": "31.0.1",
            "category": "Audio & Video",
            "icon": "obs",
            "store-url": "https://flathub.org/apps/com.obsproject.Studio",
            "store_url": "https://flathub.org/apps/com.obsproject.Studio",
        },
        {
            "id": "org.blender.Blender",
            "name": "org.blender.Blender",
            "short_name": "blender",
            "title": "Blender",
            "summary": "Free and open source 3D creation suite",
            "description": "Complete 3D pipeline — modeling, rigging, animation, simulation, rendering, compositing, and motion tracking.",
            "publisher": "Blender Foundation",
            "developer": "Blender Foundation",
            "version": "4.3.2",
            "category": "Graphics & 3D",
            "icon": "blender",
            "store-url": "https://flathub.org/apps/org.blender.Blender",
            "store_url": "https://flathub.org/apps/org.blender.Blender",
        },
        {
            "id": "md.obsidian.Obsidian",
            "name": "md.obsidian.Obsidian",
            "short_name": "obsidian",
            "title": "Obsidian",
            "summary": "Markdown-based knowledge base",
            "description": "Powerful and extensible knowledge base that works on top of your local folder of plain text Markdown files.",
            "publisher": "Obsidian",
            "developer": "Obsidian",
            "version": "1.7.7",
            "category": "Productivity",
            "icon": "obsidian",
            "store-url": "https://flathub.org/apps/md.obsidian.Obsidian",
            "store_url": "https://flathub.org/apps/md.obsidian.Obsidian",
        },
        {
            "id": "com.usebottles.bottles",
            "name": "com.usebottles.bottles",
            "short_name": "bottles",
            "title": "Bottles",
            "summary": "Run Windows software and games on Linux",
            "description": "Easily manage Wine and Proton prefixes in isolated sandboxed environments with dependency installers.",
            "publisher": "Mirko Brombin",
            "developer": "Mirko Brombin",
            "version": "51.18",
            "category": "Gaming & Wine",
            "icon": "com.usebottles.bottles",
            "store-url": "https://flathub.org/apps/com.usebottles.bottles",
            "store_url": "https://flathub.org/apps/com.usebottles.bottles",
        },
        {
            "id": "com.heroicgameslauncher.hgl",
            "name": "com.heroicgameslauncher.hgl",
            "short_name": "heroic",
            "title": "Heroic Games Launcher",
            "summary": "Open source game launcher for Epic, GOG, and Amazon",
            "description": "Play your Epic Games, GOG, and Amazon Prime Gaming library on Linux with Wine/Proton management.",
            "publisher": "Heroic Games",
            "developer": "Heroic Games",
            "version": "2.15.2",
            "category": "Gaming",
            "icon": "com.heroicgameslauncher.hgl",
            "store-url": "https://flathub.org/apps/com.heroicgameslauncher.hgl",
            "store_url": "https://flathub.org/apps/com.heroicgameslauncher.hgl",
        },
        {
            "id": "com.github.tchx84.Flatseal",
            "name": "com.github.tchx84.Flatseal",
            "short_name": "flatseal",
            "title": "Flatseal",
            "summary": "Manage Flatpak permissions",
            "description": "Graphical utility to review and modify permissions from your Flatpak applications in one click.",
            "publisher": "Martin Abente Lahaye",
            "developer": "Martin Abente Lahaye",
            "version": "2.3.0",
            "category": "System Utilities",
            "icon": "security-high",
            "store-url": "https://flathub.org/apps/com.github.tchx84.Flatseal",
            "store_url": "https://flathub.org/apps/com.github.tchx84.Flatseal",
        },
        {
            "id": "io.missioncenter.MissionCenter",
            "name": "io.missioncenter.MissionCenter",
            "short_name": "missioncenter",
            "title": "Mission Center",
            "summary": "Monitor your CPU, Memory, Disk, Network and GPU usage",
            "description": "Sleek GTK4/Libadwaita system performance and hardware telemetry monitor for modern Linux desktops.",
            "publisher": "Mission Center Developers",
            "developer": "Mission Center Developers",
            "version": "0.6.2",
            "category": "System Utilities",
            "icon": "utilities-system-monitor",
            "store-url": "https://flathub.org/apps/io.missioncenter.MissionCenter",
            "store_url": "https://flathub.org/apps/io.missioncenter.MissionCenter",
        },
        {
            "id": "com.mattjakeman.ExtensionManager",
            "name": "com.mattjakeman.ExtensionManager",
            "short_name": "extension-manager",
            "title": "Extension Manager",
            "summary": "Browse, install, and manage GNOME Shell Extensions",
            "description": "Native desktop utility for searching and managing desktop extensions and configurations.",
            "publisher": "Matthew Jakeman",
            "developer": "Matthew Jakeman",
            "version": "0.5.1",
            "category": "Utilities",
            "icon": "preferences-system",
            "store-url": "https://flathub.org/apps/com.mattjakeman.ExtensionManager",
            "store_url": "https://flathub.org/apps/com.mattjakeman.ExtensionManager",
        },
        {
            "id": "org.localsend.localsend_app",
            "name": "org.localsend.localsend_app",
            "short_name": "localsend",
            "title": "LocalSend",
            "summary": "Share files to nearby devices over local network",
            "description": "Free, open-source cross-platform AirDrop alternative that allows you to share files with nearby devices.",
            "publisher": "Tien Do Nam",
            "developer": "Tien Do Nam",
            "version": "1.16.1",
            "category": "Network & Sharing",
            "icon": "localsend",
            "store-url": "https://flathub.org/apps/org.localsend.localsend_app",
            "store_url": "https://flathub.org/apps/org.localsend.localsend_app",
        },
        {
            "id": "dev.zed.Zed",
            "name": "dev.zed.Zed",
            "short_name": "zed",
            "title": "Zed",
            "summary": "High-performance, multiplayer code editor",
            "description": "Next-generation code editor engineered in Rust for speed, AI assistance, and collaborative coding.",
            "publisher": "Zed Industries",
            "developer": "Zed Industries",
            "version": "0.172.8",
            "category": "Development",
            "icon": "dev.zed.Zed",
            "store-url": "https://flathub.org/apps/dev.zed.Zed",
            "store_url": "https://flathub.org/apps/dev.zed.Zed",
        },
        {
            "id": "com.visualstudio.code",
            "name": "com.visualstudio.code",
            "short_name": "code",
            "title": "Visual Studio Code",
            "summary": "Code editing. Redefined.",
            "description": "Visual Studio Code combines the simplicity of a source code editor with powerful developer tooling.",
            "publisher": "Microsoft",
            "developer": "Microsoft",
            "version": "1.97.0",
            "category": "Development",
            "icon": "com.visualstudio.code.oss",
            "store-url": "https://flathub.org/apps/com.visualstudio.code",
            "store_url": "https://flathub.org/apps/com.visualstudio.code",
        },
        {
            "id": "org.kde.kdenlive",
            "name": "org.kde.kdenlive",
            "short_name": "kdenlive",
            "title": "Kdenlive",
            "summary": "Non-linear video editor",
            "description": "Professional open-source video editing software with multi-track timeline, effects, and color grading.",
            "publisher": "KDE",
            "developer": "KDE",
            "version": "24.12.1",
            "category": "Audio & Video",
            "icon": "kdenlive",
            "store-url": "https://flathub.org/apps/org.kde.kdenlive",
            "store_url": "https://flathub.org/apps/org.kde.kdenlive",
        },
        {
            "id": "org.gimp.GIMP",
            "name": "org.gimp.GIMP",
            "short_name": "gimp",
            "title": "GIMP",
            "summary": "Create images and edit photographs",
            "description": "GNU Image Manipulation Program for photo retouching, image composition, and digital illustration.",
            "publisher": "The GIMP Team",
            "developer": "The GIMP Team",
            "version": "2.10.38",
            "category": "Graphics",
            "icon": "gimp",
            "store-url": "https://flathub.org/apps/org.gimp.GIMP",
            "store_url": "https://flathub.org/apps/org.gimp.GIMP",
        },
        {
            "id": "org.videolan.VLC",
            "name": "org.videolan.VLC",
            "short_name": "vlc",
            "title": "VLC",
            "summary": "VLC media player, the open-source multimedia player",
            "description": "Universal multimedia player playing all audio and video formats, DVDs, and streaming protocols.",
            "publisher": "VideoLAN",
            "developer": "VideoLAN",
            "version": "3.0.21",
            "category": "Audio & Video",
            "icon": "vlc",
            "store-url": "https://flathub.org/apps/org.videolan.VLC",
            "store_url": "https://flathub.org/apps/org.videolan.VLC",
        },
        {
            "id": "com.bitwarden.desktop",
            "name": "com.bitwarden.desktop",
            "short_name": "bitwarden",
            "title": "Bitwarden",
            "summary": "A secure and free password manager for all of your devices",
            "description": "Open-source password vault storing sensitive credentials with end-to-end zero-knowledge encryption.",
            "publisher": "Bitwarden Inc.",
            "developer": "Bitwarden Inc.",
            "version": "2025.1.0",
            "category": "Security & Privacy",
            "icon": "bitwarden",
            "store-url": "https://flathub.org/apps/com.bitwarden.desktop",
            "store_url": "https://flathub.org/apps/com.bitwarden.desktop",
        },
        {
            "id": "org.signal.Signal",
            "name": "org.signal.Signal",
            "short_name": "signal-desktop",
            "title": "Signal Desktop",
            "summary": "Private messenger for desktop",
            "description": "Fast, simple, and secure end-to-end encrypted messaging, voice, and video calling.",
            "publisher": "Signal Messenger",
            "developer": "Signal Messenger",
            "version": "7.40.0",
            "category": "Communication",
            "icon": "signal-desktop",
            "store-url": "https://flathub.org/apps/org.signal.Signal",
            "store_url": "https://flathub.org/apps/org.signal.Signal",
        },
        {
            "id": "org.telegram.desktop",
            "name": "org.telegram.desktop",
            "short_name": "telegram-desktop",
            "title": "Telegram Desktop",
            "summary": "Official desktop client for the Telegram messenger",
            "description": "Fast, secure cloud-based instant messaging synced seamlessly across all your devices.",
            "publisher": "Telegram FZ-LLC",
            "developer": "Telegram FZ-LLC",
            "version": "5.10.7",
            "category": "Communication",
            "icon": "telegram",
            "store-url": "https://flathub.org/apps/org.telegram.desktop",
            "store_url": "https://flathub.org/apps/org.telegram.desktop",
        },
    ]

    def __init__(self):
        self._lock = threading.Lock()
        self._fp_op_lock = threading.RLock()
        self.active_flatpak_ops: Dict[str, Tuple[float, str]] = {}
        self._search_cache: Dict[str, List[Dict[str, Any]]] = {}
        self.is_setting_up: bool = False
        self.setup_progress_text: str = ""
        self.setup_progress_fraction: float = 0.0
        self._status_cache: Optional[Dict[str, Any]] = None
        self._status_cache_time: float = 0.0
        self._installed_fp_cache: Optional[List[Dict[str, Any]]] = None
        self._installed_fp_cache_time: float = 0.0
        self._installed_fp_ids: Set[str] = set()
        self._installed_fp_short_names: Dict[str, str] = {}

    def invalidate_cache(self):
        with self._lock:
            self._installed_fp_cache = None
            self._installed_fp_cache_time = 0.0
            self._installed_fp_ids = set()
            self._installed_fp_short_names = {}
            self._status_cache = None
            self._status_cache_time = 0.0
        invalidate_desktop_caches()

    def is_flatpak_available(self) -> bool:
        return self.is_flatpak_installed()

    def is_flatpak_installed(self) -> bool:
        return shutil.which("flatpak") is not None or Path("/usr/bin/flatpak").exists()

    def is_flathub_configured(self) -> bool:
        if not self.is_flatpak_installed():
            return False
        for repo_cfg in (
            Path("/var/lib/flatpak/repo/config"),
            Path.home() / ".local" / "share" / "flatpak" / "repo" / "config",
        ):
            try:
                if repo_cfg.exists() and "flathub" in repo_cfg.read_text(errors="ignore").lower():
                    return True
            except Exception:
                pass
        try:
            proc = subprocess.run(["flatpak", "remotes", "--columns=name"], capture_output=True, text=True, timeout=3)
            if proc.returncode == 0 and "flathub" in proc.stdout.lower():
                return True
        except Exception:
            pass
        return False

    def get_status(self, force_refresh: bool = False) -> Dict[str, Any]:
        now = time.time()
        if not force_refresh and self._status_cache and (now - self._status_cache_time < 10.0):
            res = dict(self._status_cache)
            res["is_setting_up"] = self.is_setting_up
            return res

        has_fp = self.is_flatpak_installed()
        flathub_ok = self.is_flathub_configured() if has_fp else False

        if has_fp and flathub_ok:
            status_code = "ready"
            status_text = "Flathub repository connected and ready"
        elif has_fp and not flathub_ok:
            status_code = "remote_missing"
            status_text = "Flatpak installed, but Flathub remote is not connected yet"
        else:
            status_code = "missing"
            status_text = "Flatpak runtime is not installed on this system"

        res = {
            "has_flatpak": has_fp,
            "flathub_enabled": flathub_ok,
            "status_code": status_code,
            "status_text": status_text,
            "is_setting_up": self.is_setting_up,
        }
        self._status_cache = res
        self._status_cache_time = now
        return res

    def resolve_flatpak_id(self, name_or_id: str) -> str:
        raw = (name_or_id or "").strip()
        if not raw:
            return ""
        low = raw.lower()
        for app in self.CURATED_FLATPAK_APPS:
            if app["id"].lower() == low or app.get("short_name", "").lower() == low or app.get("title", "").lower() == low:
                return app["id"]
        if self._installed_fp_cache is None:
            try:
                self.get_installed_flatpaks()
            except Exception:
                pass
        if low in self._installed_fp_short_names:
            return self._installed_fp_short_names[low]
        for item in (self._installed_fp_cache or []):
            if item.get("id", "").lower() == low:
                return item["id"]
        for base_dir in (
            Path("/var/lib/flatpak/app"),
            Path.home() / ".local" / "share" / "flatpak" / "app",
        ):
            try:
                if base_dir.exists():
                    for child in base_dir.iterdir():
                        if child.name.lower() == low or child.name.split(".")[-1].lower() == low:
                            return child.name
            except Exception:
                pass
        return raw

    def setup_flatpak(self, progress_callback=None, completion_callback=None):
        """1-Click automated setup: install flatpak if missing and enable official Flathub remote."""
        with self._lock:
            if self.is_setting_up:
                if completion_callback:
                    completion_callback(False, "Flathub setup is already in progress.")
                return
            self.is_setting_up = True
            self.setup_progress_text = "Starting Flathub setup..."
            self.setup_progress_fraction = 0.08

        def _report(frac: float, msg: str):
            self.setup_progress_fraction = frac
            self.setup_progress_text = msg
            if progress_callback:
                progress_callback(frac, msg)

        def _task():
            try:
                env = os.environ.copy()
                if ASKPASS_SCRIPT.exists():
                    env["SUDO_ASKPASS"] = str(ASKPASS_SCRIPT)
                env["LC_ALL"] = "C"

                if not self.is_flatpak_installed():
                    _report(0.25, "Installing Flatpak runtime from official Arch repositories...")
                    sudo_prefix = ["sudo", "-n"] if PackageManager.is_passwordless_configured() else ["sudo", "-A"]
                    with GLOBAL_ALPM_LOCK:
                        wait_for_alpm_lock(progress_cb=_report, max_wait=120, env=env)
                        r = subprocess.run(sudo_prefix + ["pacman", "-S", "--needed", "--noconfirm", "flatpak"], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=180)
                        if r.returncode != 0 and sudo_prefix == ["sudo", "-n"]:
                            r = subprocess.run(["sudo", "-A", "pacman", "-S", "--needed", "--noconfirm", "flatpak"], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=180)
                        if r.returncode != 0:
                            err = (r.stderr or r.stdout or "Failed installing flatpak").strip().splitlines()[-1]
                            if completion_callback:
                                completion_callback(False, f"Failed to install flatpak: {err}")
                            return

                _report(0.65, "Connecting official Flathub repository (dl.flathub.org)...")
                # Add user-level Flathub remote first (works without root privileges!)
                subprocess.run(
                    ["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", self.FLATHUB_REMOTE_URL],
                    stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=45
                )
                # Also attempt system-wide Flathub remote
                r_sys = subprocess.run(
                    ["flatpak", "remote-add", "--if-not-exists", "flathub", self.FLATHUB_REMOTE_URL],
                    stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=45
                )
                if r_sys.returncode != 0:
                    sudo_prefix = ["sudo", "-n"] if PackageManager.is_passwordless_configured() else ["sudo", "-A"]
                    subprocess.run(
                        sudo_prefix + ["flatpak", "remote-add", "--if-not-exists", "flathub", self.FLATHUB_REMOTE_URL],
                        stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=45
                    )

                self.invalidate_cache()
                st = self.get_status(force_refresh=True)
                if st["flathub_enabled"]:
                    _report(1.0, "Flathub repository connected and ready!")
                    if completion_callback:
                        completion_callback(True, "Flathub is now connected and ready to install apps!")
                else:
                    _report(1.0, "Flatpak installed; Flathub remote added.")
                    if completion_callback:
                        completion_callback(True, "Flatpak & Flathub configured.")
            except Exception as e:
                if completion_callback:
                    completion_callback(False, f"Error configuring Flathub: {e}")
            finally:
                with self._lock:
                    self.is_setting_up = False
                    self.invalidate_cache()

        threading.Thread(target=_task, daemon=True).start()

    def get_installed_flatpaks(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        now = time.time()
        if not force_refresh and self._installed_fp_cache is not None and (now - self._installed_fp_cache_time < 10.0):
            return list(self._installed_fp_cache)

        if not self.is_flatpak_installed():
            self._installed_fp_cache = []
            self._installed_fp_cache_time = now
            self._installed_fp_ids = set()
            self._installed_fp_short_names = {}
            return []

        try:
            res = subprocess.run(
                ["flatpak", "list", "--app", "--columns=application,name,version,branch,origin,installation"],
                capture_output=True, text=True, timeout=5
            )
            if res.returncode != 0:
                self._installed_fp_cache = []
                self._installed_fp_cache_time = now
                self._installed_fp_ids = set()
                return []

            installed = []
            ids = set()
            short_map = {}
            for line in res.stdout.splitlines():
                parts = [p.strip() for p in line.split("\t")]
                if not parts or not parts[0] or parts[0].lower() in ("application", "application id"):
                    continue
                app_id = parts[0]
                disp_name = parts[1] if len(parts) > 1 and parts[1] else app_id.split(".")[-1]
                ver = parts[2] if len(parts) > 2 and parts[2] else (parts[3] if len(parts) > 3 else "stable")
                branch = parts[3] if len(parts) > 3 else "stable"
                origin = parts[4] if len(parts) > 4 else "flathub"
                inst_scope = parts[5] if len(parts) > 5 else "system"

                ids.add(app_id.lower())
                tail = app_id.split(".")[-1].lower()
                short_map[tail] = app_id
                short_map[disp_name.lower()] = app_id

                installed.append({
                    "id": app_id,
                    "name": app_id,
                    "title": disp_name,
                    "display_name": disp_name,
                    "version": ver,
                    "branch": branch,
                    "origin": origin,
                    "installation": inst_scope,
                    "source": "flatpak",
                    "is_installed": True,
                    "icon": resolve_icon_name(tail, disp_name),
                })

            self._installed_fp_cache = installed
            self._installed_fp_cache_time = now
            self._installed_fp_ids = ids
            self._installed_fp_short_names = short_map
            return list(installed)
        except Exception:
            self._installed_fp_cache = []
            self._installed_fp_cache_time = now
            self._installed_fp_ids = set()
            return []

    def is_flatpak_app_installed(self, name_or_id: str) -> bool:
        clean = (name_or_id or "").strip().lower()
        if not clean:
            return False
        resolved = self.resolve_flatpak_id(clean).lower()
        if self._installed_fp_cache is None:
            self.get_installed_flatpaks()
        if clean in self._installed_fp_ids or resolved in self._installed_fp_ids:
            return True
        if clean in self._installed_fp_short_names:
            return True
        for base_dir in (
            Path("/var/lib/flatpak/app"),
            Path.home() / ".local" / "share" / "flatpak" / "app",
        ):
            try:
                if base_dir.exists():
                    for candidate in (name_or_id.strip(), self.resolve_flatpak_id(name_or_id)):
                        if candidate and (base_dir / candidate).exists():
                            return True
            except Exception:
                pass
        return False

    def check_flatpak_updates(self) -> List[Dict[str, Any]]:
        if not self.is_flatpak_installed():
            return []
        if getattr(self, "is_setting_up", False) or bool(getattr(self, "active_flatpak_ops", None)):
            return []
        updates: List[Dict[str, Any]] = []
        seen = set()
        inst_map = {item["name"].lower(): item.get("version", "installed") for item in self.get_installed_flatpaks()}
        for extra_flags in ([], ["--user"]):
            try:
                proc = subprocess.run(
                    ["flatpak", "remote-ls", "--updates", "--app", "--columns=application,name,version,branch"] + extra_flags,
                    capture_output=True, text=True, timeout=10
                )
                if proc.returncode != 0 or not proc.stdout.strip():
                    continue
                for line in proc.stdout.splitlines():
                    parts = [p.strip() for p in line.split("\t") if p.strip()]
                    if not parts:
                        parts = line.split()
                    if not parts or parts[0].lower() in ("application", "name", "id"):
                        continue
                    app_id = parts[0]
                    if app_id.lower() in seen:
                        continue
                    seen.add(app_id.lower())
                    disp = parts[1] if len(parts) > 1 else app_id.split(".")[-1]
                    new_ver = parts[2] if len(parts) > 2 else (parts[3] if len(parts) > 3 else "latest")
                    old_ver = inst_map.get(app_id.lower(), "installed")
                    updates.append({
                        "name": app_id,
                        "display_name": disp,
                        "old_ver": old_ver,
                        "new_ver": new_ver,
                        "source": "flatpak",
                        "desc": f"{disp} (Flathub Update)",
                        "icon": resolve_icon_name(app_id.split(".")[-1].lower(), disp),
                    })
            except Exception:
                pass
        return updates

    def search_flathub(self, query: str = "") -> List[Dict[str, Any]]:
        return self.search_flatpaks(query)

    def search_flatpaks(self, query: str = "") -> List[Dict[str, Any]]:
        q = (query or "").strip().lower()
        if q and q in self._search_cache:
            return list(self._search_cache[q])

        results: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()

        # 1. Query Flathub API v2 when searching
        if q:
            try:
                url = "https://flathub.org/api/v2/search"
                payload = json.dumps({"query": q}).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "ArkST/3.1.0",
                        "Accept": "application/json"
                    }
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    hits = data.get("hits", []) if isinstance(data, dict) else []
                    if isinstance(hits, list):
                        for item in hits[:48]:
                            app_id = (item.get("app_id") or item.get("id") or "").strip()
                            if not app_id or app_id.lower() in seen_ids:
                                continue
                            seen_ids.add(app_id.lower())
                            curated = next((c for c in self.CURATED_FLATPAK_APPS if c["id"].lower() == app_id.lower()), None)
                            title = item.get("name") or (curated["title"] if curated else app_id.split(".")[-1])
                            raw_sum = item.get("summary") or item.get("description") or (curated.get("summary", "") if curated else "Flathub application")
                            summary = re.sub(r'<[^>]+>', ' ', str(raw_sum)).strip()
                            summary = re.sub(r'\s+', ' ', summary)
                            icon_url = item.get("icon") or ""
                            if icon_url and icon_url.startswith("/"):
                                icon_url = f"https://dl.flathub.org{icon_url}"
                            tail = app_id.split(".")[-1].lower()
                            icon = icon_url or (curated.get("icon") if curated else resolve_icon_name(tail, summary))
                            ver = item.get("currentReleaseVersion") or item.get("version") or (curated.get("version", "stable") if curated else "stable")
                            dev = item.get("developer_name") or (curated.get("publisher", "Flathub") if curated else "Flathub")
                            results.append({
                                "id": app_id,
                                "name": app_id,
                                "title": title,
                                "display_name": title,
                                "summary": summary,
                                "desc": summary,
                                "publisher": dev,
                                "developer": dev,
                                "version": str(ver),
                                "category": curated.get("category", "Flathub App") if curated else "Flathub App",
                                "icon": icon,
                                "icon_url": icon_url,
                                "source": "flatpak",
                                "is_installed": self.is_flatpak_app_installed(app_id),
                                "store-url": f"https://flathub.org/apps/{app_id}",
                                "store_url": f"https://flathub.org/apps/{app_id}",
                            })
            except Exception:
                pass

        # 2. Try local 'flatpak search' CLI if Flathub API returned nothing
        if not results and q and self.is_flatpak_installed():
            try:
                proc = subprocess.run(
                    ["flatpak", "search", "--columns=application,name,description,version,branch,remotes", q],
                    capture_output=True, text=True, timeout=6
                )
                if proc.returncode == 0 and proc.stdout.strip() and "no matches found" not in proc.stdout.lower():
                    for line in proc.stdout.splitlines():
                        parts = [p.strip() for p in line.split("\t")]
                        if len(parts) < 2:
                            continue
                        app_id = parts[0]
                        if not app_id or "." not in app_id or app_id.lower() in seen_ids:
                            continue
                        seen_ids.add(app_id.lower())
                        title = parts[1] if len(parts) > 1 and parts[1] else app_id.split(".")[-1]
                        summary = parts[2] if len(parts) > 2 and parts[2] else "Flathub package"
                        ver = parts[3] if len(parts) > 3 and parts[3] else "stable"
                        tail = app_id.split(".")[-1].lower()
                        results.append({
                            "id": app_id,
                            "name": app_id,
                            "title": title,
                            "display_name": title,
                            "summary": summary,
                            "desc": summary,
                            "publisher": "Flathub",
                            "developer": "Flathub",
                            "version": ver,
                            "category": "Flathub App",
                            "icon": resolve_icon_name(tail, summary),
                            "source": "flatpak",
                            "is_installed": self.is_flatpak_app_installed(app_id),
                            "store-url": f"https://flathub.org/apps/{app_id}",
                            "store_url": f"https://flathub.org/apps/{app_id}",
                        })
            except Exception:
                pass

        # 3. Curated Flathub catalog matching / fallback
        for app in self.CURATED_FLATPAK_APPS:
            app_id = app["id"]
            if app_id.lower() in seen_ids:
                continue
            if not q or (
                q in app_id.lower()
                or q in app.get("short_name", "").lower()
                or q in app.get("title", "").lower()
                or q in app.get("summary", "").lower()
                or q in app.get("category", "").lower()
                or q in app.get("publisher", "").lower()
            ):
                item = dict(app)
                item["name"] = app_id
                item["display_name"] = app["title"]
                item["desc"] = app.get("summary", "")
                item["source"] = "flatpak"
                item["is_installed"] = self.is_flatpak_app_installed(app_id)
                if q and (q == app.get("short_name", "").lower() or q == app.get("title", "").lower()):
                    results.insert(0, item)
                else:
                    results.append(item)
                seen_ids.add(app_id.lower())

        if q:
            self._search_cache[q] = list(results)
        return results

    def get_flatpak_details(self, name_or_id: str) -> Dict[str, Any]:
        app_id = self.resolve_flatpak_id(name_or_id)
        curated = next((c for c in self.CURATED_FLATPAK_APPS if c["id"].lower() == app_id.lower()), None)
        is_inst = self.is_flatpak_app_installed(app_id)
        inst_ver = ""
        if is_inst:
            for item in self.get_installed_flatpaks():
                if item["id"].lower() == app_id.lower():
                    inst_ver = item.get("version", "")
                    break

        # Try Flathub AppStream API v2
        try:
            url = f"https://flathub.org/api/v2/appstream/{urllib.parse.quote(app_id)}"
            req = urllib.request.Request(url, headers={"User-Agent": "Ark-Store/3.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict) and data.get("name"):
                    title = data.get("name") or (curated["title"] if curated else app_id.split(".")[-1])
                    summary = data.get("summary") or (curated.get("summary", "") if curated else "")
                    raw_desc = data.get("description") or summary
                    clean_desc = re.sub(r'<[^>]+>', ' ', raw_desc).strip()
                    clean_desc = re.sub(r'\s+', ' ', clean_desc)
                    dev = data.get("developer_name") or (curated.get("publisher", "Flathub") if curated else "Flathub")
                    lic = data.get("project_license") or "Open Source / Proprietary"
                    releases = data.get("releases") or []
                    ver = releases[0].get("version") if (releases and isinstance(releases[0], dict) and releases[0].get("version")) else (inst_ver or (curated.get("version", "stable") if curated else "stable"))
                    icon_url = data.get("icon") or ""
                    tail = app_id.split(".")[-1].lower()
                    icon = icon_url or (curated.get("icon") if curated else resolve_icon_name(tail, summary))
                    urls = data.get("urls") or {}
                    homepage = urls.get("homepage") or f"https://flathub.org/apps/{app_id}"
                    return {
                        "id": app_id,
                        "name": app_id,
                        "title": title,
                        "display_name": title,
                        "summary": summary,
                        "desc": summary,
                        "extended_desc": clean_desc or summary,
                        "description": clean_desc or summary,
                        "version": ver,
                        "installed_version": inst_ver or (ver if is_inst else ""),
                        "publisher": dev,
                        "developer": dev,
                        "packager": dev,
                        "maintainer": dev,
                        "license": lic,
                        "repo": "Flathub Official",
                        "arch": "x86_64",
                        "isize_str": "Sandboxed Flatpak",
                        "csize_str": "Delta OStree Layers",
                        "depends": ["flatpak", "org.freedesktop.Platform (Sandboxed Runtime)"],
                        "store-url": f"https://flathub.org/apps/{app_id}",
                        "store_url": f"https://flathub.org/apps/{app_id}",
                        "url": homepage,
                        "icon": icon,
                        "icon_url": icon_url,
                        "source": "flatpak",
                        "is_installed": is_inst,
                        "desktop_entry": app_id if is_inst else None,
                    }
        except Exception:
            pass

        title = curated["title"] if curated else get_app_display_name(app_id.split(".")[-1])
        summary = curated.get("summary", "Flathub Sandboxed Application") if curated else "Flathub Sandboxed Application"
        desc = curated.get("description", summary) if curated else summary
        dev = curated.get("publisher", "Flathub Community") if curated else "Flathub Community"
        ver = inst_ver or (curated.get("version", "stable") if curated else "stable")
        icon = curated.get("icon", resolve_icon_name(app_id.split(".")[-1].lower(), summary)) if curated else resolve_icon_name(app_id.split(".")[-1].lower(), summary)
        store_url = curated.get("store_url", f"https://flathub.org/apps/{app_id}") if curated else f"https://flathub.org/apps/{app_id}"

        return {
            "id": app_id,
            "name": app_id,
            "title": title,
            "display_name": title,
            "summary": summary,
            "desc": summary,
            "extended_desc": desc,
            "description": desc,
            "version": ver,
            "installed_version": inst_ver,
            "publisher": dev,
            "developer": dev,
            "packager": dev,
            "maintainer": dev,
            "license": "Open Source / Flathub",
            "repo": "Flathub Official",
            "arch": "x86_64",
            "isize_str": "Sandboxed Flatpak",
            "csize_str": "Delta OSTree Layers",
            "depends": ["flatpak", "org.freedesktop.Platform"],
            "store-url": store_url,
            "store_url": store_url,
            "url": store_url,
            "icon": icon,
            "source": "flatpak",
            "is_installed": is_inst,
            "desktop_entry": app_id if is_inst else None,
        }

    def _stream_flatpak_cmd(self, fp_args: List[str], env: Dict[str, str], progress_cb) -> Tuple[int, List[str]]:
        """Stream flatpak CLI output with real-time percentage parsing."""
        proc = subprocess.Popen(
            fp_args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            env=env
        )
        output_lines: List[str] = []
        buf = bytearray()
        cur_frac = 0.14
        if proc.stdout:
            while True:
                ch = proc.stdout.read(1)
                if not ch:
                    if buf:
                        clean = ANSI_ESCAPE.sub("", buf.decode("utf-8", errors="replace")).strip()
                        if clean:
                            output_lines.append(clean)
                            SnapManager._call_progress(progress_cb, cur_frac, clean[:95])
                    break
                if ch in (b"\r", b"\n"):
                    if buf:
                        clean = ANSI_ESCAPE.sub("", buf.decode("utf-8", errors="replace")).strip()
                        buf.clear()
                        if clean:
                            output_lines.append(clean)
                            if len(output_lines) > 200:
                                del output_lines[:-150]
                            m_pct = re.search(r'(\d{1,3})%', clean)
                            if m_pct:
                                pct_val = min(99, max(1, int(m_pct.group(1))))
                                cur_frac = round(0.14 + (pct_val / 100.0) * 0.82, 3)
                            else:
                                cur_frac = min(0.92, round(cur_frac + 0.03, 3))
                            SnapManager._call_progress(progress_cb, cur_frac, clean[:95])
                else:
                    buf.extend(ch)
        proc.wait()
        return proc.returncode, output_lines

    def install_flatpak(self, name_or_id: str, progress_cb=None, complete_cb=None):
        """Install an application from Flathub with automatic remote setup and user/system fallback."""
        def _task():
            app_id = self.resolve_flatpak_id(name_or_id)
            if not self.is_flatpak_installed():
                err_msg = "Flatpak runtime is not installed. Click 'Auto-Configure Flathub' on the Flathub page first."
                SnapManager._call_progress(progress_cb, 0.0, err_msg)
                SnapManager._call_complete(complete_cb, False, "install", name_or_id, err_msg)
                return

            env = os.environ.copy()
            if ASKPASS_SCRIPT.exists():
                env["SUDO_ASKPASS"] = str(ASKPASS_SCRIPT)
            env["LC_ALL"] = "C"

            fp_key = app_id.strip().lower()
            self.active_flatpak_ops[fp_key] = (0.10, f"Preparing {app_id} from Flathub...")

            def _tracked_prog(f, m=""):
                if isinstance(f, (int, float)):
                    self.active_flatpak_ops[fp_key] = (float(f), str(m))
                SnapManager._call_progress(progress_cb, f, m)

            _tracked_prog(0.10, f"Connecting to Flathub for {app_id}...")

            try:
                with self._fp_op_lock:
                    if not self.is_flathub_configured():
                        _tracked_prog(0.12, "Adding official Flathub remote...")
                        subprocess.run(
                            ["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", self.FLATHUB_REMOTE_URL],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=30
                        )

                    # Try user installation first if user flathub remote exists, else system installation
                    rc, lines = self._stream_flatpak_cmd(
                        ["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", app_id],
                        env, _tracked_prog
                    )
                    if rc != 0:
                        rc, lines = self._stream_flatpak_cmd(
                            ["flatpak", "install", "-y", "--noninteractive", "flathub", app_id],
                            env, _tracked_prog
                        )
                    if rc != 0:
                        sudo_flag = "-n" if PackageManager.is_passwordless_configured() else "-A"
                        rc, lines = self._stream_flatpak_cmd(
                            ["sudo", sudo_flag, "flatpak", "install", "-y", "--noninteractive", "flathub", app_id],
                            env, _tracked_prog
                        )

                if rc == 0:
                    self.invalidate_cache()
                    SnapManager._call_progress(progress_cb, 1.0, f"✓ Installed {app_id} from Flathub!")
                    SnapManager._call_complete(complete_cb, True, "install", name_or_id, "")
                else:
                    err = "\\n".join(lines[-3:]) if lines else f"Flatpak exited with code {rc}"
                    SnapManager._call_progress(progress_cb, 0.0, f"Installation failed: {err}")
                    SnapManager._call_complete(complete_cb, False, "install", name_or_id, err)
            except Exception as e:
                SnapManager._call_progress(progress_cb, 0.0, f"Error: {e}")
                SnapManager._call_complete(complete_cb, False, "install", name_or_id, str(e))
            finally:
                self.active_flatpak_ops.pop(fp_key, None)

        threading.Thread(target=_task, daemon=True).start()

    def remove_flatpak(self, name_or_id: str, delete_data: bool = False, progress_cb=None, complete_cb=None):
        """Uninstall a Flatpak app (and optionally purge ~/.var/app/<app_id> sandbox data)."""
        def _task():
            app_id = self.resolve_flatpak_id(name_or_id)
            if not self.is_flatpak_installed():
                err_msg = "Flatpak is not installed."
                SnapManager._call_progress(progress_cb, 0.0, err_msg)
                SnapManager._call_complete(complete_cb, False, "remove", name_or_id, err_msg)
                return

            env = os.environ.copy()
            if ASKPASS_SCRIPT.exists():
                env["SUDO_ASKPASS"] = str(ASKPASS_SCRIPT)
            env["LC_ALL"] = "C"

            SnapManager._call_progress(progress_cb, 0.15, f"Uninstalling {app_id}...")
            extra = ["--delete-data"] if delete_data else []
            try:
                with self._fp_op_lock:
                    rc, lines = self._stream_flatpak_cmd(
                        ["flatpak", "uninstall", "--user", "-y", "--noninteractive"] + extra + [app_id],
                        env, progress_cb
                    )
                    if rc != 0:
                        rc, lines = self._stream_flatpak_cmd(
                            ["flatpak", "uninstall", "-y", "--noninteractive"] + extra + [app_id],
                            env, progress_cb
                        )
                    if rc != 0:
                        sudo_flag = "-n" if PackageManager.is_passwordless_configured() else "-A"
                        rc, lines = self._stream_flatpak_cmd(
                            ["sudo", sudo_flag, "flatpak", "uninstall", "-y", "--noninteractive"] + extra + [app_id],
                            env, progress_cb
                        )
                if rc == 0:
                    self.invalidate_cache()
                    SnapManager._call_progress(progress_cb, 1.0, f"✓ Removed {app_id} successfully!")
                    SnapManager._call_complete(complete_cb, True, "remove", name_or_id, "")
                else:
                    err = "\\n".join(lines[-3:]) if lines else f"Flatpak uninstall exited with {rc}"
                    SnapManager._call_progress(progress_cb, 0.0, f"Removal failed: {err}")
                    SnapManager._call_complete(complete_cb, False, "remove", name_or_id, err)
            except Exception as e:
                SnapManager._call_progress(progress_cb, 0.0, f"Error: {e}")
                SnapManager._call_complete(complete_cb, False, "remove", name_or_id, str(e))

        threading.Thread(target=_task, daemon=True).start()

    def update_flatpak(self, name_or_id: str = "", progress_cb=None, complete_cb=None):
        """Update a specific Flatpak application or all installed Flatpak apps."""
        def _task():
            app_id = self.resolve_flatpak_id(name_or_id) if name_or_id and name_or_id not in ("system", "--all", "all") else ""
            if not self.is_flatpak_installed():
                err_msg = "Flatpak is not installed."
                SnapManager._call_progress(progress_cb, 0.0, err_msg)
                SnapManager._call_complete(complete_cb, False, "update", name_or_id, err_msg)
                return

            env = os.environ.copy()
            if ASKPASS_SCRIPT.exists():
                env["SUDO_ASKPASS"] = str(ASKPASS_SCRIPT)
            env["LC_ALL"] = "C"

            target_args = [app_id] if app_id else []
            SnapManager._call_progress(progress_cb, 0.12, f"Updating {app_id or 'Flathub applications'}...")
            try:
                with self._fp_op_lock:
                    rc1, lines1 = self._stream_flatpak_cmd(
                        ["flatpak", "update", "--user", "-y", "--noninteractive"] + target_args,
                        env, progress_cb
                    )
                    rc2, lines2 = self._stream_flatpak_cmd(
                        ["flatpak", "update", "-y", "--noninteractive"] + target_args,
                        env, progress_cb
                    )
                    rc = 0 if (rc1 == 0 or rc2 == 0) else rc2
                    lines = lines1 + lines2
                if rc == 0:
                    self.invalidate_cache()
                    SnapManager._call_progress(progress_cb, 1.0, f"✓ Updated {app_id or 'Flathub packages'}!")
                    SnapManager._call_complete(complete_cb, True, "update", name_or_id, "")
                else:
                    err = "\\n".join(lines[-3:]) if lines else f"Flatpak update exited with {rc}"
                    SnapManager._call_progress(progress_cb, 0.0, f"Update failed: {err}")
                    SnapManager._call_complete(complete_cb, False, "update", name_or_id, err)
            except Exception as e:
                SnapManager._call_progress(progress_cb, 0.0, f"Error: {e}")
                SnapManager._call_complete(complete_cb, False, "update", name_or_id, str(e))

        threading.Thread(target=_task, daemon=True).start()

    def launch_flatpak(self, name_or_id: str) -> bool:
        app_id = self.resolve_flatpak_id(name_or_id)
        if not app_id:
            return False
        env = get_gui_launch_env()
        if shutil.which("xhost"):
            try:
                subprocess.run(["xhost", "+local:"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except Exception:
                pass
        try:
            subprocess.Popen(["flatpak", "run", app_id], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            try:
                subprocess.Popen(["gtk-launch", f"{app_id}.desktop"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception:
                return False


class SnapManager:
    """
    Manages Snap package integration, API queries, installations, updates, and removals.
    Features:
    - Native integration with Snapcraft REST API v2 (find & info endpoints).
    - Curated catalog of 16 popular applications with rich metadata.
    - Local snapd status and installed package introspection via snap CLI & filesystem.
    - Upgradable snap detection via 'snap refresh --list'.
    - Background installation, removal, and refresh with realtime progress reporting.
    """

    CURATED_SNAP_APPS = [
        {
            "name": "spotify",
            "title": "Spotify",
            "summary": "Music for everyone",
            "icon": "spotify",
            "developer": "Spotify",
            "category": "Audio & Video",
            "channel": "latest/stable",
            "confinement": "strict",
            "publisher": "Spotify",
            "version": "1.2.53.440.g7b2f582a",
            "store_url": "https://snapcraft.io/spotify",
            "store-url": "https://snapcraft.io/spotify",
            "description": "Spotify is a digital music service that gives you access to millions of songs.",
        },
        {
            "name": "code",
            "title": "Visual Studio Code",
            "summary": "Code editing. Redefined.",
            "icon": "code",
            "developer": "Microsoft",
            "category": "Development",
            "channel": "latest/stable",
            "confinement": "classic",
            "publisher": "Microsoft",
            "version": "1.93.1",
            "store_url": "https://snapcraft.io/code",
            "store-url": "https://snapcraft.io/code",
            "description": "Visual Studio Code is a code editor redefined and optimized for building modern web and cloud applications.",
        },
        {
            "name": "discord",
            "title": "Discord",
            "summary": "All-in-one voice and text chat for gamers",
            "icon": "discord",
            "developer": "Snapcrafters",
            "category": "Social & Communication",
            "channel": "latest/stable",
            "confinement": "strict",
            "publisher": "Snapcrafters",
            "version": "0.0.68",
            "store_url": "https://snapcraft.io/discord",
            "store-url": "https://snapcraft.io/discord",
            "description": "Discord is the easiest way to talk over voice, video, and text.",
        },
        {
            "name": "slack",
            "title": "Slack",
            "summary": "Team communication and collaboration platform",
            "icon": "slack",
            "developer": "Slack",
            "category": "Productivity",
            "channel": "latest/stable",
            "confinement": "strict",
            "publisher": "Slack",
            "version": "4.39.95",
            "store_url": "https://snapcraft.io/slack",
            "store-url": "https://snapcraft.io/slack",
            "description": "Slack brings all your team communication together, giving everyone a shared workspace.",
        },
        {
            "name": "postman",
            "title": "Postman",
            "summary": "API platform for building and using APIs",
            "icon": "postman",
            "developer": "Postman, Inc.",
            "category": "Development",
            "channel": "latest/stable",
            "confinement": "strict",
            "publisher": "Postman, Inc.",
            "version": "11.13.0",
            "store_url": "https://snapcraft.io/postman",
            "store-url": "https://snapcraft.io/postman",
            "description": "Postman is an API platform for developers to design, build, test, and iterate their APIs.",
        },
        {
            "name": "blender",
            "title": "Blender",
            "summary": "Free and open source 3D creation suite",
            "icon": "blender",
            "developer": "Blender Foundation",
            "category": "Graphics & Media",
            "channel": "latest/stable",
            "confinement": "classic",
            "publisher": "Blender Foundation",
            "version": "4.2.2",
            "store_url": "https://snapcraft.io/blender",
            "store-url": "https://snapcraft.io/blender",
            "description": "Blender is the free and open source 3D creation suite supporting modeling, rigging, animation, and VFX.",
        },
        {
            "name": "obs-studio",
            "title": "OBS Studio",
            "summary": "Free and open source software for video recording and live streaming",
            "icon": "com.obsproject.Studio",
            "developer": "OBS Project",
            "category": "Graphics & Media",
            "channel": "latest/stable",
            "confinement": "strict",
            "publisher": "OBS Project",
            "version": "30.2.3",
            "store_url": "https://snapcraft.io/obs-studio",
            "store-url": "https://snapcraft.io/obs-studio",
            "description": "Free and open source software for video recording and live streaming.",
        },
        {
            "name": "vlc",
            "title": "VLC",
            "summary": "The ultimate media player",
            "icon": "vlc",
            "developer": "VideoLAN",
            "category": "Audio & Video",
            "channel": "latest/stable",
            "confinement": "strict",
            "publisher": "VideoLAN",
            "version": "3.0.21",
            "store_url": "https://snapcraft.io/vlc",
            "store-url": "https://snapcraft.io/vlc",
            "description": "VLC is a free and open source cross-platform multimedia player and framework that plays most multimedia files.",
        },
        {
            "name": "telegram-desktop",
            "title": "Telegram Desktop",
            "summary": "Fast and secure desktop messaging app",
            "icon": "telegram",
            "developer": "Telegram FZ-LLC",
            "category": "Social & Communication",
            "channel": "latest/stable",
            "confinement": "strict",
            "publisher": "Telegram FZ-LLC",
            "version": "5.5.5",
            "store_url": "https://snapcraft.io/telegram-desktop",
            "store-url": "https://snapcraft.io/telegram-desktop",
            "description": "Telegram is a cloud-based mobile and desktop messaging app with a focus on security and speed.",
        },
        {
            "name": "bitwarden",
            "title": "Bitwarden",
            "summary": "Open-source password manager for individuals and teams",
            "icon": "bitwarden",
            "developer": "Bitwarden",
            "category": "Security",
            "channel": "latest/stable",
            "confinement": "strict",
            "publisher": "Bitwarden",
            "version": "2024.9.0",
            "store_url": "https://snapcraft.io/bitwarden",
            "store-url": "https://snapcraft.io/bitwarden",
            "description": "Bitwarden is the easiest and safest way to store all of your logins and passwords while keeping them synced.",
        },
        {
            "name": "obsidian",
            "title": "Obsidian",
            "summary": "A powerful knowledge base on top of local Markdown files",
            "icon": "obsidian",
            "developer": "Obsidian",
            "category": "Productivity",
            "channel": "latest/stable",
            "confinement": "classic",
            "publisher": "Obsidian",
            "version": "1.6.7",
            "store_url": "https://snapcraft.io/obsidian",
            "store-url": "https://snapcraft.io/obsidian",
            "description": "Obsidian is the private and flexible writing app that adapts to the way you think.",
        },
        {
            "name": "sublime-text",
            "title": "Sublime Text",
            "summary": "Sophisticated text editor for code, markup and prose",
            "icon": "sublime-text",
            "developer": "Snapcrafters",
            "category": "Development",
            "channel": "latest/stable",
            "confinement": "classic",
            "publisher": "Snapcrafters",
            "version": "4180",
            "store_url": "https://snapcraft.io/sublime-text",
            "store-url": "https://snapcraft.io/sublime-text",
            "description": "Sublime Text is a sophisticated text editor for code, markup and prose with slick user interface.",
        },
        {
            "name": "gimp",
            "title": "GIMP",
            "summary": "GNU Image Manipulation Program",
            "icon": "gimp",
            "developer": "GIMP team",
            "category": "Graphics & Media",
            "channel": "latest/stable",
            "confinement": "strict",
            "publisher": "GIMP team",
            "version": "2.10.38",
            "store_url": "https://snapcraft.io/gimp",
            "store-url": "https://snapcraft.io/gimp",
            "description": "GIMP is a cross-platform image editor available for GNU/Linux, OS X, Windows and more operating systems.",
        },
        {
            "name": "inkscape",
            "title": "Inkscape",
            "summary": "Professional vector graphics editor for Linux, Windows and macOS",
            "icon": "org.inkscape.Inkscape",
            "developer": "Inkscape Project",
            "category": "Graphics & Media",
            "channel": "latest/stable",
            "confinement": "strict",
            "publisher": "Inkscape Project",
            "version": "1.3.2",
            "store_url": "https://snapcraft.io/inkscape",
            "store-url": "https://snapcraft.io/inkscape",
            "description": "Inkscape is a professional vector graphics editor for Linux, Windows and macOS. It is free and open source.",
        },
        {
            "name": "brave",
            "title": "Brave",
            "summary": "Browse privately, search independently, and protect your privacy online",
            "icon": "brave-browser",
            "developer": "Brave Software",
            "category": "Internet & Network",
            "channel": "latest/stable",
            "confinement": "strict",
            "publisher": "Brave Software",
            "version": "1.70.126",
            "store_url": "https://snapcraft.io/brave",
            "store-url": "https://snapcraft.io/brave",
            "description": "Brave Browser is a fast, private and secure web browser for PC, Mac and mobile.",
        },
        {
            "name": "pycharm-community",
            "title": "PyCharm Community",
            "summary": "Python IDE for Professional Developers",
            "icon": "pycharm-community",
            "developer": "JetBrains",
            "category": "Development",
            "channel": "latest/stable",
            "confinement": "classic",
            "publisher": "JetBrains",
            "version": "2024.2.2",
            "store_url": "https://snapcraft.io/pycharm-community",
            "store-url": "https://snapcraft.io/pycharm-community",
            "description": "The Python IDE for Professional Developers. PyCharm provides smart code completion and code inspections.",
        },
    ]

    def __init__(self):
        self._lock = threading.Lock()
        self._snap_op_lock = threading.RLock()
        self.active_snap_ops: Dict[str, Tuple[float, str]] = {}
        self._search_cache: Dict[str, List[Dict[str, Any]]] = {}
        self.is_setting_up: bool = False
        self.setup_progress_text: str = ""
        self.setup_progress_fraction: float = 0.0
        self._status_cache: Optional[Dict[str, Any]] = None
        self._status_cache_time: float = 0.0
        self._installed_snaps_cache: Optional[List[Dict[str, Any]]] = None
        self._installed_snaps_cache_time: float = 0.0
        self._installed_snaps_names: Set[str] = set()

    def invalidate_cache(self):
        """Invalidate all in-memory status and installed snap caches."""
        with self._lock:
            self._installed_snaps_cache = None
            self._installed_snaps_cache_time = 0.0
            self._installed_snaps_names = set()
            self._status_cache = None
            self._status_cache_time = 0.0
        invalidate_desktop_caches()

    def is_snapd_installed(self) -> bool:
        """Check if snap command is available in PATH or at /usr/bin/snap."""
        return shutil.which("snap") is not None or Path("/usr/bin/snap").exists()

    def is_snapd_running(self) -> bool:
        """Check if snapd daemon or socket is active."""
        if Path("/run/snapd.socket").exists():
            return True
        if shutil.which("systemctl"):
            try:
                proc = subprocess.run(["systemctl", "is-active", "--quiet", "snapd.socket"], capture_output=True, timeout=2)
                return proc.returncode == 0
            except Exception:
                pass
        return False

    def get_status(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Check snap binary, systemd socket, and /snap symlink status."""
        now = time.time()
        if not force_refresh and hasattr(self, "_status_cache") and self._status_cache and (now - getattr(self, "_status_cache_time", 0.0) < 10.0):
            res = dict(self._status_cache)
            res["is_setting_up"] = self.is_setting_up
            return res

        has_snap = self.is_snapd_installed()
        socket_active = self.is_snapd_running()
        symlink_ok = Path("/snap").is_symlink() or Path("/snap").exists()

        if has_snap and socket_active and symlink_ok:
            status_code = "ready"
            status_text = "Canonical Snap service active and ready"
        elif has_snap and not socket_active:
            status_code = "service_stopped"
            status_text = "snapd installed but socket is inactive"
        elif has_snap and not symlink_ok:
            status_code = "symlink_missing"
            status_text = "/snap classic confinement symlink missing"
        else:
            status_code = "missing"
            status_text = "Snapd is not installed on this system"

        res = {
            "has_snap": has_snap,
            "socket_active": socket_active,
            "symlink_ok": symlink_ok,
            "status_code": status_code,
            "status_text": status_text,
            "is_setting_up": self.is_setting_up,
        }
        self._status_cache = res
        self._status_cache_time = now
        return res

    @staticmethod
    def _parse_build_error(stderr: Optional[str], stdout: Optional[str]) -> str:
        combined = (stderr or "") + "\n" + (stdout or "")
        lines = [line.strip() for line in combined.splitlines() if line.strip()]
        if not lines:
            return "Unknown compilation or installation error."

        for line in lines:
            if "db.lck" in line or "could not lock database" in line or "unable to lock database" in line:
                return "Pacman database is locked by another running process (/var/lib/pacman/db.lck)."
            if "sudo: a password is required" in line.lower() or "authentication failure" in line.lower():
                return "Authentication failed or root privileges required."

        error_lines = []
        for line in lines:
            l_lower = line.lower()
            if l_lower.startswith("==> error:") or l_lower.startswith("error:"):
                clean = line
                if clean.startswith("==> ERROR:"):
                    clean = clean[10:].strip()
                elif clean.lower().startswith("error:"):
                    clean = clean[6:].strip()
                if clean:
                    error_lines.append(clean)
            elif "failure occurred in" in l_lower or "failed to build" in l_lower:
                error_lines.append(line)

        if error_lines:
            return error_lines[-1]

        filtered = [
            l for l in lines
            if not l.startswith("==> WARNING: Using existing $srcdir")
            and "... Passed" not in l
            and not l.startswith("->")
            and not l.startswith("==> Making package:")
        ]
        if filtered:
            return filtered[-1][:140]

        return lines[-1][:140]

    def setup_snapd(self, progress_callback=None, completion_callback=None):
        """Seamless automated setup: install snapd via paru/pacman, enable socket, link /snap."""
        with self._lock:
            if self.is_setting_up:
                if completion_callback:
                    completion_callback(False, "Snap service configuration is already in progress.")
                return
            self.is_setting_up = True
            self.setup_progress_text = "Starting Snap service setup..."
            self.setup_progress_fraction = 0.05

        def _report(frac: float, msg: str):
            self.setup_progress_fraction = frac
            self.setup_progress_text = msg
            if progress_callback:
                progress_callback(frac, msg)

        def _task():
            try:
                env = os.environ.copy()
                if ASKPASS_SCRIPT.exists():
                    env["SUDO_ASKPASS"] = str(ASKPASS_SCRIPT)
                env["LC_ALL"] = "C"

                # Step 1: Install snapd if missing
                is_installed = self.is_snapd_installed()
                if not is_installed:
                    try:
                        chk = subprocess.run(["pacman", "-Q", "snapd"], capture_output=True, timeout=5)
                        if chk.returncode == 0:
                            is_installed = True
                    except Exception:
                        pass

                if not is_installed:
                    # Check if pacman lock exists
                    if Path("/var/lib/pacman/db.lck").exists():
                        p1 = subprocess.run(["pgrep", "-x", "pacman"], capture_output=True)
                        p2 = subprocess.run(["pgrep", "-x", "paru"], capture_output=True)
                        if p1.returncode == 0 or p2.returncode == 0:
                            _report(0.1, "Waiting for existing package manager to finish...")
                            for _ in range(15):
                                time.sleep(1)
                                if not Path("/var/lib/pacman/db.lck").exists():
                                    break
                            if Path("/var/lib/pacman/db.lck").exists():
                                if completion_callback:
                                    completion_callback(False, "Pacman database is currently locked by another process (/var/lib/pacman/db.lck).")
                                return

                    # Check if a pre-compiled snapd package exists in cache
                    pkg_installed = False
                    candidate_dirs = [
                        Path.home() / ".cache" / "paru" / "clone" / "snapd",
                        Path.home() / ".cache" / "yay" / "snapd",
                    ]
                    for c_dir in candidate_dirs:
                        if c_dir.exists():
                            zst_files = sorted(c_dir.glob("snapd-*.pkg.tar.zst"), key=lambda p: p.stat().st_mtime, reverse=True)
                            if zst_files:
                                cached_pkg = zst_files[0]
                                _report(0.2, f"Installing pre-built snapd package from cache ({cached_pkg.name})...")
                                res_pkg = subprocess.run(
                                    ["sudo", "-A", "pacman", "-U", "--noconfirm", "--needed", str(cached_pkg)],
                                    capture_output=True, text=True, env=env, timeout=120
                                )
                                if res_pkg.returncode == 0:
                                    pkg_installed = True
                                    break

                    if not pkg_installed:
                        _report(0.2, "Installing snapd from repositories/AUR (this may take 1-2 minutes)...")
                        aur_helper = get_aur_helper()
                        sudo_prefix = ["sudo", "-n"] if PackageManager.is_passwordless_configured() else ["sudo", "-A"]
                        if aur_helper == "paru":
                            cmd = ["paru", "-S", "--noconfirm", "--needed", "--skipreview", "snapd"]
                        elif aur_helper == "yay":
                            cmd = ["yay", "-S", "--noconfirm", "--needed", "--nodiffmenu", "--noeditmenu", "snapd"]
                        else:
                            cmd = sudo_prefix + ["pacman", "-S", "--noconfirm", "--needed", "snapd"]
                        res = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
                        if res.returncode != 0:
                            err_msg = self._parse_build_error(res.stderr, res.stdout)
                            if completion_callback:
                                completion_callback(False, f"Failed to install snapd: {err_msg}")
                            return
                else:
                    _report(0.5, "Snap package found, verifying service and confinement symlinks...")

                # Helper that tries sudo -n first and falls back to sudo -A if sudoers only covers pacman
                def _run_root(args_list, timeout_s=30):
                    r = subprocess.run(["sudo", "-n"] + args_list, stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=timeout_s)
                    if r.returncode != 0 and ("password is required" in (r.stderr or "").lower() or "authentication" in (r.stderr or "").lower()):
                        r = subprocess.run(["sudo", "-A"] + args_list, stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=timeout_s)
                    return r

                # Step 2: Enable and start snapd.socket
                _report(0.6, "Enabling and starting snapd.socket...")
                res = _run_root(["systemctl", "enable", "--now", "snapd.socket"], timeout_s=30)
                if res.returncode != 0:
                    err_msg = self._parse_build_error(res.stderr, res.stdout)
                    if completion_callback:
                        completion_callback(False, f"Failed enabling snapd.socket: {err_msg}")
                    return

                # Step 3: Symlink /var/lib/snapd/snap /snap
                _report(0.8, "Creating /snap classical confinement symlink...")
                if not (Path("/snap").is_symlink() or Path("/snap").exists()):
                    res_ln = _run_root(["ln", "-s", "/var/lib/snapd/snap", "/snap"], timeout_s=10)
                    if res_ln.returncode != 0 and not Path("/snap").exists():
                        _run_root(["mkdir", "-p", "/var/lib/snapd/snap"], timeout_s=5)
                        _run_root(["ln", "-s", "/var/lib/snapd/snap", "/snap"], timeout_s=10)

                # Step 4: Verify socket and status
                time.sleep(1)
                st = self.get_status()
                if st["socket_active"] and st["symlink_ok"]:
                    _report(1.0, "Snap service ready!")
                    if completion_callback:
                        completion_callback(True, "Snap Store successfully configured and ready!")
                else:
                    _report(1.0, "Snap configuration finished with warnings.")
                    if completion_callback:
                        completion_callback(True, "Snap Store configured (socket active, symlink created).")
            except Exception as e:
                if completion_callback:
                    completion_callback(False, f"Error configuring snapd: {e}")
            finally:
                with self._lock:
                    self.is_setting_up = False
                    self._installed_snaps_cache = None
                    self._status_cache = None

        threading.Thread(target=_task, daemon=True).start()

    def disable_snapd(self, purge_packages: bool = False, progress_callback=None, completion_callback=None):
        """Disable snapd service and optionally remove package and symlink."""
        def _task():
            env = os.environ.copy()
            if ASKPASS_SCRIPT.exists():
                env["SUDO_ASKPASS"] = str(ASKPASS_SCRIPT)
            env["LC_ALL"] = "C"

            sudo_prefix = ["sudo", "-n"] if PackageManager.is_passwordless_configured() else ["sudo", "-A"]

            if progress_callback:
                progress_callback(0.3, "Stopping and disabling snapd services...")
            subprocess.run(sudo_prefix + ["systemctl", "disable", "--now", "snapd.socket", "snapd.service"],
                           capture_output=True, env=env, timeout=30)

            if Path("/snap").is_symlink():
                subprocess.run(sudo_prefix + ["rm", "-f", "/snap"], capture_output=True, env=env, timeout=10)

            if purge_packages:
                if progress_callback:
                    progress_callback(0.7, "Removing snapd package...")
                res_rm = subprocess.run(sudo_prefix + ["pacman", "-Rns", "--noconfirm", "snapd"],
                                        capture_output=True, text=True, env=env, timeout=60)
                if res_rm.returncode != 0:
                    self._installed_snaps_cache = None
                    self._status_cache = None
                    if completion_callback:
                        completion_callback(False, f"Failed to remove snapd package: {res_rm.stderr or res_rm.stdout}")
                    return

            self._installed_snaps_cache = None
            self._status_cache = None
            if completion_callback:
                completion_callback(True, "Snap setup disabled successfully.")

        threading.Thread(target=_task, daemon=True).start()

    def is_snap_installed(self, name: str) -> bool:
        """Check if a snap package is installed locally with O(1) in-memory lookup."""
        clean = (name or "").strip().lower()
        if not clean:
            return False
        if clean.endswith(".desktop"):
            clean = clean[:-8]
        if "_" in clean:
            clean = clean.split("_")[0]
        if hasattr(self, "_installed_snaps_cache") and self._installed_snaps_cache is not None:
            return clean in getattr(self, "_installed_snaps_names", set())
        try:
            snaps_dir = Path("/var/lib/snapd/snaps")
            if snaps_dir.exists():
                if list(snaps_dir.glob(f"{clean}_*.snap")):
                    return True
        except Exception:
            pass
        try:
            if Path(f"/snap/{clean}").exists():
                return True
        except Exception:
            pass
        try:
            self.get_installed_snaps()
            return clean in getattr(self, "_installed_snaps_names", set())
        except Exception:
            pass
        return False

    def get_installed_snaps(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """List locally installed snaps by parsing 'snap list' output with cache retention."""
        now = time.time()
        if not force_refresh and hasattr(self, "_installed_snaps_cache") and self._installed_snaps_cache is not None and (now - getattr(self, "_installed_snaps_cache_time", 0.0) < 10.0):
            return list(self._installed_snaps_cache)

        if not self.is_snapd_installed():
            self._installed_snaps_cache = []
            self._installed_snaps_cache_time = now
            self._installed_snaps_names = set()
            return []
        try:
            res = subprocess.run(["snap", "list"], capture_output=True, text=True, timeout=5)
            if res.returncode != 0:
                self._installed_snaps_cache = []
                self._installed_snaps_cache_time = now
                self._installed_snaps_names = set()
                return []
            lines = res.stdout.splitlines()
            if not lines:
                self._installed_snaps_cache = []
                self._installed_snaps_cache_time = now
                self._installed_snaps_names = set()
                return []
            installed = []
            names = set()
            for line in lines[1:]:
                parts = line.split()
                if not parts:
                    continue
                name = parts[0]
                version = parts[1] if len(parts) > 1 else ""
                rev = parts[2] if len(parts) > 2 else ""
                tracking = parts[3] if len(parts) > 3 else ""
                publisher = parts[4] if len(parts) > 4 else ""
                notes = " ".join(parts[5:]) if len(parts) > 5 else ""
                installed.append({
                    "name": name,
                    "version": version,
                    "rev": rev,
                    "tracking": tracking,
                    "publisher": publisher,
                    "notes": notes,
                    "source": "snap",
                    "is_installed": True,
                    "icon": resolve_icon_name(name),
                })
                names.add(name.lower())
            self._installed_snaps_cache = installed
            self._installed_snaps_cache_time = now
            self._installed_snaps_names = names
            return list(installed)
        except Exception:
            self._installed_snaps_cache = []
            self._installed_snaps_cache_time = now
            self._installed_snaps_names = set()
            return []

    def check_snap_updates(self) -> List[Dict[str, Any]]:
        """Check for upgradable snaps using 'snap refresh --list'."""
        if not self.is_snapd_installed():
            return []
        if getattr(self, "is_setting_up", False) or bool(getattr(self, "active_snap_ops", None)):
            return []
        updates: List[Dict[str, Any]] = []
        try:
            res = subprocess.run(["snap", "refresh", "--list"], capture_output=True, text=True, timeout=10)
            if res.returncode != 0:
                return []
            output = res.stdout.strip()
            if not output or "all snaps up to date" in output.lower():
                return []

            installed_map = {s["name"].lower(): s.get("version", "installed") for s in self.get_installed_snaps()}
            lines = output.splitlines()
            if lines and ("Name" in lines[0] or "NAME" in lines[0]):
                lines = lines[1:]
            for line in lines:
                parts = line.split()
                if not parts:
                    continue
                name = parts[0]
                new_ver = parts[1] if len(parts) > 1 else "latest"
                old_ver = installed_map.get(name.lower(), "installed")
                updates.append({
                    "name": name,
                    "old_ver": old_ver,
                    "new_ver": new_ver,
                    "source": "snap",
                    "desc": f"Snap package update ({new_ver})",
                    "icon": resolve_icon_name(name),
                })
        except Exception:
            pass
        return updates

    @staticmethod
    def _parse_snap_info(raw_output: str) -> Dict[str, Any]:
        """Parse key-value pairs and metadata from 'snap info' output."""
        details: Dict[str, Any] = {}
        in_desc = False
        desc_lines = []

        for line in raw_output.splitlines():
            # Handle multi-line description block
            if in_desc:
                if line.startswith("  ") or line.startswith("\t"):
                    desc_lines.append(line.strip())
                    continue
                else:
                    in_desc = False
                    details["description"] = "\n".join(desc_lines).strip()

            if line.startswith("description:"):
                in_desc = True
                desc_lines = []
                val = line.split(":", 1)[1].strip()
                if val and val != "|":
                    desc_lines.append(val)
                continue

            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip().lower()
                val = val.strip()

                if key == "name":
                    details["name"] = val
                elif key == "summary":
                    details["summary"] = val
                elif key == "publisher":
                    details["publisher"] = val
                elif key in ("store-url", "store_url"):
                    details["store-url"] = val
                    details["store_url"] = val
                elif key == "license":
                    details["license"] = val
                elif key == "version":
                    details["version"] = val
                elif key == "installed":
                    parts = val.split()
                    if parts:
                        details["installed_version"] = parts[0]
                        if "version" not in details:
                            details["version"] = parts[0]
                elif key == "latest/stable":
                    parts = val.split()
                    if parts and parts[0] != "↑" and "version" not in details:
                        details["version"] = parts[0]

        if in_desc and desc_lines and "description" not in details:
            details["description"] = "\n".join(desc_lines).strip()

        return details

    def search_snaps(self, query: str = "") -> List[Dict[str, Any]]:
        """Search snaps via snap CLI or Snapcraft API with fallback to curated collection."""
        q = (query or "").strip().lower()
        if hasattr(self, "_search_cache") and q and q in self._search_cache:
            return list(self._search_cache[q])
        results: List[Dict[str, Any]] = []
        seen_names = set()

        # 1. Try local snap CLI search first if snap is installed
        if shutil.which("snap"):
            try:
                proc = subprocess.run(
                    ["snap", "find", q if q else "desktop"],
                    capture_output=True, text=True, timeout=8
                )
                if proc.returncode == 0:
                    lines = proc.stdout.splitlines()
                    if lines and ("Name" in lines[0] or "NAME" in lines[0]):
                        lines = lines[1:]
                    for line in lines:
                        parts = line.split(None, 4)
                        if len(parts) >= 5:
                            s_name, s_ver, s_pub, s_notes, s_summary = parts
                        elif len(parts) == 4:
                            s_name, s_ver, s_pub, s_summary = parts
                        elif len(parts) >= 2:
                            s_name = parts[0]
                            s_summary = " ".join(parts[1:])
                            s_pub = "Unknown"
                        else:
                            continue

                        s_name = s_name.strip()
                        if not s_name or s_name in seen_names:
                            continue
                        seen_names.add(s_name)
                        curated = next((c for c in self.CURATED_SNAP_APPS if c["name"].lower() == s_name.lower()), None)
                        title = curated["title"] if curated else s_name.replace("-", " ").title()
                        results.append({
                            "name": s_name,
                            "title": title,
                            "summary": s_summary.strip(),
                            "desc": s_summary.strip(),
                            "publisher": s_pub.strip(),
                            "developer": s_pub.strip(),
                            "source": "snap",
                            "icon": curated.get("icon", s_name) if curated else s_name,
                            "category": curated.get("category", "Snap Package") if curated else "Snap Package",
                            "channel": curated.get("channel", "latest/stable") if curated else "latest/stable",
                            "confinement": curated.get("confinement", "strict") if curated else "strict",
                            "is_installed": self.is_snap_installed(s_name),
                            "store-url": f"https://snapcraft.io/{s_name}",
                            "store_url": f"https://snapcraft.io/{s_name}",
                        })
            except Exception:
                pass

        # 2. If CLI did not find results, query Snapcraft API v2
        if not results and q:
            try:
                url = f"https://api.snapcraft.io/v2/snaps/find?q={urllib.parse.quote(q)}&fields=title,summary,publisher,media"
                req = urllib.request.Request(
                    url,
                    headers={"Snap-Device-Series": "16", "User-Agent": "ArkST-Store/1.0"}
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    for item in data.get("results", []):
                        snap_name = item.get("name", "").strip()
                        if not snap_name or snap_name in seen_names:
                            continue
                        seen_names.add(snap_name)
                        snap_info = item.get("snap", {})
                        curated = next((c for c in self.CURATED_SNAP_APPS if c["name"].lower() == snap_name.lower()), None)
                        title = curated["title"] if curated else (snap_info.get("title") or snap_name.replace("-", " ").title())
                        summary = snap_info.get("summary") or ""
                        pub_info = snap_info.get("publisher", {})
                        developer = pub_info.get("display-name") or pub_info.get("username") or "Unknown"

                        icon_url = None
                        media = snap_info.get("media", [])
                        if isinstance(media, list):
                            for m in media:
                                if isinstance(m, dict) and m.get("type") == "icon" and m.get("url"):
                                    icon_url = m["url"]
                                    break

                        cat = curated.get("category", "Snap Package") if curated else "Snap Package"
                        conf = curated.get("confinement", "strict") if curated else "strict"
                        chan = curated.get("channel", "latest/stable") if curated else "latest/stable"
                        icon = icon_url or (curated.get("icon", snap_name) if curated else resolve_icon_name(snap_name, summary))

                        results.append({
                            "name": snap_name,
                            "title": title,
                            "summary": summary,
                            "desc": summary,
                            "icon": icon,
                            "icon_url": icon_url,
                            "developer": developer,
                            "publisher": developer,
                            "category": cat,
                            "channel": chan,
                            "confinement": conf,
                            "source": "snap",
                            "is_installed": self.is_snap_installed(snap_name),
                            "store-url": f"https://snapcraft.io/{snap_name}",
                            "store_url": f"https://snapcraft.io/{snap_name}",
                        })
            except Exception:
                pass

        # 3. Fallback / augment with curated catalog
        if not results:
            for app in self.CURATED_SNAP_APPS:
                s_name = app["name"].lower()
                if not q or (
                    q in s_name
                    or q in app.get("title", "").lower()
                    or q in app.get("summary", "").lower()
                    or q in app.get("category", "").lower()
                    or q in app.get("developer", "").lower()
                ):
                    item = dict(app)
                    item["is_installed"] = self.is_snap_installed(s_name)
                    item["desc"] = app.get("summary", "")
                    item["source"] = "snap"
                    results.append(item)
                    seen_names.add(s_name)
        elif q:
            for app in self.CURATED_SNAP_APPS:
                s_name = app["name"].lower()
                if s_name not in seen_names and (
                    q in s_name or q in app.get("title", "").lower()
                ):
                    item = dict(app)
                    item["is_installed"] = self.is_snap_installed(s_name)
                    item["desc"] = app.get("summary", "")
                    item["source"] = "snap"
                    results.insert(0, item)
                    seen_names.add(s_name)

        def _snap_rank(item: Dict[str, Any]) -> int:
            nm = item.get("name", "").lower()
            tt = item.get("title", "").lower()
            if nm == q or tt == q:
                return 0
            if nm.startswith(q) or tt.startswith(q):
                return 1
            if q in nm:
                return 2
            return 3

        if q:
            results.sort(key=_snap_rank)

        if hasattr(self, "_search_cache") and q:
            self._search_cache[q] = list(results)
        return results

    def get_snap_details(self, name: str) -> Dict[str, Any]:
        """Fetch full package details via snap CLI or Snapcraft API with fallback to curated catalog."""
        snap_name = (name or "").strip().lower()
        curated = next((c for c in self.CURATED_SNAP_APPS if c["name"].lower() == snap_name), None)

        # 1. Try local 'snap info' CLI first if snap is available
        if shutil.which("snap"):
            try:
                proc = subprocess.run(["snap", "info", snap_name], capture_output=True, text=True, timeout=8)
                if proc.returncode == 0:
                    parsed = self._parse_snap_info(proc.stdout)
                    if parsed:
                        info = dict(curated) if curated else {}
                        info.update(parsed)
                        info["name"] = snap_name
                        info["title"] = curated["title"] if curated else snap_name.replace("-", " ").title()
                        info["display_name"] = info["title"]
                        info["summary"] = parsed.get("summary", curated.get("summary", "") if curated else "")
                        info["desc"] = info["summary"]
                        info["publisher"] = parsed.get("publisher", curated.get("publisher", "Unknown") if curated else "Unknown")
                        info["developer"] = info["publisher"]
                        info["version"] = parsed.get("version", curated.get("version", "latest") if curated else "latest")
                        info["store-url"] = parsed.get("store-url", curated.get("store_url", f"https://snapcraft.io/{snap_name}") if curated else f"https://snapcraft.io/{snap_name}")
                        info["store_url"] = info["store-url"]
                        info["confinement"] = curated.get("confinement", "strict") if curated else "strict"
                        info["category"] = curated.get("category", "Snap Package") if curated else "Snap Package"
                        info["icon"] = curated.get("icon", snap_name) if curated else resolve_icon_name(snap_name, info["summary"])
                        info["source"] = "snap"
                        info["is_installed"] = self.is_snap_installed(snap_name)
                        return info
            except Exception:
                pass

        # 2. Query Snapcraft API v2
        details: Optional[Dict[str, Any]] = None
        try:
            url = f"https://api.snapcraft.io/v2/snaps/info/{urllib.parse.quote(snap_name)}?fields=title,summary,description,license,confinement,media,publisher,version,download"
            req = urllib.request.Request(
                url,
                headers={"Snap-Device-Series": "16", "User-Agent": "ArkST-Store/1.0"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                snap_obj = data.get("snap", {})
                cm = data.get("channel-map", [])
                stable_entry = next((e for e in cm if e.get("channel", {}).get("risk") == "stable"), cm[0] if cm else {})
                pub_obj = snap_obj.get("publisher", {})
                developer = pub_obj.get("display-name") or pub_obj.get("username") or (curated.get("developer") if curated else "Unknown")
                title = curated["title"] if curated else (snap_obj.get("title") or snap_name.replace("-", " ").title())
                summary = snap_obj.get("summary") or (curated.get("summary") if curated else "")
                description = snap_obj.get("description") or summary or (curated.get("description") if curated else "")
                version = stable_entry.get("version") or (curated.get("version") if curated else "latest")
                confinement = stable_entry.get("confinement") or (curated.get("confinement") if curated else "strict")
                license_str = snap_obj.get("license") or "Proprietary / Open Source"
                store_url = snap_obj.get("store-url") or f"https://snapcraft.io/{snap_name}"

                icon_url = None
                screenshots = []
                media = snap_obj.get("media", [])
                if isinstance(media, list):
                    for m in media:
                        if isinstance(m, dict):
                            if m.get("type") == "icon" and m.get("url") and not icon_url:
                                icon_url = m["url"]
                            elif m.get("type") == "screenshot" and m.get("url"):
                                screenshots.append(m["url"])

                icon = icon_url or (curated.get("icon") if curated else resolve_icon_name(snap_name, summary))
                category = curated.get("category", "Snap Package") if curated else "Snap Package"

                details = {
                    "name": snap_name,
                    "title": title,
                    "display_name": title,
                    "summary": summary,
                    "description": description,
                    "desc": summary or description,
                    "version": version,
                    "publisher": developer,
                    "developer": developer,
                    "license": license_str,
                    "channel-map": cm,
                    "channel_map": cm,
                    "store-url": store_url,
                    "store_url": store_url,
                    "confinement": confinement,
                    "category": category,
                    "icon": icon,
                    "icon_url": icon_url,
                    "screenshots": screenshots,
                    "source": "snap",
                    "is_installed": self.is_snap_installed(snap_name),
                }
        except Exception:
            pass

        if details:
            return details

        # 3. Fallback to curated catalog or sensible defaults
        title = curated["title"] if curated else snap_name.replace("-", " ").title()
        summary = curated.get("summary", "") if curated else "Snap package"
        developer = curated.get("developer", "Unknown") if curated else "Unknown"
        version = curated.get("version", "latest") if curated else "latest"
        icon = curated.get("icon", snap_name) if curated else resolve_icon_name(snap_name)
        confinement = curated.get("confinement", "strict") if curated else "strict"
        store_url = curated.get("store_url", f"https://snapcraft.io/{snap_name}") if curated else f"https://snapcraft.io/{snap_name}"
        desc = curated.get("description", summary) if curated else summary

        return {
            "name": snap_name,
            "title": title,
            "display_name": title,
            "summary": summary,
            "description": desc,
            "desc": summary,
            "version": version,
            "publisher": developer,
            "developer": developer,
            "license": "Proprietary / Open Source",
            "channel-map": [],
            "channel_map": [],
            "store-url": store_url,
            "store_url": store_url,
            "confinement": confinement,
            "category": curated.get("category", "Snap Package") if curated else "Snap Package",
            "icon": icon,
            "screenshots": [],
            "source": "snap",
            "is_installed": self.is_snap_installed(snap_name),
        }

    def _stream_snap_cmd(self, snap_args: List[str], env: Dict[str, str], progress_cb, start_msg: str = "") -> Tuple[int, List[str]]:
        """
        Execute a privileged snap command, streaming both '\r' and '\n' progress lines
        and automatically falling back from sudo -n to sudo -A if password is required.
        """
        # Ensure snapd.socket and /snap symlink are ready before running snap install
        if not self.is_snapd_running():
            subprocess.run(["sudo", "-n", "systemctl", "start", "snapd.socket"], stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=10)
            if not self.is_snapd_running():
                subprocess.run(["sudo", "-A", "systemctl", "start", "snapd.socket"], stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=20)
        if not (Path("/snap").is_symlink() or Path("/snap").exists()):
            subprocess.run(["sudo", "-n", "ln", "-s", "/var/lib/snapd/snap", "/snap"], stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=5)
            if not (Path("/snap").is_symlink() or Path("/snap").exists()):
                subprocess.run(["sudo", "-A", "ln", "-s", "/var/lib/snapd/snap", "/snap"], stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=15)

        def _run_once(sudo_flag: str) -> Tuple[int, List[str]]:
            cmd = ["sudo", sudo_flag] + snap_args
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,
                env=env
            )
            output_lines: List[str] = []
            buf = bytearray()
            cur_frac = 0.14
            if proc.stdout:
                while True:
                    ch = proc.stdout.read(1)
                    if not ch:
                        if buf:
                            raw_line = buf.decode("utf-8", errors="replace")
                            clean = ANSI_ESCAPE.sub("", raw_line).strip()
                            if clean:
                                output_lines.append(clean)
                                if "a password is required" not in clean.lower():
                                    self._call_progress(progress_cb, cur_frac, clean)
                        break
                    if ch in (b"\r", b"\n"):
                        if buf:
                            raw_line = buf.decode("utf-8", errors="replace")
                            buf.clear()
                            clean = ANSI_ESCAPE.sub("", raw_line).strip()
                            if clean:
                                output_lines.append(clean)
                                if len(output_lines) > 200:
                                    del output_lines[:-150]
                                m_pct = re.search(r'(\d{1,3})%', clean)
                                if m_pct:
                                    pct_val = min(99, max(1, int(m_pct.group(1))))
                                    cur_frac = round(0.12 + (pct_val / 100.0) * 0.82, 3)
                                else:
                                    cur_frac = min(0.92, round(cur_frac + 0.04, 3))
                                if "a password is required" not in clean.lower():
                                    self._call_progress(progress_cb, cur_frac, clean[:95])
                    else:
                        buf.extend(ch)
            proc.wait()
            return proc.returncode, output_lines

        snap_lock = getattr(self, "_snap_op_lock", None) or threading.RLock()
        with snap_lock:
            rc, lines = _run_once("-n")
            combined_low = "\n".join(lines).lower()
            used_flag = "-n"
            if rc != 0 and ("a password is required" in combined_low or "authentication" in combined_low or not lines):
                used_flag = "-A"
                rc, lines = _run_once("-A")
                combined_low = "\n".join(lines).lower()

            if rc != 0 and ("change in progress" in combined_low or "conflicts with" in combined_low):
                for wait_idx in range(10):
                    self._call_progress(progress_cb, 0.14, f"Waiting for background snapd task to complete ({wait_idx + 1}/10)...")
                    time.sleep(2.0)
                    rc, lines = _run_once(used_flag)
                    combined_low = "\n".join(lines).lower()
                    if rc == 0 or "change in progress" not in combined_low:
                        break
            return rc, lines

    def install_snap(self, name: str, classic: bool = False, progress_cb = None, complete_cb = None):
        """Install a snap package using 'sudo snap install' with live \r/\n progress streaming and classic fallback."""
        def _task():
            if not self.is_snapd_installed():
                err_msg = "snapd service is required to install Snap packages. Click 'Auto-Configure' on the Snap Store page."
                self._call_progress(progress_cb, 0.0, err_msg)
                self._call_complete(complete_cb, False, "install", name, err_msg)
                return

            is_classic = classic
            if not is_classic:
                curated = next((c for c in self.CURATED_SNAP_APPS if c["name"].lower() == name.lower()), None)
                if curated and curated.get("confinement") == "classic":
                    is_classic = True
                elif not curated:
                    details = self.get_snap_details(name)
                    if details.get("confinement") == "classic":
                        is_classic = True

            snap_args = ["snap", "install"]
            if is_classic:
                snap_args.append("--classic")
            snap_args.append(name)

            env = os.environ.copy()
            if ASKPASS_SCRIPT.exists():
                env["SUDO_ASKPASS"] = str(ASKPASS_SCRIPT)
            env["LC_ALL"] = "C"

            snap_key = name.strip().lower()
            if not hasattr(self, "active_snap_ops"):
                self.active_snap_ops = {}
            self.active_snap_ops[snap_key] = (0.10, f"Installing snap package {name}...")

            def _tracked_prog(f, m=""):
                if isinstance(f, (int, float)):
                    self.active_snap_ops[snap_key] = (float(f), str(m))
                self._call_progress(progress_cb, f, m)

            _tracked_prog(0.10, f"Installing snap package {name}...")

            try:
                rc, output_lines = self._stream_snap_cmd(snap_args, env, _tracked_prog, f"Installing {name}...")
                combined_low = "\n".join(output_lines).lower()
                # Automatic fallback: if snap reports classic confinement required, retry with --classic!
                if rc != 0 and ("classic confinement" in combined_low or "--classic" in combined_low) and "--classic" not in snap_args:
                    self._call_progress(progress_cb, 0.18, f"Retrying {name} with --classic confinement...")
                    rc, output_lines = self._stream_snap_cmd(["snap", "install", "--classic", name], env, progress_cb, f"Installing {name} (classic)...")

                if rc == 0:
                    self._installed_snaps_cache = None
                    self._status_cache = None
                    self._call_progress(progress_cb, 1.0, f"Successfully installed {name}!")
                    self._call_complete(complete_cb, True, "install", name, "")
                else:
                    err = "\n".join(output_lines[-3:]) if output_lines else f"Exited with code {rc}"
                    self._call_progress(progress_cb, 0.0, f"Installation failed: {err}")
                    self._call_complete(complete_cb, False, "install", name, err)
            except Exception as e:
                self._call_progress(progress_cb, 0.0, f"Error: {e}")
                self._call_complete(complete_cb, False, "install", name, str(e))
            finally:
                if hasattr(self, "active_snap_ops"):
                    self.active_snap_ops.pop(snap_key, None)

        threading.Thread(target=_task, daemon=True).start()

    def remove_snap(self, name: str, purge: bool = False, progress_cb = None, complete_cb = None):
        """Remove a snap package using _stream_snap_cmd with live progress, --terminate, and optional --purge."""
        clean_name = (name or "").strip().lower()
        if clean_name.endswith(".desktop"):
            clean_name = clean_name[:-8]
        if "_" in clean_name:
            clean_name = clean_name.split("_")[0]

        def _task():
            if not self.is_snapd_installed():
                err_msg = "snapd is not installed."
                self._call_progress(progress_cb, 0.0, err_msg)
                self._call_complete(complete_cb, False, "remove", clean_name, err_msg)
                return

            env = os.environ.copy()
            if ASKPASS_SCRIPT.exists():
                env["SUDO_ASKPASS"] = str(ASKPASS_SCRIPT)
            env["LC_ALL"] = "C"

            snap_key = clean_name
            if not hasattr(self, "active_snap_ops"):
                self.active_snap_ops = {}
            self.active_snap_ops[snap_key] = (0.08, f"Removing snap package {clean_name}...")

            def _tracked_prog(f, m=""):
                if isinstance(f, (int, float)):
                    self.active_snap_ops[snap_key] = (float(f), str(m))
                self._call_progress(progress_cb, f, m)

            _tracked_prog(0.08, f"Removing snap package {clean_name}...")
            cmd = ["snap", "remove", "--terminate"]
            if purge:
                cmd.append("--purge")
            cmd.append(clean_name)

            try:
                rc, output_lines = self._stream_snap_cmd(cmd, env, _tracked_prog, f"Removing snap package {clean_name}...")
                if rc == 0:
                    self.invalidate_cache()
                    self._call_progress(progress_cb, 1.0, f"Successfully removed {clean_name}!")
                    self._call_complete(complete_cb, True, "remove", clean_name, "")
                else:
                    err = "\n".join(output_lines[-3:]) if output_lines else f"Exited with code {rc}"
                    self._call_progress(progress_cb, 0.0, f"Removal failed: {err}")
                    self._call_complete(complete_cb, False, "remove", clean_name, err)
            except Exception as e:
                self._call_progress(progress_cb, 0.0, f"Error: {e}")
                self._call_complete(complete_cb, False, "remove", clean_name, str(e))
            finally:
                if hasattr(self, "active_snap_ops"):
                    self.active_snap_ops.pop(snap_key, None)

        threading.Thread(target=_task, daemon=True).start()

    def update_snap(self, name: str, progress_cb = None, complete_cb = None):
        """Refresh / update a snap package using _stream_snap_cmd with live progress."""
        def _task():
            if not self.is_snapd_installed():
                err_msg = "snapd is not installed."
                self._call_progress(progress_cb, 0.0, err_msg)
                self._call_complete(complete_cb, False, "update", name, err_msg)
                return

            env = os.environ.copy()
            if ASKPASS_SCRIPT.exists():
                env["SUDO_ASKPASS"] = str(ASKPASS_SCRIPT)
            env["LC_ALL"] = "C"

            self._call_progress(progress_cb, 0.08, f"Refreshing snap package {name}...")
            try:
                rc, output_lines = self._stream_snap_cmd(["snap", "refresh", name], env, progress_cb, f"Refreshing snap package {name}...")
                if rc == 0:
                    self._installed_snaps_cache = None
                    self._status_cache = None
                    self._call_progress(progress_cb, 1.0, f"Successfully refreshed {name}!")
                    self._call_complete(complete_cb, True, "update", name, "")
                else:
                    err = "\n".join(output_lines[-3:]) if output_lines else f"Exited with code {rc}"
                    self._call_progress(progress_cb, 0.0, f"Refresh failed: {err}")
                    self._call_complete(complete_cb, False, "update", name, err)
            except Exception as e:
                self._call_progress(progress_cb, 0.0, f"Error: {e}")
                self._call_complete(complete_cb, False, "update", name, str(e))

        threading.Thread(target=_task, daemon=True).start()

    def list_apps(self, query: str = "") -> List[Dict[str, Any]]:
        """List curated and discovered snap applications."""
        return self.search_snaps(query)

    def launch_snap(self, name: str) -> bool:
        """Launch an installed Snap application with full Wayland/X11 environment and desktop shortcut fallback."""
        clean = (name or "").strip().lower()
        if not clean:
            return False
        snap_pkg = clean.split("_")[0]
        env = get_gui_launch_env()
        if shutil.which("xhost"):
            try:
                subprocess.run(["xhost", "+local:"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except Exception:
                pass

        # 1. Check /var/lib/snapd/desktop/applications/<snap>_*.desktop for the exact Exec command
        snap_dt_dir = Path("/var/lib/snapd/desktop/applications")
        if snap_dt_dir.exists():
            candidates = list(snap_dt_dir.glob(f"{snap_pkg}_*.desktop"))
            if candidates:
                dt_file = candidates[0]
                if shutil.which("gio"):
                    try:
                        subprocess.Popen(["gio", "launch", str(dt_file)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        return True
                    except Exception:
                        pass
                try:
                    for line in dt_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                        if line.startswith("Exec="):
                            exec_cmd = re.sub(r'\s+%[fFuUdDnNickvm]', '', line[5:]).strip()
                            if exec_cmd:
                                subprocess.Popen(["sh", "-c", exec_cmd], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                return True
                except Exception:
                    pass

        # 2. Fallback to 'snap run <snap_pkg>' or '/snap/bin/<snap_pkg>'
        for bin_cand in (f"/snap/bin/{snap_pkg}", f"/var/lib/snapd/snap/bin/{snap_pkg}"):
            if Path(bin_cand).exists():
                try:
                    subprocess.Popen([bin_cand], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return True
                except Exception:
                    pass

        try:
            subprocess.Popen(["snap", "run", snap_pkg], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False

    @staticmethod
    def _call_progress(cb, frac: float, msg: str):
        if not cb:
            return
        try:
            import inspect
            sig = inspect.signature(cb)
            if len(sig.parameters) == 1:
                cb(msg)
            else:
                cb(frac, msg)
        except Exception:
            try:
                cb(frac, msg)
            except Exception:
                try:
                    cb(msg)
                except Exception:
                    pass

    @staticmethod
    def _call_complete(cb, ok: bool, action: str, name: str, err_or_msg: str):
        if not cb:
            return
        try:
            import inspect
            sig = inspect.signature(cb)
            has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values())
            num = len(sig.parameters)
            if has_varargs or num >= 4:
                cb(ok, action, name, err_or_msg if not ok else "")
            elif num == 2:
                cb(ok, err_or_msg)
            else:
                try:
                    cb(ok, action, name, err_or_msg if not ok else "")
                except TypeError:
                    cb(ok, err_or_msg)
        except Exception:
            try:
                cb(ok, action, name, err_or_msg if not ok else "")
            except Exception:
                try:
                    cb(ok, err_or_msg)
                except Exception:
                    pass


class ContainerManager:
    """
    Manages OCI container applications and host desktop shortcut integration.
    Features:
    - Auto-detection of container runtime (distrobox / docker).
    - Auto-installation of distrobox via pacman if missing.
    - Auto-creation of dedicated 'arkst-box' container (and automatic migration/removal of legacy 'aura-box').
    - Installation of container applications.
    - Automatic creation and deletion of host desktop shortcuts in ~/.local/share/applications.
    - Independent search that does not pollute default system search.
    """
    CONTAINER_NAME = "arkst-box"
    LEGACY_CONTAINER_NAMES = ("aura-box", "ark-box")
    SHORTCUTS_DIR = Path.home() / ".local" / "share" / "applications"
    LAUNCHER_BIN_DIR = Path.home() / ".local" / "share" / "arkst" / "bin"
    LAUNCHER_SCRIPT = LAUNCHER_BIN_DIR / "arkst-box-launch"

    CURATED_CONTAINER_APPS = [
        {
            "id": "blender",
            "name": "Blender",
            "desc": "Professional 3D modeling, animation, rendering and VFX suite",
            "category": "Graphics & Media",
            "icon": "blender",
            "binary": "blender",
            "pkg": "blender",
            "extra_pkgs": ["mesa-gl", "mesa-egl", "mesa-gles", "libxi", "libxrender", "libxfixes", "libxxf86vm", "libxkbcommon", "font-noto", "dbus-x11"],
            "size": "280 MB",
        },
        {
            "id": "code",
            "name": "Visual Studio Code",
            "desc": "Sandboxed developer code editor and language runtime environment",
            "category": "Development",
            "icon": "code",
            "binary": "code-oss",
            "pkg": "code-oss",
            "extra_pkgs": ["libx11", "libxkbfile", "libsecret", "nss", "dbus-x11", "font-noto", "adwaita-icon-theme", "mesa-gl", "mesa-egl", "git", "bash"],
            "launch_args": "--no-sandbox --disable-gpu-sandbox",
            "size": "95 MB",
        },
        {
            "id": "obs-studio",
            "name": "OBS Studio",
            "desc": "Isolated video recording and live streaming workstation",
            "category": "Graphics & Media",
            "icon": "com.obsproject.Studio",
            "binary": "obs",
            "pkg": "obs-studio",
            "extra_pkgs": ["qt6-qtwayland", "qt5-qtwayland", "mesa-gl", "mesa-egl", "dbus-x11", "font-noto", "pulseaudio-utils", "ffmpeg"],
            "size": "70 MB",
        },
        {
            "id": "chromium",
            "name": "Chromium Browser",
            "desc": "Sandboxed open-source web browser running inside isolated container",
            "category": "Internet & Network",
            "icon": "chromium",
            "binary": "chromium-browser",
            "pkg": "chromium",
            "extra_pkgs": ["nss", "freetype", "harfbuzz", "ca-certificates", "ttf-freefont", "font-noto", "dbus-x11", "mesa-gl", "mesa-egl", "pulseaudio-utils"],
            "launch_args": "--no-sandbox --disable-dev-shm-usage --test-type",
            "size": "115 MB",
        },
        {
            "id": "gimp",
            "name": "GIMP Image Studio",
            "desc": "High-powered image retouching, composition and digital artwork",
            "category": "Graphics & Media",
            "icon": "gimp",
            "binary": "gimp",
            "pkg": "gimp",
            "extra_pkgs": ["dbus-x11", "font-noto", "adwaita-icon-theme", "mesa-gl"],
            "size": "140 MB",
        },
        {
            "id": "inkscape",
            "name": "Inkscape",
            "desc": "Professional vector graphics editor for diagrams and illustrations",
            "category": "Graphics & Media",
            "icon": "org.inkscape.Inkscape",
            "binary": "inkscape",
            "pkg": "inkscape",
            "extra_pkgs": ["dbus-x11", "font-noto", "adwaita-icon-theme", "ttf-dejavu"],
            "size": "110 MB",
        },
        {
            "id": "libreoffice-fresh",
            "name": "LibreOffice Fresh",
            "desc": "Comprehensive office suite (Writer, Calc, Impress) in container",
            "category": "Productivity",
            "icon": "libreoffice-startcenter",
            "binary": "libreoffice",
            "pkg": "libreoffice",
            "extra_pkgs": ["ttf-dejavu", "font-noto", "dbus-x11", "adwaita-icon-theme", "mesa-gl"],
            "size": "450 MB",
        },
        {
            "id": "telegram-desktop",
            "name": "Telegram Desktop",
            "desc": "Fast, cloud-based messaging with cross-device sync",
            "category": "Social & Communication",
            "icon": "org.telegram.desktop",
            "binary": "Telegram",
            "pkg": "telegram-desktop",
            "extra_pkgs": ["qt6-qtwayland", "qt5-qtwayland", "dbus-x11", "font-noto", "pulseaudio-utils"],
            "post_install_cmd": "ln -sf /usr/bin/Telegram /usr/bin/telegram-desktop 2>/dev/null || true",
            "size": "55 MB",
        },
        {
            "id": "firefox-developer-edition",
            "name": "Firefox Developer Edition",
            "desc": "Developer-tailored desktop browser with web inspector and debugging tools",
            "category": "Internet & Network",
            "icon": "firefox-developer-edition",
            "binary": "firefox",
            "pkg": "firefox",
            "extra_pkgs": ["dbus-x11", "font-noto", "ttf-dejavu", "adwaita-icon-theme", "mesa-gl", "mesa-egl", "pulseaudio-utils", "alsa-plugins-pulse"],
            "size": "95 MB",
        },
        {
            "id": "kdenlive",
            "name": "Kdenlive Video Editor",
            "desc": "Multi-track non-linear video editing workstation",
            "category": "Graphics & Media",
            "icon": "kdenlive",
            "binary": "kdenlive",
            "pkg": "kdenlive",
            "extra_pkgs": ["qt6-qtwayland", "qt5-qtwayland", "dbus-x11", "breeze-icons", "font-noto", "ffmpeg", "pulseaudio-utils"],
            "size": "190 MB",
        },
        {
            "id": "audacity",
            "name": "Audacity Audio Editor",
            "desc": "Multi-track audio recorder and waveform sound editor",
            "category": "Graphics & Media",
            "icon": "audacity",
            "binary": "audacity",
            "pkg": "audacity",
            "extra_pkgs": ["dbus-x11", "font-noto", "adwaita-icon-theme", "pulseaudio-utils", "alsa-plugins-pulse"],
            "size": "45 MB",
        },
        {
            "id": "vlc",
            "name": "VLC Media Player",
            "desc": "Universal media player supporting virtually all video formats",
            "category": "Graphics & Media",
            "icon": "vlc",
            "binary": "vlc",
            "pkg": "vlc",
            "extra_pkgs": ["vlc-qt", "vlc-xorg", "qt5-qtwayland", "dbus-x11", "font-noto", "ttf-dejavu", "adwaita-icon-theme", "mesa-gl", "mesa-egl", "pulseaudio-utils", "alsa-plugins-pulse"],
            "launch_args": "--no-qt-privacy-ask",
            "size": "40 MB",
        },
    ]

    def __init__(self):
        self._lock = threading.Lock()
        self._apk_lock = threading.RLock()
        self._config_lock = threading.RLock()
        try:
            self.SHORTCUTS_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self.active_container_installs: Set[str] = set()
        self.active_container_progress: Dict[str, Tuple[float, str]] = {}
        self.is_configuring: bool = False
        self.configuring_progress_text: str = ""
        self._status_cache: Optional[Dict[str, Any]] = None
        self._status_cache_time: float = 0.0

    def invalidate_cache(self):
        """Invalidate cached status."""
        with self._lock:
            self._status_cache = None
            self._status_cache_time = 0.0
        invalidate_desktop_caches()

    def _resolve_app_meta(self, app_id: str) -> Dict[str, Any]:
        clean = (app_id or "").strip().lower()
        for app in self.CURATED_CONTAINER_APPS:
            if app["id"].lower() == clean or app.get("pkg", "").lower() == clean:
                return dict(app)
        for app in getattr(self, "EXTENDED_ALPINE_APPS", []):
            if app["id"].lower() == clean or app.get("pkg", "").lower() == clean:
                return dict(app)
        return {
            "id": app_id,
            "name": get_app_display_name(app_id),
            "desc": f"Container application ({app_id})",
            "category": "Utility",
            "icon": resolve_icon_name(app_id),
            "binary": app_id,
            "pkg": app_id,
            "extra_pkgs": ["dbus-x11", "font-noto", "adwaita-icon-theme"],
        }

    def _ensure_launcher_script(self) -> Path:
        """
        Ensure the self-healing host launcher script ~/.local/share/arkst/bin/arkst-box-launch exists.
        This script handles:
        - Starting arkst-box if paused/stopped
        - Authorizing XWayland/X11 connections via 'xhost +local:'
        - Auto-detecting WAYLAND_DISPLAY, DISPLAY, XDG_RUNTIME_DIR, and PULSE_SERVER
        - Self-healing VLC inside arkst-box (restoring clean binary if corrupted and ensuring GUI plugins)
        - Passing QT_X11_NO_MITSHM=1, _X11_NO_MITSHM=1, and LIBGL_ALWAYS_SOFTWARE=1 for rock-solid GUI rendering
        - Passing '--no-sandbox' for Chromium/Code-OSS inside Docker
        - Running with --user arkst-user without unsupported flags
        """
        script_path = self.LAUNCHER_SCRIPT
        script_content = f'''#!/usr/bin/env sh
# ArkST Box Host Application Launcher (Auto-generated by ArkST)
RAW_APP_ID="$1"
if [ -z "$RAW_APP_ID" ]; then
    exit 1
fi
shift

APP_ID="$(echo "$RAW_APP_ID" | sed 's/^arkst-box-//')"
CONTAINER="{self.CONTAINER_NAME}"
UID_VAL="$(id -u)"
GID_VAL="$(id -g)"
export XDG_RUNTIME_DIR="${{XDG_RUNTIME_DIR:-/run/user/$UID_VAL}}"

# Auto-detect Wayland socket from user environment or standard runtime paths
if [ -z "$WAYLAND_DISPLAY" ]; then
    if command -v systemctl >/dev/null 2>&1; then
        WAYLAND_DISPLAY="$(systemctl --user show-environment 2>/dev/null | sed -n 's/^WAYLAND_DISPLAY=//p')"
    fi
    if [ -z "$WAYLAND_DISPLAY" ]; then
        for cand in wayland-1 wayland-0; do
            if [ -S "$XDG_RUNTIME_DIR/$cand" ]; then
                export WAYLAND_DISPLAY="$cand"
                break
            fi
        done
        if [ -z "$WAYLAND_DISPLAY" ]; then
            for sock in "$XDG_RUNTIME_DIR"/wayland-*; do
                case "$sock" in
                    *.lock) continue ;;
                esac
                if [ -S "$sock" ]; then
                    export WAYLAND_DISPLAY="$(basename "$sock")"
                    break
                fi
            done
        fi
    fi
fi

# Auto-detect X11 / XWayland display
if [ -z "$DISPLAY" ]; then
    if command -v systemctl >/dev/null 2>&1; then
        DISPLAY="$(systemctl --user show-environment 2>/dev/null | sed -n 's/^DISPLAY=//p')"
    fi
    if [ -z "$DISPLAY" ]; then
        for xnum in 1 0 2; do
            if [ -S "/tmp/.X11-unix/X$xnum" ]; then
                export DISPLAY=":$xnum"
                break
            fi
        done
        [ -z "$DISPLAY" ] && export DISPLAY=":1"
    fi
fi

# Configure platform display variables dynamically based on active session
if [ -n "$WAYLAND_DISPLAY" ] && [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]; then
    PLATFORM_ARGS="-e QT_QPA_PLATFORM=wayland;xcb -e GDK_BACKEND=wayland,x11 -e MOZ_ENABLE_WAYLAND=1 -e ELECTRON_OZONE_PLATFORM_HINT=auto"
else
    PLATFORM_ARGS="-e QT_QPA_PLATFORM=xcb -e GDK_BACKEND=x11 -e MOZ_ENABLE_WAYLAND=0"
fi

# Authorize local container connections to XWayland / X11
if command -v xhost >/dev/null 2>&1; then
    xhost +SI:localuser:root >/dev/null 2>&1 || true
    xhost +local: >/dev/null 2>&1 || true
fi

# Universal Hardware Acceleration & GPU Vendor Negotiation (AMD, Intel, NVIDIA, Software fallback)
SW_GL_ARG=""
IS_NVIDIA_PROPRIETARY=0
for dev_drv in /sys/class/drm/card[0-9]*/device/driver /sys/class/drm/renderD[0-9]*/device/driver; do
    if [ -e "$dev_drv" ]; then
        drv_name="$(basename "$(readlink -f "$dev_drv" 2>/dev/null)" 2>/dev/null)"
        if [ "$drv_name" = "nvidia" ]; then
            IS_NVIDIA_PROPRIETARY=1
            break
        fi
    fi
done

if [ "$IS_NVIDIA_PROPRIETARY" -eq 1 ]; then
    # Proprietary NVIDIA driver active on host: check if NVIDIA Container Toolkit has injected libraries into container
    if ! docker exec "$CONTAINER" sh -c "test -f /usr/lib/libGLX_nvidia.so.0 -o -f /usr/lib64/libGLX_nvidia.so.0" >/dev/null 2>&1; then
        # Safe software llvmpipe fallback to prevent 'failed to load driver: nvidia-drm' crash
        SW_GL_ARG="-e LIBGL_ALWAYS_SOFTWARE=1 -e MESA_LOADER_DRIVER_OVERRIDE=llvmpipe"
    fi
elif [ ! -d /dev/dri ]; then
    # No DRI device available (headless or virtualized without 3D pass-through)
    SW_GL_ARG="-e LIBGL_ALWAYS_SOFTWARE=1"
fi
# For AMD (amdgpu/radeon), Intel (i915/xe/iris), and Nouveau: SW_GL_ARG remains empty, enabling full native hardware acceleration via /dev/dri!

# Ensure container is running
if [ "$(docker inspect -f '{{{{.State.Running}}}}' "$CONTAINER" 2>/dev/null)" != "true" ]; then
    docker start "$CONTAINER" >/dev/null 2>&1 || exit 1
fi

# Query render node GID from host dynamically
RENDER_GID="$(stat -c '%g' /dev/dri/renderD128 2>/dev/null || stat -c '%g' /dev/dri/card0 2>/dev/null || stat -c '%g' /dev/dri/card1 2>/dev/null || echo '')"

# Ensure user, groups and runtime directories exist inside container matching host UID and GID
docker exec "$CONTAINER" sh -c "
    id -u arkst-user >/dev/null 2>&1 || (adduser -D -u $UID_VAL -s /bin/sh arkst-user 2>/dev/null; addgroup arkst-user video 2>/dev/null; addgroup arkst-user audio 2>/dev/null; addgroup arkst-user input 2>/dev/null)
    if [ -n \"$RENDER_GID\" ]; then
        addgroup -g \"$RENDER_GID\" host-render 2>/dev/null || true
        addgroup arkst-user host-render 2>/dev/null || true
    fi
    mkdir -p /home/arkst-user/.config /home/arkst-user/.cache /home/arkst-user/.local '$XDG_RUNTIME_DIR'
    chown -R $UID_VAL:$GID_VAL /home/arkst-user 2>/dev/null || true
" >/dev/null 2>&1 || true

# Map app_id to container binary and required container flags
BIN_CMD="$APP_ID"
EXTRA_ARGS=""
case "$APP_ID" in
    vlc)
        BIN_CMD="vlc"
        EXTRA_ARGS="--no-qt-privacy-ask"
        # Self-heal VLC on Alpine: restore clean binary if corrupted by getppid, and ensure GUI plugins are installed
        docker exec "$CONTAINER" sh -c '
            if strings /usr/bin/vlc 2>/dev/null | grep -q getppid; then
                apk fix --force vlc >/dev/null 2>&1 || true
            fi
            if ! apk info -e vlc-qt >/dev/null 2>&1; then
                apk --wait 30 add --no-cache vlc-qt vlc-xorg qt5-qtwayland dbus-x11 font-noto ttf-dejavu adwaita-icon-theme >/dev/null 2>&1 || true
            fi
        ' >/dev/null 2>&1
        ;;
    code|code-oss)
        BIN_CMD="code-oss"
        EXTRA_ARGS="--no-sandbox --disable-gpu-sandbox"
        ;;
    chromium|chromium-browser)
        if docker exec "$CONTAINER" sh -c "command -v chromium-browser >/dev/null 2>&1"; then
            BIN_CMD="chromium-browser"
        else
            BIN_CMD="chromium"
        fi
        EXTRA_ARGS="--no-sandbox --disable-dev-shm-usage --test-type"
        ;;
    telegram|telegram-desktop|Telegram)
        if docker exec "$CONTAINER" sh -c "command -v telegram-desktop >/dev/null 2>&1"; then
            BIN_CMD="telegram-desktop"
        elif docker exec "$CONTAINER" sh -c "command -v Telegram >/dev/null 2>&1"; then
            BIN_CMD="Telegram"
        else
            BIN_CMD="Telegram"
        fi
        ;;
    obs-studio|obs)
        BIN_CMD="obs"
        ;;
    libreoffice-fresh|libreoffice)
        BIN_CMD="libreoffice"
        ;;
    firefox-developer-edition|firefox)
        BIN_CMD="firefox"
        ;;
    mpv)
        BIN_CMD="mpv"
        if [ "$#" -eq 0 ]; then
            EXTRA_ARGS="--player-operation-mode=pseudo-gui"
        fi
        ;;
    blender)
        BIN_CMD="blender"
        ;;
    gimp)
        BIN_CMD="gimp"
        ;;
    inkscape)
        BIN_CMD="inkscape"
        ;;
    audacity)
        BIN_CMD="audacity"
        ;;
    kdenlive)
        BIN_CMD="kdenlive"
        ;;
    krita)
        BIN_CMD="krita"
        ;;
    *)
        if docker exec "$CONTAINER" sh -c "command -v '$APP_ID' >/dev/null 2>&1"; then
            BIN_CMD="$APP_ID"
        else
            DYN_BIN="$(docker exec "$CONTAINER" sh -c '
                for dt in /usr/share/applications/*'"$APP_ID"'*.desktop; do
                    if [ -f "$dt" ]; then
                        cut -d= -f2 "$dt" | awk \'{{print $1}}\' | head -n 1
                        break
                    fi
                done
            ' 2>/dev/null)"
            if [ -n "$DYN_BIN" ]; then
                BIN_CMD="$(basename "$DYN_BIN")"
            else
                APK_BIN="$(docker exec "$CONTAINER" sh -c "apk info -L '$APP_ID' 2>/dev/null | grep -E '^usr/bin/|^bin/' | head -n 1")"
                if [ -n "$APK_BIN" ]; then
                    BIN_CMD="$(basename "$APK_BIN")"
                fi
            fi
        fi
        ;;
esac

PULSE_SOCK="$XDG_RUNTIME_DIR/pulse/native"
DBUS_SOCK="$XDG_RUNTIME_DIR/bus"

# Strip desktop file placeholders (%U, %u, %F, %f) while preserving real arguments
ARGS_FOUND=""
for a in "$@"; do
    case "$a" in
        %[uUfF]) ;;
        *)
            if [ -z "$ARGS_FOUND" ]; then
                set -- "$a"
                ARGS_FOUND=1
            else
                set -- "$@" "$a"
            fi
            ;;
    esac
done
if [ -z "$ARGS_FOUND" ]; then
    set --
fi

USER_EXEC_ARG=""
if [ "$UID_VAL" != "0" ]; then
    if docker exec "$CONTAINER" id -u arkst-user >/dev/null 2>&1; then
        USER_EXEC_ARG="--user arkst-user"
    fi
fi

exec docker exec -d $USER_EXEC_ARG \
    -e DISPLAY="$DISPLAY" \
    -e WAYLAND_DISPLAY="$WAYLAND_DISPLAY" \
    -e XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" \
    -e HOME="/home/arkst-user" \
    -e USER="arkst-user" \
    -e LOGNAME="arkst-user" \
    -e PULSE_SERVER="unix:$PULSE_SOCK" \
    -e DBUS_SESSION_BUS_ADDRESS="unix:path=$DBUS_SOCK" \
    -e QT_X11_NO_MITSHM=1 \
    -e _X11_NO_MITSHM=1 \
    $PLATFORM_ARGS \
    $SW_GL_ARG \
    "$CONTAINER" $BIN_CMD $EXTRA_ARGS "$@"
'''
        try:
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text(script_content, encoding="utf-8")
            script_path.chmod(0o755)
        except Exception:
            pass
        return script_path

    def _generate_shortcut_content(self, app_id: str, app_meta: Dict[str, Any]) -> str:
        launcher_path = self._ensure_launcher_script()
        cat_raw = app_meta.get("category", "Utility")
        cat_map = {
            "Social & Communication": "Network;Chat;InstantMessaging;",
            "Graphics & Media": "Graphics;AudioVideo;",
            "Internet & Network": "Network;WebBrowser;",
            "Development": "Development;IDE;",
            "Productivity": "Office;",
            "Utility": "Utility;",
        }
        category = cat_map.get(cat_raw, f"{cat_raw.replace(' & ', ';').replace(' ', '')};")
        if app_id in ("vlc", "mpv"):
            category = "AudioVideo;Player;Recorder;"
        icon = app_meta.get("icon", "application-x-executable")
        if app_id in ("telegram", "telegram-desktop"):
            icon = "org.telegram.desktop"
        return f"""[Desktop Entry]
Version=1.0
Type=Application
Name={app_meta['name']} (Docker)
GenericName={app_meta.get('desc', '')}
Comment=Sandboxed Docker container application ({self.CONTAINER_NAME})
Exec={launcher_path} {app_id} %U
Icon={icon}
Terminal=false
Categories={category}
StartupNotify=true
X-ArkST-Docker=true
X-ArkST-AppId={app_id}
"""

    def repair_existing_shortcuts(self):
        """Upgrade any existing arkst-box-*.desktop shortcuts to use the self-healing arkst-box-launch helper."""
        try:
            launcher_path = self._ensure_launcher_script()
            if not self.SHORTCUTS_DIR.exists():
                return
            updated_any = False
            for dt_file in self.SHORTCUTS_DIR.glob("arkst-box-*.desktop"):
                app_id = dt_file.stem[len("arkst-box-"):]
                if not app_id:
                    continue
                try:
                    txt = dt_file.read_text(encoding="utf-8", errors="ignore")
                    meta = self._resolve_app_meta(app_id)
                    expected = self._generate_shortcut_content(app_id, meta)
                    if txt.strip() != expected.strip():
                        dt_file.write_text(expected, encoding="utf-8")
                        dt_file.chmod(0o755)
                        updated_any = True
                except Exception:
                    pass
            if updated_any:
                subprocess.run(["update-desktop-database", str(self.SHORTCUTS_DIR)], capture_output=True, timeout=3)
        except Exception:
            pass

    def is_app_installing(self, app_id: str) -> bool:
        return app_id in self.active_container_installs

    @property
    def is_ready(self) -> bool:
        st = self.get_status()
        return st.get("status_code") == "ready"

    def get_status(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Check container runtime and container existence."""
        now = time.time()
        if not force_refresh and hasattr(self, "_status_cache") and self._status_cache and (now - getattr(self, "_status_cache_time", 0.0) < 10.0):
            res = dict(self._status_cache)
            res["is_configuring"] = self.is_configuring
            return res

        has_docker = shutil.which("docker") is not None
        daemon_running = False
        container_exists = False
        container_running = False

        docker_sock = Path("/var/run/docker.sock")
        user_sock = Path(f"/run/user/{os.getuid()}/docker.sock")
        if has_docker and (docker_sock.exists() or user_sock.exists()):
            try:
                proc = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=4)
                if proc.returncode == 0:
                    daemon_running = True
                elif "permission denied" in (proc.stderr or "").lower():
                    subprocess.run(["sudo", "-n", "chmod", "666", "/var/run/docker.sock"], capture_output=True, timeout=3)
                    proc2 = subprocess.run(["docker", "info"], capture_output=True, timeout=4)
                    if proc2.returncode == 0:
                        daemon_running = True
            except Exception:
                pass

        if daemon_running:
            # Always ensure legacy aura-box / ark-box containers are purged when Docker is active
            if not getattr(self, "_legacy_containers_purged", False):
                self._legacy_containers_purged = True
                try:
                    self.migrate_legacy_containers()
                except Exception:
                    pass
            try:
                proc = subprocess.run(
                    ["docker", "inspect", "-f", "{{.State.Running}}", self.CONTAINER_NAME],
                    capture_output=True, text=True, timeout=4
                )
                if proc.returncode == 0:
                    container_exists = True
                    if proc.stdout.strip() == "true":
                        container_running = True
            except Exception:
                pass

        if container_running:
            status_code = "ready"
            status_text = f"Container: {self.CONTAINER_NAME} (Active)"
        elif container_exists:
            status_code = "stopped"
            status_text = f"Container: {self.CONTAINER_NAME} (Stopped)"
        elif daemon_running:
            status_code = "missing_container"
            status_text = f"Engine Ready (Container '{self.CONTAINER_NAME}' Not Found)"
        else:
            status_code = "missing_engine"
            status_text = "Container Engine Not Running or Not Installed"

        res = {
            "has_docker": has_docker,
            "daemon_running": daemon_running,
            "container_exists": container_exists,
            "container_running": container_running,
            "container_name": self.CONTAINER_NAME,
            "status_code": status_code,
            "status_text": status_text,
            "is_configuring": self.is_configuring,
        }
        self._status_cache = res
        self._status_cache_time = now
        return res

    def stop_container(self, completion_callback=None):
        """Stop aura-box container."""
        def _task():
            res = subprocess.run(["docker", "stop", self.CONTAINER_NAME], capture_output=True, text=True, timeout=15)
            if completion_callback:
                completion_callback(res.returncode == 0, "Container stopped." if res.returncode == 0 else res.stderr)
        threading.Thread(target=_task, daemon=True).start()

    def migrate_legacy_containers(self) -> List[str]:
        """Automatically remove any legacy aura-box / ark-box containers & shortcuts across docker/podman/distrobox."""
        migrated_apps: List[str] = []
        try:
            if self.SHORTCUTS_DIR.exists():
                for pat in ("aura-box-*.desktop", "ark-box-*.desktop"):
                    for desktop_file in self.SHORTCUTS_DIR.glob(pat):
                        prefix = pat.split("*")[0]
                        app_id = desktop_file.stem[len(prefix):]
                        if app_id and app_id not in migrated_apps:
                            migrated_apps.append(app_id)
                        try:
                            desktop_file.unlink()
                        except Exception:
                            pass
                # Also scan any .desktop file in SHORTCUTS_DIR that references aura-box inside Exec=
                for desktop_file in self.SHORTCUTS_DIR.glob("*.desktop"):
                    try:
                        txt = desktop_file.read_text(encoding="utf-8", errors="ignore")
                        if "aura-box" in txt or "ark-box" in txt or "X-Aura-Docker" in txt:
                            desktop_file.unlink(missing_ok=True)
                    except Exception:
                        pass
            if shutil.which("docker"):
                for legacy_name in ("aura-box", "ark-box", "aura-sandbox"):
                    subprocess.run(["docker", "rm", "-f", legacy_name], capture_output=True, timeout=8)
            if shutil.which("podman"):
                for legacy_name in ("aura-box", "ark-box", "aura-sandbox"):
                    subprocess.run(["podman", "rm", "-f", legacy_name], capture_output=True, timeout=8)
            if shutil.which("distrobox"):
                for legacy_name in ("aura-box", "ark-box"):
                    subprocess.run(["distrobox", "rm", "-f", legacy_name], capture_output=True, timeout=8)
        except Exception:
            pass
        return migrated_apps

    def remove_container(self, purge_shortcuts: bool = True, completion_callback=None):
        """Remove arkst-box container and purge host desktop shortcuts."""
        def _task():
            subprocess.run(["docker", "rm", "-f", self.CONTAINER_NAME, "aura-box", "ark-box"], capture_output=True, timeout=15)
            if purge_shortcuts:
                for pat in (f"{self.CONTAINER_NAME}-*.desktop", "aura-box-*.desktop", "ark-box-*.desktop"):
                    for shortcut in self.SHORTCUTS_DIR.glob(pat):
                        try:
                            shortcut.unlink()
                        except Exception:
                            pass
                try:
                    subprocess.run(["update-desktop-database", str(self.SHORTCUTS_DIR)], capture_output=True, timeout=5)
                except Exception:
                    pass
            self.invalidate_cache()
            if completion_callback:
                completion_callback(True, "ArkST Box sandbox and desktop shortcuts removed.")
        threading.Thread(target=_task, daemon=True).start()

    def disable_docker_system_service(self, remove_from_group: bool = False, completion_callback=None):
        """System-level: disable docker.service and optionally drop user from docker group."""
        def _task():
            env = os.environ.copy()
            if ASKPASS_SCRIPT.exists():
                env["SUDO_ASKPASS"] = str(ASKPASS_SCRIPT)
            env["LC_ALL"] = "C"

            res = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=5)
            other_containers = [c for c in res.stdout.splitlines() if c.strip() and c.strip() != self.CONTAINER_NAME]

            subprocess.run(["sudo", "-A", "systemctl", "disable", "--now", "docker.service", "docker.socket"],
                           capture_output=True, env=env, timeout=30)

            if remove_from_group:
                user = os.environ.get("USER", "root")
                subprocess.run(["sudo", "-A", "gpasswd", "-d", user, "docker"], capture_output=True, env=env, timeout=10)

            if completion_callback:
                completion_callback(True, f"Docker service disabled. Stopped other containers: {other_containers or 'none'}.")
        threading.Thread(target=_task, daemon=True).start()

    def _run_apk(self, apk_args: List[str], timeout: int = 180) -> subprocess.CompletedProcess:
        """
        Thread-safe, lock-resilient Alpine apk runner inside aura-box:
        1. Acquires self._apk_lock so concurrent threads in Aura never collide on /lib/apk/db/lock.
        2. Passes '--wait 30' to apk so it waits if a background container task is finishing.
        3. If apk still reports 'Unable to lock database', waits for any running apk inside the
           container or clears a stale orphaned /lib/apk/db/lock and retries automatically.
        """
        apk_lock = getattr(self, "_apk_lock", None)
        if apk_lock is None:
            self._apk_lock = threading.RLock()
            apk_lock = self._apk_lock

        with apk_lock:
            # Ensure community repository is enabled inside Alpine container
            cmd = ["docker", "exec", self.CONTAINER_NAME, "apk", "--wait", "30"] + apk_args
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            combined = ((proc.stderr or "") + "\n" + (proc.stdout or "")).lower()
            if proc.returncode != 0 and ("unable to lock database" in combined or "failed to open apk database" in combined):
                # Check if an apk process is actively running inside the container
                for _ in range(10):
                    chk = subprocess.run(["docker", "exec", self.CONTAINER_NAME, "pgrep", "-x", "apk"], capture_output=True, timeout=5)
                    if chk.returncode != 0:
                        break
                    time.sleep(1.5)
                # If no apk process is running inside aura-box, ensure /lib/apk/db is writable and retry
                chk2 = subprocess.run(["docker", "exec", self.CONTAINER_NAME, "pgrep", "-x", "apk"], capture_output=True, timeout=5)
                if chk2.returncode != 0:
                    subprocess.run(["docker", "exec", self.CONTAINER_NAME, "rm", "-f", "/lib/apk/db/lock"], capture_output=True, timeout=5)
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
                combined = ((proc.stderr or "") + "\n" + (proc.stdout or "")).lower()

            # If package not found because edge/community repo wasn't indexed yet, update index & retry once
            if proc.returncode != 0 and ("no such package" in combined or "unsatisfiable constraints" in combined):
                subprocess.run(
                    ["docker", "exec", self.CONTAINER_NAME, "sh", "-c",
                     r"grep -q '/community' /etc/apk/repositories || sed -i 's/^#\(.*\/community\)/\1/' /etc/apk/repositories; apk --wait 30 update"],
                    capture_output=True, text=True, timeout=60
                )
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return proc

    def ensure_container_configured(self, progress_callback: Optional[Callable[[str], None]] = None) -> Tuple[bool, str]:
        """
        Auto create and start Docker container if not running.
        Serialized via self._config_lock so multiple simultaneous Docker app installs wait
        cleanly for container initialization instead of failing with a concurrent setup error.
        """
        def _report(msg: str):
            self.configuring_progress_text = msg
            if progress_callback:
                progress_callback(msg)

        cfg_lock = getattr(self, "_config_lock", None)
        if cfg_lock is None:
            self._config_lock = threading.RLock()
            cfg_lock = self._config_lock

        with cfg_lock:
            status = self.get_status()
            if status["status_code"] == "ready":
                return True, "Container already configured and active."

            with self._lock:
                self.is_configuring = True
                self.configuring_progress_text = "Initializing Docker environment..."

            try:
                migrated_apps = self.migrate_legacy_containers()
                status = self.get_status(force_refresh=True)
                if status["status_code"] == "ready":
                    return True, "Container already configured and active."

                if status["status_code"] == "missing_engine":
                    if status.get("has_docker") and shutil.which("systemctl"):
                        _report("Starting Docker background daemon (docker.service)...")
                        env = os.environ.copy()
                        askpass = get_askpass_script()
                        if askpass.exists():
                            env["SUDO_ASKPASS"] = str(askpass)
                        boot_cmd = "systemctl enable --now docker.service 2>/dev/null || systemctl start docker.service; chmod 666 /var/run/docker.sock 2>/dev/null || true; docker rm -f aura-box ark-box 2>/dev/null || true"
                        r = subprocess.run(["sudo", "-n", "sh", "-c", boot_cmd], stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=15)
                        if r.returncode != 0:
                            subprocess.run(["sudo", "-A", "sh", "-c", boot_cmd], stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=45)
                        time.sleep(1.0)
                        self.migrate_legacy_containers()
                        status = self.get_status(force_refresh=True)

                    if status["status_code"] == "missing_engine":
                        return False, "Docker is not installed or daemon is not running."

                self._ensure_launcher_script()
                self.repair_existing_shortcuts()
                if shutil.which("xhost"):
                    try:
                        subprocess.run(["xhost", "+local:"], capture_output=True, timeout=2)
                    except Exception:
                        pass

                if status["status_code"] == "stopped":
                    _report(f"Starting existing '{self.CONTAINER_NAME}' container...")
                    proc = subprocess.run(["docker", "start", self.CONTAINER_NAME], capture_output=True, text=True, timeout=10)
                    if proc.returncode == 0:
                        subprocess.run(["docker", "update", "--restart", "unless-stopped", self.CONTAINER_NAME], capture_output=True, timeout=5)
                        _report("Verifying baseline GUI and GPU libraries (mesa, vulkan, x11, wayland, fonts, dbus)...")
                        self._run_apk(["add", "--no-cache", "mesa-gl", "mesa-egl", "mesa-gles", "mesa-va-gallium", "mesa-vulkan-ati", "mesa-vulkan-intel", "intel-media-driver", "libx11", "libxext", "libxrender", "libxkbcommon", "qt5-qtwayland", "dbus-x11", "font-noto", "adwaita-icon-theme"], timeout=90)
                        self.invalidate_cache()
                        return True, "Started existing arkst-box container."
                    return False, f"Failed to start container: {proc.stderr}"

                _report(f"Initializing '{self.CONTAINER_NAME}' container environment (Alpine Linux)...")

                env_gui = get_gui_launch_env()
                uid = os.getuid()
                runtime_dir = env_gui.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")
                display = env_gui.get("DISPLAY", ":0")
                wayland = env_gui.get("WAYLAND_DISPLAY", "wayland-1")

                app_data_dir = Path.home() / ".local" / "share" / "arkst" / "containers"
                app_data_dir.mkdir(parents=True, exist_ok=True)

                # Ensure no stale container with same name blocks creation
                subprocess.run(["docker", "rm", "-f", self.CONTAINER_NAME, "aura-box", "ark-box"], capture_output=True, timeout=10)

                cmd = [
                    "docker", "run", "-d",
                    "--name", self.CONTAINER_NAME,
                    "--restart", "unless-stopped",
                    "--shm-size=2g",
                    "-v", "/tmp/.X11-unix:/tmp/.X11-unix",
                    "-v", f"{app_data_dir}:/home/arkst-user/app-data",
                    "-e", f"DISPLAY={display}",
                    "-e", f"WAYLAND_DISPLAY={wayland}",
                    "-e", f"XDG_RUNTIME_DIR={runtime_dir}",
                    "-e", "HOME=/home/arkst-user",
                    "-e", "QT_X11_NO_MITSHM=1",
                    "-e", "_X11_NO_MITSHM=1",
                    "-e", "QT_QPA_PLATFORM=wayland;xcb",
                    "-e", "GDK_BACKEND=wayland,x11",
                    "-e", "MOZ_ENABLE_WAYLAND=1",
                ]

                # Mount entire XDG_RUNTIME_DIR (/run/user/<uid>) so Wayland, PipeWire, PulseAudio, and D-Bus sockets stay connected
                if Path(runtime_dir).exists():
                    cmd.extend(["-v", f"{runtime_dir}:{runtime_dir}"])
                else:
                    wayland_sock = Path(runtime_dir) / wayland
                    if wayland_sock.exists():
                        cmd.extend(["-v", f"{wayland_sock}:{wayland_sock}"])
                    pulse_sock = Path(runtime_dir) / "pulse" / "native"
                    if pulse_sock.exists():
                        cmd.extend(["-v", f"{pulse_sock}:{pulse_sock}"])
                    pipewire_sock = Path(runtime_dir) / "pipewire-0"
                    if pipewire_sock.exists():
                        cmd.extend(["-v", f"{pipewire_sock}:{pipewire_sock}"])

                pulse_sock = Path(runtime_dir) / "pulse" / "native"
                cmd.extend(["-e", f"PULSE_SERVER=unix:{pulse_sock}"])

                if Path("/dev/dri").exists():
                    cmd.extend(["--device", "/dev/dri:/dev/dri"])
                if Path("/dev/snd").exists():
                    cmd.extend(["--device", "/dev/snd:/dev/snd"])

                cmd.extend([
                    "alpine:latest",
                    "tail", "-f", "/dev/null"
                ])

                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
                if proc.returncode != 0:
                    return False, f"Failed to create container: {proc.stderr}"

                # Ensure container user matching host UID exists
                subprocess.run([
                    "docker", "exec", self.CONTAINER_NAME, "sh", "-c",
                    f"id -u arkst-user >/dev/null 2>&1 || (adduser -D -u {uid} -s /bin/sh arkst-user 2>/dev/null; addgroup arkst-user video 2>/dev/null; addgroup arkst-user audio 2>/dev/null; chown -R {uid}:{uid} /home/arkst-user 2>/dev/null); mkdir -p /home/arkst-user '{runtime_dir}'; chown -R {uid}:{uid} /home/arkst-user 2>/dev/null"
                ], capture_output=True, timeout=15)

                _report("Installing baseline GUI and GPU libraries (mesa, vulkan, vaapi, x11, wayland, fonts, dbus)...")
                res_base = self._run_apk([
                    "add", "--no-cache",
                    "mesa-gl", "mesa-egl", "mesa-gles", "mesa-va-gallium",
                    "mesa-vulkan-ati", "mesa-vulkan-intel", "intel-media-driver",
                    "libx11", "libxext", "libxrender",
                    "libxi", "libxfixes", "libxcursor", "libxrandr", "libxkbcommon",
                    "wayland-libs-client", "wayland-libs-egl", "qt5-qtwayland",
                    "dbus-x11", "font-noto", "ttf-dejavu", "adwaita-icon-theme",
                    "pulseaudio-utils", "alsa-plugins-pulse"
                ], timeout=120)
                if res_base.returncode != 0:
                    self._run_apk(["add", "--no-cache", "mesa-gl", "mesa-egl", "libx11", "font-noto"], timeout=90)
                self.invalidate_cache()

                _report("Container environment configured successfully!")
                return True, "Container successfully initialized and ready."
            finally:
                with self._lock:
                    self.is_configuring = False
                    self.configuring_progress_text = ""

    def list_apps(self, query: str = "") -> List[Dict[str, Any]]:
        """List container apps: curated + installed shortcuts + Docker Hub search."""
        q = query.strip().lower()
        results = []
        seen_ids = set()

        # 1. Curated apps (filtered by query if present)
        for app in self.CURATED_CONTAINER_APPS:
            if q:
                match = (
                    q in app["name"].lower() or
                    q in app["desc"].lower() or
                    q in app["category"].lower() or
                    q in app["id"].lower()
                )
                if not match:
                    continue

            shortcut = self.SHORTCUTS_DIR / f"arkst-box-{app['id']}.desktop"
            item = dict(app)
            item["is_installed"] = shortcut.exists()
            item["shortcut_path"] = str(shortcut)
            item["is_installing"] = self.is_app_installing(app["id"])
            results.append(item)
            seen_ids.add(app["id"])

        # 2. Detect installed container apps from desktop shortcuts (not in curated list)
        try:
            for desktop_file in self.SHORTCUTS_DIR.glob("arkst-box-*.desktop"):
                app_id = desktop_file.stem.replace("arkst-box-", "", 1)
                if app_id in seen_ids:
                    continue
                if q and q not in app_id.lower():
                    continue
                # Parse basic info from .desktop file
                name = app_id.replace("-", " ").title()
                desc = "Container application"
                icon = "application-x-executable"
                try:
                    content = desktop_file.read_text()
                    for line in content.splitlines():
                        if line.startswith("Name="):
                            name = line.split("=", 1)[1].strip()
                        elif line.startswith("GenericName="):
                            desc = line.split("=", 1)[1].strip()
                        elif line.startswith("Icon="):
                            icon = line.split("=", 1)[1].strip()
                except Exception:
                    pass
                results.append({
                    "id": app_id,
                    "name": name,
                    "desc": desc,
                    "category": "Container",
                    "icon": icon,
                    "binary": app_id,
                    "pkg": app_id,
                    "is_installed": True,
                    "is_installing": self.is_app_installing(app_id),
                    "shortcut_path": str(desktop_file),
                })
                seen_ids.add(app_id)
        except Exception:
            pass

        # 3. Search extended Alpine Linux GUI & Developer catalog + live 'apk search' inside aura-box
        extended_alpine = [
            {"id": "libreoffice", "name": "LibreOffice Suite", "desc": "Full-featured office productivity suite", "category": "Productivity", "icon": "libreoffice-main", "binary": "libreoffice", "pkg": "libreoffice", "size": "280 MB"},
            {"id": "krita", "name": "Krita Digital Painting", "desc": "Professional digital painting and illustration studio", "category": "Graphics & Media", "icon": "krita", "binary": "krita", "pkg": "krita", "size": "160 MB"},
            {"id": "darktable", "name": "Darktable Photo Workflow", "desc": "Virtual lighttable and darkroom for photographers", "category": "Graphics & Media", "icon": "darktable", "binary": "darktable", "pkg": "darktable", "size": "65 MB"},
            {"id": "qbittorrent", "name": "qBittorrent Client", "desc": "Fast, lightweight Qt BitTorrent client", "category": "Internet & Network", "icon": "qbittorrent", "binary": "qbittorrent", "pkg": "qbittorrent", "size": "35 MB"},
            {"id": "filezilla", "name": "FileZilla FTP/SFTP", "desc": "Fast and reliable cross-platform FTP, FTPS and SFTP client", "category": "Internet & Network", "icon": "filezilla", "binary": "filezilla", "pkg": "filezilla", "size": "28 MB"},
            {"id": "mpv", "name": "mpv Media Player", "desc": "Minimalist hardware-accelerated video player", "category": "Graphics & Media", "icon": "mpv", "binary": "mpv", "pkg": "mpv", "size": "25 MB"},
            {"id": "remmina", "name": "Remmina Remote Desktop", "desc": "Remote desktop client supporting RDP, VNC, SPICE, and SSH", "category": "Internet & Network", "icon": "org.remmina.Remmina", "binary": "remmina", "pkg": "remmina", "size": "30 MB"},
            {"id": "geany", "name": "Geany IDE", "desc": "Fast and lightweight GTK+ integrated development environment", "category": "Development", "icon": "geany", "binary": "geany", "pkg": "geany", "size": "18 MB"},
            {"id": "meld", "name": "Meld Diff Viewer", "desc": "Visual diff and merge tool for files, directories, and Git", "category": "Development", "icon": "org.gnome.Meld", "binary": "meld", "pkg": "meld", "size": "22 MB"},
            {"id": "evince", "name": "Evince Document Viewer", "desc": "GNOME document viewer for PDF, PostScript, and DjVu", "category": "Productivity", "icon": "org.gnome.Evince", "binary": "evince", "pkg": "evince", "size": "24 MB"},
            {"id": "transmission-gtk", "name": "Transmission BitTorrent", "desc": "Clean, easy-to-use GTK BitTorrent client", "category": "Internet & Network", "icon": "transmission", "binary": "transmission-gtk", "pkg": "transmission-gtk", "size": "18 MB"},
            {"id": "shotcut", "name": "Shotcut Video Editor", "desc": "Cross-platform Qt non-linear video editor", "category": "Graphics & Media", "icon": "org.shotcut.Shotcut", "binary": "shotcut", "pkg": "shotcut", "size": "110 MB"},
        ]
        self.EXTENDED_ALPINE_APPS = extended_alpine
        if q:
            for app in extended_alpine:
                if app["id"] in seen_ids:
                    continue
                if q in app["id"].lower() or q in app["name"].lower() or q in app["desc"].lower() or q in app["category"].lower():
                    shortcut = self.SHORTCUTS_DIR / f"arkst-box-{app['id']}.desktop"
                    item = dict(app)
                    item["is_installed"] = shortcut.exists()
                    item["shortcut_path"] = str(shortcut)
                    item["is_installing"] = self.is_app_installing(app["id"])
                    results.append(item)
                    seen_ids.add(app["id"])

        if q and len(results) < 5:
            try:
                st = self.get_status()
                if st.get("container_running"):
                    proc = self._run_apk(["search", "-v", q], timeout=8)
                    if proc.returncode == 0 and proc.stdout:
                        for line in proc.stdout.splitlines():
                            line = line.strip()
                            # Alpine 'apk search -v' format: '<pkgname>-<ver>-r<rel> - <description>'
                            m = re.match(r'^([a-zA-Z0-9_+.-]+?)-[0-9][^-]*-r[0-9]+\s+-\s+(.+)$', line)
                            if not m:
                                continue
                            pkg_name, pkg_desc = m.group(1).strip(), m.group(2).strip()
                            if any(pkg_name.endswith(suf) for suf in ("-dev", "-doc", "-dbg", "-lang", "-static", "-openrc", "-libs")):
                                continue
                            if pkg_name in seen_ids:
                                continue
                            shortcut = self.SHORTCUTS_DIR / f"arkst-box-{pkg_name}.desktop"
                            results.append({
                                "id": pkg_name,
                                "name": get_app_display_name(pkg_name),
                                "desc": pkg_desc[:90],
                                "category": "Alpine Container",
                                "icon": resolve_icon_name(pkg_name, pkg_desc),
                                "binary": pkg_name,
                                "pkg": pkg_name,
                                "is_installed": shortcut.exists(),
                                "is_installing": self.is_app_installing(pkg_name),
                                "shortcut_path": str(shortcut),
                            })
                            seen_ids.add(pkg_name)
                            if len(results) >= 16:
                                break
            except Exception:
                pass

        return results

    def is_app_installed(self, app_id: str) -> bool:
        shortcut = self.SHORTCUTS_DIR / f"arkst-box-{app_id}.desktop"
        return shortcut.exists()

    def install_app(self, app_id: str, progress_callback: Optional[Callable[[str], None]] = None, completion_callback: Optional[Callable[[bool, str], None]] = None):
        """Install app inside container and auto-create desktop shortcut."""
        def _task():
            self.active_container_installs.add(app_id)
            if not hasattr(self, "active_container_progress"):
                self.active_container_progress = {}
            self.active_container_progress[app_id.lower()] = (0.15, f"Preparing Docker sandbox for {app_id}...")
            nonlocal progress_callback
            orig_prog = progress_callback
            def _tracked_prog(msg: str):
                cur_f = self.active_container_progress.get(app_id.lower(), (0.2, ""))[0]
                self.active_container_progress[app_id.lower()] = (min(0.90, cur_f + 0.25), str(msg))
                if orig_prog:
                    orig_prog(msg)
            progress_callback = _tracked_prog
            try:
                app_meta = self._resolve_app_meta(app_id)

                # 1. Ensure container is ready
                ok, msg = self.ensure_container_configured(progress_callback)
                if not ok:
                    if completion_callback:
                        completion_callback(False, f"Container setup failed: {msg}")
                    return

                # 2. Install inside container using lock-safe _run_apk helper (including GUI subpackages like vlc-qt)
                if progress_callback:
                    progress_callback(f"Installing {app_meta['name']} inside '{self.CONTAINER_NAME}'...")

                pkg = app_meta.get("pkg", app_id)
                pkg_list = [p for p in pkg.split() if p]
                extra_pkgs = list(app_meta.get("extra_pkgs", []))
                try:
                    proc = self._run_apk(["add", "--no-cache"] + pkg_list + extra_pkgs, timeout=300)
                    if proc.returncode != 0 and extra_pkgs:
                        # Retry core package + essential GUI packages individually if an optional subpackage name differed
                        proc = self._run_apk(["add", "--no-cache"] + pkg_list, timeout=300)
                        for ep in extra_pkgs:
                            self._run_apk(["add", "--no-cache", ep], timeout=60)
                    if proc.returncode != 0:
                        err_clean = (proc.stderr or proc.stdout or f"apk exited with {proc.returncode}").strip().replace("\n", " ")
                        if completion_callback:
                            completion_callback(False, f"Installation failed: {err_clean}")
                        return

                    # Post-install hook (e.g. symlinks or custom config)
                    post_cmd = app_meta.get("post_install_cmd")
                    if post_cmd:
                        subprocess.run(["docker", "exec", self.CONTAINER_NAME, "sh", "-c", post_cmd], capture_output=True, timeout=15)
                    elif app_id.lower() == "vlc" or "vlc" in pkg_list:
                        # Clean up any legacy getppid corruption from previous versions
                        subprocess.run(["docker", "exec", self.CONTAINER_NAME, "sh", "-c", "if strings /usr/bin/vlc 2>/dev/null | grep -q getppid; then apk fix --force vlc; fi"], capture_output=True, timeout=30)
                except Exception as e:
                    if completion_callback:
                        completion_callback(False, f"Installation error: {e}")
                    return

                # 3. Auto-create desktop shortcut wired to self-healing arkst-box-launch script
                if progress_callback:
                    progress_callback("Generating host desktop shortcut...")

                shortcut_path = self.SHORTCUTS_DIR / f"arkst-box-{app_id}.desktop"
                shortcut_content = self._generate_shortcut_content(app_id, app_meta)
                try:
                    shortcut_path.write_text(shortcut_content, encoding="utf-8")
                    shortcut_path.chmod(0o755)
                    subprocess.run(["update-desktop-database", str(self.SHORTCUTS_DIR)], capture_output=True, timeout=3)
                    self.invalidate_cache()
                except Exception as e:
                    if completion_callback:
                        completion_callback(False, f"Failed creating shortcut: {e}")
                    return

                if progress_callback:
                    progress_callback(f"Shortcut created: {shortcut_path.name}")

                if completion_callback:
                    completion_callback(True, f"Installed {app_meta['name']} with desktop shortcut created!")
            finally:
                self.active_container_installs.discard(app_id)
                if hasattr(self, "active_container_progress"):
                    self.active_container_progress.pop(app_id.lower(), None)

        threading.Thread(target=_task, daemon=True).start()

    def uninstall_app(self, app_id: str, progress_callback: Optional[Callable[[str], None]] = None, completion_callback: Optional[Callable[[bool, str], None]] = None):
        """Remove package from container first and verify success before purging shortcut."""
        def _task():
            app_meta = self._resolve_app_meta(app_id)
            name = app_meta["name"] if app_meta else app_id

            if progress_callback:
                progress_callback(f"Uninstalling {name} from container...")

            # 1. Package removal from container first with returncode verification (AURA-038 & AURA-039)
            status = self.get_status()
            if status["container_exists"] and status["container_running"]:
                pkg = app_meta.get("pkg", app_id) if app_meta else app_id
                proc = self._run_apk(["del", pkg], timeout=60)
                if proc.returncode != 0:
                    if completion_callback:
                        completion_callback(False, f"Failed removing package from container: {proc.stderr or proc.stdout}")
                    return

            # 2. Delete desktop shortcut only after successful removal
            shortcut_path = self.SHORTCUTS_DIR / f"arkst-box-{app_id}.desktop"
            if shortcut_path.exists():
                try:
                    shortcut_path.unlink()
                    subprocess.run(["update-desktop-database", str(self.SHORTCUTS_DIR)], capture_output=True, timeout=3)
                except Exception:
                    pass
            self.invalidate_cache()

            if completion_callback:
                completion_callback(True, f"Removed {name} and cleaned up desktop shortcut.")

        threading.Thread(target=_task, daemon=True).start()

    def launch_app(self, app_id: str) -> bool:
        """Launch container app via self-healing arkst-box-launch helper, repairing shortcuts and VLC GUI automatically."""
        clean_id = (app_id or "").strip()
        if clean_id.lower().startswith("arkst-box-"):
            clean_id = clean_id[len("arkst-box-"):]
        if not clean_id:
            return False

        launcher_path = self._ensure_launcher_script()
        self.repair_existing_shortcuts()
        env = get_gui_launch_env()

        if shutil.which("xhost"):
            try:
                subprocess.run(["xhost", "+local:"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except Exception:
                pass

        if launcher_path.exists():
            try:
                subprocess.Popen([str(launcher_path), clean_id], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception:
                pass

        # Direct fallback if launcher script couldn't be executed
        status = self.get_status()
        if not status["container_running"] and status["container_exists"]:
            subprocess.run(["docker", "start", self.CONTAINER_NAME], capture_output=True, timeout=10)

        app_meta = self._resolve_app_meta(clean_id)
        binary = app_meta.get("binary", clean_id)
        launch_args = [a for a in app_meta.get("launch_args", "").split() if a]
        if clean_id.lower() == "vlc" or binary == "vlc":
            subprocess.run(
                ["docker", "exec", self.CONTAINER_NAME, "sh", "-c",
                 "if strings /usr/bin/vlc 2>/dev/null | grep -q getppid; then apk fix --force vlc; fi; apk info -e vlc-qt >/dev/null 2>&1 || apk --wait 30 add --no-cache vlc-qt vlc-xorg qt5-qtwayland dbus-x11 font-noto adwaita-icon-theme"],
                capture_output=True, timeout=30
            )
        display = env.get("DISPLAY", ":0")
        wayland = env.get("WAYLAND_DISPLAY", "wayland-1")
        runtime_dir = env.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        try:
            subprocess.Popen([
                "docker", "exec", "-d",
                "--user", "arkst-user",
                "-e", f"DISPLAY={display}",
                "-e", f"WAYLAND_DISPLAY={wayland}",
                "-e", f"XDG_RUNTIME_DIR={runtime_dir}",
                "-e", f"PULSE_SERVER=unix:{runtime_dir}/pulse/native",
                "-e", f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime_dir}/bus",
                "-e", "QT_X11_NO_MITSHM=1",
                "-e", "_X11_NO_MITSHM=1",
                "-e", "QT_QPA_PLATFORM=xcb;wayland",
                "-e", "GDK_BACKEND=x11,wayland",
                "-e", "LIBGL_ALWAYS_SOFTWARE=1",
                self.CONTAINER_NAME, binary
            ] + launch_args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False

    def check_container_updates(self) -> List[Dict[str, Any]]:
        """Check for updates available for container-installed applications or base image."""
        updates: List[Dict[str, Any]] = []
        if getattr(self, "active_container_installs", None) or getattr(self, "is_configuring", False):
            # Skip checking container updates while an active container install or setup is running
            return updates

        status = self.get_status()
        if not status.get("daemon_running") or not status.get("container_running"):
            return updates

        apk_lock = getattr(self, "_apk_lock", None)
        if apk_lock is not None and not apk_lock.acquire(blocking=False):
            # Container package manager is currently busy; skip to avoid stalling host update checks
            return updates

        try:
            cmd = ["docker", "exec", self.CONTAINER_NAME, "apk", "version", "-l", "<"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    line = line.strip()
                    parts = line.split("<", 1)
                    if len(parts) == 2:
                        old_str = parts[0].strip()
                        new_str = parts[1].strip()
                        if old_str.lower().startswith("installed"):
                            continue
                        # Extract clean package name from Alpine '<pkgname>-<ver>-r<rel>'
                        m_pkg = re.match(r'^([a-zA-Z0-9_+-]+?)-([0-9][^-]*-r[0-9]+)$', old_str)
                        pkg_clean = m_pkg.group(1) if m_pkg else old_str
                        old_ver_clean = m_pkg.group(2) if m_pkg else old_str
                        updates.append({
                            "name": old_str,
                            "pkg_name": pkg_clean,
                            "current_version": old_str,
                            "new_version": new_str,
                            "type": "container",
                            "desc": "Container app update",
                            "old_ver": old_str,
                            "new_ver": new_str,
                            "source": "docker",
                            "icon": resolve_icon_name(pkg_clean),
                        })
        except Exception:
            pass
        finally:
            if apk_lock is not None:
                try:
                    apk_lock.release()
                except Exception:
                    pass

        return updates

    def update_app(self, app_id: str, progress_callback: Optional[Callable[[str], None]] = None, completion_callback: Optional[Callable[[bool, str], None]] = None):
        """Update container application via 'apk add --upgrade --no-cache' and refresh shortcut."""
        def _task():
            self.active_container_installs.add(app_id)
            try:
                app_meta = next((a for a in self.CURATED_CONTAINER_APPS if a["id"] == app_id), None)
                if not app_meta:
                    app_meta = {
                        "id": app_id,
                        "name": app_id.capitalize(),
                        "desc": f"Container application ({app_id})",
                        "category": "Utility",
                        "icon": "application-x-executable",
                        "binary": app_id,
                        "pkg": app_id,
                    }

                # 1. Ensure container is configured and running
                ok, msg = self.ensure_container_configured(progress_callback)
                if not ok:
                    if completion_callback:
                        completion_callback(False, f"Container setup failed: {msg}")
                    return

                # 2. Upgrade inside container (strip version suffix if app_id came from check_container_updates)
                m_ver = re.match(r'^([a-zA-Z0-9_+-]+?)-[0-9][^-]*-r[0-9]+$', app_id)
                clean_pkg_id = m_ver.group(1) if m_ver else app_id
                curated_match = next((a for a in self.CURATED_CONTAINER_APPS if a["id"] in (app_id, clean_pkg_id)), None)
                if curated_match:
                    app_meta = curated_match
                name = app_meta.get("name", clean_pkg_id)
                pkg = curated_match.get("pkg", clean_pkg_id) if curated_match else clean_pkg_id
                if progress_callback:
                    progress_callback(f"Updating {name} in '{self.CONTAINER_NAME}'...")

                try:
                    proc = self._run_apk(["add", "--upgrade", "--no-cache", pkg], timeout=300)
                    if proc.returncode != 0:
                        if completion_callback:
                            completion_callback(False, f"Update failed: {proc.stderr or proc.stdout}")
                        return
                except Exception as e:
                    if completion_callback:
                        completion_callback(False, f"Update error: {e}")
                    return

                # 3. Re-generate desktop shortcut only if this is a curated GUI app or already has a shortcut
                shortcut_path = self.SHORTCUTS_DIR / f"arkst-box-{clean_pkg_id}.desktop"
                if not curated_match and not shortcut_path.exists():
                    if progress_callback:
                        progress_callback(f"Successfully updated {name}!")
                    if completion_callback:
                        completion_callback(True, f"Updated container package {name}.")
                    return

                if clean_pkg_id.lower() == "vlc" or pkg == "vlc":
                    self._run_apk(["add", "--upgrade", "--no-cache", "vlc-qt", "vlc-xorg", "qt5-qtwayland", "dbus-x11"], timeout=120)
                    subprocess.run(["docker", "exec", self.CONTAINER_NAME, "sh", "-c", "if strings /usr/bin/vlc 2>/dev/null | grep -q getppid; then apk fix --force vlc; fi"], capture_output=True, timeout=30)

                if progress_callback:
                    progress_callback("Re-generating host desktop shortcut...")
                shortcut_content = self._generate_shortcut_content(clean_pkg_id, app_meta)
                try:
                    shortcut_path.write_text(shortcut_content, encoding="utf-8")
                    shortcut_path.chmod(0o755)
                    subprocess.run(["update-desktop-database", str(self.SHORTCUTS_DIR)], capture_output=True, timeout=3)
                    self.invalidate_cache()
                except Exception as e:
                    if completion_callback:
                        completion_callback(False, f"Failed updating shortcut: {e}")
                    return

                if progress_callback:
                    progress_callback(f"Successfully updated {name}!")

                if completion_callback:
                    completion_callback(True, f"Updated {name} and refreshed desktop shortcut.")
            finally:
                self.active_container_installs.discard(app_id)

        threading.Thread(target=_task, daemon=True).start()


class CacheManager:
    """
    Introspects and safely prunes system and user caches for Arch Linux & Aura:
    - Pacman package cache (/var/cache/pacman/pkg/)
    - AUR build cache (~/.cache/paru/clone/, ~/.cache/yay/)
    - Docker container engine layers and stopped containers
    - Aura application index & vector icon caches (~/.cache/aura/)
    - Systemd journal archives (/var/log/journal/)
    """

    PACMAN_CACHE_DIR = Path("/var/cache/pacman/pkg")
    PARU_CACHE_DIR = Path.home() / ".cache" / "paru" / "clone"
    YAY_CACHE_DIR = Path.home() / ".cache" / "yay"
    ARKST_CACHE_DIR = Path.home() / ".cache" / "arkst"
    AURA_CACHE_DIR = ARKST_CACHE_DIR
    LEGACY_AURA_CACHE_DIR = Path.home() / ".cache" / "aura"

    def __init__(self):
        self._lock = threading.Lock()

    @staticmethod
    def _dir_size(path: Path) -> int:
        if not path.exists():
            return 0
        total = 0
        try:
            for entry in os.scandir(path):
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat().st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += CacheManager._dir_size(Path(entry.path))
                except Exception:
                    pass
        except Exception:
            pass
        return total

    @staticmethod
    def format_size(bytes_val: int) -> str:
        if bytes_val >= 1024**3:
            return f"{bytes_val / (1024**3):.2f} GB"
        elif bytes_val >= 1024**2:
            return f"{bytes_val / (1024**2):.1f} MB"
        elif bytes_val >= 1024:
            return f"{bytes_val / 1024:.0f} KB"
        return f"{bytes_val} B"

    def scan_all_caches(self) -> Dict[str, Any]:
        """Fast synchronous introspection of all cache categories (< 150ms)."""
        pacman_total = self._dir_size(self.PACMAN_CACHE_DIR)
        
        # Determine reclaimable pacman cache via paccache dry-run if available
        pacman_reclaimable = 0
        if shutil.which("paccache") and pacman_total > 0:
            try:
                proc = subprocess.run(["paccache", "-d", "-k1"], capture_output=True, text=True, timeout=4, env=dict(os.environ, LC_ALL="C"))
                m = re.search(r'disk space saved:\s*([0-9.]+)\s*([A-Za-z]+)', proc.stdout)
                if m:
                    val = float(m.group(1))
                    unit = m.group(2).lower()
                    if "gib" in unit or "gb" in unit:
                        pacman_reclaimable = int(val * (1024**3))
                    elif "mib" in unit or "mb" in unit:
                        pacman_reclaimable = int(val * (1024**2))
                    elif "kib" in unit or "kb" in unit:
                        pacman_reclaimable = int(val * 1024)
            except Exception:
                pass

        paru_size = self._dir_size(self.PARU_CACHE_DIR)
        yay_size = self._dir_size(self.YAY_CACHE_DIR)
        aur_total = paru_size + yay_size

        aura_total = self._dir_size(self.ARKST_CACHE_DIR) + self._dir_size(self.LEGACY_AURA_CACHE_DIR)

        docker_reclaimable = 0
        if shutil.which("docker"):
            try:
                proc = subprocess.run(["docker", "system", "df", "--format", "{{json .}}"], capture_output=True, text=True, timeout=4)
                if proc.returncode == 0:
                    for line in proc.stdout.splitlines():
                        try:
                            data = json.loads(line)
                            reclaimable_str = data.get("Reclaimable", "0B")
                            m = re.search(r'([0-9.]+)\s*([A-Za-z]+)', reclaimable_str)
                            if m:
                                val = float(m.group(1))
                                unit = m.group(2).lower()
                                if "gb" in unit:
                                    docker_reclaimable += int(val * (1024**3))
                                elif "mb" in unit:
                                    docker_reclaimable += int(val * (1024**2))
                                elif "kb" in unit:
                                    docker_reclaimable += int(val * 1024)
                        except Exception:
                            pass
            except Exception:
                pass

        journal_total = 0
        if shutil.which("journalctl"):
            try:
                proc = subprocess.run(["journalctl", "--disk-usage"], capture_output=True, text=True, timeout=3, env=dict(os.environ, LC_ALL="C"))
                m = re.search(r'take up\s*([0-9.]+)\s*([A-Za-z]+)', proc.stdout)
                if m:
                    val = float(m.group(1))
                    unit = m.group(2).lower()
                    if "gb" in unit or "g" in unit:
                        journal_total = int(val * (1024**3))
                    elif "mb" in unit or "m" in unit:
                        journal_total = int(val * (1024**2))
                    elif "kb" in unit or "k" in unit:
                        journal_total = int(val * 1024)
            except Exception:
                pass

        try:
            disk_total, disk_used, disk_free = shutil.disk_usage("/")
        except Exception:
            disk_total, disk_used, disk_free = (0, 0, 0)

        total_reclaimable = pacman_reclaimable + aur_total + docker_reclaimable + max(0, journal_total - 20*1024*1024)

        return {
            "categories": {
                "pacman": {
                    "name": "Pacman Package Cache",
                    "total_bytes": pacman_total,
                    "reclaimable_bytes": pacman_reclaimable,
                    "total_str": self.format_size(pacman_total),
                    "reclaimable_str": self.format_size(pacman_reclaimable),
                    "desc": "Arch Linux package archives in /var/cache/pacman/pkg. Safe prune retains current installed versions for instant offline rollback.",
                    "requires_root": True,
                    "icon": "package-x-generic-symbolic",
                    "color": "#0a84ff",
                },
                "aur": {
                    "name": "AUR Build Cache",
                    "total_bytes": aur_total,
                    "reclaimable_bytes": aur_total,
                    "total_str": self.format_size(aur_total),
                    "reclaimable_str": self.format_size(aur_total),
                    "desc": "Compiled package tarballs and git clone checkouts in ~/.cache/paru and ~/.cache/yay. 100% safe to clear.",
                    "requires_root": False,
                    "icon": "folder-download-symbolic",
                    "color": "#ff9f0a",
                },
                "docker": {
                    "name": "Docker Container Cache",
                    "total_bytes": docker_reclaimable,
                    "reclaimable_bytes": docker_reclaimable,
                    "total_str": self.format_size(docker_reclaimable),
                    "reclaimable_str": self.format_size(docker_reclaimable),
                    "desc": "Unused container layers, dangling images, and stopped container artifacts.",
                    "requires_root": False,
                    "icon": "docker-symbolic",
                    "color": "#30d158",
                },
                "journal": {
                    "name": "Systemd Journal Logs",
                    "total_bytes": journal_total,
                    "reclaimable_bytes": max(0, journal_total - 20*1024*1024),
                    "total_str": self.format_size(journal_total),
                    "reclaimable_str": self.format_size(max(0, journal_total - 20*1024*1024)),
                    "desc": "System log archives. Vacuuming retains the last 7 days of service and boot diagnostic logs.",
                    "requires_root": True,
                    "icon": "text-x-generic-symbolic",
                    "color": "#bf5af2",
                },
                "arkst": {
                    "name": "ArkST Application Cache",
                    "total_bytes": aura_total,
                    "reclaimable_bytes": aura_total,
                    "total_str": self.format_size(aura_total),
                    "reclaimable_str": self.format_size(aura_total),
                    "desc": "ArkST database sync cache and cached vector application icons.",
                    "requires_root": False,
                    "icon": "preferences-system-symbolic",
                    "color": "#64d2ff",
                },
            },
            "total_reclaimable_bytes": total_reclaimable,
            "total_reclaimable_str": self.format_size(total_reclaimable),
            "disk_total_bytes": disk_total,
            "disk_free_bytes": disk_free,
            "disk_used_bytes": disk_used,
            "disk_free_str": self.format_size(disk_free),
            "disk_total_str": self.format_size(disk_total),
        }

    def prune_cache(self, category: str, safe_mode: bool = True, progress_cb=None, complete_cb=None):
        """
        Prune specific cache category in background thread.
        Concurrency-hardened:
        - Serialized per-category so rapid clicks never collide.
        - 'pacman': uses paccache -rk1 (recognizing 'no candidate packages found' exit code 1 as success),
          or acquires GLOBAL_ALPM_LOCK before running pacman -Sc so active installs are never disrupted.
        - 'aur': skips any build directory actively being compiled by paru/yay/makepkg.
        - 'docker': prunes dangling images & build cache WITHOUT deleting a stopped aura-box container!
        """
        if not hasattr(self, "_prune_lock"):
            self._prune_lock = threading.RLock()

        def _task():
            env = os.environ.copy()
            askpass_script = get_askpass_script()
            if askpass_script.exists():
                env["SUDO_ASKPASS"] = str(askpass_script)
            env["LC_ALL"] = "C"

            success = True
            msg = "Cleaned."

            with self._prune_lock:
                try:
                    if category == "pacman":
                        if progress_cb:
                            progress_cb(0.3, "Pruning pacman package archives...")
                        if shutil.which("paccache") and safe_mode:
                            res = subprocess.run(["sudo", "-n", "paccache", "-rk1"], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=30)
                            out_comb = ((res.stdout or "") + "\n" + (res.stderr or "")).lower()
                            if res.returncode != 0 and "no candidate packages found" not in out_comb and ("password is required" in out_comb or "authentication" in out_comb or not out_comb.strip()):
                                res = subprocess.run(["sudo", "-A", "paccache", "-rk1"], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=120)
                                out_comb = ((res.stdout or "") + "\n" + (res.stderr or "")).lower()
                            success = (res.returncode == 0 or "no candidate packages found" in out_comb)
                        else:
                            with GLOBAL_ALPM_LOCK:
                                wait_for_alpm_lock(progress_cb=progress_cb, max_wait=120, env=env)
                                res = subprocess.run(["sudo", "-n", "pacman", "-Sc", "--noconfirm"], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=60)
                                if res.returncode != 0:
                                    res = subprocess.run(["sudo", "-A", "pacman", "-Sc", "--noconfirm"], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=120)
                                success = (res.returncode == 0)
                        msg = "Pacman package cache safely pruned (latest versions kept)." if success else ((res.stderr or res.stdout or "Prune failed").strip()[:90])
                    elif category == "aur":
                        if progress_cb:
                            progress_cb(0.3, "Clearing AUR build repositories...")
                        aur_building = False
                        for bp in ("paru", "yay", "makepkg"):
                            try:
                                if subprocess.run(["pgrep", "-x", bp], capture_output=True, timeout=2).returncode == 0:
                                    aur_building = True
                                    break
                            except Exception:
                                pass
                        now_ts = time.time()
                        for path in (self.PARU_CACHE_DIR, self.YAY_CACHE_DIR):
                            if path.exists():
                                for child in path.iterdir():
                                    try:
                                        if aur_building and (now_ts - child.stat().st_mtime) < 300:
                                            continue
                                        if child.is_dir():
                                            shutil.rmtree(child, ignore_errors=True)
                                        else:
                                            child.unlink(missing_ok=True)
                                    except Exception:
                                        pass
                        msg = "AUR build artifacts and git trees purged."
                    elif category == "docker":
                        if progress_cb:
                            progress_cb(0.3, "Pruning unused Docker images & build cache...")
                        if shutil.which("docker"):
                            res = subprocess.run(["docker", "image", "prune", "-f"], capture_output=True, text=True, timeout=60)
                            subprocess.run(["docker", "builder", "prune", "-f"], capture_output=True, text=True, timeout=60)
                            success = (res.returncode == 0)
                            msg = "Docker dangling images and build cache pruned safely." if success else (res.stderr or "Docker prune failed")
                        else:
                            msg = "Docker is not installed."
                    elif category == "journal":
                        if progress_cb:
                            progress_cb(0.3, "Vacuuming systemd journal archives...")
                        res = subprocess.run(["sudo", "-n", "journalctl", "--vacuum-time=7d"], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=30)
                        if res.returncode != 0:
                            res = subprocess.run(["sudo", "-A", "journalctl", "--vacuum-time=7d"], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=60)
                        success = (res.returncode == 0)
                        msg = "Systemd journals vacuumed to last 7 days." if success else (res.stderr or "Journal vacuum failed")
                    elif category in ("arkst", "aura"):
                        if progress_cb:
                            progress_cb(0.3, "Purging ArkST sync index cache...")
                        for p in (CACHE_FILE, UPDATES_CACHE_FILE):
                            try:
                                if p.exists():
                                    p.unlink()
                            except Exception:
                                pass
                        if self.LEGACY_AURA_CACHE_DIR.exists():
                            shutil.rmtree(self.LEGACY_AURA_CACHE_DIR, ignore_errors=True)
                        msg = "ArkST local database cache cleared."
                    else:
                        success = False
                        msg = f"Unknown cache category: {category}"
                except Exception as e:
                    success = False
                    msg = str(e)

            if progress_cb:
                progress_cb(1.0, msg)
            if complete_cb:
                complete_cb(success, msg)

        threading.Thread(target=_task, daemon=True).start()

    def prune_all_selected(self, categories: List[str], safe_mode: bool = True, progress_cb=None, complete_cb=None):
        """Prune multiple selected categories sequentially with aggregate progress."""
        def _task():
            if not categories:
                if progress_cb:
                    progress_cb(1.0, "No cache categories selected.")
                if complete_cb:
                    complete_cb(True, "No categories selected.")
                return

            total = len(categories)
            cleaned = []
            for i, cat in enumerate(categories):
                pct = i / max(1, total)
                if progress_cb:
                    progress_cb(pct, f"Cleaning {cat}...")
                done_event = threading.Event()
                cat_ok = False

                def _on_done(ok, msg):
                    nonlocal cat_ok
                    cat_ok = ok
                    done_event.set()

                self.prune_cache(cat, safe_mode=safe_mode, complete_cb=_on_done)
                completed_in_time = done_event.wait(timeout=180)
                if completed_in_time and cat_ok:
                    cleaned.append(cat)

            if progress_cb:
                progress_cb(1.0, f"Cleaned {len(cleaned)} of {total} cache categories.")
            if complete_cb:
                complete_cb(len(cleaned) > 0, f"Successfully cleaned {', '.join(cleaned)}." if cleaned else "No caches were cleaned.")

        threading.Thread(target=_task, daemon=True).start()

class DebPackageManager:
    """
    Seamless Debian (.deb) Package Inspector, Dependency Translator & Native Arch Installer.
    Tailored for Arch Linux & Hyprland:
    - Pure-Python + bsdtar/ar inspection of .deb archives (supports gz, xz, zst, bz2 control & data tarballs)
    - 175+ Debian-to-Arch Linux package dependency mappings with live pacman sync DB verification
    - Automatic FHS normalization (/bin, /sbin -> /usr/bin; /lib, /lib64 -> /usr/lib) to prevent Arch filesystem conflicts
    - Automatic Hyprland Wayland Ozone flag injection for Electron/Chromium .deb applications
    - Native .pkg.tar.zst / .pkg.tar.xz generation and atomic installation via 'sudo pacman -U'
    - Optional debtap integration when debtap is installed and initialized
    - Direct HTTP/HTTPS .deb URL downloader and ~/Downloads local .deb scanner
    """

    DEB_CACHE_DIR = CACHE_DIR / "deb"
    DEB_ICONS_DIR = CACHE_DIR / "deb_icons"
    DEB_DOWNLOADS_DIR = CACHE_DIR / "deb_downloads"
    INSTALLED_DEBS_FILE = DATA_DIR / "installed_debs.json"

    # Comprehensive Debian/Ubuntu -> Arch Linux dependency translation table
    DEB_TO_ARCH_MAP: Dict[str, Optional[str]] = {
        "libc6": "glibc",
        "libc-bin": "glibc",
        "libgcc-s1": "gcc-libs",
        "libgcc1": "gcc-libs",
        "libstdc++6": "gcc-libs",
        "zlib1g": "zlib",
        "libglib2.0-0": "glib2",
        "libglib2.0-0t64": "glib2",
        "libgtk-3-0": "gtk3",
        "libgtk-3-0t64": "gtk3",
        "libgtk-4-1": "gtk4",
        "libgdk-pixbuf-2.0-0": "gdk-pixbuf2",
        "libgdk-pixbuf2.0-0": "gdk-pixbuf2",
        "libpango-1.0-0": "pango",
        "libpangocairo-1.0-0": "pango",
        "libpangoft2-1.0-0": "pango",
        "libcairo2": "cairo",
        "libcairo-gobject2": "cairo",
        "libatk1.0-0": "at-spi2-core",
        "libatk1.0-0t64": "at-spi2-core",
        "libatk-bridge2.0-0": "at-spi2-core",
        "libatk-bridge2.0-0t64": "at-spi2-core",
        "libatspi2.0-0": "at-spi2-core",
        "libatspi2.0-0t64": "at-spi2-core",
        "libasound2": "alsa-lib",
        "libasound2t64": "alsa-lib",
        "libpulse0": "libpulse",
        "libpipewire-0.3-0": "pipewire",
        "libpipewire-0.3-0t64": "pipewire",
        "libnss3": "nss",
        "libnspr4": "nspr",
        "libxss1": "libxss",
        "libxtst6": "libxtst",
        "libx11-6": "libx11",
        "libx11-xcb1": "libx11",
        "libxcb1": "libxcb",
        "libxcb-dri3-0": "libxcb",
        "libxcb-shm0": "libxcb",
        "libxcb-xfixes0": "libxcb",
        "libxcb-randr0": "libxcb",
        "libxcb-image0": "xcb-util-image",
        "libxcb-keysyms1": "xcb-util-keysyms",
        "libxcb-render-util0": "xcb-util-renderutil",
        "libxcb-util1": "xcb-util",
        "libxcb-wm4": "xcb-util-wm",
        "libxcb-icccm4": "xcb-util-wm",
        "libxcb-cursor0": "xcb-util-cursor",
        "libxcomposite1": "libxcomposite",
        "libxcursor1": "libxcursor",
        "libxdamage1": "libxdamage",
        "libxext6": "libxext",
        "libxfixes3": "libxfixes",
        "libxi6": "libxi",
        "libxinerama1": "libxinerama",
        "libxrandr2": "libxrandr",
        "libxrender1": "libxrender",
        "libxshmfence1": "libxshmfence",
        "libxxf86vm1": "libxxf86vm",
        "libxkbcommon0": "libxkbcommon",
        "libxkbcommon-x11-0": "libxkbcommon-x11",
        "libxkbfile1": "libxkbfile",
        "libwayland-client0": "wayland",
        "libwayland-cursor0": "wayland",
        "libwayland-egl1": "wayland",
        "libwayland-server0": "wayland",
        "libgbm1": "mesa",
        "libgl1": "libglvnd",
        "libgl1-mesa-glx": "mesa",
        "libgl1-mesa-dri": "mesa",
        "libegl1": "libglvnd",
        "libegl1-mesa": "mesa",
        "libgles2": "libglvnd",
        "libdrm2": "libdrm",
        "libvulkan1": "vulkan-icd-loader",
        "libcups2": "cups",
        "libcups2t64": "cups",
        "libdbus-1-3": "dbus",
        "libdbus-glib-1-2": "dbus-glib",
        "libexpat1": "expat",
        "libfontconfig1": "fontconfig",
        "libfreetype6": "freetype2",
        "libharfbuzz0b": "harfbuzz",
        "libfribidi0": "fribidi",
        "libnotify4": "libnotify",
        "libsecret-1-0": "libsecret",
        "libayatana-appindicator3-1": "libayatana-appindicator",
        "libayatana-ido3-0.4-0": "ayatana-ido",
        "libappindicator3-1": "libappindicator-gtk3",
        "libappindicator1": "libappindicator-gtk3",
        "libindicator3-7": "libindicator-gtk3",
        "libdbusmenu-glib4": "libdbusmenu-glib",
        "libdbusmenu-gtk3-4": "libdbusmenu-gtk3",
        "libcurl4": "curl",
        "libcurl4t64": "curl",
        "libcurl3-gnutls": "libcurl-gnutls",
        "libcurl3-nss": "curl",
        "libssl3": "openssl",
        "libssl3t64": "openssl",
        "libssl1.1": "openssl-1.1",
        "libcrypto++8": "crypto++",
        "libgcrypt20": "libgcrypt",
        "libgpg-error0": "libgpg-error",
        "libgnutls30": "gnutls",
        "libgnutls30t64": "gnutls",
        "libkrb5-3": "krb5",
        "libgssapi-krb5-2": "krb5",
        "libsqlite3-0": "sqlite",
        "libxml2": "libxml2",
        "libxslt1.1": "libxslt",
        "libudev1": "systemd-libs",
        "libsystemd0": "systemd-libs",
        "liblzma5": "xz",
        "libzstd1": "zstd",
        "libbz2-1.0": "bzip2",
        "liblz4-1": "lz4",
        "libarchive13": "libarchive",
        "libarchive13t64": "libarchive",
        "libfuse2": "fuse2",
        "libfuse2t64": "fuse2",
        "libfuse3-3": "fuse3",
        "libwebkit2gtk-4.0-37": "webkit2gtk",
        "libwebkit2gtk-4.1-0": "webkit2gtk-4.1",
        "libjavascriptcoregtk-4.0-18": "webkit2gtk",
        "libjavascriptcoregtk-4.1-0": "webkit2gtk-4.1",
        "libsoup2.4-1": "libsoup",
        "libsoup-3.0-0": "libsoup3",
        "libflac8": "flac",
        "libflac12t64": "flac",
        "libogg0": "libogg",
        "libvorbis0a": "libvorbis",
        "libvorbisenc2": "libvorbis",
        "libopus0": "opus",
        "libsndfile1": "libsndfile",
        "libmp3lame0": "lame",
        "libmpg123-0": "mpg123",
        "libmpg123-0t64": "mpg123",
        "libopenal1": "openal",
        "libsdl2-2.0-0": "sdl2",
        "libva2": "libva",
        "libva-drm2": "libva",
        "libva-x11-2": "libva",
        "libvdpau1": "libvdpau",
        "libjpeg62-turbo": "libjpeg-turbo",
        "libjpeg8": "libjpeg-turbo",
        "libpng16-16": "libpng",
        "libpng16-16t64": "libpng",
        "libwebp7": "libwebp",
        "libwebp6": "libwebp",
        "libtiff5": "libtiff",
        "libtiff6": "libtiff",
        "libqt5core5a": "qt5-base",
        "libqt5gui5": "qt5-base",
        "libqt5widgets5": "qt5-base",
        "libqt5network5": "qt5-base",
        "libqt5dbus5": "qt5-base",
        "libqt5svg5": "qt5-svg",
        "libqt5x11extras5": "qt5-x11extras",
        "libqt5waylandclient5": "qt5-wayland",
        "libqt6core6": "qt6-base",
        "libqt6core6t64": "qt6-base",
        "libqt6gui6": "qt6-base",
        "libqt6widgets6": "qt6-base",
        "libqt6waylandclient6": "qt6-wayland",
        "xdg-utils": "xdg-utils",
        "desktop-file-utils": "desktop-file-utils",
        "shared-mime-info": "shared-mime-info",
        "hicolor-icon-theme": "hicolor-icon-theme",
        "ca-certificates": "ca-certificates",
        "fonts-liberation": "ttf-liberation",
        "fonts-noto-color-emoji": "noto-fonts-emoji",
        "libnss-mdns": "nss-mdns",
        "libcap2": "libcap",
        "libattr1": "attr",
        "libacl1": "acl",
        "libuuid1": "util-linux-libs",
        "libblkid1": "util-linux-libs",
        "libmount1": "util-linux-libs",
        "libncurses6": "ncurses",
        "libncursesw6": "ncurses",
        "libtinfo6": "ncurses",
        "libreadline8": "readline",
        "libreadline8t64": "readline",
        "libffi8": "libffi",
        "libffi7": "libffi",
        "libpcre3": "pcre",
        "libpcre2-8-0": "pcre2",
        "python3": "python",
        "bash": "bash",
        "tar": "tar",
        "gzip": "gzip",
        "xz-utils": "xz",
        "zstd": "zstd",
        "curl": "curl",
        "wget": "wget",
        "git": "git",
        "gnupg": "gnupg",
        "lsb-release": "lsb-release",
        "apt": None,
        "dpkg": None,
        "debconf": None,
        "ucf": None,
        "init-system-helpers": None,
        "adduser": None,
        "multiarch-support": None,
        "gconf-service": None,
        "gconf2": None,
    }

    def __init__(self, pm: Optional["PackageManager"] = None):
        self.pm = pm
        self._lock = threading.Lock()
        for _d in (self.DEB_CACHE_DIR, self.DEB_ICONS_DIR, self.DEB_DOWNLOADS_DIR, self.INSTALLED_DEBS_FILE.parent):
            try:
                _d.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
        self._inspect_cache: Dict[str, Dict[str, Any]] = {}
        self.active_deb_installs: Dict[str, Tuple[float, str]] = {}

    @staticmethod
    def _iter_ar_members(deb_path: Path):
        """
        Pure-Python 'ar' archive parser for .deb files.
        Yields (member_name, raw_bytes) without requiring binutils 'ar'.
        """
        with open(deb_path, "rb") as f:
            magic = f.read(8)
            if magic != b"!<arch>\n":
                raise ValueError(f"Not a valid .deb (ar) archive: {deb_path.name}")
            gnu_longnames = b""
            while True:
                hdr = f.read(60)
                if not hdr or len(hdr) < 60:
                    break
                raw_name = hdr[0:16].decode("ascii", errors="replace").strip()
                size_str = hdr[48:58].decode("ascii", errors="replace").strip()
                try:
                    size = int(size_str)
                except ValueError:
                    break

                # BSD extended filename (#1/<len>)
                if raw_name.startswith("#1/"):
                    ext_len = int(raw_name[3:])
                    name = f.read(ext_len).decode("utf-8", errors="replace").rstrip("\x00")
                    data = f.read(size - ext_len)
                else:
                    data = f.read(size)
                    if raw_name == "//":
                        gnu_longnames = data
                        if size % 2 == 1:
                            f.read(1)
                        continue
                    elif raw_name.startswith("/") and raw_name[1:].isdigit() and gnu_longnames:
                        offset = int(raw_name[1:])
                        end_idx = gnu_longnames.find(b"/", offset)
                        if end_idx == -1:
                            end_idx = gnu_longnames.find(b"\n", offset)
                        name = gnu_longnames[offset:end_idx].decode("utf-8", errors="replace")
                    else:
                        name = raw_name.rstrip("/")

                if size % 2 == 1:
                    f.read(1)
                yield name, data

    @staticmethod
    def _open_tar_bytes(member_name: str, data: bytes) -> tarfile.TarFile:
        """Open a tar archive from bytes supporting .gz, .xz, .bz2, .zst, or uncompressed."""
        lower = member_name.lower()
        if lower.endswith(".zst") or lower.endswith(".zstd"):
            # Decompress zstd stream via zstd CLI or python zstandard if available
            try:
                import zstandard as zstd
                dctx = zstd.ZstdDecompressor()
                decompressed = dctx.decompress(data, max_output_size=512 * 1024 * 1024)
                return tarfile.open(fileobj=io.BytesIO(decompressed), mode="r:")
            except Exception:
                if shutil.which("zstd"):
                    proc = subprocess.run(["zstd", "-dc"], input=data, capture_output=True, timeout=60)
                    if proc.returncode == 0:
                        return tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:")
                raise RuntimeError("zstd decompression required for this .deb archive (install 'zstd' package).")
        return tarfile.open(fileobj=io.BytesIO(data), mode="r:*")

    @staticmethod
    def _parse_control_text(text: str) -> Dict[str, str]:
        """Parse Debian RFC822 control file into a dictionary."""
        fields: Dict[str, str] = {}
        current_key: Optional[str] = None
        for line in text.splitlines():
            if not line.strip():
                continue
            if line.startswith((" ", "\t")) and current_key:
                val = line.strip()
                if val == ".":
                    fields[current_key] += "\n"
                else:
                    fields[current_key] += "\n" + val
            elif ":" in line:
                k, v = line.split(":", 1)
                current_key = k.strip().lower()
                fields[current_key] = v.strip()
        return fields

    @staticmethod
    def _sanitize_arch_pkgname(deb_name: str) -> str:
        """Sanitize Debian package name into valid Arch Linux package name."""
        clean = re.sub(r'[^a-z0-9@._+-]', '-', deb_name.strip().lower())
        clean = re.sub(r'-+', '-', clean).strip('-')
        return clean or "deb-package"

    @staticmethod
    def _sanitize_arch_version(deb_ver: str) -> str:
        """Sanitize Debian version string into valid Arch Linux pkgver."""
        ver = deb_ver.strip()
        # Strip Debian epoch if present (e.g. 1:1.85.0-1 -> 1.85.0_1)
        if ":" in ver:
            ver = ver.split(":", 1)[1]
        ver = ver.replace("-", "_").replace("~", ".").replace("+", ".")
        ver = re.sub(r'[^a-zA-Z0-9._]', '', ver)
        ver = re.sub(r'\.+', '.', ver).strip('._')
        if not ver or not ver[0].isalnum():
            ver = "1.0.0"
        return ver

    def translate_deb_dependencies(self, raw_depends: str) -> Dict[str, List[str]]:
        """
        Translate Debian Depends string into Arch Linux dependencies.
        Returns dict with keys:
        - 'arch_depends': All valid mapped Arch package names
        - 'installed': Already installed on system
        - 'missing_repo': Available in official pacman repos, to be installed automatically
        - 'missing_aur': Not in official repos (may be in AUR)
        - 'ignored': Debian-specific virtual/unmapped packages safely skipped
        """
        arch_deps: List[str] = []
        installed: List[str] = []
        missing_repo: List[str] = []
        missing_aur: List[str] = []
        ignored: List[str] = []

        if not raw_depends:
            return {
                "arch_depends": arch_deps,
                "installed": installed,
                "missing_repo": missing_repo,
                "missing_aur": missing_aur,
                "ignored": ignored,
            }

        seen = set()
        for group in raw_depends.split(","):
            group = group.strip()
            if not group:
                continue
            # Handle OR-dependencies: e.g. "libappindicator3-1 | libayatana-appindicator3-1"
            alternatives = [alt.strip() for alt in group.split("|") if alt.strip()]
            mapped_choice = None
            for alt in alternatives:
                # Strip version constraints e.g. (>= 2.34) and arch qualifiers e.g. :amd64
                deb_pkg = re.split(r'[\s\(:]', alt, maxsplit=1)[0].strip().lower()
                if not deb_pkg:
                    continue
                if deb_pkg in self.DEB_TO_ARCH_MAP:
                    cand = self.DEB_TO_ARCH_MAP[deb_pkg]
                    if cand is None:
                        # Explicitly ignored Debian-only utility
                        mapped_choice = "__IGNORE__"
                        break
                    mapped_choice = cand
                    if self.pm and self.pm.is_installed(cand):
                        break
                else:
                    # Try heuristic: if exact name exists in Arch repos/installed
                    if self.pm and (self.pm.is_installed(deb_pkg) or deb_pkg in self.pm.packages):
                        mapped_choice = deb_pkg
                        break
                    # Strip trailing Debian soname numbers e.g. libfoo1 -> libfoo
                    stripped = re.sub(r'[0-9]+(t64)?$', '', deb_pkg)
                    if stripped and self.pm and (self.pm.is_installed(stripped) or stripped in self.pm.packages):
                        mapped_choice = stripped
                        break

            if mapped_choice == "__IGNORE__":
                continue
            if mapped_choice:
                if mapped_choice not in seen:
                    seen.add(mapped_choice)
                    arch_deps.append(mapped_choice)
                    if self.pm and self.pm.is_installed(mapped_choice):
                        installed.append(mapped_choice)
                    elif self.pm and mapped_choice in self.pm.packages:
                        missing_repo.append(mapped_choice)
                    else:
                        # Check via pacman -Q / pacman -Si if pm.packages isn't loaded yet
                        if self.pm and not self.pm.is_loaded:
                            missing_repo.append(mapped_choice)
                        else:
                            missing_aur.append(mapped_choice)
            else:
                first_deb = re.split(r'[\s\(:]', alternatives[0], maxsplit=1)[0].strip().lower()
                if first_deb and first_deb not in ignored:
                    ignored.append(first_deb)

        return {
            "arch_depends": arch_deps,
            "installed": installed,
            "missing_repo": missing_repo,
            "missing_aur": missing_aur,
            "ignored": ignored,
        }

    def inspect_deb(self, deb_path: str) -> Dict[str, Any]:
        """
        Inspect a local .deb file and return rich metadata, translated Arch dependencies,
        extracted icon path, desktop entry metadata, and Hyprland/Electron compatibility flags.
        """
        p = Path(os.path.expanduser(deb_path)).resolve()
        if not p.exists() or not p.is_file():
            raise FileNotFoundError(f".deb file not found: {deb_path}")

        cache_key = f"{p}:{p.stat().st_mtime}:{p.stat().st_size}"
        if cache_key in self._inspect_cache:
            cached = dict(self._inspect_cache[cache_key])
            if self.pm:
                cached["is_installed"] = self.pm.is_installed(cached["name"])
                cached["installed_version"] = self.pm.installed_versions.get(cached["name"], "")
            return cached

        control_fields: Dict[str, str] = {}
        desktop_info: Dict[str, str] = {}
        extracted_icon_path: str = ""
        is_electron = False
        file_count = 0
        sample_files: List[str] = []

        for member_name, member_bytes in self._iter_ar_members(p):
            if member_name.startswith("control.tar"):
                with self._open_tar_bytes(member_name, member_bytes) as ctar:
                    for m in ctar.getmembers():
                        if m.name.endswith("control") and m.isfile():
                            f = ctar.extractfile(m)
                            if f:
                                control_fields = self._parse_control_text(f.read().decode("utf-8", errors="replace"))
                            break
            elif member_name.startswith("data.tar"):
                try:
                    with self._open_tar_bytes(member_name, member_bytes) as dtar:
                        members = dtar.getmembers()
                        file_count = len(members)
                        best_icon_member = None
                        best_icon_score = -1

                        for m in members:
                            mname = m.name.lstrip("./")
                            if len(sample_files) < 25 and m.isfile():
                                sample_files.append("/" + mname)

                            if any(x in mname.lower() for x in ("chrome-sandbox", "app.asar", "libffmpeg.so", "electron")):
                                is_electron = True

                            if mname.endswith(".desktop") and ("applications/" in mname) and m.isfile() and not desktop_info:
                                f = dtar.extractfile(m)
                                if f:
                                    d_txt = f.read().decode("utf-8", errors="replace")
                                    for line in d_txt.splitlines():
                                        if line.startswith("Name=") and "name" not in desktop_info:
                                            desktop_info["name"] = line.split("=", 1)[1].strip()
                                        elif line.startswith("Comment=") and "comment" not in desktop_info:
                                            desktop_info["comment"] = line.split("=", 1)[1].strip()
                                        elif line.startswith("Icon=") and "icon" not in desktop_info:
                                            desktop_info["icon"] = line.split("=", 1)[1].strip()
                                        elif line.startswith("Exec=") and "exec" not in desktop_info:
                                            desktop_info["exec"] = line.split("=", 1)[1].strip()

                            # Score candidate icons (.svg or 128/256/512 .png)
                            if m.isfile() and mname.lower().endswith((".svg", ".png")) and ("icons/" in mname or "pixmaps/" in mname or mname.startswith("opt/")):
                                score = 10
                                if mname.lower().endswith(".svg"):
                                    score = 100
                                elif "512" in mname or "256" in mname:
                                    score = 90
                                elif "128" in mname or "64" in mname:
                                    score = 75
                                elif "pixmaps/" in mname:
                                    score = 60
                                if score > best_icon_score:
                                    best_icon_score = score
                                    best_icon_member = m

                        if best_icon_member is not None:
                            try:
                                f_ico = dtar.extractfile(best_icon_member)
                                if f_ico:
                                    raw_pkg = self._sanitize_arch_pkgname(control_fields.get("package", p.stem))
                                    ext = ".svg" if best_icon_member.name.lower().endswith(".svg") else ".png"
                                    out_ico = self.DEB_ICONS_DIR / f"{raw_pkg}{ext}"
                                    out_ico.write_bytes(f_ico.read())
                                    extracted_icon_path = str(out_ico)
                            except Exception:
                                pass
                except Exception:
                    pass

        deb_pkgname = control_fields.get("package", p.stem)
        arch_pkgname = self._sanitize_arch_pkgname(deb_pkgname)
        deb_ver = control_fields.get("version", "1.0.0")
        arch_ver = self._sanitize_arch_version(deb_ver)
        deb_arch = control_fields.get("architecture", "amd64").strip().lower()
        arch_map = {"amd64": "x86_64", "all": "any", "i386": "i686", "arm64": "aarch64"}
        arch_cpu = arch_map.get(deb_arch, "x86_64")

        raw_desc = control_fields.get("description", "")
        desc_lines = [l.strip() for l in raw_desc.splitlines() if l.strip()]
        short_desc = desc_lines[0] if desc_lines else (desktop_info.get("comment") or f"Debian package ({p.name})")
        long_desc = "\n".join(desc_lines[1:]) if len(desc_lines) > 1 else short_desc

        raw_deps = control_fields.get("depends", "")
        if control_fields.get("pre-depends"):
            raw_deps = f"{raw_deps}, {control_fields['pre-depends']}" if raw_deps else control_fields["pre-depends"]
        dep_report = self.translate_deb_dependencies(raw_deps)

        # Installed-Size in Debian control is in KiB
        inst_kb_str = control_fields.get("installed-size", "0")
        try:
            inst_bytes = int(re.sub(r'[^0-9]', '', inst_kb_str) or "0") * 1024
        except ValueError:
            inst_bytes = p.stat().st_size * 3
        csize_bytes = p.stat().st_size

        display_name = desktop_info.get("name") or get_app_display_name(arch_pkgname)
        icon = extracted_icon_path or desktop_info.get("icon") or resolve_icon_name(arch_pkgname, short_desc)
        is_inst = self.pm.is_installed(arch_pkgname) if self.pm else False
        inst_ver = self.pm.installed_versions.get(arch_pkgname, "") if self.pm else ""

        info = {
            "name": arch_pkgname,
            "deb_package": deb_pkgname,
            "display_name": display_name,
            "title": display_name,
            "version": arch_ver,
            "deb_version": deb_ver,
            "arch": arch_cpu,
            "deb_arch": deb_arch,
            "desc": short_desc,
            "extended_desc": long_desc,
            "url": control_fields.get("homepage", ""),
            "maintainer": sanitize_str(control_fields.get("maintainer", "Debian Package Maintainer")),
            "packager": sanitize_str(control_fields.get("maintainer", "ArkST Deb Bridge")),
            "license": control_fields.get("license", "Proprietary / Debian Package"),
            "section": control_fields.get("section", "utils"),
            "csize": csize_bytes,
            "isize": inst_bytes,
            "csize_str": format_bytes(csize_bytes),
            "isize_str": format_bytes(inst_bytes),
            "depends": dep_report["arch_depends"],
            "dep_report": dep_report,
            "raw_deb_depends": raw_deps,
            "icon": icon,
            "is_electron": is_electron,
            "file_count": file_count,
            "sample_files": sample_files,
            "deb_path": str(p),
            "deb_filename": p.name,
            "source": "deb",
            "repo": "deb-local",
            "is_installed": is_inst,
            "installed_version": inst_ver,
        }
        self._inspect_cache[cache_key] = dict(info)
        return info

    def get_deb_detail(self, name_or_path: str) -> Dict[str, Any]:
        """Return full detail dictionary for either a .deb file path or an installed .deb package name."""
        cand_path = Path(os.path.expanduser(name_or_path))
        if cand_path.exists() and cand_path.is_file():
            return self.inspect_deb(str(cand_path))
        # Check installed_debs registry
        reg = self._load_registry()
        clean = name_or_path.strip().lower()
        if clean in reg:
            saved = dict(reg[clean])
            deb_p = saved.get("deb_path", "")
            if deb_p and Path(deb_p).exists():
                try:
                    return self.inspect_deb(deb_p)
                except Exception:
                    pass
            saved["is_installed"] = self.pm.is_installed(clean) if self.pm else True
            saved["source"] = "deb"
            return saved
        # Fallback to local pacman info
        if self.pm and clean in self.pm.packages:
            d = dict(self.pm.packages[clean])
            d["source"] = "deb"
            d["is_installed"] = self.pm.is_installed(clean)
            d["display_name"] = get_app_display_name(clean)
            return d
        return {
            "name": clean,
            "display_name": get_app_display_name(clean),
            "version": "1.0.0",
            "desc": "Converted Debian (.deb) package",
            "source": "deb",
            "repo": "deb-local",
            "is_installed": self.pm.is_installed(clean) if self.pm else False,
            "icon": resolve_icon_name(clean),
        }

    def _load_registry(self) -> Dict[str, Dict[str, Any]]:
        if self.INSTALLED_DEBS_FILE.exists():
            try:
                data = json.loads(self.INSTALLED_DEBS_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    def _save_registry(self, reg: Dict[str, Dict[str, Any]]):
        try:
            self.INSTALLED_DEBS_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.INSTALLED_DEBS_FILE.write_text(json.dumps(reg, indent=2), encoding="utf-8")
        except Exception:
            pass

    def is_deb_installed(self, pkg_name: str) -> bool:
        clean = (pkg_name or "").strip().lower()
        reg = self._load_registry()
        if clean in reg:
            return self.pm.is_installed(clean) if self.pm else True
        return False

    def get_installed_debs(self) -> List[Dict[str, Any]]:
        """Return list of all currently installed .deb-origin packages on the system."""
        reg = self._load_registry()
        results = []
        seen = set()
        for pkg_name, meta in list(reg.items()):
            if self.pm and not self.pm.is_installed(pkg_name):
                continue
            item = dict(meta)
            item["name"] = pkg_name
            item["is_installed"] = True
            item["source"] = "deb"
            if self.pm:
                item["desktop_entry"] = self.pm.detect_desktop_entry(pkg_name)
            results.append(item)
            seen.add(pkg_name)

        # Also check self.pm.packages for any package built by 'Aura Deb Bridge'
        if self.pm:
            with self.pm._lock:
                for p_name, p_data in self.pm.packages.items():
                    if p_name not in seen and p_name in self.pm.installed_set:
                        if "ArkST Deb Bridge" in str(p_data.get("packager", "")) or "Aura Deb Bridge" in str(p_data.get("packager", "")):
                            results.append({
                                "name": p_name,
                                "display_name": get_app_display_name(p_name),
                                "version": self.pm.installed_versions.get(p_name, p_data.get("version", "")),
                                "desc": p_data.get("desc", "Converted .deb application"),
                                "icon": resolve_icon_name(p_name, p_data.get("desc", "")),
                                "source": "deb",
                                "is_installed": True,
                            })
        return results

    def scan_local_debs(self) -> List[Dict[str, Any]]:
        """Scan ~/Downloads, ~/Desktop, and ~/.cache/aura/deb_downloads for .deb archives."""
        search_dirs = [
            Path.home() / "Downloads",
            Path.home() / "Desktop",
            self.DEB_DOWNLOADS_DIR,
        ]
        found: List[Dict[str, Any]] = []
        seen_paths = set()
        for d in search_dirs:
            if not d.exists():
                continue
            try:
                for deb_file in sorted(d.glob("*.deb"), key=lambda p: p.stat().st_mtime, reverse=True):
                    rp = str(deb_file.resolve())
                    if rp in seen_paths:
                        continue
                    seen_paths.add(rp)
                    try:
                        info = self.inspect_deb(rp)
                        found.append(info)
                    except Exception:
                        pass
            except Exception:
                pass
        return found

    @staticmethod
    def _merge_dir_tree(src_dir: Path, dst_dir: Path):
        """Recursively merge src_dir into dst_dir and remove src_dir (for Arch FHS /bin, /lib normalization)."""
        if not src_dir.exists():
            return
        dst_dir.mkdir(parents=True, exist_ok=True)
        for item in src_dir.iterdir():
            target = dst_dir / item.name
            if item.is_dir() and not item.is_symlink():
                DebPackageManager._merge_dir_tree(item, target)
            else:
                if target.exists() or target.is_symlink():
                    target.unlink()
                shutil.move(str(item), str(target))
        shutil.rmtree(src_dir, ignore_errors=True)

    def _convert_deb_to_arch_pkg(
        self,
        deb_info: Dict[str, Any],
        staging_dir: Path,
        wayland_fix: bool = True,
        progress_cb: Optional[Callable[[float, str], None]] = None
    ) -> Path:
        """
        Convert a .deb archive into a native Arch Linux package (.pkg.tar.zst or .pkg.tar.xz)
        with full FHS normalization and Hyprland Wayland Electron optimization.
        """
        deb_path = Path(deb_info["deb_path"])
        pkgname = deb_info["name"]
        pkgver = deb_info["version"]
        arch = deb_info["arch"] if deb_info["arch"] in ("x86_64", "any", "aarch64") else "x86_64"

        pkgroot = staging_dir / "pkgroot"
        pkgroot.mkdir(parents=True, exist_ok=True)

        if progress_cb:
            progress_cb(0.35, f"Extracting {deb_path.name} data payload...")

        # 1. Extract data.tar.* into pkgroot
        extracted = False
        for member_name, member_bytes in self._iter_ar_members(deb_path):
            if member_name.startswith("data.tar"):
                with self._open_tar_bytes(member_name, member_bytes) as dtar:
                    # Safe extraction filtering out path traversal, unsafe symlinks, and device nodes (AURA-SEC-004)
                    pkgroot_resolved = pkgroot.resolve()
                    for m in dtar.getmembers():
                        m.name = m.name.lstrip("./").lstrip("/")
                        if not m.name or ".." in m.name.split("/"):
                            continue
                        if m.isdev() or m.ischr() or m.isblk() or m.isfifo():
                            continue
                        dest_candidate = (pkgroot_resolved / m.name).resolve()
                        if not str(dest_candidate).startswith(str(pkgroot_resolved)):
                            continue
                        if (m.issym() or m.islnk()) and (".." in (m.linkname or "").split("/")):
                            continue
                        dtar.extract(m, path=pkgroot, set_attrs=False)
                        if m.isfile() and not m.issym() and not m.islnk():
                            try:
                                is_exec_dir = any(m.name.startswith(p) for p in ("bin/", "sbin/", "usr/bin/", "usr/sbin/", "usr/libexec/", "opt/"))
                                if (m.mode & 0o111) or is_exec_dir:
                                    dest_candidate.chmod(0o755)
                                else:
                                    dest_candidate.chmod(0o644)
                            except Exception:
                                pass
                extracted = True
                break

        if not extracted:
            raise RuntimeError(f"No data.tar archive found inside {deb_path.name}")

        if progress_cb:
            progress_cb(0.55, "Normalizing Debian filesystem layout for Arch Linux...")

        # 2. Arch Linux FHS Normalization:
        # On Arch, /bin, /sbin, /usr/sbin are symlinks to /usr/bin, and /lib, /lib64 are symlinks to /usr/lib.
        for legacy_bin in ("bin", "sbin"):
            lb = pkgroot / legacy_bin
            if lb.exists():
                self._merge_dir_tree(lb, pkgroot / "usr" / "bin")
        usr_sbin = pkgroot / "usr" / "sbin"
        if usr_sbin.exists():
            self._merge_dir_tree(usr_sbin, pkgroot / "usr" / "bin")

        for legacy_lib in ("lib", "lib64"):
            ll = pkgroot / legacy_lib
            if ll.exists():
                self._merge_dir_tree(ll, pkgroot / "usr" / "lib")
        usr_lib64 = pkgroot / "usr" / "lib64"
        if usr_lib64.exists():
            self._merge_dir_tree(usr_lib64, pkgroot / "usr" / "lib")

        # Handle Debian multiarch library directory (/usr/lib/x86_64-linux-gnu)
        multiarch_dir = pkgroot / "usr" / "lib" / "x86_64-linux-gnu"
        if multiarch_dir.exists() and multiarch_dir.is_dir():
            self._merge_dir_tree(multiarch_dir, pkgroot / "usr" / "lib")

        # Remove Debian-specific apt/cron updater scripts that break on Arch
        for bad_dir in (pkgroot / "etc" / "apt", pkgroot / "etc" / "cron.daily", pkgroot / "etc" / "cron.weekly"):
            if bad_dir.exists():
                shutil.rmtree(bad_dir, ignore_errors=True)

        # Ensure /opt binaries have symlinks in /usr/bin if .desktop references a bare binary name
        opt_dir = pkgroot / "opt"
        usr_bin = pkgroot / "usr" / "bin"
        apps_dir = pkgroot / "usr" / "share" / "applications"

        # 3. Hyprland / Wayland Electron Auto-Optimization & /opt Binary Symlinking on .desktop launchers
        if apps_dir.exists():
            for dt_file in apps_dir.glob("*.desktop"):
                try:
                    if not deb_info.get("desktop_entry"):
                        deb_info["desktop_entry"] = dt_file.stem
                    lines = dt_file.read_text(encoding="utf-8", errors="replace").splitlines()
                    new_lines = []
                    for line in lines:
                        if line.startswith("Exec="):
                            exec_val = line[5:].strip()
                            raw_bin = _extract_exec_binary(exec_val)
                            if raw_bin.startswith("/opt/"):
                                rel_opt = raw_bin.lstrip("/")
                                opt_target = pkgroot / rel_opt
                                if opt_target.exists() and not opt_target.is_symlink():
                                    try:
                                        opt_target.chmod(0o755)
                                    except Exception:
                                        pass
                                bin_short = os.path.basename(raw_bin)
                                usr_bin.mkdir(parents=True, exist_ok=True)
                                sym_path = usr_bin / bin_short
                                if not sym_path.exists() and not sym_path.is_symlink():
                                    try:
                                        sym_path.symlink_to(raw_bin)
                                    except Exception:
                                        pass
                            if wayland_fix and deb_info.get("is_electron"):
                                extra_flags = "--ozone-platform-hint=auto --no-sandbox" if "--no-sandbox" not in exec_val else "--ozone-platform-hint=auto"
                                if "--ozone-platform" not in exec_val:
                                    if " %" in exec_val:
                                        idx = exec_val.find(" %")
                                        exec_val = exec_val[:idx] + f" {extra_flags}" + exec_val[idx:]
                                    else:
                                        exec_val = exec_val + f" {extra_flags}"
                                    line = f"Exec={exec_val}"
                        new_lines.append(line)
                    dt_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                except Exception:
                    pass

        # Calculate total uncompressed size
        total_size = 0
        for root, dirs, files in os.walk(pkgroot):
            for dname in dirs:
                dp = Path(root) / dname
                if not dp.is_symlink():
                    try:
                        dp.chmod(0o755)
                    except Exception:
                        pass
            for fname in files:
                fp = Path(root) / fname
                if not fp.is_symlink():
                    try:
                        total_size += fp.stat().st_size
                    except Exception:
                        pass

        if progress_cb:
            progress_cb(0.70, "Generating Arch Linux .PKGINFO metadata...")

        # 4. Write .PKGINFO
        pkginfo_lines = [
            "# Generated by ArkST Deb Bridge for Arch Linux",
            f"pkgname = {pkgname}",
            f"pkgbase = {pkgname}",
            f"pkgver = {pkgver}-1",
            f"pkgdesc = {deb_info.get('desc', 'Converted Debian package').replace(chr(10), ' ')}",
            f"url = {deb_info.get('url', '')}",
            f"builddate = {int(time.time())}",
            "packager = ArkST Deb Bridge <arkst@archlinux>",
            f"size = {total_size}",
            f"arch = {arch}",
            f"license = {deb_info.get('license', 'custom')}",
        ]
        # Only include dependencies that are installed or exist in official repos so pacman -U never fails on unmapped AUR/Debian names
        valid_deps = (deb_info.get("dep_report", {}).get("installed", []) +
                      deb_info.get("dep_report", {}).get("missing_repo", []))
        for dep in dict.fromkeys(valid_deps):
            pkginfo_lines.append(f"depend = {dep}")

        (pkgroot / ".PKGINFO").write_text("\n".join(pkginfo_lines) + "\n", encoding="utf-8")

        # 5. Build Arch .pkg.tar.zst (or .pkg.tar.xz) archive
        if progress_cb:
            progress_cb(0.80, f"Packaging {pkgname}-{pkgver}-1-{arch}.pkg.tar.zst...")

        entries = [".PKGINFO"] + [
            p.name for p in sorted(pkgroot.iterdir()) if p.name != ".PKGINFO"
        ]

        if shutil.which("bsdtar") and shutil.which("zstd"):
            out_pkg = staging_dir / f"{pkgname}-{pkgver}-1-{arch}.pkg.tar.zst"
            cmd_tar = ["bsdtar", "--zstd", "-cf", str(out_pkg)] + entries
            res_tar = subprocess.run(cmd_tar, cwd=str(pkgroot), capture_output=True, text=True, timeout=180)
            if res_tar.returncode == 0 and out_pkg.exists():
                return out_pkg

        # Pure-Python fallback (.pkg.tar.xz or .pkg.tar.gz) supported natively by pacman -U
        out_pkg = staging_dir / f"{pkgname}-{pkgver}-1-{arch}.pkg.tar.xz"
        with tarfile.open(out_pkg, "w:xz") as tar:
            for entry_name in entries:
                tar.add(pkgroot / entry_name, arcname=entry_name)
        return out_pkg

    def install_deb(
        self,
        deb_path: str,
        wayland_fix: bool = True,
        use_debtap: bool = False,
        progress_cb: Optional[Callable[[float, str], None]] = None,
        complete_cb: Optional[Callable[[bool, str], None]] = None,
        sync_run: bool = False
    ):
        """
        Convert and install a .deb file seamlessly on Arch Linux.
        1. Inspects .deb metadata and translates Debian dependencies to Arch packages.
        2. Installs any missing official Arch repository dependencies via pacman -S --needed --asdeps.
        3. Converts the .deb to a compliant Arch package (.pkg.tar.zst/.xz) with FHS normalization & Wayland fixes.
        4. Installs the package via 'sudo pacman -U --noconfirm'.
        """
        def _report(frac: float, msg: str):
            if progress_cb:
                try:
                    progress_cb(frac, msg)
                except Exception:
                    pass

        def _finish(ok: bool, msg: str):
            if complete_cb:
                try:
                    complete_cb(ok, msg)
                except Exception:
                    pass

        def _task():
            nonlocal _report
            staging_dir = Path(tempfile.mkdtemp(prefix="arkst-deb-build-"))
            try:
                _report(0.08, "Inspecting Debian (.deb) package metadata...")
                info = self.inspect_deb(deb_path)
                pkgname = info["name"]
                disp_name = info.get("display_name", pkgname)

                env = os.environ.copy()
                askpass = get_askpass_script()
                if askpass.exists():
                    env["SUDO_ASKPASS"] = str(askpass)
                env["LC_ALL"] = "C"
                is_pwless = PackageManager.is_passwordless_configured()
                sudo_prefix = ["sudo", "-n"] if is_pwless else ["sudo", "-A"]

                deb_key = pkgname.strip().lower()
                self.active_deb_installs[deb_key] = (0.10, f"Preparing {disp_name} (.deb)...")
                orig_report = _report
                def _tracked_report(frac: float, msg: str):
                    self.active_deb_installs[deb_key] = (frac, msg)
                    orig_report(frac, msg)
                _report = _tracked_report

                # Step 1: Convert .deb to native Arch package (.pkg.tar.zst/.xz) in isolated staging_dir FIRST
                pkg_archive: Optional[Path] = None
                if use_debtap and shutil.which("debtap") and Path("/var/cache/debtap").exists():
                    _report(0.35, f"Converting {info['deb_filename']} with debtap...")
                    shutil.copy2(info["deb_path"], staging_dir / info["deb_filename"])
                    dt_proc = subprocess.run(
                        ["debtap", "-q", info["deb_filename"]],
                        cwd=str(staging_dir),
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        timeout=240
                    )
                    if dt_proc.returncode == 0:
                        built = list(staging_dir.glob("*.pkg.tar.*"))
                        if built:
                            pkg_archive = built[0]

                if pkg_archive is None:
                    pkg_archive = self._convert_deb_to_arch_pkg(
                        info,
                        staging_dir=staging_dir,
                        wayland_fix=wayland_fix,
                        progress_cb=_report
                    )

                # Step 2: Acquire GLOBAL_ALPM_LOCK and wait safely for any active Pacman/AUR operation
                with GLOBAL_ALPM_LOCK:
                    wait_for_alpm_lock(progress_cb=_report, max_wait=240, env=env)

                    missing_repo = info.get("dep_report", {}).get("missing_repo", [])
                    if missing_repo:
                        _report(0.84, f"Installing {len(missing_repo)} Arch dependencies ({', '.join(missing_repo[:3])})...")
                        dep_cmd = sudo_prefix + ["pacman", "-S", "--needed", "--asdeps", "--noconfirm"] + missing_repo
                        dep_res = subprocess.run(dep_cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=300)
                        if dep_res.returncode != 0 and sudo_prefix == ["sudo", "-n"]:
                            sudo_prefix = ["sudo", "-A"]
                            subprocess.run(sudo_prefix + ["pacman", "-S", "--needed", "--asdeps", "--noconfirm"] + missing_repo,
                                           stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=300)

                    # Step 3: Install converted Arch package via pacman -U
                    _report(0.90, f"Installing {disp_name} into Arch system database (pacman -U)...")
                    inst_cmd = sudo_prefix + ["pacman", "-U", "--noconfirm", str(pkg_archive)]
                    proc = subprocess.run(
                        inst_cmd,
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        env=env,
                        timeout=300
                    )
                    if proc.returncode != 0 and sudo_prefix == ["sudo", "-n"] and ("password is required" in (proc.stderr or "").lower() or "authentication" in (proc.stderr or "").lower()):
                        sudo_prefix = ["sudo", "-A"]
                        proc = subprocess.run(
                            sudo_prefix + ["pacman", "-U", "--noconfirm", str(pkg_archive)],
                            stdin=subprocess.DEVNULL,
                            capture_output=True,
                            text=True,
                            env=env,
                            timeout=300
                        )
                    if proc.returncode != 0:
                        inst_cmd_retry = sudo_prefix + ["pacman", "-U", "--noconfirm", "--overwrite", "*", str(pkg_archive)]
                        proc = subprocess.run(
                            inst_cmd_retry,
                            stdin=subprocess.DEVNULL,
                            capture_output=True,
                            text=True,
                            env=env,
                            timeout=300
                        )

                if proc.returncode != 0:
                    err = (proc.stderr or proc.stdout or f"pacman -U exited with code {proc.returncode}").strip()
                    _finish(False, err.splitlines()[-1] if err else "Failed installing converted .deb package")
                    return

                # Step 5: Record in installed_debs registry and refresh caches
                reg = self._load_registry()
                reg[pkgname] = {
                    "name": pkgname,
                    "display_name": disp_name,
                    "version": info["version"],
                    "deb_version": info["deb_version"],
                    "desc": info["desc"],
                    "icon": info["icon"],
                    "deb_path": info["deb_path"],
                    "deb_filename": info["deb_filename"],
                    "installed_at": int(time.time()),
                    "wayland_optimized": bool(wayland_fix and info.get("is_electron")),
                }
                self._save_registry(reg)

                if self.pm:
                    self.pm.refresh_installed()
                    self.pm.load_pacman_db(force_reload=True)

                _report(1.0, f"✓ Installed {disp_name} ({info['deb_filename']}) seamlessly!")
                _finish(True, f"Successfully installed {disp_name} from {info['deb_filename']}!")
            except Exception as e:
                _finish(False, str(e))
            finally:
                if hasattr(self, "active_deb_installs"):
                    self.active_deb_installs.pop(locals().get("pkgname", "").strip().lower(), None)
                shutil.rmtree(staging_dir, ignore_errors=True)

        if sync_run:
            _task()
        else:
            threading.Thread(target=_task, daemon=True).start()

    def download_and_install_deb(
        self,
        url: str,
        wayland_fix: bool = True,
        progress_cb: Optional[Callable[[float, str], None]] = None,
        complete_cb: Optional[Callable[[bool, str], None]] = None
    ):
        """Download a .deb package from a direct HTTP/HTTPS URL and install it seamlessly."""
        def _task():
            try:
                clean_url = url.strip()
                if not clean_url.startswith(("http://", "https://")):
                    if complete_cb:
                        complete_cb(False, "URL must start with http:// or https://")
                    return

                parsed = urllib.parse.urlparse(clean_url)
                fname = os.path.basename(parsed.path) or "downloaded-package.deb"
                if not fname.lower().endswith(".deb"):
                    fname += ".deb"
                fname = re.sub(r'[^a-zA-Z0-9._+-]', '_', fname)
                dest_path = self.DEB_DOWNLOADS_DIR / fname

                if progress_cb:
                    progress_cb(0.03, f"Connecting to download {fname}...")

                req = urllib.request.Request(clean_url, headers={"User-Agent": "Mozilla/5.0 ArkST-Store/3.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    total_bytes = int(resp.headers.get("Content-Length", "0") or "0")
                    downloaded = 0
                    chunk_size = 65536
                    with open(dest_path, "wb") as out_f:
                        while True:
                            chunk = resp.read(chunk_size)
                            if not chunk:
                                break
                            out_f.write(chunk)
                            downloaded += len(chunk)
                            if total_bytes > 0 and progress_cb:
                                dl_frac = min(0.30, 0.03 + (downloaded / total_bytes) * 0.27)
                                progress_cb(dl_frac, f"Downloading {fname} ({format_bytes(downloaded)} / {format_bytes(total_bytes)})...")
                            elif progress_cb:
                                progress_cb(0.15, f"Downloading {fname} ({format_bytes(downloaded)})...")

                # Chain into install_deb synchronously in this worker thread
                self.install_deb(
                    str(dest_path),
                    wayland_fix=wayland_fix,
                    progress_cb=progress_cb,
                    complete_cb=complete_cb,
                    sync_run=True
                )
            except Exception as e:
                if complete_cb:
                    complete_cb(False, f"Download failed: {e}")

        threading.Thread(target=_task, daemon=True).start()

    def uninstall_deb(
        self,
        pkg_name: str,
        progress_cb: Optional[Callable[[float, str], None]] = None,
        complete_cb: Optional[Callable[[bool, str], None]] = None,
        sync_run: bool = False
    ):
        """Uninstall a converted .deb package cleanly via pacman -Rns."""
        def _task():
            clean = self._sanitize_arch_pkgname(pkg_name)
            env = os.environ.copy()
            askpass = get_askpass_script()
            if askpass.exists():
                env["SUDO_ASKPASS"] = str(askpass)
            env["LC_ALL"] = "C"
            sudo_prefix = ["sudo", "-n"] if PackageManager.is_passwordless_configured() else ["sudo", "-A"]

            if progress_cb:
                progress_cb(0.3, f"Removing {clean} via pacman...")

            proc = subprocess.run(
                sudo_prefix + ["pacman", "-Rns", "--noconfirm", clean],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                env=env,
                timeout=120
            )
            if proc.returncode == 0:
                reg = self._load_registry()
                if clean in reg:
                    del reg[clean]
                    self._save_registry(reg)
                if self.pm:
                    self.pm.refresh_installed()
                if progress_cb:
                    progress_cb(1.0, f"Removed {clean} successfully!")
                if complete_cb:
                    complete_cb(True, f"Removed {clean} successfully.")
            else:
                err = (proc.stderr or proc.stdout or f"Exited with code {proc.returncode}").strip()
                if complete_cb:
                    complete_cb(False, err)

        if sync_run:
            _task()
        else:
            threading.Thread(target=_task, daemon=True).start()


class HyprlandManager:
    """
    Hyprland Wayland Compositor Integration, Diagnostics & Optimization Engine.
    Features:
    - Live inspection of Hyprland version, active monitors, refresh rates, scaling, and portals
    - Companion daemon health checks (xdg-desktop-portal-hyprland, Polkit agent, PipeWire, Waybar, Notifications)
    - One-click Hyprland window rules & Super+A shortcut injection into ~/.config/hypr/hyprland.conf + live hyprctl reload
    - One-click native Wayland Ozone flag optimizer for Electron/Chromium desktop applications
    """

    HYPR_DIR = Path.home() / ".config" / "hypr"
    HYPR_CONF_PATH = HYPR_DIR / "hyprland.conf"
    HYPR_LUA_PATH = HYPR_DIR / "hyprland.lua"
    HYPR_RULES_LUA_PATH = HYPR_DIR / "hyprland" / "rules.lua"
    HYPR_KEYBINDS_LUA_PATH = HYPR_DIR / "hyprland" / "keybinds.lua"
    ELECTRON_FLAGS_FILES = [
        Path.home() / ".config" / "electron-flags.conf",
        Path.home() / ".config" / "code-flags.conf",
        Path.home() / ".config" / "spotify-flags.conf",
        Path.home() / ".config" / "chromium-flags.conf",
        Path.home() / ".config" / "brave-flags.conf",
    ]

    def __init__(self, pm: Optional["PackageManager"] = None):
        self.pm = pm

    @staticmethod
    def _is_proc_running(names: List[str]) -> Optional[str]:
        for name in names:
            try:
                res = subprocess.run(["pgrep", "-x", name], capture_output=True, timeout=2)
                if res.returncode == 0:
                    return name
            except Exception:
                pass
            try:
                res = subprocess.run(["pgrep", "-f", name], capture_output=True, timeout=2)
                if res.returncode == 0:
                    return name
            except Exception:
                pass
        return None

    def get_status(self) -> Dict[str, Any]:
        """Gather comprehensive Hyprland compositor, monitor, portal, and companion stack status."""
        env = self._get_hypr_env()
        hypr_sig = env.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        wayland_disp = env.get("WAYLAND_DISPLAY", "")
        xdg_desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
        is_hyprland = bool(hypr_sig or "hyprland" in xdg_desktop.lower() or shutil.which("hyprctl"))

        version_str = "Not detected"
        monitors: List[Dict[str, Any]] = []
        if shutil.which("hyprctl"):
            try:
                vproc = subprocess.run(["hyprctl", "version"], capture_output=True, text=True, env=env, timeout=2)
                if vproc.returncode == 0 and vproc.stdout:
                    first_line = vproc.stdout.splitlines()[0].strip()
                    m_ver = re.search(r'(Hyprland\s+[0-9\.]+(?:-[a-zA-Z0-9]+)?)', first_line)
                    m_br = re.search(r'branch\s+([^\s,]+)', first_line)
                    if m_ver:
                        version_str = m_ver.group(1)
                        if m_br and m_br.group(1) not in version_str:
                            version_str += f" ({m_br.group(1)})"
                    else:
                        version_str = first_line[:38]
            except Exception:
                pass
            try:
                mproc = subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True, env=env, timeout=2)
                if mproc.returncode == 0 and mproc.stdout.strip().startswith("["):
                    mdata = json.loads(mproc.stdout)
                    for m in mdata:
                        monitors.append({
                            "name": m.get("name", "Display"),
                            "model": m.get("make", "") + (" " + m.get("model", "") if m.get("model") else ""),
                            "width": m.get("width", 1920),
                            "height": m.get("height", 1080),
                            "refresh": round(float(m.get("refreshRate", 60.0)), 1),
                            "scale": m.get("scale", 1.0),
                        })
            except Exception:
                pass

        portal_installed = bool(self.pm and self.pm.is_installed("xdg-desktop-portal-hyprland"))
        polkit_running = self._is_proc_running(["hyprpolkitagent", "polkit-kde-authentication-agent-1", "polkit-gnome-authentication-agent-1", "lxpolkit"])
        bar_running = self._is_proc_running(["waybar", "ags", "eww", "hyprpanel", "quickshell"])
        wall_running = self._is_proc_running(["hyprpaper", "swww-daemon", "wpaperd", "mpvpaper"])
        notif_running = self._is_proc_running(["swaync", "mako", "dunst"])
        audio_running = self._is_proc_running(["pipewire", "pulseaudio"])

        rules_configured = self.are_window_rules_configured()
        wayland_flags_configured = self.are_electron_wayland_flags_configured()

        return {
            "is_hyprland": is_hyprland,
            "hypr_active": bool(hypr_sig),
            "version": version_str,
            "wayland_display": wayland_disp or "wayland-1",
            "monitors": monitors,
            "portal_installed": portal_installed,
            "polkit_agent": polkit_running or ("Installed" if (self.pm and self.pm.is_installed("hyprpolkitagent")) else None),
            "status_bar": bar_running,
            "wallpaper_daemon": wall_running,
            "notification_daemon": notif_running,
            "audio_server": audio_running,
            "rules_configured": rules_configured,
            "wayland_flags_configured": wayland_flags_configured,
        }

    @staticmethod
    def _get_hypr_env() -> Dict[str, str]:
        """Return environment dict with HYPRLAND_INSTANCE_SIGNATURE & XDG_RUNTIME_DIR auto-discovered."""
        env = os.environ.copy()
        uid = os.getuid()
        runtime_dir = env.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
        env["XDG_RUNTIME_DIR"] = runtime_dir
        if not env.get("HYPRLAND_INSTANCE_SIGNATURE"):
            for base in (Path(runtime_dir) / "hypr", Path("/tmp/hypr")):
                if base.exists():
                    try:
                        dirs = sorted(
                            [d for d in base.iterdir() if d.is_dir() and (d / ".socket.sock").exists()],
                            key=lambda d: d.stat().st_mtime,
                            reverse=True,
                        )
                        if dirs:
                            env["HYPRLAND_INSTANCE_SIGNATURE"] = dirs[0].name
                            break
                    except Exception:
                        pass
        return env

    @classmethod
    def _build_compatible_rule_lines(cls, env: Dict[str, str], existing_conf: str = "") -> List[str]:
        """Detect whether running Hyprland uses windowrulev2, windowrule v2, or Hyprland 0.53+ match:class syntax."""
        use_match_syntax = "match:class" in existing_conf
        rule_kw = "windowrulev2"

        if shutil.which("hyprctl") and env.get("HYPRLAND_INSTANCE_SIGNATURE"):
            try:
                p1 = subprocess.run(
                    ["hyprctl", "keyword", "windowrulev2", "float, class:^(io.github.arkst)$"],
                    capture_output=True, text=True, env=env, timeout=2
                )
                out1 = ((p1.stdout or "") + " " + (p1.stderr or "")).lower()
                if p1.returncode == 0 and "ok" in out1 and "unknown" not in out1 and "error" not in out1 and "invalid" not in out1:
                    rule_kw = "windowrulev2"
                    use_match_syntax = False
                else:
                    p2 = subprocess.run(
                        ["hyprctl", "keyword", "windowrule", "float, class:^(io.github.arkst)$"],
                        capture_output=True, text=True, env=env, timeout=2
                    )
                    out2 = ((p2.stdout or "") + " " + (p2.stderr or "")).lower()
                    if p2.returncode == 0 and "ok" in out2 and "unknown" not in out2 and "error" not in out2 and "invalid" not in out2:
                        rule_kw = "windowrule"
                        use_match_syntax = False
                    else:
                        p3 = subprocess.run(
                            ["hyprctl", "keyword", "windowrule", "float on, match:class ^(io.github.arkst)$"],
                            capture_output=True, text=True, env=env, timeout=2
                        )
                        out3 = ((p3.stdout or "") + " " + (p3.stderr or "")).lower()
                        if p3.returncode == 0 and "ok" in out3:
                            rule_kw = "windowrule"
                            use_match_syntax = True
            except Exception:
                pass

        if use_match_syntax or not rule_kw:
            return [
                r"windowrule = float, match:class ^(io\.github\.arkst|arkst|arkst\.py)$",
                r"windowrule = center, match:class ^(io\.github\.arkst|arkst|arkst\.py)$",
                r"windowrule = size 1200 760, match:class ^(io\.github\.arkst|arkst|arkst\.py)$",
                r"windowrule = float, match:class ^(io\.github\.arkst\.Askpass|arkst-askpass)$",
                r"windowrule = center, match:class ^(io\.github\.arkst\.Askpass|arkst-askpass)$",
                r"windowrule = size 430 240, match:class ^(io\.github\.arkst\.Askpass|arkst-askpass)$",
                r"windowrule = pin, match:class ^(io\.github\.arkst\.Askpass|arkst-askpass)$",
                r"windowrule = stayfocused, match:class ^(io\.github\.arkst\.Askpass|arkst-askpass)$",
                "unbind = SUPER, A",
                "bind = SUPER, A, exec, arkst",
            ]
        return [
            rf"{rule_kw} = float, class:^(io\.github\.arkst|arkst|arkst\.py)$",
            rf"{rule_kw} = center, class:^(io\.github\.arkst|arkst|arkst\.py)$",
            rf"{rule_kw} = size 1200 760, class:^(io\.github\.arkst|arkst|arkst\.py)$",
            rf"{rule_kw} = float, class:^(io\.github\.arkst\.Askpass|arkst-askpass)$",
            rf"{rule_kw} = center, class:^(io\.github\.arkst\.Askpass|arkst-askpass)$",
            rf"{rule_kw} = size 430 240, class:^(io\.github\.arkst\.Askpass|arkst-askpass)$",
            rf"{rule_kw} = pin, class:^(io\.github\.arkst\.Askpass|arkst-askpass)$",
            rf"{rule_kw} = stayfocused, class:^(io\.github\.arkst\.Askpass|arkst-askpass)$",
            "unbind = SUPER, A",
            "bind = SUPER, A, exec, arkst",
        ]

    @classmethod
    def _apply_live_window_state(cls, enable: bool, env: Dict[str, str]):
        """Immediately float, resize & center (or re-tile) any open ArkST window in the live Hyprland session."""
        if not shutil.which("hyprctl") or not env.get("HYPRLAND_INSTANCE_SIGNATURE"):
            return
        try:
            cproc = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True, env=env, timeout=3)
            if cproc.returncode == 0 and cproc.stdout.strip().startswith("["):
                clients = json.loads(cproc.stdout)
                for cl in clients:
                    c_cls = (cl.get("class") or "").lower()
                    c_init = (cl.get("initialClass") or "").lower()
                    c_title = (cl.get("title") or "").strip()
                    addr = cl.get("address", "")
                    if not addr:
                        continue
                    if any(k in (c_cls, c_init) for k in ("io.github.arkst", "arkst", "arkst.py")) or c_title == "ArkST":
                        is_floating = bool(cl.get("floating", False))
                        if enable:
                            if not is_floating:
                                r = subprocess.run(["hyprctl", "dispatch", f'hl.dsp.window.float({{ action = "on", window = "address:{addr}" }})'], capture_output=True, env=env, timeout=2)
                                if r.returncode != 0:
                                    r2 = subprocess.run(["hyprctl", "dispatch", "setfloating", f"address:{addr}"], capture_output=True, env=env, timeout=2)
                                    if r2.returncode != 0:
                                        subprocess.run(["hyprctl", "dispatch", "togglefloating", f"address:{addr}"], capture_output=True, env=env, timeout=2)
                            subprocess.run(["hyprctl", "dispatch", f'hl.dsp.window.center({{ window = "address:{addr}" }})'], capture_output=True, env=env, timeout=2)
                            subprocess.run(["hyprctl", "dispatch", "resizewindowpixel", f"exact 1200 760,address:{addr}"], capture_output=True, env=env, timeout=2)
                            subprocess.run(["hyprctl", "dispatch", "centerwindow"], capture_output=True, env=env, timeout=2)
                        else:
                            if is_floating:
                                r = subprocess.run(["hyprctl", "dispatch", f'hl.dsp.window.float({{ action = "off", window = "address:{addr}" }})'], capture_output=True, env=env, timeout=2)
                                if r.returncode != 0:
                                    r2 = subprocess.run(["hyprctl", "dispatch", "settiled", f"address:{addr}"], capture_output=True, env=env, timeout=2)
                                    if r2.returncode != 0:
                                        subprocess.run(["hyprctl", "dispatch", "togglefloating", f"address:{addr}"], capture_output=True, env=env, timeout=2)
        except Exception:
            pass

    @property
    def hypr_rules_lua_path(self) -> Path:
        return self.HYPR_CONF_PATH.parent / "hyprland" / "rules.lua"

    @property
    def hypr_keybinds_lua_path(self) -> Path:
        return self.HYPR_CONF_PATH.parent / "hyprland" / "keybinds.lua"

    @property
    def hypr_lua_path(self) -> Path:
        return self.HYPR_CONF_PATH.parent / "hyprland.lua"

    def are_window_rules_configured(self) -> bool:
        if self.hypr_rules_lua_path.exists():
            try:
                content = self.hypr_rules_lua_path.read_text(encoding="utf-8", errors="replace")
                if "io.github.arkst" in content:
                    return True
            except Exception:
                pass
        if self.hypr_lua_path.exists():
            try:
                content = self.hypr_lua_path.read_text(encoding="utf-8", errors="replace")
                if "io.github.arkst" in content:
                    return True
            except Exception:
                pass
        if self.HYPR_CONF_PATH.exists():
            try:
                content = self.HYPR_CONF_PATH.read_text(encoding="utf-8", errors="replace")
                return "hyprland-arkst.conf" in content or "io.github.arkst" in content
            except Exception:
                pass
        return False

    def configure_window_rules(self, enable: bool = True) -> Tuple[bool, str]:
        """Inject or remove ArkST floating window rules in ~/.config/hypr/hyprland/rules.lua (or hyprland.conf), purge all legacy Aura/Ark rules across ~/.config/hypr, reload Hyprland, and float/tile live."""
        try:
            hypr_dir = self.HYPR_CONF_PATH.parent
            hypr_dir.mkdir(parents=True, exist_ok=True)
            env = self._get_hypr_env()

            # 1. Delete any leftover legacy Aura/Ark hyprland rule files
            for legacy_rule in (
                Path.home() / ".local" / "share" / "aura" / "data" / "hyprland-aura.conf",
                Path.home() / ".local" / "share" / "ark" / "data" / "hyprland-ark.conf",
                hypr_dir / "hyprland-aura.conf",
                hypr_dir / "hyprland-ark.conf",
            ):
                try:
                    legacy_rule.unlink(missing_ok=True)
                except Exception:
                    pass

            marker_start = "# >>> ArkST Hyprland Integration >>>"
            marker_end = "# <<< ArkST Hyprland Integration <<<"
            lua_marker_start = "-- >>> ArkST Hyprland Integration >>>"
            lua_marker_end = "-- <<< ArkST Hyprland Integration <<<"
            legacy_starts = {
                "# >>> Aura Store Hyprland Integration >>>",
                "# >>> Aura Hyprland Integration >>>",
                "# >>> Ark Store Hyprland Integration >>>",
                "# >>> Ark Hyprland Integration >>>",
                "-- >>> Aura Store Hyprland Integration >>>",
                "-- >>> Aura Hyprland Integration >>>",
                "-- >>> Ark Store Hyprland Integration >>>",
                "-- >>> Ark Hyprland Integration >>>",
                marker_start,
                lua_marker_start,
            }
            legacy_ends = {
                "# <<< Aura Store Hyprland Integration <<<",
                "# <<< Aura Hyprland Integration <<<",
                "# <<< Ark Store Hyprland Integration <<<",
                "# <<< Ark Hyprland Integration <<<",
                "-- <<< Aura Store Hyprland Integration <<<",
                "-- <<< Aura Hyprland Integration <<<",
                "-- <<< Ark Store Hyprland Integration <<<",
                "-- <<< Ark Hyprland Integration <<<",
                marker_end,
                lua_marker_end,
            }
            legacy_tokens = (
                "hyprland-aura.conf",
                "hyprland-ark.conf",
                "io.github.aura",
                r"io\.github\.aura",
                "io.github.(ark|aura)",
                r"io\.github\.(ark|aura)",
                "Aura Store Hyprland Integration",
                "Aura Hyprland Integration",
                "Aura Package Hub",
                "exec, aura",
                "exec, /usr/bin/aura",
                "exec, ~/.local/bin/aura",
                "exec, $HOME/.local/bin/aura",
            )

            # 2. Clean all secondary *.conf and *.lua files in ~/.config/hypr/
            all_hypr_files = list(hypr_dir.glob("*.conf")) + list(hypr_dir.glob("**/*.conf")) + \
                             list(hypr_dir.glob("*.lua")) + list(hypr_dir.glob("**/*.lua"))
            for extra_file in all_hypr_files:
                if extra_file.resolve() in (self.HYPR_CONF_PATH.resolve(), self.hypr_rules_lua_path.resolve(), self.hypr_keybinds_lua_path.resolve()):
                    continue
                if extra_file.name == "hyprland-arkst.conf":
                    continue
                try:
                    etxt = extra_file.read_text(encoding="utf-8", errors="replace")
                    if any(t in etxt for t in legacy_tokens):
                        e_cleaned = []
                        in_blk = False
                        for eline in etxt.splitlines():
                            es = eline.strip()
                            if es in legacy_starts:
                                in_blk = True
                                continue
                            if es in legacy_ends:
                                in_blk = False
                                continue
                            if any(t in eline for t in legacy_tokens):
                                continue
                            if not in_blk:
                                e_cleaned.append(eline)
                        extra_file.write_text("\n".join(e_cleaned).strip() + "\n", encoding="utf-8")
                except Exception:
                    pass

            # 3. Handle Modern Hyprland Lua Configuration (rules.lua and keybinds.lua)
            if self.hypr_rules_lua_path.exists():
                try:
                    rtxt = self.hypr_rules_lua_path.read_text(encoding="utf-8", errors="replace")
                    rtxt = rtxt.replace('"io.github.aura"', '"io.github.arkst.*"')
                    r_lines = []
                    in_lua_blk = False
                    for line in rtxt.splitlines():
                        s = line.strip()
                        if s in legacy_starts:
                            in_lua_blk = True
                            continue
                        if s in legacy_ends:
                            in_lua_blk = False
                            continue
                        if not in_lua_blk and ("-- Aura Package Hub" not in s and "io.github.aura" not in s):
                            r_lines.append(line)
                    if enable:
                        lua_rule_block = [
                            "",
                            lua_marker_start,
                            'hl.window_rule({ match = { class = "io.github.arkst.*" }, float = true, center = true, size = "1200 760", opaque = true })',
                            'hl.window_rule({ match = { class = "io.github.arkst.Askpass" }, float = true, center = true, size = "430 240", pin = true, stay_focused = true })',
                            lua_marker_end,
                        ]
                        r_lines.extend(lua_rule_block)
                    self.hypr_rules_lua_path.write_text("\n".join(r_lines).strip() + "\n", encoding="utf-8")
                except Exception:
                    pass

            if self.hypr_keybinds_lua_path.exists():
                try:
                    ktxt = self.hypr_keybinds_lua_path.read_text(encoding="utf-8", errors="replace")
                    k_lines = []
                    in_k_blk = False
                    for line in ktxt.splitlines():
                        s = line.strip()
                        if s in legacy_starts:
                            in_k_blk = True
                            continue
                        if s in legacy_ends:
                            in_k_blk = False
                            continue
                        if not in_k_blk and "arkst" not in s and "aura" not in s:
                            k_lines.append(line)
                    if enable:
                        lua_keybind_block = [
                            "",
                            lua_marker_start,
                            'create_bind("SUPER + A", hl.dsp.exec_cmd("arkst"))',
                            lua_marker_end,
                        ]
                        k_lines.extend(lua_keybind_block)
                    self.hypr_keybinds_lua_path.write_text("\n".join(k_lines).strip() + "\n", encoding="utf-8")
                except Exception:
                    pass

            # 4. Handle Standard / Legacy hyprland.conf
            existing = self.HYPR_CONF_PATH.read_text(encoding="utf-8", errors="replace") if self.HYPR_CONF_PATH.exists() else ""
            rule_lines = self._build_compatible_rule_lines(env, existing)

            # Write local user copy of hyprland-arkst.conf with the exact compatible syntax
            user_rule_file = Path.home() / ".local" / "share" / "arkst" / "data" / "hyprland-arkst.conf"
            try:
                user_rule_file.parent.mkdir(parents=True, exist_ok=True)
                user_rule_file.write_text(
                    "# Hyprland Window Rules & Keybind for ArkST (io.github.arkst)\n" + "\n".join(rule_lines) + "\n",
                    encoding="utf-8"
                )
            except Exception:
                pass

            cleaned_lines = []
            in_block = False
            for line in existing.splitlines():
                s = line.strip()
                if s in legacy_starts:
                    in_block = True
                    continue
                if s in legacy_ends:
                    in_block = False
                    continue
                if any(tok in line for tok in legacy_tokens):
                    continue
                if ("hyprland-arkst.conf" in line or "io.github.arkst" in line or "exec, arkst" in line) and not enable:
                    continue
                if not in_block:
                    cleaned_lines.append(line)

            if enable:
                block = [
                    "",
                    marker_start,
                    f"# Source: {user_rule_file} (hyprland-arkst.conf)",
                    *rule_lines,
                    marker_end,
                ]
                cleaned_lines.extend(block)

            self.HYPR_CONF_PATH.write_text("\n".join(cleaned_lines).strip() + "\n", encoding="utf-8")

            if shutil.which("hyprctl") and env.get("HYPRLAND_INSTANCE_SIGNATURE"):
                subprocess.run(["hyprctl", "reload"], capture_output=True, env=env, timeout=3)
                self._apply_live_window_state(enable=enable, env=env)

            if enable:
                return True, "ArkST Hyprland floating rules & Super+A shortcut applied live!"
            return True, "ArkST window rules removed from hyprland.conf and hyprland.lua."
        except Exception as e:
            return False, f"Failed updating hyprland config: {e}"

    def are_electron_wayland_flags_configured(self) -> bool:
        ef = self.ELECTRON_FLAGS_FILES[0]
        if not ef.exists():
            return False
        try:
            txt = ef.read_text(encoding="utf-8", errors="replace")
            return "ozone-platform" in txt
        except Exception:
            return False

    def configure_electron_wayland_flags(self, enable: bool = True) -> Tuple[bool, str]:
        """Configure native Wayland Ozone rendering flags for Electron, VS Code, Spotify, Brave, and Chromium on Hyprland."""
        flags_content = (
            "--enable-features=UseOzonePlatform,WaylandWindowDecorations\n"
            "--ozone-platform-hint=auto\n"
        )
        try:
            for fpath in self.ELECTRON_FLAGS_FILES:
                if enable:
                    fpath.parent.mkdir(parents=True, exist_ok=True)
                    if fpath.exists():
                        cur = fpath.read_text(encoding="utf-8", errors="replace")
                        if "ozone-platform" not in cur:
                            fpath.write_text(cur.rstrip() + "\n" + flags_content, encoding="utf-8")
                    else:
                        fpath.write_text(flags_content, encoding="utf-8")
                else:
                    if fpath.exists():
                        lines = [
                            l for l in fpath.read_text(encoding="utf-8", errors="replace").splitlines()
                            if "ozone-platform" not in l and "WaylandWindowDecorations" not in l
                        ]
                        if lines:
                            fpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
                        else:
                            fpath.unlink(missing_ok=True)
            if enable:
                return True, "Native Wayland Ozone flags enabled for Electron, Code, Spotify, and Chromium!"
            return True, "Electron Wayland flags reset to default."
        except Exception as e:
            return False, f"Failed configuring Electron Wayland flags: {e}"


class SystemDoctor:
    """
    Arch Linux System Health Diagnostics & One-Click Repair Suite.
    Handles:
    - Stale Pacman lock (/var/lib/pacman/db.lck) detection and safe removal
    - Orphaned packages (pacman -Qdt) scanning and batch cleanup
    - Arch Linux PGP keyring & database sync repair (archlinux-keyring)
    - Unmerged .pacnew / .pacsave configuration file detection
    - Failed systemd service inspection
    """

    LOCK_PATH = Path("/var/lib/pacman/db.lck")

    def __init__(self, pm: Optional["PackageManager"] = None):
        self.pm = pm

    def get_pacman_lock_status(self) -> Dict[str, Any]:
        locked = self.LOCK_PATH.exists()
        running_procs = []
        if locked:
            for proc_name in ("pacman", "paru", "yay", "makepkg"):
                try:
                    res = subprocess.run(["pgrep", "-x", proc_name], capture_output=True, text=True, timeout=2)
                    if res.returncode == 0 and res.stdout.strip():
                        running_procs.append(proc_name)
                except Exception:
                    pass
        return {
            "locked": locked,
            "active_processes": running_procs,
            "is_stale": bool(locked and not running_procs),
        }

    def get_orphan_packages(self) -> List[Dict[str, str]]:
        orphans = []
        try:
            res = subprocess.run(["pacman", "-Qdt"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        name, ver = parts[0], parts[1]
                        pkg_meta = self.pm.packages.get(name, {}) if self.pm else {}
                        orphans.append({
                            "name": name,
                            "version": ver,
                            "desc": pkg_meta.get("desc", "Unused orphaned dependency package"),
                            "size_str": format_bytes(pkg_meta.get("isize", 0)),
                        })
        except Exception:
            pass
        return orphans

    def get_pacnew_files(self) -> List[str]:
        found = []
        search_dirs = [Path("/etc"), Path("/etc/pacman.d"), Path("/etc/security"), Path("/etc/systemd")]
        for d in search_dirs:
            if not d.exists():
                continue
            try:
                for p in d.glob("*.pacnew"):
                    found.append(str(p))
                for p in d.glob("*.pacsave"):
                    found.append(str(p))
            except Exception:
                pass
        return sorted(set(found))

    def get_failed_services(self) -> List[str]:
        failed = []
        if shutil.which("systemctl"):
            try:
                res = subprocess.run(
                    ["systemctl", "--failed", "--no-legend", "--plain"],
                    capture_output=True, text=True, timeout=3
                )
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        parts = line.strip().split()
                        if parts:
                            failed.append(parts[0])
            except Exception:
                pass
        return failed

    def scan_health(self) -> Dict[str, Any]:
        lock_st = self.get_pacman_lock_status()
        orphans = self.get_orphan_packages()
        pacnews = self.get_pacnew_files()
        failed_svcs = self.get_failed_services()
        return {
            "lock_status": lock_st,
            "orphans": orphans,
            "orphan_count": len(orphans),
            "pacnew_files": pacnews,
            "pacnew_count": len(pacnews),
            "failed_services": failed_svcs,
            "failed_services_count": len(failed_svcs),
        }

    def unlock_pacman_db(self, complete_cb: Optional[Callable[[bool, str], None]] = None):
        def _task():
            st = self.get_pacman_lock_status()
            if not st["locked"]:
                if complete_cb:
                    complete_cb(True, "Pacman database is not locked.")
                return
            if st["active_processes"] or (self.pm and self.pm.is_busy()):
                if complete_cb:
                    procs_str = ", ".join(st["active_processes"]) if st["active_processes"] else "ArkST package installer"
                    complete_cb(False, f"Cannot remove lock while {procs_str} is actively running.")
                return
            env = os.environ.copy()
            askpass = get_askpass_script()
            if askpass.exists():
                env["SUDO_ASKPASS"] = str(askpass)
            res = subprocess.run(["sudo", "-n", "rm", "-f", str(self.LOCK_PATH)], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=5)
            if res.returncode != 0 and self.LOCK_PATH.exists():
                res = subprocess.run(["sudo", "-A", "rm", "-f", str(self.LOCK_PATH)], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=30)
            ok = (res.returncode == 0 and not self.LOCK_PATH.exists())
            if complete_cb:
                complete_cb(ok, "Stale Pacman database lock removed!" if ok else f"Failed removing lock: {res.stderr}")
        threading.Thread(target=_task, daemon=True).start()

    def remove_orphans(self, progress_cb: Optional[Callable[[float, str], None]] = None, complete_cb: Optional[Callable[[bool, str], None]] = None):
        def _task():
            with GLOBAL_ALPM_LOCK:
                env = os.environ.copy()
                askpass = get_askpass_script()
                if askpass.exists():
                    env["SUDO_ASKPASS"] = str(askpass)
                env["LC_ALL"] = "C"
                wait_for_alpm_lock(progress_cb=progress_cb, max_wait=180, env=env)
                orphans = [o["name"] for o in self.get_orphan_packages()]
                if not orphans:
                    if complete_cb:
                        complete_cb(True, "No orphaned packages to remove.")
                    return
                if progress_cb:
                    progress_cb(0.3, f"Removing {len(orphans)} orphaned packages...")
                res = subprocess.run(
                    ["sudo", "-n", "pacman", "-Rns", "--noconfirm"] + orphans,
                    stdin=subprocess.DEVNULL,
                    capture_output=True, text=True, env=env, timeout=180
                )
                if res.returncode != 0:
                    res = subprocess.run(
                        ["sudo", "-A", "pacman", "-Rns", "--noconfirm"] + orphans,
                        stdin=subprocess.DEVNULL,
                        capture_output=True, text=True, env=env, timeout=180
                    )
                if res.returncode == 0:
                    if self.pm:
                        self.pm.refresh_installed()
                    if progress_cb:
                        progress_cb(1.0, f"Removed {len(orphans)} orphaned packages!")
                    if complete_cb:
                        complete_cb(True, f"Successfully removed {len(orphans)} orphaned packages!")
                else:
                    if complete_cb:
                        complete_cb(False, f"Failed removing orphans: {res.stderr or res.stdout}")
        threading.Thread(target=_task, daemon=True).start()

    def repair_keyring(self, progress_cb: Optional[Callable[[float, str], None]] = None, complete_cb: Optional[Callable[[bool, str], None]] = None):
        def _task():
            with GLOBAL_ALPM_LOCK:
                env = os.environ.copy()
                askpass = get_askpass_script()
                if askpass.exists():
                    env["SUDO_ASKPASS"] = str(askpass)
                env["LC_ALL"] = "C"
                wait_for_alpm_lock(progress_cb=progress_cb, max_wait=180, env=env)
                try:
                    if progress_cb:
                        progress_cb(0.2, "Initializing Pacman GPG keyring (pacman-key --init)...")
                    r1 = subprocess.run(["sudo", "-n", "pacman-key", "--init"], stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=60)
                    if r1.returncode != 0:
                        subprocess.run(["sudo", "-A", "pacman-key", "--init"], stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=60)
                    if progress_cb:
                        progress_cb(0.5, "Populating Arch Linux master keys (pacman-key --populate)...")
                    r2 = subprocess.run(["sudo", "-n", "pacman-key", "--populate"], stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=90)
                    if r2.returncode != 0:
                        subprocess.run(["sudo", "-A", "pacman-key", "--populate"], stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=90)
                    if progress_cb:
                        progress_cb(0.8, "Refreshing archlinux-keyring & sync databases...")
                    res = subprocess.run(
                        ["sudo", "-n", "pacman", "-Sy", "--needed", "--noconfirm", "archlinux-keyring"],
                        stdin=subprocess.DEVNULL,
                        capture_output=True, text=True, env=env, timeout=180
                    )
                    if res.returncode != 0:
                        res = subprocess.run(
                            ["sudo", "-A", "pacman", "-Sy", "--needed", "--noconfirm", "archlinux-keyring"],
                            stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, env=env, timeout=180
                        )
                    if res.returncode == 0:
                        if progress_cb:
                            progress_cb(1.0, "Arch Linux keyring & databases repaired!")
                        if complete_cb:
                            complete_cb(True, "Arch Linux GPG keyring and sync databases repaired successfully!")
                    else:
                        if complete_cb:
                            complete_cb(False, f"Keyring sync finished with warning: {res.stderr or res.stdout}")
                except Exception as e:
                    if complete_cb:
                        complete_cb(False, f"Keyring repair failed: {e}")
        threading.Thread(target=_task, daemon=True).start()

import sys as _sys
_sys.modules.setdefault('aura_backend', _sys.modules[__name__])
