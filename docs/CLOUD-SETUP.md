# Pitlane 2.2 — configure Hopsworks

**The runtime connection layer is implemented. You do not need to edit application code to point the app at the event tables in your Hopsworks project.** You need a valid Hopsworks project, a compatible SDK/server version, network access and the permissions below.

One Hopsworks project does two jobs:

- **Event data source.** Five read-only feature groups (tables) hold the F1 event data: `f1_sessions`, `f1_results`, `f1_laps`, `f1_weather` and `f1_telemetry`.
- **Feature store for derived features.** The dashboard writes and reads back its per-driver pace summaries in your team's `<prefix>_race_pace` feature group.

The app still starts in local mode without credentials. Open **Connections** in the dashboard to see configuration readiness and to run protected connection tests, table schema checks and row counts, feature planning/publishing/read-back, mode activation and bounded native telemetry reads.

## Quick setup

### 1. Install and create a private configuration

From `pitlane-lab`, in your Python virtual environment:

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-integrations.txt
python scripts/connect_cloud.py init
```

`init` creates `.env` with a random **operator token** and restrictive file permissions where supported. It **never overwrites** an existing `.env`. It makes no cloud calls and does not print any token or provider key. Open that file privately in your editor.

Python 3.11+ is recommended. The optional dependency range is `hopsworks[python]>=4.8,<6`. If your Hopsworks deployment uses a different major/minor version, pin the SDK version it recommends. Use a virtual environment, not your system Python.

### 2. Fill in these server-side values

```dotenv
# Keep both local while checking the project.
PITLANE_DATA_MODE=local
PITLANE_FEATURE_MODE=local

# Your Hopsworks project. Hostname, not a URL/path.
HOPSWORKS_HOST=your-hopsworks-host
HOPSWORKS_PROJECT=your-project-name
HOPSWORKS_API_KEY=your-hopsworks-key

# Event tables in that project (defaults shown; change them to match your tables).
HOPSWORKS_FG_SESSIONS=f1_sessions
HOPSWORKS_FG_RESULTS=f1_results
HOPSWORKS_FG_LAPS=f1_laps
HOPSWORKS_FG_WEATHER=f1_weather
HOPSWORKS_FG_TELEMETRY=f1_telemetry
HOPSWORKS_FG_VERSION=1

# Choose your own namespace. The placeholder pitlane_yourteam cannot publish.
PITLANE_FEATURE_PREFIX=pitlane_unique_team
PITLANE_FEATURE_VERSION=1
PITLANE_ALLOW_FEATURE_WRITES=false

# Keep the random token written by init. This is NOT the Hopsworks API key.
PITLANE_ADMIN_TOKEN=the-generated-operator-token
```

Do not use `VITE_` variables: those can be compiled into browser assets.

Start/restart the app after the first configuration:

```bash
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/#connections`. If the server is only for your own machine, binding to `127.0.0.1` is safer. For a wider deployment, keep this demo private or put it behind an authenticated reverse proxy.

### 3. Unlock and verify, without writes

1. Enter **PITLANE_ADMIN_TOKEN** into the operator-token field. Never enter the Hopsworks API key there.
2. Click **Test event table access**. For each of the five configured feature groups, this checks that it exists, that its schema has the required features with compatible types, and how many 2023–2024 rows it holds (counted with a server-side season filter). Telemetry gets a schema check only and is never counted or downloaded in full.
3. Click **Test feature store access**. This authenticates and obtains the feature-store handle. It does **not** create a feature group, and on its own it does not prove you can read or write offline data.
4. Select **Hopsworks event tables + Local SQLite**, choose a known event such as **2024 R15**, and click **Verify & activate modes**. The server switches only after the candidate metadata, lap and weather reads succeed. If any read fails, the previous modes stay in place.
5. Open Race pace or Weather. Those pages now use the Hopsworks event tables, and they show the active provider and any public supplements.

The protected controls run jobs in the background and show their real state: queued, running, succeeded or failed. SDK operations can take minutes. Don't click Publish repeatedly; the server rejects concurrent control jobs. A Hopsworks job that was already accepted may keep running after the process shuts down, so check the Hopsworks job UI before retrying.

If your project does not yet hold the event tables, load the bundled public archive into them (see **Load the event tables** below).

### 4. Publish one real feature batch and consume its read-back

1. In Connections, set the feature season/round, pit/outlier toggle and cutoff. Use **Preview feature plan**. Check the active source mode, row count and isolated destination. Planning performs no cloud writes.
2. When you authorize Hopsworks writes, set `PITLANE_ALLOW_FEATURE_WRITES=true` in `.env`. Restart, or use **Reload server configuration** while still authenticated. Reload restores modes from `.env`, so if `.env` still says local, activate Hopsworks data again.
3. Type the exact destination name shown, for example **`pitlane_unique_team_race_pace`**, and click **Publish & verify batch**.
4. Wait for success. The server gets or creates that group/version, inserts the selected pace summary rows and waits for the SDK write job. It then reads back that **specific batch** and verifies **IDs, counts, payloads and numeric values**. It does not switch modes automatically.
5. Select **Hopsworks event tables + Hopsworks verified read-back**, then **Verify & activate modes**.
6. Open Race pace. Its summaries, comparison bars and distributions now use the Hopsworks read-back, and the **Feature storage** metric shows Hopsworks. Raw lap curves come from the `f1_laps` table.

**Each batch belongs to one exact source snapshot, race and filter.** If you change the race or cutoff without publishing a batch for it, the dashboard shows a missing-feature error. GET requests never create a group or publish data on their own. To fix the error, go back to Connections and preview/publish the new selection, or switch features to local mode. Feature IDs bind together the source-lap digest, namespace, row values and filter, so a batch can't be reused for a different dataset or a stale one.

Read results are cached for the configured TTL (default five minutes). Reloading or restarting clears the cache and forces a fresh read. If a successful write can't be read back immediately, leave features local, check the job and storage state in Hopsworks, then retry activation. A write acknowledgment alone does not prove the features are usable.

### 5. Persist the working modes

Mode switches in the UI apply to the **running server**, not just one browser. They do not edit `.env`. To keep them across restarts, set:

```dotenv
PITLANE_DATA_MODE=hopsworks
PITLANE_FEATURE_MODE=hopsworks
```

Set these only after you have verified the event tables and the feature batches. Then restart and unlock Connections again. Cloud-mode dashboard endpoints require the operator session. Static assets and the original public-data labs remain available without it.

To go back to local data, activate local/local in Connections, or set both values back to `local` and restart. There is no automatic fallback, so local data is never shown as if it came from a working cloud connection.

## Load the event tables

Skip this if your project already holds the event tables. Otherwise, the CLI can write the bundled public 2023–2024 archive into the five source feature groups, using the same event schema the reader expects:

```bash
# Dry run: per-table row counts and feature names, no provider calls.
python scripts/connect_cloud.py load-source

# Optional narrowing.
python scripts/connect_cloud.py load-source --season 2024 --kind laps --kind weather

# Actual write: requires PITLANE_ALLOW_FEATURE_WRITES=true.
python scripts/connect_cloud.py load-source --write
```

Each table gets primary key `id` (a stable hash of the natural key: season/round/session plus driver, lap or timestamp as appropriate) and online serving is disabled. Integer, boolean and string features use explicit nullable types. After each insert, the loader reads back the `id` column to verify it. The public archive has no Qualifying lap samples. Its telemetry consists of only the four interpolated 2024 Dutch GP comparison laps.

## What actually changes—and what stays separate

| Area | With Hopsworks data mode | With Hopsworks feature mode |
|---|---|---|
| Race/Qualifying classifications | Native `f1_results`; standings use those Race points | No change |
| Calendar/session metadata | Native `f1_sessions` joined to public venue metadata | No change |
| Race lap analysis / positions / native track_status | Native `f1_laps`, read only for the selected session | Per-driver pace summaries are read from the verified feature batch |
| Qualifying lap JSON | Native `f1_laps` filtered to Qualifying, when present | No change |
| Race/Qualifying weather | Native `f1_weather` | No change |
| Tyre segments | Contiguous segments derived from the native compound, tyre-life and pit flags | Not certified physical tyre-set identity |
| Native telemetry | Connections reads/plots/downloads a **single driver/lap** from `f1_telemetry` | Not published implicitly |
| Sprint points, Q1/Q2/Q3, result elapsed times/lap totals, speed traps, pit-transit timings, race-control messages | **Explicit public supplements**, because the five-table event schema doesn't include all of these | Not attributed to Hopsworks |
| Historical timing replay | **Separate public replay**. Native event laps lack synchronized start/end timestamps | Unchanged |
| Original 3D Ghost Lap / Pitwall / Pace Detective / Driver DNA | **Separate frozen public Dutch GP experiments**; never re-imported or retrained behind the scenes | Their original local pipelines remain local |
| Track DNA | Descriptive summaries calculated from available native races + labeled public fields | Does not require or publish a batch for every race in the season |

`scripts/publish_cloud.py` publishes the **original four lab feature groups** to Hopsworks. It does not switch the dashboard runtime. The dashboard's connection and pace workflow runs through `scripts/connect_cloud.py`.

In cloud mode, schema JSON exports contain only native fields, with no public supplements added. The full-session native telemetry export is deliberately empty and points you to the bounded Connections slice instead. The Race CSV and analytical views include source and supplement notes.

## Source tables and permissions

### Event table schema

| Table | Required features (type) | Other features read when present |
|---|---|---|
| `f1_sessions` | season, round_number (numeric); session_name, event_name (string); session_date (timestamp/date/string) | country, location |
| `f1_results` | season, round_number, position, points (numeric); session_name, driver_code, status (string) | event_name, driver_number, full_name, team_name, grid_position, fastest_lap_ms |
| `f1_laps` | season, round_number, lap_number, lap_duration_ms (numeric); session_name, driver_code (string); is_pit_in_lap, is_pit_out_lap (boolean) | event_name, team_name, duration_sector_1..3, compound, tyre_life, track_status, position |
| `f1_weather` | season, round_number, session_time_s (numeric); session_name (string) | event_name, air_temperature, track_temperature, humidity, pressure, wind_speed, wind_direction, rainfall |
| `f1_telemetry` | season, round_number, lap_number, session_time_s, speed (numeric); session_name, driver_code (string) | event_name, team_name, rpm, throttle, brake, drs, n_gear, x, y, z |

Lap and sector durations must already be in **milliseconds**, and relative telemetry/weather times in **seconds**. Pit, brake and rainfall fields must be booleans or null, not strings. Optional features that are missing from a table are returned as null. Use explicit, lowercase feature-group names (letters, digits and underscores). Wildcards and paths are rejected.

The reader calls `get_feature_group(name, version)`, inspects `features` for the schema, and reads with `select([...]).filter(...).read()`. The filter always includes `season in (2023, 2024)` plus the selected season/round/session (and driver/lap for telemetry), so filtering happens in Hopsworks rather than after a full download. The reader never inserts into, alters or deletes the source tables.

### Hopsworks

`HOPSWORKS_HOST` accepts a hostname with an optional port, not `https://.../path`. The adapter logs in with `engine='python'` and enables hostname verification. SDK certificate material is kept under `.cache/hopsworks-certs`. You can supply a private CA through `HOPSWORKS_CA_CERT`. The source reader and the pace feature store share a single login.

Your project role/API key needs: read access to the event tables, offline-data reads (Arrow Flight / query service), and, for the explicit write steps only, permission to create and update feature groups. A successful login does **not** prove that storage, Flight or job connectivity works, so verify the actual read and publish/read-back workflow.

The pace destination is `<PITLANE_FEATURE_PREFIX>_race_pace`, version `PITLANE_FEATURE_VERSION`, with primary key `id` and online serving disabled. Its columns include `batch_id`, `source_id`, the original row identity, season/round/driver, sample count, median/mean/spread, cutoff/filter state and the canonical row payload. Reads are filtered by batch, so the full feature group is never loaded. Writes use stable IDs, and nothing is ever deleted. If a group has an incompatible schema, choose a new version or prefix instead of replacing it destructively. The prefix may not reuse a source table name.

## Bounds, caching and failures

Defaults in `.env.example`:

| Setting | Default | Meaning |
|---|---:|---|
| `PITLANE_METADATA_LIMIT` | 5,000 | Sessions/results read cap |
| `PITLANE_LAP_LIMIT` | 5,000 | Native lap rows per selected session |
| `PITLANE_WEATHER_LIMIT` | 2,000 | Weather rows per selected session |
| `PITLANE_TELEMETRY_LIMIT` | 20,000 | Telemetry rows per one driver/lap slice |
| `PITLANE_CACHE_SECONDS` | 300 | Bounded raw/feature in-process cache TTL |

The following produce an actionable error: a cap breach, a missing table or incompatible schema, a conflicting duplicate key, an invalid unit or type, a mismatched feature value, an authorization failure, or a failed SDK read. The adapter never truncates a slice silently, fabricates missing values or falls back to public data. Hopsworks SDK exceptions are never echoed, because they can contain secrets.

Session/result metadata is a snapshot taken when connecting. Reload or restart to pick up newly loaded sessions/results. Missing event rounds are not filled in with public Race results. Championship plots cover the available native events plus the labeled Sprint supplements, so they never claim a complete season the tables don't contain.

## CLI alternative

All commands read the server `.env`/environment. None of them accept the API key on the command line.

```bash
# Read-only schema/count and feature-store access checks:
python scripts/connect_cloud.py check --provider source
python scripts/connect_cloud.py check --provider features

# Explicit source choice, no remote writes:
python scripts/connect_cloud.py plan --data-source hopsworks --season 2024 --round 15
python scripts/connect_cloud.py publish --data-source hopsworks --season 2024 --round 15

# Actual write: requires the configured write flag, unique prefix and confirmation:
python scripts/connect_cloud.py publish --data-source hopsworks --season 2024 --round 15 \
  --write --confirm-group pitlane_unique_team_race_pace
```

Use `--cutoff 1.10` or `--all-laps` for another filter configuration. The plan reports which data source is active, so you won't publish a batch computed from local public data when you meant the Hopsworks event tables. CLI commands do not change the modes of a running web server.

## Security and packaging

- The Hopsworks API key exists only in the server environment or the private `.env`. It never appears in browser storage, compiled JavaScript or any form on Connections.
- The operator token is separate. The browser receives a signed, eight-hour, HttpOnly, SameSite=Strict session cookie, which is also Secure on HTTPS. Cloud dashboard data and all provider actions require this authorization. Cross-origin connection actions are rejected.
- Protect any reverse proxy with HTTPS and correct host/proto forwarding. Don't deploy this demo as a public multi-tenant service without additional access controls, rate limits and operational hardening.
- Package generation excludes all `.env*` files except the example, plus caches, SDK credential directories, common certificate/keystore files and live publishing reports. Native responses are cached only in memory. Disposable SQLite caches and SDK certificates live under `.cache`.
- Don't paste credentials into chat. Review your deployment's files and SDK output before distributing it publicly; software can't recognize every arbitrary filename someone might use for a secret.

## Verification boundary

The delivery includes offline tests that cover:

- the actual SDK call sequence (login, `get_feature_group`, schema inspection, filtered `select().filter().read()`, inserts and read-back)
- native schema adaptation
- operator authentication and protected source switching
- browser interactions and failure recovery

The dedicated QA fixture server is clearly marked **offline fixture** and uses in-memory SDK doubles, not a Hopsworks account. The regular app never activates that server or those fixtures.

Final acceptance check against your project: **test the event tables → test the feature store → activate Hopsworks data → publish and verify one isolated pace batch → activate Hopsworks features → confirm a real dashboard response reports Hopsworks with matching read-back evidence**. Don't call the deployment live-account validated until all of these pass.

## Version 2.2 / public replay remains independent

Ghost Lap also includes a bundled synchronized **20-driver 2024 Dutch GP** archive (218,520 recorded XY / 110,300 car-telemetry records). It works without provider credentials and is separate from the native Hopsworks telemetry table and the pace batches. The `/api/replay/*` routes serve only this public snapshot, never private cloud data. The original A/B comparison is still available as "Two-car detail." See [MULTI-CAR-REPLAY.md](MULTI-CAR-REPLAY.md).
