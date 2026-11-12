// RAÍZ: camadas extras por estado (Brasil inteiro), para a nota de persistência, o fogo e o pasto
// Bandas (todas inteiras de 0 a 255, pixel de 30 m):
//   yb_idade    idade da floresta secundária no último ano (YbYrá-BR v9, Silva Junior et al.)
//   yb_perdas   quantas vezes a floresta secundária foi derrubada no pixel (YbYrá-BR v9)
//   fogo_anos   em quantos anos diferentes o pixel queimou (MapBiomas Monitor do Fogo)
//   veg_baixa   altura da vegetação baixa no último ano, em decímetros (Global Pasture Watch, 0 a 10 m)
//   veg_cresc   crescimento da vegetação baixa nos últimos 5 anos, em decímetros (+100 = sem mudança)
//   pasto_vigor vigor do pasto no último ano (MapBiomas Pastagem: 1 baixo, 2 médio, 3 alto)
//   pasto_idade idade do pasto em anos (MapBiomas Pastagem)
// Se uma camada não abrir, o console avisa e a banda sai zerada; me mande o print do console.
// Cada estado vira uma tarefa na aba Tasks. Clique em RUN em cada uma. Pasta no Drive: raiz_extras

function tipo(id) {
  try {
    var t = String(ee.data.getAsset(id).type).toUpperCase().replace('IMAGECOLLECTION', 'IMAGE_COLLECTION');
    print(id + ' → ' + t);
    return t;
  } catch (e) { print('NÃO ABRIU: ' + id); return null; }
}
function ultimaBanda(img) { return img.select(ee.String(img.bandNames().get(-1))); }
function comoImagem(id) {
  var t = tipo(id);
  if (t === 'IMAGE') return ee.Image(id);
  if (t === 'IMAGE_COLLECTION') return ee.ImageCollection(id).toBands();
  return null;
}
var zero = ee.Image(0);

// YbYrá-BR v9
var ybBase = 'projects/ee-redd-brazil/assets/public/ybyra-br/secondary_forest_';
var ybAge = comoImagem(ybBase + 'age_collection11_v9');
var ybLoss = comoImagem(ybBase + 'loss_collection11_v9');
var yb_idade = ybAge ? ultimaBanda(ybAge).unmask(0) : zero;
var yb_perdas = ybLoss ? ybLoss.gt(0).reduce(ee.Reducer.sum()).unmask(0) : zero;

// Fogo: conta anos com queimada (bandas ou imagens mensais agrupadas por ano)
var fogoId = 'projects/mapbiomas-public/assets/brazil/fire/monitor/mapbiomas_fire_monthly_burned_v1';
var fogo_anos = zero;
var tf = tipo(fogoId);
if (tf === 'IMAGE_COLLECTION') {
  var fc = ee.ImageCollection(fogoId);
  var anosF = ee.List.sequence(1985, 2026);
  fogo_anos = ee.ImageCollection(anosF.map(function (a) {
    var s = fc.filter(ee.Filter.calendarRange(a, a, 'year'));
    return ee.Image(ee.Algorithms.If(s.size().gt(0), s.max().gt(0).unmask(0), zero)).rename('q').toUint8();
  })).sum();
} else if (tf === 'IMAGE') {
  var fi = ee.Image(fogoId);
  print('bandas do fogo', fi.bandNames());
  // uma banda por mês ou por ano: agrupa pelo ano no nome da banda
  var nomes = fi.bandNames();
  var anosB = nomes.map(function (n) { return ee.String(n).match('(19|20)[0-9]{2}').get(0); }).distinct();
  fogo_anos = ee.ImageCollection(anosB.map(function (a) {
    var bs = nomes.filter(ee.Filter.stringContains('item', a));
    return fi.select(bs).gt(0).reduce(ee.Reducer.max()).unmask(0).rename('q').toUint8();
  })).sum();
}

// Global Pasture Watch: vegetação baixa (0 a 10 m)
var gpwId = 'projects/global-pasture-watch/assets/gsvh-30m/v1/short-veg-height_m';
var veg_baixa = zero, veg_cresc = ee.Image(100);
var tg = tipo(gpwId);
if (tg) {
  var gImg = tg === 'IMAGE_COLLECTION' ? ee.ImageCollection(gpwId).sort('system:time_start').toBands() : ee.Image(gpwId);
  var n = gImg.bandNames().size();
  var g5 = gImg.select(ee.Number(n).subtract(6).max(0));
  var gL = gImg.select(ee.Number(n).subtract(1));
  veg_baixa = gL.multiply(10).unmask(0);
  veg_cresc = gL.subtract(g5).multiply(10).add(100).unmask(100);
}

// MapBiomas Pastagem (coleção 10)
var vig = comoImagem('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_vigor_v3');
var pid = comoImagem('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_age_v2');
var pasto_vigor = vig ? ultimaBanda(vig).unmask(0) : zero;
var pasto_idade = pid ? ultimaBanda(pid).unmask(0) : zero;

var img = ee.Image.cat([
  yb_idade.rename('yb_idade'), yb_perdas.rename('yb_perdas'), fogo_anos.rename('fogo_anos'),
  veg_baixa.rename('veg_baixa'), veg_cresc.rename('veg_cresc'),
  pasto_vigor.rename('pasto_vigor'), pasto_idade.rename('pasto_idade')
]).clamp(0, 255).toUint8();
print('bandas exportadas', img.bandNames());

// Retângulo de cada estado [oeste, sul, leste, norte], com folga
var estados = {
  AC: [-74.1, -11.2, -66.5, -7.0], AM: [-74.0, -10.0, -56.0, 2.3], AP: [-54.9, -1.3, -49.8, 4.5],
  MA: [-48.8, -10.3, -41.7, -1.0], MT: [-61.7, -18.1, -50.1, -7.3], PA: [-58.9, -9.9, -46.0, 2.7],
  RO: [-66.9, -13.8, -59.7, -7.9], RR: [-64.9, -1.6, -58.8, 5.3], TO: [-50.8, -13.5, -45.6, -5.1],
  AL: [-38.4, -10.6, -35.0, -8.7], BA: [-46.8, -18.5, -37.2, -8.4], CE: [-41.5, -7.9, -37.1, -2.7],
  DF: [-48.4, -16.1, -47.2, -15.4], ES: [-41.9, -21.4, -39.6, -17.8], GO: [-53.3, -19.6, -45.8, -12.3],
  MG: [-51.1, -23.0, -39.8, -14.2], MS: [-58.2, -24.1, -50.8, -17.1], PB: [-38.8, -8.4, -34.7, -5.9],
  PE: [-41.4, -9.5, -34.8, -7.2], PI: [-46.0, -11.0, -40.3, -2.7], PR: [-54.7, -26.8, -48.0, -22.5],
  RJ: [-44.9, -23.4, -40.9, -20.7], RN: [-38.6, -7.0, -34.9, -4.8], RS: [-57.7, -33.8, -49.6, -27.0],
  SC: [-53.9, -29.4, -48.3, -25.9], SE: [-38.3, -11.6, -36.3, -9.5], SP: [-53.2, -25.4, -44.1, -19.7]
};

Object.keys(estados).forEach(function (uf) {
  var roi = ee.Geometry.Rectangle(estados[uf]);
  Export.image.toDrive({
    image: img.clip(roi),
    description: 'raiz_extras_' + uf,
    folder: 'raiz_extras',
    region: roi,
    scale: 30,
    crs: 'EPSG:4326',
    maxPixels: 1e13,
    fileFormat: 'GeoTIFF',
    formatOptions: {cloudOptimized: true}
  });
});
