"""Server-only configuration. No provider credential is accepted from the browser."""
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
import os, re

ROOT=Path(__file__).resolve().parents[1]
KINDS=('sessions','results','laps','weather','telemetry')

class ConnectionProblem(Exception):
    def __init__(self,code,message,status=503):
        super().__init__(message);self.code=code;self.message=message;self.status=status
    def public(self):return {'code':self.code,'message':self.message}

def problem(code,message,status=503):raise ConnectionProblem(code,message,status)

def integer(env,name,default,lo,hi):
    try:v=int(env.get(name,str(default)))
    except (ValueError,TypeError):problem('configuration',f'{name} must be an integer.')
    if not lo<=v<=hi:problem('configuration',f'{name} must be between {lo} and {hi}.')
    return v

def mode(value,allowed,name):
    if value not in allowed:problem('configuration',f'{name} must be one of: {", ".join(allowed)}.')
    return value

@dataclass(repr=False,frozen=True)
class Settings:
    allow_feature_writes:bool=False
    data_mode:str='local'
    feature_mode:str='local'
    elastic_url:str=field(default='',repr=False)
    elastic_key:str=field(default='',repr=False)
    elastic_ca:str=field(default='',repr=False)
    hops_host:str=field(default='',repr=False)
    hops_project:str=field(default='',repr=False)
    hops_key:str=field(default='',repr=False)
    hops_ca:str=field(default='',repr=False)
    admin_token:str=field(default='',repr=False)
    indexes:dict=field(default_factory=lambda:{k:'f1-'+k for k in KINDS})
    prefix:str='pitlane_yourteam'
    feature_version:int=1
    timeout:int=20
    page_size:int=500
    metadata_limit:int=5000
    lap_limit:int=5000
    weather_limit:int=2000
    telemetry_limit:int=20000
    cache_seconds:int=300
    def __repr__(self):return f'Settings(data_mode={self.data_mode!r}, feature_mode={self.feature_mode!r}, secrets=<redacted>)'
    @classmethod
    def load(cls,path=ROOT/'.env',environ=None):
        from dotenv import dotenv_values
        values={k:v for k,v in dotenv_values(path,interpolate=False).items() if v is not None} if Path(path).exists() else {}
        values.update(os.environ if environ is None else environ)
        return cls.from_mapping(values)
    @classmethod
    def from_mapping(cls,e):
        cluster=e.get('CLUSTER','').strip().lower()
        if cluster not in {'','local','remote'}:problem('configuration','CLUSTER must be local or remote when set.')
        legacy='REMOTE_ELASTICSEARCH_' if cluster=='remote' else 'ELASTICSEARCH_'
        url=e.get('ELASTIC_SOURCE_URL',e.get(legacy+'URL','')).strip().rstrip('/')
        key=e.get('ELASTIC_SOURCE_API_KEY',e.get(legacy+'API_KEY','')).strip()
        if url:
            try:u=urlsplit(url)
            except ValueError:problem('configuration','ELASTIC_SOURCE_URL is not a valid endpoint URL.')
            if not u.hostname or u.username or u.password or u.query or u.fragment or (u.scheme!='https' and not (u.scheme=='http' and u.hostname in {'localhost','127.0.0.1','::1'})):
                problem('configuration','ELASTIC_SOURCE_URL must be HTTPS (HTTP only for loopback), without embedded credentials, query or fragment.')
        indexes={k:e.get('ELASTIC_INDEX_'+k.upper(),'f1-'+k).strip() for k in KINDS}
        if any(not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,127}',v) or v.startswith('.') for v in indexes.values()):problem('configuration','Use explicit lowercase Elastic index/alias names; wildcards and paths are not allowed.')
        prefix=e.get('PITLANE_FEATURE_PREFIX','pitlane_yourteam').strip()
        if not re.fullmatch(r'pitlane_[a-z][a-z0-9_]{2,30}',prefix):problem('configuration','PITLANE_FEATURE_PREFIX must be an isolated name such as pitlane_yourteam.')
        host=e.get('HOPSWORKS_HOST','').strip()
        if host and (not re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]{1,5})?',host) or '..' in host):problem('configuration','HOPSWORKS_HOST must be a hostname, optionally with port, not a URL/path.')
        if ':' in host and not 1<=int(host.rsplit(':',1)[1])<=65535:problem('configuration','HOPSWORKS_HOST port is out of range.')
        hops_ca=e.get('HOPSWORKS_CA_CERT','').strip()
        if hops_ca and not Path(hops_ca).is_file():problem('configuration','HOPSWORKS_CA_CERT must point to an existing trusted CA certificate.')
        ca=e.get('ELASTIC_CA_CERT','').strip()
        if ca and not Path(ca).is_file():problem('configuration','ELASTIC_CA_CERT must point to an existing trusted CA certificate.')
        return cls(allow_feature_writes=e.get('PITLANE_ALLOW_FEATURE_WRITES','false').lower() in {'true','1','yes'},data_mode=mode(e.get('PITLANE_DATA_MODE','local'),('local','elastic'),'PITLANE_DATA_MODE'),
            feature_mode=mode(e.get('PITLANE_FEATURE_MODE','local'),('local','hopsworks'),'PITLANE_FEATURE_MODE'),
            elastic_url=url,elastic_key=key,elastic_ca=ca,hops_host=host,hops_project=e.get('HOPSWORKS_PROJECT','').strip(),hops_key=e.get('HOPSWORKS_API_KEY','').strip(),hops_ca=hops_ca,admin_token=e.get('PITLANE_ADMIN_TOKEN',''),indexes=indexes,prefix=prefix,
            feature_version=integer(e,'PITLANE_FEATURE_VERSION',1,1,999),timeout=integer(e,'PITLANE_REQUEST_TIMEOUT',20,2,90),page_size=integer(e,'PITLANE_PAGE_SIZE',500,10,1000),
            metadata_limit=integer(e,'PITLANE_METADATA_LIMIT',5000,100,10000),lap_limit=integer(e,'PITLANE_LAP_LIMIT',5000,100,10000),weather_limit=integer(e,'PITLANE_WEATHER_LIMIT',2000,100,10000),
            telemetry_limit=integer(e,'PITLANE_TELEMETRY_LIMIT',20000,100,50000),cache_seconds=integer(e,'PITLANE_CACHE_SECONDS',300,10,3600))
    @property
    def elastic_ready(self):return bool(self.elastic_url and self.elastic_key)
    @property
    def hops_ready(self):return bool(self.hops_host and self.hops_project and self.hops_key)
    @property
    def admin_ready(self):return len(self.admin_token)>=24
    @property
    def group_name(self):return self.prefix+'_race_pace'
    def public(self):
        return {'configured_modes':{'data':self.data_mode,'features':self.feature_mode},'admin_configured':self.admin_ready,'feature_writes_enabled':self.allow_feature_writes,
            'elastic':{'configured':self.elastic_ready,'url_present':bool(self.elastic_url),'key_present':bool(self.elastic_key),'indexes':self.indexes},
            'hopsworks':{'configured':self.hops_ready,'host_present':bool(self.hops_host),'project_present':bool(self.hops_project),'key_present':bool(self.hops_key),'feature_group':self.group_name,'version':self.feature_version},
            'limits':{'metadata':self.metadata_limit,'laps_per_session':self.lap_limit,'weather_per_session':self.weather_limit,'telemetry_per_driver_lap':self.telemetry_limit,'cache_seconds':self.cache_seconds}}
