# Maintainer: Arka <https://github.com/Desplicableme/aura-store>
pkgname=aura-appstore-git
pkgver=2.0.0.r135.g725e105
pkgrel=1
pkgdesc="Mac-inspired modern App Store tailored exclusively for Hyprland on Arch Linux with native .deb bridge"
arch=('any')
url="https://github.com/Desplicableme/aura-store"
license=('GPL-3.0-or-later')
depends=(
    'python'
    'python-gobject'
    'gtk4'
    'libadwaita'
    'pacman-contrib'
    'libarchive'
    'zstd'
)
optdepends=(
    'paru: AUR package helper integration'
    'yay: Alternative AUR package helper'
    'debtap: Optional secondary .deb package conversion backend'
    'docker: Isolated OCI sandbox applications'
)
provides=('aura-appstore')
conflicts=('aura-appstore')
source=('git+https://github.com/Desplicableme/aura-store.git')
sha256sums=('SKIP')

pkgver() {
    cd "${srcdir}/aura-store" 2>/dev/null || cd "${startdir:-.}"
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        git describe --long --tags 2>/dev/null | sed 's/^[vV]//;s/\([^-]*-g\)/r\1/;s/-/./g' || echo "2.0.0.r$(git rev-list --count HEAD).g$(git rev-parse --short=7 HEAD)"
    else
        echo "2.0.0"
    fi
}

package() {
    local src_dir="${srcdir}/aura-store"
    if [ ! -d "${src_dir}" ]; then
        src_dir="${startdir:-.}"
    fi

    install -dm755 "${pkgdir}/usr/lib/aura"
    install -dm755 "${pkgdir}/usr/bin"
    install -dm755 "${pkgdir}/usr/share/applications"
    install -dm755 "${pkgdir}/usr/share/icons/hicolor/scalable/apps"
    install -dm755 "${pkgdir}/usr/share/metainfo"
    install -dm755 "${pkgdir}/usr/share/aura"

    install -m755 "${src_dir}/aura.py" "${pkgdir}/usr/lib/aura/aura.py"
    install -m644 "${src_dir}/aura_backend.py" "${pkgdir}/usr/lib/aura/aura_backend.py"
    install -m644 "${src_dir}/aura_ui.py" "${pkgdir}/usr/lib/aura/aura_ui.py"
    install -m755 "${src_dir}/aura-askpass" "${pkgdir}/usr/lib/aura/aura-askpass"

    # Launcher wrapper
    ln -sf "/usr/lib/aura/aura.py" "${pkgdir}/usr/bin/aura"

    # Desktop, Metadata & Hyprland config
    install -m644 "${src_dir}/data/io.github.aura.desktop" "${pkgdir}/usr/share/applications/io.github.aura.desktop"
    if [ -f "${src_dir}/data/io.github.aura.metainfo.xml" ]; then
        install -m644 "${src_dir}/data/io.github.aura.metainfo.xml" "${pkgdir}/usr/share/metainfo/io.github.aura.metainfo.xml"
    fi

    for icon in "${src_dir}"/data/icons/*.svg; do
        if [ -f "$icon" ]; then
            install -m644 "$icon" "${pkgdir}/usr/share/icons/hicolor/scalable/apps/"
        fi
    done

    if [ -f "${src_dir}/data/hyprland-aura.conf" ]; then
        install -m644 "${src_dir}/data/hyprland-aura.conf" "${pkgdir}/usr/share/aura/hyprland-aura.conf"
    fi
}
