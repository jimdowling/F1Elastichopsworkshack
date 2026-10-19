import React,{useEffect,useRef,useState} from 'react';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {LoaderCircle,AlertTriangle,Move3D,MousePointer2} from 'lucide-react';
import {makeWorld,buildCircuit,buildCar,disposeScene} from './sceneGeometry.js';

const UP=new THREE.Vector3(0,1,0),FORWARD=new THREE.Vector3(0,0,1);
function liteCar(color){
 const group=new THREE.Group(),paint=new THREE.MeshLambertMaterial({color}),carbon=new THREE.MeshLambertMaterial({color:'#121b20'});
 const box=(w,h,d,x,y,z,m)=>{const mesh=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),m);mesh.position.set(x,y,z);group.add(mesh)};
 box(.95,.65,3.8,0,.55,-.1,paint);box(.35,.2,1.6,0,.35,1.8,paint);box(2.1,.14,.7,0,.25,2.35,carbon);box(1.95,.25,.65,0,1.25,-2.1,paint);
 for(const x of [-1.0,1.0])for(const z of [-1.5,1.5])box(.38,.7,.75,x,.4,z,carbon);
 return group;
}
export default function FleetScene({reference,vehicles,motions,selected,focus,cameraMode,playing,rate,time,mode,onFocus,onFallback}){
 const host=useRef(null),canvas=useRef(null),current=useRef(null);const[ready,setReady]=useState(false),[error,setError]=useState(null);
 current.current={motions,selected,focus,cameraMode,playing,rate,time,onFocus};const identity=vehicles.map(v=>v.code).join(',');
 useEffect(()=>{
  let renderer,scene,controls,frame,observer,disposed=false;const el=canvas.current,node=host.current;if(!el||!node)return;
  setReady(false);setError(null);
  const lost=e=>{e.preventDefault();if(!disposed)setError('The graphics context was interrupted. The synchronized 2D map remains available.')};el.addEventListener('webglcontextlost',lost);
  let cleanup=()=>{};
  try{
   renderer=new THREE.WebGLRenderer({canvas:el,antialias:true,powerPreference:'high-performance'});renderer.setPixelRatio(Math.min(devicePixelRatio||1,1.35));renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.1;
   // Field overview uses low-detail cars and no shadow map; the followed car retains full geometry.
   renderer.shadowMap.enabled=mode==='ghost';renderer.shadowMap.type=THREE.PCFSoftShadowMap;
   scene=new THREE.Scene();scene.background=new THREE.Color('#a8c8d7');scene.fog=new THREE.FogExp2('#a8c8d7',.00018);
   scene.add(new THREE.HemisphereLight('#e8f4ff','#60734d',2.6));const sun=new THREE.DirectionalLight('#fff0db',3);sun.position.set(-180,330,-130);sun.castShadow=mode==='ghost';sun.shadow.mapSize.set(1024,1024);sun.shadow.camera.left=-55;sun.shadow.camera.right=55;sun.shadow.camera.top=55;sun.shadow.camera.bottom=-55;sun.shadow.camera.near=50;sun.shadow.camera.far=1000;sun.shadow.normalBias=.04;scene.add(sun,sun.target);
   const world=makeWorld(reference,reference);scene.add(buildCircuit(world,{flat:mode==='race',scenery:mode!=='race'}));const extent=Math.max(world.size.x,world.size.z),road=world.road.getSpacedPoints(360);
   const camera=new THREE.PerspectiveCamera(48,1,.3,6000);controls=new OrbitControls(camera,el);controls.enableDamping=true;controls.dampingFactor=.1;controls.minDistance=9;controls.maxDistance=2400;controls.maxPolarAngle=Math.PI*.49;controls.screenSpacePanning=false;
   const cars=new Map();for(const v of vehicles){const root=new THREE.Group(),full=buildCar(v.code,v.color,'HARD',String(v.number||'')),lite=liteCar(v.color);
    root.add(full.group,lite);root.add(full.label);full.label.position.y=3;root.userData.code=v.code;
    const ring=new THREE.Mesh(new THREE.RingGeometry(2.2,3.2,24),new THREE.MeshBasicMaterial({color:v.color,side:THREE.DoubleSide,transparent:true,opacity:.8}));ring.rotation.x=-Math.PI/2;ring.position.y=.09;root.add(ring);scene.add(root);
    cars.set(v.code,{root,full,lite,ring,tangent:new THREE.Vector3(0,0,1),point:new THREE.Vector3(),initialized:false,ghost:false});
   }
   const q=new THREE.Quaternion(),offset=new THREE.Vector3(),targetOffset=new THREE.Vector3(),desired=new THREE.Vector3(),target=new THREE.Vector3(),side=new THREE.Vector3(),look=new THREE.Vector3();
   let last=performance.now(),lastTime=-1,lastMode='',lastFocus='',lastSelection='',settle=30,dirty=true,hidden=document.hidden;
   const resize=()=>{renderer.setSize(Math.max(1,node.clientWidth),Math.max(1,node.clientHeight),false);camera.aspect=Math.max(1,node.clientWidth)/Math.max(1,node.clientHeight);camera.updateProjectionMatrix();settle=30};observer=new ResizeObserver(resize);observer.observe(node);resize();
   controls.addEventListener('change',()=>{dirty=true});
   const visibility=()=>{hidden=document.hidden;last=performance.now();settle=30};document.addEventListener('visibilitychange',visibility);
   const ray=new THREE.Raycaster(),pointer=new THREE.Vector2();let down=null;
   const pointerDown=e=>{down=[e.clientX,e.clientY]};
   const pointerUp=e=>{if(!down||Math.hypot(e.clientX-down[0],e.clientY-down[1])>5)return;const rect=el.getBoundingClientRect();pointer.set((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1);ray.setFromCamera(pointer,camera);const hits=ray.intersectObjects([...cars.values()].filter(c=>c.root.visible).map(c=>c.root),true);if(hits.length){let o=hits[0].object;while(o&&!o.userData.code)o=o.parent;if(o?.userData.code)current.current.onFocus(o.userData.code)}};
   el.addEventListener('pointerdown',pointerDown);el.addEventListener('pointerup',pointerUp);
   cleanup=()=>{document.removeEventListener('visibilitychange',visibility);el.removeEventListener('pointerdown',pointerDown);el.removeEventListener('pointerup',pointerUp)};
   const animate=now=>{
    if(disposed)return;frame=requestAnimationFrame(animate);const s=current.current,dt=Math.min(.065,Math.max(.001,(now-last)/1000));last=now;if(!s||hidden)return;
    const selectionChanged=s.selected.join(',')!==lastSelection;lastSelection=s.selected.join(',');
    const changed=Math.abs(s.time-lastTime)>.00001,jump=Math.abs(s.time-lastTime)>Math.max(.7,s.rate*.15),active=new Set(s.selected),by=Object.fromEntries(s.motions.map(m=>[m.code,m]));let visible=0;
    for(const [code,c] of cars){const m=by[code];c.root.visible=active.has(code)&&!!m?.available;if(!c.root.visible)continue;visible++;
     c.point.copy(world.worldPoint(m.x,m.y,.045));c.root.position.copy(c.point);
     if(Math.hypot(m.dx||0,m.dy||0)>1e-5)c.tangent.set(m.dx,0,-m.dy).normalize();
     else if(!c.initialized){let idx=0,best=Infinity;for(let j=0;j<road.length;j++){const d=road[j].distanceToSquared(c.point);if(d<best){best=d;idx=j}}c.tangent.copy(world.road.getTangentAt(idx/(road.length-1))).normalize()}
     q.setFromUnitVectors(FORWARD,c.tangent);if(jump||!c.initialized)c.root.quaternion.copy(q);else c.root.quaternion.slerp(q,1-Math.exp(-dt*18*Math.max(1,s.rate)));c.initialized=true;
     if(s.playing&&m.telemetryAvailable&&!m.finished)c.full.wheels.forEach(w=>w.rotation.x=(w.rotation.x+(m.speed||0)/3.6/.365*dt*s.rate)%(Math.PI*2));
    }
    const focused=cars.get(s.focus),hasFocus=focused?.root.visible,cam=hasFocus?s.cameraMode:'overview',reframe=cam!==lastMode||s.focus!==lastFocus;
    if(reframe){controls.enabled=cam==='overview';el.style.touchAction=cam==='overview'?'none':'pan-y';camera.near=cam==='overview'?3:.3;camera.updateProjectionMatrix();settle=30;
     if(cam==='overview'){controls.target.set(0,0,0);camera.position.set(extent*.48,extent*.89,extent*.53);camera.lookAt(controls.target);controls.update()}
     lastMode=cam;lastFocus=s.focus;
    }
    if(cam==='chase'){
     const m=by[s.focus],forward=focused.tangent;side.crossVectors(forward,UP).normalize();desired.copy(forward).multiplyScalar(-(17+(m.speed||0)*.012)).addScaledVector(side,2.5);desired.y=6.4;target.copy(forward).multiplyScalar(12);target.y=1.2;
     if(reframe||jump){offset.copy(desired);targetOffset.copy(target)}else{offset.lerp(desired,1-Math.exp(-dt*9*Math.max(1,s.rate)));targetOffset.lerp(target,1-Math.exp(-dt*12*Math.max(1,s.rate)))}
     camera.position.copy(focused.point).add(offset);look.copy(focused.point).add(targetOffset);camera.lookAt(look);
    }else controls.update();
    for(const [code,c] of cars){if(!c.root.visible)continue;const distance=camera.position.distanceTo(c.point),detail=cam==='chase'&&(code===s.focus||distance<70);c.full.group.visible=detail;c.lite.visible=!detail;
     const ghost=mode==='ghost'&&cam==='chase'&&code!==s.focus;if(ghost!==c.ghost){for(const obj of [c.full.group,c.lite])obj.traverse(o=>{if(o.isMesh)for(const mat of Array.isArray(o.material)?o.material:[o.material]){mat.transparent=ghost;mat.opacity=ghost?.38:1;mat.depthWrite=!ghost;mat.needsUpdate=true}});c.ghost=ghost}
     c.full.label.visible=cam==='overview'||code!==s.focus;const f=cam==='overview'?Math.max(2,distance*.025):Math.max(1,distance*.013);c.full.label.scale.set(1.9*f,.71*f,1);c.full.label.position.y=cam==='overview'?12:3.1;c.ring.visible=cam==='overview';c.ring.scale.setScalar(Math.max(1,distance*.0025));
    }
    if(hasFocus){sun.position.copy(focused.point).add(new THREE.Vector3(-180,330,-130));sun.target.position.copy(focused.point)}
    if(changed||reframe||selectionChanged)settle=15;
    if(changed||s.playing||dirty||settle>0){renderer.render(scene,camera);el.dataset.ready='true';el.dataset.vehicles=String(s.selected.length);el.dataset.visibleCars=String(visible);el.dataset.focus=s.focus;el.dataset.camera=cam;el.dataset.clock=s.time.toFixed(3);el.dataset.source=mode==='race'?'shared-session-xy':'independent-ghosts';dirty=false;settle--;}
    lastTime=s.time;
   };
   frame=requestAnimationFrame(animate);setReady(true);
  }catch(e){setError('WebGL could not initialize. Switch to the recorded-position 2D map; the data and playback controls are unchanged.')}
  return()=>{disposed=true;cancelAnimationFrame(frame);observer?.disconnect();cleanup();controls?.dispose();el.removeEventListener('webglcontextlost',lost);if(scene)disposeScene(scene);if(renderer){renderer.dispose();renderer.forceContextLoss()}};
 },[reference,identity,mode]);
 return <div ref={host} className="telemetry-scene fleet-scene"><canvas ref={canvas} className="fleet-3d-canvas" aria-label={`${mode==='race'?'Synchronized race':'Multi-car ghost'} 3D map at Zandvoort`}/>{!ready&&!error&&<div className="scene-loading"><LoaderCircle className="spin" size={24}/><span>Building the multi-car view…</span><small>Local geometry · adaptive car detail</small></div>}{error&&<div className="scene-error"><AlertTriangle size={25}/><h3>3D is unavailable</h3><p>{error}</p><button className="btn primary" onClick={onFallback}>Continue in 2D</button></div>}{ready&&!error&&<><div className="scene-location"><span className="scene-live-dot"/>ZANDVOORT<span>{mode==='race'?'SHARED-CLOCK POSITION REPLAY':'INDEPENDENT LAP COMPARISON'}</span></div><div className="scene-view-label"><Move3D size={13}/>{cameraMode==='overview'||!motions.find(m=>m.code===focus)?.available?'CIRCUIT OVERVIEW':'CHASE'}<span>{focus}</span></div>{cameraMode==='overview'&&<div className="orbit-instructions"><MousePointer2 size={12}/>Drag / zoom · click a car to follow</div>}<div className="scene-credit">RECORDED XY<span>Flat elevation · illustrative road & cars</span></div></>}</div>;
}
