"""Configure/check the Hopsworks connection without ever echoing provider credentials.

init creates a private .env. check/plan do not write provider data. load-source
copies the public archive into the event source feature groups; publish writes
one pace batch. Both require --write and PITLANE_ALLOW_FEATURE_WRITES=true;
publish also needs a unique group prefix and a name confirmation. The web
server must be restarted/reloaded after configuration.
"""
from pathlib import Path
import argparse,json,os,secrets,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.settings import Settings,ConnectionProblem
from src.connections import Runtime

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('init',help='Create .env with a random operator token; never overwrite an existing file')
    check=sub.add_parser('check',help='Read-only Hopsworks access checks');check.add_argument('--provider',choices=['source','features','all'],default='all')
    load=sub.add_parser('load-source',help='Copy the public 2023-2024 archive into the Hopsworks event feature groups (dry run without --write)')
    load.add_argument('--season',type=int,choices=[2023,2024],action='append');load.add_argument('--kind',choices=['sessions','results','laps','weather','telemetry'],action='append');load.add_argument('--write',action='store_true')
    for name in ['plan','publish']:
        s=sub.add_parser(name);s.add_argument('--season',type=int,choices=[2023,2024],default=2024);s.add_argument('--round',type=int,default=15);s.add_argument('--cutoff',type=float,default=1.07);s.add_argument('--all-laps',action='store_true');s.add_argument('--data-source',choices=['local','hopsworks'])
        if name=='publish':s.add_argument('--write',action='store_true');s.add_argument('--confirm-group',default='')
    a=p.parse_args()
    if a.command=='init':
        path=ROOT/'.env';template=(ROOT/'.env.example').read_text();token=secrets.token_urlsafe(32)
        try:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f:f.write(template.replace('PITLANE_ADMIN_TOKEN=\n','PITLANE_ADMIN_TOKEN='+token+'\n',1))
        except FileExistsError:p.error('.env already exists; it was NOT overwritten. Edit it privately.')
        print('Created .env with a random operator token. Open it privately to add provider credentials. Restart the server afterward. No provider was contacted.');return
    rt=Runtime(Settings.load())
    if a.command=='check':
        reports={}
        for provider in (['source','features'] if a.provider=='all' else [a.provider]):
            try:reports[provider]=rt.test(provider)
            except ConnectionProblem as e:reports[provider]={'ok':False,'error':e.public()}
        print(json.dumps(reports,indent=2));sys.exit(0 if all(v['ok'] for v in reports.values()) else 1)
    if a.command=='load-source':
        load_source(rt.settings,a);return
    if not 1<=a.round<=(22 if a.season==2023 else 24):p.error('Round is outside the selected season.')
    if a.data_source:rt.modes['data']=a.data_source
    if rt.modes['data']=='local':
        # CLI planning must not clear the running web server's SQLite cache.
        from src.dashboard import DashboardEngine
        from src import dashboard_api
        dashboard_api.INSTANCE=DashboardEngine(runtime_path=ROOT/'.cache'/f'cli-dashboard-{os.getpid()}.sqlite')
    if a.command=='publish' and a.write:
        result=rt.prepare(a.season,a.round,not a.all_laps,a.cutoff,a.confirm_group)
    else:
        result=rt.feature_plan(a.season,a.round,not a.all_laps,a.cutoff)
        if a.command=='publish':result['note']='DRY RUN. No provider writes. Add --write and --confirm-group only after reviewing this plan.'
    print(json.dumps(result,indent=2))
    if a.command=='publish' and a.write:print('Verified remote read-back. This does not change a running server mode; activate Hopsworks explicitly in Connections or the server environment.')

def load_source(settings,a):
    from src.dashboard import DashboardEngine
    from src.cloud import source_frames,HopsworksPublisher
    from src.remote import FIELDS
    db=DashboardEngine(runtime_path=ROOT/'.cache'/f'cli-dashboard-{os.getpid()}.sqlite')
    frames=source_frames(db,a.kind or list(FIELDS),tuple(a.season or (2023,2024)))
    plan=[{'feature_group':settings.sources[k],'version':settings.source_version,'rows':len(f),'features':list(f.columns)} for k,f in frames.items()]
    print(json.dumps({'mode':'WRITE' if a.write else 'DRY RUN — no provider calls','plan':plan},indent=2))
    if not a.write:return
    if not settings.allow_feature_writes:raise ConnectionProblem('writes_disabled','Set PITLANE_ALLOW_FEATURE_WRITES=true server-side to authorize feature-group creation/update.',403)
    print(json.dumps(HopsworksPublisher(settings).load_sources(frames),indent=2))
    print('Source feature groups loaded and ID-verified. Switch the dashboard data provider to Hopsworks in Connections or set PITLANE_DATA_MODE=hopsworks.')

if __name__=='__main__':
    try:main()
    except ConnectionProblem as e:
        print(json.dumps({'ok':False,'error':e.public()},indent=2),file=sys.stderr);sys.exit(1)
    except ValueError:
        print('Invalid season/round/filter selection. No provider write was performed.',file=sys.stderr);sys.exit(1)
