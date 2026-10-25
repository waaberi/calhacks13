# coplanar.design

Public marketing site for Coplanar. Static HTML, CSS and JavaScript with no build step and no dependencies.

## Run locally

```sh
cd website
python3 -m http.server 4173
# open http://localhost:4173
```

Any static file server works. Use a server, not `file://`, because the scripts are ES modules.

## Deploy on Vercel

- Root Directory: `website`
- Framework Preset: Other
- Build Command: none
- Output Directory: `.`

`vercel.json` sets clean URLs, caching and security headers (including a strict same-origin Content Security Policy).

## Files

- `index.html`: the page.
- `assets/styles.css`: all styles.
- `assets/scene.js`: a small canvas 3D renderer that draws the shared-modeling illustrations. It is a drawing, not a capture of the app.
- `assets/main.js`: wires the hero illustration (seats, tools, undo and redo, self-running demo) and the voice plan demo.
- `assets/og.png`, `assets/apple-touch-icon.png`, `assets/favicon.svg`: social and icon images, rendered from the page's own scene and logo.
- `assets/fonts/`: Bricolage Grotesque and JetBrains Mono, self-hosted under the SIL Open Font License (license files alongside).
