"""OFFLINE integration QA server. Never a production cloud connector.

Run only for tests: uvicorn tests/cloud_fixture_app:app via --app-dir tests.
Fixture credentials and modified values are intentionally non-secret test data.
"""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from app import app
from src import connections
from src.settings import Settings
from cloud_fixtures import FixtureHops
from fastapi.responses import JSONResponse
from fastapi import Request,HTTPException
sdk=FixtureHops()
settings=Settings.from_mapping({'HOPSWORKS_HOST':'fixture.invalid','HOPSWORKS_PROJECT':'OFFLINE_FIXTURE','HOPSWORKS_API_KEY':'OFFLINE_FIXTURE_KEY','PITLANE_ADMIN_TOKEN':'operator_test_token_only_32_characters','PITLANE_FEATURE_PREFIX':'pitlane_testteam','PITLANE_ALLOW_FEATURE_WRITES':'true'})
connections.RUNTIME=connections.Runtime(settings,client=sdk)

@app.middleware('http')
async def mark_offline_fixture(request,call_next):
    response=await call_next(request)
    if request.url.path=='/api/connections/status' and response.status_code==200:
        body=b''.join([part async for part in response.body_iterator]);data=json.loads(body);data['offline_fixture']=True
        return JSONResponse(data,headers={'Cache-Control':'no-store'})
    return response

@app.post('/_qa/reset')
def reset_fixture(request:Request):
    global sdk
    if request.headers.get('X-Pitlane-Test-Token')!='offline-fixture-only':raise HTTPException(403)
    old=connections.RUNTIME
    if old.job and old.job['state'] in {'queued','running'}:raise HTTPException(409)
    old.pool.shutdown(wait=True)
    sdk=FixtureHops()
    connections.RUNTIME=connections.Runtime(settings,client=sdk)
    return {'reset':True,'offline_fixture':True}
# The production static-file mount is terminal; put the QA-only reset before it.
app.router.routes.insert(0,app.router.routes.pop())
