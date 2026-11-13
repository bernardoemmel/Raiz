import {Map, setWorkerUrl} from '/workspace/Raiz-mapa-integrado/front/globo/node_modules/maplibre-gl/dist/maplibre-gl.mjs';
import worker from '/workspace/Raiz-mapa-integrado/front/globo/node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs?url';
const W=40075016.68557849;
const inv=p=>[p[0]/W*360,Math.atan(Math.sinh(p[1]/W*2*Math.PI))*180/Math.PI];
export async function create({geo,scenario,view,onRender,gpu}){
 setWorkerUrl(worker);
 const release=await gpu;
 const style={version:8,sources:{sat:{type:'raster',tiles:[location.origin+'/tiles/{z}/{x}/{y}.jpg'],tileSize:256,minzoom:14,maxzoom:14},farms:{type:'geojson',data:geo},mask:{type:'geojson',data:{type:'FeatureCollection',features:[]}}},layers:[
 {id:'sat',source:'sat',type:'raster',paint:{'raster-fade-duration':0}},
 {id:'veil',type:'background',paint:{'background-color':'#FAFAF7','background-opacity':.3}},
 {id:'mask',source:'mask',type:'fill',paint:{'fill-color':'#0F1A14','fill-opacity':.45,'fill-antialias':false}},
 {id:'farms',type:'fill',source:'farms',layout:{'fill-sort-key':['get','ordem_desenho']},paint:{'fill-color':'#15231B','fill-opacity':0}},
 {id:'outline',type:'line',source:'farms',filter:['!=',['get','sobreposto'],true],layout:{'line-sort-key':['get','ordem_desenho']},paint:{'line-color':'#15231B','line-width':1,'line-opacity':.8}},
 {id:'overlap',type:'line',source:'farms',filter:['==',['get','sobreposto'],true],layout:{'line-sort-key':['get','ordem_desenho']},paint:{'line-color':'#15231B','line-width':1,'line-opacity':.8,'line-dasharray':[3,3]}},
 {id:'highlight',type:'line',source:'farms',paint:{'line-color':'#1D6B44','line-width':2.5,'line-opacity':['case',['any',['boolean',['feature-state','selected'],false],['boolean',['feature-state','hover'],false]],1,0]}}
 ]};
 const map=new Map({container:'mapa',attributionControl:false,validateStyle:false,canvasContextAttributes:{desynchronized:true},pixelRatio:1,fadeDuration:0,dragRotate:false,pitchWithRotate:false,center:inv(view.center),zoom:Math.log2(W/512/view.resolution),style});
 release();
 map.on('error',e=>{window.__mapErrors??=[];window.__mapErrors.push(e.error?.message||String(e));});
 map.on('render',()=>{const c=map.getCenter();onRender({center:[c.lng/360*W,Math.log(Math.tan(Math.PI/4+c.lat*Math.PI/360))*W/(2*Math.PI)],resolution:W/512/2**map.getZoom()})});
 await new Promise(resolve=>{if(map.loaded()&&map.areTilesLoaded())resolve();else map.once('idle',resolve)});
 let current=null,hovered=null;let maskReady=Promise.resolve();
 const api={
  setView(v){map.jumpTo({center:inv(v.center),zoom:Math.log2(W/512/v.resolution)})},
  pixel(lnglat){const p=map.project(lnglat);return[p.x,p.y]},
  hit(p){const f=map.queryRenderedFeatures(p,{layers:['farms']});f.sort((a,b)=>b.properties.ordem_desenho-a.properties.ordem_desenho);return f[0]?Number(f[0].id):null},
  select(id){if(current!==null)map.setFeatureState({source:'farms',id:current},{selected:false});current=id;if(id!==null)map.setFeatureState({source:'farms',id},{selected:true});maskReady=new Promise(resolve=>{const loaded=e=>{if(e.sourceId==='mask'&&e.isSourceLoaded){map.off('sourcedata',loaded);resolve()}};map.on('sourcedata',loaded);map.getSource('mask').setData({type:'FeatureCollection',features:id===null?[]:[scenario.mask[String(id)]]})})},
  hover(id){if(hovered!==null)map.setFeatureState({source:'farms',id:hovered},{hover:false});hovered=id;if(id!==null)map.setFeatureState({source:'farms',id},{hover:true})},
  async idle(){await maskReady;await new Promise(resolve=>{map.once('idle',resolve);map.triggerRepaint()})},
  info(){return{engine:'MapLibre6.15.0',projection:'EPSG:3857',resolution:W/512/2**map.getZoom(),center:map.getCenter(),context:map.getCanvas().getContext('webgl2')?.getContextAttributes(),selected:current}},
  destroy(){map.remove()}
 };
 // promoteId is intentionally absent: both renderers keep the same numeric ids.
 return api;
}
