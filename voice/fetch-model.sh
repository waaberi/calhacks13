#!/usr/bin/env bash
# Downloads the pinned small English Vosk model and checks its SHA-256. The model is never committed.
#
#   voice/fetch-model.sh                               # into voice/models/
#   voice/fetch-model.sh app/Assets/StreamingAssets    # for the Unity app
#
# Needs curl, and unzip or python3. Works in Git Bash on Windows.
set -euo pipefail

NAME=vosk-model-small-en-us-0.15
URL="https://alphacephei.com/vosk/models/$NAME.zip"
SHA256=30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498 # 41 MB zip, checked 2026-10-23

dest="${1:-$(dirname "$0")/models}"
if [ -f "$dest/$NAME/am/final.mdl" ]; then
  echo "$dest/$NAME already exists"
  exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fL --progress-bar --retry 3 -o "$tmp/$NAME.zip" "$URL"

if command -v sha256sum >/dev/null; then
  actual="$(sha256sum "$tmp/$NAME.zip" | cut -d' ' -f1)"
else
  actual="$(shasum -a 256 "$tmp/$NAME.zip" | cut -d' ' -f1)"
fi
if [ "$actual" != "$SHA256" ]; then
  echo "Checksum mismatch for $NAME.zip: expected $SHA256, got $actual" >&2
  exit 1
fi

if command -v unzip >/dev/null; then
  unzip -q "$tmp/$NAME.zip" -d "$tmp/unpacked"
else
  python3 -m zipfile -e "$tmp/$NAME.zip" "$tmp/unpacked"
fi
mkdir -p "$dest"
mv "$tmp/unpacked/$NAME" "$dest/$NAME"
echo "Model ready in $dest/$NAME"
