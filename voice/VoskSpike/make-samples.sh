#!/usr/bin/env bash
# Generates spike samples with local text-to-speech (espeak-ng, flite and Piper through voice/make-prompts.py) into
# voice/VoskSpike/samples/, as 48 kHz 16-bit WAV like a Windows microphone, so the spike also exercises resampling.
# TTS is cleaner than a headset microphone, so treat the results as an upper bound.
set -euo pipefail

here="$(dirname "$0")"
out="$here/samples"
mkdir -p "$out"

commands=(
  "rotate this object ninety degrees" "z" "move the cube ten centimeters along x" "move it up five millimeters"
  "scale it by one point five" "scale this to fifty percent" "rotate the sphere forty five degrees around y"
  "rotate it one hundred and eighty degrees around z" "move it minus two centimeters along y" "select the cylinder"
  "add a sphere" "add a cube" "delete this" "undo" "redo" "cancel" "apply"
)
chatter=("what is the weather like today" "could you pass me the coffee please" "good morning everyone")

say() { # voice text wav
  local raw="$out/raw.wav"
  case "$1" in
    espeak-*) espeak-ng -v "${1#espeak-}" -w "$raw" "$2" ;;
    flite-*) flite -voice "${1#flite-}" -t "$2" -o "$raw" ;;
    piper) raw="$out/raw.ogg"; uv run -q "$here/../make-prompts.py" --say "$raw" "$2" ;;
  esac
  ffmpeg -loglevel error -y -i "$raw" -ar 48000 -ac 1 -sample_fmt s16 "$3"
  rm -f "$raw"
}

for voice in espeak-en-us espeak-en-gb flite-slt flite-rms piper; do
  for text in "${commands[@]}"; do
    name="$voice-${text// /-}"
    say "$voice" "$text" "$out/$name.wav"
    echo "$text" > "$out/$name.txt"
  done
  for text in "${chatter[@]}"; do
    name="$voice-chatter-${text// /-}"
    say "$voice" "$text" "$out/$name.wav"
    echo "-" > "$out/$name.txt"
  done
done
echo "$(ls "$out"/*.wav | wc -l) samples in $out"
