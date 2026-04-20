#!/bin/bash
# Sync source code into Feedscript.app/Contents/Resources/ so the bundle is
# portable (works when dragged to /Applications, Desktop, anywhere).
# Run this whenever you edit launcher.py, app.py, templates/, or static/.

set -e
cd "$(dirname "$0")"

RES="Feedscript.app/Contents/Resources"

if [ ! -d "$RES" ]; then
    echo "error: $RES does not exist — is the .app bundle intact?"
    exit 1
fi

# Copy top-level code files
cp launcher.py app.py requirements.txt "$RES/"

# Mirror templates/ and static/ (delete stale files on the target side)
rsync -a --delete templates/ "$RES/templates/"
rsync -a --delete static/ "$RES/static/"

echo "Bundled code into $RES"
