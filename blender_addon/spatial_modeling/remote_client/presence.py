"""Authoritative presence display cache; never changes native or mirror geometry."""

import copy
import re
from collections import deque


def _uuid(value):
    if not isinstance(value, str) or re.fullmatch("[0-9a-f]{32}", value) is None:
        raise ValueError("Invalid presence identity")


def _actor(actor):
    _uuid(actor["actor_id"])
    if (not isinstance(actor["name"], str) or not 1 <= len(actor["name"]) <= 256
            or actor["role"] not in ("host", "vr", "blender-client")):
        raise ValueError("Invalid participant")


class Presence:
    def __init__(self):
        self.clear()

    def clear(self):
        self.actor_id = ""
        self.participants = []
        self.leases = []
        self.activities = deque(maxlen=32)

    def welcomed(self, body):
        _uuid(body["actor_id"])
        self.clear()
        self.actor_id = body["actor_id"]

    def receive(self, body):
        participants, leases = body["participants"], body["leases"]
        if not isinstance(participants, list) or not isinstance(leases, list):
            raise TypeError("Invalid presence snapshot")
        actors, ids = set(), set()
        for actor in participants:
            _actor(actor)
            if actor["actor_id"] in actors:
                raise ValueError("Duplicate participant")
            actors.add(actor["actor_id"])
        for lease in leases:
            _uuid(lease["lease_id"])
            _actor(lease["owner"])
            targets = lease["targets"]
            if (lease["mode"] not in ("shared", "exclusive")
                    or type(lease["acquired_at"]) is not int or lease["acquired_at"] < 0
                    or not isinstance(targets, list) or lease["lease_id"] in ids
                    or lease["owner"]["actor_id"] not in actors):
                raise ValueError("Invalid lease")
            for target in targets:
                _uuid(target)
            if len(targets) != len(set(targets)):
                raise ValueError("Duplicate lease target")
            ids.add(lease["lease_id"])
        self.participants = copy.deepcopy(participants)
        self.leases = copy.deepcopy(leases)

    def activity(self, body):
        _actor(body["actor"])
        _uuid(body["request_id"])
        if body["outcome"] not in ("pending", "applied", "rejected", "unknown"):
            raise ValueError("Invalid activity outcome")
        self.activities.append(copy.deepcopy(body))
