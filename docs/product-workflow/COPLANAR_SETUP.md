# Start Coplanar

1. Connect your Quest to the PC in Meta Quest Link.
2. Open **Coplanar** from the desktop or Start menu.
3. Press **Start / Reconnect**, then enter Quest Link in the headset.

Blender opens automatically with a working copy. Leave the file field empty for
the included starter scene, or choose your own `.blend` file. The original file
stays untouched. Save your work in Blender normally.

The next launch reconnects to the same session. If Blender has closed, Start
opens a new copy of its last saved file. Unsaved changes cannot be reconstructed
after Blender exits; use Blender's recovery tools if needed.

**Show connected Blender** brings back the window actually used by VR. If you
have several Blender windows, maximizing another one does not restore the
connected screen. A maximized connected window stays maximized. The capture
helper no longer opens a separate selector during managed setup.

To choose a different scene, close the Coplanar VR window and use **New workspace**.
Your other Blender windows remain open. Setup never closes them or discards edits.
Voice is optional and does not block basic setup. Room alignment and headset
readiness still require a live headset session.

If connection fails, follow the message and retry. **Open setup logs** gives you
the session logs. No chat, shell commands, port numbers, saved process IDs, or
repository files are needed for ordinary use.

## Packaging

Ship the verified Windows package, Python runtime (Tk, Pillow, numpy, OpenCV,
windows-capture dependencies), and `desktop-capture` launcher modules together.
Run `install_coplanar.py --package COMPLETE_PACKAGE` with that runtime. It installs
per-user desktop/Start shortcuts and retains prior shortcuts for rollback. It
does not launch applications, install into personal Blender profiles, or modify
the verified application package. Blender 5.2 must be installed; setup detects
the usual installation or allows the executable to be selected.

Session files, private Blender profiles, working copies and logs live under
`%LOCALAPPDATA%/Coplanar`, outside the repository and OneDrive. Components use a
private pair of local ports, a verified native process/window binding and a fresh
capture before starting VR. Reconnect checks process lifetimes, so recycled PIDs
and HWNDs cannot stand in for an old session. New launches never terminate a
running Player, and retries retain partial progress rather than opening duplicate
Blender windows. A per-user lock prevents two setup windows from launching in parallel.

The minimized message is window-specific; actual `IsIconic(HWND)` is checked,
not window size. Restore uses `ShowWindowAsync(SW_RESTORE)` only when that verified
window is minimized. Microsoft documents these APIs at
[IsIconic](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-isiconic)
and [ShowWindowAsync](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-showwindowasync).

Automated tests cover identity/reconnect, saved-copy recovery, a wrong helper,
helper restart, maximized/minimized restore and package integrity. Fresh desktop
and headset acceptance must be recorded separately; automated passes do not prove
that the original reported physical failure is resolved.
