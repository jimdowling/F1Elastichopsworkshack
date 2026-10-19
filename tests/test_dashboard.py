"""Historical-archive, calculation, API and schema-export regression evidence.

All application observations are public source data. Tiny hostile-string cases
below are isolated test fixtures, never part of the dashboard dataset.
"""
import csv,io,json,hashlib,statistics,math
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime
import numpy as np
import pytest
from fastapi.testclient import TestClient
from src.dashboard import DashboardEngine,DASH,finished,started

@pytest.fixture(scope='module')
def db(tmp_path_factory):
    obj=DashboardEngine(runtime_path=tmp_path_factory.mktemp('dashboard-db')/'runtime.sqlite')
    yield obj
    obj.db.close()

@pytest.fixture(scope='module')
def client(db):
    from app import app
    from src import dashboard_api
    previous=dashboard_api.INSTANCE;dashboard_api.INSTANCE=db
    with TestClient(app) as c:yield c
    dashboard_api.INSTANCE=previous

def test_manifest_and_every_file_hash(db):
    m=db.manifest
    assert m['events']==46 and m['sessions']==92 and m['results']==2078
    assert m['lap_rows']==51108 and m['pit_stops']==1737 and m['stint_rows']==2659
    assert m['weather_rows']==7309 and m['qualifying_weather_rows']==3929 and m['total_weather_rows']==11238
    assert m['race_control_rows']==4070 and m['position_rows']==22892
    assert m['synthetic_observations']==0 and not m['event_cluster_connected'] and not m['errors']
    assert len(m['sha256'])==93
    for filename,digest in m['sha256'].items():assert hashlib.sha256((DASH/filename).read_bytes()).hexdigest()==digest
    assert len(m['coverage'])==46
    assert sum(x['laps'] for x in m['coverage'])==m['lap_rows']
    assert sum(x['qualifying_weather'] for x in m['coverage'])==m['qualifying_weather_rows']

def test_classification_pagination_and_readback(db):
    assert Counter((r['season'],r['session_name']) for r in db.results)==Counter({(2023,'Race'):440,(2023,'Qualifying'):440,(2023,'Sprint'):120,(2024,'Race'):479,(2024,'Qualifying'):479,(2024,'Sprint'):120})
    assert len({r['id'] for r in db.results})==2078
    assert db.db.execute('SELECT COUNT(*) FROM dashboard_results').fetchone()[0]==2078
    assert sorted(db.results,key=lambda r:r['id'])==sorted(db.catalog['results'],key=lambda r:r['id'])

@pytest.mark.parametrize('year,maximum,champion,points,constructor,team_points',[(2023,22,'max_verstappen',575,'red_bull',860),(2024,24,'max_verstappen',437,'mclaren',666)])
def test_final_championship_matches_every_official_row(db,year,maximum,champion,points,constructor,team_points):
    view=db.season_view(year,maximum)
    for kind,key in [('driver','driver_standings'),('constructor','constructor_standings')]:
        official={x['entity_id']:x for x in db.official if x['season']==year and x['kind']==kind}
        assert set(official)=={r['id'] for r in view[key]}
        for row in view[key]:
            assert row['points']==official[row['id']]['points']==row['official_final_points']
            assert row['position']==official[row['id']]['position']
        assert len({r['position'] for r in view[key]})==len(view[key])
    assert (view['driver_standings'][0]['id'],view['driver_standings'][0]['points'])==(champion,points)
    assert (view['constructor_standings'][0]['id'],view['constructor_standings'][0]['points'])==(constructor,team_points)
    assert sum(r['points'] for r in view['driver_standings'])==sum(r['points'] for r in view['constructor_standings'])

@pytest.mark.parametrize('year,maximum',[(2023,22),(2024,24)])
def test_every_cutoff_has_independent_race_plus_sprint_sums(db,year,maximum):
    for through in range(1,maximum+1):
        view=db.season_view(year,through);drivers=defaultdict(float);teams=defaultdict(float)
        for r in db.results:
            if r['season']==year and r['round_number']<=through and r['session_name'] in {'Race','Sprint'}:
                drivers[r['driver_id']]+=r['points'];teams[r['team_id']]+=r['points']
        assert {r['id']:r['points'] for r in view['driver_standings']}==dict(drivers)
        assert {r['id']:r['points'] for r in view['constructor_standings']}==dict(teams)
        assert max(h['round_number'] for h in view['history']['drivers'])==through
        if through<maximum:assert all(r['official_final_points'] is None for r in view['driver_standings'])

def test_historical_numbers_and_substitute_team_credit(db):
    end=db.season_view(2024,24)
    drivers={r['id']:r for r in end['drivers']};teams={r['id']:r for r in end['teams']}
    assert drivers['norris']['number']==4 and drivers['max_verstappen']['number']==1
    bear=drivers['bearman'];assert bear['points']==7 and len(bear['team_history'])==2
    assert next(r for r in teams['ferrari']['drivers'] if r['id']=='bearman')['points']==6
    assert next(r for r in teams['haas']['drivers'] if r['id']=='bearman')['points']==1
    for team in teams.values():assert sum(r['points'] for r in team['drivers'])==team['points']

def test_pole_start_is_not_qualifying_p1(db):
    for year,round_number in [(2023,12),(2024,14)]:
        q=db.classifications(year,round_number,'Qualifying');r=db.classifications(year,round_number,'Race')
        assert q[0]['driver_code']=='VER'
        assert next(x for x in r if x['grid_position']==1)['driver_code']=='LEC'
    v=db.season_view(2024,24)
    for d in v['drivers']:
        races=[r for r in db.rows(2024,24,'Race') if r['driver_id']==d['id']]
        assert d['pole_starts']==sum(r['grid_position']==1 for r in races)

def test_profiles_and_head_to_head(db):
    d=db.driver_view(2024,15,'NOR')
    assert d['profile']['points']==225 and d['profile']['number']==4
    assert len(d['history'])==15 and len(d['previous_season_points'])==15
    h=db.compare(2024,15,'NOR','PIA');assert h['wins']['Race']=={'a':10,'b':5,'paired':15,'tied':0}
    assert h['wins']['Qualifying']['a']==12 and h['wins']['Qualifying']['b']==3
    assert h['rounds'][-1]['points_gap']==46
    for row in h['rounds']:
        qa=next((r for r in db.classifications(2024,row['round_number'],'Qualifying') if r['driver_code']=='NOR'),None)
        qb=next((r for r in db.classifications(2024,row['round_number'],'Qualifying') if r['driver_code']=='PIA'),None)
        if row['qualifying_segment']:
            field=row['qualifying_segment'].lower()+'_ms'
            assert row['qualifying_gap_s']==pytest.approx((qa[field]-qb[field])/1000)
    with pytest.raises(ValueError):db.compare(2024,15,'NOR','NOR')
    with pytest.raises(ValueError):db.driver_view(2023,22,'bearman')

@pytest.mark.parametrize('year,round_number',[(e['season'],e['round_number']) for e in json.loads((DASH/'catalog.json').read_text())['events']])
def test_each_race_has_consistent_provenance_and_units(db,year,round_number):
    raw=db.race_raw(year,round_number);event=db.event(year,round_number)
    assert raw['event']==event and raw['laps'] and raw['weather'] and raw['positions'] and raw['race_control']
    assert len({l['id'] for l in raw['laps']})==len(raw['laps'])
    assert all(l['season']==year and l['round_number']==round_number and l['session_name']=='Race' for l in raw['laps'])
    assert all(l['track_status'] is None for l in raw['laps'])
    assert all(l['lap_duration_ms'] is None or isinstance(l['lap_duration_ms'],int) for l in raw['laps'])
    assert all(1<=p['position']<=22 for p in raw['positions'])
    origin=raw['clock_origin_epoch'];assert origin==datetime.fromisoformat(raw['session']['date_start']).timestamp()
    for l in raw['laps']:
        if l['lap_start_s'] is not None:
            assert origin+l['lap_start_s']==pytest.approx(datetime.fromisoformat(l['date_start']).timestamp(),abs=.0011,rel=0)
        if l['lap_end_s'] is not None:
            assert l['lap_end_s']-l['lap_start_s']==pytest.approx(l['lap_duration_ms']/1000,abs=.0011)
        if l['tyre_life'] is not None:
            st=next(s for s in raw['stints'] if s['driver_code']==l['driver_code'] and s['stint_number']==l['stint'])
            assert l['tyre_life']==st['tyre_age_at_start']+l['lap_number']-st['lap_start']+1
    w=raw['weather'][0];assert origin+w['session_time_s']==pytest.approx(datetime.fromisoformat(w['date']).timestamp(),abs=.0011,rel=0)
    q=db.weather_view(year,round_number,'Qualifying');assert q['rows']

def test_position_asof_join_and_missing_stint_boundaries(db):
    raw=db.race_raw(2024,15)
    for l in raw['laps']:
        if l['lap_end_s'] is None:continue
        positions=[p for p in raw['positions'] if p['driver_code']==l['driver_code'] and p['session_time_s']<=l['lap_end_s']+.000001]
        expected=max(positions,key=lambda p:p['session_time_s'])['position'] if positions else None
        assert l['position']==expected
    assert any(s['lap_start'] is None or s['lap_end'] is None for s in db.race_raw(2023,3)['stints'])

def test_pace_filter_and_persisted_values(db):
    raw=db.race_raw(2024,15);metrics,accepted=db.pace_rows(2024,15,True,1.07)
    expected=set()
    for m in metrics:
        all_laps=[l for l in raw['laps'] if l['driver_code']==m['driver_code'] and l['lap_duration_ms'] is not None and l['lap_duration_ms']>0]
        base=[l for l in all_laps if l['lap_number']>1 and not l['is_pit_in_lap'] and not l['is_pit_out_lap']]
        threshold=statistics.median(l['lap_duration_ms'] for l in base)*1.07
        selected=[l for l in base if l['lap_duration_ms']<=threshold]
        expected.update(l['id'] for l in selected)
        assert m['samples']==len(selected)
        assert m['median_s']==pytest.approx(statistics.median(l['lap_duration_ms']/1000 for l in selected),abs=1e-6)
        stored=json.loads(db.db.execute('SELECT payload FROM race_pace_features WHERE id=?',(m['id'],)).fetchone()[0])
        assert stored['median_s']==m['median_s'] and stored['samples']==m['samples']
    assert accepted==expected and len(metrics)==20
    unfiltered,ids=db.pace_rows(2024,15,False,1.07)
    assert len(ids)==sum(l['lap_duration_ms'] is not None and l['lap_duration_ms']>0 for l in raw['laps'])
    assert len(ids)>len(accepted)
    view=db.race_view(2024,15);assert {l['id'] for l in view['laps'] if l['included']}==accepted
    a,_=db.pace_rows(2024,15,True,1.07001);b,_=db.pace_rows(2024,15,True,1.07002)
    assert not ({r['id'] for r in a}&{r['id'] for r in b})
    with pytest.raises(ValueError):db.pace_rows(2024,15,True,float('nan'))

def test_pit_lane_summaries_retain_raw_outliers(db):
    d=db.pit_view(2023,22);valid=[p for p in d['rows'] if p['duration_s'] is not None and 10<=p['duration_s']<=90]
    assert d['valid_count']==len(valid) and d['excluded_count']==len(d['rows'])-len(valid)
    assert d['excluded_count']>0
    assert d['mean_s']==pytest.approx(np.mean([p['duration_s'] for p in valid]),abs=1e-6)
    assert d['fastest']['duration_s']>=10
    assert 'not stationary' in d['methodology']
    assert all('source_local_time' in p and 'date' not in p for p in d['rows'])

@pytest.mark.parametrize('year,expected',[(2023,22),(2024,24)])
def test_timing_dna_uses_disclosed_standardized_distance(db,year,expected):
    d=db.tracks(year);rows=d['rows'];assert len(rows)==expected
    fields=['lap_length_km','median_pace_s','stops_per_entry','retirement_rate']
    incomplete=[r for r in rows if any(r[k] is None for k in fields)]
    assert all('similar' not in r for r in incomplete)
    rows=[r for r in rows if all(r[k] is not None for k in fields)]
    matrix=np.array([[r[k] for k in fields] for r in rows]);sd=matrix.std(axis=0);sd[sd==0]=1;scaled=(matrix-matrix.mean(axis=0))/sd
    for i,r in enumerate(rows):
        distances=np.sqrt(((scaled-scaled[i])**2).sum(axis=1));order=[j for j in np.argsort(distances) if j!=i][:3]
        assert [x['round_number'] for x in r['similar']]==[rows[j]['round_number'] for j in order]
        for value,j in zip(r['similar'],order):assert value['distance']==pytest.approx(distances[j],abs=.00051)
    dutch=next(r for r in rows if r['circuit_id']=='zandvoort');assert dutch['lap_length_km']==pytest.approx(4.259,abs=.002)

@pytest.mark.parametrize('path',[
 '/catalog','/season?season=2023&round=22','/season?season=2024&round=24','/race?season=2024&round=15&clean=false&cutoff=1.10',
 '/driver?season=2024&round=24&driver=NOR','/compare?season=2024&round=24&a=norris&b=piastri','/pits?season=2023&round=22',
 '/tracks?season=2024','/weather?season=2023&round=13&session=Qualifying','/coverage'])
def test_api_read_surfaces(client,path):
    r=client.get('/api/dashboard'+path);assert r.status_code==200,r.text
    assert isinstance(r.json(),dict) and len(r.content)>20

@pytest.mark.parametrize('path',[
 '/season?season=2026','/season?season=2023&round=24','/race?round=0','/race?cutoff=nan','/race?cutoff=inf','/race?cutoff=2',
 '/driver?driver=unknown','/compare?a=NOR&b=NOR','/weather?session=Sprint','/export/laps.csv?session=Qualifying','/export/weather.csv?session=Sprint',
 '/export/unknown.csv','/schema/unknown.json','/schema/f1-laps.json?season=2025'])
def test_api_rejects_invalid_or_unsupported_slices(client,path):
    r=client.get('/api/dashboard'+path);assert r.status_code==422,r.text

@pytest.mark.parametrize('kind',['results','laps','weather','pits','stints','race-control','features','sessions','driver-stats','constructor-stats'])
def test_csv_exports(client,kind):
    r=client.get(f'/api/dashboard/export/{kind}.csv?season=2024&round=15')
    assert r.status_code==200 and 'text/csv' in r.headers['content-type'] and 'attachment' in r.headers['content-disposition']
    rows=list(csv.DictReader(io.StringIO(r.text)));assert rows
    if kind=='sessions':assert len(rows)==1 and rows[0]['session_name']=='Race'
    if kind=='driver-stats':assert next(x for x in rows if x['code']=='NOR')['points']=='225.0'

def test_csv_formula_escape_without_mutating_sources(db):
    result=db.results[0];before=result['full_name'];result['full_name']='  =HYPERLINK("bad")'
    try:
        rows=list(csv.DictReader(io.StringIO(db.export('results',result['season'],result['round_number'],result['session_name']))))
        value=next(x for x in rows if x['id']==result['id'])['full_name'];assert value.startswith("'  =")
    finally:result['full_name']=before

@pytest.mark.parametrize('index,expected',[('f1-sessions',1),('f1-results',20),('f1-laps',1426),('f1-weather',153),('f1-telemetry',1444)])
def test_schema_export_dimensions_and_coverage(client,index,expected):
    r=client.get(f'/api/dashboard/schema/{index}.json?season=2024&round=15');assert r.status_code==200
    d=r.json();assert d['record_count']==len(d['records'])==expected
    assert 'not the event cluster' in d['provenance']
    for row in d['records']:
        assert row['season']==2024 and row['round_number']==15 and row['event_name']=='Dutch Grand Prix' and row['session_name']=='Race'
        if index=='f1-laps':assert row['track_status'] is None and (row['lap_duration_ms'] is None or isinstance(row['lap_duration_ms'],int))
        if index=='f1-weather':assert row['rainfall'] is None or isinstance(row['rainfall'],bool)
        if index=='f1-telemetry':
            assert row['is_interpolated'] is True and row['drs'] is None and row['z'] is None
            assert all(isinstance(row[k],int) for k in ['speed','rpm','throttle','n_gear']) and isinstance(row['brake'],bool)
            assert 0<=row['throttle']<=100
    if index=='f1-telemetry':assert Counter(x['driver_code'] for x in d['records'])=={'NOR':361,'VER':361,'LEC':361,'PIA':361}

def test_unsupported_high_frequency_and_qualifying_laps_stay_empty(client):
    for path in ['/schema/f1-telemetry.json?season=2023&round=13','/schema/f1-laps.json?session=Qualifying','/schema/f1-telemetry.json?session=Qualifying']:
        d=client.get('/api/dashboard'+path).json();assert d['records']==[] and d['record_count']==0
    assert client.get('/api/dashboard/schema/f1-weather.json?session=Qualifying').json()['record_count']==79

def test_original_four_labs_and_manifest_remain_available(client):
    for path in ['/api/bootstrap','/api/ghost','/api/strategy','/api/pace','/api/dna/challenge','/api/pipeline']:
        assert client.get(path).status_code==200
    assert client.get('/api/health').json()=={'status':'ok','cloud_connected':False,'synthetic_observations':0}
    from src.dashboard import ROOT
    original=json.loads((ROOT/'data/manifest.json').read_text())
    assert original['synthetic_observations']==0


def test_lapped_is_a_finish_not_a_retirement(db):
    assert finished({'status':'Lapped'}) and finished({'status':'+1 Lap'}) and finished({'status':'Finished'})
    assert not finished({'status':'Retired'}) and not finished({'status':'Disqualified'})
    results=db.classifications(2024,1)
    assert len(results)==20 and all(r['finished'] for r in results)
    assert sum(d['dnfs'] for d in db.season_view(2024,1)['drivers'])==0
    track=next(r for r in db.tracks(2024)['rows'] if r['round_number']==1)
    assert track['retirement_rate']==0

def test_quality_gaps_are_explicit(db):
    q=db.archive_quality()
    assert q['stint_rows_missing_boundary']==23
    assert q['lap_rows_missing_duration']>0 and q['lap_rows_missing_end_time']>0
    assert q['events_without_inferred_length']==['2024 Monaco Grand Prix']
