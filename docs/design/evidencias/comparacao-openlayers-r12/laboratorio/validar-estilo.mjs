// Validação equivalente à executada antes da série original. Nenhum navegador.
import fs from 'node:fs';
import {validateStyleMin} from '/workspace/Raiz-mapa-integrado/front/globo/node_modules/@maplibre/maplibre-gl-style-spec/dist/index.mjs';
const code = fs.readFileSync('maplibre.js', 'utf8');
const expression = code.split('const style=')[1].split('\n const map=')[0].trim().replace(/;$/, '');
const geo = JSON.parse(fs.readFileSync('public/dados/imoveis.geojson'));
// A expressão é o código controlado do adaptador local, nunca entrada de rede.
const style = new Function('geo', 'location', 'return (' + expression + ')')(geo, {origin:'http://127.0.0.1:8765'});
const errors = validateStyleMin(style).map(error => error.message);
fs.writeFileSync('validacao-estilo.json', JSON.stringify({validator:'@maplibre/maplibre-gl-style-spec26.6.0', errors}, null, 2));
if (errors.length) throw new Error(JSON.stringify(errors));
console.log('Estilo validado sem erros.');
