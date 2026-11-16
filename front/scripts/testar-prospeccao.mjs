#!/usr/bin/env node
/** Fluxo de consulta no Chromium com API controlada: bloqueio, débito, contato, recompra, troca de sessão e celular. */
import assert from "node:assert/strict"
import { conferirPaginaAcessivel } from "./conferir-acessibilidade.mjs"
import fs from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

const globo = fileURLToPath(new URL("../globo/", import.meta.url))
const require = createRequire(path.join(globo, "package.json"))
const { chromium } = require("playwright")
const { default: AxeBuilder } = await import(pathToFileURL(require.resolve("@axe-core/playwright")).href)
const { PNG } = require("pngjs")

const { createServer } = await import(pathToFileURL(require.resolve("vite")).href)
process.env.VITE_RAIZ_API = "/teste-api"
const servidor = await createServer({ root: globo, configFile: path.join(globo, "vite.config.ts"), server: { port: 0 }, logLevel: "error" })
await servidor.listen()
const executavel = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || (fs.existsSync("/usr/bin/chromium") ? "/usr/bin/chromium" : undefined)
const browser = await chromium.launch({ executablePath: executavel, args: ["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] })
const prints = process.env.RAIZ_PRINTS || "/tmp/raiz-ficha-prospeccao"
fs.mkdirSync(prints, { recursive: true })
const car = "PA-1507300-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
const medida = (valor, unidade = "ha") => ({ valor, unidade, fonte: "Base de teste da terra", data_referencia: "2024", data_corte: "2026-11-12", estimado: false })
const faixas = { p10: medida(100, "tCO₂e/contrato"), p50: medida(150, "tCO₂e/contrato"), p90: medida(200, "tCO₂e/contrato") }
const mudancas = [{ tipo: "embargos", campo: "embargos", antes: { area: medida(null) }, depois: { area: medida(0) }, fonte: "IBAMA sintético", data_referencia: "2024", data_corte: "2026-11-12" }]
const evidencia = { fonte_id: "verra", objeto_id: "VCS-TESTE", registro: "VCS", tipo: "projeto_carbono", situacao: "ativo", certeza: "poligono_oficial", fonte_url: "https://verra.org/", data_referencia: null, observado_em: "2026-11-12", inicio: "2024-01-01", fim: null, area: medida(3) }
const ficha = {
  versao: 1, codigo_car: car, municipio: "São Félix do Xingu", cod_ibge: 1507300, uf: "PA", bioma: "Amazônia", data_corte: "2026-11-12",
  area_total: medida(30), area_restauravel: medida(12), caminho_terra: { codigo: "posse_em_titulacao", rotulo: "Posse em titulação", situacao: "em_espera", fonte: "INCRA", data_referencia: "2024", regra_versao: "teste" },
  pendencias: [{ codigo: "titulo", texto: "Conferir a titulação" }], sobreposicoes: [{ codigo: "uc", rotulo: "Unidade de conservação", area: medida(null) }], embargos: { area: medida(0), situacao: "sem_sobreposicao_identificada" },
  serie_uso: [{ ano: 2024, mata: medida(40, "%"), pasto: medida(60, "%"), lavoura: medida(0, "%"), agua: medida(0, "%") }], perdas: [{ ano: 2024, tipo: "desmatamento", rotulo: "Desmatamento observado", area: medida(0) }],
  credito: { ...faixas, base: "liquido_contrato", metodo: "Simulação de teste identificada.", versao_modelo: "teste" }, tir: { p10: medida(null, "%/ano"), p50: medida(null, "%/ano"), p90: medida(null, "%/ano"), tipo: "sem_financiamento" },
  risco: { nivel: "medio", fonte: "Regra de teste", data_referencia: "2024", regra_versao: "teste" }, agrupamento: { pequena: true, grupo_id: null, imoveis: medida(null, "fazendas"), area: medida(null) },
  terra_comprometida: { versao: 1, situacao: "sobreposicao_confirmada", area_confirmada: medida(3), area_indicio: medida(null), evidencias: [evidencia], contexto_jurisdicional: [{ ...evidencia, fonte_id: "art_jurisdicional", registro: "ART", tipo: "programa_jurisdicional", certeza: "contexto_jurisdicional", area: medida(null) }], cobertura: [{ fonte_id: "verra", estado: "parcial", escopo: "brasil", recorte: "BR", bbox: null, url: "https://verra.org/", licenca: "Licença sintética de teste", data_referencia: null, consultado_em: "2026-11-12" }], aviso: "Ausência de sobreposição nas fontes consultadas não comprova terra livre. Polígonos confirmam interseção com o registro observado, não exclusividade de carbono." },
  versao_ficha: { id: 2, hash: "b".repeat(64), registrada_em: "2026-11-12T15:00:00Z" },
  o_que_mudou: { primeira_consulta: false, consulta_anterior_em: "2026-11-10T12:00:00Z", versao_anterior_id: 1, versao_atual_id: 2, mudancas },
}
const car2 = "PA-1507300-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
let desbloqueada = false, debitos = 0, contatos = 0, precosProvisorios = false
let buscasSalvas = [], avisos = []
const salvo = (nome, filtros) => ({ id: "busca-1", nome, filtros, criada_em: "2026-11-12", verificada_em: "2026-11-12" })
const anel = [[-52.1, -6.7], [-52.08, -6.7], [-52.08, -6.68], [-52.1, -6.68], [-52.1, -6.7]]
const colecao = (coordinates, properties = {}) => ({ type: "FeatureCollection", features: [{ type: "Feature", properties, geometry: { type: "Polygon", coordinates } }] })
const visual = { imovel: colecao([anel]), mascara: colecao([[[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]], anel]), camadas: colecao([[[-52.1, -6.7], [-52.09, -6.7], [-52.09, -6.68], [-52.1, -6.68], [-52.1, -6.7]]], { camada: "pode_voltar" }), fonte_perimetro: "Limite sintético de teste", fonte_camadas: "Camada sintética de teste", data_referencia: null, data_corte: "2026-11-12", avisos: [] }
const png = new PNG({ width: 4, height: 4 })
for (let i = 0; i < png.data.length; i += 4) png.data.set([120, 140, 110, 255], i)
const imagemTeste = PNG.sync.write(png)
const creditoTeste = "Imagem sintética de teste; legenda de atribuição: Contains modified Copernicus Sentinel data 2026"
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
    if (caminho === "planos" && precosProvisorios) return json({ planos: ["por_ficha", "por_lote", "assinatura"].map((id, i) => ({ id, modalidade: id, nome: ["Por ficha", "Por lote", "Assinatura"][i], creditos: [1, 10, 50][i], status_quantidade: "proposta", valor_rs: null, status: "provisorio", aviso_preco: "a definir pelo fundador", pagamento_disponivel: false, cobranca_implementada: i !== 2, renovacao_automatica: false, ...(i === 2 ? { creditos_por_ciclo: 50, ciclo_meses: 1, status_ciclo: "proposta", aviso_modalidade: "Proposta de assinatura. Cobrança por ciclo ainda não implementada." } : {}) })), custo_ficha: 1, unidade: "crédito de consulta", pagamento_disponivel: false, status: "provisorio", mensagem: "Preços a definir pelo fundador. Vendas desativadas." })
    if (url.pathname === "/teste-api/eventos") return json({
      eventos: [{ id: "a".repeat(24), tipo: "leilao_imovel", titulo: "Leilão fictício para teste da ficha", data: "2099-11-15", prazo: null,
        uf: "PA", municipio: "1507300", codigos_car: [car], fonte_url: "https://example.test/leilao", fonte_nome: "Fonte fictícia de teste",
        coletado_em: "2026-11-12T12:00:00Z", confianca: 0.9, situacao: "previsto" }],
      total: 1, coletado_em: "2026-11-12T12:00:00Z", fontes: [],
    })
    if (caminho === "planos") return json({ planos: [{ id: "pesquisa", nome: "Pesquisa", creditos: 10, valor_rs: 20 }], custo_ficha: 1, unidade: "crédito de consulta", pagamento_disponivel: true, mensagem: "Valores de teste." })
    if (caminho === "saldo") return json({ creditos: 5 - debitos, fichas_desbloqueadas: debitos })
    if (caminho === "compras" && req.method() === "GET") return json([compra(99)])
    if (caminho === "compras" && req.method() === "POST") { chaves.push(req.postDataJSON().chave_idempotencia); return json(compra(chaves.length)) }
    if (caminho.startsWith("compras/")) return json(compra(Number(caminho.split("/")[1]), "paga"))
    if (caminho === "comparar") {
      const { codigos_car } = req.postDataJSON()
      if (!desbloqueada || req.headers().authorization !== "Bearer cliente-a" || codigos_car.some((c) => ![car, car2].includes(c))) return json({ detail: "Ficha precisa de crédito pago" }, 402)
      return json({ fichas: codigos_car.map((codigo_car) => ({ ...ficha, codigo_car })) })
    }
    if (caminho === "buscas-salvas" && req.method() === "GET") return json(req.headers().authorization === "Bearer cliente-a" ? buscasSalvas : [])
    if (caminho === "buscas-salvas" && req.method() === "POST") {
      const { nome, filtros } = req.postDataJSON(); assert.equal(filtros.area_min_ha, "0")
      const nova = salvo(nome, { ...filtros, area_min_ha: 0 }); buscasSalvas = [nova]; return json(nova)
    }
    if (caminho.startsWith("buscas-salvas/") && req.method() === "DELETE") { buscasSalvas = []; avisos = []; return json({ id: "busca-1", excluida: true }) }
    if (caminho === "avisos") {
      const lista = req.headers().authorization === "Bearer cliente-a" ? avisos.filter((a) => a.id > Number(url.searchParams.get("depois") || 0)) : []
      return json({ avisos: lista.slice(0, 50), proximo_cursor: lista.length > 50 ? lista[49].id : null })
    }
    if (caminho === "avisos/7/ler") { avisos = avisos.map((a) => ({ ...a, lida_em: "2026-11-12" })); return json({ id: 7, lida_em: "2026-11-12" }) }
    if (caminho.endsWith("/historico") || caminho.endsWith("/exportar")) {
      assert.ok(desbloqueada && req.headers().authorization === "Bearer cliente-a", "Histórico e exportações só com ficha paga na própria conta")
      if (caminho.endsWith("/historico")) { assert.equal(url.searchParams.get("limite"), "20"); return json({ codigo_car: car, historico: [{ id: 2, origem: "carga", registrada_em: "2026-11-12T15:00:00Z", versao_id: 2, anterior_id: 1, mudancas, hash_conteudo: "b".repeat(64) }] }) }
      return url.searchParams.get("formato") === "json" ? json({ ficha, protecao: { marca: "marca-sintetica-da-conta" } }) : route.fulfill({ contentType: "text/csv", body: "marca,campo,valor\nmarca-sintetica-da-conta,area_total,30\n" })
    }
    if (caminho.endsWith("/pdf")) return desbloqueada && req.headers().authorization === "Bearer cliente-a" ? route.fulfill({ contentType: "application/pdf", body: "%PDF-1.4\nTeste de ficha paga" }) : json({ detail: "Ficha precisa de crédito pago" }, 402)
    if (caminho.endsWith("/desbloquear")) { desbloqueada = true; debitos++; return json({ ...ficha, o_que_mudou: { ...ficha.o_que_mudou, primeira_consulta: true, consulta_anterior_em: null, versao_anterior_id: null, mudancas: [] } }) }
    if (caminho.includes("/visual")) {
      assert.ok(desbloqueada && req.headers().authorization === "Bearer cliente-a", "Visual só depois do crédito e com a sessão da conta")
      if (caminho.endsWith("satelite.webp")) return route.fulfill({ status: 200, contentType: "image/png", body: imagemTeste })
      if (caminho.endsWith("satelite")) return json({ disponivel: true, caixa: [-52.105, -6.705, -52.075, -6.675], data_cena: "2026-10-10", metodo: "cena", satelite: "Sentinel-2", credito: creditoTeste, largura: 4, altura: 4 })
      return json(visual)
    }
    if (caminho === `fichas/${car}/pastas`) return json({ codigo_car: car, pastas: [{ pedido_id: "pedido-teste", opcao: "barata", pasta_id: "pasta-teste", versao_id: "versao-teste", numero: 1, pronto: false, data_corte: "2026-11-12", imovel: { codigo_car: car, titulo: { nivel: "documento_apresentado", situacao: "pendente", fontes: [] }, creditos: [] } }] })
    if (caminho.startsWith("fichas/")) return desbloqueada && req.headers().authorization === "Bearer cliente-a" ? json(ficha) : json({ detail: "Ficha precisa de crédito pago" }, 402)
    if (caminho === "contatos") { contatos++; assert.deepEqual(req.postDataJSON(), { codigo_car: car }); return json({ id: 7, estado: "recebido", criado_em: "2026-11-12", mensagem: "Pedido registrado na Raíz. O contato será tratado depois." }) }
    if (caminho === "busca" || caminho === "agregado") {
      const liberada = desbloqueada && req.headers().authorization === "Bearer cliente-a"
      const resumo = caminho === "agregado" ? totais : { ...totais, fichas_liberadas: liberada ? 1 : 0, area_restauravel_ha: liberada ? 12 : null, credito_p10: liberada ? 100 : null, credito_p50: liberada ? 150 : null, credito_p90: liberada ? 200 : null, com_credito: liberada ? 1 : 0 }
      return json({ total: 10, pagina: 1, limite: 20, tem_mais: false, totais: resumo, escopo_metricas: caminho === "agregado" ? "agregado_regional" : "fichas_liberadas",
        agrupamentos: [{ uf: "PA", cod_ibge: 1507300, municipio: "São Félix do Xingu", bioma: "Amazônia", fazendas: 10, area_ha: 300, credito_p50: liberada ? 150 : null, criterio: "Mesmo município e bioma; proximidade a confirmar." }],
        imoveis: caminho === "agregado" ? undefined : [{ codigo_car: car, ficha_liberada: liberada, situacao_basica: "com_pendencia", uf: "PA", cod_ibge: 1507300, municipio: "São Félix do Xingu", bioma: "Amazônia", area_ha: 30, area_restauravel_ha: liberada ? 12 : null, caminho_terra: liberada ? "posse_em_titulacao" : null, risco: liberada ? "medio" : null, pequena: true, agrupar: true, credito_p50: liberada ? 150 : null, fonte: "Base de teste", data_corte: "2026-11-12" }], aviso: "Dados controlados de teste." })
    }
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
  assert.equal(chamadas.filter((c) => c.caminho.includes("/historico") || c.caminho.includes("/exportar")).length, 0)
  assert.equal(await page.getByRole("link", { name: "Em leilão: conferir edital e prazo", exact: true }).count(), 0)
  assert.equal(chamadas.filter((c) => c.caminho === "/teste-api/eventos").length, 0, "Só confere vínculos do calendário após desbloquear a ficha")
  await print("ficha-bloqueada-1440.png")
  const leiturasAntesDesbloqueio = chamadas.filter((c) => c.caminho === `fichas/${car}`).length
  await page.getByRole("button", { name: "Desbloquear por 1 crédito" }).click()
  await page.getByRole("heading", { name: "Uso da terra ao longo dos anos" }).waitFor()
  await page.getByRole("link", { name: "Em leilão: conferir edital e prazo", exact: true }).waitFor()
  assert.equal(await page.getByRole("link", { name: "Em leilão: conferir edital e prazo", exact: true }).getAttribute("href"), `#/calendario/${encodeURIComponent(car)}`)
  assert.equal(debitos, 1)
  await page.getByText("Esta é a primeira consulta desta conta.", { exact: false }).waitFor()
  assert.equal(chamadas.filter((c) => c.caminho === `fichas/${car}`).length, leiturasAntesDesbloqueio, "Desbloquear usa a ficha recebida, sem uma segunda leitura que apagaria a comparação")
  await page.reload()
  await page.getByRole("heading", { name: "Uso da terra ao longo dos anos" }).waitFor()
  await page.getByRole("heading", { name: "Terra comprometida", exact: true }).waitFor()
  await page.getByText("Cobertura parcial. Escopo:", { exact: false }).waitFor()
  await page.getByText("Certeza: Polígono oficial.", { exact: false }).waitFor()
  await page.getByRole("button", { name: "Ver a conferência nos meus lotes", exact: true }).click()
  await page.getByText("Título em nível: Documento apresentado.", { exact: false }).waitFor()
  assert.equal(await page.getByRole("link", { name: "Lote barata, versão 1", exact: true }).getAttribute("href"), "#/pedidos/pedido-teste/pasta/barata")
  assert.equal(debitos, 1, "A pasta do próprio lote não compra outra ficha")
  const versoes = page.locator(".versoes-ficha")
  await versoes.locator("summary").filter({ hasText: /^Embargos$/ }).click()
  await versoes.getByText("IBAMA sintético", { exact: false }).waitFor()
  assert.ok((await versoes.innerText()).includes("Antes") && (await versoes.innerText()).includes("Depois"))
  await versoes.getByRole("button", { name: "Ver histórico da ficha" }).focus()
  await page.keyboard.press("Enter")
  await versoes.getByRole("region", { name: "Histórico da ficha" }).waitFor()
  await versoes.locator(".historico-ficha > li > details > summary").click()
  await versoes.locator(".historico-ficha .mudancas-terra summary").click()
  assert.ok((await versoes.innerText()).includes("Identificador de integridade"))
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
  const download = page.waitForEvent("download")
  await page.getByRole("button", { name: "Exportar ficha em PDF" }).click()
  const pdf = await download
  assert.ok(pdf.suggestedFilename().endsWith(".pdf"))
  const caminhoPdf = await pdf.path()
  assert.ok(fs.readFileSync(caminhoPdf, "utf8").startsWith("%PDF-"))
  assert.equal(debitos, 1, "Exportar não consome outro crédito")
  for (const formato of ["json", "csv"]) {
    const baixando = page.waitForEvent("download")
    await page.getByRole("button", { name: `Exportar ficha em ${formato.toUpperCase()}` }).click()
    const arquivo = await baixando
    assert.ok(arquivo.suggestedFilename().endsWith(`.${formato}`))
    assert.ok(fs.readFileSync(await arquivo.path(), "utf8").includes("marca-sintetica-da-conta"), "Marca retornada pelo servidor permanece na exportação")
  }
  assert.equal(debitos, 1, "Histórico e todos os formatos não debitam créditos")
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
  const mapaPrivado = page.locator(".mapa-ficha-terra")
  const credito = mapaPrivado.locator(".maplibregl-ctrl-attrib-inner")
  assert.ok((await credito.innerText()).includes(creditoTeste), "Atribuição Sentinel permanece íntegra junto aos créditos da base cartográfica")
  const caixaMapa = await mapaPrivado.boundingBox(), caixaCredito = await credito.boundingBox()
  const caixaEscala = await mapaPrivado.locator(".maplibregl-ctrl-scale").boundingBox()
  assert(caixaMapa && caixaCredito && caixaEscala)
  assert(caixaEscala.y + caixaEscala.height <= caixaCredito.y, "Escala fica acima da atribuição, sem sobrepor o texto completo")
  assert(caixaCredito.x >= caixaMapa.x && caixaCredito.x + caixaCredito.width <= caixaMapa.x + caixaMapa.width, "Atribuição cabe na largura do mapa")
  assert(caixaCredito.y + caixaCredito.height <= caixaMapa.y + caixaMapa.height, "Atribuição inteira permanece visível")
  assert.equal(await mapaPrivado.locator(".maplibregl-ctrl-attrib-button:visible").count(), 0, "Crédito aberto não exibe botão redundante")
  for (const botao of await mapaPrivado.locator(".maplibregl-ctrl-group button").all()) {
    const caixa = await botao.boundingBox()
    assert(caixa && caixa.width >= 48 && caixa.height >= 48, "Controles do mapa têm área de toque de 48 px no celular")
  }
  await page.screenshot({ path: path.join(prints, "mapa-ficha-terra-360.png") })
  await print("ficha-terra-360.png")
  await conferirPaginaAcessivel(page, AxeBuilder, "ficha-desbloqueada-360", prints)
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Ficha cabe no celular")
  await page.goto(`${url}#/prospeccao`)
  await page.getByRole("heading", { name: "Quanto existe na base" }).waitFor()
  await page.getByLabel("Área mínima, ha").fill("0")
  await page.getByRole("button", { name: "Aplicar filtros" }).click()
  await page.getByRole("heading", { name: "Quanto existe na base" }).waitFor()
  await page.getByLabel("Nome da busca", { exact: true }).fill("Áreas pequenas")
  await page.getByRole("button", { name: "Salvar filtros aplicados" }).click()
  await page.getByRole("button", { name: "Aplicar busca Áreas pequenas", exact: true }).waitFor()
  await page.getByRole("button", { name: "Limpar filtros" }).click()
  await page.getByRole("button", { name: "Aplicar busca Áreas pequenas", exact: true }).click()
  assert.equal(await page.getByLabel("Área mínima, ha").inputValue(), "0")
  avisos = [{ id: 7, busca_id: "busca-1", nome_busca: "Áreas pequenas", codigo_car: car, criada_em: "2026-11-12", lida_em: null, tipo: "alteracao_terra", ficha_liberada: true, mudancas, mensagem: "Há atualizações da terra ou da seleção. Consulte a ficha liberada." }]
  await page.getByRole("button", { name: "Atualizar avisos" }).click()
  await page.locator(".buscas-salvas .mudancas-terra summary").click()
  await page.locator(".buscas-salvas").getByText("IBAMA sintético", { exact: false }).waitFor()
  await conferirPaginaAcessivel(page, AxeBuilder, "avisos-mudancas-360", prints)
  await page.getByRole("button", { name: "Marcar aviso como lido" }).click()
  await page.getByText("Lido em 12/11/2026.", { exact: false }).waitFor()
  await page.getByLabel("Códigos do CAR para comparar").fill(`${car}\n${car2}`)
  await page.getByRole("button", { name: "Comparar fichas liberadas", exact: true }).click()
  await page.locator(".comparar-fazendas table").first().waitFor()
  assert.equal(debitos, 1, "Comparar não consome crédito")
  assert.equal(await page.locator(".comparar-fazendas table").getByText("Base de teste da terra", { exact: false }).count() > 0, true)
  await print("comparacao-360.png")
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Comparação cabe no celular")
  avisos = [...avisos, ...Array.from({ length: 51 }, (_, k) => ({ ...avisos[0], id: k + 8, lida_em: null }))]
  await page.getByRole("button", { name: "Atualizar avisos" }).click()
  await page.getByRole("button", { name: "Carregar mais avisos" }).click()
  await page.getByRole("button", { name: "Atualizar avisos" }).click()
  assert.equal(await page.getByText("Áreas pequenas: novo aviso", { exact: true }).count(), 51, "Atualização preserva páginas anteriores e busca avisos novos pelo maior id")
  await page.getByText("Lido em 12/11/2026.", { exact: false }).waitFor()
  await page.getByRole("button", { name: "Excluir busca Áreas pequenas", exact: true }).click()
  await page.getByText("Busca excluída.", { exact: true }).waitFor()
  assert.deepEqual(buscasSalvas, [])
  await page.getByLabel("Nome da busca", { exact: true }).fill("Áreas pequenas")
  await page.getByRole("button", { name: "Salvar filtros aplicados" }).click()
  await page.getByRole("button", { name: "Aplicar busca Áreas pequenas", exact: true }).waitFor()
  await page.getByLabel("Códigos do CAR para comparar").fill(`${car}\nPA-1507300-CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC`)
  await page.getByRole("button", { name: "Comparar fichas liberadas", exact: true }).click()
  await page.locator(".comparar-fazendas").getByRole("alert").waitFor()
  assert.equal(await page.locator(".comparar-fazendas table").count(), 0, "A comparação não deixa resultado parcial de ficha bloqueada")
  assert.equal(debitos, 1)
  await page.getByLabel("Códigos do CAR para comparar").fill(`${car}\n${car2}`)
  await page.getByRole("button", { name: "Comparar fichas liberadas", exact: true }).click()
  await page.locator(".comparar-fazendas table").first().waitFor()
  // Uma resposta privada iniciada na conta A não pode reaparecer ou baixar após trocar para B.
  const concorrente = await ctx.newPage(), downloadsTardios = []
  concorrente.on("download", (d) => downloadsTardios.push(d))
  let liberarRespostas, exportacaoIniciada, historicoIniciado
  const liberar = new Promise((resolve) => { liberarRespostas = resolve })
  const pediuExportacao = new Promise((resolve) => { exportacaoIniciada = resolve })
  const pediuHistorico = new Promise((resolve) => { historicoIniciado = resolve })
  const respostasTerminadas = []
  for (const recurso of ["historico?limite=20", "exportar?formato=csv"]) {
    let terminou
    respostasTerminadas.push(new Promise((resolve) => { terminou = resolve }))
    await concorrente.route(`**/fichas/${car}/${recurso}`, async (route) => {
      assert.equal(route.request().headers().authorization, "Bearer cliente-a")
      if (recurso.startsWith("historico")) historicoIniciado(); else exportacaoIniciada()
      await liberar
      try { await route.fulfill({ contentType: recurso.startsWith("historico") ? "application/json" : "text/csv", body: recurso.startsWith("historico") ? JSON.stringify({ codigo_car: car, historico: [] }) : "conta,marca\nA,nao-pode-baixar\n" }) }
      catch { /* O AbortController pode encerrar o pedido antes da resposta. */ }
      finally { terminou() }
    })
  }
  await concorrente.goto(`${url}#/fazenda/${car}`)
  await concorrente.getByRole("button", { name: "Ver histórico da ficha" }).click()
  await concorrente.getByRole("button", { name: "Exportar ficha em CSV" }).click()
  await Promise.all([pediuHistorico, pediuExportacao])
  precosProvisorios = true
  await page.evaluate(() => { localStorage.setItem("raiz.sessao", JSON.stringify({ token: "cliente-b", email: "outra@raiz.invalid" })); window.dispatchEvent(new Event("raiz-sessao")) })
  await concorrente.getByRole("button", { name: "Desbloquear por 1 crédito" }).waitFor()
  liberarRespostas(); await Promise.all(respostasTerminadas)
  assert.equal(await concorrente.locator(".versoes-ficha").count(), 0)
  assert.equal(await concorrente.getByRole("button", { name: "Exportar ficha em CSV" }).count(), 0)
  assert.deepEqual(downloadsTardios, [])
  await concorrente.close()
  await page.getByRole("heading", { name: "Quanto existe na base" }).waitFor()
  assert.equal(await page.locator(".comparar-fazendas table").count(), 0)
  assert.equal(await page.getByRole("button", { name: "Aplicar busca Áreas pequenas", exact: true }).count(), 0)
  await page.getByText("Ficha completa fechada", { exact: true }).waitFor()
  assert.equal(await page.getByText("Disponível na ficha paga", { exact: true }).count(), 2)
  await page.getByText("Crédito e área restaurável abaixo somam somente as 0 fichas liberadas", { exact: false }).waitFor()
  await page.getByText("1 crédito: preço a definir pelo fundador", { exact: false }).waitFor()
  assert.equal(await page.getByRole("button", { name: "Compra ainda indisponível" }).count(), 3)
  for (const botao of await page.getByRole("button", { name: "Compra ainda indisponível" }).all()) assert.ok(await botao.isDisabled())
  await page.getByText("Proposta: 50 créditos por ciclo de 1 mês.", { exact: false }).waitFor()
  await page.goto(`${url}#/fazenda/${car}`)
  await page.getByRole("button", { name: "Desbloquear por 1 crédito" }).waitFor()
  assert.equal(await page.getByRole("heading", { name: "Uso da terra ao longo dos anos" }).count(), 0)
  assert.equal(await page.getByRole("button", { name: "Exportar ficha em PDF" }).count(), 0)
  assert.equal(await page.getByRole("button", { name: "Exportar ficha em JSON" }).count(), 0)
  assert.equal(await page.locator(".versoes-ficha").count(), 0)
  assert.equal(await page.locator(".compromissos-terra").count(), 0)
  assert.equal(await page.locator(".visual-terra").count(), 0, "O mapa e o satélite da conta anterior desaparecem ao trocar a sessão")
  assert.equal(await page.getByText("Pedido 7 recebido", { exact: false }).count(), 0)
  assert.equal(await page.getByRole("link", { name: "Em leilão: conferir edital e prazo", exact: true }).count(), 0)
  await page.goto(`${url}#/prospeccao`)
  await page.getByRole("heading", { name: "Quanto existe na base" }).waitFor()
  await page.getByLabel("Área mínima, ha").fill("0")
  await page.getByRole("button", { name: "Aplicar filtros" }).click()
  await page.getByRole("heading", { name: "Quanto existe na base" }).waitFor()
  await print("busca-terra-360.png")
  await conferirPaginaAcessivel(page, AxeBuilder, "prospeccao-360", prints)
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Busca cabe no celular")
  assert.equal(await page.locator('a[href="#/"]').count() > 0, true)
  await page.evaluate(() => { localStorage.removeItem("raiz.sessao"); window.dispatchEvent(new Event("raiz-sessao")) })
  await page.getByRole("link", { name: "Entre para ver a lista de fazendas" }).waitFor()
  assert.ok(await page.getByLabel("Área mínima, ha").isDisabled())
  assert.equal(await page.locator(`a[href*="${car}"]`).count(), 0)
  assert.ok(chamadas.filter((c) => c.caminho === "agregado").every((c) => !c.token))
  assert.deepEqual(erros, [])
  console.log(`Prospecção conferida no Chromium: mapa privado, Sentinel-2 simulado, linha do tempo, compromissos e cobertura, versões/diff/histórico, exportações autenticadas PDF/JSON/CSV, cancelamento na troca de conta, débito, contato, compra repetida, comparação, buscas/avisos, três planos propostos, axe e celular. Prints em ${prints}`)
} finally { await browser.close(); await servidor.close() }
