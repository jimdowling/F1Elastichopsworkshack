"""Server-only configuration. No provider credential is accepted from the browser."""
from dataclasses import dataclass, field
from pathlib import Path
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
    hops_host:str=field(default='',repr=False)
    hops_project:str=field(default='',repr=False)
    hops_key:str=field(default='',repr=False)
    hops_ca:str=field(default='',repr=False)
    admin_token:str=field(default='',repr=False)
    sources:dict=field(default_factory=lambda:{k:'f1_'+k for k in KINDS})
    source_version:int=1
    prefix:str='pitlane_yourteam'
    feature_version:int=1
    timeout:int=20
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
        sources={k:e.get('HOPSWORKS_FG_'+k.upper(),'f1_'+k).strip() for k in KINDS}
        if any(not re.fullmatch(r'[a-z][a-z0-9_]{0,62}',v) for v in sources.values()):problem('configuration','Use explicit lowercase Hopsworks feature-group names (letters, digits, underscores); wildcards and paths are not allowed.')
        prefix=e.get('PITLANE_FEATURE_PREFIX','pitlane_yourteam').strip()
        if not re.fullmatch(r'pitlane_[a-z][a-z0-9_]{2,30}',prefix):problem('configuration','PITLANE_FEATURE_PREFIX must be an isolated name such as pitlane_yourteam.')
        if prefix+'_race_pace' in sources.values():problem('configuration','The pace feature group must not reuse a source feature-group name.')
        host=e.get('HOPSWORKS_HOST','').strip()
        if host and (not re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]{1,5})?',host) or '..' in host):problem('configuration','HOPSWORKS_HOST must be a hostname, optionally with port, not a URL/path.')
        if ':' in host and not 1<=int(host.rsplit(':',1)[1])<=65535:problem('configuration','HOPSWORKS_HOST port is out of range.')
        hops_ca=e.get('HOPSWORKS_CA_CERT','').strip()
        if hops_ca and not Path(hops_ca).is_file():problem('configuration','HOPSWORKS_CA_CERT must point to an existing trusted CA certificate.')
        return cls(allow_feature_writes=e.get('PITLANE_ALLOW_FEATURE_WRITES','false').lower() in {'true','1','yes'},data_mode=mode(e.get('PITLANE_DATA_MODE','local'),('local','hopsworks'),'PITLANE_DATA_MODE'),
            feature_mode=mode(e.get('PITLANE_FEATURE_MODE','local'),('local','hopsworks'),'PITLANE_FEATURE_MODE'),
            hops_host=host,hops_project=e.get('HOPSWORKS_PROJECT','').strip(),hops_key=e.get('HOPSWORKS_API_KEY','').strip(),hops_ca=hops_ca,admin_token=e.get('PITLANE_ADMIN_TOKEN',''),sources=sources,
            source_version=integer(e,'HOPSWORKS_FG_VERSION',1,1,999),prefix=prefix,
            feature_version=integer(e,'PITLANE_FEATURE_VERSION',1,1,999),timeout=integer(e,'PITLANE_REQUEST_TIMEOUT',20,2,90),
            metadata_limit=integer(e,'PITLANE_METADATA_LIMIT',5000,100,10000),lap_limit=integer(e,'PITLANE_LAP_LIMIT',5000,100,10000),weather_limit=integer(e,'PITLANE_WEATHER_LIMIT',2000,100,10000),
            telemetry_limit=integer(e,'PITLANE_TELEMETRY_LIMIT',20000,100,50000),cache_seconds=integer(e,'PITLANE_CACHE_SECONDS',300,10,3600))
    @property
    def hops_ready(self):return bool(self.hops_host and self.hops_project and self.hops_key)
    @property
    def admin_ready(self):return len(self.admin_token)>=24
    @property
    def group_name(self):return self.prefix+'_race_pace'
    def public(self):
        return {'configured_modes':{'data':self.data_mode,'features':self.feature_mode},'admin_configured':self.admin_ready,'feature_writes_enabled':self.allow_feature_writes,
            'hopsworks':{'configured':self.hops_ready,'host_present':bool(self.hops_host),'project_present':bool(self.hops_project),'key_present':bool(self.hops_key),
                'source_groups':self.sources,'source_version':self.source_version,'feature_group':self.group_name,'version':self.feature_version},
            'limits':{'metadata':self.metadata_limit,'laps_per_session':self.lap_limit,'weather_per_session':self.weather_limit,'telemetry_per_driver_lap':self.telemetry_limit,'cache_seconds':self.cache_seconds}}
