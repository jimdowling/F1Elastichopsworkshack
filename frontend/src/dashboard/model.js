export const TONES={lime:'#d7ff62',blue:'#7ca7ff',orange:'#ff9e65',purple:'#bf9dff',teal:'#57d8bf',red:'#ff7282'};
export const TYRES={SOFT:'#ff697b',MEDIUM:'#f2cf66',HARD:'#e3e8ee',INTERMEDIATE:'#78cc8e',WET:'#6b9dff',UNKNOWN:'#8794a2'};
export const NAV_GROUPS=[
 {label:'RACE DESK',items:[['dashboard','Dashboard','LayoutDashboard'],['timing','Historical timing','Radio'],['calendar','Race calendar','CalendarDays'],['results','Session results','Flag']]},
 {label:'CHAMPIONSHIP',items:[['driver-standings','Driver standings','Trophy'],['constructor-standings','Constructor standings','Award'],['drivers','Drivers & profiles','ContactRound'],['teams','Teams','Users'],['driver-stats','Driver statistics','ChartNoAxesCombined']]},
 {label:'RACE INTELLIGENCE',items:[['head-to-head','Head to head','Swords'],['consistency','Consistency','Activity'],['race-pace','Race pace','Gauge'],['pit-stops','Pit-lane analysis','Timer'],['tyres','Tyres & stints','CircleDot'],['weather','Weather & conditions','CloudSun'],['race-control','Race control','Siren'],['track-dna','Track DNA','Route']]},
 {label:'DATA WORKBENCH',items:[['data','Coverage & schema','Database']]}
];
export const DASH_PAGES=NAV_GROUPS.flatMap(g=>g.items.map(x=>x[0]));
export const PAGE_NAMES=Object.fromEntries(NAV_GROUPS.flatMap(g=>g.items.map(x=>[x[0],x[1]])));
export const fmt=(v,n=0)=>v==null||!Number.isFinite(Number(v))?'—':Number(v).toLocaleString('en-GB',{minimumFractionDigits:n,maximumFractionDigits:n});
export const sign=(v,n=1)=>v==null?'—':`${v>=0?'+':''}${fmt(v,n)}`;
export function time(ms){if(ms==null||!Number.isFinite(ms))return '—';const v=Math.max(0,Math.round(ms)),s=Math.floor(v/1000),m=Math.floor(s/60),h=Math.floor(m/60);return `${h?h+':'+String(m%60).padStart(2,'0'):m}:${String(s%60).padStart(2,'0')}.${String(v%1000).padStart(3,'0')}`;}
export function clock(sec){const s=Math.max(0,Math.floor(sec||0));return `${String(Math.floor(s/3600)).padStart(2,'0')}:${String(Math.floor(s/60)%60).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;}
export const shortGP=name=>(name||'').replace('Grand Prix','GP');
export const date=value=>value?new Intl.DateTimeFormat('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(value.slice(0,10)+'T12:00:00Z')):'—';
const CODES={'Bahrain':'BH','Saudi Arabia':'SA','Australia':'AU','Azerbaijan':'AZ','USA':'US','United States':'US','Monaco':'MC','Spain':'ES','Canada':'CA','Austria':'AT','UK':'GB','United Kingdom':'GB','Hungary':'HU','Belgium':'BE','Netherlands':'NL','Italy':'IT','Singapore':'SG','Japan':'JP','Qatar':'QA','Mexico':'MX','Brazil':'BR','UAE':'AE','United Arab Emirates':'AE','China':'CN'};
export const flag=country=>{const c=CODES[country];return c?[...c].map(x=>String.fromCodePoint(127397+x.charCodeAt())).join(''):'🏁'};
export function quant(values,p){const a=values.filter(Number.isFinite).sort((a,b)=>a-b);if(!a.length)return null;const x=(a.length-1)*p,i=Math.floor(x);return a[i]+(a[Math.ceil(x)]-a[i])*(x-i)}
export const distribution=values=>({samples:values.length,min:quant(values,0),p10:quant(values,.1),q1:quant(values,.25),median:quant(values,.5),q3:quant(values,.75),p90:quant(values,.9),max:quant(values,1)});
export function driverColor(d,index=0){if(!d)return '#8d9dab';const code=d.driver_code||d.code;const special={NOR:'#ff9e65',PIA:'#ffcc9e',VER:'#7ca7ff',PER:'#527ed0',LEC:'#ff6d7d',SAI:'#ff9da8',HAM:'#57d8bf',RUS:'#9fe7d9',ALO:'#61b99d',STR:'#a1cfbd',GAS:'#bf9dff',OCO:'#dec8ff',ALB:'#6cb4fb',SAR:'#afcef5',TSU:'#a3addf',RIC:'#cdd1f3',LAW:'#d9ddff',BOT:'#a1d580',ZHO:'#d0e7ad',HUL:'#b2becf',MAG:'#e5edf2'};return special[code]||d.color||Object.values(TONES)[index%6]}
export const compoundLabel=c=>({SOFT:'S',MEDIUM:'M',HARD:'H',INTERMEDIATE:'I',WET:'W',UNKNOWN:'?'}[c]||'?');

/** A common-time archival snapshot, not an invented live gap feed or full-field XY simulation. */
export function timingFrame(race,lap){
 if(!race?.results)return {rows:[],cutoff:0,clock:0,bestSectors:[null,null,null],frame:lap};
 const all=race.laps||[],max=race.max_laps||1,offset=(race.race_start_epoch||0)-(race.clock_origin_epoch||race.race_start_epoch||0);
 const by=new Map();for(const r of all){if(!by.has(r.driver_code))by.set(r.driver_code,[]);by.get(r.driver_code).push(r)}
 for(const arr of by.values())arr.sort((a,b)=>a.lap_number-b.lap_number);
 const effectiveEnd=new Map(),derivedEnd=new Set(),reconciledEnd=new Set(),quarantined=new Set();
 // Source dates can be rewritten at restarts while duration fields still refer to
 // the first attempt (Japan 2024 is a real example). A recorded next-lap start is
 // a disclosed completion estimate; original durations/rows are never overwritten.
 for(const arr of by.values()){
  let previous=-Infinity;
  for(let i=0;i<arr.length;i++){
   const row=arr[i],next=arr[i+1],nextStart=next?.lap_number===row.lap_number+1?next.lap_start_s:null;
   let end=Number.isFinite(row.lap_end_s)?row.lap_end_s:null;
   if(Number.isFinite(nextStart)&&(end==null||Math.abs(nextStart-end)>.25)){
    if(end!=null)reconciledEnd.add(row.id);end=nextStart;derivedEnd.add(row.id);
   }
   if(end!=null&&end<previous-.001){end=null;quarantined.add(row.id)}
   if(end!=null)previous=end;
   effectiveEnd.set(row.id,end);
  }
 }
 const final=lap>=max,allEnds=[...effectiveEnd.values()].filter(Number.isFinite);
 let cutoff=lap===0?0:final?Math.max(offset,...allEnds):offset,dataGap=false,referenceLap=0;
 if(lap>0&&!final){
  for(let n=1;n<=lap;n++){
   const ends=all.filter(r=>r.lap_number===n).map(r=>effectiveEnd.get(r.id)).filter(v=>Number.isFinite(v)&&v>=cutoff-.001);
   if(ends.length){cutoff=Math.min(...ends);referenceLap=n;dataGap=false}else dataGap=true;
  }
 }else if(final)referenceLap=lap;
 const completed=lap===0?[]:all.filter(r=>r.lap_number<=lap&&Number.isFinite(effectiveEnd.get(r.id))&&effectiveEnd.get(r.id)<=cutoff+.001);
 const bestSectors=[1,2,3].map(n=>{const values=completed.map(r=>r['duration_sector_'+n]).filter(v=>Number.isFinite(v)&&v>0);return values.length?Math.min(...values):null});
 const rows=race.results.map(result=>{
  const laps=completed.filter(l=>l.driver_code===result.driver_code).sort((a,b)=>a.lap_number-b.lap_number),last=laps.at(-1)||null;
  const pos=(race.positions||[]).filter(p=>p.driver_code===result.driver_code&&p.session_time_s<=cutoff+.001).sort((a,b)=>a.session_time_s-b.session_time_s).at(-1);
  const currentStint=(race.stints||[]).filter(s=>s.driver_code===result.driver_code&&s.lap_start!=null&&s.lap_start<=(last?.lap_number||1)&&((s.lap_end||999)>=(last?.lap_number||1))).at(-1);
  const bestLaps=laps.map(l=>l.lap_duration_ms).filter(v=>Number.isFinite(v)&&v>0);
  return {...result,display_position:final?result.position:lap===0?(result.grid_position||99):(pos?.position??null),position_source:final?'classification':lap===0?'grid':pos?'recorded':'unavailable',last_lap:last,
   completed_laps:final?(result.laps||0):(last?.lap_number||0),last_lap_end_derived:!!last&&derivedEnd.has(last.id),last_effective_end:last?effectiveEnd.get(last.id):null,best_lap_ms:bestLaps.length?Math.min(...bestLaps):null,
   tyre:currentStint?.compound||last?.compound||'UNKNOWN',tyre_age:last?.tyre_life??null,
   stops:(race.pit_stops||[]).filter(p=>p.driver_code===result.driver_code&&(final||p.lap_number<=(last?.lap_number||0))).length,
   personal_sectors:[1,2,3].map(n=>{const values=laps.map(l=>l['duration_sector_'+n]).filter(v=>Number.isFinite(v)&&v>0);return values.length?Math.min(...values):null})};
 });
 rows.sort((a,b)=>(a.display_position??999)-(b.display_position??999)||b.completed_laps-a.completed_laps||a.position-b.position);
 return {rows,cutoff,clock:lap===0?0:Math.max(0,cutoff-offset),bestSectors,frame:lap,final,dataGap,referenceLap,reconciled_endpoints:reconciledEnd.size,quarantined_endpoints:quarantined.size};
}
