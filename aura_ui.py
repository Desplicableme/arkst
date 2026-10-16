#!/usr/bin/env python3
"""
Aura Package Hub - Authentic macOS App Store Interface
Pixel-perfect recreation of the macOS / iOS 27 App Store UI:
- Native left navigation sidebar with search and categorized channels (Discover, Arcade, Create, Work, Play, Develop, Updates, Installed)
- Top Developer Spotlight / Showcase banners
- Perfectly symmetrical 3-column Mac App Store row grid
- 56x56 smooth squircles with 42px vector icons (zero emojis)
- Full-page Product Page with ambient colored glow hero, 100x100 squircle, Apple Quick Stats Strip, and feature highlight cards
- 0ms instantaneous Installed view with segmented Applications vs All Packages switcher
- Session credential caching (prompts password once per session, never repeatedly)
- In-app automatic progress bar for installation & updates (zero terminal windows)
- Smooth crossfade and push/pop slide animations
"""

import os
import sys
import re
import time
import shutil
import subprocess
import threading
import urllib.request
import urllib.parse
import json
from pathlib import Path
from typing import Dict, List, Optional, Any

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Adw, GLib, Gio, Gdk, GdkPixbuf, Pango

from aura_backend import (
    PackageManager, CURATED_CATEGORIES, resolve_icon_name, sanitize_str,
    get_app_display_name
)

APP_DIR = os.path.dirname(os.path.abspath(__file__))


def get_cached_icon_file(name: str, icon_url: str = "") -> str:
    """Return local path to cached icon if available, or fetch in background."""
    if not icon_url or not icon_url.startswith(("http://", "https://")):
        return icon_url or resolve_icon_name(name)
    try:
        cache_dir = Path.home() / ".cache" / "aura" / "icons"
        cache_dir.mkdir(parents=True, exist_ok=True)
        clean_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name)
        ext = ".svg" if ".svg" in icon_url.lower() else ".png"
        local_path = cache_dir / f"{clean_name}{ext}"
        if local_path.exists() and local_path.stat().st_size > 0:
            return str(local_path)

        def _fetch():
            try:
                req = urllib.request.Request(icon_url, headers={"User-Agent": "Aura-Store/1.0"})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = resp.read()
                    if data:
                        local_path.write_bytes(data)
            except Exception:
                pass
        threading.Thread(target=_fetch, daemon=True).start()
    except Exception:
        pass
    return resolve_icon_name(name)


_ICON_TEXTURE_CACHE: Dict[ Any, Any ] = {}


def create_scaled_image(icon_target: str, size: int = 40) -> Gtk.Image:
    """
    Safely and symmetrically scale any vector icon name or image file to exact pixel dimensions.
    CRITICAL: Never set hexpand=True or vexpand=True on the returned Gtk.Image, because GTK4
    propagates child expand flags upward to parent boxes (which would stretch brand_box and icon columns).
    """
    def _configure(im: Gtk.Image) -> Gtk.Image:
        im.set_pixel_size(size)
        im.set_halign(Gtk.Align.CENTER)
        im.set_valign(Gtk.Align.CENTER)
        im.set_hexpand(False)
        im.set_vexpand(False)
        return im

    eff_target = icon_target
    if icon_target and icon_target.startswith(("http://", "https://")):
        eff_target = get_cached_icon_file(os.path.basename(icon_target).split("?")[0], icon_target)
    if eff_target and os.path.isabs(eff_target) and os.path.exists(eff_target):
        cache_key = (eff_target, size)
        cached_tex = _ICON_TEXTURE_CACHE.get(cache_key)
        if cached_tex is not None:
            return _configure(Gtk.Image.new_from_paintable(cached_tex))
        try:
            if hasattr(GdkPixbuf.Pixbuf, "new_from_file_at_scale") and hasattr(Gdk.Texture, "new_for_pixbuf"):
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(eff_target, size, size, True)
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                if len(_ICON_TEXTURE_CACHE) < 512:
                    _ICON_TEXTURE_CACHE[cache_key] = texture
                return _configure(Gtk.Image.new_from_paintable(texture))
            return _configure(Gtk.Image.new_from_file(eff_target))
        except Exception:
            try:
                return _configure(Gtk.Image.new_from_file(eff_target))
            except Exception:
                pass
    clean_target = eff_target if eff_target else "system-software-install"
    return _configure(Gtk.Image.new_from_icon_name(clean_target))


# Authentic Apple Mac App Store Design System CSS
APPLE_CSS = """
/* Modern Keyframe Animations & Transitions */
@keyframes mac-pulse {
    0% { opacity: 0.55; }
    50% { opacity: 1.0; }
    100% { opacity: 0.55; }
}

@keyframes aura-hero-float {
    0% { transform: translateY(0px) scale(1.0); }
    50% { transform: translateY(-4px) scale(1.03); }
    100% { transform: translateY(0px) scale(1.0); }
}

@keyframes aura-watermark-drift {
    0% { transform: scale(1.0) rotate(0deg); opacity: 0.11; }
    50% { transform: scale(1.06) rotate(-2deg); opacity: 0.16; }
    100% { transform: scale(1.0) rotate(0deg); opacity: 0.11; }
}

@keyframes aura-glow-pulse {
    0% { box-shadow: 0 0 0 0 rgba(10, 132, 255, 0.35); }
    70% { box-shadow: 0 0 0 8px rgba(10, 132, 255, 0.0); }
    100% { box-shadow: 0 0 0 0 rgba(10, 132, 255, 0.0); }
}

.mac-loading-shimmer {
    animation: mac-pulse 1.5s ease-in-out infinite;
}

.aura-card-staging {
    opacity: 0.0;
    transform: translateY(12px) scale(0.98);
}

/* Sleek Minimalist Scrollbars — Zero Trough Background Capsule */
scrollbar,
scrollbar.overlay-indicator,
scrollbar.overlay-indicator.dragging,
scrollbar.overlay-indicator.hovering,
scrollbar contents,
scrollbar range,
scrollbar trough {
    background: transparent;
    background-color: transparent;
    background-image: none;
    border: none;
    box-shadow: none;
    outline: none;
    padding: 0;
    margin: 0;
}

scrollbar slider,
scrollbar.overlay-indicator slider,
scrollbar.overlay-indicator.hovering slider,
scrollbar.overlay-indicator.dragging slider {
    min-width: 4px;
    min-height: 32px;
    border-radius: 9999px;
    background: rgba(255, 255, 255, 0.16);
    background-color: rgba(255, 255, 255, 0.16);
    border: none;
    box-shadow: none;
    margin: 2px 3px;
    padding: 0;
    transition: background-color 150ms ease;
}

scrollbar slider:hover,
scrollbar.overlay-indicator.hovering slider:hover {
    background-color: rgba(255, 255, 255, 0.32);
}

.mac-sidebar scrollbar,
.mac-sidebar scrollbar trough,
.mac-sidebar scrollbar slider {
    min-width: 0px;
    min-height: 0px;
    opacity: 0;
    background: transparent;
    border: none;
    box-shadow: none;
    margin: 0;
    padding: 0;
}

/* Modern Animated Search Spinner & Status Indicator */
.mac-search-spinner {
    color: #0a84ff;
    min-width: 15px;
    min-height: 15px;
    margin-right: 4px;
}

.mac-search-status-box {
    min-height: 24px;
    margin-top: 2px;
    margin-bottom: 2px;
}

/* Base Window & Typography */
window.background {
    background-color: #0e0f14;
    color: #f5f5f7;
    font-family: "Inter Display", "Inter", -apple-system, BlinkMacSystemFont, "Adwaita Sans", sans-serif;
}

.aura-page {
    background-color: #0e0f14;
}

/* Disable GTK4 blurry undershoot / overshoot gradient overlays */
scrolledwindow undershoot.top,
scrolledwindow undershoot.bottom,
scrolledwindow overshoot.top,
scrolledwindow overshoot.bottom {
    background: none;
    box-shadow: none;
}

scrolledwindow,
scrolledwindow viewport {
    background-color: transparent;
    border: none;
}

/* Minimalist Seamless Header Bar */
.mac-header {
    background-color: transparent;
    border-bottom: none;
    min-height: 48px;
    padding: 8px 20px;
}

.mac-back-btn {
    border-radius: 9999px;
    min-width: 32px;
    min-height: 32px;
    padding: 0;
    background: #20222a;
    color: #ffffff;
    border: 1px solid rgba(255, 255, 255, 0.14);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
    transition: all 180ms cubic-bezier(0.2, 0.8, 0.2, 1);
}
.mac-back-btn image {
    margin-right: 1px; /* Optical centering compensation for left arrow */
}

.mac-back-btn:hover {
    background: #2e313d;
    border-color: rgba(255, 255, 255, 0.25);
    color: #ffffff;
}

.mac-back-btn:active, .mac-win-btn:active {
    transform: scale(0.92);
}

/* Linux-style Window Action Buttons */
.mac-win-btn {
    min-width: 32px;
    min-height: 32px;
    border-radius: 9999px;
    padding: 0px;
    background: #20222a;
    border: 1px solid rgba(255, 255, 255, 0.14);
    color: #e0e0e6;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
    transition: all 150ms ease;
}

.mac-win-btn:hover {
    background: #2e313d;
    color: #ffffff;
    border-color: rgba(255, 255, 255, 0.25);
}

.mac-win-close:hover {
    background: #ff453a;
    color: #ffffff;
    border-color: #ff453a;
    box-shadow: 0 1px 4px rgba(255, 69, 58, 0.25);
}

.mac-win-close:hover, .mac-win-min:hover, .mac-win-max:hover {
    transform: scale(1.15);
    transition: transform 150ms ease;
}

.mac-header-title {
    font-size: 14.5px;
    font-weight: 600;
    color: #ffffff;
    letter-spacing: -0.2px;
}

/* Modern Floating Glass Sidebar */
.mac-sidebar {
    background-color: rgba(18, 20, 26, 0.95);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 18px;
    margin: 12px 0 12px 12px;
    min-width: 210px;
    padding: 14px 10px 16px 10px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
}

.mac-brand-box {
    padding: 4px 6px 14px 6px;
}

.mac-brand-logo-squircle {
    min-width: 36px;
    min-height: 36px;
    border-radius: 9px;
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
    box-shadow: 0 4px 14px rgba(0,0,0,0.4);
}

.mac-brand-title {
    font-size: 15.5px;
    font-weight: 800;
    letter-spacing: -0.3px;
    color: #ffffff;
}

.mac-brand-sub {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: #0a84ff;
}

.mac-sidebar-section-hdr {
    font-size: 10.5px;
    font-weight: 700;
    color: #636366;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    margin: 12px 0 4px 10px;
}

/* Sidebar Search Entry */
.mac-sidebar-search {
    background-color: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 9px;
    padding: 6px 10px;
    font-size: 12.5px;
    color: #ffffff;
    margin: 2px 4px 12px 4px;
    transition: all 150ms ease;
}

.mac-sidebar-search:focus-within {
    background-color: rgba(255, 255, 255, 0.1);
    border-color: #0a84ff;
    box-shadow: 0 0 0 2px rgba(10, 132, 255, 0.35);
}

.mac-sidebar-search text {
    color: #ffffff;
    padding-left: 6px;
    padding-right: 6px;
}

.mac-sidebar-search image {
    color: #8e8e93;
}

/* Sidebar Navigation Items */
.mac-nav-item {
    background: transparent;
    border: none;
    border-radius: 9px;
    padding: 6px 10px;
    margin: 1px 2px;
    font-size: 12.5px;
    font-weight: 500;
    color: #98989d;
    transition: all 180ms cubic-bezier(0.16, 1, 0.3, 1);
}

.mac-nav-item:active {
    transform: scale(0.97);
}

.mac-nav-item:hover {
    transform: translateX(3px);
    background-color: rgba(255, 255, 255, 0.07);
    color: #ffffff;
}

.mac-nav-item:checked {
    background-color: #0071e3;
    color: #ffffff;
    font-weight: 600;
    box-shadow: 0 1px 4px rgba(0, 113, 227, 0.25);
}

.mac-nav-item:checked label {
    color: #ffffff;
}

/* Symmetrical Modern Monochrome Sidebar Icons */
.mac-nav-icon-box {
    min-width: 22px;
    min-height: 22px;
    color: #98989d;
    transition: all 200ms cubic-bezier(0.2, 0.8, 0.2, 1);
}

.mac-nav-icon-box image {
    color: #98989d;
    transition: all 200ms cubic-bezier(0.2, 0.8, 0.2, 1);
}

.mac-nav-item:hover .mac-nav-icon-box,
.mac-nav-item:hover .mac-nav-icon-box image {
    color: #ffffff;
}

.mac-nav-item:checked .mac-nav-icon-box,
.mac-nav-item:checked .mac-nav-icon-box image {
    color: #ffffff;
}

/* Container Applications Page Components */
.mac-container-card {
    transition: all 200ms cubic-bezier(0.16, 1, 0.3, 1);
}

.mac-container-card:hover {
    transform: translateY(-2px);
    border-color: rgba(255, 255, 255, 0.18);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
}

.mac-container-status-card {
    background: linear-gradient(135deg, rgba(28, 144, 237, 0.09), rgba(255, 255, 255, 0.02));
    border: 1px solid rgba(28, 144, 237, 0.22);
    border-radius: 16px;
    padding: 16px 18px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
    transition: all 180ms ease;
}

.mac-container-status-card:hover {
    border-color: rgba(28, 144, 237, 0.38);
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.35);
}

.mac-container-icon-box {
    min-width: 56px;
    min-height: 56px;
    border-radius: 14px;
    background: rgba(28, 144, 237, 0.12);
    border: 1px solid rgba(28, 144, 237, 0.25);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
    transition: all 200ms cubic-bezier(0.2, 0.8, 0.2, 1);
}

.mac-container-icon-box:hover {
    background: rgba(28, 144, 237, 0.20);
    border-color: rgba(28, 144, 237, 0.45);
}

.mac-container-pill {
    padding: 3px 10px;
    border-radius: 9999px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.3px;
}

.mac-container-pill-active {
    background: rgba(48, 209, 88, 0.18);
    color: #30d158;
    border: 1px solid rgba(48, 209, 88, 0.3);
}

.mac-container-pill-pending {
    background: rgba(255, 159, 10, 0.18);
    color: #ff9f0a;
    border: 1px solid rgba(255, 159, 10, 0.3);
}

.mac-container-search {
    background-color: rgba(255, 255, 255, 0.06);
    border-radius: 9px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    color: #ffffff;
    font-size: 13px;
    padding: 6px 12px;
}

.mac-container-search:focus-within {
    background-color: rgba(255, 255, 255, 0.10);
    border-color: #0a84ff;
}

.mac-container-tag {
    font-size: 10.5px;
    font-weight: 600;
    color: #0a84ff;
    background: rgba(10, 132, 255, 0.12);
    border: 1px solid rgba(10, 132, 255, 0.25);
    padding: 2px 7px;
    border-radius: 5px;
}

/* Sidebar Count Badges */
.mac-nav-badge {
    background-color: rgba(255, 255, 255, 0.12);
    color: #f2f2f7;
    border-radius: 9999px;
    min-width: 24px;
    min-height: 18px;
    padding: 1px 6px;
    font-size: 11px;
    font-weight: 700;
}

.mac-sidebar-section-header {
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.8px;
    color: #636366;
    margin: 16px 10px 4px 10px;
}

.mac-sidebar-divider {
    background-color: rgba(255, 255, 255, 0.06);
    min-height: 1px;
    margin: 10px 6px;
}

/* =========================================================================
   Animated Mac Hero Carousel / Slideshow
   ========================================================================= */
.mac-hero-carousel {
    border-radius: 18px;
    min-height: 195px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.45);
}

.mac-hero-slide {
    padding: 0;
    margin: 0;
    border-radius: 18px;
    min-height: 195px;
    transition: all 250ms cubic-bezier(0.16, 1, 0.3, 1);
}

.mac-hero-slide-0 {
    background: radial-gradient(circle at 80% 50%, rgba(235, 119, 0, 0.30) 0%, rgba(235, 119, 0, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(235, 119, 0, 0.22) 0%, rgba(20, 24, 32, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%);
    border: 1px solid rgba(235, 119, 0, 0.38);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.1);
}

.mac-hero-slide-1 {
    background: radial-gradient(circle at 80% 50%, rgba(0, 122, 204, 0.30) 0%, rgba(0, 122, 204, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(0, 122, 204, 0.25) 0%, rgba(18, 24, 34, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%);
    border: 1px solid rgba(0, 122, 204, 0.38);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.1);
}

.mac-hero-slide-2 {
    background: radial-gradient(circle at 80% 50%, rgba(102, 192, 244, 0.30) 0%, rgba(102, 192, 244, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(23, 29, 37, 0.6) 0%, rgba(102, 192, 244, 0.22) 45%, rgba(13, 17, 23, 0.98) 100%);
    border: 1px solid rgba(102, 192, 244, 0.38);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.1);
}

.mac-hero-slide-3 {
    background: radial-gradient(circle at 80% 50%, rgba(163, 113, 247, 0.30) 0%, rgba(163, 113, 247, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(48, 54, 61, 0.4) 0%, rgba(163, 113, 247, 0.24) 55%, rgba(13, 17, 23, 0.98) 100%);
    border: 1px solid rgba(163, 113, 247, 0.38);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.1);
}

.mac-hero-slide-4 {
    background: radial-gradient(circle at 80% 50%, rgba(109, 74, 255, 0.30) 0%, rgba(109, 74, 255, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(109, 74, 255, 0.25) 0%, rgba(20, 20, 35, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%);
    border: 1px solid rgba(109, 74, 255, 0.38);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.1);
}

.mac-hero-watermark {
    opacity: 0.13;
}

.mac-hero-tag {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: #0a84ff;
}

.mac-hero-title {
    font-size: 22px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: -0.3px;
}

.mac-hero-sub {
    font-size: 13px;
    color: #a1a1a6;
    line-height: 1.4;
}

.mac-hero-squircle {
    background: linear-gradient(135deg, rgba(255, 255, 255, 0.14) 0%, rgba(255, 255, 255, 0.04) 100%);
    border: 1px solid rgba(255, 255, 255, 0.22);
    border-radius: 22px;
    min-width: 88px;
    min-height: 88px;
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.55), inset 0 1px 0 rgba(255, 255, 255, 0.25);
    padding: 0;
    margin: 0;
    transition: transform 240ms cubic-bezier(0.22, 1, 0.36, 1), box-shadow 240ms ease;
}

.mac-hero-squircle:hover {
    transform: scale(1.04);
}

.mac-hero-squircle image {
    margin: 0;
}

button.mac-hero-nav-btn,
.mac-hero-nav-btn {
    min-width: 34px;
    min-height: 34px;
    padding: 0;
    margin: 0;
    border-radius: 9999px;
    background: rgba(20, 20, 25, 0.65);
    border: 1px solid rgba(255, 255, 255, 0.18);
    color: #ffffff;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.45);
    transition: all 180ms cubic-bezier(0.16, 1, 0.3, 1);
    outline: none;
}

button.mac-hero-nav-btn:hover,
.mac-hero-nav-btn:hover {
    background: rgba(255, 255, 255, 0.2);
    border-color: rgba(255, 255, 255, 0.35);
    transform: scale(1.12);
}

button.mac-hero-nav-btn:active,
.mac-hero-nav-btn:active {
    transform: scale(0.96);
    background: rgba(255, 255, 255, 0.28);
}

button.mac-hero-dot,
.mac-hero-dot {
    min-width: 7px;
    min-height: 7px;
    border-radius: 9999px;
    background-color: rgba(255, 255, 255, 0.3);
    border: none;
    padding: 0;
    margin: 0 3px;
    outline: none;
    box-shadow: none;
    transition: all 220ms cubic-bezier(0.16, 1, 0.3, 1);
}

button.mac-hero-dot:hover,
.mac-hero-dot:hover {
    background-color: rgba(255, 255, 255, 0.6);
}

button.mac-hero-dot-active,
.mac-hero-dot-active {
    min-width: 22px;
    min-height: 7px;
    border-radius: 9999px;
    background-color: rgba(255, 255, 255, 0.9);
    border: none;
    padding: 0;
    margin: 0 3px;
    outline: none;
    box-shadow: 0 0 8px rgba(255, 255, 255, 0.5);
    transition: all 220ms cubic-bezier(0.16, 1, 0.3, 1);
}

/* Top Spotlight Showcase Cards */
.mac-spotlight-card {
    border-radius: 14px;
    padding: 18px 20px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    transition: all 180ms cubic-bezier(0.16, 1, 0.3, 1);
}

.mac-spotlight-card:hover {
    border-color: rgba(255, 255, 255, 0.18);
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
}

.mac-spotlight-blue {
    background: linear-gradient(135deg, rgba(10, 132, 255, 0.22), rgba(14, 15, 20, 0.85));
}

.mac-spotlight-purple {
    background: linear-gradient(135deg, rgba(191, 90, 242, 0.22), rgba(14, 15, 20, 0.85));
}

.mac-spotlight-teal {
    background: linear-gradient(135deg, rgba(90, 200, 250, 0.22), rgba(14, 15, 20, 0.85));
}

.mac-eyebrow {
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.8px;
    color: #0a84ff;
}

.mac-eyebrow-purple {
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.8px;
    color: #bf5af2;
}

.mac-eyebrow-teal {
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.8px;
    color: #5ac8fa;
}

.mac-spotlight-title {
    font-size: 16px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: -0.2px;
}

.mac-spotlight-desc {
    font-size: 12px;
    color: #a1a1a6;
    line-height: 1.35;
}

/* Page & Category Section Titles */
.mac-page-title {
    font-size: 26px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: -0.5px;
}

.mac-page-subtitle {
    font-size: 13px;
    color: #86868b;
    font-weight: 400;
}

.mac-section-title {
    font-size: 17px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: -0.3px;
}

.mac-section-chevron {
    color: #86868b;
    font-size: 15px;
}

/* Symmetrical Multi-Column Mac App Store Item Row */
.mac-app-row {
    background: linear-gradient(145deg, rgba(255, 255, 255, 0.048) 0%, rgba(255, 255, 255, 0.018) 100%);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 16px;
    padding: 12px 14px;
    min-height: 80px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.07);
    transition: transform 240ms cubic-bezier(0.22, 1, 0.36, 1),
                opacity 260ms cubic-bezier(0.22, 1, 0.36, 1),
                background 220ms ease,
                border-color 220ms ease,
                box-shadow 240ms ease;
}

.mac-source-badge {
    font-size: 9.5px;
    font-weight: 800;
    letter-spacing: 0.5px;
    padding: 1px 6px;
    border-radius: 5px;
}

.mac-source-pacman {
    background: rgba(10, 132, 255, 0.14);
    color: #47a3ff;
    border: 1px solid rgba(10, 132, 255, 0.28);
}

.mac-source-aur {
    background: rgba(191, 90, 242, 0.15);
    color: #d48aff;
    border: 1px solid rgba(191, 90, 242, 0.30);
}

.mac-source-deb {
    background: rgba(255, 159, 10, 0.16);
    color: #ffb340;
    border: 1px solid rgba(255, 159, 10, 0.32);
}

.mac-source-snap {
    background: rgba(228, 92, 40, 0.16);
    color: #ff8552;
    border: 1px solid rgba(228, 92, 40, 0.32);
}

.mac-source-docker {
    background: rgba(36, 150, 237, 0.16);
    color: #5ac8fa;
    border: 1px solid rgba(36, 150, 237, 0.32);
}

.mac-log-terminal-box {
    background-color: #08090d;
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 10px;
    padding: 10px 12px;
    margin-top: 6px;
}

.mac-log-text {
    font-family: "JetBrains Mono", "Fira Code", monospace;
    font-size: 11px;
    color: #a1a1aa;
}

flowboxchild {
    padding: 0px;
    margin: 0px;
    background: transparent;
    border: none;
    outline: none;
}

.mac-app-row:hover {
    transform: translateY(-3px);
    background: linear-gradient(145deg, rgba(255, 255, 255, 0.085) 0%, rgba(10, 132, 255, 0.04) 100%);
    border-color: rgba(10, 132, 255, 0.32);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.42), 0 0 16px rgba(10, 132, 255, 0.08);
}

.mac-app-row:active {
    background: rgba(255, 255, 255, 0.07);
    transform: scale(0.985);
}

/* Curated Category Cards */
.mac-category-card {
    transition: all 200ms cubic-bezier(0.16, 1, 0.3, 1);
}

.mac-category-card:hover {
    transform: translateY(-2px);
    border-color: rgba(255, 255, 255, 0.2);
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
}

/* 54x54 Glossy Squircle Icon Container */
.mac-squircle {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 13px;
    min-width: 54px;
    min-height: 54px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
    transition: transform 200ms cubic-bezier(0.16, 1, 0.3, 1);
}

.mac-squircle:hover {
    transform: scale(1.05);
}

.mac-app-title {
    font-size: 13.5px;
    font-weight: 600;
    color: #ffffff;
    letter-spacing: -0.15px;
    line-height: 1.25;
}

.mac-app-desc {
    font-size: 11.5px;
    color: #86868b;
    line-height: 1.25;
}

/* Symmetrical Full-Rounded Action Pill Buttons (GET, OPEN, INSTALLED, UPDATE, UNINSTALL, QUEUED) */
.mac-btn-get, .mac-btn-open, .mac-btn-installed, .mac-btn-update, .mac-btn-uninstall, .mac-btn-queued {
    min-width: 68px;
    min-height: 28px;
    padding: 0px 10px;
    border-radius: 9999px;
    font-size: 11.5px;
    font-weight: 700;
    letter-spacing: 0.5px;
    border: none;
    transition: all 160ms cubic-bezier(0.16, 1, 0.3, 1);
}

.mac-btn-get:active,
.mac-btn-open:active,
.mac-btn-installed:active,
.mac-btn-update:active,
.mac-btn-uninstall:active,
.mac-btn-queued:active,
.mac-btn-update-all:active,
.mac-btn-primary-large:active,
.mac-btn-detail-open:active,
.mac-website-btn:active {
    transform: scale(0.95);
}

.mac-btn-get {
    background: linear-gradient(180deg, #0a84ff, #0071e3);
    color: #ffffff;
    border: none;
    box-shadow: 0 1px 4px rgba(10, 132, 255, 0.2);
}

.mac-btn-get:hover {
    background: linear-gradient(180deg, #2191ff, #0077ed);
    box-shadow: 0 2px 6px rgba(10, 132, 255, 0.3);
}

.mac-btn-queued {
    background: linear-gradient(180deg, #d29922, #b07d10);
    color: #ffffff;
    font-weight: 700;
    border: none;
    box-shadow: 0 1px 4px rgba(210, 153, 34, 0.25);
}

.mac-btn-queued:disabled {
    opacity: 0.88;
    box-shadow: none;
}

.mac-btn-primary-large.mac-btn-queued {
    background: linear-gradient(180deg, #d29922, #b07d10);
    color: #ffffff;
    box-shadow: 0 1px 4px rgba(210, 153, 34, 0.25);
}

.mac-btn-open {
    background: linear-gradient(180deg, #34c759, #28a745);
    color: #ffffff;
    border: none;
    box-shadow: 0 1px 4px rgba(40, 167, 69, 0.2);
}

.mac-btn-open:hover {
    background: linear-gradient(180deg, #3cd864, #2eb94c);
    box-shadow: 0 2px 6px rgba(40, 167, 69, 0.3);
}

.mac-btn-installed {
    background: linear-gradient(180deg, #414658, #323646);
    color: #ffffff;
    font-weight: 700;
    border: none;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
}

.mac-btn-installed:hover {
    background: linear-gradient(180deg, #4c5268, #3b4052);
    color: #ffffff;
    border-color: rgba(255, 255, 255, 0.35);
}

.mac-btn-update {
    background: linear-gradient(135deg, #ff9f0a 0%, #ff6b00 100%);
    color: #ffffff;
    font-weight: 700;
    border: none;
    box-shadow: 0 2px 8px rgba(255, 159, 10, 0.35);
}

.mac-btn-update:hover {
    background: linear-gradient(135deg, #ffaa26 0%, #ff791a 100%);
    box-shadow: 0 4px 14px rgba(255, 159, 10, 0.45);
}

.mac-btn-get:disabled {
    opacity: 0.85;
    box-shadow: none;
}

.mac-btn-update:disabled,
.mac-btn-update-all:disabled {
    opacity: 0.45;
    box-shadow: none;
}

.mac-btn-installed:disabled {
    opacity: 0.85;
    box-shadow: none;
}

.mac-btn-uninstall {
    background: linear-gradient(180deg, #ff453a, #d70015);
    color: #ffffff;
    font-weight: 700;
    border: none;
    box-shadow: 0 1px 4px rgba(255, 69, 58, 0.2);
}

.mac-btn-uninstall:hover {
    background: linear-gradient(180deg, #ff5b52, #e01b22);
    box-shadow: 0 2px 6px rgba(255, 69, 58, 0.3);
}

.mac-btn-trash {
    min-width: 30px;
    min-height: 30px;
    border-radius: 9999px;
    background: rgba(255, 69, 58, 0.12);
    color: #ff453a;
    border: 1px solid rgba(255, 69, 58, 0.25);
    padding: 0;
    transition: all 180ms cubic-bezier(0.2, 0.8, 0.2, 1);
}
.mac-btn-trash:hover {
    background: rgba(255, 69, 58, 0.24);
    border-color: rgba(255, 69, 58, 0.5);
    color: #ff3b30;
    box-shadow: 0 2px 6px rgba(255, 69, 58, 0.25);
}
.mac-btn-trash:active {
    transform: scale(0.92);
}

.mac-btn-update-all {
    background: linear-gradient(180deg, #ff9f0a, #e68e00);
    color: #ffffff;
    border-radius: 9999px;
    min-width: 114px;
    min-height: 32px;
    padding: 0 16px;
    font-size: 11.5px;
    font-weight: 700;
    letter-spacing: 0.4px;
    border: none;
    box-shadow: 0 1px 4px rgba(255, 159, 10, 0.2);
    transition: all 160ms cubic-bezier(0.16, 1, 0.3, 1);
}

.mac-btn-update-all:hover {
    background: linear-gradient(180deg, #ffab26, #f09500);
    box-shadow: 0 2px 6px rgba(255, 159, 10, 0.3);
}

/* Segmented Pill Switcher (Installed Page) */
.mac-segmented-box {
    background-color: #181920;
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 9999px;
    padding: 3px;
}

.mac-segmented-box button {
    border-radius: 9999px;
    padding: 6px 16px;
    font-size: 12.5px;
    font-weight: 600;
    color: #8e8e93;
    border: none;
    background: transparent;
    transition: all 140ms ease;
}

.mac-segmented-box button:active {
    transform: scale(0.96);
}

.mac-segmented-box button:checked {
    background: linear-gradient(180deg, #0a84ff, #0071e3);
    color: #ffffff;
    font-weight: 600;
    box-shadow: 0 1px 4px rgba(10, 132, 255, 0.25);
}

.mac-segmented-box button:hover:not(:checked) {
    color: #ffffff;
}

/* Product Detail Inspector Page */
.mac-detail-hero {
    background: linear-gradient(135deg, rgba(24, 38, 64, 0.45), rgba(14, 15, 20, 0.85));
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 18px;
    padding: 20px 22px;
}

.mac-detail-icon-squircle {
    background: linear-gradient(145deg, rgba(255, 255, 255, 0.09), rgba(255, 255, 255, 0.03));
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 20px;
    min-width: 88px;
    min-height: 88px;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25);
}

.mac-detail-title {
    font-size: 24px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: -0.4px;
}

.mac-detail-subtitle {
    font-size: 13.5px;
    color: #86868b;
    margin-top: 2px;
}

.mac-detail-meta {
    font-size: 12px;
    color: #636366;
    margin-top: 4px;
}

.mac-btn-primary-large {
    background: linear-gradient(180deg, #0a84ff, #0071e3);
    color: #ffffff;
    border-radius: 9999px;
    min-width: 108px;
    min-height: 36px;
    padding: 0px 18px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.5px;
    border: none;
    box-shadow: 0 1px 4px rgba(10, 132, 255, 0.2);
    transition: all 140ms cubic-bezier(0.16, 1, 0.3, 1);
}

.mac-btn-danger-pill:active {
    transform: scale(0.95);
}

.mac-btn-primary-large:hover {
    background: linear-gradient(180deg, #2191ff, #0077ed);
    box-shadow: 0 2px 6px rgba(10, 132, 255, 0.3);
}

.mac-btn-detail-open {
    background: linear-gradient(180deg, #34c759, #28a745);
    color: #ffffff;
    border-radius: 9999px;
    min-width: 108px;
    min-height: 36px;
    padding: 0px 18px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.5px;
    border: none;
    box-shadow: 0 1px 4px rgba(40, 167, 69, 0.2);
    transition: all 140ms cubic-bezier(0.16, 1, 0.3, 1);
}

.mac-btn-detail-open:hover {
    background: linear-gradient(180deg, #3cd864, #2eb94c);
    box-shadow: 0 2px 6px rgba(40, 167, 69, 0.3);
}

.mac-btn-danger-pill {
    background: linear-gradient(180deg, #ff453a, #d70015);
    color: #ffffff;
    border-radius: 9999px;
    min-width: 108px;
    min-height: 36px;
    padding: 0px 18px;
    font-size: 11.5px;
    font-weight: 700;
    letter-spacing: 0.5px;
    border: none;
    box-shadow: 0 1px 4px rgba(255, 69, 58, 0.2);
    transition: all 140ms cubic-bezier(0.16, 1, 0.3, 1);
}

.mac-btn-danger-pill:hover {
    background: linear-gradient(180deg, #ff5b52, #e01b22);
    box-shadow: 0 2px 6px rgba(255, 69, 58, 0.3);
}

/* Apple Quick Stats Strip */
.mac-stats-strip {
    background: rgba(255, 255, 255, 0.025);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 14px;
    padding: 10px 8px;
    margin: 2px 0;
}

.mac-stat-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.8px;
    color: #86868b;
    margin-bottom: 2px;
}

.mac-stat-value {
    font-size: 12.5px;
    font-weight: 600;
    color: #ffffff;
    letter-spacing: -0.15px;
    line-height: 1.25;
}

/* Feature Preview Cards */
.mac-preview-card {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 14px;
    padding: 16px 18px;
    transition: all 140ms ease;
}

.mac-preview-card:hover {
    background: rgba(255, 255, 255, 0.055);
    border-color: rgba(255, 255, 255, 0.12);
}

.mac-highlight-icon {
    color: #0a84ff;
}

.mac-preview-card-title {
    font-size: 13px;
    font-weight: 600;
    color: #ffffff;
}

.mac-preview-card-desc {
    font-size: 11.5px;
    color: #86868b;
    line-height: 1.35;
}

/* Badges */
.badge-pacman {
    background-color: rgba(10, 132, 255, 0.16);
    color: #0a84ff;
    border-radius: 9999px;
    padding: 2px 8px;
    font-size: 10.5px;
    font-weight: 600;
}

.badge-aur {
    background-color: rgba(191, 90, 242, 0.18);
    color: #bf5af2;
    border-radius: 9999px;
    padding: 2px 8px;
    font-size: 10.5px;
    font-weight: 600;
}

.badge-installed {
    background-color: rgba(48, 209, 88, 0.16);
    color: #30d158;
    border-radius: 9999px;
    padding: 2px 8px;
    font-size: 10.5px;
    font-weight: 600;
}

/* See All Button & Section Subtitle */
.mac-see-all-btn {
    background: transparent;
    border: none;
    color: #0a84ff;
    font-size: 12px;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 6px;
    transition: all 140ms ease;
}

.mac-see-all-btn:hover {
    background: rgba(10, 132, 255, 0.12);
    color: #0071e3;
}

.mac-section-subtitle {
    font-size: 11.5px;
    color: #86868b;
    font-weight: 400;
}

/* Enhanced About Card & Metadata */
.mac-about-card {
    background: rgba(255, 255, 255, 0.025);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 14px;
    padding: 18px 20px;
}

.mac-about-text {
    font-size: 13px;
    color: #d1d1d6;
    line-height: 1.5;
}

.mac-website-btn {
    background: linear-gradient(180deg, #0a84ff, #0071e3);
    color: #ffffff;
    border: none;
    border-radius: 9999px;
    min-height: 32px;
    min-width: 116px;
    padding: 0 16px;
    font-size: 11.5px;
    font-weight: 700;
    box-shadow: 0 1px 4px rgba(10, 132, 255, 0.2);
    transition: all 140ms cubic-bezier(0.16, 1, 0.3, 1);
}

.mac-website-btn:hover {
    background: linear-gradient(180deg, #2191ff, #0077ed);
    color: #ffffff;
    box-shadow: 0 2px 6px rgba(10, 132, 255, 0.3);
}

.mac-deps-flow {
    background: transparent;
}

.mac-deps-flow flowboxchild {
    background: transparent;
    padding: 0;
    margin: 0;
    border-radius: 9999px;
}

.mac-dep-tag {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 9999px;
    padding: 3px 12px;
    font-size: 11px;
    font-weight: 500;
    color: #98989d;
    font-family: monospace;
    transition: all 120ms ease;
}

.mac-dep-tag:hover {
    background: rgba(255, 255, 255, 0.12);
    border-color: rgba(255, 255, 255, 0.18);
    color: #ffffff;
}

.mac-stat-col {
    padding: 6px 8px;
    border-right: 1px solid rgba(255, 255, 255, 0.08);
}

.mac-stat-col-last {
    padding: 6px 8px;
    border-right: none;
}

.mac-tag-pill {
    background-color: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 500;
    color: #a1a1a6;
}

/* Circular Highlight Badges */
.mac-highlight-badge-blue {
    background: rgba(10, 132, 255, 0.15);
    color: #0a84ff;
    border-radius: 9999px;
    min-width: 28px;
    min-height: 28px;
}

.mac-highlight-badge-green {
    background: rgba(48, 209, 88, 0.15);
    color: #30d158;
    border-radius: 9999px;
    min-width: 28px;
    min-height: 28px;
}

.mac-highlight-badge-amber {
    background: rgba(255, 159, 10, 0.15);
    color: #ff9f0a;
    border-radius: 9999px;
    min-width: 28px;
    min-height: 28px;
}

/* Specifications Table / Information Card */
.mac-info-card {
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 14px;
    padding: 2px 0;
}

.mac-info-row {
    padding: 12px 20px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.mac-info-row-last {
    padding: 12px 20px;
}

.mac-info-key {
    font-size: 13px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.55);
}

.mac-info-val {
    font-size: 13px;
    font-weight: 600;
    color: #f5f5f7;
}

.mac-auth-verified {
    color: #30d158;
}

.mac-auth-verified:hover {
    color: #3cd864;
}

.mac-auth-needed {
    color: #e0e0e6;
}

.success-status {
    color: #30d158;
    font-weight: 600;
    font-size: 12px;
}

/* Modern Apple Glassmorphic Progress Capsule */
.progress-card {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 16px;
    padding: 16px 20px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35);
    transition: all 250ms cubic-bezier(0.16, 1, 0.3, 1);
}

.mac-progress-header {
    margin-bottom: 8px;
}

.mac-progress-title {
    font-size: 13px;
    font-weight: 600;
    color: #ffffff;
    font-feature-settings: "tnum";
    font-variant-numeric: tabular-nums;
}

.mac-progress-percent {
    font-size: 13px;
    font-weight: 700;
    color: #0a84ff;
    font-feature-settings: "tnum";
    font-variant-numeric: tabular-nums;
}

progressbar.mac-capsule-progress {
    min-height: 8px;
    border-radius: 9999px;
}

progressbar.mac-capsule-progress > trough {
    background: rgba(0, 0, 0, 0.45);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 9999px;
    min-height: 8px;
    box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.6);
}

progressbar.mac-capsule-progress > trough > progress {
    background: linear-gradient(90deg, #0071e3 0%, #0a84ff 60%, #64d2ff 100%);
    border-radius: 9999px;
    min-height: 8px;
    box-shadow: 0 0 12px rgba(10, 132, 255, 0.5);
    transition: width 150ms cubic-bezier(0.16, 1, 0.3, 1);
}

/* Floating Header Global Progress Pill */
.mac-header-progress-pill {
    background: rgba(10, 132, 255, 0.15);
    border: 1px solid rgba(10, 132, 255, 0.35);
    border-radius: 9999px;
    padding: 4px 12px;
    font-size: 11.5px;
    font-weight: 600;
    color: #5ac8fa;
    font-feature-settings: "tnum";
    font-variant-numeric: tabular-nums;
    transition: all 200ms ease;
}
.mac-header-progress-pill:hover {
    background: rgba(10, 132, 255, 0.25);
    border-color: rgba(10, 132, 255, 0.5);
}

flowboxchild {
    padding: 0;
    margin: 0;
    background: transparent;
    border: none;
    outline: none;
}

flowboxchild:focus,
flowboxchild:selected,
flowboxchild:hover {
    outline: none;
    background: transparent;
    box-shadow: none;
}

/* Detail Page Update Banner (Modern Glassmorphic Card) */
.mac-update-banner {
    background: linear-gradient(135deg, rgba(255, 159, 10, 0.16) 0%, rgba(255, 94, 58, 0.08) 100%);
    border: 1px solid rgba(255, 159, 10, 0.35);
    border-radius: 16px;
    padding: 14px 18px;
    margin-bottom: 14px;
    box-shadow: 0 4px 20px rgba(255, 159, 10, 0.08), 0 2px 8px rgba(0, 0, 0, 0.25);
    transition: all 180ms ease;
}

.mac-update-banner:hover {
    border-color: rgba(255, 159, 10, 0.50);
    box-shadow: 0 6px 26px rgba(255, 159, 10, 0.18), 0 2px 10px rgba(0, 0, 0, 0.3);
}

.mac-update-badge-icon {
    min-width: 40px;
    min-height: 40px;
    border-radius: 12px;
    background: linear-gradient(135deg, #ff9f0a 0%, #ff6b00 100%);
    border: 1px solid rgba(255, 255, 255, 0.25);
    color: #ffffff;
    box-shadow: 0 3px 10px rgba(255, 159, 10, 0.40);
}

.mac-update-banner-title {
    font-size: 14px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: -0.2px;
}

.mac-update-version-pill {
    background: rgba(255, 159, 10, 0.22);
    border: 1px solid rgba(255, 159, 10, 0.45);
    border-radius: 8px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 700;
    color: #ffd080;
    letter-spacing: 0.2px;
}

.mac-update-banner-sub {
    font-size: 12px;
    color: rgba(255, 255, 255, 0.65);
    margin-top: 2px;
}

/* Modern Search Filter Pills & Glass Search Bar */
.mac-search-filter-pill {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 9999px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 600;
    color: #98989d;
    transition: all 180ms cubic-bezier(0.16, 1, 0.3, 1);
    outline: none;
}

.mac-search-filter-pill:hover {
    background: rgba(255, 255, 255, 0.10);
    color: #ffffff;
    border-color: rgba(255, 255, 255, 0.18);
    transform: translateY(-1px);
}

.mac-search-filter-pill:active {
    transform: scale(0.96);
}

.mac-search-filter-pill:checked {
    background: linear-gradient(135deg, #0a84ff, #0071e3);
    color: #ffffff;
    border-color: #0a84ff;
    box-shadow: 0 2px 8px rgba(10, 132, 255, 0.35);
    font-weight: 700;
}

.mac-search-filter-pill:checked label,
.mac-search-filter-pill:checked image {
    color: #ffffff;
}

/* Segmented Primary Ecosystem Capsule Pills */
.mac-segmented-box .mac-search-filter-pill {
    background: transparent;
    border: none;
    padding: 6px 16px;
    border-radius: 9999px;
    color: #8e8e93;
    box-shadow: none;
    font-size: 12.5px;
}

.mac-segmented-box .mac-search-filter-pill:hover:not(:checked) {
    background: rgba(255, 255, 255, 0.08);
    color: #ffffff;
    border-color: transparent;
    transform: none;
}

.mac-segmented-box .mac-search-filter-pill:checked {
    background: linear-gradient(180deg, #0a84ff, #0071e3);
    color: #ffffff;
    border: none;
    box-shadow: 0 1px 6px rgba(10, 132, 255, 0.35);
    font-weight: 700;
}

.mac-search-glass-bar {
    background-color: rgba(255, 255, 255, 0.06);
    background-image: none;
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 12px;
    padding: 6px 14px;
    min-height: 40px;
    color: #ffffff;
    font-size: 13.5px;
    box-shadow: none;
    outline: none;
}

.mac-search-glass-bar:focus-within {
    background-color: rgba(255, 255, 255, 0.09);
    border-color: rgba(10, 132, 255, 0.65);
    box-shadow: 0 0 0 2px rgba(10, 132, 255, 0.25);
}

.mac-search-glass-bar text {
    color: #ffffff;
    padding-left: 8px;
    padding-right: 8px;
}

.mac-search-glass-bar image {
    color: #8e8e93;
}

.mac-installed-empty-box {
    margin-top: 50px;
    margin-bottom: 50px;
}

.mac-installed-empty-icon {
    opacity: 0.35;
    color: #8e8e93;
    margin-bottom: 8px;
}

.mac-installed-empty-title {
    font-size: 16px;
    font-weight: 600;
    color: #f5f5f7;
    margin-bottom: 2px;
}

.mac-browse-status-label {
    min-height: 22px;
    font-size: 12.5px;
    color: #8e8e93;
}

.mac-browse-results-container {
    min-height: 0;
}

.mac-search-hero {
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.04) 0%, rgba(255, 255, 255, 0.01) 100%);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 20px;
    padding: 24px 24px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
}

.mac-search-hero-centered {
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.04) 0%, rgba(255, 255, 255, 0.01) 100%);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 18px;
    padding: 20px 20px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
}

.mac-search-hero-icon {
    min-width: 52px;
    min-height: 52px;
    border-radius: 15px;
    background: linear-gradient(135deg, rgba(10, 132, 255, 0.25), rgba(10, 132, 255, 0.08));
    border: 1px solid rgba(10, 132, 255, 0.35);
    color: #0a84ff;
    box-shadow: 0 4px 16px rgba(10, 132, 255, 0.2);
}

.mac-search-hero-title {
    font-size: 16.5px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: -0.3px;
    margin-top: 4px;
}

.mac-search-hero-desc {
    font-size: 12px;
    color: #98989d;
    line-height: 1.4;
    margin-top: 2px;
}

.mac-search-chip {
    background-color: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 20px;
    padding: 5px 12px;
    font-size: 11.5px;
    font-weight: 500;
    color: #c7c7cc;
    transition: all 150ms ease;
}

.mac-search-chip:hover {
    background-color: rgba(10, 132, 255, 0.18);
    border-color: rgba(10, 132, 255, 0.4);
    color: #ffffff;
}

/* Canonical Snap Store Channel */
.mac-snap-badge {
    font-size: 10.5px;
    font-weight: 600;
    color: #e45c28;
    background: rgba(228, 92, 40, 0.14);
    border: 1px solid rgba(228, 92, 40, 0.28);
    padding: 2px 7px;
    border-radius: 5px;
}

.mac-snap-hero-card {
    background: radial-gradient(circle at 85% 50%, rgba(228, 92, 40, 0.22) 0%, transparent 60%), linear-gradient(135deg, rgba(228, 92, 40, 0.12) 0%, rgba(20, 22, 28, 0.95) 60%);
    border: 1px solid rgba(228, 92, 40, 0.28);
    border-radius: 16px;
    padding: 20px 24px;
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.35);
}

.mac-snap-card {
    transition: all 200ms cubic-bezier(0.16, 1, 0.3, 1);
}

.mac-snap-card:hover {
    transform: translateY(-2px);
    border-color: rgba(228, 92, 40, 0.35);
    box-shadow: 0 4px 18px rgba(0, 0, 0, 0.4);
}

/* Storage & Maintenance System */
.mac-storage-card {
    background-color: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 14px;
    padding: 16px 18px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
    margin-bottom: 16px;
}

.mac-storage-meter-track {
    background-color: rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    min-height: 16px;
    margin: 12px 0 10px 0;
}

.mac-storage-seg-pacman {
    background-color: #0a84ff;
    min-height: 16px;
}

.mac-storage-seg-aur {
    background-color: #ff9f0a;
    min-height: 16px;
}

.mac-storage-seg-docker {
    background-color: #30d158;
    min-height: 16px;
}

.mac-storage-seg-journal {
    background-color: #bf5af2;
    min-height: 16px;
}

.mac-storage-seg-aura {
    background-color: #64d2ff;
    min-height: 16px;
}

.mac-storage-seg-free {
    background-color: rgba(255, 255, 255, 0.12);
    min-height: 16px;
}

.mac-cache-row {
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 12px;
    padding: 14px 18px;
    transition: all 150ms ease;
    margin-bottom: 8px;
}

.mac-cache-row:hover {
    background-color: rgba(255, 255, 255, 0.06);
    border-color: rgba(255, 255, 255, 0.12);
}

.mac-cache-size-pill {
    font-size: 13px;
    font-weight: 700;
    color: #ffffff;
    background-color: rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    padding: 4px 10px;
}
"""

CURATED_SNAPS = [
    {
        "name": "spotify",
        "title": "Spotify",
        "summary": "Music for everyone",
        "publisher": "Spotify",
        "icon": "spotify",
        "desc": "Spotify is a digital music service that gives you access to millions of songs, podcasts and videos from artists all over the world.",
        "version": "1.2.53",
        "source": "snap"
    },
    {
        "name": "code",
        "title": "Visual Studio Code",
        "summary": "Code editing. Redefined.",
        "publisher": "Microsoft",
        "icon": "code",
        "desc": "Visual Studio Code is a code editor redefined and optimized for building and debugging modern web and cloud applications.",
        "version": "1.97.2",
        "source": "snap"
    },
    {
        "name": "discord",
        "title": "Discord",
        "summary": "All-in-one voice and text chat for gamers",
        "publisher": "Snapcrafters",
        "icon": "discord",
        "desc": "Discord is the easiest way to talk over voice, video, and text. Talk, chat, hang out, and stay close with your friends and communities.",
        "version": "0.0.84",
        "source": "snap"
    },
    {
        "name": "slack",
        "title": "Slack",
        "summary": "One platform for your team and your work",
        "publisher": "Slack",
        "icon": "slack",
        "desc": "Slack brings all your team communication together in one place, with real-time messaging, archiving and search for modern teams.",
        "version": "4.41.105",
        "source": "snap"
    },
    {
        "name": "postman",
        "title": "Postman",
        "summary": "API Platform for building and using APIs",
        "publisher": "Postman",
        "icon": "postman",
        "desc": "Postman is an API platform for building and using APIs. Postman simplifies each step of the API lifecycle and streamlines collaboration.",
        "version": "11.33.1",
        "source": "snap"
    },
    {
        "name": "telegram-desktop",
        "title": "Telegram Desktop",
        "summary": "Official desktop app for Telegram messenger",
        "publisher": "Telegram",
        "icon": "telegram",
        "desc": "Telegram is a messaging app with a focus on speed and security, it's super-fast, simple and free.",
        "version": "5.10.3",
        "source": "snap"
    },
    {
        "name": "vlc",
        "title": "VLC",
        "summary": "The ultimate open source multimedia player",
        "publisher": "VideoLAN",
        "icon": "vlc",
        "desc": "VLC media player is a free and open source cross-platform multimedia player that plays most multimedia files as well as DVDs, Audio CDs, VCDs, and various streaming protocols.",
        "version": "3.0.21",
        "source": "snap"
    },
    {
        "name": "blender",
        "title": "Blender",
        "summary": "Free and open source 3D creation suite",
        "publisher": "Blender Foundation",
        "icon": "blender",
        "desc": "Blender is the free and open source 3D creation suite supporting modeling, rigging, animation, simulation, rendering, compositing and motion tracking.",
        "version": "4.3.2",
        "source": "snap"
    },
    {
        "name": "obsidian",
        "title": "Obsidian",
        "summary": "Sharpen your thinking with Markdown notes",
        "publisher": "Obsidian",
        "icon": "obsidian",
        "desc": "Obsidian is a powerful and extensible knowledge base that works on top of your local folder of plain text files.",
        "version": "1.7.7",
        "source": "snap"
    },
    {
        "name": "chromium",
        "title": "Chromium",
        "summary": "Fast, reliable, and secure web browser",
        "publisher": "Canonical",
        "icon": "chromium",
        "desc": "Chromium is an open-source browser project that aims to build a safer, faster, and more stable way for all users to experience the web.",
        "version": "133.0",
        "source": "snap"
    },
    {
        "name": "pycharm-community",
        "title": "PyCharm Community",
        "summary": "Python IDE for professional developers",
        "publisher": "JetBrains",
        "icon": "pycharm-community",
        "desc": "The Python IDE for Professional Developers by JetBrains.",
        "version": "2024.3.2",
        "source": "snap"
    },
    {
        "name": "insomnia",
        "title": "Insomnia",
        "summary": "Design, debug, and test APIs like never before",
        "publisher": "Kong Inc.",
        "icon": "insomnia",
        "desc": "The open-source, cross-platform API client for GraphQL, REST, WebSockets, SSE and gRPC.",
        "version": "10.3.0",
        "source": "snap"
    },
    {
        "name": "bitwarden",
        "title": "Bitwarden",
        "summary": "Secure and free password manager",
        "publisher": "Bitwarden",
        "icon": "bitwarden",
        "desc": "A secure and free password manager for all of your devices.",
        "version": "2024.12.0",
        "source": "snap"
    },
    {
        "name": "audacity",
        "title": "Audacity",
        "summary": "Audio editor and recorder",
        "publisher": "Audacity Team",
        "icon": "audacity",
        "desc": "Audacity is a multi-track audio editor and recorder for Linux, Windows and macOS.",
        "version": "3.7.1",
        "source": "snap"
    },
]


DEFAULT_HERO_SLIDES = [
    {
        "id": "blender",
        "source": "pacman",
        "tag": "FEATURED 3D STUDIO",
        "title": "Blender 3D Studio",
        "sub": "Unleash next-gen modeling, animation, physics simulation, and real-time photorealistic rendering",
        "bg": "radial-gradient(circle at 80% 50%, rgba(235, 119, 0, 0.30) 0%, rgba(235, 119, 0, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(235, 119, 0, 0.22) 0%, rgba(20, 24, 32, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(235, 119, 0, 0.38)",
        "icon": "blender",
        "color": "#eb7700",
    },
    {
        "id": "code",
        "source": "pacman",
        "tag": "DEVELOPER SPOTLIGHT",
        "title": "Visual Studio Code",
        "sub": "The world's most versatile code editor with intelligent autocompletion and rich language tooling",
        "bg": "radial-gradient(circle at 80% 50%, rgba(0, 122, 204, 0.30) 0%, rgba(0, 122, 204, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(0, 122, 204, 0.25) 0%, rgba(18, 24, 34, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(0, 122, 204, 0.38)",
        "icon": "code",
        "color": "#007acc",
    },
    {
        "id": "steam",
        "source": "pacman",
        "tag": "PRO GAMING PLATFORM",
        "title": "Steam on Linux",
        "sub": "Play thousands of native and Windows titles with seamless Proton performance and community integration",
        "bg": "radial-gradient(circle at 80% 50%, rgba(102, 192, 244, 0.30) 0%, rgba(102, 192, 244, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(23, 29, 37, 0.6) 0%, rgba(102, 192, 244, 0.22) 45%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(102, 192, 244, 0.38)",
        "icon": "steam",
        "color": "#66c0f4",
    },
    {
        "id": "obs-studio",
        "source": "pacman",
        "tag": "BROADCAST ESSENTIAL",
        "title": "OBS Studio",
        "sub": "Stream high-definition gameplay and record pristine multi-source desktop broadcasts",
        "bg": "radial-gradient(circle at 80% 50%, rgba(163, 113, 247, 0.30) 0%, rgba(163, 113, 247, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(48, 54, 61, 0.4) 0%, rgba(163, 113, 247, 0.24) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(163, 113, 247, 0.38)",
        "icon": "obs-studio",
        "color": "#a371f7",
    },
    {
        "id": "proton-vpn-gtk-app",
        "source": "pacman",
        "tag": "SECURITY & PRIVACY",
        "title": "Proton VPN",
        "sub": "High-speed encrypted WireGuard VPN tunnel with strict zero-logging and built-in Kill Switch",
        "bg": "radial-gradient(circle at 80% 50%, rgba(109, 74, 255, 0.30) 0%, rgba(109, 74, 255, 0.05) 50%, transparent 75%), linear-gradient(135deg, rgba(109, 74, 255, 0.25) 0%, rgba(20, 20, 35, 0.95) 55%, rgba(13, 17, 23, 0.98) 100%)",
        "border": "rgba(109, 74, 255, 0.38)",
        "icon": "proton-vpn-gtk-app",
        "color": "#6d4aff",
    },
]


class MacHeroCarousel(Gtk.Overlay):
    """
    Authentic macOS App Store & GNOME Software Animated Hero Carousel / Slideshow.
    Features:
    - Dynamic featured application spotlight via PackageManager
    - Multi-stop atmospheric gradients with rich radial glow
    - 160px semi-transparent watermarked background graphic
    - Strictly dead-centered 88x88 squircle icon container
    - Floating frosted glass navigation arrows with generous margins
    - Interactive pagination pills (elongated active pill, jumping on click)
    - Dynamic action button (OPEN if installed, GET otherwise)
    - Full-card click opening package inspector
    - 5-second auto-advance slideshow with pause on mouse hover
    """
    def __init__(self, aura_window):
        super().__init__()
        self.aura_window = aura_window
        self.add_css_class("mac-hero-carousel")
        self.set_hexpand(True)
        self.set_size_request(-1, 195)
        self._last_open_time = 0.0

        # Dynamic slides support via PackageManager
        featured = None
        if hasattr(self.aura_window, "pm") and self.aura_window.pm:
            try:
                if hasattr(self.aura_window.pm, "get_dynamic_featured_apps"):
                    featured = self.aura_window.pm.get_dynamic_featured_apps(count=5, refresh=True)
            except Exception as e:
                print(f"[Aura] Error loading dynamic featured apps: {e}", file=sys.stderr)

        if featured and isinstance(featured, list) and len(featured) > 0:
            self.slides = featured[:5]
        else:
            self.slides = list(DEFAULT_HERO_SLIDES)

        self.current_idx = 0
        self._is_hovered = False
        self._timer_id = None

        # Main Carousel Stack with smooth crossfade
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(220)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(False)
        self.stack.set_size_request(-1, 195)
        self.set_child(self.stack)

        # Bottom Indicator Pills Box
        self.dots_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.dots_box.set_valign(Gtk.Align.END)
        self.dots_box.set_halign(Gtk.Align.CENTER)
        self.dots_box.set_margin_bottom(12)
        self.dots: List[Gtk.Button] = []

        self._rebuild_all_slides()

        # Floating Left Navigation Arrow (34x34 Frosted Circle with 16px margin)
        self.left_btn = Gtk.Button()
        self.left_btn.add_css_class("mac-hero-nav-btn")
        self.left_btn.set_valign(Gtk.Align.CENTER)
        self.left_btn.set_halign(Gtk.Align.START)
        self.left_btn.set_margin_start(16)
        self.left_btn.set_size_request(34, 34)
        left_icon = Gtk.Image.new_from_icon_name("go-previous-symbolic")
        left_icon.set_pixel_size(14)
        self.left_btn.set_child(left_icon)
        self.left_btn.set_tooltip_text("Previous slide")
        self.left_btn.set_cursor(Gdk.Cursor.new_from_name("pointer", None))
        self.left_btn.connect("clicked", lambda b: self._prev_slide())
        self.add_overlay(self.left_btn)

        # Floating Right Navigation Arrow (34x34 Frosted Circle with 16px margin)
        self.right_btn = Gtk.Button()
        self.right_btn.add_css_class("mac-hero-nav-btn")
        self.right_btn.set_valign(Gtk.Align.CENTER)
        self.right_btn.set_halign(Gtk.Align.END)
        self.right_btn.set_margin_end(16)
        self.right_btn.set_size_request(34, 34)
        right_icon = Gtk.Image.new_from_icon_name("go-next-symbolic")
        right_icon.set_pixel_size(14)
        self.right_btn.set_child(right_icon)
        self.right_btn.set_tooltip_text("Next slide")
        self.right_btn.set_cursor(Gdk.Cursor.new_from_name("pointer", None))
        self.right_btn.connect("clicked", lambda b: self._next_slide())
        self.add_overlay(self.right_btn)

        self.add_overlay(self.dots_box)

        # Pause on hover controller
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self._on_enter)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

        # Auto-advance slideshow: GLib.timeout_add(5000, self._auto_advance)
        self._timer_id = GLib.timeout_add(5000, self._auto_advance)
        self.connect("destroy", self._on_destroy)

    def refresh_slides(self):
        """Fetch fresh spotlight applications and rebuild carousel slides."""
        featured = None
        if hasattr(self.aura_window, "pm") and self.aura_window.pm:
            try:
                if hasattr(self.aura_window.pm, "get_dynamic_featured_apps"):
                    featured = self.aura_window.pm.get_dynamic_featured_apps(count=5, refresh=True)
            except Exception as e:
                print(f"[Aura] Error loading dynamic featured apps: {e}", file=sys.stderr)

        if featured and isinstance(featured, list) and len(featured) > 0:
            self.slides = featured[:5]
        else:
            self.slides = list(DEFAULT_HERO_SLIDES)

        self._rebuild_all_slides()

    def _rebuild_all_slides(self):
        """Clear and rebuild stack slides and pagination pills."""
        while True:
            child = self.stack.get_first_child()
            if not child:
                break
            self.stack.remove(child)

        while True:
            child = self.dots_box.get_first_child()
            if not child:
                break
            self.dots_box.remove(child)
        self.dots.clear()

        self.current_idx = 0

        for idx, slide in enumerate(self.slides):
            # Dynamic slide style injection if slide provides custom bg / border
            bg = slide.get("bg")
            border = slide.get("border")
            if bg or border:
                css_rules = f".mac-hero-slide-{idx} {{"
                if bg:
                    css_rules += f" background: {bg};"
                if border:
                    css_rules += f" border: 1px solid {border};"
                css_rules += " }"
                accent = slide.get("accent_color") or slide.get("color")
                if accent:
                    css_rules += f" .mac-hero-slide-{idx} .mac-hero-tag {{ color: {accent}; }}"
                prov = Gtk.CssProvider()
                prov.load_from_data(css_rules.encode("utf-8"))
                display = Gdk.Display.get_default()
                if display:
                    Gtk.StyleContext.add_provider_for_display(display, prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

            slide_box = self._build_slide(idx, slide)
            self.stack.add_named(slide_box, f"slide_{idx}")

            dot = Gtk.Button()
            dot.add_css_class("mac-hero-dot-active" if idx == 0 else "mac-hero-dot")
            dot.set_cursor(Gdk.Cursor.new_from_name("pointer", None))
            dot.connect("clicked", lambda b, target_idx=idx: self._jump_to_slide(target_idx))
            self.dots.append(dot)
            self.dots_box.append(dot)

        if self.slides:
            self.stack.set_visible_child_name("slide_0")

    def _open_detail(self, sid: str, ssrc: str):
        now = time.time()
        if now - self._last_open_time < 0.35:
            return
        self._last_open_time = now
        self.aura_window._open_package_detail(sid, ssrc)

    def _build_slide(self, idx: int, slide: Dict[str, Any]) -> Gtk.Widget:
        slide_overlay = Gtk.Overlay()
        slide_overlay.add_css_class("mac-hero-slide")
        slide_overlay.add_css_class(f"mac-hero-slide-{idx}")
        slide_overlay.set_hexpand(True)
        slide_overlay.set_valign(Gtk.Align.FILL)
        slide_overlay.set_size_request(-1, 195)
        slide_overlay.set_overflow(Gtk.Overflow.HIDDEN)

        icon_target = resolve_icon_name(slide.get("icon", slide["id"]), slide.get("sub", ""))

        # 1. Subtle, Semi-Transparent Watermarked Backdrop Graphic (160px)
        watermark_layer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        watermark_layer.set_hexpand(True)
        watermark_layer.set_vexpand(True)
        watermark_layer.set_can_target(False)

        watermark_img = create_scaled_image(icon_target, size=160)
        watermark_img.add_css_class("mac-hero-watermark")
        watermark_img.set_opacity(0.12)
        watermark_img.set_halign(Gtk.Align.END)
        watermark_img.set_valign(Gtk.Align.CENTER)
        watermark_img.set_hexpand(True)
        watermark_img.set_margin_end(48)
        watermark_img.set_can_target(False)
        watermark_layer.append(watermark_img)

        slide_overlay.set_child(watermark_layer)

        # 2. Foreground Content Container
        content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        content_box.set_hexpand(True)
        content_box.set_vexpand(True)
        content_box.set_valign(Gtk.Align.FILL)

        # Left Column: Tag chip, Title, Subtitle, Action button
        left_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        left_col.set_hexpand(True)
        left_col.set_valign(Gtk.Align.CENTER)
        left_col.set_halign(Gtk.Align.START)
        left_col.set_margin_start(64)

        tag_lbl = Gtk.Label(label=slide.get("tag", "FEATURED"))
        tag_lbl.add_css_class("mac-hero-tag")
        tag_lbl.set_halign(Gtk.Align.START)
        left_col.append(tag_lbl)

        title_lbl = Gtk.Label(label=slide.get("title", slide["id"]))
        title_lbl.add_css_class("mac-hero-title")
        title_lbl.set_halign(Gtk.Align.START)
        title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        left_col.append(title_lbl)

        sub_lbl = Gtk.Label(label=slide.get("sub", ""))
        sub_lbl.add_css_class("mac-hero-sub")
        sub_lbl.set_halign(Gtk.Align.START)
        sub_lbl.set_wrap(True)
        sub_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        sub_lbl.set_lines(2)
        sub_lbl.set_max_width_chars(44)
        sub_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        left_col.append(sub_lbl)

        # Dynamic Action Button (UPDATING... / INSTALLING... / QUEUED / UPDATE / OPEN / GET)
        sid = slide["id"]
        ssrc = slide.get("source", "pacman")
        pm = getattr(self.aura_window, "pm", None)

        is_installed = False
        if pm:
            try:
                is_installed = self.aura_window._is_pkg_installed_unified(sid, ssrc)
            except Exception:
                pass

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        btn_box.set_margin_top(8)

        sid_low = sid.strip().lower()
        res_name = getattr(pm, "resolve_installed_pkg_name", lambda x: x)(sid_low).lower() if pm else sid_low
        is_updating = bool(pm and hasattr(pm, "is_pkg_updating") and pm.is_pkg_updating(sid))
        is_installing = bool(pm and hasattr(pm, "is_pkg_installing") and pm.is_pkg_installing(sid))
        is_queued = bool(pm and hasattr(pm, "is_pkg_queued") and pm.is_pkg_queued(sid))

        is_upgradable = False
        if pm:
            upg_list = list(getattr(pm, "upgradable_list", []) or [])
            is_upgradable = any(
                (u.get("name") or "").strip().lower() in (sid_low, res_name, f"{sid_low}-bin")
                for u in upg_list
            )

        if is_updating:
            action_btn = Gtk.Button(label="UPDATING...")
            action_btn.add_css_class("mac-btn-get")
            action_btn.set_sensitive(False)
        elif is_installing:
            action_btn = Gtk.Button(label="INSTALLING...")
            action_btn.add_css_class("mac-btn-get")
            action_btn.set_sensitive(False)
        elif is_queued:
            action_btn = Gtk.Button(label="QUEUED")
            action_btn.add_css_class("mac-btn-queued")
            action_btn.set_sensitive(False)
        elif is_upgradable:
            action_btn = Gtk.Button(label="UPDATE")
            action_btn.add_css_class("mac-btn-update")
            action_btn.set_sensitive(True)
        else:
            action_btn = Gtk.Button(label="OPEN" if is_installed else "GET")
            action_btn.add_css_class("mac-btn-open" if is_installed else "mac-btn-get")
            action_btn.set_sensitive(True)

        action_btn.set_size_request(80, 30)
        action_btn.set_valign(Gtk.Align.CENTER)
        action_btn.set_cursor(Gdk.Cursor.new_from_name("pointer", None))

        def _on_hero_action_clicked(b, s_id=sid, s_src=ssrc):
            if pm and hasattr(pm, "is_pkg_updating") and pm.is_pkg_updating(s_id):
                return
            if pm and hasattr(pm, "is_pkg_installing") and pm.is_pkg_installing(s_id):
                return
            if pm and hasattr(pm, "is_pkg_queued") and pm.is_pkg_queued(s_id):
                return
            nl = s_id.strip().lower()
            rn = getattr(pm, "resolve_installed_pkg_name", lambda x: x)(nl).lower() if pm else nl
            up_l = list(getattr(pm, "upgradable_list", []) or [])
            upg = any(
                (u.get("name") or "").strip().lower() in (nl, rn, f"{nl}-bin")
                for u in up_l
            )
            if upg:
                self.aura_window._update_single_package(s_id, s_src)
                return
            if self.aura_window._is_pkg_installed_unified(s_id, s_src):
                if pm and pm.detect_desktop_entry(s_id):
                    self.aura_window._open_or_launch(s_id, s_src)
                else:
                    self._open_detail(s_id, s_src)
            else:
                self.aura_window._install_from_card(s_id, s_src, action_btn)

        action_btn.connect("clicked", _on_hero_action_clicked)
        btn_box.append(action_btn)
        left_col.append(btn_box)

        slide_overlay._action_btn = action_btn
        slide_overlay._pkg_name = sid
        slide_overlay._source = ssrc
        if hasattr(self.aura_window, "_registered_cards"):
            self.aura_window._registered_cards.setdefault(sid_low, []).append(slide_overlay)
            if res_name != sid_low:
                self.aura_window._registered_cards.setdefault(res_name, []).append(slide_overlay)

        content_box.append(left_col)

        # Right Column: Dead-Centered Squircle Icon Container
        right_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right_col.set_valign(Gtk.Align.CENTER)
        right_col.set_halign(Gtk.Align.END)
        right_col.set_margin_end(64)

        icon_box = Gtk.Box()
        icon_box.add_css_class("mac-hero-squircle")
        icon_box.set_homogeneous(True)
        icon_box.set_size_request(88, 88)
        icon_box.set_valign(Gtk.Align.CENTER)
        icon_box.set_halign(Gtk.Align.CENTER)
        icon_box.set_hexpand(False)
        icon_box.set_vexpand(False)

        icon_img = create_scaled_image(icon_target, size=76)
        icon_img.set_halign(Gtk.Align.CENTER)
        icon_img.set_valign(Gtk.Align.CENTER)
        icon_box.append(icon_img)

        right_col.append(icon_box)
        content_box.append(right_col)

        slide_overlay.add_overlay(content_box)

        # Clicking anywhere on the slide opens package detail (ignoring clicks on action_btn)
        gesture = Gtk.GestureClick()
        def _on_slide_click(g, n, x, y, sid=slide["id"], ssrc=slide.get("source", "pacman")):
            picked = slide_overlay.pick(x, y, Gtk.PickFlags.INSENSITIVE)
            if picked is not None and (picked == action_btn or action_btn.is_ancestor(picked)):
                return
            alloc = action_btn.compute_bounds(slide_overlay)
            if alloc[0]:
                rect = alloc[1]
                rx, ry = rect.get_x(), rect.get_y()
                rw, rh = rect.get_width(), rect.get_height()
                if rx <= x <= rx + rw and ry <= y <= ry + rh:
                    return
            self._open_detail(sid, ssrc)
        gesture.connect("released", _on_slide_click)
        slide_overlay.add_controller(gesture)
        slide_overlay.set_cursor(Gdk.Cursor.new_from_name("pointer", None))

        return slide_overlay

    def _jump_to_slide(self, index: int):
        if not self.slides or index < 0 or index >= len(self.slides) or index == self.current_idx:
            return
        trans = Gtk.StackTransitionType.SLIDE_LEFT if index > self.current_idx else Gtk.StackTransitionType.SLIDE_RIGHT
        self.stack.set_transition_type(trans)
        self.stack.set_transition_duration(320)
        self.current_idx = index
        self.stack.set_visible_child_name(f"slide_{index}")
        self._update_dots()

    def _next_slide(self):
        if not self.slides:
            return
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        self.stack.set_transition_duration(320)
        new_idx = (self.current_idx + 1) % len(self.slides)
        self.current_idx = new_idx
        self.stack.set_visible_child_name(f"slide_{new_idx}")
        self._update_dots()

    def _prev_slide(self):
        if not self.slides:
            return
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_RIGHT)
        self.stack.set_transition_duration(320)
        new_idx = (self.current_idx - 1) % len(self.slides)
        self.current_idx = new_idx
        self.stack.set_visible_child_name(f"slide_{new_idx}")
        self._update_dots()

    def _update_dots(self):
        for i, dot in enumerate(self.dots):
            if i == self.current_idx:
                dot.remove_css_class("mac-hero-dot")
                dot.add_css_class("mac-hero-dot-active")
            else:
                dot.remove_css_class("mac-hero-dot-active")
                dot.add_css_class("mac-hero-dot")

    def _on_enter(self, controller, x, y):
        self._is_hovered = True

    def _on_leave(self, controller):
        self._is_hovered = False

    def _auto_advance(self) -> bool:
        if not self._is_hovered and hasattr(self.aura_window, "main_stack"):
            if self.aura_window.main_stack.get_visible_child_name() == "discover":
                sw = getattr(self.aura_window, "discover_page", None)
                vadj = sw.get_vadjustment() if sw else None
                if not vadj or vadj.get_value() < 220:
                    self._next_slide()
        return True

    def _on_destroy(self, *args):
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = None


class AuraWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, package_manager: PackageManager):
        super().__init__(application=app, title="Aura Store")
        self.pm = package_manager
        self.set_default_size(1180, 760)
        self.set_size_request(720, 500)

        # Register custom icons search paths (e.g. docker-symbolic, aura-icon)
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        theme.add_search_path(str(Path.home() / ".local/share/icons/hicolor/scalable/apps"))
        theme.add_search_path(str(Path(__file__).resolve().parent / "data/icons"))
        theme.add_search_path(str(Path(__file__).resolve().parent))
        theme.add_search_path(str(Path.home() / ".local" / "share" / "aura"))
        Gtk.Window.set_default_icon_name("aura-icon")
        self.set_icon_name("aura-icon")

        self._setup_css()

        # State tracking
        self.current_filter = "native"
        self.active_request_id = 0
        self._detail_request_id = 0
        self._saved_scroll_positions: Dict[str, float] = {}
        self._cache_row_widgets: Dict[str, Gtk.Box] = {}
        self._search_timer_id: Optional[int] = None
        self._search_sync_lock: bool = False
        self._previous_page = "discover"
        self._dep_rows: List[Adw.ActionRow] = []
        self._current_detail: Dict[str, Any] = {}
        self._cached_installed_apps_flow: Optional[Gtk.FlowBox] = None
        self._registered_grids: List[Gtk.FlowBox] = []
        self._active_cols: int = 2
        self._snap_curated_populated: bool = False
        self._snap_curated_dirty: bool = False

        # Updates View Button and Card Registry for realtime status tracking
        self._updates_buttons: Dict[str, Gtk.Button] = {}
        self._updates_cards: Dict[str, Gtk.Box] = {}
        self._registered_cards: Dict[str, List[Gtk.Box]] = {}

        # Smooth Progress and Animation State
        self._progress_anim_id: Optional[int] = None
        self._current_progress: float = 0.0
        self._target_progress: float = 0.0
        self._progress_action: str = ""
        self._progress_pkg_name: str = ""
        self._progress_display_name: str = ""
        self._progress_source: str = "pacman"
        self._progress_status_text: str = ""
        self._progress_target_view: str = "detail"
        self._progress_auto_hide_id: Optional[int] = None

        # Root Toast Overlay
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        # Main Horizontal Layout: Left Sidebar + Right Content View
        self.main_layout = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.toast_overlay.set_child(self.main_layout)

        # Header Bar (Back button, Refresh, Status)
        self.header_bar = self._build_headerbar()

        # Content Main Page Stack - Non-homogeneous with overflow protection so pages never clip headerbar
        self.main_stack = Gtk.Stack()
        self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.main_stack.set_transition_duration(220)
        self.main_stack.set_hexpand(True)
        self.main_stack.set_vexpand(True)
        self.main_stack.set_hhomogeneous(False)
        self.main_stack.set_vhomogeneous(False)
        self.main_stack.set_interpolate_size(False)
        self.main_stack.set_overflow(Gtk.Overflow.HIDDEN)

        # Page 1: Discover (Top Showcase Carousel + Curated 2-Column Sections)
        self.discover_page = self._build_discover_page()
        self.main_stack.add_named(self.discover_page, "discover")

        # Page 2: Browse & Search
        self.browse_page = self._build_browse_page()
        self.main_stack.add_named(self.browse_page, "browse")

        # Page 3: Updates
        self.updates_page = self._build_updates_page()
        self.main_stack.add_named(self.updates_page, "updates")

        # Page 4: Installed (Instant 0ms pre-cached)
        self.installed_page = self._build_installed_page()
        self.main_stack.add_named(self.installed_page, "installed")

        # Page 5: Full Product Detail Inspector
        self.detail_page = self._build_detail_page()
        self.main_stack.add_named(self.detail_page, "detail")

        # Page 6: Curated Category Explorer
        self.category_page = self._build_category_page()
        self.main_stack.add_named(self.category_page, "category")

        # Page 7: Docker Applications (Isolated OCI Sandbox + Host Desktop Shortcuts)
        self.containers_page = self._build_containers_page()
        self.main_stack.add_named(self.containers_page, "docker")

        # Page 8: Snap Store (Universal Linux packages with isolated sandbox)
        self.snap_page = self._build_snap_page()
        self.main_stack.add_named(self.snap_page, "snap")

        # Page 9: Storage & System Caches
        self.storage_page = self._build_storage_page()
        self.main_stack.add_named(self.storage_page, "storage")

        # Page 10: .deb Package Installer & Bridge
        self.deb_page = self._build_deb_page()
        self.main_stack.add_named(self.deb_page, "deb")

        # Page 11: Hyprland Hub & Compositor Tools
        self.hyprland_page = self._build_hyprland_page()
        self.main_stack.add_named(self.hyprland_page, "hyprland")

        # 1. Left Sidebar
        self.sidebar = self._build_sidebar()
        self.main_layout.append(self.sidebar)

        # 2. Right Content Column
        content_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content_col.set_hexpand(True)
        content_col.set_vexpand(True)
        content_col.set_overflow(Gtk.Overflow.HIDDEN)
        content_col.append(self.header_bar)
        content_col.append(self.main_stack)
        self.main_layout.append(content_col)

        self.main_stack.set_visible_child_name("discover")

        # Responsive Breakpoints for multi-column grids (calibrated with 232px sidebar):
        # Fullscreen / Ultra-wide (>= 1580px): 4 columns
        # Wide (1200px - 1579px): 3 columns
        # Standard Window (680px - 1199px): 2 columns (enforces 2 apps per row in windowed mode)
        # Ultra-compact (< 680px): 1 column
        bp_ultrawide = Adw.Breakpoint.new(Adw.breakpoint_condition_parse('min-width: 1580px'))
        bp_ultrawide.connect('apply', lambda b: self._set_grid_cols(4))
        bp_ultrawide.connect('unapply', lambda b: self._sync_responsive_cols())
        self.add_breakpoint(bp_ultrawide)

        bp_wide = Adw.Breakpoint.new(Adw.breakpoint_condition_parse('min-width: 1200px and max-width: 1579px'))
        bp_wide.connect('apply', lambda b: self._set_grid_cols(3))
        bp_wide.connect('unapply', lambda b: self._sync_responsive_cols())
        self.add_breakpoint(bp_wide)

        bp_standard = Adw.Breakpoint.new(Adw.breakpoint_condition_parse('min-width: 680px and max-width: 1199px'))
        bp_standard.connect('apply', lambda b: self._set_grid_cols(2))
        bp_standard.connect('unapply', lambda b: self._sync_responsive_cols())
        self.add_breakpoint(bp_standard)

        bp_compact = Adw.Breakpoint.new(Adw.breakpoint_condition_parse('max-width: 679px'))
        bp_compact.connect('apply', lambda b: self._set_grid_cols(1))
        bp_compact.connect('unapply', lambda b: self._sync_responsive_cols())
        self.add_breakpoint(bp_compact)

        self.connect("notify::fullscreened", lambda *a: self._sync_responsive_cols())
        self.connect("close-request", self._on_close_request)

        # Global Type-to-Search Key Controller
        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_ctrl.connect("key-pressed", self._on_window_key_pressed)
        self.add_controller(key_ctrl)

        # Global Drag-and-Drop Controller for .deb files
        try:
            drop_target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
            drop_target.connect("drop", self._on_window_file_dropped)
            self.add_controller(drop_target)
        except Exception:
            pass

        # Initial Background Load of package database
        self._load_data_async()

    def _sync_responsive_cols(self):
        w = self.get_width() if hasattr(self, "get_width") else 0
        content_w = max(300, (w - 232)) if w > 0 else 800
        if self.is_fullscreen() or content_w >= 1340:
            self._set_grid_cols(4)
        elif content_w >= 940:
            self._set_grid_cols(3)
        elif content_w >= 440:
            self._set_grid_cols(2)
        else:
            self._set_grid_cols(1)

    def _set_grid_cols(self, cols: int):
        self._active_cols = cols
        for flow in getattr(self, "_registered_grids", []):
            min_c = getattr(flow, "_aura_min_cols", 1)
            max_c = getattr(flow, "_aura_max_cols", 4)
            target = max(min_c, min(cols, max_c))
            eff_min = 1 if target <= 1 else min(target, max(min_c, 2))
            flow.set_min_children_per_line(eff_min)
            flow.set_max_children_per_line(target)

    def _get_target_cols(self) -> int:
        if self.is_fullscreen():
            return 4
        w = self.get_width() if hasattr(self, "get_width") else 0
        content_w = max(300, (w - 232)) if w > 0 else 800
        if content_w >= 1340:
            return 4
        elif content_w >= 940:
            return 3
        elif content_w >= 440:
            return 2
        elif 0 < content_w < 440:
            return 1
        return getattr(self, "_active_cols", 2)

    def _sync_all_grid_columns(self):
        self._sync_responsive_cols()

    def _on_close_request(self, window) -> bool:
        """Intercept window close: if transactions or tasks are active/queued, hide window, finish in background, then cleanly exit."""
        if hasattr(self.pm, "has_active_tasks") and self.pm.has_active_tasks():
            try:
                active_tx = self.pm.get_active_transaction()
                pkg = (active_tx.get("pkg_name") or "package") if isinstance(active_tx, dict) else "package"
                subprocess.Popen(["notify-send", "-a", "Aura", "-i", "aura-icon", "Aura Store", f"Finishing package installation for {pkg} in background..."])
            except Exception:
                pass

            # Hide the window immediately so user feels the window closed
            self.set_visible(False)

            def _poll_exit():
                if self.pm.has_active_tasks():
                    return True  # Keep polling
                try:
                    subprocess.Popen(["notify-send", "-a", "Aura", "-i", "aura-icon", "Aura Store", "All background package tasks completed."])
                except Exception:
                    pass
                app = self.get_application()
                if app:
                    app.quit()
                return False

            GLib.timeout_add(1000, _poll_exit)
            return True  # Stop default close from destroying window immediately
        return False

    def _is_pkg_installed_unified(self, name: str, source: str = "pacman") -> bool:
        """Unified installed check across Arch repos/AUR, Snap, and Docker containers."""
        if not name:
            return False
        if source == "snap":
            return bool(hasattr(self.pm, "snap_mgr") and self.pm.snap_mgr.is_snap_installed(name))
        elif source in ("docker", "container"):
            return bool(hasattr(self.pm, "container_mgr") and self.pm.container_mgr.is_app_installed(name))
        elif source == "deb":
            if str(name).lower().endswith(".deb") and hasattr(self.pm, "deb_mgr"):
                try:
                    info = self.pm.deb_mgr.inspect_deb(name)
                    return bool(self.pm.is_installed(info["name"]))
                except Exception:
                    return False
            return bool(hasattr(self.pm, "is_installed") and self.pm.is_installed(name))
        else:
            return bool(hasattr(self.pm, "is_installed") and self.pm.is_installed(name))

    def _sync_card_widget_state(self, card: Any):
        """Helper to sync an individual card or slide widget's action button state."""
        if not card:
            return
        btn = getattr(card, "_action_btn", None)
        name = getattr(card, "_pkg_name", None)
        if not btn or not name:
            return
        source = getattr(card, "_source", "pacman")

        # 1. Active transaction: updating
        if hasattr(self.pm, "is_pkg_updating") and self.pm.is_pkg_updating(name) is True:
            btn.set_label("UPDATING...")
            btn.remove_css_class("mac-btn-queued")
            btn.remove_css_class("mac-btn-open")
            btn.remove_css_class("mac-btn-installed")
            btn.remove_css_class("mac-btn-update")
            if not btn.has_css_class("mac-btn-get"):
                btn.add_css_class("mac-btn-get")
            btn.set_sensitive(False)
            return

        # 2. Active transaction: installing
        if hasattr(self.pm, "is_pkg_installing") and self.pm.is_pkg_installing(name) is True:
            btn.set_label("INSTALLING...")
            btn.remove_css_class("mac-btn-queued")
            btn.remove_css_class("mac-btn-open")
            btn.remove_css_class("mac-btn-installed")
            btn.remove_css_class("mac-btn-update")
            if not btn.has_css_class("mac-btn-get"):
                btn.add_css_class("mac-btn-get")
            btn.set_sensitive(False)
            return

        # 3. Queued in transaction queue or batch update
        if hasattr(self.pm, "is_pkg_queued") and self.pm.is_pkg_queued(name) is True:
            btn.set_label("QUEUED")
            btn.remove_css_class("mac-btn-get")
            btn.remove_css_class("mac-btn-open")
            btn.remove_css_class("mac-btn-installed")
            btn.remove_css_class("mac-btn-update")
            if not btn.has_css_class("mac-btn-queued"):
                btn.add_css_class("mac-btn-queued")
            btn.set_sensitive(False)
            return

        # 4. Check upgradable status with alias resolution (lock-free read on UI thread)
        btn.remove_css_class("mac-btn-queued")
        name_low = name.strip().lower()
        res_name = getattr(self.pm, "resolve_installed_pkg_name", lambda x: x)(name_low).lower()
        upg_list = list(getattr(self.pm, "upgradable_list", []) or [])
        is_upgradable = any(
            (u.get("name") or "").strip().lower() in (name_low, res_name, f"{name_low}-bin")
            for u in upg_list
        )

        if is_upgradable:
            btn.set_label("UPDATE")
            btn.remove_css_class("mac-btn-get")
            btn.remove_css_class("mac-btn-installed")
            btn.remove_css_class("mac-btn-open")
            if not btn.has_css_class("mac-btn-update"):
                btn.add_css_class("mac-btn-update")
            btn.set_sensitive(True)
        elif self._is_pkg_installed_unified(name, source):
            has_desktop = bool(self.pm.detect_desktop_entry(name))
            btn.set_label("OPEN" if has_desktop else "INSTALLED")
            btn.remove_css_class("mac-btn-get")
            btn.remove_css_class("mac-btn-update")
            btn.remove_css_class("mac-btn-installed" if has_desktop else "mac-btn-open")
            btn.add_css_class("mac-btn-open" if has_desktop else "mac-btn-installed")
            btn.set_sensitive(True)
        else:
            btn.set_label("GET")
            btn.remove_css_class("mac-btn-open")
            btn.remove_css_class("mac-btn-installed")
            btn.remove_css_class("mac-btn-update")
            if not btn.has_css_class("mac-btn-get"):
                btn.add_css_class("mac-btn-get")
            btn.set_sensitive(True)

    def _animate_card_entrance(self, card: Gtk.Widget, index: int = 0):
        """Zero-stutter card readiness hook (hardware-accelerated via parent Gtk.Stack transition)."""
        return

    def _sync_all_cards(self):
        """Dynamically refresh action button states across all registered grids and cards when background tasks update."""
        self._snap_curated_dirty = True
        synced_cards = set()

        # 1. Sync through registered FlowBox grids
        for flow in getattr(self, "_registered_grids", []):
            child = flow.get_first_child()
            while child:
                card = child.get_child() if hasattr(child, "get_child") else None
                if card and hasattr(card, "_pkg_name") and hasattr(card, "_action_btn"):
                    try:
                        self._sync_card_widget_state(card)
                        synced_cards.add(id(card))
                    except Exception:
                        pass
                child = child.get_next_sibling()

        # 2. Sync through direct card registry (for hero carousel, custom views, etc.)
        if hasattr(self, "_registered_cards"):
            for pkg_k, card_list in list(self._registered_cards.items()):
                valid_cards = []
                for card in card_list:
                    try:
                        if id(card) not in synced_cards:
                            self._sync_card_widget_state(card)
                            synced_cards.add(id(card))
                        valid_cards.append(card)
                    except Exception:
                        pass
                self._registered_cards[pkg_k] = valid_cards

        # 3. Synchronize detail page if open
        self._sync_detail_page()

    def _sync_detail_page(self, target_name: Optional[str] = None):
        """
        Dynamically synchronize the package detail page UI with live package status.
        Ensures action buttons ('OPEN', 'INSTALLED', 'UNINSTALL', 'GET', 'INSTALLING...', 'QUEUED')
        and progress bar reflect real-time backend state without full page reload.
        """
        if not hasattr(self, "main_stack") or self.main_stack.get_visible_child_name() != "detail":
            return
        if not getattr(self, "_current_detail", None):
            return

        name = self._current_detail.get("name", "")
        if not name:
            return
        if target_name and target_name.lower().strip() != name.lower().strip():
            return

        source = self._current_detail.get("source", "pacman")

        # 1. Dynamic live status check
        is_updating = bool(hasattr(self.pm, "is_pkg_updating") and self.pm.is_pkg_updating(name) is True)
        is_installing = (hasattr(self.pm, "is_pkg_installing") and self.pm.is_pkg_installing(name)) or is_updating
        is_queued = hasattr(self.pm, "is_pkg_queued") and self.pm.is_pkg_queued(name)

        is_installed = self._is_pkg_installed_unified(name, source)
        self._current_detail["is_installed"] = is_installed
        desktop_entry = self.pm.detect_desktop_entry(name) if is_installed else None
        self._current_detail["desktop_entry"] = desktop_entry

        # Check upgradable status with alias resolution
        name_low = name.strip().lower()
        res_name = getattr(self.pm, "resolve_installed_pkg_name", lambda x: x)(name_low).lower()
        up_item = None
        if hasattr(self.pm, "upgradable_list") and self.pm.upgradable_list:
            up_item = next(
                (u for u in self.pm.upgradable_list if (u.get("name") or "").strip().lower() in (name_low, res_name, f"{name_low}-bin")),
                None
            )

        # 2. Update Quick Stats version and size if installed
        if is_installed:
            inst_ver = self.pm.installed_versions.get(name, "")
            if not inst_ver:
                clean = re.sub(r'-(bin|git|hg|svn|pure|gtk-app|qt-app|gui|cli|daemon|desktop|launcher)$', '', name.lower())
                inst_ver = self.pm.installed_versions.get(clean, "")
            if inst_ver and hasattr(self, "stat_val_version"):
                self.stat_val_version.set_text(f"v{inst_ver}")
                self._current_detail["installed_version"] = inst_ver
                self._current_detail["version"] = inst_ver

        # 3. Synchronize Action Buttons and Progress Container
        if is_installing:
            self.progress_container.set_visible(True)
            prog, msg = 0.0, ("Updating..." if (up_item or is_updating) else "Installing...")
            if hasattr(self.pm, "get_active_progress"):
                try:
                    res_p = self.pm.get_active_progress(name)
                    if isinstance(res_p, (tuple, list)) and len(res_p) == 2:
                        prog, msg = res_p
                except Exception:
                    pass
            self.progress_bar.set_fraction(prog)
            self.progress_status_label.set_text(msg or ("Updating..." if (up_item or is_updating) else "Installing..."))
            self.progress_percent_label.set_text(f"{int(prog * 100)}%")

            if hasattr(self, "btn_banner_update"):
                self.btn_banner_update.set_label("UPDATING...")
                self.btn_banner_update.set_sensitive(False)

            self.btn_detail_launch.set_visible(False)
            if hasattr(self, "btn_detail_update"):
                self.btn_detail_update.set_visible(False)
            self.btn_detail_install.set_label("UPDATING..." if (up_item or is_updating) else "INSTALLING...")
            self.btn_detail_install.set_sensitive(False)
            self.btn_detail_install.set_css_classes(["mac-btn-primary-large"])
            self.btn_detail_install.set_size_request(108, 36)
            self.btn_detail_install.set_visible(True)
            self.btn_detail_remove.set_visible(False)

        elif is_queued:
            self.progress_container.set_visible(False)
            if hasattr(self, "btn_banner_update"):
                self.btn_banner_update.set_label("QUEUED")
                self.btn_banner_update.set_sensitive(False)
            self.btn_detail_launch.set_visible(False)
            if hasattr(self, "btn_detail_update"):
                self.btn_detail_update.set_visible(False)
            self.btn_detail_install.set_label("QUEUED")
            self.btn_detail_install.set_sensitive(False)
            self.btn_detail_install.set_css_classes(["mac-btn-primary-large", "mac-btn-queued"])
            self.btn_detail_install.set_size_request(108, 36)
            self.btn_detail_install.set_visible(True)
            self.btn_detail_remove.set_visible(False)

        elif up_item:
            self.progress_container.set_visible(False)
            if desktop_entry:
                self.btn_detail_launch.set_label("OPEN")
                self.btn_detail_launch.set_css_classes(["mac-btn-detail-open"])
                self.btn_detail_launch.set_size_request(108, 36)
                self.btn_detail_launch.set_sensitive(True)
                self.btn_detail_launch.set_visible(True)
            else:
                self.btn_detail_launch.set_visible(False)
            self.btn_detail_install.set_visible(False)
            if hasattr(self, "btn_detail_update"):
                self.btn_detail_update.set_label("UPDATE")
                self.btn_detail_update.set_sensitive(True)
                self.btn_detail_update.set_visible(True)
            self.btn_detail_remove.set_label("UNINSTALL")
            self.btn_detail_remove.set_size_request(108, 36)
            self.btn_detail_remove.set_sensitive(True)
            self.btn_detail_remove.set_visible(True)

        elif is_installed:
            self.progress_container.set_visible(False)
            if hasattr(self, "detail_update_banner"):
                self.detail_update_banner.set_visible(False)
            if hasattr(self, "btn_detail_update"):
                self.btn_detail_update.set_visible(False)
            if desktop_entry:
                self.btn_detail_launch.set_label("OPEN")
                self.btn_detail_launch.set_css_classes(["mac-btn-detail-open"])
                self.btn_detail_launch.set_size_request(108, 36)
                self.btn_detail_launch.set_sensitive(True)
                self.btn_detail_launch.set_visible(True)
                self.btn_detail_install.set_visible(False)
            else:
                self.btn_detail_launch.set_visible(False)
                self.btn_detail_install.set_label("INSTALLED")
                self.btn_detail_install.set_css_classes(["mac-btn-installed"])
                self.btn_detail_install.set_size_request(108, 36)
                self.btn_detail_install.set_sensitive(True)
                self.btn_detail_install.set_visible(True)
            self.btn_detail_remove.set_label("UNINSTALL")
            self.btn_detail_remove.set_size_request(108, 36)
            self.btn_detail_remove.set_sensitive(True)
            self.btn_detail_remove.set_visible(True)

        else:
            self.progress_container.set_visible(False)
            self.btn_detail_launch.set_visible(False)
            if hasattr(self, "detail_update_banner"):
                self.detail_update_banner.set_visible(False)
            if hasattr(self, "btn_detail_update"):
                self.btn_detail_update.set_visible(False)
            self.btn_detail_install.set_label("GET")
            self.btn_detail_install.set_css_classes(["mac-btn-primary-large"])
            self.btn_detail_install.set_size_request(108, 36)
            self.btn_detail_install.set_sensitive(True)
            self.btn_detail_install.set_visible(True)
            self.btn_detail_remove.set_visible(False)

    def _on_window_key_pressed(self, controller: Gtk.EventControllerKey, keyval: int, keycode: int, state: Gdk.ModifierType) -> bool:
        # 1. Do not intercept if a modal or alert dialog is active
        if hasattr(self, "get_visible_dialog") and self.get_visible_dialog() is not None:
            return False

        # 2. Support standard Ctrl+F shortcut to focus search
        if (state & Gdk.ModifierType.CONTROL_MASK) and keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self._activate_search_entry()
            return True

        # 3. Ignore non-text modifier combinations (Ctrl, Alt, Super)
        active_mods = state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK)
        if active_mods != 0:
            return False

        # 4. If an editable or text view is already focused, let it process keystrokes natively
        focused = self.get_focus()
        if focused is not None and isinstance(focused, (Gtk.Editable, Gtk.TextView)):
            return False

        # 5. Convert keyval to unicode character
        u = Gdk.keyval_to_unicode(keyval)
        if u == 0:
            return False
        ch = chr(u)

        # 6. Only printable non-whitespace characters trigger type-to-search
        # (Spacebar is preserved for activating focused buttons / scrolling)
        if not ch.isprintable() or ch.isspace():
            return False

        # 7. Route and transfer character to active search entry
        self._handle_type_to_search(ch)
        return True

    def _handle_type_to_search(self, ch: str):
        curr = self.main_stack.get_visible_child_name()
        if curr in ("containers", "docker") and hasattr(self, "container_search_entry"):
            target_entry = self.container_search_entry
        elif curr == "snap" and hasattr(self, "snap_search_entry"):
            target_entry = self.snap_search_entry
        elif curr == "installed" and hasattr(self, "installed_search_entry"):
            target_entry = self.installed_search_entry
        else:
            if curr != "browse":
                self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
                self.main_stack.set_transition_duration(180)
                self.main_stack.set_visible_child_name("browse")
                self.header_title.set_text("Search Results")
            target_entry = getattr(self, "browse_search_entry", None) or getattr(self, "search_entry", None)

        if target_entry:
            target_entry.grab_focus()
            cur_text = target_entry.get_text()
            target_entry.set_text(cur_text + ch)
            target_entry.set_position(-1)

    def _activate_search_entry(self):
        curr = self.main_stack.get_visible_child_name()
        if curr in ("containers", "docker") and hasattr(self, "container_search_entry"):
            target_entry = self.container_search_entry
        elif curr == "snap" and hasattr(self, "snap_search_entry"):
            target_entry = self.snap_search_entry
        elif curr == "installed" and hasattr(self, "installed_search_entry"):
            target_entry = self.installed_search_entry
        else:
            if curr != "browse":
                self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
                self.main_stack.set_transition_duration(180)
                self.main_stack.set_visible_child_name("browse")
                self.header_title.set_text("Search Results")
            target_entry = getattr(self, "browse_search_entry", None) or getattr(self, "search_entry", None)

        if target_entry:
            target_entry.grab_focus()
            target_entry.select_region(0, -1)

    def _setup_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(APPLE_CSS.encode("utf-8"))
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    # =========================================================================
    # macOS Left Sidebar Navigation
    # =========================================================================
    def _build_sidebar(self) -> Gtk.Box:
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.add_css_class("mac-sidebar")
        sidebar.set_size_request(220, -1)
        sidebar.set_hexpand(False)

        # App Brand Header (Squircle icon + Aura Store + Package Hub subtitle)
        brand_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        brand_box.add_css_class("mac-brand-box")
        brand_box.set_valign(Gtk.Align.START)
        brand_box.set_halign(Gtk.Align.START)
        brand_box.set_hexpand(False)
        brand_box.set_vexpand(False)

        brand_logo_box = Gtk.Box()
        brand_logo_box.add_css_class("mac-brand-logo-squircle")
        brand_logo_box.set_size_request(36, 36)
        brand_logo_box.set_homogeneous(True)
        brand_logo_box.set_halign(Gtk.Align.CENTER)
        brand_logo_box.set_valign(Gtk.Align.CENTER)
        brand_logo_box.set_hexpand(False)
        brand_logo_box.set_vexpand(False)
        icon_candidates = [
            os.path.join(APP_DIR, "aura-icon.svg"),
            os.path.join(os.path.expanduser("~"), ".local", "share", "aura", "aura-icon.svg"),
            os.path.join(APP_DIR, "data", "icons", "io.github.aura.svg"),
        ]
        found_icon = next((p for p in icon_candidates if os.path.exists(p)), "aura-icon")
        brand_logo_img = create_scaled_image(found_icon, size=36)
        brand_logo_box.append(brand_logo_img)
        brand_box.append(brand_logo_box)

        brand_text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        brand_text_box.set_valign(Gtk.Align.CENTER)
        brand_lbl = Gtk.Label(label="Aura Store")
        brand_lbl.add_css_class("mac-brand-title")
        brand_lbl.set_halign(Gtk.Align.START)
        brand_text_box.append(brand_lbl)

        brand_sub = Gtk.Label(label="Package Hub")
        brand_sub.add_css_class("mac-brand-sub")
        brand_sub.set_halign(Gtk.Align.START)
        brand_text_box.append(brand_sub)

        brand_box.append(brand_text_box)
        sidebar.append(brand_box)

        # Search Entry in Sidebar — persistent, synchronized live search bar
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.add_css_class("mac-sidebar-search")
        self.search_entry.set_placeholder_text("Search packages & apps...")
        self.search_entry.connect("changed", self._on_sidebar_search_activate)
        self.search_entry.connect("search-changed", self._on_sidebar_search_activate)
        self.search_entry.connect("stop-search", lambda e: e.set_text(""))
        sidebar.append(self.search_entry)

        # Scrolled Sidebar Navigation (EXTERNAL policy hides scrollbar track completely while preserving wheel scroll)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.EXTERNAL)

        nav_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        # Structured Navigation Sections
        self.sidebar_buttons = {}
        self._sidebar_ready = False
        first_btn = None

        sections = [
            ("DISCOVER", [
                ("discover", "Discover", "starred-symbolic"),
                ("categories", "Categories", "view-app-grid-symbolic"),
            ]),
            ("ECOSYSTEM", [
                ("deb", ".deb Installer", "package-x-generic-symbolic"),
                ("hyprland", "Hyprland Hub", "preferences-desktop-display-symbolic"),
                ("docker", "Docker Apps", "application-x-addon-symbolic"),
                ("snap", "Snap Store", "package-x-generic-symbolic"),
            ]),
            ("LIBRARY", [
                ("installed", "Installed", "feather-check-symbolic"),
                ("updates", "Updates", "feather-refresh-cw-symbolic"),
            ]),
            ("MAINTENANCE", [
                ("storage", "Storage & Caches", "drive-harddisk-symbolic"),
            ]),
        ]

        for sec_idx, (sec_title, items) in enumerate(sections):
            if sec_idx > 0:
                div = Gtk.Box()
                div.add_css_class("mac-sidebar-divider")
                nav_box.append(div)

            hdr = Gtk.Label(label=sec_title)
            hdr.add_css_class("mac-sidebar-section-hdr")
            hdr.set_halign(Gtk.Align.START)
            nav_box.append(hdr)

            for key, label, icon_name in items:
                btn = Gtk.ToggleButton()
                btn.add_css_class("mac-nav-item")

                btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                btn_box.set_valign(Gtk.Align.CENTER)

                icon_box = Gtk.Box()
                icon_box.add_css_class("mac-nav-icon-box")
                icon_box.set_size_request(22, 22)
                icon_box.set_halign(Gtk.Align.CENTER)
                icon_box.set_valign(Gtk.Align.CENTER)
                icon = Gtk.Image.new_from_icon_name(icon_name)
                icon.set_pixel_size(17)
                icon.set_halign(Gtk.Align.CENTER)
                icon.set_valign(Gtk.Align.CENTER)
                icon_box.append(icon)
                btn_box.append(icon_box)

                lbl = Gtk.Label(label=label)
                lbl.set_hexpand(True)
                lbl.set_halign(Gtk.Align.START)
                lbl.set_valign(Gtk.Align.CENTER)
                btn_box.append(lbl)

                if key == "updates":
                    upg_list = getattr(self.pm, "upgradable_list", [])
                    upg_count = len(upg_list) if upg_list else 0
                    self.sidebar_updates_badge = Gtk.Label(label=str(upg_count) if upg_count > 0 else "")
                    self.sidebar_updates_badge.add_css_class("mac-nav-badge")
                    self.sidebar_updates_badge.set_valign(Gtk.Align.CENTER)
                    self.sidebar_updates_badge.set_halign(Gtk.Align.END)
                    self.sidebar_updates_badge.set_visible(upg_count > 0)
                    btn_box.append(self.sidebar_updates_badge)
                elif key == "installed":
                    num_inst = len(self.pm.get_installed_desktop_apps())
                    self.sidebar_installed_badge = Gtk.Label(label=str(num_inst))
                    self.sidebar_installed_badge.add_css_class("mac-nav-badge")
                    self.sidebar_installed_badge.set_valign(Gtk.Align.CENTER)
                    self.sidebar_installed_badge.set_halign(Gtk.Align.END)
                    btn_box.append(self.sidebar_installed_badge)

                btn.set_child(btn_box)

                if first_btn is None:
                    first_btn = btn
                else:
                    btn.set_group(first_btn)

                btn.connect("toggled", self._make_sidebar_nav_handler(key))
                btn.connect("clicked", lambda b, k=key: self._on_sidebar_channel_click(k))
                self.sidebar_buttons[key] = btn
                nav_box.append(btn)

        # Aliases for backwards compatibility
        self.sidebar_buttons["category"] = self.sidebar_buttons.get("categories")
        self.sidebar_buttons["containers"] = self.sidebar_buttons.get("docker")

        self._sidebar_ready = True
        if first_btn:
            first_btn.set_active(True)

        scrolled.set_child(nav_box)
        sidebar.append(scrolled)
        return sidebar

    def _on_sidebar_channel_click(self, key: str):
        if not getattr(self, "_sidebar_ready", False):
            return
        now = time.monotonic()
        last_key, last_t = getattr(self, "_last_nav_event", ("", 0.0))
        target_stack_map = {
            "discover": "discover",
            "categories": "category",
            "category": "category",
            "docker": "docker",
            "containers": "docker",
            "snap": "snap",
            "updates": "updates",
            "installed": "installed",
            "storage": "storage",
            "maintenance": "storage",
            "deb": "deb",
            "hyprland": "hyprland",
        }
        expected_page = target_stack_map.get(key, key)
        if key == last_key and (now - last_t) < 0.08 and self.main_stack.get_visible_child_name() == expected_page:
            return
        self._last_nav_event = (key, now)

        self.set_focus(None)
        self.back_btn.set_visible(False)
        self._previous_page = key

        # Keep sidebar search visible and clear search entries synchronously under lock
        self._show_sidebar_search()
        self._search_sync_lock = True
        try:
            if hasattr(self, "search_entry") and self.search_entry.get_text():
                self.search_entry.set_text("")
            if hasattr(self, "browse_search_entry") and self.browse_search_entry.get_text():
                self.browse_search_entry.set_text("")
        finally:
            self._search_sync_lock = False

        # Clear redundant header bar title so page title is prominent
        self.header_title.set_text("")

        if key == "discover":
            self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            self.main_stack.set_transition_duration(180)
            self.main_stack.set_visible_child_name("discover")
        elif key in ("categories", "category"):
            self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            self.main_stack.set_transition_duration(180)
            self.main_stack.set_visible_child_name("category")
            self._load_categories_view()
        elif key in ("docker", "containers"):
            self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            self.main_stack.set_transition_duration(180)
            self.main_stack.set_visible_child_name("docker")
            self._load_containers_view()
        elif key == "snap":
            self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            self.main_stack.set_transition_duration(180)
            self.main_stack.set_visible_child_name("snap")
            self._load_snap_view()
        elif key == "updates":
            self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            self.main_stack.set_transition_duration(180)
            self.main_stack.set_visible_child_name("updates")
            self._load_updates_view()
        elif key == "installed":
            self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            self.main_stack.set_transition_duration(180)
            self.main_stack.set_visible_child_name("installed")
            self._load_installed_view()
        elif key in ("storage", "maintenance"):
            self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            self.main_stack.set_transition_duration(180)
            self.main_stack.set_visible_child_name("storage")
            self._load_storage_view()
        elif key == "deb":
            self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            self.main_stack.set_transition_duration(180)
            self.main_stack.set_visible_child_name("deb")
            self._load_deb_view()
        elif key == "hyprland":
            self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            self.main_stack.set_transition_duration(180)
            self.main_stack.set_visible_child_name("hyprland")
            self._load_hyprland_view()

    def _make_sidebar_nav_handler(self, key: str):
        def _handler(button: Gtk.ToggleButton):
            if button.get_active():
                self._on_sidebar_channel_click(key)
        return _handler

    def _on_sidebar_category_click(self, ckey: str, clabel: str):
        if not getattr(self, "_sidebar_ready", False):
            return
        self.set_focus(None)
        self._open_category(ckey, clabel)

    def _make_sidebar_category_handler(self, ckey: str, clabel: str):
        def _handler(button: Gtk.ToggleButton):
            if button.get_active():
                self._on_sidebar_category_click(ckey, clabel)
        return _handler

    def _load_categories_view(self, cat_id: Optional[str] = None):
        """Loads categories page with interactive category pills."""
        if not cat_id:
            cat_id = "essential"
        self._open_category(cat_id)

    def _open_category(self, cat_id: str, cat_title: str = ""):
        """Opens dedicated Category page with 100% working curated packages."""
        self._save_current_scroll_position()
        self.set_focus(None)
        self._previous_page = "discover"
        self.back_btn.set_visible(True)

        cat_obj = None
        for c in CURATED_CATEGORIES:
            if c.get("id") == cat_id or c.get("category") == cat_id or c.get("category") == cat_title:
                cat_obj = c
                break

        display_title = cat_obj["category"] if cat_obj else (cat_title or cat_id.capitalize())
        self.header_title.set_text("")
        self.cat_page_title.set_text(display_title)

        subtitle = cat_obj.get("subtitle", "Curated high-performance software") if cat_obj else "Curated applications"
        self.cat_page_subtitle.set_text(subtitle)

        # Highlight sidebar button without re-triggering _on_sidebar_channel_click
        prev_ready = getattr(self, "_sidebar_ready", True)
        self._sidebar_ready = False
        try:
            if "categories" in self.sidebar_buttons and self.sidebar_buttons["categories"]:
                self.sidebar_buttons["categories"].set_active(True)
            elif "category" in self.sidebar_buttons and self.sidebar_buttons["category"]:
                self.sidebar_buttons["category"].set_active(True)
        finally:
            self._sidebar_ready = prev_ready

        # Highlight category pill
        if cat_obj and hasattr(self, "category_pill_buttons"):
            cid = cat_obj.get("id")
            if cid in self.category_pill_buttons:
                self.category_pill_buttons[cid].set_active(True)

        # Populate Category Grid with staggered entrance animation
        self.cat_flow_box.remove_all()
        if cat_obj and "apps" in cat_obj:
            for idx, app_meta in enumerate(cat_obj["apps"]):
                card = self._create_mac_app_row(
                    app_meta["name"],
                    app_meta.get("desc", ""),
                    app_meta.get("source", "pacman"),
                    title_override=app_meta.get("title", "")
                )
                card.add_css_class("mac-category-card")
                self.cat_flow_box.append(card)
                self._animate_card_entrance(card, idx)

        self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.main_stack.set_transition_duration(180)
        self.main_stack.set_visible_child_name("category")
        if self.category_page.get_vadjustment():
            self.category_page.get_vadjustment().set_value(0)

    def _build_category_page(self) -> Gtk.ScrolledWindow:
        scrolled = Gtk.ScrolledWindow()
        scrolled.add_css_class("aura-page")
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(16)
        box.set_margin_bottom(40)
        box.set_margin_start(20)
        box.set_margin_end(20)

        # Category Header Row
        header_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.cat_page_title = Gtk.Label(label="Category")
        self.cat_page_title.add_css_class("mac-page-title")
        self.cat_page_title.set_halign(Gtk.Align.START)
        header_row.append(self.cat_page_title)

        self.cat_page_subtitle = Gtk.Label(label="Curated applications & packages")
        self.cat_page_subtitle.add_css_class("mac-page-subtitle")
        self.cat_page_subtitle.set_halign(Gtk.Align.START)
        header_row.append(self.cat_page_subtitle)
        box.append(header_row)

        # Category Selector Chips/Pills
        self.cat_pills_box = Gtk.FlowBox()
        cat_pills_box = self.cat_pills_box
        cat_pills_box.set_selection_mode(Gtk.SelectionMode.NONE)
        cat_pills_box.set_max_children_per_line(10)
        cat_pills_box.set_min_children_per_line(1)
        cat_pills_box.set_row_spacing(8)
        cat_pills_box.set_column_spacing(8)
        cat_pills_box.set_halign(Gtk.Align.START)
        cat_pills_box.set_margin_top(4)
        cat_pills_box.set_margin_bottom(12)

        self.category_pill_buttons = {}
        first_cat_btn = None
        for c in CURATED_CATEGORIES:
            cid = c.get("id")
            cname = c.get("category")
            cbtn = Gtk.ToggleButton(label=cname)
            cbtn.add_css_class("mac-search-filter-pill")
            if first_cat_btn is None:
                first_cat_btn = cbtn
            else:
                cbtn.set_group(first_cat_btn)
            cbtn.connect("clicked", lambda b, cid=cid, cname=cname: self._open_category(cid, cname))
            self.category_pill_buttons[cid] = cbtn
            cat_pills_box.append(cbtn)

        box.append(cat_pills_box)

        # Symmetrical Grid
        self.cat_flow_box = self._create_symmetric_grid(min_columns=1, max_columns=4)
        box.append(self.cat_flow_box)

        scrolled.set_child(box)
        return scrolled

    # =========================================================================
    # Header Bar
    # =========================================================================
    def _build_headerbar(self) -> Gtk.Box:
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header.add_css_class("mac-header")
        header.set_valign(Gtk.Align.CENTER)

        # Back Button (Visible when inside Detail or Category view)
        self.back_btn = Gtk.Button()
        self.back_btn.add_css_class("mac-back-btn")
        self.back_btn.set_size_request(32, 32)
        self.back_btn.set_halign(Gtk.Align.START)
        self.back_btn.set_valign(Gtk.Align.CENTER)
        self.back_btn.set_hexpand(False)
        self.back_btn.set_vexpand(False)
        back_icon = Gtk.Image.new_from_icon_name("go-previous-symbolic")
        back_icon.set_pixel_size(14)
        back_icon.set_halign(Gtk.Align.CENTER)
        back_icon.set_valign(Gtk.Align.CENTER)
        back_icon.set_hexpand(False)
        back_icon.set_vexpand(False)
        self.back_btn.set_child(back_icon)
        self.back_btn.set_visible(False)
        self.back_btn.connect("clicked", lambda b: self._navigate_back())
        header.append(self.back_btn)

        # Title Label (Only used for Details and Search)
        self.header_title = Gtk.Label(label="")
        self.header_title.add_css_class("mac-header-title")
        self.header_title.set_halign(Gtk.Align.START)
        self.header_title.set_valign(Gtk.Align.CENTER)
        self.header_title.set_ellipsize(Pango.EllipsizeMode.END)
        header.append(self.header_title)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)

        # Global Floating Progress Indicator in Header Bar
        self.header_progress_pill = Gtk.Button()
        self.header_progress_pill.add_css_class("mac-header-progress-pill")
        self.header_progress_pill.set_valign(Gtk.Align.CENTER)
        self.header_progress_pill.set_visible(False)
        self.header_progress_pill.set_cursor(Gdk.Cursor.new_from_name("pointer", None))

        pill_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pill_box.set_valign(Gtk.Align.CENTER)

        self.header_progress_spinner = Gtk.Spinner()
        self.header_progress_spinner.set_size_request(13, 13)
        pill_box.append(self.header_progress_spinner)

        self.header_progress_label = Gtk.Label(label="")
        self.header_progress_label.set_ellipsize(Pango.EllipsizeMode.END)
        pill_box.append(self.header_progress_label)

        self.header_progress_pill.set_child(pill_box)
        self.header_progress_pill.connect("clicked", lambda b: self._on_header_progress_clicked())
        header.append(self.header_progress_pill)

        # Window Controls & Utilities Group (Hyprland / Tiling Friendly)
        btn_group = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_group.set_valign(Gtk.Align.CENTER)

        # Lifetime Auth / Security Button
        self.auth_btn = Gtk.Button()
        self.auth_btn.add_css_class("mac-win-btn")
        self.auth_btn.set_size_request(32, 32)
        self.auth_btn.set_valign(Gtk.Align.CENTER)
        self.auth_icon = Gtk.Image.new_from_icon_name("channel-secure-symbolic")
        self.auth_icon.set_pixel_size(14)
        self.auth_btn.set_child(self.auth_icon)
        self.auth_btn.connect("clicked", lambda b: self._show_password_config_dialog())
        btn_group.append(self.auth_btn)

        # Refresh Database Button
        refresh_btn = Gtk.Button()
        refresh_btn.add_css_class("mac-win-btn")
        refresh_btn.set_size_request(32, 32)
        refresh_btn.set_valign(Gtk.Align.CENTER)
        ref_icon = Gtk.Image.new_from_icon_name("view-refresh-symbolic")
        ref_icon.set_pixel_size(14)
        refresh_btn.set_child(ref_icon)
        refresh_btn.set_tooltip_text("Reload package database")
        refresh_btn.connect("clicked", lambda b: self._reload_database())
        btn_group.append(refresh_btn)

        # Window Close Button
        close_btn = Gtk.Button()
        close_btn.add_css_class("mac-win-btn")
        close_btn.add_css_class("mac-win-close")
        close_btn.set_size_request(32, 32)
        close_btn.set_valign(Gtk.Align.CENTER)
        close_icon = Gtk.Image.new_from_icon_name("window-close-symbolic")
        close_icon.set_pixel_size(13)
        close_btn.set_child(close_icon)
        close_btn.set_tooltip_text("Close Aura App Store")
        close_btn.connect("clicked", lambda b: self.close())
        btn_group.append(close_btn)

        header.append(btn_group)
        self._update_auth_btn_status()
        return header

    def _update_auth_btn_status(self):
        if hasattr(self, "auth_btn"):
            if self.pm.is_passwordless_configured():
                self.auth_btn.set_tooltip_text("Lifetime Authorization Active (Never prompts for password)")
                self.auth_btn.remove_css_class("mac-auth-needed")
                self.auth_btn.add_css_class("mac-auth-verified")
            else:
                self.auth_btn.set_tooltip_text("Configure Lifetime Passwordless Mode")
                self.auth_btn.remove_css_class("mac-auth-verified")
                self.auth_btn.add_css_class("mac-auth-needed")

    def _on_header_progress_clicked(self):
        active_tx = self.pm.get_active_transaction() if hasattr(self.pm, "get_active_transaction") else None
        action = ""
        pkg_name = ""
        source = "pacman"
        if active_tx and isinstance(active_tx, dict):
            action = active_tx.get("action", "")
            pkg_name = active_tx.get("pkg_name", "")
            source = active_tx.get("source", "pacman")
        elif self._progress_pkg_name:
            action = self._progress_action
            pkg_name = self._progress_pkg_name
            source = self._progress_source

        if action in ["update", "upgrade"] or pkg_name in ["system", "--all", "all", ""]:
            if "updates" in self.sidebar_buttons:
                if not self.sidebar_buttons["updates"].get_active():
                    self.sidebar_buttons["updates"].set_active(True)
                else:
                    self._on_sidebar_channel_click("updates")
        elif pkg_name:
            self._open_package_detail(pkg_name, source)

    def _show_password_config_dialog(self):
        is_cfg = self.pm.is_passwordless_configured()

        dialog = Adw.AlertDialog.new(
            "Passwordless Package Management",
            "Configure a dedicated sudoers drop-in policy for pacman, paru, and yay operations. When enabled, Aura performs package installations and updates seamlessly without repeatedly prompting for administrator credentials."
        )

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(16)
        box.set_margin_end(16)

        # Status badge
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_box.set_halign(Gtk.Align.CENTER)
        status_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic" if is_cfg else "dialog-password-symbolic")
        status_lbl = Gtk.Label()
        if is_cfg:
            status_lbl.set_label("Passwordless Mode Active (Never prompts)")
            status_lbl.add_css_class("success-status")
        else:
            status_lbl.set_label("Password required for root operations")
            status_lbl.add_css_class("dim-label")
        status_box.append(status_icon)
        status_box.append(status_lbl)
        box.append(status_box)

        pwd_lbl = Gtk.Label(
            label="Administrator Password (to remove sudoers policy):" if is_cfg else "Administrator Password:"
        )
        pwd_lbl.set_halign(Gtk.Align.START)
        pwd_lbl.add_css_class("mac-stat-label")
        box.append(pwd_lbl)

        entry = Gtk.PasswordEntry()
        entry.set_show_peek_icon(True)
        entry.set_hexpand(True)
        box.append(entry)

        if is_cfg:
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("disable", "Disable Passwordless Mode")
            dialog.set_response_appearance("disable", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("disable")
        else:
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("enable", "Enable Passwordless Mode")
            dialog.set_response_appearance("enable", Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response("enable")

        dialog.set_close_response("cancel")
        dialog.set_extra_child(box)

        def on_response(dlg, resp):
            if resp == "disable":
                pwd = entry.get_text().strip() if entry is not None else ""
                success, msg = self.pm.remove_passwordless(password=pwd if pwd else None)
                self.show_toast(msg)
                self._update_auth_btn_status()
            elif resp == "enable":
                if entry is None:
                    return
                pwd = entry.get_text()
                if not pwd:
                    self.show_toast("Password cannot be empty")
                    return
                success, msg = self.pm.configure_passwordless(pwd)
                self.show_toast(msg)
                self._update_auth_btn_status()

        dialog.connect("response", on_response)
        dialog.present(self)

    def _get_page_scrolled_window(self, page_name: str) -> Optional[Gtk.ScrolledWindow]:
        page_map = {
            "discover": getattr(self, "discover_page", None),
            "browse": getattr(self, "browse_page", None),
            "updates": getattr(self, "updates_page", None),
            "installed": getattr(self, "installed_page", None),
            "detail": getattr(self, "detail_page", None),
            "category": getattr(self, "category_page", None),
            "categories": getattr(self, "category_page", None),
            "docker": getattr(self, "containers_page", None),
            "containers": getattr(self, "containers_page", None),
            "snap": getattr(self, "snap_page", None),
            "storage": getattr(self, "storage_page", None),
            "deb": getattr(self, "deb_page", None),
            "hyprland": getattr(self, "hyprland_page", None),
        }
        w = page_map.get(page_name)
        return w if isinstance(w, Gtk.ScrolledWindow) else None

    def _save_current_scroll_position(self):
        curr = self.main_stack.get_visible_child_name()
        if not curr or curr == "detail":
            return
        sw = self._get_page_scrolled_window(curr)
        if sw and sw.get_vadjustment():
            self._saved_scroll_positions[curr] = sw.get_vadjustment().get_value()

    def _restore_scroll_position(self, page_name: str):
        saved_val = self._saved_scroll_positions.get(page_name)
        if saved_val is None:
            return
        sw = self._get_page_scrolled_window(page_name)
        if not sw:
            return
        def _apply_scroll():
            self.set_focus(None)
            vadj = sw.get_vadjustment()
            if vadj and vadj.get_upper() >= saved_val:
                vadj.set_value(saved_val)
            return False
        _apply_scroll()
        GLib.idle_add(_apply_scroll)
        GLib.timeout_add(35, _apply_scroll)

    def _navigate_back(self):
        target_page = getattr(self, "_previous_page", "discover") or "discover"
        # If we are in 'category', back goes to 'discover'; if in 'detail', back goes to _previous_page
        curr_page = self.main_stack.get_visible_child_name()
        if curr_page == "category":
            target_page = "discover"
            self.back_btn.set_visible(False)
        else:
            # If returning from detail to category, keep back_btn visible so user can still go back to discover!
            self.back_btn.set_visible(target_page == "category")

        self.set_focus(None)
        self.main_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_RIGHT)
        self.main_stack.set_transition_duration(180)
        self.main_stack.set_visible_child_name(target_page)

        if target_page == "browse":
            self.header_title.set_text("Search Results")
            self._show_sidebar_search()
        else:
            self.header_title.set_text("")
            self._show_sidebar_search()
            # Synchronize active sidebar toggle button WITHOUT firing _on_sidebar_channel_click (preserves scroll & view!)
            target_btn = self.sidebar_buttons.get(target_page, self.sidebar_buttons.get("discover"))
            if target_btn and not target_btn.get_active():
                prev_ready = getattr(self, "_sidebar_ready", True)
                self._sidebar_ready = False
                try:
                    target_btn.set_active(True)
                finally:
                    self._sidebar_ready = prev_ready

        # Sync card action buttons in-place without destroying FlowBox children
        self._sync_all_cards()
        self._restore_scroll_position(target_page)

    # =========================================================================
    # Page 1: Discover View (Spotlight Showcase Banners + 3-Column Grid)
    # =========================================================================
    def _build_discover_page(self) -> Gtk.ScrolledWindow:
        scrolled = Gtk.ScrolledWindow()
        scrolled.add_css_class("aura-page")
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        box.set_margin_top(16)
        box.set_margin_bottom(40)
        box.set_margin_start(20)
        box.set_margin_end(20)

        # Discover Page Header (macOS App Store Style)
        header_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header_title = Gtk.Label(label="Discover")
        header_title.add_css_class("mac-page-title")
        header_title.set_halign(Gtk.Align.START)
        header_row.append(header_title)

        header_sub = Gtk.Label(label="Curated applications & high-performance software")
        header_sub.add_css_class("mac-page-subtitle")
        header_sub.set_halign(Gtk.Align.START)
        header_sub.set_wrap(True)
        header_sub.set_wrap_mode(Pango.WrapMode.WORD)
        header_sub.set_ellipsize(Pango.EllipsizeMode.END)
        header_row.append(header_sub)
        box.append(header_row)

        # Mac Hero Carousel (Curated 5-Slide Animated Showcase)
        self.hero_carousel = MacHeroCarousel(self)
        self.hero_carousel.set_margin_top(4)
        self.hero_carousel.set_margin_bottom(8)
        box.append(self.hero_carousel)

        # 2. Curated Categories (Multi-Column Symmetrical Grids)
        for cat in CURATED_CATEGORIES:
            sec_header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            sec_header_box.set_margin_top(16)
            sec_header_box.set_valign(Gtk.Align.CENTER)

            title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            cat_title = Gtk.Label(label=cat["category"])
            cat_title.add_css_class("mac-section-title")
            cat_title.set_halign(Gtk.Align.START)
            title_box.append(cat_title)

            if cat.get("subtitle"):
                cat_sub = Gtk.Label(label=cat["subtitle"])
                cat_sub.add_css_class("mac-section-subtitle")
                cat_sub.set_halign(Gtk.Align.START)
                title_box.append(cat_sub)
            sec_header_box.append(title_box)

            sp = Gtk.Box()
            sp.set_hexpand(True)
            sec_header_box.append(sp)

            see_all_btn = Gtk.Button()
            see_all_btn.add_css_class("mac-see-all-btn")
            see_all_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            see_all_lbl = Gtk.Label(label="See All")
            see_all_box.append(see_all_lbl)
            see_all_icon = Gtk.Image.new_from_icon_name("go-next-symbolic")
            see_all_icon.set_pixel_size(11)
            see_all_box.append(see_all_icon)
            see_all_btn.set_child(see_all_box)
            see_all_btn.set_tooltip_text(f"View all {cat['category']} packages")
            see_all_btn.connect("clicked", lambda b, cid=cat["id"], cname=cat["category"]: self._open_category(cid, cname))
            sec_header_box.append(see_all_btn)

            box.append(sec_header_box)

            # Symmetrical Grid (up to 4 columns fullscreen)
            flow = self._create_symmetric_grid(min_columns=1, max_columns=4)
            for app_meta in cat["apps"]:
                card = self._create_mac_app_row(
                    app_meta["name"],
                    app_meta.get("desc", ""),
                    app_meta.get("source", "pacman"),
                    title_override=app_meta.get("title", "")
                )
                card.add_css_class("mac-category-card")
                flow.append(card)
            box.append(flow)

        scrolled.set_child(box)
        return scrolled

    # =========================================================================
    # Page 2: Browse & Search View (3-Column Grid)
    # =========================================================================
    def _build_browse_page(self) -> Gtk.ScrolledWindow:
        scrolled = Gtk.ScrolledWindow()
        scrolled.add_css_class("aura-page")
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        page_box.set_margin_top(18)
        page_box.set_margin_bottom(36)
        page_box.set_margin_start(20)
        page_box.set_margin_end(20)
        page_box.set_vexpand(True)
        page_box.set_hexpand(True)

        # 1. Prominent Modern Glass Search Bar
        search_bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        search_bar_box.set_hexpand(True)

        self.browse_search_entry = Gtk.SearchEntry()
        self.browse_search_entry.add_css_class("mac-search-glass-bar")
        self.browse_search_entry.set_placeholder_text("Search packages, apps, libraries...")
        self.browse_search_entry.set_hexpand(True)
        self.browse_search_entry.connect("changed", self._on_browse_search_changed)
        self.browse_search_entry.connect("search-changed", self._on_browse_search_changed)
        self.browse_search_entry.connect("stop-search", self._on_browse_stop_search)
        search_bar_box.append(self.browse_search_entry)
        page_box.append(search_bar_box)

        # 2. Modern Apple-Style Segmented Capsule Ecosystem Switcher
        tabs_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        tabs_box.add_css_class("mac-segmented-box")
        tabs_box.set_halign(Gtk.Align.START)

        ecosystems = [
            ("native", "Arch Linux (Pacman & AUR)", "package-x-generic-symbolic"),
            ("snap", "Snap Store", "snapcraft"),
            ("docker", "Docker Apps", "docker-symbolic"),
        ]
        self.filter_buttons = {}
        first_btn = None
        for key, label, icon_name in ecosystems:
            btn = Gtk.ToggleButton()
            btn.add_css_class("mac-search-filter-pill")

            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            btn_box.set_valign(Gtk.Align.CENTER)

            eff_icon = icon_name
            display = Gdk.Display.get_default()
            theme = Gtk.IconTheme.get_for_display(display) if display else None
            if theme and not theme.has_icon(eff_icon) and eff_icon == "snapcraft" and theme.has_icon("snap"):
                eff_icon = "snap"

            icon = Gtk.Image.new_from_icon_name(eff_icon)
            icon.set_pixel_size(14)
            icon.set_valign(Gtk.Align.CENTER)
            btn_box.append(icon)

            lbl = Gtk.Label(label=label)
            lbl.set_valign(Gtk.Align.CENTER)
            btn_box.append(lbl)

            btn.set_child(btn_box)
            self.filter_buttons[key] = btn

            if first_btn is None:
                first_btn = btn
            else:
                btn.set_group(first_btn)

            btn.connect("toggled", self._make_filter_handler(key))
            tabs_box.append(btn)

        if first_btn:
            first_btn.set_active(True)

        page_box.append(tabs_box)

        # 3. Status Box with Spinner for search results (Always visible to maintain stable layout)
        self.browse_status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.browse_status_box.add_css_class("mac-search-status-box")
        self.browse_status_box.set_valign(Gtk.Align.CENTER)

        self.browse_spinner = Gtk.Spinner()
        self.browse_spinner.add_css_class("mac-search-spinner")
        self.browse_spinner.set_visible(False)
        self.browse_status_box.append(self.browse_spinner)

        self.browse_status_label = Gtk.Label(label="")
        self.browse_status_label.set_halign(Gtk.Align.START)
        self.browse_status_label.add_css_class("mac-browse-status-label")
        self.browse_status_label.add_css_class("dim-label")
        self.browse_status_label.set_visible(True)
        self.browse_status_box.append(self.browse_status_label)

        page_box.append(self.browse_status_box)

        # 4. Glassmorphic Guidance Hero Card (empty/welcome state) - Perfectly Symmetrical
        self.browse_hero_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.browse_hero_card.add_css_class("mac-search-hero")
        self.browse_hero_card.add_css_class("mac-search-hero-centered")
        self.browse_hero_card.set_halign(Gtk.Align.CENTER)
        self.browse_hero_card.set_valign(Gtk.Align.START)
        self.browse_hero_card.set_margin_top(12)
        self.browse_hero_card.set_margin_bottom(12)

        hero_icon_box = Gtk.Box()
        hero_icon_box.add_css_class("mac-search-hero-icon")
        hero_icon_box.set_size_request(52, 52)
        hero_icon_box.set_halign(Gtk.Align.CENTER)
        hero_icon_box.set_valign(Gtk.Align.CENTER)
        hero_icon = Gtk.Image.new_from_icon_name("system-search-symbolic")
        hero_icon.set_pixel_size(26)
        hero_icon.set_halign(Gtk.Align.CENTER)
        hero_icon.set_valign(Gtk.Align.CENTER)
        hero_icon.set_hexpand(True)
        hero_icon.set_vexpand(True)
        hero_icon_box.append(hero_icon)
        self.browse_hero_card.append(hero_icon_box)

        hero_title = Gtk.Label(label="Discover Applications & Packages")
        hero_title.add_css_class("mac-search-hero-title")
        hero_title.set_halign(Gtk.Align.CENTER)
        self.browse_hero_card.append(hero_title)

        hero_desc = Gtk.Label(
            label="Search official Arch repositories, AUR packages, Snap Store apps, and Docker containers in one place."
        )
        hero_desc.add_css_class("mac-search-hero-desc")
        hero_desc.set_halign(Gtk.Align.CENTER)
        hero_desc.set_justify(Gtk.Justification.CENTER)
        hero_desc.set_wrap(True)
        hero_desc.set_max_width_chars(52)
        self.browse_hero_card.append(hero_desc)

        # Quick Search Suggestion Chips
        chips_box = Gtk.FlowBox()
        chips_box.set_selection_mode(Gtk.SelectionMode.NONE)
        chips_box.set_halign(Gtk.Align.CENTER)
        chips_box.set_valign(Gtk.Align.CENTER)
        chips_box.set_margin_top(6)
        chips_box.set_row_spacing(8)
        chips_box.set_column_spacing(8)
        chips_box.set_min_children_per_line(1)
        chips_box.set_max_children_per_line(5)

        suggestions = [
            ("🌐 Browsers", "browser"),
            ("💻 Development", "code"),
            ("🎵 Media", "media"),
            ("🎮 Gaming", "games"),
            ("📦 Utilities", "tools"),
        ]
        for chip_label, search_term in suggestions:
            chip_btn = Gtk.Button(label=chip_label)
            chip_btn.add_css_class("mac-search-chip")
            chip_btn.connect("clicked", lambda b, term=search_term: self._on_suggestion_chip_clicked(term))
            chips_box.append(chip_btn)

        self.browse_hero_card.append(chips_box)
        page_box.append(self.browse_hero_card)

        # Dedicated stable container for results flow box
        self.browse_results_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.browse_results_container.add_css_class("mac-browse-results-container")
        self.browse_results_container.set_vexpand(True)
        self.browse_results_container.set_hexpand(True)
        self.browse_results_container.set_visible(False)

        self.browse_flow_box = self._create_symmetric_grid(min_columns=1, max_columns=4)
        self.browse_results_container.append(self.browse_flow_box)
        page_box.append(self.browse_results_container)

        scrolled.set_child(page_box)
        return scrolled

    # =========================================================================
    # Page 3: System Updates View
    # =========================================================================
    def _build_updates_page(self) -> Gtk.ScrolledWindow:
        scrolled = Gtk.ScrolledWindow()
        scrolled.add_css_class("aura-page")
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        self.updates_main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.updates_main_box.set_margin_top(20)
        self.updates_main_box.set_margin_bottom(36)
        self.updates_main_box.set_margin_start(20)
        self.updates_main_box.set_margin_end(20)

        # Progress bar for update operations
        self.updates_progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.updates_progress_box.add_css_class("progress-card")
        self.updates_progress_box.set_visible(False)

        up_prog_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        up_prog_hdr.add_css_class("mac-progress-header")

        self.updates_progress_lbl = Gtk.Label(label="Updating packages...")
        self.updates_progress_lbl.set_halign(Gtk.Align.START)
        self.updates_progress_lbl.set_hexpand(True)
        self.updates_progress_lbl.add_css_class("mac-progress-title")
        up_prog_hdr.append(self.updates_progress_lbl)

        self.updates_percent_label = Gtk.Label(label="0%")
        self.updates_percent_label.add_css_class("mac-progress-percent")
        self.updates_percent_label.set_halign(Gtk.Align.END)
        up_prog_hdr.append(self.updates_percent_label)

        self.updates_progress_box.append(up_prog_hdr)

        self.updates_progress_bar = Gtk.ProgressBar()
        self.updates_progress_bar.add_css_class("mac-capsule-progress")
        self.updates_progress_bar.set_fraction(0.0)
        self.updates_progress_box.append(self.updates_progress_bar)

        self.updates_main_box.append(self.updates_progress_box)

        # Header with UPDATE ALL Button
        updates_header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        updates_header_row.set_valign(Gtk.Align.CENTER)

        title_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.updates_count_label = Gtk.Label(label="Checking for updates...")
        self.updates_count_label.add_css_class("mac-section-title")
        self.updates_count_label.set_halign(Gtk.Align.START)
        self.updates_count_label.set_ellipsize(Pango.EllipsizeMode.END)
        title_vbox.append(self.updates_count_label)

        sub_label = Gtk.Label(label="Updates available for installed packages and software.")
        sub_label.add_css_class("dim-label")
        sub_label.set_halign(Gtk.Align.START)
        sub_label.set_wrap(True)
        sub_label.set_wrap_mode(Pango.WrapMode.WORD)
        sub_label.set_ellipsize(Pango.EllipsizeMode.END)
        title_vbox.append(sub_label)
        updates_header_row.append(title_vbox)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        updates_header_row.append(spacer)

        self.btn_update_all = Gtk.Button(label="UPDATE ALL")
        self.btn_update_all.add_css_class("mac-btn-update-all")
        self.btn_update_all.set_valign(Gtk.Align.CENTER)
        self.btn_update_all.connect("clicked", lambda b: self._update_all_packages())
        updates_header_row.append(self.btn_update_all)

        self.updates_main_box.append(updates_header_row)

        # Symmetrical Grid for Updates (Synchronized with Discover & Installed)
        self.updates_flow_box = self._create_symmetric_grid(min_columns=1, max_columns=4)
        self.updates_main_box.append(self.updates_flow_box)

        scrolled.set_child(self.updates_main_box)
        return scrolled

    def _load_updates_view(self):
        self._sync_all_grid_columns()
        self.updates_flow_box.remove_all()

        active_tx = self.pm.get_active_transaction() if hasattr(self.pm, "get_active_transaction") else None
        is_updating = False
        if active_tx and isinstance(active_tx, dict):
            if active_tx.get("action") in ["update", "upgrade"]:
                is_updating = True

        if is_updating:
            self.updates_progress_box.set_visible(True)
            self.btn_update_all.set_sensitive(False)
            prog = float(active_tx.get("progress", self._current_progress or 0.05))
            msg = str(active_tx.get("status_msg") or active_tx.get("status") or "Updating packages...")
            self.updates_progress_bar.set_fraction(prog)
            self.updates_progress_lbl.set_text(msg)
            self.updates_percent_label.set_text(f"{int(prog * 100)}%")
            self._target_progress = max(self._target_progress, prog)
            self._current_progress = prog
            self._progress_target_view = "updates"
            self._progress_action = active_tx.get("action", "update")
            tx_pkg = active_tx.get("pkg_name", "system")
            self._progress_pkg_name = tx_pkg
            self._progress_display_name = get_app_display_name(tx_pkg) if tx_pkg not in ["system", "--all", "all", ""] else "System Packages"
            if hasattr(self, "header_progress_pill"):
                self.header_progress_pill.set_visible(True)
                pill_t = "Updating System" if tx_pkg in ["system", "--all", "all", ""] else f"Updating {self._progress_display_name}"
                self.header_progress_label.set_text(f"⟳ {pill_t} • {int(prog * 100)}%")
            if not getattr(self, "_progress_anim_id", None) and prog < 1.0:
                self._progress_anim_id = GLib.timeout_add(16, self._on_progress_lerp_tick)

            self._populate_updates(self.pm.upgradable_list)
            self._sync_updates_ui_state()
        else:
            if not getattr(self, "_progress_auto_hide_id", None):
                self.updates_progress_box.set_visible(False)
            if not self.pm.updates_checked:
                self.updates_count_label.set_text("Checking for updates...")
                self.updates_count_label.add_css_class("mac-loading-shimmer")
                self.btn_update_all.set_sensitive(False)
                def _bg():
                    upgrades = self.pm.check_updates()
                    GLib.idle_add(lambda: self._populate_updates(upgrades))
                threading.Thread(target=_bg, daemon=True).start()
            else:
                self.updates_count_label.remove_css_class("mac-loading-shimmer")
                self._populate_updates(self.pm.upgradable_list)

    def _populate_updates(self, upgrades: List[Dict[str, str]]):
        self.updates_count_label.remove_css_class("mac-loading-shimmer")
        self.updates_flow_box.remove_all()
        self._updates_buttons.clear()
        self._updates_cards.clear()
        count = len(upgrades)

        active_tx = self.pm.get_active_transaction() if hasattr(self.pm, "get_active_transaction") else None
        is_updating = bool(active_tx and isinstance(active_tx, dict) and active_tx.get("action") in ["update", "upgrade"])
        completed_pkgs = [p.strip().lower() for p in active_tx.get("completed_pkgs", [])] if is_updating else []

        if count == 0:
            self.updates_count_label.set_text("System is up to date")
            self.btn_update_all.set_sensitive(False)
            self.sidebar_updates_badge.set_visible(False)
            empty_lbl = Gtk.Label(label="All official packages and AUR software are up to date.")
            empty_lbl.add_css_class("dim-label")
            empty_lbl.set_margin_top(40)
            self.updates_flow_box.append(empty_lbl)
        else:
            comp_count = sum(1 for u in upgrades if u.get("name", "").strip().lower() in completed_pkgs)
            rem_count = max(0, count - comp_count)

            if is_updating and comp_count > 0:
                self.updates_count_label.set_text(f"{rem_count} Updates Remaining ({comp_count} completed)")
                self.sidebar_updates_badge.set_text(str(rem_count) if rem_count > 0 else "")
            else:
                self.updates_count_label.set_text(f"{count} Updates Available")
                self.sidebar_updates_badge.set_text(str(count))

            self.sidebar_updates_badge.set_visible(rem_count > 0 if is_updating else True)
            self.btn_update_all.set_sensitive(not is_updating)

            for idx, u in enumerate(upgrades):
                name = u["name"]
                pkg = self.pm.packages.get(name, {})
                desc = pkg.get("desc", "System software update")
                u_source = u.get("source", "pacman")
                card = self._create_mac_app_row(
                    name,
                    desc,
                    u_source,
                    is_installed_view=True,
                    update_info={"old_ver": u["old_ver"], "new_ver": u["new_ver"]}
                )
                self._updates_cards[name] = card
                if hasattr(card, "_action_btn"):
                    self._updates_buttons[name] = card._action_btn
                self.updates_flow_box.append(card)
                self._animate_card_entrance(card, idx)

            if is_updating:
                self._sync_updates_ui_state()

    def _sync_updates_ui_state(self):
        """Synchronize updates view buttons, labels, and progress box to the current transaction state."""
        active_tx = self.pm.get_active_transaction() if hasattr(self.pm, "get_active_transaction") else None
        is_active_update = False
        curr_pkg = None
        completed_pkgs = []

        if active_tx and isinstance(active_tx, dict):
            action = active_tx.get("action", "")
            if action in ["update", "upgrade"]:
                is_active_update = True
                curr_pkg = active_tx.get("current_pkg") or active_tx.get("pkg_name")
                completed_pkgs = active_tx.get("completed_pkgs", [])
        elif getattr(self, "_progress_action", None) in ["update", "upgrade"] and getattr(self, "_progress_anim_id", None):
            is_active_update = True
            curr_pkg = getattr(self, "_progress_pkg_name", None)

        if not is_active_update:
            if hasattr(self, "btn_update_all"):
                upgrades_count = len(self.pm.upgradable_list)
                self.btn_update_all.set_sensitive(upgrades_count > 0)
            for pkg_name, btn in self._updates_buttons.items():
                btn.set_sensitive(True)
                btn.set_label("UPDATE")
                btn.remove_css_class("mac-btn-get")
                btn.remove_css_class("mac-btn-installed")
                if not btn.has_css_class("mac-btn-update"):
                    btn.add_css_class("mac-btn-update")
            return

        # An update transaction is active
        if hasattr(self, "btn_update_all"):
            self.btn_update_all.set_sensitive(False)

        curr_norm = curr_pkg.strip().lower() if curr_pkg and curr_pkg not in ["system", "--all", "all", ""] else None
        completed_norm = {p.strip().lower() for p in completed_pkgs if p}

        # Update remaining count label if updating all
        if hasattr(self, "updates_count_label") and len(self._updates_buttons) > 0:
            total_count = len(self._updates_buttons)
            comp_count = sum(1 for name in self._updates_buttons if name.lower() in completed_norm)
            rem_count = max(0, total_count - comp_count)
            if comp_count > 0:
                self.updates_count_label.set_text(f"{rem_count} Updates Remaining ({comp_count} completed)")
                if hasattr(self, "sidebar_updates_badge"):
                    self.sidebar_updates_badge.set_text(str(rem_count) if rem_count > 0 else "")
                    self.sidebar_updates_badge.set_visible(rem_count > 0)

        for pkg_name, btn in self._updates_buttons.items():
            p_lower = pkg_name.strip().lower()
            if curr_norm and p_lower == curr_norm:
                btn.set_label("UPDATING...")
                btn.set_sensitive(False)
                btn.remove_css_class("mac-btn-update")
                btn.remove_css_class("mac-btn-installed")
                if not btn.has_css_class("mac-btn-get"):
                    btn.add_css_class("mac-btn-get")
            elif p_lower in completed_norm:
                btn.set_label("UPDATED")
                btn.set_sensitive(False)
                btn.remove_css_class("mac-btn-update")
                btn.remove_css_class("mac-btn-get")
                if not btn.has_css_class("mac-btn-installed"):
                    btn.add_css_class("mac-btn-installed")
            else:
                btn.set_label("UPDATE")
                btn.set_sensitive(False)
                btn.remove_css_class("mac-btn-get")
                btn.remove_css_class("mac-btn-installed")
                if not btn.has_css_class("mac-btn-update"):
                    btn.add_css_class("mac-btn-update")

    # =========================================================================
    # Page 4: Installed View (Pre-cached Instant 0ms Load + Instant Filter)
    # =========================================================================
    def _build_installed_page(self) -> Gtk.ScrolledWindow:
        scrolled = Gtk.ScrolledWindow()
        scrolled.add_css_class("aura-page")
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(20)
        box.set_margin_bottom(36)
        box.set_margin_start(20)
        box.set_margin_end(20)

        # 1. Header Row
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header_box.set_valign(Gtk.Align.CENTER)

        num_inst = len(self.pm.get_installed_desktop_apps())
        self.installed_header_label = Gtk.Label(label=f"Installed Applications ({num_inst})")
        self.installed_header_label.add_css_class("mac-section-title")
        self.installed_header_label.set_halign(Gtk.Align.START)
        self.installed_header_label.set_ellipsize(Pango.EllipsizeMode.END)
        header_box.append(self.installed_header_label)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header_box.append(spacer)

        # Segmented Switcher
        switch_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        switch_box.add_css_class("mac-segmented-box")

        self.btn_inst_apps = Gtk.ToggleButton(label="Applications")
        self.btn_inst_all = Gtk.ToggleButton(label="All Packages")
        self.btn_inst_all.set_group(self.btn_inst_apps)
        self.btn_inst_apps.set_active(True)

        self.btn_inst_apps.connect("toggled", lambda b: self._on_installed_mode_toggle("apps", b))
        self.btn_inst_all.connect("toggled", lambda b: self._on_installed_mode_toggle("all", b))

        switch_box.append(self.btn_inst_apps)
        switch_box.append(self.btn_inst_all)
        header_box.append(switch_box)

        box.append(header_box)

        # 2. Sleek macOS-Style Search Bar Row
        search_bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        search_bar_box.set_hexpand(True)
        search_bar_box.set_valign(Gtk.Align.CENTER)

        self.installed_search_entry = Gtk.SearchEntry()
        self.installed_search_entry.add_css_class("mac-search-glass-bar")
        self.installed_search_entry.set_placeholder_text("Search installed applications...")
        self.installed_search_entry.set_hexpand(True)
        self.installed_search_entry.connect("changed", self._on_installed_search_changed)
        self.installed_search_entry.connect("stop-search", self._on_installed_stop_search)

        # Key controller for Escape key to clear search
        esc_controller = Gtk.EventControllerKey.new()
        esc_controller.connect("key-pressed", self._on_installed_search_key_pressed)
        self.installed_search_entry.add_controller(esc_controller)

        search_bar_box.append(self.installed_search_entry)
        box.append(search_bar_box)

        # 3. Symmetric Grid with Filter Support
        self.installed_flow_box = self._create_symmetric_grid(min_columns=1, max_columns=4)
        self.installed_flow_box.set_filter_func(self._installed_filter_func)
        box.append(self.installed_flow_box)

        # 4. Clean macOS Empty State Placeholder
        self.installed_empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.installed_empty_box.add_css_class("mac-installed-empty-box")
        self.installed_empty_box.set_halign(Gtk.Align.CENTER)
        self.installed_empty_box.set_valign(Gtk.Align.CENTER)
        self.installed_empty_box.set_margin_top(48)
        self.installed_empty_box.set_margin_bottom(48)
        self.installed_empty_box.set_visible(False)

        empty_icon = Gtk.Image.new_from_icon_name("system-search-symbolic")
        empty_icon.set_pixel_size(48)
        empty_icon.add_css_class("mac-installed-empty-icon")
        self.installed_empty_box.append(empty_icon)

        self.installed_empty_title = Gtk.Label(label="No Installed Apps Found")
        self.installed_empty_title.add_css_class("mac-installed-empty-title")
        self.installed_empty_box.append(self.installed_empty_title)

        self.installed_empty_subtitle = Gtk.Label(label="No installed applications matching your search.")
        self.installed_empty_subtitle.add_css_class("dim-label")
        self.installed_empty_box.append(self.installed_empty_subtitle)

        self.installed_empty_clear_btn = Gtk.Button(label="Clear Search")
        self.installed_empty_clear_btn.add_css_class("mac-btn-get")
        self.installed_empty_clear_btn.set_size_request(120, 32)
        self.installed_empty_clear_btn.set_halign(Gtk.Align.CENTER)
        self.installed_empty_clear_btn.connect("clicked", self._on_installed_clear_search_click)
        self.installed_empty_box.append(self.installed_empty_clear_btn)

        box.append(self.installed_empty_box)

        scrolled.set_child(box)
        return scrolled

    def _on_installed_mode_toggle(self, mode: str, button: Gtk.ToggleButton):
        if button.get_active():
            self._installed_mode = mode
            if hasattr(self, "installed_search_entry"):
                if mode == "apps":
                    self.installed_search_entry.set_placeholder_text("Search installed applications...")
                else:
                    self.installed_search_entry.set_placeholder_text("Search all installed packages...")
            self._load_installed_view()

    def _load_installed_view(self):
        mode = getattr(self, "_installed_mode", "apps")
        query = getattr(self, "installed_search_entry", None)
        q_text = query.get_text().strip().lower() if query else ""

        if mode == "apps":
            apps = self.pm.get_installed_desktop_apps()
            total_apps = len(apps)
            self.sidebar_installed_badge.set_text(str(total_apps))

            # Populate flow box if not cached
            if self._cached_installed_apps_flow is None:
                self.installed_flow_box.remove_all()
                for idx, a in enumerate(apps):
                    card = self._create_mac_app_row(
                        a["name"],
                        a.get("desc", ""),
                        a.get("source", "pacman"),
                        title_override=a.get("display_name", ""),
                        is_installed_view=True,
                        icon_override=a.get("icon", "")
                    )
                    self.installed_flow_box.append(card)
                    self._animate_card_entrance(card, idx)
                self._cached_installed_apps_flow = self.installed_flow_box

            # Apply active filter
            self._filter_installed_apps()
        else:
            self._cached_installed_apps_flow = None
            total_pkgs = len(self.pm.installed_set)

            if not q_text:
                self.installed_header_label.set_text(f"All Packages ({total_pkgs})")
                self.installed_flow_box.set_visible(True)
                self.installed_empty_box.set_visible(False)
                self.installed_flow_box.remove_all()
                installed_names = sorted(list(self.pm.installed_set))
                for name in installed_names[:90]:
                    pkg = self.pm.packages.get(name, {})
                    desc = pkg.get("desc", "Locally installed package")
                    card = self._create_mac_app_row(name, desc, "pacman", is_installed_view=True)
                    self.installed_flow_box.append(card)
            else:
                self._filter_installed_apps()

    def _installed_filter_func(self, child: Gtk.FlowBoxChild) -> bool:
        """Native GTK4 FlowBox filter evaluated in C for instantaneous 0-latency filtering."""
        mode = getattr(self, "_installed_mode", "apps")
        if mode != "apps":
            return True
        query = getattr(self, "_installed_search_query", "").strip().lower()
        if not query:
            return True
        card = child.get_child()
        corpus = getattr(card, "_search_corpus", "")
        if not corpus:
            name = getattr(card, "_pkg_name", "").lower()
            return query in name
        return query in corpus

    def _on_installed_search_changed(self, entry: Gtk.SearchEntry):
        """Instant zero-latency filter trigger."""
        self._filter_installed_apps()

    def _on_installed_stop_search(self, entry: Gtk.SearchEntry):
        """Escape key / Clear icon handler."""
        entry.set_text("")
        self._filter_installed_apps()

    def _on_installed_search_key_pressed(self, controller: Gtk.EventControllerKey, keyval: int, keycode: int, state: Gdk.ModifierType) -> bool:
        if keyval == Gdk.KEY_Escape:
            if hasattr(self, "installed_search_entry") and self.installed_search_entry.get_text():
                self.installed_search_entry.set_text("")
                self._filter_installed_apps()
                return True
        return False

    def _on_installed_clear_search_click(self, button: Gtk.Button):
        """Clear button inside empty state placeholder."""
        if hasattr(self, "installed_search_entry"):
            self.installed_search_entry.set_text("")
            self.installed_search_entry.grab_focus()

    def _filter_installed_apps(self):
        """Core zero-latency filtering and header/empty-state synchronization."""
        entry = getattr(self, "installed_search_entry", None)
        query = entry.get_text().strip().lower() if entry else ""
        self._installed_search_query = query
        mode = getattr(self, "_installed_mode", "apps")

        if mode == "apps":
            if self._cached_installed_apps_flow is None:
                self._load_installed_view()
                return

            total_apps = len(self.pm.get_installed_desktop_apps())

            # Evaluate filter across all cached cards
            self.installed_flow_box.invalidate_filter()

            # Count visible cards
            visible_apps = 0
            child = self.installed_flow_box.get_first_child()
            while child:
                if child.get_child_visible():
                    visible_apps += 1
                child = child.get_next_sibling()

            if not query:
                self.installed_header_label.set_text(f"Installed Applications ({total_apps})")
                self.installed_flow_box.set_visible(True)
                self.installed_empty_box.set_visible(False)
            else:
                self.installed_header_label.set_text(f"Showing {visible_apps} of {total_apps} installed applications")
                if visible_apps == 0:
                    self.installed_flow_box.set_visible(False)
                    self.installed_empty_box.set_visible(True)
                    self.installed_empty_title.set_text("No Installed Applications Found")
                    self.installed_empty_subtitle.set_text(f'No installed applications matching "{entry.get_text().strip()}"')
                else:
                    self.installed_flow_box.set_visible(True)
                    self.installed_empty_box.set_visible(False)
        else:
            # "all" packages mode: in-memory search over installed_set
            total_pkgs = len(self.pm.installed_set)
            if not query:
                self.installed_header_label.set_text(f"All Packages ({total_pkgs})")
                self.installed_flow_box.set_visible(True)
                self.installed_empty_box.set_visible(False)
                self.installed_flow_box.remove_all()
                installed_names = sorted(list(self.pm.installed_set))
                for name in installed_names[:90]:
                    pkg = self.pm.packages.get(name, {})
                    desc = pkg.get("desc", "Locally installed package")
                    card = self._create_mac_app_row(name, desc, "pacman", is_installed_view=True)
                    self.installed_flow_box.append(card)
            else:
                matches = []
                for name in sorted(self.pm.installed_set):
                    pkg = self.pm.packages.get(name, {})
                    desc = pkg.get("desc", "")
                    if query in name.lower() or (desc and query in desc.lower()):
                        matches.append((name, desc or "Locally installed package"))

                count = len(matches)
                self.installed_header_label.set_text(f"Showing {count} of {total_pkgs} packages")
                self.installed_flow_box.remove_all()

                if count == 0:
                    self.installed_flow_box.set_visible(False)
                    self.installed_empty_box.set_visible(True)
                    self.installed_empty_title.set_text("No Installed Packages Found")
                    self.installed_empty_subtitle.set_text(f'No installed packages matching "{entry.get_text().strip()}"')
                else:
                    self.installed_flow_box.set_visible(True)
                    self.installed_empty_box.set_visible(False)
                    for name, desc in matches[:90]:
                        card = self._create_mac_app_row(name, desc, "pacman", is_installed_view=True)
                        self.installed_flow_box.append(card)

    # =========================================================================
    # =========================================================================
    # Page: Docker Applications (Isolated OCI Sandbox + Host Desktop Shortcuts)
    # =========================================================================
    def _build_containers_page(self) -> Gtk.ScrolledWindow:
        scrolled = Gtk.ScrolledWindow()
        scrolled.add_css_class("aura-page")
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(20)
        box.set_margin_bottom(36)
        box.set_margin_start(20)
        box.set_margin_end(20)

        # 1. Page Title Header
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        page_title = Gtk.Label(label="Docker Applications")
        page_title.add_css_class("mac-page-title")
        page_title.set_halign(Gtk.Align.START)
        title_box.append(page_title)

        page_subtitle = Gtk.Label(label="Isolated OCI applications running via Docker with automatic host desktop integration")
        page_subtitle.add_css_class("mac-page-subtitle")
        page_subtitle.set_halign(Gtk.Align.START)
        page_subtitle.set_wrap(True)
        page_subtitle.set_wrap_mode(Pango.WrapMode.WORD)
        page_subtitle.set_lines(2)
        page_subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        page_subtitle.set_max_width_chars(75)
        title_box.append(page_subtitle)
        box.append(title_box)

        # 2. Docker Status & Configuration Spotlight Banner
        status_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        status_card.add_css_class("mac-container-status-card")
        status_card.set_valign(Gtk.Align.CENTER)
        status_card.set_hexpand(True)

        c_icon_box = Gtk.Box()
        c_icon_box.add_css_class("mac-brand-logo-squircle")
        c_icon_box.set_homogeneous(True)
        c_icon_box.set_size_request(56, 56)
        c_icon_box.set_halign(Gtk.Align.CENTER)
        c_icon_box.set_valign(Gtk.Align.CENTER)
        c_icon_box.set_hexpand(False)
        c_icon_box.set_vexpand(False)

        docker_brand_candidates = [
            os.path.join(APP_DIR, "data", "icons", "docker-brand.svg"),
            os.path.join(os.path.expanduser("~"), ".local", "share", "aura", "data", "icons", "docker-brand.svg"),
            os.path.join(APP_DIR, "data", "icons", "docker-desktop.svg"),
        ]
        docker_brand_path = next((p for p in docker_brand_candidates if os.path.exists(p)), "docker-symbolic")
        c_icon = create_scaled_image(docker_brand_path, size=56)
        c_icon.set_halign(Gtk.Align.CENTER)
        c_icon.set_valign(Gtk.Align.CENTER)
        c_icon_box.append(c_icon)
        status_card.append(c_icon_box)

        c_info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        c_info_box.set_hexpand(True)
        c_info_box.set_valign(Gtk.Align.CENTER)

        c_status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        c_status_row.set_valign(Gtk.Align.CENTER)

        self.container_title_lbl = Gtk.Label(label="Aura Box Sandbox")
        self.container_title_lbl.add_css_class("mac-spotlight-title")
        self.container_title_lbl.set_halign(Gtk.Align.START)
        self.container_title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        c_status_row.append(self.container_title_lbl)

        self.container_status_pill = Gtk.Label(label="Checking...")
        self.container_status_pill.add_css_class("mac-container-pill")
        self.container_status_pill.add_css_class("mac-container-pill-pending")
        c_status_row.append(self.container_status_pill)
        c_info_box.append(c_status_row)

        self.container_desc_lbl = Gtk.Label(
            label="Isolated container environment powered by your existing Docker service. Runs apps securely with zero host clutter."
        )
        self.container_desc_lbl.add_css_class("mac-spotlight-desc")
        self.container_desc_lbl.set_halign(Gtk.Align.START)
        self.container_desc_lbl.set_wrap(True)
        self.container_desc_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.container_desc_lbl.set_lines(2)
        self.container_desc_lbl.set_max_width_chars(65)
        c_info_box.append(self.container_desc_lbl)
        status_card.append(c_info_box)

        # Status Action Buttons Box
        c_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        c_btn_box.set_valign(Gtk.Align.CENTER)

        self.btn_configure_container = Gtk.Button(label="Configure")
        self.btn_configure_container.add_css_class("mac-btn-get")
        self.btn_configure_container.set_valign(Gtk.Align.CENTER)
        self.btn_configure_container.set_size_request(130, 34)
        self.btn_configure_container.connect("clicked", self._on_configure_container_click)
        c_btn_box.append(self.btn_configure_container)

        self.btn_container_options = Gtk.Button()
        self.btn_container_options.set_icon_name("view-more-symbolic")
        self.btn_container_options.add_css_class("mac-btn-outline")
        self.btn_container_options.set_tooltip_text("Container Options & Management")
        self.btn_container_options.set_valign(Gtk.Align.CENTER)
        self.btn_container_options.connect("clicked", self._on_container_options_click)
        c_btn_box.append(self.btn_container_options)

        status_card.append(c_btn_box)

        box.append(status_card)

        # 3. Dedicated Docker Search & Filter Bar
        search_filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        search_filter_box.set_valign(Gtk.Align.CENTER)

        self.container_search_entry = Gtk.SearchEntry()
        self.container_search_entry.add_css_class("mac-container-search")
        self.container_search_entry.set_placeholder_text("Search Docker apps...")
        self.container_search_entry.set_hexpand(True)
        self.container_search_entry.connect("search-changed", self._on_container_search_changed)
        search_filter_box.append(self.container_search_entry)

        box.append(search_filter_box)

        # Dedicated Search Status & Spinner Box for smooth animated feedback
        self.container_status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.container_status_box.add_css_class("mac-search-status-box")
        self.container_status_box.set_valign(Gtk.Align.CENTER)

        self.container_spinner = Gtk.Spinner()
        self.container_spinner.add_css_class("mac-search-spinner")
        self.container_spinner.set_visible(False)
        self.container_status_box.append(self.container_spinner)

        self.container_status_lbl = Gtk.Label(label="Isolated container apps powered by Docker")
        self.container_status_lbl.add_css_class("dim-label")
        self.container_status_lbl.set_halign(Gtk.Align.START)
        self.container_status_box.append(self.container_status_lbl)

        box.append(self.container_status_box)

        # 4. Applications Flow Grid
        self.containers_flow_box = self._create_symmetric_grid(min_columns=1, max_columns=4)
        box.append(self.containers_flow_box)

        scrolled.set_child(box)
        return scrolled

    def _load_containers_view(self, query: str = "", update_status: bool = True):
        """Loads and updates the Docker applications grid and status."""
        if update_status:
            status = self.pm.container_mgr.get_status()
            self.container_title_lbl.set_text("Aura Box Sandbox")
            if getattr(self.pm.container_mgr, "is_configuring", False) is True:
                self.container_status_pill.set_text("CONFIGURING...")
                self.container_status_pill.remove_css_class("mac-container-pill-active")
                self.container_status_pill.add_css_class("mac-container-pill-pending")
                prog_raw = getattr(self.pm.container_mgr, "configuring_progress_text", "")
                prog_txt = prog_raw if isinstance(prog_raw, str) and prog_raw else "Configuring container sandbox in the background..."
                self.container_desc_lbl.set_text(prog_txt)
                self.btn_configure_container.set_label("Configuring...")
                self.btn_configure_container.set_sensitive(False)
            elif status["status_code"] == "ready":
                self.container_status_pill.set_text("ACTIVE")
                self.container_status_pill.remove_css_class("mac-container-pill-pending")
                self.container_status_pill.add_css_class("mac-container-pill-active")
                self.container_desc_lbl.set_text("Running securely inside your existing Docker system. Host MySQL and services remain untouched.")
                self.btn_configure_container.set_label("Rebuild")
            elif status["status_code"] == "stopped":
                self.container_status_pill.set_text("PAUSED")
                self.container_status_pill.remove_css_class("mac-container-pill-active")
                self.container_status_pill.add_css_class("mac-container-pill-pending")
                self.container_desc_lbl.set_text("Aura Box sandbox container is paused. Click Start Sandbox to resume.")
                self.btn_configure_container.set_label("Start Sandbox")
            elif status["status_code"] == "missing_container":
                self.container_status_pill.set_text("STANDBY")
                self.container_status_pill.remove_css_class("mac-container-pill-active")
                self.container_status_pill.add_css_class("mac-container-pill-pending")
                self.container_desc_lbl.set_text("Docker daemon active. Initialize the aura-box container to run isolated sandbox applications.")
                self.btn_configure_container.set_label("Initialize")
            else:
                self.container_status_pill.set_text("AUTO-SETUP")
                self.container_status_pill.remove_css_class("mac-container-pill-active")
                self.container_status_pill.add_css_class("mac-container-pill-pending")
                self.container_desc_lbl.set_text("Docker daemon is not active. Click Initialize to configure sandbox.")
                self.btn_configure_container.set_label("Initialize")

        self._search_containers_async(query)

    def _on_container_search_changed(self, entry: Gtk.SearchEntry):
        q = entry.get_text().strip()
        if hasattr(self, "_container_search_timer") and self._container_search_timer:
            GLib.source_remove(self._container_search_timer)
            self._container_search_timer = None

        if hasattr(self, "container_spinner"):
            self.container_spinner.set_visible(True)
            self.container_spinner.start()
        if hasattr(self, "container_status_lbl"):
            self.container_status_lbl.set_text(f"Searching Docker sandbox apps for '{q}'..." if q else "Loading Docker apps...")
            self.container_status_lbl.add_css_class("mac-loading-shimmer")

        self._container_search_timer = GLib.timeout_add(180, self._trigger_container_search, q)

    def _trigger_container_search(self, q: str) -> bool:
        self._container_search_timer = None
        self._search_containers_async(q)
        return False

    def _search_containers_async(self, query: str):
        if not hasattr(self, "_container_req_id"):
            self._container_req_id = 0
        self._container_req_id += 1
        req_id = self._container_req_id

        def _bg():
            apps = self.pm.container_mgr.list_apps(query)
            def _ui():
                if req_id != self._container_req_id:
                    return
                if hasattr(self, "container_spinner"):
                    self.container_spinner.stop()
                    self.container_spinner.set_visible(False)
                if hasattr(self, "container_status_lbl"):
                    self.container_status_lbl.remove_css_class("mac-loading-shimmer")
                    if query:
                        count = len(apps)
                        self.container_status_lbl.set_text(f"Found {count} Docker application{'s' if count != 1 else ''} matching '{query}'")
                    else:
                        self.container_status_lbl.set_text("Isolated container apps powered by Docker")
                self.containers_flow_box.remove_all()
                for idx, a in enumerate(apps):
                    card = self._create_container_app_card(a)
                    self.containers_flow_box.append(card)
                    self._animate_card_entrance(card, idx)
            GLib.idle_add(_ui)

        threading.Thread(target=_bg, daemon=True).start()

    def _on_configure_container_click(self, btn: Gtk.Button):
        btn.set_sensitive(False)
        self.container_status_pill.set_text("CONFIGURING...")
        self.show_toast("Initializing Docker environment in background...")

        def _bg():
            ok, msg = self.pm.container_mgr.ensure_container_configured(
                progress_callback=lambda s: GLib.idle_add(lambda: self.container_desc_lbl.set_text(str(s)))
            )
            def _ui():
                btn.set_sensitive(True)
                self._load_containers_view(self.container_search_entry.get_text())
                if ok:
                    self.show_toast("✓ Docker container configured and ready!")
                else:
                    self.show_toast(f"Setup warning: {msg}")
            GLib.idle_add(_ui)

        threading.Thread(target=_bg, daemon=True).start()

    def _on_container_options_click(self, btn: Gtk.Button):
        dlg = Adw.AlertDialog.new(
            "Docker Sandbox Options",
            "Manage the 'aura-box' isolated container and Docker system integration."
        )
        status = self.pm.container_mgr.get_status()
        if status.get("container_running"):
            dlg.add_response("pause", "Pause Sandbox")
        elif status.get("container_exists"):
            dlg.add_response("start", "Start Sandbox")

        dlg.add_response("remove", "Remove Sandbox & Shortcuts")
        dlg.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)

        dlg.add_response("disable_service", "Disable Docker Service")
        dlg.set_response_appearance("disable_service", Adw.ResponseAppearance.DESTRUCTIVE)

        dlg.add_response("cancel", "Cancel")

        def _on_resp(dialog, resp_id):
            if resp_id == "pause":
                self.show_toast("Pausing aura-box sandbox...")
                self.pm.container_mgr.stop_container(
                    lambda ok, msg: GLib.idle_add(lambda: (self.show_toast("Sandbox paused." if ok else msg), self._load_containers_view()))
                )
            elif resp_id == "start":
                self.show_toast("Starting aura-box sandbox...")
                self._on_configure_container_click(self.btn_configure_container)
            elif resp_id == "remove":
                self._confirm_remove_sandbox()
            elif resp_id == "disable_service":
                self._confirm_disable_docker()

        dlg.connect("response", _on_resp)
        dlg.present(self)

    def _confirm_remove_sandbox(self):
        dlg = Adw.AlertDialog.new(
            "Remove Aura Box Sandbox?",
            "This will delete the 'aura-box' container and purge all associated host desktop shortcuts.\nAny containerized apps will need to be re-downloaded if reinitialized."
        )
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("remove", "Remove Sandbox")
        dlg.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)

        def _on_resp(dialog, resp_id):
            if resp_id == "remove":
                self.show_toast("Removing aura-box sandbox...")
                self.pm.container_mgr.remove_container(
                    True,
                    lambda ok, msg: GLib.idle_add(lambda: (self.show_toast(msg), self._load_containers_view()))
                )

        dlg.connect("response", _on_resp)
        dlg.present(self)

    def _confirm_disable_docker(self):
        dlg = Adw.AlertDialog.new(
            "Disable Docker Service?",
            "This will stop and disable docker.service via systemctl.\nAura Box sandbox will be unavailable until Docker is re-enabled."
        )
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("disable", "Disable Docker")
        dlg.set_response_appearance("disable", Adw.ResponseAppearance.DESTRUCTIVE)

        def _on_resp(dialog, resp_id):
            if resp_id == "disable":
                self.show_toast("Disabling Docker service...")
                self.pm.container_mgr.disable_docker_system_service(
                    False,
                    lambda ok, msg: GLib.idle_add(lambda: (self.show_toast(msg), self._load_containers_view()))
                )

        dlg.connect("response", _on_resp)
        dlg.present(self)

    def _create_container_app_card(self, app: Dict[str, Any]) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        card.add_css_class("mac-app-row")
        card.add_css_class("mac-container-card")
        card.set_hexpand(True)
        card.set_valign(Gtk.Align.FILL)

        # 1. 54x54 Squircle App Icon Container (Rigid, Non-expanding, Dead-Center)
        icon_name = app.get("icon", "application-x-executable")
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        if theme.has_icon(icon_name):
            icon_target = icon_name
        elif theme.has_icon(app["id"]):
            icon_target = app["id"]
        else:
            icon_target = "docker-symbolic"

        icon_box = Gtk.Box()
        icon_box.add_css_class("mac-squircle")
        icon_box.set_homogeneous(True)
        icon_box.set_valign(Gtk.Align.CENTER)
        icon_box.set_halign(Gtk.Align.CENTER)
        icon_box.set_size_request(54, 54)
        icon_box.set_hexpand(False)
        icon_box.set_vexpand(False)

        img = create_scaled_image(icon_target, size=40)
        img.set_halign(Gtk.Align.CENTER)
        img.set_valign(Gtk.Align.CENTER)
        icon_box.append(img)
        card.append(icon_box)

        # 2. Information Column
        info_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_col.set_hexpand(True)
        info_col.set_valign(Gtk.Align.CENTER)

        name_lbl = Gtk.Label(label=app["name"])
        name_lbl.add_css_class("mac-app-title")
        name_lbl.set_halign(Gtk.Align.FILL)
        name_lbl.set_xalign(0.0)
        name_lbl.set_hexpand(True)
        name_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        info_col.append(name_lbl)

        desc = app.get("desc", "")
        cat = app.get("category", "")
        if app.get("is_installed"):
            sub_text = f"{desc} • Active shortcut" if desc else "Desktop shortcut active"
        elif desc and cat and cat not in ("Container", "Development"):
            sub_text = f"{desc} • {cat}"
        elif desc:
            sub_text = desc
        else:
            sub_text = "Docker container application"

        desc_lbl = Gtk.Label(label=sub_text)
        desc_lbl.add_css_class("mac-app-desc")
        desc_lbl.set_halign(Gtk.Align.FILL)
        desc_lbl.set_xalign(0.0)
        desc_lbl.set_hexpand(True)
        desc_lbl.set_wrap(True)
        desc_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        desc_lbl.set_lines(2)
        desc_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        info_col.append(desc_lbl)

        card.append(info_col)

        # 3. Action Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_valign(Gtk.Align.CENTER)

        app_id = app["id"]
        is_installed = app.get("is_installed", False)
        is_installing = app.get("is_installing", False)

        if is_installing:
            btn_inst = Gtk.Button(label="INSTALLING...")
            btn_inst.add_css_class("mac-btn-installed")
            btn_inst.set_sensitive(False)
            btn_inst.set_size_request(96, 32)
            btn_box.append(btn_inst)
            btn_get = None
        elif is_installed:
            btn_open = Gtk.Button(label="OPEN")
            btn_open.add_css_class("mac-btn-open")
            btn_open.set_valign(Gtk.Align.CENTER)
            btn_open.set_size_request(74, 30)
            btn_open.connect("clicked", lambda b, aid=app_id: self.pm.container_mgr.launch_app(aid))
            btn_box.append(btn_open)

            btn_uninst = Gtk.Button()
            btn_uninst.add_css_class("mac-btn-trash")
            trash_img = Gtk.Image.new_from_icon_name("user-trash-symbolic")
            trash_img.set_pixel_size(15)
            btn_uninst.set_child(trash_img)
            btn_uninst.set_valign(Gtk.Align.CENTER)
            btn_uninst.set_size_request(30, 30)
            btn_uninst.set_tooltip_text(f"Uninstall {app['name']}")
            btn_uninst.connect("clicked", lambda b, aid=app_id, aname=app["name"]: self._confirm_container_uninstall(aid, aname, b))
            btn_box.append(btn_uninst)
            btn_get = None
        else:
            btn_get = Gtk.Button(label="GET")
            btn_get.add_css_class("mac-btn-get")
            btn_get.set_valign(Gtk.Align.CENTER)
            btn_get.set_size_request(88, 32)
            btn_get.connect("clicked", lambda b, aid=app_id, aname=app["name"]: self._confirm_container_install(aid, aname, b))
            btn_box.append(btn_get)

        card.append(btn_box)

        primary_btn = btn_get if btn_get is not None else (btn_inst if is_installing else btn_open)
        card._action_btn = primary_btn
        card._pkg_name = app_id
        card._source = "docker"
        if hasattr(self, "_registered_cards"):
            self._registered_cards.setdefault(app_id.strip().lower(), []).append(card)

        card.set_cursor(Gdk.Cursor.new_from_name("pointer"))
        def _on_card_click(gesture, n_press, x, y, aid=app_id):
            picked = card.pick(x, y, Gtk.PickFlags.INSENSITIVE)
            if picked is not None and (picked == btn_box or btn_box.is_ancestor(picked)):
                return
            alloc = btn_box.compute_bounds(card)
            if alloc[0]:
                rect = alloc[1]
                rx, ry = rect.get_x(), rect.get_y()
                rw, rh = rect.get_width(), rect.get_height()
                if rx <= x <= rx + rw and ry <= y <= ry + rh:
                    return
            self._open_package_detail(aid, "docker")

        card_gesture = Gtk.GestureClick()
        card_gesture.connect("released", _on_card_click)
        card.add_controller(card_gesture)

        return card

    def _confirm_container_install(self, app_id: str, app_name: str, button: Gtk.Button):
        # Direct 1-click install into isolated aura-box container without blocking modal dialog
        self._execute_container_install(app_id, app_name, button)

    def _execute_container_install(self, app_id: str, app_name: str, button: Optional[Gtk.Button]):
        if self.pm.container_mgr.is_app_installing(app_id):
            return
        if button:
            button.set_sensitive(False)
            button.set_label("INSTALLING...")
        self._start_smooth_progress("install", app_id, display_name=app_name, source="docker", target_view="detail")

        def _progress(msg):
            GLib.idle_add(lambda: self._on_progress_update(0.55, str(msg), pkg_name=app_id))

        def _completion(ok, msg):
            def _ui():
                self._finish_smooth_progress(ok, "install", app_id, "" if ok else str(msg))
                self.show_toast(msg)
                self.pm.refresh_installed()
                self._cached_installed_apps_flow = None
                if hasattr(self, "sidebar_installed_badge"):
                    self.sidebar_installed_badge.set_text(str(len(self.pm.get_installed_desktop_apps())))
                self._load_containers_view(self.container_search_entry.get_text(), update_status=False)
                self._sync_all_cards()
            GLib.idle_add(_ui)

        self.pm.container_mgr.install_app(app_id, progress_callback=_progress, completion_callback=_completion)

    def _confirm_container_uninstall(self, app_id: str, app_name: str, button: Optional[Gtk.Button]):
        dlg = Adw.AlertDialog.new(
            f"Uninstall {app_name}?",
            f"Are you sure you want to uninstall {app_name}?\nThis will remove the desktop shortcut and clean up container files."
        )
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("uninstall", "Uninstall")
        dlg.set_response_appearance("uninstall", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("cancel")
        dlg.set_close_response("cancel")
        def _on_response(d, resp):
            if resp == "uninstall":
                self._execute_container_uninstall(app_id, app_name, button)
        dlg.connect("response", _on_response)
        dlg.present(self)

    def _execute_container_uninstall(self, app_id: str, app_name: str, button: Optional[Gtk.Button]):
        if button:
            button.set_sensitive(False)
        self._start_smooth_progress("remove", app_id, display_name=app_name, source="docker", target_view="detail")

        def _progress(msg):
            GLib.idle_add(lambda: self._on_progress_update(0.6, str(msg), pkg_name=app_id))

        def _completion(ok, msg):
            def _ui():
                self._finish_smooth_progress(ok, "remove", app_id, "" if ok else str(msg))
                self.show_toast(msg)
                self.pm.refresh_installed()
                self._cached_installed_apps_flow = None
                if hasattr(self, "sidebar_installed_badge"):
                    self.sidebar_installed_badge.set_text(str(len(self.pm.get_installed_desktop_apps())))
                if self.main_stack.get_visible_child_name() == "installed":
                    self._load_installed_view()
                else:
                    self._load_containers_view(self.container_search_entry.get_text(), update_status=False)
                self._sync_all_cards()
            GLib.idle_add(_ui)

        self.pm.container_mgr.uninstall_app(app_id, progress_callback=_progress, completion_callback=_completion)

    # =========================================================================
    # Page: Snap Store (Universal Linux packages with isolated sandbox)
    # =========================================================================
    def _build_snap_page(self) -> Gtk.ScrolledWindow:
        scrolled = Gtk.ScrolledWindow()
        scrolled.add_css_class("aura-page")
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(20)
        box.set_margin_bottom(36)
        box.set_margin_start(20)
        box.set_margin_end(20)

        # 1. Header with Title & Subtitle
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        page_title = Gtk.Label(label="Snap Store")
        page_title.add_css_class("mac-page-title")
        page_title.set_halign(Gtk.Align.START)
        title_box.append(page_title)

        page_subtitle = Gtk.Label(label="Universal Linux packages with isolated sandbox & automatic updates from Canonical")
        page_subtitle.add_css_class("mac-page-subtitle")
        page_subtitle.set_halign(Gtk.Align.START)
        page_subtitle.set_wrap(True)
        page_subtitle.set_wrap_mode(Pango.WrapMode.WORD)
        page_subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        title_box.append(page_subtitle)
        box.append(title_box)

        # 2. Canonical Snap Status Spotlight Banner
        snap_status_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        snap_status_card.add_css_class("mac-container-status-card")
        snap_status_card.set_valign(Gtk.Align.CENTER)
        snap_status_card.set_hexpand(True)

        snap_logo_box = Gtk.Box()
        snap_logo_box.add_css_class("mac-brand-logo-squircle")
        snap_logo_box.set_homogeneous(True)
        snap_logo_box.set_size_request(56, 56)
        snap_logo_box.set_halign(Gtk.Align.CENTER)
        snap_logo_box.set_valign(Gtk.Align.CENTER)
        snap_logo_box.set_hexpand(False)
        snap_logo_box.set_vexpand(False)

        snap_brand_candidates = [
            os.path.join(APP_DIR, "data", "icons", "snap-brand.svg"),
            os.path.join(os.path.expanduser("~"), ".local", "share", "aura", "data", "icons", "snap-brand.svg"),
        ]
        snap_brand_path = next((p for p in snap_brand_candidates if os.path.exists(p)), "snap-brand")
        snap_logo_icon = create_scaled_image(snap_brand_path, size=56)
        snap_logo_icon.set_halign(Gtk.Align.CENTER)
        snap_logo_icon.set_valign(Gtk.Align.CENTER)
        snap_logo_box.append(snap_logo_icon)
        snap_status_card.append(snap_logo_box)

        snap_info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        snap_info_box.set_hexpand(True)
        snap_info_box.set_valign(Gtk.Align.CENTER)

        snap_status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        snap_status_row.set_valign(Gtk.Align.CENTER)

        self.snap_title_lbl = Gtk.Label(label="Canonical Snap Service")
        self.snap_title_lbl.add_css_class("mac-spotlight-title")
        self.snap_title_lbl.set_halign(Gtk.Align.START)
        self.snap_title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        snap_status_row.append(self.snap_title_lbl)

        self.snap_status_pill = Gtk.Label(label="Checking...")
        self.snap_status_pill.add_css_class("mac-container-pill")
        self.snap_status_pill.add_css_class("mac-container-pill-pending")
        snap_status_row.append(self.snap_status_pill)
        snap_info_box.append(snap_status_row)

        self.snap_desc_lbl = Gtk.Label(
            label="Universal Linux packages with isolated sandbox & automatic updates from Canonical's official store."
        )
        self.snap_desc_lbl.add_css_class("mac-spotlight-desc")
        self.snap_desc_lbl.set_halign(Gtk.Align.START)
        self.snap_desc_lbl.set_wrap(True)
        self.snap_desc_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.snap_desc_lbl.set_lines(2)
        self.snap_desc_lbl.set_max_width_chars(65)
        snap_info_box.append(self.snap_desc_lbl)
        snap_status_card.append(snap_info_box)

        # Action Buttons Box
        snap_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        snap_btn_box.set_valign(Gtk.Align.CENTER)

        self.btn_configure_snap = Gtk.Button(label="Auto-Configure")
        self.btn_configure_snap.add_css_class("mac-btn-get")
        self.btn_configure_snap.set_valign(Gtk.Align.CENTER)
        self.btn_configure_snap.set_size_request(130, 34)
        self.btn_configure_snap.connect("clicked", self._on_configure_snap_click)
        snap_btn_box.append(self.btn_configure_snap)

        self.btn_snap_options = Gtk.Button()
        self.btn_snap_options.set_icon_name("view-more-symbolic")
        self.btn_snap_options.add_css_class("mac-btn-outline")
        self.btn_snap_options.set_tooltip_text("Snap Store Options & Management")
        self.btn_snap_options.set_valign(Gtk.Align.CENTER)
        self.btn_snap_options.connect("clicked", self._on_snap_options_click)
        snap_btn_box.append(self.btn_snap_options)

        snap_status_card.append(snap_btn_box)
        box.append(snap_status_card)

        # 3. Search Entry specifically for snaps
        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        search_box.set_valign(Gtk.Align.CENTER)

        self.snap_search_entry = Gtk.SearchEntry()
        self.snap_search_entry.add_css_class("mac-search-glass-bar")
        self.snap_search_entry.set_placeholder_text("Search Canonical Snap Store...")
        self.snap_search_entry.set_hexpand(True)
        self.snap_search_entry.connect("search-changed", self._on_snap_search_changed)
        search_box.append(self.snap_search_entry)
        box.append(search_box)

        # 4. Status Box with Spinner & Label
        self.snap_status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.snap_status_box.add_css_class("mac-search-status-box")
        self.snap_status_box.set_valign(Gtk.Align.CENTER)

        self.snap_spinner = Gtk.Spinner()
        self.snap_spinner.add_css_class("mac-search-spinner")
        self.snap_spinner.set_visible(False)
        self.snap_status_box.append(self.snap_spinner)

        self.snap_status_lbl = Gtk.Label(label="Curated top software from Canonical Snap Store")
        self.snap_status_lbl.add_css_class("dim-label")
        self.snap_status_lbl.set_halign(Gtk.Align.START)
        self.snap_status_box.append(self.snap_status_lbl)

        box.append(self.snap_status_box)

        # 5. Symmetrical Grid
        self.snap_flow_box = self._create_symmetric_grid(min_columns=1, max_columns=4)
        box.append(self.snap_flow_box)

        scrolled.set_child(box)
        return scrolled

    def _load_snap_view(self, query: str = "", force_refresh: bool = False):
        """Loads and populates curated and searched snap packages and updates status."""
        snap_st = self.pm.snap_mgr.get_status()
        if snap_st["status_code"] == "ready":
            self.snap_status_pill.set_text("ACTIVE")
            self.snap_status_pill.remove_css_class("mac-container-pill-pending")
            self.snap_status_pill.add_css_class("mac-container-pill-active")
            self.snap_desc_lbl.set_text("Snap daemon (snapd.socket) is active and running. Confinement symlink /snap is configured.")
            self.btn_configure_snap.set_label("Ready")
            self.btn_configure_snap.set_sensitive(False)
            self.btn_snap_options.set_visible(True)
        elif getattr(self.pm.snap_mgr, "is_setting_up", False) is True:
            self.snap_status_pill.set_text("CONFIGURING...")
            self.snap_status_pill.remove_css_class("mac-container-pill-active")
            self.snap_status_pill.add_css_class("mac-container-pill-pending")
            prog_raw = getattr(self.pm.snap_mgr, "setup_progress_text", "")
            prog_txt = prog_raw if isinstance(prog_raw, str) and prog_raw else "Auto-configuring Canonical snapd service in background..."
            self.snap_desc_lbl.set_text(prog_txt)
            self.btn_configure_snap.set_label("Configuring...")
            self.btn_configure_snap.set_sensitive(False)
            self.btn_snap_options.set_visible(False)
        else:
            self.snap_status_pill.set_text("AUTO-SETUP")
            self.snap_status_pill.remove_css_class("mac-container-pill-active")
            self.snap_status_pill.add_css_class("mac-container-pill-pending")
            self.snap_desc_lbl.set_text("Snapd service is not configured. Click Auto-Configure to install snapd, enable socket, and configure /snap.")
            self.btn_configure_snap.set_label("Auto-Configure")
            self.btn_configure_snap.set_sensitive(True)
            self.btn_snap_options.set_visible(False)

        q = query.strip()
        if hasattr(self, "_snap_search_timer") and self._snap_search_timer:
            GLib.source_remove(self._snap_search_timer)
            self._snap_search_timer = None

        if not q:
            # If curated catalog is already populated and not marked dirty, keep existing widgets (0ms instantaneous transition)
            if not force_refresh and getattr(self, "_snap_curated_populated", False) and not getattr(self, "_snap_curated_dirty", False):
                if hasattr(self, "snap_spinner"):
                    self.snap_spinner.stop()
                    self.snap_spinner.set_visible(False)
                self.snap_status_lbl.remove_css_class("mac-loading-shimmer")
                self.snap_status_lbl.set_text("Curated top software from Canonical Snap Store")
                return

            if hasattr(self, "snap_spinner"):
                self.snap_spinner.set_visible(True)
                self.snap_spinner.start()
            self.snap_status_lbl.set_text("Loading Canonical Snap Store catalog...")
            self.snap_status_lbl.add_css_class("mac-loading-shimmer")

            # Show skeleton placeholder cards if grid is empty
            if not self.snap_flow_box.get_first_child():
                for _ in range(6):
                    self.snap_flow_box.append(self._create_snap_skeleton_card())

            def _populate_curated():
                curated = list(self.pm.snap_mgr.CURATED_SNAP_APPS)
                self.snap_flow_box.remove_all()
                for snap in curated:
                    card = self._create_snap_app_card(snap)
                    self.snap_flow_box.append(card)
                if hasattr(self, "snap_spinner"):
                    self.snap_spinner.stop()
                    self.snap_spinner.set_visible(False)
                self.snap_status_lbl.remove_css_class("mac-loading-shimmer")
                self.snap_status_lbl.set_text("Curated top software from Canonical Snap Store")
                self._snap_curated_populated = True
                self._snap_curated_dirty = False
                self._sync_responsive_cols()
                return False

            GLib.idle_add(_populate_curated)
        else:
            self._snap_curated_dirty = True
            if hasattr(self, "snap_spinner"):
                self.snap_spinner.set_visible(True)
                self.snap_spinner.start()
            self.snap_status_lbl.set_text(f"Searching Canonical Snap Store for '{query}'...")
            self.snap_status_lbl.add_css_class("mac-loading-shimmer")
            self._search_snaps_online(query)

    def _create_snap_skeleton_card(self) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        card.add_css_class("mac-app-row")
        card.add_css_class("mac-loading-shimmer")
        card.set_hexpand(True)
        card.set_valign(Gtk.Align.FILL)

        sq = Gtk.Box()
        sq.add_css_class("mac-squircle")
        sq.set_size_request(54, 54)
        card.append(sq)

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        col.set_hexpand(True)
        col.set_valign(Gtk.Align.CENTER)

        t_bar = Gtk.Box()
        t_bar.add_css_class("mac-stat-card")
        t_bar.set_size_request(130, 14)
        t_bar.set_halign(Gtk.Align.START)
        col.append(t_bar)

        d_bar = Gtk.Box()
        d_bar.add_css_class("mac-stat-card")
        d_bar.set_size_request(190, 10)
        d_bar.set_halign(Gtk.Align.START)
        col.append(d_bar)

        card.append(col)

        btn = Gtk.Box()
        btn.add_css_class("mac-btn-get")
        btn.set_size_request(88, 32)
        btn.set_valign(Gtk.Align.CENTER)
        card.append(btn)
        return card

    def _on_configure_snap_click(self, btn: Gtk.Button):
        btn.set_sensitive(False)
        self.snap_status_pill.set_text("CONFIGURING...")
        self.show_toast("Configuring Canonical Snap service in background...")

        def _prog(frac, msg):
            GLib.idle_add(lambda: self.snap_desc_lbl.set_text(str(msg)))

        def _done(ok, msg):
            def _ui():
                btn.set_sensitive(True)
                self._snap_curated_dirty = True
                self._load_snap_view(self.snap_search_entry.get_text(), force_refresh=True)
                if ok:
                    self.show_toast("✓ " + msg)
                else:
                    self.show_toast("Setup notice: " + msg)
            GLib.idle_add(_ui)

        self.pm.snap_mgr.setup_snapd(progress_callback=_prog, completion_callback=_done)

    def _on_snap_options_click(self, btn: Gtk.Button):
        dlg = Adw.AlertDialog.new(
            "Snap Service Options",
            "Manage Canonical snapd service and local integration."
        )
        dlg.add_response("disable", "Disable snapd Service")
        dlg.set_response_appearance("disable", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.add_response("purge", "Disable & Remove snapd Package")
        dlg.set_response_appearance("purge", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.add_response("cancel", "Cancel")

        def _on_resp(dialog, resp_id):
            if resp_id in ("disable", "purge"):
                purge = (resp_id == "purge")
                self.show_toast("Disabling snapd...")
                self.pm.snap_mgr.disable_snapd(
                    purge_packages=purge,
                    progress_callback=lambda f, m: GLib.idle_add(lambda: self.snap_desc_lbl.set_text(str(m))),
                    completion_callback=lambda ok, m: GLib.idle_add(lambda: (setattr(self, "_snap_curated_dirty", True), self.show_toast(m), self._load_snap_view(force_refresh=True)))
                )

        dlg.connect("response", _on_resp)
        dlg.present(self)

    def _on_snap_search_changed(self, entry: Gtk.SearchEntry):
        q = entry.get_text().strip()
        if hasattr(self, "_snap_search_timer") and self._snap_search_timer:
            GLib.source_remove(self._snap_search_timer)
            self._snap_search_timer = None

        if q:
            if hasattr(self, "snap_spinner"):
                self.snap_spinner.set_visible(True)
                self.snap_spinner.start()
            if hasattr(self, "snap_status_lbl"):
                self.snap_status_lbl.set_text(f"Searching Canonical Snap Store for '{q}'...")
                self.snap_status_lbl.add_css_class("mac-loading-shimmer")

        self._snap_search_timer = GLib.timeout_add(220, self._trigger_snap_search, q)

    def _trigger_snap_search(self, q: str) -> bool:
        self._snap_search_timer = None
        self._load_snap_view(q)
        return False

    def _search_snaps_online(self, query: str):
        if not hasattr(self, "_snap_req_id"):
            self._snap_req_id = 0
        self._snap_req_id += 1
        req_id = self._snap_req_id

        def _bg():
            # Query backend SnapManager which searches the live Snapcraft catalog
            snaps = self.pm.snap_mgr.search_snaps(query)

            def _ui():
                if req_id != self._snap_req_id:
                    return
                if hasattr(self, "snap_spinner"):
                    self.snap_spinner.stop()
                    self.snap_spinner.set_visible(False)
                self.snap_status_lbl.remove_css_class("mac-loading-shimmer")
                self.snap_flow_box.remove_all()
                if snaps:
                    seen = set()
                    for s in snaps[:60]:
                        s_name = s.get("name")
                        if s_name and s_name not in seen:
                            seen.add(s_name)
                            self.snap_flow_box.append(self._create_snap_app_card(s))
                    self.snap_status_lbl.set_text(f"Found {len(seen)} snaps matching '{query}' in Canonical Snap Store")
                else:
                    self.snap_status_lbl.set_text(f"No snaps found matching '{query}'. Try checking spelling.")
                    empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
                    empty_box.set_margin_top(40)
                    empty_lbl = Gtk.Label(label=f"No snap packages found matching '{query}'.")
                    empty_lbl.add_css_class("dim-label")
                    empty_box.append(empty_lbl)
                    self.snap_flow_box.append(empty_box)

            GLib.idle_add(_ui)

        threading.Thread(target=_bg, daemon=True).start()

    def _create_snap_app_card(self, snap: Dict[str, Any]) -> Gtk.Box:
        name = snap.get("name", "")
        title = snap.get("title") or get_app_display_name(name)
        summary = snap.get("summary") or snap.get("desc", "")
        publisher = snap.get("publisher", "Canonical")
        icon_target = snap.get("icon") or resolve_icon_name(name, summary)

        is_inst = False
        try:
            if hasattr(self.pm, "snap_mgr") and self.pm.snap_mgr:
                is_inst = self.pm.snap_mgr.is_snap_installed(name)
        except Exception:
            is_inst = False
        has_desktop = is_inst and bool(self.pm.detect_desktop_entry(name))

        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        card.add_css_class("mac-app-row")
        card.add_css_class("mac-snap-card")
        card.set_hexpand(True)
        card.set_valign(Gtk.Align.FILL)
        card.set_cursor(Gdk.Cursor.new_from_name("pointer", None))

        # 1. 54x54 Squircle App Icon
        icon_box = Gtk.Box()
        icon_box.add_css_class("mac-squircle")
        icon_box.set_homogeneous(True)
        icon_box.set_valign(Gtk.Align.CENTER)
        icon_box.set_halign(Gtk.Align.CENTER)
        icon_box.set_size_request(54, 54)
        icon_box.set_hexpand(False)
        icon_box.set_vexpand(False)
        icon_box.set_cursor(Gdk.Cursor.new_from_name("pointer", None))

        img = create_scaled_image(icon_target, size=40)
        img.set_halign(Gtk.Align.CENTER)
        img.set_valign(Gtk.Align.CENTER)
        icon_box.append(img)
        card.append(icon_box)

        # 2. Information Column (Harmonized with _create_mac_app_row)
        info_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_col.set_hexpand(True)
        info_col.set_valign(Gtk.Align.CENTER)

        title_lbl = Gtk.Label(label=title)
        title_lbl.add_css_class("mac-app-title")
        title_lbl.set_halign(Gtk.Align.FILL)
        title_lbl.set_xalign(0.0)
        title_lbl.set_hexpand(True)
        title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        info_col.append(title_lbl)

        if summary and publisher and publisher.lower() not in ("canonical", "snapcraft"):
            sub_text = f"{summary} • by {publisher}"
        elif summary:
            sub_text = summary
        elif publisher:
            sub_text = f"Snap package by {publisher}"
        else:
            sub_text = "Canonical Snap package"

        desc_lbl = Gtk.Label(label=sub_text)
        desc_lbl.add_css_class("mac-app-desc")
        desc_lbl.set_halign(Gtk.Align.FILL)
        desc_lbl.set_xalign(0.0)
        desc_lbl.set_hexpand(True)
        desc_lbl.set_wrap(True)
        desc_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        desc_lbl.set_lines(2)
        desc_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        info_col.append(desc_lbl)

        card.append(info_col)

        # 3. Action Button (GET / OPEN / INSTALLED / UPDATING... / INSTALLING... / QUEUED)
        if hasattr(self.pm, "is_pkg_updating") and self.pm.is_pkg_updating(name):
            action_btn = Gtk.Button(label="UPDATING...")
            action_btn.add_css_class("mac-btn-get")
            action_btn.set_sensitive(False)
        elif hasattr(self.pm, "is_pkg_installing") and self.pm.is_pkg_installing(name):
            action_btn = Gtk.Button(label="INSTALLING...")
            action_btn.add_css_class("mac-btn-get")
            action_btn.set_sensitive(False)
        elif hasattr(self.pm, "is_pkg_queued") and self.pm.is_pkg_queued(name):
            action_btn = Gtk.Button(label="QUEUED")
            action_btn.add_css_class("mac-btn-queued")
            action_btn.set_sensitive(False)
        elif is_inst:
            if has_desktop:
                action_btn = Gtk.Button(label="OPEN")
                action_btn.add_css_class("mac-btn-open")
                action_btn.connect("clicked", lambda b, n=name, s="snap": self._open_or_launch(n, s))
            else:
                action_btn = Gtk.Button(label="INSTALLED")
                action_btn.add_css_class("mac-btn-installed")
                action_btn.connect("clicked", lambda b, n=name, s="snap": self._open_package_detail(n, s))
        else:
            action_btn = Gtk.Button(label="GET")
            action_btn.add_css_class("mac-btn-get")
            action_btn.connect("clicked", lambda b, n=name, s="snap": self._install_from_card(n, s, b))

        action_btn.set_valign(Gtk.Align.CENTER)
        action_btn.set_halign(Gtk.Align.END)
        action_btn.set_hexpand(False)
        action_btn.set_vexpand(False)
        action_btn.set_size_request(80, 30)
        action_btn.set_cursor(Gdk.Cursor.new_from_name("pointer", None))
        card.append(action_btn)

        card._action_btn = action_btn
        card._pkg_name = name
        card._source = "snap"
        card._update_info = None

        if hasattr(self, "_registered_cards"):
            self._registered_cards.setdefault(name.strip().lower(), []).append(card)

        gesture = Gtk.GestureClick()
        def _on_card_click(g, n_press, x, y, n=name):
            picked = card.pick(x, y, Gtk.PickFlags.INSENSITIVE)
            if picked is not None and (picked == action_btn or action_btn.is_ancestor(picked)):
                return
            alloc = action_btn.compute_bounds(card)
            if alloc[0]:
                rect = alloc[1]
                rx, ry = rect.get_x(), rect.get_y()
                rw, rh = rect.get_width(), rect.get_height()
                if rx <= x <= rx + rw and ry <= y <= ry + rh:
                    return
            self._open_package_detail(n, "snap")
        gesture.connect("released", _on_card_click)
        card.add_controller(gesture)

        return card

    def _get_snap_detail(self, name: str) -> Dict[str, Any]:
        """Fetch full details for any Snap package from the Snapcraft catalog."""
        snap_is_inst = False
        snap_inst_ver = ""
        try:
            if hasattr(self.pm, "snap_mgr") and self.pm.snap_mgr:
                snap_is_inst = bool(self.pm.snap_mgr.is_snap_installed(name))
                if snap_is_inst:
                    installed_snaps = self.pm.snap_mgr.get_installed_snaps()
                    if isinstance(installed_snaps, list):
                        for sn in installed_snaps:
                            if isinstance(sn, dict) and sn.get("name", "").lower() == name.lower():
                                snap_inst_ver = sn.get("version", "")
                                break
        except Exception:
            pass

        info = None
        try:
            if hasattr(self.pm, "snap_mgr") and callable(getattr(self.pm.snap_mgr, "get_snap_details", None)):
                res = self.pm.snap_mgr.get_snap_details(name)
                if isinstance(res, dict):
                    info = dict(res)
        except Exception:
            pass

        base = next((s for s in CURATED_SNAPS if s["name"] == name), None)
        detail = info if info else {
            "name": name,
            "display_name": base["title"] if base else get_app_display_name(name),
            "source": "snap",
            "repo": "Canonical Snapcraft",
            "version": base.get("version", "stable") if base else "latest",
            "desc": base.get("desc") or base.get("summary", "") if base else "Canonical Snap package",
            "extended_desc": base.get("desc", "") if base else "",
            "packager": base.get("publisher", "Canonical") if base else "Canonical",
            "license": "Proprietary / Open Source",
            "icon": resolve_icon_name(name, ""),
            "url": f"https://snapcraft.io/{name}",
        }
        detail["source"] = "snap"
        detail["is_installed"] = snap_is_inst
        detail["installed_version"] = snap_inst_ver
        detail["desktop_entry"] = self.pm.detect_desktop_entry(name) if snap_is_inst else None
        detail["depends"] = ["snapd (Isolated Sandboxed Runtime)"]
        detail["isize_str"] = detail.get("isize_str", "Sandboxed snap")
        detail["csize_str"] = detail.get("csize_str", "Varies by channel")
        return detail

    # =========================================================================
    # Page: Storage & System Caches (macOS Style Storage Cleaner)
    # =========================================================================
    def _build_storage_page(self) -> Gtk.ScrolledWindow:
        scrolled = Gtk.ScrolledWindow()
        scrolled.add_css_class("aura-page")
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(20)
        box.set_margin_bottom(36)
        box.set_margin_start(20)
        box.set_margin_end(20)

        # 1. Page Title Header
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        page_title = Gtk.Label(label="Storage & Caches")
        page_title.add_css_class("mac-page-title")
        page_title.set_halign(Gtk.Align.START)
        title_box.append(page_title)

        page_subtitle = Gtk.Label(label="Review disk usage, package caches, build artifacts, and reclaim storage safely")
        page_subtitle.add_css_class("mac-page-subtitle")
        page_subtitle.set_halign(Gtk.Align.START)
        page_subtitle.set_wrap(True)
        page_subtitle.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        page_subtitle.set_max_width_chars(50)
        title_box.append(page_subtitle)
        box.append(title_box)

        # 2. System Storage Overview Card (macOS System Settings Storage style)
        storage_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        storage_card.add_css_class("mac-storage-card")

        card_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        disk_icon = Gtk.Image.new_from_icon_name("drive-harddisk-symbolic")
        disk_icon.set_pixel_size(20)
        card_header.append(disk_icon)

        disk_title = Gtk.Label(label="Root Storage Drive (/)")
        disk_title.add_css_class("mac-spotlight-title")
        disk_title.set_halign(Gtk.Align.START)
        disk_title.set_ellipsize(Pango.EllipsizeMode.END)
        disk_title.set_max_width_chars(32)
        card_header.append(disk_title)

        self.storage_disk_summary_lbl = Gtk.Label(label="Calculating disk usage...")
        self.storage_disk_summary_lbl.add_css_class("dim-label")
        self.storage_disk_summary_lbl.set_halign(Gtk.Align.END)
        self.storage_disk_summary_lbl.set_hexpand(True)
        self.storage_disk_summary_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.storage_disk_summary_lbl.set_max_width_chars(65)
        card_header.append(self.storage_disk_summary_lbl)
        storage_card.append(card_header)

        # Segmented Storage Bar
        self.storage_bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.storage_bar_box.add_css_class("mac-storage-meter-track")
        self.storage_bar_box.set_hexpand(True)

        self.seg_pacman = Gtk.Box()
        self.seg_pacman.add_css_class("mac-storage-seg-pacman")
        self.seg_pacman.set_size_request(20, 16)
        self.storage_bar_box.append(self.seg_pacman)

        self.seg_aur = Gtk.Box()
        self.seg_aur.add_css_class("mac-storage-seg-aur")
        self.seg_aur.set_size_request(20, 16)
        self.storage_bar_box.append(self.seg_aur)

        self.seg_docker = Gtk.Box()
        self.seg_docker.add_css_class("mac-storage-seg-docker")
        self.seg_docker.set_size_request(10, 16)
        self.storage_bar_box.append(self.seg_docker)

        self.seg_journal = Gtk.Box()
        self.seg_journal.add_css_class("mac-storage-seg-journal")
        self.seg_journal.set_size_request(10, 16)
        self.storage_bar_box.append(self.seg_journal)

        self.seg_aura = Gtk.Box()
        self.seg_aura.add_css_class("mac-storage-seg-aura")
        self.seg_aura.set_size_request(10, 16)
        self.storage_bar_box.append(self.seg_aura)

        self.seg_free = Gtk.Box()
        self.seg_free.add_css_class("mac-storage-seg-free")
        self.seg_free.set_hexpand(True)
        self.storage_bar_box.append(self.seg_free)

        storage_card.append(self.storage_bar_box)

        # Legend Row (Responsive FlowBox allowing smooth wrapping)
        self.storage_legend_box = Gtk.FlowBox()
        self.storage_legend_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.storage_legend_box.set_valign(Gtk.Align.CENTER)
        self.storage_legend_box.set_margin_top(4)
        self.storage_legend_box.set_column_spacing(16)
        self.storage_legend_box.set_row_spacing(8)
        self.storage_legend_box.set_min_children_per_line(1)
        self.storage_legend_box.set_max_children_per_line(6)

        self.lbl_pacman_size = Gtk.Label(label="Pacman: --")
        self.lbl_aur_size = Gtk.Label(label="AUR: --")
        self.lbl_docker_size = Gtk.Label(label="Docker: --")
        self.lbl_journal_size = Gtk.Label(label="Journals: --")
        self.lbl_aura_size = Gtk.Label(label="Aura App: --")
        self.lbl_free_size = Gtk.Label(label="Free: --")

        for lbl in (self.lbl_pacman_size, self.lbl_aur_size, self.lbl_docker_size, self.lbl_journal_size, self.lbl_aura_size, self.lbl_free_size):
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            lbl.set_max_width_chars(16)

        def _make_legend_item(color: str, label_widget: Gtk.Label) -> Gtk.Box:
            item_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            dot = Gtk.Box()
            dot.set_size_request(8, 8)
            dot.set_valign(Gtk.Align.CENTER)
            dot_css = Gtk.CssProvider()
            dot_css.load_from_string(f"box {{ background-color: {color}; border-radius: 4px; min-width: 8px; min-height: 8px; }}")
            dot.get_style_context().add_provider(dot_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            item_box.append(dot)
            label_widget.add_css_class("dim-label")
            item_box.append(label_widget)
            return item_box

        self.storage_legend_box.append(_make_legend_item("#0a84ff", self.lbl_pacman_size))
        self.storage_legend_box.append(_make_legend_item("#ff9f0a", self.lbl_aur_size))
        self.storage_legend_box.append(_make_legend_item("#30d158", self.lbl_docker_size))
        self.storage_legend_box.append(_make_legend_item("#bf5af2", self.lbl_journal_size))
        self.storage_legend_box.append(_make_legend_item("#64d2ff", self.lbl_aura_size))
        self.storage_legend_box.append(_make_legend_item("rgba(255,255,255,0.25)", self.lbl_free_size))

        storage_card.append(self.storage_legend_box)
        box.append(storage_card)

        # 3. Reclaimable Cache Spotlight Banner
        reclaim_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        reclaim_card.add_css_class("mac-container-status-card")
        reclaim_card.set_valign(Gtk.Align.CENTER)
        reclaim_card.set_hexpand(True)

        rec_info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        rec_info_box.set_hexpand(True)
        rec_info_box.set_valign(Gtk.Align.CENTER)

        self.lbl_reclaimable_total = Gtk.Label(label="Scanning Caches...")
        self.lbl_reclaimable_total.add_css_class("mac-spotlight-title")
        self.lbl_reclaimable_total.set_halign(Gtk.Align.START)
        self.lbl_reclaimable_total.set_ellipsize(Pango.EllipsizeMode.END)
        self.lbl_reclaimable_total.set_max_width_chars(28)
        rec_info_box.append(self.lbl_reclaimable_total)

        rec_sub = Gtk.Label(label="Safe pruning retains current installed packages for offline rollback while cleaning unneeded archives.")
        rec_sub.add_css_class("mac-spotlight-desc")
        rec_sub.set_halign(Gtk.Align.START)
        rec_sub.set_wrap(True)
        rec_sub.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        rec_sub.set_max_width_chars(42)
        rec_sub.set_ellipsize(Pango.EllipsizeMode.END)
        rec_info_box.append(rec_sub)
        reclaim_card.append(rec_info_box)

        # Clean Selected Caches Button
        self.btn_clean_all_caches = Gtk.Button(label="Clean Selected Caches")
        self.btn_clean_all_caches.add_css_class("mac-btn-get")
        self.btn_clean_all_caches.set_valign(Gtk.Align.CENTER)
        self.btn_clean_all_caches.set_size_request(150, 34)
        self.btn_clean_all_caches.connect("clicked", self._on_clean_selected_caches_click)
        reclaim_card.append(self.btn_clean_all_caches)

        box.append(reclaim_card)

        # 4. Cache Category Rows Section
        categories_label = Gtk.Label(label="Manage System & User Caches")
        categories_label.add_css_class("mac-section-header")
        categories_label.set_halign(Gtk.Align.START)
        categories_label.set_margin_top(10)
        box.append(categories_label)

        self.cache_rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.cache_checkboxes: Dict[str, Gtk.CheckButton] = {}
        self.cache_action_buttons: Dict[str, Gtk.Button] = {}
        box.append(self.cache_rows_box)

        # 5. System Health & Pacman Doctor Section
        doctor_label = Gtk.Label(label="System Health & Pacman Doctor")
        doctor_label.add_css_class("mac-section-header")
        doctor_label.set_halign(Gtk.Align.START)
        doctor_label.set_margin_top(14)
        box.append(doctor_label)

        self.doctor_rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(self.doctor_rows_box)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(860)
        clamp.set_tightening_threshold(640)
        clamp.set_child(box)
        scrolled.set_child(clamp)
        return scrolled

    def _load_storage_view(self):
        """Scans caches in background and updates storage bar, metrics, and category cards."""
        self.lbl_reclaimable_total.set_text("Scanning Caches...")
        if hasattr(self, "btn_clean_all_caches"):
            self.btn_clean_all_caches.set_sensitive(False)

        def _bg():
            data = self.pm.cache_mgr.scan_all_caches()
            health = self.pm.doctor_mgr.scan_health() if hasattr(self.pm, "doctor_mgr") else {}
            def _ui():
                self._update_storage_ui(data)
                self._update_doctor_ui(health)
            GLib.idle_add(_ui)

        threading.Thread(target=_bg, daemon=True).start()

    def _update_storage_ui(self, data: Dict[str, Any]):
        total_rec_str = data.get("total_reclaimable_str", "0 B")
        total_rec_bytes = data.get("total_reclaimable_bytes", 0)
        self.lbl_reclaimable_total.set_text(f"Reclaimable Cache: {total_rec_str}")
        self.btn_clean_all_caches.set_sensitive(total_rec_bytes > 0)
        if total_rec_bytes > 0:
            self.btn_clean_all_caches.set_label(f"Clean Selected ({total_rec_str})")
        else:
            self.btn_clean_all_caches.set_label("Caches Clean")

        disk_tot = data.get("disk_total_bytes", 1)
        disk_used = data.get("disk_used_bytes", 0)
        disk_free = data.get("disk_free_bytes", 0)
        free_str = data.get("disk_free_str", "0 B")
        tot_str = data.get("disk_total_str", "0 B")
        used_str = self.pm.cache_mgr.format_size(disk_used)

        self.storage_disk_summary_lbl.set_text(f"{used_str} used of {tot_str} • {free_str} free")

        cats = data.get("categories", {})
        pacman_info = cats.get("pacman", {})
        aur_info = cats.get("aur", {})
        docker_info = cats.get("docker", {})
        journal_info = cats.get("journal", {})
        aura_info = cats.get("aura", {})

        self.lbl_pacman_size.set_text(f"Pacman: {pacman_info.get('reclaimable_str', '0 B')}")
        self.lbl_aur_size.set_text(f"AUR: {aur_info.get('reclaimable_str', '0 B')}")
        self.lbl_docker_size.set_text(f"Docker: {docker_info.get('reclaimable_str', '0 B')}")
        self.lbl_journal_size.set_text(f"Journals: {journal_info.get('reclaimable_str', '0 B')}")
        self.lbl_aura_size.set_text(f"Aura App: {aura_info.get('reclaimable_str', '0 B')}")
        self.lbl_free_size.set_text(f"Free: {free_str}")

        def _calc_px(bytes_val: int) -> int:
            if bytes_val <= 0:
                return 0
            return max(8, min(60, int(bytes_val / (1024**3) * 8)))

        self.seg_pacman.set_size_request(_calc_px(pacman_info.get("reclaimable_bytes", 0)), 16)
        self.seg_aur.set_size_request(_calc_px(aur_info.get("reclaimable_bytes", 0)), 16)
        self.seg_docker.set_size_request(_calc_px(docker_info.get("reclaimable_bytes", 0)), 16)
        self.seg_journal.set_size_request(_calc_px(journal_info.get("reclaimable_bytes", 0)), 16)
        self.seg_aura.set_size_request(_calc_px(aura_info.get("reclaimable_bytes", 0)), 16)

        # Update existing cache rows in-place (zero icon reload / zero flicker!), or build once on first load
        if not hasattr(self, "_cache_row_widgets"):
            self._cache_row_widgets = {}
        for key, cat_data in cats.items():
            existing_row = self._cache_row_widgets.get(key)
            if existing_row is not None and existing_row.get_parent() == self.cache_rows_box:
                rec_str = cat_data.get("reclaimable_str", "0 B")
                tot_str = cat_data.get("total_str", "0 B")
                rec_bytes = cat_data.get("reclaimable_bytes", 0)
                if hasattr(existing_row, "_size_lbl"):
                    existing_row._size_lbl.set_text(f"{rec_str} Reclaimable")
                if hasattr(existing_row, "_tot_lbl"):
                    existing_row._tot_lbl.set_text(f"{tot_str} on disk")
                if hasattr(existing_row, "_btn_clean"):
                    existing_row._btn_clean.set_label("Clean")
                    existing_row._btn_clean.set_sensitive(rec_bytes > 0)
            else:
                row = self._create_cache_category_row(key, cat_data)
                self._cache_row_widgets[key] = row
                self.cache_rows_box.append(row)

    def _create_cache_category_row(self, key: str, cat_data: Dict[str, Any]) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        row.add_css_class("mac-cache-row")
        row.set_valign(Gtk.Align.CENTER)
        row.set_hexpand(True)

        # Checkbox (Fixed column 1)
        chk = Gtk.CheckButton()
        chk.set_active(True)
        chk.set_valign(Gtk.Align.CENTER)
        chk.set_hexpand(False)
        self.cache_checkboxes[key] = chk
        row.append(chk)

        # Icon Squircle (Fixed column 2: 44x44 homogeneous dead-centered)
        icon_box = Gtk.Box()
        icon_box.add_css_class("mac-squircle")
        icon_box.set_size_request(44, 44)
        icon_box.set_homogeneous(True)
        icon_box.set_homogeneous(True)
        icon_box.set_halign(Gtk.Align.CENTER)
        icon_box.set_valign(Gtk.Align.CENTER)
        icon_box.set_hexpand(False)
        icon_box.set_vexpand(False)
        icon_name = cat_data.get("icon", "drive-harddisk-symbolic")
        icon_img = create_scaled_image(icon_name, size=22)
        icon_box.append(icon_img)
        row.append(icon_box)

        # Details (Expanding column 3: strictly left-aligned at exact X coordinate)
        info_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_col.set_hexpand(True)
        info_col.set_halign(Gtk.Align.FILL)
        info_col.set_valign(Gtk.Align.CENTER)

        title_lbl = Gtk.Label(label=cat_data.get("name", key.capitalize()))
        title_lbl.add_css_class("mac-app-title")
        title_lbl.set_halign(Gtk.Align.FILL)
        title_lbl.set_xalign(0.0)
        title_lbl.set_hexpand(True)
        title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        info_col.append(title_lbl)

        desc_lbl = Gtk.Label(label=cat_data.get("desc", ""))
        desc_lbl.add_css_class("mac-app-desc")
        desc_lbl.set_halign(Gtk.Align.FILL)
        desc_lbl.set_xalign(0.0)
        desc_lbl.set_hexpand(True)
        desc_lbl.set_wrap(True)
        desc_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        desc_lbl.set_lines(2)
        desc_lbl.set_max_width_chars(36)
        desc_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        info_col.append(desc_lbl)
        row.append(info_col)

        # Size Label (Fixed column 4: 155px right-aligned, never truncates '43.0 MB Reclaimable')
        size_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        size_col.set_valign(Gtk.Align.CENTER)
        size_col.set_halign(Gtk.Align.END)
        size_col.set_hexpand(False)
        size_col.set_size_request(155, -1)
        size_col.set_margin_end(6)

        rec_str = cat_data.get("reclaimable_str", "0 B")
        tot_str = cat_data.get("total_str", "0 B")
        size_lbl = Gtk.Label(label=f"{rec_str} Reclaimable")
        size_lbl.add_css_class("mac-app-title")
        size_lbl.set_halign(Gtk.Align.END)
        size_lbl.set_xalign(1.0)
        size_col.append(size_lbl)

        tot_lbl = Gtk.Label(label=f"{tot_str} on disk")
        tot_lbl.add_css_class("dim-label")
        tot_lbl.set_halign(Gtk.Align.END)
        tot_lbl.set_xalign(1.0)
        size_col.append(tot_lbl)
        row.append(size_col)

        # Prune Button (Fixed column 5: 96x32)
        rec_bytes = cat_data.get("reclaimable_bytes", 0)
        btn_clean = Gtk.Button(label="Clean")
        btn_clean.add_css_class("mac-btn-get")
        btn_clean.set_valign(Gtk.Align.CENTER)
        btn_clean.set_hexpand(False)
        btn_clean.set_size_request(96, 32)
        btn_clean.set_sensitive(rec_bytes > 0)
        btn_clean.connect("clicked", lambda b, k=key: self._on_clean_single_cache_click(b, k))
        self.cache_action_buttons[key] = btn_clean
        row._size_lbl = size_lbl
        row._tot_lbl = tot_lbl
        row._btn_clean = btn_clean
        row.append(btn_clean)

        return row

    def _on_clean_selected_caches_click(self, btn: Gtk.Button):
        selected_cats = [k for k, chk in self.cache_checkboxes.items() if chk.get_active()]
        if not selected_cats:
            self.show_toast("No cache categories selected.")
            return

        btn.set_sensitive(False)
        btn.set_label("Cleaning...")

        def _prog(frac, msg):
            def _ui_p():
                if frac < 1.0 and msg:
                    btn.set_label(msg[:22])
            GLib.idle_add(_ui_p)

        def _done(ok, msg):
            def _ui():
                self.show_toast(msg)
                self._load_storage_view()
            GLib.idle_add(_ui)

        self.pm.cache_mgr.prune_all_selected(selected_cats, progress_cb=_prog, complete_cb=_done)

    def _on_clean_single_cache_click(self, btn: Gtk.Button, cache_key: str):
        btn.set_sensitive(False)
        btn.set_label("Cleaning...")

        def _prog(frac, msg):
            return

        def _done(ok, msg):
            def _ui():
                self.show_toast(msg)
                self._load_storage_view()
            GLib.idle_add(_ui)

        self.pm.cache_mgr.prune_cache(cache_key, progress_cb=_prog, complete_cb=_done)

    # =========================================================================
    # Page 5: Full-Page Product Detail Inspector (Exact macOS App Store Page)
    # =========================================================================
    def _build_detail_page(self) -> Gtk.ScrolledWindow:
        scrolled = Gtk.ScrolledWindow()
        scrolled.add_css_class("aura-page")
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_valign(Gtk.Align.START)
        box.set_vexpand(False)
        box.set_hexpand(True)
        box.set_margin_top(16)
        box.set_margin_bottom(36)
        box.set_margin_start(20)
        box.set_margin_end(20)

        # 1. Hero Ambient Banner
        self.detail_hero_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        self.detail_hero_box.add_css_class("mac-detail-hero")
        self.detail_hero_box.set_valign(Gtk.Align.START)

        # 88x88 Squircle Icon Container
        self.detail_icon_box = Gtk.Box()
        self.detail_icon_box.add_css_class("mac-detail-icon-squircle")
        self.detail_icon_box.set_homogeneous(True)
        self.detail_icon_box.set_valign(Gtk.Align.CENTER)
        self.detail_icon_box.set_halign(Gtk.Align.CENTER)
        self.detail_icon_box.set_size_request(88, 88)
        self.detail_icon_box.set_hexpand(False)
        self.detail_icon_box.set_vexpand(False)
        self.detail_icon_img = Gtk.Image.new_from_icon_name("system-software-install")
        self.detail_icon_img.set_pixel_size(64)
        self.detail_icon_img.set_halign(Gtk.Align.CENTER)
        self.detail_icon_img.set_valign(Gtk.Align.CENTER)
        self.detail_icon_img.set_hexpand(False)
        self.detail_icon_img.set_vexpand(False)
        self.detail_icon_box.append(self.detail_icon_img)
        self.detail_hero_box.append(self.detail_icon_box)

        # Title & Metadata
        vbox_title = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vbox_title.set_hexpand(True)
        vbox_title.set_valign(Gtk.Align.CENTER)

        self.detail_title = Gtk.Label(label="Application Name")
        self.detail_title.add_css_class("mac-detail-title")
        self.detail_title.set_halign(Gtk.Align.START)
        self.detail_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.detail_title.set_max_width_chars(65)
        vbox_title.append(self.detail_title)

        self.detail_subtitle = Gtk.Label(label="Subtitle / Category Description")
        self.detail_subtitle.add_css_class("mac-detail-subtitle")
        self.detail_subtitle.set_halign(Gtk.Align.START)
        self.detail_subtitle.set_wrap(True)
        self.detail_subtitle.set_wrap_mode(Pango.WrapMode.WORD)
        self.detail_subtitle.set_lines(2)
        self.detail_subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        self.detail_subtitle.set_max_width_chars(75)
        vbox_title.append(self.detail_subtitle)

        self.detail_meta = Gtk.Label(label="Official Repository • Free & Open Source")
        self.detail_meta.add_css_class("mac-detail-meta")
        self.detail_meta.set_halign(Gtk.Align.START)
        self.detail_meta.set_ellipsize(Pango.EllipsizeMode.END)
        self.detail_meta.set_max_width_chars(75)
        vbox_title.append(self.detail_meta)

        self.detail_hero_box.append(vbox_title)

        # Action Buttons Box inside Hero
        self.detail_actions_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.detail_actions_box.set_valign(Gtk.Align.CENTER)

        self.btn_detail_launch = Gtk.Button(label="OPEN")
        self.btn_detail_launch.add_css_class("mac-btn-detail-open")
        self.btn_detail_launch.set_size_request(108, 36)
        self.btn_detail_launch.set_visible(False)
        self.btn_detail_launch.connect("clicked", lambda b: self._launch_app())
        self.detail_actions_box.append(self.btn_detail_launch)

        self.btn_detail_update = Gtk.Button(label="UPDATE")
        self.btn_detail_update.add_css_class("mac-btn-update")
        self.btn_detail_update.set_size_request(108, 36)
        self.btn_detail_update.set_visible(False)
        self.detail_actions_box.append(self.btn_detail_update)

        self.btn_detail_install = Gtk.Button(label="GET")
        self.btn_detail_install.add_css_class("mac-btn-primary-large")
        self.btn_detail_install.set_size_request(108, 36)
        self.btn_detail_install.connect("clicked", lambda b: self._on_install_click())
        self.detail_actions_box.append(self.btn_detail_install)

        self.btn_detail_remove = Gtk.Button(label="UNINSTALL")
        self.btn_detail_remove.add_css_class("mac-btn-danger-pill")
        self.btn_detail_remove.set_size_request(108, 36)
        self.btn_detail_remove.set_visible(False)
        self.btn_detail_remove.connect("clicked", lambda b: self._on_remove_click())
        self.detail_actions_box.append(self.btn_detail_remove)

        self.detail_hero_box.append(self.detail_actions_box)
        box.append(self.detail_hero_box)

        # In-App Progress Card
        self.progress_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.progress_container.add_css_class("progress-card")
        self.progress_container.set_visible(False)

        prog_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        prog_hdr.add_css_class("mac-progress-header")

        self.progress_status_label = Gtk.Label(label="Installing...")
        self.progress_status_label.set_halign(Gtk.Align.START)
        self.progress_status_label.set_hexpand(True)
        self.progress_status_label.add_css_class("mac-progress-title")
        prog_hdr.append(self.progress_status_label)

        self.progress_percent_label = Gtk.Label(label="0%")
        self.progress_percent_label.add_css_class("mac-progress-percent")
        self.progress_percent_label.set_halign(Gtk.Align.END)
        prog_hdr.append(self.progress_percent_label)

        self.progress_container.append(prog_hdr)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.add_css_class("mac-capsule-progress")
        self.progress_bar.set_fraction(0.0)
        self.progress_container.append(self.progress_bar)

        # Expandable Live Terminal Output Drawer inside Progress Card
        self.progress_log_expander = Gtk.Expander(label="View Live Package Manager Output")
        self.progress_log_expander.add_css_class("dim-label")
        self.progress_log_expander.set_margin_top(4)

        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_min_content_height(95)
        log_scroll.set_max_content_height(150)
        log_scroll.add_css_class("mac-log-terminal-box")

        self.progress_log_label = Gtk.Label(label="Waiting for package manager stream...")
        self.progress_log_label.add_css_class("mac-log-text")
        self.progress_log_label.set_halign(Gtk.Align.START)
        self.progress_log_label.set_valign(Gtk.Align.START)
        self.progress_log_label.set_xalign(0.0)
        self.progress_log_label.set_selectable(True)
        self.progress_log_label.set_wrap(True)
        self.progress_log_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        log_scroll.set_child(self.progress_log_label)
        self.progress_log_expander.set_child(log_scroll)
        self.progress_container.append(self.progress_log_expander)

        box.append(self.progress_container)

        # 2. Apple Quick Stats Strip (5 Columns with subtle border)
        stats_strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        stats_strip.add_css_class("mac-stats-strip")
        stats_strip.set_homogeneous(True)
        stats_strip.set_valign(Gtk.Align.START)

        def _make_stat(title_text: str, default_val: str):
            svbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            svbox.set_hexpand(True)
            svbox.set_halign(Gtk.Align.FILL)
            lbl = Gtk.Label(label=title_text)
            lbl.add_css_class("mac-stat-label")
            lbl.set_halign(Gtk.Align.CENTER)
            svbox.append(lbl)
            val = Gtk.Label(label=default_val)
            val.add_css_class("mac-stat-value")
            val.set_halign(Gtk.Align.CENTER)
            val.set_justify(Gtk.Justification.CENTER)
            val.set_wrap(True)
            val.set_wrap_mode(Pango.WrapMode.WORD)
            val.set_lines(2)
            val.set_ellipsize(Pango.EllipsizeMode.END)
            val.set_max_width_chars(24)
            svbox.append(val)
            return svbox, val

        col1, self.stat_val_dev = _make_stat("DEVELOPER", "Community")
        col1.add_css_class("mac-stat-col")
        stats_strip.append(col1)

        col2, self.stat_val_source = _make_stat("REPOSITORY", "Official")
        col2.add_css_class("mac-stat-col")
        stats_strip.append(col2)

        col3, self.stat_val_version = _make_stat("VERSION", "1.0.0")
        col3.add_css_class("mac-stat-col")
        stats_strip.append(col3)

        col4, self.stat_val_size = _make_stat("INSTALLED SIZE", "Unknown")
        col4.add_css_class("mac-stat-col-last")
        stats_strip.append(col4)

        box.append(stats_strip)

        # 4. About / Description Section (Rich Glassmorphic Card)
        about_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        about_card.add_css_class("mac-about-card")

        # Update Available Glassmorphic Banner
        self.detail_update_banner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.detail_update_banner.add_css_class("mac-update-banner")
        self.detail_update_banner.set_valign(Gtk.Align.CENTER)
        self.detail_update_banner.set_visible(False)

        up_banner_icon_box = Gtk.Box()
        up_banner_icon_box.add_css_class("mac-update-badge-icon")
        up_banner_icon_box.set_valign(Gtk.Align.CENTER)
        up_banner_icon_box.set_halign(Gtk.Align.CENTER)
        up_banner_icon_box.set_size_request(40, 40)
        up_banner_icon_box.set_hexpand(False)
        up_banner_icon_box.set_vexpand(False)
        up_banner_icon = Gtk.Image.new_from_icon_name("feather-refresh-cw-symbolic")
        up_banner_icon.set_pixel_size(18)
        up_banner_icon.set_halign(Gtk.Align.CENTER)
        up_banner_icon.set_valign(Gtk.Align.CENTER)
        up_banner_icon.set_hexpand(True)
        up_banner_icon.set_vexpand(True)
        up_banner_icon_box.append(up_banner_icon)
        self.detail_update_banner.append(up_banner_icon_box)

        up_text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        up_text_box.set_hexpand(True)
        up_text_box.set_valign(Gtk.Align.CENTER)

        up_title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        up_title_row.set_valign(Gtk.Align.CENTER)
        self.detail_update_banner_title = Gtk.Label(label="Update Available")
        self.detail_update_banner_title.add_css_class("mac-update-banner-title")
        self.detail_update_banner_title.set_halign(Gtk.Align.START)
        up_title_row.append(self.detail_update_banner_title)

        self.detail_update_banner_pill = Gtk.Label(label="")
        self.detail_update_banner_pill.add_css_class("mac-update-version-pill")
        self.detail_update_banner_pill.set_valign(Gtk.Align.CENTER)
        up_title_row.append(self.detail_update_banner_pill)
        up_text_box.append(up_title_row)

        self.detail_update_banner_sub = Gtk.Label(label="A newer version of this software is ready to install.")
        self.detail_update_banner_sub.add_css_class("mac-update-banner-sub")
        self.detail_update_banner_sub.set_halign(Gtk.Align.START)
        self.detail_update_banner_sub.set_wrap(True)
        self.detail_update_banner_sub.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.detail_update_banner_sub.set_max_width_chars(50)
        up_text_box.append(self.detail_update_banner_sub)

        self.detail_update_banner.append(up_text_box)

        # Inline Action Button inside the Update Card
        self.btn_banner_update = Gtk.Button(label="Update Now")
        self.btn_banner_update.add_css_class("mac-btn-update")
        self.btn_banner_update.set_valign(Gtk.Align.CENTER)
        self.btn_banner_update.set_size_request(114, 34)
        self.detail_update_banner.append(self.btn_banner_update)

        about_card.append(self.detail_update_banner)

        about_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        about_hdr_lbl = Gtk.Label(label="About this Application")
        about_hdr_lbl.add_css_class("mac-section-title")
        about_hdr_lbl.set_halign(Gtk.Align.START)
        about_hdr.append(about_hdr_lbl)

        sp = Gtk.Box()
        sp.set_hexpand(True)
        about_hdr.append(sp)

        self.btn_detail_website = Gtk.Button(label="Visit Website ↗")
        self.btn_detail_website.add_css_class("mac-website-btn")
        self.btn_detail_website.set_visible(False)
        self.btn_detail_website.connect("clicked", lambda b: self._open_upstream_website())
        about_hdr.append(self.btn_detail_website)
        about_card.append(about_hdr)

        self.detail_desc_label = Gtk.Label(label="Package description...")
        self.detail_desc_label.set_halign(Gtk.Align.START)
        self.detail_desc_label.set_wrap(True)
        self.detail_desc_label.add_css_class("mac-about-text")
        about_card.append(self.detail_desc_label)

        # Dependencies Pills Container
        self.detail_deps_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.detail_deps_box.set_visible(False)
        deps_lbl = Gtk.Label(label="Package Dependencies")
        deps_lbl.add_css_class("mac-stat-label")
        deps_lbl.set_halign(Gtk.Align.START)
        self.detail_deps_box.append(deps_lbl)

        self.detail_deps_flow = Gtk.FlowBox()
        self.detail_deps_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.detail_deps_flow.set_homogeneous(False)
        self.detail_deps_flow.set_min_children_per_line(1)
        self.detail_deps_flow.set_max_children_per_line(24)
        self.detail_deps_flow.set_column_spacing(8)
        self.detail_deps_flow.set_row_spacing(8)
        self.detail_deps_flow.add_css_class("mac-deps-flow")
        self.detail_deps_box.append(self.detail_deps_flow)
        about_card.append(self.detail_deps_box)

        box.append(about_card)

        # 5. Information Specifications
        info_title = Gtk.Label(label="Information")
        info_title.add_css_class("mac-section-title")
        info_title.set_halign(Gtk.Align.START)
        info_title.set_margin_top(10)
        box.append(info_title)

        info_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        info_card.add_css_class("mac-info-card")

        def _make_info_row(key_text: str, is_last: bool = False):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
            row.add_css_class("mac-info-row-last" if is_last else "mac-info-row")
            key_lbl = Gtk.Label(label=key_text)
            key_lbl.add_css_class("mac-info-key")
            key_lbl.set_halign(Gtk.Align.START)
            row.append(key_lbl)

            spacer = Gtk.Box()
            spacer.set_hexpand(True)
            row.append(spacer)

            val_lbl = Gtk.Label(label="—")
            val_lbl.add_css_class("mac-info-val")
            val_lbl.set_halign(Gtk.Align.END)
            val_lbl.set_selectable(True)
            val_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            val_lbl.set_max_width_chars(60)
            row.append(val_lbl)
            return row, val_lbl

        row_repo, self.info_val_repo = _make_info_row("Repository")
        info_card.append(row_repo)

        row_arch, self.info_val_arch = _make_info_row("Architecture")
        info_card.append(row_arch)

        row_size, self.info_val_size = _make_info_row("Installed Size")
        info_card.append(row_size)

        row_csize, self.info_val_csize = _make_info_row("Download Size")
        info_card.append(row_csize)

        row_license, self.info_val_license = _make_info_row("License")
        info_card.append(row_license)

        row_packager, self.info_val_packager = _make_info_row("Packager", is_last=True)
        info_card.append(row_packager)

        box.append(info_card)

        scrolled.set_child(box)
        return scrolled

    # =========================================================================
    # Symmetrical Multi-Column Grid Builder
    # =========================================================================
    def _create_symmetric_grid(self, min_columns: Optional[int] = None, max_columns: Optional[int] = 4, columns: Optional[int] = None) -> Gtk.FlowBox:
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_homogeneous(True)
        min_c = min_columns if min_columns is not None else 1
        max_c = max_columns if max_columns is not None else 4
        flow._aura_min_cols = min_c
        flow._aura_max_cols = max_c
        cols = self._get_target_cols()
        target = max(min_c, min(cols, max_c))
        eff_min = 1 if target <= 1 else min(target, max(min_c, 2))
        flow.set_min_children_per_line(eff_min)
        flow.set_max_children_per_line(target)
        flow.set_column_spacing(16)
        flow.set_row_spacing(12)
        flow.set_hexpand(True)
        flow.set_valign(Gtk.Align.START)
        if not hasattr(self, "_registered_grids"):
            self._registered_grids = []
        self._registered_grids.append(flow)
        return flow

    def _create_mac_app_row(
        self,
        name: str,
        desc: str,
        source: str,
        title_override: str = "",
        is_installed_view: bool = False,
        icon_override: str = "",
        update_info: Optional[Dict[str, str]] = None
    ) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        card.add_css_class("mac-app-row")
        card.set_hexpand(True)
        card.set_valign(Gtk.Align.FILL)

        display_title = get_app_display_name(name, title_override)

        # 1. 54x54 Squircle App Icon Container (Rigid, Non-expanding, Dead-Center)
        if icon_override and os.path.isabs(icon_override):
            icon_target = icon_override
        elif icon_override:
            icon_target = resolve_icon_name(icon_override, desc)
        else:
            icon_target = resolve_icon_name(name, desc)

        icon_box = Gtk.Box()
        icon_box.add_css_class("mac-squircle")
        icon_box.set_homogeneous(True)
        icon_box.set_valign(Gtk.Align.CENTER)
        icon_box.set_halign(Gtk.Align.CENTER)
        icon_box.set_size_request(54, 54)
        icon_box.set_hexpand(False)
        icon_box.set_vexpand(False)
        icon_box.set_cursor(Gdk.Cursor.new_from_name("pointer", None))

        img = create_scaled_image(icon_target, size=40)
        img.set_halign(Gtk.Align.CENTER)
        img.set_valign(Gtk.Align.CENTER)
        icon_box.append(img)
        card.append(icon_box)

        # 2. Text Column (Full-width App Title + Clean Subtitle with inline source tag)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        vbox.set_hexpand(True)
        vbox.set_halign(Gtk.Align.FILL)
        vbox.set_valign(Gtk.Align.CENTER)

        title_lbl = Gtk.Label(label=display_title)
        title_lbl.add_css_class("mac-app-title")
        title_lbl.set_halign(Gtk.Align.FILL)
        title_lbl.set_xalign(0.0)
        title_lbl.set_hexpand(True)
        title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        title_lbl.set_tooltip_text(display_title)
        vbox.append(title_lbl)

        src_low = (source or "pacman").lower()
        src_prefix_map = {
            "aur": "AUR • ",
            "deb": ".DEB • ",
            "snap": "Snap • ",
            "docker": "Docker • ",
        }
        src_prefix = src_prefix_map.get(src_low, "")

        if update_info:
            base_sub = f"{desc} • {update_info.get('old_ver', '')} → {update_info.get('new_ver', '')}" if desc else f"{update_info.get('old_ver', '')} → {update_info.get('new_ver', '')}"
        else:
            base_sub = desc if desc else ("Desktop application" if source == "pacman" else "Community package")
        sub_text = f"{src_prefix}{base_sub}" 

        desc_lbl = Gtk.Label(label=sub_text)
        desc_lbl.set_halign(Gtk.Align.FILL)
        desc_lbl.set_xalign(0.0)
        desc_lbl.set_hexpand(True)
        desc_lbl.set_wrap(True)
        desc_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        desc_lbl.set_lines(2)
        desc_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        desc_lbl.add_css_class("mac-app-desc")
        vbox.append(desc_lbl)

        card.append(vbox)

        # 3. Action Pill Button (GET / OPEN / INSTALLED / UPDATE / UPDATING... / INSTALLING... / QUEUED)
        is_inst = is_installed_view or self._is_pkg_installed_unified(name, source)
        has_desktop = is_installed_view or (is_inst and bool(self.pm.detect_desktop_entry(name)))

        name_lower = name.strip().lower()
        res_name = getattr(self.pm, "resolve_installed_pkg_name", lambda x: x)(name_lower).lower()

        is_updating = bool(hasattr(self.pm, "is_pkg_updating") and self.pm.is_pkg_updating(name))
        is_installing = bool(hasattr(self.pm, "is_pkg_installing") and self.pm.is_pkg_installing(name))
        is_queued = bool(hasattr(self.pm, "is_pkg_queued") and self.pm.is_pkg_queued(name))

        upg_list = list(getattr(self.pm, "upgradable_list", []) or [])
        is_upgradable = any(
            (u.get("name") or "").strip().lower() in (name_lower, res_name, f"{name_lower}-bin")
            for u in upg_list
        )

        if update_info:
            active_tx = self.pm.get_active_transaction() if hasattr(self.pm, "get_active_transaction") else None
            is_tx_updating = bool(active_tx and isinstance(active_tx, dict) and active_tx.get("action") in ["update", "upgrade"])
            curr_pkg = (active_tx.get("current_pkg") or active_tx.get("pkg_name") or "").strip().lower() if is_tx_updating else ""
            completed_pkgs = [p.strip().lower() for p in active_tx.get("completed_pkgs", [])] if is_tx_updating else []

            if is_tx_updating and curr_pkg and curr_pkg in (name_lower, res_name):
                action_btn = Gtk.Button(label="UPDATING...")
                action_btn.add_css_class("mac-btn-get")
                action_btn.set_sensitive(False)
            elif is_tx_updating and (name_lower in completed_pkgs or res_name in completed_pkgs):
                action_btn = Gtk.Button(label="UPDATED")
                action_btn.add_css_class("mac-btn-installed")
                action_btn.set_sensitive(False)
            elif is_tx_updating:
                action_btn = Gtk.Button(label="UPDATE")
                action_btn.add_css_class("mac-btn-update")
                action_btn.set_sensitive(False)
            else:
                action_btn = Gtk.Button(label="UPDATE")
                action_btn.add_css_class("mac-btn-update")
                action_btn.set_sensitive(True)
        elif is_updating:
            action_btn = Gtk.Button(label="UPDATING...")
            action_btn.add_css_class("mac-btn-get")
            action_btn.set_sensitive(False)
        elif is_installing:
            action_btn = Gtk.Button(label="INSTALLING...")
            action_btn.add_css_class("mac-btn-get")
            action_btn.set_sensitive(False)
        elif is_queued:
            action_btn = Gtk.Button(label="QUEUED")
            action_btn.add_css_class("mac-btn-queued")
            action_btn.set_sensitive(False)
        elif is_upgradable:
            action_btn = Gtk.Button(label="UPDATE")
            action_btn.add_css_class("mac-btn-update")
            action_btn.set_sensitive(True)
        elif is_inst:
            if has_desktop:
                action_btn = Gtk.Button(label="OPEN")
                action_btn.add_css_class("mac-btn-open")
            else:
                action_btn = Gtk.Button(label="INSTALLED")
                action_btn.add_css_class("mac-btn-installed")
            action_btn.set_sensitive(True)
        else:
            action_btn = Gtk.Button(label="GET")
            action_btn.add_css_class("mac-btn-get")
            action_btn.set_sensitive(True)

        def _on_card_action_clicked(btn, n=name, s=source):
            if hasattr(self.pm, "is_pkg_updating") and self.pm.is_pkg_updating(n):
                return
            if hasattr(self.pm, "is_pkg_installing") and self.pm.is_pkg_installing(n):
                return
            if hasattr(self.pm, "is_pkg_queued") and self.pm.is_pkg_queued(n):
                return
            # Dynamic check for upgradable status
            nl = n.strip().lower()
            rn = getattr(self.pm, "resolve_installed_pkg_name", lambda x: x)(nl).lower()
            up_l = list(getattr(self.pm, "upgradable_list", []) or [])
            upg = any(
                (u.get("name") or "").strip().lower() in (nl, rn, f"{nl}-bin")
                for u in up_l
            )
            if upg:
                self._update_single_package(n, s)
                return
            if self._is_pkg_installed_unified(n, s):
                has_dt = bool(self.pm.detect_desktop_entry(n))
                if has_dt:
                    self._open_or_launch(n, s)
                else:
                    self._open_package_detail(n, s)
                return
            self._install_from_card(n, s, btn)

        action_btn.connect("clicked", _on_card_action_clicked)

        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions_box.set_valign(Gtk.Align.CENTER)
        actions_box.set_halign(Gtk.Align.END)
        actions_box.set_hexpand(False)
        actions_box.set_vexpand(False)

        action_btn.set_valign(Gtk.Align.CENTER)
        action_btn.set_halign(Gtk.Align.END)
        action_btn.set_hexpand(False)
        action_btn.set_vexpand(False)
        action_btn.set_size_request(72, 28)
        action_btn.set_cursor(Gdk.Cursor.new_from_name("pointer", None))
        actions_box.append(action_btn)

        # Direct Uninstall / Clean Uninstall button on Installed page cards
        trash_btn = None
        if is_installed_view and not update_info:
            trash_btn = Gtk.Button()
            trash_btn.add_css_class("mac-btn-trash")
            trash_icon = Gtk.Image.new_from_icon_name("user-trash-symbolic")
            trash_icon.set_pixel_size(13)
            trash_btn.set_child(trash_icon)
            trash_btn.set_size_request(28, 28)
            trash_btn.set_valign(Gtk.Align.CENTER)
            trash_btn.set_cursor(Gdk.Cursor.new_from_name("pointer", None))
            trash_btn.set_tooltip_text(f"Uninstall {display_title} (with Clean Data option)")
            trash_btn.connect(
                "clicked",
                lambda b, n=name, s=source, dt=display_title: self._confirm_package_uninstall(n, s, dt)
            )
            actions_box.append(trash_btn)

        card.append(actions_box)

        card._action_btn = action_btn
        card._trash_btn = trash_btn
        card._pkg_name = name
        card._source = source
        card._update_info = update_info
        card._display_name = display_title
        card._desc = desc
        card._search_corpus = f"{name} {display_title} {desc}".lower()
        card.set_cursor(Gdk.Cursor.new_from_name("pointer", None))

        if hasattr(self, "_registered_cards"):
            self._registered_cards.setdefault(name_lower, []).append(card)
            if res_name != name_lower:
                self._registered_cards.setdefault(res_name, []).append(card)

        # Card Gesture Click opens full-page inspector (ignoring clicks inside actions_box)
        gesture = Gtk.GestureClick()
        def _on_card_click(g, n_press, x, y, n=name, s=source):
            picked = card.pick(x, y, Gtk.PickFlags.INSENSITIVE)
            if picked is not None and (picked == actions_box or actions_box.is_ancestor(picked)):
                return
            alloc = actions_box.compute_bounds(card)
            if alloc[0]:
                rect = alloc[1]
                rx, ry = rect.get_x(), rect.get_y()
                rw, rh = rect.get_width(), rect.get_height()
                if rx <= x <= rx + rw and ry <= y <= ry + rh:
                    return
            self._open_package_detail(n, s)
        gesture.connect("released", _on_card_click)
        card.add_controller(gesture)

        return card

    def _open_or_launch(self, name: str, source: str):
        entry = self.pm.detect_desktop_entry(name)
        if entry:
            self.pm.launch_desktop_app(entry)
            disp = get_app_display_name(name)
            self.show_toast(f"Launching {disp}...")
        else:
            self._open_package_detail(name, source)

    def _set_detail_icon(self, icon: str):
        while child := self.detail_icon_box.get_first_child():
            self.detail_icon_box.remove(child)
        img = create_scaled_image(icon, size=64)
        img.set_halign(Gtk.Align.CENTER)
        img.set_valign(Gtk.Align.CENTER)
        self.detail_icon_img = img
        self.detail_icon_box.append(img)

    def _open_package_detail(self, name: str, source: str):
        """Open the full-page package inspector with zero stale data flash and preserved scroll offset."""
        self._save_current_scroll_position()
        self.set_focus(None)
        self._detail_request_id = getattr(self, "_detail_request_id", 0) + 1
        req_id = self._detail_request_id

        self.back_btn.set_visible(True)
        self.header_title.set_text("")

        curr_page = self.main_stack.get_visible_child_name()
        is_from_snap_page = (curr_page == "snap" or (curr_page == "detail" and getattr(self, "_previous_page", "") == "snap"))
        if curr_page != "detail":
            self._previous_page = curr_page

        # If locally installed via pacman/AUR, ensure source correctly reflects native pacman or aur
        # unless explicitly opened from the Snap Store page
        if self.pm.is_installed(name) and not is_from_snap_page and source not in ("docker", "deb"):
            pkg_entry = self.pm.packages.get(name)
            if pkg_entry and pkg_entry.get("repo") not in ("local", "deb-local", "aur"):
                source = "pacman"
            elif pkg_entry and pkg_entry.get("source") == "deb":
                source = "deb"
            else:
                clean = re.sub(r'-(bin|git|hg|svn|pure|gtk-app|qt-app|gui|cli|daemon|desktop|launcher)$', '', name.lower())
                clean_entry = self.pm.packages.get(clean)
                if clean_entry and clean_entry.get("repo") not in ("local", "deb-local", "aur"):
                    source = "pacman"
                else:
                    source = "aur"

        # Immediately wipe previous package data so user NEVER sees stale cached values
        self._clear_detail_page_loading(name, source)

        self.main_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        self.main_stack.set_transition_duration(180)
        self.main_stack.set_visible_child_name("detail")
        if self.detail_page.get_vadjustment():
            self.detail_page.get_vadjustment().set_value(0)

        def _bg():
            try:
                if source == "snap":
                    detail = self._get_snap_detail(name)
                else:
                    detail = self.pm.get_package_detail(name, source)
            except Exception as e:
                detail = {"name": name, "source": source, "desc": f"Package details ({e})"}
            if req_id == getattr(self, "_detail_request_id", 0):
                GLib.idle_add(lambda: self._render_detail_page(detail))
        threading.Thread(target=_bg, daemon=True).start()

    def _clear_detail_page_loading(self, name: str, source: str):
        """Immediately wipe previous package data so user NEVER sees stale cached values."""
        self._current_detail = {"name": name, "source": source}
        disp_title = get_app_display_name(name)
        self.detail_title.set_text(disp_title)
        self.detail_subtitle.set_text(f"{name} • Fetching package details...")
        if source == "snap":
            repo_name = "Canonical Snap Store"
            self.detail_meta.set_text(f"{name} • {repo_name} • Sandboxed Package")
        elif source in ("docker", "container"):
            repo_name = "Docker App Sandbox (aura-box)"
            self.detail_meta.set_text(f"{name} • {repo_name} • Isolated Alpine Container")
        elif source == "deb":
            repo_name = "Debian (.deb) Native Bridge"
            self.detail_meta.set_text(f"{name} • {repo_name} • Pacman Tracked")
        elif source == "pacman":
            repo_name = "Official System Repository"
            self.detail_meta.set_text(f"{name} • {repo_name} • Free & Open Source")
        else:
            repo_name = "Community Repository (AUR)"
            self.detail_meta.set_text(f"{name} • {repo_name} • Free & Open Source")

        # Set best known icon immediately
        icon_name = resolve_icon_name(name, "")
        self._set_detail_icon(icon_name)

        # Immediately pre-fill known metadata from in-memory caches so user never waits on network/CLI
        known_dev = "Open Source Community"
        known_ver = "latest"
        known_size = "—"
        known_desc = ""
        if source == "snap":
            cur_s = next((s for s in CURATED_SNAPS if s.get("name", "").lower() == name.lower()), None)
            if not cur_s and hasattr(self.pm, "snap_mgr"):
                cur_s = next((s for s in getattr(self.pm.snap_mgr, "CURATED_SNAP_APPS", []) if s.get("name", "").lower() == name.lower()), None)
            if cur_s:
                known_dev = cur_s.get("publisher") or cur_s.get("developer") or "Canonical"
                known_ver = cur_s.get("version", "stable")
                known_desc = cur_s.get("desc") or cur_s.get("summary") or ""
                known_size = "Sandboxed Snap"
        elif name in self.pm.packages:
            p_raw = self.pm.packages[name]
            known_dev = re.sub(r'<[^>]*>', '', str(p_raw.get("packager") or "Arch Linux")).strip() or "Arch Linux"
            known_ver = p_raw.get("version") or self.pm.installed_versions.get(name, "latest")
            known_desc = p_raw.get("desc", "")
        if known_desc:
            self.detail_subtitle.set_text(known_desc)

        self.stat_val_dev.set_text(known_dev)
        self.stat_val_source.set_text("Snap Store" if source == "snap" else ("Official" if source == "pacman" else "AUR"))
        self.stat_val_version.set_text(f"v{known_ver}" if known_ver and not str(known_ver).startswith("v") else str(known_ver))
        self.stat_val_size.set_text(known_size)
        # License stat was moved to Information card

        # Hide action buttons during load
        self.btn_detail_launch.set_visible(False)
        self.btn_detail_install.set_visible(False)
        self.btn_detail_remove.set_visible(False)
        if hasattr(self, "btn_detail_update"):
            self.btn_detail_update.set_visible(False)
        if hasattr(self, "detail_update_banner"):
            self.detail_update_banner.set_visible(False)

        if hasattr(self.pm, "is_pkg_installing") and self.pm.is_pkg_installing(name):
            self.progress_container.set_visible(True)
            prog, msg = self.pm.get_active_progress(name) if hasattr(self.pm, "get_active_progress") else (0.0, "Installing...")
            self.progress_bar.set_fraction(prog)
            self.progress_status_label.set_text(msg or "Installing...")
            self.progress_percent_label.set_text(f"{int(prog * 100)}%")
        elif hasattr(self.pm, "is_pkg_queued") and self.pm.is_pkg_queued(name):
            self.progress_container.set_visible(False)
            self.btn_detail_install.set_label("QUEUED")
            self.btn_detail_install.set_sensitive(False)
            self.btn_detail_install.set_css_classes(["mac-btn-primary-large", "mac-btn-queued"])
            self.btn_detail_install.set_size_request(108, 36)
            self.btn_detail_install.set_visible(True)
        else:
            self.progress_container.set_visible(False)

        # Clear description & website button & dependency pills
        self.detail_desc_label.set_text("Retrieving package details and system metadata...")
        self.detail_desc_label.add_css_class("mac-loading-shimmer")
        if hasattr(self, "btn_detail_website"):
            self.btn_detail_website.set_visible(False)
        if hasattr(self, "detail_deps_box"):
            self.detail_deps_box.set_visible(False)
        if hasattr(self, "detail_deps_flow"):
            self.detail_deps_flow.remove_all()

        # Reset specs table
        if hasattr(self, "info_val_repo"):
            self.info_val_repo.set_text("Loading...")
            self.info_val_arch.set_text("x86_64")
            self.info_val_size.set_text("—")
            self.info_val_csize.set_text("—")
            self.info_val_license.set_text("—")
            self.info_val_packager.set_text("—")

    def _render_detail_page(self, d: Dict[str, Any]):
        self._current_detail = d
        self.detail_desc_label.remove_css_class("mac-loading-shimmer")
        name = d.get("name", "")
        source = d.get("source", "pacman")

        # Live dynamic check prevents race condition with background fetch
        is_installed = self._is_pkg_installed_unified(name, source)
        d["is_installed"] = is_installed
        desktop_entry = self.pm.detect_desktop_entry(name) if is_installed else None
        d["desktop_entry"] = desktop_entry

        installed_ver = d.get("installed_version", "")
        ver = d.get("version", installed_ver)
        desc = d.get("desc", "No description available.")
        repo = d.get("repo", "extra")
        icon = d.get("icon", "system-software-install")

        # Icon
        self._set_detail_icon(icon)

        # Titles & Metadata
        display_title = d.get("display_name") or get_app_display_name(name)
        self.detail_title.set_text(display_title)
        self.detail_subtitle.set_text(desc)
        if source == "snap":
            repo_text = "Canonical Snap Store"
        elif source in ("docker", "container"):
            repo_text = "Docker App Sandbox (aura-box)"
        elif source == "deb":
            repo_text = "Debian (.deb) Native Bridge"
        elif source == "pacman":
            repo_text = "Official System Repository"
        else:
            repo_text = "Community Repository (AUR)"
        self.detail_meta.set_text(f"{name} • {repo_text} • Sandboxed Package" if source in ("snap", "docker", "container") else f"{name} • {repo_text} • Free & Open Source")

        # Stats Strip
        raw_dev = d.get("packager") or d.get("maintainer") or "Open Source Community"
        dev_clean = re.sub(r'<[^>]*>', '', str(raw_dev)).strip() or "Open Source Community"
        self.stat_val_dev.set_text(dev_clean)
        if source == "snap":
            repo_clean = "Snap Store"
        elif source in ("docker", "container"):
            repo_clean = "Docker Box"
        elif source == "deb":
            repo_clean = ".deb Bridge"
        elif source == "pacman":
            repo_clean = f"Official · {repo}"
        else:
            repo_clean = "AUR"
        self.stat_val_source.set_text(repo_clean)
        self.stat_val_version.set_text(f"v{ver}")
        self.stat_val_size.set_text(d.get("isize_str") or d.get("csize_str") or "Unknown")
        # License is shown in the Information card below

        # Check upgradable status with alias resolution
        name_low = name.strip().lower()
        res_name = getattr(self.pm, "resolve_installed_pkg_name", lambda x: x)(name_low).lower()
        up_item = None
        if hasattr(self.pm, "upgradable_list") and self.pm.upgradable_list:
            up_item = next(
                (u for u in self.pm.upgradable_list if (u.get("name") or "").strip().lower() in (name_low, res_name, f"{name_low}-bin")),
                None
            )

        if up_item:
            old_ver = up_item.get("old_ver", installed_ver or "")
            new_ver = up_item.get("new_ver", ver or "")
            self.detail_update_banner_title.set_text("Update Available")
            self.detail_update_banner_pill.set_text(f"v{old_ver} → v{new_ver}")
            self.detail_update_banner_pill.set_visible(True)
            self.detail_update_banner_sub.set_text("A newer version of this software is ready to install.")
            self.btn_banner_update.set_label("Update Now")
            self.btn_banner_update.set_sensitive(True)
            self.btn_banner_update.set_visible(True)
            self.detail_update_banner.set_visible(True)

            # Connect update action to detail button
            if hasattr(self, "_btn_update_sig") and self._btn_update_sig:
                try:
                    self.btn_detail_update.disconnect(self._btn_update_sig)
                except Exception:
                    pass
            self._btn_update_sig = self.btn_detail_update.connect(
                "clicked", lambda b, n=name, s=source: self._update_single_package(n, s)
            )

            # Connect update action to banner button
            if hasattr(self, "_btn_banner_update_sig") and self._btn_banner_update_sig:
                try:
                    self.btn_banner_update.disconnect(self._btn_banner_update_sig)
                except Exception:
                    pass
            self._btn_banner_update_sig = self.btn_banner_update.connect(
                "clicked", lambda b, n=name, s=source: self._update_single_package(n, s)
            )
        else:
            if hasattr(self, "detail_update_banner"):
                self.detail_update_banner.set_visible(False)
            if hasattr(self, "btn_detail_update"):
                self.btn_detail_update.set_visible(False)

        # Action Buttons
        desktop_entry = d.get("desktop_entry")
        is_updating = bool(hasattr(self.pm, "is_pkg_updating") and self.pm.is_pkg_updating(name) is True)
        is_installing = (hasattr(self.pm, "is_pkg_installing") and self.pm.is_pkg_installing(name) is True) or is_updating
        is_queued = hasattr(self.pm, "is_pkg_queued") and self.pm.is_pkg_queued(name) is True

        if is_installing:
            self.progress_container.set_visible(True)
            prog, msg = 0.0, ("Updating..." if (up_item or is_updating) else "Installing...")
            if hasattr(self.pm, "get_active_progress"):
                try:
                    res_p = self.pm.get_active_progress(name)
                    if isinstance(res_p, (tuple, list)) and len(res_p) == 2:
                        prog, msg = res_p
                except Exception:
                    pass
            self.progress_bar.set_fraction(prog)
            self.progress_status_label.set_text(msg or ("Updating..." if (up_item or is_updating) else "Installing..."))
            self.progress_percent_label.set_text(f"{int(prog * 100)}%")

            if hasattr(self, "btn_banner_update"):
                self.btn_banner_update.set_label("UPDATING...")
                self.btn_banner_update.set_sensitive(False)

            self.btn_detail_launch.set_visible(False)
            if hasattr(self, "btn_detail_update"):
                self.btn_detail_update.set_visible(False)
            self.btn_detail_install.set_label("UPDATING..." if (up_item or is_updating) else "INSTALLING...")
            self.btn_detail_install.set_sensitive(False)
            self.btn_detail_install.set_css_classes(["mac-btn-primary-large"])
            self.btn_detail_install.set_size_request(108, 36)
            self.btn_detail_install.set_visible(True)
            self.btn_detail_remove.set_visible(False)
        elif is_queued:
            self.progress_container.set_visible(False)
            if hasattr(self, "btn_banner_update"):
                self.btn_banner_update.set_label("QUEUED")
                self.btn_banner_update.set_sensitive(False)
            self.btn_detail_launch.set_visible(False)
            if hasattr(self, "btn_detail_update"):
                self.btn_detail_update.set_visible(False)
            self.btn_detail_install.set_label("QUEUED")
            self.btn_detail_install.set_sensitive(False)
            self.btn_detail_install.set_css_classes(["mac-btn-primary-large", "mac-btn-queued"])
            self.btn_detail_install.set_size_request(108, 36)
            self.btn_detail_install.set_visible(True)
            self.btn_detail_remove.set_visible(False)
        elif up_item:
            self.progress_container.set_visible(False)
            if desktop_entry:
                self.btn_detail_launch.set_label("OPEN")
                self.btn_detail_launch.set_css_classes(["mac-btn-detail-open"])
                self.btn_detail_launch.set_size_request(108, 36)
                self.btn_detail_launch.set_visible(True)
            else:
                self.btn_detail_launch.set_visible(False)
            self.btn_detail_install.set_visible(False)
            if hasattr(self, "btn_detail_update"):
                self.btn_detail_update.set_label("UPDATE")
                self.btn_detail_update.set_sensitive(True)
                self.btn_detail_update.set_visible(True)
            self.btn_detail_remove.set_label("UNINSTALL")
            self.btn_detail_remove.set_size_request(108, 36)
            self.btn_detail_remove.set_visible(True)
        elif is_installed:
            self.progress_container.set_visible(False)
            if hasattr(self, "btn_detail_update"):
                self.btn_detail_update.set_visible(False)
            if desktop_entry:
                self.btn_detail_launch.set_label("OPEN")
                self.btn_detail_launch.set_css_classes(["mac-btn-detail-open"])
                self.btn_detail_launch.set_size_request(108, 36)
                self.btn_detail_launch.set_visible(True)
                self.btn_detail_install.set_visible(False)
            else:
                self.btn_detail_launch.set_visible(False)
                self.btn_detail_install.set_label("INSTALLED")
                self.btn_detail_install.set_css_classes(["mac-btn-installed"])
                self.btn_detail_install.set_size_request(108, 36)
                self.btn_detail_install.set_visible(True)
            self.btn_detail_remove.set_label("UNINSTALL")
            self.btn_detail_remove.set_size_request(108, 36)
            self.btn_detail_remove.set_visible(True)
        else:
            self.progress_container.set_visible(False)
            self.btn_detail_launch.set_visible(False)
            if hasattr(self, "btn_detail_update"):
                self.btn_detail_update.set_visible(False)
            self.btn_detail_install.set_label("GET")
            self.btn_detail_install.set_css_classes(["mac-btn-primary-large"])
            self.btn_detail_install.set_size_request(108, 36)
            self.btn_detail_install.set_sensitive(True)
            self.btn_detail_install.set_visible(True)
            self.btn_detail_remove.set_visible(False)

        # Description
        full_desc = d.get("extended_desc") or desc
        self.detail_desc_label.set_text(full_desc)

        # Upstream Website Button
        url = d.get("url")
        if url and (url.startswith("http://") or url.startswith("https://")):
            self.btn_detail_website.set_visible(True)
            self._current_url = url
        else:
            self.btn_detail_website.set_visible(False)
            self._current_url = ""

        # Dependencies Pills
        deps = d.get("depends", [])
        self.detail_deps_flow.remove_all()
        if deps:
            self.detail_deps_box.set_visible(True)
            for dep in deps[:20]:
                dep_clean = dep.split(">=")[0].split("<=")[0].split("=")[0].split(":")[0].strip()
                dep_btn = Gtk.Button(label=dep_clean)
                dep_btn.add_css_class("mac-dep-tag")
                dep_btn.set_halign(Gtk.Align.START)
                dep_btn.set_hexpand(False)
                dep_btn.set_cursor(Gdk.Cursor.new_from_name("pointer", None))
                dep_btn.set_tooltip_text(f"Inspect dependency package '{dep_clean}'")
                dep_btn.connect("clicked", lambda b, dn=dep_clean: self._open_package_detail(dn, self.pm.resolve_package_source(dn)))
                self.detail_deps_flow.append(dep_btn)
            if len(deps) > 20:
                more_pill = Gtk.Label(label=f"+{len(deps) - 20} more")
                more_pill.add_css_class("mac-dep-tag")
                more_pill.set_halign(Gtk.Align.START)
                more_pill.set_hexpand(False)
                self.detail_deps_flow.append(more_pill)
        else:
            self.detail_deps_box.set_visible(False)

        # Specifications Table
        if source == "pacman":
            spec_repo = f"Official · {repo}"
        elif source in ("docker", "container"):
            spec_repo = "Docker App Sandbox (Alpine Linux)"
        elif source == "deb":
            spec_repo = "Debian (.deb) Native Bridge"
        elif source == "snap":
            spec_repo = "Canonical Snap Store"
        else:
            spec_repo = "Community Repository (AUR)"
        if hasattr(self, "info_val_repo"):
            self.info_val_repo.set_text(spec_repo)
            self.info_val_arch.set_text(d.get("arch", "x86_64"))
            self.info_val_size.set_text(sanitize_str(d.get("isize_str"), "Unknown"))
            self.info_val_csize.set_text(sanitize_str(d.get("csize_str"), "N/A (Built from source)" if source == "aur" else "Unknown"))
            self.info_val_license.set_text(d.get("license", "Custom License"))
            self.info_val_packager.set_text(dev_clean)

    def _open_upstream_website(self):
        url = getattr(self, "_current_url", "")
        if url:
            try:
                Gio.AppInfo.launch_default_for_uri(url, None)
                self.show_toast(f"Opening {url} in browser...")
            except Exception as e:
                self.show_toast(f"Failed to open URL: {e}")

    def _launch_app(self):
        if not getattr(self, "_current_detail", None):
            return
        name = self._current_detail.get("name", "")
        source = self._current_detail.get("source", "pacman")
        disp = self._current_detail.get("display_name") or get_app_display_name(name)
        if source in ("docker", "container") and hasattr(self.pm, "container_mgr"):
            self.pm.container_mgr.launch_app(name)
            self.show_toast(f"Launching {disp} (Docker Sandbox)...")
            return
        desktop_entry = self._current_detail.get("desktop_entry")
        if desktop_entry:
            self.pm.launch_desktop_app(desktop_entry)
            self.show_toast(f"Launching {disp}...")

    # =========================================================================
    # Search & Filter Logic
    # =========================================================================
    def _make_filter_handler(self, filter_key: str):
        def _handler(button: Gtk.ToggleButton):
            if button.get_active():
                self.current_filter = filter_key
                q = ""
                if hasattr(self, "browse_search_entry"):
                    q = self.browse_search_entry.get_text().strip()
                if q:
                    self._do_debounced_search(q)
        return _handler

    def _show_sidebar_search(self):
        """Keep the sidebar search entry always visible."""
        if hasattr(self, "search_entry"):
            self.search_entry.set_visible(True)

    def _hide_sidebar_search(self):
        """Keep the sidebar search entry visible to prevent Wayland IMContext focus crashes."""
        if hasattr(self, "search_entry"):
            self.search_entry.set_visible(True)

    def _on_sidebar_search_activate(self, entry: Gtk.SearchEntry):
        """Sidebar live search handler: synchronizes with browse_search_entry without hiding or stealing focus."""
        if getattr(self, "_search_sync_lock", False):
            return
        raw = entry.get_text()

        curr = self.main_stack.get_visible_child_name()
        if curr in ("containers", "docker") and hasattr(self, "container_search_entry"):
            if self.container_search_entry.get_text() != raw:
                self.container_search_entry.set_text(raw)
            return
        if curr == "snap" and hasattr(self, "snap_search_entry"):
            if self.snap_search_entry.get_text() != raw:
                self.snap_search_entry.set_text(raw)
            return

        # Mirror text into browse_search_entry synchronously without recursive signal emission
        self._search_sync_lock = True
        try:
            if hasattr(self, "browse_search_entry") and self.browse_search_entry.get_text() != raw:
                self.browse_search_entry.set_text(raw)
        finally:
            self._search_sync_lock = False

        q = raw.strip()
        if q and curr != "browse":
            self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            self.main_stack.set_transition_duration(180)
            self.main_stack.set_visible_child_name("browse")
            self.header_title.set_text("Search Results")

        self._schedule_live_search(q)

    def _on_browse_search_changed(self, entry: Gtk.SearchEntry):
        """Browse page search handler: synchronizes with sidebar search_entry and schedules search."""
        if getattr(self, "_search_sync_lock", False):
            return
        raw = entry.get_text()

        self._search_sync_lock = True
        try:
            if hasattr(self, "search_entry") and self.search_entry.get_text() != raw:
                self.search_entry.set_text(raw)
        finally:
            self._search_sync_lock = False

        q = raw.strip()
        curr = self.main_stack.get_visible_child_name()
        if q and curr != "browse":
            self.main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            self.main_stack.set_transition_duration(180)
            self.main_stack.set_visible_child_name("browse")
            self.header_title.set_text("Search Results")

        self._schedule_live_search(q)

    def _schedule_live_search(self, q: str):
        """Unified debounced search scheduler with signal deduplication."""
        if q and q == getattr(self, "_last_scheduled_query", None) and self._search_timer_id is not None:
            return
        self._last_scheduled_query = q

        if self._search_timer_id:
            GLib.source_remove(self._search_timer_id)
            self._search_timer_id = None

        if not q:
            self.active_request_id += 1
            if hasattr(self, "browse_spinner"):
                self.browse_spinner.stop()
                self.browse_spinner.set_visible(False)
            if hasattr(self, "browse_hero_card"):
                self.browse_hero_card.set_visible(True)
            if hasattr(self, "browse_results_container"):
                self.browse_results_container.set_visible(False)
            if hasattr(self, "browse_status_label"):
                self.browse_status_label.set_text("")
                self.browse_status_label.remove_css_class("mac-loading-shimmer")
            if hasattr(self, "browse_flow_box"):
                self.browse_flow_box.remove_all()
            return

        if hasattr(self, "browse_hero_card"):
            self.browse_hero_card.set_visible(False)
        if hasattr(self, "browse_results_container"):
            self.browse_results_container.set_visible(True)
        if hasattr(self, "browse_spinner"):
            self.browse_spinner.set_visible(True)
            self.browse_spinner.start()
        if hasattr(self, "browse_status_label"):
            self.browse_status_label.set_text(f"Searching for '{q}'...")
            self.browse_status_label.add_css_class("mac-loading-shimmer")

        self._search_timer_id = GLib.timeout_add(180, self._do_debounced_search, q)

    def _on_suggestion_chip_clicked(self, term: str):
        """Click handler for browse suggestions chips to quick-fill and execute search."""
        if hasattr(self, "browse_search_entry"):
            self.browse_search_entry.set_text(term)
            self.browse_search_entry.set_position(-1)
            self.browse_search_entry.grab_focus()

    def _on_browse_stop_search(self, entry: Gtk.SearchEntry):
        """Handle clear button / Escape — clear and stay on browse."""
        entry.set_text("")

    def _do_debounced_search(self, query: str) -> bool:
        """Debounced search trigger — called from timer."""
        self._search_timer_id = None
        if query:
            self._trigger_search(query)
        return False

    def _trigger_search(self, query: str) -> bool:
        self._search_timer_id = None
        if not query:
            if hasattr(self, "browse_spinner"):
                self.browse_spinner.stop()
                self.browse_spinner.set_visible(False)
            if hasattr(self, "browse_hero_card"):
                self.browse_hero_card.set_visible(True)
            if hasattr(self, "browse_results_container"):
                self.browse_results_container.set_visible(False)
            if hasattr(self, "browse_status_label"):
                self.browse_status_label.set_text("")
                self.browse_status_label.remove_css_class("mac-loading-shimmer")
            if hasattr(self, "browse_flow_box"):
                self.browse_flow_box.remove_all()
            return False

        if hasattr(self, "browse_hero_card"):
            self.browse_hero_card.set_visible(False)
        if hasattr(self, "browse_results_container"):
            self.browse_results_container.set_visible(True)
        if hasattr(self, "browse_spinner"):
            self.browse_spinner.set_visible(True)
            self.browse_spinner.start()
        if hasattr(self, "browse_status_label"):
            self.browse_status_label.set_text(f"Searching for '{query}'...")
            self.browse_status_label.add_css_class("mac-loading-shimmer")

        self.active_request_id += 1
        req_id = self.active_request_id

        def _bg():
            filter_mode = self.current_filter
            results: List[Dict[str, Any]] = []
            try:
                if filter_mode == "docker":
                    d_apps = self.pm.container_mgr.list_apps(query)
                    for a in d_apps:
                        results.append({"_card_type": "docker", "data": a})
                elif filter_mode == "snap":
                    seen = set()
                    q_lower = query.lower()
                    for s in CURATED_SNAPS:
                        s_name = s.get("name", "")
                        if s_name and (q_lower in s_name.lower() or q_lower in s.get("title", "").lower() or q_lower in s.get("summary", "").lower()):
                            if s_name not in seen:
                                seen.add(s_name)
                                results.append({"_card_type": "snap", "data": dict(s)})

                    try:
                        if hasattr(self.pm, "snap_mgr") and callable(getattr(self.pm.snap_mgr, "search_snaps", None)):
                            raw_snaps = self.pm.snap_mgr.search_snaps(query)
                            if isinstance(raw_snaps, list):
                                for s in raw_snaps[:60]:
                                    s_name = s.get("name")
                                    if s_name and s_name not in seen:
                                        seen.add(s_name)
                                        results.append({"_card_type": "snap", "data": s})
                    except Exception:
                        pass
                elif filter_mode in ("pacman", "aur"):
                    raw_pkgs = self.pm.search(query, source=filter_mode, limit=60)
                    for p in raw_pkgs:
                        results.append({"_card_type": "pkg", "data": p})
                else:
                    raw_pkgs = self.pm.search(query, source="all", limit=60)
                    for p in raw_pkgs:
                        results.append({"_card_type": "pkg", "data": p})
            except Exception as e:
                print(f"[Aura] Search background error: {e}", file=sys.stderr)

            if req_id == self.active_request_id:
                GLib.idle_add(lambda: self._display_search_results(query, results))

        threading.Thread(target=_bg, daemon=True).start()
        return False

    def _display_search_results(self, query: str, results: List[Dict[str, Any]]):
        try:
            # Stop and hide animated search spinner
            if hasattr(self, "browse_spinner"):
                self.browse_spinner.stop()
                self.browse_spinner.set_visible(False)

            # Check current text from either browse_search_entry or sidebar search_entry
            current_text = ""
            if hasattr(self, "browse_search_entry"):
                current_text = self.browse_search_entry.get_text().strip()
            if not current_text and hasattr(self, "search_entry"):
                current_text = self.search_entry.get_text().strip()

            if not current_text and not query:
                if hasattr(self, "browse_hero_card"):
                    self.browse_hero_card.set_visible(True)
                if hasattr(self, "browse_results_container"):
                    self.browse_results_container.set_visible(False)
                if hasattr(self, "browse_status_label"):
                    self.browse_status_label.set_text("")
                    self.browse_status_label.remove_css_class("mac-loading-shimmer")
                if hasattr(self, "browse_flow_box"):
                    self.browse_flow_box.remove_all()
                return

            if hasattr(self, "browse_hero_card"):
                self.browse_hero_card.set_visible(False)
            if hasattr(self, "browse_results_container"):
                self.browse_results_container.set_visible(True)

            self.browse_status_label.remove_css_class("mac-loading-shimmer")
            self.browse_flow_box.remove_all()
            count = len(results)

            if self.current_filter == "snap":
                scope = "Canonical Snap Store"
            elif self.current_filter == "docker":
                scope = "Docker App Sandbox"
            else:
                scope = "Arch Linux Repositories (Pacman & AUR)"

            self.browse_status_label.set_text(f"Found {count} results for '{query}' in {scope}")

            if count == 0:
                empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
                empty_box.set_margin_top(40)
                empty_lbl = Gtk.Label(label=f"No packages found matching '{query}'. Try switching filter source or checking spelling.")
                empty_lbl.add_css_class("dim-label")
                empty_lbl.set_wrap(True)
                empty_lbl.set_ellipsize(Pango.EllipsizeMode.END)
                empty_box.append(empty_lbl)
                self.browse_flow_box.append(empty_box)
                return

            seen_keys = set()
            idx = 0
            for r in results:
                try:
                    card_type = r.get("_card_type", "pkg") if isinstance(r, dict) else "pkg"
                    data = r.get("data", r) if isinstance(r, dict) else {}
                    item_key = (card_type, data.get("name", ""))
                    if not item_key[1] or item_key in seen_keys:
                        continue
                    seen_keys.add(item_key)
                    if card_type == "docker":
                        card = self._create_container_app_card(data)
                    elif card_type == "snap":
                        card = self._create_snap_app_card(data)
                    else:
                        card = self._create_mac_app_row(
                            data.get("name", ""),
                            data.get("desc", ""),
                            data.get("source", "pacman"),
                            title_override=data.get("display_name") or data.get("title", ""),
                            icon_override=data.get("icon", "")
                        )
                    self.browse_flow_box.append(card)
                    self._animate_card_entrance(card, idx)
                    idx += 1
                except Exception as card_err:
                    print(f"[Aura] Error rendering search card: {card_err}", file=sys.stderr)
        except Exception as e:
            print(f"[Aura] Error displaying search results: {e}", file=sys.stderr)

    # =========================================================================
    # Install / Update / Remove Background Actions with Silky Smooth Progress Lerp
    # =========================================================================
    def _start_smooth_progress(
        self,
        action: str,
        pkg_name: str,
        display_name: str = "",
        source: str = "pacman",
        target_view: str = "detail"
    ):
        """Initialize smooth state-tracked progress bar and multi-engine header capsule."""
        if getattr(self, "_progress_auto_hide_id", None):
            GLib.source_remove(self._progress_auto_hide_id)
            self._progress_auto_hide_id = None

        if not hasattr(self, "_active_ui_tasks"):
            self._active_ui_tasks = {}

        disp = display_name or get_app_display_name(pkg_name)
        key = (pkg_name or "system").strip().lower()

        if action == "install":
            st_text = f"Preparing to install {disp}..."
            pill_title = f"Installing {disp}"
        elif action == "remove":
            st_text = f"Preparing to remove {disp}..."
            pill_title = f"Removing {disp}"
        elif action in ["update", "upgrade"]:
            if pkg_name in ["system", "--all", "all", ""] or not pkg_name:
                st_text = "Upgrading all system packages..."
                pill_title = "Updating System"
            else:
                st_text = f"Updating {disp}..."
                pill_title = f"Updating {disp}"
        else:
            st_text = f"Working on {disp}..."
            pill_title = f"Processing {disp}"

        existing = self._active_ui_tasks.get(key)
        if existing is None:
            self._active_ui_tasks[key] = {
                "action": action,
                "pkg_name": pkg_name,
                "display_name": disp,
                "source": source,
                "target_view": target_view,
                "current": 0.05,
                "target": 0.08,
                "status": st_text,
                "pill_title": pill_title,
                "start_time": time.monotonic(),
            }
        else:
            existing["action"] = action
            existing["display_name"] = disp
            existing["source"] = source
            existing["target_view"] = target_view
            existing["pill_title"] = pill_title

        task = self._active_ui_tasks[key]
        self._progress_action = action
        self._progress_pkg_name = pkg_name
        self._progress_display_name = disp
        self._progress_source = source
        self._progress_target_view = target_view
        self._current_progress = task["current"]
        self._target_progress = task["target"]
        self._progress_status_text = task["status"]

        # 1. Floating Header Pill
        self.header_progress_pill.set_visible(True)
        self.header_progress_spinner.start()
        total_jobs = len(self._active_ui_tasks) + (self.pm.get_queue_length() if hasattr(self.pm, "get_queue_length") else 0)
        extra_tag = f" (+{total_jobs - 1} more)" if total_jobs > 1 else ""
        self.header_progress_label.set_text(f"⟳ {pill_title} • {int(task['current'] * 100)}%{extra_tag}")

        # 2. View specific containers
        if target_view == "detail":
            if self._current_detail and (self._current_detail.get("name") or "").strip().lower() == key:
                self.progress_container.set_visible(True)
                self.progress_bar.set_fraction(task["current"])
                self.progress_status_label.set_text(task["status"])
                self.progress_percent_label.set_text(f"{int(task['current'] * 100)}%")
                self.btn_detail_install.set_sensitive(False)
                self.btn_detail_install.set_label("INSTALLING..." if action == "install" else "WORKING...")
                self.btn_detail_launch.set_visible(False)
        elif target_view == "updates":
            self.updates_progress_box.set_visible(True)
            self.updates_progress_bar.set_fraction(task["current"])
            self.updates_progress_lbl.set_text(task["status"])
            self.updates_percent_label.set_text(f"{int(task['current'] * 100)}%")
            self.btn_update_all.set_sensitive(False)

        # 3. Start tick animation
        if not getattr(self, "_progress_anim_id", None):
            self._progress_anim_id = GLib.timeout_add(16, self._on_progress_lerp_tick)

    def _on_progress_update(self, frac: float, msg: str, pkg_name: Optional[str] = None):
        """Called asynchronously when any backend engine outputs progress."""
        def _apply():
            if not hasattr(self, "_active_ui_tasks"):
                self._active_ui_tasks = {}
            eff_pkg = pkg_name or self._progress_pkg_name or "system"
            key = eff_pkg.strip().lower()
            clamped = max(0.0, min(1.0, float(frac)))

            task = self._active_ui_tasks.get(key)
            if task is not None:
                # If task is still active (frac < 1.0), never step backwards; also ignore stale 1.0 from another task
                if clamped < 1.0 and task["target"] >= 1.0:
                    task["target"] = max(0.08, clamped)
                    task["current"] = min(task["current"], task["target"])
                else:
                    task["target"] = max(task["target"], clamped)
                if msg:
                    task["status"] = msg

            # If this update belongs to the primary displayed task (or no primary task is set), sync legacy fields
            if key == (self._progress_pkg_name or "").strip().lower() or not self._progress_pkg_name:
                self._progress_pkg_name = eff_pkg
                if task is not None:
                    self._target_progress = task["target"]
                    self._current_progress = task["current"]
                else:
                    self._target_progress = max(self._target_progress, clamped)
                if msg:
                    self._progress_status_text = msg

            # Update Detail Page if currently open for this package
            if self._current_detail and (self._current_detail.get("name") or "").strip().lower() == key:
                if self.progress_container.get_visible() and msg:
                    self.progress_status_label.set_text(msg)
                if hasattr(self, "progress_log_label"):
                    active_tx = self.pm.get_active_transaction() if hasattr(self.pm, "get_active_transaction") else None
                    if active_tx and active_tx.get("log_lines") and (active_tx.get("pkg_name") or "").strip().lower() == key:
                        tail = "\n".join(active_tx["log_lines"][-12:])
                        self.progress_log_label.set_text(tail)
                    elif msg:
                        self.progress_log_label.set_text(msg)

            if self._progress_target_view == "updates" and self.updates_progress_box.get_visible() and msg:
                self.updates_progress_lbl.set_text(msg)

            if not getattr(self, "_progress_anim_id", None):
                self._progress_anim_id = GLib.timeout_add(16, self._on_progress_lerp_tick)

            if self._progress_target_view == "updates" or (hasattr(self, "main_stack") and self.main_stack.get_visible_child_name() == "updates"):
                self._sync_updates_ui_state()
        GLib.idle_add(_apply)

    def _on_progress_lerp_tick(self) -> bool:
        """Smoothly interpolate current_fraction toward target_fraction at 60fps across all active tasks."""
        if not hasattr(self, "_active_ui_tasks"):
            self._active_ui_tasks = {}

        # Auto-adopt active_transaction if backend popped a queued package into active_transaction
        active_tx = self.pm.get_active_transaction() if hasattr(self.pm, "get_active_transaction") else None
        if active_tx and not active_tx.get("is_completed"):
            tx_pkg = (active_tx.get("pkg_name") or "").strip()
            tx_key = tx_pkg.lower()
            if tx_key and tx_key not in self._active_ui_tasks:
                tx_act = active_tx.get("action", "install")
                tx_src = active_tx.get("source", "pacman")
                tx_disp = get_app_display_name(tx_pkg)
                self._active_ui_tasks[tx_key] = {
                    "action": tx_act,
                    "pkg_name": tx_pkg,
                    "display_name": tx_disp,
                    "source": tx_src,
                    "target_view": "updates" if tx_act in ("update", "upgrade") else "detail",
                    "current": 0.05,
                    "target": max(0.08, float(active_tx.get("progress", 0.06))),
                    "status": str(active_tx.get("status_msg") or f"Installing {tx_disp}..."),
                    "pill_title": f"Updating {tx_disp}" if tx_act in ("update", "upgrade") else f"Installing {tx_disp}",
                    "start_time": time.monotonic(),
                }
            elif tx_key in self._active_ui_tasks:
                t_ref = self._active_ui_tasks[tx_key]
                bk_prog = float(active_tx.get("progress", 0.0))
                if 0.0 < bk_prog < 1.0:
                    t_ref["target"] = max(t_ref["target"], bk_prog)
                bk_msg = active_tx.get("status_msg") or active_tx.get("status")
                if bk_msg:
                    t_ref["status"] = str(bk_msg)

        # Interpolate every active task independently
        for t_key, task in list(self._active_ui_tasks.items()):
            diff = task["target"] - task["current"]
            if abs(diff) < 0.0005:
                task["current"] = task["target"]
            else:
                step = max(abs(diff) * 0.12, 0.0025)
                if diff > 0:
                    task["current"] = min(task["target"], task["current"] + step)
                else:
                    task["current"] = max(task["target"], task["current"] - step)

        # Sync primary progress task
        prim_key = (self._progress_pkg_name or "").strip().lower()
        prim_task = self._active_ui_tasks.get(prim_key)
        if prim_task is None and self._active_ui_tasks:
            prim_key, prim_task = next(iter(self._active_ui_tasks.items()))
            self._progress_pkg_name = prim_task["pkg_name"]
            self._progress_display_name = prim_task["display_name"]
            self._progress_action = prim_task["action"]
            self._progress_source = prim_task["source"]

        if prim_task is not None:
            self._current_progress = prim_task["current"]
            self._target_progress = prim_task["target"]
            self._progress_status_text = prim_task["status"]
        else:
            diff = self._target_progress - self._current_progress
            if abs(diff) < 0.0005:
                self._current_progress = self._target_progress
            else:
                step = max(abs(diff) * 0.12, 0.0025)
                self._current_progress = min(self._target_progress, self._current_progress + step) if diff > 0 else max(self._target_progress, self._current_progress - step)

        cur = self._current_progress
        pct = int(cur * 100)
        pct_str = f"{pct}%"

        # Update Detail page progress for whichever package is currently open on Detail page!
        if hasattr(self, "progress_bar") and hasattr(self, "progress_container") and self._current_detail:
            det_key = (self._current_detail.get("name") or "").strip().lower()
            det_task = self._active_ui_tasks.get(det_key)
            if det_task is not None:
                if not self.progress_container.get_visible():
                    self.progress_container.set_visible(True)
                det_cur = det_task["current"]
                self.progress_bar.set_fraction(det_cur)
                if hasattr(self, "progress_percent_label"):
                    self.progress_percent_label.set_text(f"{int(det_cur * 100)}%")
                if hasattr(self, "progress_status_label") and det_task.get("status"):
                    self.progress_status_label.set_text(det_task["status"])

        # Update Updates page progress if visible
        if hasattr(self, "updates_progress_bar") and hasattr(self, "updates_progress_box") and self.updates_progress_box.get_visible():
            self.updates_progress_bar.set_fraction(cur)
            if hasattr(self, "updates_percent_label"):
                self.updates_percent_label.set_text(pct_str)

        # Update Floating Header Pill
        if hasattr(self, "header_progress_pill") and self.header_progress_pill.get_visible():
            disp = self._progress_display_name or self._progress_pkg_name
            if self._progress_action == "install":
                pill_title = f"Installing {disp}"
            elif self._progress_action == "remove":
                pill_title = f"Removing {disp}"
            elif self._progress_action in ["update", "upgrade"]:
                if self._progress_pkg_name in ["system", "--all", "all", ""] or not self._progress_pkg_name:
                    pill_title = "Updating System"
                else:
                    pill_title = f"Updating {disp}"
            else:
                pill_title = f"Processing {disp}"
            total_jobs = len(self._active_ui_tasks) + (self.pm.get_queue_length() if hasattr(self.pm, "get_queue_length") else 0)
            extra_tag = f" (+{total_jobs - 1} more)" if total_jobs > 1 else ""
            if hasattr(self, "header_progress_label"):
                self.header_progress_label.set_text(f"⟳ {pill_title} • {pct_str}{extra_tag}")

        if not self._active_ui_tasks and self._current_progress >= self._target_progress:
            if not (hasattr(self.pm, "has_active_tasks") and self.pm.has_active_tasks()):
                self._progress_anim_id = None
                return False

        return True

    def _finish_smooth_progress(self, ok: bool, action: str, pkg_name: str, err: str = ""):
        """Handle completion or failure of background action while keeping other concurrent/queued tasks alive."""
        if not hasattr(self, "_active_ui_tasks"):
            self._active_ui_tasks = {}
        key = (pkg_name or "system").strip().lower()
        finished_task = self._active_ui_tasks.pop(key, None)
        disp = (finished_task.get("display_name") if finished_task else None) or (get_app_display_name(pkg_name) if pkg_name else "Package")

        # Update Detail page if the user is currently looking at the package that just finished
        if hasattr(self, "progress_bar") and self.progress_container.get_visible():
            if self._current_detail and (self._current_detail.get("name") or "").strip().lower() == key:
                if ok:
                    self.progress_bar.set_fraction(1.0)
                    self.progress_percent_label.set_text("100%")
                    if action == "install":
                        self.progress_status_label.set_text("✓ Installation complete!")
                    elif action == "remove":
                        self.progress_status_label.set_text("✓ Removed successfully!")
                    else:
                        self.progress_status_label.set_text("✓ Operation complete!")
                else:
                    self.progress_bar.set_fraction(0.0)
                    self.progress_percent_label.set_text("0%")
                    self.progress_status_label.set_text(f"Error: {err[:55]}")

        # Check if backend has already popped another queued package or if other concurrent tasks are running
        active_tx = self.pm.get_active_transaction() if hasattr(self.pm, "get_active_transaction") else None
        if active_tx and not active_tx.get("is_completed"):
            tx_pkg = (active_tx.get("pkg_name") or "").strip()
            tx_key = tx_pkg.lower()
            if tx_key and tx_key != key and tx_key not in self._active_ui_tasks:
                tx_act = active_tx.get("action", "install")
                tx_src = active_tx.get("source", "pacman")
                tx_disp = get_app_display_name(tx_pkg)
                self._active_ui_tasks[tx_key] = {
                    "action": tx_act,
                    "pkg_name": tx_pkg,
                    "display_name": tx_disp,
                    "source": tx_src,
                    "target_view": "updates" if tx_act in ("update", "upgrade") else "detail",
                    "current": 0.05,
                    "target": max(0.08, float(active_tx.get("progress", 0.06))),
                    "status": str(active_tx.get("status_msg") or f"Installing {tx_disp}..."),
                    "pill_title": f"Updating {tx_disp}" if tx_act in ("update", "upgrade") else f"Installing {tx_disp}",
                    "start_time": time.monotonic(),
                }

        # If other tasks are still active, seamlessly switch header pill to the next active task!
        if self._active_ui_tasks:
            next_key, next_task = next(iter(self._active_ui_tasks.items()))
            self._progress_pkg_name = next_task["pkg_name"]
            self._progress_display_name = next_task["display_name"]
            self._progress_action = next_task["action"]
            self._progress_source = next_task["source"]
            self._progress_target_view = next_task["target_view"]
            self._current_progress = next_task["current"]
            self._target_progress = next_task["target"]
            self._progress_status_text = next_task["status"]
            self.header_progress_pill.set_visible(True)
            self.header_progress_spinner.start()
            if not getattr(self, "_progress_anim_id", None):
                self._progress_anim_id = GLib.timeout_add(16, self._on_progress_lerp_tick)
            return

        if getattr(self, "_progress_anim_id", None):
            GLib.source_remove(self._progress_anim_id)
            self._progress_anim_id = None

        self.header_progress_spinner.stop()

        if ok:
            self._current_progress = 1.0
            self._target_progress = 1.0
            done_title = "System Updated" if pkg_name in ["system", "--all", "all", ""] else f"{disp} Done"
            self.header_progress_label.set_text(f"✓ {done_title}")

            if hasattr(self, "updates_progress_bar") and self.updates_progress_box.get_visible():
                self.updates_progress_bar.set_fraction(1.0)
                self.updates_percent_label.set_text("100%")
                self.updates_progress_lbl.set_text("✓ System update complete!" if pkg_name == "system" else f"✓ Updated {disp} successfully!")

            def _auto_dismiss():
                self._progress_auto_hide_id = None
                if getattr(self, "_progress_anim_id", None) or bool(getattr(self, "_active_ui_tasks", None)) or (hasattr(self.pm, "has_active_tasks") and self.pm.has_active_tasks()):
                    return False
                self.header_progress_pill.set_visible(False)
                if hasattr(self, "progress_container") and self._current_detail and (self._current_detail.get("name") or "").strip().lower() == key:
                    self.progress_container.set_visible(False)
                if hasattr(self, "updates_progress_box"):
                    self.updates_progress_box.set_visible(False)
                return False

            self._progress_auto_hide_id = GLib.timeout_add(2500, _auto_dismiss)
        else:
            self._current_progress = 0.0
            self._target_progress = 0.0
            self.header_progress_label.set_text(f"✕ Failed: {disp[:18]}")

            if hasattr(self, "updates_progress_bar") and self.updates_progress_box.get_visible():
                self.updates_progress_bar.set_fraction(0.0)
                self.updates_percent_label.set_text("0%")
                self.updates_progress_lbl.set_text(f"Error: {err[:55]}")

            def _auto_dismiss_err():
                self._progress_auto_hide_id = None
                if getattr(self, "_progress_anim_id", None) or bool(getattr(self, "_active_ui_tasks", None)) or (hasattr(self.pm, "has_active_tasks") and self.pm.has_active_tasks()):
                    return False
                self.header_progress_pill.set_visible(False)
                if hasattr(self, "progress_container") and self._current_detail and (self._current_detail.get("name") or "").strip().lower() == key:
                    self.progress_container.set_visible(False)
                if hasattr(self, "updates_progress_box"):
                    self.updates_progress_box.set_visible(False)
                return False

            self._progress_auto_hide_id = GLib.timeout_add(4500, _auto_dismiss_err)

    def _install_from_card(self, pkg_name: str, source: str = "pacman", btn: Optional[Gtk.Button] = None):
        """Install package directly when user clicks GET from any card in the store."""
        disp = get_app_display_name(pkg_name)

        if hasattr(self.pm, "is_pkg_updating") and self.pm.is_pkg_updating(pkg_name):
            return
        if hasattr(self.pm, "is_pkg_installing") and self.pm.is_pkg_installing(pkg_name):
            return
        if hasattr(self.pm, "is_pkg_queued") and self.pm.is_pkg_queued(pkg_name):
            return

        nl = pkg_name.strip().lower()
        rn = getattr(self.pm, "resolve_installed_pkg_name", lambda x: x)(nl).lower()
        is_upgradable = False
        with getattr(self.pm, "_lock", threading.Lock()):
            up_l = getattr(self.pm, "upgradable_list", [])
            is_upgradable = any(
                (u.get("name") or "").strip().lower() in (nl, rn, f"{nl}-bin")
                for u in up_l
            )
        if is_upgradable:
            self._update_single_package(pkg_name, source)
            return

        if self._is_pkg_installed_unified(pkg_name, source):
            self._open_or_launch(pkg_name, source)
            return

        if source == "snap":
            if not self.pm.snap_mgr.is_snapd_installed():
                self._open_package_detail(pkg_name, source)
                return

        matching_cards = []
        if hasattr(self, "_registered_cards"):
            matching_cards.extend(self._registered_cards.get(nl, []))
            if rn != nl:
                matching_cards.extend(self._registered_cards.get(rn, []))
        for card in matching_cards:
            b = getattr(card, "_action_btn", None)
            if b:
                b.set_sensitive(False)
                b.set_label("QUEUED")
                b.remove_css_class("mac-btn-get")
                b.remove_css_class("mac-btn-open")
                b.remove_css_class("mac-btn-installed")
                b.remove_css_class("mac-btn-update")
                b.add_css_class("mac-btn-queued")
        if btn and btn not in [getattr(c, "_action_btn", None) for c in matching_cards]:
            btn.set_sensitive(False)
            btn.set_label("QUEUED")
            btn.remove_css_class("mac-btn-get")
            btn.add_css_class("mac-btn-queued")

        def _on_start():
            def _ui_s():
                self._start_smooth_progress("install", pkg_name, display_name=disp, source=source, target_view="detail")
                if btn:
                    btn.set_label("INSTALLING...")
                    btn.remove_css_class("mac-btn-queued")
                    if not btn.has_css_class("mac-btn-get"):
                        btn.add_css_class("mac-btn-get")
                    btn.set_sensitive(False)
                self._sync_detail_page(pkg_name)
                self._sync_all_cards()
            GLib.idle_add(_ui_s)

        def _on_prog(frac: float, msg: str):
            def _ui_p():
                if getattr(self, "_progress_pkg_name", "") != pkg_name or not getattr(self, "_progress_anim_id", None):
                    self._start_smooth_progress("install", pkg_name, display_name=disp, source=source, target_view="detail")
                if btn:
                    if btn.get_label() == "QUEUED" and frac > 0.0:
                        btn.set_label("INSTALLING...")
                        btn.remove_css_class("mac-btn-queued")
                        btn.add_css_class("mac-btn-get")
                self._on_progress_update(frac, msg, pkg_name=pkg_name)
                self._sync_detail_page(pkg_name)
            GLib.idle_add(_ui_p)

        def _on_done(ok: bool, action: str, name: str, err: str):
            def _ui():
                self._finish_smooth_progress(ok, action, name, err)
                if ok:
                    self.show_toast(f"Successfully installed {disp}!")
                    self.pm.refresh_installed()
                    self._cached_installed_apps_flow = None
                    if hasattr(self, "sidebar_installed_badge"):
                        self.sidebar_installed_badge.set_text(str(len(self.pm.get_installed_desktop_apps())))
                    if btn:
                        has_desktop = bool(self.pm.detect_desktop_entry(name))
                        btn.set_label("OPEN" if has_desktop else "INSTALLED")
                        btn.remove_css_class("mac-btn-get")
                        btn.remove_css_class("mac-btn-queued")
                        btn.add_css_class("mac-btn-open" if has_desktop else "mac-btn-installed")
                        btn.set_sensitive(True)
                    self._sync_detail_page(name)
                    self._sync_all_cards()
                else:
                    if btn:
                        btn.set_label("GET")
                        btn.remove_css_class("mac-btn-queued")
                        btn.add_css_class("mac-btn-get")
                        btn.set_sensitive(True)
                    self.show_toast(f"Installation failed: {err[:50]}")
                    self._sync_detail_page(name)
                    self._sync_all_cards()
                GLib.timeout_add(300, lambda: (self._sync_all_cards(), self._sync_detail_page(name)) and False)
            GLib.idle_add(_ui)

        res = self.pm.execute_background_action("install", pkg_name, source, _on_prog, _on_done, start_cb=_on_start)
        if res == "queued":
            pos = self.pm.get_queue_position(pkg_name)
            self.show_toast(f"Added {disp} to installation queue (position #{pos})")
            if btn:
                btn.set_label("QUEUED")
                btn.remove_css_class("mac-btn-get")
                btn.add_css_class("mac-btn-queued")
                btn.set_sensitive(False)
            self._sync_detail_page(pkg_name)
            self._sync_all_cards()
        else:
            self._start_smooth_progress("install", pkg_name, display_name=disp, source=source, target_view="detail")
            self._sync_detail_page(pkg_name)
            self._sync_all_cards()

    def _on_install_click(self):
        if not self._current_detail:
            return
        name = self._current_detail["name"]
        source = self._current_detail.get("source", "pacman")
        disp = self._current_detail.get("display_name") or get_app_display_name(name)

        if source == "snap":
            if not self.pm.snap_mgr.is_snapd_installed():
                dlg = Adw.AlertDialog.new(
                    "Snap Service Required",
                    f"To install '{disp}' from Canonical's Snap Store, the snapd background service is required.\n\nWould you like Aura to automatically configure and start snapd now?"
                )
                dlg.add_response("cancel", "Cancel")
                dlg.add_response("setup", "Auto-Configure Now")
                dlg.set_response_appearance("setup", Adw.ResponseAppearance.SUGGESTED)

                def _on_snap_resp(dialog, resp_id):
                    if resp_id == "setup":
                        self._on_configure_snap_click(self.btn_configure_snap)
                dlg.connect("response", _on_snap_resp)
                dlg.present(self)
                return

        def _on_start():
            def _ui_s():
                self._start_smooth_progress("install", name, display_name=disp, source=source, target_view="detail")
                self._sync_detail_page(name)
                self._sync_all_cards()
            GLib.idle_add(_ui_s)

        def _on_prog(frac: float, status_msg: str):
            def _ui_p():
                if getattr(self, "_progress_pkg_name", "") != name or not getattr(self, "_progress_anim_id", None):
                    self._start_smooth_progress("install", name, display_name=disp, source=source, target_view="detail")
                if hasattr(self, "btn_detail_install") and self._current_detail and self._current_detail.get("name") == name:
                    if self.btn_detail_install.get_label() == "QUEUED" and frac > 0.0:
                        self.btn_detail_install.set_label("INSTALLING...")
                        self.btn_detail_install.remove_css_class("mac-btn-queued")
                        self.btn_detail_install.add_css_class("mac-btn-primary-large")
                self._on_progress_update(frac, status_msg, pkg_name=name)
                self._sync_detail_page(name)
            GLib.idle_add(_ui_p)

        def _on_done(ok: bool, action: str, pkg_name: str, err: str):
            def _ui():
                self._finish_smooth_progress(ok, action, pkg_name, err)
                if ok:
                    self.show_toast(f"Successfully installed {disp}!")
                    self.pm.refresh_installed()
                    self._cached_installed_apps_flow = None
                    if hasattr(self, "sidebar_installed_badge"):
                        self.sidebar_installed_badge.set_text(str(len(self.pm.get_installed_desktop_apps())))
                    self._sync_detail_page(pkg_name)
                    self._sync_all_cards()
                else:
                    self.btn_detail_install.set_sensitive(True)
                    self.btn_detail_install.remove_css_class("mac-btn-queued")
                    self.btn_detail_install.remove_css_class("mac-btn-primary-large")
                    self.btn_detail_install.add_css_class("mac-btn-get")
                    self.btn_detail_install.set_label("GET")
                    self.show_toast(f"Installation failed: {err[:50]}")
                    self._sync_detail_page(pkg_name)
                    self._sync_all_cards()
                GLib.timeout_add(300, lambda: (self._sync_all_cards(), self._sync_detail_page(pkg_name)) and False)
            GLib.idle_add(_ui)

        res = self.pm.execute_background_action("install", name, source, _on_prog, _on_done, start_cb=_on_start)
        if res == "queued":
            pos = self.pm.get_queue_position(name)
            self.btn_detail_install.set_label("QUEUED")
            self.btn_detail_install.remove_css_class("mac-btn-primary-large")
            self.btn_detail_install.add_css_class("mac-btn-queued")
            self.btn_detail_install.set_sensitive(False)
            self.show_toast(f"Added {disp} to installation queue (position #{pos})")
            self._sync_detail_page(name)
            self._sync_all_cards()
        else:
            self._start_smooth_progress("install", name, display_name=disp, source=source, target_view="detail")
            self._sync_detail_page(name)
            self._sync_all_cards()

    def _ensure_auth_then_run(self, action_callback):
        """
        Ensure a valid administrator session or passwordless sudo rule is active before
        launching background privileged actions. If not, prompt cleanly in-app once.
        """
        if self.pm.has_valid_sudo_session():
            action_callback()
            return

        dlg = Adw.AlertDialog.new(
            "Administrator Authentication",
            "Enter your sudo password to authorize this package action. You can enable Passwordless Mode below so Aura never needs to prompt again."
        )
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(6)
        box.set_margin_start(12)
        box.set_margin_end(12)

        entry = Gtk.PasswordEntry()
        entry.set_show_peek_icon(True)
        entry.set_hexpand(True)
        box.append(entry)

        chk_pwless = Gtk.CheckButton(label="Enable Lifetime Passwordless Mode (Recommended)")
        chk_pwless.set_active(True)
        box.append(chk_pwless)

        dlg.set_extra_child(box)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("auth", "Authorize & Continue")
        dlg.set_response_appearance("auth", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("auth")
        dlg.set_close_response("cancel")

        def _on_resp(d, resp):
            if resp == "auth":
                pwd = entry.get_text()
                if not pwd:
                    self.show_toast("Password cannot be empty.")
                    return
                ok, msg = self.pm.authenticate_session(pwd, enable_passwordless=chk_pwless.get_active())
                self._update_auth_btn_status()
                if ok:
                    action_callback()
                else:
                    self.show_toast(msg)

        dlg.connect("response", _on_resp)
        dlg.present(self)

    def _confirm_package_uninstall(self, name: str, source: str = "pacman", display_name: str = ""):
        """
        Present a smart Uninstall confirmation sheet showing the resolved package name
        and a Clean Uninstall toggle to purge residual ~/.config, ~/.cache, and ~/.local/share data.
        """
        disp = display_name or get_app_display_name(name)
        resolved_pkg = self.pm.resolve_installed_pkg_name(name) if hasattr(self.pm, "resolve_installed_pkg_name") else name

        if source == "docker" or (hasattr(self.pm, "container_mgr") and self.pm.container_mgr.is_app_installed(name)):
            self._confirm_container_uninstall(name, disp, self.btn_detail_remove)
            return

        dlg = Adw.AlertDialog.new(
            f"Uninstall {disp}?",
            f"This will remove package '{resolved_pkg}' ({source.upper()}) and its unused dependencies from your system."
        )
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(6)
        box.set_margin_start(12)
        box.set_margin_end(12)

        chk_clean = Gtk.CheckButton()
        chk_clean.set_active(True)
        chk_clean_lbl = Gtk.Label(
            label="Clean Uninstall (Also purge residual ~/.config, ~/.cache, and ~/.local/share app data)"
        )
        chk_clean_lbl.set_wrap(True)
        chk_clean_lbl.set_xalign(0.0)
        chk_clean_lbl.set_max_width_chars(38)
        chk_clean.set_child(chk_clean_lbl)
        box.append(chk_clean)

        dlg.set_extra_child(box)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("uninstall", "Uninstall")
        dlg.set_response_appearance("uninstall", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("uninstall")
        dlg.set_close_response("cancel")

        def _on_resp(d, resp):
            if resp == "uninstall":
                clean_mode = chk_clean.get_active()
                self._execute_package_removal(name, source, disp, clean_remove=clean_mode)

        dlg.connect("response", _on_resp)
        dlg.present(self)

    def _execute_package_removal(self, name: str, source: str, disp: str, clean_remove: bool = True):
        if source == "snap":
            import shutil
            if not shutil.which("snap"):
                self.show_toast("Snap daemon is not installed.")
                return

        resolved_pkg = self.pm.resolve_installed_pkg_name(name)
        action_type = "clean_remove" if clean_remove else "remove"
        self.btn_detail_remove.set_sensitive(False)
        curr_view = self.main_stack.get_visible_child_name()
        target_v = "detail" if curr_view == "detail" else "updates"
        self._start_smooth_progress("remove", name, display_name=disp, source=source, target_view=target_v)

        def _on_prog(frac: float, status_msg: str):
            self._on_progress_update(frac, status_msg, pkg_name=name)
            self._sync_detail_page(name)

        def _on_done(ok: bool, action: str, pkg_name: str, err: str):
            def _ui():
                self.btn_detail_remove.set_sensitive(True)
                self._finish_smooth_progress(ok, "remove", pkg_name, err)
                if ok:
                    msg_suffix = " and purged residual app data!" if clean_remove else "!"
                    self.show_toast(f"Successfully uninstalled {disp}{msg_suffix}")
                    self.pm.refresh_installed()
                    self._cached_installed_apps_flow = None
                    num_inst = len(self.pm.get_installed_desktop_apps())
                    if hasattr(self, "sidebar_installed_badge"):
                        self.sidebar_installed_badge.set_text(str(num_inst))
                    if self.main_stack.get_visible_child_name() == "installed":
                        self._load_installed_view()
                    elif self.main_stack.get_visible_child_name() == "deb":
                        self._load_deb_view()
                    self._sync_detail_page(name)
                    self._sync_detail_page(resolved_pkg)
                    self._sync_all_cards()
                else:
                    self.show_toast(f"Removal failed: {err[:65]}")
                    self._sync_detail_page(name)
                    self._sync_all_cards()
                GLib.timeout_add(300, lambda: (self._sync_all_cards(), self._sync_detail_page(name)) and False)
            GLib.idle_add(_ui)

        self.pm.execute_background_action(action_type, resolved_pkg, source, _on_prog, _on_done)

    def _on_remove_click(self):
        if not self._current_detail:
            return
        name = self._current_detail["name"]
        source = self._current_detail.get("source", "pacman")
        disp = self._current_detail.get("display_name") or get_app_display_name(name)
        self._confirm_package_uninstall(name, source, disp)

    def _update_single_package(self, pkg_name: str, source: str = "pacman"):
        disp = get_app_display_name(pkg_name)

        # 1. Immediately set that specific package's button to UPDATING... (sensitive=False)
        btn = self._updates_buttons.get(pkg_name)
        if btn:
            btn.set_label("UPDATING...")
            btn.remove_css_class("mac-btn-update")
            btn.remove_css_class("mac-btn-installed")
            btn.add_css_class("mac-btn-get")
            btn.set_sensitive(False)

        # Also update detail page button if viewing this package
        if hasattr(self, "btn_detail_update") and self.main_stack.get_visible_child_name() == "detail" and self._current_detail and self._current_detail.get("name") == pkg_name:
            self.btn_detail_update.set_label("UPDATING...")
            self.btn_detail_update.set_sensitive(False)

        if hasattr(self, "btn_banner_update") and self.main_stack.get_visible_child_name() == "detail" and self._current_detail and self._current_detail.get("name") == pkg_name:
            self.btn_banner_update.set_label("UPDATING...")
            self.btn_banner_update.set_sensitive(False)

        # Immediately notify all matching cards across Discover, Category, and grids
        nl = pkg_name.strip().lower()
        rn = getattr(self.pm, "resolve_installed_pkg_name", lambda x: x)(nl).lower()
        matching_cards = []
        if hasattr(self, "_registered_cards"):
            matching_cards.extend(self._registered_cards.get(nl, []))
            if rn != nl:
                matching_cards.extend(self._registered_cards.get(rn, []))
        for card in matching_cards:
            b = getattr(card, "_action_btn", None)
            if b:
                b.set_label("UPDATING...")
                b.remove_css_class("mac-btn-update")
                b.remove_css_class("mac-btn-installed")
                b.remove_css_class("mac-btn-open")
                b.remove_css_class("mac-btn-queued")
                if not b.has_css_class("mac-btn-get"):
                    b.add_css_class("mac-btn-get")
                b.set_sensitive(False)
        self._sync_all_cards()

        def _on_start():
            def _ui_s():
                self._start_smooth_progress("update", pkg_name, display_name=disp, source=source, target_view="updates")
                self._sync_all_cards()
            GLib.idle_add(_ui_s)

        def _on_prog(frac: float, msg: str):
            def _ui_p():
                if getattr(self, "_progress_pkg_name", "") != pkg_name or not getattr(self, "_progress_anim_id", None):
                    self._start_smooth_progress("update", pkg_name, display_name=disp, source=source, target_view="updates")
                if hasattr(self, "_updates_buttons") and pkg_name in self._updates_buttons:
                    b = self._updates_buttons[pkg_name]
                    if b.get_label() == "QUEUED" and frac > 0.0:
                        b.set_label("UPDATING...")
                        b.remove_css_class("mac-btn-queued")
                        b.add_css_class("mac-btn-get")
                if hasattr(self, "btn_banner_update") and self.main_stack.get_visible_child_name() == "detail" and self._current_detail and self._current_detail.get("name") == pkg_name:
                    if self.btn_banner_update.get_label() == "QUEUED" and frac > 0.0:
                        self.btn_banner_update.set_label("UPDATING...")
                        self.btn_banner_update.remove_css_class("mac-btn-queued")
                        self.btn_banner_update.add_css_class("mac-btn-get")
                self._on_progress_update(frac, msg)
            GLib.idle_add(_ui_p)

        def _on_done(ok: bool, action: str, name: str, err: str):
            def _ui():
                self._finish_smooth_progress(ok, action, name, err)
                if ok:
                    self.show_toast(f"Updated {disp} successfully!")
                    res_inst = getattr(self.pm, "resolve_installed_pkg_name", lambda x: x)(name)
                    with self.pm._lock:
                        self.pm.upgradable_list = [
                            u for u in self.pm.upgradable_list
                            if u.get("name") not in (name, f"{name}-bin", res_inst)
                        ]
                    rem = len(self.pm.upgradable_list)
                    self.sidebar_updates_badge.set_text(str(rem) if rem > 0 else "")
                    self.sidebar_updates_badge.set_visible(rem > 0)
                    self.pm.refresh_installed()
                    num_inst = len(self.pm.get_installed_desktop_apps())
                    self.sidebar_installed_badge.set_text(str(num_inst))
                    self._cached_installed_apps_flow = None
                    self._populate_updates(self.pm.upgradable_list)
                    # Refresh detail page if open for this package
                    self._sync_detail_page(name)
                else:
                    self.show_toast(f"Update failed for {disp}: {err[:50]}")
                    self._sync_updates_ui_state()
                self._sync_all_cards()
            GLib.idle_add(_ui)

        res = self.pm.execute_background_action("update", pkg_name, source, _on_prog, _on_done, start_cb=_on_start)
        if res == "queued":
            pos = self.pm.get_queue_position(pkg_name)
            if btn:
                btn.set_label("QUEUED")
                btn.remove_css_class("mac-btn-get")
                btn.remove_css_class("mac-btn-update")
                btn.add_css_class("mac-btn-queued")
                btn.set_sensitive(False)
            for card in matching_cards:
                b = getattr(card, "_action_btn", None)
                if b:
                    b.set_label("QUEUED")
                    b.remove_css_class("mac-btn-get")
                    b.remove_css_class("mac-btn-update")
                    b.remove_css_class("mac-btn-installed")
                    b.remove_css_class("mac-btn-open")
                    b.add_css_class("mac-btn-queued")
                    b.set_sensitive(False)
            if hasattr(self, "btn_detail_update") and self.main_stack.get_visible_child_name() == "detail" and self._current_detail and self._current_detail.get("name") == pkg_name:
                self.btn_detail_update.set_label("QUEUED")
                self.btn_detail_update.remove_css_class("mac-btn-get")
                self.btn_detail_update.add_css_class("mac-btn-queued")
                self.btn_detail_update.set_sensitive(False)
            if hasattr(self, "btn_banner_update") and self.main_stack.get_visible_child_name() == "detail" and self._current_detail and self._current_detail.get("name") == pkg_name:
                self.btn_banner_update.set_label("QUEUED")
                self.btn_banner_update.remove_css_class("mac-btn-update")
                self.btn_banner_update.add_css_class("mac-btn-queued")
                self.btn_banner_update.set_sensitive(False)
            self.show_toast(f"Added {disp} update to queue (position #{pos})")
            self._sync_all_cards()
        else:
            self._start_smooth_progress("update", pkg_name, display_name=disp, source=source, target_view="updates")
            self._sync_all_cards()

    def _update_all_packages(self):
        # 1. Immediately disable UPDATE ALL button
        if hasattr(self, "btn_update_all"):
            self.btn_update_all.set_sensitive(False)

        # 2. Disable other package cards in the list to prevent conflicting parallel pacman locks
        for btn in self._updates_buttons.values():
            btn.set_sensitive(False)

        self._start_smooth_progress("update", "system", display_name="System Packages", source="pacman", target_view="updates")
        self._sync_all_cards()

        def _on_prog(frac: float, msg: str):
            self._on_progress_update(frac, msg)

        def _on_done(ok: bool, action: str, name: str, err: str):
            def _ui():
                self._finish_smooth_progress(ok, action, name, err)
                if ok:
                    self.show_toast("All packages updated successfully!")
                    with self.pm._lock:
                        self.pm.upgradable_list = []
                    self.sidebar_updates_badge.set_text("")
                    self.sidebar_updates_badge.set_visible(False)
                    self.pm.refresh_installed()
                    num_inst = len(self.pm.get_installed_desktop_apps())
                    self.sidebar_installed_badge.set_text(str(num_inst))
                    self._populate_updates([])
                    self._sync_all_cards()
                else:
                    self.show_toast(f"System update error: {err[:50]}")
                    if hasattr(self, "btn_update_all"):
                        self.btn_update_all.set_sensitive(True)
                    self._sync_updates_ui_state()
                    self._sync_all_cards()
                GLib.timeout_add(300, lambda: self._sync_all_cards() or False)
            GLib.idle_add(_ui)

        self.pm.execute_background_action("update", "system", "pacman", _on_prog, _on_done)

    def _pulse_updates_bar(self) -> bool:
        return False

    def _pulse_detail_bar(self) -> bool:
        return False

    # =========================================================================
    # Helpers & Async Database Loading
    # =========================================================================
    def show_toast(self, message: str):
        toast = Adw.Toast.new(message)
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    def _load_data_async(self):
        def _bg():
            self.pm.load_pacman_db()
            upgrades = self.pm.check_updates()
            GLib.idle_add(lambda: self._on_data_loaded(len(upgrades)))
        threading.Thread(target=_bg, daemon=True).start()

    def _on_data_loaded(self, update_count: int):
        if update_count > 0:
            self.sidebar_updates_badge.set_text(str(update_count))
            self.sidebar_updates_badge.set_visible(True)
        else:
            self.sidebar_updates_badge.set_visible(False)
        if self.main_stack.get_visible_child_name() == "updates":
            self._load_updates_view()

    # =========================================================================
    # System Doctor UI in Storage & Maintenance Page
    # =========================================================================
    def _update_doctor_ui(self, health: Dict[str, Any]):
        if not hasattr(self, "doctor_rows_box"):
            return
        if not hasattr(self, "_doctor_row_widgets"):
            self._doctor_row_widgets = {}

        lock_st = health.get("lock_status", {})
        is_locked = lock_st.get("locked", False)
        is_stale = lock_st.get("is_stale", False)
        active_procs = lock_st.get("active_processes", [])

        # 1. Pacman Database Lock Card
        if is_stale:
            lock_sub = "Stale /var/lib/pacman/db.lck detected (no package manager running). Click Unlock to fix."
            lock_status_txt = "Stale Lock"
        elif is_locked:
            lock_sub = f"Database currently in use by: {', '.join(active_procs)}"
            lock_status_txt = "Busy"
        else:
            lock_sub = "No stale database lock (/var/lib/pacman/db.lck is clean and ready)."
            lock_status_txt = "Healthy"

        # 2. Orphaned Packages Card
        orphan_count = health.get("orphan_count", 0)
        orphans = health.get("orphans", [])
        orphan_names = ", ".join(o["name"] for o in orphans[:5])
        if orphan_count > 5:
            orphan_names += f" +{orphan_count - 5} more"
        orphan_desc = (
            f"Unused build & dependency packages ({orphan_names}). Safe to remove via pacman -Rns."
            if orphan_count > 0 else "Zero unused orphaned dependency packages on your system."
        )

        # 3. Arch Linux Keyring & Sync Repair Card
        pacnew_count = health.get("pacnew_count", 0)
        pacnew_note = f" • {pacnew_count} .pacnew config(s) in /etc" if pacnew_count > 0 else " • PGP master keys active"
        keyring_desc = "Re-initializes pacman-key, populates master signatures, and refreshes archlinux-keyring to fix PGP errors." + pacnew_note

        specs = [
            ("lock", "changes-prevent-symbolic", "Pacman Database Lock Status", lock_sub, lock_status_txt, "/var/lib/pacman/db.lck", "Unlock DB", is_stale, self._on_doctor_unlock_click),
            ("orphans", "user-trash-symbolic", "Orphaned Dependencies (pacman -Qdt)", orphan_desc, f"{orphan_count} Orphans", "Unused packages", "Remove Orphans", (orphan_count > 0), self._on_doctor_orphans_click),
            ("keyring", "security-high-symbolic", "Arch Linux Keyring & Database Sync", keyring_desc, "PGP Keyring", "archlinux-keyring", "Repair Keyring", True, self._on_doctor_keyring_click),
        ]

        for key, icon_name, title, desc, metric_top, metric_sub, btn_label, btn_sensitive, on_click in specs:
            existing = self._doctor_row_widgets.get(key)
            if existing is not None and existing.get_parent() == self.doctor_rows_box:
                existing._desc_lbl.set_label(desc)
                existing._top_lbl.set_label(metric_top)
                existing._sub_lbl.set_label(metric_sub)
                existing._btn.set_label(btn_label)
                existing._btn.set_sensitive(btn_sensitive)
            else:
                row = self._create_doctor_action_row(
                    icon_name=icon_name,
                    title=title,
                    desc=desc,
                    metric_top=metric_top,
                    metric_sub=metric_sub,
                    btn_label=btn_label,
                    btn_sensitive=btn_sensitive,
                    on_click=on_click
                )
                self._doctor_row_widgets[key] = row
                self.doctor_rows_box.append(row)

    def _create_doctor_action_row(
        self,
        icon_name: str,
        title: str,
        desc: str,
        metric_top: str,
        metric_sub: str,
        btn_label: str,
        btn_sensitive: bool,
        on_click
    ) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("mac-cache-row")
        row.set_valign(Gtk.Align.CENTER)
        row.set_hexpand(True)

        icon_box = Gtk.Box()
        icon_box.add_css_class("mac-squircle")
        icon_box.set_size_request(44, 44)
        icon_box.set_homogeneous(True)
        icon_box.set_halign(Gtk.Align.CENTER)
        icon_box.set_valign(Gtk.Align.CENTER)
        icon_box.set_hexpand(False)
        icon_box.set_vexpand(False)
        icon_img = create_scaled_image(icon_name, size=22)
        icon_box.append(icon_img)
        row.append(icon_box)

        info_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_col.set_hexpand(True)
        info_col.set_valign(Gtk.Align.CENTER)

        title_lbl = Gtk.Label(label=title)
        title_lbl.add_css_class("mac-app-title")
        title_lbl.set_halign(Gtk.Align.FILL)
        title_lbl.set_xalign(0.0)
        title_lbl.set_hexpand(True)
        title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        title_lbl.set_max_width_chars(28)
        info_col.append(title_lbl)

        desc_lbl = Gtk.Label(label=desc)
        desc_lbl.add_css_class("mac-app-desc")
        desc_lbl.set_halign(Gtk.Align.FILL)
        desc_lbl.set_xalign(0.0)
        desc_lbl.set_hexpand(True)
        desc_lbl.set_wrap(True)
        desc_lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        desc_lbl.set_lines(2)
        desc_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        desc_lbl.set_max_width_chars(34)
        info_col.append(desc_lbl)
        row.append(info_col)

        size_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        size_col.set_valign(Gtk.Align.CENTER)
        size_col.set_hexpand(False)
        size_col.set_margin_end(6)

        top_lbl = Gtk.Label(label=metric_top)
        top_lbl.add_css_class("mac-app-title")
        top_lbl.set_halign(Gtk.Align.END)
        top_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        top_lbl.set_max_width_chars(16)
        size_col.append(top_lbl)

        sub_lbl = Gtk.Label(label=metric_sub)
        sub_lbl.add_css_class("dim-label")
        sub_lbl.set_halign(Gtk.Align.END)
        sub_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        sub_lbl.set_max_width_chars(16)
        size_col.append(sub_lbl)
        row.append(size_col)

        btn = Gtk.Button(label=btn_label)
        btn.add_css_class("mac-btn-get")
        btn.set_valign(Gtk.Align.CENTER)
        btn.set_hexpand(False)
        btn.set_size_request(110, 32)
        btn.set_sensitive(btn_sensitive)
        btn.connect("clicked", on_click)
        row.append(btn)
        row._desc_lbl = desc_lbl
        row._top_lbl = top_lbl
        row._sub_lbl = sub_lbl
        row._btn = btn
        return row

    def _on_doctor_unlock_click(self, btn: Gtk.Button):
        btn.set_sensitive(False)
        btn.set_label("Unlocking...")
        self.pm.doctor_mgr.unlock_pacman_db(
            complete_cb=lambda ok, msg: GLib.idle_add(lambda: (self.show_toast(msg), self._load_storage_view()))
        )

    def _on_doctor_orphans_click(self, btn: Gtk.Button):
        btn.set_sensitive(False)
        btn.set_label("Removing...")
        self.pm.doctor_mgr.remove_orphans(
            progress_cb=None,
            complete_cb=lambda ok, msg: GLib.idle_add(lambda: (self.show_toast(msg), self._load_storage_view()))
        )

    def _on_doctor_keyring_click(self, btn: Gtk.Button):
        btn.set_sensitive(False)
        btn.set_label("Repairing...")
        self.pm.doctor_mgr.repair_keyring(
            progress_cb=None,
            complete_cb=lambda ok, msg: GLib.idle_add(lambda: (btn.set_sensitive(True), btn.set_label("Repair Keyring"), self.show_toast(msg)))
        )

    # =========================================================================
    # Page 10: .deb Package Bridge (Seamless Debian .deb Installer for Arch)
    # =========================================================================
    def _build_deb_page(self) -> Gtk.ScrolledWindow:
        scrolled = Gtk.ScrolledWindow()
        scrolled.add_css_class("aura-page")
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(20)
        box.set_margin_bottom(36)
        box.set_margin_start(20)
        box.set_margin_end(20)

        # 1. Page Title Header
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        page_title = Gtk.Label(label=".deb Package Installer")
        page_title.add_css_class("mac-page-title")
        page_title.set_halign(Gtk.Align.START)
        title_box.append(page_title)

        page_subtitle = Gtk.Label(
            label="Seamlessly convert, resolve Arch dependencies, apply Hyprland Wayland fixes, and install .deb files via Pacman"
        )
        page_subtitle.add_css_class("mac-page-subtitle")
        page_subtitle.set_halign(Gtk.Align.START)
        page_subtitle.set_wrap(True)
        page_subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        page_subtitle.set_max_width_chars(52)
        title_box.append(page_subtitle)
        box.append(title_box)

        # 2. Hero Dropzone & File/URL Selector Spotlight Banner
        hero_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        hero_card.add_css_class("mac-container-status-card")
        hero_card.set_valign(Gtk.Align.CENTER)
        hero_card.set_hexpand(True)

        deb_icon_box = Gtk.Box()
        deb_icon_box.add_css_class("mac-squircle")
        deb_icon_box.set_size_request(54, 54)
        deb_icon_box.set_homogeneous(True)
        deb_icon_box.set_halign(Gtk.Align.CENTER)
        deb_icon_box.set_valign(Gtk.Align.CENTER)
        deb_icon_box.set_hexpand(False)
        deb_icon_box.set_vexpand(False)
        deb_icon = create_scaled_image("package-x-generic-symbolic", size=30)
        deb_icon_box.append(deb_icon)
        hero_card.append(deb_icon_box)

        deb_info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        deb_info_box.set_hexpand(True)
        deb_info_box.set_valign(Gtk.Align.CENTER)

        deb_title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        deb_title = Gtk.Label(label="Native Arch Linux .deb Bridge")
        deb_title.add_css_class("mac-spotlight-title")
        deb_title.set_halign(Gtk.Align.START)
        deb_title.set_ellipsize(Pango.EllipsizeMode.END)
        deb_title.set_max_width_chars(28)
        deb_title_row.append(deb_title)

        deb_pill = Gtk.Label(label="PACMAN TRACKED")
        deb_pill.add_css_class("mac-container-pill")
        deb_pill.add_css_class("mac-container-pill-active")
        deb_title_row.append(deb_pill)
        deb_info_box.append(deb_title_row)

        deb_desc = Gtk.Label(
            label="Drop any .deb file onto Aura, choose a local archive, or paste a direct download URL. Automatically maps Debian libraries to Arch packages."
        )
        deb_desc.add_css_class("mac-spotlight-desc")
        deb_desc.set_halign(Gtk.Align.FILL)
        deb_desc.set_xalign(0.0)
        deb_desc.set_hexpand(True)
        deb_desc.set_wrap(True)
        deb_desc.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        deb_desc.set_lines(2)
        deb_desc.set_ellipsize(Pango.EllipsizeMode.END)
        deb_desc.set_max_width_chars(38)
        deb_info_box.append(deb_desc)

        # Wayland Electron auto-fix checkbox with wrapped/ellipsized child label (zero horizontal overflow)
        wayland_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        wayland_row.set_margin_top(2)
        self.chk_deb_wayland = Gtk.CheckButton()
        self.chk_deb_wayland.set_active(True)
        chk_wl_lbl = Gtk.Label(label="Auto-inject Hyprland Native Wayland flags (--ozone-platform-hint=auto)")
        chk_wl_lbl.add_css_class("mac-app-desc")
        chk_wl_lbl.set_halign(Gtk.Align.START)
        chk_wl_lbl.set_xalign(0.0)
        chk_wl_lbl.set_wrap(True)
        chk_wl_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        chk_wl_lbl.set_max_width_chars(36)
        self.chk_deb_wayland.set_child(chk_wl_lbl)
        wayland_row.append(self.chk_deb_wayland)
        deb_info_box.append(wayland_row)

        hero_card.append(deb_info_box)

        # Action Buttons (Select .deb File + Install from URL)
        deb_btn_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        deb_btn_col.set_valign(Gtk.Align.CENTER)
        deb_btn_col.set_hexpand(False)

        btn_pick_deb = Gtk.Button(label="Select .deb File...")
        btn_pick_deb.add_css_class("mac-btn-get")
        btn_pick_deb.set_size_request(132, 32)
        btn_pick_deb.connect("clicked", self._on_pick_deb_file_click)
        deb_btn_col.append(btn_pick_deb)

        btn_url_deb = Gtk.Button(label="Install from URL...")
        btn_url_deb.add_css_class("mac-btn-installed")
        btn_url_deb.set_size_request(132, 32)
        btn_url_deb.connect("clicked", self._on_deb_url_click)
        deb_btn_col.append(btn_url_deb)

        hero_card.append(deb_btn_col)
        box.append(hero_card)

        # 3. Live .deb Inspector & Progress Card (Shown when a .deb file is selected/dropped)
        self.deb_inspector_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.deb_inspector_card.add_css_class("mac-about-card")
        self.deb_inspector_card.set_visible(False)

        insp_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.deb_insp_icon_box = Gtk.Box()
        self.deb_insp_icon_box.add_css_class("mac-squircle")
        self.deb_insp_icon_box.set_homogeneous(True)
        self.deb_insp_icon_box.set_size_request(64, 64)
        self.deb_insp_icon_box.set_hexpand(False)
        self.deb_insp_icon_box.set_vexpand(False)
        self.deb_insp_icon_box.set_halign(Gtk.Align.CENTER)
        self.deb_insp_icon_box.set_valign(Gtk.Align.CENTER)
        insp_top.append(self.deb_insp_icon_box)

        insp_meta_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        insp_meta_col.set_hexpand(True)
        insp_meta_col.set_valign(Gtk.Align.CENTER)

        self.deb_insp_title = Gtk.Label(label="Package Name")
        self.deb_insp_title.add_css_class("mac-section-title")
        self.deb_insp_title.set_halign(Gtk.Align.START)
        self.deb_insp_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.deb_insp_title.set_max_width_chars(32)
        insp_meta_col.append(self.deb_insp_title)

        self.deb_insp_sub = Gtk.Label(label="version • arch • size")
        self.deb_insp_sub.add_css_class("mac-app-desc")
        self.deb_insp_sub.set_halign(Gtk.Align.START)
        self.deb_insp_sub.set_ellipsize(Pango.EllipsizeMode.END)
        self.deb_insp_sub.set_max_width_chars(38)
        insp_meta_col.append(self.deb_insp_sub)

        self.deb_insp_deps_lbl = Gtk.Label(label="")
        self.deb_insp_deps_lbl.add_css_class("dim-label")
        self.deb_insp_deps_lbl.set_halign(Gtk.Align.START)
        self.deb_insp_deps_lbl.set_wrap(True)
        self.deb_insp_deps_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.deb_insp_deps_lbl.set_max_width_chars(38)
        insp_meta_col.append(self.deb_insp_deps_lbl)

        insp_top.append(insp_meta_col)

        self.btn_deb_install_now = Gtk.Button(label="INSTALL .DEB")
        self.btn_deb_install_now.add_css_class("mac-btn-primary-large")
        self.btn_deb_install_now.set_valign(Gtk.Align.CENTER)
        self.btn_deb_install_now.set_size_request(140, 38)
        self.btn_deb_install_now.connect("clicked", self._on_install_inspected_deb_click)
        insp_top.append(self.btn_deb_install_now)

        self.deb_inspector_card.append(insp_top)

        # Progress bar inside .deb inspector
        self.deb_progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.deb_progress_box.set_visible(False)
        self.deb_progress_lbl = Gtk.Label(label="Converting and installing .deb package...")
        self.deb_progress_lbl.add_css_class("mac-progress-title")
        self.deb_progress_lbl.set_halign(Gtk.Align.START)
        self.deb_progress_box.append(self.deb_progress_lbl)

        self.deb_progress_bar = Gtk.ProgressBar()
        self.deb_progress_bar.add_css_class("mac-capsule-progress")
        self.deb_progress_box.append(self.deb_progress_bar)
        self.deb_inspector_card.append(self.deb_progress_box)

        box.append(self.deb_inspector_card)

        # 4. Discovered .deb Archives in ~/Downloads
        dl_hdr_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        dl_hdr = Gtk.Label(label="Discovered .deb Files in ~/Downloads")
        dl_hdr.add_css_class("mac-section-title")
        dl_hdr.set_halign(Gtk.Align.START)
        dl_hdr_box.append(dl_hdr)

        sp_dl = Gtk.Box()
        sp_dl.set_hexpand(True)
        dl_hdr_box.append(sp_dl)

        btn_rescan_deb = Gtk.Button(label="Rescan Downloads")
        btn_rescan_deb.add_css_class("mac-see-all-btn")
        btn_rescan_deb.connect("clicked", lambda b: self._load_deb_view())
        dl_hdr_box.append(btn_rescan_deb)
        box.append(dl_hdr_box)

        self.deb_local_status_lbl = Gtk.Label(label="Scanning ~/Downloads for .deb archives...")
        self.deb_local_status_lbl.add_css_class("dim-label")
        self.deb_local_status_lbl.set_halign(Gtk.Align.START)
        self.deb_local_status_lbl.set_wrap(True)
        self.deb_local_status_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.deb_local_status_lbl.set_max_width_chars(52)
        box.append(self.deb_local_status_lbl)

        self.deb_local_flow_box = self._create_symmetric_grid(min_columns=1, max_columns=4)
        box.append(self.deb_local_flow_box)

        # 5. Installed .deb Packages Section
        inst_hdr = Gtk.Label(label="Installed .deb Applications (Tracked by Pacman)")
        inst_hdr.add_css_class("mac-section-title")
        inst_hdr.set_halign(Gtk.Align.START)
        inst_hdr.set_ellipsize(Pango.EllipsizeMode.END)
        inst_hdr.set_margin_top(12)
        box.append(inst_hdr)

        self.deb_installed_status_lbl = Gtk.Label(label="No .deb packages installed yet.")
        self.deb_installed_status_lbl.add_css_class("dim-label")
        self.deb_installed_status_lbl.set_halign(Gtk.Align.START)
        self.deb_installed_status_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.deb_installed_status_lbl.set_max_width_chars(52)
        box.append(self.deb_installed_status_lbl)

        self.deb_installed_flow_box = self._create_symmetric_grid(min_columns=1, max_columns=4)
        box.append(self.deb_installed_flow_box)

        scrolled.set_child(box)
        return scrolled

    def _load_deb_view(self, inspect_path: Optional[str] = None):
        if inspect_path:
            self._inspect_and_display_deb(inspect_path)

        def _bg():
            local_debs = self.pm.deb_mgr.scan_local_debs() if hasattr(self.pm, "deb_mgr") else []
            inst_debs = self.pm.deb_mgr.get_installed_debs() if hasattr(self.pm, "deb_mgr") else []

            def _ui():
                self.deb_local_flow_box.remove_all()
                if local_debs:
                    self.deb_local_status_lbl.set_text(
                        f"Found {len(local_debs)} .deb archive{'s' if len(local_debs) != 1 else ''} ready for 1-click installation"
                    )
                    for d_info in local_debs:
                        self.deb_local_flow_box.append(self._create_deb_file_card(d_info))
                else:
                    self.deb_local_status_lbl.set_text(
                        "No .deb files found in ~/Downloads. Click 'Select .deb File...' above or drop a .deb file onto this window."
                    )

                self.deb_installed_flow_box.remove_all()
                if inst_debs:
                    self.deb_installed_status_lbl.set_text(
                        f"{len(inst_debs)} .deb package{'s' if len(inst_debs) != 1 else ''} converted and tracked in Pacman"
                    )
                    for item in inst_debs:
                        card = self._create_mac_app_row(
                            item["name"],
                            item.get("desc", "Converted .deb package"),
                            "deb",
                            title_override=item.get("display_name", ""),
                            is_installed_view=True,
                            icon_override=item.get("icon", "")
                        )
                        self.deb_installed_flow_box.append(card)
                else:
                    self.deb_installed_status_lbl.set_text("No .deb packages currently installed.")

            GLib.idle_add(_ui)

        threading.Thread(target=_bg, daemon=True).start()

    def _create_deb_file_card(self, d_info: Dict[str, Any]) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        card.add_css_class("mac-app-row")
        card.set_hexpand(True)

        icon_box = Gtk.Box()
        icon_box.add_css_class("mac-squircle")
        icon_box.set_homogeneous(True)
        icon_box.set_size_request(54, 54)
        icon_box.set_halign(Gtk.Align.CENTER)
        icon_box.set_valign(Gtk.Align.CENTER)
        icon_box.set_hexpand(False)
        icon_box.set_vexpand(False)
        img = create_scaled_image(d_info.get("icon", "package-x-generic-symbolic"), size=40)
        icon_box.append(img)
        card.append(icon_box)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        vbox.set_hexpand(True)
        vbox.set_valign(Gtk.Align.CENTER)

        title_lbl = Gtk.Label(label=d_info.get("display_name") or d_info.get("name", ".deb Package"))
        title_lbl.add_css_class("mac-app-title")
        title_lbl.set_halign(Gtk.Align.START)
        title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        vbox.append(title_lbl)

        sub_txt = f"{d_info.get('deb_filename', '')} • v{d_info.get('deb_version', '')} • {d_info.get('csize_str', '')}"
        desc_lbl = Gtk.Label(label=sub_txt)
        desc_lbl.add_css_class("mac-app-desc")
        desc_lbl.set_halign(Gtk.Align.START)
        desc_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        vbox.append(desc_lbl)
        card.append(vbox)

        is_inst = d_info.get("is_installed", False)
        btn = Gtk.Button(label="REINSTALL" if is_inst else "INSPECT & GET")
        btn.add_css_class("mac-btn-installed" if is_inst else "mac-btn-get")
        btn.set_valign(Gtk.Align.CENTER)
        btn.set_size_request(112, 32)
        deb_path = d_info.get("deb_path", "")
        btn.connect("clicked", lambda b, p=deb_path: self._inspect_and_display_deb(p))
        card.append(btn)
        return card

    def _inspect_and_display_deb(self, deb_path: str):
        if not deb_path:
            return
        try:
            info = self.pm.deb_mgr.inspect_deb(deb_path)
        except Exception as e:
            self.show_toast(f"Invalid .deb file: {e}")
            return

        self._current_inspected_deb = info
        while (child := self.deb_insp_icon_box.get_first_child()):
            self.deb_insp_icon_box.remove(child)
        img = create_scaled_image(info.get("icon", "package-x-generic-symbolic"), size=48)
        self.deb_insp_icon_box.append(img)

        wayland_tag = " • ⚡ Electron App (Wayland Auto-Fix Ready)" if info.get("is_electron") else ""
        self.deb_insp_title.set_text(f"{info.get('display_name', info['name'])} ({info['deb_filename']})")
        self.deb_insp_sub.set_text(
            f"Debian v{info['deb_version']} → Arch {info['name']}-{info['version']} ({info['arch']}) • "
            f"Archive: {info['csize_str']} • Installed: {info['isize_str']}{wayland_tag}"
        )

        dep_rep = info.get("dep_report", {})
        sat = len(dep_rep.get("installed", []))
        miss_repo = dep_rep.get("missing_repo", [])
        ign = len(dep_rep.get("ignored", []))
        miss_txt = f" | Auto-installing from Arch repos: {', '.join(miss_repo[:6])}" if miss_repo else " | All Arch dependencies satisfied!"
        self.deb_insp_deps_lbl.set_text(
            f"Dependencies: {sat} already installed{miss_txt}" + (f" ({ign} Debian virtuals skipped)" if ign else "")
        )

        self.btn_deb_install_now.set_sensitive(True)
        self.btn_deb_install_now.set_label("REINSTALL .DEB" if info.get("is_installed") else "INSTALL .DEB")
        self.deb_progress_box.set_visible(False)
        self.deb_inspector_card.set_visible(True)

    def _on_pick_deb_file_click(self, btn: Gtk.Button):
        try:
            dialog = Gtk.FileDialog.new()
            dialog.set_title("Select Debian (.deb) Package to Install on Arch Linux")
            f_filter = Gtk.FileFilter()
            f_filter.set_name("Debian Packages (*.deb)")
            f_filter.add_pattern("*.deb")
            filters = Gio.ListStore.new(Gtk.FileFilter)
            filters.append(f_filter)
            dialog.set_filters(filters)
            dialog.set_default_filter(f_filter)

            dl_dir = Path.home() / "Downloads"
            if dl_dir.exists():
                dialog.set_initial_folder(Gio.File.new_for_path(str(dl_dir)))

            def _on_open_done(dlg, res):
                try:
                    gfile = dlg.open_finish(res)
                    if gfile:
                        path = gfile.get_path()
                        if path:
                            self._inspect_and_display_deb(path)
                except Exception:
                    pass

            dialog.open(self, None, _on_open_done)
        except Exception as e:
            self.show_toast(f"Could not open file chooser: {e}")

    def _on_deb_url_click(self, btn: Gtk.Button):
        dlg = Adw.AlertDialog.new(
            "Install .deb from Direct URL",
            "Paste a direct HTTP/HTTPS link to any .deb package (e.g., Google Chrome, Discord, Cursor, Steam). Aura will download, convert, resolve dependencies, and install it via Pacman."
        )
        entry = Gtk.Entry()
        entry.set_placeholder_text("https://example.com/package-amd64.deb")
        entry.set_hexpand(True)
        dlg.set_extra_child(entry)
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("download", "Download & Install")
        dlg.set_response_appearance("download", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("download")

        def _on_resp(d, resp):
            if resp == "download":
                url = entry.get_text().strip()
                if not url:
                    self.show_toast("Please enter a valid .deb URL")
                    return
                self._start_deb_url_install(url)

        dlg.connect("response", _on_resp)
        dlg.present(self)

    def _start_deb_url_install(self, url: str):
        wayland_fix = self.chk_deb_wayland.get_active() if hasattr(self, "chk_deb_wayland") else True
        self.deb_inspector_card.set_visible(True)
        self.deb_insp_title.set_text("Downloading Remote .deb Package...")
        self.deb_insp_sub.set_text(url)
        self.deb_insp_deps_lbl.set_text("Preparing download and dependency translation...")
        self.btn_deb_install_now.set_sensitive(False)
        self.btn_deb_install_now.set_label("DOWNLOADING...")
        self.deb_progress_box.set_visible(True)
        self.deb_progress_bar.set_fraction(0.05)

        def _prog(frac: float, msg: str):
            def _ui():
                self.deb_progress_bar.set_fraction(max(0.05, min(1.0, frac)))
                self.deb_progress_lbl.set_text(msg)
                self._on_progress_update(frac, msg, pkg_name=info['name'] if 'info' in locals() and isinstance(info, dict) else 'Remote .deb')
            GLib.idle_add(_ui)

        def _done(ok: bool, msg: str):
            def _ui():
                self._finish_smooth_progress(ok, "install", "deb-package", "" if ok else msg)
                self.btn_deb_install_now.set_sensitive(True)
                self.btn_deb_install_now.set_label("INSTALLED" if ok else "RETRY")
                self.deb_progress_lbl.set_text(msg)
                self.show_toast(msg)
                self._load_deb_view()
            GLib.idle_add(_ui)

        self._start_smooth_progress("install", "Remote .deb", display_name="Remote .deb", source="deb", target_view="deb")
        self.pm.deb_mgr.download_and_install_deb(url, wayland_fix=wayland_fix, progress_cb=_prog, complete_cb=_done)

    def _on_install_inspected_deb_click(self, btn: Gtk.Button):
        info = getattr(self, "_current_inspected_deb", None)
        if not info or not info.get("deb_path"):
            return
        deb_path = info["deb_path"]
        disp = info.get("display_name", info["name"])
        wayland_fix = self.chk_deb_wayland.get_active() if hasattr(self, "chk_deb_wayland") else True

        btn.set_sensitive(False)
        btn.set_label("INSTALLING...")
        self.deb_progress_box.set_visible(True)
        self.deb_progress_bar.set_fraction(0.05)
        self.deb_progress_lbl.set_text(f"Starting conversion & installation for {disp}...")

        self._start_smooth_progress("install", info["name"], display_name=disp, source="deb", target_view="deb")

        def _prog(frac: float, msg: str):
            def _ui():
                self.deb_progress_bar.set_fraction(max(0.05, min(1.0, frac)))
                self.deb_progress_lbl.set_text(msg)
                self._on_progress_update(frac, msg, pkg_name=info['name'] if 'info' in locals() and isinstance(info, dict) else 'Remote .deb')
            GLib.idle_add(_ui)

        def _done(ok: bool, msg: str):
            def _ui():
                self._finish_smooth_progress(ok, "install", info["name"], "" if ok else msg)
                btn.set_sensitive(True)
                btn.set_label("INSTALLED" if ok else "INSTALL .DEB")
                self.deb_progress_bar.set_fraction(1.0 if ok else 0.0)
                self.deb_progress_lbl.set_text(msg)
                self.show_toast(msg)
                self._load_deb_view()
                self._sync_all_cards()
            GLib.idle_add(_ui)

        self.pm.deb_mgr.install_deb(deb_path, wayland_fix=wayland_fix, progress_cb=_prog, complete_cb=_done)

    def _on_window_file_dropped(self, drop_target, value, x, y) -> bool:
        try:
            files = value.get_files() if hasattr(value, "get_files") else []
            for gfile in files:
                p = gfile.get_path()
                if p and p.lower().endswith(".deb"):
                    if "deb" in self.sidebar_buttons:
                        self.sidebar_buttons["deb"].set_active(True)
                    self.main_stack.set_visible_child_name("deb")
                    self._load_deb_view(inspect_path=p)
                    self.show_toast(f"Loaded { os.path.basename(p) } in .deb Package Bridge")
                    return True
        except Exception:
            pass
        return False

    # =========================================================================
    # Page 11: Hyprland Hub (Wayland Diagnostics, Rules & Ecosystem)
    # =========================================================================
    def _build_hyprland_page(self) -> Gtk.ScrolledWindow:
        scrolled = Gtk.ScrolledWindow()
        scrolled.add_css_class("aura-page")
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        box.set_margin_top(20)
        box.set_margin_bottom(36)
        box.set_margin_start(20)
        box.set_margin_end(20)

        # 1. Header
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        page_title = Gtk.Label(label="Hyprland Hub")
        page_title.add_css_class("mac-page-title")
        page_title.set_halign(Gtk.Align.START)
        title_box.append(page_title)

        page_subtitle = Gtk.Label(
            label="Live Wayland compositor diagnostics, window rules, Electron Wayland optimization, and essential Hyprland companion tools"
        )
        page_subtitle.add_css_class("mac-page-subtitle")
        page_subtitle.set_halign(Gtk.Align.START)
        page_subtitle.set_wrap(True)
        page_subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        page_subtitle.set_max_width_chars(52)
        title_box.append(page_subtitle)
        box.append(title_box)

        # 2. Live Hyprland Compositor Telemetry Card
        status_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        status_card.add_css_class("mac-container-status-card")
        status_card.set_valign(Gtk.Align.CENTER)
        status_card.set_hexpand(True)

        h_icon_box = Gtk.Box()
        h_icon_box.add_css_class("mac-squircle")
        h_icon_box.set_size_request(54, 54)
        h_icon_box.set_homogeneous(True)
        h_icon_box.set_halign(Gtk.Align.CENTER)
        h_icon_box.set_valign(Gtk.Align.CENTER)
        h_icon_box.set_hexpand(False)
        h_icon_box.set_vexpand(False)
        h_icon = create_scaled_image("preferences-desktop-display-symbolic", size=30)
        h_icon_box.append(h_icon)
        status_card.append(h_icon_box)

        h_info_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        h_info_col.set_hexpand(True)
        h_info_col.set_valign(Gtk.Align.CENTER)

        h_title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        h_title_row.set_hexpand(True)
        self.hypr_version_lbl = Gtk.Label(label="Hyprland Wayland Compositor")
        self.hypr_version_lbl.add_css_class("mac-spotlight-title")
        self.hypr_version_lbl.set_halign(Gtk.Align.START)
        self.hypr_version_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.hypr_version_lbl.set_max_width_chars(32)
        h_title_row.append(self.hypr_version_lbl)

        self.hypr_status_pill = Gtk.Label(label="WAYLAND")
        self.hypr_status_pill.add_css_class("mac-container-pill")
        self.hypr_status_pill.add_css_class("mac-container-pill-active")
        self.hypr_status_pill.set_valign(Gtk.Align.CENTER)
        h_title_row.append(self.hypr_status_pill)
        h_info_col.append(h_title_row)

        self.hypr_monitors_lbl = Gtk.Label(label="Inspecting Wayland outputs, portals, and companion daemons...")
        self.hypr_monitors_lbl.add_css_class("mac-spotlight-desc")
        self.hypr_monitors_lbl.set_halign(Gtk.Align.FILL)
        self.hypr_monitors_lbl.set_xalign(0.0)
        self.hypr_monitors_lbl.set_hexpand(True)
        self.hypr_monitors_lbl.set_wrap(True)
        self.hypr_monitors_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.hypr_monitors_lbl.set_max_width_chars(44)
        h_info_col.append(self.hypr_monitors_lbl)

        self.hypr_daemons_lbl = Gtk.Label(label="")
        self.hypr_daemons_lbl.add_css_class("dim-label")
        self.hypr_daemons_lbl.set_halign(Gtk.Align.FILL)
        self.hypr_daemons_lbl.set_xalign(0.0)
        self.hypr_daemons_lbl.set_hexpand(True)
        self.hypr_daemons_lbl.set_wrap(True)
        self.hypr_daemons_lbl.set_lines(2)
        self.hypr_daemons_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.hypr_daemons_lbl.set_max_width_chars(44)
        h_info_col.append(self.hypr_daemons_lbl)

        status_card.append(h_info_col)
        box.append(status_card)

        # 3. One-Click Hyprland Optimizations Section
        opt_hdr = Gtk.Label(label="One-Click Hyprland & Wayland Optimizations")
        opt_hdr.add_css_class("mac-section-title")
        opt_hdr.set_halign(Gtk.Align.START)
        box.append(opt_hdr)

        self.hypr_opt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(self.hypr_opt_box)

        # 4. Curated Hyprland Ecosystem Grid
        eco_hdr = Gtk.Label(label="Essential Hyprland Ecosystem Packages")
        eco_hdr.add_css_class("mac-section-title")
        eco_hdr.set_halign(Gtk.Align.START)
        eco_hdr.set_margin_top(8)
        box.append(eco_hdr)

        self.hypr_flow_box = self._create_symmetric_grid(min_columns=1, max_columns=4)
        hypr_cat = next((c for c in CURATED_CATEGORIES if c.get("id") == "hyprland"), None)
        if hypr_cat:
            for app_meta in hypr_cat.get("apps", []):
                card = self._create_mac_app_row(
                    app_meta["name"],
                    app_meta.get("desc", ""),
                    app_meta.get("source", "pacman"),
                    title_override=app_meta.get("title", "")
                )
                self.hypr_flow_box.append(card)
        box.append(self.hypr_flow_box)

        scrolled.set_child(box)
        return scrolled

    def _load_hyprland_view(self):
        def _bg():
            st = self.pm.hypr_mgr.get_status() if hasattr(self.pm, "hypr_mgr") else {}
            def _ui():
                ver = st.get("version", "Hyprland Compositor")
                self.hypr_version_lbl.set_text(ver if ver != "Not detected" else "Hyprland Wayland Environment")
                if st.get("hypr_active"):
                    self.hypr_status_pill.set_text("ACTIVE SESSION")
                else:
                    self.hypr_status_pill.set_text("CONFIG READY")

                mons = st.get("monitors", [])
                if mons:
                    m_strs = [f"{m['name']} ({m['width']}x{m['height']} @ {m['refresh']}Hz, {m['scale']}x scale)" for m in mons]
                    self.hypr_monitors_lbl.set_text("Displays: " + " • ".join(m_strs))
                else:
                    self.hypr_monitors_lbl.set_text(f"Wayland Socket: {st.get('wayland_display', 'wayland-1')} • Configured for floating 1040x680 glass layout")

                daemons = [
                    f"Portal: {'✓ xdg-desktop-portal-hyprland' if st.get('portal_installed') else '✕ Missing'}",
                    f"Polkit: {st.get('polkit_agent') or 'Not running'}",
                    f"Bar: {st.get('status_bar') or 'None'}",
                    f"Wallpaper: {st.get('wallpaper_daemon') or 'None'}",
                    f"Notifications: {st.get('notification_daemon') or 'None'}",
                    f"Audio: {st.get('audio_server') or 'PipeWire'}",
                ]
                self.hypr_daemons_lbl.set_text("  •  ".join(daemons))

                while (child := self.hypr_opt_box.get_first_child()):
                    self.hypr_opt_box.remove(child)

                rules_ok = st.get("rules_configured", False)
                row_rules = self._create_doctor_action_row(
                    icon_name="preferences-system-windows-symbolic",
                    title="Aura Floating Window Rules & Super+A Keybind",
                    desc="Sources hyprland-aura.conf in ~/.config/hypr/hyprland.conf so Aura & its authentication prompt float and center smoothly.",
                    metric_top="Configured" if rules_ok else "Not Applied",
                    metric_sub="hyprland.conf",
                    btn_label="Remove Rules" if rules_ok else "Apply Rules",
                    btn_sensitive=True,
                    on_click=lambda b, en=(not rules_ok): self._on_toggle_hypr_rules(en)
                )
                self.hypr_opt_box.append(row_rules)

                wl_ok = st.get("wayland_flags_configured", False)
                row_wl = self._create_doctor_action_row(
                    icon_name="applications-graphics-symbolic",
                    title="Electron & Chromium Native Wayland Ozone Optimizer",
                    desc="Configures electron-flags.conf, code-flags.conf, spotify-flags.conf & chromium-flags.conf with --ozone-platform-hint=auto for sharp HiDPI text.",
                    metric_top="Enabled" if wl_ok else "Default (XWayland)",
                    metric_sub="Ozone Wayland",
                    btn_label="Reset Flags" if wl_ok else "Enable Wayland",
                    btn_sensitive=True,
                    on_click=lambda b, en=(not wl_ok): self._on_toggle_electron_wayland(en)
                )
                self.hypr_opt_box.append(row_wl)
                self._sync_all_cards()

            GLib.idle_add(_ui)

        threading.Thread(target=_bg, daemon=True).start()

    def _on_toggle_hypr_rules(self, enable: bool):
        ok, msg = self.pm.hypr_mgr.configure_window_rules(enable=enable)
        self.show_toast(msg)
        self._load_hyprland_view()

    def _on_toggle_electron_wayland(self, enable: bool):
        ok, msg = self.pm.hypr_mgr.configure_electron_wayland_flags(enable=enable)
        self.show_toast(msg)
        self._load_hyprland_view()

    def _reload_database(self):
        self.show_toast("Reloading package database...")
        self._cached_installed_apps_flow = None
        def _bg():
            self.pm.refresh_installed()
            self.pm.load_pacman_db()
            upgrades = self.pm.check_updates()
            GLib.idle_add(lambda: (
                self._on_data_loaded(len(upgrades)),
                self.show_toast("Database refreshed!")
            ))
        threading.Thread(target=_bg, daemon=True).start()
