"""Import real shared-clock Dutch GP position/telemetry for the multi-car replay.

Run explicitly; this is not an application startup task. Resumable, paced HTTP
requests, raw source digests, compact columnar snapshots. No invented samples:
select one actual location record per 0.5 s bin and car record per 1 s bin.
Interpolation/gap handling is a disclosed browser visualization operation.
"""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,math,time,sys
import requests
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'data/replay';CACHE=ROOT/'.cache/race-replay-sources'
OUT.mkdir(parents=True,exist_ok=True);CACHE.mkdir(parents=True,exist_ok=True)
SESSION=9582

def read(p):return json.loads(p.read_text())
def write(p,value):
    text=json.dumps(value,separators=(',',':'),allow_nan=False);tmp=p.with_suffix('.tmp');tmp.write_text(text);tmp.replace(p)
def epoch(value):return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
def iso(value):return datetime.fromtimestamp(value,timezone.utc).isoformat()
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

race=read(ROOT/'data/dashboard/race_2024_15.json');cat=read(ROOT/'data/dashboard/catalog.json');origin=race['clock_origin_epoch']
results=sorted([r for r in cat['results'] if (r['season'],r['round_number'],r['session_name'])==(2024,15,'Race')],key=lambda r:r['position'])
start=max(0,race['race_start_epoch']-origin-3);end=max(l['lap_end_s'] for l in race['laps'] if l['lap_end_s'] is not None)+3
client=requests.Session();last=0;sources=[]

def fetch(kind,number):
    global last
    params={'session_key':SESSION,'driver_number':number,'date>':iso(origin+start),'date<':iso(origin+end)}
    request=requests.Request('GET','https://api.openf1.org/v1/'+kind,params=params).prepare();url=request.url
    path=CACHE/(hashlib.sha256(url.encode()).hexdigest()+'.json')
    if not path.exists():
        for attempt in range(4):
            time.sleep(max(0,2.15-(time.monotonic()-last)));last=time.monotonic()
            try:
                r=client.get(url,timeout=(10,120));r.raise_for_status();rows=r.json()
                if not isinstance(rows,list):raise ValueError('Expected an observation array')
                write(path,rows);break
            except (requests.RequestException,ValueError):
                if attempt==3:raise
                time.sleep(3*(attempt+1))
    rows=read(path)
    if any(r.get('session_key')!=SESSION or r.get('driver_number')!=number for r in rows):raise ValueError('Source returned records outside the requested session/driver scope')
    sources.append({'url':url,'kind':kind,'driver_number':number,'raw_rows':len(rows),'sha256':digest(path)})
    return rows

def compact(rows,fields,bin_seconds):
    bins={};invalid=0
    for r in rows:
        try:
            t=epoch(r['date'])-origin
            if not start<=t<=end or any(r.get(k) is not None and (not isinstance(r[k],(int,float)) or not math.isfinite(r[k])) for k in fields):raise ValueError()
        except (KeyError,TypeError,ValueError):invalid+=1;continue
        # Missing XY cannot be placed; other channel nulls remain null.
        if 'x' in fields and (r.get('x') is None or r.get('y') is None):invalid+=1;continue
        b=math.floor(t/bin_seconds);error=abs(t-(b+.5)*bin_seconds)
        if b not in bins or error<bins[b][0]:bins[b]=(error,t,r)
    selected=sorted((t,r) for _,t,r in bins.values());out={'time':[round(t,6) for t,r in selected]}
    for k in fields:out[k]=[r.get(k) for t,r in selected]
    return out,invalid

meta={'schema_version':1,'session_key':SESSION,'season':2024,'round_number':15,'session_name':'Race','event_name':'Dutch Grand Prix','circuit':'Zandvoort',
      'clock_origin_epoch':origin,'clock_origin_utc':iso(origin),'start_s':round(start,6),'end_s':round(end,6),'fetched_at':iso(time.time()),'drivers':[],'synthetic_observations':0,
      'source':'OpenF1 public historical location + car_data; public race timing/ranks/stints from the bundled archive',
      'cadence':{'location_bin_s':.5,'car_data_bin_s':1},'max_interpolation_gap_s':2.5,
      'notes':['All cars use the same provider session clock; this is not an alignment of independent fastest laps.',
               'Each retained sample is an actual source record with its actual timestamp, not a synthetic uniform sample.',
               'Short intervals between samples are interpolated for display. Missing/stale/outlier intervals are hidden, not filled with invented motion.',
               'Provider XY drives placement. Elevation is flattened; road width, scenery, cars, steering and audio remain illustrative.',
               'Out-of-range telemetry values remain in the source archive but are unavailable for displayed instruments/interpolation; invalid throttle is not silently clamped into a claimed measurement.',
               'Position ranks are last recorded as of the shared time. Physical XY separation is derived and is not an official race interval.'],
      'errors':[]}
for r in results:
    code=r['driver_code'];number=r['driver_number'];print(f'Fetching {code} / {number}',flush=True)
    try:
        raw_xy=fetch('location',number);raw_car=fetch('car_data',number)
        location,bad_xy=compact(raw_xy,['x','y','z'],.5);car,bad_car=compact(raw_car,['speed','rpm','throttle','brake','n_gear','drs'],1)
        payload={'driver_code':code,'driver_number':number,'location':location,'car_data':car}
        write(OUT/f'{code}.json',payload)
        row={'driver_code':code,'driver_number':number,'full_name':r['full_name'],'team_name':r['team_name'],'team_id':r['team_id'],
             'location_samples':len(location['time']),'car_samples':len(car['time']),'first_s':location['time'][0] if location['time'] else None,'last_s':location['time'][-1] if location['time'] else None,
             'invalid_location_rows':bad_xy,'invalid_car_rows':bad_car,'out_of_range_channels':{k:sum(v is not None and not lo<=v<=hi for v in car[k]) for k,(lo,hi) in {'speed':(0,400),'rpm':(0,15000),'throttle':(0,100),'brake':(0,100),'n_gear':(0,8)}.items()},'max_location_gap_s':round(max([b-a for a,b in zip(location['time'],location['time'][1:])]+[0]),6),'file':f'{code}.json'}
        meta['drivers'].append(row);print(f"  {row['location_samples']} XY / {row['car_samples']} telemetry; max gap {row['max_location_gap_s']}s",flush=True)
    except Exception as e:
        meta['errors'].append({'driver_code':code,'error':str(e)[:350]});print(f'  ERROR {code}: {str(e)[:180]}',flush=True)
meta['sources']=sources;meta['sha256']={r['file']:digest(OUT/r['file']) for r in meta['drivers']};meta['driver_count']=len(meta['drivers']);meta['location_samples']=sum(r['location_samples'] for r in meta['drivers']);meta['car_samples']=sum(r['car_samples'] for r in meta['drivers'])
write(OUT/'manifest.json',meta)
print(json.dumps({k:meta[k] for k in ['driver_count','location_samples','car_samples','start_s','end_s','errors']},indent=2),flush=True)
if meta['errors']:sys.exit(1)
