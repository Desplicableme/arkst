#!/usr/bin/env python3
"""
ArkST - Main Application Entrypoint
Standalone Universal Linux App Store for Arch Linux, AUR, Flathub, Snap, Docker & .deb packages.
"""

import sys
import os
import threading
import urllib.parse
from pathlib import Path

ARKST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ARKST_DIR))

from arkst_gtk_shim import install_gtk4_shim_if_needed
install_gtk4_shim_if_needed()

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, GLib

# Ensure Wayland / Hyprland xdg_toplevel app_id is always io.github.arkst
GLib.set_prgname("io.github.arkst")
GLib.set_application_name("ArkST")

from arkst_backend import PackageManager, HyprlandManager, ContainerManager
from arkst_ui import AuraWindow, ArkSTWindow

_MIGRATED_DOCKER_APPS = []


def ensure_arkst_desktop_and_purge_legacy():
    """
    Synchronously purge all legacy Aura/Ark directories, caches, and desktop shortcuts
    (including aura-box-*.desktop) BEFORE PackageManager scans desktop entries, and
    install multi-resolution ArkST icons.
    """
    global _MIGRATED_DOCKER_APPS
    try:
        import shutil
        home = Path.home()
        local_share = home / ".local" / "share"
        apps_dir = local_share / "applications"
        icons_base = local_share / "icons" / "hicolor"
        arkst_dir = Path(__file__).resolve().parent

        # 1. Purge legacy Aura / Ark directories & caches
        for legacy_dir in (local_share / "aura", local_share / "ark", home / ".cache" / "aura", home / ".config" / "aura"):
            if legacy_dir.exists():
                shutil.rmtree(legacy_dir, ignore_errors=True)

        # 2. Synchronously record & delete any legacy aura-box-*.desktop / ark-box-*.desktop and io.github.aura.desktop
        if apps_dir.exists():
            for pat in ("aura-box-*.desktop", "ark-box-*.desktop"):
                for f in apps_dir.glob(pat):
                    prefix = pat.split("*")[0]
                    app_id = f.stem[len(prefix):]
                    if app_id and app_id not in _MIGRATED_DOCKER_APPS:
                        _MIGRATED_DOCKER_APPS.append(app_id)
                    try:
                        f.unlink()
                    except Exception:
                        pass
            for pat in ("*aura*.desktop", "io.github.ark.desktop", "ark.desktop"):
                for f in apps_dir.glob(pat):
                    try:
                        f.unlink()
                    except Exception:
                        pass
            for f in apps_dir.glob("*.desktop"):
                try:
                    txt = f.read_text(encoding="utf-8", errors="ignore")
                    if "aura-box" in txt or "ark-box" in txt or "io.github.aura" in txt:
                        f.unlink(missing_ok=True)
                except Exception:
                    pass

        # 3. Purge legacy Aura / Ark icons
        if icons_base.exists():
            for pat in ("*aura*", "io.github.ark.svg", "io.github.ark.png"):
                for f in icons_base.rglob(pat):
                    try:
                        if f.is_file() or f.is_symlink():
                            f.unlink()
                    except Exception:
                        pass

        # 4. Install multi-size ArkST icons into ~/.local/share/icons/hicolor
        src_icons = arkst_dir / "data" / "icons"
        master_png = arkst_dir / "arkst-icon.png"
        if not master_png.exists():
            master_png = src_icons / "io.github.arkst.png"

        size_map = {
            "512x512": master_png,
            "256x256": src_icons / "arkst-256.png",
            "128x128": src_icons / "arkst-128.png",
            "64x64": src_icons / "arkst-64.png",
            "48x48": src_icons / "arkst-48.png",
        }
        for sz_dir, src_file in size_map.items():
            if src_file.exists():
                dest_dir = icons_base / sz_dir / "apps"
                dest_dir.mkdir(parents=True, exist_ok=True)
                for dest_name in ("io.github.arkst.png", "arkst.png", "arkst-icon.png"):
                    target = dest_dir / dest_name
                    if not target.exists() or target.stat().st_size != src_file.stat().st_size:
                        shutil.copy2(src_file, target)

        svg_src = arkst_dir / "arkst-icon.svg"
        if svg_src.exists():
            scal_dir = icons_base / "scalable" / "apps"
            scal_dir.mkdir(parents=True, exist_ok=True)
            for dest_name in ("io.github.arkst.svg", "arkst.svg", "arkst-icon.svg"):
                target = scal_dir / dest_name
                if not target.exists() or target.stat().st_size != svg_src.stat().st_size:
                    shutil.copy2(svg_src, target)

        # 5. Ensure user .desktop entry exists if not installed system-wide
        sys_desktop = Path("/usr/share/applications/io.github.arkst.desktop")
        if not sys_desktop.exists():
            apps_dir.mkdir(parents=True, exist_ok=True)
            exec_cmd = shutil.which("arkst") or f"python3 {arkst_dir / 'arkst.py'}"
            icon_val = str(master_png) if master_png.exists() else "io.github.arkst"
            desktop_txt = (
                "[Desktop Entry]\n"
                "Version=1.0\n"
                "Name=ArkST\n"
                "GenericName=Software Center & Package Manager\n"
                "Comment=ArkST — Universal Linux App Store for Arch Linux, AUR, Flathub, Snap, Docker & .deb packages\n"
                f"Exec={exec_cmd} %U\n"
                f"Icon={icon_val}\n"
                "Terminal=false\n"
                "Type=Application\n"
                "Categories=System;PackageManager;Settings;Utility;GTK;\n"
                "Keywords=arkst;pacman;paru;yay;aur;flathub;flatpak;deb;hyprland;store;apps;\n"
                "StartupNotify=true\n"
                "StartupWMClass=io.github.arkst\n"
            )
            (apps_dir / "io.github.arkst.desktop").write_text(desktop_txt, encoding="utf-8")
    except Exception:
        pass


class AuraApplication(Adw.Application):
    def __init__(self, initial_query: str = ""):
        GLib.set_prgname("io.github.arkst")
        super().__init__(
            application_id="io.github.arkst",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        )
        self.initial_query = initial_query
        self.pm = PackageManager()
        self.window = None
        self._start_background_migrations()

    def _start_background_migrations(self):
        """Auto-migrate Hyprland rules and Docker aura-box -> arkst-box using self.pm instances."""
        def _bg():
            try:
                # 1. Clean any leftover Aura Hyprland rules & apply ArkST rules if Hyprland is detected
                hypr_dir = Path.home() / ".config" / "hypr"
                if hypr_dir.exists() and hasattr(self.pm, "hypr_mgr"):
                    if not self.pm.hypr_mgr.are_window_rules_configured():
                        self.pm.hypr_mgr.configure_window_rules(enable=True)
            except Exception:
                pass

            try:
                # 2. Clean legacy aura-box / ark-box and repair shortcuts
                if hasattr(self.pm, "container_mgr"):
                    cm = self.pm.container_mgr
                    cm.migrate_legacy_containers()
                    cm.repair_existing_shortcuts()
            except Exception:
                pass

        threading.Thread(target=_bg, daemon=True).start()

    def do_activate(self):
        GLib.set_prgname("io.github.arkst")
        if not self.window:
            self.window = AuraWindow(self, self.pm)
            if self.initial_query:
                self.window.search_entry.set_text(self.initial_query)
        self.window.set_visible(True)
        self.window.present()

    def do_shutdown(self):
        PackageManager.clear_auth_cache()
        Adw.Application.do_shutdown(self)

    def do_command_line(self, command_line):
        GLib.set_prgname("io.github.arkst")
        args = command_line.get_arguments()
        query = ""
        action = None
        target_pkg = None

        if len(args) > 1:
            raw_arg = args[1]
            if raw_arg in ["-h", "--help"]:
                print("Usage: arkst [search-query] [file.deb] [--flathub|-F] [--deb|-B [file.deb]] [--hyprland|-H] [--discover] [--updates|-u] [--installed] [--docker|-D] [--snap|-S] [--storage] [--detail <pkg>] [--install <pkg|file.deb>] [appstream://<app-id>] [arkst://<route>]")
                print("ArkST - Standalone Universal Linux App Store for Arch Linux, AUR, Flathub, Snap, Docker & Hyprland")
                return 0
            elif raw_arg in ["--flathub", "--flatpak", "-F"]:
                action = "flathub"
            elif raw_arg in ["--discover"]:
                action = "discover"
            elif raw_arg in ["-u", "--updates"]:
                action = "updates"
            elif raw_arg in ["--installed"]:
                action = "installed"
            elif raw_arg in ["--docker", "-D", "--containers", "-C"]:
                action = "docker"
            elif raw_arg in ["--snap", "-S"]:
                action = "snap"
            elif raw_arg in ["--storage", "--maintenance"]:
                action = "storage"
            elif raw_arg in ["--deb", "-B"]:
                action = "deb"
                if len(args) > 2:
                    target_pkg = args[2]
            elif raw_arg in ["--hyprland", "-H"]:
                action = "hyprland"
            elif raw_arg.lower().endswith(".deb"):
                action = "deb"
                target_pkg = raw_arg
            elif raw_arg in ["-m", "--maximize"]:
                action = "maximize"
            elif raw_arg in ["-f", "--fullscreen"]:
                action = "fullscreen"
            elif raw_arg in ["-c", "--category"]:
                if len(args) > 2:
                    action = "category"
                    target_pkg = args[2]
                else:
                    print("[ArkST] Error: -c/--category requires a category name.", file=sys.stderr)
                    return 1
            elif raw_arg in ["--auth-dialog"]:
                action = "auth_dialog"
            elif raw_arg in ["--scroll-bottom"]:
                action = "scroll_bottom"
            elif raw_arg in ["-d", "--detail"]:
                if len(args) > 2:
                    action = "detail"
                    target_pkg = args[2]
                else:
                    print("[ArkST] Error: -d/--detail requires a package name.", file=sys.stderr)
                    return 1
            elif raw_arg in ["-i", "--install"]:
                if len(args) > 2:
                    pkg_name = args[2]
                    source = self.pm.resolve_package_source(pkg_name)
                    print(f"[ArkST] Direct install requested for: {pkg_name} (source: {source})")
                    self.hold()

                    def _prog(fraction: float, status: str):
                        pct = int(round(fraction * 100)) if fraction <= 1.0 else int(round(fraction))
                        print(f"[ArkST] [{pct}%] {status}", flush=True)

                    def _done(ok: bool, action: str, name: str, err: str):
                        if ok:
                            print(f"[ArkST] Installation of {name} completed successfully.", flush=True)
                        else:
                            print(f"[ArkST] Installation of {name} failed: {err}", file=sys.stderr, flush=True)
                        self.release()
                        try:
                            GLib.idle_add(lambda: False)
                        except Exception:
                            pass

                    res = self.pm.execute_background_action("install", pkg_name, source, _prog, _done)
                    if res in ("already_active", "already_queued"):
                        print(f"[ArkST] Package {pkg_name} is already being installed or queued.", flush=True)
                        self.release()
                    return 0
                else:
                    print("[ArkST] Error: -i/--install requires a package name.", file=sys.stderr)
                    return 1
            elif raw_arg.startswith("appstream://") or raw_arg.startswith("appstream:"):
                prefix = "appstream://" if raw_arg.startswith("appstream://") else "appstream:"
                app_id = raw_arg[len(prefix):].strip("/")
                if app_id.endswith(".desktop") and app_id not in self.pm.packages:
                    app_id = app_id[:-8]
                if app_id:
                    action = "detail"
                    target_pkg = app_id
            elif raw_arg.startswith(("arkst://", "arkst:", "ark://", "ark:", "aura://", "aura:")):
                for pfx in ("arkst://", "arkst:", "ark://", "ark:", "aura://", "aura:"):
                    if raw_arg.startswith(pfx):
                        prefix = pfx
                        break
                uri_val = raw_arg[len(prefix):].strip("/")
                if uri_val in ("discover", "updates", "installed", "docker", "snap", "flathub", "flatpak", "storage", "deb", "hyprland"):
                    action = "flathub" if uri_val == "flatpak" else uri_val
                elif uri_val.startswith("detail/"):
                    action = "detail"
                    target_pkg = uri_val[len("detail/"):].strip("/")
                elif uri_val.startswith("package/"):
                    action = "detail"
                    target_pkg = uri_val[len("package/"):].strip("/")
                elif uri_val.startswith("install/"):
                    action = "detail"
                    target_pkg = uri_val[len("install/"):].strip("/")
                elif uri_val.startswith("category/"):
                    action = "category"
                    target_pkg = uri_val[len("category/"):].strip("/")
                elif uri_val.startswith("search/") or uri_val.startswith("search?"):
                    if "/" in uri_val:
                        query = uri_val.split("/", 1)[1]
                    else:
                        parsed_q = urllib.parse.parse_qs(urllib.parse.urlparse(raw_arg).query)
                        query = parsed_q.get("q", [""])[0]
                elif uri_val:
                    action = "detail"
                    target_pkg = uri_val
            elif raw_arg in ["%U", "%u"] or raw_arg.startswith("%"):
                pass
            elif "://" in raw_arg:
                print(f"[ArkST] Unsupported URI: {raw_arg}", file=sys.stderr)
            elif raw_arg.startswith("-"):
                print(f"[ArkST] Unknown option: {raw_arg}", file=sys.stderr)
                print("Run 'arkst --help' for available options.", file=sys.stderr)
                return 1
            else:
                query = " ".join(args[1:])

        if not self.window:
            self.window = AuraWindow(self, self.pm)
        self.window.set_visible(True)

        if action == "discover":
            self.window.back_btn.set_visible(False)
            target = self.window.sidebar_buttons.get("discover")
            if target:
                target.set_active(True)
            self.window._on_sidebar_channel_click("discover")
        elif action == "updates":
            self.window.back_btn.set_visible(False)
            target = self.window.sidebar_buttons.get("updates")
            if target:
                target.set_active(True)
            self.window._on_sidebar_channel_click("updates")
        elif action == "installed":
            self.window.back_btn.set_visible(False)
            target = self.window.sidebar_buttons.get("installed")
            if target:
                target.set_active(True)
            self.window._on_sidebar_channel_click("installed")
        elif action in ("docker", "containers"):
            self.window.back_btn.set_visible(False)
            target = self.window.sidebar_buttons.get("docker") or self.window.sidebar_buttons.get("containers")
            if target:
                target.set_active(True)
            self.window._on_sidebar_channel_click("docker")
        elif action in ("flathub", "flatpak"):
            self.window.back_btn.set_visible(False)
            target = self.window.sidebar_buttons.get("flathub")
            if target:
                target.set_active(True)
            self.window._on_sidebar_channel_click("flathub")
        elif action == "snap":
            self.window.back_btn.set_visible(False)
            target = self.window.sidebar_buttons.get("snap")
            if target:
                target.set_active(True)
            self.window._on_sidebar_channel_click("snap")
        elif action == "storage":
            self.window.back_btn.set_visible(False)
            target = self.window.sidebar_buttons.get("storage")
            if target:
                target.set_active(True)
            self.window._on_sidebar_channel_click("storage")
        elif action == "deb":
            self.window.back_btn.set_visible(False)
            target = self.window.sidebar_buttons.get("deb")
            if target:
                target.set_active(True)
            self.window._on_sidebar_channel_click("deb")
            if target_pkg:
                self.window._load_deb_view(inspect_path=target_pkg)
        elif action == "hyprland":
            self.window.back_btn.set_visible(False)
            target = self.window.sidebar_buttons.get("hyprland")
            if target:
                target.set_active(True)
            self.window._on_sidebar_channel_click("hyprland")
        elif action == "maximize":
            self.window.maximize()
        elif action == "fullscreen":
            self.window.fullscreen()
        elif action == "category" and target_pkg:
            self.window._open_category(target_pkg)
        elif action == "detail" and target_pkg:
            source = self.pm.resolve_package_source(target_pkg)
            self.window._open_package_detail(target_pkg, source)
        elif action == "auth_dialog":
            self.window._show_password_config_dialog()
        elif action == "scroll_bottom":
            def _scroll():
                adj = self.window.detail_page.get_vadjustment()
                if adj:
                    adj.set_value(adj.get_upper())
                return False
            GLib.timeout_add(300, _scroll)
        elif query:
            self.window.back_btn.set_visible(False)
            self.window.search_entry.set_text(query)
            self.window._trigger_search(query)

        self.window.set_visible(True)
        self.window.present()
        return 0

    def on_command_line(self, app, command_line):
        return self.do_command_line(command_line)


def main():
    ensure_arkst_desktop_and_purge_legacy()
    initial_q = ""
    if len(sys.argv) > 1:
        first = sys.argv[1]
        if not first.startswith("-") and not first.startswith("%") and "://" not in first and not first.startswith(("arkst:", "aura:", "ark:")) and not first.lower().endswith((".deb", ".flatpakref")):
            initial_q = " ".join(sys.argv[1:])

    app = AuraApplication(initial_query=initial_q)
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

ArkApplication = AuraApplication
ArkSTApplication = AuraApplication
import sys as _sys
_sys.modules.setdefault('aura', _sys.modules[__name__])
