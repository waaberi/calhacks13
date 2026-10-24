# Explicit fresh C launch

The default launcher remains the P1 attachment flow. `--fresh-c` is a separate
ordinary-host route for the final C package. It never attaches to an existing host
or stops one. Occupied localhost8765 is a clear conflict before any dependency
copy, picker or Player starts. The original P1 host must be handed off deliberately;
do not terminate unrelated Blender windows to free the port.

Prepare the exact cumulative C extension ZIP with
`desktop-capture/fresh_c.py:build_addon_zip(source_directory, new_zip, frozen_commit)`.
The source directory is `blender_addon/spatial_modeling` from that frozen tree.
The helper includes its source revision, file hashes and retained dependency notices
from `docs/third-party`, returning the final ZIP SHA256. A distribution must also
retain the pinned CAD extension/runtime, wheel, complete notices and source
provenance. Do not package credentials, user profiles or generated caches.

Launch with the actual artifact values supplied by the final release manifest:

```text
python desktop-capture/launch.py --fresh-c
  --player <complete-final-C-Player-directory/SpatialModeling.exe>
  --player-assembly-sha256 <tested-Assembly-CSharp.dll-SHA256>
  --player-source-revision <tested-Player-source-commit>
  --blender <pinned-Blender5.2.2-executable>
  --blend <verified-saved-starter.blend>
  --addon-zip <matching-C-extension.zip>
  --addon-sha256 <published-ZIP-SHA256>
  --cad-extension <pinned-CAD_Sketcher-directory>
  --session-dir <new-empty-directory-outside-OneDrive>
```

The display is multiline for readability; pass those options in one command or use
the shell's normal line continuation. Paths containing spaces must be quoted. The
Player needs all adjacent files from its verified Windows build. Its EXE stub hash
alone does not identify the application assembly. The assembly is rechecked again
immediately before spawn, after the user's picker wait.

The launcher copies the source `.blend` to `working.blend` inside the new session;
native Save targets that copy. Blender starts with a new private resource/config/
scripts directory and factory startup. CAD Sketcher0.32.1 is copied privately, and
the pinned CPython3.13 Windows slvs3.2 wheel is extracted outside Blender's managed
extensions directory. CAD is registered before opening the saved copy. The exact
project ZIP is then unpacked and enabled as a plain private package using normal
project registration/Host lifecycle. Global extension dependency reconciliation
and preference saving are not used.

The fresh private bootstrap sets its transient `view.show_splash` preference false
before the GUI event loop and before opening the working copy. It restores the
original value on its owned stop/error path and never saves preferences. Blender
5.2.2 rejects `--no-splash`; that unsupported CLI option is not used. This source
guard prevents startup splash configuration, not a proven useful-viewport image.
The ordinary launch check must inspect the actual native capture for a clear,
properly framed model/sketch without overlays; fresh pixels alone are insufficient.
Because `load_ui=False` preserves the new session layout, a saved starter's viewport
layout is not a substitute for that check.

The bootstrap verifies actual CAD/native-solver module paths and versions, project
source file hashes, working-copy path, process identity and listener. Before the
picker or Player, the launcher independently obtains a real native welcome,
complete snapshot and matching pong; C sketch capability, document/open epoch and
host epoch must match this new process. A ping alone is insufficient.

An existing helper remains on its prior selection until the user deliberately
chooses the new C Blender PID in its picker. A title is insufficient: the launcher
requires the effective selected PID/HWND and actual fresh pixel timestamps. It
never reselects another window automatically. It refuses a competing Player and
revalidates the host, selection, pixel age and Player assembly before launch.

`--host-only` with `--fresh-c` verifies the actual native bootstrap/handshake and
returns before the picker or Player. Player identity is explicitly unvalidated in
that mode. This is useful for packaging validation, not a substitute for the final
combined Player gate. To stop only that owned host deliberately, first verify its
session/PID/file identity, save as needed, then close its window normally or create
its session-local `stop.signal`; no other process is searched or stopped.

The native test API permits an expected listener port/constructor injection in a
new owned test process. This has no CLI option and is not a new production port
feature. Tests use it while the original P1 host owns8765. Ordinary full default-port
launch remains blocked until that legacy-session handoff; no successful default-port
or final-C Player launch is inferred from an alternate-port host-only test.

Pinned manifest SHA256:
`2e8c1899bf52764e43c19e6d06c79e8883314dc0fc04d97f1db62858943bbdfa`.
Pinned slvs wheel SHA256:
`86159bc0c5e749eb04d94cbf28b6d38ace795e802b8131be36870502e336f4fa`.
Preserve both the wrapper metadata and bundled native SolveSpace GPL COPYING;
do not label the whole solver MIT-only. No upgrade or replacement solver is used.
