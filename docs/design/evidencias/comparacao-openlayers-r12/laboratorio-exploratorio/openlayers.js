import Map from 'ol/Map.js';import View from 'ol/View.js';import TileLayer from 'ol/layer/Tile.js';import VectorLayer from 'ol/layer/Vector.js';import XYZ from 'ol/source/XYZ.js';import VectorSource from 'ol/source/Vector.js';import GeoJSON from 'ol/format/GeoJSON.js';import Feature from 'ol/Feature.js';import Polygon from 'ol/geom/Polygon.js';import {fromLonLat,toLonLat} from 'ol/proj.js';import Style from 'ol/style/Style.js';import Stroke from 'ol/style/Stroke.js';import Fill from 'ol/style/Fill.js';
export async function create({geo,scenario,view,onRender}){
 const format=new GeoJSON();const features=format.readFeatures(geo,{featureProjection:'EPSG:3857'});const src=new VectorSource({features,wrapX:false});let selected=null,hovered=null;
 const normal=new Style({stroke:new Stroke({lineCap:'butt',lineJoin:'miter',miterLimit:2,color:'rgba(21,35,27,.8)',width:1}),fill:new Fill({color:'rgba(21,35,27,0)'})});
 const overlap=new Style({stroke:new Stroke({lineCap:'butt',lineJoin:'miter',miterLimit:2,color:'rgba(21,35,27,.8)',width:1,lineDash:[3,3]}),fill:new Fill({color:'rgba(21,35,27,0)'})});
 const highlight=new Style({stroke:new Stroke({lineCap:'butt',lineJoin:'miter',miterLimit:2,color:'#1D6B44',width:2.5})});
 const dashPixels=res=>3*2**(Math.log2(40075016.68557849/512/res)%1);
 const applyDash=res=>{const d=dashPixels(res);overlap.getStroke().setLineDash([d,d])};applyDash(view.resolution);
 const maskSource=new VectorSource({wrapX:false});
 const farms=new VectorLayer({source:src,renderOrder:(a,b)=>a.get('ordem_desenho')-b.get('ordem_desenho'),style:f=>f.get('sobreposto')?overlap:normal,updateWhileAnimating:true,updateWhileInteracting:true});
 const selectedLayer=new VectorLayer({source:src,style:f=>f.getId()===selected||f.getId()===hovered?highlight:null});
 const satSource=new XYZ({url:'/tiles/{z}/{x}/{y}.jpg',minZoom:14,maxZoom:14,crossOrigin:'anonymous',transition:0,wrapX:false});
 satSource.on('tileloaderror',()=>{window.__mapErrors??=[];window.__mapErrors.push('Falha de tile Sentinel')});
 const veilSource=new VectorSource({features:[new Feature(new Polygon([[[-20037508,-20037508],[-20037508,20037508],[20037508,20037508],[20037508,-20037508],[-20037508,-20037508]]]))]});
 const map=new Map({target:'mapa',pixelRatio:1,controls:[],interactions:[],layers:[new TileLayer({source:satSource,preload:0}),new VectorLayer({source:veilSource,style:new Style({fill:new Fill({color:'rgba(250,250,247,.3)'})})}),new VectorLayer({source:maskSource,style:new Style({fill:new Fill({color:'rgba(15,26,20,.45)'})})}),farms,selectedLayer],view:new View({projection:'EPSG:3857',center:view.center,resolution:view.resolution,constrainResolution:false,maxZoom:30})});
 map.on('postrender',e=>onRender({center:e.frameState.viewState.center.slice(),resolution:e.frameState.viewState.resolution}));
 await new Promise(r=>map.once('rendercomplete',r));
 return{
  setView(v){if(map.getView().getResolution()!==v.resolution){applyDash(v.resolution);farms.changed()}map.getView().setCenter(v.center);map.getView().setResolution(v.resolution)},
  pixel(lnglat){return map.getPixelFromCoordinate(fromLonLat(lnglat))},
  hit(p){const found=[];map.forEachFeatureAtPixel(p,f=>{found.push(f)},{layerFilter:l=>l===farms,hitTolerance:0});found.sort((a,b)=>b.get('ordem_desenho')-a.get('ordem_desenho'));return found[0]?.getId()??null},
  select(id){selected=id;maskSource.clear();if(id!==null)maskSource.addFeature(format.readFeature(scenario.mask[String(id)],{featureProjection:'EPSG:3857'}));selectedLayer.changed()},
  hover(id){hovered=id;selectedLayer.changed()},
  async idle(){map.render();await new Promise(r=>map.once('rendercomplete',r))},
  info(){return{engine:'OpenLayers10.11.0Canvas',projection:'EPSG:3857',resolution:map.getView().getResolution(),center:toLonLat(map.getView().getCenter()),selected}},
  destroy(){map.dispose()}
 }
}
