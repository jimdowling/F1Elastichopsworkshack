"""Four exploratory F1 experiments, fitted per race from the Hopsworks F1 feature groups.

Inputs (laps, results, telemetry signatures, ghost-lap traces) are built from the shared
feature groups through the Hopsworks Query Service and cached in RonDB; every feature table
the models consume is written to RonDB (app_pitlane__lab_features) and read back first.
"""
from datetime import datetime, timezone
from threading import RLock
from collections import OrderedDict
import hashlib, logging, time
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBRegressor, XGBClassifier
import threading
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, accuracy_score, confusion_matrix
from . import hopsdata
from .hopsdata import records
from .registry import models as model_store
from . import model_plots

log=logging.getLogger('pitlane.engine')
LAB_DRIVERS=4
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

def now():return datetime.now(timezone.utc).isoformat()


def clean_lap(r):
    return (r['lap_number']>1 and pd.notna(r['lap_duration_s']) and r['lap_duration_s']>0
        and not r['is_pit_in_lap'] and not r['is_pit_out_lap'] and str(r['track_status'])=='1'
        and bool(r['is_accurate']) and r['compound'] in ['SOFT','MEDIUM','HARD'] and pd.notna(r['tyre_life']))


def make_pace_features(laps,cuts):
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
                     'split':'train' if r['lap_number']<=cuts[0] else 'validation' if r['lap_number']<=cuts[1] else 'test'})
            hist.append(r);last=r
    return pd.DataFrame(features)


def digest(frame,cols):
    """Fingerprint of a model's training data: a registered model is reused only for identical data."""
    return hashlib.sha256(frame[cols].to_csv(index=False,float_format='%.9g').encode()).hexdigest()


def eligible(r):
    return r['lap_number']>1 and r['lap_duration_s'] is not None and not r['is_pit_in_lap'] and not r['is_pit_out_lap'] and r['track_status']=='1' and r['is_accurate']


def build_lab_inputs(arch,data,season,rnd):
    """Port of the original Dutch-GP snapshot builder, for any race, from feature groups."""
    raw=arch.races.get((season,rnd))
    if not raw or not raw['laps']:raise ValueError('This event has no Race lap data in f1_laps.')
    event=raw['event'];key=raw['session']['session_key'];start=raw['race_start_epoch'];origin=raw['clock_origin_epoch']
    race=sorted([r for r in arch.catalog['results'] if r['season']==season and r['round_number']==rnd and r['session_name']=='Race'],key=lambda r:r['position'] or 99)
    colours={d['driver_number']:d.get('team_colour') for d in records(data.read('f1_session_drivers',['driver_number','team_colour'],lambda fg:fg.session_key==int(key)))}
    results=[dict(code=r['driver_code'],name=r['full_name'],number=str(r['driver_number']),team=r['team_name'],color='#'+(colours.get(r['driver_number']) or '8d9dab'),
        grid=r['grid_position'] or 0,position=r['position'] or 99,status=r['status'] or 'Unknown',points=r['points']) for r in race]
    classified={r['driver_code']:r['classified_time_ms']/1000 for r in race if r.get('classified_time_ms')}
    # Conservatively exclude laps overlapping recorded yellow/red flag intervals.
    active={};interrupted=[];end_of_race=max([l['lap_end_s'] for l in raw['laps'] if l['lap_end_s'] is not None]+[7200])+origin
    for e in sorted(raw['race_control'],key=lambda e:e['session_time_s']):
        t=origin+e['session_time_s'];flag=e.get('flag') or '';sector=e.get('sector') or 'track'
        if flag in ['YELLOW','DOUBLE YELLOW','RED']:active.setdefault(sector,t)
        if flag in ['CLEAR','GREEN']:
            for k in (list(active) if sector=='track' else [sector]):
                if k in active:interrupted.append((active.pop(k),t))
    interrupted+=[(t,end_of_race) for t in active.values()]
    rows=[]
    for l in raw['laps']:
        if l['lap_start_s'] is None:continue
        t0=origin+l['lap_start_s'];duration=None if l['lap_duration_ms'] is None else l['lap_duration_ms']/1000;t1=t0+(duration or 0)
        sectors=[None if l[f'duration_sector_{i}'] is None else l[f'duration_sector_{i}']/1000 for i in (1,2,3)]
        rows.append(dict(id=l['id'],season=season,round_number=rnd,event_name=event['event_name'],session_name='Race',driver_code=l['driver_code'],driver_number=l['driver_number'],
            team_name=l['team_name'],lap_number=l['lap_number'],lap_duration_s=duration,lap_duration_ms=l['lap_duration_ms'],compound=l['compound'],tyre_life=l['tyre_life'],stint=l['stint'],
            is_pit_in_lap=l['is_pit_in_lap'],is_pit_out_lap=l['is_pit_out_lap'],track_status='2' if any(a<t1 and b>t0 for a,b in interrupted) else '1',position=l['position'],
            is_accurate=bool(duration and all(v is not None for v in sectors) and abs(sum(sectors)-duration)<0.1),sector1_s=sectors[0],sector2_s=sectors[1],sector3_s=sectors[2],
            lap_start_s=t0-start,lap_end_s=t1-start,date_start=l['date_start'],t0=t0,source='f1_laps + f1_stints + f1_race_control',synthetic=False))
    rows.sort(key=lambda x:(x['driver_code'],x['lap_number']))
    counts={c:sum(eligible(x) for x in rows if x['driver_code']==c) for c in [r['code'] for r in results]}
    selected=[r['code'] for r in results if counts.get(r['code'],0)>=8][:LAB_DRIVERS]
    if len(selected)<2:raise ValueError('Fewer than two drivers have enough green-flag laps in this race for the experiments.')
    numbers={r['code']:int(r['number']) for r in results}
    car_all=data.car_telemetry(key,[numbers[c] for c in selected]);loc_all=data.car_location(key,[numbers[c] for c in selected])
    ghosts={};dna=[]
    for code in selected:
        driver_rows=[x for x in rows if x['driver_code']==code and eligible(x)];best=min(driver_rows,key=lambda x:x['lap_duration_s'])
        car=car_all[car_all.driver_number==numbers[code]].sort_values('t').drop_duplicates('t');ct=car.t.to_numpy()
        loc=loc_all[loc_all.driver_number==numbers[code]].sort_values('t').drop_duplicates('t');lt=loc.t.to_numpy()
        for row in driver_rows:
            t0=row['t0'];duration=row['lap_duration_s'];t1=t0+duration
            sub=car[(car.t>=t0)&(car.t<=t1)]
            if len(sub)<100:continue
            tt=sub.t.to_numpy()-t0;speed=sub.speed.to_numpy(float);rpm=sub.rpm.to_numpy(float);gear=sub.n_gear.to_numpy(float)
            throttle=sub.throttle.to_numpy(float);brake=(sub.brake.to_numpy(float)>50).astype(float)
            dt=np.diff(tt);accel=np.diff(speed)/3.6/np.maximum(dt,.02)
            features=dict(mean_speed=np.mean(speed),p95_speed=np.percentile(speed,95),speed_std=np.std(speed),full_throttle=np.mean(throttle>=98),
              brake_fraction=np.mean(brake),mean_throttle=np.mean(throttle),mean_rpm=np.mean(rpm),mean_gear=np.mean(gear),
              drs_fraction=np.mean(sub.drs.to_numpy(float)>=10),accel_std=np.std(np.clip(accel,-20,20)),low_speed=np.percentile(speed,10),high_gear_fraction=np.mean(gear>=7))
            # Trapezoidal integration of measured speed provides approximate distance.
            distance=np.r_[0,np.cumsum((speed[1:]+speed[:-1])/2/3.6*dt)]
            if distance[-1]<=0:continue
            dd=distance/distance[-1];gg=np.linspace(0,1,100)
            dna.append(dict(id=hashlib.sha256(f'DNA-{season}-{rnd}-{code}-{row["lap_number"]}'.encode()).hexdigest()[:16],driver=code,lap_number=row['lap_number'],
              compound=row['compound'],tyre_life=row['tyre_life'],lap_time=duration,features=features,
              trace={'speed':np.round(np.interp(gg,dd,speed),1),'throttle':np.round(np.interp(gg,dd,throttle),1),'brake':np.round(np.interp(gg,dd,brake),2)}))
            if row['id']==best['id'] and len(lt)>1:
                times=np.r_[0,tt[(tt>0)&(tt<duration)],duration]
                vals={k:np.interp(t0+times,ct,car[c].to_numpy(float)) for k,c in [('speed','speed'),('throttle','throttle'),('brake','brake'),('gear','n_gear'),('rpm','rpm')]}
                vals['brake']=(vals['brake']>50).astype(float)
                dis=np.r_[0,np.cumsum((vals['speed'][1:]+vals['speed'][:-1])/2/3.6*np.diff(times))];d=dis/dis[-1];grid=np.linspace(0,1,361)
                trace={k:np.interp(grid,d,v) for k,v in vals.items()};trace['time']=np.interp(grid,d,times);trace['distance']=grid
                trace['x']=np.interp(t0+trace['time'],lt,loc.x.to_numpy(float));trace['y']=np.interp(t0+trace['time'],lt,loc.y.to_numpy(float))
                ghosts[code]=dict(driver=code,number=str(numbers[code]),lap_number=row['lap_number'],lap_time=duration,compound=row['compound'],tyre_life=row['tyre_life'],
                  sectors=[row['sector1_s'],row['sector2_s'],row['sector3_s']],source='f1_car_telemetry + f1_car_location; approximate distance integrated from speed; positions interpolated; official lap-time endpoints',
                  trace={k:np.round(v,3 if k!='distance' else 6) for k,v in trace.items()})
    selected=[c for c in selected if c in ghosts and sum(x['driver']==c for x in dna)>=4]
    if len(selected)<2:raise ValueError('Fewer than two drivers have usable telemetry laps in this race for the experiments.')
    for r in rows:r.pop('t0',None)
    w=raw['weather'];air=[x['air_temperature'] for x in w if x.get('air_temperature') is not None];track=[x['track_temperature'] for x in w if x.get('track_temperature') is not None]
    manifest=dict(dataset=f"{season} {event['event_name']} · Race",circuit=event.get('location') or event.get('circuit_name'),circuit_name=event.get('circuit_name'),country=event.get('country'),
     date=event['date'],season=season,round=rnd,total_laps=int(max(x['lap_number'] for x in rows)),lap_rows=len(rows),drivers=len(results),dna_laps=sum(x['driver'] in selected for x in dna),
     ghost_laps=len(selected),selected_drivers=selected,fetched_at=now(),source=f'Hopsworks feature groups in {hopsdata.FEATURE_STORE} via the Hopsworks Query Service',synthetic_observations=0,
     weather={'air_temp_c':float(np.median(air)) if air else None,'track_temp_c':float(np.median(track)) if track else None,'rain_samples':int(sum(bool(x.get('rainfall')) for x in w)),'samples':len(w)},
     feature_groups=['f1_laps','f1_stints','f1_race_control','f1_race_results','f1_session_drivers','f1_car_telemetry','f1_car_location'],
     notes=['All observations come from the shared Hopsworks F1 feature groups. Zero synthetic race observations.',
      'Tyre age and pit-in flags are derived from stint/pit records. Track eligibility is conservatively derived from race-control flags. Sector-sum consistency is the lap-accuracy check.',
      'Distance is approximated by integrating measured speed. Telemetry and positions are interpolated for visualization.',
      'Pitwall outcomes are illustrative model outputs, not observed alternatives or validated causal predictions.',
      'Feature tables are written to and read back from RonDB (app_pitlane__lab_features) before the models consume them.',
      'Different fastest laps have different tyre/fuel/traffic conditions. Driver DNA identifies same-race driver-car signatures, not intrinsic driving style.'])
    return safe(dict(manifest=manifest,results=results,laps=rows,ghosts={c:ghosts[c] for c in selected},dna=[x for x in dna if x['driver'] in selected],classified_times=classified,selected=selected))

class LabEngine:
    def __init__(self,season,rnd,arch,data,store):
        self.season=season;self.round=rnd;self.race_key=f'{season}-{rnd:02d}';self.store=store
        inputs=store.cached(f'lab-inputs:{self.race_key}',lambda:build_lab_inputs(arch,data,season,rnd))
        self.manifest=inputs['manifest'];self.results=inputs['results'];self.raw_ghosts=inputs['ghosts'];self.ghosts=self.raw_ghosts
        self.dna_raw=inputs['dna'];self.raw_laps=inputs['laps'];self.laps=pd.DataFrame(self.raw_laps);self.classified_times=inputs['classified_times']
        self.drivers=inputs['selected'];L=int(self.laps.lap_number.max());self.total_laps=L
        # Chronological splits as fractions of race distance (72 laps -> 43/57 as in the original Dutch GP lab).
        self.pace_cuts=(int(L*.6),int(L*.8));self.dna_cuts=(int(L*.7),int(L*.8));self.window=(max(2,int(L*.17)),int(L*.79))
        for col in ['lap_duration_s','tyre_life','sector1_s','sector2_s','sector3_s','lap_start_s','lap_end_s']:self.laps[col]=pd.to_numeric(self.laps[col],errors='coerce')
        self.steps=[];self.built_at=now();self.model_sources={};self.pending=[];self.force_train=False;self.rebuild()

    def step(self,name,count,start,detail):
        self.steps.append(dict(name=name,rows=int(count),seconds=round(time.perf_counter()-start,3),status='complete',detail=detail))

    def rebuild(self):
        start=time.perf_counter();self.steps=[]
        if not self.laps.id.is_unique:raise RuntimeError('Duplicate raw laps')
        self.store.put_read(self.race_key,'race_laps',self.laps)
        self.step('Read & index observations',len(self.laps),start,'Laps read from f1_laps/f1_stints/f1_race_control via the Query Service; indexed in RonDB')
        t=time.perf_counter();points=[]
        for code,g in self.raw_ghosts.items():
            for i in range(len(g['trace']['time'])):
                points.append({'id':f'{self.race_key}-R-{code}-{g["lap_number"]}-{i:03d}','driver_code':code,'lap_number':g['lap_number'],'sample':i,
                    'lap_time':g['lap_time'],'compound':g['compound'],'tyre_life':g['tyre_life'],**{k:v[i] for k,v in g['trace'].items()}})
        self.ghost_features=self.store.put_read(self.race_key,'ghost_features',pd.DataFrame(points));self.ghosts={}
        for code,g in self.raw_ghosts.items():
            rows=self.ghost_features[self.ghost_features.driver_code==code].sort_values('sample')
            self.ghosts[code]={**g,'trace':{k:rows[k].tolist() for k in g['trace']}}
        self.step('Align & read back replay features',len(self.ghost_features),t,f'{len(self.drivers)} real lap traces; all replay channels consumed from the RonDB feature table')
        t=time.perf_counter();features=make_pace_features(self.laps,self.pace_cuts)
        if features.empty or not (features.split=='test').any() or not (features.split=='train').any():raise ValueError('Not enough clean green-flag laps in this race to fit the pace model.')
        self.pace=self.store.put_read(self.race_key,'pace_features',features)
        assert (self.pace.history_max_lap<self.pace.lap_number).all()
        self.step('Engineer & read back pace features',len(self.pace),t,'Past-only rolling windows; persisted feature-table round trip')
        t=time.perf_counter();self.fit_pace()
        self.step('Train & evaluate pace model',self.pace_report['test_rows'],t,self.source_note('pace')+f' · XGBoost · Chronological train ≤{self.pace_cuts[0]} / validation {self.pace_cuts[0]+1}–{self.pace_cuts[1]} / test ≥{self.pace_cuts[1]+1}')
        t=time.perf_counter();self.fit_strategy()
        self.step('Calibrate strategy simulator',self.strategy_report['rows'],t,self.source_note('strategy')+' · Ridge-calibrated pace assumptions; not a causal model')
        t=time.perf_counter();self.fit_dna()
        self.step('Train & evaluate driver–car classifier',self.dna_report['test_rows'],t,self.source_note('dna')+' · XGBoost · telemetry-only features; whole-lap chronological holdout')
        t=time.perf_counter();self.store.put_read(self.race_key,'pace_results',self.pace)
        self.step('Publish application results',len(self.pace),t,'Results in RonDB; all four experiences ready')
        self.built_at=now();self.duration=round(time.perf_counter()-start,3);self.force_train=False
        self.register_pending()
        return self.pipeline_status()

    def model(self,kind,training_digest,train):
        """This race's model from the Model Registry when one matches, else train() it and queue registration."""
        name=f'pitlane_{kind}_{self.season}_{self.round:02d}'
        if not self.force_train:
            found=model_store().load(name,training_digest)
            if found:
                self.model_sources[kind]={'name':name,'version':found[1],'source':'downloaded from the Model Registry'};return found[0]
        obj=train();self.pending.append((kind,name,obj,training_digest))
        self.model_sources[kind]={'name':name,'version':None,'source':'trained in the app; registering in the Model Registry'}
        return obj

    def source_note(self,kind):
        m=self.model_sources.get(kind,{});return f"{m.get('name')} v{m['version']} downloaded from the Model Registry" if m.get('version') else 'Trained now; registering in the Model Registry'

    def retrain(self):
        """Explicit re-run: train fresh models and register them as new versions."""
        self.force_train=True;return self.rebuild()

    def register_pending(self):
        """Upload newly trained models in the background so requests don't wait on the registry."""
        pending,self.pending=self.pending,[]
        if not pending:return
        metrics={'pace':lambda:{'model_mae':self.pace_report['model_mae'],'baseline_mae':self.pace_report['baseline_mae'],'validation_mae':self.pace_report['validation_mae']},
                 'dna':lambda:{'accuracy':self.dna_report['accuracy'],'chance_accuracy':self.dna_report['chance_accuracy']},
                 'strategy':lambda:{'age_coefficient':self.age_coefficient,'fuel_coefficient':self.fuel_coefficient,'pit_loss':self.pit_loss}}
        about={'pace':'XGBoost lap-time regressor (Pace Detective)','dna':'XGBoost driver-car classifier (Driver DNA)','strategy':'Ridge pace calibration for the Pitwall simulator'}
        jobs=[(kind,name,obj,d,metrics[kind](),f"{about[kind]} for {self.manifest['dataset']}; trained on RonDB feature tables built from the Hopsworks F1 feature groups.") for kind,name,obj,d in pending]
        def run():
            for kind,name,obj,d,m,text in jobs:
                try:
                    version=model_store().save(name,obj,d,m,text,images=lambda folder,kind=kind:model_plots.write(kind,folder,self))
                    self.model_sources[kind]={'name':name,'version':version,'source':'trained in the app; registered in the Model Registry'}
                    log.info('Registered %s v%s',name,version)
                except Exception as e:
                    self.model_sources[kind]={'name':name,'version':None,'source':f'trained in the app; registration failed ({type(e).__name__})'}
                    log.exception('Could not register %s',name)
        threading.Thread(target=run,daemon=True).start()

    def fit_pace(self):
        p=self.pace
        numeric=['lap_number','tyre_life','rolling_median','rolling_mean','rolling_std','previous_lap_s']
        cats=['driver_code','compound'];self.pace_inputs=numeric+cats
        pre=ColumnTransformer([('numeric','passthrough',numeric),('category',OneHotEncoder(handle_unknown='ignore',sparse_output=False),cats)])
        train=p.split=='train';valid=p.split=='validation';test=p.split=='test'
        def fit():
            m=Pipeline([('features',pre),('model',XGBRegressor(n_estimators=300,max_depth=4,learning_rate=.05,subsample=.9,colsample_bytree=.9,min_child_weight=3,random_state=42,n_jobs=1))])
            return m.fit(p.loc[train,self.pace_inputs],p.loc[train,'lap_duration_s'])
        self.pace_model=self.model('pace',digest(p[train],['id']+self.pace_inputs+['lap_duration_s']),fit);pre=self.pace_model.named_steps['features']
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
        frame=self.store.put_read(self.race_key,'strategy_features',clean[cols])
        def fit():
            pre=ColumnTransformer([('numeric','passthrough',['lap_number','tyre_life']),('category',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['driver_code','compound'])])
            return Pipeline([('pre',pre),('ridge',Ridge(alpha=5.))]).fit(frame,frame.lap_duration_s)
        model=self.model('strategy',digest(frame,cols),fit);pre=model.named_steps['pre'];self.strategy_frame=frame;self.strategy_model=model
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
        stoppers=[d for d in self.drivers if d in self.driver_base and self.laps[(self.laps.driver_code==d)&self.laps.is_pit_in_lap].shape[0]]
        self.strategy_driver=stoppers[0] if stoppers else None
        self.strategy_report=safe(dict(rows=len(frame),age_coefficient=self.age_coefficient,fuel_coefficient=self.fuel_coefficient,
          raw_age_coefficient=raw_age,raw_fuel_coefficient=raw_fuel,compound_offsets=self.compound_offsets,pit_loss=self.pit_loss,
          pit_loss_pairs=len(excess),pit_loss_source='Median pit-in/out excess vs fitted clean pace' if excess else '22-second assumed fallback',
          compound_counts=frame.compound.value_counts().to_dict(),compound_max_age=frame.groupby('compound').tyre_life.max().to_dict(),
          note='In-sample calibration for an illustrative simulator, not validated strategy prediction. Fuel/tyre/traffic effects are confounded.'))

    def clean_pace(self,driver,lap,age,compound,scale=1.):
        return self.driver_base[driver]+self.fuel_coefficient*lap+self.age_coefficient*scale*age+self.compound_offsets.get(compound,0)

    def strategy(self,driver=None,pit_lap=None,compound='HARD',degradation=1.,pit_loss=None):
        driver=driver or self.strategy_driver
        if driver not in self.driver_base:raise ValueError('Select one of this race\'s lab drivers')
        g=self.laps[self.laps.driver_code==driver].sort_values('lap_number')
        stops=g[g.is_pit_in_lap].lap_number.astype(int).tolist()
        if not stops:raise ValueError(f'{driver} made no pit stop in this race; there is no stop to move.')
        if pit_lap is not None and not 2<=int(pit_lap)<int(g.lap_number.max())-1:raise ValueError('Pit lap is outside this race distance')
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
        for stop in range(self.window[0],self.window[1]+1):
            change=float((predicted(stop,compound,degradation,pit_loss)-baseline).sum());window.append({'lap':stop,'delta':change})
        best=min(window,key=lambda x:x['delta'])
        warnings=['Illustrative counterfactual, not a validated forecast. No rival reactions, traffic simulation, or safety cars.']
        if compound==start_comp:warnings.append('Same-compound plan: not a legal dry-race one-stop strategy.')
        max_age=new_age+int(g.lap_number.max())-pit_lap-1
        if max_age>self.strategy_report['compound_max_age'].get(compound,0):warnings.append('Chosen stint extrapolates beyond observed tyre ages for this compound.')
        lap_sum_total=float(actual.sum())
        actual_total=self.classified_times.get(driver,lap_sum_total);scenario_total=actual_total+float(delta.sum())
        order=[r['code'] for r in sorted(self.results,key=lambda r:r['position'])];rival=order[0] if driver!=order[0] else order[1];rg=self.laps[self.laps.driver_code==rival]
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
        self.dna=self.store.put_read(self.race_key,'dna_features',frame)
        a,b=self.dna_cuts;train=self.dna.lap_number<=a;valid=(self.dna.lap_number>a)&(self.dna.lap_number<=b);test=self.dna.lap_number>b
        if not test.any() or self.dna.loc[train,'driver'].nunique()<2:raise ValueError('Not enough held-out telemetry laps in this race for Driver DNA.')
        def fit():
            X=self.dna.loc[train,DNA_FEATURES];y=self.dna.loc[train,'driver'];labels=sorted(y.unique())
            clf=XGBClassifier(n_estimators=300,max_depth=4,learning_rate=.08,subsample=.9,colsample_bytree=.8,random_state=42,n_jobs=1,eval_metric='mlogloss')
            clf.fit(X,y.map({c:i for i,c in enumerate(labels)}),sample_weight=compute_sample_weight('balanced',y))
            return {'model':clf,'classes':labels}  # XGBoost needs integer labels; keep the driver codes alongside
        bundle=self.model('dna',digest(self.dna[train],['id','driver']+DNA_FEATURES),fit)
        self.dna_model=bundle['model'];self.dna_classes=bundle['classes']
        predictions=np.array(self.dna_classes)[self.dna_model.predict(self.dna.loc[test,DNA_FEATURES]).astype(int)];classes=self.drivers
        self.challenge_ids=self.dna.loc[test,'id'].tolist();np.random.default_rng(42).shuffle(self.challenge_ids)
        self.dna_map={x['id']:x for x in self.dna_raw}
        self.radar_low=self.dna.loc[train,RADAR_FEATURES].quantile(.01);self.radar_high=self.dna.loc[train,RADAR_FEATURES].quantile(.99)
        self.dna_report=safe(dict(train_rows=int(train.sum()),validation_rows=int(valid.sum()),test_rows=int(test.sum()),classes=classes,
          accuracy=accuracy_score(self.dna.loc[test,'driver'],predictions),confusion=confusion_matrix(self.dna.loc[test,'driver'],predictions,labels=classes),
          chance_accuracy=1/len(classes),feature_count=len(DNA_FEATURES),features=DNA_FEATURES,
          importance=[{'name':FEATURE_LABELS[k],'key':k,'value':float(v)} for k,v in sorted(zip(DNA_FEATURES,self.dna_model.feature_importances_),key=lambda x:-x[1])],
          archetypes={d:self.radar_values(g[RADAR_FEATURES].median()) for d,g in self.dna.loc[train].groupby('driver')},
          radar_labels=[FEATURE_LABELS[k] for k in RADAR_FEATURES],
          note=f'XGBoost classifier. Identifies {len(classes)} same-race driver–car combinations. Car, tyres, DRS, and track conditions confound style. Votes are not calibrated probabilities.'))

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
        votes=sorted([{'driver':str(c),'vote':float(p)} for c,p in zip(self.dna_classes,probabilities)],key=lambda x:-x['vote'])
        return safe(dict(id=cid,actual=r['driver'],model_guess=votes[0]['driver'],model_correct=votes[0]['driver']==r['driver'],
          guess=guess,correct=guess==r['driver'] if guess else None,votes=votes,lap_number=r['lap_number'],lap_time=r['lap_time'],compound=r['compound'],tyre_life=r['tyre_life'],
          features=[{'name':FEATURE_LABELS[k],'value':r['features'][k],'key':k} for k in DNA_FEATURES]))

    def pace_view(self,driver=None,method='model',threshold=0.):
        driver=driver or self.drivers[0]
        if driver not in set(self.laps.driver_code):raise ValueError('Unknown driver')
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

    def ghost_view(self,a=None,b=None):
        a=a or self.drivers[0];b=b or self.drivers[1]
        if a==b or a not in self.ghosts or b not in self.ghosts:raise ValueError('Select two different lab drivers for this race')
        aa=self.ghosts[a];bb=self.ghosts[b]
        delta=np.array(bb['trace']['time'])-np.array(aa['trace']['time'])
        return safe(dict(a=aa,b=bb,delta=delta,finish_delta=bb['lap_time']-aa['lap_time']))

    def pipeline_status(self):
        return safe(dict(status='ready',built_at=self.built_at,duration_seconds=getattr(self,'duration',0),steps=self.steps,
          search_backend=f'Hopsworks Query Service · {hopsdata.FEATURE_STORE}',feature_backend=self.store.name,cloud_connected=True,race_key=self.race_key,models=self.model_sources,
          groups=[{'name':n,'rows':int(c),'version':1,'primary_key':'id','read_back':True} for n,c in sorted(self.store.counts(self.race_key).items()) if n!='race_laps']))

    def bootstrap(self):
        lead=self.drivers[0]
        return safe(dict(manifest=self.manifest,season=self.season,round=self.round,drivers=self.results,selected_drivers=self.drivers,strategy_driver=self.strategy_driver,
          total_laps=self.total_laps,window=list(self.window),pace_cuts=list(self.pace_cuts),dna_cuts=list(self.dna_cuts),pipeline=self.pipeline_status(),
          pace_report=self.pace_report,dna_report=self.dna_report,strategy_report=self.strategy_report,
          overview_track=self.ghosts[lead]['trace'],ghost_summary=[{k:v for k,v in self.ghosts[d].items() if k!='trace'} for d in self.drivers],
          strategy_preview=self.strategy()['window'] if self.strategy_driver else [],
          pace_preview=[{'x':int(r.lap_number),'actual':r.lap_duration_s,'predicted':r.baseline_prediction} for _,r in self.pace[(self.pace.driver_code==lead)&(self.pace.split=='test')].sort_values('lap_number').iterrows()]))


ENGINES=OrderedDict();ENGINE_LOCK=RLock();BUILD_LOCKS={}


def lab(season,rnd):
    """Per-race lab engine (fitted once, kept for the 3 most recent races)."""
    from .hopsdata import archive,hops
    from .appdb import store
    key=(season,rnd)
    with ENGINE_LOCK:
        if key in ENGINES:ENGINES.move_to_end(key);return ENGINES[key]
        build_lock=BUILD_LOCKS.setdefault(key,RLock())
    with build_lock:
        with ENGINE_LOCK:
            if key in ENGINES:return ENGINES[key]
        engine=LabEngine(season,rnd,archive(),hops(),store())
        with ENGINE_LOCK:
            ENGINES[key]=engine
            while len(ENGINES)>3:ENGINES.popitem(last=False)
        return engine
