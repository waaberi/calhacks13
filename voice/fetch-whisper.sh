#!/usr/bin/env bash
# Downloads whisper.cpp's whisper-server for Windows x64 (the prebuilt release b5454, checked by SHA-256) and the
# ggml tiny.en and base.en models (a pinned revision, checked by SHA-256) into DEST/whisper/, the folder the app
# starts whisper-server from (VoiceRecognizers.Create). About 240 MB, so it is never committed.
#
#   voice/fetch-whisper.sh app/Assets/StreamingAssets                # for the Unity app and its Windows build
#   voice/fetch-whisper.sh                                           # into voice/models/whisper/, for the tests
#   voice/fetch-whisper.sh --models-only [DEST]                      # just the models (Linux, macOS)
#
# The Windows binaries need the Microsoft Visual C++ 2015-2022 Redistributable (x64) on the PC that runs them:
# https://aka.ms/vs/17/release/vc_redist.x64.exe (whisper-server.exe imports MSVCP140, VCRUNTIME140, VCRUNTIME140_1).
# There is no prebuilt server for Linux or macOS: build one as voice/README.md describes.
# Needs curl, and unzip, PowerShell or python3. Works in Git Bash on Windows.
set -euo pipefail

RELEASE=b5454 # 2026-10-06; whisper.cpp's v1.9.5 tag has no Windows assets
ZIP_URL="https://github.com/ggml-org/whisper.cpp/releases/download/$RELEASE/whisper-bin-x64.zip"
ZIP_SHA256=6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb # 9 MB zip, checked 2026-10-24
MODEL_REVISION=5359861c739e955e79d9a303bcbc70fb988958b1                   # huggingface.co/ggerganov/whisper.cpp
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/$MODEL_REVISION"
MODELS="ggml-tiny.en.bin:921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f
ggml-base.en.bin:a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002" # 78 MB and 148 MB

binaries=1
if [ "${1:-}" = "--models-only" ]; then
  binaries=0
  shift
fi
dest="${1:-$(dirname "$0")/models}/whisper"
mkdir -p "$dest"

sha256() {
  if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

# fetch URL SHA256 OUT: downloads to a temporary file, checks it, then moves it into place.
fetch() {
  local url="$1" expected="$2" out="$3" actual
  curl -fL --progress-bar --retry 3 -o "$out.part" "$url"
  actual="$(sha256 "$out.part")"
  if [ "$actual" != "$expected" ]; then
    rm -f "$out.part"
    echo "Checksum mismatch for $url: expected $expected, got $actual" >&2
    exit 1
  fi
  mv "$out.part" "$out"
}

# unpack ZIP DIR: unzip, else PowerShell (Git Bash and MSYS2 may lack unzip), else Python.
unpack() {
  if command -v unzip >/dev/null; then
    unzip -q "$1" -d "$2"
  elif command -v powershell.exe >/dev/null; then
    powershell.exe -NoProfile -Command "Expand-Archive -Force -LiteralPath '$(cygpath -w "$1")' -DestinationPath '$(cygpath -w "$2")'"
  else
    python3 -m zipfile -e "$1" "$2"
  fi
}

if [ "$binaries" = 1 ]; then
  if [ -f "$dest/.whisper-$RELEASE" ]; then # written last, so an interrupted run starts over
    echo "whisper-server $RELEASE is already in $dest"
  else
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    fetch "$ZIP_URL" "$ZIP_SHA256" "$tmp/whisper-bin-x64.zip"
    unpack "$tmp/whisper-bin-x64.zip" "$tmp/unpacked"
    # Only the server and the libraries it loads; ggml picks the ggml-cpu-*.dll that suits the CPU at run time.
    cp "$tmp/unpacked/Release/whisper-server.exe" "$tmp/unpacked/Release/whisper.dll" "$tmp/unpacked/Release/ggml.dll" \
      "$tmp/unpacked/Release/ggml-base.dll" "$tmp/unpacked/Release"/ggml-cpu-*.dll "$dest/"
    echo "$ZIP_SHA256" > "$dest/.whisper-$RELEASE"
    echo "whisper-server $RELEASE ready in $dest"
  fi
fi

echo "$MODELS" | while IFS=: read -r name expected; do
  if [ -f "$dest/$name" ] && [ "$(sha256 "$dest/$name")" = "$expected" ]; then
    echo "$dest/$name already exists"
  else
    fetch "$MODEL_URL/$name" "$expected" "$dest/$name"
    echo "Model ready in $dest/$name"
  fi
done
