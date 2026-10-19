# Pitlane 2.2 — configure Elastic + Hopsworks when credentials arrive

**The runtime connection layer is implemented. You do not need to edit application code to configure the documented event schema.** You will need valid accounts, compatible SDK/server versions, network access and the permissions below. Live account validation has **not** occurred in this delivery.

The app still starts in local mode without credentials. Open **Connections** in the dashboard for configuration readiness, protected connection tests, actual source counts, feature planning/publishing/read-back, mode activation and bounded native telemetry.

## Quick setup

### 1. Install and create a private configuration

From `pitlane-lab`, in your Python virtual environment:

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-integrations.txt
python scripts/connect_cloud.py init
```

`init` creates `.env` with a random **operator token** and restrictive file permissions where supported. It **never overwrites** an existing `.env`. It makes no cloud calls and does not print any token or provider key. Open that file privately in your editor.

Python 3.11+ is recommended. This build installed/imported **Hopsworks SDK 5.2.1 on Python 3.13** and checked the SDK methods used by the adapter. This is an SDK import/API-shape check, **not** proof that your deployment accepts that version. The optional dependency range is `hopsworks[python]>=4.8,<6`; pin the version recommended for your Hopsworks deployment if its major/minor differs. Use a virtual environment, not your system Python.

### 2. Fill in these server-side values

```dotenv
# Keep both local while checking the accounts.
PITLANE_DATA_MODE=local
PITLANE_FEATURE_MODE=local

# The read-only event source: Elasticsearch endpoint, NOT Kibana's /app URL.
ELASTIC_SOURCE_URL=https://your-cluster-endpoint
ELASTIC_SOURCE_API_KEY=your-encoded-api-key

# Your team-owned Hopsworks project. Hostname, not a URL/path.
HOPSWORKS_HOST=your-hopsworks-host
HOPSWORKS_PROJECT=your-project-name
HOPSWORKS_API_KEY=your-hopsworks-key

# Choose your own namespace. The placeholder pitlane_yourteam cannot publish.
PITLANE_FEATURE_PREFIX=pitlane_unique_team
PITLANE_FEATURE_VERSION=1
PITLANE_ALLOW_FEATURE_WRITES=false

# Keep the random token written by init. This is NOT either provider API key.
PITLANE_ADMIN_TOKEN=the-generated-operator-token
```

Do **not** add the `ApiKey ` prefix to the Elastic key value; the backend adds the authorization scheme. Use the encoded API-key string supplied by Elastic/organizers, not an API-key ID by itself. Do not use `VITE_` variables: those can be compiled into browser assets.

Start/restart the app after the first configuration:

```bash
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/#connections` on your computer, or the Arena live preview's **Connections** page. If the server is only for your own machine, binding to `127.0.0.1` instead is safer; Arena live previews require `0.0.0.0`. Keep this demo private or behind an authenticated reverse proxy for wider deployment.

### 3. Unlock and verify, without writes

1. Enter **PITLANE_ADMIN_TOKEN** into the operator-token field. Never enter an Elastic/Hopsworks API key there.
2. Click **Test Elastic read access**. This checks mappings and actual 2023–2024 document counts for the five configured indices.
3. Click **Test Hopsworks access**. This authenticates and obtains the feature-store handle; it does **not** create a feature group, and does not by itself prove offline-data read/write access.
4. Select **Elastic event indices + Local SQLite**, choose a known event such as **2024 R15**, and click **Verify & activate modes**. The candidate metadata/lap/weather reads must succeed before the server switches. A failure leaves the previous modes unchanged.
5. Open Race pace or Weather: those now consume the configured Elastic source. The active provider and public supplements are displayed.

The protected controls run jobs in the background and display actual queued/running/succeeded/failed states. SDK operations can take minutes. Do not repeatedly click Publish; concurrent control jobs are rejected. A provider may continue an accepted job after a process shutdown—check the provider's job UI before retrying.

### 4. Publish one real feature batch and consume its read-back

1. In Connections, set the feature season/round, pit/outlier toggle and cutoff. Use **Preview feature plan**. Check the active source mode, row count and isolated destination. Planning performs no cloud writes.
2. When you authorize Hopsworks writes, set `PITLANE_ALLOW_FEATURE_WRITES=true` in `.env`. Restart, or use **Reload server configuration** while still authenticated. Reload restores modes from `.env`, so re-activate Elastic if `.env` still says local.
3. Type the exact displayed destination name, for example **`pitlane_unique_team_race_pace`**, and click **Publish & verify batch**.
4. Wait for success. The code creates/gets that group/version, inserts the selected descriptive pace rows, waits for the SDK write job, then reads the **specific batch** back and verifies **IDs, counts, payloads and numeric values**. It does not switch modes automatically.
5. Select **Elastic event indices + Hopsworks verified read-back**, then **Verify & activate modes**.
6. Open Race pace. Its summaries/comparison bars/distributions now consume the Hopsworks read-back; the **Feature storage** metric says Hopsworks. Raw lap curves still come from Elastic.

**One batch belongs to one exact source snapshot + race + filter.** Changing the race or cutoff without publishing its batch produces a visible missing-feature error; GET requests never silently create a group or publish data. Return to Connections, preview/publish the new selection, or explicitly switch features to local mode. Feature IDs bind the exact source-lap digest, namespace, row values and filter, preventing stale or cross-dataset reuse.

Read results are cached for the configured TTL (default five minutes). Reloading/restarting clears the cache and forces a new provider read. If a successful write is not immediately readable, leave features local, check the provider job/storage state, then retry activation. Do not treat a write acknowledgment as proof of usable features.

### 5. Persist the working modes

UI switches apply to the **running server**, not just one browser. They do not edit `.env`:

```dotenv
PITLANE_DATA_MODE=elastic
PITLANE_FEATURE_MODE=hopsworks
```

Set those only after the corresponding feature batches/read permissions have been verified. Restart and unlock Connections again. Cloud-mode dashboard endpoints require the operator session; static assets and the original public-data labs remain available.

To recover locally, explicitly activate local/local or put both values back to `local` and restart. There is no automatic fallback that would misrepresent local data as a working cloud connection.

## What actually changes—and what stays separate

| Area | With Elastic data mode | With Hopsworks feature mode |
|---|---|---|
| Race/Qualifying classifications | Native `f1-results`; standings use those Race points | No change |
| Calendar/session metadata | Native `f1-sessions` joined to public venue metadata | No change |
| Race lap analysis / positions / native track_status | Native `f1-laps`, fetched only for selected sessions | Per-driver pace summaries are read from the verified feature batch |
| Qualifying lap JSON | Native `f1-laps` selected by Qualifying, when present | No change |
| Race/Qualifying weather | Native `f1-weather` | No change |
| Tyre segments | Derived contiguous segments from native compound, tyre-life and pit flags | Not certified physical tyre-set identity |
| Native telemetry | Connections reads/plots/downloads a **single driver/lap** from `f1-telemetry` | Not implicitly published |
| Sprint points, Q1/Q2/Q3, result elapsed times/lap totals, speed traps, pit-transit timings, race-control messages | **Explicit public supplements**: these are not all in the advertised five-index schema | No claim that they came from Hopsworks |
| Historical timing replay | **Separate public replay**. Native event laps lack synchronized start/end timestamps | Unchanged |
| Original 3D Ghost Lap / Pitwall / Pace Detective / Driver DNA | **Separate frozen public Dutch GP experiments**; not silently re-imported or retrained | Their original local pipelines remain local |
| Track DNA | Descriptive summaries calculated from available native races + labeled public fields | Does not implicitly require/publish every season-wide feature batch |

The original `scripts/publish_cloud.py` is still available for the **original four lab feature groups**. It is not the dashboard runtime switch. In particular, its Elastic publisher expects your **own writable destination**, never the organizer's read-only event source. The new `scripts/connect_cloud.py` handles the dashboard connection/pace workflow.

Cloud schema JSON exports use native fields without adding public supplemental fields. Native full-session telemetry export is intentionally empty with instructions to use the bounded Connections slice. The Race CSV/analytical views include source/supplement notes.

## Source configuration and permissions

### Elastic

Default aliases are configurable independently:

```dotenv
ELASTIC_INDEX_SESSIONS=f1-sessions
ELASTIC_INDEX_RESULTS=f1-results
ELASTIC_INDEX_LAPS=f1-laps
ELASTIC_INDEX_WEATHER=f1-weather
ELASTIC_INDEX_TELEMETRY=f1-telemetry
```

Use explicit index/alias names, not wildcards or comma-separated multi-index patterns. Expected fields/units are in `docs/DASHBOARD-GUIDE.md` and the organizer's participant guide. Keyword fields and `text` fields with a compatible `.keyword` subfield are supported for filters. Lap/sector durations must already be **milliseconds**, relative telemetry/weather time **seconds**, and pit/brake/rainfall fields booleans/null—not strings.

The source reader uses `_field_caps`, `_count`, point-in-time search with `search_after`, and PIT cleanup. Required source permissions normally include **read** and **view_index_metadata** on the five indices. PIT open/close manages a temporary search context, **not source-document creation/deletion**. There are no `_bulk`, `_reindex`, update or source-document delete calls in this adapter. Cluster configuration/proxy restrictions may require the organizer to permit PIT operations.

Canonical `ELASTIC_SOURCE_URL/API_KEY` take priority. If you want the organizer's variables instead, **remove** the two canonical entries rather than leaving them blank:

```dotenv
CLUSTER=remote
REMOTE_ELASTICSEARCH_URL=https://source-endpoint
REMOTE_ELASTICSEARCH_API_KEY=encoded-readonly-key
```

With `CLUSTER` unset or `local`, legacy `ELASTICSEARCH_URL/API_KEY` are accepted. Empty canonical values deliberately prevent accidental fallback to an unrelated writable destination. `.env` values are overridden by actual process environment variables. Variable interpolation inside `.env` is disabled.

TLS verification stays enabled. Public HTTPS endpoints normally need no extra configuration. For a self-managed/private CA, set `ELASTIC_CA_CERT` to a trusted certificate file. Plain HTTP is accepted only for loopback development. URLs with embedded credentials, query strings or fragments are rejected. Redirects are not followed with an API key.

### Hopsworks

Use your project name, host and API key. `HOPSWORKS_HOST` accepts a hostname and optional port, not `https://.../path`. The adapter enables hostname verification and keeps SDK certificate material under `.cache/hopsworks-certs`. A private CA can be supplied through `HOPSWORKS_CA_CERT`.

Your project role/API key must allow feature-store access, group creation/update for the explicit write step, and offline-data reads. Successful login does **not** establish storage/Flight/Kafka/Spark-job connectivity; verify the actual publish/read-back workflow. Some accounts/networks need additional provider configuration that cannot be established without credentials.

The destination is `<PITLANE_FEATURE_PREFIX>_race_pace`, version `PITLANE_FEATURE_VERSION`, primary key `id`, with online serving disabled. Columns include `batch_id`, `source_id`, original row identity, season/round/driver, sample count, median/mean/spread, cutoff/filter state, and the canonical row payload. Batch-filtered reads avoid loading the full feature group. Writes use stable IDs; no delete operations are performed. If a group has an incompatible schema, choose a new version or prefix rather than destructively replacing it.

## Bounds, caching and failures

Defaults in `.env.example`:

| Setting | Default | Meaning |
|---|---:|---|
| `PITLANE_REQUEST_TIMEOUT` | 20 s | Per Elastic request; connection timeout is also bounded |
| `PITLANE_PAGE_SIZE` | 500 | Search page size, maximum 1,000 |
| `PITLANE_METADATA_LIMIT` | 5,000 | Sessions/results read cap |
| `PITLANE_LAP_LIMIT` | 5,000 | Native lap rows per selected session |
| `PITLANE_WEATHER_LIMIT` | 2,000 | Weather rows per selected session |
| `PITLANE_TELEMETRY_LIMIT` | 20,000 | Telemetry rows per one driver/lap slice |
| `PITLANE_CACHE_SECONDS` | 300 | Bounded raw/feature in-process cache TTL |

A cap breach, partial shard response, timeout, stalled pagination, conflicting duplicate key, invalid unit/type, missing group, mismatched feature value or authorization failure produces an actionable error. The adapter does **not** silently truncate a slice, fabricate missing values or fall back to the public data. Provider response bodies/SDK exceptions are not echoed because they may contain secrets.

Metadata is a connection snapshot; reload/restart to discover newly indexed sessions/results. Missing event rounds are not filled with public Race results. Championship plots cover the available native events plus labeled Sprint supplements, not a falsely complete event-cluster season.

## CLI alternative

All commands read server `.env`/environment; none accept provider keys on the command line.

```bash
# Read-only mapping/count and feature-store access checks:
python scripts/connect_cloud.py check --provider elastic
python scripts/connect_cloud.py check --provider hopsworks

# Explicit source choice, no remote writes:
python scripts/connect_cloud.py plan --data-source elastic --season 2024 --round 15
python scripts/connect_cloud.py publish --data-source elastic --season 2024 --round 15

# Actual write: requires the configured write flag, unique prefix and confirmation:
python scripts/connect_cloud.py publish --data-source elastic --season 2024 --round 15 \
  --write --confirm-group pitlane_unique_team_race_pace
```

Use `--cutoff 1.10` or `--all-laps` for another filter configuration. Planning reports the active source so you do not accidentally publish a public-data batch while expecting an Elastic-derived one. CLI commands do not change a running web server's modes.

## Security and packaging

- Provider keys are only in the server environment/private `.env`, never browser storage, compiled JavaScript or a form on Connections.
- The operator token is separate. The browser receives a signed, eight-hour, HttpOnly, SameSite=Strict session cookie; it is Secure on HTTPS. Cloud dashboard data and all provider actions require authorization. Cross-origin connection actions are rejected.
- Protect any reverse proxy with HTTPS and correct host/proto forwarding. Do not deploy this demo as a public multi-tenant service without additional access controls, rate limits and operational hardening.
- Package generation excludes `.env*` except the example, caches, SDK credential directories, common certificate/keystore files and live publishing reports. Native responses are cached only in memory; disposable SQLite caches and SDK certificates live under `.cache`.
- Do not paste credentials into chat. Review your deployment's files and SDK output before public distribution; software cannot recognize every arbitrary filename someone might use for a secret.
- No cloud infrastructure is automatically provisioned, no reindex of the 57M-row corpus occurs, and no provider charges/writes were incurred while developing/testing this layer.

## Verification boundary

The delivery includes offline tests of the actual HTTP request construction/pagination, native schema adaptation, SDK calls and read-back validation, operator authentication, protected source switching, browser interactions and failure recovery. The dedicated QA fixture server is clearly marked **offline fixture** and uses in-memory doubles, not an Elastic or Hopsworks account. The regular app never activates that server or those fixtures.

Your final acceptance check, once credentials arrive: **test both providers → activate native Elastic → publish and verify one isolated Hopsworks batch → activate Hopsworks → confirm a real dashboard response reports Hopsworks with matching read-back evidence**. Only after that should you call the deployment live-account validated.

## Version 2.2 / public replay remains independent

Ghost Lap additionally includes a bundled synchronized **20-driver 2024 Dutch GP** archive (218,520 recorded XY / 110,300 car-telemetry records). It works without provider credentials and is distinct from native Elastic telemetry and Hopsworks pace batches. New `/api/replay/*` routes serve only this public snapshot, not private cloud data. The original A/B comparison is still available as “Two-car detail.” See [MULTI-CAR-REPLAY.md](MULTI-CAR-REPLAY.md).
