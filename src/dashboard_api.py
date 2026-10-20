"""Read-only historical dashboard endpoints and schema-aligned exports, over Hopsworks feature groups."""
from threading import RLock
from typing import Literal
from fastapi import APIRouter,HTTPException,Query
from fastapi.responses import Response,JSONResponse
from .dashboard import DashboardEngine

router=APIRouter(prefix='/api/dashboard',tags=['Historical dashboard'])
INIT_LOCK=RLock();INSTANCE=None
Kind=Literal['Race','Qualifying','Sprint']

def get_dashboard():
    global INSTANCE
    with INIT_LOCK:
        if INSTANCE is None:
            from .hopsdata import archive
            from .appdb import store
            INSTANCE=DashboardEngine(archive(),store())
        return INSTANCE

def call(method,*args):
    try:return getattr(get_dashboard(),method)(*args)
    except ValueError as e:raise HTTPException(422,str(e))

@router.get('/timing')
def timing(season:int=Query(2024,ge=2023,le=2024),round:int=Query(15,ge=1,le=24)):
    return call('race_view',season,round)

@router.get('/catalog')
def catalog():return get_dashboard().catalog_view()

@router.get('/season')
def season(season:int=Query(2024,ge=2023,le=2024),round:int=Query(15,ge=1,le=24)):
    return call('season_view',season,round)

@router.get('/race')
def race(season:int=Query(2024,ge=2023,le=2024),round:int=Query(15,ge=1,le=24),clean:bool=True,cutoff:float=Query(1.07,ge=1.,le=1.5,allow_inf_nan=False)):
    return call('race_view',season,round,clean,cutoff)

@router.get('/driver')
def driver(season:int=Query(2024,ge=2023,le=2024),round:int=Query(15,ge=1,le=24),driver:str='norris'):
    return call('driver_view',season,round,driver)

@router.get('/compare')
def compare(season:int=Query(2024,ge=2023,le=2024),round:int=Query(15,ge=1,le=24),a:str='norris',b:str='piastri'):
    return call('compare',season,round,a,b)

@router.get('/pits')
def pits(season:int=Query(2024,ge=2023,le=2024),round:int=Query(15,ge=1,le=24)):
    return call('pit_view',season,round)

@router.get('/tracks')
def tracks(season:int=Query(2024,ge=2023,le=2024)):return call('tracks',season)

@router.get('/weather')
def weather(season:int=Query(2024,ge=2023,le=2024),round:int=Query(15,ge=1,le=24),session:Literal['Race','Qualifying']='Race'):
    return call('weather_view',season,round,session)

@router.get('/coverage')
def coverage():return get_dashboard().coverage_view()

@router.get('/export/{kind}.csv')
def export(kind:Literal['results','laps','weather','pits','stints','race-control','features','sessions','driver-stats','constructor-stats'],season:int=Query(2024,ge=2023,le=2024),round:int=Query(15,ge=1,le=24),session:Kind='Race'):
    value=call('export',kind,season,round,session)
    filename=f'pitlane-{season}-through-r{round}-{kind}.csv' if kind.endswith('-stats') else f'pitlane-{season}-r{round}-{session.lower()}-{kind}.csv'
    return Response(value,media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="{filename}"'})

def local_source_rows(db,kind,season,round,session):
    """Public-archive rows in the event schema; also what load-source writes to Hopsworks."""
    event=db.event(season,round)
    base={'season':season,'round_number':round,'event_name':event['event_name'],'session_name':session}
    if kind=='sessions':
        return [{**base,'country':event['country'],'location':event['location'],'session_date':s['session_date']} for s in db.sessions if s['season']==season and s['round_number']==round and s['session_name']==session]
    if kind=='results':
        fields=['driver_number','driver_code','full_name','team_name','position','points','grid_position','status','fastest_lap_ms']
        return [{**base,**{k:r.get(k) for k in fields}} for r in db.classifications(season,round,session)]
    if kind=='laps':
        fields=['driver_code','team_name','lap_number','lap_duration_ms','duration_sector_1','duration_sector_2','duration_sector_3','compound','tyre_life','is_pit_out_lap','is_pit_in_lap','track_status','position']
        return [{**base,**{k:r.get(k) for k in fields}} for r in db.race_raw(season,round)['laps']] if session=='Race' else []
    if kind=='weather':
        fields=['session_time_s','air_temperature','track_temperature','humidity','pressure','wind_speed','wind_direction','rainfall']
        return [{**base,**{k:r.get(k) for k in fields},'rainfall':None if r.get('rainfall') is None else bool(r['rainfall'])} for r in db.weather_view(season,round,session)['rows']]
    rows=[]
    if session=='Race':
        from .engine import lab
        try:engine=lab(season,round)
        except ValueError:return rows
        laps=db.race_raw(season,round)['laps']
        for code,g in engine.ghosts.items():
            lap=next((l for l in laps if l['driver_code']==code and l['lap_number']==g['lap_number']),None)
            if lap is None or lap['lap_start_s'] is None:continue
            tr=g['trace']
            for i,t in enumerate(tr['time']):
                rows.append({**base,'driver_code':code,'team_name':lap['team_name'],'lap_number':g['lap_number'],'session_time_s':round_float(lap['lap_start_s']+t),
                    'speed':int(tr['speed'][i]+.5),'rpm':int(tr['rpm'][i]+.5),'throttle':max(0,min(100,int(tr['throttle'][i]+.5))),'brake':tr['brake'][i]>.5,'n_gear':int(tr['gear'][i]+.5),
                    'drs':None,'x':tr['x'][i],'y':tr['y'][i],'z':None,'is_interpolated':True})
    return rows

@router.get('/schema/{index}.json')
def schema_export(index:Literal['f1-sessions','f1-results','f1-laps','f1-weather','f1-telemetry'],season:int=Query(2024,ge=2023,le=2024),round:int=Query(15,ge=1,le=24),session:Literal['Race','Qualifying']='Race'):
    try:rows=local_source_rows(get_dashboard(),index.removeprefix('f1-'),season,round,session)
    except ValueError as e:raise HTTPException(422,str(e))
    payload={'index':index,'records':rows,'record_count':len(rows),'provenance':'Hopsworks F1 feature groups read through the Hopsworks Query Service.',
        'notes':['Unknown fields stay null. Sector/lap durations are milliseconds. Relative time uses the session start date.',
            'Race lap position is an as-of join of f1_track_positions at each lap end.',
            'Qualifying lap samples are not exported; qualifying results/weather are available.',
            'Telemetry export is the lab ghost laps for this race (fastest green-flag lap per lab driver), interpolated to 361 samples, not the full f1_car_telemetry table.']}
    return JSONResponse(payload,headers={'Content-Disposition':f'attachment; filename="{index}-{season}-r{round}-{session.lower()}.json"'})

def round_float(value):return float(f'{value:.6f}')
