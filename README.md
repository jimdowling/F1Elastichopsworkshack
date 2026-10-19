# F1Elastichopsworkshack — PITLANE

[Live demo](https://fihackdemo.kiranreddy.nl) · [Static GitHub Pages overview](https://knarayanareddy.github.io/F1Elastichopsworkshack/) · [Workflow slide](./docs/presentation/Elastic-Hopsworks-Workflow.pptx)

> The public demo uses a temporary Cloudflare Tunnel to the FastAPI server on the demo Mac; it is available only while that host and tunnel are online. GitHub Pages itself is static. Provider credentials remain server-side and are not published.

---

**An explorable 2023–2024 race workspace, plus four fully working 2024 Dutch GP experiments.** Version 2.2 expands Ghost Lap with four-car comparison and a synchronized 20-car race replay, while retaining the configurable Elastic/Hopsworks runtime and original analytics.

## New / multi-car Ghost Lap

Open **Ghost Lap** for three tabs:

- **4-car ghosts:** NOR / VER / LEC / PIA, aligned lap starts, relative same-distance deltas, selectable cars and cameras.
- **20-car race replay:** real simultaneous Dutch GP positions on a common session clock—**218,520 recorded XY samples + 110,300 car-telemetry samples**, already bundled. No credentials required. Show/hide drivers, follow any car, orbit/click the 3D map, scrub, use lap presets, inspect actual rank/XY separation, switch to 2D, expand and enable synthesized engine audio.
- **Two-car detail:** the original A/B lap analysis remains intact.

These modes are deliberately different: independent ghost laps are **not actual race positions**; the race view uses shared-clock observations, not a guessed lap-progress field. XY separation is **not an official timing interval**. Road width/elevation/cars/scenery are illustrative. Full-field coverage is this **2024 Dutch GP**, not all 46 events.

See [docs/MULTI-CAR-REPLAY.md](docs/MULTI-CAR-REPLAY.md) for controls, provenance, gap/outlier handling and limits. Dashboard cloud configuration remains unchanged.

## Configure cloud access later — no application-code edits for the documented schema

The connection layer is implemented. It is **not live-account validated** yet; local mode still needs no credentials.

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-integrations.txt
python scripts/connect_cloud.py init
```

Open the generated private `.env`, add your Elastic source URL/key and Hopsworks host/project/key, choose your own feature prefix, and restart the server. In **Connections**, unlock with the separate generated operator token, test access, activate Elastic + local features, explicitly publish/read back one pace batch, then activate Hopsworks. Provider keys never go into the frontend.

**Full instructions:** [docs/CLOUD-SETUP.md](docs/CLOUD-SETUP.md). That guide covers exact environment variables, permissions, SDK compatibility, read/write boundaries, safe recovery, bounded native telemetry and CLI alternatives. Cloud mode powers the historical dashboard and its pace summaries; historical timing and the four original experiments retain their separately labeled public snapshots.

## Start here

- Open the **live preview** to explore **46 Grands Prix across 2023 and 2024**. The initial selection is 2024 · R15 · Dutch GP.
- Use the season/Grand Prix selectors for historical championship snapshots and event analysis; **Season end** selects the final round.
- Read [docs/DASHBOARD-GUIDE.md](docs/DASHBOARD-GUIDE.md) for the full reference-feature adaptation, loaded coverage, methods, APIs and hackathon-schema mapping.
- Read [DEMO-GUIDE.md](DEMO-GUIDE.md) for a short dashboard tour and the original four demo stories.
- Open **Coverage & schema** for archive counts, known gaps, exports, query templates and actual local feature read-back.
- The **Experiments** group preserves Ghost Lap, Pitwall Sandbox, Pace Detective and Driver DNA, all explicitly scoped to the original Dutch GP snapshot. **Compare ideas**, shortlisting and the ML pipeline still work.

## What you can explore

**19 dashboard/connection views:** home, historical timing, calendar, results, driver standings, constructor standings, drivers/profiles, teams, driver statistics, head to head, consistency, race pace, pit-lane analysis, tyres/stints, weather, race control, Track DNA, the data workbench and Connections. Tables are sortable, relevant views have search/filter/export controls, charts are interactive, and scope/theme/navigation preferences persist. Desktop and mobile layouts are included.

Unsupported reference modules were **replaced**, not filled with invented data: technical updates → race-control evidence; component allocations → tyre/stint evidence; crash costs → weather/conditions. Track DNA uses disclosed timing-derived features rather than fabricated engineering ratings. The design and implementation are original; the reference site informed functionality and information architecture only.

**Four retained experiments:**

1. **Ghost Lap** — real-lap 3D telemetry replay, chase/orbit cameras, synthesized RPM-driven sound, instruments, theatre mode and 2D fallback.
2. **Pitwall Sandbox** — working one-stop counterfactual with pit-lap, compound, tyre-age and pit-loss controls.
3. **Pace Detective** — past-only features, rolling baseline, fitted random forest, chronological evaluation and inspectable anomalies.
4. **Driver DNA** — blind driver–car identification with held-out laps, actual classifier votes and a confusion matrix.

## What is real, and what is modeled?

| Layer | Status |
|---|---|
| Historical archive | **Real public observations:** 46 events, 92 Race/Qualifying sessions, 2,078 classifications including Sprint |
| Session detail | **51,108 Race lap rows**, 11,238 weather observations, 2,659 stints, 1,737 pit-lane visits, 4,070 race-control messages |
| Providers | Jolpica + OpenF1; exact URLs and hashes in `data/dashboard/manifest.json` |
| Historical timing | Recorded as-of ranks and lap evidence on a reconciled common clock; **archive/replay, not live** |
| High-frequency dashboard export | **Four Dutch GP laps / 1,444 interpolated display samples**, not full-field two-season telemetry |
| Original experiment snapshot | Separate 1,425 Dutch GP laps and 275 eligible telemetry laps for four drivers; preserved, not relabeled by the archive selectors |
| Synthetic imported observations | **None**; interpolations, model outputs and procedural presentation are separately disclosed |
| Road, cars, scenery, steering and audio | **Illustrative/procedural**, driven by recorded telemetry; not surveyed geometry, physics simulation or official recordings |
| Pace / DNA models | Actually fitted and evaluated on the original **one-race** snapshot; no two-season generalization claim |
| Pitwall outcomes | **Modeled counterfactuals**, not observed or causally validated alternatives |
| Default runtime | Local JSON/SQLite, available without any credentials |
| Configurable cloud runtime | Read-only native Elastic results/laps/weather + labeled public supplements; dashboard pace summaries can consume **actual verified Hopsworks read-back** |
| Connection validation | Runtime adapters and UI are tested against offline HTTP/SDK fixtures; real Hopsworks SDK import/API shape checked; **your accounts still need live validation** |
| Original-lab publisher | Separate optional script for the original four feature groups; it does not switch the original experiments to cloud execution |

The event's advertised 57M telemetry rows have **not** been loaded. The **bundled archive** has Qualifying classifications/weather but no Qualifying lap samples. Once configured, native Qualifying laps are exportable from Elastic, and Connections can read/plot/export a bounded single driver/lap telemetry slice. Missing channels, incomplete stints and insufficient Track DNA evidence are visible rather than fabricated. The workbench documents these boundaries alongside the supplied schema.

Default/local mode makes no provider calls. Cloud mode is explicit, requires server-side credentials and protects native dashboard access with an operator session. Hopsworks writes require a server write flag plus explicit name confirmation (or the documented CLI --write flow); publishing alone does not switch modes. This is an independent exploratory prebuild, **not certified compliant with the event's event-day-code rule**.

## Run the downloaded project

The compiled frontend and the curated data are included. **Node is not required just to run the app.** Python 3.11+ is recommended; this build was tested on Python 3.13.

From the `pitlane-lab` directory:

```bash
python -m venv .venv
```

Activate it:

```bash
# macOS / Linux
source .venv/bin/activate
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

Then:

```bash
python -m pip install -r requirements.txt
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

On your own computer, open **http://localhost:8000**. In Arena, use the provided live-preview URL instead. The browser uses relative `/api/...` URLs; all fonts and assets are bundled locally.

The original lab startup verifies its data hashes, rebuilds its SQLite feature tables, fits the models and measures the metrics. In local mode, the dashboard lazily loads its classifications and builds race-pace features on demand; its full archive hash verification is covered by the validation suite. Optional provider reads are activated separately through Connections or environment modes. All three curated data scopes run without internet after dependencies are installed. This is a development/demo server, not a hardened public service.

## Ghost Lap / preserved two-car detail controls

1. Open **Ghost Lap → Two-car detail**. This preserved view starts **paused at the start of the lap**, with sound off and **1×** playback.
2. Click **Enable sound**, then **Play**. Volume starts at 35%; adjust it or mute at any time.
3. Use **Chase NOR / Chase VER** (or the currently selected drivers) to follow either car. The other car is translucent so overlapping historical laps remain distinguishable.
4. Select **Circuit orbit**: drag to rotate and scroll/pinch to zoom. Both cars keep following their own recorded lap timelines.
5. Click **Expand** for a theatre view with live speed, gear and RPM instruments. **Escape** or **Exit** returns to the dashboard.
6. Scrub with the transport slider or the telemetry chart. Switch replay speed between **1× / 4× / 8×**, swap drivers, or choose LEC/PIA.
7. **2D map** retains the original map and all replay/audio controls. It also works when WebGL is unavailable or a graphics context is lost.

Audio is created only after an explicit click. Pausing, finishing a lap, muting, zero volume, hiding the page, or leaving Ghost Lap silences it; leaving the experience closes the audio context. Switching chase cameras foregrounds that driver in the mix. Circuit orbit and 2D foreground Ghost A. Playback speed compresses replay time, not the RPM-to-pitch relationship.

**Requirements:** a modern WebGL 2 browser for 3D; Web Audio for sound. All models, textures, sound and fonts are local/procedural—no external asset downloads, accounts, audio recordings or CDNs. Graphics performance is device-dependent; use 2D if needed. Browser tests used desktop and mobile-sized Chromium with software WebGL; Safari, Firefox and physical mobile devices have not been separately verified.

**This is telemetry replay, not a drivable physics simulator.** Positions, speed, RPM and gears originate in the recorded laps; geometry, terrain, steering animation and sound are illustrative. There is no steering input, tyre-force model, collisions, validated track elevation or official car livery.

## Measured results on the included snapshot

| Check | Measured result |
|---|---:|
| Pace baseline test MAE | **0.361525 seconds** |
| Pace random-forest test MAE | **0.412548 seconds** |
| Pace held-out rows | **280** |
| Pace feature rows | **1,196** |
| DNA classifier test accuracy | **85% (51 / 60)** |
| DNA training / reserved validation / test laps | **187 / 28 / 60** |
| Replay feature rows | **1,444** |
| Strategy calibration rows | **1,348** |

The forest has about **14.1% higher** pace error than the rolling baseline. That result is displayed, not hidden. These are limited **one-race** results, not claims of cross-circuit generalization. DNA identifies same-race driver–car combinations; it does not isolate driving style.

See [QA-REPORT.md](QA-REPORT.md) for test evidence and [DATA-NOTICE.md](DATA-NOTICE.md) for data provenance and rights considerations.

## Architecture

```text
Public 2023–2024 archive                 Original 2024 Dutch GP snapshot
  93 hashed files                        Separate provenance manifest
         ↓                                          ↓
  dashboard_results (SQLite)              lab.sqlite / four feature groups
  race_pace_features + read-back           fitted models / replay / what-if
         ↓                                          ↓
  /api/dashboard/*                        original /api/* endpoints
         └───────────────────┬───────────────────────┘
                FastAPI + local compiled assets
                             ↓
        19 dashboard/connection views + 4 labs + comparison overview
                React / SVG / Three.js / Web Audio
```

**Stack:** React, Vite, Three.js 0.180.0, Web Audio, FastAPI, pandas, NumPy, scikit-learn, SQLite. No CDN dependencies, stock imagery, external UI services, or external model API are needed at runtime.

### Important files

| Path | Purpose |
|---|---|
| `app.py` | API, validation, exports, and static-site hosting |
| `src/race_replay.py`, `scripts/prepare_race_replay.py`, `data/replay/` | Public shared-clock 20-driver replay API, paced importer and compact curated streams |
| `frontend/src/replay/GhostWorkspace.jsx`, `FleetScene.jsx`, `fleetModel.js` | Separate ghost/race modes, multi-car 3D/2D and gap-safe frame logic |
| `src/settings.py`, `src/remote.py` | Server-only configuration, bounded read-only Elastic client, explicit-write/value-verified Hopsworks batches |
| `src/elastic_dashboard.py`, `src/connections.py` | Native event adapters, labeled supplements, authenticated control jobs and runtime mode switching |
| `scripts/connect_cloud.py`, `docs/CLOUD-SETUP.md` | Private .env initializer, read-only checks, feature plan/publish and deployment guide |
| `src/dashboard.py`, `src/dashboard_api.py` | Two-season archive analytics, local feature read-back, validation and schema/CSV APIs |
| `frontend/src/dashboard/` | Historical pages, shared controls, replay clock and responsive themes |
| `data/dashboard/` | Public archive and 93-file SHA-256 manifest |
| `docs/DASHBOARD-GUIDE.md` | Reference-feature map, field units, source limits and hackathon migration guide |
| `src/engine.py` | Feature engineering, persisted read-backs, models, simulation, and metrics |
| `src/cloud.py` | Optional Elastic/Hopsworks publishing bridges |
| `frontend/src/main.jsx` | Four interactive applications and shared UI |
| `frontend/src/styles.css` | Shared responsive styling |
| `frontend/src/replay/` | Lazy-loaded Three.js scene, procedural models, Web Audio engine and replay styling |
| `web/` | Prebuilt frontend, including local fonts |
| `data/` | Real curated observations, manifest, and regenerated local database |
| `scripts/prepare_data.py` | Re-fetch the original Dutch GP experiment data |
| `scripts/prepare_dashboard_data.py` | Cache/resume the public 2023–2024 archive import |
| `scripts/publish_cloud.py` | Explicit cloud publishing; dry-run by default |
| `tests/` | Data, model, API, offline cloud-contract, and browser tests |
| `qa/` | Test results and screenshots from actual runs |

## Develop the frontend

Node 20+:

```bash
cd frontend
npm ci
npm run build
```

The build writes to `web/`, not `dist/`, so the ready-to-run artifact remains in the workspace snapshot.

For frontend development, run the Python server separately, then `npm run dev`. Vite accepts preview hosts and proxies relative API calls server-side to the Python service.

## Run the tests

```bash
python -m pytest -q tests/test_engine.py tests/test_cloud_contracts.py tests/test_dashboard.py tests/test_connections.py tests/test_race_replay.py
```

Install browser dependencies once, then run the browser suites **sequentially** with the server on port 8000:

```bash
cd frontend
npm ci
npx playwright install chromium
# Linux, if system libraries are missing: npx playwright install-deps chromium
cd ..
node tests/dashboard-model.mjs
node tests/dashboard-browser.mjs
node tests/browser.mjs
node tests/replay-geometry.mjs
node tests/fleet-model.mjs
node tests/fleet-browser.mjs
node tests/replay-browser.mjs
```

**3,529 passing tests/check assertions across twelve suites:** 104 dashboard Python/API tests, 2,846 dashboard-model checks, 137 dashboard browser checks, 73 new connection/security/adapter tests, 63 connection browser checks, plus 50 race-archive/API tests, 39 multi-car model checks (including 22,080 sampled driver frames), 41 multi-car browser checks, and the original 60 Python / 25 browser / 48 geometry / 43 replay-audio checks. The timing model audits every one of the 2,739 intermediate lap frames across all 46 events, including restart inconsistencies. Browser automation exercises all 19 dashboard/connection routes at desktop/mobile widths, actual API requests, downloads, filters, recovery, preferences and the unchanged lab scope. It also measures native Web Audio output and real WebGL rendering. See [QA-REPORT.md](QA-REPORT.md) for evidence and limits.

### Offline integration browser suite

The normal app should be on port 8000. In a separate terminal, start the **test-only** fixture server:

```bash
python -m uvicorn cloud_fixture_app:app --app-dir tests --host 127.0.0.1 --port 8001
```

Then run `node tests/connections-browser.mjs`. It verifies operator login, native mode, Hopsworks publish/read-back/activation, all 19 routes with a sparse native-shaped fixture, bounded telemetry, recovery and mobile layout. Stop the fixture server afterward. It uses visibly labeled in-memory doubles—**never a live provider account**. Run heavy browser suites sequentially.

## Refresh the multi-car position archive

The completed 20-driver replay is bundled; startup makes no OpenF1 request. To deliberately refresh it, run `python scripts/prepare_race_replay.py`, then restart/reload and re-audit the manifest. The importer reuses its raw cache unless removed; it does not ingest the event cluster or automatically change the original models.

## Refresh the public data

The included archive is already complete for this release; **do not re-import just to run the app**. To intentionally refresh, stop the server first and back up the snapshots:

```bash
# Expanded archive, leaving the original experiment files separate:
python scripts/prepare_dashboard_data.py

# Original Dutch GP experiment snapshot (changes may affect fixed-snapshot ML results):
python scripts/prepare_data.py
```

These scripts make public API requests and use caches under `.cache/`, excluded from the package. Availability, API limits and corrected historical records can change. Review the resulting manifests and rerun validation before comparing new results. The direct F1 timing host returned HTTP 403 during the original preparation; this project uses **OpenF1/Jolpica**, not a claimed successful event-cluster/FastF1 import.

## Package the project

```bash
python scripts/package.py
# Optional: verify extraction plus the running local server
python tests/package-smoke.py --live-url http://127.0.0.1:8000
# Repack to include the new report, then verify without rewriting it
python scripts/package.py
python tests/package-smoke.py --live-url http://127.0.0.1:8000 --verify-only
```

This writes `../pitlane-lab.zip` containing source, compiled assets, curated observations, documentation, licenses and test evidence. Dependencies, caches, private `.env` files and common secret/SQLite sidecar files are excluded. The app's **Download project** link serves that archive (or generates it on demand if absent).

## Cloud runtime versus the original-lab publisher

Use **Connections** and `scripts/connect_cloud.py` for the new dashboard runtime. See [docs/CLOUD-SETUP.md](docs/CLOUD-SETUP.md) for the full setup. The source reader never writes to event indices. Hopsworks batches use a unique team prefix and validated source/filter identities, and GET requests never auto-publish missing features.

The older `scripts/publish_cloud.py` remains available for the original Dutch GP lab's feature groups. Its default is a network-free dry run:

```bash
python scripts/publish_cloud.py --target elastic --prefix pitlane_yourteam
python scripts/publish_cloud.py --target hopsworks --prefix pitlane_yourteam
```

Actual legacy publishing requires `--write`, the optional dependencies and your own writable destination. Legacy Elastic destination variables are `ELASTICSEARCH_URL/API_KEY`; do **not** put the organizer's read-only source there when running that publisher. New canonical read-source variables are `ELASTIC_SOURCE_URL/API_KEY`. The original lab pipeline stays local after legacy publishing; it is distinct from the dashboard's configurable pace-feature backend.

No accounts, deployments or billable cloud resources are provisioned automatically. Real account permissions, schema, connectivity and SDK/server compatibility must be checked when credentials arrive. The installed Hopsworks SDK 5.2.1 was imported and its API surface inspected; provider login and storage/network access remain unverified against live accounts.

## Scope and event rules

These are exploration prototypes for comparing concepts. The event's published rule against prebuilt submission repositories has not changed; confirm what you may reuse. The two-hour recommendations in the demo guide refer to deliberately smaller implementations, not reproducing this entire lab during the event.
