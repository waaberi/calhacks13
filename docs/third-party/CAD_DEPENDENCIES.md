# CAD dependency pins and retained notices

| Component | Exact tested dependency | Source / notice |
| --- | --- | --- |
| Blender | 5.2.2 LTS, build d13f752e3b9c; Python3.13.13 Windows x64 | Existing project-pinned Blender installation |
| CAD Sketcher | 0.32.1, manifest minimum Blender5.0.0 | https://github.com/hlorus/CAD_Sketcher ; manifest `SPDX:GPL-3.0-or-later`; retained unmodified `CAD_SKETCHER_GPL3.txt` |
| slvs native wheel | slvs-3.2-cp313-cp313-win_amd64.whl | https://pypi.org/project/slvs/3.2/ ; bundled wheel retained COPYING as `SLVS_COPYING.txt`; SolveSpace source https://github.com/solvespace/solvespace |

Pinned installed CAD Sketcher manifest SHA256: `2e8c1899bf52764e43c19e6d06c79e8883314dc0fc04d97f1db62858943bbdfa`.
Pinned Windows CPython3.13 slvs wheel SHA256: `86159bc0c5e749eb04d94cbf28b6d38ace795e802b8131be36870502e336f4fa`.

The slvs3.2 wheel's METADATA labels the wrapper MIT, while its bundled `licenses/COPYING.txt` is the GNU GPLv3 license for the included SolveSpace code. Preserve both facts and the full COPYING notice; do not relabel the bundled native solver MIT-only. The adapter repository does not redistribute dependency binaries. Packaging CAD Sketcher or its wheel must retain the extension manifest, copyright/license files and corresponding upstream source provenance. No automatic upgrade or custom solver fallback is performed.

CAD Sketcher's upstream README identifies it as experimental. The adapter stages changes and retains last-valid editable native data on a rejected solver trial; use isolated copies for compatibility and failure tests. The source and wheel are the already-installed P0-verified versions, not newly fetched dependencies.
