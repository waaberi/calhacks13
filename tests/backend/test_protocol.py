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


@pytest.mark.parametrize(
    "number", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999", "1" * 5000], ids=lambda n: n[:9]
)
def test_rejects_non_finite_numbers(number):
    line = '{"v": 1, "type": "ping", "id": "a", "payload": {"x": ' + number + "}}\n"
    with pytest.raises(protocol.ProtocolError):
        protocol.decode(line.encode())


def test_accepts_ordinary_numbers():
    line = b'{"v": 1, "type": "ping", "id": "a", "payload": {"x": [1e300, -0.0, 2, 1.5e-7]}}\n'
    assert protocol.decode(line)["payload"]["x"] == [1e300, -0.0, 2, 1.5e-7]


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_never_sends_non_finite_numbers(number):
    with pytest.raises(protocol.ProtocolError):
        protocol.encode(protocol.message("ping", {"x": number}))
