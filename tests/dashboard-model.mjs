import fs from 'node:fs';
import path from 'node:path';
import {timingFrame,time,clock,quant,distribution,DASH_PAGES} from '../frontend/src/dashboard/model.js';
const root=path.resolve(import.meta.dirname,'..'),checks=[],started=Date.now(),measurements={};
const check=(name,condition)=>{checks.push({name,passed:!!condition});if(!condition)throw new Error(name)};
const read=p=>JSON.parse(fs.readFileSync(path.join(root,p),'utf8'));
try{
 check('19 distinct dashboard/connection routes, separate from the experiments',DASH_PAGES.length===19&&new Set(DASH_PAGES).size===19&&!DASH_PAGES.includes('ghost'));
 check('Milliseconds format correctly',time(73817)==='1:13.817'&&time(5445519)==='1:30:45.519');
 check('Null and non-finite times remain absent',time(null)==='—'&&time(NaN)==='—');
 check('Clock and quantiles are deterministic',clock(3661)==='01:01:01'&&quant([1,2,3,4],.5)===2.5&&distribution([]).median===null);
 const result=(code,pos,grid,ms)=>({driver_id:code,driver_code:code,full_name:code,position:pos,grid_position:grid,laps:2,classified_time_ms:ms});
 const lap=(code,n,start,end,ms)=>({id:code+n,driver_code:code,lap_number:n,lap_start_s:start,lap_end_s:end,lap_duration_ms:ms,duration_sector_1:20000,duration_sector_2:20000,duration_sector_3:ms==null?null:ms-40000,compound:'MEDIUM',tyre_life:n});
 const sample={race_start_epoch:1000,clock_origin_epoch:1000,max_laps:2,results:[result('B',1,2,127000),result('A',2,1,130000)],laps:[lap('A',1,0,60,60000),lap('B',1,0,62,62000),lap('A',2,60,120,60000),lap('B',2,62,127,65000)],positions:[{driver_code:'A',session_time_s:-2,position:1},{driver_code:'B',session_time_s:-2,position:2},{driver_code:'A',session_time_s:61,position:2},{driver_code:'B',session_time_s:61,position:1}],stints:[],pit_stops:[]};
 const start=timingFrame(sample,0);check('Grid frame uses historical grid, not final classification',start.rows[0].driver_code==='A'&&start.rows.every(r=>r.completed_laps===0));
 const one=timingFrame(sample,1);check('Common timestamp is the first recorded lap completion',one.cutoff===60&&one.clock===60);
 check('A trailing car does not get its future lap time',one.rows.find(r=>r.driver_code==='B').completed_laps===0&&one.rows.find(r=>r.driver_code==='B').last_lap===null);
 check('Future rank changes are not used',one.rows[0].driver_code==='A'&&one.rows[0].display_position===1);
 const final=timingFrame(sample,2);check('Final frame explicitly uses official classification and laps',final.final&&final.rows[0].driver_code==='B'&&final.rows.every(r=>r.completed_laps===2));
 check('Final data clock reaches the last observation',final.cutoff===127);
 const missing=structuredClone(sample);missing.laps[0].lap_end_s=null;missing.laps[0].lap_duration_ms=null;const derived=timingFrame(missing,1);
 check('Missing lap end may use next observed start, with a disclosure flag',derived.cutoff===60&&derived.rows.find(r=>r.driver_code==='A').last_lap_end_derived);
 check('Missing durations are never turned into fabricated lap times',derived.rows.find(r=>r.driver_code==='A').last_lap.lap_duration_ms===null);
 const gaps=structuredClone(sample);gaps.max_laps=4;gaps.results=gaps.results.map(r=>({...r,laps:4}));gaps.laps=gaps.laps.filter(l=>l.lap_number===1);const held=timingFrame(gaps,3);
 check('A wholly missing frame holds the prior common clock, without inventing timestamps',held.dataGap&&held.referenceLap===1&&held.cutoff===60);
 const empty=timingFrame({results:[],laps:[],positions:[],stints:[],pit_stops:[],max_laps:1},1);check('An empty observation slice stays empty and finite',empty.rows.length===0&&Number.isFinite(empty.cutoff));
 const catalog=read('data/dashboard/catalog.json');let frames=0,derivedFrames=0,gapFrames=0;
 for(const event of catalog.events){
  const raw=read(`data/dashboard/race_${event.season}_${String(event.round_number).padStart(2,'0')}.json`),results=catalog.results.filter(r=>r.season===event.season&&r.round_number===event.round_number&&r.session_name==='Race');
  const race={...raw,results,pit_stops:catalog.pit_stops.filter(p=>p.season===event.season&&p.round_number===event.round_number),max_laps:Math.max(...results.map(r=>r.laps||0),...raw.laps.map(l=>l.lap_number))};
  const label=`${event.season} R${event.round_number}`;
  const zero=timingFrame(race,0);check(`${label}: all classified entries appear on the starting screen`,zero.rows.length===results.length&&zero.rows.every(r=>r.completed_laps===0));
  let previous=-Infinity;
  for(const n of Array.from({length:race.max_laps-1},(_,i)=>i+1)){
   const f=timingFrame(race,n);frames++;if(f.dataGap)gapFrames++;if(f.rows.some(r=>r.last_lap_end_derived))derivedFrames++;
   check(`${label} lap ${n}: common frame is finite, monotonic and has no future completed lap`,Number.isFinite(f.cutoff)&&f.cutoff>=previous-.002&&f.rows.every(r=>r.completed_laps<=n&&(!r.last_lap||r.last_effective_end==null||r.last_effective_end<=f.cutoff+.001)));previous=f.cutoff;
   for(const row of f.rows){
    const updates=raw.positions.filter(p=>p.driver_code===row.driver_code&&p.session_time_s<=f.cutoff+.001).sort((a,b)=>a.session_time_s-b.session_time_s);
    if(updates.length&&row.display_position!==updates.at(-1).position)throw new Error(`${label}: wrong as-of position for ${row.driver_code}`);
   }
  }
  const end=timingFrame(race,race.max_laps);const ordered=results.slice().sort((a,b)=>a.position-b.position);
  check(`${label}: final classification and completed-lap counts exactly match results`,end.final&&end.rows.every((r,i)=>r.driver_id===ordered[i].driver_id&&r.completed_laps===ordered[i].laps));
 }
 const jp=read('data/dashboard/race_2024_04.json');const jpRace={...jp,results:catalog.results.filter(r=>r.season===2024&&r.round_number===4&&r.session_name==='Race'),max_laps:53,pit_stops:[]};const jp1=timingFrame(jpRace,1),jp2=timingFrame(jpRace,2);check('Japan 2024 restart timestamp conflicts are reconciled without changing raw durations',jp1.reconciled_endpoints>0&&jp2.cutoff>jp1.cutoff&&jpRace.laps.find(l=>l.driver_code==='TSU'&&l.lap_number===2).lap_duration_ms===203186);
 measurements.real_race_frames=frames;measurements.frames_with_derived_lap_ends=derivedFrames;measurements.frames_held_for_missing_timestamp=gapFrames;
 console.log(`PASS ${checks.length} archive/replay model checks across 46 real races`,measurements);
}catch(error){console.error(error);process.exitCode=1}finally{
 fs.writeFileSync(path.join(root,'qa/dashboard-model-results.json'),JSON.stringify({created_at:new Date().toISOString(),duration_ms:Date.now()-started,passed:checks.filter(x=>x.passed).length,total:checks.length,measurements,checks},null,2));
}
