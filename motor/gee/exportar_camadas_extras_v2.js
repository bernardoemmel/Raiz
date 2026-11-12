// RAÍZ: camadas extras v2 por estado (Brasil inteiro). Substitui a v1 (exportar_camadas_extras.js).
// O que mudou da v1:
//   - veg_baixa e veg_cresc corrigidos: o Global Pasture Watch já vem em decímetros (a v1 multiplicava por 10 e estourava)
//   - novas bandas: fogo_ultimo, cultura, cultura_anos, tmf, causa_perda
//   - exporta também o MapBiomas base do RJ, que faltou na primeira rodada
// Bandas (inteiras de 0 a 255, pixel de 30 m):
//   1 yb_idade     idade da floresta secundária no último ano (YbYrá-BR v9)
//   2 yb_perdas    quantas vezes a floresta secundária foi derrubada no pixel (YbYrá-BR v9)
//   3 fogo_anos    em quantos anos diferentes o pixel queimou (MapBiomas Fogo)
//   4 fogo_ultimo  último ano com fogo menos 1984 (ex.: 2024 = 40; 0 = nunca queimou)
//   5 veg_baixa    altura da vegetação baixa no último ano, em decímetros (Global Pasture Watch, 0 a 10 m)
//   6 veg_cresc    crescimento da vegetação baixa nos últimos 5 anos, em decímetros (+100 = sem mudança)
//   7 pasto_vigor  vigor do pasto no último ano (MapBiomas Pastagem: 1 baixo, 2 médio, 3 alto)
//   8 pasto_idade  idade do pasto como vem do MapBiomas (o script Python converte)
//   9 cultura      classe MapBiomas do último ano quando é agricultura ou silvicultura (39 soja, 20 cana, 46 café,
//                  47 citros, 62 algodão, 40 arroz, 41 outras temporárias, 48 outras perenes, 35 dendê, 9 silvicultura); 0 = não é
//  10 cultura_anos em quantos dos últimos 5 anos o pixel foi agricultura (0 a 5)
//  11 tmf          JRC Tropical Moist Forest, último ano (1 floresta intacta, 2 degradada, 3 desmatada, 4 em regeneração,
//                  5 água, 6 outro uso); 0 = fora da floresta úmida
//  12 causa_perda  causa dominante da perda de floresta (WRI/Google DeepMind Drivers, classe 1 a 7); 0 = sem perda
// Se uma camada não abrir, o console avisa "NÃO ABRIU" e a banda sai zerada; me mande o print do console.
// Cada estado vira uma tarefa na aba Tasks. Pasta no Drive: raiz_extras_v2 (e raiz para o MapBiomas do RJ).
// As tarefas da v1 que ainda não rodaram podem ser canceladas: a v2 tem tudo o que a v1 tinha.

function tipo(id) {
  try {
    var t = String(ee.data.getAsset(id).type).toUpperCase().replace('IMAGECOLLECTION', 'IMAGE_COLLECTION');
    print('ABRIU: ' + id + ' → ' + t);
    return t;
  } catch (e) { print('NÃO ABRIU: ' + id); return null; }
}
function comoImagem(id) {
  var t = tipo(id);
  if (t === 'IMAGE') return ee.Image(id);
  if (t === 'IMAGE_COLLECTION') return ee.ImageCollection(id).sort('system:time_start').toBands();
  return null;
}
// tenta vários endereços e usa o primeiro que abrir
function primeiro(ids) {
  for (var i = 0; i < ids.length; i++) { var im = comoImagem(ids[i]); if (im) return im; }
  return null;
}
function ultimaBanda(img) { return img.select(ee.String(img.bandNames().get(-1))); }
var zero = ee.Image(0);

// 1 e 2. YbYrá-BR v9
var ybBase = 'projects/ee-redd-brazil/assets/public/ybyra-br/secondary_forest_';
var ybAge = comoImagem(ybBase + 'age_collection11_v9');
var ybLoss = comoImagem(ybBase + 'loss_collection11_v9');
var yb_idade = ybAge ? ultimaBanda(ybAge).unmask(0) : zero;
var yb_perdas = ybLoss ? ybLoss.gt(0).reduce(ee.Reducer.sum()).unmask(0) : zero;

// 3 e 4. Fogo: anos com queimada e último ano com queimada
var fogoId = 'projects/mapbiomas-public/assets/brazil/fire/monitor/mapbiomas_fire_monthly_burned_v1';
var fogo_anos = zero, fogo_ultimo = zero;
var tf = tipo(fogoId);
var anuais = null;
if (tf === 'IMAGE_COLLECTION') {
  var fc = ee.ImageCollection(fogoId);
  anuais = ee.ImageCollection(ee.List.sequence(1985, 2026).map(function (a) {
    var s = fc.filter(ee.Filter.calendarRange(a, a, 'year'));
    var q = ee.Image(ee.Algorithms.If(s.size().gt(0), s.max().gt(0).unmask(0), zero)).rename('q').toUint8();
    return q.addBands(q.multiply(ee.Number(a).subtract(1984)).rename('ano').toUint8());
  }));
} else if (tf === 'IMAGE') {
  var fi = ee.Image(fogoId);
  var nomes = fi.bandNames();
  var anosB = nomes.map(function (n) { return ee.String(n).match('(19|20)[0-9]{2}').get(0); }).distinct();
  anuais = ee.ImageCollection(anosB.map(function (a) {
    var bs = nomes.filter(ee.Filter.stringContains('item', a));
    var q = fi.select(bs).gt(0).reduce(ee.Reducer.max()).unmask(0).rename('q').toUint8();
    return q.addBands(q.multiply(ee.Number.parse(a).subtract(1984)).rename('ano').toUint8());
  }));
}
if (anuais) {
  fogo_anos = anuais.select('q').sum();
  fogo_ultimo = anuais.select('ano').max();
}

// 5 e 6. Global Pasture Watch: vegetação baixa (já em decímetros, sem multiplicar)
var gpwId = 'projects/global-pasture-watch/assets/gsvh-30m/v1/short-veg-height_m';
var veg_baixa = zero, veg_cresc = ee.Image(100);
var tg = tipo(gpwId);
if (tg) {
  var gImg = tg === 'IMAGE_COLLECTION' ? ee.ImageCollection(gpwId).sort('system:time_start').toBands() : ee.Image(gpwId);
  print('bandas do Global Pasture Watch (confira a unidade)', gImg.bandNames());
  var n = gImg.bandNames().size();
  var g5 = gImg.select(ee.Number(n).subtract(6).max(0));
  var gL = gImg.select(ee.Number(n).subtract(1));
  veg_baixa = gL.unmask(0);
  veg_cresc = gL.subtract(g5).add(100).unmask(100);
}

// 7 e 8. MapBiomas Pastagem (coleção 10)
var vig = comoImagem('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_vigor_v3');
var pid = comoImagem('projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_pasture_age_v2');
var pasto_vigor = vig ? ultimaBanda(vig).unmask(0) : zero;
var pasto_idade = pid ? ultimaBanda(pid).unmask(0) : zero;

// 9 e 10. Cultura principal (MapBiomas cobertura, coleção 10; se não abrir, coleção 9)
var cov = primeiro([
  'projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_integration_v2',
  'projects/mapbiomas-public/assets/brazil/lulc/collection10/mapbiomas_brazil_collection10_integration_v1',
  'projects/mapbiomas-public/assets/brazil/lulc/collection9/mapbiomas_collection90_integration_v1'
]);
var CULT = [39, 20, 46, 47, 62, 40, 41, 48, 35, 9];
var AGRI = [39, 20, 46, 47, 62, 40, 41, 48, 35];
var cultura = zero, cultura_anos = zero;
if (cov) {
  var nb = cov.bandNames().size();
  var ult = cov.select(ee.Number(nb).subtract(1));
  cultura = ult.remap(CULT, CULT, 0);
  var ult5 = ee.List.sequence(ee.Number(nb).subtract(5), ee.Number(nb).subtract(1));
  cultura_anos = ee.ImageCollection(ult5.map(function (i) {
    return cov.select(ee.Number(i)).remap(AGRI, AGRI.map(function () { return 1; }), 0).rename('a');
  })).sum();
}

// 11. JRC Tropical Moist Forest (último ano da série anual)
var tmfImg = primeiro(['projects/JRC/TMF/v1_2024/AnnualChanges', 'projects/JRC/TMF/v1_2023/AnnualChanges']);
var tmf = tmfImg ? ultimaBanda(tmfImg).unmask(0) : zero;

// 12. Causas da perda de floresta (WRI e Google DeepMind)
var drv = primeiro([
  'projects/landandcarbon/assets/wri_gdm_drivers_forest_loss_1km/v1_2_2001_2024',
  'projects/landandcarbon/assets/wri_gdm_drivers_forest_loss_1km/v1_1_2001_2023'
]);
var causa_perda = zero;
if (drv) {
  print('bandas das causas de perda', drv.bandNames());
  // a primeira banda costuma ser a classe dominante; confira no print acima
  causa_perda = drv.select(0).unmask(0);
}

var img = ee.Image.cat([
  yb_idade.rename('yb_idade'), yb_perdas.rename('yb_perdas'),
  fogo_anos.rename('fogo_anos'), fogo_ultimo.rename('fogo_ultimo'),
  veg_baixa.rename('veg_baixa'), veg_cresc.rename('veg_cresc'),
  pasto_vigor.rename('pasto_vigor'), pasto_idade.rename('pasto_idade'),
  cultura.rename('cultura'), cultura_anos.rename('cultura_anos'),
  tmf.rename('tmf'), causa_perda.rename('causa_perda')
]).clamp(0, 255).toUint8();
print('bandas exportadas (devem ser 12)', img.bandNames());

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
    description: 'raiz_extras2_' + uf,
    folder: 'raiz_extras_v2',
    region: roi,
    scale: 30,
    crs: 'EPSG:4326',
    maxPixels: 1e13,
    fileFormat: 'GeoTIFF',
    formatOptions: {cloudOptimized: true}
  });
});

// MapBiomas base do RJ (faltou na primeira rodada): mesmas bandas dos outros estados fora da Amazônia
// cob2008, cob_atual, sec_idade, ano_desm (coleção 9, igual ao exportar_resto_brasil.js)
var base9 = 'projects/mapbiomas-public/assets/brazil/lulc/collection9/';
var ids9 = ee.data.listAssets(base9).assets.map(function (a) { return a.id; });
function pick9(re) { return ids9.filter(function (i) { return re.test(i); }); }
var cov9 = ee.Image(pick9(/integration/)[0]);
var secs9 = pick9(/secondar.*age/);
var sec9 = ee.Image(secs9.length ? secs9[0] : pick9(/secondar/)[0]);
var NATIVA = [3, 4, 5, 6, 11, 12, 13, 32, 29, 49, 50];
var HUMANO = [9, 15, 18, 19, 20, 21, 24, 25, 30, 35, 36, 39, 40, 41, 46, 47, 48, 62];
function classe9(ano, lista) {
  return cov9.select('classification_' + ano).remap(lista, lista.map(function () { return 1; }), 0);
}
var bandas9 = cov9.bandNames().getInfo();
var anoDesm = ee.Image(0);
bandas9.map(function (b) { return parseInt(b.slice(-4), 10); }).forEach(function (ano) {
  if (ano < 2001) return;
  anoDesm = anoDesm.where(classe9(ano - 1, NATIVA).and(classe9(ano, HUMANO)), ano - 2000);
});
var base = cov9.select('classification_2008').rename('cob2008')
  .addBands(cov9.select(ee.String(cov9.bandNames().get(-1))).rename('cob_atual'))
  .addBands(sec9.select(ee.String(sec9.bandNames().get(-1))).rename('sec_idade'))
  .addBands(anoDesm.rename('ano_desm'))
  .toUint8();
var roiRJ = ee.Geometry.Rectangle(estados.RJ);
Export.image.toDrive({
  image: base.clip(roiRJ),
  description: 'raiz_mapbiomas_RJ',
  folder: 'raiz',
  region: roiRJ,
  scale: 30,
  crs: 'EPSG:4326',
  maxPixels: 1e13,
  fileFormat: 'GeoTIFF',
  formatOptions: {cloudOptimized: true}
});
