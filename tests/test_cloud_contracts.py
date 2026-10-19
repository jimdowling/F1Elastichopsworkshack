"""Offline contract checks. These do NOT constitute live cloud validation."""
import sys
from pathlib import Path
import pandas as pd
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from cloud_fixtures import FixtureHops
from src.cloud import validate_prefix,typed,source_frames,HopsworksPublisher
from src.settings import Settings
from src.remote import FIELDS,HopsSource

SETTINGS={'HOPSWORKS_HOST':'fixture.invalid','HOPSWORKS_PROJECT':'fixture_project','HOPSWORKS_API_KEY':'HOPS_SECRET'}

@pytest.mark.parametrize('bad',['f1_laps','../source','pitlane_X','pitlane_*','my-team'])
def test_no_unsafe_destination_prefix(bad):
    with pytest.raises(ValueError):validate_prefix(bad)

def test_typed_source_frame_has_stable_ids_and_nullable_dtypes():
    rows=[{'season':2024,'round_number':15,'event_name':'Dutch Grand Prix','session_name':'Race','driver_code':'NOR','lap_number':1,'lap_duration_ms':None,'is_pit_in_lap':None,'is_pit_out_lap':True}]
    f=typed('laps',rows)
    assert list(f.columns[:5])==['id','season','round_number','event_name','session_name'] and set(FIELDS['laps'])<=set(f.columns)
    assert str(f.lap_duration_ms.dtype)=='Int64' and str(f.is_pit_in_lap.dtype)=='boolean' and f.id[0]==typed('laps',rows).id[0]
    with pytest.raises(ValueError,match='Duplicate'):typed('laps',rows*2)

def test_hopsworks_bridge_with_explicit_fake_sdk():
    sdk=FixtureHops();p=HopsworksPublisher(Settings.from_mapping(SETTINGS),client=sdk)
    report=p.publish('pitlane_demo',{'ghost_features':pd.DataFrame([{'id':'one','speed':123.}])})
    assert report[0]['id_read_back'] is True and sdk.last_login['engine']=='python'

def test_loaded_public_archive_reads_back_through_source_reader(tmp_path):
    from src.dashboard import DashboardEngine
    db=DashboardEngine(runtime_path=tmp_path/'load.sqlite')
    frames=source_frames(db,seasons=(2024,))
    sdk=FixtureHops();sdk.groups={};settings=Settings.from_mapping(SETTINGS)
    report=HopsworksPublisher(settings,client=sdk).load_sources(frames)
    assert {r['feature_group'] for r in report}=={'f1_'+k for k in FIELDS} and all(r['id_read_back'] for r in report)
    # Turn the written frames into fixture source groups and read them back as the dashboard would.
    for (name,version),g in list(sdk.groups.items()):
        kind=name.removeprefix('f1_');g.source=True;g.kind=kind
        g.rows=[{k:(None if pd.isna(v) else v) for k,v in r.items()} for r in g.frame.astype(object).to_dict('records')]
    laps=HopsSource(settings,sdk).read('laps',{'season':2024,'round_number':15,'session_name':'Race'})
    assert len(laps)==len([r for r in frames['laps'].to_dict('records') if r['round_number']==15])
    db.db.close()
