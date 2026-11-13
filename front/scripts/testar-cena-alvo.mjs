#!/usr/bin/env node
/** Cena-alvo com fixtures explícitas: resumos públicos, campos pagos recusados, três lotes autorizados, demonstração fictícia e ficha bloqueada.
 * Nenhum número desta fixture é usado pelo build público. Não inicia contato com proprietários.
 */
import assert from "node:assert/strict"
import { conferirSensibilidade } from "./conferir-sensibilidade.mjs"
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
  contrato: "publico_lotes", versao: 1, estado: "publicado", aviso: "Fixture de cenário publicado, com números exclusivos do teste.", fonte: "Release dados",
  atualizado_em: "2026-11-12T12:00:00Z", cenario: "central_r11", modelo_versao: "fixture-cena-v1", uf: "PA",
  volume_creditos: 1_000_000, preco_contrato_usd: 25, pedido_recalculado: false,
  base: { fazendas: 321, hectares: null, creditos: { p10: null, p50: 2_500_000, p90: null }, observacao: "Oferta pronta do cenário publicado." },
  cobertura: { municipios: 2, estados: 1, fazendas: 400, hectares: 9000 },
  opcoes: ids.map((id, i) => ({
    id, creditos: { p10: faixa.p10 + i * 10_000, p50: faixa.p50 + i * 10_000, p90: faixa.p90 + i * 10_000 }, tir_p50: 0.125 + i / 100,
    custo_usd_credito: 20 + i, hectares: 5000 + i * 100, fazendas: 30 + i, pequenas: 10, reservas: 3,
    terra_pronta: { creditos_p50: 400_000 + i * 50_000, fracao_meta: 0.4 + i * 0.05 },
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
    itens: [{ cod_imovel: `CAR-FIXTURE-${i}`, ficha_liberada: true, cod_ibge: "1505536", municipio: "Parauapebas", uf: "PA", papel: "lote", hectares: 5000,
      creditos: faixa, metodo: "regeneracao_assistida", caminho: "matricula_a_conferir", custo_usd_credito: 20, pequena: true,
      interesse: "sem_contato", lon, lat,
      geometria: { type: "Polygon", coordinates: [[[lon - 0.15, lat - 0.12], [lon + 0.15, lat - 0.12], [lon + 0.15, lat + 0.12], [lon - 0.15, lat + 0.12], [lon - 0.15, lat - 0.12]]] },
    }],
  }
})
const pedido = {
  id: "fixture", criado_em: "2026-11-12T12:00:00Z", campos, status: "lote_montado", opcoes,
  base: { fazendas: 321, hectares: 10_000, creditos: { p10: 2_000_000, p50: 2_500_000, p90: 3_000_000 }, por_caminho: [], por_interesse: [], alcanca_meta: true, falta: 0, afrouxar: [] },
  opcao_escolhida: null, reservado_ate: null, alertas: [], versao_modelo: "fixture-cena-v1", revisao_lote: "a".repeat(64),
}
const carFechado = "PA-1505536-CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
const pedidoComFichaFechada = {
  ...pedido,
  opcoes: opcoes.map((opcao) => opcao.id === "barata" ? {
    ...opcao, fazendas: 2,
    itens: [...opcao.itens, {
      ...opcao.itens[0], cod_imovel: carFechado, ficha_liberada: false,
      hectares: null, creditos: null, caminho: null, metodo: null, custo_usd_credito: null,
      risco_terra: null, pequena: null, geometria: null, lon: null, lat: null,
    }],
  } : opcao),
}
const erros = [], contatos = [], snapshots = []
const navegador = await chromium.launch({
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}),
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
})

async function servidor(api) {
  const vite = await createServer({ root: globo, configFile: path.join(globo, "vite.config.ts"),
    define: { "import.meta.env.VITE_RAIZ_API": JSON.stringify(api ? "/api/" : "") },
    server: { host: "127.0.0.1", port: 0, hmr: false, watch: null }, logLevel: "error",
  })
  await vite.listen()
  return { vite, base: vite.resolvedUrls.local[0] }
}
async function celular(p, width = 360, height = 800) {
  await p.setViewportSize({ width, height })
  // O cabeçalho troca o input pela busca compacta em resposta ao matchMedia.
  await p.getByRole("button", { name: "Buscar CAR, município ou estado", exact: true }).waitFor()
}
async function pagina(base, publicacao, autenticada = false, pedidoApi = pedido) {
  const contexto = await navegador.newContext({ viewport: { width: 1440, height: 960 }, reducedMotion: "reduce" })
  const p = await contexto.newPage()
  p.on("pageerror", (erro) => erros.push(erro.message))
  p.on("console", (mensagem) => { if (mensagem.type() === "error") erros.push(mensagem.text()) })
  p.on("response", (r) => { if (r.status() >= 400) erros.push(`${r.status()} ${r.url()}`) })
  p.on("request", (r) => { if (/solicitar-interesse|reservar/.test(r.url())) contatos.push(r.url()) })
  await p.route("**/amostra/lote_PA_central_r11.json", (rota) => { snapshots.push(rota.request().url()); return rota.fulfill({ json: publicacao }) })
  if (autenticada) {
    await p.addInitScript(() => localStorage.setItem("raiz.sessao", JSON.stringify({ token: "sessao-fixture-cliente", email: "cliente@example.test" })))
    await p.route("**/api/pedidos/fixture", (rota) => {
      assert.equal(rota.request().headers().authorization, "Bearer sessao-fixture-cliente")
      return rota.fulfill({ json: pedidoApi })
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
  const coresCabecalho = await p.locator(".tabela-comparacao thead button").evaluateAll((botoes) => botoes.map((botao) => getComputedStyle(botao).color))
  assert.equal(new Set(coresCabecalho).size, 3, "A legenda da tabela deve distinguir as cores das três opções.")
  return p
}

/** O painel novo lê o snapshot de teste, preserva o portão pago e leva critérios reais ao formulário. */
async function conferirPainelMapaV2(base) {
  const contexto = await navegador.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" })
  const p = await contexto.newPage()
  p.on("pageerror", (erro) => erros.push(erro.message))
  p.on("response", (r) => { if (r.status() >= 400) erros.push(`${r.status()} ${r.url()}`) })
  p.on("request", (r) => { if (/solicitar-interesse|reservar/.test(r.url())) contatos.push(r.url()) })
  const snapshot = { ...publicado, volume_creditos: 700_000, preco_contrato_usd: 39 }
  await p.route("**/amostra/lote_PA_central_r11.json", rota => rota.fulfill({ json: snapshot }))
  await p.goto(base)
  await p.getByRole("button", { name: "Fazer pedido", exact: true }).click()
  const painel = p.locator(".pedido-mapa-v2")
  await painel.getByRole("heading", { name: /700 mil créditos/ }).waitFor()
  assert.equal(await painel.locator(".pedido-mapa-v2-lote").count(), 3)
  assert.equal(await painel.getByText("resumo público", { exact: true }).count(), 3)
  assert(!/CAR-FIXTURE|Conferir o georreferenciamento|reserva de 20%|no mapa/.test(await painel.innerText()), "Resumo aberto não inventa localização, reserva ou diligência.")
  await painel.locator(".pedido-mapa-v2-abas").getByRole("button", { name: "Mais seguro", exact: true }).click()
  assert.equal(await painel.locator(".pedido-mapa-v2-lote.ativo h3").innerText(), "Mais seguro")
  assert.equal(await painel.locator(".pedido-mapa-v2-faixa-barra").count(), 3)
  await painel.getByRole("button", { name: "Buscar interesse dos donos", exact: true }).click()
  await painel.getByText("Contato somente na fase final", { exact: true }).waitFor()
  assert.equal(contatos.length, 0, "Abrir a etapa de interesse não envia contatos.")
  await celular(p, 390, 844)
  await conferirPaginaAcessivel(p, AxeBuilder, "painel-pedido-v2-390", resultado)
  await painel.getByRole("link", { name: "Editar critérios do pedido", exact: true }).click()
  await p.getByRole("heading", { name: "Novo pedido", exact: true }).waitFor()
  assert.equal(await p.getByLabel("Quantidade (créditos)").inputValue(), "700.000", "A meta veio da publicação, não do padrão anterior nem da maquete.")
  assert.equal(await p.getByLabel("Custo máximo (US$ por crédito)").inputValue(), "", "Preço de venda não vira teto de custo.")
  await p.locator(".mais-filtros summary").click()
  assert.equal(await p.getByLabel("Preço de venda (US$ por crédito)").inputValue(), "39")
  assert.match(await p.locator(".pedido-cena-resumo").innerText(), /critérios vieram do mapa/)
  await contexto.close()
}

async function conferirPainelAutorizadoV2(base) {
  const contexto = await navegador.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" })
  const p = await contexto.newPage()
  p.on("pageerror", erro => erros.push(erro.message))
  p.on("response", r => { if (r.status() >= 400) erros.push(`${r.status()} ${r.url()}`) })
  p.on("request", r => { if (/solicitar-interesse|reservar/.test(r.url())) contatos.push(r.url()) })
  let leiturasResumo = 0
  await p.route("**/amostra/lote_PA_central_r11.json", rota => { leiturasResumo++; return rota.fulfill({ json: publicado }) })
  await p.addInitScript(() => localStorage.setItem("raiz.sessao", JSON.stringify({ token: "sessao-fixture-cliente", email: "cliente@example.test" })))
  const comNegada = structuredClone(pedidoComFichaFechada)
  // Mesmo se o payload trouxer geometria por engano, ficha_liberada:false não passa ao mapa.
  comNegada.opcoes[0].itens[1].geometria = opcoes[1].itens[0].geometria
  await p.route("**/api/pedidos/fixture", rota => {
    assert.equal(rota.request().headers().authorization, "Bearer sessao-fixture-cliente")
    return rota.fulfill({ json: comNegada })
  })
  await p.goto(`${base}#/pedidos/fixture/mapa`)
  const painel = p.locator(".pedido-mapa-v2")
  await painel.getByRole("heading", { name: /1 milhão de créditos/ }).waitFor()
  const sourcePronto = await p.waitForFunction(() => {
    const fonte = document.querySelector(".mapa-brasil .mapa")?.__mapa?.getSource("lote-autorizado")
    if (!fonte) return false
    const features = fonte.serialize().data?.features
    return features?.length === 1 ? features : false
  })
  const geometria = await sourcePronto.jsonValue()
  assert.equal(geometria.length, 1)
  assert.deepEqual(geometria[0].geometry, opcoes[0].itens[0].geometria)
  assert(!JSON.stringify(geometria).includes(carFechado), "O item bloqueado nunca chegou ao source autorizado.")
  assert.equal(leiturasResumo, 0, "A rota autenticada não usa o resumo do Pará como fallback.")
  await painel.locator(".pedido-mapa-v2-abas").getByRole("button", { name: "Mais seguro", exact: true }).click()
  await p.waitForFunction(esperado => {
    const fonte = document.querySelector(".mapa-brasil .mapa")?.__mapa?.getSource("lote-autorizado")
    return fonte && JSON.stringify(fonte.serialize().data?.features?.[0]?.geometry) === JSON.stringify(esperado)
  }, opcoes[1].itens[0].geometria)
  await painel.getByRole("button", { name: "Fechar pedido", exact: true }).click()
  await p.waitForFunction(() => {
    const fonte = document.querySelector(".mapa-brasil .mapa")?.__mapa?.getSource("lote-autorizado")
    return fonte && fonte.serialize().data?.features?.length === 0
  })
  await p.evaluate(() => { localStorage.removeItem("raiz.sessao"); window.dispatchEvent(new Event("storage")) })
  await p.getByRole("heading", { name: "Entrar na Raíz", exact: true }).waitFor()
  assert.equal(await p.locator(".mapa-brasil").count(), 0, "O mapa autorizado é desmontado quando a sessão sai.")
  await contexto.close()
}

let publico, api
try {
  publico = await servidor(false)
  let p = await pagina(publico.base, { estado: "ausente" })
  assert.match(await p.locator(".fontes-pedido").innerText(), /Resumos dos lotes ainda indisponíveis/)
  assert.match(await p.locator(".tabela-comparacao").innerText(), /Ainda não publicado/)
  assert(!/US\$ 0|0% ao ano|Resposta de exemplo/.test(await p.locator(".pedido-painel").innerText()))
  await p.screenshot({ path: path.join(resultado, "release-ausente-1440.png") })
  await p.context().close()
  p = await pagina(publico.base, { ...publicado, contrato: undefined })
  const tabela = await p.locator(".tabela-comparacao").innerText()
  for (const valor of ["900.000", "1.100.000", "1.300.000", "12,5% ao ano", "5.000 ha", "8 fazendas"]) assert(!tabela.includes(valor), `Métrica financeira do snapshot legado exposta: ${valor}`)
  assert.match(await p.locator(".fontes-pedido").innerText(), /API autenticada/)
  assert.equal(await p.locator(".tabela-lote").count(), 0, "A consulta pública não expõe lotes individuais.")
  assert.equal(snapshots.length, 2, "O site lê somente a projeção pública, nunca o pacote privado.")
  await p.screenshot({ path: path.join(resultado, "snapshot-legado-ignorado-1440.png") })
  await celular(p)
  assert(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "A página ultrapassou 360 px.")
  await conferirPaginaAcessivel(p, AxeBuilder, "cobertura-publica-360", resultado)
  await p.context().close()
  p = await pagina(publico.base, publicado)
  const resumo = await p.locator(".tabela-comparacao").innerText()
  for (const valor of ["900.000", "1.100.000", "1.300.000", "5.000 ha", "40%", "400.000"]) assert(resumo.includes(valor), `Resumo público incompleto: ${valor}`)
  assert(!/TIR|Pendências|Fazendas de reserva|8 fazendas|Conferir o georreferenciamento/.test(resumo), "O resumo público expôs uma coluna paga.")
  assert.equal(await p.locator(".quadro-destrava, .tabela-lote, .mapa-lote, .pedido-mapa").count(), 0, "O público não renderiza os detalhes nem o mapa de seleção.")
  await celular(p)
  await conferirPaginaAcessivel(p, AxeBuilder, "resumo-publico-360", resultado)
  assert(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  await p.screenshot({ path: path.join(resultado, "resumo-publico-360.png"), fullPage: true })
  await p.getByRole("link", { name: "Conhecer a demonstração da área logada", exact: true }).click()
  await p.getByRole("button", { name: "Abrir demonstração da área logada", exact: true }).click()
  await p.getByRole("heading", { name: "O que destrava", exact: true }).waitFor()
  assert.match(await p.locator(".aviso-exemplo").innerText(), /dados fictícios/)
  await p.waitForFunction(() => document.querySelector(".mapa-lote")?.__mapa?.loaded())
  assert.match(await p.locator(".aba-conteudo[data-state=active] .tabela-lote").innerText(), /DEMONSTRACAO/)
  assert.equal(await p.evaluate(() => localStorage.getItem("raiz.sessao")), null, "A demonstração não cria uma sessão real.")
  await conferirPaginaAcessivel(p, AxeBuilder, "demonstracao-360", resultado)
  assert(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  await p.screenshot({ path: path.join(resultado, "demonstracao-360.png"), fullPage: true })
  await p.context().close()
  await conferirPainelMapaV2(publico.base)
  await publico.vite.close()
  publico = null

  api = await servidor(true)
  p = await pagina(api.base, publicado, true)
  await conferirSensibilidade(p, AxeBuilder, resultado, pedido)
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
  await celular(p)
  assert(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Os lotes autorizados ultrapassaram 360 px.")
  await conferirPaginaAcessivel(p, AxeBuilder, "lotes-autorizados-360", resultado)
  await p.context().close()

  p = await pagina(api.base, publicado, true, pedidoComFichaFechada)
  const linhaFechada = p.locator(".aba-conteudo[data-state=active] .tabela-lote tbody tr").last()
  assert.equal(await p.locator(".aba-conteudo[data-state=active] .tabela-lote tbody tr").count(), 2)
  assert.equal((await linhaFechada.locator("td.num").innerText()).trim(), "Ficha paga", "Crédito individual ausente não pode aparecer como zero.")
  await linhaFechada.getByRole("button").click()
  const detalheFechado = p.locator(".fazenda-escolhida")
  await detalheFechado.waitFor()
  assert.match(await detalheFechado.innerText(), /Os dados desta fazenda ficam na ficha paga/)
  const medidasFechadas = await detalheFechado.locator(".ficha-numeros dd").allInnerTexts()
  assert.equal(medidasFechadas.filter((texto) => texto.trim() === "Disponível na ficha paga").length, 5,
    "Área, créditos, método, caminho e custo fechados precisam manter ausência explícita.")
  assert(!/\bNaN\b|undefined|(?:^|\s)0(?:[,.]0+)?(?:\s|%|$)/.test(medidasFechadas.join("\n")), "A ficha bloqueada inventou zero ou exibiu dado inválido.")
  assert.equal(await detalheFechado.getByRole("link", { name: "Abrir a ficha", exact: true }).getAttribute("href"), `#/fazenda/${carFechado}`)
  await p.screenshot({ path: path.join(resultado, "lote-com-ficha-bloqueada-1440.png") })
  await celular(p)
  assert(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "A ficha bloqueada ultrapassou 360 px.")
  await conferirPaginaAcessivel(p, AxeBuilder, "lote-com-ficha-bloqueada-360", resultado)
  await p.context().close()
  await conferirPainelAutorizadoV2(api.base)
  assert.deepEqual(contatos, [], "O teste tentou iniciar contato ou reserva.")
  assert.deepEqual(erros, [], "Há erro HTTP ou JavaScript.")
  fs.writeFileSync(path.join(resultado, "resumo.json"), JSON.stringify({ cenarios: ["cobertura pública", "snapshot legado ignorado", "resumo público sem campos pagos", "painel V2 e passagem de critérios sem contato", "demonstração fictícia", "API autorizada", "item com ficha paga bloqueada"], cores, erros, contatos }, null, 2))
  console.log("Cena-alvo: resumo público sem detalhes pagos, demonstração fictícia, três lotes coloridos autorizados, ficha bloqueada, teclado, 360 px e nenhum contato ou 404.")
} catch (erro) {
  let paginaFalhou = 0
  for (const contexto of navegador.contexts()) for (const pagina of contexto.pages()) {
    const nome = `falha-${++paginaFalhou}`
    await pagina.screenshot({ path: path.join(resultado, `${nome}.png`), fullPage: true }).catch(() => {})
    const diagnostico = await pagina.evaluate(() => ({
      url: location.href, largura: innerWidth, larguraDocumento: document.documentElement.scrollWidth,
      transbordam: [...document.querySelectorAll("body *")].map(el => ({ elemento: el.tagName, classe: el.className, x: el.getBoundingClientRect().x, direita: el.getBoundingClientRect().right })).filter(el => el.direita > innerWidth + 1 || el.x < -1).slice(0, 30),
    })).catch(() => null)
    fs.writeFileSync(path.join(resultado, `${nome}.json`), JSON.stringify(diagnostico, null, 2))
  }
  throw erro
} finally {
  await navegador.close()
  await publico?.vite.close()
  await api?.vite.close()
}
