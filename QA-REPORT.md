# QA report — Pitlane 2.2 / multi-car replay + configurable dashboard

Verified during this build on **2026-10-19**. All twelve suites below were executed after the multi-car replay integration; browser suites ran sequentially to avoid graphics contention. These are actual tests of the implementation, not inferred coverage from screenshots.

## Automated results

| Suite | Result | Evidence |
|---|---:|---|
| Dashboard Python / data / API | **104 passed**, 0 failures | `qa/dashboard-pytest-results.xml` |
| Dashboard pure model / exhaustive timing frames | **2,846 passed**, 0 failures | `qa/dashboard-model-results.json` |
| Dashboard Chromium interactions / desktop / mobile | **137 passed**, 0 failures | `qa/dashboard-browser-results.json` |
| Connection configuration / auth / native adapters / Hopsworks contracts | **73 passed**, 0 failures | `qa/connections-pytest-results.xml` |
| Connection UI / native-mode navigation / mobile / recovery (offline fixtures) | **63 passed**, 0 failures | `qa/connections-browser-results.json` |
| Original Python data/model/API + offline cloud contracts | **60 passed**, 0 failures | `qa/pytest-results.xml` |
| Original four-experience browser interactions | **25 passed**, 0 failures | `qa/browser-results.json` |
| 3D geometry, all 12 ordered driver pairs | **48 passed**, 0 failures | `qa/replay-geometry-results.json` |
| 3D cameras, transport, native audio, recovery and mobile | **43 passed**, 0 failures | `qa/replay-browser-results.json` |
| Shared-clock archive / all-driver API integrity | **50 passed**, 0 failures | `qa/race-replay-pytest-results.xml` |
| Multi-car pure frame model / gap handling | **39 passed**, 0 failures | `qa/fleet-model-results.json` |
| Four/20-car browser / 3D / audio / mobile / recovery | **41 passed**, 0 failures | `qa/fleet-browser-results.json` |
| Unexpected browser runtime/console errors | **0** | All five browser reports |
| External browser requests required | **0** | Request interception/audits |
| Optional cloud publishing | **Dry runs only; no real writes** | Original cloud-plan reports / offline contracts |

**3,521 passing test/check assertions across twelve suites.** This aggregates Python tests and explicit JavaScript checks, not 3,521 independent end-to-end scenarios. The Python runs have a nonfailing Starlette TestClient/httpx deprecation warning. The build succeeds with the expected >500 kB lazy Three.js chunk warning; the scene is loaded only when needed.

## New multi-car replay verification

The public import completed successfully: **20 drivers**, **218,520 retained location records**, **110,300 retained car-data records**, 40 source responses and **841,220 raw records**. Source session/driver identity was audited in every raw record; all 20 curated file hashes verify. Per-driver streams have distinct content and monotonic timestamps. The stored timestamp sequence is not a fabricated uniform grid.

The 39 model checks cover four-lap ordering/equal-distance deltas, exact sample boundaries, missing/out-of-range channels, gap/jump rejection, real common-clock rank joins, partial coverage, final classification and **22,080 sampled driver frames** across the race. All those sampled real-data frames were renderable; separate explicit fixtures exercise hidden gaps/outliers. This is sampled-frame evidence, not a claim that every possible interpolated instant is perfect.

The 41 browser checks exercise the actual four-car and 20-car scenes: hide/show redraw while paused, every-driver focus selection, a real projected 3D marker click, orbit, shared-clock advancement, frame changes, lap presets, comparisons, consent-gated audio, pause silence, immersive/Escape, mobile, 2D marker selection, preserved A/B detail, missing-position recovery and WebGL fallback. Unexpected normal-path browser errors and external asset requests were **zero**. Deliberately injected missing-position and no-WebGL cases are isolated from that audit.

- A real 65 ms overlap between NOR lap 28's duration-derived end and lap 29's recorded start was identified. Continuous-time lap/tyre labels now use the consecutive recorded start as the boundary; raw durations and the separate historical-timing module are unchanged.
- One throttle=104 and five brake=104 source values were retained/flagged. Instruments and plots reject out-of-range percentages rather than claiming silently clipped values.
- Audio pause/mute updates now run on logical state changes rather than waiting for a graphics-heavy animation frame. Changing focus resets gear-transition history so a different driver's gear is not mistaken for a recorded gearshift.
- Latest multi-car analyser measurements: ghost playback RMS **0.0587207**, paused RMS **0**; synchronized race playback RMS **0.0445374**. Audio is designed/synthesized, not an official F1 recording.
- The original general/replay suites now explicitly enter the preserved **Two-car detail** tab. Their original assertions remain, and all **25 / 43** checks pass.
- Already-open tabs can finish loading the previous hashed asset versions during an update. Refresh to activate the new UI; old compiled assets do not change active entrypoint/source parity.

## New connection-layer verification

**73 Python tests** exercise server-only configuration, precedence (including organizer remote variables), strict mode/index/URL/CA validation, secret-safe diagnostics, authenticated actions, signed HttpOnly/SameSite/Secure cookies, tamper/cross-origin rejection, native-data access protection, private CLI initialization and archive exclusions.

Actual adapter logic is exercised against an **in-memory HTTP transport and SDK doubles**: exact mapping/count requests, PIT/search-after pagination and cleanup, bounded telemetry, no source-document writes, cap/timeout/partial-shard errors, native result/lap/weather usage, null positions and dates, sparse seasons, duplicate handling, unique feature batches, explicit write gates, filtered SDK reads, value verification, stale/corrupt batches and no hidden fallback. Native fixture values deliberately differ from the public archive so the test cannot pass by accidentally serving local data.

**63 connection browser checks** exercise the real UI/API with that explicitly labeled fixture server: wrong/correct operator login, no token in JS-readable storage/cookies, provider checks, native mode activation, native schema preview, failed activation before publication, real fixture feature planning/write/read-back, Hopsworks consumption by Race pace, all 19 routes with sparse native-shaped data, bounded telemetry plot/JSON, empty-slice honesty, mobile layout, local recovery and session locking. These are **not live account tests**. Expected wrong-token HTTP 401 output is recorded separately from the zero-unexpected-error audit.

- The native weather path initially exposed an assumption that every sample has a UTC date. It now displays “Not supplied” plus actual session seconds instead of crashing or inventing a timestamp.
- Partial native seasons retain gaps and disclose available-round counts; final standings are not forcibly replaced with public totals.
- A previous fixed-modal full-page screenshot timed out in the general browser harness. The modal is now captured as its actual viewport, with a larger screenshot allowance; the complete 25-check suite and 43-check replay suite subsequently passed. No functional assertion was removed.
- **Hopsworks SDK 5.2.1** was installed/imported on **Python 3.13.16**, and the login/insert/query-read signatures were inspected (`qa/hopsworks-sdk-contract.json`). The adapter explicitly enables hostname verification and stores SDK certificates under the excluded `.cache` tree. This is API-shape/import evidence, **not** server-version or live network/storage validation.
- The CLI's real local feature plan is in `qa/connection-plan-local.json`; no external provider writes were performed. The original lab cloud dry-run reports remain historical offline evidence, not new live verification.

## Dashboard data and API checks

- Verify all **93 archive file hashes**, actual coverage counts, unique lap/result IDs, native units/types and null preservation.
- Check every round's Race + Sprint championship sums and both seasons' final standings against independent Jolpica totals; preserve driver-team attribution. Bearman's Ferrari/Haas split and lapped-finish classification have dedicated assertions.
- Validate standings/profiles/aggregate stats, head-to-head shared qualifying segments, pace selection/quantiles, pit-lane summaries, weather, Track DNA complete-case similarity and missing Monaco evidence.
- Build local pace features, inspect actual SQLite read-back, distinguish exact filter configurations, and verify reruns. Tests use a separate temporary database, not the live app's connection.
- Exercise all dashboard API routes, five schema envelopes, ten CSV kinds, safe CSV cells, invalid parameters, unsupported slices, appropriate filenames and finite cutoff bounds.
- Qualifying weather is genuinely separate from Race weather; unsupported qualifying laps/full-field telemetry remain empty rather than being borrowed from another event.

## Exhaustive historical-timing checks

Every one of **2,739 intermediate lap frames across all 46 races** is checked, alongside grid/final frames and targeted fixtures. The suite verifies monotonic clocks, nonnegative ranks where known, no completed-lap leakage beyond the selected frame, actual as-of evidence, correct final order/counts, missing endpoints, discontinuous lap sequences and missing-frame holds.

A real **Japan 2024 restart inconsistency** caused the original implementation's clock to reverse between laps 1 and 2. The revised model uses the next consecutive recorded start when an endpoint is missing or differs by >0.25 s, quarantines remaining chronological conflicts, and preserves raw archive durations. **723 intermediate frames** use derived endpoints; no real selected frame needs a missing-frame hold in this snapshot. Separate synthetic fixtures exercise holding and missing-position behavior. This establishes consistency of the disclosed replay method, not a certified official lights-out timestamp.

## Dashboard browser coverage

- All **19 dashboard/connection routes** at **1440×1050 desktop** and **390×844 mobile**, with no horizontal document overflow.
- Real season/round changes, championship cutoffs, final-season action, results sessions, sorting, search, driver profiles, aggregate driver/constructor statistics and CSV downloads.
- Head-to-head, consistency DNF filtering, all race-pace chart modes, threshold changes and empty-selection/All recovery. Chart tooltips recover after empty data.
- Tyre timelines, pit filters, Race/Qualifying weather, race-control search/empty states and Track DNA's insufficient-evidence state.
- Coverage/schema/adaptation tabs, clipboard query template, actual local feature building, record previews, JSON downloads and truthful empty unsupported telemetry.
- Historical play/pause/reset/scrub, driver evidence dialogs, explicit final classification and the Japan restart regression.
- Theme/scope persistence, sidebar collapse, mobile drawer/Escape and preservation of the separate Dutch GP lab scope.
- An isolated injected HTTP 503 verifies error/retry recovery. Its expected console message is recorded separately from the normal-path zero-error audit; the same applies to the intentional WebGL-unavailable test in the original replay suite.

## Retained 3D and audio — rerun after the dashboard expansion

### Geometry and graphics

- The trajectories pass through **every one of the 361 resampled measured XY points**, for both cars in every ordered pair of NOR, VER, LEC and PIA.
- Each selected reference XY polyline is scaled to the nominal **4,259 m** circuit length. The road is closed, while the per-lap trajectories retain separate, non-looping finish endpoints.
- The maximum sampled offset of any comparison trajectory from its reference racing line was **2.248 m or less**, inside the illustrative 15 m road ribbon. This tests rendering consistency, **not surveyed track accuracy**.
- Actual Chromium **WebGL 2 / SwiftShader** contexts rendered the procedural circuit and cars. Chase A/B produced different image buffers; orbit dragging and wheel zoom changed the rendered view.
- Replay moves both cars, pauses, scrubs, reaches both exact finish distances, restarts, switches all four selected drivers, and retains its position when switching between 3D and the original 2D map.
- Desktop and mobile-sized theatre views keep the replay and sound controls within the viewport. Desktop Escape exits the theatre view. Speed/gear/RPM instruments remain visible in chase theatre mode.
- A real `WEBGL_lose_context` event exposes the 2D recovery action. A separately instrumented browser with WebGL unavailable can still load and play the 2D experience.
- That deliberately WebGL-disabled browser logs the expected Three.js initialization error. It is recorded separately, not mistaken for an unexpected production-path error.

### Native Web Audio, not just UI labels

The tests wrap browser-native AudioContext/node factories externally. Production code does not require test globals or mocked audio nodes.

- **No AudioContext exists before the explicit Enable sound click.** Enabling while paused creates a running context but does not generate an audible output signal.
- At 35% volume while playing, a sampled analyser window measured **RMS 0.06154** and **peak 0.10165** on the normalized output scale: nonzero, below digital clipping.
- After pause, the sampled RMS was **0**, below the **10⁻⁵** silence assertion threshold. Mute, zero volume and finishing the replay also pass the silence assertion.
- High/low recorded RPM samples produced combustion oscillator frequencies of approximately **605.67 Hz / 325.28 Hz**, within 3 Hz of the displayed RPM/20 reference after smoothing.
- Recorded gear transitions triggered additional transient sources and designed combustion/body frequency ratios of **2.58 / 3.21**, versus **3.00** outside the shift envelope.
- Chase B foregrounded driver B in the actual gain-node values, not only the text label. Raising volume restored nonzero signal; re-enabling reused the existing context.
- A **simulated document visibility event** exercises the page-hiding handler and confirms real output silence plus paused transport. This is a handler test, not a claim to have tested every operating system's background/audio policy.
- Navigating to Pitwall closes the audio context and releases the replay renderer. Returning to 3D from 2D creates a working renderer without changing replay time.

These measurements validate signal generation, telemetry responsiveness, controls and cleanup. They do **not** establish acoustic fidelity to a real F1 car, physical speaker loudness, cross-browser audio quality or real-world vehicle dynamics.

## Existing coverage rerun after the upgrade

- Checksums, unique lap keys, real/synthetic provenance, telemetry bounds and finish-line delta consistency.
- Target/future-leakage checks, rolling-history resets and chronological train/validation/test separation.
- Direct metric recomputation and persisted/read-back data in all four local feature groups.
- Original-strategy restoration to zero modeled change, pit-loss sensitivity and same-compound legality warnings.
- Driver identity exclusion from classifier inputs, whole-lap holdout, vote normalization and confusion-matrix accuracy.
- API validation and rejection of bad drivers, methods, ranges and feature-table names.
- Deterministic local pipeline reruns and downloadable feature CSVs.
- Offline cloud payload/prefix checks and a **fake SDK** Hopsworks insert/read-back contract, not a live Hopsworks test.
- Driver selection/swap, telemetry channels, pit controls, anomaly filters/evidence, blind driver guesses, next-lap reveal, shortlist/comparison and provenance dialogs.
- All four experiences at **1440px desktop** and **390px mobile**, including mobile navigation and no horizontal document overflow.

## Model results remain unchanged

- Pace baseline MAE: **0.361525 s** on 280 test rows.
- Pace random-forest MAE: **0.412548 s**, on the same rows; worse than the baseline and displayed honestly.
- DNA accuracy: **85%** on 60 test laps.
- Feature groups: ghost_features (1,444 rows), pace_features (1,196), dna_features (275), strategy_features (1,348).

Full analytical metrics are in `qa/metrics.json`. Timing is environment-dependent, not a performance guarantee.

## Visual inspection

Actual rendered screenshots are in `qa/`:

- `01-overview.png` through `08-mobile-ghost.png`: rerun coverage of the four experiences, pipeline and mobile layout.
- `09-ghost-3d.png`: default chase view at the start line.
- `10-ghost-orbit.png`: circuit orbit camera.
- `11-ghost-chase-b.png`: following the second car.
- `12-ghost-immersive.png`: desktop theatre viewport with instruments.
- `13-ghost-mobile.png`: responsive phone-sized dashboard.
- `14-ghost-mobile-immersive.png`: mobile theatre viewport.
- `15-ghost-2d.png`: retained 2D map.
- `16-dashboard-home.png`–`24-dashboard-timing-mobile.png`: current dashboard home, timing, standings, race pace, stints, Track DNA, light theme, mobile home and mobile timing.
- `25-connections-ready.png`, `26-connections-mobile.png`: production/default readiness with no credentials.
- `27-connections-offline-fixture.png`: explicitly labeled offline fixture operation evidence; **not a live-account screenshot**.
- `28-fleet-ghosts.png`–`33-fleet-mobile-immersive.png`: actual four-car comparison, 20-car overview/chase, responsive mobile, 2D map and immersive UI.

These are screenshots of the functioning application, not generated concept art. Theatre captures show the visible viewport, not the underlying off-screen page.

## Source-package verification

The version-2.2 archive includes all 19 dashboard/connection pages, all three curated data scopes, schema adapters, compiled dashboard/Three.js assets, test suites, cloud and multi-car setup guides, private configuration initializer, provider adapters and third-party licenses. `qa/package-smoke.json` records ZIP integrity, exclusions, archive hashes, fresh-extraction startup/API checks, local compiled assets, on-demand ZIP generation and live-preview/download verification. Fresh extraction uses the installed Python dependencies; it does not claim a clean-OS installation test.

## Not established by these tests

- A physically accurate car, tyre-force model, drivable racing game, surveyed Zandvoort elevation/banking or official engine recording.
- A frame-rate guarantee, physical mobile-device testing or equivalent behavior in Safari/Firefox; browser automation used Chromium.
- Successful connections to your Hopsworks project, native dataset permissions, provider storage/Flight/Kafka access or SDK/server compatibility. Those remain your post-credential acceptance step.
- Production readiness, multi-tenant security, rate limiting or public-service hardening. The demo operator authentication path is separately tested; that is not a production security certification.
- ML generalization beyond the original Dutch GP, or fitness for live prediction. Descriptive archive coverage across 46 events is independently tested, not evidence of cross-race model accuracy.
- Causal driver-style identification or optimal real-world pit strategies.
- Permission to submit a prebuilt repository under the event's rules.

Use the reproducibility commands in `README.md` to rerun the suites.
