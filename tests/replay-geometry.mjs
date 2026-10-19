import fs from 'node:fs';
import path from 'node:path';
import {makeWorld,ROAD_WIDTH,CIRCUIT_LENGTH} from '../frontend/src/replay/sceneGeometry.js';
const root=path.resolve(import.meta.dirname,'..');
const ghosts=JSON.parse(fs.readFileSync(path.join(root,'data/ghosts.json'),'utf8'));
const checks=[],metrics=[];
function check(name,condition){checks.push({name,passed:Boolean(condition)});if(!condition)throw new Error(name)}
try{
 for(const a of Object.keys(ghosts))for(const b of Object.keys(ghosts).filter(b=>b!==a)){
  const A=ghosts[a],B=ghosts[b],w=makeWorld(A,B),n=A.trace.x.length;
  const samples=w.road.getSpacedPoints(1500);let maxOffRoad=0,maxNodeError=0,rawLength=0;
  for(let i=0;i<n;i++){
   const p=w.trajectoryA.getPoint(i/(n-1)),expected=w.worldPoint(A.trace.x[i],A.trace.y[i],.045);
   maxNodeError=Math.max(maxNodeError,p.distanceTo(expected));
   const q=w.trajectoryB.getPoint(i/(n-1)),expectedB=w.worldPoint(B.trace.x[i],B.trace.y[i],.045);
   maxNodeError=Math.max(maxNodeError,q.distanceTo(expectedB));
   maxOffRoad=Math.max(maxOffRoad,Math.min(...samples.map(r=>Math.hypot(r.x-q.x,r.z-q.z))));
   if(i)rawLength+=Math.hypot(A.trace.x[i]-A.trace.x[i-1],A.trace.y[i]-A.trace.y[i-1]);
  }
  check(`${a}/${b}: both paths pass through all 361 measured XY samples`,maxNodeError<1e-7);
  check(`${a}/${b}: physical reference polyline scales to 4,259 m`,Math.abs(rawLength*w.scale-CIRCUIT_LENGTH)<1e-7);
  check(`${a}/${b}: closed road, non-looping lap trajectories`,w.road.closed&&!w.trajectoryA.closed&&!w.trajectoryB.closed);
  check(`${a}/${b}: both recorded trajectories stay within the illustrative road`,maxOffRoad<ROAD_WIDTH/2);
  metrics.push({pair:`${a}/${b}`,max_sample_error_m:maxNodeError,max_b_distance_from_reference_line_m:maxOffRoad,spline_length_m:w.road.getLength()});
 }
}catch(e){console.error(e);process.exitCode=1}
finally{
 const result={run_at:new Date().toISOString(),checks,metrics};fs.writeFileSync(path.join(root,'qa/replay-geometry-results.json'),JSON.stringify(result,null,2));
 console.log(JSON.stringify({passed:checks.filter(c=>c.passed).length,failed:checks.filter(c=>!c.passed).length,max_observed_road_offset_m:Math.max(...metrics.map(m=>m.max_b_distance_from_reference_line_m))},null,2));
}
