# Data provenance, transformations, and limitations

## Version 2.2 / separate shared-clock replay archive

A third bundled data scope now exists under `data/replay/`: the **2024 Dutch GP field**, using public OpenF1 session **9582** location/car-data observations. It is separate from the original four-lap/model snapshot and the two-season dashboard archive.

- **20 drivers**, **218,520 retained XY records**, **110,300 retained car-telemetry records**; **40 raw responses / 841,220 raw source records**. All response records were checked against the requested session and driver. No synthetic race observations were added.
- Actual source timestamps are retained: one observed location record per 0.5-second bin and one car-data record per one-second bin. The stored arrays are not a synthetic uniform timeline.
- The shared provider clock starts at 2024-08-25 13:00:00 UTC. Common retained coverage is approximately 189.315–5706.816 seconds from that origin, not a certified lights-out race clock.
- The manifest retains source URLs/raw-response digests and **20 curated-file hashes**. Raw caches are excluded from the project archive.
- Playback interpolates only short valid brackets; positions outside coverage, across >2.5-second gaps or implausible >150 m/s approximate-world jumps are hidden. Gaps never borrow the independent ghost trajectories.
- The raw archive retains **one throttle=104 and five brake=104** source values, with quality counts. Invalid percentages are unavailable in instruments/interpolation/plots rather than silently clipped. Raw values are not rewritten.
- Rank is an as-of timing-feed observation, then final classification after completion. XY separation is derived straight-line distance, not an official race interval. Lap/tyre labels use consecutive recorded lap starts to resolve small endpoint overlaps; raw durations remain unchanged.
- XY is mapped into an illustrative 3D world; source Z is retained but elevation is flattened. Cars, road width, scenery and engine sound are not surveyed/manufacturer-authenticated physical models.

See `docs/MULTI-CAR-REPLAY.md`. The original 1,444-sample telemetry schema export and four ML/replay feature groups remain scoped to the independent comparison laps; the new field replay has dedicated `/api/replay/*` endpoints. No private event/Hopsworks account is implied or required by this public replay.

## Configurable native connections in version 2.1

No event/user account was accessed during this build. The delivered runtime can now query the configured Hopsworks event tables (`f1_*` feature groups) and consume selected-race pace features from verified Hopsworks batches after explicit configuration. These are optional, operator-protected paths; the default remains the bundled public archive.

Native Race/Qualifying results, laps, weather and bounded telemetry are distinct from labeled public supplements (venue/driver metadata, Sprint, timing details, speed traps, pit transit and control messages). Native lap timestamps are not invented: historical timing stays on its public reference. Native weather's absent absolute UTC date stays absent. The original four experiments are not silently retrained or relabeled. See `docs/CLOUD-SETUP.md` for exact scope, credentials, permissions and retention/security boundaries.

Offline integration fixtures deliberately alter a few values to prove the app uses the selected source. They exist only in test code/in-memory QA, are visibly marked in the fixture UI, and are **not** part of either real imported dataset. No new synthetic race observations were added to `data/`.

## Two independent bundled data scopes

### Public 2023–2024 dashboard archive

`data/dashboard/manifest.json` records exact source URLs, fetch time, per-event coverage and SHA-256 digests for **93 normalized files**. The snapshot contains **46 events**, **92 Race/Qualifying session records**, **2,078 classifications** (1,838 Race/Qualifying + 240 supplementary Sprint), **51,108 Race laps**, **2,659 stints**, **22,892 position changes**, **1,737 pit-lane visits**, **4,070 race-control messages**, and **11,238 weather samples** (7,309 Race + 3,929 Qualifying). No synthetic race observations were imported.

- **Jolpica:** calendars, classifications, final standings and per-round pit visits — https://api.jolpi.ca/ergast/f1/
- **OpenF1:** public session metadata, Race laps/stints/positions/control and Race/Qualifying weather — https://api.openf1.org/v1/
- The reference dashboard informed functionality only. Its code, graphics, opaque scores and 2026 results are not bundled.

The event cluster was not accessed. Its published counts and the public archive's actual counts are presented separately. The supplied schema is mapped in [docs/DASHBOARD-GUIDE.md](docs/DASHBOARD-GUIDE.md), with units, keys, derivations, unsupported fields and export contracts.

**Known quality boundaries:** 204 lap rows lack duration/raw calculated end time; 154 have unknown compound; 23 stints have incomplete boundaries. Qualifying lap samples and full-field two-season car/location telemetry are absent. Monaco 2024 lacks evidence for inferred length/similarity. Missing channels and unsupported selections are not filled with plausible values.

**Timing:** sector times and lap durations are exported in milliseconds. Position is an as-of join, not native FastF1 lap position; native `track_status` stays null. The historical replay reconciles missing or >0.25 s-discrepant endpoints with the next consecutive recorded lap start, quarantines backwards endpoints and holds its clock when no completion is available. This addresses restart inconsistencies such as Japan 2024 while preserving raw archive values. Its monotonic observed-reference clock is **not certified lights-out elapsed time**. The grid is static; the final frame uses official classification. Sector comparison colors are not incident flags.

**Other interpretations:** pit durations measure lane transit, not stationary service. Rainfall is a boolean flag, not precipitation intensity. Weather includes the provider's pre/post-session windows. Track DNA is descriptive timing-derived similarity, not surveyed engineering data. Retrospective pace filtering is not guaranteed green-flag or fuel/tyre-adjusted running. Crash costs, technical upgrades and component allocations are not supplied; they were replaced with data-backed analyses rather than invented.

The dashboard's five-index telemetry export contains only **1,444 interpolated samples from four Dutch GP laps**, marked `is_interpolated=true`, with unsupported DRS/Z null. It is not the guide's published 57,353,359 native telemetry rows. No two-season ML model was trained.

### Original Dutch GP experiment snapshot

The following original-snapshot documentation remains applicable. It has **1,425 lap rows**, while the separately imported dashboard Dutch GP archive has **1,426**. Neither snapshot is silently rewritten to match the other. Changing archive selectors does not change the original 3D/ML experiment's data scope.

## Included observations

The curated snapshot is the **2024 Dutch Grand Prix race**, OpenF1 session **9582**, held on **25 August 2024** at Zandvoort.

- **1,425 lap rows** across 20 drivers.
- **275 eligible telemetry laps** for NOR, VER, LEC, and PIA.
- Four selected fastest clean race laps, each resampled to 361 display points.
- Real stint and pit records, plus final classification from Jolpica.
- **Zero synthetic race observations.**

The exact fetch timestamp, requested URLs, counts, and SHA-256 digests are in `data/manifest.json` and exposed by the app's **Data & provenance** dialog.

Sources:

- OpenF1 documentation: https://openf1.org/
- Session metadata: https://api.openf1.org/v1/sessions?session_key=9582
- Final results: https://api.jolpi.ca/ergast/f1/2024/15/results.json

The public F1 timing host used by FastF1 returned HTTP 403 during preparation. Rather than invent observations or imply successful access to the event cluster, this build uses public **OpenF1** data. It does not contain or require event credentials.

## Derived fields are not original provider measurements

- `tyre_life`: computed from the actual stint start, actual starting tyre age, and lap number.
- `is_pit_in_lap`: matched to the real pit records.
- `track_status`: a conservative derived eligibility code based on overlapping race-control flag intervals. It is **not** a claim to have obtained FastF1's `TrackStatus` field.
- `is_accurate`: our positive-duration / sector-sum consistency check. It is **not** FastF1's `IsAccurate` field.
- Per-lap aggregate telemetry features: computed from actual car samples.
- Rolling pace features: computed only from earlier eligible laps, resetting at gaps and pit/stint/compound boundaries.

Provider observations and these explicitly derived fields are distinct from fabricated or synthetic race records.

## Telemetry visualization

Measured speed is integrated over time to approximate distance. Each lap is then normalized to 0–100%. Car signals and position measurements are interpolated for display; actual lap-time endpoints are retained.

This is not surveying-grade spatial alignment. Different racing lines, sample timing, missing samples, and interpolation can affect fine-grained corner comparisons. Selected fastest laps also differ in tyre age, race phase, fuel, and traffic. They do not isolate driver ability.

## 3D geometry and engine audio

The 3D upgrade reuses the same four recorded 361-sample traces. **No new synthetic race measurements were added.**

- Position XY is centered, its Y axis becomes world −Z, and the selected reference lap's XY polyline is scaled to the nominal **4,259 m** circuit length. Open Catmull–Rom trajectories pass through the measured resampled points, preserving each driver's own time-to-position relationship and finish endpoint.
- The displayed asphalt is an illustrative **15 m-wide ribbon around a recorded racing line**, not surveyed track boundaries. Its elevation is flat. Dunes, curbs, barriers, stands, pits, signs and start/finish decoration are procedural and not a verified reconstruction of the venue.
- Open-wheel bodies, numbers and ghost colors are procedural, not licensed team CAD or official liveries. Wheel spin uses measured speed and an illustrative wheel radius; steering and small body lean are derived from trajectory curvature. There are no tyre forces, collisions, driver inputs or vehicle-dynamics validation. Independent historical ghosts can overlap.
- The engine sound is **original procedural synthesis**, not a recorded or manufacturer-calibrated F1 engine. Recorded RPM sets combustion/body oscillator frequencies, throttle shapes loudness/filtering, and gear changes trigger short pitch/envelope changes and noise transients. Background/foreground mixing is a presentation choice, not measured acoustics. It is neither narration nor music.
- Sound requires a user click, defaults to 35% volume, is limited, and fades to silence on pause, finish, mute, zero volume or page hiding. Leaving Ghost Lap closes the audio context.

The source code and QA report distinguish measured channels, interpolated visualization, designed sound and illustrative geometry. “Zero synthetic race observations” does **not** mean the graphics or sound are real footage/recordings.

## Statistical scope

**Pace:** one-race chronological split at lap 43/57. Features exclude same-lap sector times, final results, and future pace. The eligible clean-lap set is retrospective: its non-pit/clear-track status is known after lap completion. Therefore its error is not unrestricted live forecasting accuracy.

**DNA:** 12 telemetry-only summary features, four driver–car classes, whole-lap chronological holdout. The car, tyre condition, DRS, traffic, and race evolution confound identity and style. The 85% accuracy is a measured result on just 60 later laps, not a universal driver-recognition claim. Forest vote shares are not calibrated probabilities.

**Pitwall:** all eligible race laps calibrate a simplified additive pace model. Some coefficients are bounded to keep the demonstration numerically sensible. Counterfactual headline schedules and finish gaps are anchored to Jolpica's classified elapsed race times. Per-lap cumulative fields sum the OpenF1 lap durations; those sums can differ slightly from classified totals because of timing alignment. Modeled deltas are not affected by that difference. Rival behavior, traffic interactions, safety cars, and causal identification are absent. Outputs are hypothetical model results, not alternative observed races or validated optimal strategies. Out-of-range tyre-age extrapolation and same-compound legality issues are flagged.

## Infrastructure boundary

The default application and original four lab pipelines use SQLite. Version 2.1 adds optional, explicit dashboard Hopsworks modes: the app can consume native reads and verified remote pace-feature batches, not only publish data. Account validation has not happened during this build. Public supplements, private native values and the original experiments remain labeled separately. The legacy original-lab publisher does not automatically switch those experiments to cloud execution.

## Use and attribution

This is an independent exploratory demo, not an official Formula 1, team, driver, OpenF1, or Hopsworks product. Public availability does not establish unrestricted rights to redistribute or commercially exploit a data feed. Review the source providers' current terms and applicable data/trademark rights before broader redistribution or commercial deployment. No ownership or new license over third-party race data is asserted here.
