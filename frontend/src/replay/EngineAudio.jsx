import React, {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {Volume2,VolumeX,Headphones,Info} from 'lucide-react';

const clamp=(x,a,b)=>Math.min(b,Math.max(a,x));
function noiseBuffer(ctx,seconds=1.5,seed=7){
  const buffer=ctx.createBuffer(1,Math.floor(ctx.sampleRate*seconds),ctx.sampleRate),out=buffer.getChannelData(0);
  for(let i=0;i<out.length;i++){seed=(seed*16807)%2147483647;out[i]=(seed/2147483647*2-1)*.7;}
  return buffer;
}
function distortion(){const curve=new Float32Array(4096);for(let i=0;i<curve.length;i++){let x=(i/(curve.length-1)*2-1);curve[i]=Math.tanh(x*2.1)*.8;}return curve;}

function voice(ctx,output,pan,seed){
  const combustion=ctx.createOscillator(),body=ctx.createOscillator(),bodyGain=ctx.createGain(),tone=ctx.createBiquadFilter(),saturator=ctx.createWaveShaper(),gain=ctx.createGain(),panner=ctx.createStereoPanner();
  const real=new Float32Array(17),imag=new Float32Array(17);
  // A designed harmonic combustion tone, not a recording or manufacturer-specific engine model.
  [0,1,.44,.28,.34,.15,.19,.09,.12,.06,.08,.04,.05,.02,.025,.015,.01].forEach((x,i)=>imag[i]=x);
  combustion.setPeriodicWave(ctx.createPeriodicWave(real,imag));combustion.frequency.value=430;
  body.type='triangle';body.frequency.value=145;bodyGain.gain.value=.34;
  tone.type='lowpass';tone.frequency.value=3200;tone.Q.value=.5;
  saturator.curve=distortion();saturator.oversample='2x';gain.gain.value=0;panner.pan.value=pan;
  combustion.connect(tone);body.connect(bodyGain);bodyGain.connect(tone);tone.connect(saturator);saturator.connect(gain);gain.connect(panner);panner.connect(output);
  const air=ctx.createBufferSource(),airFilter=ctx.createBiquadFilter(),airGain=ctx.createGain();
  const noise=noiseBuffer(ctx,1.5,seed);air.buffer=noise;air.loop=true;airFilter.type='bandpass';airFilter.frequency.value=2600;airFilter.Q.value=.65;airGain.gain.value=0;
  air.connect(airFilter);airFilter.connect(airGain);airGain.connect(panner);
  combustion.start();body.start();air.start();
  let lastGear=0,lastShift=-10,shiftDirection=1;
  const update=(motion,active,foreground,reset=false)=>{
    if(reset){lastGear=0;lastShift=-10;}
    const now=ctx.currentTime,rpm=clamp(Number(motion?.rpm)||8500,3500,14500),throttle=clamp((Number(motion?.throttle)||0)/100,0,1),speed=Number(motion?.speed)||0,gear=Math.max(1,Math.round(Number(motion?.gear)||1));
    if(active&&lastGear&&gear!==lastGear){
      shiftDirection=gear>lastGear?1:-1;lastShift=now;
      const pop=ctx.createBufferSource(),envelope=ctx.createGain(),filter=ctx.createBiquadFilter();
      pop.buffer=noise;filter.type='bandpass';filter.frequency.value=650;filter.Q.value=.65;
      envelope.gain.setValueAtTime(0,now);envelope.gain.linearRampToValueAtTime(.035*(foreground?1:.25),now+.006);envelope.gain.exponentialRampToValueAtTime(.0001,now+.07);
      pop.connect(filter);filter.connect(envelope);envelope.connect(panner);pop.start(now);pop.stop(now+.08);pop.onended=()=>{pop.disconnect();filter.disconnect();envelope.disconnect();};
    }
    lastGear=gear;
    const shifting=active&&now-lastShift<.065;
    // Three combustion events per crank revolution as a V6-like design reference.
    const frequency=rpm/20*(shifting?(shiftDirection>0?.86:1.07):1);
    combustion.frequency.setTargetAtTime(frequency,now,.024);body.frequency.setTargetAtTime(rpm/60,now,.028);
    tone.frequency.setTargetAtTime(1700+throttle*3600+rpm*.075,now,.04);
    const mix=foreground?1:.20,level=active?(.15+throttle*.19)*(shifting?.73:1)*mix:0;
    gain.gain.setTargetAtTime(level,now,.035);
    airGain.gain.setTargetAtTime(active?(.006+throttle*.009+Math.max(0,speed-160)*.000055)*mix:0,now,.06);
    airFilter.frequency.setTargetAtTime(1800+throttle*2300,now,.07);
  };
  const stop=()=>{
    for(const n of [combustion,body,air]){try{n.stop()}catch{}n.disconnect()}
    for(const n of [bodyGain,tone,saturator,gain,panner,airFilter,airGain])n.disconnect();
  };
  return {update,stop};
}

class EngineMixer {
  constructor(){
    const Context=window.AudioContext||window.webkitAudioContext;
    if(!Context)throw new Error('Web Audio is not available in this browser.');
    this.context=new Context({latencyHint:'interactive'});
    this.master=this.context.createGain();this.master.gain.value=0;
    this.limiter=this.context.createDynamicsCompressor();this.limiter.threshold.value=-15;this.limiter.knee.value=12;this.limiter.ratio.value=8;this.limiter.attack.value=.004;this.limiter.release.value=.12;
    this.analyser=this.context.createAnalyser();this.analyser.fftSize=256;this.analyser.smoothingTimeConstant=.65;
    this.master.connect(this.limiter);this.limiter.connect(this.analyser);this.analyser.connect(this.context.destination);
    this.voices=[voice(this.context,this.master,-.14,77),voice(this.context,this.master,.14,99)];this.closed=false;
  }
  async resume(){if(this.context.state==='suspended')await this.context.resume();}
  update({a,b,playing,enabled,volume,focus,visible,driverA,driverB}){
    if(this.closed)return;
    const active=Boolean(playing&&enabled&&visible);
    this.master.gain.setTargetAtTime(active?clamp(volume/100,0,1)*.72:0,this.context.currentTime,.035);
    this.voices[0].update(a,active&&!a?.finished,focus===0,this.driverA!==driverA);this.voices[1].update(b,active&&!b?.finished,focus===1,this.driverB!==driverB);this.driverA=driverA;this.driverB=driverB;
  }
  dispose(){if(this.closed)return;this.closed=true;this.voices.forEach(v=>v.stop());this.master.disconnect();this.limiter.disconnect();this.analyser.disconnect();this.context.close().catch(()=>{});}
}

export default function EngineAudio({motionA,motionB,playing,cameraMode,driverA,driverB}) {
  const [enabled,setEnabled]=useState(false),[volume,setVolume]=useState(35),[error,setError]=useState(null),[busy,setBusy]=useState(false);
  const mixer=useRef(null),meterRef=useRef(null),current=useRef(null);
  const focus=cameraMode==='follow-b'?1:0;
  current.current={a:motionA,b:motionB,playing,enabled,volume,focus,driverA,driverB,visible:!document.hidden};
  // Logical mute/pause changes must not wait for a graphics-heavy animation frame.
  useLayoutEffect(()=>{mixer.current?.update(current.current)},[playing,enabled,volume,cameraMode,driverA,driverB,motionA?.finished,motionB?.finished]);
  useEffect(()=>{
    let frame,alive=true;const frequency=new Uint8Array(128);
    const visibility=()=>{if(current.current)mixer.current?.update({...current.current,visible:!document.hidden});};
    document.addEventListener('visibilitychange',visibility);
    const tick=()=>{
      if(!alive)return;frame=requestAnimationFrame(tick);
      const state=current.current;if(!state)return;state.visible=!document.hidden;
      mixer.current?.update(state);
      const canvas=meterRef.current,ctx=canvas?.getContext('2d');
      if(ctx){
        ctx.clearRect(0,0,canvas.width,canvas.height);
        if(mixer.current)mixer.current.analyser.getByteFrequencyData(frequency);else frequency.fill(0);
        const active=state.enabled&&state.playing&&state.volume>0&&!document.hidden;
        for(let i=0;i<18;i++){
          const value=frequency[2+i*2]/255,height=active?Math.max(2,value*22):2;
          ctx.fillStyle=active?'#d7ff62':'#526257';ctx.fillRect(i*4,24-height,2,height);
        }
      }
    };frame=requestAnimationFrame(tick);
    return()=>{alive=false;cancelAnimationFrame(frame);document.removeEventListener('visibilitychange',visibility);mixer.current?.dispose();mixer.current=null;};
  },[]);
  const toggle=async()=>{
    if(busy)return;
    if(enabled){setEnabled(false);return;}
    setBusy(true);setError(null);
    try{
      if(!mixer.current)mixer.current=new EngineMixer();
      await mixer.current.resume();setEnabled(true);
    }catch(e){setError('Engine audio could not start. The replay still works; try again after interacting with the page.');}
    finally{setBusy(false);}
  };
  return <div className="engine-audio-module">
    <div className="engine-audio-controls">
      <button type="button" className={`sound-toggle ${enabled?'enabled':''}`} aria-label={enabled?'Mute engine sound':'Enable engine sound'} aria-pressed={enabled} disabled={busy} onClick={toggle}>
        {enabled?<Volume2 size={16}/>:<VolumeX size={16}/>}<span>{busy?'Starting…':enabled?'Sound on':'Enable sound'}</span>
      </button>
      <label className="volume-control"><span>VOLUME</span><input type="range" aria-label="Engine volume" min="0" max="100" value={volume} onChange={e=>setVolume(+e.target.value)}/><output>{volume}%</output></label>
      <canvas ref={meterRef} className="engine-meter" width="72" height="26" aria-label="Engine audio level meter"/>
      <span className="audio-focus"><Headphones size={12}/>{enabled?(playing?`FOCUS: ${focus?driverB:driverA}`:'PRESS PLAY TO LISTEN'):'AUDIO STARTS ON CLICK'}</span>
    </div>
    <div className="engine-audio-caption"><span>SYNTHESIZED ENGINE AUDIO</span>RPM + throttle + gear changes · not recorded F1 sound</div>
    {error&&<div className="audio-error"><Info size={13}/>{error}</div>}
  </div>;
}
