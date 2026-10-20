"""Shared-clock multi-car race replay for any race, from f1_car_location + f1_car_telemetry.

One Query Service read per table for the race session (all drivers), then one actual
location record per 0.5 s bin and one car record per 1 s bin per driver. No invented
samples; interpolation and gap handling are a disclosed browser visualization step.
The compact per-driver series are cached in RonDB (app_pitlane_cache).
"""
from datetime import datetime, timezone
from threading import RLock
import math
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

router = APIRouter(prefix='/api/replay', tags=['Multi-car race replay'])
LOCKS = {}; LOCK = RLock()
RANGES = {'speed': (0, 400), 'rpm': (0, 15000), 'throttle': (0, 100), 'brake': (0, 100), 'n_gear': (0, 8)}


def iso(t): return datetime.fromtimestamp(t, timezone.utc).isoformat()


def compact(df, fields, bin_seconds, origin, start, end):
    """Keep the actual record nearest each bin centre; missing XY rows cannot be placed."""
    rel = df['t'].to_numpy() - origin
    keep = (rel >= start) & (rel <= end)
    valid = np.ones(len(df), bool)
    for k in fields:
        v = df[k].to_numpy(float)
        valid &= ~np.isinf(v)
        if k in ('x', 'y'): valid &= ~np.isnan(v)
    invalid = int((keep & ~valid).sum())
    sub = df[keep & valid].assign(rel=rel[keep & valid])
    b = np.floor(sub['rel'] / bin_seconds); err = (sub['rel'] - (b + .5) * bin_seconds).abs()
    sub = sub.assign(b=b, err=err).sort_values(['b', 'err']).drop_duplicates('b').sort_values('rel')
    out = {'time': [round(float(t), 6) for t in sub['rel']]}
    for k in fields:
        out[k] = [None if (isinstance(v, float) and math.isnan(v)) else (int(v) if float(v).is_integer() else float(v)) for v in sub[k].to_numpy(float)]
    return out, invalid


def build(season, rnd):
    from .hopsdata import archive, hops
    arch = archive(); raw = arch.races.get((season, rnd))
    if not raw or not raw['laps']: raise HTTPException(404, 'This event has no Race session data; no positions are invented.')
    key = raw['session']['session_key']; origin = raw['clock_origin_epoch']; event = raw['event']
    results = sorted([r for r in arch.catalog['results'] if (r['season'], r['round_number'], r['session_name']) == (season, rnd, 'Race')], key=lambda r: r['position'] or 99)
    start = max(0, raw['race_start_epoch'] - origin - 3); end = max(l['lap_end_s'] for l in raw['laps'] if l['lap_end_s'] is not None) + 3
    data = hops(); loc = data.car_location(key); car = data.car_telemetry(key, [r['driver_number'] for r in results])
    meta = {'schema_version': 2, 'session_key': key, 'season': season, 'round_number': rnd, 'session_name': 'Race', 'event_name': event['event_name'], 'circuit': event.get('location'),
            'clock_origin_epoch': origin, 'clock_origin_utc': iso(origin), 'start_s': round(start, 6), 'end_s': round(end, 6), 'fetched_at': iso(datetime.now(timezone.utc).timestamp()),
            'drivers': [], 'synthetic_observations': 0, 'source': 'f1_car_location + f1_car_telemetry via the Hopsworks Query Service; race timing/ranks/stints from the archive feature groups',
            'cadence': {'location_bin_s': .5, 'car_data_bin_s': 1}, 'max_interpolation_gap_s': 2.5,
            'notes': ['All cars use the same session clock; this is not an alignment of independent fastest laps.',
                      'Each retained sample is an actual record with its actual timestamp, not a synthetic uniform sample.',
                      'Short intervals between samples are interpolated for display. Missing/stale/outlier intervals are hidden, not filled with invented motion.',
                      'Recorded XY drives placement. Elevation is flattened; road width, scenery, cars, steering and audio remain illustrative.',
                      'Out-of-range telemetry values are unavailable for displayed instruments/interpolation; invalid throttle is not silently clamped into a claimed measurement.',
                      'Position ranks are last recorded as of the shared time. Physical XY separation is derived and is not an official race interval.'],
            'errors': []}
    series = {}
    for r in results:
        code = r['driver_code']; number = r['driver_number']
        location, bad_xy = compact(loc[loc.driver_number == number], ['x', 'y', 'z'], .5, origin, start, end)
        cars, bad_car = compact(car[car.driver_number == number], ['speed', 'rpm', 'throttle', 'brake', 'n_gear', 'drs'], 1, origin, start, end)
        if not location['time']:
            meta['errors'].append({'driver_code': code, 'error': 'No recorded XY samples in the race window'}); continue
        series[code] = {'driver_code': code, 'driver_number': number, 'location': location, 'car_data': cars}
        meta['drivers'].append({'driver_code': code, 'driver_number': number, 'full_name': r['full_name'], 'team_name': r['team_name'], 'team_id': r['team_id'],
                                'location_samples': len(location['time']), 'car_samples': len(cars['time']), 'first_s': location['time'][0], 'last_s': location['time'][-1],
                                'invalid_location_rows': bad_xy, 'invalid_car_rows': bad_car,
                                'out_of_range_channels': {k: sum(v is not None and not lo <= v <= hi for v in cars[k]) for k, (lo, hi) in RANGES.items()},
                                'max_location_gap_s': round(max([b - a for a, b in zip(location['time'], location['time'][1:])] + [0]), 6)})
    meta['driver_count'] = len(meta['drivers']); meta['location_samples'] = sum(d['location_samples'] for d in meta['drivers']); meta['car_samples'] = sum(d['car_samples'] for d in meta['drivers'])
    return meta, series


def replay(season, rnd):
    """Manifest + per-driver series, from RonDB when cached, else built and stored."""
    from .appdb import store
    db = store(); race_key = f'{season}-{rnd:02d}'
    with LOCK: lock = LOCKS.setdefault(race_key, RLock())
    with lock:
        built = {}
        def manifest():
            meta, series = build(season, rnd); built.update(series); return meta
        meta = db.cached(f'replay:{race_key}:manifest', manifest)
        if built:
            for code, payload in built.items(): db.cached(f'replay:{race_key}:{code}', lambda p=payload: p)
        return meta


def driver_series(season, rnd, code):
    from .appdb import store
    meta = replay(season, rnd)
    if not any(d['driver_code'] == code for d in meta['drivers']): raise HTTPException(404, 'This driver has no recorded positions in this race. Missing coverage is not fabricated.')
    race_key = f'{season}-{rnd:02d}'
    def rebuild():
        _, series = build(season, rnd); return series[code]
    return store().cached(f'replay:{race_key}:{code}', rebuild)


@router.get('/race')
def race(season: int = Query(2024, ge=2023, le=2024), round: int = Query(15, ge=1, le=24)):
    from .hopsdata import archive
    m = replay(season, round); arch = archive(); raw = arch.races[(season, round)]
    fields = ['id', 'driver_code', 'lap_number', 'lap_start_s', 'lap_end_s', 'lap_duration_ms', 'compound', 'tyre_life', 'is_pit_in_lap', 'is_pit_out_lap']
    results = [r for r in arch.catalog['results'] if (r['season'], r['round_number'], r['session_name']) == (season, round, 'Race')]
    return {'manifest': m, 'results': results, 'laps': [{k: l.get(k) for k in fields} for l in raw['laps']], 'positions': raw['positions'], 'stints': raw['stints'],
            'race_control': raw['race_control'], 'source_mode': 'hopsworks-synchronized',
            'scope_note': f"Same-time recorded positions for the {season} {raw['event']['event_name']}. Not the independent ghost laps and not live timing."}


@router.get('/driver/{code}')
def driver(code: str, season: int = Query(2024, ge=2023, le=2024), round: int = Query(15, ge=1, le=24)):
    if not code.isalpha() or len(code) > 4: raise HTTPException(404, 'Unknown driver code')
    return JSONResponse(driver_series(season, round, code.upper()), headers={'X-Pitlane-Source': 'hopsworks-recorded-session', 'Cache-Control': 'private, max-age=3600'})
