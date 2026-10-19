"""Optional publishing bridges, NOT the active web application's backends.
Live connection validation requires user-supplied accounts and has not been run.
No delete operations. Publishing must be explicitly requested by the CLI.
"""
import json, re, os
from pathlib import Path
from urllib.parse import urlparse
import pandas as pd
import requests
from .engine import safe

GROUPS=('ghost_features','pace_features','dna_features','strategy_features')

def validate_prefix(prefix):
    if not re.fullmatch(r'pitlane_[a-z][a-z0-9_]{2,30}',prefix):
        raise ValueError('Use an isolated prefix such as pitlane_yourteam; never an organizer source index.')
    return prefix

def elastic_name(prefix,group):return validate_prefix(prefix).replace('_','-')+'-'+group.replace('_','-')

def frame_records(frame):
    return [safe(x) for x in frame.where(pd.notna(frame),None).to_dict(orient='records')]

def mapping(frame):
    fields={}
    for col in frame.columns:
        dtype=frame[col].dtype
        typ='boolean' if pd.api.types.is_bool_dtype(dtype) else 'long' if pd.api.types.is_integer_dtype(dtype) else 'double' if pd.api.types.is_numeric_dtype(dtype) else 'keyword'
        fields[col]={'type':typ}
    return {'mappings':{'properties':fields}}

def bulk_payload(index,records):
    lines=[]
    for r in records:
        lines.extend([json.dumps({'index':{'_index':index,'_id':str(r['id'])}}),json.dumps(r,allow_nan=False)])
    return '\n'.join(lines)+'\n'

class ElasticPublisher:
    def __init__(self,url,key,session=None):
        u=urlparse(url)
        if u.scheme!='https' and not (u.scheme=='http' and u.hostname in ('localhost','127.0.0.1')):
            raise ValueError('Elastic endpoint must use HTTPS, except local development.')
        if not key:raise ValueError('An API key for your writable destination is required.')
        self.url=url.rstrip('/');self.session=session or requests.Session()
        self.session.headers.update({'Authorization':f'ApiKey {key}','Content-Type':'application/json'})
    def publish(self,prefix,frames):
        report=[]
        for group,frame in frames.items():
            index=elastic_name(prefix,group);check=self.session.head(f'{self.url}/{index}',timeout=30)
            if check.status_code==404:
                self.session.put(f'{self.url}/{index}',json=mapping(frame),timeout=30).raise_for_status()
            else:check.raise_for_status()
            records=frame_records(frame)
            for offset in range(0,len(records),500):
                r=self.session.post(f'{self.url}/_bulk',params={'refresh':'wait_for'},data=bulk_payload(index,records[offset:offset+500]),headers={'Content-Type':'application/x-ndjson'},timeout=90)
                r.raise_for_status()
                if r.json().get('errors'):raise RuntimeError(f'Bulk indexing errors in {index}; inspect destination mapping/permissions.')
            count=self.session.get(f'{self.url}/{index}/_count',timeout=30);count.raise_for_status()
            read=self.session.post(f'{self.url}/{index}/_mget',json={'ids':[str(r['id']) for r in records[:5]]},timeout=30);read.raise_for_status()
            if count.json()['count']<len(records) or not all(r.get('found') for r in read.json()['docs']):raise RuntimeError('Elastic read-back verification failed')
            report.append({'index':index,'published_rows':len(records),'index_count':count.json()['count'],'sample_read_back':True})
        return report

class HopsworksPublisher:
    def __init__(self,host,project,key,client=None):
        if not all([host,project,key]):raise ValueError('Hopsworks host, project name, and API key are required.')
        if client is None:
            import hopsworks
            client=hopsworks
        certs=Path(__file__).resolve().parents[1]/'.cache/hopsworks-certs';certs.mkdir(parents=True,exist_ok=True)
        self.project=client.login(host=host,project=project,api_key_value=key,hostname_verification=True,cert_folder=str(certs))
        self.store=self.project.get_feature_store()
    def publish(self,prefix,frames):
        validate_prefix(prefix);report=[]
        for group,frame in frames.items():
            name=prefix+'_'+group
            fg=self.store.get_or_create_feature_group(name=name,version=1,primary_key=['id'],online_enabled=False,
                description='Exploratory 2024 Dutch GP features. Public OpenF1 observations; batch demo, not live production features.')
            fg.insert(frame,write_options={'wait_for_job':True})
            read=fg.read()
            if not set(frame.id.astype(str)).issubset(set(read.id.astype(str))):raise RuntimeError(f'Feature Group read-back incomplete: {name}')
            report.append({'feature_group':name,'version':1,'published_rows':len(frame),'read_rows':len(read),'id_read_back':True})
        return report
