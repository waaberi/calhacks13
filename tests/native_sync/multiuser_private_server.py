"""Own-fixture upstream server; force loopback before any listener is created."""
import json
import sys
import time
from pathlib import Path

folder = Path(sys.argv[1])
config = json.loads((folder / "config.json").read_text())
sys.path.insert(0, config["dependencies"])
from replication import net
from replication.server import ServerNetService

original_listener = net.Listener


class PrivateListener(original_listener):
    def __init__(self, port, address="127.0.0.1", **kwargs):
        assert address == "127.0.0.1"
        super().__init__(port, address=address, **kwargs)


net.Listener = PrivateListener
server = ServerNetService()
server.listen(port=config["port"], server_password=config["server_password"],
              admin_password=config["admin_password"], timeout=20000)
(folder / "server-ready").touch()
try:
    deadline = time.monotonic() + 180
    while not (folder / "stop-server").exists() and time.monotonic() < deadline:
        time.sleep(.1)
finally:
    server.stop()
