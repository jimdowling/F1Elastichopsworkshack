"""Historical dashboard: real public observations, transparent aggregations.

The published hackathon dimensions (season/round/session/driver) are retained.
No live timing or cloud connection is implied. Classification records and
on-demand pace features make a verified local SQLite round trip.
"""
from pathlib import Path
from functools import lru_cache
from collections import defaultdict,Counter
from threading import RLock
import json,sqlite3,hashlib,statistics,csv,io,math
import numpy as np

ROOT=Path(__file__).resolve().parents[1];DASH=ROOT/'data/dashboard'
TEAM_COLORS={'red_bull':'#7ca7ff','mercedes':'#58d8c4','ferrari':'#ff677a','mclaren':'#ff9e65','aston_martin':'#64bd9c','alpine':'#be9aff','williams':'#78b2ff','haas':'#b8c3cf','alphatauri':'#a6acdf','rb':'#a6acdf','alfa':'#d2829b','sauber':'#a4db70'}
NO_START={'Did not start','Withdrew','Did not qualify','Did not prequalify','Excluded'}

def finished(row):return (row.get('status') or '').strip().casefold() in {'finished','lapped'} or (row.get('status') or '').startswith('+')
def started(row):return row.get('status') not in NO_START and bool((row.get('laps') or 0)>0 or (row.get('grid_position') or 0)>0)
def mean(v):return round(float(np.mean(v)),6) if v else None
def quant(v,p):return round(float(np.quantile(v,p)),6) if v else None
def read(path):return json.loads(Path(path).read_text())
def finite(v):return v is not None and isinstance(v,(int,float)) and math.isfinite(v)

class DashboardEngine:
    def __init__(self,path=DASH,runtime_path=None,catalog=None,feature_reader=None):
        self.path=Path(path);self.catalog=catalog if catalog is not None else read(self.path/'catalog.json');self.feature_reader=feature_reader;self.feature_source='SQLite';self.data_source='public'
        self.manifest=read(self.path/'manifest.json') if (self.path/'manifest.json').exists() else {'coverage':[],'errors':[],'synthetic_observations':0,'status':'importing'}
        self.events=self.catalog['events'];self.drivers={d['driver_id']:d for d in self.catalog['drivers']};self.teams={t['team_id']:{**t,'color':TEAM_COLORS.get(t['team_id'],'#b3bfcc')} for t in self.catalog['teams']}
        self.event_map={(e['season'],e['round_number']):e for e in self.events};self.lock=RLock()
        runtime=Path(runtime_path) if runtime_path is not None else ROOT/'.cache/dashboard-runtime.sqlite';runtime.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(runtime,check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS dashboard_results (id TEXT PRIMARY KEY, season INTEGER, round_number INTEGER, session_name TEXT, payload TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS race_pace_features (id TEXT PRIMARY KEY, season INTEGER, round_number INTEGER, payload TEXT)')
        self.db.execute('DELETE FROM dashboard_results');self.db.execute('DELETE FROM race_pace_features')
        self.db.executemany('INSERT INTO dashboard_results VALUES (?,?,?,?,?)',[(r['id'],r['season'],r['round_number'],r['session_name'],json.dumps(r,separators=(',',':'))) for r in self.catalog['results']]);self.db.commit()
        self.results=[json.loads(r[0]) for r in self.db.execute('SELECT payload FROM dashboard_results ORDER BY season,round_number,session_name,id')]
        if len(self.results)!=len(self.catalog['results']):raise RuntimeError('Classification read-back count mismatch')
        self.pits=self.catalog['pit_stops'];self.sessions=self.catalog['sessions'];self.official=self.catalog['official_standings']

    def event(self,season,round_number):
        try:return self.event_map[(season,round_number)]
        except KeyError:raise ValueError('This season/round is not in the loaded archive')

    def resolve(self,driver):
        if driver in self.drivers:return driver
        match=next((d['driver_id'] for d in self.drivers.values() if d['code'].upper()==str(driver).upper()),None)
        if match:return match
        raise ValueError('Unknown driver')

    def rows(self,season,through,kind=None):
        self.event(season,through)
        return [r for r in self.results if r['season']==season and r['round_number']<=through and (kind is None or r['session_name']==kind)]

    def enriched(self,r):
        return {**r,'color':self.teams.get(r.get('team_id'),{}).get('color','#b3bfcc'),'finished':finished(r),'started':started(r)}

    def classifications(self,season,round_number,kind='Race'):
        self.event(season,round_number)
        return [self.enriched(r) for r in sorted(self.results,key=lambda r:r.get('position') or 999) if r['season']==season and r['round_number']==round_number and r['session_name']==kind]

    def catalog_view(self):
        return {'seasons':self.catalog['seasons'],'events':self.events,'drivers':list(self.drivers.values()),'teams':list(self.teams.values()),
            'counts':{'events':len(self.events),'classifications':len(self.results),'pit_records':len(self.pits),'sessions':len(self.sessions),'laps':self.manifest.get('lap_rows',0)},
            'backend':'Local SQLite read-back + public historical JSON archive','cloud_connected':False,'synthetic_observations':0}

    def _standings(self,season,through,kind):
        entries=self.rows(season,through);points=defaultdict(float);counts=defaultdict(Counter);last={}
        for r in entries:
            if r['session_name'] not in ('Race','Sprint'):continue
            key=r['driver_id'] if kind=='driver' else r['team_id'];points[key]+=r['points'];last[key]=r
            if r['session_name']=='Race' and r['position'] is not None and r.get('status')!='Disqualified':counts[key][r['position']]+=1
        keys=sorted(points,key=lambda k:(-points[k],*[-counts[k][p] for p in range(1,31)],k))
        # Official final classification supplies final tie-break order, with independently summed points below.
        maximum=max(e['round_number'] for e in self.events if e['season']==season)
        official={o['entity_id']:o for o in self.official if o['season']==season and o['kind']==kind}
        if through==maximum:keys.sort(key=lambda k:official.get(k,{}).get('position',999))
        out=[]
        for rank,key in enumerate(keys,1):
            row=last[key];entity=self.drivers[key] if kind=='driver' else self.teams[key]
            out.append({'id':key,'position':rank,'name':entity['name'],'code':entity.get('code'), 'team_id':row['team_id'] if kind=='driver' else key,
                'team_name':row['team_name'] if kind=='driver' else entity['name'],'color':self.teams[row['team_id'] if kind=='driver' else key]['color'],
                'points':round(points[key],3),'wins':counts[key][1],'podiums':sum(counts[key][p] for p in [1,2,3]),
                'gap':round(points[keys[0]]-points[key],3),'official_final_points':official.get(key,{}).get('points') if through==maximum else None})
        return out

    @lru_cache(maxsize=12)
    def season_view(self,season,through):
        event=self.event(season,through);rows=self.rows(season,through);races=[r for r in rows if r['session_name']=='Race'];qual=[r for r in rows if r['session_name']=='Qualifying'];sprints=[r for r in rows if r['session_name']=='Sprint']
        driver_standings=self._standings(season,through,'driver');team_standings=self._standings(season,through,'constructor')
        previous=max([e['round_number'] for e in self.events if e['season']==season and e['round_number']<through],default=0)
        prev_driver={x['id']:x['position'] for x in self._standings(season,previous,'driver')} if previous else {}
        prev_team={x['id']:x['position'] for x in self._standings(season,previous,'constructor')} if previous else {}
        for r in driver_standings:r['movement']=prev_driver.get(r['id'],r['position'])-r['position']
        for r in team_standings:r['movement']=prev_team.get(r['id'],r['position'])-r['position']
        profiles=[]
        for standing in driver_standings:
            key=standing['id'];rr=[r for r in races if r['driver_id']==key];qq=[r for r in qual if r['driver_id']==key];ss=[r for r in sprints if r['driver_id']==key]
            finishers=[r for r in rr if finished(r)];entered=[r for r in rr if started(r)];latest=max(rr or qq,key=lambda r:r['round_number'])
            profile={**self.drivers[key],**standing,'number':latest['driver_number'],'starts':len(entered),'race_entries':len(rr),'sprint_starts':len([r for r in ss if started(r)]),
                'pole_starts':sum(r['grid_position']==1 for r in rr),'qualifying_p1':sum(r['position']==1 for r in qq),'q3_appearances':sum(r.get('q3_ms') is not None for r in qq),
                'points_finishes':sum(r['points']>0 for r in rr),'finish_rate':round(len(finishers)/len(entered)*100,3) if entered else 0,
                'dnfs':sum(started(r) and not finished(r) and r['status']!='Disqualified' for r in rr),'disqualifications':sum(r['status']=='Disqualified' for r in rr),
                'avg_finish':mean([r['position'] for r in rr if started(r) and r['position'] is not None]),'avg_classified_finish':mean([r['position'] for r in finishers if r['position'] is not None]),
                'avg_qualifying':mean([r['position'] for r in qq if r['position'] is not None]),'best_finish':min([r['position'] for r in entered if r['position'] is not None],default=None),
                'sprint_wins':sum(r['position']==1 for r in ss),'sprint_podiums':sum(r['position'] is not None and r['position']<=3 for r in ss),'fastest_laps':sum(r['fastest_lap_rank']==1 for r in rr),
                'positions_gained':sum(r['grid_position']-r['position'] for r in rr if (r['grid_position'] or 0)>0 and r['position'] is not None),
                'race_points':round(sum(r['points'] for r in rr),3),'sprint_points':round(sum(r['points'] for r in ss),3),
                'laps_completed':sum(r['laps'] or 0 for r in rr),'team_history':list(dict.fromkeys(r['team_name'] for r in rr)),
                'finish_positions':[r['position'] for r in rr if started(r) and r['position'] is not None],'classified_positions':[r['position'] for r in finishers if r['position'] is not None],
                'qualifying_positions':[r['position'] for r in qq if r['position'] is not None],'sprint_positions':[r['position'] for r in ss if started(r) and r['position'] is not None]}
            profiles.append(profile)
        team_profiles=[]
        for standing in team_standings:
            key=standing['id'];rr=[r for r in races if r['team_id']==key];qq=[r for r in qual if r['team_id']==key]
            contribution=defaultdict(float);entry_counts=Counter()
            for r in rows:
                if r['team_id']==key and r['session_name'] in ('Race','Sprint'):contribution[r['driver_id']]+=r['points']
                if r['team_id']==key and r['session_name']=='Race':entry_counts[r['driver_id']]+=1
            team_profiles.append({**self.teams[key],**standing,'pole_starts':sum(r['grid_position']==1 for r in rr),'qualifying_p1':sum(r['position']==1 for r in qq),
                'laps_completed':sum(r['laps'] or 0 for r in rr),'dnfs':sum(started(r) and not finished(r) and r['status']!='Disqualified' for r in rr),
                'avg_finish':mean([r['position'] for r in rr if started(r) and r['position'] is not None]),
                'drivers':[{'id':d,**self.drivers[d],'points':round(pts,3),'entries':entry_counts[d]} for d,pts in sorted(contribution.items(),key=lambda x:-x[1])]})
        history={'drivers':[],'teams':[]}
        for n in sorted(e['round_number'] for e in self.events if e['season']==season and e['round_number']<=through):
            for kind,key in [('driver','drivers'),('constructor','teams')]:
                for row in self._standings(season,n,kind):history[key].append({'id':row['id'],'round_number':n,'position':row['position'],'points':row['points']})
        calendar=[]
        for ev in [e for e in self.events if e['season']==season]:
            rr=self.classifications(season,ev['round_number'],'Race');qq=self.classifications(season,ev['round_number'],'Qualifying');ss=self.classifications(season,ev['round_number'],'Sprint')
            pole=next((r for r in rr if r['grid_position']==1),None);gap=None
            if len(rr)>1 and rr[0]['classified_time_ms'] is not None and rr[1]['classified_time_ms'] is not None:gap=(rr[1]['classified_time_ms']-rr[0]['classified_time_ms'])/1000
            calendar.append({**ev,'winner':rr[0] if rr else None,'pole_starter':pole,'qualifying_p1':qq[0] if qq else None,'sprint_winner':ss[0] if ss else None,'winning_margin_s':gap,'laps':max([r['laps'] or 0 for r in rr],default=0)})
        return {'season':season,'through_round':through,'event':event,'driver_standings':driver_standings,'constructor_standings':team_standings,'drivers':profiles,'teams':team_profiles,'history':history,'calendar':calendar,
            'race_results':self.classifications(season,through,'Race'),'qualifying_results':self.classifications(season,through,'Qualifying'),'sprint_results':self.classifications(season,through,'Sprint'),
            'methodology':'Championship points sum Race + Sprint classifications. Pole starts use actual race grid P1, distinct from qualifying P1. Intermediate ties use Grand Prix finishing-position countback; final ordering is cross-checked against published final standings.'}

    @lru_cache(maxsize=8)
    def race_raw(self,season,round_number):
        self.event(season,round_number);p=self.path/f'race_{season}_{round_number:02d}.json'
        if not p.exists():return {'event':self.event(season,round_number),'laps':[],'stints':[],'positions':[],'weather':[],'race_control':[],'coverage_note':'Detailed session observations are not loaded.'}
        return read(p)

    def compute_pace_rows(self,season,round_number,clean=True,cutoff=1.07):
        if not finite(cutoff) or not 1<=cutoff<=1.5:raise ValueError('Pace cutoff must be finite and between 1.0 and 1.5')
        cutoff=float(cutoff)
        raw=self.race_raw(season,round_number);by=defaultdict(list)
        for l in raw['laps']:
            if finite(l.get('lap_duration_ms')) and l['lap_duration_ms']>0:by[l['driver_code']].append(l)
        out=[];accepted=set()
        for code,all_laps in by.items():
            base=[l for l in all_laps if l['lap_number']>1 and l['is_pit_in_lap'] is False and l['is_pit_out_lap'] is False]
            reference=statistics.median(l['lap_duration_ms'] for l in base) if base else None
            selected=[l for l in base if l['lap_duration_ms']<=reference*cutoff] if clean and reference else ([] if clean else all_laps)
            if not clean:selected=all_laps
            if not selected:continue
            values=[l['lap_duration_ms']/1000 for l in selected];accepted.update(l['id'] for l in selected)
            out.append({'id':f'{season}-{round_number}-{code}-{int(clean)}-{cutoff!r}','season':season,'round_number':round_number,'driver_code':code,'team_id':selected[0]['team_id'],'team_name':selected[0]['team_name'],
                'samples':len(values),'total_samples':len(all_laps),'mean_s':mean(values),'median_s':quant(values,.5),'p10_s':quant(values,.1),'q1_s':quant(values,.25),'q3_s':quant(values,.75),'p90_s':quant(values,.9),
                'min_s':round(min(values),3),'max_s':round(max(values),3),'std_s':round(float(np.std(values)),6),'iqr_s':round(quant(values,.75)-quant(values,.25),6),
                'reference_median_s':None if reference is None else reference/1000,'cutoff':cutoff,'pit_outlier_filter':bool(clean)})
        return out,accepted

    def pace_source_id(self,season,round_number):
        rows=self.race_raw(season,round_number)['laps']
        raw=json.dumps({'source':self.data_source,'laps':rows},sort_keys=True,separators=(',',':'),allow_nan=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    def pace_rows(self,season,round_number,clean=True,cutoff=1.07):
        out,accepted=self.compute_pace_rows(season,round_number,clean,cutoff)
        if self.feature_reader:
            readback=self.feature_reader(self.pace_source_id(season,round_number),out)
        else:
            with self.lock:
                self.db.executemany('INSERT OR REPLACE INTO race_pace_features VALUES (?,?,?,?)',[(r['id'],season,round_number,json.dumps(r,separators=(',',':'))) for r in out]);self.db.commit()
                fetched={r['id']:r for r in [json.loads(x[0]) for x in self.db.execute('SELECT payload FROM race_pace_features WHERE season=? AND round_number=?',(season,round_number))]}
            readback=[fetched[r['id']] for r in out]
        readback.sort(key=lambda r:r['median_s'])
        if readback:
            best=readback[0]['median_s']
            for r in readback:r['delta_s']=round(r['median_s']-best,6)
        return readback,accepted

    def race_view(self,season,round_number,clean=True,cutoff=1.07):
        raw=self.race_raw(season,round_number);metrics,accepted=self.pace_rows(season,round_number,clean,cutoff)
        laps=[{**l,'included':l['id'] in accepted} for l in raw['laps']]
        results=self.classifications(season,round_number)
        lookup={r['driver_code']:r for r in results}
        for m in metrics:
            rr=lookup.get(m['driver_code'],{});m.update({'driver_id':rr.get('driver_id'),'name':rr.get('full_name',m['driver_code']),'color':rr.get('color','#a1acbd')})
        weather=raw.get('weather',[])
        weather_summary={k:mean([w[k] for w in weather if finite(w.get(k))]) for k in ['air_temperature','track_temperature','humidity','pressure','wind_speed']}
        weather_summary.update({'samples':len(weather),'rain_samples':sum(bool(w.get('rainfall')) for w in weather)})
        return {'feature_backend':self.feature_source,'data_source':self.data_source,'season':season,'round_number':round_number,'event':raw['event'],'race_start_epoch':raw.get('race_start_epoch'),'clock_origin_epoch':raw.get('clock_origin_epoch'),'laps':laps,'metrics':metrics,
            'stints':raw['stints'],'positions':raw['positions'],'weather':weather,'race_control':raw['race_control'],
            'pit_stops':[p for p in self.pits if p['season']==season and p['round_number']==round_number],'results':results,
            'max_laps':max([r['laps'] or 0 for r in results]+[l['lap_number'] for l in laps]+[0]),'weather_summary':weather_summary,
            'coverage':{k:len(raw.get(k,[])) for k in ['laps','stints','positions','weather','race_control']},
            'filter':{'pit_outlier_filter':clean,'cutoff':cutoff,'definition':'Excludes lap 1, pit-in/out laps and laps slower than cutoff × each driver’s non-pit median. This is not a guaranteed green-flag, fuel- or tyre-corrected pace sample.'},
            'timing_note':'Historical common-time snapshots from recorded position changes and lap timestamps. Final frame uses classified results; no live feed, team radio or full-field XY positions are supplied.'}

    def driver_view(self,season,through,driver):
        driver=self.resolve(driver);season_data=self.season_view(season,through);profile=next((d for d in season_data['drivers'] if d['id']==driver),None)
        if profile is None:raise ValueError('This driver has no classification at this season/round cutoff')
        entries=self.rows(season,through);history=[]
        for ev in [e for e in self.events if e['season']==season and e['round_number']<=through]:
            r=next((r for r in entries if r['round_number']==ev['round_number'] and r['driver_id']==driver and r['session_name']=='Race'),None)
            q=next((r for r in entries if r['round_number']==ev['round_number'] and r['driver_id']==driver and r['session_name']=='Qualifying'),None)
            sp=next((r for r in entries if r['round_number']==ev['round_number'] and r['driver_id']==driver and r['session_name']=='Sprint'),None)
            history.append({'round_number':ev['round_number'],'event_name':ev['event_name'],'country':ev['country'],'race':self.enriched(r) if r else None,'qualifying':q,'sprint':sp})
        prior=[]
        if season-1 in self.catalog['seasons']:
            previous_max=max(e['round_number'] for e in self.events if e['season']==season-1)
            previous_round=max([e['round_number'] for e in self.events if e['season']==season-1 and e['round_number']<=min(through,previous_max)],default=None)
            if previous_round is not None:prior=[h for h in self.season_view(season-1,previous_round)['history']['drivers'] if h['id']==driver]
        return {'profile':profile,'history':history,'points_history':[h for h in season_data['history']['drivers'] if h['id']==driver],'previous_season_points':prior,'previous_season_note':'Aligned by round number, not by the same circuits; calendars differ.'}

    def compare(self,season,through,a,b):
        a=self.resolve(a);b=self.resolve(b)
        if a==b:raise ValueError('Select two different drivers')
        sa=self.driver_view(season,through,a);sb=self.driver_view(season,through,b);ha={h['round_number']:h for h in sa['history']};hb={h['round_number']:h for h in sb['history']}
        wins={k:{'a':0,'b':0,'paired':0,'tied':0} for k in ['Race','Qualifying','Sprint']};rounds=[];cuma=cumb=0
        for n in sorted(set(ha)&set(hb)):
            aa=ha[n];bb=hb[n];gap=None;segment=None
            for field,kind in [('race','Race'),('qualifying','Qualifying'),('sprint','Sprint')]:
                x,y=aa[field],bb[field]
                if not x or not y or x['position'] is None or y['position'] is None:continue
                if kind!='Qualifying' and (not started(x) or not started(y)):continue
                wins[kind]['paired']+=1
                if x['position']==y['position']:wins[kind]['tied']+=1
                else:wins[kind]['a' if x['position']<y['position'] else 'b']+=1
            qa,qb=aa['qualifying'],bb['qualifying']
            if qa and qb:
                for seg in ['q3_ms','q2_ms','q1_ms']:
                    if qa.get(seg) and qb.get(seg):gap=(qa[seg]-qb[seg])/1000;segment=seg[:2].upper();break
            pa=sum((aa[k] or {}).get('points',0) for k in ['race','sprint']);pb=sum((bb[k] or {}).get('points',0) for k in ['race','sprint']);cuma+=pa;cumb+=pb
            rounds.append({'round_number':n,'event_name':aa['event_name'],'country':aa['country'],'a_race':(aa['race'] or {}).get('position'),'b_race':(bb['race'] or {}).get('position'),
                'a_quali':(qa or {}).get('position'),'b_quali':(qb or {}).get('position'),'a_points':pa,'b_points':pb,'a_cumulative':cuma,'b_cumulative':cumb,'points_gap':cuma-cumb,'qualifying_gap_s':gap,'qualifying_segment':segment})
        qg=[x['qualifying_gap_s'] for x in rounds if x['qualifying_gap_s'] is not None]
        return {'a':sa['profile'],'b':sb['profile'],'wins':wins,'rounds':rounds,'mean_qualifying_gap_s':mean(qg),'paired_qualifying_times':len(qg),
                'methodology':'Head-to-head uses classifications in shared entries. Race/Sprint includes starters, including retirements. Qualifying time gaps use the last shared Q segment, not necessarily matched track conditions. No opaque SPS/TMS grades are invented.'}

    def pit_view(self,season,through):
        self.event(season,through);rows=[p for p in self.pits if p['season']==season and p['round_number']<=through]
        valid=[p for p in rows if finite(p['duration_s']) and 10<=p['duration_s']<=90];teams=[];drivers=[]
        for field,output in [('team_id',teams),('driver_id',drivers)]:
            by=defaultdict(list)
            for p in valid:by[p[field]].append(p)
            for key,values in by.items():
                durations=[p['duration_s'] for p in values];entity=self.teams[key] if field=='team_id' else self.drivers[key]
                output.append({'id':key,'name':entity['name'],'code':entity.get('code'),'color':self.teams[values[-1]['team_id']]['color'],'count':len(values),'mean_s':mean(durations),'median_s':quant(durations,.5),'std_s':round(float(np.std(durations)),6),'min_s':min(durations),'total_s':round(sum(durations),3),'q1_s':quant(durations,.25),'q3_s':quant(durations,.75)})
            output.sort(key=lambda r:r['median_s'])
        return {'rows':rows,'teams':teams,'drivers':drivers,'valid_count':len(valid),'excluded_count':len(rows)-len(valid),'fastest':min(valid,key=lambda x:x['duration_s']) if valid else None,
            'mean_s':mean([p['duration_s'] for p in valid]),'total_s':round(sum(p['duration_s'] for p in valid),3),
            'methodology':'Recorded pit-lane duration, not stationary service time. Summary comparisons retain 10–90 s records to exclude obvious long interruptions/invalid timings. Different circuits have different lane lengths; this is not a pit-crew ranking or DHL award score.'}

    def weather_view(self,season,round_number,session='Race'):
        self.event(season,round_number)
        if session=='Race':rows=self.race_raw(season,round_number).get('weather',[])
        else:
            p=self.path/f'weather_{season}_{round_number:02d}_qualifying.json';rows=read(p) if p.exists() else []
        return {'season':season,'round_number':round_number,'session_name':session,'rows':rows,'summary':{k:mean([r[k] for r in rows if finite(r.get(k))]) for k in ['air_temperature','track_temperature','humidity','pressure','wind_speed']},'rain_samples':sum(bool(r.get('rainfall')) for r in rows),'source':'OpenF1; full-session samples, including pre/post-race where supplied'}

    @lru_cache(maxsize=2)
    def tracks(self,season):
        if season not in self.catalog['seasons']:raise ValueError('Unknown season')
        rows=[]
        for event in [e for e in self.events if e['season']==season]:
            r=event['round_number'];results=self.classifications(season,r);raw=self.race_raw(season,r)
            length_values=[x['fastest_lap_avg_kph']*x['fastest_lap_ms']/3_600_000 for x in results if x['fastest_lap_avg_kph'] and x['fastest_lap_ms']]
            length=quant(length_values,.5);metrics,_=self.compute_pace_rows(season,r,True,1.07);pit_count=sum(p['season']==season and p['round_number']==r for p in self.pits)
            rows.append({**event,'lap_length_km':None if length is None else round(length,3),'race_distance_km':round(length*max([x['laps'] or 0 for x in results],default=0),3) if length else None,
                'median_pace_s':quant([m['median_s'] for m in metrics],.5),'median_iqr_s':quant([m['iqr_s'] for m in metrics],.5),'pit_events':pit_count,'stops_per_entry':pit_count/len(results) if results else None,
                'retirement_rate':sum(started(x) and not finished(x) for x in results)/len(results)*100 if results else None,'weather_samples':len(raw.get('weather',[])),
                'rain_samples':sum(bool(w.get('rainfall')) for w in raw.get('weather',[])),'drivers':len(results),'lap_samples':len(raw.get('laps',[]))})
        features=['lap_length_km','median_pace_s','stops_per_entry','retirement_rate'];complete=[r for r in rows if all(finite(r[k]) for k in features)]
        if complete:
            matrix=np.array([[r[k] for k in features] for r in complete]);sd=matrix.std(axis=0);sd[sd==0]=1;scaled=(matrix-matrix.mean(axis=0))/sd
            for i,r in enumerate(complete):
                distances=np.sqrt(((scaled-scaled[i])**2).sum(axis=1));order=np.argsort(distances)
                r['similar']=[{'circuit_id':complete[j]['circuit_id'],'event_name':complete[j]['event_name'],'round_number':complete[j]['round_number'],'distance':round(float(distances[j]),3)} for j in order if j!=i][:3]
        return {'season':season,'rows':rows,'methodology':'Timing DNA, not engineering ratings. Lap length is inferred from reported fastest-lap average speed × lap time; distance uses winner completed laps. Similarity is Euclidean distance over four standardized timing/pit/retirement metrics. No turn counts, tyre-stress or downforce ratings are fabricated.'}

    @lru_cache(maxsize=1)
    def archive_quality(self):
        out={'lap_rows_missing_duration':0,'lap_rows_missing_end_time':0,'lap_rows_unknown_compound':0,'stint_rows_missing_boundary':0,'events_without_inferred_length':[]}
        for event in self.events:
            y,r=event['season'],event['round_number'];raw=self.race_raw(y,r)
            out['lap_rows_missing_duration']+=sum(l['lap_duration_ms'] is None for l in raw['laps'])
            out['lap_rows_missing_end_time']+=sum(l['lap_end_s'] is None for l in raw['laps'])
            out['lap_rows_unknown_compound']+=sum(l['compound']=='UNKNOWN' for l in raw['laps'])
            out['stint_rows_missing_boundary']+=sum(s['lap_start'] is None or s['lap_end'] is None for s in raw['stints'])
            if not any(x['fastest_lap_avg_kph'] and x['fastest_lap_ms'] for x in self.classifications(y,r)):
                out['events_without_inferred_length'].append(f"{y} {event['event_name']}")
        return out

    def coverage_view(self):
        with self.lock:feature_count=self.db.execute('SELECT COUNT(*) FROM race_pace_features').fetchone()[0]
        return {'manifest':self.manifest,'quality':self.archive_quality(),'source_url':'https://api.jolpi.ca/ergast/f1/','reference_url':'https://app.formula1dashboard.com/',
            'local_feature_rows':feature_count,'result_readback_rows':len(self.results),'models_scope':'The four existing ML/replay experiments use the separately validated 2024 Dutch GP snapshot, not a newly trained two-season model.',
            'schema_mapping':[
                {'index':'f1-sessions','source':'Jolpica calendar + OpenF1 session metadata','supported':'season, round_number, country, location, event_name, session_name, session_date','note':'Public equivalents, not the event cluster.'},
                {'index':'f1-results','source':'Jolpica classifications','supported':'driver, team, grid, classification, points, status, fastest_lap_ms, qualifying segments','note':'Sprint data supplements championship points; race/qualifying remain distinct.'},
                {'index':'f1-laps','source':'OpenF1 laps + stints + position changes; Jolpica pit matching','supported':'lap_duration_ms, sector durations in ms, compound, tyre_life, pit flags, derived as-of position, speed traps','note':'track_status is null rather than falsely claimed to be native FastF1. Filtering is explicitly retrospective.'},
                {'index':'f1-weather','source':'OpenF1 race/qualifying weather','supported':'session_time_s, temperatures, humidity, pressure, wind, rainfall','note':'Session-relative time; UTC date is retained.'},
                {'index':'f1-telemetry','source':'Existing four Dutch-GP replay traces + 275 lap signatures','supported':'speed, RPM, throttle, brake, gear, measured XY on selected laps','note':'The schema export remains four comparison laps. A separate public Dutch GP replay includes the full field at reduced cadence; the 57-million-row event index has not been ingested.'}],
            'replacements':[
                {'reference':'Tech Updates','adapted':'Race Control','reason':'Recorded messages, flags and lap-deletion context replace unavailable upgrade reports.'},
                {'reference':'Used Elements','adapted':'Tyre & Stint Explorer','reason':'Observed compounds and stint lengths replace unsupported power-unit allocations.'},
                {'reference':'Destructors Championship','adapted':'Weather & Conditions','reason':'Measured session conditions replace unsupported crash-cost estimates.'},
                {'reference':'SPS / TMS grades','adapted':'Raw statistics and paired head-to-head','reason':'No proprietary scoring formula is guessed.'},
                {'reference':'Live Timing / radio','adapted':'Historical timing replay + 3D Ghost Lap','reason':'Recorded observations are not represented as a live feed, radio recording or full-field GPS replay.'}]}

    def export(self,kind,season,round_number,session='Race'):
        self.event(season,round_number)
        if kind in {'laps','pits','stints','race-control','features'} and session!='Race':raise ValueError('This export is available for Race only')
        if kind=='weather' and session not in {'Race','Qualifying'}:raise ValueError('Weather is loaded for Race and Qualifying only')
        if kind=='results':rows=self.classifications(season,round_number,session)
        elif kind=='laps':rows=self.race_raw(season,round_number)['laps']
        elif kind=='weather':rows=self.weather_view(season,round_number,session)['rows']
        elif kind=='pits':rows=[r for r in self.pits if r['season']==season and r['round_number']==round_number]
        elif kind=='stints':rows=self.race_raw(season,round_number)['stints']
        elif kind=='race-control':rows=self.race_raw(season,round_number)['race_control']
        elif kind=='features':rows=self.pace_rows(season,round_number,True,1.07)[0]
        elif kind=='sessions':rows=[s for s in self.sessions if s['season']==season and s['round_number']==round_number and s['session_name']==session]
        elif kind=='driver-stats':rows=self.season_view(season,round_number)['drivers']
        elif kind=='constructor-stats':rows=self.season_view(season,round_number)['teams']
        else:raise ValueError('Unknown export')
        columns=list(dict.fromkeys(k for r in rows for k in r)) if rows else ['no_rows_in_selected_slice']
        out=io.StringIO();writer=csv.DictWriter(out,fieldnames=columns);writer.writeheader()
        for r in rows:
            safe={}
            for k,v in r.items():
                if isinstance(v,(dict,list)):v=json.dumps(v,ensure_ascii=False)
                if isinstance(v,str) and (v.lstrip().startswith(('=','+','-','@')) or v.startswith(('\t','\r'))):v="'"+v
                safe[k]=v
            writer.writerow(safe)
        return out.getvalue()
