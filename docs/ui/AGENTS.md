# App UI extension rules

For app-owned UI in this project, use GlassTheme and GlassComponents from docs/ui/GLASS_SYSTEM.md. Reuse semantic tokens, RoundedGlassImage contours and GlassControl states. Route direct controller hit testing through GlassRaycast or GlassTheme.Contains; transparent corners must not steal input. Use StyleText for dynamic labels. New Blender descendants inherit GlassCurveMesh, and all pointer mapping must unbend through the same cylinder.

Do not put tint/blur/glass over native working pixels, introduce another modeling menu, or change native authority/history to fit UI styling. Preserve registered press, ON/LOCKED/error/release cues and accessibility settings. Model/CAD/room geometry and third-party/native widget geometry are explicit exemptions from UI rounding.

Run tools/audit_glass_ui.py and relevant GlassChecks/cumulative Unity gates. Software checks do not establish physical acceptance. Follow the human's current runtime/publication boundaries; this document grants no runtime, push, PR or main permission.
