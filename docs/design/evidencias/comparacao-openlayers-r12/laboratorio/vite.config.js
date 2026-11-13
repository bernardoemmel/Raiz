import {maplibreCeuTransparente} from '/workspace/Raiz-mapa-integrado/front/compartilhado/vite-maplibre-ceu.ts';
export default {plugins:[maplibreCeuTransparente()],build:{outDir:'dist',sourcemap:true},server:{fs:{allow:['/tmp/raiz-comparacao-openlayers-corrigida','/workspace/Raiz-mapa-integrado']}}};
