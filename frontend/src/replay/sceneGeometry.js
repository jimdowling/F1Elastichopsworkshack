import * as THREE from 'three';

export const ROAD_WIDTH = 15;
export const CIRCUIT_LENGTH = 4259;
const UP = new THREE.Vector3(0, 1, 0);
const FORWARD = new THREE.Vector3(0, 0, 1);

function rng(seed=12) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
function material(color, extra={}) { return new THREE.MeshStandardMaterial({ color, roughness: .72, metalness: .12, ...extra }); }
function box(parent, w,h,d, x,y,z, mat) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w,h,d),mat);
  mesh.position.set(x,y,z); mesh.castShadow=true;mesh.receiveShadow=true;parent.add(mesh);return mesh;
}
function cylinderBetween(parent, a,b,r, mat) {
  const delta=new THREE.Vector3().subVectors(b,a);
  const m=new THREE.Mesh(new THREE.CylinderGeometry(r,r,delta.length(),7),mat);
  m.position.copy(a).add(b).multiplyScalar(.5);m.quaternion.setFromUnitVectors(UP,delta.normalize());m.castShadow=true;parent.add(m);return m;
}
function textTexture(text,fg='#e9efdd',bg='#18201e',width=1024,height=192) {
  const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
  const ctx=canvas.getContext('2d');ctx.fillStyle=bg;ctx.fillRect(0,0,width,height);
  ctx.fillStyle=fg;ctx.textAlign='center';ctx.textBaseline='middle';ctx.font=`700 ${Math.round(height*.52)}px sans-serif`;ctx.fillText(text,width/2,height/2,width*.94);
  const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;return texture;
}
function grainTexture() {
  const canvas=document.createElement('canvas');canvas.width=canvas.height=256;const c=canvas.getContext('2d'),image=c.createImageData(256,256),random=rng(51);
  for(let i=0;i<image.data.length;i+=4){const v=105+random()*48;image.data[i]=v;image.data[i+1]=v+2;image.data[i+2]=v+4;image.data[i+3]=255;}
  c.putImageData(image,0,0);const texture=new THREE.CanvasTexture(canvas);texture.wrapS=texture.wrapT=THREE.RepeatWrapping;texture.colorSpace=THREE.SRGBColorSpace;return texture;
}

export function makeWorld(a,b) {
  const trace=a.trace,xs=trace.x,ys=trace.y;
  let length=0;for(let i=1;i<xs.length;i++)length+=Math.hypot(xs[i]-xs[i-1],ys[i]-ys[i-1]);
  const scale=CIRCUIT_LENGTH/length;
  const cx=(Math.min(...xs)+Math.max(...xs))/2,cy=(Math.min(...ys)+Math.max(...ys))/2;
  const worldPoint=(x,y,height=0)=>new THREE.Vector3((x-cx)*scale,height,-(y-cy)*scale);
  const points=(g)=>g.trace.x.map((x,i)=>worldPoint(x,g.trace.y[i],.045));
  const pa=points(a),pb=points(b);
  // This road is an illustrative ribbon around a measured racing line, not surveyed track boundaries.
  const roadPoints=pa.slice(0,-1).map(p=>p.clone().setY(0));
  const road=new THREE.CatmullRomCurve3(roadPoints,true,'centripetal');
  const trajectoryA=new THREE.CatmullRomCurve3(pa,false,'centripetal');
  const trajectoryB=new THREE.CatmullRomCurve3(pb,false,'centripetal');
  const bounds=new THREE.Box3().setFromPoints(roadPoints);const size=bounds.getSize(new THREE.Vector3());
  return {road,trajectoryA,trajectoryB,bounds,size,worldPoint,scale};
}

function ribbon(curve,inner,outer,height,mat,segments=1200,curb=false) {
  const pos=[],uv=[],colors=[],indices=[];const white=new THREE.Color('#e6e4d6'),red=new THREE.Color('#be433c');
  for(let i=0;i<=segments;i++){
    const t=i/segments,p=curve.getPointAt(t),v=curve.getTangentAt(t).normalize(),n=new THREE.Vector3(-v.z,0,v.x);
    const color=Math.floor(t*CIRCUIT_LENGTH/4)%2?white:red;
    for(const offset of [inner,outer]){
      pos.push(p.x+n.x*offset,height,p.z+n.z*offset);uv.push(offset/6,t*CIRCUIT_LENGTH/6);
      colors.push(color.r,color.g,color.b);
    }
    if(i<segments){const k=i*2;indices.push(k,k+2,k+1,k+1,k+2,k+3);}
  }
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(pos,3));geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));
  if(curb)geometry.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));
  geometry.setIndex(indices);geometry.computeVertexNormals();
  const mesh=new THREE.Mesh(geometry,mat);mesh.receiveShadow=true;return mesh;
}

function guardrail(curve,offset) {
  const pos=[],indices=[],segments=900;
  for(let i=0;i<=segments;i++){
    const p=curve.getPointAt(i/segments),v=curve.getTangentAt(i/segments),n=new THREE.Vector3(-v.z,0,v.x);
    pos.push(p.x+n.x*offset,.38,p.z+n.z*offset,p.x+n.x*offset,1.1,p.z+n.z*offset);
    if(i<segments){let k=i*2;indices.push(k,k+1,k+2,k+1,k+3,k+2);}
  }
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3));g.setIndex(indices);g.computeVertexNormals();
  return new THREE.Mesh(g,material('#a8b4b1',{side:THREE.DoubleSide,metalness:.65,roughness:.5}));
}

function terrain(world,flat=false) {
  const length=Math.max(world.size.x,world.size.z)+1500;
  const geometry=new THREE.PlaneGeometry(length,length,100,100);geometry.rotateX(-Math.PI/2);
  const points=world.road.getSpacedPoints(600),pos=geometry.attributes.position,colors=[],sand=new THREE.Color('#a39775'),grass=new THREE.Color('#6f8056');
  for(let i=0;i<pos.count;i++){
    const x=pos.getX(i),z=pos.getZ(i);let d2=Infinity;
    for(const p of points){const d=(p.x-x)**2+(p.z-z)**2;if(d<d2)d2=d;}
    const distance=Math.sqrt(d2),f=THREE.MathUtils.smoothstep(distance,45,180);
    // Stylized dunes are decoration; no measured elevation is implied.
    const h=flat?-.18:(Math.sin(x*.012)*Math.cos(z*.009)*8+Math.sin(z*.021+x*.007)*4+10)*f-.18;
    pos.setY(i,h);
    const noise=(Math.sin(x*.041+z*.017)+1)*.5;
    const color=grass.clone().lerp(sand,.18+f*.42+noise*.13);colors.push(color.r,color.g,color.b);
  }
  geometry.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));geometry.computeVertexNormals();
  const mesh=new THREE.Mesh(geometry,material('#ffffff',{vertexColors:true,roughness:1}));mesh.receiveShadow=true;return mesh;
}

function addScenery(group,world) {
  const road=world.road,concrete=material('#c5c9bf'),steel=material('#555f60',{metalness:.55}),dark=material('#242f32'),seat=material('#506777');
  // A modest, illustrative grandstand and pit buildings beside the start section.
  const p=road.getPointAt(.01),t=road.getTangentAt(.01),n=new THREE.Vector3(-t.z,0,t.x);
  const stand=new THREE.Group();stand.position.copy(p).addScaledVector(n,35);stand.quaternion.setFromUnitVectors(FORWARD,t);
  for(let i=0;i<6;i++){
    box(stand,3.5,.65,80,-i*2.5,1+i*.85,0,concrete);
    box(stand,1.4,.45,78,-i*2.5,1.55+i*.85,0,seat);
  }
  box(stand,19,.25,86,-6,9,0,dark);
  for(const z of [-36,-12,12,36])box(stand,.5,9,.5,-12,4.5,z,steel);
  group.add(stand);
  const pits=new THREE.Group();pits.position.copy(p).addScaledVector(n,-38);pits.quaternion.setFromUnitVectors(FORWARD,t);
  for(let i=0;i<9;i++){
    box(pits,12,5,9,0,2.5,(i-4)*10,material(i%2?'#67716f':'#73817f'));
    box(pits,.1,3.1,6.6,6.05,1.65,(i-4)*10,dark);
    box(pits,13,.3,9.9,0,5.05,(i-4)*10,concrete);
  }
  group.add(pits);
  const boards=[.08,.18,.31,.45,.58,.71,.85,.94];
  for(let i=0;i<boards.length;i++){
    const f=boards[i],p=road.getPointAt(f),t=road.getTangentAt(f),n=new THREE.Vector3(-t.z,0,t.x);
    const anchor=new THREE.Group();anchor.position.copy(p).addScaledVector(n,13);anchor.quaternion.setFromUnitVectors(FORWARD,t);
    const tex=textTexture(i%2?'PITLANE':'ZANDVOORT','#d7ff62','#17211f',768,160);
    const sign=new THREE.Mesh(new THREE.BoxGeometry(.15,1.8,11),[material('#26312b'),material('#26312b'),material('#26312b'),material('#26312b'),material('#26312b'),material('#26312b')]);
    // Text faces the road on the sign's inner side.
    const panel=new THREE.Mesh(new THREE.PlaneGeometry(11,1.8),new THREE.MeshStandardMaterial({map:tex,roughness:1,side:THREE.DoubleSide}));
    panel.rotation.y=Math.PI/2;panel.position.set(-.1,1.8,0);anchor.add(panel);sign.position.y=1.8;anchor.add(sign);
    box(anchor,.15,1.5,.15,0,.75,-4,steel);box(anchor,.15,1.5,.15,0,.75,4,steel);group.add(anchor);
  }
  // Start/finish gantry and a physical chequered start line.
  const gate=new THREE.Group(),gp=road.getPointAt(0),gt=road.getTangentAt(0);gate.position.copy(gp);gate.quaternion.setFromUnitVectors(FORWARD,gt);
  box(gate,.5,7,.5,-10,3.5,0,steel);box(gate,.5,7,.5,10,3.5,0,steel);box(gate,21,1.8,.5,0,7,0,dark);
  const face=new THREE.Mesh(new THREE.PlaneGeometry(19,1.35),new THREE.MeshStandardMaterial({map:textTexture('PITLANE  /  GHOST LAP','#d7ff62','#18211f'),side:THREE.DoubleSide}));face.position.set(0,7,-.27);face.rotation.y=Math.PI;gate.add(face);
  for(let x=0;x<16;x++)for(let z=0;z<2;z++)box(gate,.9,.015,.9,(x-7.5)*.9,.065,(z-.5)*.9,material((x+z)%2?'#292f32':'#e7e6dc'));
  group.add(gate);
  // A few distance boards are illustrative decoration, not official braking references.
  for(const f of [.12,.26,.5,.67,.83]){
    const p=road.getPointAt(f),t=road.getTangentAt(f),n=new THREE.Vector3(-t.z,0,t.x),board=new THREE.Group();board.position.copy(p).addScaledVector(n,-11);board.quaternion.setFromUnitVectors(FORWARD,t);
    const m=new THREE.Mesh(new THREE.PlaneGeometry(1.8,1.5),new THREE.MeshStandardMaterial({map:textTexture('100','#25312b','#e6e5d9',256,192),side:THREE.DoubleSide}));m.position.y=1.2;m.rotation.y=Math.PI;board.add(m);group.add(board);
  }
}

export function buildCircuit(world,options={}) {
  const group=new THREE.Group();group.name='Illustrative Zandvoort environment';
  group.add(terrain(world,!!options.flat));
  const asphalt=material('#585d60',{map:grainTexture(),roughness:.97,side:THREE.DoubleSide});
  const verge=material('#7a8a5c',{side:THREE.DoubleSide,roughness:1});
  group.add(ribbon(world.road,-ROAD_WIDTH/2-4,ROAD_WIDTH/2+4,-.05,verge));
  group.add(ribbon(world.road,-ROAD_WIDTH/2,ROAD_WIDTH/2,.035,asphalt));
  const stripe=material('#ece8d6',{side:THREE.DoubleSide,roughness:1});
  const curbs=material('#ffffff',{vertexColors:true,side:THREE.DoubleSide,roughness:.95});
  for(const side of [-1,1]){
    group.add(ribbon(world.road,side*(ROAD_WIDTH/2-.15),side*(ROAD_WIDTH/2+.03),.055,stripe));
    group.add(ribbon(world.road,side*(ROAD_WIDTH/2+.08),side*(ROAD_WIDTH/2+1.1),.07,curbs,1400,true));
    group.add(guardrail(world.road,side*(ROAD_WIDTH/2+4.5)));
  }
  // Instanced guardrail posts: a single draw call rather than hundreds of meshes.
  const count=700,posts=new THREE.InstancedMesh(new THREE.BoxGeometry(.13,.85,.13),material('#7b8988',{metalness:.5}),count);const dummy=new THREE.Object3D();
  for(let i=0;i<count;i++){
    const p=world.road.getPointAt((i>>1)/(count/2)),t=world.road.getTangentAt((i>>1)/(count/2)),n=new THREE.Vector3(-t.z,0,t.x),side=i%2?1:-1;
    dummy.position.copy(p).addScaledVector(n,side*(ROAD_WIDTH/2+4.5));dummy.position.y=.6;dummy.updateMatrix();posts.setMatrixAt(i,dummy.matrix);
  }
  group.add(posts);if(options.scenery!==false)addScenery(group,world);return group;
}

function bodyGeometry(stations) {
  const pos=[],indices=[];
  for(const [z,width,base,top] of stations){pos.push(-width,base,z,width,base,z,-width*.86,top,z,width*.86,top,z);}
  for(let i=0;i<stations.length-1;i++){
    let a=i*4,b=a+4;
    indices.push(a,a+2,b,a+2,b+2,b,a+1,b+1,a+3,a+3,b+1,b+3,a+2,a+3,b+2,a+3,b+3,b+2,a,b,a+1,a+1,b,b+1);
  }
  const e=(stations.length-1)*4;indices.push(0,1,2,1,3,2,e,e+2,e+1,e+1,e+2,e+3);
  for(let i=0;i<indices.length;i+=3){const t=indices[i+1];indices[i+1]=indices[i+2];indices[i+2]=t;}
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3));g.setIndex(indices);g.computeVertexNormals();return g;
}

export function buildCar(code,color,compound='HARD',number='4') {
  const group=new THREE.Group();group.name=code+' stylized open-wheel car';
  const chassis=new THREE.Group();group.add(chassis);
  const paint=material(color,{metalness:.3,roughness:.29}),carbon=material('#151b20',{roughness:.52,metalness:.1}),rubber=material('#171b1c',{roughness:.9}),rim=material('#778488',{metalness:.86,roughness:.3}),black=material('#080f12',{roughness:.42});
  const white=material('#ecf2df'),silver=material('#b4c2c3',{metalness:.7,roughness:.25});
  box(chassis,1.9,.09,4.9,0,.22,0,carbon);
  const main=new THREE.Mesh(bodyGeometry([[-2.05,.31,.3,.66],[-1.45,.46,.32,1.05],[-.65,.5,.34,.99],[.2,.38,.33,.88],[1.2,.25,.3,.54],[2.35,.12,.25,.38]]),paint);main.castShadow=true;main.receiveShadow=true;chassis.add(main);
  // Sidepods and cooling openings.
  for(const side of [-1,1]){
    const pod=new THREE.Mesh(bodyGeometry([[-1.65,.27,.28,.55],[-1.05,.39,.26,.76],[.1,.37,.27,.82],[.48,.24,.37,.72]]),paint);pod.position.x=side*.63;pod.castShadow=true;chassis.add(pod);
    box(chassis,.42,.24,.03,side*.62,.57,.5,black);
    box(chassis,.09,.14,1.95,side*.92,.38,-.5,carbon);
    const accent=box(chassis,.04,.11,1.4,side*.99,.64,-.6,white);accent.rotation.z=side*.08;
    cylinderBetween(chassis,new THREE.Vector3(side*.35,.95,.2),new THREE.Vector3(side*.77,1.03,.4),.025,carbon);
    box(chassis,.19,.13,.3,side*.82,1.06,.4,paint);
  }
  // Open cockpit, seated helmet and visible halo.
  const cockpit=new THREE.Mesh(new THREE.SphereGeometry(.36,20,10),black);cockpit.scale.set(.9,.32,1.5);cockpit.position.set(0,.99,-.18);chassis.add(cockpit);
  const helmet=new THREE.Mesh(new THREE.SphereGeometry(.165,20,12),material('#e7e9bd',{roughness:.35}));helmet.position.set(0,1.1,-.2);helmet.castShadow=true;chassis.add(helmet);
  box(chassis,.25,.075,.05,0,1.115,-.045,black);
  const haloCurve=new THREE.CatmullRomCurve3([new THREE.Vector3(-.38,1.03,-.65),new THREE.Vector3(-.41,1.34,-.3),new THREE.Vector3(-.3,1.35,.35),new THREE.Vector3(0,1.32,.55),new THREE.Vector3(.3,1.35,.35),new THREE.Vector3(.41,1.34,-.3),new THREE.Vector3(.38,1.03,-.65)]);
  const halo=new THREE.Mesh(new THREE.TubeGeometry(haloCurve,30,.045,7,false),carbon);halo.castShadow=true;chassis.add(halo);
  cylinderBetween(chassis,new THREE.Vector3(0,.89,.52),new THREE.Vector3(0,1.32,.55),.045,carbon);
  const cover=new THREE.Mesh(bodyGeometry([[-1.7,.1,.75,.88],[-1.08,.16,.9,1.4],[-.71,.19,.97,1.45],[-.55,.21,.94,1.2]]),paint);cover.castShadow=true;chassis.add(cover);
  box(chassis,.3,.1,.13,0,1.47,-.91,carbon);
  // Multi-element front wing, rear wing, and diffuser.
  for(let i=0;i<3;i++){
    const wing=box(chassis,2.12-i*.08,.055,.25,0,.26+i*.065,2.47-i*.2,i===2?paint:carbon);wing.rotation.x=-.10;
  }
  for(const side of [-1,1])box(chassis,.055,.34,.88,side*1.06,.38,2.28,paint);
  for(const side of [-1,1])box(chassis,.04,.7,.92,side*.97,1.11,-2.02,paint);
  box(chassis,1.94,.065,.52,0,1.42,-2.05,paint);const flap=box(chassis,1.94,.06,.29,0,1.26,-2.24,carbon);flap.rotation.x=-.12;
  cylinderBetween(chassis,new THREE.Vector3(-.25,.48,-1.8),new THREE.Vector3(-.25,1.38,-1.95),.035,carbon);
  cylinderBetween(chassis,new THREE.Vector3(.25,.48,-1.8),new THREE.Vector3(.25,1.38,-1.95),.035,carbon);
  for(let i=-2;i<=2;i++)box(chassis,.04,.2,.6,i*.26,.3,-2.25,carbon);
  const rearLight=box(chassis,.12,.08,.05,0,.54,-2.4,material('#ef483c',{emissive:'#d43122',emissiveIntensity:.7}));
  // Suspension, steering pivots, spinning wheels, rims and sidewall rings.
  const wheels=[],frontPivots=[];const tyreColor=compound==='SOFT'?'#f2757b':compound==='MEDIUM'?'#e9ce54':'#e7eadc';
  for(const front of [true,false])for(const side of [-1,1]){
    const z=front?1.5:-1.5,x=side*(front?1.03:1.06),width=front?.32:.39;
    const pivot=new THREE.Group();pivot.position.set(x,.39,z);group.add(pivot);if(front)frontPivots.push(pivot);
    const wheel=new THREE.Group();pivot.add(wheel);wheels.push(wheel);
    const tyre=new THREE.Mesh(new THREE.CylinderGeometry(.365,.365,width,28,1),rubber);tyre.rotation.z=Math.PI/2;tyre.castShadow=true;wheel.add(tyre);
    const hub=new THREE.Mesh(new THREE.CylinderGeometry(.21,.21,width+.012,18),rim);hub.rotation.z=Math.PI/2;wheel.add(hub);
    for(const face of [-1,1]){
      const ring=new THREE.Mesh(new THREE.TorusGeometry(.28,.012,5,30),material(tyreColor));ring.rotation.y=Math.PI/2;ring.position.x=face*(width/2+.008);wheel.add(ring);
      const center=new THREE.Mesh(new THREE.CylinderGeometry(.077,.077,.018,12),carbon);center.rotation.z=Math.PI/2;center.position.x=face*(width/2+.02);wheel.add(center);
      for(let i=0;i<6;i++){
        const spoke=new THREE.Mesh(new THREE.BoxGeometry(.013,.28,.018),silver);spoke.position.x=face*(width/2+.012);spoke.rotation.x=i*Math.PI/3;wheel.add(spoke);
      }
    }
    for(const longitudinal of [-.36,.34]){
      cylinderBetween(group,new THREE.Vector3(side*.3,.57,z+longitudinal),new THREE.Vector3(x,.39,z),.024,carbon);
      cylinderBetween(group,new THREE.Vector3(side*.28,.32,z+longitudinal),new THREE.Vector3(x,.39,z),.02,carbon);
    }
  }
  const numberPlate=new THREE.Mesh(new THREE.PlaneGeometry(.28,.45),new THREE.MeshStandardMaterial({map:textTexture(number,'#152020',color,128,192),roughness:.5}));numberPlate.rotation.x=-Math.PI/2;numberPlate.position.set(0,.6,1.17);chassis.add(numberPlate);
  const labelTexture=textTexture(code,color,'#112024',256,96);
  const label=new THREE.Sprite(new THREE.SpriteMaterial({map:labelTexture,depthTest:false,transparent:true,opacity:.95}));label.scale.set(1.9,.71,1);label.position.set(0,2.5,0);group.add(label);
  return {group,chassis,wheels,frontPivots,label,rearLight};
}

export function disposeScene(scene) {
  const geometries=new Set(),materials=new Set(),textures=new Set();
  scene.traverse(obj=>{if(obj.geometry)geometries.add(obj.geometry);if(obj.material){for(const m of (Array.isArray(obj.material)?obj.material:[obj.material]))materials.add(m);}});
  for(const m of materials){for(const value of Object.values(m))if(value?.isTexture)textures.add(value);m.dispose();}
  for(const g of geometries)g.dispose();for(const t of textures)t.dispose();
}
