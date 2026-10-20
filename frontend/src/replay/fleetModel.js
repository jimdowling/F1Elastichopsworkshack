// Pure multi-car replay logic. No invented race motion, race gaps or missing samples.
export const MAX_INTERPOLATION_GAP=2.5;
export const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));
const finite=Number.isFinite;
export function lowerIndex(times,t){let lo=0,hi=times.length;while(lo<hi){const mid=(lo+hi)>>>1;if(times[mid]<=t)lo=mid+1;else hi=mid}return lo-1}
export function clock(t){if(!finite(t))return '—';const s=Math.max(0,t);return `${String(Math.floor(s/3600)).padStart(2,'0')}:${String(Math.floor(s/60)%60).padStart(2,'0')}:${String(Math.floor(s)%60).padStart(2,'0')}`}
export function formatLap(t){return finite(t)?`${Math.floor(t/60)}:${(t%60).toFixed(3).padStart(6,'0')}`:'—'}
export function transformFor(reference){const xs=reference.trace.x,ys=reference.trace.y;let length=0;for(let i=1;i<xs.length;i++)length+=Math.hypot(xs[i]-xs[i-1],ys[i]-ys[i-1]);return {scale:4259/length,cx:(Math.min(...xs)+Math.max(...xs))/2,cy:(Math.min(...ys)+Math.max(...ys))/2}}
export function ghostAt(g,time){
 const tr=g.trace,t=clamp(time,0,g.lap_time),i=clamp(lowerIndex(tr.time,t),0,tr.time.length-2),f=clamp((t-tr.time[i])/(tr.time[i+1]-tr.time[i]||1),0,1);
 const value=k=>tr[k]?.[i]+f*(tr[k]?.[i+1]-tr[k]?.[i]);
 return {code:g.driver,x:value('x'),y:value('y'),speed:value('speed'),rpm:value('rpm'),throttle:value('throttle'),brake:tr.brake[f>=1?i+1:i],gear:tr.gear[f>=1?i+1:i],distance:value('distance'),time:t,
  dx:tr.x[i+1]-tr.x[i],dy:tr.y[i+1]-tr.y[i],available:true,telemetryAvailable:true,finished:time>=g.lap_time,lap:g.lap_number,compound:g.compound,tyre_age:g.tyre_life,status:'ghost'};
}
export function timeAtDistance(g,d){const a=g.trace.distance,i=clamp(lowerIndex(a,d),0,a.length-2),f=clamp((d-a[i])/(a[i+1]-a[i]||1),0,1);return g.trace.time[i]+f*(g.trace.time[i+1]-g.trace.time[i])}
export function ghostFrame(ghosts,time,codes){
 const map=Object.fromEntries(ghosts.map(g=>[g.driver,g]));const rows=codes.filter(c=>map[c]).map(c=>({...ghostAt(map[c],time),lap_time:map[c].lap_time}));
 rows.sort((a,b)=>b.distance-a.distance||a.lap_time-b.lap_time||a.code.localeCompare(b.code));
 const leader=rows[0];return rows.map((r,i)=>({...r,position:i+1,gap:i===0?0:timeAtDistance(map[r.code],r.distance)-timeAtDistance(map[leader.code],r.distance)}));
}
export function sampleLocation(series,time,scale,maxGap=MAX_INTERPOLATION_GAP){
 if(!series?.time?.length)return {available:false,status:'no-position-data'};
 const ts=series.time,n=ts.length,i=lowerIndex(ts,time);
 if(i<0||time>ts[n-1]+1e-6)return {available:false,status:'outside-position-coverage'};
 const j=Math.min(i+1,n-1),dt=ts[j]-ts[i];
 if(dt>maxGap&&time>ts[i]+1e-6)return {available:false,status:'position-gap',gap_s:dt};
 const a=i===j?Math.max(0,i-1):i,b=i===j?j:j,span=ts[b]-ts[a];
 const speed=span>0?Math.hypot(series.x[b]-series.x[a],series.y[b]-series.y[a])*scale/span:0;
 if(!finite(series.x[i])||!finite(series.y[i])||!finite(series.x[j])||!finite(series.y[j])||speed>150)return {available:false,status:'position-jump'};
 const f=dt>0?clamp((time-ts[i])/dt,0,1):0;
 return {available:true,status:f>0?'interpolated-position':'recorded-position',x:series.x[i]+f*(series.x[j]-series.x[i]),y:series.y[i]+f*(series.y[j]-series.y[i]),
  dx:series.x[b]-series.x[a],dy:series.y[b]-series.y[a],sample_before_s:ts[i],sample_after_s:ts[j],gap_s:dt};
}
export function sampleTelemetry(series,time,maxGap=MAX_INTERPOLATION_GAP){
 if(!series?.time?.length)return {telemetryAvailable:false};const i=lowerIndex(series.time,time),n=series.time.length;
 if(i<0||time>series.time[n-1]+1e-6)return {telemetryAvailable:false};
 const j=Math.min(n-1,i+1),dt=series.time[j]-series.time[i];
 if(dt>maxGap&&time>series.time[i]+1e-6)return {telemetryAvailable:false};
 const f=dt>0?clamp((time-series.time[i])/dt,0,1):0;
 const bounds={speed:[0,400],rpm:[0,15000],throttle:[0,100],brake:[0,100],n_gear:[0,8],drs:[0,14]},valid=(k,v)=>finite(v)&&v>=bounds[k][0]&&v<=bounds[k][1];
 const value=k=>valid(k,series[k]?.[i])&&(f===0||valid(k,series[k]?.[j]))?(f===0?series[k][i]:series[k][i]+f*(series[k][j]-series[k][i])):null,discrete=k=>valid(k,series[k]?.[i])?series[k][i]:null;
 return {telemetryAvailable:finite(value('rpm'))&&finite(value('speed'))&&finite(value('throttle'))&&discrete('n_gear')!=null,speed:value('speed'),rpm:value('rpm'),throttle:value('throttle'),gear:discrete('n_gear'),brake:discrete('brake'),drs:discrete('drs')};
}
export function prepareRace(data,series){
 const drivers={};let lastCompletion=-Infinity;
 for(const result of data.results){const code=result.driver_code,raw=(data.laps||[]).filter(l=>l.driver_code===code).sort((a,b)=>a.lap_number-b.lap_number),laps=[];let previous=-Infinity;
  for(let i=0;i<raw.length;i++){
   const l=raw[i],next=raw[i+1],start=next?.lap_number===l.lap_number+1?next.lap_start_s:null;let end=finite(l.lap_end_s)?l.lap_end_s:null,derived=false;
   // For continuous-time lap/tyre labels, the next consecutive recorded start
   // is the boundary; raw duration-derived ends can overlap it by milliseconds.
   if(finite(start)){derived=end==null||Math.abs(start-end)>.000001;end=start}
   if(end!=null&&end<previous-.001)end=null;
   if(end!=null){previous=end;lastCompletion=Math.max(lastCompletion,end);laps.push({...l,effective_end:end,derived_end:derived})}
  }
  const ranks=(data.positions||[]).filter(p=>p.driver_code===code).sort((a,b)=>a.session_time_s-b.session_time_s);
  drivers[code]={result,laps,ends:laps.map(l=>l.effective_end),ranks,rankTimes:ranks.map(r=>r.session_time_s),stints:(data.stints||[]).filter(s=>s.driver_code===code&&finite(s.lap_start)&&finite(s.lap_end)),series:series[code]};
 }
 const available=data.manifest.drivers.filter(d=>d.location_samples>1),intersectionStart=Math.max(...available.map(d=>d.first_s)),intersectionEnd=Math.min(...available.map(d=>d.last_s));
 // Clip at most minor leading/trailing sample offsets. A partial driver never
 // truncates the whole race; its missing coverage is instead shown per frame.
 const mostlyShared=intersectionEnd-intersectionStart>(data.manifest.end_s-data.manifest.start_s)*.98;
 return {drivers,lastCompletion,start:mostlyShared?intersectionStart:data.manifest.start_s,end:mostlyShared?intersectionEnd:data.manifest.end_s};
}
export function raceFrame(prepared,time,codes,scale,focus){
 const rows=codes.filter(c=>prepared.drivers[c]).map(code=>{
  const d=prepared.drivers[code],pos=sampleLocation(d.series?.location,time,scale),telemetry=sampleTelemetry(d.series?.car_data,time),rank=d.ranks[lowerIndex(d.rankTimes,time)],last=d.laps[lowerIndex(d.ends,time)];
  const completed=last?.lap_number||0,finished=completed>=(d.result.laps||Infinity),lap=Math.min(completed+1,d.result.laps||completed+1),stint=d.stints.find(s=>lap>=s.lap_start&&lap<=s.lap_end);
  const final=time>=prepared.lastCompletion;
  return {code,...pos,...telemetry,position:final?d.result.position:rank?.position??null,position_source:final?'final-classification':rank?'last-recorded-rank':'unavailable',position_time_s:rank?.session_time_s??null,
   completed_laps:completed,lap,compound:stint?.compound||last?.compound||'UNKNOWN',tyre_age:stint?.tyre_age_at_start!=null?stint.tyre_age_at_start+(lap-stint.lap_start+1):null,
   classified:finished,finished:!pos.available||!telemetry.telemetryAvailable,lap_end_derived:!!last?.derived_end,final};
 });
 const focused=rows.find(r=>r.code===focus&&r.available);
 for(const row of rows)row.separation_m=focused&&row.available?Math.hypot(row.x-focused.x,row.y-focused.y)*scale:null;
 return rows.sort((a,b)=>(a.position??999)-(b.position??999)||b.completed_laps-a.completed_laps||a.code.localeCompare(b.code));
}
