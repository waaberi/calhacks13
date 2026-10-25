"""Display host-solved sketch geometry; never run a local constraint solver."""

import math


def polylines(record):
    """Tessellate only the host's solved line endpoints and analytic circles."""
    points = {e["id"]: e["at"] for e in record["entities"] if e["kind"] == "point"}
    paths = []
    for entity in record["entities"]:
        if entity["kind"] == "line":
            paths.append(([(*points[p], 0) for p in entity["points"]], False))
        elif entity["kind"] == "circle":
            center, radius = points[entity["center"]], entity["radius"]
            paths.append(([(center[0] + radius * math.cos(i * math.tau / 128),
                            center[1] + radius * math.sin(i * math.tau / 128), 0)
                           for i in range(128)], True))
    return paths
