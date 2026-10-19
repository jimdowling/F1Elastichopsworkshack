"""Real archive/API integrity for the shared-clock 20-car replay."""
import json,math,hashlib
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data/replay'
MANIFEST=json.loads((DATA/'manifest.json').read_text());CODES=[d['driver_code'] for d in MANIFEST['drivers']]

@pytest.fixture(scope='module')
def client():
    from app import app
    with TestClient(app) as c:yield c

def test_manifest_scope_counts_and_all_hashes():
    m=MANIFEST
    assert (m['season'],m['round_number'],m['session_key'],m['session_name'])==(2024,15,9582,'Race')
    assert m['driver_count']==20 and m['location_samples']==218520 and m['car_samples']==110300
    assert m['synthetic_observations']==0 and not m['errors'] and len(m['sha256'])==20
    assert m['start_s']==189.071 and m['end_s']==5706.927 and m['clock_origin_epoch']==1724590800
    assert sum(d['out_of_range_channels']['throttle'] for d in m['drivers'])==1
    assert sum(d['out_of_range_channels']['brake'] for d in m['drivers'])==5
    assert len(m['sources'])==40 and sum(s['raw_rows'] for s in m['sources'])==841220
    for file,sha in m['sha256'].items():assert hashlib.sha256((DATA/file).read_bytes()).hexdigest()==sha
    for source in m['sources']:
        assert source['url'].startswith('https://api.openf1.org/v1/') and 'session_key=9582' in source['url']
        assert source['kind'] in {'location','car_data'} and len(source['sha256'])==64

@pytest.mark.parametrize('code',CODES)
def test_every_driver_has_monotonic_real_channels(code):
    d=json.loads((DATA/(code+'.json')).read_text());meta=next(x for x in MANIFEST['drivers'] if x['driver_code']==code)
    assert d['driver_code']==code and d['driver_number']==meta['driver_number']
    for key,count in [('location',meta['location_samples']),('car_data',meta['car_samples'])]:
        series=d[key];assert len(series['time'])==count
        assert all(len(values)==count for values in series.values())
        assert all(b>a for a,b in zip(series['time'],series['time'][1:]))
        assert all(MANIFEST['start_s']<=t<=MANIFEST['end_s'] for t in series['time'])
        assert all(v is None or isinstance(v,(int,float)) and math.isfinite(v) for arr in series.values() for v in arr)
    assert meta['max_location_gap_s']<2.5
    assert all(0<=v<=400 for v in d['car_data']['speed'] if v is not None)
    assert sum(v is not None and not 0<=v<=100 for v in d['car_data']['throttle'])==meta['out_of_range_channels']['throttle']
    assert all(0<=v<=8 for v in d['car_data']['n_gear'] if v is not None)

def test_driver_streams_not_duplicated_and_clock_shared():
    payload=[json.loads((DATA/(c+'.json')).read_text()) for c in CODES]
    assert len({hashlib.sha256(json.dumps(d['location']).encode()).hexdigest() for d in payload})==20
    assert len({hashlib.sha256(json.dumps(d['car_data']).encode()).hexdigest() for d in payload})==20
    assert all(d['location']['time']==payload[0]['location']['time'] for d in payload)
    # Actual feed timestamps are retained; this is NOT a fabricated 0.5 s grid.
    assert any(abs(b-a-.5)>.05 for a,b in zip(payload[0]['location']['time'],payload[0]['location']['time'][1:]))

def test_four_car_api_uses_existing_feature_readback(client):
    d=client.get('/api/ghost/field');assert d.status_code==200;data=d.json()
    assert {g['driver'] for g in data['drivers']}=={'NOR','VER','LEC','PIA'}
    for g in data['drivers']:
        other='NOR' if g['driver']!='NOR' else 'VER'
        assert g==client.get('/api/ghost',params={'a':g['driver'],'b':other}).json()['a']
    assert 'independent' in data['scope'].lower() and 'persisted' in data['data_source']

def test_race_api_keeps_positions_timing_and_source_separate(client):
    d=client.get('/api/replay/race');assert d.status_code==200;r=d.json()
    assert r['source_mode']=='public-synchronized' and r['manifest']['driver_count']==20
    assert len(r['results'])==20 and len(r['laps'])==1426 and len(r['positions'])==540 and len(r['stints'])==46
    assert r['race_control'] and r['laps'][0]['lap_duration_ms'] is None
    assert 'not a cloud connection claim' in r['scope_note']

@pytest.mark.parametrize('code',CODES)
def test_all_driver_endpoints_serve_exact_curated_bytes(client,code):
    r=client.get('/api/replay/driver/'+code);assert r.status_code==200
    assert r.content==(DATA/(code+'.json')).read_bytes()
    assert r.headers['x-pitlane-source']=='public-recorded-session'

@pytest.mark.parametrize('code',['XXX','nor','manifest','../.env','%2e%2e%2f.env'])
def test_unknown_or_path_driver_not_served(client,code):
    r=client.get('/api/replay/driver/'+code);assert r.status_code in {404,422}

def test_missing_archive_fails_honestly(monkeypatch,tmp_path,client):
    from src import race_replay
    race_replay.manifest.cache_clear();monkeypatch.setattr(race_replay,'REPLAY',tmp_path)
    r=client.get('/api/replay/race');assert r.status_code==503 and 'no race positions are invented' in r.json()['detail']
    assert client.get('/api/ghost/field').status_code==200
    race_replay.manifest.cache_clear()
