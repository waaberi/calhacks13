# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = ["piper-tts==1.3.0", "soundfile==0.13.1"]
# ///
"""Speaks every VoiceCore prompt into a clip the Unity app plays: offline, with a voice we may redistribute.

    uv run voice/make-prompts.py              # all prompts
    uv run voice/make-prompts.py ask_axis     # only these
    uv run voice/make-prompts.py --say OUT.ogg "move it up five millimeters"   # any text, for test audio

Reads the prompts from voice/VoiceCore/Runtime/Prompt.cs and writes
voice/VoiceCore/Prompts/Resources/VoiceCorePrompts/<id>.ogg (Ogg Vorbis, mono, 22.05 kHz) with a .meta that keeps
the same GUID on every machine. The prompt's text goes into the clip's COMMENT tag, and tests/voice checks that it
still matches Prompt.cs, so a changed prompt fails the tests until its clip is made again.

Voice: Piper's en_US-ljspeech-high (MIT, trained on the public-domain LJ Speech dataset), pinned below by
revision and SHA-256 and cached in voice/models/piper/.
"""

import argparse
import hashlib
import re
import sys
import urllib.request
from pathlib import Path

import numpy as np
import soundfile
from piper import PiperVoice, SynthesisConfig

VOICE = "en_US-ljspeech-high"
REVISION = "5041a7a49ae5b3a0f30e6837769eb03fdbb231bd"  # rhasspy/piper-voices on Hugging Face, 2026-10-20
FILES = {
    f"{VOICE}.onnx": "5d4f08ba6a2a48c44592eed3ce56bf85e9de3dd4e20df90541ae68a8310c029a",
    f"{VOICE}.onnx.json": "7e1f4634af596d83cca997fb7a931ba80b70f8a316a2655ee69c55365e0ace14",
}
URL = f"https://huggingface.co/rhasspy/piper-voices/resolve/{REVISION}/en/en_US/ljspeech/high/"

VOICE_DIR = Path(__file__).resolve().parent
PROMPT_CS = VOICE_DIR / "VoiceCore/Runtime/Prompt.cs"
CLIPS = VOICE_DIR / "VoiceCore/Prompts/Resources/VoiceCorePrompts"
QUALITY = 0.4  # Vorbis quality from 0 to 1: about 45 kbit/s at 22.05 kHz mono
PAD = 0.08  # seconds of silence kept around the speech

META = """fileFormatVersion: 2
guid: {guid}
AudioImporter:
  externalObjects: {{}}
  serializedVersion: 6
  defaultSettings:
    loadType: 0
    sampleRateSetting: 0
    sampleRateOverride: 44100
    compressionFormat: 1
    quality: 0.7
    conversionMode: 0
  platformSettingOverrides: {{}}
  forceToMono: 1
  normalize: 0
  preloadAudioData: 1
  loadInBackground: 0
  ambisonic: 0
  3D: 0
  userData: 
  assetBundleName: 
  assetBundleVariant: 
"""


def prompts():
    text = PROMPT_CS.read_text(encoding="utf-8")
    found = re.findall(r'new Prompt\("([a-z_]+)", "((?:[^"\\]|\\.)*)"\)', text)
    if not found:
        sys.exit(f"No prompts found in {PROMPT_CS}")
    return [(pid, re.sub(r"\\(.)", r"\1", line)) for pid, line in found]


def load_voice():
    cache = VOICE_DIR / "models/piper"
    cache.mkdir(parents=True, exist_ok=True)
    for name, sha in FILES.items():
        path = cache / name
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            print(f"Downloading {name}")
            data = urllib.request.urlopen(URL + name).read()
            if hashlib.sha256(data).hexdigest() != sha:
                sys.exit(f"Checksum mismatch for {name}")
            path.write_bytes(data)
    voice = PiperVoice.load(str(cache / f"{VOICE}.onnx"))
    voice.config.espeak_voice = "en-us"  # the voice's config says "en", which speaks British "zed" and "cahn't"
    return voice


def speak(voice, text):
    # No generator noise, so the same text always gives the same audio.
    config = SynthesisConfig(noise_scale=0.0, noise_w_scale=0.0)
    chunks = list(voice.synthesize(text, syn_config=config))
    rate = chunks[0].sample_rate
    audio = np.concatenate([c.audio_float_array for c in chunks])
    loud = np.flatnonzero(np.abs(audio) > 0.02)
    pad = int(PAD * rate)
    audio = audio[max(0, loud[0] - pad) : loud[-1] + pad] if loud.size else audio
    return audio, rate


def write(path, audio, rate, comment):
    with soundfile.SoundFile(path, "w", rate, 1, format="OGG", subtype="VORBIS", compression_level=1 - QUALITY) as f:
        f.comment = comment
        f.artist = f"Piper {VOICE}"
        f.write(audio)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ids", nargs="*", help="prompt IDs (default: all)")
    parser.add_argument("--say", nargs=2, metavar=("OUT", "TEXT"), help="speak TEXT into the Ogg file OUT")
    args = parser.parse_args()
    voice = load_voice()

    if args.say:
        out, text = args.say
        write(out, *speak(voice, text), comment=text)
        return

    all_prompts = prompts()
    unknown = set(args.ids) - {pid for pid, _ in all_prompts}
    if unknown:
        sys.exit(f"Unknown prompt IDs: {', '.join(sorted(unknown))}")
    CLIPS.mkdir(parents=True, exist_ok=True)
    total = 0.0
    for pid, line in all_prompts:
        if args.ids and pid not in args.ids:
            continue
        audio, rate = speak(voice, line)
        clip = CLIPS / f"{pid}.ogg"
        write(clip, audio, rate, comment=line)
        meta = clip.with_name(clip.name + ".meta")
        if not meta.exists():
            guid = hashlib.md5(f"voicecore/prompt/{pid}".encode()).hexdigest()
            meta.write_text(META.format(guid=guid), encoding="utf-8")
        total += len(audio) / rate
        print(f"{pid:20} {len(audio) / rate:4.1f} s  {clip.stat().st_size / 1024:5.1f} KB  {line}")
    print(f"{total:.1f} s of prompts in {CLIPS}")


if __name__ == "__main__":
    main()
