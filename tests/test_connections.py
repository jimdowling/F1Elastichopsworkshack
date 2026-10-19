"""Offline integration/security contracts. Not live Hopsworks evidence."""
from dataclasses import replace
import copy,json,os,sys,time,zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).parent))
from cloud_fixtures import FixtureHops
from src.settings import Settings,ConnectionProblem
from src.remote import HopsConnection,HopsSource,HopsFeatures,canonical
from src.hops_dashboard import HopsDashboard
from src.connections import Runtime

TOKEN='operator_test_token_only_32_characters'
BASE={'HOPSWORKS_HOST':'fixture.invalid','HOPSWORKS_PROJECT':'fixture_project','HOPSWORKS_API_KEY':'HOPS_SECRET','PITLANE_ADMIN_TOKEN':TOKEN,'PITLANE_FEATURE_PREFIX':'pitlane_testteam','PITLANE_ALLOW_FEATURE_WRITES':'true'}
@pytest.fixture
def settings():return Settings.from_mapping(BASE)
@pytest.fixture
def sdk():return FixtureHops()
@pytest.fixture
def reader(settings,sdk):return HopsSource(settings,sdk)
@pytest.fixture
def hops(settings,sdk):return HopsFeatures(settings,sdk),sdk
@pytest.fixture
def db(reader,tmp_path):
    d=HopsDashboard(reader,runtime_path=tmp_path/'native.sqlite');yield d;d.db.close()
@pytest.fixture
def rt(settings,sdk):return Runtime(settings,client=sdk)
@pytest.fixture
def client(rt):
    from app import app
    from src import connections
    old=connections.RUNTIME;connections.RUNTIME=rt
    with TestClient(app) as c:yield c
    rt.pool.shutdown(wait=True);connections.RUNTIME=old

def test_defaults_no_external_calls():
    s=Settings.from_mapping({});r=Runtime(s)
    assert r.status()['modes']=={'data':'local','features':'local'} and not r.status()['cloud_connected']
    assert r.connection is None and r.source is None and r.hops is None and not r.private

@pytest.mark.parametrize('change',[{'HOPSWORKS_FG_LAPS':'*'},{'HOPSWORKS_FG_LAPS':'a,b'},{'HOPSWORKS_FG_LAPS':'../a'},{'HOPSWORKS_FG_LAPS':'F1-Laps'},{'HOPSWORKS_FG_VERSION':'0'},{'HOPSWORKS_FG_LAPS':'pitlane_testteam_race_pace'},{'PITLANE_FEATURE_PREFIX':'f1_laps'},{'PITLANE_FEATURE_VERSION':'0'},{'PITLANE_DATA_MODE':'elastic'},{'PITLANE_FEATURE_MODE':'auto'},{'PITLANE_TELEMETRY_LIMIT':'99999999'},{'PITLANE_CACHE_SECONDS':'nan'},{'HOPSWORKS_HOST':'https://host/path'},{'HOPSWORKS_HOST':'host:99999'}])
def test_invalid_config_fails_safely(change):
    with pytest.raises(ConnectionProblem) as e:Settings.from_mapping({**BASE,**change})
    assert 'HOPS_SECRET' not in str(e.value)

def test_server_env_precedence_and_no_interpolation(tmp_path):
    p=tmp_path/'.env';p.write_text('HOPSWORKS_HOST=fixture.invalid\nHOPSWORKS_API_KEY=${OTHER_SECRET}\nPITLANE_DATA_MODE=local\n')
    s=Settings.load(p,{'PITLANE_DATA_MODE':'hopsworks'});assert s.data_mode=='hopsworks' and s.hops_key=='${OTHER_SECRET}'

def test_source_group_names_are_configurable():
    s=Settings.from_mapping({**BASE,'HOPSWORKS_FG_LAPS':'race_laps','HOPSWORKS_FG_VERSION':'3'})
    assert s.sources['laps']=='race_laps' and s.sources['results']=='f1_results' and s.source_version==3

def test_public_settings_and_repr_never_contain_secrets(settings):
    value=json.dumps(settings.public())+repr(settings)
    for s in ['HOPS_SECRET',TOKEN,'fixture.invalid','fixture_project']:assert s not in value

def test_source_read_is_filtered_server_side_and_cached(reader,sdk):
    rows=reader.read('laps',{'season':2024,'round_number':15,'session_name':'Race'})
    group=sdk.source('laps');assert len(rows)==1426 and group.reads==1
    assert ('season','in',(2023,2024)) in group.queries[0] and ('round_number','==',15) in group.queries[0]
    assert reader.read('laps',{'season':2024,'round_number':15,'session_name':'Race'})==rows and group.reads==1
    assert all(isinstance(r['lap_number'],int) and (r['is_pit_in_lap'] is None or isinstance(r['is_pit_in_lap'],bool)) for r in rows)
    assert not any(g.inserts for g in sdk.groups.values()) and sdk.logins==1

def test_null_numeric_cells_become_null_not_nan(reader,sdk):
    sdk.source('laps').rows[0]['position']=None
    row=reader.read('laps',{'season':2024,'round_number':15,'session_name':'Race'})[0]
    assert row['position'] is None and json.dumps(row)

def test_readiness_counts_real_responses_without_writes(reader,sdk):
    d=reader.inspect();assert d['ok'] and d['dashboard_ready'] and d['read_only']
    assert {x['kind']:x['count'] for x in d['groups']}=={'sessions':2,'results':40,'laps':1426,'weather':232,'telemetry':None}
    assert sdk.source('telemetry').reads==0 and sdk.created==0

def test_missing_source_group_is_actionable(reader,sdk):
    del sdk.groups[('f1_weather',1)]
    with pytest.raises(ConnectionProblem,match='f1_weather'):reader.read('weather',{})
    d=reader.inspect();assert not d['ok'] and not d['dashboard_ready']

def test_missing_telemetry_group_keeps_dashboard_ready(reader,sdk):
    del sdk.groups[('f1_telemetry',1)];d=reader.inspect();assert not d['ok'] and d['dashboard_ready']

def test_read_errors_are_sanitized(reader,sdk):
    sdk.source('laps').fail=True
    with pytest.raises(ConnectionProblem) as e:reader.read('laps',{'season':2024,'round_number':15})
    assert 'PROVIDER_SECRET' not in str(e.value) and not reader.cache

def test_schema_errors_are_actionable(reader,sdk):
    sdk.source('laps').missing.add('lap_duration_ms')
    with pytest.raises(ConnectionProblem,match='lap_duration_ms'):reader.read('laps',{})
    sdk.source('results').types['position']='string'
    with pytest.raises(ConnectionProblem,match='position'):reader.read('results',{})

def test_row_cap_fails_closed(settings,sdk):
    reader=HopsSource(replace(settings,lap_limit=100),sdk)
    with pytest.raises(ConnectionProblem,match='cap'):reader.read('laps',{'season':2024,'round_number':15})
    assert not reader.cache

def test_unsupported_filter_rejected(reader):
    with pytest.raises(ConnectionProblem,match='filters'):reader.read('laps',{'team_name':'McLaren'})

def test_telemetry_cannot_read_entire_corpus(reader,sdk):
    with pytest.raises(ConnectionProblem,match='requires'):reader.read('telemetry',{'season':2024})
    assert sdk.logins==0
    assert len(reader.read('telemetry',{'season':2024,'round_number':15,'session_name':'Race','driver_code':'NOR','lap_number':72}))==12

def test_source_and_features_share_one_login(rt,sdk):
    rt.reader().inspect();rt.store().inspect();assert sdk.logins==1

def test_native_values_used_in_actual_analytics(db):
    assert len(db.events)==1 and db.catalog_view()['cloud_connected']
    season=db.season_view(2024,15);nor=next(r for r in season['driver_standings'] if r['code']=='NOR');assert nor['points']==27
    assert all(r['official_final_points'] is None for r in season['driver_standings'])
    v=db.race_view(2024,15);assert v['data_source']=='hopsworks' and v['feature_backend']=='SQLite'
    assert v['laps'][0]['track_status']=='1' and all(l['lap_start_s'] is None for l in v['laps'])
    assert not v['positions'] and v['race_control'] and v['pit_stops']
    assert next(m for m in v['metrics'] if m['driver_code']=='NOR')['median_s']>75
    assert all('Derived' in s['source'] for s in v['stints'])
    assert db.compare(2024,15,'NOR','PIA')['rounds'][0]['round_number']==15
    assert len(db.weather_view(2024,15,'Qualifying')['rows'])==79
    assert len(db.tracks(2024)['rows'])==1
    assert 'source' in db.export('laps',2024,15)

def test_string_driver_numbers_from_hopsworks_are_normalized(reader,sdk,tmp_path):
    sdk.source('results').types['driver_number']='string'
    for row in sdk.rows['results']:
        row['driver_number']=str(row['driver_number'])
    db=HopsDashboard(reader,runtime_path=tmp_path/'string-driver-number.sqlite')
    try:
        results=db.classifications(2024,15)
        assert len(results)==20
        assert all(isinstance(row['driver_number'],int) for row in results)
    finally:
        db.db.close()

def test_missing_qualifying_points_are_zero(reader,sdk,tmp_path):
    for row in sdk.rows['results']:
        if row['session_name']=='Qualifying':row['points']=None
    db=HopsDashboard(reader,runtime_path=tmp_path/'qualifying-points.sqlite')
    try:
        results=db.classifications(2024,15,'Qualifying')
        assert len(results)==20
        assert all(row['points']==0 for row in results)
    finally:
        db.db.close()

def test_native_coverage_does_not_bulk_fetch_laps(db,sdk):
    d=db.coverage_view();assert d['native_results']==40 and d['cached_race_slices']==0
    assert sdk.source('laps').reads==0

def test_missing_native_slice_never_falls_back(db,sdk):
    sdk.source('laps').rows.clear();db.reader.cache.clear()
    with pytest.raises(ConnectionProblem,match='not substituted'):db.race_raw(2024,15)

@pytest.mark.parametrize('field,value',[('lap_duration_ms',73.2),('is_pit_in_lap','false'),('driver_code','NOTCODE'),('lap_number',None),('season',2023)])
def test_bad_native_lap_values_rejected(reader,sdk,tmp_path,field,value):
    d=HopsDashboard(reader,runtime_path=tmp_path/'x.sqlite');sdk.rows['laps'][1][field]=value
    # season=2023 is correctly filtered by the provider, so exercise the adapter's defense directly.
    if field=='season':
        from src.hops_dashboard import scope
        with pytest.raises(ConnectionProblem):scope([sdk.rows['laps'][1]],{'season':2024})
    else:
        with pytest.raises(ConnectionProblem):d.race_raw(2024,15)
    d.db.close()

def test_conflicting_duplicate_laps_rejected(db,sdk):
    row=copy.deepcopy(sdk.rows['laps'][1]);row['lap_duration_ms']=123000;sdk.rows['laps'].append(row)
    with pytest.raises(ConnectionProblem,match='Conflicting'):db.race_raw(2024,15)

def test_null_pit_flag_excluded_from_clean_sample(db,sdk):
    sdk.rows['laps'][1]['is_pit_in_lap']=None
    rows,accepted=db.compute_pace_rows(2024,15);raw=db.race_raw(2024,15)['laps'];target=next(l for l in raw if l['driver_code']==sdk.rows['laps'][1]['driver_code'] and l['lap_number']==sdk.rows['laps'][1]['lap_number'])
    assert target['id'] not in accepted

def test_hopsworks_check_does_not_create_or_write(hops):
    store,sdk=hops;d=store.inspect();assert d['ok'] and not d['write_performed'] and sdk.logins==1 and sdk.created==0 and sdk.last_login['engine']=='python'
    assert sdk.last_login['hostname_verification'] is True and '.cache/hopsworks-certs' in sdk.last_login['cert_folder']

def test_hopsworks_read_missing_group_is_not_auto_publish(hops,db):
    store,sdk=hops;rows,_=db.compute_pace_rows(2024,15)
    with pytest.raises(ConnectionProblem,match='Publish'):store.read(db.pace_source_id(2024,15),rows)
    assert sdk.created==0

def test_hopsworks_value_verified_readback_used_by_chart(hops,db):
    store,sdk=hops;rows,_=db.compute_pace_rows(2024,15);source=db.pace_source_id(2024,15)
    report=store.publish(source,rows);assert report['rows']==20 and report['verified_values'] and not report['active_mode_changed']
    group=sdk.groups[(store.settings.group_name,1)];assert group.inserts==1 and group.reads==1 and group.frame.id.is_unique
    store.cache.clear();db.feature_reader=store.read;db.feature_source='Hopsworks'
    view=db.race_view(2024,15);assert view['feature_backend']=='Hopsworks' and len(view['metrics'])==20 and group.reads==2 and group.inserts==1
    assert db.db.execute('SELECT COUNT(*) FROM race_pace_features').fetchone()[0]==0
    store.publish(source,rows);assert len(group.frame)==20 and group.inserts==2

def test_changed_source_or_filter_requires_new_hopsworks_batch(hops,db):
    store,sdk=hops;rows,_=db.compute_pace_rows(2024,15);source=db.pace_source_id(2024,15);store.publish(source,rows)
    other,_=db.compute_pace_rows(2024,15,True,1.1)
    for changed_source,changed_rows in [(source,other),('changed-native-dataset',rows)]:
        with pytest.raises(ConnectionProblem):store.read(changed_source,changed_rows)
    assert sdk.groups[(store.settings.group_name,1)].inserts==1

def test_corrupt_remote_values_rejected(hops,db):
    store,sdk=hops;rows,_=db.compute_pace_rows(2024,15);source=db.pace_source_id(2024,15);store.publish(source,rows)
    sdk.groups[(store.settings.group_name,1)].corrupt=True;store.cache.clear()
    with pytest.raises(ConnectionProblem,match='differ'):store.read(source,rows)

def test_hops_error_secrets_sanitized(hops):
    store,sdk=hops;sdk.fail=True
    with pytest.raises(ConnectionProblem) as e:store.inspect()
    assert 'PROVIDER_SECRET' not in str(e.value)

def test_explicit_write_guards(rt):
    rt.settings=replace(rt.settings,allow_feature_writes=False)
    with pytest.raises(ConnectionProblem,match='PITLANE_ALLOW'):rt.prepare(2024,15,True,1.07,rt.settings.group_name)
    rt.settings=replace(rt.settings,allow_feature_writes=True)
    with pytest.raises(ConnectionProblem,match='exact'):rt.prepare(2024,15,True,1.07,'wrong')
    rt.settings=replace(rt.settings,prefix='pitlane_yourteam')
    with pytest.raises(ConnectionProblem,match='own'):rt.prepare(2024,15,True,1.07,rt.settings.group_name)

def unlock(client):
    r=client.post('/api/connections/unlock',json={'token':TOKEN},headers={'Origin':'http://testserver'});assert r.status_code==200
    assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=strict' in r.headers['set-cookie'] and TOKEN not in r.headers['set-cookie']

def wait_job(rt):
    deadline=time.monotonic()+15
    while rt.job['state'] in {'running','queued'} and time.monotonic()<deadline:time.sleep(.01)
    assert rt.job['state'] not in {'running','queued'};return rt.job

def test_api_unauthorized_and_cross_origin_denied(client,rt,sdk):
    assert client.post('/api/connections/test/source').status_code==401 and not sdk.logins
    assert client.post('/api/connections/unlock',json={'token':TOKEN},headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post('/api/connections/unlock',json={'token':'wrong'}).status_code==401
    assert client.get('/api/connections/telemetry').status_code==401
    assert not sdk.logins

def test_api_operator_login_and_no_secret_echo(client,rt):
    unlock(client);d=client.get('/api/connections/status').json();assert d['unlocked']
    text=json.dumps(d)
    for key in ['PROVIDER_SECRET','HOPS_SECRET',TOKEN]:assert key not in text
    r=client.post('/api/connections/unlock',json={'token':'SENSITIVE'*200});assert r.status_code==422 and 'SENSITIVE' not in r.text
    assert client.post('/api/connections/test/source',headers={'Origin':'https://evil.example'}).status_code==403

def test_api_cloud_workflow_and_auth_guard(client,rt,hops):
    unlock(client)
    assert client.post('/api/connections/test/source').status_code==202;assert wait_job(rt)['result']['ok']
    assert client.post('/api/connections/modes',json={'data':'hopsworks','features':'local','season':2024,'round':15}).status_code==202;assert wait_job(rt)['state']=='succeeded'
    r=client.get('/api/dashboard/race?season=2024&round=15');assert r.status_code==200 and r.json()['data_source']=='hopsworks'
    assert client.get('/api/dashboard/season?season=2024&round=15').json()['driver_standings'][0]['points']==27
    q=client.get('/api/dashboard/schema/f1-laps.json?season=2024&round=15&session=Qualifying');assert q.status_code==200 and q.json()['record_count']==0
    native=client.get('/api/dashboard/schema/f1-laps.json?season=2024&round=15').json();assert native['record_count']==1426 and native['records'][0]['track_status']=='1' and 'lap_start_s' not in native['records'][0]
    assert client.get('/api/dashboard/timing?season=2024&round=15').json()['data_source']=='public-timing-reference'
    assert client.get('/api/connections/telemetry').json()['record_count']==12
    assert client.post('/api/connections/feature-plan',json={}).status_code==202;assert wait_job(rt)['result']['rows']==20 and not hops[1].created
    assert client.post('/api/connections/modes',json={'data':'hopsworks','features':'hopsworks'}).status_code==202;assert wait_job(rt)['state']=='failed' and rt.modes['features']=='local'
    assert client.post('/api/connections/publish',json={'confirm_group':rt.settings.group_name}).status_code==202;assert wait_job(rt)['state']=='succeeded'
    assert rt.modes['features']=='local' # publishing alone does not activate anything
    assert client.post('/api/connections/modes',json={'data':'hopsworks','features':'hopsworks'}).status_code==202;assert wait_job(rt)['state']=='succeeded'
    race=client.get('/api/dashboard/race').json();assert race['feature_backend']=='Hopsworks'
    assert client.get('/api/dashboard/race?cutoff=1.1').status_code==409
    assert hops[1].groups[(rt.settings.group_name,1)].inserts==1
    assert client.post('/api/connections/lock').status_code==200
    assert client.get('/api/dashboard/catalog').status_code==401
    d=client.get('/api/connections/status').json();assert not d['unlocked'] and d['job'] is None and d['last_hopsworks_read'] is None
    assert client.get('/api/bootstrap').status_code==200 # independent public original labs remain available

def test_failed_cloud_activation_does_not_change_modes(client,rt,sdk):
    unlock(client);sdk.fail=True
    client.post('/api/connections/modes',json={'data':'hopsworks','features':'local'});j=wait_job(rt)
    assert j['state']=='failed' and rt.modes=={'data':'local','features':'local'}

def test_duplicate_job_rejected(rt):
    import threading
    event=threading.Event();rt.submit('fixture-wait',lambda:event.wait(1))
    try:
        with pytest.raises(ConnectionProblem,match='already running'):rt.submit('duplicate',lambda:None)
    finally:event.set();wait_job(rt);rt.pool.shutdown(wait=True)

def test_package_excludes_credentials_and_runtime(tmp_path):
    from src.archive import create_archive
    for name in ['.env','.env.prod','client.key','trust.jks','cert.p12','chain.pem','client.pfx','root.crt','.cache/native-data.json','.hopsworks/secret.json','connection_state/session.json','certificates/key.txt','.secrets/values.txt','data/hopsworks-publish-report.json']:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('DO_NOT_SHIP')
    (tmp_path/'.env.example').write_text('PLACEHOLDERS_ONLY');(tmp_path/'readme.md').write_text('safe')
    zpath=tmp_path.parent/'safe.zip';create_archive(tmp_path,zpath)
    with zipfile.ZipFile(zpath) as z:assert set(z.namelist())=={'pitlane-lab/.env.example','pitlane-lab/readme.md'}

@pytest.mark.parametrize('kind',['Race','Qualifying'])
def test_null_native_result_position_is_preserved_and_safe(reader,sdk,tmp_path,kind):
    next(r for r in sdk.rows['results'] if r['driver_code']=='NOR' and r['session_name']==kind)['position']=None
    d=HopsDashboard(reader,runtime_path=tmp_path/'nullable.sqlite')
    assert next(r for r in d.classifications(2024,15,kind) if r['driver_code']=='NOR')['position'] is None
    assert d.season_view(2024,15)['drivers'] and d.compare(2024,15,'NOR','PIA')
    d.db.close()

def test_native_relative_weather_does_not_fabricate_utc(db):
    rows=db.weather_view(2024,15)['rows'];assert all(r['date'] is None and r['id'] and isinstance(r['rainfall'],bool) for r in rows)

@pytest.mark.parametrize('field,value',[('status',['Finished']),('full_name',{'name':'not a string'}),('team_name',42)])
def test_invalid_native_result_strings_fail_actionably(reader,sdk,tmp_path,field,value):
    sdk.rows['results'][0][field]=value
    with pytest.raises(ConnectionProblem,match=field):HopsDashboard(reader,runtime_path=tmp_path/'bad.sqlite')

def test_native_result_conflict_and_identical_duplicate(reader,sdk,tmp_path):
    sdk.rows['results'].append(copy.deepcopy(sdk.rows['results'][0]))
    d=HopsDashboard(reader,runtime_path=tmp_path/'dedupe.sqlite');assert len(d.native_results)==40;d.db.close()
    reader.cache.clear();sdk.rows['results'][-1]['points']+=1
    with pytest.raises(ConnectionProblem,match='Conflicting'):HopsDashboard(reader,runtime_path=tmp_path/'conflict.sqlite')

def test_no_config_operator_control_is_disabled_and_readiness_safe(monkeypatch):
    from app import app
    from src import connections
    r=Runtime(Settings.from_mapping({}));monkeypatch.setattr(connections,'RUNTIME',r)
    with TestClient(app) as c:
        assert c.get('/api/connections/status').json()['admin_configured'] is False
        assert c.post('/api/connections/test/source').status_code==503
        assert c.post('/api/connections/unlock',json={'token':TOKEN}).status_code==503
        assert r.connection is None and r.hops is None

def test_secure_cookie_on_https_and_tamper_denied(rt,monkeypatch):
    from app import app
    from src import connections
    monkeypatch.setattr(connections,'RUNTIME',rt)
    with TestClient(app,base_url='https://testserver') as c:
        response=c.post('/api/connections/unlock',json={'token':TOKEN},headers={'Origin':'https://testserver'})
        assert 'Secure' in response.headers['set-cookie'] and c.get('/api/connections/status').json()['unlocked']
        c.cookies.clear();c.cookies.set('pitlane_operator','9999999999999.fake.invalid')
        assert not c.get('/api/connections/status').json()['unlocked']

def test_cli_init_private_random_token_and_never_overwrites(tmp_path,monkeypatch,capsys):
    import importlib.util,stat
    spec=importlib.util.spec_from_file_location('connect_cloud_cli',Path(__file__).resolve().parents[1]/'scripts/connect_cloud.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    (tmp_path/'.env.example').write_text('PITLANE_ADMIN_TOKEN=\nHOPSWORKS_API_KEY=\n')
    monkeypatch.setattr(module,'ROOT',tmp_path);monkeypatch.setattr(sys,'argv',['connect_cloud.py','init']);module.main()
    text=(tmp_path/'.env').read_text();token=text.splitlines()[0].split('=',1)[1]
    assert len(token)>=43 and token not in capsys.readouterr().out
    assert stat.S_IMODE((tmp_path/'.env').stat().st_mode)==0o600
    with pytest.raises(SystemExit):module.main()
    assert (tmp_path/'.env').read_text()==text

def test_reload_invalid_configuration_preserves_working_modes(rt,monkeypatch):
    old=rt.settings
    def invalid():raise ConnectionProblem('configuration','Invalid fixture config')
    monkeypatch.setattr(Settings,'load',invalid)
    with pytest.raises(ConnectionProblem):rt.reload()
    assert rt.settings is old and rt.modes=={'data':'local','features':'local'}

def test_source_schema_telemetry_refuses_unbounded_export(client,rt):
    unlock(client);rt.switch('hopsworks','local',2024,15,True,1.07)
    r=client.get('/api/dashboard/schema/f1-telemetry.json');assert r.status_code==200 and r.json()['record_count']==0 and 'driver and lap' in r.json()['provenance']
    assert client.get('/api/connections/telemetry?season=2023&round=24').status_code==422
    assert client.get('/api/connections/telemetry?driver=NOT').json()['record_count']==0
