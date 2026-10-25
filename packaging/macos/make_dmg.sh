#!/usr/bin/env bash
# Build a macOS .dmg from the PyInstaller bundle produced by scripts/build.py.
# Usage: bash packaging/macos/make_dmg.sh <version>
set -euo pipefail

VERSION="${1:?usage: make_dmg.sh <version>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP="$ROOT/dist/AI Desktop Assistant.app"
DMG="$ROOT/dist/AI-Desktop-Assistant-${VERSION}-macos.dmg"

if [[ ! -d "$APP" ]]; then
  echo "error: $APP not found; run 'uv run python scripts/build.py' first" >&2
  exit 1
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
rm -f "$DMG"

create-dmg \
  --volname "AI Desktop Assistant" \
  --window-pos 200 120 \
  --window-size 800 450 \
  --icon-size 100 \
  --icon "AI Desktop Assistant.app" 200 190 \
  --hide-extension "AI Desktop Assistant.app" \
  --app-drop-link 600 190 \
  "$DMG" "$STAGE"

echo "built $DMG"
