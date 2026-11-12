// RAÍZ: exporta o MapBiomas (coleção 9) dos 9 estados da Amazônia Legal para o Google Drive
// Bandas: cob2008 (cobertura em 2008), cob_atual (cobertura mais recente), sec_idade (idade da vegetação secundária)
// Cada estado vira uma tarefa na aba Tasks. Clique em RUN em cada uma (pode rodar todas ao mesmo tempo).

var base = 'projects/mapbiomas-public/assets/brazil/lulc/collection9/';
var ids = ee.data.listAssets(base).assets.map(function (a) { return a.id; });
function pick(re) { return ids.filter(function (i) { return re.test(i); }); }

var cov = ee.Image(pick(/integration/)[0]);
var secs = pick(/secondar.*age/);
var sec = ee.Image(secs.length ? secs[0] : pick(/secondar/)[0]);
print('cobertura', cov.bandNames());
print('secundaria', sec.bandNames());

var img = cov.select('classification_2008').rename('cob2008')
  .addBands(cov.select(ee.String(cov.bandNames().get(-1))).rename('cob_atual'))
  .addBands(sec.select(ee.String(sec.bandNames().get(-1))).rename('sec_idade'))
  .toUint8();

// Retângulo de cada estado [oeste, sul, leste, norte], com folga
var estados = {
  AC: [-74.1, -11.2, -66.5, -7.0],
  AM: [-74.0, -10.0, -56.0, 2.3],
  AP: [-54.9, -1.3, -49.8, 4.5],
  MA: [-48.8, -10.3, -41.7, -1.0],
  MT: [-61.7, -18.1, -50.1, -7.3],
  PA: [-58.9, -9.9, -46.0, 2.7],
  RO: [-66.9, -13.8, -59.7, -7.9],
  RR: [-64.9, -1.6, -58.8, 5.3],
  TO: [-50.8, -13.5, -45.6, -5.1]
};

Object.keys(estados).forEach(function (uf) {
  var roi = ee.Geometry.Rectangle(estados[uf]);
  Export.image.toDrive({
    image: img.clip(roi),
    description: 'raiz_mapbiomas_' + uf,
    folder: 'raiz',
    region: roi,
    scale: 30,
    crs: 'EPSG:4326',
    maxPixels: 1e13,
    fileFormat: 'GeoTIFF',
    formatOptions: {cloudOptimized: true}
  });
});
