# Native lease lifetime while the owner disconnects

`tests/backend/p3b_native_execution_check.py` uses actual GUI Blender and the
production `host.register/start/_drain`, `Commands`, `Editor`, `Session` and lease
store. The only application override selects an isolated loopback port. There
is no FakeEditor, manual `Session.left`, reentrant queue drain or geometry
substitute. This diagnostic has no CAD/capabilities or Unity dependency.

Two real socket clients join. The owner reserves a 20 mm native cube and sends
one ordinary shared-leased 10 mm X move. A controlled diagnostic pause inside
the committing real `Editor.apply` lets either an explicit socket shutdown or
the unchanged six-second transport timeout occur. The server's I/O thread must
have removed the socket writer while main-thread participant cleanup is still
pending. Throughout that interval the transaction is committing and the lease
must remain held. A different client sends a competing reservation request
during the interval; its handler cannot interleave the executing native call.

The original real Editor then applies and reads back the native transform and
pushes its ordinary Undo step. The lease must still exist at the end of that
native application. Normal server queue processing then delivers disconnect
cleanup and releases it. A fresh peer receives the current complete scene and
queries the lost applied receipt. Exactly one command was sent and one real
native apply ran; the fresh native coordinate is 10 mm, with no replay.

The main-thread architecture naturally queues disconnect delivery until after
the executing call. This is an actual transport/commit boundary test, not an
artificial direct call to the deferred `Session.left` unit-test branch. The
pause models an executing call's duration and is not a geometry performance
measurement. A pinging observer remains connected throughout the silent-owner
timeout case. Neither strict desktop protection nor physical/second-PC
acceptance follows from these results.

Run from an unchanged tested checkout with a fresh outside-OneDrive evidence
directory and an unused nonstandard loopback port:

```powershell
$env:P3B_EXECUTION_BLENDER = 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe'
$env:P3B_EXECUTION_EVIDENCE = 'C:/isolated/evidence/new-p3b-execution-run'
$env:P3B_EXECUTION_PORT = '33765'
& $python313 -m pytest tests/backend/test_p3b_native_execution.py -q -rs
```

The opt-in test starts hidden GUI Blender separately for `disconnect` and
`timeout`, with isolated user resources below each case output. It refuses to
overwrite previous evidence. Each result records source and harness hashes,
events/timestamps, native coordinate, current scene, recovered receipt, every
received message and outgoing message IDs/types, errors and process identity.
The runner validates received messages against that checkout's actual schemas
and requires clean process exit. The actual frozen cumulative B must rerun
these cases after integration; an earlier foundational/native result is not a
pass for a different B commit.
