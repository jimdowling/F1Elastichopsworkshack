"""Explicit Hopsworks publishing, NOT the web application's request path.

Two jobs, both CLI-driven and dry-run by default:
- load the public 2023-2024 archive into the event source feature groups
  (f1_sessions, f1_results, f1_laps, f1_weather, f1_telemetry) that the
  dashboard reads in Hopsworks data mode;
- publish the original Dutch GP lab feature tables.
No delete operations. Every write is followed by an ID read-back.
"""
import re
import pandas as pd
from .remote import FIELDS,HopsConnection,digest

GROUPS=('ghost_features','pace_features','dna_features','strategy_features')
KEYS={'sessions':['season','round_number','session_name'],'results':['season','round_number','session_name','driver_code'],
    'laps':['season','round_number','session_name','driver_code','lap_number'],'weather':['season','round_number','session_name','session_time_s'],
    'telemetry':['season','round_number','session_name','driver_code','lap_number','session_time_s']}
INTS={'season','round_number','driver_number','position','grid_position','fastest_lap_ms','lap_number','lap_duration_ms','duration_sector_1','duration_sector_2','duration_sector_3','tyre_life','speed','rpm','throttle','n_gear','drs'}
BOOLS={'is_pit_out_lap','is_pit_in_lap','rainfall','brake','is_interpolated'}
STRINGS={'event_name','session_name','country','location','session_date','driver_code','full_name','team_name','status','compound','track_status'}

def validate_prefix(prefix):
    if not re.fullmatch(r'pitlane_[a-z][a-z0-9_]{2,30}',prefix):
        raise ValueError('Use an isolated prefix such as pitlane_yourteam; never a source feature-group name.')
    return prefix

def typed(kind,rows):
    """Explicit nullable dtypes so Hopsworks infers stable bigint/double/boolean/string features."""
    columns=FIELDS[kind]+sorted({k for r in rows for k in r}-set(FIELDS[kind]))
    frame=pd.DataFrame(rows,columns=columns)
    for c in frame.columns:
        if c in INTS:frame[c]=frame[c].astype('Int64')
        elif c in BOOLS:frame[c]=frame[c].astype('boolean')
        elif c in STRINGS:frame[c]=frame[c].astype('string')
        else:frame[c]=frame[c].astype('Float64')
    ids=[digest([kind,*[None if pd.isna(v) else v for v in key]]) for key in frame[KEYS[kind]].astype(object).itertuples(index=False)]
    frame.insert(0,'id',pd.array(ids,dtype='string'))
    if not frame.id.is_unique:raise ValueError(f'Duplicate {kind} keys in the public archive; refusing an ambiguous source load.')
    return frame

def source_frames(db,kinds=FIELDS,seasons=(2023,2024)):
    """Event-schema frames for every loaded public event (Race + Qualifying)."""
    from .dashboard_api import local_source_rows
    rows={k:[] for k in kinds}
    for e in db.events:
        if e['season'] not in seasons:continue
        for session in ('Race','Qualifying'):
            for kind in kinds:rows[kind].extend(local_source_rows(db,kind,e['season'],e['round_number'],session))
    return {k:typed(k,v) for k,v in rows.items() if v}

class HopsworksPublisher:
    def __init__(self,settings,client=None):
        if not settings.hops_ready:raise ValueError('Hopsworks host, project name, and API key are required.')
        self.settings=settings;self.store=HopsConnection(settings,client).connect()
    def write(self,name,version,frame,description):
        fg=self.store.get_or_create_feature_group(name=name,version=version,primary_key=['id'],online_enabled=False,description=description)
        fg.insert(frame,write_options={'wait_for_job':True})
        read=fg.select(['id']).read()
        if not set(frame.id.astype(str)).issubset(set(read.id.astype(str))):raise RuntimeError(f'Feature group read-back incomplete: {name}')
        return {'feature_group':name,'version':version,'published_rows':len(frame),'read_rows':len(read),'id_read_back':True}
    def load_sources(self,frames):
        return [self.write(self.settings.sources[kind],self.settings.source_version,frame,
            f'F1 {kind} in the Pitlane event schema. Public OpenF1/Jolpica observations, 2023-2024; read-only dashboard source.') for kind,frame in frames.items()]
    def publish(self,prefix,frames):
        validate_prefix(prefix)
        return [self.write(prefix+'_'+group,1,frame,'Exploratory 2024 Dutch GP features. Public OpenF1 observations; batch demo, not live production features.') for group,frame in frames.items()]
