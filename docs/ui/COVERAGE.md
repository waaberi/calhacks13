# Glass migration coverage

Scope: existing P3 functionality, with P2/P2.5 control/clarity fixes selectively reconciled. This assignment adds appearance and the human-requested gentle preview curve. No runtime, feature publication, PR or main action is included.

| Reachable surface | Live creation path | Migration / boundary |
|---|---|---|
| Workspace arrangement, pinned/hand menu | TablePlacement.CreatePanel | Rounded glass panel/actions, circle gear, exact corner hit contour; accepted placement callbacks retained |
| Settings, environment, independent plane pages | TablePlacement.CreatePanel | Same factories; dynamic pages and pagination included |
| Appearance/accessibility | Existing Settings submenu | Persisted text/target scale, contrast, transparency, motion; no separate editing settings menu |
| Blender window title, toolbar, controls, capture/connection/empty/error status | BlenderScreen.BuildUi / LateUpdate | Rounded glass frame and curved canvas, same semantic states, native image never tinted/blurred |
| Live native image / resized or auxiliary window | BlenderScreen + PreviewInputMapping | Same native source pixels/aspect/filter/encoding/crop; rounded safe-inset stencil; analytical curved hit conversion |
| Native input toggle, lock, controller/mouse controls | PreviewInteraction.BuildControls / RefreshInputIndicator | Press/hover/focus/ON/LOCKED/pending/blocked/releasing retained through GlassControl |
| Basic and full keyboard, modifiers | PreviewInteraction.BuildControls / keyboard pages | Rounded keys, persistent modifiers, identical balanced native-key/release handling; follows curved parent |
| Window/dialog chooser, pagination, cancel, focus/error feedback | PreviewInteraction.BuildWindowControls | Dynamic buttons/text use shared factories and curved projection; owned native dialog backend untouched |
| Ownership, drawing and input action/error notices | Existing preview feedback/actionFeedback | Shared type, meaningful text and native state retained; no alternate modeling controls |
| Connection fallback without a preview | HostScene.UpdateHeadsetStatus / OnGUI | Glass world panel plus rounded monitor-only emergency status/action |
| Plane labels / manual fallback notices | WorkspaceSurfaces level labels | Rounded label backing and shared type; unlit semantic grid/handle/model edges preserved |
| Quest setup companion instructions | QuestRoomSetup.BuildUi | Same rounded theme/type; companion remains optional, not automatically launched/enabled |
| Reusable fields/toggles/sliders/scrollbars/tooltips/dialogs | GlassComponents | Same tokens/contours/states; gallery covers them; baseline does not invent these product flows |
| Voice and remote-presence panels | Not present in selected compatible P3/P2.5 app tree | No unrelated main/voice/presence integration or activation; future adoption uses the shared API |
| Legacy numeric/model/shortcut editing palettes | Retired, BuildObjectControls/BuildCommonControls not called | Not reachable; native-only regression verifies they are not constructed. Existing historical code/tests preserved |
| Native Blender widgets/popups/add-on UI | Private Blender factory-startup profile | Supported theme palette/roundness only; Blender-owned separators/layout/icons cannot be reshaped by Unity |
| CAD objects, ownership model overlay, room scan polygons/meshes and guide lines | Content, not UI | Exact semantic geometry retained; no rounding CAD edges or changing authority/history |

## Regression and adoption map

New files: GlassTheme, RoundedGlassImage, GlassControl, GlassType, GlassRoot, GlassComponents, GlassController, GlassCurvedCanvas, GlassGraphicRaycaster, GlassDesktopStatus and the retained GlassSatinMetal shader. Native companion: glass_blender_theme.py in the existing private bootstrap package.

Adapt existing screen factories through StylePanel/StyleAction/StyleText; preserve caller state labels and action ownership. The changed call sites are TablePlacement, BlenderScreen, PreviewInteraction, HostScene, WorkspaceSurfaces and QuestRoomSetup. Controller appearance is in WorkspaceInteraction.CreateHand/RenderHand. The curved renderer and exact GlassRaycast/desktop raycaster changes must travel together. Keep the existing shader/resource meta GUIDs when copying into a branch. Never copy another branch's entire input/backend files over newer functional fixes.

`tools/audit_glass_ui.py` catches new direct Image constructors and unthemed Text/IMGUI factories in app-owned scripts. It explicitly excludes native/third-party content and geometry. Actual Unity tests verify contours, source/sample alignment, rendering and mapping; a static audit alone is not visual or physical acceptance.

The gallery is an implemented Unity render, not a mockup. The preview image used for visual QA is explicitly labeled synthetic, not live Blender. Live helper tests verify freshness and changing encoder callbacks without capturing or manipulating the shared desktop. Actual native GUI delivery, live changing preview, binocular comfort and controller feel remain the later coordinated physical checklist.
