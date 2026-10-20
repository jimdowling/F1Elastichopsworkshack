"""PITLANE: F1 2023–2024 dashboard and idea lab on Hopsworks (FastAPI JSON API under /api + prebuilt React UI from web/).

Data: the F1 feature groups (F1_FEATURE_STORE, else the project's own store, else hopsworks_default_featurestore), read with
the Hopsworks Python client (fg.select(...).filter(...).read()), which is served by the Hopsworks Query
Service. App state (pace features, per-race lab feature tables, derived replay/telemetry payloads) lives
in RonDB tables app_pitlane__* (registered with app.register_table) in the project database. No bundled data and no SQLite.

Runs as a Hopsworks custom app: binds 0.0.0.0:$APP_PORT, serves /health for the readiness probe, and every
UI URL is relative so it works under the proxy mount /hopsworks-api/pythonapp/<project>/<app>/.
The four experiments (Ghost Lap, Pitwall Sandbox, Pace Detective, Driver DNA) and the multi-car replay
are fitted per race: every lab endpoint takes season and round.
"""
import logging, os, threading
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
Season = Query(2024, ge=2023, le=2024)
Round = Query(15, ge=1, le=24)


def warm():
    """Load the archive in the background so the first page view is fast; /health answers meanwhile."""
    try:
        from src.dashboard_api import get_dashboard
        get_dashboard()
    except Exception:
        logging.getLogger('pitlane').exception('Archive warm-up failed; it will be retried on the next request')


@asynccontextmanager
async def lifespan(_):
    threading.Thread(target=warm, daemon=True).start()
    yield


app = FastAPI(title='Pitlane on Hopsworks', version='3.0.0', description='F1 feature groups via the Hopsworks Query Service; app state in RonDB.', lifespan=lifespan)


def lab(season, rnd):
    from src.engine import lab as get_lab
    try: return get_lab(season, rnd)
    except ValueError as e: raise HTTPException(422, str(e))


def run(fn, *args):
    try: return fn(*args)
    except ValueError as e: raise HTTPException(422, str(e))


@app.get('/health')
def readiness(): return {'status': 'ok'}


@app.get('/api/health')
def health():
    from src import hopsdata
    from src.appdb import store
    return {'status': 'ok', 'archive_loaded': hopsdata.ARCHIVE is not None, 'feature_store': hopsdata.FEATURE_STORE, 'app_store': store().name, 'synthetic_observations': 0}


@app.get('/api/bootstrap')
def bootstrap(season: int = Season, round: int = Round): return lab(season, round).bootstrap()


@app.get('/api/ghost')
def ghost(season: int = Season, round: int = Round, a: str | None = None, b: str | None = None): return run(lab(season, round).ghost_view, a, b)


@app.get('/api/ghost/field')
def ghost_field(season: int = Season, round: int = Round):
    e = lab(season, round)
    return {'drivers': [e.ghosts[d] for d in e.drivers], 'reference_driver': e.drivers[0], 'season': season, 'round': round, 'event_name': e.manifest['dataset'],
            'scope': 'Independent recorded laps, aligned at lap start. Relative deltas compare equal normalized lap distance, not actual race positions.',
            'data_source': 'f1_car_telemetry + f1_car_location; replay channels read from the RonDB feature table.'}


@app.get('/api/strategy')
def strategy(season: int = Season, round: int = Round, driver: str | None = None, pit_lap: int | None = Query(None, ge=2, le=90), compound: Literal['HARD', 'MEDIUM', 'SOFT'] = 'HARD',
             degradation: float = Query(1., ge=.5, le=2.), pit_loss: float | None = Query(None, ge=12, le=40)):
    return run(lab(season, round).strategy, driver, pit_lap, compound, degradation, pit_loss)


@app.get('/api/pace')
def pace(season: int = Season, round: int = Round, driver: str | None = None, method: Literal['model', 'baseline'] = 'model', threshold: float = Query(0., ge=0, le=10)):
    return run(lab(season, round).pace_view, driver, method, threshold)


@app.get('/api/dna/challenge')
def challenge(season: int = Season, round: int = Round, index: int = Query(0, ge=0, le=100000)): return lab(season, round).challenge(index)


class Guess(BaseModel):
    id: str
    guess: str | None = None


@app.post('/api/dna/reveal')
def reveal(body: Guess, season: int = Season, round: int = Round): return run(lab(season, round).reveal, body.id, body.guess)


@app.get('/api/pipeline')
def pipeline(season: int = Season, round: int = Round): return lab(season, round).pipeline_status()


@app.post('/api/pipeline')
def rerun(season: int = Season, round: int = Round): return run(lab(season, round).retrain)


@app.get('/api/features/{group}.csv')
def features(group: str, season: int = Season, round: int = Round):
    try: csv = lab(season, round).store.read(f'{season}-{round:02d}', group).to_csv(index=False)
    except ValueError: raise HTTPException(404, 'Unknown feature group')
    return Response(csv, media_type='text/csv', headers={'Content-Disposition': f'attachment; filename="{group}-{season}-r{round}.csv"'})


@app.get('/api/manifest')
def manifest(season: int = Season, round: int = Round): return lab(season, round).manifest


@app.get('/api/download/project')
def project_download():
    import tempfile
    path = Path(tempfile.gettempdir()) / 'pitlane-lab.zip'
    if not path.exists():
        from src.archive import create_archive
        create_archive(ROOT, path)
    return FileResponse(path, media_type='application/zip', filename='pitlane-lab.zip')


@app.get('/api/download/brief')
def brief_download():
    p = ROOT / 'DEMO-GUIDE.md'
    if not p.exists(): raise HTTPException(503, 'Guide is not available')
    return FileResponse(p, media_type='text/markdown', filename='PITLANE-DEMO-GUIDE.md')


@app.middleware('http')
async def headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    if request.url.path.startswith('/api/') and 'Cache-Control' not in response.headers: response.headers['Cache-Control'] = 'no-store'
    return response


from src.dashboard_api import router as dashboard_router
from src.race_replay import router as replay_router
app.include_router(dashboard_router)
app.include_router(replay_router)
app.mount('/', StaticFiles(directory=ROOT / 'web', html=True, check_dir=False), name='website')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('APP_PORT', '8000')), proxy_headers=True, forwarded_allow_ips='*')
