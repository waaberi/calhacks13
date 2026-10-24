# P1 measured pipeline follow-up — 2026-10-24

Recommendation: promote only the product request policy from [`1526ec8`](https://github.com/waaberi/calhacks13/commit/1526ec8a157a9a4b9b993447e7fab5a3bec9da7c), subject to the current production-source builds and cumulative regression gates. Retain the existing two encoder workers and 16ms capture hint. The measured gain does **not** pass minimum 40fps or establish headset presentation. The coordinator owns phase-chain integration; this diagnostic branch does not update main or the product phase branches.

## Actual source and setup

Windows 11, Unity 6000.6.5f1, Blender 5.2.2 LTS, Python 3.12.14. A separately owned Blender fixture continuously changed its viewport without changing object transforms/dimensions. No competing Player/build/heavy test was scheduled. Full source resolution, JPEG95/4:4:4, render assets and accepted interaction source were preserved.

The v24 build used diagnostic source `34b29931541910de377067a526c50b64ce6e5b4d`; Assembly-CSharp SHA256 `56d2f91300f59b916dec9faa60a83f2b5b802a9b165aba4483dab8bb66d9e0a4`. Its actual build had zero errors and passed integrated P1 movement/controller/startup/render/request checks. The same binary ran all comparisons. Every trial reported eye0x0 and the explicit software-profile passthrough skip. No compositor or physical passthrough result is claimed. The guard and profiler must stay out of the product request-policy commit.

The unguarded v23 source `78db8e0` failed during its first claim trial with `XR_ERROR_LIMIT_REACHED`, `Crash!!!` and exit0xE06D7363. Baseline also logged thousands of app-space changes. Preserve that failure in [#125](https://github.com/waaberi/calhacks13/issues/125#issuecomment-6385408482). Manager/origin interaction is an investigative lead; neither HTTP causation nor an SDK resource leak is proved. The zero-eye guard permanently skips room startup for that diagnostic run and cannot handle later eye activation or neutralize a pre-existing manager.

## Same-binary legacy/claim/claim/legacy

Four 40-second profile trials ran sequentially from 14:32:12 to 14:35:34 UTC. All exited normally with code0 and no app-space-change log events. Complete intervals were included only when their **start** was at least6 profile seconds and their end at most40; each trial contributes16 intervals/about32.06 seconds. Rates use uncensored assignment counters divided by actual interval duration.

| Mode | Unique texture assignments / second | Minimum two-second interval |
|---|---:|---:|
| Legacy 1 | 32.9797 | 28.8644 |
| Claim 1 | 41.1407 | 29.9985 |
| Claim 2 | 41.4811 | 29.9781 |
| Legacy 2 | 33.1191 | 29.9279 |

Pooled legacy33.0494 versus claim41.3109 gives **24.9973% more software texture assignments**. Fifteen of32 claim intervals were below40. Minimum40 therefore fails. Claim request traces hit their4096 cap; trace totals are censored and are not full-run health counts. Retained DataProcessingError rows pair with intentional HTTP304 responses; InProgress rows pair with intentionally discarded HTTP200 requests. Producer clients were disabled for this comparison, so its empty HTTP counters provide no helper-availability evidence.

## Multi-minute claim reliability

The same v24 binary ran a305-second profile from14:48:16.434 to14:53:30.172 UTC and exited0 (313.731 seconds wall time). There were no Crash or app-space-change log events; eyes remained0x0. The149 complete intervals after6 seconds cover298.635 seconds:11,847 assignments, **39.6704fps**, minimum26.9070;73/149 intervals below40. Early fresh headers were available before completion19,214 times in these intervals. Counts include19,454 HTTP200,21,276 HTTP304 and7,607 discarded requests. These are software counters, not displayed headset frames.

Texture count stayed near79, maximum80. Mean texture memory for the first ten versus last ten retained intervals was135.520MB versus135.314MB; maximum171.344MB. No growth trend was observed over this bounded run; this does not prove indefinite leak freedom.

The exact two-worker helper ran alongside this Player and two independent HTTP sampling clients for324.110 observed seconds,319.110 steady. All21,118 attempts had outcomes:20,135 HTTP200,961 HTTP304,22 startup HTTP503; **zero steady failures, zero sampling exceptions, zero worker exceptions**. No failures completed after the observation boundary. The498 decoded quality samples were2560×1600, 4:4:4 and exact JPEG95 tables, with497 distinct sampled viewport hashes. All correlation rows were known. Source changed-publication bins averaged42.9686fps, minimum29.5: minimum40 still fails.

Frozen helper SHA256 `a46c15b31039dd375226525c66622a07ed83717da43bdd0f418be34407262c09`. Measurement V4 SHA256 `7be43b0856385594ff7d7f29444144e61feffef8ae1fc3e639707f3ba37d19b5`; correlation SHA256 `a258c548f7c4d63d94782458a458bb3e079ade4d402b4716b7dd80321c8b8ab7`. Ten focused harness checks passed. Publication rows are atomic and steady failures have an observed-end bound. Instrumentation overhead remains; comparisons use matched configurations.

## Helper variants

Four sequential40-second two-client trials ran14:39:01–14:41:45 UTC: two workers/16ms, three workers/16ms, two workers/1ms, repeated two-worker/16ms baseline. Steady publication rates were54.412,54.420,56.360 and57.114fps. Baseline drift exceeded the apparent variant gains. All exited0; no steady failures, worker errors or unknown correlations. Startup503 counts22/22/21/22 are retained. Quality samples58/62/64/54 were full2560×1600/JPEG95/4:4:4. No helper variant earned product promotion.

## Real resize and recovery

Genuine Computer Use actions targeted only the owned fixture. DPI-aware read-only Win32 bounds and decoded captures established the changes; requested dimensions alone were not accepted.

| Observation | Actual client pixels | Actual captured JPEG pixels |
|---|---:|---:|
| Initial restored window | 2560×1542 | 2564×1602 |
| Maximized | 2560×1555 | 2560×1600 |
| Restored | 2560×1542 | 2564×1602 |
| Width changed | 1267×1542 | 1271×1602 |
| Width and height changed | 1267×735 | 1271×795 |
| Maximized again | 2560×1555 | 2560×1600 |
| Minimized | 0×0 | Three expected HTTP503 responses |
| Restored from minimize | 2560×1555 | 2560×1600 |

JPEG dimensions matched measured DWM visible frame bounds, including nonclient decoration; they do not equal client dimensions. All available observations had three fresh200 captures, exact JPEG95 tables and4:4:4 sampling. Moving viewport samples changed; maximum decoded age was below100ms. The initial border-drag attempt left bounds unchanged and is retained as a failed attempt. Native titlebar Size controls produced the verified material changes.

Afterward the private helper closed normally0 and the fixture restored its view, checked object matrices/dimensions unchanged and quit. Native C remained alive and already dirty at revision1; its complete snapshot, open epoch and saved-file hash matched before/after. The exact prior C window was reselected by the restored normal helper with fresh2560×1600 pixels. No Save/discard, personal-window change, Meta/Link restart or security-setting change occurred. Six private build-generated settings files were archived/restored; the three known original settings byte hashes match. Accepted v20 and C4 rollback artifacts remain unchanged.

Evidence index: `v24-abba-runs.json`, `v24-abba-analysis.json`, `v24-claim-305-run.json`, `v24-claim-305-analysis.json`, raw source/result JSONs, all Player/build logs, helper-matrix receipts, resize01–09 JSON/PNG, native-result and C-restoration proofs are retained in local planning/experiment storage. Independent review and canonical issues distinguish observed results from product integration. Active-XR startup/late readiness/teardown, accepted physical movement/clarity, real second-PC and sustained minimum40 remain open gates.
