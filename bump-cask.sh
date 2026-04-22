#!/bin/bash
# Update Casks/feedscript.rb to the latest tagged release. Run after a
# new v* tag has been pushed and GitHub Actions has attached
# Feedscript-macOS.zip to the release.
#
# Usage:  ./bump-cask.sh 0.1.2

set -e
cd "$(dirname "$0")"

VERSION="$1"
if [ -z "$VERSION" ]; then
    echo "Usage: $0 <version>   e.g. $0 0.1.2"
    exit 1
fi

URL="https://github.com/smhammad/feedscript/releases/download/v${VERSION}/Feedscript-macOS.zip"

echo "→ Downloading $URL"
TMP=$(mktemp)
curl -sfL "$URL" -o "$TMP" || {
    echo "Download failed — is the release published and the zip attached?"
    exit 1
}

SHA=$(shasum -a 256 "$TMP" | awk '{print $1}')
rm "$TMP"
echo "→ SHA256: $SHA"

python3 <<PY
import re, pathlib
p = pathlib.Path("Casks/feedscript.rb")
src = p.read_text()
src = re.sub(r'version "[^"]+"', f'version "{"$VERSION"}"', src)
src = re.sub(r'sha256 "[^"]+"', f'sha256 "{"$SHA"}"', src)
p.write_text(src)
print(f"→ Updated {p}")
PY

echo "Done. Review with: git diff Casks/feedscript.rb"
