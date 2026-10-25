"""Presence is an atomic display cache, independent of scene/mirror changes."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "remote_presence", ROOT / "blender_addon/spatial_modeling/remote_client/presence.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def example(name):
    return json.loads((ROOT / f"contracts/examples/{name}.json").read_text())["payload"]


def test_full_names_leases_atomic_replace_and_disconnect():
    presence = MODULE.Presence()
    welcome, update = example("welcome"), example("session.update")
    presence.welcomed(welcome)
    presence.receive(update)
    assert presence.actor_id == welcome["actor_id"]
    assert presence.participants == update["participants"]
    assert presence.leases[0]["owner"]["name"] == "Lee Jae-yeon"
    update["leases"][0]["owner"]["name"] = "changed caller data"
    assert presence.leases[0]["owner"]["name"] == "Lee Jae-yeon"
    presence.receive({"participants": update["participants"], "leases": []})
    assert not presence.leases
    presence.clear()
    assert presence.actor_id == "" and not presence.participants and not presence.activities


@pytest.mark.parametrize("bad", ["duplicate_actor", "missing_owner", "bad_target", "bad_mode"])
def test_invalid_presence_never_partially_replaces_current_state(bad):
    presence = MODULE.Presence()
    body = example("session.update")
    presence.receive(body)
    before = copy.deepcopy(presence.leases)
    if bad == "duplicate_actor":
        body["participants"].append(body["participants"][0])
    elif bad == "missing_owner":
        body["leases"][0]["owner"]["actor_id"] = "f" * 32
    elif bad == "bad_target":
        body["leases"][0]["targets"].append("not-an-id")
    else:
        body["leases"][0]["mode"] = "unknown"
    with pytest.raises(ValueError):
        presence.receive(body)
    assert presence.leases == before


def test_activity_is_bounded_and_welcome_clears_prior_connection():
    presence = MODULE.Presence()
    for _ in range(50):
        presence.activity(example("activity"))
    assert len(presence.activities) == 32
    presence.welcomed(example("welcome"))
    assert not presence.activities and not presence.leases
