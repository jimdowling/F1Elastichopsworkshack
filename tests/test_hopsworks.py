"""Integration tests against the shared Hopsworks F1 feature groups (run inside a Hopsworks terminal or pod).

The archive is read through the Hopsworks Query Service; app tables use RonDB when MYSQL_* is set,
otherwise process memory. Values below are the published 2023–2024 results, so a regression in
reading or joining the feature groups shows up as a wrong championship, count or lab metric.
"""
from collections import Counter, defaultdict
import statistics
import numpy as np
import pytest

pytest.importorskip('hopsworks')
from fastapi.testclient import TestClient
from src.dashboard_api import get_dashboard
from src.engine import lab as get_lab, make_pace_features, DNA_FEATURES


@pytest.fixture(scope='session')
def db(): return get_dashboard()


@pytest.fixture(scope='session')
def lab(): return get_lab(2024, 15)


@pytest.fixture(scope='session')
def client():
    from app import app
    return TestClient(app)


def test_archive_counts_match_the_published_archive(db):
    m = db.manifest
    assert (m['events'], m['results'], m['pit_stops'], m['sessions']) == (46, 2078, 1737, 92)
    assert (m['lap_rows'], m['stint_rows'], m['position_rows'], m['race_control_rows']) == (51108, 2659, 22892, 4070)
    assert m['synthetic_observations'] == 0 and m['feature_store']
    assert Counter((r['season'], r['session_name']) for r in db.results) == Counter({(2023, 'Race'): 440, (2023, 'Qualifying'): 440, (2023, 'Sprint'): 120,
                                                                                   (2024, 'Race'): 479, (2024, 'Qualifying'): 479, (2024, 'Sprint'): 120})
    assert len({r['id'] for r in db.results}) == 2078


@pytest.mark.parametrize('year,maximum,champion,points,constructor,team_points', [(2023, 22, 'max_verstappen', 575, 'red_bull', 860), (2024, 24, 'max_verstappen', 437, 'mclaren', 666)])
def test_final_championship_matches_official_standings(db, year, maximum, champion, points, constructor, team_points):
    view = db.season_view(year, maximum)
    for kind, key in [('driver', 'driver_standings'), ('constructor', 'constructor_standings')]:
        official = {x['entity_id']: x for x in db.official if x['season'] == year and x['kind'] == kind}
        assert set(official) == {r['id'] for r in view[key]}
        for row in view[key]:
            assert row['points'] == official[row['id']]['points'] == row['official_final_points']
            assert row['position'] == official[row['id']]['position']
    assert (view['driver_standings'][0]['id'], view['driver_standings'][0]['points']) == (champion, points)
    assert (view['constructor_standings'][0]['id'], view['constructor_standings'][0]['points']) == (constructor, team_points)


@pytest.mark.parametrize('year,maximum', [(2023, 22), (2024, 24)])
def test_every_cutoff_sums_race_plus_sprint(db, year, maximum):
    for through in range(1, maximum + 1):
        view = db.season_view(year, through); drivers = defaultdict(float)
        for r in db.results:
            if r['season'] == year and r['round_number'] <= through and r['session_name'] in {'Race', 'Sprint'}: drivers[r['driver_id']] += r['points']
        assert {r['id']: r['points'] for r in view['driver_standings']} == dict(drivers)


def test_profiles_head_to_head_and_pole_start(db):
    d = db.driver_view(2024, 15, 'NOR')
    assert d['profile']['points'] == 225 and d['profile']['number'] == 4
    h = db.compare(2024, 15, 'NOR', 'PIA'); assert h['wins']['Race'] == {'a': 10, 'b': 5, 'paired': 15, 'tied': 0}
    for year, rnd in [(2023, 12), (2024, 14)]:
        assert db.classifications(year, rnd, 'Qualifying')[0]['driver_code'] == 'VER'
        assert next(x for x in db.classifications(year, rnd, 'Race') if x['grid_position'] == 1)['driver_code'] == 'LEC'


def test_position_asof_join(db):
    raw = db.race_raw(2024, 15)
    for l in raw['laps']:
        if l['lap_end_s'] is None: continue
        positions = [p for p in raw['positions'] if p['driver_code'] == l['driver_code'] and p['session_time_s'] <= l['lap_end_s'] + .000001]
        assert l['position'] == (max(positions, key=lambda p: p['session_time_s'])['position'] if positions else None)


def test_pace_features_round_trip_through_the_app_store(db):
    raw = db.race_raw(2024, 15); metrics, accepted = db.pace_rows(2024, 15, True, 1.07)
    stored = {r['id']: r for r in db.store.backend.get_pace(2024, 15)}
    for m in metrics:
        base = [l for l in raw['laps'] if l['driver_code'] == m['driver_code'] and l['lap_duration_ms'] and l['lap_number'] > 1 and not l['is_pit_in_lap'] and not l['is_pit_out_lap']]
        selected = [l for l in base if l['lap_duration_ms'] <= statistics.median(l['lap_duration_ms'] for l in base) * 1.07]
        assert m['samples'] == len(selected)
        assert stored[m['id']]['median_s'] == m['median_s']
    assert len(metrics) == 20


def test_lab_reproduces_the_original_dutch_gp_snapshot(lab):
    assert lab.drivers == ['NOR', 'VER', 'LEC', 'PIA']
    assert len(lab.raw_laps) == 1425 and lab.manifest['dna_laps'] == 275 and lab.total_laps == 72
    assert lab.pace_cuts == (43, 57) and lab.pace_report['test_rows'] == 280
    assert lab.pace_report['baseline_mae'] == pytest.approx(0.3615, abs=2e-3)


def test_pace_history_is_past_only(lab):
    assert (lab.pace.history_max_lap < lab.pace.lap_number).all()
    row = lab.pace.iloc[30]; changed = lab.laps.copy()
    changed.loc[(changed.driver_code == row.driver_code) & (changed.lap_number >= row.lap_number), 'lap_duration_s'] += 8
    altered = make_pace_features(changed, lab.pace_cuts).set_index('id').loc[row.id]
    for k in ['rolling_median', 'rolling_mean', 'rolling_std', 'previous_lap_s']: assert altered[k] == row[k]


@pytest.mark.parametrize('group', ['ghost_features', 'pace_features', 'dna_features', 'strategy_features'])
def test_lab_feature_tables_round_trip(lab, group):
    frame = lab.store.read(lab.race_key, group)
    assert len(frame) > 0 and frame.id.is_unique
    assert len(frame) == next(g['rows'] for g in lab.pipeline_status()['groups'] if g['name'] == group)


def test_strategy_anchor_and_dna_holdout(lab):
    s = lab.strategy('NOR')
    assert abs(s['delta_seconds']) < 1e-8 and s['actual_total'] == lab.classified_times['NOR'] and len(s['laps']) == 72
    m = np.array(lab.dna_report['confusion']); assert abs(np.trace(m) / m.sum() - lab.dna_report['accuracy']) < 1e-6
    assert lab.dna[lab.dna.id.isin(lab.challenge_ids)].lap_number.min() > lab.dna_cuts[1]
    assert not {'id', 'driver', 'lap_number'} & set(DNA_FEATURES)


def test_lab_works_for_another_race():
    e = get_lab(2023, 1)
    assert e.drivers[0] == 'VER' and e.total_laps == 57
    assert e.bootstrap()['selected_drivers'] == e.drivers


@pytest.mark.parametrize('path', ['/health', '/api/health', '/api/dashboard/catalog', '/api/dashboard/season?season=2023&round=22', '/api/dashboard/race?season=2024&round=15',
                                  '/api/dashboard/tracks?season=2024', '/api/dashboard/coverage', '/api/bootstrap?season=2024&round=15', '/api/ghost?season=2024&round=15',
                                  '/api/strategy?season=2024&round=15&pit_lap=30', '/api/pace?season=2024&round=15', '/api/replay/race?season=2024&round=15',
                                  '/api/replay/driver/NOR?season=2024&round=15', '/api/dashboard/export/laps.csv?season=2024&round=15'])
def test_api_surfaces(client, path): assert client.get(path).status_code == 200


@pytest.mark.parametrize('path', ['/api/ghost?season=2024&round=15&a=NOR&b=NOR', '/api/dashboard/season?season=2023&round=24', '/api/strategy?season=2024&round=15&driver=XXX',
                                  '/api/replay/driver/..?season=2024&round=15'])
def test_api_rejects_bad_input(client, path): assert client.get(path).status_code in (404, 422)
