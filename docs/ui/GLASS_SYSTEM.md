# Shared glass appearance

This is the bounded P3 appearance assignment. Existing P3 editing, native authority/history and direct drawing are preserved. The work does not reopen functional P3 acceptance or enable other phases.

## Reference and translation

Reviewed Apple's [visionOS guidance](https://developer.apple.com/design/human-interface-guidelines/designing-for-visionos), [materials](https://developer.apple.com/design/human-interface-guidelines/materials), [buttons](https://developer.apple.com/design/human-interface-guidelines/buttons), [ornaments](https://developer.apple.com/design/human-interface-guidelines/ornaments), [accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility) and [Liquid Glass overview](https://developer.apple.com/documentation/technologyoverviews/liquid-glass). The materials window example and visionOS alert example informed nested curves, grouped controls and the separation of navigation from content. Original implementation assets are generated geometry/shader code. The existing Unity-licensed LegacyRuntime font remains in use; no Apple font, SF Symbol or proprietary artwork is shipped.

The first v9 candidate was rejected by the human as rounded transparency rather than convincing glass. That observation is retained; it was a real visual gap. The revised implementation adds actual scene-color diffusion, a rounded optical bevel, bounded Snell-law refraction, angle-dependent Fresnel response and directional highlights. These effects live in one shared material on every RoundedGlassImage; native working pixels remain outside it. Glass is deliberately subdued behind text and semantic states.

`GlassBackdropFeature` is added to the existing PC renderer, rather than replacing the pipeline. BeforeRenderingTransparents captures the opaque Unity scene before world-space UI can feed back into itself. Two normalized separable Gaussian passes produce a half-resolution RGBA diffusion texture. Camera texture dimension and array slices are inherited, and shader samples use per-eye texture-array macros. Full camera render scale1, MSAA4, framebuffer/URP alpha, native image resolution and OpenXR features remain unchanged. Only the diffusion texture is half resolution. Transparent scene objects are not in this capture; nested UI intentionally uses one scene backdrop instead of recursively frosting text and controls.

`GlassSurface.shader` uses the rounded shape's signed distance to derive bevel normals. A refracted ray with index1.45 and a capped thickness approximation displaces scene samples only around the edge. It projects displacement through screen derivatives so curved/yawed panels retain coherent edge direction. Fresnel and restrained broad reflections provide depth. The `_Frost` and `_Refraction` material parameters support controlled clear/frosted comparison. UI stencil, clipping, premultiplied alpha and the rounded raycast contour are preserved. Reduced transparency/high contrast bypass scene transmission.

Meta compositor passthrough is not exposed to these shaders. Empty RGBA scene regions therefore use the readable satin charcoal/reflection fallback while retaining passthrough alpha. This build cannot diffuse or refract the physical room. The Quest reference inspected requires a separate passthrough camera texture and permissions; adding that Android camera path to this Windows Link assignment would violate its boundaries. No camera access or substitute room image was introduced. Offline eye-reference renders and XR shader variants are software checks; active-XR stereo/alpha remains a physical gate.

Implementation research, pinned repository commits and license review are in [RESEARCH.md](RESEARCH.md). The code is an original small adaptation to our world-space/XR/alpha constraints, rather than importing a screen-overlay demo unchanged.

## Public API

`GlassTheme` owns semantic color, radii, type/spacing and controller material/dimension tokens. Use its factories and `GlassComponents`; do not invent per-screen palettes. Existing imperative factories call `StylePanel`, `StyleAction` and `StyleText` at creation, so dynamic windows inherit the same system.

```csharp
var panel = GlassTheme.Panel(parent, "Inspector", Vector2.zero, new Vector2(640, 380));
GlassTheme.Label(panel, "Workspace", new Vector2(0, 120), new Vector2(600, 60), 30);
var action = GlassTheme.Action(panel, "Continue", new Vector2(0, -100), new Vector2(300, 64), Continue);
var field = GlassComponents.Field(panel, "Name", Vector2.zero, new Vector2(560, 72), "", Rename);
GlassComponents.Status(panel, "Connection lost · input released", new Vector2(0, 70), new Vector2(600, 80), error: true);
GlassTheme.State(action, selected: true); // caller supplies a meaningful ON/locked label
```

Also available: Toggle, Slider, Scrollbar, Tooltip and Dialog. They do not enable any unrelated feature. Future native-text fields must use the existing input owner and cleanup barriers. Do not add another editing menu or a parallel native-input service.

`RoundedGlassImage` emits the actual contour used by its raycast filter and Unity stencil mask. Direct controller paths use `GlassTheme.Contains` or `GlassRaycast.Hit`, rather than only a rectangular bound. `GlassControl` supplies immediate registered press, hover, keyboard focus, selected, disabled and error appearance. Focus/selection strengthen the contour. Existing product labels retain ON, LOCKED, blocked, pending and release status. Caller click handlers can invoke `Press()` for explicit controller dispatch; no animation is added to tracked poses.

## Accessibility

Settings > Appearance / accessibility persists text/target scale1–2×, contrast, reduced transparency and reduced motion through PlayerPrefs. GlassRoot enlarges the entire surface and its hit regions together, retaining all labels/actions rather than truncating enlarged text into old bounds. Native Blender text remains controlled by the private profile's1.5 UI scale and full-resolution capture. High contrast and reduced transparency use opaque surfaces. Reduced motion eliminates decorative movement (there is no decorative controller motion) and shortens the stationary press acknowledgment. It never introduces or removes manipulation filtering.

## Curved Blender canvas

The human requested a slightly curved Meta Link-like preview. GlassCurvedCanvas bends the image, frame, masks, text and controls onto one cylindrical arc, radius5600 canvas units (5.6m at default scale, approximately18.8° across1840 units). GlassCurveMesh subdivides long UI triangles before bending; native UVs and source pixels stay untouched. GlassRaycast analytically intersects the same cylinder and unbends to the original RectTransform coordinates before the existing screen-to-native mapping. It covers corners, resize, yaw, magnification, pan and popup controls. GlassGraphicRaycaster provides the matching desktop/UI event projection. Root arrangement still uses the accepted aim-relative screen grab with manipulation stabilization, world placement and release anchoring; no head-follow or spring is added.

The viewport has a rounded stencil well with a safe inset. All of the native rectangular image, including corner controls, remains inside that well; no native edge pixel is cropped solely to round a corner. Native menus/popups remain accessible through the existing auxiliary-window route. No glass, tint, blur, refraction or vignette covers the working image.

## Controllers

Both meshes are smooth lathed cylinders with hemispherical caps and analytic normals; there are no flat primitive ends or colliders. Left is icy blue, right is lavender-purple, with shared metalness/roughness/dimension tokens. The shader supplies broad studio-environment highlights independent of room lighting, not an emissive rod.

Local +Z is the forward axis, and the forward rounded pole is local zero. The visible cylinder follows the current same-device OpenXR aim sample once per BeforeRender, converted through the origin once. Its parent retains the accepted grip pose. The decorative body is independent of the stabilized pointer and held contact: hovering or grabbing cannot turn or drag the body away from the physical controller. Existing pointer hit routing, grab stabilization, two-hand manipulation and release remain unchanged. Missing aim never substitutes grip. BeforeRender does not inject native input.

## Native Blender theme limits

`desktop-capture/glass_blender_theme.py` applies a reversible palette and any supported widget roundness only inside the existing factory-startup private profile. Autosaving preferences is disabled. The code never saves a personal preference file, opens/modifies a document or touches an existing Blender process. Blender owns native widget outlines, layout, editor separators, icons and popup geometry; those cannot all be reshaped by Unity. The native add-on remains the sole editing menu.

## Adoption and verification

Other branches can adopt the shared Glass*.cs, RoundedGlassImage, Resources/GlassSatinMetal, GlassSurface and GlassBackdropBlur shaders plus the GlassBackdropFeature renderer entry, then port the calls listed in COVERAGE.md. Do not replace another branch's input/backend/runtime files wholesale. The BlenderScreen/PreviewInteraction ray changes are inseparable from curvature. Preserve new functional fixes when resolving those files.

Run `tools/audit_glass_ui.py`, GlassChecks.Run and GlassBuild.Windows. GlassChecks generates a real Unity component gallery and actual preview/keyboard renders. The build invokes the existing cumulative P1/P2/P2.5 gates, including current-device/loss, aim drag, placement, room/scale, native pixel mapping, release/focus and freshness checks. Controller calibration/readability/curvature comfort, real changing native capture and actual headset input require the later coordinated runtime slot. Source/build/evidence manifests distinguish software delivery from physical acceptance.


Physical v4 rejection is preserved: the complete UI/controller appearance was not usable despite prior software passes. Stability correction removes idle mesh invalidation, adds explicit stereo variants with actual two-eye texture-array GPU checks, aligns all keyboard rows and the six-by-two action grid, and separates current controller body tracking from held-contact/ray filtering. Human appearance acceptance remains pending.
