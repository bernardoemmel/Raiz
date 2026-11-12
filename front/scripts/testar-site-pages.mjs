#!/usr/bin/env node
/** Testa o site compilado como no Pages: só arquivos, /Raiz/ e HTTP Range, sem API nem fallback do Vite.
 * Antes: preparar-teste-site.mjs e construir-site.sh com RAIZ_DADOS/RAIZ_GEO apontando à fixture,
 * RAIZ_CALENDARIO_DADOS apontando ao calendário da fixture, RAIZ_BASE=/Raiz/ e VITE_RAIZ_TESTE_MAPA=1. PLAYWRIGHT_CHROMIUM_EXECUTABLE é opcional no ambiente local.
 */
import assert from "node:assert/strict"
import fs from "node:fs"
import http from "node:http"
import { createRequire } from "node:module"
import path from "node:path"
import zlib from "node:zlib"
import { CANARIO_PRIVADO, CAR, CARS, MUNICIPIO, REPO, SEM_DESENHO } from "./preparar-teste-site.mjs"

const require = createRequire(path.join(REPO, "front/globo/package.json"))
const { chromium } = require("playwright")
const { PNG } = require("pngjs")
const site = path.join(REPO, "site")
const resultado = path.join(REPO, "front/.cache/teste-site/resultado")
fs.mkdirSync(resultado, { recursive: true })
const tipos = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".geojson": "application/geo+json", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".gz": "application/gzip" }
const ausentes = [], faixas = [], erros = [], pedidos = []
const servidor = http.createServer((req, res) => {
  const url = new URL(req.url, "http://localhost")
  const rel = decodeURIComponent(url.pathname).replace(/^\/Raiz\//, "")
  const arquivo = path.resolve(site, rel || "index.html")
  if (!url.pathname.startsWith("/Raiz/") || !arquivo.startsWith(site + path.sep) || !fs.existsSync(arquivo) || !fs.statSync(arquivo).isFile()) {
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
const base = `http://127.0.0.1:${servidor.address().port}/Raiz/`
const navegador = await chromium.launch({
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}),
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
})
const pagina = await navegador.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" })
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
  assert.equal(permitidos.size, CARS.length + 1, "A publicação básica inclui todas as fazendas da fixture.")
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
        assert.deepEqual(Object.keys(f.properties), ["cod_imovel"], "A geometria não pode carregar métricas pagas.")
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
  await pagina.waitForFunction(() => {
    const m = document.querySelector(".mapa-brasil .mapa").__mapa
    return m.queryRenderedFeatures({ layers: ["estados-linha"] }).some((f) => f.properties.uf === "PA")
  })
  const baseNacional = await pagina.evaluate(() => { const fonte = document.querySelector(".mapa-brasil .mapa").__mapa.getStyle().sources.protomaps; return fonte.url ?? fonte.tiles?.[0] })
  assert(baseNacional.includes("base_brasil.pmtiles"), "A entrada precisa usar o PMTiles nacional.")
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
  await pagina.screenshot({ path: path.join(resultado, "municipio-basico.png"), fullPage: true })
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
  assert.deepEqual([...new Set(individuais.map((f) => f.g))].sort(), [0, 1, 2], "As três situações básicas precisam colorir o mapa.")
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
  console.log(`ok: país e município desenhados; zoom ${zoom.toFixed(1)}, base visível com overzoom e polígonos básicos nas três situações.`)

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
  assert(!pedidos.some((u) => /\/(?:imoveis_\d{7}\.csv|fichas\/|certidoes_|desenvolvedor_)/.test(new URL(u).pathname)),
    "A navegação aberta não pode requisitar camadas ou fichas pagas.")
  assert.deepEqual(ausentes, [], "Nenhum arquivo pode responder 404.")
  assert.deepEqual(erros, [], "Nenhum erro de rede, JavaScript ou renderização.")
  console.log("ok: busca por nome, IBGE e CAR, acesso pago pela lista e pelo CAR, publicação somente básica, calendário e feed ICS, zero 404 e zero erro no navegador.")
} catch (erro) {
  await pagina.screenshot({ path: path.join(resultado, "falha.png"), fullPage: true }).catch(() => {})
  console.error(JSON.stringify({ ausentes, erros }, null, 2))
  throw erro
} finally {
  fs.writeFileSync(path.join(resultado, "rede.json"), JSON.stringify({ ausentes, erros, faixas, pedidos }, null, 2))
  await navegador.close()
  await new Promise((resolve) => servidor.close(resolve))
}
