import hashlib, json, sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from src.engine import LabEngine, DATA, DRIVERS, DNA_FEATURES, make_pace_features

@pytest.fixture(scope='session')
def lab(tmp_path_factory):
    return LabEngine(tmp_path_factory.mktemp('features')/'test.sqlite')

@pytest.fixture(scope='session')
def api():
    from app import app
    return TestClient(app)

def test_real_observations_and_unique_ids(lab):
    assert lab.manifest['synthetic_observations']==0
    assert len(lab.raw_laps)==1425
    assert lab.laps.id.is_unique
    assert not lab.laps.synthetic.any()
    assert lab.laps.driver_code.nunique()==20

@pytest.mark.parametrize('name',json.loads((DATA/'manifest.json').read_text())['sha256'].keys())
def test_raw_checksums(name):
    m=json.loads((DATA/'manifest.json').read_text())
    assert hashlib.sha256((DATA/name).read_bytes()).hexdigest()==m['sha256'][name]

@pytest.mark.parametrize('driver',DRIVERS)
def test_ghost_trace(lab,driver):
    g=lab.ghosts[driver]; t=g['trace']
    assert len(t['time'])==361
    assert t['time'][0]==0 and abs(t['time'][-1]-g['lap_time'])<1e-6
    assert t['distance'][0]==0 and t['distance'][-1]==1
    assert np.all(np.diff(t['time'])>0)
    assert all(np.isfinite(v).all() for v in map(np.array,t.values()))
    assert 50<min(t['speed'])<max(t['speed'])<370
    assert 0<=min(t['throttle'])<=max(t['throttle'])<=100

@pytest.mark.parametrize('pair',[('NOR','VER'),('LEC','PIA'),('VER','NOR')])
def test_ghost_finish_delta(lab,pair):
    result=lab.ghost_view(*pair)
    assert result['delta'][0]==0
    assert abs(result['delta'][-1]-result['finish_delta'])<1e-6

def test_pace_history_is_past_only(lab):
    assert (lab.pace.history_max_lap<lab.pace.lap_number).all()
    row=lab.pace.iloc[30];changed=lab.laps.copy()
    changed.loc[changed.id==row.id,'lap_duration_s']+=10
    altered=make_pace_features(changed).set_index('id').loc[row.id]
    for k in ['rolling_median','rolling_mean','rolling_std','previous_lap_s']:
        assert altered[k]==row[k]

def test_future_laps_do_not_change_current_features(lab):
    row=lab.pace.iloc[30];changed=lab.laps.copy()
    changed.loc[(changed.driver_code==row.driver_code)&(changed.lap_number>row.lap_number),'lap_duration_s']+=8
    altered=make_pace_features(changed).set_index('id').loc[row.id]
    for k in ['rolling_median','rolling_mean','rolling_std','previous_lap_s']:
        assert altered[k]==row[k]

def test_feature_windows_do_not_cross_pits(lab):
    lookup=lab.laps.set_index('id')
    for _,r in lab.pace.iterrows():
        for l in range(int(r.lap_number)-3,int(r.lap_number)):
            history=lookup.loc[f'2024-15-R-{r.driver_code}-{l}']
            assert history.stint==r.stint
            assert not history.is_pit_in_lap and not history.is_pit_out_lap

def test_pace_split(lab):
    assert lab.pace[lab.pace.split=='train'].lap_number.max()<=43
    assert lab.pace[lab.pace.split=='validation'].lap_number.between(44,57).all()
    assert lab.pace[lab.pace.split=='test'].lap_number.min()>=58
    assert not {'lap_duration_s','sector1_s','sector2_s','sector3_s','position'}&set(lab.pace_inputs)

def test_reported_metrics_are_measured(lab):
    t=lab.pace[lab.pace.split=='test']
    assert abs(abs(t.baseline_residual).mean()-lab.pace_report['baseline_mae'])<1e-6
    assert abs(abs(t.model_residual).mean()-lab.pace_report['model_mae'])<1e-6
    assert len(t)==lab.pace_report['test_rows']
    # Deliberately no assertion that the trained model outperforms the baseline.

def test_anomalies_are_test_only(lab):
    data=lab.pace_view('NOR','baseline',.5)
    assert all(x['lap']>=58 and x['delta']>=.5 for x in data['anomalies'])
    assert all(x['predicted'] is None for x in data['chart'] if x['split']=='train')

@pytest.mark.parametrize('group',['ghost_features','pace_features','dna_features','strategy_features'])
def test_feature_roundtrip(lab,group):
    frame=lab.store.read(group)
    assert len(frame)>0 and frame.id.is_unique
    assert len(frame)==next(g['rows'] for g in lab.pipeline_status()['groups'] if g['name']==group)

@pytest.mark.parametrize('driver',DRIVERS)
def test_original_strategy_recovers_anchor(lab,driver):
    s=lab.strategy(driver)
    assert abs(s['delta_seconds'])<1e-8
    assert abs(s['actual_total']-s['scenario_total'])<1e-8
    assert s['actual_total']==lab.classified_times[driver]
    assert s['actual_total_source']=='Jolpica classified elapsed race time'
    assert len(s['window'])==45 and len(s['laps'])==72

def test_pit_loss_sensitivity(lab):
    a=lab.strategy('NOR',32,pit_loss=20); b=lab.strategy('NOR',32,pit_loss=25)
    assert abs((b['delta_seconds']-a['delta_seconds'])-5)<1e-6

def test_strategy_compound_rule_and_minimum(lab):
    s=lab.strategy('NOR',32,'MEDIUM')
    assert any('not a legal' in w for w in s['warnings'])
    assert s['best']['delta']==min(w['delta'] for w in s['window'])

def test_dna_no_identity_features(lab):
    assert not {'id','driver','driver_code','lap_number','compound','tyre_life'}&set(DNA_FEATURES)
    train=set(lab.dna[lab.dna.lap_number<=50].id)
    assert not train.intersection(lab.challenge_ids)
    assert lab.dna[lab.dna.id.isin(lab.challenge_ids)].lap_number.min()>=58

def test_dna_measured_accuracy(lab):
    m=np.array(lab.dna_report['confusion'])
    assert m.sum()==lab.dna_report['test_rows']==60
    assert abs(np.trace(m)/m.sum()-lab.dna_report['accuracy'])<1e-6

def test_anonymous_challenge_does_not_leak_label(lab):
    c=lab.challenge(0)
    assert 'driver' not in c and 'actual' not in c
    r=lab.reveal(c['id'],'NOR')
    assert abs(sum(x['vote'] for x in r['votes'])-1)<2e-6
    assert r['actual'] in DRIVERS
    assert r['correct']==(r['actual']=='NOR')
    assert c['id']!=lab.challenge(1)['id']

def test_api_health_and_local_disclosure(api):
    response=api.get('/api/bootstrap');assert response.status_code==200
    data=response.json();assert data['pipeline']['cloud_connected'] is False
    assert len(data['pipeline']['steps'])==7
    assert 'SQLite' in data['pipeline']['feature_backend']

@pytest.mark.parametrize('path',['/api/ghost?a=NOR&b=NOR','/api/ghost?a=FAKE','/api/strategy?pit_lap=0','/api/strategy?degradation=-1','/api/strategy?pit_loss=100','/api/strategy?compound=WET','/api/pace?driver=FAKE','/api/pace?method=bad','/api/dna/challenge?index=-1'])
def test_bad_api_inputs(api,path):assert api.get(path).status_code==422

@pytest.mark.parametrize('path',['/api/ghost','/api/strategy','/api/pace','/api/dna/challenge','/api/manifest','/api/pipeline'])
def test_valid_endpoints(api,path):
    r=api.get(path);assert r.status_code==200
    assert 'NaN' not in r.text and 'Infinity' not in r.text

def test_invalid_reveal(api):assert api.post('/api/dna/reveal',json={'id':'not-held-out','guess':'NOR'}).status_code==422

def test_csv_export(api):
    r=api.get('/api/features/pace_features.csv')
    assert r.status_code==200 and 'rolling_median' in r.text.splitlines()[0]
    assert 'attachment' in r.headers['content-disposition']
    assert api.get('/api/features/not_a_table.csv').status_code==404

def test_deterministic_rerun(api):
    a=api.get('/api/bootstrap').json()
    assert api.post('/api/pipeline').status_code==200
    b=api.get('/api/bootstrap').json()
    assert a['pace_report']['model_mae']==b['pace_report']['model_mae']
    assert a['dna_report']['accuracy']==b['dna_report']['accuracy']
