#!/usr/bin/env node
/** Testa o site compilado: só arquivos e HTTP Range, sem API nem fallback do Vite.
 * Antes: preparar-teste-site.mjs e construir-site.sh com RAIZ_DADOS/RAIZ_GEO apontando à fixture,
 * RAIZ_CALENDARIO_DADOS apontando ao calendário da fixture, RAIZ_BASE=/Raiz/, VITE_RAIZ_TESTE_MAPA=1
 * e VITE_RAIZ_PROCESSAMENTO_URL=./amostra/processamento.json. PLAYWRIGHT_CHROMIUM_EXECUTABLE é opcional no ambiente local.
 */
import assert from "node:assert/strict"
import { conferirCicloMapa } from "./conferir-ciclo-mapa.mjs"
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

async function buscar(texto, destino) {
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

try {
  conferirPublicacao()
  console.log("Abrindo o build estático básico no Chromium...")
  await pagina.goto(base)
  await mapaPronto()
  assert.equal(await pagina.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.getStyle().sources["brasil-estados"].data),
    new URL("geo/brasil_estados.geojson", base).href, "Os estados públicos chegam ao worker pela URL anunciada.")
  assert.equal(await pagina.locator(".mapa-brasil svg").count(), 0, "A entrada abre no MapLibre, sem o SVG nacional.")
  await pagina.getByRole("heading", { name: "Cobertura do mapa", exact: true }).waitFor()
  await pagina.waitForFunction(() => document.querySelectorAll(".processamento-estado").length === 27)
  assert(pedidos.some((u) => new URL(u).pathname === `${prefixo}amostra/processamento.json`),
    "O processamento no build de teste deve vir da fixture local, sem depender do Actions.")
  assert.equal(await pagina.locator(".processamento-aviso").count(), 0)
  assert((await pagina.locator(".processamento-situacao").allTextContents())
    .every((texto) => texto === "Sem informação de processamento"), "A fixture não inventa execução municipal.")
  await pagina.getByText("1 município em 1 estado", { exact: true }).waitFor()
  await pagina.locator('time[datetime="2026-11-12T10:41:00Z"]').waitFor()
  await pagina.locator('time[datetime="2026-11-11T18:00:00Z"]').waitFor()
  // Supercluster recebe somente células agregadas, antes de qualquer limite municipal ou CAR.
  await pagina.waitForFunction(() => {
    return document.querySelector(".mapa-brasil .mapa").__grupos?.some(grupo => grupo.fazendas === 11)
  })
  assert(!pedidos.some(url => /brasil_municipios|imoveis_\d|imoveis_basicos_/.test(url)), "A entrada não pode baixar milhares de polígonos nem tabelas individuais.")
  const inicial = await pagina.evaluate(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    const grupo = document.querySelector(".mapa-brasil .mapa").__grupos[0]
    return { grupo, hexagonos: !!m.getLayer("potencial-h3"), zoom: m.getZoom(), fonteDuplicada: !!m.getSource("agregados-nacionais"), circulo: !!m.getLayer("grupos-fazendas") }
  })
  // O worker próprio lê a projeção pública; o mapa recebe somente grupos e não recria a fonte bruta.
  assert(pedidos.includes(new URL("geo/agregados_brasil.geojson", base).href), "O mapa deve carregar a projeção normal anunciada para o worker.")
  assert(!pedidos.some(url => url.endsWith("/agregados_brasil.geojson.gz")), "A publicação nova não precisa baixar também o agregado legado.")
  assert.equal(inicial.hexagonos, false, "O H3 é só a agregação de entrada, não o desenho da escala nacional.")
  assert.equal(inicial.grupo.fazendas, 11)
  assert.equal(inicial.grupo.hectares, 1000)
  assert.equal(inicial.grupo.semMedida, 1)
  assert.equal(typeof inicial.grupo.cluster, "number", "Os dois pontos formam um grupo com onze fazendas.")
  assert.equal(inicial.fonteDuplicada, false, "O GeoJSON agregado não pode voltar à main como uma fonte MapLibre.")
  assert.equal(inicial.circulo, false, "Os botões não precisam de círculos invisíveis no renderizador.")
  assert.equal(pedidosSatelite.length, 0, "A entrada nacional não baixa imagens de satélite.")
  assert.equal(await pagina.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.getPaintProperty("boundaries_country", "line-dasharray")), undefined, "Fronteiras iniciais contínuas reutilizam o programa dos estados.")
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
  const marcadorInicial = pagina.locator("button.cartografia-grupo").filter({ hasText: "1.000 ha" })
  await marcadorInicial.waitFor({ state: "visible" })
  assert.equal(await marcadorInicial.innerText(), "11\n1.000 ha")
  assert.match(await marcadorInicial.getAttribute("aria-label"), /^11 1\.000 ha\. 11 fazendas.*Cobertura parcial.*Aproximar/)
  await marcadorInicial.evaluate(botao => {
    window.__grupoInicial = botao
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    m.fire("idle"); m.fire("idle")
  })
  assert(await marcadorInicial.evaluate(botao => botao === window.__grupoInicial), "Atualizar o mapa preserva o mesmo botão, sem duplicar nem perder o foco.")
  await marcadorInicial.focus()
  await pagina.keyboard.press("Enter")
  await pagina.waitForFunction(zoom => document.querySelector(".mapa-brasil .mapa").__mapa.getZoom() > zoom, inicial.zoom)
  await mapaPronto()
  assert(await pagina.locator(".maplibregl-canvas").evaluate(el => el === document.activeElement), "O teclado permanece no mapa após a divisão do grupo.")
  assert.equal(new URL(pagina.url()).hash, "", "O botão não pode propagar clique para escolher o estado sob ele.")
  await pagina.locator(".cartografia-resumo > summary").click()
  await pagina.getByText("Explorar grupos com teclado", { exact: true }).click()
  const listaGrupos = pagina.locator(".cartografia-grupos-lista")
  assert(await pagina.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.getZoom()) > inicial.zoom)
  await listaGrupos.getByRole("button", { name: /^6 fazendas/ }).click()
  await pagina.waitForURL(u => u.hash === `#/municipio/${MUNICIPIO}`)
  await pagina.locator(".lista-basica").waitFor()
  await mapaPronto()
  assert(await pagina.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.getZoom()) >= 12,
    "O município aberto por aproximação precisa preservar o detalhe, sem voltar ao país.")
  assert.equal(await pagina.locator("button.cartografia-grupo").count(), 0, "No detalhe da fazenda não ficam marcadores antigos sobre o satélite.")
  await pagina.locator('.migalhas a[href="#/"]').first().click()
  await mapaPronto()
  pedidosSatelite.length = 0
  await pagina.locator('.lista-estados a[href="#/estado/PA"]').click()
  await pagina.waitForURL(u => u.hash === "#/estado/PA")
  await pagina.getByRole("heading", { name: "Pará", exact: true }).waitFor()
  await mapaPronto()
  await pagina.waitForFunction(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    return m.queryRenderedFeatures({ layers: ["estados-linha"] }).some((f) => f.properties.uf === "PA")
  })
  const baseNacional = await pagina.evaluate(() => { const fonte = document.querySelector(".mapa-brasil .mapa").__mapa.getStyle().sources.protomaps; return fonte.url ?? fonte.tiles?.[0] })
  assert(baseNacional.includes("base_brasil.pmtiles"), "A entrada precisa usar o PMTiles nacional.")
  assert.equal(pedidosSatelite.length, 0, "A escala estadual não pode baixar imagens de satélite.")
  assert(await pagina.evaluate(() => !!document.querySelector(".mapa-brasil .mapa").__mapa.getPaintProperty("boundaries_country", "line-dasharray")), "O estilo regional restaura o tracejado das fronteiras.")
  console.log("Buscando Parauapebas...")
  await buscar("Parauapebas", `#/municipio/${MUNICIPIO}`)
  await pagina.locator(".lista-basica").waitFor()
  const leilaoNaLista = pagina.locator(".lista-basica").getByRole("link", { name: "Em leilão", exact: true })
  await leilaoNaLista.waitFor()
  assert.equal(await leilaoNaLista.getAttribute("href"), `#/calendario/${encodeURIComponent(CAR)}`)
  await mapaPronto()
  await pagina.waitForFunction((cod) => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    return m.queryRenderedFeatures({ layers: ["municipio"] }).some((f) => String(f.properties.cod_ibge) === cod)
  }, MUNICIPIO)
  assert.equal(await pagina.evaluate(() => { const fonte = document.querySelector(".mapa-brasil .mapa").__mapa.getStyle().sources.protomaps; return fonte.url ?? fonte.tiles?.[0] }), baseNacional,
    "O município precisa reutilizar a mesma base nacional.")
  await pagina.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.jumpTo({ zoom: 11, center: [-49.9, -6.1] }))
  await mapaPronto()
  await pagina.locator("button.cartografia-grupo").first().waitFor()
  const distante = await pagina.evaluate(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    return { fazendas: m.queryRenderedFeatures({ layers: ["imoveis", "imoveis-linha", "imoveis-sobrepostos"] }).length,
      grupos: document.querySelectorAll("button.cartografia-grupo").length, preenchimento: m.getPaintProperty("imoveis", "fill-opacity") }
  })
  assert.equal(distante.fazendas, 0, "Nenhum imóvel é desenhado no zoom 11.")
  assert(distante.grupos > 0, "Os grupos com contagem e hectares precisam aparecer na escala regional.")
  assert(await pagina.locator("button.cartografia-grupo:visible").count() > 0, "Os grupos do worker precisam corresponder a botões desenhados.")
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
      grupos: document.querySelectorAll("button.cartografia-grupo").length,
      sobrepostos: [...new Set(m.queryRenderedFeatures({ layers: ["imoveis-sobrepostos"] }).map(f => f.properties.cod_imovel))],
      hachura: m.queryRenderedFeatures({ layers: ["restauracao-hachura"] }).length,
      ordem, fundoDetalhadoAbaixo: camadas.every(camada => camada.source !== "protomaps-detalhe" || camada.type === "symbol" || ordem[camada.id] < ordem["brasil-mun"]) }
  })
  assert.equal(desenho.contorno, 1)
  assert.equal(desenho.fill, 0)
  assert.equal(desenho.grupos, 0, "Os grupos saem do detalhe para não encobrir o satélite e os CARs reais.")
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
  assert.equal(await pagina.locator(".lista-basica li").count(), 6)
  await pagina.getByRole("combobox", { name: /^Situação básica/ }).selectOption("com_pendencia")
  assert.equal(await pagina.locator(".lista-basica li").count(), 2)
  await pagina.waitForFunction(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    return m.queryRenderedFeatures({ layers: ["imoveis"] }).every((f) => [1, 3].includes(m.getFeatureState({ source: "imoveis", id: f.properties.cod_imovel }).g))
  })
  await pagina.getByRole("combobox", { name: /^Situação básica/ }).selectOption("")
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
  await pagina.getByRole("button", { name: /^(Fechar ficha breve|Close popup)$/ }).click()
  await pagina.setViewportSize({ width: 360, height: 800 })
  await mapaPronto()
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
  console.log(`ok: país e município desenhados; zoom ${zoom.toFixed(1)}, base visível com overzoom e CARs transparentes, grupos Supercluster e satélite no detalhe.`)

  await buscar(SEM_DESENHO, `#/municipio/${SEM_DESENHO}`)
  await pagina.getByText("O desenho das fazendas deste município ainda não está disponível.", { exact: false }).waitFor()
  await buscar(MUNICIPIO, `#/municipio/${MUNICIPIO}`)
  await pagina.locator(".lista-basica").waitFor()
  // Os links básicos abrem o portão pago e nunca entregam a ficha completa no site.
  await pagina.locator('.lista-basica a[href^="#/fazenda/"]').first().click()
  await pagina.getByRole("heading", { name: "Ficha da terra", exact: true }).waitFor()
  await pagina.getByText("A ficha exige créditos pagos e conexão com a Raíz.", { exact: false }).waitFor()
  await buscar(CAR.toLowerCase().replaceAll("-", ""), `#/fazenda/${CAR}`)
  // A entrada manual de CAR continua disponível fora do mapa.
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
    return document.querySelector(".mapa-brasil .mapa")?.__grupos?.some(grupo => grupo.fazendas === 11 && grupo.hectares === 1000 && grupo.semMedida === 1)
  })
  assert(pedidosLegados.some(url => url.endsWith("/agregados_brasil.geojson.gz")), "Índice antigo usa o gzip legado.")
  assert(!pedidosLegados.some(url => url.endsWith("/agregados_brasil.geojson")), "Índice antigo não presume um arquivo novo não anunciado.")
  assert.equal(await legado.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.getStyle().sources["brasil-estados"].data.type),
    "FeatureCollection", "Geometria estadual legada continua funcionando como objeto.")
  await legado.close()
  // A falha do GeoJSON do worker é visível e não deixa marcadores de outro snapshot.
  const semAgregados = await contexto.newPage()
  await semAgregados.route("**/geo/agregados_brasil.geojson", rota => rota.fulfill({ status: 503, body: "Falha simulada do agregado" }))
  await semAgregados.goto(base)
  await semAgregados.getByRole("alert").filter({ hasText: "Não foi possível carregar os agregados" }).waitFor()
  await semAgregados.waitForFunction(() => document.querySelector(".mapa-brasil .mapa")?.__mapa?.loaded())
  await semAgregados.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.fire("idle"))
  assert.equal(await semAgregados.locator("button.cartografia-grupo").count(), 0)
  await semAgregados.close()
  await conferirCicloMapa(navegador, base)
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
