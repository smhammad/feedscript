#!/bin/bash
# Feedscript — one-line macOS installer.
#
# Downloads the latest Feedscript-macOS.zip from the GitHub release,
# removes the macOS "downloaded from the internet" quarantine flag so
# Gatekeeper doesn't block it, and installs the app into /Applications.
#
# Usage (run in Terminal):
#   curl -fsSL https://raw.githubusercontent.com/smhammad/feedscript/main/install.sh | bash

set -e

LATEST_URL="https://github.com/smhammad/feedscript/releases/latest/download/Feedscript-macOS.zip"
DEST="/Applications"

if [[ "$(uname)" != "Darwin" ]]; then
    echo "This installer is for macOS. See the README for other platforms:"
    echo "  https://github.com/smhammad/feedscript"
    exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "→ Downloading Feedscript-macOS.zip…"
curl -fsSL "$LATEST_URL" -o "$TMP/app.zip"

echo "→ Unpacking…"
(cd "$TMP" && unzip -q app.zip)

if [ ! -d "$TMP/Feedscript.app" ]; then
    echo "error: Feedscript.app not found in the zip — release asset may be malformed."
    exit 1
fi

echo "→ Removing macOS quarantine flag…"
xattr -dr com.apple.quarantine "$TMP/Feedscript.app" 2>/dev/null || true

if [ -d "$DEST/Feedscript.app" ]; then
    echo "→ Replacing existing $DEST/Feedscript.app"
    rm -rf "$DEST/Feedscript.app"
fi

echo "→ Moving into $DEST…"
mv "$TMP/Feedscript.app" "$DEST/"

echo ""
echo "✓ Feedscript installed to $DEST/Feedscript.app"
echo "   Launch it from Spotlight (⌘Space → Feedscript) or double-click it in Applications."
