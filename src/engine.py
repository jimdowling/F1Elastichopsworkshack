"""Real-data, deterministic local pipelines for four exploratory F1 applications.
SQLite is explicitly the local feature-store substitute, not Hopsworks. All models consume a verified read-back from the feature tables.
"""
from pathlib import Path
from datetime import datetime, timezone
import json, time, hashlib, sqlite3
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, accuracy_score, confusion_matrix

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'
DRIVERS=['NOR','VER','LEC','PIA']
DNA_FEATURES=['mean_speed','p95_speed','speed_std','full_throttle','brake_fraction','mean_throttle','mean_rpm','mean_gear','drs_fraction','accel_std','low_speed','high_gear_fraction']
RADAR_FEATURES=['full_throttle','brake_fraction','p95_speed','mean_gear','mean_rpm','drs_fraction']
FEATURE_LABELS={'mean_speed':'Average speed','p95_speed':'Top-end speed','speed_std':'Speed variation','full_throttle':'Full throttle','brake_fraction':'Braking','mean_throttle':'Throttle input','mean_rpm':'Engine RPM','mean_gear':'Gear usage','drs_fraction':'DRS usage','accel_std':'Acceleration variation','low_speed':'Corner speed','high_gear_fraction':'High gears'}

def safe(obj):
    if isinstance(obj,dict):return {str(k):safe(v) for k,v in obj.items()}
    if isinstance(obj,(list,tuple,np.ndarray)):return [safe(x) for x in obj]
    if isinstance(obj,np.integer):return int(obj)
    if isinstance(obj,(np.floating,float)):return round(float(obj),6) if np.isfinite(obj) else None
    if isinstance(obj,np.bool_):return bool(obj)
    if obj is pd.NA:return None
    return obj

def load(name):return json.loads((DATA/name).read_text())
def now():return datetime.now(timezone.utc).isoformat()

class LocalFeatureStore:
    """A real persisted round trip, deliberately labeled as a local stand-in."""
    def __init__(self,path=DATA/'lab.sqlite'):
        self.path=Path(path)
    def put_read(self,name,frame):
        if not name.replace('_','').isalnum():raise ValueError('Invalid table name')
        if 'id' in frame and not frame.id.is_unique:raise ValueError('Feature primary keys must be unique')
        with sqlite3.connect(self.path) as con:
            frame.to_sql(name,con,if_exists='replace',index=False)
            if 'id' in frame:con.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS idx_{name}_id ON {name}(id)')
            read=pd.read_sql_query(f'SELECT * FROM {name} ORDER BY id' if 'id' in frame else f'SELECT * FROM {name}',con)
        if len(frame)!=len(read):raise RuntimeError('Feature-store round-trip row count mismatch')
        return read
    def read(self,name):
        if name not in {'pace_features','dna_features','strategy_features','ghost_features','pace_results','race_laps'}:raise ValueError('Unknown table')
        with sqlite3.connect(self.path) as con:return pd.read_sql_query(f'SELECT * FROM {name}',con)


def clean_lap(r):
    return (r['lap_number']>1 and pd.notna(r['lap_duration_s']) and r['lap_duration_s']>0
        and not r['is_pit_in_lap'] and not r['is_pit_out_lap'] and str(r['track_status'])=='1'
        and bool(r['is_accurate']) and r['compound'] in ['SOFT','MEDIUM','HARD'] and pd.notna(r['tyre_life']))


def make_pace_features(laps):
    """Reset history on pit/flag/gap/compound/stint boundaries; never use target."""
    features=[]
    for driver,g in laps.groupby('driver_code'):
        hist=[]; last=None
        for _,r in g.sort_values('lap_number').iterrows():
            if not clean_lap(r):hist=[];last=None;continue
            if last is not None and (r['lap_number']!=last['lap_number']+1 or r['stint']!=last['stint'] or r['compound']!=last['compound']):hist=[]
            if len(hist)>=3:
                h=hist[-3:]; vals=[x['lap_duration_s'] for x in h]
                features.append({k:r[k] for k in ['id','driver_code','lap_number','compound','tyre_life','lap_duration_s','stint']} |
                    {'rolling_median':float(np.median(vals)),'rolling_mean':float(np.mean(vals)),'rolling_std':float(np.std(vals)),
                     'previous_lap_s':float(vals[-1]),'history_max_lap':int(h[-1]['lap_number']),
                     'split':'train' if r['lap_number']<=43 else 'validation' if r['lap_number']<=57 else 'test'})
            hist.append(r);last=r
    return pd.DataFrame(features)

class LabEngine:
    def __init__(self,db_path=None):
        self.store=LocalFeatureStore(db_path or DATA/'lab.sqlite')
        self.manifest=load('manifest.json');self.results=load('results.json');self.raw_ghosts=load('ghosts.json');self.ghosts=self.raw_ghosts
        self.dna_raw=load('dna_laps.json');self.raw_laps=load('laps.json');self.laps=pd.DataFrame(self.raw_laps)
        classified=load('jolpica_results.json')['MRData']['RaceTable']['Races'][0]['Results']
        self.classified_times={r['Driver']['code']:int(r['Time']['millis'])/1000 for r in classified if r.get('Time',{}).get('millis')}
        self.steps=[];self.built_at=now();self.rebuild()

    def step(self,name,count,start,detail):
        self.steps.append(dict(name=name,rows=int(count),seconds=round(time.perf_counter()-start,3),status='complete',detail=detail))

    def rebuild(self):
        start=time.perf_counter();self.steps=[]
        for name,digest in self.manifest['sha256'].items():
            if hashlib.sha256((DATA/name).read_bytes()).hexdigest()!=digest:raise RuntimeError(f'Data checksum mismatch: {name}')
        if not self.laps.id.is_unique:raise RuntimeError('Duplicate raw laps')
        self.store.put_read('race_laps',self.laps)
        self.step('Validate & index observations',len(self.laps),start,'SHA-256 verified; real OpenF1 records indexed in local SQLite')
        t=time.perf_counter();points=[]
        for code,g in self.raw_ghosts.items():
            for i in range(len(g['trace']['time'])):
                points.append({'id':f'2024-15-R-{code}-{g["lap_number"]}-{i:03d}','driver_code':code,'lap_number':g['lap_number'],'sample':i,
                    'lap_time':g['lap_time'],'compound':g['compound'],'tyre_life':g['tyre_life'],**{k:v[i] for k,v in g['trace'].items()}})
        self.ghost_features=self.store.put_read('ghost_features',pd.DataFrame(points));self.ghosts={}
        for code,g in self.raw_ghosts.items():
            rows=self.ghost_features[self.ghost_features.driver_code==code].sort_values('sample')
            self.ghosts[code]={**g,'trace':{k:rows[k].tolist() for k in g['trace']}}
        self.step('Align & read back replay features',len(self.ghost_features),t,'Four real lap traces; all replay channels consumed from the persisted feature table')
        t=time.perf_counter();features=make_pace_features(self.laps)
        self.pace=self.store.put_read('pace_features',features)
        assert (self.pace.history_max_lap<self.pace.lap_number).all()
        self.step('Engineer & read back pace features',len(self.pace),t,'Past-only rolling windows; persisted feature-table round trip')
        t=time.perf_counter();self.fit_pace()
        self.step('Train & evaluate pace model',self.pace_report['test_rows'],t,'Chronological train ≤43 / validation 44–57 / test ≥58')
        t=time.perf_counter();self.fit_strategy()
        self.step('Calibrate strategy simulator',self.strategy_report['rows'],t,'Ridge-calibrated pace assumptions; not a causal model')
        t=time.perf_counter();self.fit_dna()
        self.step('Train & evaluate driver–car classifier',self.dna_report['test_rows'],t,'Telemetry-only features; whole-lap chronological holdout')
        t=time.perf_counter();self.store.put_read('pace_results',self.pace)
        self.step('Publish local application results',len(self.pace),t,'Queryable results; all four experiences ready')
        self.built_at=now();self.duration=round(time.perf_counter()-start,3)
        return self.pipeline_status()

    def fit_pace(self):
        p=self.pace
        numeric=['lap_number','tyre_life','rolling_median','rolling_mean','rolling_std','previous_lap_s']
        cats=['driver_code','compound'];self.pace_inputs=numeric+cats
        pre=ColumnTransformer([('numeric','passthrough',numeric),('category',OneHotEncoder(handle_unknown='ignore',sparse_output=False),cats)])
        self.pace_model=Pipeline([('features',pre),('model',RandomForestRegressor(n_estimators=180,max_depth=9,min_samples_leaf=3,max_features=.85,random_state=42,n_jobs=1))])
        train=p.split=='train';valid=p.split=='validation';test=p.split=='test'
        self.pace_model.fit(p.loc[train,self.pace_inputs],p.loc[train,'lap_duration_s'])
        p['baseline_prediction']=p.rolling_median
        p['model_prediction']=self.pace_model.predict(p[self.pace_inputs])
        p['baseline_residual']=p.lap_duration_s-p.baseline_prediction;p['model_residual']=p.lap_duration_s-p.model_prediction
        base=mean_absolute_error(p.loc[test,'lap_duration_s'],p.loc[test,'baseline_prediction'])
        model=mean_absolute_error(p.loc[test,'lap_duration_s'],p.loc[test,'model_prediction'])
        importance=self.pace_model.named_steps['model'].feature_importances_; names=pre.get_feature_names_out();agg={}
        for name,value in zip(names,importance):
            key='Driver' if 'driver_code_' in name else 'Compound' if 'compound_' in name else name.replace('numeric__','').replace('_',' ').title()
            agg[key]=agg.get(key,0)+float(value)
        self.pace_report=safe(dict(train_rows=int(train.sum()),validation_rows=int(valid.sum()),test_rows=int(test.sum()),eligible_rows=len(p),raw_rows=len(self.laps),
          baseline_mae=base,model_mae=model,improvement_pct=(base-model)/base*100,
          validation_mae=mean_absolute_error(p.loc[valid,'lap_duration_s'],p.loc[valid,'model_prediction']),
          inputs=self.pace_inputs,importance=[{'name':k,'value':v} for k,v in sorted(agg.items(),key=lambda x:-x[1])],
          note='One-race, retrospective clean-lap evaluation. Not cross-race validation. Models may lose to the baseline.'))

    def fit_strategy(self):
        clean=self.laps[self.laps.apply(clean_lap,axis=1)].copy()
        cols=['id','driver_code','lap_number','tyre_life','compound','lap_duration_s']
        frame=self.store.put_read('strategy_features',clean[cols])
        pre=ColumnTransformer([('numeric','passthrough',['lap_number','tyre_life']),('category',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['driver_code','compound'])])
        model=Pipeline([('pre',pre),('ridge',Ridge(alpha=5.))]);model.fit(frame,frame.lap_duration_s)
        coefs=dict(zip(pre.get_feature_names_out(),model.named_steps['ridge'].coef_))
        raw_age=float(coefs['numeric__tyre_life']);raw_fuel=float(coefs['numeric__lap_number'])
        self.age_coefficient=float(np.clip(raw_age,.002,.16));self.fuel_coefficient=float(np.clip(raw_fuel,-.12,.03))
        self.compound_offsets={c:float(coefs.get('category__compound_'+c,0)) for c in ['HARD','MEDIUM','SOFT']}
        self.driver_base={d:float((g.lap_duration_s-self.age_coefficient*g.tyre_life-self.fuel_coefficient*g.lap_number-g.compound.map(self.compound_offsets)).median()) for d,g in frame.groupby('driver_code')}
        excess=[]
        for _,r in self.laps[self.laps.is_pit_in_lap].iterrows():
            pair=self.laps[(self.laps.driver_code==r.driver_code)&self.laps.lap_number.isin([r.lap_number,r.lap_number+1])]
            if len(pair)!=2 or pair.lap_duration_s.isna().any():continue
            e=sum(x.lap_duration_s-self.clean_pace(x.driver_code,x.lap_number,x.tyre_life,x.compound) for _,x in pair.iterrows())
            if 10<e<40:excess.append(e)
        self.pit_loss=float(np.median(excess)) if excess else 22.
        self.strategy_report=safe(dict(rows=len(frame),age_coefficient=self.age_coefficient,fuel_coefficient=self.fuel_coefficient,
          raw_age_coefficient=raw_age,raw_fuel_coefficient=raw_fuel,compound_offsets=self.compound_offsets,pit_loss=self.pit_loss,
          pit_loss_pairs=len(excess),pit_loss_source='Median pit-in/out excess vs fitted clean pace' if excess else '22-second assumed fallback',
          compound_counts=frame.compound.value_counts().to_dict(),compound_max_age=frame.groupby('compound').tyre_life.max().to_dict(),
          note='In-sample calibration for an illustrative simulator, not validated strategy prediction. Fuel/tyre/traffic effects are confounded.'))

    def clean_pace(self,driver,lap,age,compound,scale=1.):
        return self.driver_base[driver]+self.fuel_coefficient*lap+self.age_coefficient*scale*age+self.compound_offsets.get(compound,0)

    def strategy(self,driver='NOR',pit_lap=None,compound='HARD',degradation=1.,pit_loss=None):
        g=self.laps[self.laps.driver_code==driver].sort_values('lap_number')
        stops=g[g.is_pit_in_lap].lap_number.astype(int).tolist()
        original=int(stops[0]);pit_lap=original if pit_lap is None else int(pit_lap);pit_loss=self.pit_loss if pit_loss is None else float(pit_loss)
        start_comp=str(g.iloc[0].compound);start_age=float(g.iloc[0].tyre_life)
        after=g[g.lap_number==original+1].iloc[0];new_age=float(after.tyre_life)
        original_comp=str(after.compound)
        def predicted(stop,new_comp,scale,loss,use_actual=False):
            arr=[]
            for _,r in g.iterrows():
                lap=int(r.lap_number)
                c=str(r.compound) if use_actual else start_comp if lap<=stop else new_comp
                age=float(r.tyre_life) if use_actual else start_age+lap-1 if lap<=stop else new_age+lap-stop-1
                v=self.clean_pace(driver,lap,age,c,scale)
                if lap in [stop,stop+1]:v+=loss/2
                arr.append(v)
            return np.array(arr)
        baseline=predicted(original,original_comp,1.,self.pit_loss,True)
        alternative=predicted(pit_lap,compound,degradation,pit_loss)
        delta=alternative-baseline;actual=g.lap_duration_s.to_numpy(float)
        if not np.isfinite(actual).all():raise ValueError('Race has missing lap durations for this driver')
        window=[]
        for stop in range(12,57):
            change=float((predicted(stop,compound,degradation,pit_loss)-baseline).sum());window.append({'lap':stop,'delta':change})
        best=min(window,key=lambda x:x['delta'])
        warnings=['Illustrative counterfactual, not a validated forecast. No rival reactions, traffic simulation, or safety cars.']
        if compound==start_comp:warnings.append('Same-compound plan: not a legal dry-race one-stop strategy.')
        max_age=new_age+int(g.lap_number.max())-pit_lap-1
        if max_age>self.strategy_report['compound_max_age'].get(compound,0):warnings.append('Chosen stint extrapolates beyond observed tyre ages for this compound.')
        lap_sum_total=float(actual.sum())
        actual_total=self.classified_times.get(driver,lap_sum_total);scenario_total=actual_total+float(delta.sum())
        rival='VER' if driver!='VER' else 'NOR';rg=self.laps[self.laps.driver_code==rival]
        rival_total=self.classified_times.get(rival,float(rg.lap_duration_s.sum()))
        return safe(dict(driver=driver,original_stop=original,original_compound=original_comp,start_compound=start_comp,pit_lap=pit_lap,compound=compound,
          degradation=degradation,pit_loss=pit_loss,default_pit_loss=self.pit_loss,delta_seconds=float(delta.sum()),actual_total=actual_total,scenario_total=scenario_total,
          lap_sum_total=lap_sum_total,actual_total_source='Jolpica classified elapsed race time' if driver in self.classified_times else 'Sum of OpenF1 lap durations',
          rival=rival,actual_gap=actual_total-rival_total,scenario_gap=scenario_total-rival_total,best=best,window=window,
          laps=[{'lap':int(l),'actual_cumulative':a,'scenario_cumulative':b,'delta':d} for l,a,b,d in zip(g.lap_number,np.cumsum(actual),np.cumsum(actual+delta),np.cumsum(delta))],
          actual_stints=[{'compound':str(c),'start':int(s.lap_number.min()),'end':int(s.lap_number.max())} for (n,c),s in g.groupby(['stint','compound'])],
          warnings=warnings,calibration=self.strategy_report))

    def fit_dna(self):
        frame=pd.DataFrame([{'id':x['id'],'driver':x['driver'],'lap_number':x['lap_number'],**x['features']} for x in self.dna_raw])
        self.dna=self.store.put_read('dna_features',frame)
        train=self.dna.lap_number<=50;valid=(self.dna.lap_number>50)&(self.dna.lap_number<=57);test=self.dna.lap_number>=58
        self.dna_model=RandomForestClassifier(n_estimators=220,max_depth=8,min_samples_leaf=2,max_features=.8,class_weight='balanced',random_state=42,n_jobs=1)
        self.dna_model.fit(self.dna.loc[train,DNA_FEATURES],self.dna.loc[train,'driver'])
        predictions=self.dna_model.predict(self.dna.loc[test,DNA_FEATURES]);classes=DRIVERS
        self.challenge_ids=self.dna.loc[test,'id'].tolist();np.random.default_rng(42).shuffle(self.challenge_ids)
        self.dna_map={x['id']:x for x in self.dna_raw}
        self.radar_low=self.dna.loc[train,RADAR_FEATURES].quantile(.01);self.radar_high=self.dna.loc[train,RADAR_FEATURES].quantile(.99)
        self.dna_report=safe(dict(train_rows=int(train.sum()),validation_rows=int(valid.sum()),test_rows=int(test.sum()),classes=classes,
          accuracy=accuracy_score(self.dna.loc[test,'driver'],predictions),confusion=confusion_matrix(self.dna.loc[test,'driver'],predictions,labels=classes),
          chance_accuracy=.25,feature_count=len(DNA_FEATURES),features=DNA_FEATURES,
          importance=[{'name':FEATURE_LABELS[k],'key':k,'value':float(v)} for k,v in sorted(zip(DNA_FEATURES,self.dna_model.feature_importances_),key=lambda x:-x[1])],
          archetypes={d:self.radar_values(g[RADAR_FEATURES].median()) for d,g in self.dna.loc[train].groupby('driver')},
          radar_labels=[FEATURE_LABELS[k] for k in RADAR_FEATURES],
          note='Identifies four same-race driver–car combinations. Car, tyres, DRS, and track conditions confound style. Votes are not calibrated probabilities.'))

    def radar_values(self,features):
        return [float(np.clip((features[k]-self.radar_low[k])/max(self.radar_high[k]-self.radar_low[k],1e-8),0,1)) for k in RADAR_FEATURES]

    def challenge(self,index=0):
        cid=self.challenge_ids[index%len(self.challenge_ids)];r=self.dna_map[cid]
        return safe(dict(id=cid,index=index,lap_number=r['lap_number'],trace=r['trace'],radar=self.radar_values(r['features']),
          radar_labels=self.dna_report['radar_labels'],source='Real held-out telemetry; driver identity hidden',total=len(self.challenge_ids)))

    def reveal(self,cid,guess=None):
        if cid not in self.challenge_ids:raise ValueError('Not a held-out challenge')
        row=self.dna[self.dna.id==cid];r=self.dna_map[cid]
        probabilities=self.dna_model.predict_proba(row[DNA_FEATURES])[0]
        votes=sorted([{'driver':str(c),'vote':float(p)} for c,p in zip(self.dna_model.classes_,probabilities)],key=lambda x:-x['vote'])
        return safe(dict(id=cid,actual=r['driver'],model_guess=votes[0]['driver'],model_correct=votes[0]['driver']==r['driver'],
          guess=guess,correct=guess==r['driver'] if guess else None,votes=votes,lap_number=r['lap_number'],lap_time=r['lap_time'],compound=r['compound'],tyre_life=r['tyre_life'],
          features=[{'name':FEATURE_LABELS[k],'value':r['features'][k],'key':k} for k in DNA_FEATURES]))

    def pace_view(self,driver='NOR',method='model',threshold=0.):
        p=self.pace;g=p[p.driver_code==driver];pred=method+'_prediction';res=method+'_residual';test=g[g.split=='test']
        chart=[]
        for _,r in g.iterrows():
            chart.append({'lap':int(r.lap_number),'actual':r.lap_duration_s,'predicted':r[pred] if r.split!='train' else None,
              'baseline':r.baseline_prediction if r.split!='train' else None,'split':r.split,'compound':r.compound,'tyre_life':r.tyre_life})
        anomalies=p[(p.split=='test')&(p[res]>=threshold)].sort_values(res,ascending=False).head(16)
        return safe(dict(driver=driver,method=method,chart=chart,report=self.pace_report,
          driver_metrics={'rows':len(test),'mae':mean_absolute_error(test.lap_duration_s,test[pred]) if len(test) else None},
          anomalies=[{'id':r.id,'driver':r.driver_code,'lap':int(r.lap_number),'actual':r.lap_duration_s,'predicted':r[pred],'delta':r[res],
            'compound':r.compound,'tyre_life':r.tyre_life,'previous_median':r.rolling_median,'previous_std':r.rolling_std,'previous_lap':r.previous_lap_s,'history_max_lap':int(r.history_max_lap)} for _,r in anomalies.iterrows()]))

    def ghost_view(self,a='NOR',b='VER'):
        aa=self.ghosts[a];bb=self.ghosts[b]
        delta=np.array(bb['trace']['time'])-np.array(aa['trace']['time'])
        return safe(dict(a=aa,b=bb,delta=delta,finish_delta=bb['lap_time']-aa['lap_time']))

    def pipeline_status(self):
        return safe(dict(status='ready',built_at=self.built_at,duration_seconds=getattr(self,'duration',0),steps=self.steps,
          search_backend='SQLite · local query tables',feature_backend='SQLite · local Hopsworks substitute',cloud_connected=False,
          groups=[{'name':n,'rows':len(f),'version':1,'primary_key':'id','read_back':True} for n,f in [('ghost_features',self.ghost_features),('pace_features',self.pace),('dna_features',self.dna),('strategy_features',self.store.read('strategy_features'))]]))

    def bootstrap(self):
        return safe(dict(manifest=self.manifest,drivers=self.results,selected_drivers=DRIVERS,pipeline=self.pipeline_status(),
          pace_report=self.pace_report,dna_report=self.dna_report,strategy_report=self.strategy_report,
          overview_track=self.ghosts['NOR']['trace'],ghost_summary=[{k:v for k,v in self.ghosts[d].items() if k!='trace'} for d in DRIVERS],
          strategy_preview=self.strategy('NOR')['window'],
          pace_preview=[{'x':int(r.lap_number),'actual':r.lap_duration_s,'predicted':r.baseline_prediction} for _,r in self.pace[(self.pace.driver_code=='NOR')&(self.pace.split=='test')].sort_values('lap_number').iterrows()]))
