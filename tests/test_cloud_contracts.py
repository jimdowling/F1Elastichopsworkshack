"""Offline contract checks. These do NOT constitute live cloud validation."""
import json
import pandas as pd
import pytest
from src.cloud import validate_prefix,elastic_name,mapping,bulk_payload,frame_records,HopsworksPublisher

@pytest.mark.parametrize('bad',['f1-laps','../source','pitlane_X','pitlane_*','my-team'])
def test_no_unsafe_destination_prefix(bad):
    with pytest.raises(ValueError):validate_prefix(bad)

def test_elastic_payload_and_mapping():
    f=pd.DataFrame([{'id':'lap-1','speed':284.,'driver':'NOR','sample':1}])
    index=elastic_name('pitlane_demo','ghost_features')
    assert index=='pitlane-demo-ghost-features'
    assert mapping(f)['mappings']['properties']['driver']['type']=='keyword'
    lines=bulk_payload(index,frame_records(f)).strip().splitlines()
    assert json.loads(lines[0])['index']['_id']=='lap-1'
    assert json.loads(lines[1])['speed']==284.

def test_hopsworks_bridge_with_explicit_fake_sdk():
    class Group:
        def insert(self,df,write_options):self.df=df.copy()
        def read(self):return self.df.copy()
    class Store:
        def get_or_create_feature_group(self,**kwargs):
            assert kwargs['primary_key']==['id'] and kwargs['online_enabled'] is False
            return Group()
    class Project:
        def get_feature_store(self):return Store()
    class FakeSDK:
        def login(self,**kwargs):return Project()
    p=HopsworksPublisher('fake-host','fake-project','fake-key',client=FakeSDK())
    report=p.publish('pitlane_demo',{'ghost_features':pd.DataFrame([{'id':'one','speed':123.}])})
    assert report[0]['id_read_back'] is True
