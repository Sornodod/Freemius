#!/usr/bin/env bash
# Собирает Freemius.AppImage.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
cd "$ROOT"

APP_NAME="freemius"
APP_VERSION="$(grep '^Version:' "$SCRIPT_DIR/deb-control" | awk '{print $2}')"
ARCH="$(uname -m)"
[ "$ARCH" = "x86_64" ] && ARCH_APPIMAGE="x86_64" || ARCH_APPIMAGE="$ARCH"

APPDIR="$ROOT/dist/${APP_NAME}.AppDir"
OUTPUT="$ROOT/dist/${APP_NAME}-${APP_VERSION}-${ARCH_APPIMAGE}.AppImage"
TOOL="$ROOT/build/appimagetool-${ARCH_APPIMAGE}.AppImage"

echo "==> [1/4] PyInstaller"
if [ ! -x "dist/${APP_NAME}/${APP_NAME}" ] || [ "${1:-}" = "--rebuild" ]; then
    pyinstaller --clean --noconfirm scripts/linux.spec
else
    echo "  dist/${APP_NAME}/ уже собран (используй --rebuild для принудительной пересборки)"
fi

echo "==> [2/4] AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -a "dist/${APP_NAME}/." "$APPDIR/usr/bin/"

install -m 0755 "$SCRIPT_DIR/AppRun"             "$APPDIR/AppRun"
install -m 0644 "$SCRIPT_DIR/freemius.desktop"   "$APPDIR/freemius.desktop"
install -m 0644 "$SCRIPT_DIR/freemius.png"       "$APPDIR/freemius.png"

echo "==> [3/4] appimagetool"
if [ ! -x "$TOOL" ]; then
    URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH_APPIMAGE}.AppImage"
    echo "  качаю $URL"
    wget -q -O "$TOOL" "$URL"
    chmod +x "$TOOL"
fi

echo "==> [4/4] Собираю AppImage v${APP_VERSION}"
ARCH="$ARCH_APPIMAGE" "$TOOL" "$APPDIR" "$OUTPUT"

echo ""
echo "Готово: $OUTPUT"
ls -lh "$OUTPUT"
