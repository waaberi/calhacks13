"""Display-only ownership records shared by the Blender overlays and tests.

These helpers never write object properties, colors, materials or selection.
The owner names come from authenticated host presence, not local placeholders.
"""


def markers(leases, object_ids, own_actor_id=None):
    """Object ID -> real owner names for leases held by other participants.

    An exclusive reservation covers every displayed object. Shared reservation
    targets already include linked data and dependent objects, as expanded by
    the host. Missing/deleted IDs are deliberately ignored.
    """
    available = set(object_ids)
    result = {}
    for lease in leases:
        owner = lease["owner"]
        if own_actor_id is not None and owner["actor_id"] == own_actor_id:
            continue
        targets = available if lease["mode"] == "exclusive" else lease["targets"]
        for target in targets:
            if target in available:
                names = result.setdefault(target, [])
                if owner["name"] not in names:
                    names.append(owner["name"])
    return {key: tuple(value) for key, value in result.items()}


def activity_text(leases, own_actor_id=None):
    """A compact notice using the current lease owners' actual names."""
    active = list(dict.fromkeys(x["owner"]["name"] for x in leases))
    if len(active) > 1:
        return "Two people are editing: " + ", ".join(active)
    other = [x for x in leases if x["owner"]["actor_id"] != own_actor_id]
    if not other:
        return ""
    lease = other[0]
    who = lease["owner"]["name"]
    return (f"{who} is editing — wait for Apply" if lease["mode"] == "exclusive"
            else f"{who} is editing the pink objects")
