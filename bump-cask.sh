#!/bin/bash
# Update Casks/feedscript.rb to the latest tagged release. Run after a
# new v* tag has been pushed and GitHub Actions has attached
# Feedscript-macOS.zip to the release.
#
# NOTE ON ORDER: the version in Info.plist has to be bumped and committed
# BEFORE the tag is created, because the release zips the .app as it is at
# that tag. This script re-writes the plist too, but by the time it can run
# (the zip must exist to be checksummed) that release has already been built
# — so it only keeps the working tree honest for next time.
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

# Keep the bundle's own version in step, or brew audit flags the mismatch.
q = pathlib.Path("Feedscript.app/Contents/Info.plist")
plist = q.read_text()
for key in ("CFBundleShortVersionString", "CFBundleVersion"):
    plist = re.sub(
        r'(<key>' + key + r'</key>\s*<string>)[^<]*(</string>)',
        lambda m: m.group(1) + "$VERSION" + m.group(2),
        plist,
    )
q.write_text(plist)
print(f"→ Updated {q}")
PY

echo "Done. Review with: git diff Casks/feedscript.rb"
