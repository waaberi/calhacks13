"""Check a saved P2 snapshot against independently recorded IDs/positions/units.

python tests/backend/check_snapshot.py snapshot.json --reference positions.json --scale-length .001
positions.json maps stable object IDs to world [x,y,z] positions in meters.
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] /
                      "blender_addon/spatial_modeling/remote_client"))
from state import SceneState


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--scale-length", required=True, type=float)
    args = parser.parse_args()
    data = json.loads(args.snapshot.read_text(encoding="utf-8"))
    state = SceneState()
    state.receive(data.get("payload", data), True)
    result = state.check_reference(json.loads(args.reference.read_text(encoding="utf-8")))
    if not math.isclose(result["scale_length"], args.scale_length, rel_tol=1e-9):
        raise ValueError("Host scene unit scale differs from the independent reference")
    print(json.dumps({"passed": True, **result}))


if __name__ == "__main__":
    main()
