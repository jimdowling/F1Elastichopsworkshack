"""OFFLINE TEST FIXTURES ONLY. No accounts, sockets or provider writes.

A minimal stand-in for the Hopsworks SDK: login -> feature store -> feature
groups with select/filter/read and insert.

A small event-shaped subset derived from the bundled public archive; deliberate
fixture-only changes prove the runtime is not silently using local values.
"""
from pathlib import Path
from types import SimpleNamespace
import copy,json
import pandas as pd
from src.remote import FIELDS,REQUIRED
from src.settings import KINDS
ROOT=Path(__file__).resolve().parents[1]

def source_rows():
    """Event-schema rows for 2024 R15 with deliberate fixture-only changes."""
    rows={k:[] for k in FIELDS}
    cat=json.loads((ROOT/'data/dashboard/catalog.json').read_text());raw=json.loads((ROOT/'data/dashboard/race_2024_15.json').read_text());qual=json.loads((ROOT/'data/dashboard/weather_2024_15_qualifying.json').read_text())
    for r in cat['sessions']:
        if r['season']==2024 and r['round_number']==15:
            rows['sessions'].append({**{k:r.get(k) for k in FIELDS['sessions']},'country':'Netherlands','location':'Zandvoort'})
    for r in cat['results']:
        if r['season']==2024 and r['round_number']==15 and r['session_name'] in {'Race','Qualifying'}:
            row={k:r.get(k) for k in FIELDS['results']}
            if row['driver_code']=='NOR' and row['session_name']=='Race':row['points']=27.0 # TEST-ONLY change.
            rows['results'].append(row)
    for l in raw['laps']:
        row={k:l.get(k) for k in FIELDS['laps']};row['track_status']='1'
        if row['driver_code']=='NOR' and row['lap_duration_ms'] is not None:row['lap_duration_ms']+=1000 # TEST-ONLY change.
        rows['laps'].append(row)
    rows['weather']=[{k:r.get(k) for k in FIELDS['weather']} for r in raw['weather']+qual]
    for r in rows['weather']:r['rainfall']=None if r['rainfall'] is None else bool(r['rainfall'])
    rows['telemetry']=[{'season':2024,'round_number':15,'event_name':'Dutch Grand Prix','session_name':'Race','driver_code':'NOR','team_name':'McLaren','lap_number':72,'session_time_s':5000+i*.1,'speed':220+i*4,'rpm':11000+i*10,'throttle':100,'brake':False,'drs':12,'n_gear':7,'x':i*3.0,'y':i*2.0,'z':0.0} for i in range(12)]
    return rows

class Predicate:
    def __init__(self,test,fields):self.test=test;self.fields=fields
    def __and__(self,other):return Predicate(lambda r:self.test(r) and other.test(r),self.fields+other.fields)
class Field:
    def __init__(self,name):self.name=name
    def __eq__(self,value):return Predicate(lambda r:r.get(self.name)==value,[(self.name,'==',value)])
    def isin(self,values):return Predicate(lambda r:r.get(self.name) in values,[(self.name,'in',tuple(values))])
class FeatureDef:
    def __init__(self,name,type):self.name=name;self.type=type
class Query:
    def __init__(self,group,columns=None):self.group=group;self.columns=columns;self.predicate=None
    def filter(self,predicate):self.predicate=predicate;return self
    def read(self):
        self.group.reads+=1;g=self.group
        if g.fail:raise RuntimeError('PROVIDER_SECRET from failed SDK read')
        if g.source:
            assert self.predicate is not None,'A bounded server-side filter is mandatory'
            g.queries.append(self.predicate.fields)
            rows=[{k:r.get(k) for k in self.columns} for r in copy.deepcopy(g.rows) if self.predicate.test(r)]
            return pd.DataFrame(rows,columns=self.columns)
        frame=g.frame.copy()
        if self.predicate is not None:
            assert self.predicate.fields[0][0]=='batch_id','A bounded server-side batch filter is mandatory'
            if len(frame):frame=frame[frame['batch_id']==self.predicate.fields[0][2]].copy()
        if g.corrupt and len(frame):frame.loc[frame.index[0],'median_s']+=2
        return frame[self.columns] if self.columns else frame
class Group:
    def __init__(self,rows=None,kind=None):
        self.frame=pd.DataFrame();self.inserts=0;self.reads=0;self.corrupt=False;self.fail=False;self.queries=[]
        self.source=rows is not None;self.rows=rows;self.kind=kind;self.missing=set();self.types={}
    @property
    def features(self):
        def kind_of(name):
            sample=next((r[name] for r in self.rows if r.get(name) is not None),None)
            if isinstance(sample,bool):return 'boolean'
            if isinstance(sample,int):return 'bigint'
            if isinstance(sample,float):return 'double'
            if isinstance(sample,str):return 'string'
            allowed=REQUIRED[self.kind].get(name,set())
            return 'boolean' if 'boolean' in allowed else 'double' if 'double' in allowed else 'string'
        return [FeatureDef(n,self.types.get(n,kind_of(n))) for n in FIELDS[self.kind] if n not in self.missing]
    def __getitem__(self,key):return Field(key)
    def select_all(self):return Query(self)
    def select(self,columns):return Query(self,list(columns))
    def insert(self,frame,**kwargs):
        assert kwargs['write_options']['wait_for_job'] is True
        self.inserts+=1;self.frame=pd.concat([self.frame,frame],ignore_index=True).drop_duplicates('id',keep='last')
class FixtureHops:
    def __init__(self):
        self.logins=0;self.created=0;self.fail=False;self.rows=source_rows()
        self.groups={('f1_'+k,1):Group(self.rows[k],k) for k in KINDS}
    def source(self,kind):return self.groups[('f1_'+kind,1)]
    def login(self,**kwargs):
        self.logins+=1;self.last_login=kwargs
        if self.fail:raise RuntimeError('PROVIDER_SECRET from failed SDK')
        return self
    def get_feature_store(self):return self
    def get_feature_group(self,name,version):return self.groups[(name,version)]
    def get_or_create_feature_group(self,name,version,**kwargs):
        assert kwargs['primary_key']==['id'] and kwargs['online_enabled'] is False
        if (name,version) not in self.groups:self.groups[(name,version)]=Group();self.created+=1
        return self.groups[(name,version)]
