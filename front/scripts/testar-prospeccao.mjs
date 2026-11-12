#!/usr/bin/env node
/** Fluxo de consulta no Chromium com API controlada: bloqueio, débito, contato, recompra, troca de sessão e celular. */
import assert from "node:assert/strict"
import fs from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

const globo = fileURLToPath(new URL("../globo/", import.meta.url))
const require = createRequire(path.join(globo, "package.json"))
const { chromium } = require("playwright")
const { PNG } = require("pngjs")
const { createServer } = await import(pathToFileURL(require.resolve("vite")).href)
process.env.VITE_RAIZ_API = "/teste-api"
const servidor = await createServer({ root: globo, configFile: path.join(globo, "vite.config.ts"), server: { port: 0 }, logLevel: "error" })
await servidor.listen()
const executavel = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || (fs.existsSync("/usr/bin/chromium") ? "/usr/bin/chromium" : undefined)
const browser = await chromium.launch({ executablePath: executavel, args: ["--no-sandbox"] })
const prints = process.env.RAIZ_PRINTS || "/tmp/raiz-ficha-prospeccao"
fs.mkdirSync(prints, { recursive: true })
const car = "PA-1507300-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
const medida = (valor, unidade = "ha") => ({ valor, unidade, fonte: "Base de teste da terra", data_referencia: "2024", data_corte: "2026-11-12", estimado: false })
const faixas = { p10: medida(100, "tCO₂e/contrato"), p50: medida(150, "tCO₂e/contrato"), p90: medida(200, "tCO₂e/contrato") }
const ficha = {
  versao: 1, codigo_car: car, municipio: "São Félix do Xingu", cod_ibge: 1507300, uf: "PA", bioma: "Amazônia", data_corte: "2026-11-12",
  area_total: medida(30), area_restauravel: medida(12), caminho_terra: { codigo: "posse_em_titulacao", rotulo: "Posse em titulação", situacao: "em_espera", fonte: "INCRA", data_referencia: "2024", regra_versao: "teste" },
  pendencias: [{ codigo: "titulo", texto: "Conferir a titulação" }], sobreposicoes: [{ codigo: "uc", rotulo: "Unidade de conservação", area: medida(null) }], embargos: { area: medida(0), situacao: "sem_sobreposicao_identificada" },
  serie_uso: [{ ano: 2024, mata: medida(40, "%"), pasto: medida(60, "%"), lavoura: medida(0, "%"), agua: medida(0, "%") }], perdas: [{ ano: 2024, tipo: "desmatamento", rotulo: "Desmatamento observado", area: medida(0) }],
  credito: { ...faixas, base: "liquido_contrato", metodo: "Simulação de teste identificada.", versao_modelo: "teste" }, tir: { p10: medida(null, "%/ano"), p50: medida(null, "%/ano"), p90: medida(null, "%/ano"), tipo: "sem_financiamento" },
  risco: { nivel: "medio", fonte: "Regra de teste", data_referencia: "2024", regra_versao: "teste" }, agrupamento: { pequena: true, grupo_id: null, imoveis: medida(null, "fazendas"), area: medida(null) },
}
const anel = [[-52.1, -6.7], [-52.08, -6.7], [-52.08, -6.68], [-52.1, -6.68], [-52.1, -6.7]]
const colecao = (coordinates, properties = {}) => ({ type: "FeatureCollection", features: [{ type: "Feature", properties, geometry: { type: "Polygon", coordinates } }] })
const visual = { imovel: colecao([anel]), mascara: colecao([[[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]], anel]), camadas: colecao([[[-52.1, -6.7], [-52.09, -6.7], [-52.09, -6.68], [-52.1, -6.68], [-52.1, -6.7]]], { camada: "pode_voltar" }), fonte_perimetro: "Limite sintético de teste", fonte_camadas: "Camada sintética de teste", data_referencia: null, data_corte: "2026-11-12", avisos: [] }
const png = new PNG({ width: 4, height: 4 })
for (let i = 0; i < png.data.length; i += 4) png.data.set([120, 140, 110, 255], i)
const imagemTeste = PNG.sync.write(png)
let desbloqueada = false, debitos = 0, contatos = 0
const chaves = [], chamadas = []
const totais = { fazendas: 10, area_ha: 300, area_restauravel_ha: 120, credito_p10: 1000, credito_p50: 1500, credito_p90: 2000, com_credito: 10, pequenas: 10, fonte: "Base de teste", data_corte_min: "2026-11-12", data_corte_max: "2026-11-12" }
const compra = (id, estado = "pendente") => ({ id, plano: "pesquisa", creditos: 10, valor_rs: 20, estado, modo: "producao", pix_copia_cola: "PIX-DE-TESTE-NAO-PAGAVEL", expira_em: "2026-11-13" })
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  await ctx.addInitScript(() => localStorage.setItem("raiz.sessao", JSON.stringify({ token: "cliente-a", email: "teste@raiz.invalid" })))
  await ctx.route("**/teste-api/**", async (route) => {
    const req = route.request(), url = new URL(req.url()), caminho = url.pathname.replace("/teste-api/prospeccao/", "")
    chamadas.push({ caminho, method: req.method(), token: req.headers().authorization })
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) })
    if (caminho === "planos") return json({ planos: [{ id: "pesquisa", nome: "Pesquisa", creditos: 10, valor_rs: 20 }], custo_ficha: 1, unidade: "crédito de consulta", pagamento_disponivel: true, mensagem: "Valores de teste." })
    if (caminho === "saldo") return json({ creditos: 5 - debitos, fichas_desbloqueadas: debitos })
    if (caminho === "compras" && req.method() === "GET") return json([compra(99)])
    if (caminho === "compras" && req.method() === "POST") { chaves.push(req.postDataJSON().chave_idempotencia); return json(compra(chaves.length)) }
    if (caminho.startsWith("compras/")) return json(compra(Number(caminho.split("/")[1]), "paga"))
    if (caminho.endsWith("/desbloquear")) { desbloqueada = true; debitos++; return json(ficha) }
    if (caminho.includes("/visual")) {
      assert.ok(desbloqueada && req.headers().authorization === "Bearer cliente-a", "Visual só depois do crédito e com a sessão da conta")
      if (caminho.endsWith("satelite.webp")) return route.fulfill({ status: 200, contentType: "image/png", body: imagemTeste })
      if (caminho.endsWith("satelite")) return json({ disponivel: true, caixa: [-52.105, -6.705, -52.075, -6.675], data_cena: "2026-10-10", satelite: "Sentinel-2", credito: "Imagem sintética para teste; sem dado orbital", largura: 4, altura: 4 })
      return json(visual)
    }
    if (caminho.startsWith("fichas/")) return desbloqueada && req.headers().authorization === "Bearer cliente-a" ? json(ficha) : json({ detail: "Ficha precisa de crédito pago" }, 402)
    if (caminho === "contatos") { contatos++; assert.deepEqual(req.postDataJSON(), { codigo_car: car }); return json({ id: 7, estado: "recebido", criado_em: "2026-11-12", mensagem: "Pedido registrado na Raíz. O contato será tratado depois." }) }
    if (caminho === "busca" || caminho === "agregado") return json({ total: 10, pagina: 1, limite: 20, tem_mais: false, totais, agrupamentos: [{ uf: "PA", cod_ibge: 1507300, municipio: "São Félix do Xingu", bioma: "Amazônia", fazendas: 10, area_ha: 300, credito_p50: 1500, criterio: "Mesmo município e bioma; proximidade a confirmar." }], imoveis: caminho === "agregado" ? undefined : [{ codigo_car: car, uf: "PA", cod_ibge: 1507300, municipio: "São Félix do Xingu", bioma: "Amazônia", area_ha: 30, area_restauravel_ha: 12, caminho_terra: "posse_em_titulacao", risco: "medio", pequena: true, agrupar: true, credito_p50: 150, fonte: "Base de teste", data_corte: "2026-11-12" }], aviso: "Dados controlados de teste." })
    return json({ detail: "Rota inesperada no teste" }, 404)
  })
  const page = await ctx.newPage(), erros = []
  const print = async (nome) => { await page.evaluate(() => window.scrollTo(0, 0)); await page.screenshot({ path: path.join(prints, nome), fullPage: true }) }
  page.on("pageerror", (e) => erros.push(e.message))
  page.on("console", (m) => { if (m.type() === "error" && !m.text().includes("status of 402 (Payment Required)")) erros.push(m.text()) })
  const url = servidor.resolvedUrls.local[0]
  await page.goto(`${url}#/fazenda/${car}`)
  await page.getByRole("button", { name: "Desbloquear por 1 crédito" }).waitFor()
  assert.equal(await page.getByRole("heading", { name: "Uso da terra ao longo dos anos" }).count(), 0)
  assert.equal(chamadas.filter((c) => c.caminho.includes("/visual")).length, 0)
  await print("ficha-bloqueada-1440.png")
  await page.getByRole("button", { name: "Desbloquear por 1 crédito" }).click()
  await page.getByRole("heading", { name: "Uso da terra ao longo dos anos" }).waitFor()
  assert.equal(debitos, 1)
  await page.waitForFunction(() => {
    const m = document.querySelector(".mapa-ficha-terra")?.__mapa
    return m?.loaded() && m?.getLayer("sentinel") && m?.queryRenderedFeatures({ layers: ["pode-voltar"] }).length > 0
  })
  await page.getByText("Sentinel-2 em 10/10/2026", { exact: false }).waitFor()
  assert.ok(await page.locator(".linha-tempo-terra").innerText().then((t) => t.includes("2024") && t.includes("Fonte: Base de teste da terra")))
  await page.getByLabel("Mostrar área que pode virar mata").uncheck()
  await page.waitForFunction(() => (() => { const m = document.querySelector(".mapa-ficha-terra")?.__mapa; return m?.getLayer("pode-voltar") && m.getLayoutProperty("pode-voltar", "visibility") === "none" })())
  await page.getByLabel("Mostrar área que pode virar mata").check()
  await page.waitForFunction(() => (() => { const m = document.querySelector(".mapa-ficha-terra")?.__mapa; return m?.getLayer("pode-voltar") && m.getLayoutProperty("pode-voltar", "visibility") === "visible" })())
  await page.getByRole("button", { name: "Pedir contato", exact: true }).click()
  await page.getByRole("button", { name: "Pedido de contato recebido" }).waitFor()
  assert.equal(contatos, 1)
  await print("ficha-terra-1440.png")
  await page.getByRole("button", { name: "Comprar pelo Pix" }).click()
  assert.equal(chaves.length, 0, "Recupera a compra pendente do servidor sem duplicar Pix")
  await page.getByRole("button", { name: "Conferir pagamento" }).click()
  await page.getByRole("heading", { name: "Pagamento confirmado" }).waitFor()
  await page.getByRole("button", { name: "Comprar pelo Pix" }).click()
  await page.getByRole("button", { name: "Conferir pagamento" }).click()
  await page.getByRole("heading", { name: "Pagamento confirmado" }).waitFor()
  await page.getByRole("button", { name: "Comprar pelo Pix" }).click()
  await page.getByRole("heading", { name: "Pix aguardando pagamento" }).waitFor()
  assert.equal(chaves.length, 2); assert.notEqual(chaves[0], chaves[1])
  await page.setViewportSize({ width: 360, height: 800 })
  await page.locator(".visual-terra").scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(prints, "mapa-ficha-terra-360.png") })
  await print("ficha-terra-360.png")
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Ficha cabe no celular")
  await page.evaluate(() => { localStorage.setItem("raiz.sessao", JSON.stringify({ token: "cliente-b", email: "outra@raiz.invalid" })); window.dispatchEvent(new Event("raiz-sessao")) })
  await page.getByRole("button", { name: "Desbloquear por 1 crédito" }).waitFor()
  assert.equal(await page.getByRole("heading", { name: "Uso da terra ao longo dos anos" }).count(), 0)
  assert.equal(await page.getByText("Pedido 7 recebido", { exact: false }).count(), 0)
  await page.goto(`${url}#/prospeccao`)
  await page.getByRole("heading", { name: "Quanto existe na base" }).waitFor()
  await page.getByLabel("Área mínima, ha").fill("0")
  await page.getByRole("button", { name: "Aplicar filtros" }).click()
  await page.getByRole("heading", { name: "Quanto existe na base" }).waitFor()
  await print("busca-terra-360.png")
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Busca cabe no celular")
  assert.equal(await page.locator('a[href="#/"]').count() > 0, true)
  await page.evaluate(() => { localStorage.removeItem("raiz.sessao"); window.dispatchEvent(new Event("raiz-sessao")) })
  await page.getByRole("link", { name: "Entre para ver a lista de fazendas" }).waitFor()
  assert.ok(await page.getByLabel("Área mínima, ha").isDisabled())
  assert.equal(await page.locator(`a[href*="${car}"]`).count(), 0)
  assert.ok(chamadas.filter((c) => c.caminho === "agregado").every((c) => !c.token))
  assert.deepEqual(erros, [])
  console.log(`Prospecção conferida no Chromium: mapa privado, Sentinel-2 simulado, hachura, linha do tempo, débito, contato, compra repetida, troca de conta, agregado e celular. Prints em ${prints}`)
} finally { await browser.close(); await servidor.close() }
