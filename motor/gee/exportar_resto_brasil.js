// RAÍZ: exporta o MapBiomas (coleção 9) dos 18 estados FORA da Amazônia Legal para o Google Drive
// Bandas: cob2008, cob_atual, sec_idade (iguais às da Amazônia Legal) + ano_desm
// ano_desm = último ano em que o pixel passou de vegetação nativa para uso humano (2023 vira 23; 0 = nunca).
// Fora da Amazônia não existe PRODES, então essa banda faz o papel dele (régua de anos sem desmatamento).
// Cada estado vira uma tarefa na aba Tasks. Clique em RUN em cada uma (pode rodar todas ao mesmo tempo).

var base = 'projects/mapbiomas-public/assets/brazil/lulc/collection9/';
var ids = ee.data.listAssets(base).assets.map(function (a) { return a.id; });
function pick(re) { return ids.filter(function (i) { return re.test(i); }); }

var cov = ee.Image(pick(/integration/)[0]);
var secs = pick(/secondar.*age/);
var sec = ee.Image(secs.length ? secs[0] : pick(/secondar/)[0]);
var bandas = cov.bandNames().getInfo();
print('cobertura', bandas);
print('secundaria', sec.bandNames());

// Vegetação nativa: floresta, savana, mangue, floresta alagável, campo alagado, campo, outras não florestais,
// apicum, afloramento rochoso, restinga
var NATIVA = [3, 4, 5, 6, 11, 12, 13, 32, 29, 49, 50];
// Uso humano: pasto, agricultura, silvicultura, mosaico, área urbana, mineração, outras áreas não vegetadas
var HUMANO = [9, 15, 18, 19, 20, 21, 24, 25, 30, 35, 36, 39, 40, 41, 46, 47, 48, 62];
function classe(ano, lista) {
  return cov.select('classification_' + ano)
    .remap(lista, lista.map(function () { return 1; }), 0);
}

var anoDesm = ee.Image(0);
var anos = bandas.map(function (b) { return parseInt(b.slice(-4), 10); });
anos.forEach(function (ano) {
  if (ano < 2001) return;
  var virou = classe(ano - 1, NATIVA).and(classe(ano, HUMANO));
  anoDesm = anoDesm.where(virou, ano - 2000);
});

var img = cov.select('classification_2008').rename('cob2008')
  .addBands(cov.select(ee.String(cov.bandNames().get(-1))).rename('cob_atual'))
  .addBands(sec.select(ee.String(sec.bandNames().get(-1))).rename('sec_idade'))
  .addBands(anoDesm.rename('ano_desm'))
  .toUint8();

// Retângulo de cada estado [oeste, sul, leste, norte], com folga
var estados = {
  AL: [-38.4, -10.6, -35.0, -8.7],
  BA: [-46.8, -18.5, -37.2, -8.4],
  CE: [-41.5, -7.9, -37.1, -2.7],
  DF: [-48.4, -16.1, -47.2, -15.4],
  ES: [-41.9, -21.4, -39.6, -17.8],
  GO: [-53.3, -19.6, -45.8, -12.3],
  MG: [-51.1, -23.0, -39.8, -14.2],
  MS: [-58.2, -24.1, -50.8, -17.1],
  PB: [-38.8, -8.4, -34.7, -5.9],
  PE: [-41.4, -9.5, -34.8, -7.2],
  PI: [-46.0, -11.0, -40.3, -2.7],
  PR: [-54.7, -26.8, -48.0, -22.5],
  RJ: [-44.9, -23.4, -40.9, -20.7],
  RN: [-38.6, -7.0, -34.9, -4.8],
  RS: [-57.7, -33.8, -49.6, -27.0],
  SC: [-53.9, -29.4, -48.3, -25.9],
  SE: [-38.3, -11.6, -36.3, -9.5],
  SP: [-53.2, -25.4, -44.1, -19.7]
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
