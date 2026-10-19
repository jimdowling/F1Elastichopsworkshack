import React,{useState,useEffect,useRef} from 'react';
import {CalendarDays,ChevronRight,Database,Flag} from 'lucide-react';
import {DashContext,useRemote,useDebounced,Busy,LoadError,Badge,Note} from './ui.jsx';
import {Home,Calendar,Results,Standings,Drivers,Teams,DriverStats,Consistency,HeadToHead} from './SeasonPages.jsx';
import {RacePace,Tyres,PitStops,Weather,RaceControl,TrackDNA} from './RacePages.jsx';
import {Timing} from './Timing.jsx';
import {Workbench} from './Workbench.jsx';
import {Connections} from './Connections.jsx';
import {shortGP,flag} from './model.js';
import './dashboard.css';

function savedScope(){try{const v=JSON.parse(localStorage.getItem('pitlane-archive-scope'));if([2023,2024].includes(v?.year)&&Number.isInteger(v.round)&&v.round>=1&&v.round<=(v.year===2023?22:24))return v}catch{}return {year:2024,round:15}}
const NEED_RACE=['dashboard','timing','race-pace','tyres','race-control'];
export default function Dashboard({page,navigate,boot,Chart,Track,openPipeline,connectionStatus}){
 const[preferences,setPreferences]=useState({});
 const[scope,setScope]=useState(savedScope),[clean,setClean]=useState(true),[cutoff,setCutoff]=useState(1.07),[focusDriver,setFocusDriver]=useState('norris'),[focusTeam,setFocusTeam]=useState('mclaren'),[compare,setCompare]=useState(['norris','piastri']);const{year,round}=scope;
 const debouncedCutoff=useDebounced(cutoff),catalogRemote=useRemote(page==='connections'?null:'/api/dashboard/catalog');
 const seasonRemote=useRemote(catalogRemote.data?`/api/dashboard/season?season=${year}&round=${round}`:null);
 const needRace=NEED_RACE.includes(page),raceRemote=useRemote(catalogRemote.data&&needRace?(page==='timing'?`/api/dashboard/timing?season=${year}&round=${round}`:`/api/dashboard/race?season=${year}&round=${round}&clean=${clean}&cutoff=${debouncedCutoff}`):null);
 const previousRace=useRef(null),key=`${year}-${round}-${connectionStatus?.modes?.data}-${connectionStatus?.modes?.features}`;if(raceRemote.data)previousRace.current={key,data:raceRemote.data};
 const race=raceRemote.data||(previousRace.current?.key===key?previousRace.current.data:null);
 useEffect(()=>{try{localStorage.setItem('pitlane-archive-scope',JSON.stringify(scope))}catch{}},[scope]);
 const setRound=r=>setScope(s=>({...s,round:Number(r)}));
 const setYear=y=>{const newYear=Number(y),all=catalogRemote.data?.events||[],old=all.find(e=>e.season===year&&e.round_number===round),matching=all.find(e=>e.season===newYear&&e.circuit_id===old?.circuit_id);setScope({year:newYear,round:matching?.round_number||(all.some(e=>e.season===newYear&&e.round_number===round)?round:all.find(e=>e.season===newYear)?.round_number)||Math.min(round,newYear===2023?22:24)})};
 const catalog=catalogRemote.data,events=(catalog?.events||[]).filter(e=>e.season===year),event=events.find(e=>e.round_number===round);
 const ctx={connectionStatus,year,round,setYear,setRound,catalog,data:seasonRemote.data,race,clean,setClean,cutoff,setCutoff,filterLoading:raceRemote.loading||cutoff!==debouncedCutoff,
  preferences,setPreferences,focusDriver,setFocusDriver:id=>{setFocusDriver(id);setPreferences(p=>({...p,'driver-stat-mode':'profile'}))},focusTeam,setFocusTeam,compare,setCompare,navigate,Chart,Track,boot,openPipeline};
 let content;const err=catalogRemote.error||seasonRemote.error||(needRace?raceRemote.error:null);
 if(page==='connections')content=<Connections/>;
 else if(err)content=<><LoadError error={err} retry={()=>{catalogRemote.retry();seasonRemote.retry();raceRemote.retry()}}/><button className="db-button" onClick={()=>navigate('connections')}>Open Connections / unlock or change source</button></>;
 else if(!catalog||!seasonRemote.data||needRace&&!race)content=<Busy/>;
 else switch(page){
  case 'timing':content=<Timing/>;break;case 'calendar':content=<Calendar/>;break;case 'results':content=<Results/>;break;
  case 'driver-standings':content=<Standings key="drivers"/>;break;case 'constructor-standings':content=<Standings key="teams" constructors/>;break;
  case 'drivers':content=<Drivers/>;break;case 'teams':content=<Teams/>;break;case 'driver-stats':content=<DriverStats/>;break;
  case 'head-to-head':content=<HeadToHead/>;break;case 'consistency':content=<Consistency/>;break;case 'race-pace':content=<RacePace/>;break;
  case 'pit-stops':content=<PitStops/>;break;case 'tyres':content=<Tyres/>;break;case 'weather':content=<Weather/>;break;
  case 'race-control':content=<RaceControl/>;break;case 'track-dna':content=<TrackDNA/>;break;case 'data':content=<Workbench/>;break;
  default:content=<Home/>;
 }
 return <DashContext.Provider value={ctx}><div className="dashboard-workspace">
  <div className="db-scope-bar"><div className="db-scope-label"><Database size={14}/><span>{connectionStatus?.modes?.data==='hopsworks'?'HOPSWORKS EVENT DATA':'PUBLIC ARCHIVE'}</span><i/><b>2023–2024</b></div><div className="db-scope-controls"><label><CalendarDays size={14}/><span>Season</span><select aria-label="Archive season" value={year} onChange={e=>setYear(e.target.value)} disabled={!catalog}>{(catalog?.seasons||[2024,2023]).slice().sort((a,b)=>b-a).map(y=><option key={y} value={y}>{y}</option>)}</select></label><label className="db-event-select"><Flag size={14}/><select aria-label="Grand Prix" value={round} onChange={e=>setRound(e.target.value)} disabled={!catalog}>{events.map(e=><option key={e.id} value={e.round_number}>R{String(e.round_number).padStart(2,'0')} · {flag(e.country)} {shortGP(e.event_name)}</option>)}</select></label><button className="db-season-end" disabled={!catalog||round===Math.max(...events.map(e=>e.round_number),0)} onClick={()=>setRound(Math.max(...events.map(e=>e.round_number),1))} title="View the final round and final championship standings">Season end <ChevronRight size={12}/></button></div></div>
  <div className="db-snapshot-caption"><span>CHAMPIONSHIP CUTOFF <b>AFTER ROUND {round}</b></span><span>Session analyses use this GP · 3D / ML labs keep their original Dutch GP scope</span></div>
  <div className="db-page-content" data-dashboard-page={page}>{connectionStatus?.offline_fixture&&<Note tone="orange">OFFLINE QA FIXTURE — simulated provider responses, not a live Hopsworks account.</Note>}{page!=='connections'&&connectionStatus?.modes?.data==='hopsworks'&&<Note tone="orange">{page==='timing'?'Historical timing stays on the public OpenF1/Jolpica reference. The native event lap feature group does not supply synchronized lap timestamps.':`${events.filter(e=>e.round_number<=round).length} / ${round} GP rounds available at this cutoff; missing rounds are not filled. Hopsworks event feature groups power Race/Qualifying results, laps and weather. Public supplements: Sprint points, venue/profile metadata, result timing, qualifying segments, speed traps, pit-lane visits and race control. Derived stints are contiguous native lap segments.`}</Note>}{content}</div>
 </div></DashContext.Provider>;
}
