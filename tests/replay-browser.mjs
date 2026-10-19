import {chromium} from '../frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
const root=path.resolve(import.meta.dirname,'..');
const base=process.env.PITLANE_TEST_URL||'http://127.0.0.1:8000';
const checks=[],errors=[],external=[],requests=[],measurements={};
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader','--disable-dev-shm-usage']});
const page=await browser.newPage({viewport:{width:1440,height:1050},deviceScaleFactor:1});
page.setDefaultTimeout(30000);
page.on('pageerror',e=>errors.push(e.message));
page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
page.on('request',r=>requests.push(r.url()));
await page.route('**/*',route=>{
 const u=new URL(route.request().url());
 if(u.protocol.startsWith('http')&&u.origin!==new URL(base).origin){external.push(u.href);return route.abort()}
 return route.continue();
});
// Instrument browser-native nodes from the test, not with production-only test hooks.
await page.addInitScript(()=>{
 window.__audioContexts=[];
 const Native=window.AudioContext;
 window.AudioContext=class AuditedContext extends Native{
  constructor(...args){super(...args);this.testAnalysers=[];this.testOsc=[];this.testGains=[];this.testSources=[];this.testTargets=[];window.__audioContexts.push(this)}
  createAnalyser(){const n=super.createAnalyser();this.testAnalysers.push(n);return n}
  createGain(){const n=super.createGain();this.testGains.push(n);return n}
  createBufferSource(){const n=super.createBufferSource();this.testSources.push(n);return n}
  createOscillator(){
   const n=super.createOscillator(),id=this.testOsc.length;this.testOsc.push(n);
   const schedule=n.frequency.setTargetAtTime.bind(n.frequency);
   n.frequency.setTargetAtTime=(value,time,tau)=>{this.testTargets.push({id,value,time,tau});if(this.testTargets.length>8000)this.testTargets.splice(0,2000);return schedule(value,time,tau)};
   return n;
  }
 };
});
const check=(name,condition=true)=>{checks.push({name,passed:Boolean(condition)});if(!condition)throw new Error(name)};
const shot=async name=>page.screenshot({path:path.join(root,'qa',name+'.png'),fullPage:!(await page.locator('.replay-stage.theatre').count()),animations:'disabled'});
const ready=()=>page.waitForFunction(()=>document.querySelector('.replay-3d-canvas')?.dataset.ready==='true');
const hash=buf=>crypto.createHash('sha256').update(buf).digest('hex');
const canvas=()=>page.locator('.replay-3d-canvas');
const range=async(label,value)=>page.getByRole('slider',{name:label,exact:true}).evaluate((el,v)=>{
 Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,v);
 el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));
},String(value));
const progress=async()=>+await page.getByRole('slider',{name:'Replay position',exact:true}).inputValue();
const waitAudio=()=>page.waitForTimeout(600);
const audio=()=>page.evaluate(()=>{
 const c=window.__audioContexts.at(-1);if(!c)return {contexts:0};
 const a=c.testAnalysers[0],data=new Float32Array(a.fftSize);a.getFloatTimeDomainData(data);
 const body=new Map(c.testTargets.filter(t=>t.id===1).map(t=>[t.time,t.value]));
 const ratios=c.testTargets.filter(t=>t.id===0&&body.has(t.time)).map(t=>t.value/body.get(t.time));
 return {contexts:__audioContexts.length,state:c.state,rms:Math.sqrt(data.reduce((s,x)=>s+x*x,0)/data.length),peak:Math.max(...data.map(Math.abs)),frequency:c.testOsc.map(n=>n.frequency.value),gains:c.testGains.slice(0,7).map(n=>n.gain.value),sources:c.testSources.length,shiftRatioMin:Math.min(...ratios),shiftRatioMax:Math.max(...ratios)};
});
try{
 await page.goto(base+'/#overview',{waitUntil:'networkidle'});
 check('Three.js scene is lazy-loaded, not requested by Overview',!requests.some(u=>u.includes('/TelemetryScene-')));
 await page.locator('.sidebar nav .nav-item').filter({hasText:'Ghost Lap'}).click();await page.getByRole('tab',{name:'Two-car detail',exact:true}).click();await ready();
 check('Ghost Lap initializes a real WebGL 2 scene',await canvas().evaluate(c=>{const gl=c.getContext('webgl2');return Boolean(gl&&!gl.isContextLost()&&Number(c.dataset.drawCalls)>100)}));
 check('3D scene chunk loads on demand',requests.some(u=>u.includes('/TelemetryScene-')));
 check('Audio does not initialize or autoplay on page load',(await audio()).contexts===0);
 check('Replay starts paused at lap start with 1× selected',(await progress())===0&&await page.getByRole('button',{name:'1×',exact:true}).getAttribute('aria-pressed')==='true');
 await page.waitForTimeout(650);await shot('09-ghost-3d');
 const viewA=hash(await canvas().screenshot());
 await page.getByRole('button',{name:'Chase Ghost B',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('.replay-3d-canvas')?.dataset.camera==='follow-b');
 const viewB=hash(await canvas().screenshot());
 check('Chase B produces a different rendered camera view',viewA!==viewB);
 await page.getByRole('button',{name:'Orbit camera',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('.replay-3d-canvas')?.dataset.camera==='orbit');
 const orbitBefore=hash(await canvas().screenshot()),box=await canvas().boundingBox();
 await page.mouse.move(box.x+box.width*.55,box.y+box.height*.45);await page.mouse.down();await page.mouse.move(box.x+box.width*.65,box.y+box.height*.54,{steps:8});await page.mouse.up();await page.waitForTimeout(500);
 check('Orbit drag changes rendered camera position',orbitBefore!==hash(await canvas().screenshot()));
 const preZoom=hash(await canvas().screenshot());await page.mouse.wheel(0,-140);await page.waitForTimeout(500);
 check('Orbit scroll zoom changes the rendered view',preZoom!==hash(await canvas().screenshot()));
 await shot('10-ghost-orbit');
 await page.getByRole('button',{name:'Chase Ghost A',exact:true}).click();
 await page.getByRole('button',{name:'Enable engine sound',exact:true}).click();await waitAudio();
 let a=await audio();check('Explicit enable creates one running AudioContext but stays silent while paused',a.contexts===1&&a.state==='running'&&a.rms<1e-5);
 await page.getByRole('button',{name:'Play replay',exact:true}).click();
 await page.waitForFunction(()=>+document.querySelector('input[aria-label="Replay position"]').value>15);
 a=await audio();measurements.playing=a;
 check('Real synthesized audio is nonzero and does not clip while playing',a.rms>.002&&a.peak<.99);
 check('Both 3D car positions advance during playback',+(await canvas().getAttribute('data-distance-a'))>.01&&+(await canvas().getAttribute('data-distance-b'))>.01);
 await page.getByRole('button',{name:'Pause replay',exact:true}).click();await waitAudio();
 measurements.paused=await audio();check('Pause silences the actual analyser output',measurements.paused.rms<1e-5);
 const pausedPosition=await progress();await page.waitForTimeout(200);check('Pause holds replay time steady',(await progress())===pausedPosition);
 const ghost=await (await page.request.get(base+'/api/ghost?a=NOR&b=VER')).json(),trace=ghost.a.trace,duration=Math.max(ghost.a.lap_time,ghost.b.lap_time);
 const extrema=['max','min'].map(kind=>trace.rpm.indexOf(Math[kind](...trace.rpm)));
 const frequencies=[];
 for(const index of extrema){
  await range('Replay position',Math.round(trace.time[index]/duration*1000));await waitAudio();
  const state=await audio(),rpm=Number((await page.locator('.engine-rpm-row>b').first().innerText()).replaceAll(',',''));
  frequencies.push(state.frequency[0]);check(`Oscillator follows the recorded ${index===extrema[0]?'high':'low'} RPM sample`,Math.abs(state.frequency[0]-rpm/20)<3);
 }
 measurements.rpm_driven_frequencies_hz=frequencies;
 check('Recorded RPM changes produce a material pitch change',frequencies[0]-frequencies[1]>150);
 await range('Replay position',350);await page.waitForTimeout(300);
 await page.getByRole('button',{name:'Chase Ghost B',exact:true}).click();await page.waitForTimeout(400);await shot('11-ghost-chase-b');
 await page.getByRole('button',{name:'Play replay',exact:true}).click();await waitAudio();
 a=await audio();check('Chase B also foregrounds driver B in the audio mix',a.gains[5]>a.gains[2]&&await page.locator('.audio-focus').innerText().then(t=>t.includes('VER')));
 await range('Engine volume',0);await waitAudio();a=await audio();check('Zero volume silences output without pausing the replay',a.rms<1e-5&&await page.getByRole('button',{name:'Pause replay',exact:true}).isVisible());
 await range('Engine volume',35);await waitAudio();check('Raising the volume restores an actual audio signal',(await audio()).rms>.002);
 await page.getByRole('button',{name:'Mute engine sound',exact:true}).click();await waitAudio();check('Mute silences actual audio while the cars continue moving',(await audio()).rms<1e-5&&await page.getByRole('button',{name:'Pause replay',exact:true}).isVisible());
 await page.getByRole('button',{name:'Enable engine sound',exact:true}).click();await waitAudio();a=await audio();check('Re-enabling sound reuses the existing context',a.contexts===1&&a.rms>.002);
 await page.getByRole('button',{name:'Pause replay',exact:true}).click();await range('Replay position',10);
 await page.getByRole('button',{name:'8×',exact:true}).click();await page.getByRole('button',{name:'Play replay',exact:true}).click();
 await page.waitForFunction(()=>+document.querySelector('input[aria-label="Replay position"]').value>110);
 a=await audio();measurements.gear_shifts=a;
 check('Real gear changes trigger audible shift envelopes and transients',a.sources>2&&(a.shiftRatioMin<2.8||a.shiftRatioMax>3.1));
 await page.getByRole('button',{name:'4×',exact:true}).click();check('4× transport control is selectable',await page.getByRole('button',{name:'4×',exact:true}).getAttribute('aria-pressed')==='true');
 // Simulated visibility event validates the handler and real output, not an assumed UI mute label.
 await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'))});await waitAudio();
 check('Background visibility handler pauses playback and silences audio',(await audio()).rms<1e-5&&await page.getByRole('button',{name:'Play replay',exact:true}).isVisible());
 await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event('visibilitychange'))});
 await range('Replay position',995);await page.getByRole('button',{name:'8×',exact:true}).click();await page.getByRole('button',{name:'Play replay',exact:true}).click();
 await page.waitForFunction(()=>+document.querySelector('input[aria-label="Replay position"]').value===1000);await waitAudio();
 check('Lap end clamps both cars at their finish and automatically silences audio',+(await canvas().getAttribute('data-distance-a'))===1&&+(await canvas().getAttribute('data-distance-b'))===1&&(await audio()).rms<1e-5);
 await page.getByRole('button',{name:'Restart replay',exact:true}).click();check('Restart returns to exact lap start',(await progress())===0);
 await page.getByRole('button',{name:'Expand replay',exact:true}).click();
 const theatre=page.getByRole('dialog',{name:'Immersive Ghost Lap replay'});await theatre.waitFor();await page.waitForTimeout(500);
 const bounds=await theatre.boundingBox();check('Immersive mode fills the viewport with live driver instruments',bounds.x<25&&bounds.width>1380&&await page.locator('.scene-instruments').isVisible());
 await shot('12-ghost-immersive');await page.keyboard.press('Escape');check('Escape closes immersive mode',await page.getByRole('dialog').count()===0);
 for(const driver of ['LEC','PIA','NOR']){
  await page.getByRole('combobox',{name:'Ghost A',exact:true}).selectOption(driver);
  await page.waitForFunction(d=>document.querySelector('.replay-3d-canvas')?.getAttribute('aria-label')?.includes(`${d} and VER`)&&document.querySelector('.replay-3d-canvas')?.dataset.ready==='true',driver);
  check(`${driver}/VER driver change rebuilds a working 3D scene`,Number(await canvas().getAttribute('data-draw-calls'))>100);
 }
 await range('Replay position',480);const before2d=await progress();
 await page.getByRole('button',{name:'2D map view',exact:true}).click();
 check('2D fallback preserves timeline and the original map',await canvas().count()===0&&await page.locator('.map-visual .track-svg').count()===1&&(await progress())===before2d);
 await shot('15-ghost-2d');await page.getByRole('button',{name:'3D replay view',exact:true}).click();await ready();
 check('Returning from 2D rebuilds the 3D renderer at the same replay time',(await progress())===before2d);
 await page.setViewportSize({width:390,height:844});await page.waitForTimeout(650);await shot('13-ghost-mobile');
 check('3D layout fits a 390px phone viewport',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 check('3D canvas and sound controls remain visible on mobile',(await canvas().boundingBox()).width>300&&await page.locator('.sound-toggle').isVisible());
 await page.getByRole('button',{name:'Expand replay',exact:true}).click();await page.waitForTimeout(500);await shot('14-ghost-mobile-immersive');
 check('Mobile immersive view keeps timeline, sound, and instruments within screen',await page.locator('.replay-stage.theatre').evaluate(e=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.bottom<=innerHeight})&&await page.locator('.scene-instruments').isVisible());
 await page.getByRole('button',{name:'Exit immersive view',exact:true}).click();
 await canvas().evaluate(c=>c.getContext('webgl2').getExtension('WEBGL_lose_context').loseContext());
 await page.getByRole('heading',{name:'3D is unavailable in this browser',exact:true}).waitFor();
 await page.getByRole('button',{name:'Continue in 2D',exact:true}).click();
 check('A real WebGL context-loss event offers a working 2D recovery',await page.locator('.map-visual .track-svg').count()===1);
 // Unmount without page navigation: verify that the actual AudioContext closes.
 await page.getByRole('button',{name:'Open navigation',exact:true}).click();
 await page.locator('.sidebar nav .nav-item').filter({hasText:'Pitwall Sandbox'}).click();await page.locator('.scenario-panel').waitFor();
 check('Leaving Ghost Lap closes its AudioContext',await page.evaluate(()=>window.__audioContexts.every(c=>c.state==='closed')));
 check('The other experiences remain reachable after disposing the 3D scene',await page.locator('.scenario-panel').isVisible());
 // Also exercise startup with WebGL completely unavailable; its one console error is expected.
 const noGL=await browser.newPage({viewport:{width:1280,height:900}}),expectedInitErrors=[];
 noGL.on('console',m=>{if(m.type()==='error')expectedInitErrors.push(m.text())});
 noGL.on('pageerror',e=>errors.push(e.message));
 await noGL.addInitScript(()=>{const get=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(type,...args){return type==='webgl2'||type==='webgl'?null:get.call(this,type,...args)}});
 await noGL.goto(base+'/#ghost',{waitUntil:'networkidle'});await noGL.getByRole('tab',{name:'Two-car detail',exact:true}).click();await noGL.getByRole('heading',{name:'3D is unavailable in this browser',exact:true}).waitFor();
 await noGL.getByRole('button',{name:'Continue in 2D',exact:true}).click();check('WebGL-unavailable browser can open and replay in 2D',await noGL.locator('.map-visual .track-svg').count()===1);
 await noGL.getByRole('button',{name:'Play replay',exact:true}).click();await noGL.waitForFunction(()=>+document.querySelector('input[aria-label="Replay position"]').value>10);
 check('2D fallback playback works without a WebGL context');measurements.expected_webgl_unavailable_console=expectedInitErrors;await noGL.close();
 check('No external browser assets or services are required',external.length===0);
 check('No unexpected browser runtime or console errors',errors.length===0);
}catch(e){console.error(e);checks.push({name:e.message,passed:false});process.exitCode=1;try{await shot('replay-failure')}catch{}}
finally{
 fs.writeFileSync(path.join(root,'qa/replay-browser-results.json'),JSON.stringify({run_at:new Date().toISOString(),browser:'Chromium / SwiftShader WebGL 2 / native Web Audio',checks,errors,external_requests:external,measurements},null,2));
 console.log(JSON.stringify({passed:checks.filter(c=>c.passed).length,failed:checks.filter(c=>!c.passed).length,errors,measurements},null,2));await browser.close();
}
