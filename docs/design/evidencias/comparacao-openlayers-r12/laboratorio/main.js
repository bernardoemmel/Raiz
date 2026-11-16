import {prepararGpu} from '/workspace/Raiz-mapa-integrado/front/globo/src/mapa/preparar-gpu.ts';
const params=new URLSearchParams(location.search),engine=params.get('engine')||'ml',caseName=params.get('case')||'com';
const raf=()=>new Promise(r=>requestAnimationFrame(r));const marks={};const timings=[],frames=[],commands=[];let step=null;let api;
window.__errors=[];window.addEventListener('error',e=>window.__errors.push(e.message));window.addEventListener('unhandledrejection',e=>window.__errors.push(String(e.reason)));
const longTasks=[];new PerformanceObserver(list=>{for(const e of list.getEntries())longTasks.push({start:e.startTime,duration:e.duration})}).observe({type:'longtask',buffered:true});
const onRender=view=>{const at=performance.now();if(!step||step.kind==='select')return;
 const s=step;const matches=Math.abs(view.resolution-s.view.resolution)<1e-7&&view.center.every((n,i)=>Math.abs(n-s.view.center[i])<.001);
 const frame={at,kind:s.kind,sequence:s.sequence,command:s.command,matches,view};frames.push(frame);
 if(matches&&!s.seen){s.seen=true;requestAnimationFrame(()=>{frame.renderNextRafProxy=performance.now();timings.push({kind:s.kind,sequence:s.sequence,step:s.index,command:s.command,renderLatency:at-s.start,renderNextRafProxy:performance.now()-s.start})})}
};
async function start(){
 marks.start=performance.now();const gpu=engine==='ml'?prepararGpu():Promise.resolve(()=>{});
 const loading=engine==='ml'?import('./maplibre.js'):import('./openlayers.js');
 const data=Promise.all([fetch('/dados/imoveis.geojson').then(r=>r.json()),fetch('/dados/casos.json').then(r=>r.json())]).then(value=>{marks.commonDataReady=performance.now();return value});
 const module=await loading;marks.imported=performance.now();
 const[geo,cases]=await data;const scenario=cases[caseName];const width=window.innerWidth;const view=scenario.views[width>=960?'960':'360'];
 marks.constructStart=performance.now();api=await module.create({geo,scenario,view,onRender,gpu});marks.loaded=performance.now();await raf();marks.complete=performance.now();
 document.querySelector('#titulo').textContent=`${engine==='ml'?'MapLibre':'OpenLayers'} · ${caseName==='com'?'com sobreposição':'sem sobreposição'}`;
 const output=document.querySelector('#resultado');
 function select(id){api.select(id);output.textContent=id===null?'Sem seleção':`CAR ${geo.features[id].properties.cod_imovel}`}
 document.querySelector('#mapa').addEventListener('pointermove',e=>{const b=e.currentTarget.getBoundingClientRect();api.hover(api.hit([e.clientX-b.left,e.clientY-b.top]))});
 document.querySelector('#mapa').addEventListener('click',e=>{const b=e.currentTarget.getBoundingClientRect();select(api.hit([e.clientX-b.left,e.clientY-b.top]))});
 document.querySelector('#mapa').addEventListener('keydown',e=>{if(e.key==='Escape')select(null);if(e.key==='Enter')select(scenario.target)});
 const testResults=scenario.tests.map(t=>({...t,pixel:api.pixel(t.lnglat),actual:api.hit(api.pixel(t.lnglat))}));
 window.lab={engine,caseName,marks,scenario,view,testResults,controlPoints:scenario.control_points.map(p=>({lnglat:p,pixel:api.pixel(p)})),info:api.info(),longTasks,timings,
  async settle(){await api.idle();await raf();return api.info()},
  async select(id){select(id);await api.idle();await raf();return api.info()},
  async hover(id){api.hover(id);await api.idle();await raf()},
  async reset(){api.setView(view);select(null);api.hover(null);await api.idle();await raf()},
  async run(){const intervals=[],updates=[];let previous;
   for(let sequence=0;sequence<3;sequence++){
    for(const kind of ['pan','zoom']){
     await new Promise(resolve=>{let i=0;function tick(now){if(previous!==undefined)intervals.push({kind,sequence,ms:now-previous});previous=now;
      const t=i/59,angle=t*Math.PI*2;
      const v=kind==='pan'?{center:[view.center[0]+Math.sin(angle)*120*view.resolution,view.center[1]+Math.sin(angle*2)*60*view.resolution],resolution:view.resolution}:{center:view.center,resolution:view.resolution*2**(Math.sin(angle)*.3)};
      const start=performance.now();step={kind,sequence,index:i,start,seen:false,view:v,command:commands.length};commands.push({kind,sequence,index:i,start,view:v,command:commands.length,noOp:i===0});api.setView(v);updates.push({kind,sequence,ms:performance.now()-start});if(++i<60)requestAnimationFrame(tick);else{resolve()}}requestAnimationFrame(tick)});
     previous=undefined;api.setView(view);await api.idle();await raf();step=null;
    }
    for(let i=0;i<20;i++){await raf();const start=performance.now();step={kind:'select',sequence,index:i,start,seen:false};const id=i%2?null:scenario.tests.find(t=>t.expected!==null).expected;select(id);updates.push({kind:'select',sequence,ms:performance.now()-start});await api.idle();await raf();timings.push({kind:'select',sequence,step:i,renderNextRafProxy:performance.now()-start,definition:'fonte atualizada + idle/rendercomplete + RAF, proxy sem garantia de apresentação física'});step=null}
   }
   await window.lab.reset();return{intervals,updates,frames,commands,timings:timings.slice(),longTasks:longTasks.slice(),info:api.info()}
  }
 };
 window.__ready=true;
}
start().catch(e=>{window.__errors.push(e.stack||String(e));window.__failed=true});
