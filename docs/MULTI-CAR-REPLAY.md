# Pitlane 2.2 — multi-car Ghost Lap and shared-clock race replay

Open **Ghost Lap** in the live app. Refresh an already-open tab after upgrading. The dashboard remains the default workspace; the Ghost Lap scope remains **2024 Dutch Grand Prix / Zandvoort**, regardless of the dashboard’s global season/round filters or cloud mode.

## Three tabs, two different meanings of position

### 4-car ghosts

Compare **NOR, VER, LEC and PIA** together. These are the original four independent recorded laps, aligned at lap start:

| Driver | Recorded lap | Lap time |
|---|---:|---:|
| NOR | 72 | 1:13.817 |
| PIA | 36 | 1:14.237 |
| LEC | 62 | 1:14.585 |
| VER | 30 | 1:14.752 |

The preview opens paused at 24 seconds, following VER so the other three ghost cars can be seen ahead. **Restart** brings everyone back to aligned lap time zero. Show/hide drivers, follow any selected driver, or orbit the circuit.

- Virtual order uses normalized lap progress. It is not a race classification.
- “Δ to leader” compares time at the **same normalized lap distance**, using the fastest-progressing selected ghost as the reference. At the finish, the NOR-relative deltas are PIA **+0.420s**, LEC **+0.768s**, VER **+0.935s**.
- Distance normalization comes from the original integrated-speed lap traces. These laps have different tyres, tyre ages, fuel and traffic. They were not recorded simultaneously and do not establish intrinsic driver skill.
- In chase view, other ghosts are translucent to make overlap understandable. There is no collision or handling simulation.

### 20-car race replay

This is a **separate, synchronized race archive**, not the four laps stretched into an estimated field animation. All cars are sampled at the **same provider session timestamp** using OpenF1’s recorded location and car-data streams.

The imported race interval contains:

| Coverage | Count |
|---|---:|
| Drivers | **20** |
| Retained location records | **218,520** |
| Retained car-telemetry records | **110,300** |
| Original source responses | **40** |
| Original source records represented by those responses | **841,220** |
| Curated per-driver files with SHA-256 hashes | **20** |
| Synthetic race observations added | **0** |

Recorded common coverage is approximately **00:03:09.315–01:35:06.816** on the provider’s session clock, whose origin is **2024-08-25 13:00:00 UTC**. This is **not certified elapsed time from lights-out**. The initial view is paused at **00:13:09.315**, showing the field around lap eight. At that timestamp the recorded rank feed has VER ahead of NOR; it is not reusing the ghost-lap order.

The replay works **now, offline after installation, without Elastic/Hopsworks credentials**. It uses a deliberately separate public archive; it does not claim your private event telemetry is connected.

### Two-car detail

The original A/B experience remains available here, unchanged in purpose: driver swapping, per-driver instruments, speed/throttle/brake/delta charts, Chase A/B, orbit, theatre, engine audio and 2D fallback. Its original regression tests still run through this tab.

## Controls

- **Driver chips:** show/hide a car; at least one selected driver remains. Race mode has “All 20” and a NOR/VER/LEC/PIA shortcut.
- **Follow:** choose any selected driver from the dropdown, timing table, 3D car marker or interactive 2D map.
- **Chase / Overview:** chase follows the selected car. Overview supports drag-to-orbit and wheel/pinch zoom.
- **3D / 2D:** switch without changing the selected source clock. The 2D map is also the WebGL recovery path.
- **Play / Pause / Restart / scrubber:** the scrubber pauses and seeks precisely within the recorded interval. Hiding the browser tab pauses playback.
- **Playback rate:** 0.25–4× for ghosts; 1–60× for the race. The rate changes replay time, not the recorded speed readings.
- **Race presets:** opening grid and NOR lap-start timestamps (10, 18, 29, 50, 70). These move the shared clock for every car; they do not align each driver to the same lap number.
- **Expand:** an immersive, keyboard-accessible view with focus-driver instruments. Escape exits and restores focus. Mobile retains the essential playback controls.
- **Enable sound:** explicit consent is required. Audio follows the focused car plus the nearest selected car with usable telemetry; it is synthesized from RPM/throttle/gear, not an official engine recording. Pause/mute/zero volume/background/unmount silence or dispose the audio. Switching modes resets consent; changing driver focus does not fabricate a gearshift.
- **Telemetry chart:** ghosts show selected lap traces by normalized distance. Race mode defaults to a five-minute window following the playhead, with a full-session option. Click to seek the corresponding source clock.

## What the race timing table means

**Rank:** the last recorded position update at or before the shared timestamp. Asynchronous updates can be sparse, so this is not a fabricated continuously observed order. Once all recorded lap completions have been reached, the table explicitly switches to the published final classification.

**Lap / tyres:** based on recorded lap evidence and stint boundaries. For continuous-time lap labels, the next consecutive recorded lap start defines the previous completion boundary. Source durations are not overwritten. This handles real small overlaps such as NOR’s lap-29 start occurring 65 ms before lap 28’s duration-derived endpoint. In contrast, the separate dashboard’s older lap-stepped timing module retains its own documented reconciliation threshold.

**XY to [focus]:** approximate **straight-line separation** between the two current XY positions, scaled using the existing 4,259 m reference. It is **not** an official time interval, gap to the race leader, or distance along the racing line. Cars on different laps can be geographically close.

**Position availability:** missing/stale/outlier positions are hidden, not advanced around a guessed racing line. The stage reports visible/selected counts; unavailable focused cars produce a notice and safe overview camera. Other drivers can continue playing.

## Sampling and missing-data policy

The importer selects **one actual location record per 0.5-second bin** and **one actual car-data record per one-second bin**, choosing the source record nearest the bin centre. The original record’s timestamp and channel values are retained. It does not create a synthetic uniform timeline in the stored files.

For display, the model interpolates short intervals between bracketing position observations. It never extrapolates before/after a driver’s coverage. Gaps exceeding **2.5 seconds** are hidden; apparent movements above **150 m/s** in the approximate world scale are treated as implausible jumps rather than animated as real motion. Vehicle heading is derived from nearby position samples, not an independent observed heading channel.

Continuous telemetry uses valid bracketing samples; gear/brake/DRS use as-of samples. Out-of-range channels become unavailable rather than silently clipped into a claimed measurement. The release retained and flagged **one throttle=104 and five brake=104** source values. The affected raw records remain inspectable in the archive; instruments/plots do not present those invalid percentages as valid readings. Missing required engine telemetry is silent.

The imported observed location streams happen to share feed timestamps, but the model independently brackets every driver against the common clock and supports unequal/missing streams. This is tested with explicit gap fixtures as well as the real archive.

## 3D mapping and limits

- Cars are placed from recorded **XY**, not from race rank, interpolated lap completion or a simulated driver policy.
- The road reference remains the measured NOR lap trace. Its length is scaled to 4,259 m; this is an approximate visual mapping, not a surveyed map.
- Elevation is flattened. Road width, kerbs, scenery, car shapes/liveries, steering and engine acoustics are illustrative. Source Z is retained in the archive but not claimed to be a calibrated elevation model.
- The race scene uses flat surroundings and adaptive car detail to keep a 20-car field practical. Nearby/followed cars retain detailed models; distant cars and scalable labels support the overview. No vehicle handling, collision or driving controls are implied.
- Full-field coverage is for **this Dutch GP**, not every race in the 2023–2024 dashboard.
- Dashboard cloud modes and original Pace Detective / Driver DNA / Pitwall training scopes are not silently changed. The original five-index telemetry schema export remains the four comparison laps; the new archive uses dedicated replay endpoints.

## Files, endpoints and refresh

- `data/replay/manifest.json`: source URLs/digests, scope, cadence, counts, per-driver quality and file hashes.
- `data/replay/<CODE>.json`: separate `location` and `car_data` column arrays, each with its own real `time` values in session seconds.
- `GET /api/ghost/field`: original four ghosts, consumed from the existing persisted-feature read-back.
- `GET /api/replay/race`: public manifest, classifications, lap/rank/stint/control context.
- `GET /api/replay/driver/<CODE>`: one installed curated driver file. Unknown drivers and path-like values are not served.
- `frontend/src/replay/fleetModel.js`: sampling, gap handling, relative comparison and shared-time frame logic.
- `GhostWorkspace.jsx`, `FleetScene.jsx`, `fleet.css`: separate modes, player, multi-car renderer and responsive layout.

To deliberately refresh the public snapshot:

```bash
python scripts/prepare_race_replay.py
```

The importer is paced/resumable, checks response session/driver scope and caches raw source responses under `.cache/race-replay-sources`. That cache is excluded from the distributed project. Reusing it does not make fresh network requests. After a refresh, restart the server and reload the browser; re-audit changed counts/hashes. No import runs automatically at app startup.

## Verification boundary

See `QA-REPORT.md` and the new `qa/race-replay-pytest-results.xml`, `qa/fleet-model-results.json` and `qa/fleet-browser-results.json`. Tests cover archive hashes/scopes, every driver endpoint, independent stream identities, comparison deltas, shared-clock brackets/ranks, 22,080 sampled driver frames, explicit gap/outlier fixtures, four/20-car rendering, actual 3D marker selection, audio output and silence, all controls, mobile/theatre, preserved A/B analysis and WebGL recovery. No live private provider account validation is implied.
