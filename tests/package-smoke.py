"""Verify the assembled ZIP, fresh extraction, and an optional running app.

Run from the project root after scripts/package.py. Uses already-installed Python
packages, not a clean OS/venv. --verify-only repeats without changing the report.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse, hashlib, io, json, os, re, stat, subprocess, sys, tempfile, urllib.request, zipfile

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--archive',type=Path,default=ROOT.parent/'pitlane-lab.zip')
p.add_argument('--live-url',default=None,help='Optional running API, e.g. http://127.0.0.1:8000')
p.add_argument('--verify-only',action='store_true',help='Do not rewrite qa/package-smoke.json')
args=p.parse_args()
checks=[]
report={'passed':False,'app_version':'2.2.0','tested_at':datetime.now(timezone.utc).isoformat(),'checks':checks,
        'scope':'Fresh extraction with installed Python dependencies; no clean-OS or live cloud claim.',
        'repack_note':'The final repack includes this report. --verify-only repeats all checks without modifying it.'}
def check(name,condition=True):
    if not condition:raise AssertionError(name)
    checks.append(name)
def http(path):
    with urllib.request.urlopen(args.live_url.rstrip('/')+path,timeout=60) as r:
        assert r.status==200,(path,r.status)
        return r.read()

CHILD=r'''
from pathlib import Path
import io,json,re,zipfile
from fastapi.testclient import TestClient
from app import app
root=Path.cwd()
assert app.version=='2.2.0'
paths=['/','/api/health','/api/bootstrap','/api/ghost','/api/strategy','/api/pace','/api/dna/challenge','/api/pipeline',
 '/api/dashboard/catalog','/api/dashboard/season?season=2024&round=24','/api/dashboard/season?season=2023&round=22',
 '/api/dashboard/race?season=2024&round=15','/api/dashboard/race?season=2024&round=4','/api/dashboard/race?season=2023&round=1',
 '/api/dashboard/driver?season=2024&round=15&driver=norris','/api/dashboard/compare?season=2024&round=15&a=norris&b=piastri',
 '/api/dashboard/pits?season=2024&round=15','/api/dashboard/tracks?season=2024',
 '/api/dashboard/weather?season=2024&round=15&session=Qualifying','/api/dashboard/coverage','/api/download/brief']
result={'statuses':{},'assets':[],'schema_counts':{},'csv_kinds':[]}
with TestClient(app) as c:
 responses={}
 for path in paths:
  r=c.get(path);assert r.status_code==200,(path,r.status_code,r.text[:300]);result['statuses'][path]=r.status_code;responses[path]=r
 assert len(responses['/api/dashboard/catalog'].json()['events'])==46
 assert responses['/api/dashboard/season?season=2024&round=24'].json()['driver_standings'][0]['points']==437
 assert responses['/api/dashboard/season?season=2024&round=24'].json()['constructor_standings'][0]['points']==666
 assert responses['/api/dashboard/season?season=2023&round=22'].json()['driver_standings'][0]['points']==575
 assert responses['/api/dashboard/season?season=2023&round=22'].json()['constructor_standings'][0]['points']==860
 cv=responses['/api/dashboard/coverage'].json();assert cv['manifest']['lap_rows']==51108 and cv['manifest']['total_weather_rows']==11238
 assert cv['result_readback_rows']==2078 and cv['local_feature_rows']>0
 assert cv['quality']['lap_rows_missing_duration']==204 and cv['quality']['stint_rows_missing_boundary']==23
 for index,count in [('f1-sessions',1),('f1-results',20),('f1-laps',1426),('f1-weather',153),('f1-telemetry',1444)]:
  r=c.get(f'/api/dashboard/schema/{index}.json?season=2024&round=15&session=Race');assert r.status_code==200
  d=r.json();assert d['record_count']==count and len(d['records'])==count and d['provenance'];result['schema_counts'][index]=count
 assert c.get('/api/dashboard/schema/f1-telemetry.json?season=2023&round=1').json()['record_count']==0
 assert len(responses['/api/dashboard/weather?season=2024&round=15&session=Qualifying'].json()['rows'])==79
 for kind in ['results','laps','weather','pits','stints','race-control','features','sessions','driver-stats','constructor-stats']:
  r=c.get(f'/api/dashboard/export/{kind}.csv?season=2024&round=15');assert r.status_code==200 and len(r.content)>20 and '.csv' in r.headers['content-disposition'];result['csv_kinds'].append(kind)
 assert c.get('/api/dashboard/race?season=2026').status_code==422
 assert c.get('/api/dashboard/race?cutoff=nan').status_code==422
 html=responses['/'].text
 for url in re.findall(r'(?:src|href)="([^"]+)"',html):
  if url.startswith('/assets/'):
   assert c.get(url).status_code==200;result['assets'].append(url)
 for pattern in ['Dashboard-*.js','TelemetryScene-*.js','GhostWorkspace-*.js','FleetScene-*.js','sceneGeometry-*.js']:
  asset=next((root/'web/assets').glob(pattern));url='/assets/'+asset.name;assert c.get(url).status_code==200;result['assets'].append(url)
 for asset in sorted((root/'web/assets').iterdir()):
  if asset.is_file():assert c.get('/assets/'+asset.name).status_code==200
 result['all_bundled_assets_served']=True
 assert not re.search(r'(?:src|href)="https?://',html)
 ghost=responses['/api/ghost'].json();assert len(ghost['a']['trace']['rpm'])==361 and abs(ghost['finish_delta']-.935)<1e-9
 assert abs(responses['/api/strategy'].json()['actual_gap']+22.896)<1e-9
 guide=responses['/api/download/brief'].text;assert 'dashboard tour' in guide.lower() and 'Enable sound' in guide
 state=c.get('/api/connections/status').json();assert state['modes']=={'data':'local','features':'local'} and not state['hopsworks']['configured'] and not state['admin_configured']
 assert c.post('/api/connections/test/source').status_code==503
 assert c.get('/api/connections/guide').status_code==200 and 'PITLANE_ADMIN_TOKEN' in c.get('/api/connections/guide').text
 assert c.post('/_qa/reset').status_code in (404,405) # fixture control must not exist in production
 result['credential_free_safe_defaults']=True;result['cloud_setup_guide']=True;result['no_production_fixture_reset']=True
 field=c.get('/api/ghost/field');assert field.status_code==200 and len(field.json()['drivers'])==4
 replay=c.get('/api/replay/race');assert replay.status_code==200
 manifest=replay.json()['manifest'];assert manifest['driver_count']==20 and manifest['location_samples']==218520 and manifest['car_samples']==110300
 assert sum(d['out_of_range_channels']['brake'] for d in manifest['drivers'])==5
 for row in manifest['drivers']:
  response=c.get('/api/replay/driver/'+row['driver_code']);assert response.status_code==200 and response.content==(root/'data/replay'/row['file']).read_bytes()
 assert c.get('/api/replay/driver/XXX').status_code==404
 result['multi_car_replay']={'comparison_drivers':4,'race_drivers':20,'location_samples':218520,'telemetry_samples':110300,'all_driver_files_verified':True}

 assert not (root.parent/'pitlane-lab.zip').exists()
 r=c.get('/api/download/project');assert r.status_code==200
 with zipfile.ZipFile(io.BytesIO(r.content)) as z:
  assert z.testzip() is None
  assert 'pitlane-lab/docs/DASHBOARD-GUIDE.md' in z.namelist()
  assert 'pitlane-lab/data/dashboard/race_2024_24.json' in z.namelist()
 result['on_demand_zip_bytes']=len(r.content)
 result['ghost_rpm_points']=361;result['classified_actual_gap']=-22.896
print('PACKAGE_RESULT='+json.dumps(result))
'''
try:
    (ROOT/'.cache').mkdir(exist_ok=True)
    archive=args.archive.resolve();raw=archive.read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        check('ZIP integrity',z.testzip() is None)
        names=z.namelist();report['archive_files']=len(names)
        check('Safe rooted paths and no symlink members',all(n.startswith('pitlane-lab/') and '..' not in Path(n).parts and '\\' not in n for n in names) and not any(stat.S_ISLNK(i.external_attr>>16) for i in z.infolist()))
        excluded={'.git','.cache','.venv','node_modules','__pycache__','.pytest_cache','.hopsworks','.hsfs','connection_state','certificates','.secrets'}
        check('Dependencies, caches and secret/sidecar files excluded',not any(excluded.intersection(Path(n).parts) or (Path(n).name.startswith('.env') and Path(n).name!='.env.example') or n.endswith(('.key','.pem','.jks','.p12','.pfx','.crt','.cer','-journal','-wal','-shm')) for n in names))
        required=['src/dashboard.py','src/dashboard_api.py','frontend/src/dashboard/Timing.jsx','frontend/src/dashboard/SeasonStatistics.jsx','frontend/src/replay/TelemetryScene.jsx','frontend/src/replay/EngineAudio.jsx','tests/test_dashboard.py','tests/dashboard-model.mjs','tests/dashboard-browser.mjs','tests/replay-browser.mjs','tests/package-smoke.py','docs/DASHBOARD-GUIDE.md','docs/CLOUD-SETUP.md','docs/MULTI-CAR-REPLAY.md','src/race_replay.py','scripts/prepare_race_replay.py','data/replay/manifest.json','frontend/src/replay/GhostWorkspace.jsx','frontend/src/replay/FleetScene.jsx','frontend/src/replay/fleetModel.js','tests/test_race_replay.py','tests/fleet-model.mjs','tests/fleet-browser.mjs','src/settings.py','src/remote.py','src/connections.py','src/hops_dashboard.py','scripts/connect_cloud.py','.env.example','tests/test_connections.py','tests/connections-browser.mjs','DATA-NOTICE.md','QA-REPORT.md','licenses/three-LICENSE.txt','licenses/Inter-OFL.txt','data/dashboard/manifest.json','data/manifest.json','web/index.html']
        check('Dashboard, original labs, test suites, guides, licenses and all three curated data scopes included',all('pitlane-lab/'+n in names for n in required))
        check('Version 2.2 package metadata',json.loads(z.read('pitlane-lab/frontend/package.json'))['version']=='2.2.0')
        manifest=json.loads(z.read('pitlane-lab/data/dashboard/manifest.json'))
        check('All 93 dashboard archive SHA-256 hashes match',len(manifest['sha256'])==93 and all(hashlib.sha256(z.read('pitlane-lab/data/dashboard/'+name)).hexdigest()==digest for name,digest in manifest['sha256'].items()))
        replay_manifest=json.loads(z.read('pitlane-lab/data/replay/manifest.json'))
        check('All 20 multi-car replay SHA-256 hashes match',len(replay_manifest['sha256'])==20 and all(hashlib.sha256(z.read('pitlane-lab/data/replay/'+name)).hexdigest()==digest for name,digest in replay_manifest['sha256'].items()))
        for name,total in [('fleet-model-results.json',39),('fleet-browser-results.json',41),('dashboard-model-results.json',2846),('dashboard-browser-results.json',137),('connections-browser-results.json',63)]:
            check('Included passing '+name,json.loads(z.read('pitlane-lab/qa/'+name))['passed']==total)
        if args.verify_only:
            previous=json.loads(z.read('pitlane-lab/qa/package-smoke.json'))
            check('Final ZIP includes current successful 2.2 package-smoke evidence',previous['passed'] and previous['app_version']=='2.2.0')
        with tempfile.TemporaryDirectory(prefix='package-smoke-',dir=ROOT/'.cache') as tmp:
            z.extractall(tmp);extracted=Path(tmp)/'pitlane-lab'
            child=subprocess.run([sys.executable,'-c',CHILD],cwd=extracted,env={**os.environ,'PYTHONPATH':str(extracted)},capture_output=True,text=True,timeout=100)
            if child.returncode:raise RuntimeError(child.stdout[-4000:]+'\n'+child.stderr[-4000:])
            line=next(x for x in child.stdout.splitlines() if x.startswith('PACKAGE_RESULT='));report['extraction']=json.loads(line.split('=',1)[1])
            for name in ['Fresh extraction boots version 2.2 and serves 21 original/dashboard routes','Both final championships match independent totals','Archive counts, quality gaps and actual local read-back preserved','All five schema exports have correct counts and unsupported telemetry stays empty','All ten CSV exports work','Invalid year and nonfinite cutoff rejected','Bundled entrypoint and lazy dashboard/3D assets served without CDN references','Original recorded RPM, finish delta and classified strategy anchor preserved','Updated dashboard/3D demo guide downloadable','Fresh extraction defaults to local modes with no provider credentials and refuses connection actions','Cloud setup guide downloads; QA reset endpoint absent in production','Four-car comparison and all 20 shared-clock replay endpoints work from fresh extraction','All bundled current and retained hashed assets are served','On-demand ZIP generation works from extracted source']:
                check(name)
    if args.live_url:
        live_paths=['/','/api/health','/api/ghost','/api/strategy','/api/pace','/api/dna/challenge','/api/dashboard/catalog','/api/dashboard/season?season=2024&round=24','/api/dashboard/race?season=2024&round=15','/api/dashboard/coverage','/api/ghost/field','/api/replay/race','/api/replay/driver/ZHO']
        for path in live_paths:http(path)
        check('Live preview serves dashboard and all four original experiences')
        check('Live project download byte-matches assembled ZIP',http('/api/download/project')==raw)
        check('Live demo guide exposes dashboard and 3D/audio tour',b'dashboard tour' in http('/api/download/brief').lower() and b'Enable sound' in http('/api/download/brief'))
        report['live_paths']=live_paths
    report['passed']=True
    print(f'PASS {len(checks)} package checks; {len(raw):,} ZIP bytes; {report["archive_files"]} files')
except Exception as e:
    report['error']=str(e);print('FAIL',e,file=sys.stderr)
finally:
    if not args.verify_only:(ROOT/'qa/package-smoke.json').write_text(json.dumps(report,indent=2)+'\n')
if not report['passed']:sys.exit(1)
