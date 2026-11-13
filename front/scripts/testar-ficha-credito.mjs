#!/usr/bin/env node
/** Ficha de lote com API de teste: base comum, revisão, dados ausentes e fronteira aberto/pago. */
import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"
import { createRequire } from "node:module"
import { fileURLToPath, pathToFileURL } from "node:url"
import { conferirPaginaAcessivel } from "./conferir-acessibilidade.mjs"

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const globo = path.join(repo, "front/globo"), require = createRequire(path.join(globo, "package.json"))
const { chromium } = require("playwright")
const { createServer } = await import(pathToFileURL(require.resolve("vite")).href)
const { default: AxeBuilder } = await import(pathToFileURL(require.resolve("@axe-core/playwright")).href)
const saida = path.join(repo, "front/.cache/teste-ficha-credito")
fs.mkdirSync(saida, { recursive: true })
const revisao = "a".repeat(64)
const textos = { titulo: "Documentação da terra ainda não conferida.", metodo: "Estimativa agregada do motor para a composição e o horizonte desta ficha.", perdas: "Perdas ainda não documentadas para este horizonte.", garantias: "Garantias ainda não documentadas.", risco_nao_entrega: "Risco de não entrega ainda não avaliado." }
const secoes = Object.fromEntries(Object.entries(textos).map(([id, texto]) => [id, {
  texto, fonte: "Demonstração fictícia", data_referencia: "2026-10-01", revisado_em: "2026-10-02",
}]))
const ficha = {
  contrato: "ficha_credito", versao: 1, estado: "disponivel", documento_versao: "d".repeat(64),
  publicada_em: "2026-11-12T12:00:00Z", revisao_lote: revisao, opcao_id: "barata", exemplo: true, aviso: "Ficha inteiramente fictícia para o teste de interface.",
  base: { horizonte_anos: 25, inicio: "2026-01-01", fim: "2051-01-01", classe_ativo: "credito_carbono", unidade: "tCO2e", escopo_carteira: "titulares_e_reservas", classe_evidencia: "estimativa_modelo", metodo: "regeneracao_assistida", modelo_versao: "fixture-v1", fonte: "Demonstração fictícia", data_referencia: "2026-10-01", evidencia_id: "fixture-evidencia" },
  creditos_lote: { p10: 10000, p50: 15000, p90: 20000 }, creditos_por_ha: { p10: 100, p50: 150, p90: 200 },
  area_total_ha: 140, area_elegivel_ha: 100, fonte_area: "Demonstração fictícia", data_referencia_area: "2026-10-01", evidencia_area_id: "fixture-area",
  exclusoes: [{ motivo: "embargo", hectares: 30, fonte: "Demonstração fictícia", data_referencia: "2026-10-01" }, { motivo: "inelegivel_metodo", hectares: 20, fonte: "Demonstração fictícia", data_referencia: "2026-10-01" }], secoes,
}
const pedido = {
  id: "fixture", criado_em: "2026-11-12", campos: { meta: { tipo: "creditos", valor: 1000000 }, cronograma: "profloresta", onde: { ufs: ["PA"], biomas: [], municipios: [] } },
  opcoes: [{ id: "barata", ficha_credito: ficha }], versao_modelo: "fixture-v1", revisao_lote: revisao, exemplo: true,
}
const args = ["--no-sandbox", "--disable-dev-shm-usage", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || (fs.existsSync("/usr/bin/chromium") ? "/usr/bin/chromium" : undefined), args })
let servidor
const resumo = { axe: [], erros: [], chamadas: [] }
async function abrirServidor(api) {
  servidor = await createServer({ root: globo, configFile: path.join(globo, "vite.config.ts"), define: { "import.meta.env.VITE_RAIZ_API": JSON.stringify(api ? "/api/" : "") }, server: { host: "127.0.0.1", port: 0 }, logLevel: "error" })
  await servidor.listen()
  return servidor.resolvedUrls.local[0]
}
function acompanhar(page) {
  page.on("pageerror", (e) => resumo.erros.push(e.message))
  page.on("response", (r) => { if (r.status() >= 400) resumo.erros.push(`${r.status()} ${new URL(r.url()).pathname}`) })
}
try {
  const url = await abrirServidor(true)
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  await ctx.addInitScript(() => localStorage.setItem("raiz.sessao", JSON.stringify({ token: "fixture-ficha", email: "fixture@raiz.invalid" })))
  let atual = structuredClone(pedido)
  await ctx.route("**/api/**", (route) => {
    const req = route.request(), pathname = new URL(req.url()).pathname
    resumo.chamadas.push({ method: req.method(), caminho: pathname })
    assert.equal(req.method(), "GET", "A ficha somente consulta, não inicia contato ou pagamento")
    assert.equal(pathname, "/api/pedidos/fixture")
    assert.equal(req.headers().authorization, "Bearer fixture-ficha")
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(atual) })
  })
  const page = await ctx.newPage(); acompanhar(page)
  await page.goto(url + "#/pedidos/fixture/ficha/barata")
  await page.getByRole("heading", { name: "Fatos do lote", exact: true }).waitFor()
  assert.deepEqual(await page.locator(".ficha-banco > section > h2").allTextContents(), ["Título", "Método", "Perdas", "Garantias", "Risco de não entrega"])
  assert.equal(await page.locator(".fatos-central").innerText(), "P50\t150\t15.000")
  assert.match(await page.locator(".fatos-credito").innerText(), /25 anos/)
  assert.match(await page.locator(".fatos-credito").innerText(), /titulares e reservas/)
  assert.match(await page.locator(".fatos-credito").innerText(), /As áreas de exclusão podem se sobrepor/)
  assert.equal(await page.locator(".revisao-ficha").count(), 5)
  assert((await page.locator(".revisao-ficha").allTextContents()).every((t) => t.includes("02/10/2026") && !t.includes("12/11/2026")), "Revisão técnica não usa data de publicação")
  await page.getByRole("note").filter({ hasText: "dados fictícios" }).waitFor()
  resumo.axe.push(await conferirPaginaAcessivel(page, AxeBuilder, "ficha-lote-1440", saida))
  await page.setViewportSize({ width: 360, height: 800 })
  resumo.axe.push(await conferirPaginaAcessivel(page, AxeBuilder, "ficha-lote-360", saida))
  await page.locator(".ficha-lote-identidade summary").focus(); await page.keyboard.press("Enter")
  assert.equal(await page.locator(".ficha-lote-identidade").getAttribute("open"), "")
  assert(await page.locator(".ficha-lote-identidade").innerText().then((t) => t.includes("d".repeat(64))))
  atual = structuredClone(pedido); atual.opcoes[0].ficha_credito.base.fim = "2040-01-01"
  await page.reload(); await page.getByRole("status").filter({ hasText: "O motor ainda não publicou" }).waitFor()
  assert.equal(await page.locator(".fatos-central").innerText(), "P50\tNão informado\tNão informado", "Horizontes incompatíveis não se tornam uma comparação")
  atual = structuredClone(pedido); atual.opcoes[0].ficha_credito.revisao_lote = "b".repeat(64)
  await page.reload(); await page.getByRole("status").filter({ hasText: "O motor ainda não publicou" }).waitFor()
  assert.equal(await page.locator(".fatos-central").innerText(), "P50\tNão informado\tNão informado")
  atual = structuredClone(pedido); delete atual.opcoes[0].ficha_credito
  await page.reload(); await page.getByRole("heading", { name: "Fatos do lote", exact: true }).waitFor()
  assert.equal(await page.locator(".fatos-central").innerText(), "P50\tNão informado\tNão informado")
  assert((await page.locator(".revisao-ficha").allTextContents()).every((t) => t.includes("não informada")))
  await page.evaluate(() => { localStorage.removeItem("raiz.sessao"); dispatchEvent(new Event("raiz-sessao")) })
  await page.getByRole("heading", { name: "Entrar na Raíz", exact: true }).waitFor()
  assert.equal(await page.locator(".fatos-credito").count(), 0, "Sair remove o conteúdo pago da tela")
  await ctx.close(); await servidor.close(); servidor = undefined

  const publico = await abrirServidor(false), contextoPublico = await browser.newContext({ viewport: { width: 360, height: 800 } })
  const pagePublica = await contextoPublico.newPage()
  acompanhar(pagePublica)
  pagePublica.on("request", (r) => { if (r.url().includes("/api/")) resumo.erros.push("A fonte pública tentou consultar a API privada") })
  await pagePublica.goto(publico + "#/pedidos/fixture/ficha/barata")
  await pagePublica.getByRole("status").filter({ hasText: "Ficha do lote na área de clientes" }).waitFor()
  assert.equal(await pagePublica.locator(".ficha-banco").count(), 0)
  resumo.axe.push(await conferirPaginaAcessivel(pagePublica, AxeBuilder, "ficha-publica-bloqueada-360", saida))
  // O transporte simulado usa a mesma projeção e os gráficos da ficha, nunca o Release.
  await pagePublica.evaluate(() => localStorage.setItem("raiz.demonstracao.sessao", JSON.stringify({ token: "demonstracao-local-sem-valor-de-autenticacao", email: "demonstracao@example.invalid" })))
  await pagePublica.goto(publico + "?demonstracao=lotes#/pedidos/demonstracao/ficha/barata")
  await pagePublica.getByRole("heading", { name: "Fatos do lote", exact: true }).waitFor()
  assert.equal(await pagePublica.locator(".fatos-central").innerText(), "P50\t275\t1.100.000")
  await pagePublica.getByRole("button", { name: "Abrir gráfico: contratado, emitido e entregue", exact: true }).waitFor()
  await pagePublica.getByRole("button", { name: "Abrir gráfico: faixa prevista e resultado real", exact: true }).waitFor()
  assert.equal(await pagePublica.locator(".painel-grafico canvas, .painel-grafico svg").count(), 0, "Os gráficos aguardam a escolha da pessoa")
  assert.equal(await pagePublica.evaluate(() => localStorage.getItem("raiz.sessao")), null, "A demonstração não cria uma sessão real")
  resumo.axe.push(await conferirPaginaAcessivel(pagePublica, AxeBuilder, "ficha-demonstracao-360", saida))
  await contextoPublico.close()
  assert.deepEqual(resumo.erros, [])
  fs.writeFileSync(path.join(saida, "resumo.json"), JSON.stringify(resumo, null, 2) + "\n")
  console.log("ok ficha do lote: mesma base, revisão, ausência, acesso, teclado, axe e 360 px sem 404")
} finally { await browser.close(); await servidor?.close() }
