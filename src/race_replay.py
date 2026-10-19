"""Read-only public, shared-clock race replay. Independent of dashboard cloud mode."""
from pathlib import Path
from functools import lru_cache
import hashlib,json
from fastapi import APIRouter,HTTPException
from fastapi.responses import FileResponse
ROOT=Path(__file__).resolve().parents[1];REPLAY=ROOT/'data/replay'
router=APIRouter(prefix='/api/replay',tags=['Public multi-car race replay'])

def read(path):return json.loads(path.read_text())
@lru_cache(maxsize=1)
def manifest():
    p=REPLAY/'manifest.json'
    if not p.exists():raise HTTPException(503,'The synchronized position archive is not installed. Ghost comparison still works; no race positions are invented.')
    return read(p)

@router.get('/race')
def race():
    m=manifest();raw=read(ROOT/'data/dashboard/race_2024_15.json');cat=read(ROOT/'data/dashboard/catalog.json')
    fields=['id','driver_code','lap_number','lap_start_s','lap_end_s','lap_duration_ms','compound','tyre_life','is_pit_in_lap','is_pit_out_lap']
    results=[r for r in cat['results'] if (r['season'],r['round_number'],r['session_name'])==(2024,15,'Race')]
    return {'manifest':m,'results':results,'laps':[{k:l.get(k) for k in fields} for l in raw['laps']],'positions':raw['positions'],'stints':raw['stints'],'race_control':raw['race_control'],
            'source_mode':'public-synchronized','scope_note':'Same-time recorded OpenF1 positions for the 2024 Dutch GP. Not the four independent ghost laps, not live timing, and not a cloud connection claim.'}

@router.get('/driver/{code}')
def driver(code:str):
    # Resolve filenames from the curated manifest only; no arbitrary path access.
    m=manifest();row=next((r for r in m['drivers'] if r['driver_code']==code),None)
    if row is None:raise HTTPException(404,'This driver has no installed position replay. Missing coverage is not fabricated.')
    p=REPLAY/row['file']
    if not p.is_file():raise HTTPException(503,'The selected position snapshot is missing from the installation.')
    return FileResponse(p,media_type='application/json',headers={'X-Pitlane-Source':'public-recorded-session','Cache-Control':'public, max-age=3600'})
