"""Read the F1 archive from Hopsworks feature groups through the Hopsworks Query Service.

Every read is `fg.select(...).filter(...).read()` on the python engine, so it is
served by the Hopsworks Feature Query Service (Arrow Flight, "Flyingduck") with
the filter pushed down; nothing goes through Trino and nothing is bundled.

The feature groups are read from F1_FEATURE_STORE when it is set; otherwise from
the project's own feature store when it holds them, else from the store shared
with the project, hopsworks_default_featurestore. Jolpica-derived
groups (f1_races, f1_race_results, ...) are keyed by season/round; OpenF1-derived
groups (f1_laps, f1_car_telemetry, ...) by session_key.
"""
from collections import defaultdict
from bisect import bisect_right
from datetime import datetime, timezone
from threading import RLock
import logging, math, os, time

import numpy as np
import pandas as pd

log = logging.getLogger('pitlane.hopsdata')
SHARED_FEATURE_STORE = 'hopsworks_default_featurestore'
# Resolved by HopsData.store() on first use; this is the name until then.
FEATURE_STORE = os.environ.get('F1_FEATURE_STORE', SHARED_FEATURE_STORE)
VERSION = int(os.environ.get('F1_FEATURE_VERSION', '1'))
SEASONS = [2023, 2024]
INT_FIELDS = {'position', 'grid', 'laps', 'car_number', 'fastest_lap_number', 'fastest_lap_rank', 'stint_number', 'lap_start', 'lap_end',
              'tyre_age_at_start', 'driver_number', 'lap_number', 'sector', 'rainfall', 'wind_direction', 'session_key', 'meeting_key', 'circuit_key', 'year'}


def epoch(value):
    """Naive feature-group timestamps are UTC."""
    if value is None or value is pd.NaT or (isinstance(value, float) and math.isnan(value)): return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None: ts = ts.tz_localize('UTC')
    return ts.timestamp()


def iso(value):
    t = epoch(value)
    return None if t is None else datetime.fromtimestamp(t, timezone.utc).isoformat().replace('+00:00', 'Z')


def plain(value, key=None):
    """pandas/numpy cell -> JSON value; NaN/NaT -> None; integral fields stay integers."""
    if value is None or value is pd.NA or value is pd.NaT: return None
    if isinstance(value, (pd.Timestamp, datetime)): return iso(value)
    if isinstance(value, np.ndarray): return [plain(v) for v in value.tolist()]
    if hasattr(value, 'item'): value = value.item()
    if isinstance(value, float):
        if not math.isfinite(value): return None
        if key in INT_FIELDS and value.is_integer(): return int(value)
    return value


def records(df):
    cols = list(df.columns)
    return [{c: plain(v, c) for c, v in zip(cols, row)} for row in df.itertuples(index=False, name=None)]


def ms_label(total_ms, winner_ms):
    """Jolpica-style classified time label: winner h:mm:ss.sss, others +gap."""
    if total_ms is None: return None
    if winner_ms is None or total_ms == winner_ms:
        s = total_ms / 1000; h = int(s // 3600); m = int(s % 3600 // 60)
        return f'{h}:{m:02d}:{s % 60:06.3f}'
    gap = (total_ms - winner_ms) / 1000
    return f'+{gap:.3f}' if gap < 60 else f'+{int(gap // 60)}:{gap % 60:06.3f}'


class HopsData:
    """One Hopsworks login and feature-store handle; all reads go through the Query Service."""

    def __init__(self):
        self.lock = RLock(); self.fs = None; self._project = None; self.groups = {}; self.reads = []

    def project(self):
        with self.lock:
            if self._project is None:
                import hopsworks
                self._project = hopsworks.login(engine='python')  # in a Hopsworks pod: JWT, no host/key needed
            return self._project

    def store(self):
        with self.lock:
            if self.fs is None: self.fs = self._resolve_store()
            return self.fs

    def _resolve_store(self):
        global FEATURE_STORE
        project = self.project()
        if 'F1_FEATURE_STORE' in os.environ: fs = project.get_feature_store(os.environ['F1_FEATURE_STORE'])
        else:
            fs = project.get_feature_store()
            if fs.get_feature_group('f1_races', version=VERSION) is None: fs = project.get_feature_store(SHARED_FEATURE_STORE)
        FEATURE_STORE = fs.name
        log.info('Reading F1 feature groups from %s', FEATURE_STORE)
        return fs

    def group(self, name):
        with self.lock:
            if name not in self.groups:
                fg = self.store().get_feature_group(name, version=VERSION)
                if fg is None: raise RuntimeError(f'Feature group {name} v{VERSION} is not available in {FEATURE_STORE}')
                self.groups[name] = fg
            return self.groups[name]

    def read(self, name, columns=None, where=None):
        """where(fg) -> hsfs Filter. Returns a pandas DataFrame read via the Query Service."""
        fg = self.group(name); started = time.perf_counter()
        query = fg.select(columns) if columns else fg.select_all()
        if where is not None: query = query.filter(where(fg))
        df = query.read(dataframe_type='pandas')
        self.reads.append({'feature_group': f'{name}_{VERSION}', 'rows': len(df), 'seconds': round(time.perf_counter() - started, 3)})
        return df

    # ---- bounded high-frequency reads (one session, explicit drivers) ----
    def car_telemetry(self, session_key, drivers):
        df = self.read('f1_car_telemetry', ['driver_number', 'date', 'speed', 'rpm', 'n_gear', 'throttle', 'brake', 'drs'],
                       lambda fg: (fg.session_key == int(session_key)) & fg.driver_number.isin([int(d) for d in drivers]))
        df['t'] = seconds_since(df['date'])
        return df

    def car_location(self, session_key, drivers=None):
        cond = (lambda fg: (fg.session_key == int(session_key)) & fg.driver_number.isin([int(d) for d in drivers])) if drivers else (lambda fg: fg.session_key == int(session_key))
        df = self.read('f1_car_location', ['driver_number', 'date', 'x', 'y', 'z'], cond)
        df['t'] = seconds_since(df['date'])
        return df


def seconds_since(ts_series):
    """Epoch seconds for a datetime column, independent of its resolution."""
    return pd.to_datetime(ts_series).dt.tz_localize(None).astype('datetime64[ns]').astype('int64') / 1e9


class Archive:
    """The 2023–2024 archive (calendar, classifications, race sessions) built from feature groups.

    Shapes match what the dashboard engine consumes: catalog, per-race payloads
    (laps/stints/positions/weather/race_control) and qualifying weather.
    """

    def __init__(self, data: HopsData):
        self.data = data; started = time.perf_counter()
        self.catalog = self._catalog()
        self.races, self.qualifying_weather, coverage = self._sessions()
        self.manifest = self._manifest(coverage, time.perf_counter() - started)
        log.info('Archive loaded in %.1fs: %d events, %d results', time.perf_counter() - started, len(self.catalog['events']), len(self.catalog['results']))

    def _catalog(self):
        d = self.data
        races = d.read('f1_races', where=lambda fg: fg.season.isin(SEASONS)).sort_values(['season', 'round'])
        circuits = {r['circuit_id']: r for r in records(d.read('f1_circuits'))}
        events = []
        for r in records(races):
            c = circuits.get(r['circuit_id'], {}); race_t = epoch(r['race_ts'])
            calendar = []
            for key, label in [('fp1_ts', 'Practice 1'), ('fp2_ts', 'Practice 2'), ('fp3_ts', 'Practice 3'), ('qualifying_ts', 'Qualifying'), ('sprint_ts', 'Sprint'), ('race_ts', 'Race')]:
                if r.get(key): calendar.append({'name': label, 'date': r[key][:10], 'time': r[key][11:19] + 'Z'})
            events.append({'id': f"{r['season']}-{r['round']}", 'season': r['season'], 'round_number': r['round'], 'event_name': r['race_name'], 'circuit_id': r['circuit_id'],
                           'circuit_name': c.get('circuit_name'), 'country': c.get('country'), 'location': c.get('locality'), 'latitude': c.get('lat'), 'longitude': c.get('lon'),
                           'date': r['race_ts'][:10] if r.get('race_ts') else None, 'time': r['race_ts'][11:19] + 'Z' if r.get('race_ts') else None,
                           'race_epoch': race_t, 'qualifying_epoch': epoch(r.get('qualifying_ts')), 'calendar_sessions': calendar, 'source': 'f1_races + f1_circuits'})
        event_by = {(e['season'], e['round_number']): e for e in events}
        drivers = {}
        for r in records(d.read('f1_drivers')):
            drivers[r['driver_id']] = {'driver_id': r['driver_id'], 'code': r.get('driver_code') or (r.get('family_name') or r['driver_id'])[:3].upper(),
                                       'name': f"{r.get('given_name')} {r.get('family_name')}", 'first_name': r.get('given_name'), 'last_name': r.get('family_name'),
                                       'nationality': r.get('nationality'), 'date_of_birth': r.get('date_of_birth') if isinstance(r.get('date_of_birth'), str) else (str(r['date_of_birth'])[:10] if r.get('date_of_birth') else None)}
        teams = {r['constructor_id']: {'team_id': r['constructor_id'], 'name': r['constructor_name'], 'nationality': r.get('nationality')} for r in records(d.read('f1_constructors'))}
        results = []
        for name, kind in [('f1_race_results', 'Race'), ('f1_qualifying_results', 'Qualifying'), ('f1_sprint_results', 'Sprint')]:
            rows = records(d.read(name, where=lambda fg: fg.season.isin(SEASONS)))
            winners = {}
            for r in rows:
                if r.get('position') == 1: winners[(r['season'], r['round'])] = r.get('total_race_time_ms')
            for r in rows:
                key = (r['season'], r['round'])
                if key not in event_by: continue
                drv = drivers.get(r['driver_id']) or {'code': r['driver_id'][:3].upper(), 'name': r['driver_id']}
                team = teams.get(r['constructor_id']) or {'name': r['constructor_id']}
                total = r.get('total_race_time_ms'); total = None if total is None else int(round(total))
                results.append({'id': f"{r['season']}-{r['round']}-{kind}-{r['driver_id']}", 'season': r['season'], 'round_number': r['round'], 'session_name': kind,
                                'event_name': event_by[key]['event_name'], 'driver_id': r['driver_id'], 'driver_code': drv['code'], 'full_name': drv['name'],
                                'driver_number': r.get('car_number'), 'team_id': r['constructor_id'], 'team_name': team['name'], 'position': r.get('position'),
                                'position_text': r.get('position_text') if kind != 'Qualifying' else (str(r['position']) if r.get('position') else None),
                                'points': float(r.get('points') or 0), 'grid_position': r.get('grid'), 'laps': r.get('laps'), 'status': r.get('status'),
                                'classified_time_ms': total, 'time_label': ms_label(total, winners.get(key)) if kind != 'Qualifying' else None,
                                'fastest_lap_ms': None if r.get('fastest_lap_time_ms') is None else int(round(r['fastest_lap_time_ms'])),
                                'fastest_lap_rank': r.get('fastest_lap_rank'), 'fastest_lap_number': r.get('fastest_lap_number'),
                                'fastest_lap_avg_kph': r.get('fastest_lap_avg_speed_kph'),
                                'q1_ms': None if r.get('q1_ms') is None else int(round(r['q1_ms'])), 'q2_ms': None if r.get('q2_ms') is None else int(round(r['q2_ms'])),
                                'q3_ms': None if r.get('q3_ms') is None else int(round(r['q3_ms'])), 'source': name})
        # Official standings after each season's last round (used for final tie-break ordering).
        official = []
        for name, kind, key in [('f1_driver_standings', 'driver', 'driver_id'), ('f1_constructor_standings', 'constructor', 'constructor_id')]:
            df = d.read(name, where=lambda fg: fg.season.isin(SEASONS))
            last = df.groupby('season')['round'].transform('max')
            for r in records(df[df['round'] == last]):
                official.append({'season': r['season'], 'round_number': r['round'], 'kind': kind, 'entity_id': r[key], 'position': r['position'], 'points': float(r['points'] or 0), 'wins': int(r['wins'] or 0)})
        race_rows = {(r['season'], r['round_number'], r['driver_id']): r for r in results if r['session_name'] == 'Race'}
        pits = []
        for p in records(d.read('f1_pit_stops', where=lambda fg: fg.season.isin(SEASONS))):
            ref = race_rows.get((p['season'], p['round'], p['driver_id']))
            if not ref: continue
            pits.append({'id': f"{p['season']}-{p['round']}-{p['driver_id']}-{p['stop']}", 'season': p['season'], 'round_number': p['round'], 'event_name': ref['event_name'],
                         'session_name': 'Race', 'driver_id': p['driver_id'], 'driver_code': ref['driver_code'], 'team_id': ref['team_id'], 'team_name': ref['team_name'],
                         'lap_number': p['lap'], 'stop': p['stop'], 'duration_s': None if p.get('duration_ms') is None else p['duration_ms'] / 1000,
                         'source_local_time': p.get('local_time_of_day'), 'source': 'f1_pit_stops: pit-lane duration; not stationary wheel-change time'})
        # Map OpenF1 sessions to (season, round) by date, as the original importer did.
        sessions = []
        srows = records(d.read('f1_sessions', where=lambda fg: fg.year.isin(SEASONS) & fg.session_name.isin(['Race', 'Qualifying'])))
        for s in srows:
            start = epoch(s['date_start']); best = None
            for e in events:
                if e['season'] != s['year']: continue
                expected = e['race_epoch'] if s['session_name'] == 'Race' else (e['qualifying_epoch'] or e['race_epoch'])
                if expected is None or start is None: continue
                gap = abs(start - expected) / 86400
                if gap <= 2 and (best is None or gap < best[0]): best = (gap, e)
            if not best: continue
            e = best[1]
            sessions.append({**s, 'id': f"{s['year']}-{e['round_number']}-{s['session_name']}", 'season': s['year'], 'round_number': e['round_number'],
                             'event_name': e['event_name'], 'session_date': s['date_start'], 'source': 'f1_sessions'})
        for s in sessions:
            if s['session_name'] == 'Race': event_by[(s['season'], s['round_number'])]['race_session_key'] = s['session_key']
        return {'schema_version': 2, 'seasons': SEASONS, 'events': events, 'drivers': list(drivers.values()), 'teams': list(teams.values()), 'results': results,
                'official_standings': official, 'pit_stops': pits, 'sessions': sessions}

    def session_key(self, season, round_number, name='Race'):
        s = next((s for s in self.catalog['sessions'] if s['season'] == season and s['round_number'] == round_number and s['session_name'] == name), None)
        return None if s is None else s['session_key']

    def _sessions(self):
        d = self.data; cat = self.catalog
        race_sessions = [s for s in cat['sessions'] if s['session_name'] == 'Race']
        quali_sessions = [s for s in cat['sessions'] if s['session_name'] == 'Qualifying']
        race_keys = [s['session_key'] for s in race_sessions]; all_keys = race_keys + [s['session_key'] for s in quali_sessions]
        by_session = lambda df: {k: g for k, g in df.groupby('session_key')}
        laps = by_session(d.read('f1_laps', ['session_key', 'driver_number', 'lap_number', 'date_start', 'lap_duration', 'duration_sector_1', 'duration_sector_2', 'duration_sector_3',
                                             'i1_speed', 'i2_speed', 'st_speed', 'is_pit_out_lap'], lambda fg: fg.session_key.isin(race_keys)))
        stints = by_session(d.read('f1_stints', ['session_key', 'driver_number', 'stint_number', 'lap_start', 'lap_end', 'compound', 'tyre_age_at_start'], lambda fg: fg.session_key.isin(race_keys)))
        positions = by_session(d.read('f1_track_positions', ['session_key', 'driver_number', 'date', 'position'], lambda fg: fg.session_key.isin(race_keys)))
        weather = by_session(d.read('f1_weather', ['session_key', 'date', 'air_temperature', 'track_temperature', 'humidity', 'pressure', 'wind_speed', 'wind_direction', 'rainfall'],
                                    lambda fg: fg.session_key.isin(all_keys)))
        controls = by_session(d.read('f1_race_control', ['session_key', 'date', 'seq', 'category', 'flag', 'scope', 'sector', 'driver_number', 'lap_number', 'message'],
                                     lambda fg: fg.session_key.isin(race_keys)))
        empty = pd.DataFrame()
        event_by = {(e['season'], e['round_number']): e for e in cat['events']}
        races = {}; coverage = []; qual_weather = {}
        for s in race_sessions:
            y, r, key = s['season'], s['round_number'], s['session_key']; event = event_by[(y, r)]
            results = [x for x in cat['results'] if x['season'] == y and x['round_number'] == r]
            mapping = {x['driver_number']: x for x in results if x['session_name'] == 'Qualifying'}
            mapping.update({x['driver_number']: x for x in results if x['session_name'] == 'Race'})
            origin = epoch(s['date_start'])
            lap_df = laps.get(key, empty)
            # A lap start equal to the session start is a filled-in null (no lap can start at the scheduled time), so treat it as unknown.
            if len(lap_df): lap_df = lap_df.assign(date_start=lap_df['date_start'].where(seconds_since(lap_df['date_start']) != origin))
            starts = [epoch(v) for v in lap_df.get('date_start', [])]
            starts = [v for v in starts if v is not None]; actual_start = min(starts) if starts else origin
            base = {'season': y, 'round_number': r, 'event_name': event['event_name'], 'session_name': 'Race'}
            pos_rows = []; by_driver = defaultdict(list)
            for p in records(positions.get(key, empty).sort_values('date') if key in positions else empty):
                ref = mapping.get(p['driver_number']); t = epoch(p['date'])
                if not ref or t is None: continue
                pos_rows.append({'driver_code': ref['driver_code'], 'driver_number': p['driver_number'], 'position': p['position'], 'session_time_s': round(t - origin, 3), 'date': p['date']})
                by_driver[p['driver_number']].append((t, p['position']))
            stint_rows = []
            for st in records(stints.get(key, empty).sort_values(['driver_number', 'stint_number']) if key in stints else empty):
                ref = mapping.get(st['driver_number'])
                if not ref: continue
                stint_rows.append({**base, 'driver_code': ref['driver_code'], 'team_id': ref['team_id'], 'driver_number': st['driver_number'], 'stint_number': st['stint_number'],
                                   'lap_start': st['lap_start'], 'lap_end': st.get('lap_end'), 'compound': st.get('compound') or 'UNKNOWN', 'tyre_age_at_start': st.get('tyre_age_at_start'), 'source': 'f1_stints'})
            pit_set = {(p['driver_code'], p['lap_number']) for p in cat['pit_stops'] if p['season'] == y and p['round_number'] == r}
            lap_rows = []
            for l in records(lap_df.sort_values(['driver_number', 'lap_number']) if key in laps else empty):
                ref = mapping.get(l['driver_number'])
                if not ref or l.get('lap_number') is None: continue
                n = l['driver_number']; lap = l['lap_number']; start = epoch(l.get('date_start')); duration = l.get('lap_duration')
                end = start + duration if start is not None and duration is not None else None
                stint = next((x for x in stint_rows if x['driver_number'] == n and x['lap_start'] is not None and x['lap_start'] <= lap <= (x['lap_end'] or 999)), None)
                posrows = by_driver.get(n, []); idx = bisect_right([q[0] for q in posrows], end) - 1 if end is not None else -1
                age = None if stint is None or stint['tyre_age_at_start'] is None else stint['tyre_age_at_start'] + lap - stint['lap_start'] + 1
                ms = lambda v: None if v is None else int(round(v * 1000))
                lap_rows.append({**base, 'id': f"{y}-{r}-R-{ref['driver_code']}-{lap}", 'driver_code': ref['driver_code'], 'driver_number': n, 'team_name': ref['team_name'], 'team_id': ref['team_id'],
                                 'lap_number': lap, 'lap_duration_ms': ms(duration), 'duration_sector_1': ms(l.get('duration_sector_1')), 'duration_sector_2': ms(l.get('duration_sector_2')),
                                 'duration_sector_3': ms(l.get('duration_sector_3')), 'compound': stint['compound'] if stint else 'UNKNOWN', 'tyre_life': age,
                                 'stint': stint['stint_number'] if stint else None, 'is_pit_in_lap': (ref['driver_code'], lap) in pit_set, 'is_pit_out_lap': bool(l.get('is_pit_out_lap')),
                                 'track_status': None, 'position': posrows[idx][1] if idx >= 0 else None, 'date_start': l.get('date_start'),
                                 'lap_start_s': None if start is None else round(start - origin, 3), 'lap_end_s': None if end is None else round(end - origin, 3),
                                 'speed_trap_kph': l.get('st_speed'), 'i1_speed_kph': l.get('i1_speed'), 'i2_speed_kph': l.get('i2_speed'),
                                 'source': 'f1_laps + f1_stints + f1_track_positions; pit-in from f1_pit_stops'})
            weather_rows = [{**base, 'session_time_s': round(epoch(w['date']) - origin, 3), 'date': w['date'],
                             **{k: w.get(k) for k in ['air_temperature', 'track_temperature', 'humidity', 'pressure', 'wind_speed', 'wind_direction', 'rainfall']}, 'source': 'f1_weather'}
                            for w in records(weather.get(key, empty).sort_values('date') if key in weather else empty) if w.get('date')]
            control_rows = []
            for i, c in enumerate(records(controls.get(key, empty).sort_values(['date', 'seq']) if key in controls else empty)):
                t = epoch(c.get('date')); ref = mapping.get(c.get('driver_number'))
                if t is None: continue
                control_rows.append({**base, 'id': f'{y}-{r}-control-{i}', 'date': c['date'], 'session_time_s': round(t - origin, 3), 'driver_code': ref['driver_code'] if ref else None,
                                     **{k: c.get(k) for k in ['category', 'flag', 'scope', 'sector', 'lap_number', 'message']}, 'source': 'f1_race_control'})
            races[(y, r)] = {'schema_version': 2, 'event': event, 'session': s, 'race_start_epoch': actual_start, 'clock_origin_epoch': origin, 'laps': lap_rows,
                             'stints': stint_rows, 'positions': pos_rows, 'weather': weather_rows, 'race_control': control_rows}
            coverage.append({'season': y, 'round_number': r, 'race_session': True, 'laps': len(lap_rows), 'stints': len(stint_rows), 'positions': len(pos_rows),
                             'weather': len(weather_rows), 'race_control': len(control_rows)})
        for s in quali_sessions:
            y, r, key = s['season'], s['round_number'], s['session_key']; origin = epoch(s['date_start'])
            qual_weather[(y, r)] = [{'season': y, 'round_number': r, 'session_name': 'Qualifying', 'event_name': s['event_name'], 'session_time_s': round(epoch(w['date']) - origin, 3),
                                     'date': w['date'], **{k: w.get(k) for k in ['air_temperature', 'track_temperature', 'humidity', 'pressure', 'wind_speed', 'wind_direction', 'rainfall']},
                                     'source': 'f1_weather'} for w in records(weather.get(key, empty).sort_values('date') if key in weather else empty) if w.get('date')]
        seen = {(c['season'], c['round_number']) for c in coverage}
        coverage += [{'season': e['season'], 'round_number': e['round_number'], 'race_session': False} for e in cat['events'] if (e['season'], e['round_number']) not in seen]
        for c in coverage: c['qualifying_weather'] = len(qual_weather.get((c['season'], c['round_number']), []))
        return races, qual_weather, sorted(coverage, key=lambda c: (c['season'], c['round_number']))

    def _manifest(self, coverage, seconds):
        cat = self.catalog
        return {'schema_version': 2, 'fetched_at': datetime.now(timezone.utc).isoformat(), 'seasons': SEASONS, 'synthetic_observations': 0,
                'source': f'Hopsworks feature groups in {FEATURE_STORE}, read through the Hopsworks Query Service', 'feature_store': FEATURE_STORE,
                'load_seconds': round(seconds, 1), 'reads': list(self.data.reads),
                'events': len(cat['events']), 'results': len(cat['results']), 'pit_stops': len(cat['pit_stops']), 'sessions': len(cat['sessions']),
                'lap_rows': sum(c.get('laps', 0) for c in coverage), 'weather_rows': sum(c.get('weather', 0) for c in coverage),
                'race_control_rows': sum(c.get('race_control', 0) for c in coverage), 'qualifying_weather_rows': sum(c.get('qualifying_weather', 0) for c in coverage),
                'total_weather_rows': sum(c.get('weather', 0) + c.get('qualifying_weather', 0) for c in coverage),
                'position_rows': sum(c.get('positions', 0) for c in coverage), 'stint_rows': sum(c.get('stints', 0) for c in coverage), 'coverage': coverage, 'errors': [],
                'notes': ['Jolpica-derived feature groups supply calendar, classifications, standings and pit-lane timings; OpenF1-derived groups supply laps, stints, positions, weather, race control and car telemetry/location.',
                          'Sprint classifications supplement championship points; sprint qualifying is not loaded.',
                          'Pit durations are total recorded pit-lane durations, not stationary wheel-change times.',
                          'Positions in lap rows are the latest recorded position at each driver lap end; the raw position change timeline is retained.',
                          'Relative clocks use the session date_start; pre-session observations can have negative times.',
                          'weather_rows is Race only; total_weather_rows includes Qualifying.',
                          'Unknown stint boundaries and unavailable lap/sector durations remain null.',
                          'Telemetry and car location are read on demand for one race and a bounded set of drivers.']}


INSTANCE = None; LOCK = RLock()


def hops():
    global INSTANCE
    with LOCK:
        if INSTANCE is None: INSTANCE = HopsData()
        return INSTANCE


ARCHIVE = None


def archive():
    global ARCHIVE
    with LOCK:
        if ARCHIVE is None: ARCHIVE = Archive(hops())
        return ARCHIVE
