#!/usr/bin/env python3
"""
Aura Package Hub - Main Application Entrypoint
Ultra-fast, beautiful Arch Linux & AUR package manager with fuzzy search.
Prioritizes Pacman official repositories first, then Paru (AUR).
"""

import sys
import os
import urllib.parse
from pathlib import Path

# Add current directory to path
AURA_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AURA_DIR))

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, GLib

from aura_backend import PackageManager
from aura_ui import AuraWindow


class AuraApplication(Adw.Application):
    def __init__(self, initial_query: str = ""):
        super().__init__(
            application_id="io.github.aura",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE
        )
        self.initial_query = initial_query
        self.pm = PackageManager()
        self.window = None

    def do_activate(self):
        if not self.window:
            self.window = AuraWindow(self, self.pm)
            self.window.connect("close-request", lambda w: self.quit())
            if self.initial_query:
                self.window.search_entry.set_text(self.initial_query)
        self.window.present()

    def do_shutdown(self):
        PackageManager.clear_auth_cache()
        Adw.Application.do_shutdown(self)

    def do_command_line(self, command_line):
        args = command_line.get_arguments()
        query = ""
        action = None
        target_pkg = None

        if len(args) > 1:
            raw_arg = args[1]
            if raw_arg in ["-h", "--help"]:
                print("Usage: aura [search-query] [file.deb] [--deb|-B [file.deb]] [--hyprland|-H] [--discover] [--updates|-u] [--installed] [--docker|-D] [--snap|-S] [--storage] [--detail <pkg>] [--install <pkg|file.deb>] [appstream://<app-id>]")
                print("Aura App Store - Minimal, Modern App Store tailored for Hyprland")
                return 0
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
                    print("[Aura] Error: -c/--category requires a category name.", file=sys.stderr)
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
                    print("[Aura] Error: -d/--detail requires a package name.", file=sys.stderr)
                    return 1
            elif raw_arg in ["-i", "--install"]:
                if len(args) > 2:
                    pkg_name = args[2]
                    source = self.pm.resolve_package_source(pkg_name)
                    print(f"[Aura] Direct install requested for: {pkg_name} (source: {source})")
                    self.hold()

                    def _prog(fraction: float, status: str):
                        pct = int(round(fraction * 100)) if fraction <= 1.0 else int(round(fraction))
                        print(f"[Aura] [{pct}%] {status}", flush=True)

                    def _done(ok: bool, action: str, name: str, err: str):
                        if ok:
                            print(f"[Aura] Installation of {name} completed successfully.", flush=True)
                        else:
                            print(f"[Aura] Installation of {name} failed: {err}", file=sys.stderr, flush=True)
                        self.release()
                        try:
                            GLib.idle_add(lambda: False)
                        except Exception:
                            pass

                    res = self.pm.execute_background_action("install", pkg_name, source, _prog, _done)
                    if res in ("already_active", "already_queued"):
                        print(f"[Aura] Package {pkg_name} is already being installed or queued.", flush=True)
                        self.release()
                    return 0
                else:
                    print("[Aura] Error: -i/--install requires a package name.", file=sys.stderr)
                    return 1
            elif raw_arg.startswith("appstream://") or raw_arg.startswith("appstream:"):
                prefix = "appstream://" if raw_arg.startswith("appstream://") else "appstream:"
                app_id = raw_arg[len(prefix):].strip("/")
                if app_id.endswith(".desktop") and app_id not in self.pm.packages:
                    app_id = app_id[:-8]
                if app_id:
                    action = "detail"
                    target_pkg = app_id
            elif raw_arg.startswith("aura://") or raw_arg.startswith("aura:"):
                prefix = "aura://" if raw_arg.startswith("aura://") else "aura:"
                uri_val = raw_arg[len(prefix):].strip("/")
                if uri_val in ("discover", "updates", "installed", "docker", "snap", "storage", "deb", "hyprland"):
                    action = uri_val
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
                # Desktop entry placeholder passed literally; open normally without search
                pass
            elif "://" in raw_arg:
                print(f"[Aura] Unsupported URI: {raw_arg}", file=sys.stderr)
            elif raw_arg.startswith("-"):
                print(f"[Aura] Unknown option: {raw_arg}", file=sys.stderr)
                print("Run 'aura --help' for available options.", file=sys.stderr)
                return 1
            else:
                query = " ".join(args[1:])

        if not self.window:
            self.window = AuraWindow(self, self.pm)
            self.window.connect("close-request", lambda w: self.quit())

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

        self.window.present()
        return 0

    def on_command_line(self, app, command_line):
        return self.do_command_line(command_line)


def main():
    initial_q = ""
    if len(sys.argv) > 1:
        first = sys.argv[1]
        if not first.startswith("-") and not first.startswith("%") and "://" not in first and not first.startswith("aura:") and not first.lower().endswith(".deb"):
            initial_q = " ".join(sys.argv[1:])

    app = AuraApplication(initial_query=initial_q)
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
