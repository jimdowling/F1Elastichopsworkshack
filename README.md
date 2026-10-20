# F1Elastichopsworkshack — PITLANE on Hopsworks

An explorable 2023–2024 Formula 1 race workspace and four ML/3D experiments, running as a **Hopsworks app**. All data is read from the shared Hopsworks F1 feature groups; there is no bundled data and no SQLite.

## Architecture

```
 browser (React UI, web/)                    Hopsworks app pod (custom app, python app.py)
 ───────────────────────── relative URLs ──▶ FastAPI  /api/...  /health
                                               │
           Hopsworks Python client             │  fg.select(...).filter(...).read()
           (Hopsworks Query Service) ◀─────────┤  shared feature store: hopsworks_default_featurestore
                                               │  f1_races, f1_race_results, f1_laps, f1_stints, f1_car_telemetry, ...
           RonDB (project database) ◀──────────┘  app_pitlane_race_pace, app_pitlane_lab_features, app_pitlane_cache
```

- **Reads** go through the Hopsworks Python client, so `fg.read()` is served by the **Hopsworks Query Service** with the filter pushed down. Trino is not used. At startup the app loads the archive with 16 bounded reads (calendar, classifications, standings, pit stops, and race sessions for laps, stints, positions, weather and race control). This takes about 30 s. High-frequency `f1_car_telemetry` / `f1_car_location` (about 100M rows each) are read on demand for **one race session and an explicit set of drivers**.
- **App state** lives in RonDB tables in the project database, through the `MYSQL_*` variables Hopsworks injects into the app pod (`src/appdb.py`):
  - `app_pitlane_race_pace`: per-driver race-pace features computed by the dashboard. They are written and then read back.
  - `app_pitlane_lab_features`: the experiment feature tables (ghost/pace/dna/strategy/...) per race. They are written and read back before the models consume them.
  - `app_pitlane_cache`: derived per-race payloads (lab telemetry signatures, multi-car replay series), compressed.

  Creating these tables needs the app to be **started by a Data Owner**. Outside a Hopsworks pod (no `MYSQL_HOST`) the same interface is kept in process memory.
- **The experiments are fitted per race.** The race is the season/GP chosen in the dashboard scope bar. The lab drivers are the top four finishers with enough green-flag laps and telemetry. Chronological splits are fractions of race distance, so the 72-lap Dutch GP keeps the original 43/57 cut-offs and reproduces the original snapshot exactly: 1,425 laps, 275 telemetry signatures and the same model metrics.

| Feature group(s) | Used for |
|---|---|
| `f1_races`, `f1_circuits` | calendar, venues |
| `f1_race_results`, `f1_qualifying_results`, `f1_sprint_results`, `f1_drivers`, `f1_constructors` | classifications, standings, profiles, head-to-head |
| `f1_driver_standings`, `f1_constructor_standings` | official final standings (tie-break check) |
| `f1_pit_stops` | pit-lane analysis, pit-in flags |
| `f1_sessions` | Race/Qualifying session keys (matched to rounds by date) |
| `f1_laps`, `f1_stints`, `f1_track_positions`, `f1_weather`, `f1_race_control` | timing replay, race pace, tyres, weather, race control, lab inputs |
| `f1_session_drivers` | team colours for the lab |
| `f1_car_telemetry`, `f1_car_location` | ghost laps, Driver DNA signatures, multi-car replay |

### Important files

- `app.py`: FastAPI app, lab endpoints (`season`/`round` on every lab call), static UI, `/health`.
- `src/hopsdata.py`: Query Service reads and the archive builder.
- `src/appdb.py`: RonDB app tables, with an in-memory fallback.
- `src/dashboard.py`, `src/dashboard_api.py`: historical dashboard.
- `src/engine.py`: the four experiments, per race.
- `src/race_replay.py`: shared-clock multi-car replay, per race.
- `frontend/`: React/Vite source. `web/` holds the committed build the app serves.
- `tests/test_hopsworks.py`: integration tests against the live feature groups.

## Deploy as a Hopsworks app

```bash
hops env clone pitlane-app-env --from python-agent-pipeline
hops env install pitlane-app-env -f app-requirements.txt
hops app create pitlane --path /Projects/<project>/Users/<user>/F1Elastichopsworkshack/app.py \
  --app-kind custom --entrypoint-command "python app.py" --app-port 8080 \
  --readiness-probe-path /health --environment pitlane-app-env --memory 4096 --start
```

Database access is on by default (`MYSQL_*` injected). Every UI URL is relative, so the app works under the proxy mount `/hopsworks-api/pythonapp/<project>/<app>/`. To point at a different shared feature store, set `F1_FEATURE_STORE` (default `hopsworks_default_featurestore`).

After a code change: `hops app redeploy pitlane`. If the project CPU quota can't fit a second pod during the rolling update, run `hops app stop pitlane && hops app start pitlane` instead.

## Develop

```bash
cd frontend && npm ci && npm run build     # writes ../web
python app.py                              # inside a Hopsworks terminal; serves on $APP_PORT or 8000
python -m pytest -q tests/test_hopsworks.py
```

In a Hopsworks terminal `hopsworks.login()` needs no host or API key. Without `MYSQL_*` the app tables are kept in memory, which is fine for development.

## What you can explore

**18 dashboard views:** home, historical timing, calendar, results, driver/constructor standings, drivers, teams, driver statistics, head to head, consistency, race pace, pit-lane analysis, tyres/stints, weather, race control, Track DNA and the data workbench.

**Four experiments, for any 2023–2024 GP:**

1. **Ghost Lap**: 3D telemetry replay of the lab drivers' fastest clean laps, plus a synchronized full-field race replay.
2. **Pitwall Sandbox**: one-stop counterfactual with pit-lap, compound, degradation and pit-loss controls.
3. **Pace Detective**: past-only features, rolling baseline, fitted random forest, chronological evaluation and anomalies.
4. **Driver DNA**: blind driver–car identification from held-out telemetry laps.

## What is real, and what is modeled?

| Layer | Status |
|---|---|
| Archive | Real observations from the shared feature groups: 46 events, 92 Race/Qualifying sessions, 2,078 classifications including Sprint, 51,108 Race laps |
| Timing | Recorded as-of ranks and lap evidence on a common session clock; archive replay, not live |
| Telemetry | Read per race and per driver on demand; ghost traces interpolated to 361 samples; replay binned to 0.5 s XY / 1 s telemetry |
| Pace / DNA models | Fitted and evaluated on one race at a time; no cross-race generalization claim |
| Pitwall outcomes | Modeled counterfactuals, not observed or causally validated alternatives |
| Road, cars, scenery, steering and audio | Illustrative/procedural, driven by recorded telemetry |

`f1_laps` has no track status. The experiments derive green-flag eligibility from `f1_race_control` flags, and the dashboard leaves `track_status` null. Missing channels, incomplete stints and insufficient evidence stay visible rather than being invented.

The other documents (`DATA-NOTICE.md`, `DEMO-GUIDE.md`, `QA-REPORT.md`, `docs/`, `qa/`) describe the earlier standalone v2.2 build with bundled public data and local SQLite. Keep them for history only.
