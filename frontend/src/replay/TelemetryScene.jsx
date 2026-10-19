import React, {useEffect, useRef, useState} from 'react';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {LoaderCircle, Move3D, AlertTriangle, MousePointer2} from 'lucide-react';
import {makeWorld,buildCircuit,buildCar,disposeScene} from './sceneGeometry.js';

const FORWARD=new THREE.Vector3(0,0,1),UP=new THREE.Vector3(0,1,0);
const COLORS=['#d7ff62','#7ca7ff'];
const clamp=THREE.MathUtils.clamp;

export default function TelemetryScene({a,b,motionA,motionB,playing,rate,cameraMode='follow-a',onFallback}) {
  const hostRef=useRef(null),canvasRef=useRef(null),state=useRef(null);
  const [ready,setReady]=useState(false),[error,setError]=useState(null);
  state.current={a,b,motionA,motionB,playing,rate,cameraMode};
  useEffect(()=>{
    const host=hostRef.current,canvas=canvasRef.current;
    if(!host||!canvas)return;
    let renderer,controls,frame,observer,disposed=false,scene;
    const onLost=e=>{e.preventDefault();if(!disposed)setError('The 3D graphics context was interrupted. The 2D replay is still available.');};
    canvas.addEventListener('webglcontextlost',onLost);
    setReady(false);setError(null);
    try {
      renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:false,powerPreference:'high-performance'});
      renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.6));
      renderer.outputColorSpace=THREE.SRGBColorSpace;
      renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.12;
      renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
      scene=new THREE.Scene();scene.background=new THREE.Color('#a5c6d4');scene.fog=new THREE.FogExp2('#a5c6d4',.00024);
      const camera=new THREE.PerspectiveCamera(49,1,.15,5000);
      scene.add(new THREE.HemisphereLight('#d9ecff','#697c46',2.35));
      const sun=new THREE.DirectionalLight('#fff1d8',3.2);sun.castShadow=true;sun.shadow.mapSize.set(1536,1536);
      sun.shadow.camera.left=-65;sun.shadow.camera.right=65;sun.shadow.camera.top=65;sun.shadow.camera.bottom=-65;
      sun.shadow.camera.near=50;sun.shadow.camera.far=1000;sun.shadow.normalBias=.035;sun.shadow.bias=-.00008;
      scene.add(sun,sun.target);
      const world=makeWorld(a,b),circuit=buildCircuit(world);scene.add(circuit);
      const cars=[buildCar(a.driver,COLORS[0],a.compound,a.driver==='NOR'?'4':a.driver==='VER'?'1':a.driver==='LEC'?'16':'81'),buildCar(b.driver,COLORS[1],b.compound,b.driver==='NOR'?'4':b.driver==='VER'?'1':b.driver==='LEC'?'16':'81')];
      cars.forEach(c=>scene.add(c.group));
      controls=new OrbitControls(camera,canvas);controls.enableDamping=true;controls.dampingFactor=.09;
      controls.minDistance=9;controls.maxDistance=2200;controls.maxPolarAngle=Math.PI*.485;
      controls.screenSpacePanning=false;controls.enablePan=true;controls.rotateSpeed=.65;controls.zoomSpeed=.8;
      const extent=Math.max(world.size.x,world.size.z);
      let lastMode='',lastTime=performance.now(),settle=30,lastProgress=-1,first=true,hidden=document.hidden;
      const pose=[new THREE.Vector3(),new THREE.Vector3()],tangent=[new THREE.Vector3(),new THREE.Vector3()];
      const quaternion=new THREE.Quaternion(),desiredCamera=new THREE.Vector3(),desiredTarget=new THREE.Vector3(),lookTarget=new THREE.Vector3(),side=new THREE.Vector3(),followOffset=new THREE.Vector3(),lookOffset=new THREE.Vector3();
      let controlsDirty=true;controls.addEventListener('change',()=>{controlsDirty=true});
      const resize=()=>{
        const width=Math.max(1,host.clientWidth),height=Math.max(1,host.clientHeight);
        renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();settle=30;
      };
      observer=new ResizeObserver(resize);observer.observe(host);resize();
      const visibility=()=>{hidden=document.hidden;lastTime=performance.now();if(!hidden)settle=30;};
      document.addEventListener('visibilitychange',visibility);
      const updateCar=(i,motion,dt,active,speed)=>{
        const path=i?world.trajectoryB:world.trajectoryA,progress=clamp(motion.distance,0,1);
        path.getPoint(progress,pose[i]);path.getTangent(progress,tangent[i]).normalize();
        const car=cars[i];car.group.position.copy(pose[i]);
        quaternion.setFromUnitVectors(FORWARD,tangent[i]);
        if(first||Math.abs(progress-lastProgress)>.05)car.group.quaternion.copy(quaternion);
        else car.group.quaternion.slerp(quaternion,1-Math.exp(-dt*17*Math.max(1,speed)));
        const before=path.getTangent(clamp(progress-.0007,0,1)),after=path.getTangent(clamp(progress+.0007,0,1));
        const cross=before.x*after.z-before.z*after.x;
        const curvature=-Math.asin(clamp(cross,-1,1))/(.0014*4259);
        const steer=clamp(Math.atan(3.15*curvature),-.48,.48);
        car.frontPivots.forEach(p=>p.rotation.y=THREE.MathUtils.damp(p.rotation.y,steer,12,dt));
        const lean=clamp((motion.speed/3.6)**2*curvature*.0008,-.025,.025);
        car.chassis.rotation.z=THREE.MathUtils.damp(car.chassis.rotation.z,lean,9,dt);
        if(active&&!motion.finished)car.wheels.forEach(w=>w.rotation.x=(w.rotation.x+motion.speed/3.6/.365*dt*speed)%(Math.PI*2));
        car.rearLight.material.emissiveIntensity=.65;
      };
      const animate=now=>{
        if(disposed)return;frame=requestAnimationFrame(animate);
        const s=state.current,dt=Math.min(.06,Math.max(.001,(now-lastTime)/1000));lastTime=now;
        if(!s?.motionA||hidden)return;
        const changed=Math.abs(s.motionA.distance-lastProgress)>1e-7;
        if(Math.abs(s.motionA.distance-lastProgress)>.04)first=true;
        updateCar(0,s.motionA,dt,s.playing,s.rate);updateCar(1,s.motionB,dt,s.playing,s.rate);
        const mode=s.cameraMode,focus=mode==='follow-b'?1:0;
        if(mode!==lastMode){
          controls.enabled=mode==='orbit';canvas.style.touchAction=mode==='orbit'?'none':'pan-y';settle=40;
          camera.near=mode==='orbit'?5:.35;camera.far=mode==='orbit'?5000:3000;camera.updateProjectionMatrix();
          cars.forEach((car,i)=>car.group.traverse(obj=>{if(obj.isMesh&&obj.material){const ghost=mode!=='orbit'&&i!==focus;for(const m of (Array.isArray(obj.material)?obj.material:[obj.material])){m.transparent=ghost;m.opacity=ghost?.40:1;m.depthWrite=!ghost;m.needsUpdate=true;}}}));
          if(mode==='orbit'){
            controls.target.set(0,0,0);camera.position.set(extent*.52,extent*.88,extent*.62);camera.lookAt(controls.target);controls.update();
          } else first=true;
          lastMode=mode;
        }
        if(mode!=='orbit'){
          const current=focus?s.motionB:s.motionA,forward=tangent[focus];side.crossVectors(forward,UP).normalize();
          desiredCamera.copy(pose[focus]).addScaledVector(forward,-(16+current.speed*.014)).addScaledVector(side,2.6);desiredCamera.y+=5.9;
          desiredTarget.copy(pose[focus]).addScaledVector(forward,11);desiredTarget.y+=1.05;
          desiredCamera.sub(pose[focus]);desiredTarget.sub(pose[focus]);
          if(first){followOffset.copy(desiredCamera);lookOffset.copy(desiredTarget);}else{
            followOffset.lerp(desiredCamera,1-Math.exp(-dt*7.5*Math.max(1,s.rate)));lookOffset.lerp(desiredTarget,1-Math.exp(-dt*10*Math.max(1,s.rate)));
          }
          camera.position.copy(pose[focus]).add(followOffset);lookTarget.copy(pose[focus]).add(lookOffset);camera.lookAt(lookTarget);
        }else controls.update();
        cars.forEach((c,i)=>{c.label.visible=mode==='orbit'||i!==focus;c.label.material.opacity=.92;const factor=mode==='orbit'?camera.position.distanceTo(c.group.position)*.029:1;c.label.scale.set(1.9*factor,.71*factor,1);c.label.position.y=mode==='orbit'?10:2.5;});
        // Local moving shadow frustum around the foreground car, not a huge low-resolution circuit shadow.
        sun.position.copy(pose[focus]).add(new THREE.Vector3(-180,330,-130));sun.target.position.copy(pose[focus]);
        if(changed)settle=30;
        if(s.playing||changed||controlsDirty||settle>0||first){
          renderer.render(scene,camera);canvas.dataset.ready='true';canvas.dataset.camera=mode;
          canvas.dataset.distanceA=s.motionA.distance.toFixed(4);canvas.dataset.distanceB=s.motionB.distance.toFixed(4);
          canvas.dataset.drawCalls=String(renderer.info.render.calls);
          if(first)setReady(true);
          controlsDirty=false;settle--;
        }
        lastProgress=s.motionA.distance;first=false;
      };
      frame=requestAnimationFrame(animate);
      return ()=>{
        disposed=true;cancelAnimationFrame(frame);observer?.disconnect();controls?.dispose();
        document.removeEventListener('visibilitychange',visibility);canvas.removeEventListener('webglcontextlost',onLost);
        disposeScene(scene);renderer.dispose();renderer.forceContextLoss();
      };
    }catch(e){
      if(!disposed)setError('3D requires WebGL 2. Your browser could not initialize it. You can continue with the full 2D replay.');
      observer?.disconnect();controls?.dispose();if(scene)disposeScene(scene);renderer?.dispose();
      return ()=>{disposed=true;cancelAnimationFrame(frame);canvas.removeEventListener('webglcontextlost',onLost);};
    }
  },[a.driver,a.lap_number,b.driver,b.lap_number]);

  return <div className="telemetry-scene" ref={hostRef}>
    <canvas ref={canvasRef} className="replay-3d-canvas" aria-label={`3D telemetry replay of ${a.driver} and ${b.driver} at Zandvoort`} data-testid="replay-3d-canvas"/>
    {!ready&&!error&&<div className="scene-loading"><LoaderCircle size={23} className="spin"/><span>Building your trackside view…</span><small>Local 3D models · no external assets</small></div>}
    {error&&<div className="scene-error"><AlertTriangle size={25}/><h3>3D is unavailable in this browser</h3><p>{error}</p><button className="btn primary" onClick={onFallback}>Continue in 2D</button></div>}
    {ready&&!error&&<>
      <div className="scene-location"><span className="scene-live-dot"/> ZANDVOORT<span>2024 · HISTORICAL REPLAY</span></div>
      <div className="scene-view-label"><Move3D size={13}/>{cameraMode==='orbit'?'CIRCUIT / ORBIT':`CHASE · GHOST ${cameraMode==='follow-b'?'B':'A'}`}<span>{cameraMode==='follow-b'?b.driver:a.driver}</span></div>
      {cameraMode==='orbit'&&<div className="orbit-instructions"><MousePointer2 size={12}/>Drag to orbit · scroll / pinch to zoom</div>}
      <div className="scene-credit">REAL XY TELEMETRY<span>Illustrative road, cars & scenery</span></div>
    </>}
  </div>;
}
