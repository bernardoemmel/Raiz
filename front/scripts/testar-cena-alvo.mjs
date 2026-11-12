#!/usr/bin/env node
/** Cena-alvo com fixtures explícitas: Release ausente/presente e resposta autenticada com três lotes desenhados.
 * Nenhum número desta fixture é usado pelo build público. Não inicia contato com proprietários.
 */
import assert from "node:assert/strict"
import { conferirPaginaAcessivel } from "./conferir-acessibilidade.mjs"
import fs from "node:fs"
import path from "node:path"
import { createRequire } from "node:module"
import { pathToFileURL } from "node:url"
import { REPO, FIXTURE, preparar } from "./preparar-teste-site.mjs"

const globo = path.join(REPO, "front/globo")
const require = createRequire(path.join(globo, "package.json"))
const { chromium } = require("playwright")
const { PNG } = require("pngjs")
const { default: AxeBuilder } = await import(pathToFileURL(require.resolve("@axe-core/playwright")).href)
const { createServer } = await import(pathToFileURL(require.resolve("vite")).href)
const resultado = path.join(REPO, "front/.cache/teste-cena-alvo")
fs.mkdirSync(resultado, { recursive: true })
preparar()
process.env.RAIZ_DADOS = path.join(FIXTURE, "dados")
process.env.RAIZ_GEO = path.join(FIXTURE, "geo")
process.env.RAIZ_BASE = "/"
process.env.VITE_CONFIG_NATIVE_IGNORE_WARNING = "true"
const ids = ["barata", "segura", "compacta"]
const campos = {
  meta: { tipo: "creditos", valor: 1_000_000 }, cronograma: "profloresta",
  onde: { biomas: ["Amazônia"], ufs: ["PA"], municipios: [], raio: null, poligono: null, so_fornecedores_cadeia: false },
  dinheiro: { custo_max_usd_credito: 24, tir_min: null, preco_venda_usd: 25, fracao_financiada: 0 },
  metodos: ["regeneracao_assistida"], terra: ["matricula_a_conferir"],
  forma: { distancia_max_km: null, max_donos: null, area_min_contigua_ha: null }, interesse: "qualquer", exclusoes: [],
}
const faixa = { p10: 900_000, p50: 1_100_000, p90: 1_300_000 }
const publicado = {
  estado: "publicado", aviso: "Fixture de cenário publicado, com números exclusivos do teste.", fonte: "Release dados",
  atualizado_em: "2026-11-12", cenario: "central_r11", modelo_versao: "fixture-cena-v1", uf: "PA",
  volume_creditos: 1_000_000, preco_contrato_usd: 25, pedido_recalculado: false,
  base: { fazendas: 321, hectares: null, creditos: { p10: null, p50: 2_500_000, p90: null }, observacao: "Oferta pronta do cenário publicado." },
  cobertura: { municipios: 2, estados: 1, fazendas: 400, hectares: 9000 },
  opcoes: ids.map((id, i) => ({
    id, creditos: { p10: faixa.p10 + i * 10_000, p50: faixa.p50 + i * 10_000, p90: faixa.p90 + i * 10_000 }, tir_p50: 0.125 + i / 100,
    custo_usd_credito: 20 + i, hectares: 5000 + i * 100, fazendas: 30 + i, pequenas: 10, reservas: 3,
    pendencias_terra: [{ caminho: "matricula_a_conferir", fazendas: 8, hectares: 750 }],
    destrava: [{ texto: "Conferir o georreferenciamento das áreas em espera.", fazendas: 8, hectares: 750, creditos: 123_000, tipo: "regularizacao", creditos_faixa: { p10: 100_000, p50: 123_000, p90: 150_000 }, somavel: false }], o_que_falta: [],
  })),
}
const opcoes = ids.map((id, i) => {
  const lon = -53.4 + i * 0.5, lat = -7.2
  return {
    id, creditos: faixa, hectares: 5000, fazendas: 1, pequenas: 1, tir: { p10: 0.08, p50: 0.12, p90: 0.16 },
    custo_usd_credito: { p10: 18, p50: 20 + i, p90: 24 }, pico_caixa_usd: 500_000, marcos: [{ ano: 7, fracao: 0.12, chance: 0.8 }],
    multa_esperada_usd: 1000, mistura_terra: [{ caminho: "matricula_a_conferir", fracao: 1 }], metodos: [{ metodo: "regeneracao_assistida", fazendas: 1 }],
    alcanca_meta: true, falta: 0,
    itens: [{ cod_imovel: `CAR-FIXTURE-${i}`, cod_ibge: "1505536", municipio: "Parauapebas", uf: "PA", papel: "lote", hectares: 5000,
      creditos: faixa, metodo: "regeneracao_assistida", caminho: "matricula_a_conferir", custo_usd_credito: 20, pequena: true,
      interesse: "sem_contato", lon, lat,
      geometria: { type: "Polygon", coordinates: [[[lon - 0.15, lat - 0.12], [lon + 0.15, lat - 0.12], [lon + 0.15, lat + 0.12], [lon - 0.15, lat + 0.12], [lon - 0.15, lat - 0.12]]] },
    }],
  }
})
const pedido = {
  id: "fixture", criado_em: "2026-11-12T12:00:00Z", campos, status: "lote_montado", opcoes,
  base: { fazendas: 321, hectares: 10_000, creditos: { p10: 2_000_000, p50: 2_500_000, p90: 3_000_000 }, por_caminho: [], por_interesse: [], alcanca_meta: true, falta: 0, afrouxar: [] },
  opcao_escolhida: null, reservado_ate: null, alertas: [], versao_modelo: "fixture-cena-v1",
}
const erros = [], contatos = []
const navegador = await chromium.launch({
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}),
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
})

async function servidor(api) {
  const vite = await createServer({ root: globo, configFile: path.join(globo, "vite.config.ts"),
    define: { "import.meta.env.VITE_RAIZ_API": JSON.stringify(api ? "/api/" : "") },
    server: { host: "127.0.0.1", port: 0 }, logLevel: "error",
  })
  await vite.listen()
  return { vite, base: vite.resolvedUrls.local[0] }
}
async function pagina(base, publicacao, autenticada = false) {
  const contexto = await navegador.newContext({ viewport: { width: 1440, height: 960 }, reducedMotion: "reduce" })
  const p = await contexto.newPage()
  p.on("pageerror", (erro) => erros.push(erro.message))
  p.on("console", (mensagem) => { if (mensagem.type() === "error") erros.push(mensagem.text()) })
  p.on("response", (r) => { if (r.status() >= 400) erros.push(`${r.status()} ${r.url()}`) })
  p.on("request", (r) => { if (/solicitar-interesse|reservar/.test(r.url())) contatos.push(r.url()) })
  await p.route("**/amostra/lote_PA_central_r11.json", (rota) => rota.fulfill({ json: publicacao }))
  if (autenticada) {
    await p.addInitScript(() => localStorage.setItem("raiz.sessao", JSON.stringify({ token: "sessao-fixture-cliente", email: "cliente@example.test" })))
    await p.route("**/api/pedidos/fixture", (rota) => {
      assert.equal(rota.request().headers().authorization, "Bearer sessao-fixture-cliente")
      return rota.fulfill({ json: pedido })
    })
    await p.goto(`${base}#/pedidos/fixture`)
  } else {
    await p.goto(`${base}#/pedidos/novo`)
    await p.getByRole("heading", { name: "Novo pedido", exact: true }).waitFor()
    assert.equal(await p.getByLabel("Quantidade (créditos)").inputValue(), "1.000.000")
    assert.match(await p.locator(".fichas-escolhidas").innerText(), /Pará/)
    await p.getByLabel("Custo máximo (US$ por crédito)").fill("24")
    await p.locator('button[type="submit"]').click()
  }
  await p.getByRole("heading", { name: "Quanto existe na nossa base", exact: true }).waitFor()
  assert(await p.getByRole("button", { name: "Solicitar interesse dos donos", exact: true }).isDisabled())
  assert.equal(await p.locator(".tabela-comparacao thead button").count(), 3)
  return p
}

let publico, api
try {
  publico = await servidor(false)
  let p = await pagina(publico.base, { estado: "ausente" })
  assert.match(await p.locator(".fontes-pedido").innerText(), /ainda não foi publicado/)
  assert.match(await p.locator(".tabela-comparacao").innerText(), /Ainda não publicado/)
  assert(!/US\$ 0|0% ao ano|Resposta de exemplo/.test(await p.locator(".pedido-painel").innerText()))
  await p.screenshot({ path: path.join(resultado, "release-ausente-1440.png") })
  await p.close()
  p = await pagina(publico.base, publicado)
  const tabela = await p.locator(".tabela-comparacao").innerText()
  for (const valor of ["900.000", "1.100.000", "1.300.000", "12,5% ao ano", "5.000 ha", "8 fazendas"]) assert(tabela.includes(valor), `Falta na comparação: ${valor}`)
  assert.match(await p.locator(".fontes-pedido").innerText(), /ainda não foram recalculados/)
  assert.match(await p.locator(".quadro-destrava").innerText(), /georreferenciamento/)
  assert.match(await p.locator(".quadro-destrava").innerText(), /Não some as linhas/)
  assert.equal(await p.locator(".tabela-lote").count(), 0, "O resumo público não expõe fazendas.")
  await p.screenshot({ path: path.join(resultado, "release-publicado-1440.png") })
  await p.setViewportSize({ width: 360, height: 800 })
  assert(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "A página ultrapassou 360 px.")
  await conferirPaginaAcessivel(p, AxeBuilder, "release-publicado-360", resultado)
  await p.close()
  await publico.vite.close()
  publico = null

  api = await servidor(true)
  p = await pagina(api.base, publicado, true)
  await p.waitForFunction(() => {
    const m = document.querySelector(".mapa-lote")?.__mapa
    return m?.loaded() && m.queryRenderedFeatures({ layers: ["lote-area"] }).length >= 3
  }, null, { timeout: 30_000 })
  const mapa = await p.locator(".mapa-lote").evaluate((el) => {
    const m = el.__mapa
    return { opcoes: [...new Set(m.queryRenderedFeatures({ layers: ["lote-area"] }).map((f) => f.properties.opcao))].sort(),
      cores: ["barata", "segura", "compacta"].map((id) => m.getPaintProperty(`lote-opcao-${id}`, "line-color")) }
  })
  assert.deepEqual(mapa.opcoes, [...ids].sort())
  assert.equal(new Set(mapa.cores).size, 3)
  const captura = await p.locator(".mapa-lote").screenshot({ path: path.join(resultado, "lotes-autorizados-mapa.png") })
  const png = PNG.sync.read(captura)
  const cores = { verde: 0, azul: 0, ocre: 0 }
  for (let i = 0; i < png.data.length; i += 4) {
    const [r, g, b] = png.data.subarray(i, i + 3)
    if (g > r * 1.2 && g > b * 1.1) cores.verde++
    if (b > r * 1.2 && b > g * 1.1) cores.azul++
    if (r > g * 1.15 && g > b * 1.3) cores.ocre++
  }
  for (const [cor, pixels] of Object.entries(cores)) assert(pixels > 50, `Faltou polígono ${cor} na captura (${pixels} pixels).`)
  await p.locator(".comparacao-lotes").scrollIntoViewIfNeeded()
  await p.screenshot({ path: path.join(resultado, "lotes-autorizados-comparacao-1440.png") })
  await p.getByRole("tab", { name: "Mais barata", exact: true }).focus()
  await p.keyboard.press("ArrowRight")
  await p.getByRole("tab", { name: "Mais segura", exact: true }).and(p.locator('[aria-selected="true"]')).waitFor()
  assert.equal(await p.getByRole("tab", { name: "Mais segura", exact: true }).getAttribute("aria-selected"), "true")
  await p.screenshot({ path: path.join(resultado, "lotes-autorizados-1440.png") })
  await p.setViewportSize({ width: 360, height: 800 })
  await conferirPaginaAcessivel(p, AxeBuilder, "lotes-autorizados-360", resultado)
  await p.close()
  assert.deepEqual(contatos, [], "O teste tentou iniciar contato ou reserva.")
  assert.deepEqual(erros, [], "Há erro HTTP ou JavaScript.")
  fs.writeFileSync(path.join(resultado, "resumo.json"), JSON.stringify({ cenarios: ["release ausente", "release publicado", "API autorizada"], cores, erros, contatos }, null, 2))
  console.log("Cena-alvo: Release ausente/presente, números publicados, três lotes coloridos autorizados, teclado, 360 px e nenhum contato ou 404.")
} finally {
  await navegador.close()
  await publico?.vite.close()
  await api?.vite.close()
}
