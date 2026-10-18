# Maintainer: ArkST Team
pkgname=arkst
pkgver=3.1.0
pkgrel=1
pkgdesc="ArkST — Universal Graphical Package Manager for Arch Linux (Pacman, AUR, Flathub, Snap, Docker & .deb)"
arch=('any')
url="https://github.com/Desplicableme/arkst"
license=('GPL-3.0-or-later')
depends=(
    'python'
    'python-gobject'
    'gtk4'
    'libadwaita'
    'librsvg'
    'pacman-contrib'
    'flatpak'
    'hicolor-icon-theme'
)
optdepends=(
    'paru: AUR package support (recommended)'
    'yay: Alternative AUR helper'
    'snapd: Snap Store package support'
    'docker: Docker Hub and container app support'
)
replaces=('aura-store' 'aura-store-git' 'ark-store')
conflicts=('aura-store' 'aura-store-git' 'ark-store')
source=("$pkgname-$pkgver.tar.gz")
sha256sums=('SKIP')

package() {
    cd "$srcdir/$pkgname-$pkgver"

    install -dm755 "$pkgdir/usr/lib/arkst/data/icons"
    install -Dm755 arkst.py            "$pkgdir/usr/lib/arkst/arkst.py"
    install -Dm644 arkst_ui.py         "$pkgdir/usr/lib/arkst/arkst_ui.py"
    install -Dm644 arkst_backend.py    "$pkgdir/usr/lib/arkst/arkst_backend.py"
    install -Dm644 arkst_gtk_shim.py   "$pkgdir/usr/lib/arkst/arkst_gtk_shim.py"
    install -Dm755 arkst-askpass       "$pkgdir/usr/lib/arkst/arkst-askpass"
    install -Dm644 arkst-icon.png      "$pkgdir/usr/lib/arkst/arkst-icon.png"
    install -Dm644 arkst-icon.svg      "$pkgdir/usr/lib/arkst/arkst-icon.svg"

    for f in data/icons/*; do
        install -Dm644 "$f" "$pkgdir/usr/lib/arkst/data/icons/$(basename "$f")"
    done

    install -dm755 "$pkgdir/usr/bin"
    printf '#!/usr/bin/env bash\nexport PYTHONPATH="/usr/lib/arkst:${PYTHONPATH:-}"\nexec python3 /usr/lib/arkst/arkst.py "$@"\n' > "$pkgdir/usr/bin/arkst"
    chmod 755 "$pkgdir/usr/bin/arkst"

    install -Dm644 data/io.github.arkst.desktop \
        "$pkgdir/usr/share/applications/io.github.arkst.desktop"
    install -Dm644 data/io.github.arkst.metainfo.xml \
        "$pkgdir/usr/share/metainfo/io.github.arkst.metainfo.xml"
    install -Dm644 arkst-icon.png "$pkgdir/usr/share/icons/hicolor/512x512/apps/io.github.arkst.png"
    install -Dm644 data/icons/arkst-256.png "$pkgdir/usr/share/icons/hicolor/256x256/apps/io.github.arkst.png"
    install -Dm644 data/icons/arkst-128.png "$pkgdir/usr/share/icons/hicolor/128x128/apps/io.github.arkst.png"
    install -Dm644 data/icons/arkst-64.png  "$pkgdir/usr/share/icons/hicolor/64x64/apps/io.github.arkst.png"
    install -Dm644 data/icons/arkst-48.png  "$pkgdir/usr/share/icons/hicolor/48x48/apps/io.github.arkst.png"
    install -Dm644 arkst-icon.svg "$pkgdir/usr/share/icons/hicolor/scalable/apps/io.github.arkst.svg"
    install -Dm644 arkst-icon.png "$pkgdir/usr/share/pixmaps/io.github.arkst.png"
}
