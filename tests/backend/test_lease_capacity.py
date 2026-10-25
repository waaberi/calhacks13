"""An evicted acquisition request must never silently acquire a new reservation."""

import leases
from test_commands import SHAFT, hosting
from test_leases import acquire, released


def test_evicted_acquire_id_does_not_grant_a_new_lease(monkeypatch):
    monkeypatch.setattr(leases, "MAX_REQUESTS", 3)
    with hosting() as host, host.vr() as vr:
        request = acquire(vr, "shared", [SHAFT])
        original = vr.ask(request)[1]
        released(vr, original["payload"]["lease"]["lease_id"])
        for _ in range(3):
            assert vr.ask(acquire(vr, "shared", ["0" * 32]))[1]["type"] == "error"
        assert request["id"] not in host.leases.requests
        replay = vr.ask(request)[1]
        assert replay["type"] == "error"
        assert replay["payload"]["code"] == "duplicate_request"
        assert host.sess.store.leases() == []
