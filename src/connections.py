"""Explicit cloud-mode control, operator authentication and background jobs.

Secrets remain in the server environment; the browser receives only presence
flags, safe errors, bounded data and an HttpOnly operator-session cookie.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from threading import RLock
from typing import Literal
import hashlib,hmac,json,secrets,time,uuid
from fastapi import APIRouter,Request,HTTPException,Query
from fastapi.responses import FileResponse,JSONResponse
from pydantic import BaseModel,Field
from .settings import Settings,ConnectionProblem,problem,ROOT
from .remote import HopsConnection,HopsSource,HopsFeatures

router=APIRouter(prefix='/api/connections',tags=['Server-side connections'])
def now():return datetime.now(timezone.utc).isoformat()

class Runtime:
    def __init__(self,settings=None,client=None):
        # client: optional Hopsworks SDK stand-in (tests); production imports the hopsworks module lazily.
        self.lock=RLock();self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='pitlane-connection');self.client=client
        self.settings_error=None
        try:self.settings=settings or Settings.load()
        except ConnectionProblem as e:self.settings=Settings();self.settings_error=e
        self.modes={'data':self.settings.data_mode,'features':self.settings.feature_mode};self.generation=uuid.uuid4().hex[:12]
        self.connection=None;self.source=None;self.hops=None;self.engines={};self.checks={};self.job=None;self.last_feature_plan=None
    @property
    def private(self):return self.settings_error is not None or self.modes['data']!='local' or self.modes['features']!='local'
    def hopsworks(self):
        if self.settings_error:raise self.settings_error
        if self.connection is None:self.connection=HopsConnection(self.settings,self.client)
        return self.connection
    def reader(self):
        if self.source is None:self.source=HopsSource(self.settings,self.hopsworks())
        return self.source
    def store(self):
        if self.hops is None:self.hops=HopsFeatures(self.settings,self.hopsworks())
        return self.hops
    def engine(self,data=None,features=None):
        if self.settings_error:raise self.settings_error
        data=data or self.modes['data'];features=features or self.modes['features'];key=(data,features)
        if key==('local','local'):
            from .dashboard_api import local_dashboard
            return local_dashboard()
        with self.lock:
            if key in self.engines:return self.engines[key]
            from .dashboard import DashboardEngine
            path=ROOT/'.cache'/f'dashboard-{self.generation}-{data}-{features}.sqlite'
            reader=self.store().read if features=='hopsworks' else None
            if data=='hopsworks':
                from .hops_dashboard import HopsDashboard
                db=HopsDashboard(self.reader(),feature_reader=reader,runtime_path=path)
            else:db=DashboardEngine(feature_reader=reader,runtime_path=path)
            db.feature_source='Hopsworks' if features=='hopsworks' else 'SQLite';self.engines[key]=db;return db
    def status(self):
        source_read=self.source.last_read if self.source else None;hops_read=self.hops.last_read if self.hops else None
        active_verified=(self.modes['data']=='hopsworks' and bool(source_read)) or (self.modes['features']=='hopsworks' and bool(hops_read))
        return {**self.settings.public(),'modes':dict(self.modes),'configuration_error':self.settings_error.public() if self.settings_error else None,'checks':dict(self.checks),'job':dict(self.job) if self.job else None,
            'cloud_connected':bool(active_verified),'last_source_read':source_read,'last_hopsworks_read':hops_read,'feature_plan':self.last_feature_plan,
            'scope':'Cloud modes apply to the historical dashboard and its pace features. Historical timing and all four original Dutch-GP labs remain the separately labeled public snapshot.',
            'persistence':'Mode switches affect this server process. Put the desired modes in .env for restart persistence. Credentials are never edited or returned by this API.'}
    def test(self,provider):
        try:
            result=self.reader().inspect() if provider=='source' else self.store().inspect()
            self.checks[provider]={**result,'tested_at':now()};return self.checks[provider]
        except ConnectionProblem as e:
            self.checks[provider]={'ok':False,'tested_at':now(),'error':e.public()};raise
    def feature_inputs(self,season,round_number,clean,cutoff,data=None):
        db=self.engine(data or self.modes['data'],'local');rows,_=db.compute_pace_rows(season,round_number,clean,cutoff);source=db.pace_source_id(season,round_number)
        return source,rows
    def feature_plan(self,season,round_number,clean,cutoff):
        source,rows=self.feature_inputs(season,round_number,clean,cutoff);batch,_=HopsFeatures(self.settings).batch(source,rows)
        self.last_feature_plan={'feature_group':self.settings.group_name,'version':self.settings.feature_version,'rows':len(rows),'batch_id':batch,'source_mode':self.modes['data'],'season':season,'round_number':round_number,'clean':clean,'cutoff':cutoff,'write_performed':False}
        return self.last_feature_plan
    def prepare(self,season,round_number,clean,cutoff,confirm_group):
        if not self.settings.allow_feature_writes:problem('writes_disabled','Set PITLANE_ALLOW_FEATURE_WRITES=true server-side only when you authorize feature-group creation/update.',403)
        if self.settings.prefix=='pitlane_yourteam':problem('namespace_required','Replace PITLANE_FEATURE_PREFIX with your own isolated team prefix before publishing.',422)
        if confirm_group!=self.settings.group_name:problem('confirmation_required','Type the exact configured feature-group name to authorize this write.',422)
        source,rows=self.feature_inputs(season,round_number,clean,cutoff)
        return self.store().publish(source,rows)
    def switch(self,data,features,season,round_number,clean,cutoff):
        if data not in {'local','hopsworks'} or features not in {'local','hopsworks'}:problem('invalid_mode','Unsupported backend mode.',422)
        if data!='local' or features!='local':
            if not self.settings.admin_ready:problem('admin_required','Configure a PITLANE_ADMIN_TOKEN of at least 24 characters before enabling cloud mode.',403)
        # Construct and verify the candidate first. Failures leave the old modes unchanged.
        candidate=self.engine(data,features)
        if data=='hopsworks':candidate.event(season,round_number);candidate.race_raw(season,round_number)
        if features=='hopsworks':
            rows,_=candidate.pace_rows(season,round_number,clean,cutoff)
            if not rows:problem('empty_features','The selected scope has no eligible feature rows to verify. Choose a supported race/filter.',409)
        self.modes={'data':data,'features':features}
        return {'modes':dict(self.modes),'verified_scope':{'season':season,'round_number':round_number,'clean':clean,'cutoff':cutoff},'restart_persistence':False}
    def reload(self):
        settings=Settings.load() # Failure preserves the previous working configuration.
        if (settings.data_mode!='local' or settings.feature_mode!='local') and not settings.admin_ready:problem('admin_required','Cloud mode requires a PITLANE_ADMIN_TOKEN of at least 24 characters.',403)
        self.settings=settings;self.settings_error=None;self.generation=uuid.uuid4().hex[:12];self.connection=None;self.source=None;self.hops=None;self.engines={};self.checks={};self.last_feature_plan=None
        self.modes={'data':settings.data_mode,'features':settings.feature_mode}
        return {'reloaded':True,'modes':dict(self.modes),'note':'Server environment overrides .env. Provider access has not yet been validated; unlock again if the operator token changed.'}
    def telemetry(self,season,round_number,session,driver,lap):
        from .hops_dashboard import scope,number,code_of
        if round_number>(22 if season==2023 else 24):problem('invalid_selection','Round is outside the selected season.',422)
        filters={'season':season,'round_number':round_number,'session_name':session,'driver_code':driver,'lap_number':lap}
        rows=scope(self.reader().read('telemetry',filters),filters)
        for r in rows:
            code_of(r)
            for field in ['session_time_s','speed','rpm','throttle','n_gear','x','y','z','drs']:number(r.get(field),field)
            if r.get('brake') is not None and not isinstance(r['brake'],bool):problem('schema_mismatch','Native telemetry brake must be boolean or null.')
        rows.sort(key=lambda r:r.get('session_time_s') if r.get('session_time_s') is not None else -float('inf'))
        return {'records':rows,'record_count':len(rows),'scope':filters,'source':'Hopsworks event telemetry; bounded native driver/lap slice, not the public interpolated Ghost Lap','limit':self.settings.telemetry_limit}
    def native_schema(self,index,season,round_number,session):
        db=self.engine();kind=index.removeprefix('f1-');db.event(season,round_number)
        filters={'season':season,'round_number':round_number,'session_name':session}
        if kind=='telemetry':return {'index':index,'records':[],'record_count':0,'provenance':'Native Hopsworks telemetry requires an additional driver and lap filter. Use Connections → Native telemetry slice.','notes':['No full-session or whole-corpus telemetry download is performed.']}
        if kind in {'sessions','results'}:rows=[r for r in getattr(db,'native_'+kind) if all(r.get(k)==v for k,v in filters.items())]
        else:rows=db.native(kind,season,round_number,session)
        return {'index':index,'records':rows,'record_count':len(rows),'provenance':'Native configured Hopsworks event feature group; no public supplemental fields added to this schema export.','notes':['Source units preserved: lap/sector milliseconds, session-relative seconds. Native track_status is retained.']}
    def submit(self,kind,operation):
        with self.lock:
            if self.job and self.job['state'] in {'queued','running'}:problem('busy','A connection job is already running. Wait for it to finish; no duplicate write was started.',409)
            job={'id':uuid.uuid4().hex,'kind':kind,'state':'queued','started_at':now(),'finished_at':None,'result':None,'error':None};self.job=job
            def run():
                job['state']='running'
                try:job['result']=operation();job['state']='succeeded'
                except ConnectionProblem as e:job['error']=e.public();job['state']='failed'
                except ValueError:job['error']={'code':'invalid_selection','message':'The selected season, round, driver or filter is not supported by the loaded source.'};job['state']='failed'
                except Exception:job['error']={'code':'integration_error','message':'Integration operation failed. Check SDK compatibility, schema and provider job status. Raw provider exceptions are withheld to protect credentials.'};job['state']='failed'
                finally:job['finished_at']=now()
            self.pool.submit(run);return dict(job)

RUNTIME=None
RUNTIME_LOCK=RLock()
def runtime():
    global RUNTIME
    with RUNTIME_LOCK:
        if RUNTIME is None:RUNTIME=Runtime()
        return RUNTIME

COOKIE='pitlane_operator'
def signature(token,payload):return hmac.new(token.encode(),payload.encode(),hashlib.sha256).hexdigest()
def authorized(request):
    r=runtime();token=r.settings.admin_token
    if not r.settings.admin_ready:return False
    header=request.headers.get('x-pitlane-admin-token')
    if header and hmac.compare_digest(header.encode(),token.encode()):return True
    value=request.cookies.get(COOKIE,'')
    try:
        expiry,nonce,sig=value.split('.');payload=expiry+'.'+nonce
        return int(expiry)>int(time.time()) and int(expiry)<=int(time.time())+28860 and hmac.compare_digest(signature(token,payload),sig)
    except (ValueError,TypeError):return False

def same_origin(request):
    origin=request.headers.get('origin')
    if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):raise HTTPException(403,'Cross-origin connection actions are not allowed.')

def require_operator(request):
    same_origin(request)
    if not runtime().settings.admin_ready:raise HTTPException(503,'Set PITLANE_ADMIN_TOKEN (at least 24 characters) in the server environment and restart before using connection controls.')
    if not authorized(request):raise HTTPException(401,'Unlock Connections with your operator token; provider API keys stay server-side.')

class Unlock(BaseModel):token:str=Field(min_length=1,max_length=1024)
class Selection(BaseModel):
    season:int=Field(default=2024,ge=2023,le=2024)
    round:int=Field(default=15,ge=1,le=24)
    clean:bool=True
    cutoff:float=Field(default=1.07,ge=1,le=1.5,allow_inf_nan=False)
class Publish(Selection):confirm_group:str=Field(max_length=100)
class Modes(Selection):
    data:Literal['local','hopsworks']='local'
    features:Literal['local','hopsworks']='local'

def submit(kind,operation):
    try:return JSONResponse(runtime().submit(kind,operation),status_code=202)
    except ConnectionProblem as e:raise HTTPException(e.status,e.message)

@router.get('/status')
def status(request:Request):
    d=runtime().status();d['unlocked']=authorized(request)
    if not d['unlocked']:
        # Native job/results can contain private dataset scopes. Only operator sees these.
        for k in ['job','feature_plan','last_source_read','last_hopsworks_read']:d[k]=None
        d['checks']={k:{'ok':v.get('ok'),'tested_at':v.get('tested_at')} for k,v in d['checks'].items()}
    return d

@router.post('/unlock')
def unlock(request:Request,body:Unlock):
    same_origin(request);r=runtime()
    if not r.settings.admin_ready:raise HTTPException(503,'Configure PITLANE_ADMIN_TOKEN server-side and restart. Provider keys must not be entered here.')
    if not hmac.compare_digest(body.token.encode(),r.settings.admin_token.encode()):raise HTTPException(401,'Incorrect operator token.')
    payload=str(int(time.time())+28800)+'.'+secrets.token_hex(16);response=JSONResponse({'unlocked':True,'expires_in_seconds':28800})
    response.set_cookie(COOKIE,payload+'.'+signature(r.settings.admin_token,payload),max_age=28800,httponly=True,secure=request.url.scheme=='https',samesite='strict',path='/api')
    return response

@router.post('/lock')
def lock(request:Request):
    same_origin(request);response=JSONResponse({'unlocked':False});response.delete_cookie(COOKIE,path='/api');return response

@router.post('/test/{provider}')
def test_provider(provider:Literal['source','features'],request:Request):
    require_operator(request);return submit('test-'+provider,lambda:runtime().test(provider))

@router.post('/feature-plan')
def feature_plan(request:Request,body:Selection):
    require_operator(request);return submit('feature-plan',lambda:runtime().feature_plan(body.season,body.round,body.clean,body.cutoff))

@router.post('/publish')
def publish(request:Request,body:Publish):
    require_operator(request);return submit('publish-features',lambda:runtime().prepare(body.season,body.round,body.clean,body.cutoff,body.confirm_group))

@router.post('/modes')
def modes(request:Request,body:Modes):
    require_operator(request);return submit('switch-modes',lambda:runtime().switch(body.data,body.features,body.season,body.round,body.clean,body.cutoff))

@router.post('/reload')
def reload(request:Request):
    require_operator(request);return submit('reload-configuration',lambda:runtime().reload())

@router.get('/telemetry')
def telemetry(request:Request,season:int=Query(2024,ge=2023,le=2024),round:int=Query(15,ge=1,le=24),session:Literal['Race','Qualifying']='Race',driver:str=Query('NOR',pattern='^[A-Z]{3}$'),lap:int=Query(72,ge=1,le=100)):
    require_operator(request)
    try:return runtime().telemetry(season,round,session,driver,lap)
    except ConnectionProblem as e:raise HTTPException(e.status,e.message)

@router.get('/guide')
def guide():return FileResponse(ROOT/'docs/CLOUD-SETUP.md',media_type='text/markdown',filename='PITLANE-CLOUD-SETUP.md')
