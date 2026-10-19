"""Native Hopsworks event feature-group reads, with explicitly labeled public supplements.

Event schema has no lap timestamps, pit-transit durations, control messages,
Sprint results or Q1/Q2/Q3 times. Those are never silently claimed as Hopsworks source data.
"""
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
import copy,math,re,time
from .dashboard import DashboardEngine,DASH,ROOT,read,mean
from .remote import FIELDS,canonical,digest
from .settings import problem

NATIVE_NOTE=('Hopsworks event feature groups supply Race/Qualifying results, laps and weather. Public supplements supply venue/driver metadata, Sprint points, classified elapsed times/completed-lap totals, qualifying segments, speed traps, pit-lane visits and race control. Historical timing and the four original labs remain separate public snapshots. No silent local fallback is used for failed native reads.')
RESULT_FIELDS=FIELDS['results']

def number(value,name,integer=False,minimum=None):
    if value is None:return None
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):problem('schema_mismatch',f'Event field {name} must be a finite number or null.')
    if integer and value!=int(value):problem('schema_mismatch',f'Event field {name} must contain integral values.')
    if minimum is not None and value<minimum:problem('schema_mismatch',f'Event field {name} is outside its supported range.')
    return int(value) if integer else value

def base_record(r):
    y=number(r.get('season'),'season',True);n=number(r.get('round_number'),'round_number',True)
    if y not in {2023,2024} or n is None or not 1<=n<=(22 if y==2023 else 24) or not isinstance(r.get('session_name'),str) or r.get('session_name') not in {'Race','Qualifying'}:problem('schema_mismatch','Native record has unsupported season, round or session values.')
    if not isinstance(r.get('event_name'),str) or not r['event_name']:problem('schema_mismatch','Native records need an event_name.')
    return y,n,r['session_name']

def code_of(r):
    code=r.get('driver_code')
    if not isinstance(code,str) or not re.fullmatch('[A-Z]{3}',code):problem('schema_mismatch','Native driver_code must be a three-letter uppercase code.')
    return code

def unique(rows,key):
    out={}
    for r in rows:
        k=key(r)
        if k in out and canonical(out[k])!=canonical(r):problem('duplicate_keys','Conflicting native records have the same session/driver/lap key. Resolve duplicate ingestion before activating this slice.')
        out[k]=r
    return list(out.values())

def scope(rows,filters):
    # Defense in depth: do not trust a proxy/fixture to have applied the requested filters.
    for r in rows:
        base_record(r)
        if any(r.get(k)!=v for k,v in filters.items()):problem('scope_mismatch','Hopsworks returned records outside the requested scope; no mixed dataset was activated.')
    return rows

class HopsDashboard(DashboardEngine):
    def __init__(self,reader,feature_reader=None,runtime_path=None):
        self.reader=reader;public=read(DASH/'catalog.json');self.public_catalog=public
        self.native_sessions=unique(scope(reader.read('sessions',{}),{}),lambda r:base_record(r))
        self.native_results=unique(scope(reader.read('results',{}),{}),lambda r:(*base_record(r),code_of(r)))
        session_keys={(r['season'],r['round_number']) for r in self.native_sessions if r['session_name']=='Race'}
        race_keys={(r['season'],r['round_number']) for r in self.native_results if r['session_name']=='Race'}
        keys=session_keys&race_keys
        if not keys:problem('empty_source','No matching Race session/result records were found in the configured Hopsworks event feature groups.')
        drivers=copy.deepcopy(public['drivers']);teams=copy.deepcopy(public['teams']);by_code={d['code']:d for d in drivers};team_ids={t['team_id'] for t in teams}
        refs={(r['season'],r['round_number'],r['session_name'],r['driver_code']):r for r in public['results']}
        normalized=[]
        for r in self.native_results:
            y,n,kind=base_record(r);code=code_of(r)
            for field in ['full_name','team_name','status']:
                if r.get(field) is not None and not isinstance(r[field],str):problem('schema_mismatch',f'Native {field} must be a string or null.')
            if (y,n) not in keys:continue
            ref=refs.get((y,n,kind,code),{})
            if code not in by_code:
                name=r.get('full_name') or code;d={'driver_id':'event_'+code.lower(),'code':code,'name':name,'first_name':name.split()[0],'last_name':name.split()[-1],'nationality':None,'date_of_birth':None};drivers.append(d);by_code[code]=d
            driver=by_code[code];team_name=r.get('team_name') or ref.get('team_name') or 'Unknown team'
            team_id=ref.get('team_id') or 'event_'+re.sub('[^a-z0-9]+','_',team_name.lower()).strip('_')
            if team_id not in team_ids:teams.append({'team_id':team_id,'name':team_name,'nationality':None});team_ids.add(team_id)
            row={k:ref.get(k) for k in ['laps','classified_time_ms','time_label','fastest_lap_rank','fastest_lap_number','fastest_lap_avg_kph','q1_ms','q2_ms','q3_ms']}
            row.update({k:r.get(k) for k in RESULT_FIELDS})
            row.update({'id':f'{y}-{n}-{kind}-{driver["driver_id"]}','driver_id':driver['driver_id'],'team_id':team_id,'full_name':r.get('full_name') or driver['name'],'team_name':team_name,'position_text':str(r.get('position') or '—'),'source':'Hopsworks event results + labeled public timing/metadata supplements','supplemental_fields':['laps','classified_time_ms','time_label','fastest_lap_rank','fastest_lap_number','fastest_lap_avg_kph','q1_ms','q2_ms','q3_ms']})
            for name in ['driver_number','position','grid_position','fastest_lap_ms']:
                value=row.get(name)
                if name=='driver_number' and isinstance(value,str) and re.fullmatch(r'\d+',value):value=int(value)
                row[name]=number(value,name,True,0)
            row['points']=number(row.get('points'),'points',False,0)
            if row['points'] is None and kind=='Qualifying':row['points']=0
            if row['points'] is None:problem('schema_mismatch','Native result points must be supplied (zero is valid).')
            row['status']=row.get('status') or 'Unknown'
            normalized.append(row)
        # Event feature groups advertise Race/Qualifying only. Sprint is explicit public supplemental data.
        normalized.extend({**r,'source':'Jolpica public Sprint supplement'} for r in public['results'] if r['session_name']=='Sprint' and (r['season'],r['round_number']) in keys)
        events=[];sessions=[];event_refs={(e['season'],e['round_number']):e for e in public['events']}
        for key in sorted(keys):
            event=copy.deepcopy(event_refs[key]);native=next(r for r in self.native_sessions if (r['season'],r['round_number'],r['session_name'])==(*key,'Race'))
            event.update({k:native[k] for k in ['event_name','country','location'] if native.get(k) is not None})
            date=native.get('session_date')
            try:datetime.fromisoformat(date.replace('Z','+00:00'))
            except (ValueError,TypeError,AttributeError):problem('schema_mismatch','Native session_date must be an ISO date/time.')
            event['date']=date[:10];event['source']='Hopsworks session metadata + public venue metadata';events.append(event)
        for r in self.native_sessions:
            if (r['season'],r['round_number']) in keys:sessions.append({**r,'id':f"{r['season']}-{r['round_number']}-{r['session_name']}",'source':'Hopsworks event sessions'})
        catalog={'seasons':sorted({k[0] for k in keys}),'events':events,'drivers':drivers,'teams':teams,'sessions':sessions,'results':normalized,'official_standings':[],
            'pit_stops':[p for p in public['pit_stops'] if (p['season'],p['round_number']) in keys]}
        # A separate disposable DB avoids overwriting the public runtime cache.
        super().__init__(catalog=catalog,feature_reader=feature_reader,runtime_path=runtime_path or ROOT/'.cache/hops-dashboard.sqlite')
        self.data_source='hopsworks';self.raw_cache={};self.loaded_at=datetime.now(timezone.utc).isoformat()
    def pace_source_id(self,season,round_number):
        s=self.reader.settings;return digest([s.hops_host,s.hops_project,s.sources,s.source_version,super().pace_source_id(season,round_number)])
    def catalog_view(self):
        d=super().catalog_view();d.update({'backend':'Hopsworks event feature groups + explicit public supplements','data_source':'hopsworks','cloud_connected':True,'scope_note':NATIVE_NOTE})
        d['counts'].update({'laps':None,'native_results':len(self.native_results)});return d
    def season_view(self,season,through):
        d=copy.deepcopy(super().season_view(season,through));d['methodology']='Points over the available Hopsworks Race results + public Sprint supplements. Missing rounds are not filled; final cloud standings are not forced to public totals.';d['source_note']=NATIVE_NOTE;return d
    def native(self,kind,season,round_number,session='Race'):
        self.event(season,round_number);filters={'season':season,'round_number':round_number,'session_name':session}
        rows=scope(self.reader.read(kind,filters),filters)
        if kind=='laps':
            for r in rows:
                code_of(r);number(r.get('lap_number'),'lap_number',True,1)
                for f in ['team_name','compound','track_status']:
                    if r.get(f) is not None and not isinstance(r[f],str):problem('schema_mismatch',f'Native {f} must be a string or null.')
                if r.get('lap_number') is None:problem('schema_mismatch','Native laps require lap_number.')
                for f in ['lap_duration_ms','duration_sector_1','duration_sector_2','duration_sector_3','tyre_life','position']:number(r.get(f),f,True,0)
                for f in ['is_pit_in_lap','is_pit_out_lap']:
                    if r.get(f) is not None and not isinstance(r[f],bool):problem('schema_mismatch',f'{f} must be boolean or null, not a string.')
            rows=unique(rows,lambda r:(code_of(r),r['lap_number']))
        if kind=='weather':
            for r in rows:
                for f in ['session_time_s','air_temperature','track_temperature','humidity','pressure','wind_speed','wind_direction']:number(r.get(f),f)
                if r.get('rainfall') is not None and not isinstance(r['rainfall'],bool):problem('schema_mismatch','rainfall must be boolean or null.')
            rows=unique(rows,lambda r:r.get('session_time_s'))
        return rows
    def race_raw(self,season,round_number):
        key=(season,round_number)
        if key in self.raw_cache and time.monotonic()-self.raw_cache[key][0]<self.reader.settings.cache_seconds:return copy.deepcopy(self.raw_cache[key][1])
        native=self.native('laps',season,round_number);weather=self.native('weather',season,round_number)
        if not native:problem('empty_source','No Race laps were returned for the selected event. The public archive was not substituted.')
        refs=read(DASH/f'race_{season}_{round_number:02d}.json');ref_laps={(l['driver_code'],l['lap_number']):l for l in refs['laps']};results={r['driver_code']:r for r in self.classifications(season,round_number)}
        laps=[];by=defaultdict(list)
        for r in sorted(native,key=lambda r:(r['driver_code'],r['lap_number'])):
            code=r['driver_code'];result=results.get(code)
            if not result:problem('schema_mismatch','A native lap driver has no corresponding Race result in the selected event.')
            ref=ref_laps.get((code,r['lap_number']),{});l={**r,'id':f'{season}-{round_number}-R-{code}-{r["lap_number"]}','team_id':result['team_id'],'team_name':r.get('team_name') or result['team_name'],'driver_number':result['driver_number'],
                'compound':r.get('compound') or 'UNKNOWN','source':'Hopsworks event laps; public speed-trap supplement only','date_start':None,'lap_start_s':None,'lap_end_s':None,
                'speed_trap_kph':ref.get('speed_trap_kph'),'i1_speed_kph':ref.get('i1_speed_kph'),'i2_speed_kph':ref.get('i2_speed_kph')}
            # Preserve null native flags; clean filtering treats unknown as ineligible.
            for f in FIELDS['laps']:l.setdefault(f,None)
            laps.append(l);by[code].append(l)
        stints=[]
        for code,rows in by.items():
            current=None;previous=None;num=0
            for l in rows:
                boundary=previous is None or l['lap_number']!=previous['lap_number']+1 or l['compound']!=previous['compound'] or l.get('is_pit_out_lap') is True or previous.get('is_pit_in_lap') is True or (l.get('tyre_life') is not None and previous.get('tyre_life') is not None and l['tyre_life']<previous['tyre_life'])
                if boundary:
                    num+=1;current={k:l[k] for k in ['season','round_number','event_name','session_name','driver_code','driver_number','team_id','compound']};current.update({'stint_number':num,'lap_start':l['lap_number'],'lap_end':l['lap_number'],'tyre_age_at_start':max(0,l['tyre_life']-1) if l.get('tyre_life') is not None else None,'source':'Derived contiguous native lap segment; not certified physical tyre-set identity'});stints.append(current)
                current['lap_end']=l['lap_number'];l['stint']=num;previous=l
        # Absolute lap timestamps are not in the event schema. Never invent a common replay clock.
        raw={'event':self.event(season,round_number),'laps':laps,'weather':self._weather_rows(weather),'stints':stints,'positions':[],'race_control':refs['race_control'],
            'race_start_epoch':None,'clock_origin_epoch':None,'coverage_note':NATIVE_NOTE}
        self.raw_cache[key]=(time.monotonic(),raw);return copy.deepcopy(raw)
    def _weather_rows(self,rows):
        return [{**{k:r.get(k) for k in FIELDS['weather']},'id':digest(r),'source':'Hopsworks event weather','date':None} for r in sorted(rows,key=lambda r:r.get('session_time_s') if r.get('session_time_s') is not None else -float('inf'))]
    def weather_view(self,season,round_number,session='Race'):
        rows=self._weather_rows(self.native('weather',season,round_number,session))
        return {'season':season,'round_number':round_number,'session_name':session,'rows':rows,'summary':{k:mean([r[k] for r in rows if isinstance(r.get(k),(int,float))]) for k in ['air_temperature','track_temperature','humidity','pressure','wind_speed']},'rain_samples':sum(r.get('rainfall') is True for r in rows),'source':'Hopsworks event weather; native session-relative time'}
    def race_view(self,*args):
        d=super().race_view(*args);d['source_note']=NATIVE_NOTE;d['timing_note']='Use the separate public historical-timing endpoint: native event laps do not supply synchronized lap timestamps.';return d
    def coverage_view(self):
        # No implicit 46-race cloud download just to render coverage.
        return {'data_source':'hopsworks','source_note':NATIVE_NOTE,'loaded_at':self.loaded_at,'native_sessions':len(self.native_sessions),'native_results':len(self.native_results),'events':len(self.events),
            'verified_group_counts':self.reader.counts,'cached_race_slices':len(self.raw_cache),'last_native_read':self.reader.last_read,'feature_backend':self.feature_source,'models_scope':'Original four experiments remain the frozen public Dutch GP snapshot. Dashboard race-pace features use the selected provider.'}
