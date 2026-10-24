"""A bounded history must never turn an evicted ID or query fence into a new edit."""

import uuid

import commands
import pytest
from test_commands import SHAFT, assert_rejected, hosting


@pytest.mark.parametrize("originally_applied", [True, False])
def test_evicted_receipt_or_query_fence_never_becomes_an_edit(monkeypatch, originally_applied):
    monkeypatch.setattr(commands, "MAX_RECEIPTS", 3)
    with hosting() as host, host.vr() as vr:
        request = vr.command("object.add", args={"primitive": "cube", "location": [0, 0, 0],
                                                 "dimensions": [0.02, 0.02, 0.02]})
        if originally_applied:
            assert vr.ask(request)[1]["payload"]["outcome"] == "applied"
        else:
            assert vr.query(request["id"])["missing"] == [request["id"]]
        vr.query(*(uuid.uuid4().hex for _ in range(3)))
        assert request["id"] not in host.cmds.receipts
        before = list(host.editor.applied)
        assert_rejected(vr.ask(request)[1]["payload"], "duplicate_request")
        assert host.editor.applied == before
        assert len(host.cmds.receipts) <= 3


def test_capacity_fails_closed_for_new_writes_but_retained_receipts_still_replay(monkeypatch):
    monkeypatch.setattr(commands, "MAX_RECEIPTS", 3)
    with hosting() as host, host.vr() as vr:
        vr.query(*(uuid.uuid4().hex for _ in range(3)))
        request = vr.command("object.move", SHAFT, {"by": [0.01, 0, 0]})
        receipt = vr.ask(request)[1]["payload"]
        assert receipt["outcome"] == "applied"  # no IDs had been dropped before this write
        assert host.cmds.evicted
        assert vr.ask(request)[1]["payload"] == receipt
        before = list(host.editor.applied)
        denied = vr.run("object.move", {"id": SHAFT, "generation": receipt["revision"]},
                        {"by": [0.01, 0, 0]})
        assert_rejected(denied, "duplicate_request")
        assert "restart" in denied["error"]["message"]
        assert host.editor.applied == before
