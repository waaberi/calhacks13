import protocol
import pytest


def test_round_trip():
    msg = protocol.message("ping")
    line = protocol.encode(msg)
    assert line.endswith(b"\n") and line.count(b"\n") == 1
    assert protocol.decode(line) == msg


def test_reply_sets_re():
    ping = protocol.message("ping")
    pong = protocol.message("pong", re=ping["id"])
    assert protocol.decode(protocol.encode(pong))["re"] == ping["id"]


@pytest.mark.parametrize(
    "line",
    [
        b"not json\n",
        b"[1, 2]\n",
        b'{"v": 2, "type": "ping", "id": "a", "payload": {}}\n',
        b'{"v": 1, "id": "a", "payload": {}}\n',
        b'{"v": 1, "type": "ping", "id": "a", "payload": []}\n',
        b'{"v": 1, "type": "ping", "id": "a", "payload": {}, "re": 5}\n',
        b"\xff\xfe\n",
    ],
)
def test_rejects_malformed(line):
    with pytest.raises(protocol.ProtocolError):
        protocol.decode(line)


def test_rejects_oversized(monkeypatch):
    monkeypatch.setattr(protocol, "MAX_LINE_BYTES", 64)
    with pytest.raises(protocol.ProtocolError):
        protocol.encode(protocol.message("ping", {"blob": "x" * 100}))
    with pytest.raises(protocol.ProtocolError):
        protocol.decode(b"x" * 100)
