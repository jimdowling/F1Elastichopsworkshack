# PITLANE — dashboard tour & four ideas to try

Open the live preview. The default is the **2023–2024 historical dashboard**; the four original experiments remain under **Experiments**, explicitly scoped to the **2024 Dutch GP**. No event credentials are needed to explore the included public archive.

## New in 2.2 / the multi-car demo

1. Open **Ghost Lap → 4-car ghosts**. The paused 24-second preview follows VER with the other ghosts ahead. Toggle a car, follow PIA, then choose Overview. Explain that these are different recorded laps aligned for comparison.
2. Switch to **20-car race replay**. All cars now use the same real session clock, initially around lap eight. VER's recorded lead here contrasts with NOR's faster independent ghost lap—proof these are different analyses.
3. Show All 20 / four-driver filtering, click a car marker to chase, use **NOR lap 29** to inspect the pit phase, and scrub the shared time. Rank comes from as-of updates; XY distance is not an official timing gap.
4. Expand, enable synthesized sound, and then demonstrate the same data in 2D/mobile. Missing samples stay unavailable rather than becoming a guessed animation.
5. **Two-car detail** preserves the original A/B experiment below. See `docs/MULTI-CAR-REPLAY.md` for the complete methodology. The public position archive is bundled—no credentials are needed for this demo.

## New in 2.1 / Connections

Open **Connections** to see server-side credential readiness without exposing any keys. When credentials arrive, follow [docs/CLOUD-SETUP.md](docs/CLOUD-SETUP.md): create the private `.env`, test the event tables, explicitly activate Hopsworks data, preview/publish/verify one isolated Hopsworks batch, then activate Hopsworks for the dashboard pace panel. Missing batches and connection failures are visible; the app never silently falls back to public data.

Before credentials, buttons remain safely disabled. No provider accounts were connected for this delivery. After configuration, native Hopsworks telemetry can be inspected for one driver/lap at a time. Historical timing and the four original 3D/ML experiments keep their public Dutch GP scope; this is not a claim that every original model has moved to cloud execution.

## A five-minute dashboard tour

1. **Dashboard · 2024 R15:** start with Norris's Dutch GP win, the podium and the championship picture. Switch to 2023 or choose **Season end** to show that the archive selection genuinely recalculates the standings.
2. **Driver standings / Constructor standings:** sort the table, inspect evolution and the round matrix. The points include Sprint and respect the selected round cutoff. Try Driver statistics → aggregate driver/constructor comparisons and download the CSV.
3. **Historical timing:** return to 2024 R15, play the race or scrub to lap 40, then open Norris's lap evidence. Say “historical timing replay,” not “live timing.” The final frame switches explicitly to official classification.
4. **Race pace:** select several drivers, change the pit/outlier filter and compare distributions, positions and speed traps. Point to the persisted feature read-back. This is retrospective observed pace, not a fuel-corrected estimate.
5. **Tyres / Pit-lane / Weather / Race control:** show stint lengths, lane visits, Race versus Qualifying weather, and a searchable race-control message. Pit-lane duration is not stationary crew service time.
6. **Coverage & schema:** show 46 events / 51,108 Race laps and the five-table mapping. Preview actual records, export JSON, copy the Hopsworks query template and build/read back local race features. Disclose the active source/feature modes. Default mode is SQLite; configured cloud mode shows native-source/read-back evidence.
7. **Ghost Lap:** switch to the original Dutch GP 3D experience, enable sound explicitly and try a chase camera. Its scope remains fixed even after changing the historical dashboard selectors.

For the complete feature adaptation, methodology, known gaps and API contract, read [docs/DASHBOARD-GUIDE.md](docs/DASHBOARD-GUIDE.md). Dark/light themes, collapsed navigation and mobile layouts are functional.

### The honest hackathon story

“The public archive lets us explore the same kinds of seasons, sessions, laps, results, weather and telemetry fields described by the event schema. We can choose one focused experience, then configure the included native adapters and verify a real Hopsworks event-table query and feature-group read-back against our project. This local prebuild is not evidence that those cloud steps have happened.”

The advertised 57M telemetry corpus is **not** loaded: the dashboard telemetry export is four interpolated Dutch GP laps. The original ML retains its one-race holdout. Confirm the event-day-code rule before reusing any prebuilt repository.

---

## The shortlist

| Idea | The audience moment | My assessment |
|---|---|---|
| **Ghost Lap** | Follow 3D open-wheel cars around the circuit and hear the recorded RPM shape their engine sound. | **Strongest immediate visual impact.** |
| **Pitwall Sandbox** | Someone picks a pit lap and tyre; the entire scenario recalculates. | **Best collaborative what-if demo**, but the assumptions need careful explanation. |
| **Pace Detective** | Click a surprising real lap and show exactly which earlier laps informed the expectation. | **Safest small hack-night project**, with a clear Hopsworks story. |
| **Driver DNA** | Hide the identity, get an audience vote, then reveal the actual driver and model vote. | **Best interactive reveal** and a useful classification discussion. |

The assessments above are recommendations, not official judging scores. You can star ideas in the app; **Compare ideas** shows their intended platform roles, risks, and relative event-build effort.

---

## 01 / Ghost Lap
### Question: Where did the lap go?

**Try it — about 90 seconds**

1. Open **Ghost Lap**, starting with **NOR vs VER**. The default is a paused 3D chase view at the start line.
2. Click **Enable sound**, keep the volume comfortable, then press **Play** at **1×**. Hear RPM rise and gear changes interrupt the synthesized engine tone.
3. Switch between **Chase NOR**, **Chase VER**, and **Circuit orbit**. In orbit, drag to rotate and scroll/pinch to zoom. The foreground audio follows the chase selection; orbit uses Ghost A.
4. Click **Expand** for the full theatre view and live speed/gear/RPM instruments. Press **Escape** to return. Use **4× / 8×** for a quicker lap.
5. Pause near a braking zone: sound stops. Inspect **Speed**, **Throttle**, **Brake**, or **Time delta**, and click the trace to scrub the replay.
6. Swap drivers, or select LEC/PIA, to show that this is not one canned animation. Try **2D map** to demonstrate the original low-graphics fallback.

**What actually happens:** recorded car and position samples are interpolated onto a common normalized-distance grid. A lazy-loaded Three.js renderer follows those XY trajectories with procedural open-wheel models. Web Audio synthesizes two engine voices from real RPM, throttle and gear, with a limiter, volume control and camera-dependent mixing. Elapsed-time replay uses each lap's own time-to-position relationship. The delta trace is the difference between elapsed times at approximately equal lap distance.

**What to point out:** on this snapshot, Norris's selected fastest clean race lap is **1:13.817**, and Verstappen's is **1:14.752**—a **0.935-second** finish-line difference.

**The honesty line:** those were different race laps and tyre ages. Fuel, traffic, and track conditions differ. The 3D road, flat track elevation, scenery, car models, inferred steering and engine sound are illustrative—not a surveyed track, official recording, or drivable vehicle-physics simulator. This demonstrates recorded telemetry, not a controlled experiment in driving skill. Distance is approximated from integrated measured speed, so fine-grained corner attribution is approximate.

**Local end-to-end path:** observations → `ghost_features` → persisted read-back → replay API → 3D cars + engine audio + live instruments + synchronized SVG charts / 2D map.

**Event-sized version:** one driver pair, one selected lap each, one replay, one speed/delta chart. Hopsworks event tables supply the records; a Hopsworks feature group stores useful aligned/aggregated telemetry features. This exploratory build includes a 3D renderer, but leave a drivable game/physics engine out of the two-hour event scope.

---

## 02 / Pitwall Sandbox
### Question: What would changing the pit stop do in a simple race model?

**Try it — about 90 seconds**

1. Open **Pitwall Sandbox** and select **LEC**.
2. Click **Restore actual strategy**. The modeled change should return to **0.00 seconds**.
3. Drag the stop earlier and later. Watch the modeled race-time change and cumulative delta.
4. Click **Try this window** to use the lowest point of the current 45-candidate scan.
5. Adjust the **tyre-age effect** or **pit loss** to show how assumptions change the answer.
6. Try the same compound as the starting stint: the app flags the dry-race legality issue. Long stints outside observed tyre-age coverage are also flagged.

**What actually happens:** a ridge regression calibrates race-lap, tyre-age, compound, and driver offsets from real eligible laps. The simulator compares a proposed one-stop schedule with the modeled actual schedule, then anchors the difference to the observed race time. Pit loss is estimated from pit-in/out excess time against fitted clean pace.

At the default calibration, the lowest HARD-tyre stop in the scan is around **lap 32**. For Leclerc, moving from the observed lap-24 stop to that modeled window produces about **2.72 seconds** of modeled improvement. This is an illustration of the model, **not a claim that Ferrari should actually have made that call**.

**The honesty line:** no rival reactions, traffic dynamics, safety cars, causal identification, or out-of-sample strategy validation. Fuel and tyre effects are confounded. “Best” means best among the scanned alternatives under these assumptions, not globally optimal racing strategy.

**Local end-to-end path:** observations → `strategy_features` → persisted read-back → calibrated simulator → scenario API → pit-window curve, tyre timelines, cumulative delta.

**Event-sized version:** one driver, one-stop alternatives, two or three explicit assumptions, and a transparent sensitivity chart. Never promise a genuine pit-strategy optimizer from this small dataset and time budget.

---

## 03 / Pace Detective
### Question: Which laps were unexpectedly slow relative to recent pace?

**Try it — about 90 seconds**

1. Open **Pace Detective** and read the two test-error cards.
2. Switch between **Rolling baseline** and **Random forest**.
3. Select different drivers; the grey line is actual eligible pace, and the blue line is the selected expectation on validation/test rows.
4. Click a row in **Laps worth a closer look**.
5. Read the feature evidence: previous three-lap median/spread, previous lap time, tyre state, and the last lap included in history.
6. Raise **MIN Δ** to narrow the investigation.

**What actually happens:** each feature row uses only earlier eligible laps from the same uninterrupted segment. History resets around pit stops, compound/stint changes, interruptions, and gaps. The baseline is a previous-three-lap median. A real random forest is trained on earlier race laps and evaluated on later ones.

**Actual result:**

- Baseline test MAE: **0.361525 s**.
- Forest test MAE: **0.412548 s**.
- Same **280 held-out rows** for both.
- The forest is about **14.1% worse**, and the app explicitly says so.

A useful demo is ZHO, lap 64, under the forest: an observed **79.340 s** lap versus roughly **76.481 s** expected. The residual is evidence worth investigating, not proof of an incident.

**The honesty line:** retrospective clean-lap evaluation in one race, not unrestricted live forecasting. The green/non-pit eligibility is known after a lap completes. A residual is not a causal explanation.

**Local end-to-end path:** observations → `pace_features` → persisted read-back → train/score/evaluate → searchable `pace_results` → evidence dashboard.

**Event-sized version:** rolling baseline first; meaningful Feature Group read-back; one dashboard view with actual/expected pace and a residual table. Add the forest only after the pipeline and demo work.

---

## 04 / Driver DNA
### Question: Can a telemetry signature reveal the driver–car pairing?

**Try it — about 90 seconds**

1. Open **Driver DNA** without revealing the identity.
2. Ask the audience to choose **NOR, VER, LEC, or PIA** from the speed trace and signature.
3. Click the chosen driver. The app reveals the real identity, the audience's result, and the model's result.
4. Show the vote bars. They are forest votes, not calibrated probabilities.
5. Click **Next blind lap** and repeat, or use **Let the model make the call**.
6. Show the confusion matrix: where does the model fail?

**What actually happens:** 12 aggregated car-telemetry features feed a fitted random forest classifier. Driver IDs and lap numbers are excluded from prediction inputs. Entire later laps are held out; telemetry samples from a single lap are not randomly scattered across train/test sets.

**Actual result:** **51 correct out of 60 test laps (85%)**, versus a balanced four-class chance baseline of 25%. Training uses 187 laps up to lap 50; 28 intervening laps are reserved; test laps begin at lap 58.

The confusion matrix shows Norris frequently being classified as Piastri. Both drive McLarens. That is an interesting clue to the model's limitations, not something to hide.

**The honesty line:** “DNA” is a metaphor. This model recognizes same-race driver–car combinations, influenced by car characteristics, tyre state, DRS, and race conditions—not universal individual driving style. Sixty held-out laps are a small evaluation set.

**Local end-to-end path:** real telemetry → `dna_features` → persisted read-back → classifier → hidden-label challenge API → prediction/reveal and measured confusion matrix.

**Event-sized version:** four classes, a handful of honest summary features, one held-out-lap challenge, and a clear model card. This is more memorable than presenting an accuracy number alone.

---

## Show the plumbing, not just the screen

Click **Pipeline**:

- Seven real processing stages with measured durations.
- Four populated local feature tables (schema v1).
- CSV downloads for each group.
- A **Re-run local pipeline** button that verifies data and refits/evaluates the models.

Click **Data & provenance**:

- 1,425 real lap rows; 275 telemetry laps; **zero synthetic race observations**.
- OpenF1/Jolpica sources and SHA-256 checksums.
- The distinction between observations, interpolation, derived features, and simulation.
- The explicit infrastructure boundary: **SQLite substitutes for Hopsworks here**.

Optional cloud publishing bridges are in the source package. They have offline contract/dry-run checks, not successful live-account tests. They do not automatically switch the app to cloud search or inference.

## My recommendation

- **Choose Ghost Lap** if your priority is an immediate, understandable visual wow.
- **Choose Driver DNA** if you want the room to participate and remember the reveal.
- **Choose Pace Detective** if you want the most defensible, tightly scoped two-hour implementation.
- **Choose Pitwall** if you enjoy explaining assumptions and sensitivity—not if you need to claim a validated predictive strategy.

These prototypes are for exploration. The event's no-prebuilt-submission rule still applies; confirm reuse boundaries with the organizers.
