"""Fetch a reproducible, historical 2023–2024 dashboard archive.

Jolpica: complete calendars, race/qualifying/sprint classifications, final
standings, and pit-lane timings. OpenF1: bounded per-session lap, tyre,
position, weather, and race-control observations. No bulk car/location
telemetry ingestion and no observations copied from the reference website.

Sources are cached; the importer is resumable and does not overwrite the
original Dutch-GP experiment snapshot. API rate limits are respected.
"""
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from bisect import bisect_right
import hashlib,json,time,requests,sys

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'/'dashboard';DATA.mkdir(parents=True,exist_ok=True)
CACHE=ROOT/'.cache'/'dashboard-sources';CACHE.mkdir(parents=True,exist_ok=True)
URLS=[];ERRORS=[];LAST={};YEAR_SET=[2023,2024]
SESSION=requests.Session();SESSION.headers['User-Agent']='PitlaneHistoricalResearch/2.0 (public 2023-2024 dataset)'

def dump(path,obj):
    path=Path(path);tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':'),allow_nan=False));tmp.replace(path)
    print('WROTE',path.relative_to(ROOT),path.stat().st_size,flush=True)

def get(url,required=True):
    URLS.append(url);key=hashlib.sha256(url.encode()).hexdigest();cache=CACHE/(key+'.json')
    if cache.exists():return json.loads(cache.read_text())
    host='openf1' if 'openf1.org' in url else 'jolpica';interval=2.12 if host=='openf1' else .52
    for attempt in range(6):
        delay=LAST.get(host,0)+interval-time.monotonic()
        if delay>0:time.sleep(delay)
        LAST[host]=time.monotonic();print('GET',url,flush=True)
        try:
            r=SESSION.get(url,timeout=75)
            if r.status_code in (429,500,502,503,504):
                pause=min(65,max(float(r.headers.get('Retry-After','0') or 0),3*2**attempt))
                print('RETRY',r.status_code,'after',pause,flush=True);time.sleep(pause);continue
            r.raise_for_status();data=r.json();dump_cache=json.dumps(data,ensure_ascii=False,separators=(',',':'));cache.write_text(dump_cache);return data
        except (requests.RequestException,ValueError) as e:
            if attempt<5:time.sleep(min(30,2**attempt));continue
            error={'url':url,'error':str(e)};ERRORS.append(error)
            if required:raise
            print('UNAVAILABLE',error,flush=True);return []
    error={'url':url,'error':'Retries exhausted'};ERRORS.append(error)
    if required:raise RuntimeError(error)
    return []

def jolpica(endpoint,field=None):
    offset=0;out=[]
    while True:
        j=get(f'https://api.jolpi.ca/ergast/f1/{endpoint}.json?limit=100&offset={offset}')['MRData']
        if 'StandingsTable' in j:return j['StandingsTable']['StandingsLists']
        races=j.get('RaceTable',{}).get('Races',[])
        if field:
            for race in races:
                for row in race.get(field,[]):out.append((int(race['season']),int(race['round']),row))
        else:out.extend(races)
        offset+=int(j['limit']);total=int(j['total'])
        if offset>=total:break
    return out

def seconds(v):
    if v in (None,''):return None
    try:
        if isinstance(v,(int,float)):return float(v)
        parts=str(v).split(':');value=0
        for p in parts:value=value*60+float(p)
        return value
    except (ValueError,TypeError):return None

def ms(v):
    value=seconds(v);return None if value is None else round(value*1000)

def stamp(v):
    if not v:return None
    try:return datetime.fromisoformat(v.replace('Z','+00:00')).timestamp()
    except (TypeError,ValueError):return None

def integer(v,default=None):
    try:return int(v)
    except (TypeError,ValueError):return default

def normalize_result(y,r,row,kind):
    d=row['Driver'];t=row['Constructor'];fast=row.get('FastestLap',{})
    drivers[d['driverId']]={'driver_id':d['driverId'],'code':d.get('code') or d['familyName'][:3].upper(),'name':d['givenName']+' '+d['familyName'],'first_name':d['givenName'],'last_name':d['familyName'],'nationality':d.get('nationality'),'date_of_birth':d.get('dateOfBirth')}
    teams[t['constructorId']]={'team_id':t['constructorId'],'name':t['name'],'nationality':t.get('nationality')}
    return {'id':f'{y}-{r}-{kind}-{d["driverId"]}','season':y,'round_number':r,'session_name':kind,'event_name':event_by_key[(y,r)]['event_name'],
      'driver_id':d['driverId'],'driver_code':drivers[d['driverId']]['code'],'full_name':drivers[d['driverId']]['name'],'driver_number':integer(row.get('number')),
      'team_id':t['constructorId'],'team_name':t['name'],'position':integer(row.get('position')),'position_text':row.get('positionText'),
      'points':float(row.get('points',0)),'grid_position':integer(row.get('grid')),'laps':integer(row.get('laps')),'status':row.get('status'),
      'classified_time_ms':integer(row.get('Time',{}).get('millis')),'time_label':row.get('Time',{}).get('time'),
      'fastest_lap_ms':ms(fast.get('Time',{}).get('time')),'fastest_lap_rank':integer(fast.get('rank')),'fastest_lap_number':integer(fast.get('lap')),
      'fastest_lap_avg_kph':seconds(fast.get('AverageSpeed',{}).get('speed')),
      'q1_ms':ms(row.get('Q1')),'q2_ms':ms(row.get('Q2')),'q3_ms':ms(row.get('Q3')),'source':'Jolpica'}

print('PITLANE / PUBLIC ARCHIVE IMPORT / 2023–2024',flush=True)
events=[];drivers={};teams={};results=[];official=[];pits=[];sessions=[]
for year in YEAR_SET:
    for r in jolpica(str(year)):
        circuit=r['Circuit'];loc=circuit['Location'];calendar=[]
        for key,label in [('FirstPractice','Practice 1'),('SecondPractice','Practice 2'),('ThirdPractice','Practice 3'),('Qualifying','Qualifying'),('Sprint','Sprint'),('SprintQualifying','Sprint Qualifying')]:
            if r.get(key):calendar.append({'name':label,'date':r[key].get('date'),'time':r[key].get('time')})
        calendar.append({'name':'Race','date':r['date'],'time':r.get('time')})
        events.append({'id':f'{year}-{r["round"]}','season':year,'round_number':int(r['round']),'event_name':r['raceName'],'circuit_id':circuit['circuitId'],
            'circuit_name':circuit['circuitName'],'country':loc.get('country'),'location':loc.get('locality'),'latitude':float(loc['lat']),'longitude':float(loc['long']),
            'date':r['date'],'time':r.get('time'),'calendar_sessions':calendar,'source':'Jolpica'})
event_by_key={(e['season'],e['round_number']):e for e in events}
for year in YEAR_SET:
    for ep,field,kind in [('results','Results','Race'),('qualifying','QualifyingResults','Qualifying'),('sprint','SprintResults','Sprint')]:
        for y,r,row in jolpica(f'{year}/{ep}',field):results.append(normalize_result(y,r,row,kind))
    for ep,field,kind in [('driverStandings','DriverStandings','driver'),('constructorStandings','ConstructorStandings','constructor')]:
        data=jolpica(f'{year}/{ep}')
        for block in data:
            for row in block.get(field,[]):official.append({'season':year,'round_number':int(block['round']),'kind':kind,'entity_id':row['Driver']['driverId'] if kind=='driver' else row['Constructor']['constructorId'],'position':int(row['position']),'points':float(row['points']),'wins':int(row['wins'])})
for event in events:
    y,r=event['season'],event['round_number']
    mapping={row['driver_id']:row for row in results if row['season']==y and row['round_number']==r and row['session_name']=='Race'}
    for _,_,raw in jolpica(f'{y}/{r}/pitstops','PitStops'):
        ref=mapping.get(raw['driverId']);duration=seconds(raw.get('duration'))
        if not ref:continue
        pits.append({'id':f'{y}-{r}-{raw["driverId"]}-{raw["stop"]}','season':y,'round_number':r,'event_name':event['event_name'],'session_name':'Race','driver_id':raw['driverId'],
          'driver_code':ref['driver_code'],'team_id':ref['team_id'],'team_name':ref['team_name'],'lap_number':int(raw['lap']),'stop':int(raw['stop']),
          'duration_s':duration,'source_local_time':raw.get('time'),'source':'Jolpica pit-lane duration; not stationary wheel-change time'})
print('CORE COMPLETE',len(events),'events',len(results),'classifications',len(pits),'pit records',flush=True)
catalog={'schema_version':1,'seasons':YEAR_SET,'events':events,'drivers':list(drivers.values()),'teams':list(teams.values()),'results':results,'official_standings':official,'pit_stops':pits,'sessions':sessions}
dump(DATA/'catalog.json',catalog)
for year in YEAR_SET:
    raw=get(f'https://api.openf1.org/v1/sessions?year={year}',required=False)
    for s in raw:
        kind=s.get('session_name')
        if kind not in ('Race','Qualifying') or s.get('is_cancelled'):continue
        candidates=[]
        for event in events:
            if event['season']!=year:continue
            expected=next((x['date'] for x in event['calendar_sessions'] if x['name']==kind),event['date'])
            gap=abs((datetime.fromisoformat(s['date_start'][:10])-datetime.fromisoformat(expected)).days)
            if gap<=2:candidates.append((gap,event))
        if not candidates:continue
        candidates.sort(key=lambda x:x[0]);event=candidates[0][1]
        sessions.append({**s,'id':f'{year}-{event["round_number"]}-{kind}','season':year,'round_number':event['round_number'],'event_name':event['event_name'],'session_date':s['date_start'],'source':'OpenF1'})
catalog['sessions']=sessions;dump(DATA/'catalog.json',catalog)
order=sorted(events,key=lambda e:(0 if (e['season'],e['round_number'])==(2024,15) else 1 if (e['season'],e['round_number'])==(2023,13) else 2,e['season'],e['round_number']))
coverage=[]
for event in order:
    y,r=event['season'],event['round_number'];session=next((s for s in sessions if s['season']==y and s['round_number']==r and s['session_name']=='Race'),None)
    if not session:coverage.append({'season':y,'round_number':r,'race_session':False});continue
    key=session['session_key'];print('RACE',y,r,event['event_name'],'SESSION',key,flush=True)
    raw={ep:get(f'https://api.openf1.org/v1/{ep}?session_key={key}',required=False) for ep in ['laps','stints','position','weather','race_control']}
    mapping={row['driver_number']:row for row in results if row['season']==y and row['round_number']==r and row['session_name']=='Qualifying'}
    mapping.update({row['driver_number']:row for row in results if row['season']==y and row['round_number']==r and row['session_name']=='Race'})
    starts=[stamp(l.get('date_start')) for l in raw['laps'] if stamp(l.get('date_start')) is not None]
    origin=stamp(session['date_start']);actual_race_start=min(starts) if starts else origin
    base={'season':y,'round_number':r,'event_name':event['event_name'],'session_name':'Race'}
    positions=[];by_driver=defaultdict(list)
    for p in raw['position']:
        ref=mapping.get(p['driver_number']);t=stamp(p.get('date'))
        if not ref or t is None:continue
        v={'driver_code':ref['driver_code'],'driver_number':p['driver_number'],'position':p['position'],'session_time_s':round(t-origin,3),'date':p['date']}
        positions.append(v);by_driver[p['driver_number']].append((t,p['position']))
    for n in by_driver:by_driver[n].sort()
    stints=[]
    for s in raw['stints']:
        ref=mapping.get(s['driver_number'])
        if not ref:continue
        stints.append({**base,'driver_code':ref['driver_code'],'team_id':ref['team_id'],'driver_number':s['driver_number'],'stint_number':s['stint_number'],
          'lap_start':s['lap_start'],'lap_end':s.get('lap_end'),'compound':s.get('compound') or 'UNKNOWN','tyre_age_at_start':s.get('tyre_age_at_start'),'source':'OpenF1'})
    pit_set={(p['driver_code'],p['lap_number']) for p in pits if p['season']==y and p['round_number']==r}
    laps=[]
    for l in raw['laps']:
        ref=mapping.get(l['driver_number'])
        if not ref or l.get('lap_number') is None:continue
        n=l['driver_number'];lap=l['lap_number'];start=stamp(l.get('date_start'));duration=seconds(l.get('lap_duration'));end=start+duration if start is not None and duration is not None else None
        stint=next((s for s in stints if s['driver_number']==n and s['lap_start'] is not None and s['lap_start']<=lap<=(s['lap_end'] or 999)),None)
        posrows=by_driver.get(n,[]);idx=bisect_right([p[0] for p in posrows],end)-1 if end is not None else -1
        pos=posrows[idx][1] if idx>=0 else None
        age=None if stint is None or stint['tyre_age_at_start'] is None else stint['tyre_age_at_start']+lap-stint['lap_start']+1
        laps.append({**base,'id':f'{y}-{r}-R-{ref["driver_code"]}-{lap}','driver_code':ref['driver_code'],'driver_number':n,'team_name':ref['team_name'],'team_id':ref['team_id'],
          'lap_number':lap,'lap_duration_ms':ms(duration),'duration_sector_1':ms(l.get('duration_sector_1')),'duration_sector_2':ms(l.get('duration_sector_2')),'duration_sector_3':ms(l.get('duration_sector_3')),
          'compound':stint['compound'] if stint else 'UNKNOWN','tyre_life':age,'stint':stint['stint_number'] if stint else None,
          'is_pit_in_lap':(ref['driver_code'],lap) in pit_set,'is_pit_out_lap':bool(l.get('is_pit_out_lap')),'track_status':None,'position':pos,
          'date_start':l.get('date_start'),'lap_start_s':None if start is None else round(start-origin,3),'lap_end_s':None if end is None else round(end-origin,3),
          'speed_trap_kph':l.get('st_speed'),'i1_speed_kph':l.get('i1_speed'),'i2_speed_kph':l.get('i2_speed'),'source':'OpenF1; positions as-of lap end, pit-in matched from Jolpica'})
    weather=[]
    for w in raw['weather']:
        t=stamp(w.get('date'))
        if t is None:continue
        weather.append({**base,'session_time_s':round(t-origin,3),'date':w['date'],**{k:w.get(k) for k in ['air_temperature','track_temperature','humidity','pressure','wind_speed','wind_direction','rainfall']},'source':'OpenF1'})
    controls=[]
    for i,c in enumerate(raw['race_control']):
        t=stamp(c.get('date'));ref=mapping.get(c.get('driver_number'))
        if t is None:continue
        controls.append({**base,'id':f'{y}-{r}-control-{i}','date':c['date'],'session_time_s':round(t-origin,3),'driver_code':ref['driver_code'] if ref else None,
          **{k:c.get(k) for k in ['category','flag','scope','sector','lap_number','message']},'source':'OpenF1'})
    payload={'schema_version':1,'event':event,'session':session,'race_start_epoch':actual_race_start,'clock_origin_epoch':origin,'laps':laps,'stints':stints,'positions':positions,'weather':weather,'race_control':controls}
    dump(DATA/f'race_{y}_{r:02d}.json',payload)
    coverage.append({'season':y,'round_number':r,'race_session':True,'laps':len(laps),'stints':len(stints),'positions':len(positions),'weather':len(weather),'race_control':len(controls)})
# Qualifying weather is small, useful, and part of the published hackathon schema.
qualifying_weather_counts={}
for s in [s for s in sessions if s['session_name']=='Qualifying']:
    y,r=s['season'],s['round_number'];origin=stamp(s['date_start']);weather=[]
    for w in get(f'https://api.openf1.org/v1/weather?session_key={s["session_key"]}',required=False):
        t=stamp(w.get('date'))
        if t is None:continue
        weather.append({'season':y,'round_number':r,'session_name':'Qualifying','event_name':s['event_name'],'session_time_s':round(t-origin,3),'date':w['date'],
          **{k:w.get(k) for k in ['air_temperature','track_temperature','humidity','pressure','wind_speed','wind_direction','rainfall']},'source':'OpenF1'})
    dump(DATA/f'weather_{y}_{r:02d}_qualifying.json',weather)
    qualifying_weather_counts[(y,r)]=len(weather)
for row in coverage:row['qualifying_weather']=qualifying_weather_counts.get((row['season'],row['round_number']),0)
manifest={'schema_version':1,'fetched_at':datetime.now(timezone.utc).isoformat(),'seasons':YEAR_SET,'synthetic_observations':0,'event_cluster_connected':False,
 'source':'Jolpica historical classifications + OpenF1 public session observations','events':len(events),'results':len(results),'pit_stops':len(pits),'sessions':len(sessions),
 'lap_rows':sum(x.get('laps',0) for x in coverage),'weather_rows':sum(x.get('weather',0) for x in coverage),'race_control_rows':sum(x.get('race_control',0) for x in coverage),
 'qualifying_weather_rows':sum(qualifying_weather_counts.values()),'total_weather_rows':sum(x.get('weather',0) for x in coverage)+sum(qualifying_weather_counts.values()),
 'position_rows':sum(x.get('positions',0) for x in coverage),'stint_rows':sum(x.get('stints',0) for x in coverage),
 'coverage':sorted(coverage,key=lambda c:(c['season'],c['round_number'])),'urls':sorted(set(URLS)),'errors':ERRORS,
 'notes':['Race/qualifying dimensions follow the published hackathon schema; public observations are not the event cluster.',
 'Sprint classifications supplement championship points; sprint qualifying is not loaded.',
 'Pit durations are total recorded pit-lane durations, not stationary wheel-change times.',
 'Positions in lap rows are the latest OpenF1 position at each driver lap end; the raw position change timeline is retained.',
 'Relative clocks use the OpenF1 session date_start; pre-session observations can have negative times.',
 'weather_rows is Race only; total_weather_rows includes Qualifying.',
 'Unknown stint boundaries and unavailable lap/sector durations remain null.',
 'Original 3D/high-frequency telemetry and ML experiments remain the separate 2024 Dutch GP snapshot.',
 'No historical observations, proprietary scores, photos, liveries, or code were copied from formula1dashboard.com.'],
 'sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(DATA.glob('*.json')) if p.name!='manifest.json'}}
dump(DATA/'manifest.json',manifest)
print('COMPLETE',json.dumps({k:manifest[k] for k in ['events','results','pit_stops','sessions','lap_rows','weather_rows','race_control_rows','errors']}),flush=True)
