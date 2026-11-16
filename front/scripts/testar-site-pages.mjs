#!/usr/bin/env node
/** Testa o site compilado: só arquivos e HTTP Range, sem API nem fallback do Vite.
 * Antes: preparar-teste-site.mjs e construir-site.sh com RAIZ_DADOS/RAIZ_GEO apontando à fixture,
 * RAIZ_CALENDARIO_DADOS apontando ao calendário da fixture, RAIZ_BASE=/Raiz/, VITE_RAIZ_TESTE_MAPA=1
 * e VITE_RAIZ_PROCESSAMENTO_URL=./amostra/processamento.json. PLAYWRIGHT_CHROMIUM_EXECUTABLE é opcional no ambiente local.
 */
import assert from "node:assert/strict"
import { conferirCicloMapa } from "./conferir-ciclo-mapa.mjs"
import { conferirAtribuicaoCompacta } from "./conferir-atribuicao.mjs"
import { conferirEstabilidadePainelBrasil, conferirProcessamentoEstavel } from "./conferir-processamento-estavel.mjs"
import { configurarPublicacao } from "./configurar-publicacao.mjs"
import fs from "node:fs"
import http from "node:http"
import { createRequire } from "node:module"
import path from "node:path"
import zlib from "node:zlib"
import { CANARIO_PRIVADO, CAR, CAR_FRONTEIRA, CARS, MUNICIPIO, MUNICIPIOS_FRONTEIRA, REPO, SEM_DESENHO } from "./preparar-teste-site.mjs"

const require = createRequire(path.join(REPO, "front/globo/package.json"))
const { chromium } = require("playwright")
const { PNG } = require("pngjs")
const { default: AxeBuilder } = require("@axe-core/playwright")
const site = path.join(REPO, "site")
const prefixo = configurarPublicacao(process.env).base
assert(prefixo.startsWith("/") && prefixo.endsWith("/"), "RAIZ_BASE precisa começar e terminar em /.")
const resultado = path.join(REPO, "front/.cache/teste-site/resultado")
fs.mkdirSync(resultado, { recursive: true })
const tipos = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".geojson": "application/geo+json", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".gz": "application/gzip" }
const ausentes = [], faixas = [], erros = [], pedidos = []
const servidor = http.createServer((req, res) => {
  const url = new URL(req.url, "http://localhost")
  const pathname = decodeURIComponent(url.pathname)
  const rel = pathname.slice(prefixo.length)
  const arquivo = path.resolve(site, !rel || rel.endsWith("/") ? rel + "index.html" : rel)
  if (!pathname.startsWith(prefixo) || !arquivo.startsWith(site + path.sep) || !fs.existsSync(arquivo) || !fs.statSync(arquivo).isFile()) {
    ausentes.push(url.pathname)
    res.writeHead(404).end("Arquivo não encontrado")
    return
  }
  const bytes = fs.readFileSync(arquivo)
  const faixa = /^bytes=(\d+)-(\d*)$/.exec(req.headers.range ?? "")
  const headers = { "Content-Type": tipos[path.extname(arquivo)] ?? "application/octet-stream", "Accept-Ranges": "bytes" }
  if (faixa) {
    const inicio = Number(faixa[1]), fim = Math.min(Number(faixa[2] || bytes.length - 1), bytes.length - 1)
    if (inicio > fim) return res.writeHead(416, { "Content-Range": `bytes */${bytes.length}` }).end()
    faixas.push({ arquivo: rel, inicio, fim })
    res.writeHead(206, { ...headers, "Content-Range": `bytes ${inicio}-${fim}/${bytes.length}`, "Content-Length": fim - inicio + 1 })
    res.end(bytes.subarray(inicio, fim + 1))
  } else {
    res.writeHead(200, { ...headers, "Content-Length": bytes.length })
    res.end(req.method === "HEAD" ? undefined : bytes)
  }
})
await new Promise((resolve) => servidor.listen(0, "127.0.0.1", resolve))
const base = `http://127.0.0.1:${servidor.address().port}${prefixo}`
const navegador = await chromium.launch({
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}),
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
})
const contexto = await navegador.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" })
const pagina = await contexto.newPage()
// Apenas o mosaico do teste é sintético. O raster percorre o protocolo real do MapLibre, sem acesso externo no CI.
const tile = new PNG({ width: 256, height: 256 })
for (let i = 0; i < tile.data.length; i += 4) tile.data.set([70, 100, 65, 255], i)
const tilePng = PNG.sync.write(tile)
const pedidosSatelite = []
await pagina.route("https://tiles.maps.eox.at/**", (rota) => {
  pedidosSatelite.push(rota.request().url())
  return rota.fulfill({ status: 200, contentType: "image/png", body: tilePng, headers: { "Access-Control-Allow-Origin": "*" } })
})
pagina.on("request", (r) => pedidos.push(r.url()))
pagina.on("pageerror", (e) => erros.push(e.message))
pagina.on("response", (r) => { if (r.status() >= 400) erros.push(`${r.status()} ${r.url()}`) })
pagina.on("console", (m) => { if (m.type() === "error") erros.push(m.text()) })

function conferirPublicacao() {
  const arquivos = (pasta) => fs.readdirSync(pasta, { withFileTypes: true }).flatMap((item) => {
    const arquivo = path.join(pasta, item.name)
    return item.isDirectory() ? arquivos(arquivo) : [arquivo]
  })
  const estados = JSON.parse(fs.readFileSync(path.join(site, "amostra/estados.json"), "utf8"))
  assert.equal(estados.acesso, "publico_basico", "A camada individual requer o contrato público básico explícito.")
  const permitidos = new Set()
  const todos = ["amostra", "geo"].flatMap((pasta) => arquivos(path.join(site, pasta)))
  // A fixture usa municípios sem vírgulas: cabeçalho e linhas exatos impedem colunas privadas no CSV servido.
  for (const arquivo of todos.filter((a) => /imoveis_basicos_\d{7}\.csv\.gz$/.test(a))) {
    const texto = zlib.gunzipSync(fs.readFileSync(arquivo)).toString("utf8")
    const [cabecalho, ...linhas] = texto.trimEnd().split(/\r?\n/)
    assert.equal(cabecalho, "cod_imovel,cod_ibge,municipio,uf,situacao_basica")
    for (const linha of linhas) {
      const campos = linha.split(",")
      assert.equal(campos.length, 5, "Somente cinco campos básicos por imóvel.")
      assert.match(campos[0], /^[A-Z]{2}-\d{7}-[A-F0-9]{32}$/)
      assert(["apto", "com_pendencia", "nao_apto"].includes(campos[4]))
      permitidos.add(campos[0])
    }
  }
  assert.equal(permitidos.size, CARS.length + 2, "A publicação básica inclui todas as fazendas da fixture.")
  for (const arquivo of todos) {
    const nome = path.relative(site, arquivo)
    assert(!/(?:^|\/)(?:imoveis_\d{7}\.csv|filtros_|ficha_|certidoes_|desenvolvedor_)/.test(nome), `Camada paga publicada: ${nome}`)
    assert(!nome.includes("/fichas/"), `Ficha individual publicada: ${nome}`)
    if (!/\.(json|geojson|csv)(\.gz)?$/.test(nome)) continue
    const bytes = fs.readFileSync(arquivo)
    const texto = (nome.endsWith(".gz") ? zlib.gunzipSync(bytes) : bytes).toString("utf8")
    assert(!texto.includes(CANARIO_PRIVADO), `Conteúdo pago publicado: ${nome}`)
    if (/imoveis_basicos_\d{7}\.csv\.gz$/.test(nome)) continue
    if (/imoveis_\d{7}\.geojson\.gz$/.test(nome)) {
      const geo = JSON.parse(texto)
      assert.equal(geo.type, "FeatureCollection")
      assert.equal(geo.features.length, CARS.length, "CAR sem registro básico precisa ser excluído da geometria.")
      for (const f of geo.features) {
        assert.deepEqual(Object.keys(f).sort(), ["geometry", "properties", "type"])
        assert(Object.keys(f.properties).every((k) => ["cod_imovel", "sobreposto"].includes(k)), "A geometria só pode carregar CAR e indicador topológico.")
        if ("sobreposto" in f.properties) assert.equal(typeof f.properties.sobreposto, "boolean")
        assert(permitidos.has(f.properties.cod_imovel))
      }
      continue
    }
    if (/car_[A-Z]{2}\.json$/.test(nome)) {
      for (const [car, cod] of Object.entries(JSON.parse(texto))) {
        assert(permitidos.has(car), "O índice CAR só admite registros do contrato básico.")
        assert.match(cod, /^\d{7}$/)
      }
      continue
    }
    assert(!texto.includes("cod_imovel"), `Identificador individual fora do contrato básico: ${nome}`)
    assert(!/[A-Z]{2}-[0-9]{7}-[A-F0-9]{32}/.test(texto), `CAR fora do contrato básico: ${nome}`)
  }
}

async function abrirDados() {
  const dialogo = pagina.locator(".dados-mapa-v2")
  if (!await dialogo.count() || !await dialogo.evaluate(el => el.open)) await pagina.getByRole("button", { name: /^Sobre os dados/ }).click()
}
async function fecharDados() {
  if (await pagina.locator(".dados-mapa-v2").count() && await pagina.locator(".dados-mapa-v2").evaluate(el => el.open)) await pagina.getByRole("button", { name: "Fechar dados", exact: true }).click()
}
async function abrirMenu() {
  if (!await pagina.locator(".topo-conta").evaluate(el => el.open)) await pagina.locator(".topo-conta > summary").click()
}
async function buscar(texto, destino) {
  await fecharDados()
  const busca = pagina.locator(".topo .busca input")
  await busca.fill(texto)
  await pagina.locator('.busca [role="option"]').first().waitFor()
  await busca.press("Enter")
  await pagina.waitForURL((u) => decodeURIComponent(u.hash) === destino)
}
async function mapaPronto() {
  await pagina.waitForFunction(() => {
    const m = document.querySelector(".mapa-brasil .mapa")?.__mapa
    return m?.loaded() && !m.isMoving()
  }, null, { timeout: 30000 })
}
async function pontoDaFazenda(camera, car, etapa) {
  await pagina.waitForFunction(async ({ car, municipio }) => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    const [imoveis, limite] = await Promise.all([m.getSource("imoveis").getData(), m.getSource("municipio").getData()])
    return imoveis.features.some(f => f.properties.cod_imovel === car)
      && limite.features.some(f => String(f.properties.cod_ibge) === municipio)
  }, { car, municipio: MUNICIPIO })
  // Fontes em cache podem estar prontas antes do commit da nova rota. Dois frames
  // deixam o efeito de enquadramento iniciar; mapaPronto espera esse voo terminar.
  await pagina.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await mapaPronto()
  const evidencia = await pagina.evaluate(async camera => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    // A fonte pode estar pronta antes do efeito React que enquadra a nova rota.
    // Deixa esse enquadramento apresentar seu frame antes da aproximação do teste.
    await new Promise(resolve => { m.once("idle", resolve); m.triggerRepaint() })
    const antes = { center: m.getCenter().toArray(), zoom: m.getZoom() }
    await new Promise(resolve => { m.once("idle", resolve); m.jumpTo(camera); m.triggerRepaint() })
    const p = m.project([-49.925, -6.102]), r = m.getCanvas().getBoundingClientRect()
    return { antes, depois: { center: m.getCenter().toArray(), zoom: m.getZoom() },
      ponto: { x: r.x + p.x, y: r.y + p.y },
      feicoes: m.queryRenderedFeatures(p, { layers: ["imoveis"] }).map(f => ({ source: f.source, car: f.properties.cod_imovel })) }
  }, camera)
  fs.writeFileSync(path.join(resultado, `selecao-${etapa}.json`), JSON.stringify(evidencia, null, 2))
  assert.equal(evidencia.depois.zoom, camera.zoom, "O enquadramento precisa terminar antes de reprojetar o ponto do clique.")
  assert.equal(evidencia.feicoes[0]?.car, car, "O ponto reprojetado precisa atingir o CAR esperado no desenho real.")
  return evidencia.ponto
}

try {
  conferirPublicacao()
  console.log("Abrindo o build estático básico no Chromium...")
  await pagina.goto(base)
  await mapaPronto()
  const apresentacao = await pagina.evaluate(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    return { solicitada: m._canvasContextAttributes.desynchronized, efetiva: m.getCanvas().getContext("webgl2").getContextAttributes().desynchronized }
  })
  assert.equal(apresentacao.solicitada, false, "O mapa preserva a composição normal pela opção pública do MapLibre.")
  assert.equal(apresentacao.efetiva, false, "O navegador compõe mapa e cartões no mesmo ciclo de apresentação.")
  assert.equal(pedidos.filter(url => url === new URL("geo/brasil_estados.geojson", base).href).length, 2,
    "A geometria é lida para enquadramento e pela URL no worker; o navegador pode reutilizar o cache HTTP.")
  assert.equal(await pagina.locator(".mapa-brasil svg").count(), 0, "A entrada abre no MapLibre, sem o SVG nacional.")
  await abrirDados()
  await pagina.getByRole("heading", { name: "Cobertura do mapa", exact: true }).waitFor()
  await pagina.waitForFunction(() => document.querySelectorAll(".processamento-estado").length === 27)
  assert(pedidos.some((u) => new URL(u).pathname === `${prefixo}amostra/processamento.json`),
    "O processamento no build de teste deve vir da fixture local, sem depender do Actions.")
  assert.equal(await pagina.locator(".processamento-aviso").count(), 0)
  assert((await pagina.locator(".processamento-situacao").allTextContents())
    .every((texto) => texto === "Sem informação de processamento"), "A fixture não inventa execução municipal.")
  await pagina.getByText("1 município em 1 estado", { exact: true }).waitFor()
  await pagina.locator('time[datetime="2026-11-12T10:41:00Z"]').first().waitFor()
  await pagina.locator('time[datetime="2026-11-11T18:00:00Z"]').first().waitFor()
  await fecharDados()
  // H3 recebe somente células agregadas, antes de qualquer limite municipal ou CAR.
  await pagina.waitForFunction(() => {
    return document.querySelector(".mapa-brasil .mapa").__hexagonos?.reduce((s, h) => s + h.fazendas, 0) === 11
  })
  assert(!pedidos.some(url => /brasil_municipios|imoveis_\d|imoveis_basicos_/.test(url)), "A entrada não pode baixar milhares de polígonos nem tabelas individuais.")
  const inicial = await pagina.evaluate(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    const hexagonos = document.querySelector(".mapa-brasil .mapa").__hexagonos
    return { hexagonos, camada: m.getLayer("hexagonos").type, zoom: m.getZoom(), fonteDuplicada: !!m.getSource("agregados-nacionais"),
      poligonos: m.queryRenderedFeatures({ layers: ["hexagonos"] }).map(f => f.geometry.type),
      fundo: m.getPaintProperty("background", "background-color") }
  })
  // O worker próprio calcula e devolve polígonos, sem trazer composição de imóveis.
  assert(pedidos.includes(new URL("geo/agregados_brasil.geojson", base).href), "O mapa deve carregar a projeção normal anunciada para o worker.")
  assert(!pedidos.some(url => url.endsWith("/agregados_brasil.geojson.gz")), "A publicação nova não baixa também o agregado legado.")
  assert.equal(inicial.camada, "fill", "Hexágonos reais substituem círculos por pixels.")
  assert(inicial.poligonos.length > 0 && inicial.poligonos.every(t => t === "Polygon"))
  assert.equal(inicial.hexagonos.reduce((s, h) => s + h.fazendas, 0), 11)
  assert.equal(inicial.hexagonos.reduce((s, h) => s + (h.hectares ?? 0), 0), 1000)
  assert.equal(inicial.hexagonos.reduce((s, h) => s + h.semMedida, 0), 1)
  assert(inicial.hexagonos.every(h => h.resolucao === 4))
  assert.equal(inicial.fundo, "#111815", "A base inicial usa a paleta escura aprovada.")
  assert.equal(inicial.fonteDuplicada, false, "O GeoJSON bruto não se duplica numa fonte MapLibre.")
  assert.equal(await pagina.locator("button.cartografia-grupo").count(), 0)
  assert.equal(pedidosSatelite.length, 0, "A entrada nacional não baixa imagens de satélite.")
  await pagina.screenshot({ path: path.join(resultado, "depois-nacional-1440.png"), fullPage: true })
  // CAR cadastrado na PB, publicado em dois recortes do RN: uma opção, sem consultar arquivos da PB.
  const inicioFronteira = pedidos.length
  const buscaFronteira = pagina.locator(".topo .busca input")
  await buscaFronteira.fill(CAR_FRONTEIRA)
  const opcaoFronteira = pagina.locator('.busca [role="option"]').filter({ hasText: "Município de fronteira (RN)" })
  await opcaoFronteira.waitFor()
  assert.equal(await pagina.locator('.busca [role="option"]').count(), 1, "O mesmo CAR em dois recortes não pode duplicar a opção nem seu ID acessível.")
  const estadosPublicados = JSON.parse(fs.readFileSync(path.join(site, "amostra/estados.json"), "utf8"))
  assert.equal(estadosPublicados.estados.find(e => e.uf === "PB").situacao, "sem_dados")
  assert.equal(estadosPublicados.car_fronteira, "car_fronteira.json")
  assert.deepEqual(pedidos.slice(inicioFronteira).filter(url => /imoveis_basicos_/.test(url)).sort(),
    MUNICIPIOS_FRONTEIRA.map(cod => new URL(`amostra/imoveis_basicos_${cod}.csv.gz`, base).href).sort())
  assert(!pedidos.some(url => /(?:car_PB|indice_PB|imoveis_basicos_2500106)/.test(url)), "Nenhuma URL inexistente da UF cadastral pode ser tentada.")
  await buscaFronteira.fill("")
  await buscaFronteira.press("Escape")
  const ajuda = pagina.locator(".cartografia-ajuda > summary")
  await ajuda.focus()
  await pagina.keyboard.press("Enter")
  await pagina.getByText("Explorar hexágonos com teclado", { exact: true }).click()
  const listaHexagonos = pagina.locator(".cartografia-hexagonos-lista")
  await listaHexagonos.getByRole("button", { name: /^6 fazendas cadastradas/ }).focus()
  await pagina.keyboard.press("Enter")
  await pagina.waitForFunction(() => document.querySelector(".mapa-brasil .mapa").__hexagonos?.some(h => h.resolucao === 5))
  await mapaPronto()
  assert(await pagina.locator(".maplibregl-canvas").evaluate(el => el === document.activeElement), "A expansão devolve o teclado ao mapa.")
  assert.equal(new URL(pagina.url()).hash, "", "O clique H3 não escolhe um estado indiretamente.")
  await listaHexagonos.getByRole("button", { name: /^6 fazendas cadastradas/ }).click()
  await pagina.waitForURL(u => u.hash === `#/municipio/${MUNICIPIO}`)
  await abrirDados()
  await pagina.locator(".lista-basica").waitFor()
  await fecharDados()
  await mapaPronto()
  assert(await pagina.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.getZoom()) >= 9,
    "O município aberto pelo H3 preserva o detalhe.")
  await ajuda.click()
  // Reproduz a corrida: voltar ao Brasil e começar a busca antes do efeito da rota.
  await pagina.evaluate(() => {
    location.hash = "#/"
    document.querySelector(".topo .busca input").focus()
  })
  await pagina.waitForURL(u => u.hash === "#/")
  await mapaPronto()
  assert(await pagina.locator(".topo .busca input").evaluate(el => el === document.activeElement),
    "A mudança de rota não pode roubar o foco de quem já começou uma busca.")
  pedidosSatelite.length = 0
  await buscar("Pará", "#/estado/PA")
  await mapaPronto()
  await pagina.waitForFunction(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    return m.queryRenderedFeatures({ layers: ["estados-linha"] }).some((f) => f.properties.uf === "PA")
  })
  const baseNacional = await pagina.evaluate(() => { const fonte = document.querySelector(".mapa-brasil .mapa").__mapa.getStyle().sources.protomaps; return fonte.url ?? fonte.tiles?.[0] })
  assert(baseNacional.includes("base_brasil.pmtiles"), "A entrada precisa usar o PMTiles nacional.")
  assert.equal(pedidosSatelite.length, 0, "A escala estadual não pode baixar imagens de satélite.")

  console.log("Buscando Parauapebas...")
  await buscar("Parauapebas", `#/municipio/${MUNICIPIO}`)
  await abrirDados()
  await pagina.locator(".lista-basica").waitFor()
  const leilaoNaLista = pagina.locator(".lista-basica").getByRole("link", { name: "Em leilão", exact: true })
  await leilaoNaLista.waitFor()
  assert.equal(await leilaoNaLista.getAttribute("href"), `#/calendario/${encodeURIComponent(CAR)}`)
  await fecharDados()
  await mapaPronto()
  await pagina.waitForFunction((cod) => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    return m.queryRenderedFeatures({ layers: ["municipio"] }).some((f) => String(f.properties.cod_ibge) === cod)
  }, MUNICIPIO)
  assert.equal(await pagina.evaluate(() => { const fonte = document.querySelector(".mapa-brasil .mapa").__mapa.getStyle().sources.protomaps; return fonte.url ?? fonte.tiles?.[0] }), baseNacional,
    "O município precisa reutilizar a mesma base nacional.")
  await pagina.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.jumpTo({ zoom: 8, center: [-49.9, -6.1] }))
  await mapaPronto()
  await pagina.waitForFunction(() => document.querySelector(".mapa-brasil .mapa").__mapa.queryRenderedFeatures({ layers: ["hexagonos"] }).length > 0)
  const distante = await pagina.evaluate(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    return { fazendas: m.queryRenderedFeatures({ layers: ["imoveis", "imoveis-linha", "imoveis-sobrepostos"] }).length,
      hexagonos: m.queryRenderedFeatures({ layers: ["hexagonos"] }).length, preenchimento: m.getPaintProperty("imoveis", "fill-opacity") }
  })
  assert.equal(distante.fazendas, 0, "Nenhum imóvel é desenhado no zoom 8.")
  assert(distante.hexagonos > 0, "Polígonos H3 precisam aparecer na escala regional.")
  assert.equal(distante.preenchimento, 0, "O CAR não recebe preenchimento em nenhum zoom.")
  await pagina.screenshot({ path: path.join(resultado, "depois-regional-1440.png"), fullPage: true })
  // Usa o controle que o visitante usa; não pula direto para um estado interno do mapa.
  console.log("Aproximando pelo botão do mapa...")
  while (await pagina.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.getZoom()) < 13) {
    await pagina.getByRole("button", { name: "Aproximar", exact: true }).click()
    await mapaPronto()
  }
  await pagina.waitForFunction(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    return m.queryRenderedFeatures({ layers: ["water"] }).length > 0
  }, null, { timeout: 30000 })
  const zoom = await pagina.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.getZoom())
  assert(zoom > 6, "O teste precisa aproximar além do zoom 6 disponível na base.")
  const individuais = await pagina.evaluate(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    return m.queryRenderedFeatures({ layers: ["imoveis"] }).map((f) => ({ car: f.properties.cod_imovel, g: m.getFeatureState({ source: "imoveis", id: f.properties.cod_imovel }).g }))
  })
  assert.deepEqual([...new Set(individuais.map((f) => f.car))].sort(), [...CARS].sort(), "Todos os polígonos básicos precisam aparecer.")
  assert.deepEqual([...new Set(individuais.map((f) => f.g))].sort(), [0, 1, 2], "A situação básica deve continuar conhecida, mesmo sem preencher os imóveis.")
  assert(pedidosSatelite.length > 0, "O detalhe precisa renderizar o raster, não um fundo vazio.")
  const desenho = await pagina.evaluate(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    const camadas = m.getStyle().layers
    const ordem = Object.fromEntries(camadas.map((camada, i) => [camada.id, i]))
    return { contorno: m.getPaintProperty("imoveis-linha", "line-width"), fill: m.getPaintProperty("imoveis", "fill-opacity"),
      opacidadeH3: m.getPaintProperty("hexagonos", "fill-opacity"),
      sobrepostos: [...new Set(m.queryRenderedFeatures({ layers: ["imoveis-sobrepostos"] }).map(f => f.properties.cod_imovel))],
      hachura: m.queryRenderedFeatures({ layers: ["restauracao-hachura"] }).length,
      ordem, fundoDetalhadoAbaixo: camadas.every(camada => camada.source !== "protomaps-detalhe" || camada.type === "symbol" || ordem[camada.id] < ordem["brasil-mun"]) }
  })
  assert.equal(desenho.contorno, 1)
  assert.equal(desenho.fill, 0)
  assert.equal(desenho.opacidadeH3, 0, "H3 sai do detalhe para não encobrir satélite e CARs reais.")
  assert.equal(desenho.sobrepostos.length, 2, "Sobreposições confirmadas precisam aparecer tracejadas.")
  assert.equal(desenho.hachura, 0, "Sem geometria de restauração autorizada, não se inventa hachura.")
  for (const overlay of ["brasil-mun", "brasil-mun-escolhido", "imoveis-linha", "imoveis-sobrepostos", "mascara-fazenda"]) {
    assert(desenho.ordem["sentinel-publico-veu"] < desenho.ordem[overlay],
      `O satélite e o véu precisam ficar abaixo de ${overlay}; uma fonte carregada pode estar encoberta no canvas.`)
  }
  assert(desenho.fundoDetalhadoAbaixo, "O fundo estadual não pode cobrir o potencial agregado nem os contornos.")
  await pagina.screenshot({ path: path.join(resultado, "depois-detalhe-1440.png"), fullPage: true })
  await pagina.waitForFunction((car) => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    return m.getFeatureState({ source: "imoveis", id: car }).emLeilao === true
  }, CAR)
  const destaqueLeilao = await pagina.evaluate((cars) => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    return { tracejado: m.getPaintProperty("imoveis-leilao", "line-dasharray"),
      marcados: cars.filter((car) => m.getFeatureState({ source: "imoveis", id: car }).emLeilao === true) }
  }, CARS)
  assert.deepEqual(destaqueLeilao.tracejado, [2, 2], "O contorno do leilão precisa ser tracejado.")
  assert.deepEqual(destaqueLeilao.marcados, [CAR], "O calendário marca somente o imóvel vinculado ao evento.")
  await abrirDados()
  assert.equal(await pagina.locator(".lista-basica li").count(), 6)
  await pagina.locator(".dados-mapa-v2").getByRole("combobox", { name: /^Situação básica/ }).selectOption("com_pendencia")
  assert.equal(await pagina.locator(".lista-basica li").count(), 2)
  await pagina.waitForFunction(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    return m.queryRenderedFeatures({ layers: ["imoveis"] }).every((f) => [1, 3].includes(m.getFeatureState({ source: "imoveis", id: f.properties.cod_imovel }).g))
  })
  await pagina.locator(".dados-mapa-v2").getByRole("combobox", { name: /^Situação básica/ }).selectOption("")
  await fecharDados()
  // Ao clicar no interior, a máscara apaga o resto e abre a ficha básica existente.
  const pontoFazenda = await pagina.evaluate(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    const p = m.project([-49.925, -6.102])
    const r = m.getCanvas().getBoundingClientRect()
    return { x: r.x + p.x, y: r.y + p.y }
  })
  await pagina.mouse.click(pontoFazenda.x, pontoFazenda.y)
  await pagina.locator(".maplibregl-popup").waitFor()
  const mascara = await pagina.evaluate(async () => (await document.querySelector(".mapa-brasil .mapa").__mapa.getSource("mascara-fazenda").getData()).features)
  assert.equal(mascara.length, 1)
  assert.equal(mascara[0].geometry.coordinates.length, 2, "A máscara precisa ter um furo no imóvel escolhido.")
  // Trocar a rota pela busca não clica no canvas: a seleção precisa terminar por conta própria.
  const selecaoAntes = await pagina.evaluate(cars => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    window.__mapaAntesTrocaMunicipio = m
    return { selecionados: cars.filter(car => m.getFeatureState({ source: "imoveis", id: car }).selecionado),
      sobre: cars.filter(car => m.getFeatureState({ source: "imoveis", id: car }).sobre),
      camera: { center: m.getCenter().toArray(), zoom: m.getZoom() } }
  }, CARS)
  assert.equal(selecaoAntes.selecionados.length, 1, "O clique seleciona exatamente um CAR.")
  assert(selecaoAntes.sobre.length > 0, "O percurso também precisa exercer o hover real da fazenda.")
  await buscar(SEM_DESENHO, `#/municipio/${SEM_DESENHO}`)
  await abrirDados()
  await pagina.getByText("O desenho das fazendas deste município ainda não está disponível.", { exact: false }).waitFor()
  await fecharDados()
  await mapaPronto()
  const conferirSelecaoLimpa = async () => {
    const estado = await pagina.evaluate(async cars => {
      const m = document.querySelector(".mapa-brasil .mapa").__mapa
      return { mesmaInstancia: m === window.__mapaAntesTrocaMunicipio,
        selecionados: cars.filter(car => m.getFeatureState({ source: "imoveis", id: car }).selecionado),
        destacados: cars.filter(car => { const f = m.getFeatureState({ source: "imoveis", id: car }); return f.sobre || f.destaque }),
        mascara: (await m.getSource("mascara-fazenda").getData()).features.length,
        popup: document.querySelectorAll(".maplibregl-popup").length }
    }, CARS)
    assert.deepEqual(estado, { mesmaInstancia: true, selecionados: [], destacados: [], mascara: 0, popup: 0 },
      "A mesma instância do mapa precisa esquecer popup, seleção, hover e máscara ao trocar de município.")
  }
  await conferirSelecaoLimpa()
  // A malha nacional já permite enquadrar a rota. A divisa local pode chegar só
  // depois de a pessoa aproximar: essa resposta não pode desfazer a escolha.
  const divisaUrl = new URL(`geo/municipio_${MUNICIPIO}.geojson`, base).href
  let liberarDivisa
  const esperaDivisa = new Promise(resolve => { liberarDivisa = resolve })
  await pagina.route(divisaUrl, async rota => { await esperaDivisa; await rota.continue() }, { times: 1 })
  const pedidoDivisa = pagina.waitForRequest(divisaUrl)
  try {
    await buscar("Parauapebas", `#/municipio/${MUNICIPIO}`)
    await abrirDados()
    await pagina.locator(".lista-basica").waitFor()
    await fecharDados()
    await pedidoDivisa
    await pagina.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await mapaPronto()
    await pagina.evaluate(camera => document.querySelector(".mapa-brasil .mapa").__mapa.jumpTo(camera), selecaoAntes.camera)
    await mapaPronto()
  } finally { liberarDivisa() }
  await pagina.waitForFunction(async municipio => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    return (await m.getSource("municipio").getData()).features.some(f => String(f.properties.cod_ibge) === municipio)
  }, MUNICIPIO)
  await pagina.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await mapaPronto()
  assert.equal(await pagina.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.getZoom()), selecaoAntes.camera.zoom,
    "A divisa local atrasada não pode desfazer o zoom escolhido na mesma rota.")
  const pontoAoVoltar = await pontoDaFazenda(selecaoAntes.camera, selecaoAntes.selecionados[0], "volta")
  await conferirSelecaoLimpa()
  // A limpeza não impede uma seleção nova quando os mesmos CARs voltam à fonte.
  await pagina.mouse.click(pontoAoVoltar.x, pontoAoVoltar.y)
  await pagina.locator(".maplibregl-popup").waitFor()
  const selecaoDepois = await pagina.evaluate(async car => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    return { selecionado: m.getFeatureState({ source: "imoveis", id: car }).selecionado,
      mascara: (await m.getSource("mascara-fazenda").getData()).features.length }
  }, selecaoAntes.selecionados[0])
  assert.deepEqual(selecaoDepois, { selecionado: true, mascara: 1 })
  await pagina.getByRole("button", { name: /^(Fechar ficha breve|Close popup)$/ }).click()
  await pagina.setViewportSize({ width: 360, height: 800 })
  await mapaPronto()
  await conferirAtribuicaoCompacta(pagina)
  assert(await pagina.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "O mapa não pode exceder 360 px.")
  const acessibilidade = await new AxeBuilder({ page: pagina }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze()
  fs.writeFileSync(path.join(resultado, "axe-mapa-360.json"), JSON.stringify(acessibilidade.violations, null, 2))
  assert.deepEqual(acessibilidade.violations.map(v => ({ id: v.id, impacto: v.impact })), [], "A legenda e os controles do mapa devem funcionar a 360 px.")
  await pagina.screenshot({ path: path.join(resultado, "depois-detalhe-360.png"), fullPage: true })
  await pagina.setViewportSize({ width: 1440, height: 900 })
  await pagina.evaluate(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    m.jumpTo({ zoom: 13, center: [-49.9, -6.1] })
    m.setLayoutProperty("sentinel-publico-2016", "visibility", "none")
    m.setLayoutProperty("sentinel-publico-veu", "visibility", "none")
  })
  await mapaPronto()
  const corAgua = await pagina.evaluate(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    const contexto = document.createElement("canvas").getContext("2d")
    contexto.fillStyle = m.getPaintProperty("water", "fill-color")
    contexto.fillRect(0, 0, 1, 1)
    return Array.from(contexto.getImageData(0, 0, 1, 1).data).slice(0, 3)
  })
  const png = PNG.sync.read(await pagina.locator(".mapa-brasil canvas").screenshot({ path: path.join(resultado, "parauapebas.png") }))
  let agua = 0
  for (let i = 0; i < png.data.length; i += 4) {
    const [r, g, b, a] = png.data.subarray(i, i + 4)
    if (a > 240 && [r, g, b].every((c, k) => Math.abs(c - corAgua[k]) <= 2)) agua++
  }
  assert(agua > png.width * png.height * 0.5,
    `O MVT da fixture cobre a tela de água; o canvas precisa pintá-la: ${agua} pixels da cor ${corAgua}.`)
  assert(faixas.some((f) => f.arquivo.endsWith("base_brasil.pmtiles")), "A base precisa ser lida por HTTP Range.")
  assert(faixas.every((f) => f.arquivo.endsWith("base_brasil.pmtiles")), "A mesma base nacional deve atender o município.")
  console.log(`ok: país e município desenhados; zoom ${zoom.toFixed(1)}, base visível com overzoom e CARs transparentes, hexágonos H3 e satélite no detalhe.`)

  await buscar(SEM_DESENHO, `#/municipio/${SEM_DESENHO}`)
  await abrirDados()
  await pagina.getByText("O desenho das fazendas deste município ainda não está disponível.", { exact: false }).waitFor()
  await fecharDados()
  await buscar(MUNICIPIO, `#/municipio/${MUNICIPIO}`)
  await abrirDados()
  await pagina.locator(".lista-basica").waitFor()
  await fecharDados()
  const pontoAntesDaSaida = await pontoDaFazenda(selecaoAntes.camera, selecaoAntes.selecionados[0], "saida")
  await pagina.mouse.click(pontoAntesDaSaida.x, pontoAntesDaSaida.y)
  await pagina.locator(".maplibregl-popup").waitFor()
  await abrirDados()
  await pagina.locator('.lista-basica a[href^="#/fazenda/"]').first().focus()
  await pagina.waitForFunction(() => {
    const car = decodeURIComponent(document.activeElement.getAttribute("href").slice("#/fazenda/".length))
    return document.querySelector(".mapa-brasil .mapa").__mapa.getFeatureState({ source: "imoveis", id: car }).destaque === true
  })
  // Uma fonte já descarregada não pode transformar o fechamento da ficha em erro no teardown.
  await pagina.evaluate(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    const fontes = ["imoveis", "mascara-fazenda"]
    for (const camada of m.getStyle().layers) if (fontes.includes(camada.source)) m.removeLayer(camada.id)
    for (const fonte of fontes) m.removeSource(fonte)
  })
  // Os links básicos abrem o portão pago e nunca entregam a ficha completa no site.
  await pagina.keyboard.press("Enter")
  await pagina.getByRole("heading", { name: "Ficha da terra", exact: true }).waitFor()
  assert.equal(await pagina.locator(".maplibregl-popup, canvas.maplibregl-canvas").count(), 0,
    "A saída do mapa remove a ficha breve e o canvas, mesmo com fontes já descarregadas.")
  await pagina.getByText("A ficha exige créditos pagos e conexão com a Raíz.", { exact: false }).waitFor()
  await buscar(CAR.toLowerCase().replaceAll("-", ""), `#/fazenda/${CAR}`)
  // A entrada manual de CAR continua disponível fora do mapa.
  await abrirMenu()
  await pagina.getByRole("link", { name: "Fazendas", exact: true }).click()
  await pagina.getByRole("heading", { name: "Prospectar terras no Brasil" }).waitFor()
  await pagina.getByLabel("Abrir ficha pelo código do CAR").fill(CAR)
  await pagina.getByRole("button", { name: "Abrir ficha", exact: true }).click()
  await pagina.waitForURL((u) => decodeURIComponent(u.hash) === `#/fazenda/${CAR}`)
  await pagina.getByRole("heading", { name: "Ficha da terra", exact: true }).waitFor()
  await pagina.getByText("A ficha exige créditos pagos e conexão com a Raíz.", { exact: false }).waitFor()
  assert.equal(await pagina.getByRole("button", { name: "Pedir contato", exact: true }).count(), 0,
    "O site aberto não concede acesso à ficha ou ao pedido de contato.")
  assert.equal(await pagina.locator(".visual-terra").count(), 0, "O perímetro com camadas e o satélite pagos não são servidos pelo Pages.")
  await pagina.waitForLoadState("networkidle")
  assert.equal(await pagina.getByRole("link", { name: "Em leilão: conferir edital e prazo", exact: true }).count(), 0,
    "A ficha bloqueada não expõe os vínculos individuais do calendário.")
  await abrirMenu()
  await pagina.getByRole("link", { name: "Calendário", exact: true }).click()
  await pagina.getByRole("heading", { name: "Calendário da Raíz" }).waitFor()
  await pagina.getByRole("heading", { name: "Leilão fictício para teste do Pages" }).waitFor()
  assert.equal(await pagina.locator(".calendario-evento").count(), 1)
  const feed = await pagina.getByRole("link", { name: "Baixar agenda completa (.ics)" }).getAttribute("href")
  const respostaFeed = await pagina.request.get(new URL(feed, base).href)
  assert.equal(respostaFeed.status(), 200)
  assert((await respostaFeed.text()).startsWith("BEGIN:VCALENDAR"))
  assert(!pedidos.some((u) => new URL(u).pathname.endsWith("/busca")), "A busca estática não pode pedir /busca.")
  assert(!pedidos.some((u) => /\/(?:imoveis_\d{7}\.csv|fichas\/|certidoes_|desenvolvedor_|visual(?:\/|$))/.test(new URL(u).pathname)),
    "A navegação aberta não pode requisitar camadas ou fichas pagas.")
  // O formulário nativo do produtor precisa navegar tanto no subcaminho quanto na raiz, sem JavaScript.
  const contextoSemJs = await navegador.newContext({ javaScriptEnabled: false })
  const produtor = await contextoSemJs.newPage()
  produtor.on("response", (r) => { if (r.status() >= 400) erros.push(`${r.status()} ${r.url()}`) })
  await produtor.goto(new URL("produtor/", base).href)
  await produtor.getByRole("heading", { name: "Ficha da sua fazenda", exact: true }).waitFor()
  await produtor.getByLabel("Código do CAR", { exact: false }).fill("CAR-TESTE-DE-NAVEGACAO")
  await produtor.getByRole("button", { name: "Ver a ficha", exact: true }).click()
  await produtor.waitForURL((u) => u.searchParams.get("car") === "CAR-TESTE-DE-NAVEGACAO")
  assert.equal(new URL(produtor.url()).pathname, new URL("produtor/", base).pathname,
    "O formulário do produtor precisa conservar a base configurada.")
  await contextoSemJs.close()
  // Publicações anteriores continuam funcionando quando o índice só anuncia o gzip antigo.
  const legado = await contexto.newPage()
  const pedidosLegados = []
  legado.on("request", r => pedidosLegados.push(r.url()))
  legado.on("pageerror", e => erros.push(e.message))
  legado.on("response", r => { if (r.status() >= 400) erros.push(`${r.status()} ${r.url()}`) })
  await legado.route("**/geo/indice.json", async rota => {
    const resposta = await rota.fetch(), indice = await resposta.json()
    delete indice.agregados.normal
    delete indice.agregados.metadados
    indice.brasil.estados.arquivo = "estados-legados.geojson"
    await rota.fulfill({ response: resposta, json: indice })
  })
  await legado.route("**/geo/estados-legados.geojson", async rota => {
    const resposta = await rota.fetch({ url: new URL("geo/brasil_estados.geojson", base).href })
    await rota.fulfill({ response: resposta })
  })
  await legado.goto(base)
  await legado.waitForFunction(() => {
    const h = document.querySelector(".mapa-brasil .mapa")?.__hexagonos; return h?.reduce((s, x) => s + x.fazendas, 0) === 11 && h.reduce((s, x) => s + (x.hectares ?? 0), 0) === 1000 && h.some(x => x.hectares === null)
  })
  assert(pedidosLegados.some(url => url.endsWith("/agregados_brasil.geojson.gz")), "Índice antigo usa o gzip legado.")
  assert(!pedidosLegados.some(url => url.endsWith("/agregados_brasil.geojson")), "Índice antigo não presume um arquivo novo não anunciado.")
  assert.equal(await legado.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.getStyle().sources["brasil-estados"].data.type),
    "FeatureCollection", "Geometria estadual legada continua funcionando como objeto.")
  assert.equal(pedidosLegados.filter(url => url.endsWith("/estados-legados.geojson")).length, 1,
    "O fallback reaproveita a geometria lida, sem uma segunda requisição pelo worker.")
  await legado.close()
  // A falha do GeoJSON do worker é visível e não deixa marcadores de outro snapshot.
  const semAgregados = await contexto.newPage()
  await semAgregados.route("**/geo/agregados_brasil.geojson", rota => rota.fulfill({ status: 503, body: "Falha simulada do agregado" }))
  await semAgregados.goto(base)
  await semAgregados.getByRole("alert").filter({ hasText: "Não foi possível carregar os agregados" }).waitFor()
  await semAgregados.waitForFunction(() => document.querySelector(".mapa-brasil .mapa")?.__mapa?.loaded())
  await semAgregados.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.fire("idle"))
  assert.equal(await semAgregados.evaluate(() => document.querySelector(".mapa-brasil .mapa").__hexagonos?.length ?? 0), 0)
  await semAgregados.close()
  await conferirCicloMapa(navegador, base)
  await conferirProcessamentoEstavel(navegador, base)
  console.log("Estabilidade do painel nacional:", await conferirEstabilidadePainelBrasil(navegador, base))
  assert.deepEqual(ausentes, [], "Nenhum arquivo pode responder 404.")
  assert.deepEqual(erros, [], "Nenhum erro de rede, JavaScript ou renderização.")
  console.log("ok: busca por nome, IBGE e CAR, acesso pago pela lista e pelo CAR, produtor sem JavaScript, publicação somente básica, calendário e feed ICS, zero 404 e zero erro no navegador.")
} catch (erro) {
  await pagina.screenshot({ path: path.join(resultado, "falha.png"), fullPage: true }).catch(() => {})
  console.error(JSON.stringify({ ausentes, erros }, null, 2))
  throw erro
} finally {
  fs.writeFileSync(path.join(resultado, "rede.json"), JSON.stringify({ ausentes, erros, faixas, pedidos }, null, 2))
  await navegador.close()
  await new Promise((resolve) => servidor.close(resolve))
}
