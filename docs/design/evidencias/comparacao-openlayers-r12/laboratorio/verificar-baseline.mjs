import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {corrigirCeuTransparente} from '/workspace/Raiz-mapa-integrado/front/compartilhado/vite-maplibre-ceu.ts';
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const vendor = '/workspace/Raiz-mapa-integrado/front/globo/node_modules/maplibre-gl';
const pkg = JSON.parse(fs.readFileSync(path.join(vendor, 'package.json')));
const raw = fs.readFileSync(path.join(vendor, 'dist/maplibre-gl.mjs'), 'utf8');
const patched = corrigirCeuTransparente(raw, pkg.version);
const guard = 'if(i["sky-color"].a===0&&i["horizon-color"].a===0)return;';
if (!patched.includes(guard) || raw.includes(guard)) throw new Error('Transformação do céu não demonstrada.');
const assets = 'dist/assets';
const mapFile = fs.readdirSync(assets).find(name => /^maplibre-.*\.js\.map$/.test(name));
const map = JSON.parse(fs.readFileSync(path.join(assets, mapFile)));
const index = map.sources.findIndex(name => name.endsWith('/maplibre-gl/dist/maplibre-gl.mjs'));
if (index < 0) throw new Error('Fonte do MapLibre ausente no sourcemap.');
const bundledSource = map.sourcesContent[index];
if (bundledSource !== patched) throw new Error('Fonte do bundle não é a transformação exata do plugin do produto.');
const bundleFile = path.join(assets, fs.readdirSync(assets).find(name => /^maplibre-.*\.js$/.test(name)));
const bundle = fs.readFileSync(bundleFile, 'utf8');
const guardFragments = [...bundle.matchAll(/.{0,55}\[["\x27\x60]sky-color["\x27\x60]\]\.a.{0,90}\[["\x27\x60]horizon-color["\x27\x60]\]\.a.{0,95}/g)].map(m => m[0]);
if (!guardFragments.length) throw new Error('Guarda alfa ausente no bundle compilado.');
const rawMapPath = path.join(vendor, 'dist/maplibre-gl.mjs.map');
const rawMap = JSON.parse(fs.readFileSync(rawMapPath));
const skyIndex = rawMap.sources.findIndex(name => name.endsWith('/sky.fragment.glsl.g.ts'));
if (skyIndex < 0) throw new Error('Fonte do shader de céu não encontrada.');
const skySource = rawMap.sourcesContent[skyIndex];
if (!skySource.includes('u_sky_color') || !skySource.includes('u_horizon_color') || !skySource.includes('mix(')) throw new Error('Shader de céu divergente.');
// Reprodução: comparar contra hashes registrados, nunca contra o próprio build.
const expected = JSON.parse(fs.readFileSync('auxiliares-esperados.json'));
const unchanged = [];
for (const [name, hash] of Object.entries(expected)) {
 const actual = sha(fs.readFileSync(path.join(assets, name)));
 if (actual !== hash) throw new Error('Auxiliar diverge do registro original: ' + name);
 unchanged.push({file:name,sha256:actual});
}
const proof = {version:pkg.version,raw_sha256:sha(raw),plugin_output_sha256:sha(patched),bundled_source_sha256:sha(bundledSource),exact_plugin_output_in_bundle:true,bundle_file:bundleFile,bundle_sha256:sha(bundle),compiled_guard:guardFragments,sky_shader_source:rawMap.sources[skyIndex],sky_shader_sha256:sha(skySource),sky_shader:skySource,unchanged};
fs.writeFileSync('baseline-verificado.json', JSON.stringify(proof,null,2)+'\n');
console.log(JSON.stringify({version:pkg.version,raw_sha256:sha(raw),plugin_output_sha256:sha(patched),exact_plugin_output_in_bundle:true,unchanged},null,2));
