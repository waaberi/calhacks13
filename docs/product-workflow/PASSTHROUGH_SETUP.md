# Windows room passthrough

This uses the Meta compositor underlay; the app does not read raw camera images.

1. Verify the same Meta developer account used in Link and finish developer team setup.
2. Restart Link after setup, coordinating with any active headset test. Settings should expose **Developer**.
3. Enable **Developer runtime features**. The user enables **Pass-through over Meta Horizon Link** and handles its consent. Raw **Pass-through camera API permissions** are not needed.
4. Before launching the app, confirm the runtime exposes `XR_FB_passthrough`. An available extension is a prerequisite, not proof that the room is visible.
5. Launch the Windows build. Check actual headset visibility of the keyboard/room behind the Blender panel, both controller rays/grips, and the Room view toggle. A black desktop mirror alone is inconclusive.

The URP build must preserve framebuffer alpha and retain alpha-output variants. The room-view camera disables HDR while passthrough is requested, avoiding the packed HDR color format without alpha, and restores its previous settings when room view is disabled. Meta's underlay needs a transparent eye-buffer background.

Meta developer features can expose a different controller layout. The input reader supports both Input System `PoseState` and the Meta OpenXR `Pose` control, retaining valid position/rotation checks and the current before-render sampling. Missing or partially tracked poses are rejected.

Relevant reports: [passthrough #124](https://github.com/waaberi/calhacks13/issues/124), [controller pose types #126](https://github.com/waaberi/calhacks13/issues/126), [observed Windows shutdown crash #125](https://github.com/waaberi/calhacks13/issues/125).

Meta references: [Link setup](https://developers.meta.com/vr/documentation/unity/unity-link/), [passthrough troubleshooting](https://developers.meta.com/vr/documentation/unity/unity-pt-troubleshooting/). Link's documentation also specifies at least 2 Gbps effective USB bandwidth for color passthrough; report actual results separately from app initialization.

Passthrough was developed on isolated `codex/talia-passthrough` and its accepted alpha fixes are integrated into [`codex/talia-p1-usb-screen`](https://github.com/waaberi/calhacks13/tree/codex/talia-p1-usb-screen). Source publication, main integration and physical acceptance are recorded independently.

2026-10-24 physical USB result: Talia confirms real room visibility and both controller rays/grips work in p1-passthrough-combined-v2. Movement smoothness, text/icon quality and recovery tests remain separate. Published evidence: https://github.com/waaberi/calhacks13/issues/124#issuecomment-6382355899 .
