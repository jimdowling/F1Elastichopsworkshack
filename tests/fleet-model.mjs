import fs from 'node:fs';
import {lowerIndex,ghostAt,ghostFrame,timeAtDistance,sampleLocation,sampleTelemetry,prepareRace,raceFrame,transformFor,clock} from '../frontend/src/replay/fleetModel.js';
const checks=[],measurements={},start=Date.now();const check=(name,condition=true)=>{checks.push({name,passed:!!condition});if(!condition)throw new Error(name)};
const read=p=>JSON.parse(fs.readFileSync(p));
try{
 const ghosts=Object.values(read('data/ghosts.json')),codes=ghosts.map(g=>g.driver),reference=ghosts.find(g=>g.driver==='NOR'),scale=transformFor(reference).scale;
 check('Binary search handles boundaries and exact samples',lowerIndex([1,2,3],0)===-1&&lowerIndex([1,2,3],2)===1&&lowerIndex([1,2,3],9)===2);
 for(const g of ghosts){const first=ghostAt(g,0),last=ghostAt(g,999);check(`${g.driver}: ghost motion clamps to recorded lap`,first.distance===0&&last.distance===1&&last.finished&&last.time===g.lap_time);check(`${g.driver}: final RPM is recorded, not a fallback`,last.rpm===g.trace.rpm.at(-1));check(`${g.driver}: distance/time inverse is preserved`,Math.abs(timeAtDistance(g,ghostAt(g,30).distance)-30)<1e-6)}
 const final=ghostFrame(ghosts,100,codes);check('Four-car finish order follows actual source lap times',final.map(r=>r.code).join(',')==='NOR,PIA,LEC,VER');check('Finish differences are real recorded-lap comparisons',Math.abs(final.at(-1).gap-.935)<1e-8&&Math.abs(final[1].gap-.420)<1e-8);
 for(let t=0;t<=75;t+=.25){const rows=ghostFrame(ghosts,t,codes);if(rows.some(r=>r.gap<-.000001||!Number.isFinite(r.x)||r.distance<0||r.distance>1))throw new Error('Invalid ghost frame '+t)}
 check('All four ghost trajectories and equal-distance gaps remain valid throughout 301 frames');
 check('Single-driver comparison is valid with zero relative gap',ghostFrame(ghosts,20,['VER']).length===1&&ghostFrame(ghosts,20,['VER'])[0].gap===0);
 const sparse={time:[0,1,10,11],x:[10,20,100,110],y:[1,2,10,11]};
 check('Position data is not extrapolated before or after coverage',!sampleLocation(sparse,-1,.1).available&&!sampleLocation(sparse,12,.1).available);
 check('A real sample remains available at a gap boundary',sampleLocation(sparse,1,.1).available);
 check('Long position gaps are hidden, not linearly invented',!sampleLocation(sparse,5,.1).available&&sampleLocation(sparse,5,.1).status==='position-gap');
 check('Short gaps interpolate only within observed brackets',sampleLocation(sparse,.5,.1).x===15&&sampleLocation(sparse,.5,.1).sample_before_s===0&&sampleLocation(sparse,.5,.1).sample_after_s===1);
 check('Physically implausible jumps are hidden',sampleLocation({time:[0,.1],x:[0,10000],y:[0,0]},.05,.1).status==='position-jump');
 check('Missing position streams stay missing',!sampleLocation(null,0,.1).available);
 const tel={time:[1,2,10],speed:[100,200,300],rpm:[8000,10000,12000],throttle:[20,80,100],n_gear:[3,4,8],brake:[0,100,0],drs:[0,12,12]};
 check('Continuous telemetry interpolates; gear/brake use as-of samples',sampleTelemetry(tel,1.5).rpm===9000&&sampleTelemetry(tel,1.5).gear===3&&sampleTelemetry(tel,1.5).brake===0);
 check('Exact telemetry boundary selects the recorded gear',sampleTelemetry(tel,2).gear===4);
 check('Telemetry gaps/bounds do not produce fake RPM',!sampleTelemetry(tel,5).telemetryAvailable&&!sampleTelemetry(tel,0).telemetryAvailable&&!sampleTelemetry(tel,11).telemetryAvailable);
 const badTel={...tel,throttle:[50,104,100],brake:[0,104,0]};
 check('Out-of-range source values become unavailable, not silently clipped',sampleTelemetry(badTel,1.5).throttle===null&&sampleTelemetry(badTel,2).brake===null&&!sampleTelemetry(badTel,2).telemetryAvailable);
 check('An exact valid telemetry sample survives an invalid later neighbor',sampleTelemetry(badTel,1).throttle===50);
 const m=read('data/replay/manifest.json'),raw=read('data/dashboard/race_2024_15.json'),cat=read('data/dashboard/catalog.json'),series=Object.fromEntries(m.drivers.map(d=>[d.driver_code,read('data/replay/'+d.file)]));
 const race={...raw,manifest:m,results:cat.results.filter(r=>r.season===2024&&r.round_number===15&&r.session_name==='Race')},p=prepareRace(race,series),all=m.drivers.map(d=>d.driver_code);
 check('Recorded streams define a real common race window',p.start===189.315&&p.end===5706.816);
 let total=0,available=0,suppressed=0,maxDistance=0;
 for(let t=p.start;t<=p.end;t+=5){const rows=raceFrame(p,t,all,scale,'NOR');if(rows.length!==20)throw new Error('Lost driver row');for(const r of rows){total++;if(r.available){available++;if(!Number.isFinite(r.x)||!Number.isFinite(r.y)||r.sample_before_s>t+.000001||r.sample_after_s<t-.000001)throw new Error('Invalid synchronized bracket');maxDistance=Math.max(maxDistance,r.separation_m||0)}else suppressed++;
   const d=p.drivers[r.code],source=d.ranks.filter(v=>v.session_time_s<=t).at(-1);if(!r.final&&r.position!==(source?.position??null))throw new Error('Future/wrong rank '+r.code);
   if(r.completed_laps>(d.result.laps||100))throw new Error('Future completed lap');
  }}
 check('Every five-second frame across the recorded race has 20 consistent as-of rows');
 check('Displayed positions have valid shared-time brackets; invalid intervals remain hidden',available/total>.99&&suppressed>=0);
 measurements.shared_time_driver_frames=total;measurements.renderable_position_frames=available;measurements.hidden_invalid_frames=suppressed;measurements.max_xy_separation_m=maxDistance;
 const atDefault=raceFrame(p,p.start+600,all,scale,'NOR');check('Initial race view has all 20 recorded-position cars',atDefault.every(r=>r.available));check('Default ranks reflect recorded VER lead, not fastest ghost order',atDefault[0].code==='VER'&&atDefault[1].code==='NOR');check('Focus separation is derived from actual common-time XY',atDefault.find(r=>r.code==='NOR').separation_m===0&&atDefault.find(r=>r.code==='VER').separation_m>0);
 const pitBoundary=race.laps.find(l=>l.driver_code==='NOR'&&l.lap_number===29).lap_start_s;
 check('A recorded next-lap start wins over a millisecond-overlapping duration endpoint',raceFrame(p,pitBoundary,['NOR'],scale,'NOR')[0].lap===29&&raceFrame(p,pitBoundary,['NOR'],scale,'NOR')[0].compound==='HARD');
 const end=raceFrame(p,p.end,all,scale,'NOR');check('Final classification is used only once all recorded lap endpoints are reached',end[0].code==='NOR'&&end.every(r=>r.final&&r.position_source==='final-classification'));
 check('Partial driver coverage never extrapolates a hidden car',!raceFrame(prepareRace(race,{...series,NOR:{...series.NOR,location:{time:[300,301],x:[5,6],y:[10,11]}}}),500,all,scale,'NOR').find(r=>r.code==='NOR').available);
 check('Long coverage gaps in one driver do not shrink the whole replay window',prepareRace(race,{...series,NOR:undefined}).end===p.end);
 check('Clock formatter never implies a live feed',clock(789.315)==='00:13:09');
 console.log('PASS',checks.length,'multi-car model checks',measurements);
}finally{fs.writeFileSync('qa/fleet-model-results.json',JSON.stringify({created_at:new Date().toISOString(),passed:checks.filter(c=>c.passed).length,total:checks.length,duration_ms:Date.now()-start,measurements,checks},null,2))}
