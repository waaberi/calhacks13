#!/usr/bin/env bash
# Downloads Vosk 0.3.38's native libraries (from its NuGet package, checked by SHA-256) into the VoiceCore package's
# Plugins/ folder, with Unity import settings: Windows x64 for the build and the Windows editor, macOS (universal)
# and Linux x64 for those editors. About 85 MB unpacked, so they are never committed (voice/VoiceCore/.gitignore).
#
#   voice/fetch-vosk.sh
#
# Needs curl, and unzip or python3. Works in Git Bash on Windows. Close Unity first if it already loaded an older copy.
set -euo pipefail

VERSION=0.3.38
URL="https://www.nuget.org/api/v2/package/Vosk/$VERSION"
SHA256=d01f96e306f3b6abd68bd0eef6d8aacb15c870b7873a74074c775b13dd50397f # 24 MB nupkg, checked 2026-10-23

dest="$(cd "$(dirname "$0")" && pwd)/VoiceCore/Plugins"
if [ -f "$dest/Windows/libvosk.dll" ] && [ -f "$dest/macOS/libvosk.dylib" ] && [ -f "$dest/Linux/libvosk.so" ]; then
  echo "Vosk $VERSION is already in $dest"
  exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fL --progress-bar --retry 3 -o "$tmp/vosk.nupkg" "$URL"

if command -v sha256sum >/dev/null; then
  actual="$(sha256sum "$tmp/vosk.nupkg" | cut -d' ' -f1)"
else
  actual="$(shasum -a 256 "$tmp/vosk.nupkg" | cut -d' ' -f1)"
fi
if [ "$actual" != "$SHA256" ]; then
  echo "Checksum mismatch for Vosk $VERSION: expected $SHA256, got $actual" >&2
  exit 1
fi

if command -v unzip >/dev/null; then
  unzip -q "$tmp/vosk.nupkg" 'build/lib/*' -d "$tmp/unpacked"
else
  python3 -m zipfile -e "$tmp/vosk.nupkg" "$tmp/unpacked"
fi
lib="$tmp/unpacked/build/lib"
rm -rf "$dest"
mkdir -p "$dest/Windows" "$dest/macOS" "$dest/Linux"
cp "$lib"/win-x64/*.dll "$dest/Windows/"
cp "$lib/osx-universal/libvosk.dylib" "$dest/macOS/"
cp "$lib/linux-x64/libvosk.so" "$dest/Linux/"

guid() { # a fixed GUID per file, so every machine imports it the same way
  if command -v md5sum >/dev/null; then printf '%s' "voicecore/$1" | md5sum | cut -c1-32
  else printf '%s' "voicecore/$1" | md5 -q; fi
}

# meta FILE OS CPU: the plugin loads in that OS's editor and in that platform's player only.
meta() {
  local file="$1" os="$2" cpu="$3" win=0 mac=0 linux=0
  case "$os" in Windows) win=1 ;; OSX) mac=1 ;; Linux) linux=1 ;; esac
  cat > "$dest/$file.meta" <<EOF
fileFormatVersion: 2
guid: $(guid "$file")
PluginImporter:
  externalObjects: {}
  serializedVersion: 2
  iconMap: {}
  executionOrder: {}
  defineConstraints: []
  isPreloaded: 0
  isOverridable: 1
  isExplicitlyReferenced: 0
  validateReferences: 1
  platformData:
  - first:
      : Any
    second:
      enabled: 0
      settings:
        Exclude Editor: 0
        Exclude Linux64: $((1 - linux))
        Exclude OSXUniversal: $((1 - mac))
        Exclude Win: 1
        Exclude Win64: $((1 - win))
  - first:
      Any:
    second:
      enabled: 0
      settings: {}
  - first:
      Editor: Editor
    second:
      enabled: 1
      settings:
        CPU: $cpu
        DefaultValueInitialized: true
        OS: $os
  - first:
      Standalone: Linux64
    second:
      enabled: $linux
      settings:
        CPU: $([ $linux = 1 ] && echo x86_64 || echo None)
  - first:
      Standalone: OSXUniversal
    second:
      enabled: $mac
      settings:
        CPU: $([ $mac = 1 ] && echo AnyCPU || echo None)
  - first:
      Standalone: Win
    second:
      enabled: 0
      settings:
        CPU: None
  - first:
      Standalone: Win64
    second:
      enabled: $win
      settings:
        CPU: $([ $win = 1 ] && echo x86_64 || echo None)
  userData:
  assetBundleName:
  assetBundleVariant:
EOF
}

for dll in "$dest"/Windows/*.dll; do
  meta "Windows/$(basename "$dll")" Windows x86_64 # libvosk.dll and the MinGW runtime it loads from the same folder
done
meta macOS/libvosk.dylib OSX AnyCPU # x86_64 and arm64
meta Linux/libvosk.so Linux x86_64
echo "Vosk $VERSION ready in $dest"
