"""Reproducibly fetch real OpenF1 2024 Dutch GP data. No generated observations.
The direct F1/FastF1 host returned HTTP 403 in this environment, so OpenF1 is
our public historical data provider. Jolpica cross-references final results.
"""
from pathlib import Path
import json, hashlib, datetime, time
import numpy as np
import pandas as pd
import requests

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
CACHE=ROOT/'.cache'/'openf1'; CACHE.mkdir(parents=True,exist_ok=True)
SELECTED=['NOR','VER','LEC','PIA']; SESSION=9582
SOURCES=[]

def clean(v):
    if isinstance(v,dict): return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple,np.ndarray)): return [clean(x) for x in v]
    if isinstance(v,np.integer): return int(v)
    if isinstance(v,(np.floating,float)): return round(float(v),6) if np.isfinite(v) else None
    if isinstance(v,np.bool_): return bool(v)
    if v is pd.NA or v is pd.NaT: return None
    return v

def dump(name,obj):
    p=DATA/name; p.write_text(json.dumps(clean(obj),separators=(',',':'),allow_nan=False))
    print(f'Wrote {name}: {p.stat().st_size:,} bytes',flush=True)

def get(ep,**params):
    params={'session_key':SESSION,**params}
    url=requests.Request('GET','https://api.openf1.org/v1/'+ep,params=params).prepare().url
    SOURCES.append(url)
    cache=CACHE/(hashlib.sha256(url.encode()).hexdigest()+'.json')
    if cache.exists(): return json.loads(cache.read_text())
    print('Fetching',ep,params,flush=True)
    for attempt in range(5):
        r=requests.get(url,timeout=120)
        if r.status_code in (429,502,503,504):
            time.sleep(2**attempt+1);continue
        r.raise_for_status(); obj=r.json();cache.write_text(json.dumps(obj));time.sleep(.4);return obj
    raise RuntimeError(f'Public provider did not respond: {url} ({r.status_code})')

def epoch(value): return pd.Timestamp(value).timestamp()
def stamp(value): return datetime.datetime.fromtimestamp(value,datetime.timezone.utc).isoformat()

print('Loading actual 2024 Dutch Grand Prix via OpenF1...',flush=True)
raw_laps=get('laps'); stints=get('stints'); pits=get('pit'); drivers=get('drivers'); controls=get('race_control'); weather=get('weather')
by_number={d['driver_number']:d for d in drivers}; by_code={d['name_acronym']:d for d in drivers}
r=requests.get('https://api.jolpi.ca/ergast/f1/2024/15/results.json',timeout=30);r.raise_for_status();jolpica=r.json();dump('jolpica_results.json',jolpica)
finals={int(x['number']):x for x in jolpica['MRData']['RaceTable']['Races'][0]['Results']}
results=[]
for d in drivers:
    f=finals.get(d['driver_number'],{})
    results.append(dict(code=d['name_acronym'],name=f"{d['first_name']} {d['last_name']}",number=str(d['driver_number']),team=d['team_name'],
      color='#'+d['team_colour'],grid=int(f.get('grid',0)),position=int(f.get('position',99)),status=f.get('status','Unknown'),points=float(f.get('points',0))))
results.sort(key=lambda x:x['position']);dump('results.json',results)
start=min(epoch(l['date_start']) for l in raw_laps if l.get('date_start'))
# Conservatively exclude laps overlapping recorded yellow/red flag intervals.
active={}; interrupted=[]
for e in sorted(controls,key=lambda e:e['date']):
    t=epoch(e['date']); flag=e.get('flag') or ''; key=e.get('sector') or 'track'
    if flag in ['YELLOW','DOUBLE YELLOW','RED']: active.setdefault(key,t)
    if flag in ['CLEAR','GREEN']:
        keys=list(active) if key=='track' else [key]
        for k in keys:
            if k in active: interrupted.append((active.pop(k),t))
for t in active.values():interrupted.append((t,start+7200))
rows=[]
for l in raw_laps:
    n=l['driver_number']; lap=l['lap_number']; duration=l.get('lap_duration'); ds=l.get('date_start')
    if n not in by_number or not ds: continue
    t0=epoch(ds); t1=t0+(duration or 0)
    stint=next((s for s in stints if s['driver_number']==n and s['lap_start']<=lap<=(s.get('lap_end') or 999)),None)
    pit_in=any(p['driver_number']==n and p['lap_number']==lap for p in pits)
    sectors=[l.get('duration_sector_'+str(i)) for i in [1,2,3]]
    accurate=bool(duration and all(v is not None for v in sectors) and abs(sum(sectors)-duration)<0.1)
    row=dict(id=f'2024-15-R-{by_number[n]["name_acronym"]}-{lap}',season=2024,round_number=15,event_name='Dutch Grand Prix',session_name='Race',
      driver_code=by_number[n]['name_acronym'],team_name=by_number[n]['team_name'],lap_number=lap,lap_duration_s=duration,
      lap_duration_ms=None if duration is None else int(round(duration*1000)),compound=stint['compound'] if stint else 'UNKNOWN',
      tyre_life=stint['tyre_age_at_start']+lap-stint['lap_start']+1 if stint else None,stint=stint['stint_number'] if stint else None,
      is_pit_in_lap=pit_in,is_pit_out_lap=bool(l.get('is_pit_out_lap')),track_status='2' if any(a<t1 and b>t0 for a,b in interrupted) else '1',
      position=None,is_accurate=accurate,sector1_s=sectors[0],sector2_s=sectors[1],sector3_s=sectors[2],lap_start_s=t0-start,lap_end_s=t1-start,
      date_start=ds,source='OpenF1 public historical API',synthetic=False)
    rows.append(row)
rows.sort(key=lambda x:(x['driver_code'],x['lap_number']));dump('laps.json',rows);dump('stints.json',stints);dump('pits.json',pits)

def eligible(r):
    return r['lap_number']>1 and r['lap_duration_s'] is not None and not r['is_pit_in_lap'] and not r['is_pit_out_lap'] and r['track_status']=='1' and r['is_accurate']

ghosts={};dna=[]
for code in SELECTED:
    number=by_code[code]['driver_number']; driver_rows=[x for x in rows if x['driver_code']==code and eligible(x)]
    best=min(driver_rows,key=lambda x:x['lap_duration_s'])
    car=pd.DataFrame(get('car_data',driver_number=number))
    car['t']=pd.to_datetime(car.date,format='ISO8601').astype('int64')/1e9
    car=car.sort_values('t').drop_duplicates('t'); ct=car.t.to_numpy()
    print(f'{code}: {len(car):,} real car samples; {len(driver_rows)} clean laps; best lap {best["lap_number"]}',flush=True)
    for row in driver_rows:
        t0=epoch(row['date_start']); duration=row['lap_duration_s'];t1=t0+duration
        sub=car[(car.t>=t0)&(car.t<=t1)]
        if len(sub)<100:continue
        tt=sub.t.to_numpy()-t0;speed=sub.speed.to_numpy(float);rpm=sub.rpm.to_numpy(float);gear=sub.n_gear.to_numpy(float)
        throttle=sub.throttle.to_numpy(float);brake=(sub.brake.to_numpy(float)>50).astype(float)
        dt=np.diff(tt);accel=np.diff(speed)/3.6/np.maximum(dt,.02)
        features=dict(mean_speed=np.mean(speed),p95_speed=np.percentile(speed,95),speed_std=np.std(speed),full_throttle=np.mean(throttle>=98),
          brake_fraction=np.mean(brake),mean_throttle=np.mean(throttle),mean_rpm=np.mean(rpm),mean_gear=np.mean(gear),
          drs_fraction=np.mean(sub.drs.to_numpy(float)>=10),accel_std=np.std(np.clip(accel,-20,20)),low_speed=np.percentile(speed,10),high_gear_fraction=np.mean(gear>=7))
        # Trapezoidal integration of measured speed provides approximate distance.
        distance=np.r_[0,np.cumsum((speed[1:]+speed[:-1])/2/3.6*dt)];dd=distance/distance[-1];gg=np.linspace(0,1,100)
        dna.append(dict(id=hashlib.sha256(f'DNA-{code}-{row["lap_number"]}'.encode()).hexdigest()[:16],driver=code,lap_number=row['lap_number'],
          compound=row['compound'],tyre_life=row['tyre_life'],lap_time=duration,features=features,
          trace={'speed':np.round(np.interp(gg,dd,speed),1),'throttle':np.round(np.interp(gg,dd,throttle),1),'brake':np.round(np.interp(gg,dd,brake),2)}))
        if row['id']==best['id']:
            loc=pd.DataFrame(get('location',driver_number=number,**{'date>':stamp(t0-1),'date<':stamp(t1+1)}))
            lt=pd.to_datetime(loc.date,format='ISO8601').astype('int64').to_numpy()/1e9
            # Exact lap endpoints plus interpolated real observed car channels.
            times=np.r_[0,tt[(tt>0)&(tt<duration)],duration]
            vals={k:np.interp(t0+times,ct,car[c].to_numpy(float)) for k,c in [('speed','speed'),('throttle','throttle'),('brake','brake'),('gear','n_gear'),('rpm','rpm')]}
            vals['brake']=(vals['brake']>50).astype(float)
            dis=np.r_[0,np.cumsum((vals['speed'][1:]+vals['speed'][:-1])/2/3.6*np.diff(times))];d=dis/dis[-1];grid=np.linspace(0,1,361)
            trace={k:np.interp(grid,d,v) for k,v in vals.items()};trace['time']=np.interp(grid,d,times);trace['distance']=grid
            trace['x']=np.interp(t0+trace['time'],lt,loc.x.to_numpy(float));trace['y']=np.interp(t0+trace['time'],lt,loc.y.to_numpy(float))
            ghosts[code]=dict(driver=code,lap_number=row['lap_number'],lap_time=duration,compound=row['compound'],tyre_life=row['tyre_life'],
              sectors=[row['sector1_s'],row['sector2_s'],row['sector3_s']],source='Real OpenF1 telemetry; approximate distance integrated from speed; real positions interpolated; official lap-time endpoints',
              trace={k:np.round(v,3 if k!='distance' else 6) for k,v in trace.items()})
dump('ghosts.json',ghosts);dump('dna_laps.json',dna)
wf=pd.DataFrame(weather)
manifest=dict(dataset='2024 Dutch Grand Prix · Race',circuit='Zandvoort',date='2024-08-25',season=2024,round=15,total_laps=72,
 lap_rows=len(rows),drivers=len(results),dna_laps=len(dna),ghost_laps=len(ghosts),selected_drivers=SELECTED,
 fetched_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),source='OpenF1 public historical API; Jolpica final results',synthetic_observations=0,
 weather={'air_temp_c':float(wf.air_temperature.median()),'track_temp_c':float(wf.track_temperature.median()),'rain_samples':int(wf.rainfall.sum()),'samples':len(wf)},
 urls=list(dict.fromkeys(SOURCES))+['https://api.jolpi.ca/ergast/f1/2024/15/results.json','https://openf1.org/'],
 notes=['All observations are real public historical data, not event-cluster records. Zero synthetic race observations.',
 'Direct FastF1/F1 timing host returned HTTP 403; OpenF1 is used instead.',
 'Tyre age and pit-in flags are derived from real stint/pit records. Track eligibility is conservatively derived from race-control flags, not FastF1 TrackStatus. Sector-sum consistency is our quality check, not FastF1 IsAccurate.',
 'Distance is approximated by integrating measured speed. Telemetry and positions are interpolated for visualization.',
 'Pitwall outcomes are illustrative model outputs, not observed alternatives or validated causal predictions.',
 'Local SQLite feature tables stand in for Hopsworks. The original labs are not connected to Hopsworks.',
 'Different fastest laps have different tyre/fuel/traffic conditions. Driver DNA identifies same-race driver-car signatures, not intrinsic driving style.'])
manifest['sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in DATA.glob('*.json') if p.name!='manifest.json'}
dump('manifest.json',manifest)
print('REAL DATA READY',flush=True)
