"""Bounded, read-only Elastic adapter and explicit-write Hopsworks feature store.

No raw HTTP/SDK exception is sent to clients: provider errors can echo credentials.
PIT creation/cleanup changes only a temporary search context, never source data.
"""
import hashlib, json, math, threading, time
from urllib.parse import quote
import pandas as pd
import requests
from .settings import ConnectionProblem, problem, KINDS,ROOT

COMMON=['season','round_number','event_name','session_name']
FIELDS={
 'sessions':COMMON+['country','location','session_date'],
 'results':COMMON+['driver_number','driver_code','full_name','team_name','position','points','grid_position','status','fastest_lap_ms'],
 'laps':COMMON+['driver_code','team_name','lap_number','lap_duration_ms','duration_sector_1','duration_sector_2','duration_sector_3','compound','tyre_life','is_pit_out_lap','is_pit_in_lap','track_status','position'],
 'weather':COMMON+['session_time_s','air_temperature','track_temperature','humidity','pressure','wind_speed','wind_direction','rainfall'],
 'telemetry':COMMON+['driver_code','team_name','lap_number','session_time_s','speed','rpm','throttle','brake','drs','n_gear','x','y','z']}
NUMERIC={'byte','short','integer','long','float','double','half_float','scaled_float','unsigned_long'}
TEXT={'keyword','constant_keyword','wildcard'}
REQUIRED={
 'sessions':{'season':NUMERIC,'round_number':NUMERIC,'session_name':TEXT,'event_name':TEXT,'session_date':{'date','date_nanos','keyword'}},
 'results':{'season':NUMERIC,'round_number':NUMERIC,'session_name':TEXT,'driver_code':TEXT,'position':NUMERIC,'points':NUMERIC,'status':TEXT},
 'laps':{'season':NUMERIC,'round_number':NUMERIC,'session_name':TEXT,'driver_code':TEXT,'lap_number':NUMERIC,'lap_duration_ms':NUMERIC,'is_pit_in_lap':{'boolean'},'is_pit_out_lap':{'boolean'}},
 'weather':{'season':NUMERIC,'round_number':NUMERIC,'session_name':TEXT,'session_time_s':NUMERIC},
 'telemetry':{'season':NUMERIC,'round_number':NUMERIC,'session_name':TEXT,'driver_code':TEXT,'lap_number':NUMERIC,'session_time_s':NUMERIC,'speed':NUMERIC}}

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()

class ElasticReader:
    def __init__(self,settings,session=None):
        if not settings.elastic_ready:problem('not_configured','Set the Elastic source URL and API key in the server environment, then reload configuration.')
        self.settings=settings;self.session=session or requests.Session();self.session.trust_env=False
        self.session.headers.update({'Authorization':'ApiKey '+settings.elastic_key,'Content-Type':'application/json'})
        self.lock=threading.RLock();self.caps={};self.cache={};self.counts={};self.last_read=None
    def request(self,method,path,body=None,params=None):
        # Fixed paths are constructed internally, never from browser input.
        try:
            r=self.session.request(method,self.settings.elastic_url+path,json=body,params=params,timeout=(5,self.settings.timeout),verify=self.settings.elastic_ca or True,allow_redirects=False)
        except requests.Timeout:problem('timeout','Elastic request timed out. Check connectivity or retry a smaller slice.')
        except requests.RequestException:problem('unreachable','Cannot reach Elastic. Check the source URL, network and CA certificate; TLS verification remains enabled.')
        if r.status_code in (401,403):problem('authentication' if r.status_code==401 else 'permission','Elastic rejected access. Check the API key and read/view_index_metadata permissions on the configured source indices.')
        if r.status_code==404:problem('missing_index','An Elastic source index or search context is unavailable. Check index aliases and retry.')
        if r.status_code==429:problem('rate_limit','Elastic is rate-limiting requests. Wait, then retry.')
        if not 200<=r.status_code<300:problem('provider_error','Elastic rejected the request. Check deployment compatibility and server-side permissions; source data was not written.')
        try:return r.json()
        except ValueError:problem('invalid_response','Elastic returned an invalid JSON response.')
    def mapping(self,kind):
        if kind not in FIELDS:problem('invalid_index','Unsupported event index.',422)
        if kind in self.caps:return self.caps[kind]
        fields=self.request('POST','/'+quote(self.settings.indexes[kind],safe='')+'/_field_caps',params={'fields':','.join(FIELDS[kind]+[x+'.keyword' for x in REQUIRED[kind]])}).get('fields',{})
        lookup={};missing=[]
        for name,allowed in REQUIRED[kind].items():
            selected=name
            types=set(fields.get(name,{}))
            if not types.intersection(allowed) and set(fields.get(name+'.keyword',{})).intersection(allowed):selected=name+'.keyword';types=set(fields[selected])
            if not types or not types.issubset(allowed):missing.append(name)
            lookup[name]=selected
        if missing:problem('schema_mismatch',f'{kind} mapping has missing/incompatible fields: '+', '.join(missing)+'. Verify the event schema and units.')
        self.caps[kind]=lookup;return lookup
    def query(self,kind,filters):
        fields=self.mapping(kind);terms=[{'terms':{fields.get('season','season'):[2023,2024]}}]
        for k,v in filters.items():
            if k not in {'season','round_number','session_name','driver_code','lap_number'}:problem('invalid_filter','Only bounded event/driver/lap filters are supported.',422)
            terms.append({'term':{fields.get(k,k):v}})
        return {'bool':{'filter':terms}}
    def inspect(self):
        result=[]
        with self.lock:
            for kind in KINDS:
                try:
                    query=self.query(kind,{})
                    value=self.request('POST','/'+quote(self.settings.indexes[kind],safe='')+'/_count',{'query':query})
                    if value.get('_shards',{}).get('failed',0):problem('partial_search','Elastic returned incomplete shard results; partial counts are not accepted.')
                    count=int(value['count']);self.counts[kind]=count
                    result.append({'kind':kind,'ok':True,'count':count})
                except ConnectionProblem as e:result.append({'kind':kind,'ok':False,'error':e.public()})
        return {'ok':all(r['ok'] for r in result),'dashboard_ready':all(r['ok'] for r in result if r['kind']!='telemetry'),'indexes':result,'read_only':True}
    def read(self,kind,filters,limit=None,fresh=False):
        if kind not in FIELDS:problem('invalid_index','Unsupported event index.',422)
        if kind=='telemetry' and not {'season','round_number','session_name','driver_code','lap_number'}.issubset(filters):problem('unbounded_telemetry','Telemetry requires a season, round, session, driver and lap.',422)
        default=self.settings.metadata_limit if kind in {'sessions','results'} else self.settings.lap_limit if kind=='laps' else self.settings.weather_limit if kind=='weather' else self.settings.telemetry_limit
        limit=min(default,limit or default);key=canonical([kind,filters,limit])
        with self.lock:
            if not fresh and key in self.cache and time.monotonic()-self.cache[key][0]<self.settings.cache_seconds:return json.loads(self.cache[key][1])
            query=self.query(kind,filters);pit=None;rows=[];after=None;total=None;deadline=time.monotonic()+max(60,self.settings.timeout*3)
            try:
                pit=self.request('POST','/'+quote(self.settings.indexes[kind],safe='')+'/_pit',params={'keep_alive':'1m'}).get('id')
                if not pit:problem('invalid_response','Elastic did not return a point-in-time search context.')
                while True:
                    if time.monotonic()>deadline:problem('timeout','The bounded Elastic read exceeded its time budget. Retry the selected slice.')
                    body={'pit':{'id':pit,'keep_alive':'1m'},'query':query,'size':min(self.settings.page_size,limit+1-len(rows)),'sort':[{'_shard_doc':'asc'}],'track_total_hits':True,'_source':FIELDS[kind]}
                    if after is not None:body['search_after']=after
                    data=self.request('POST','/_search',body);pit=data.get('pit_id',pit)
                    if data.get('timed_out') or data.get('_shards',{}).get('failed',0):problem('partial_search','Elastic returned a partial/timed-out search. No partial dataset was activated.')
                    hits=data.get('hits',{});count=hits.get('total',{})
                    if not isinstance(count,dict) or count.get('relation')!='eq':problem('invalid_response','Exact Elastic result counts are required for bounded reads.')
                    if total is None:total=count['value']
                    if total>limit:problem('slice_limit',f'The {kind} slice exceeds the configured {limit:,}-row cap. Narrow the selection or explicitly raise the server-side cap.',413)
                    page=hits.get('hits',[])
                    if not page:break
                    for h in page:
                        if not isinstance(h.get('_source'),dict):problem('invalid_response','Source documents must be available in the configured Elastic indices.')
                        rows.append(h['_source'])
                    next_after=page[-1].get('sort')
                    if next_after is None or next_after==after:problem('invalid_response','Elastic pagination did not advance safely.')
                    after=next_after
                    if len(rows)>=total:break
                if len(rows)!=total:problem('partial_search','Elastic result count changed or pagination was incomplete. Retry; no partial dataset was activated.')
                if len(self.cache)>=128:self.cache.pop(next(iter(self.cache)))
                self.cache[key]=(time.monotonic(),canonical(rows));self.last_read={'kind':kind,'rows':len(rows),'scope':dict(filters)}
                return rows
            finally:
                if pit:
                    try:self.request('DELETE','/_pit',{'id':pit})
                    except ConnectionProblem:pass # PIT expires after one minute even if cleanup is unavailable.

class HopsFeatures:
    """Dashboard pace batches only. GET/read never creates or inserts a group."""
    def __init__(self,settings,client=None):
        self.settings=settings;self.client=client;self.store=None;self.lock=threading.RLock();self.cache={};self.last_read=None
    def connect(self):
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
