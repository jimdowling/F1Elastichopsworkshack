"""OFFLINE TEST FIXTURES ONLY. No accounts, sockets or provider writes.

A small event-shaped subset derived from the bundled public archive; deliberate
fixture-only changes prove the runtime is not silently using local values.
"""
from pathlib import Path
from types import SimpleNamespace
import copy,json
import pandas as pd
from src.remote import FIELDS,REQUIRED
ROOT=Path(__file__).resolve().parents[1]

class Reply:
    def __init__(self,data,status=200):self.data=data;self.status_code=status
    def json(self):return self.data

class FixtureHTTP:
    def __init__(self):
        self.headers={};self.calls=[];self.pits={};self.next_id=0;self.fail=None;self.partial=False;self.repeat=False;self.count_override=None;self.bad_mapping=None;self.text_fields=False
        cat=json.loads((ROOT/'data/dashboard/catalog.json').read_text());raw=json.loads((ROOT/'data/dashboard/race_2024_15.json').read_text());qual=json.loads((ROOT/'data/dashboard/weather_2024_15_qualifying.json').read_text())
        self.rows={k:[] for k in FIELDS}
        for r in cat['sessions']:
            if r['season']==2024 and r['round_number']==15:
                self.rows['sessions'].append({**{k:r.get(k) for k in FIELDS['sessions']},'country':'Netherlands','location':'Zandvoort'})
        for r in cat['results']:
            if r['season']==2024 and r['round_number']==15 and r['session_name'] in {'Race','Qualifying'}:
                row={k:r.get(k) for k in FIELDS['results']}
                if row['driver_code']=='NOR' and row['session_name']=='Race':row['points']=27.0 # TEST-ONLY change.
                self.rows['results'].append(row)
        for l in raw['laps']:
            row={k:l.get(k) for k in FIELDS['laps']};row['track_status']='1'
            if row['driver_code']=='NOR' and row['lap_duration_ms'] is not None:row['lap_duration_ms']+=1000 # TEST-ONLY change.
            self.rows['laps'].append(row)
        self.rows['weather']=[{k:r.get(k) for k in FIELDS['weather']} for r in raw['weather']+qual]
        for r in self.rows['weather']:r['rainfall']=None if r['rainfall'] is None else bool(r['rainfall'])
        self.rows['telemetry']=[{'season':2024,'round_number':15,'event_name':'Dutch Grand Prix','session_name':'Race','driver_code':'NOR','team_name':'McLaren','lap_number':72,'session_time_s':5000+i*.1,'speed':220+i*4,'rpm':11000+i*10,'throttle':100,'brake':False,'drs':12,'n_gear':7,'x':i*3.0,'y':i*2.0,'z':0.0} for i in range(12)]
    def selected(self,kind,query):
        rows=copy.deepcopy(self.rows[kind])
        for item in query.get('bool',{}).get('filter',[]):
            if 'term' in item:
                k,v=next(iter(item['term'].items()));k=k.removesuffix('.keyword');rows=[r for r in rows if r.get(k)==v]
            elif 'terms' in item:
                k,v=next(iter(item['terms'].items()));k=k.removesuffix('.keyword');rows=[r for r in rows if r.get(k) in v]
        return rows
    def request(self,method,url,json=None,params=None,**kwargs):
        self.calls.append({'method':method,'url':url,'body':copy.deepcopy(json),'params':params,**kwargs})
        if self.fail:
            if isinstance(self.fail,Exception):raise self.fail
            return Reply({'error':'fixture secret could be echoed here: PROVIDER_SECRET'},self.fail)
        path=url.split('fixture.invalid')[-1]
        if path.endswith('/_field_caps'):
            kind=path.split('/')[1].removeprefix('f1-');fields={}
            for k,types in REQUIRED[kind].items():
                typ='keyword' if 'keyword' in types else 'double' if 'double' in types else 'boolean' if 'boolean' in types else 'date'
                if self.text_fields and typ=='keyword':fields[k]={'text':{}};fields[k+'.keyword']={'keyword':{}}
                else:fields[k]={typ:{}}
            if self.bad_mapping:fields.pop(self.bad_mapping,None)
            return Reply({'fields':fields})
        if path.endswith('/_count'):
            kind=path.split('/')[1].removeprefix('f1-');return Reply({'count':len(self.selected(kind,json['query'])),'_shards':{'failed':0}})
        if path.endswith('/_pit') and path!='/_pit':
            self.next_id+=1;pit=str(self.next_id);self.pits[pit]=path.split('/')[1].removeprefix('f1-');return Reply({'id':pit})
        if path=='/_pit':self.pits.pop(json['id'],None);return Reply({'succeeded':True})
        if path=='/_search':
            kind=self.pits[json['pit']['id']];rows=self.selected(kind,json['query']);offset=(json.get('search_after',[-1])[0]+1);page=rows[offset:offset+json['size']]
            return Reply({'_shards':{'failed':1 if self.partial else 0},'hits':{'total':{'value':self.count_override if self.count_override is not None else len(rows),'relation':'eq'},'hits':[{'_source':r,'sort':[-1 if self.repeat else offset+i]} for i,r in enumerate(page)]}})
        raise AssertionError('UNEXPECTED HTTP PATH '+path)

class Field:
    def __init__(self,name):self.name=name
    def __eq__(self,value):return (self.name,value)
class Query:
    def __init__(self,group):self.group=group;self.predicate=None
    def filter(self,predicate):self.predicate=predicate;return self
    def read(self):
        assert self.predicate and self.predicate[0]=='batch_id','A bounded server-side batch filter is mandatory'
        self.group.reads+=1;frame=self.group.frame.copy()
        if len(frame):frame=frame[frame[self.predicate[0]]==self.predicate[1]].copy()
        if self.group.corrupt and len(frame):frame.loc[frame.index[0],'median_s']+=2
        return frame
class Group:
    def __init__(self):self.frame=pd.DataFrame();self.inserts=0;self.reads=0;self.corrupt=False
    def __getitem__(self,key):return Field(key)
    def select_all(self):return Query(self)
    def insert(self,frame,**kwargs):
        assert kwargs['write_options']['wait_for_job'] is True
        self.inserts+=1;self.frame=pd.concat([self.frame,frame],ignore_index=True).drop_duplicates('id',keep='last')
class FixtureHops:
    def __init__(self):self.groups={};self.logins=0;self.created=0;self.fail=False
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
