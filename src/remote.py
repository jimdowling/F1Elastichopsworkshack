"""Bounded, read-only Hopsworks source reader and explicit-write pace feature store.

Both use one server-side Hopsworks login. No raw SDK exception is sent to
clients: provider errors can echo credentials. Source reads never insert into,
alter or delete the configured event feature groups.
"""
import hashlib, json, math, threading, time
from datetime import date,datetime
import pandas as pd
from .settings import ConnectionProblem, problem, KINDS,ROOT

COMMON=['season','round_number','event_name','session_name']
FIELDS={
 'sessions':COMMON+['country','location','session_date'],
 'results':COMMON+['driver_number','driver_code','full_name','team_name','position','points','grid_position','status','fastest_lap_ms'],
 'laps':COMMON+['driver_code','team_name','lap_number','lap_duration_ms','duration_sector_1','duration_sector_2','duration_sector_3','compound','tyre_life','is_pit_out_lap','is_pit_in_lap','track_status','position'],
 'weather':COMMON+['session_time_s','air_temperature','track_temperature','humidity','pressure','wind_speed','wind_direction','rainfall'],
 'telemetry':COMMON+['driver_code','team_name','lap_number','session_time_s','speed','rpm','throttle','brake','drs','n_gear','x','y','z']}
INTEGER={'tinyint','smallint','int','integer','bigint'}
NUMERIC=INTEGER|{'float','double','decimal'}
TEXT={'string','varchar','char'}
REQUIRED={
 'sessions':{'season':NUMERIC,'round_number':NUMERIC,'session_name':TEXT,'event_name':TEXT,'session_date':{'timestamp','date','string'}},
 'results':{'season':NUMERIC,'round_number':NUMERIC,'session_name':TEXT,'driver_code':TEXT,'position':NUMERIC,'points':NUMERIC,'status':TEXT},
 'laps':{'season':NUMERIC,'round_number':NUMERIC,'session_name':TEXT,'driver_code':TEXT,'lap_number':NUMERIC,'lap_duration_ms':NUMERIC,'is_pit_in_lap':{'boolean'},'is_pit_out_lap':{'boolean'}},
 'weather':{'season':NUMERIC,'round_number':NUMERIC,'session_name':TEXT,'session_time_s':NUMERIC},
 'telemetry':{'season':NUMERIC,'round_number':NUMERIC,'session_name':TEXT,'driver_code':TEXT,'lap_number':NUMERIC,'session_time_s':NUMERIC,'speed':NUMERIC}}
FILTERS={'season','round_number','session_name','driver_code','lap_number'}

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def base_type(value):return str(value or '').lower().split('(')[0].split('<')[0].strip()

def plain(value,typ=None):
    """pandas/numpy cell -> JSON value; nulls stay null, integral columns stay integers."""
    if value is None or value is pd.NA or value is pd.NaT:return None
    if isinstance(value,(list,dict,tuple)):return value
    if isinstance(value,(pd.Timestamp,datetime,date)):return value.isoformat()
    if hasattr(value,'item'):value=value.item()
    if isinstance(value,float):
        if math.isnan(value):return None
        if typ in INTEGER and value.is_integer():return int(value)
    return value

class HopsConnection:
    """One authenticated feature-store handle shared by source reads and pace features."""
    def __init__(self,settings,client=None):
        self.settings=settings;self.client=client;self.store=None;self.lock=threading.RLock()
    def connect(self):
        with self.lock:
            if self.store is not None:return self.store
            if not self.settings.hops_ready:problem('not_configured','Set HOPSWORKS_HOST, HOPSWORKS_PROJECT and HOPSWORKS_API_KEY server-side, then reload configuration.')
            try:
                if self.client is None:
                    import hopsworks
                    self.client=hopsworks
                host=self.settings.hops_host;port=443
                if ':' in host:host,port=host.rsplit(':',1);port=int(port)
                certs=ROOT/'.cache/hopsworks-certs';certs.mkdir(parents=True,exist_ok=True)
                project=self.client.login(host=host,port=port,project=self.settings.hops_project,api_key_value=self.settings.hops_key,hostname_verification=True,trust_store_path=self.settings.hops_ca or None,cert_folder=str(certs),engine='python')
                self.store=project.get_feature_store();return self.store
            except ImportError:problem('sdk_missing','Install requirements-integrations.txt in the server Python environment before connecting Hopsworks.')
            except Exception:problem('hopsworks_connection','Hopsworks connection failed. Check host/project/key, SDK/server compatibility and feature-store permissions.')

def connection(settings,client):return client if isinstance(client,HopsConnection) else HopsConnection(settings,client)

class HopsSource:
    """Bounded reads of the event feature groups (f1_sessions, f1_results, ...)."""
    def __init__(self,settings,client=None):
        if not settings.hops_ready:problem('not_configured','Set HOPSWORKS_HOST, HOPSWORKS_PROJECT and HOPSWORKS_API_KEY in the server environment, then reload configuration.')
        self.settings=settings;self.connection=connection(settings,client)
        self.lock=threading.RLock();self.groups={};self.types={};self.cache={};self.counts={};self.last_read=None
    def group(self,kind):
        if kind not in FIELDS:problem('invalid_source','Unsupported event feature group.',422)
        if kind in self.groups:return self.groups[kind]
        store=self.connection.connect();name=self.settings.sources[kind]
        try:fg=store.get_feature_group(name=name,version=self.settings.source_version)
        except Exception:fg=None
        if fg is None:problem('missing_source',f'Hopsworks feature group {name} v{self.settings.source_version} is unavailable. Load the event data (scripts/connect_cloud.py load-source) or check read permission.')
        try:types={f.name:base_type(f.type) for f in fg.features}
        except Exception:problem('invalid_response',f'Hopsworks did not return a schema for {name}.')
        missing=[k for k,allowed in REQUIRED[kind].items() if types.get(k) not in allowed]
        if missing:problem('schema_mismatch',f'{kind} feature group has missing/incompatible features: '+', '.join(missing)+'. Verify the event schema and units.')
        self.groups[kind]=fg;self.types[kind]=types;return fg
    def predicate(self,fg,filters):
        condition=fg['season'].isin([2023,2024])
        for k,v in filters.items():
            if k not in FILTERS:problem('invalid_filter','Only bounded event/driver/lap filters are supported.',422)
            condition=condition&(fg[k]==v)
        return condition
    def fetch(self,kind,filters,columns):
        fg=self.group(kind)
        try:frame=fg.select(columns).filter(self.predicate(fg,filters)).read()
        except ConnectionProblem:raise
        except Exception:problem('source_read','Hopsworks source read failed. Check offline storage/Arrow Flight access and SDK/server compatibility; no partial dataset was activated.')
        if frame is None:return pd.DataFrame(columns=columns)
        if not isinstance(frame,pd.DataFrame):problem('invalid_response','Hopsworks returned an unexpected dataframe type.')
        return frame
    def inspect(self):
        result=[]
        with self.lock:
            for kind in KINDS:
                try:
                    self.group(kind)
                    # Never count the full telemetry corpus; its schema check is the readiness signal.
                    count=None if kind=='telemetry' else len(self.fetch(kind,{},['season']))
                    if count is not None:self.counts[kind]=count
                    result.append({'kind':kind,'name':self.settings.sources[kind],'ok':True,'count':count})
                except ConnectionProblem as e:result.append({'kind':kind,'name':self.settings.sources[kind],'ok':False,'error':e.public()})
        return {'ok':all(r['ok'] for r in result),'dashboard_ready':all(r['ok'] for r in result if r['kind']!='telemetry'),'groups':result,'version':self.settings.source_version,'read_only':True}
    def read(self,kind,filters,limit=None,fresh=False):
        if kind not in FIELDS:problem('invalid_source','Unsupported event feature group.',422)
        if kind=='telemetry' and not FILTERS.issubset(filters):problem('unbounded_telemetry','Telemetry requires a season, round, session, driver and lap.',422)
        default=self.settings.metadata_limit if kind in {'sessions','results'} else self.settings.lap_limit if kind=='laps' else self.settings.weather_limit if kind=='weather' else self.settings.telemetry_limit
        limit=min(default,limit or default);key=canonical([kind,filters,limit])
        with self.lock:
            if not fresh and key in self.cache and time.monotonic()-self.cache[key][0]<self.settings.cache_seconds:return json.loads(self.cache[key][1])
            self.group(kind);types=self.types[kind];columns=[f for f in FIELDS[kind] if f in types]
            frame=self.fetch(kind,filters,columns)
            if len(frame)>limit:problem('slice_limit',f'The {kind} slice exceeds the configured {limit:,}-row cap. Narrow the selection or explicitly raise the server-side cap.',413)
            rows=[{f:plain(r.get(f),types.get(f)) for f in FIELDS[kind]} for r in frame.to_dict('records')]
            if len(self.cache)>=128:self.cache.pop(next(iter(self.cache)))
            self.cache[key]=(time.monotonic(),canonical(rows));self.last_read={'kind':kind,'rows':len(rows),'scope':dict(filters),'feature_group':self.settings.sources[kind]}
            return rows

class HopsFeatures:
    """Dashboard pace batches only. GET/read never creates or inserts a group."""
    def __init__(self,settings,client=None):
        self.settings=settings;self.connection=connection(settings,client);self.store=None;self.lock=threading.RLock();self.cache={};self.last_read=None
    def connect(self):
        if self.store is None:self.store=self.connection.connect()
        return self.store
    def inspect(self):
        with self.lock:self.connect()
        return {'ok':True,'feature_group':self.settings.group_name,'version':self.settings.feature_version,'write_performed':False,'note':'Authenticated feature-store access; this does not prove ingestion or offline-data read permission.'}
    def batch(self,source,rows):
        # source includes a digest of the exact lap slice, not only season/filter IDs.
        batch=digest({'schema':'pitlane_race_pace_v1','group':self.settings.group_name,'version':self.settings.feature_version,'source':source,'rows':rows})
        records=[]
        for r in rows:
            records.append({'id':digest([batch,r['id']]),'batch_id':batch,'row_id':r['id'],'source_id':source,
                **{k:r[k] for k in ['season','round_number','driver_code','samples','median_s','mean_s','std_s','iqr_s','cutoff','pit_outlier_filter']},'payload_json':canonical(r)})
        return batch,pd.DataFrame(records)
    def _read(self,fg,batch,expected):
        try:
            # Server-side filter: never download the entire feature group.
            frame=fg.select_all().filter(fg['batch_id']==batch).read()
        except Exception:problem('feature_read','Hopsworks batch read failed. Check offline storage/Flight access and SDK/server compatibility.')
        if frame is None or len(frame)==0:problem('features_missing','No Hopsworks batch exists for this exact source, race and filter. Publish it in Connections first.',409)
        need={'id','batch_id','row_id','source_id','payload_json','season','round_number','driver_code','samples','median_s','mean_s','std_s','iqr_s','cutoff','pit_outlier_filter'}
        if not need.issubset(frame.columns) or not frame.id.is_unique or len(frame)!=len(expected):problem('feature_readback','Hopsworks batch columns, IDs or row count did not verify.',409)
        actual={str(r['id']):r for r in frame.to_dict('records')};out=[]
        for e in expected.to_dict('records'):
            a=actual.get(e['id'])
            if a is None or a['batch_id']!=batch:problem('feature_readback','Hopsworks batch identity did not verify.',409)
            try:
                payload=json.loads(a['payload_json'])
                if canonical(payload)!=e['payload_json']:raise ValueError()
                for k in need-{'payload_json'}:
                    if isinstance(e[k],(float,int)) and not isinstance(e[k],bool):
                        if not math.isclose(float(a[k]),float(e[k]),rel_tol=1e-9,abs_tol=1e-6):raise ValueError()
                    elif a[k]!=e[k]:raise ValueError()
                out.append(payload)
            except (ValueError,TypeError,KeyError):problem('feature_readback','Hopsworks feature values differ from the selected source/filter batch. Use a new version or verify the source.',409)
        self.last_read={'batch_id':batch,'rows':len(out),'feature_group':self.settings.group_name,'version':self.settings.feature_version,'verified_values':True}
        return out
    def read(self,source,rows):
        if not rows:return []
        batch,frame=self.batch(source,rows)
        with self.lock:
            if batch in self.cache and time.monotonic()-self.cache[batch][0]<self.settings.cache_seconds:return json.loads(self.cache[batch][1])
            store=self.connect()
            try:fg=store.get_feature_group(name=self.settings.group_name,version=self.settings.feature_version)
            except Exception:problem('features_missing','The configured Hopsworks feature group is unavailable. Publish the selected-race batch first, or check read permission.',409)
            out=self._read(fg,batch,frame)
            if len(self.cache)>=64:self.cache.pop(next(iter(self.cache)))
            self.cache[batch]=(time.monotonic(),canonical(out));return out
    def publish(self,source,rows):
        if not rows:problem('empty_features','No eligible pace features to publish for this selection.',422)
        batch,frame=self.batch(source,rows)
        with self.lock:
            store=self.connect()
            try:
                fg=store.get_or_create_feature_group(name=self.settings.group_name,version=self.settings.feature_version,primary_key=['id'],online_enabled=False,
                    description='Pitlane dashboard pace summaries. Batch IDs bind exact source laps, season, round and filter. Descriptive, not a live forecasting model.')
                fg.insert(frame,write_options={'wait_for_job':True})
            except Exception:problem('feature_write','Hopsworks write failed. Check write/storage permissions, existing group schema, SDK compatibility and provider job status. A partial write may exist; retry is ID-idempotent.')
            out=self._read(fg,batch,frame) # No activation before a real value-verified read-back.
            self.cache[batch]=(time.monotonic(),canonical(out))
            return {**self.last_read,'write_performed':True,'active_mode_changed':False}
