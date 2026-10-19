from pathlib import Path
from threading import RLock
from typing import Literal
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from src.engine import LabEngine, DATA, ROOT, DRIVERS

app=FastAPI(title='Pitlane Lab',version='2.2.0',description='Real historical observations; transparent local feature/search backends.')
engine=LabEngine();lock=RLock()
Driver=Literal['NOR','VER','LEC','PIA']

@app.get('/api/health')
def health():
    from src.connections import runtime
    r=runtime();return {'status':'configuration_error' if r.settings_error else 'ok','cloud_connected':r.status()['cloud_connected'],'synthetic_observations':0}

@app.get('/api/bootstrap')
def bootstrap():
    with lock:return engine.bootstrap()

@app.get('/api/ghost')
def ghost(a:Driver='NOR',b:Driver='VER'):
    if a==b:raise HTTPException(422,'Select two different drivers')
    with lock:return engine.ghost_view(a,b)

@app.get('/api/ghost/field')
def ghost_field():
    with lock:
        return {'drivers':list(engine.ghosts.values()),'reference_driver':'NOR','scope':'Four independent recorded laps, aligned at lap start. Relative deltas compare equal normalized lap distance, not actual race positions.','data_source':'Original public Dutch GP snapshot; replay channels read from persisted feature tables.'}

@app.get('/api/strategy')
def strategy(driver:Driver='NOR',pit_lap:int|None=Query(None,ge=10,le=60),compound:Literal['HARD','MEDIUM','SOFT']='HARD',degradation:float=Query(1.,ge=.5,le=2.),pit_loss:float|None=Query(None,ge=12,le=40)):
    with lock:return engine.strategy(driver,pit_lap,compound,degradation,pit_loss)

@app.get('/api/pace')
def pace(driver:str='NOR',method:Literal['model','baseline']='model',threshold:float=Query(0.,ge=0,le=10)):
    if driver not in set(engine.laps.driver_code):raise HTTPException(422,'Unknown driver')
    with lock:return engine.pace_view(driver,method,threshold)

@app.get('/api/dna/challenge')
def challenge(index:int=Query(0,ge=0,le=100000)):
    with lock:return engine.challenge(index)

class Guess(BaseModel):
    id:str
    guess:Driver|None=None

@app.post('/api/dna/reveal')
def reveal(body:Guess):
    try:
        with lock:return engine.reveal(body.id,body.guess)
    except ValueError as e:raise HTTPException(422,str(e))

@app.get('/api/pipeline')
def pipeline():
    with lock:return engine.pipeline_status()

@app.post('/api/pipeline')
def rerun():
    with lock:return engine.rebuild()

@app.get('/api/features/{group}.csv')
def features(group:str):
    try:
        with lock:csv=engine.store.read(group).to_csv(index=False)
    except ValueError:raise HTTPException(404,'Unknown feature group')
    return Response(csv,media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{group}.csv"'})

@app.get('/api/manifest')
def manifest():return engine.manifest

@app.get('/api/download/project')
def project_download():
    path=ROOT.parent/'pitlane-lab.zip'
    if not path.exists():
        from src.archive import create_archive
        with lock:
            if not path.exists():create_archive(ROOT,path)
    return FileResponse(path,media_type='application/zip',filename='pitlane-lab.zip')

@app.get('/api/download/brief')
def brief_download():
    p=ROOT/'DEMO-GUIDE.md'
    if not p.exists():raise HTTPException(503,'Guide is being prepared')
    return FileResponse(p,media_type='text/markdown',filename='PITLANE-DEMO-GUIDE.md')

@app.middleware('http')
async def headers(request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    if request.url.path.startswith('/api/'):response.headers['Cache-Control']='no-store'
    return response

from src.dashboard_api import router as dashboard_router
app.include_router(dashboard_router)

from src.connections import router as connections_router,runtime,authorized
from src.settings import ConnectionProblem
from fastapi.responses import JSONResponse
app.include_router(connections_router)
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler

@app.exception_handler(RequestValidationError)
async def safe_validation(request,exc):
    if request.url.path.startswith('/api/connections/'):
        return JSONResponse({'detail':'Invalid connection request. Check field names, selection bounds and required confirmations.'},status_code=422)
    return await request_validation_exception_handler(request,exc)

@app.exception_handler(ConnectionProblem)
async def connection_problem(request,exc):
    return JSONResponse({'detail':exc.message,'code':exc.code},status_code=exc.status)

@app.middleware('http')
async def protect_cloud_data(request,call_next):
    if request.url.path.startswith('/api/dashboard/') and runtime().private and not authorized(request):
        return JSONResponse({'detail':'Cloud dashboard data is operator-protected. Open Connections and unlock with your server operator token.'},status_code=401,headers={'Cache-Control':'no-store'})
    return await call_next(request)

from src.race_replay import router as replay_router
app.include_router(replay_router)

app.mount('/',StaticFiles(directory=ROOT/'web',html=True,check_dir=False),name='website')
