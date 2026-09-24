#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APP_NAME="freemius"
APP_VERSION="$(grep '^Version:' scripts/deb-control | awk '{print $2}')"
ARCH="amd64"

STAGE="$ROOT/build/deb-stage"
DEB_DIR="$STAGE/${APP_NAME}_${APP_VERSION}_${ARCH}"
DEB_FILE="$ROOT/dist/${APP_NAME}_${APP_VERSION}_${ARCH}.deb"

# 0) проверить, что PyInstaller уже собрал dist/freemius/
if [ ! -x "dist/freemius/freemius" ]; then
    echo "==> dist/freemius/ пусто, собираю PyInstaller"
    pyinstaller --clean --noconfirm scripts/linux.spec
fi

echo "==> Готовлю структуру пакета"
rm -rf "$STAGE"
mkdir -p "$DEB_DIR/DEBIAN"
mkdir -p "$DEB_DIR/usr/bin"
mkdir -p "$DEB_DIR/usr/lib/${APP_NAME}"
mkdir -p "$DEB_DIR/usr/share/applications"
mkdir -p "$DEB_DIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$DEB_DIR/usr/share/icons/hicolor/512x512/apps"

# control
cp scripts/deb-control "$DEB_DIR/DEBIAN/control"

# launcher
cp scripts/deb-freemius "$DEB_DIR/usr/bin/freemius"
chmod 0755 "$DEB_DIR/usr/bin/freemius"

# бинарь
cp -a dist/freemius/. "$DEB_DIR/usr/lib/${APP_NAME}/"
chmod 0755 "$DEB_DIR/usr/lib/${APP_NAME}/freemius"

# desktop
cp scripts/freemius.desktop "$DEB_DIR/usr/share/applications/freemius.desktop"

# иконки
cp scripts/freemius.png "$DEB_DIR/usr/share/icons/hicolor/256x256/apps/freemius.png"
# если есть 512×512 — положи её, иначе копируем 256-ю
if [ -f scripts/freemius-512.png ]; then
    cp scripts/freemius-512.png "$DEB_DIR/usr/share/icons/hicolor/512x512/apps/freemius.png"
else
    cp scripts/freemius.png "$DEB_DIR/usr/share/icons/hicolor/512x512/apps/freemius.png"
fi

echo "==> Права root:root"

echo "==> Собираю .deb"
dpkg-deb --root-owner-group --build "$DEB_DIR" "$DEB_FILE"

echo ""
echo "Готово: $DEB_FILE"
ls -lh "$DEB_FILE"
