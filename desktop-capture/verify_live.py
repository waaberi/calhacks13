"""Live gate: move Blender's viewport while sampling real pixels and the Player log.

A static image/HTTP heartbeat cannot pass this gate. No desktop input or native
model edit is performed. Requires Pillow and the selected-window helper.
"""

import argparse
import io
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageChops, ImageStat, JpegImagePlugin


def verify(seconds, player_log):
    start = time.monotonic()
    offset = player_log.stat().st_size
    previous = None
    changes = 0
    samples = 0
    unavailable = 0
    ages = []
    sizes = set()
    quality_ok = True
    reference = io.BytesIO()
    Image.new("RGB", (8, 8)).save(reference, format="JPEG", quality=95, subsampling=0)
    reference.seek(0)
    quantization = Image.open(reference).quantization
    while time.monotonic() - start < seconds:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8766/frame", timeout=2) as response:
                captured = int(response.headers["X-Captured-At"])
                image = Image.open(io.BytesIO(response.read()))
                image.load()
                ages.append(int(time.time() * 1000) - captured)
                sizes.add(image.size)
                quality_ok &= JpegImagePlugin.get_sampling(image) == 0 and image.quantization == quantization
                # Ignore title/status changes and ordinary small cursor movement.
                w, h = image.size
                viewport = image.crop((w * 0.2, h * 0.2, w * 0.7, h * 0.7)).resize((320, 200)).convert("L")
                if previous is not None:
                    change = ImageStat.Stat(ImageChops.difference(viewport, previous)).mean[0]
                    changes += change > 0.25
                previous = viewport
                samples += 1
        except (OSError, ValueError, urllib.error.URLError):
            unavailable += 1
        time.sleep(0.1)
    with player_log.open(encoding="utf-8", errors="replace") as stream:
        stream.seek(offset)
        log = stream.read()
    rates = [float(x) for x in re.findall(r"P1_SCREEN_RATE fps=([\d.]+)", log)]
    passed = changes >= 5 and ages and max(ages) <= 3000 and quality_ok and rates and max(rates) > 1
    return {"passed": bool(passed), "viewport_changes": changes, "samples": samples,
            "unavailable_samples": unavailable, "max_pixel_age_ms": max(ages) if ages else None,
            "source_sizes": sorted(sizes), "jpeg95_444": bool(quality_ok),
            "peak_player_rate_during_trial": max(rates) if rates else None,
            "note": "Requires real viewport motion. This is not an independently certified sustained40fps result."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--player-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.seconds, args.player_log)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    raise SystemExit(0 if result["passed"] else 1)
