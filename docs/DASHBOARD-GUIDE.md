# Pitlane 2.2 — historical dashboard & hackathon adaptation

The default workspace is an independent **2023–2024 historical F1 dashboard**, with the four original Dutch-GP experiments still available. The information architecture was informed by [Formula 1 Dashboard](https://app.formula1dashboard.com/); no proprietary code, assets, opaque scores, or 2026 race data were copied.

## Version 2.1 connection layer

This guide's archive counts/methods describe the **bundled public-data mode**. The added **Connections** page (19th dashboard/control view) can configure native Elastic queries and actual Hopsworks pace read-back without application-code changes for the documented event schema. Use [CLOUD-SETUP.md](CLOUD-SETUP.md) for secure setup, provider checks, mode switching, permissions, limits and the hybrid-source boundary. No live accounts were validated during delivery.

Native schema exports preserve native values, including Qualifying laps when available. Native telemetry requires a driver/lap bound. Public timing replay stays separate because native lap endpoints are absent; weather UTC values are not invented. Original experiments remain local and separately scoped.

## 1. Start exploring

Open the app's live preview, or run the downloaded project as described in `README.md`.

1. Start on **Dashboard**, initially **2024 · R15 · Dutch GP**. The top selectors control the historical season and Grand Prix. Championship pages show the snapshot **through that round**; session pages analyze that event. **Season end** jumps to the final round.
2. Open **Driver standings**, sort the table, and switch between evolution and round-by-round points. Explore 2023 and 2024 without conflating their teams or driver numbers.
3. Open **Historical timing**, play or scrub the lap control, choose a driver watchlist, and open a driver's lap evidence. This is a retrospective timing desk, not a live feed or full-field 3D simulation.
4. Open **Race pace**. Select drivers, change the pit/outlier filter, and compare lap times, distributions, positions, speed traps and the fastest 20 laps. Inspect the persisted feature read-back beneath the charts.
5. Explore **Tyres & stints**, **Pit-lane analysis**, **Weather & conditions**, and **Race control** for the context behind an unusual lap.
6. Open **Coverage & schema** for exact loaded counts, quality gaps, schema alignment, feature methods, a copyable ES|QL template, and real JSON previews/downloads.
7. Use the **Experiments** navigation group for Ghost Lap, Pitwall Sandbox, Pace Detective and Driver DNA. Their explicit **2024 Dutch GP** scope is independent of the dashboard's season selection. Returning to the dashboard restores that selection.

Dark/light appearance, sidebar state, archive scope and relevant page controls are saved in the browser. The mobile sidebar is a drawer; wide evidence tables scroll inside their cards rather than widening the whole document. Data failures expose a retry action.

## 2. Reference-to-build feature map

| Reference area | Implemented adaptation | Deliberate boundary |
|---|---|---|
| Home | Event winner, podium, fastest lap, championship snapshot/evolution, weather, control notes and next historical rounds | Historical, never presented as upcoming 2026 events |
| Live timing | Playable historical timing, as-of order, completed-lap evidence, sectors, tyres, weather, control context, watchlist and driver drill-down | No live-feed claim, radio recordings or invented real-time gaps |
| Schedule | Searchable season calendar, event dates, venues, session metadata and event navigation | Public historical calendar; not a current-season schedule |
| Results | Race, Qualifying and available Sprint classifications, grid/finish changes, timing details and CSV | Sprint is supplementary public data, outside the advertised event Race/Qualifying scope |
| Driver standings | Round cutoff, points/gaps, rank movement, wins, evolution and round matrix | Race + Sprint points; final totals checked against Jolpica standings |
| Constructor standings | Equivalent constructor views and actual per-event team point attribution | A driver changing teams does not transfer earlier points to the new team |
| Drivers | Searchable driver directory, profiles, results, points and prior-season comparison | Actual historical entries, not a fabricated current grid |
| Teams | Seasonal lineups, driver contributions and constructor results | Original schematic visuals; no invented chassis specifications or official liveries |
| Driver statistics | Individual profile plus sortable/searchable season-wide driver and constructor comparisons; CSV exports | Metrics describe the selected season through the selected round |
| Head to head | Any two entered drivers; Race/Qualifying/Sprint records, points, finish/grid deltas and comparable qualifying gaps | Raw metrics replace unexplained proprietary scores |
| Consistency | Finishing distributions, spread and a DNF inclusion control | Classification is not an isolated measure of driver skill |
| Race pace | Multi-driver filtering, lap evolution, distributions, recorded positions, speed traps, fastest 20 and feature evidence | Retrospective observations, not green-flag/fuel/tyre-adjusted estimates |
| Pit stops | Event and season lane-visit tables, distributions, timeline and driver/team comparisons | Pit-lane transit duration, **not stationary crew service time**, DHL scores or video footage |
| Technical updates | **Race control**: searchable/filterable official-message context and chronology | No unsupported component-development narrative |
| Used elements / allocations | **Tyres & stints**: actual compound and tyre-life observations, timelines and compound pace | No fabricated engine/gearbox allocation counts |
| Destructor / crash costs | **Weather & conditions**: Race/Qualifying observations, trends and rainfall flags | No speculative damage-cost or blame rankings |
| Track DNA | Inferred lap length, timing/pit/retirement characteristics and disclosed similarity calculation | Not surveyed geometry, downforce, tyre stress or engineering ratings |
| Preferences | Original Pitlane styling, light/dark theme, collapsible navigation, mobile layouts and saved selections | English UI; reference translations, feedback service and accounts were not replicated |
| Additional workbench | Coverage, five-index schema mapping, CSV/JSON, local feature generation/read-back and query template | Local SQLite; no implied event-cluster or cloud connection |

## 3. What is actually included?

Snapshot imported on **2026-10-18**, with exact timestamps, requested source URLs, coverage and hashes in `data/dashboard/manifest.json`.

| Archive layer | Included |
|---|---:|
| Grand Prix events | **46** — 22 in 2023, 24 in 2024 |
| Race/Qualifying session records | **92** |
| Classifications, including Sprint | **2,078** |
| Race + Qualifying classifications only | **1,838** |
| Supplementary Sprint classifications | **240** |
| Race lap rows | **51,108** |
| Tyre stint records | **2,659** |
| Position-change observations | **22,892** |
| Pit-lane visits | **1,737** |
| Race-control messages | **4,070** |
| Weather samples | **11,238** — 7,309 Race + 3,929 Qualifying |
| SHA-256-verified archive files | **93**, excluding the manifest itself |
| Schema-aligned high-frequency telemetry export | **1,444 interpolated display samples from four Dutch GP laps** |
| Synthetic imported race observations | **0** |

**Sources:** Jolpica supplies calendars, classifications, pit-lane timings and standings; OpenF1 supplies session metadata, race laps, stints, position changes, weather and race control. Runtime requests are served locally from the included archive, not from those providers.

The original lab snapshot remains separate: **1,425 Dutch GP laps**, 275 eligible four-driver telemetry laps for Driver DNA, and four selected 361-point replay traces. The expanded archive has **1,426 Dutch GP lap rows**. These are separate imports/curation snapshots; neither is silently overwritten to force equality. The dashboard does not pretend that the original models were retrained on two seasons.

### Missingness is visible

- **204** race lap rows lack duration and raw calculated end time.
- **154** lap rows have unknown compound.
- **23** stint records lack a start or end boundary; incomplete bands are not invented.
- The 2024 Monaco source lacks the fastest-lap average-speed evidence needed for the length estimate. Its similarity panel reports insufficient evidence instead of assigning a fictitious profile.
- Qualifying classifications and weather are included; **Qualifying lap samples are not loaded**.
- Full-field car/location telemetry for all events is **not** included. Unsupported schema selections return an empty record array with scope notes.

## 4. Alignment with the published hackathon schema

The [organizer's participant guide](https://github.com/afzaal-ahmad-zeeshan/2026-10-19-ElasticxHopsworks-Hackathon-Amsterdam/blob/main/docs/PARTICIPANT-GUIDE.md) advertises the following counts. They are **published counts, not independently queried cloud counts**:

| Event index | Published event records | This build's public equivalent |
|---|---:|---|
| `f1-sessions` | 93 | 92 Race/Qualifying session metadata rows |
| `f1-results` | 1,858 | 1,838 Race/Qualifying rows; 240 additional Sprint rows in the dashboard/CSV layer |
| `f1-laps` | 67,110 | 51,108 Race laps; Qualifying laps absent |
| `f1-weather` | 11,391 | 11,238 Race/Qualifying observations |
| `f1-telemetry` | 57,353,359 | Four interpolated replay traces / 1,444 samples, **not** the full event telemetry |

Provider windows, data definitions and coverage differ. Schema alignment does not establish row-for-row equivalence to native FastF1/event data.

### Common keys and units

Every schema-export record includes `season`, `round_number`, `event_name`, `session_name`. Driver-specific records add `driver_code` and `team_name`.

| Index | Fields and mapping |
|---|---|
| Sessions | `country`, `location`, `session_date` from matched public calendar/OpenF1 session metadata |
| Results | `driver_number`, `full_name`, `position`, `points`, `grid_position`, `status`, `fastest_lap_ms`; historical result numbers, not today's permanent numbers |
| Laps | `lap_number`, `lap_duration_ms`, `duration_sector_1`, `duration_sector_2`, `duration_sector_3` are integer **milliseconds**; compound/stint joins supply `compound` and `tyre_life`; OpenF1 provides pit-out flags and Jolpica pit matching derives pit-in flags |
| Lap position/status | `position` is the last recorded position as of the calculated lap endpoint, not a native FastF1 lap-position field. `track_status` remains **null**; timing-sector comparison colors are not incident flags |
| Weather | `session_time_s`, temperatures, humidity, pressure and wind speed are numeric; `wind_direction` is integer; `rainfall` is boolean or null, not millimetres of precipitation |
| Telemetry | `session_time_s` is numeric; speed/RPM/throttle/gear are integer schema values; `brake` is boolean; `x/y` are interpolated coordinates; unsupported `drs/z` are **null**; `is_interpolated=true` explicitly identifies the display-derived subset |

Relative timestamps use the OpenF1 session's `date_start`, not a fabricated lights-out timestamp. Pre-session observations can legitimately have negative `session_time_s`. Pit-stop `source_local_time` is retained without claiming a verified timezone conversion.

### Export contract

```text
GET /api/dashboard/schema/{index}.json?season=2024&round=15&session=Race
```

`index` is one of the five names above. `session` is `Race` or `Qualifying`. The response is an envelope:

```json
{
  "index": "f1-laps",
  "records": [],
  "record_count": 0,
  "provenance": "...",
  "notes": ["..."]
}
```

That example illustrates the shape, **not** the Dutch GP lap count. The real 2024 R15 Race export contains 1 session, 20 results, 1,426 laps, 153 weather observations or 1,444 telemetry samples depending on the selected index; Qualifying weather contains 79 samples. The UI previews actual records and offers the same JSON for download.

This envelope is **not** an Elasticsearch bulk-ingest body. Ingest the `records` explicitly with appropriate IDs/mappings in your own writable destination; preserve the provenance and notes separately. A lap key should include season, round, session, driver and lap; telemetry needs timestamp/sample identity as well.

## 5. Historical timing methodology

The timing desk uses a **single common timestamp per selected lap**, not each driver's own end-of-lap row assembled into a misleading simultaneous view.

1. Build per-driver lap sequences. Prefer each raw calculated endpoint.
2. If that endpoint is missing, or differs by **more than 0.25 seconds** from the **next consecutive recorded lap start**, use that next start as a disclosed endpoint estimate. Never jump across an unrecorded lap. Raw archived lap durations and timestamps remain unchanged.
3. Quarantine endpoints that still run backwards within a driver's chronological sequence.
4. Choose a monotonic common cutoff for the selected lap. If no usable completion exists, **hold the preceding data clock** and disclose the gap rather than invent a timestamp.
5. Include only observed completions at or before the cutoff **and at or before the selected lap**. Use recorded position changes as of that same time; unknown ranks remain unknown. The grid frame is a static starting-grid view with zero completed laps.
6. Use the official classification and completed-lap counts for the explicitly labeled final frame. This is a final-results mode, not an inferred ranking.

The imported **2024 Japan restart** exposes inconsistent start/duration relationships. The reconciliation above prevents the lap-1-to-lap-2 clock reversal without pretending to recover a certified official race clock. The displayed clock is relative to the earliest observed lap-start reference, **not guaranteed lights-out elapsed time**. A position sample is a recorded observation, not a continuously measured car location; completion-time comparisons are not a live timing-gap feed.

The model suite audits all **2,739 intermediate lap frames across all 46 races**, plus grid/final frames and synthetic edge-case fixtures. **723 intermediate frames** use at least one derived endpoint. No real selected frame in this snapshot needed the missing-frame hold; dedicated fixtures test that behavior. Synthetic test fixtures are not imported race data.

## 6. Analytical definitions worth knowing

- **Championship:** sum Race and Sprint points through the chosen round. Credit points to the team represented at that event. Final totals are independently checked against Jolpica final standings. Bearman's 2024 points are split correctly: Ferrari 6, Haas 1. Lapped finishers (`Lapped` / `+N Lap(s)`) count as finishers, not retirements.
- **Qualifying comparisons:** use the last shared Q segment when both drivers have times there. Race-grid pole and qualifying P1 are distinct because of penalties/other grid changes.
- **Pace:** the default filter excludes lap 1, pit-in/out laps and durations above **107% of each driver's non-pit median**. Its adjustable threshold is retrospective. It does not guarantee green-flag running or remove fuel, tyre, traffic or weather effects. Charts connect available observations; they do not reconstruct missing laps.
- **Pace features:** persist per-driver race summaries (including sample count, median, quartiles/spread and delta) to `race_pace_features`, then return the actual SQLite read-back. Configuration identity includes the exact filter values. The CSV feature export uses the disclosed **default filter**, not an undocumented current chart threshold.
- **Pit-lane comparisons:** source records measure lane transit. Summary comparisons use the disclosed 10–90 s subset to avoid obvious interruptions/invalid values; raw tables retain the visits. Circuit lane lengths differ. Do not interpret these as stationary crew performance.
- **Weather:** session charts/averages include supplied pre/post-race samples. Rainfall is a flag, not rain intensity. Replay weather is the last available sample by the common clock; absent earlier samples stay absent.
- **Track DNA:** infer lap length from reported fastest-lap average speed × duration. Similarity uses complete-case standardized Euclidean distance over inferred length, median pace, stops per entry and retirement rate. No missing dimensions are silently imputed and no engineering/causal interpretation is warranted.
- **Original ML:** Pace Detective and Driver DNA are unchanged one-race experiments, with measured holdout results in `README.md` and `qa/metrics.json`. The dashboard's descriptive summaries are not a newly trained two-season model.

## 7. API and local architecture

Browser requests are same-origin, and all compiled fonts/scripts are bundled. No cloud call is required in default/local mode. Explicit cloud modes make server-side provider requests using private environment credentials.

| Endpoint | Scope |
|---|---|
| `/api/dashboard/catalog` | Seasons, events and archive metadata |
| `/api/dashboard/season` | `season`, `round` cutoff; standings, profiles/statistics and matrices |
| `/api/dashboard/race` | `season`, `round`, `clean`, `cutoff`; race observations and stored pace-feature read-back |
| `/api/dashboard/driver` | Selected `driver`, season and cutoff |
| `/api/dashboard/compare` | Drivers `a`, `b`, season and cutoff |
| `/api/dashboard/pits` | Season/cutoff pit-lane analysis |
| `/api/dashboard/tracks` | Season-level timing DNA |
| `/api/dashboard/weather` | Season, round and Race/Qualifying session |
| `/api/dashboard/coverage` | Coverage of the active provider; no implicit whole-season native download |
| `/api/dashboard/timing` | Always the separate public historical-timing reference |
| `/api/connections/*` | Credential presence, authenticated tests/jobs/modes, bounded telemetry and setup guide |
| `/api/dashboard/export/{kind}.csv` | Ten bounded export kinds below |
| `/api/dashboard/schema/{index}.json` | Five public-equivalent index envelopes |

CSV kinds: `results`, `laps`, `weather`, `pits`, `stints`, `race-control`, `features`, `sessions`, `driver-stats`, `constructor-stats`. Statistics exports are **season-through-round** and have corresponding filenames; event exports name the selected event/session. CSV cells are guarded against spreadsheet-formula injection. Invalid years, rounds, drivers and nonfinite/out-of-range cutoff values are rejected.

`src/dashboard.py` loads normalized classifications into `dashboard_results` and generates/read-backs `race_pace_features`. The disposable database is `.cache/dashboard-runtime.sqlite`; deleting it is safe while the server is stopped. The router serializes access to the shared SQLite connection. The original engine/database and all original APIs remain separate and intact.

The public-mode workbench offers a copyable **ES|QL template** and genuine selected-provider feature reads/building. It does not execute arbitrary SQL/ES|QL. Version 2.1 Connections uses fixed, bounded read-only Elastic queries and an explicit Hopsworks batch workflow. The older optional cloud publisher still applies only to original-lab feature groups; it is distinct from the new dashboard runtime.

## 8. Taking the idea to the hackathon

1. Confirm the event's rule about code written on the day. This prebuild is exploratory and **not certified submission-compliant**.
2. Connect to the organizer's actual data using their supplied connection instructions/permissions. Do not write into source indices or assume the published record counts have been verified here.
3. Configure the included native adapter and compare counts, units, nulls and timestamp semantics on a small known session before scaling.
4. Choose one bounded story: for example, retrieve Dutch GP laps/weather/race-control context with Elastic, materialize a genuine Hopsworks pace feature group, then explain a lap in the existing UI concept.
5. Use a team-owned writable destination and explicit feature keys. Verify write **and read-back** before claiming a cloud feature store. Do not publish secrets or imply that local SQLite proves cloud integration.
6. Keep the one-race ML evaluation separate from descriptive two-season views. Larger telemetry availability is an opportunity for a new experiment, not evidence of generalization.

The event's published full telemetry corpus was not downloaded. No event credentials were used and no Elastic/Hopsworks account writes occurred during this expansion.

## Version 2.2 / Ghost Lap expansion

The dashboard routes and cloud modes remain as documented. Ghost Lap now offers four-car independent comparison, a separate synchronized 20-driver public Dutch GP replay, and the preserved two-car detail. See [MULTI-CAR-REPLAY.md](MULTI-CAR-REPLAY.md). The new 218,520-position / 110,300-telemetry archive does not change the original four-lap schema export, retrain the original models or imply full-field replay at every event. Native cloud modes still have their own explicit source/feature boundaries.
