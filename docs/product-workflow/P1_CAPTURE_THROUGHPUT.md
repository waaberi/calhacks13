# P1 capture throughput checkpoint

The 2026-10-24 helper candidate improves full-quality changing-window capture but **does not pass the requested sustained minimum 40fps**. It is a helper-only proposal based on P1 `5d7110d`; it is not active-headset or combined P2/P3 acceptance.

## Source and behavior

Python implementation: `6f264b1bc35f03d35c4c86ddfd6057a7f1dedaf9`, followed by empty-frame recovery in `08fdb59022695468b63b842151059597b757173d`. Exact measured helper SHA256: `a46c15b31039dd375226525c66622a07ed83717da43bdd0f418be34407262c09`.

Inside the native callback, OpenCV copies the mapped BGRA color channels into owned contiguous BGR memory. JPEG already ignored alpha; padded source channel equality, ownership after source mutation and identical encoded JPEG bytes are tested. Exactly two JPEG workers share one replaceable waiting snapshot. Generation, capture-time and restart-epoch checks prevent obsolete publication. Restart and final publication share a lock; FPS timestamps use the high-resolution clock inside that lock with a nonpositive-span guard. An empty/unsupported mapped frame reports unavailable and a subsequent valid frame can recover.

Resolution limits, JPEG95/4:4:4, the original 16ms capture hint at 60fps, actual-pixel freshness, explicit window selection and fixed status schema remain unchanged. No interaction, render or XR code changes are included.

## Exact-source five-minute trial

Collection: **2026-10-24 11:56:36.815–12:01:42.600 UTC**, 305 seconds including five seconds of startup/warmup and 300 steady seconds. An isolated Blender 5.2.2 LTS copy continuously orbited its viewport; native object transforms/dimensions remained unchanged and the original view was restored. No Unity Player/build or competing heavy native test ran during this reserved interval. Windows Graphics Capture, two source encoder workers and two local HTTP clients used the exact helper above. Local instrumentation recorded callback, encode, publish, viewport fingerprints, HTTP observations, JPEG quality and thread exceptions.

| Measurement | Observed result |
| --- | --- |
| Steady changed-viewport publications, complete two-second bins | Mean **37.15fps**, minimum **30.0**, maximum **43.0** |
| Steady publication rate | 37.16fps |
| Entire-run callback rate | 46.16fps |
| Unique frames received by HTTP clients | 10,037 / 32.91fps |
| Steady unavailable responses | **0** |
| HTTP errors / thread exceptions | **0 / 0** |
| HTTP actual pixel age | Mean66.68ms, p95 85.06ms, maximum104.45ms |
| Owned pixel copy | Mean1.50ms |
| JPEG encoding | Mean44.43ms per encoded frame |
| Quality samples | **444**, all2560×1600, JPEG95 quantization and4:4:4;444 different viewport fingerprints |

The first five seconds included32 HTTP503 startup responses. These remain in the raw results; availability above is explicitly the subsequent300 seconds. Nineteen obsolete/out-of-order encoded frames were rejected. Status FPS is a short-window estimate with startup transients; publication counts and complete two-second bins determine the performance result.

Earlier short experiments reached approximately40 mean published fps. They used earlier experimental sources and do not replace this longer exact-source failure. The previous single-worker trial measured roughly24fps under a different workload; it is useful bottleneck evidence, not a matched claim of percentage improvement.

Local evidence identifiers: `final08fdb59-quiet-{raw,result,verified}.json`. Profiler SHA256: `bbe376cc5c0522d045ddb52c3afb9059555fbe9c5c36ef4f29cfda9966e314de`. The source-only callback path executes without an experimental copy or minimum-interval override. Instrumentation adds sampling overhead, so this is a measured test configuration, not an uninstrumented benchmark.

## Checks, failures and limits

All **22 capture/launcher tests passed**, Ruff passed. Actual worker regressions force restart after initial validation, delayed older-frame completion, owned padded buffers and empty-frame recovery; thread exceptions are collected and worker threads are joined. The initial parallel prototype raised `ZeroDivisionError: float division by zero` from coincident Windows clock ticks while unittest misleadingly printed OK. That run was rejected; the clock/lock/zero-span fix and exception-aware tests are included. Before the empty-frame guard, its red regression raised OpenCV `(-215:Assertion failed) !_src.empty()` in `cv::cvtColor`; the next valid frame now recovers. Reports belong to existing issue [#21](https://github.com/waaberi/calhacks13/issues/21).

Run the capture suite with the documented capture dependencies available: `python -m unittest discover -s desktop-capture -p test_*.py -v`, followed by `ruff check desktop-capture`. Use the project's Python3.13 test environment for Ruff. The production helper still requires the existing Windows capture dependencies.

This trial contains no Unity texture-assignment or active-compositor measurement. A previous diagnostic Player discarded many duplicate decoded textures; a separate bounded request-claim proposal requires a matched real Unity A/B trial before propagation. The absent headset, physical clarity/controllers/passthrough, active-XR shutdown, broad resize sweep and human contract review remain separate pending gates. The physically accepted v20 binary is retained as rollback. Main was not updated.
