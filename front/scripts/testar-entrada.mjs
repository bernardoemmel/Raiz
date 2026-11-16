#!/usr/bin/env node
/** Teste de integração da entrada V2: mapa inteiro, resumo real, menu e busca por teclado,
 * estado/município/CAR e dados extensos em diálogo. As camadas e geometrias são verificadas
 * pelo teste Pages e pelos testes unitários do estilo e dos hexágonos. */
import { execSync, spawnSync } from "node:child_process"
import fs from "node:fs"
import { createRequire } from "node:module"
import os from "node:os"
import path from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import { gzipSync } from "node:zlib"
import { CAR, MUNICIPIO } from "./preparar-teste-site.mjs"
import { conferirAtribuicaoCompacta } from "./conferir-atribuicao.mjs"

const GLOBO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../globo")
const doGlobo = createRequire(path.join(GLOBO, "package.json"))

function playwright() {
  try {
    return doGlobo("playwright")
  } catch {
    // instalado no sistema (fora do projeto)
    return createRequire(path.join(execSync("npm root -g").toString().trim(), "x.js"))("playwright")
  }
}

const { createServer } = await import(pathToFileURL(doGlobo.resolve("vite")).href)
const { chromium } = playwright()

const SFX = "1507300"
const ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]

let falhas = 0
const conferir = (ok, frase) => {
  console.log(`${ok ? "ok  " : "FALHOU"} ${frase}`)
  if (!ok) falhas++
}

// 0. sem internet: o predev avisa e segue, sem trocar uma origem ausente por números da amostra.
const semInternet = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "raiz-e2e-")), "estados")
const predev = spawnSync(process.execPath, [path.resolve(GLOBO, "../scripts/baixar-dados.mjs")], {
  env: { ...process.env, RAIZ_DADOS: semInternet, RAIZ_DADOS_URL: "http://127.0.0.1:9/dados", RAIZ_SEM_DOWNLOAD: "" },
  encoding: "utf8",
  timeout: 30000,
})
conferir(predev.status === 0 && /não consegui ler o estados\.json público/.test(predev.stderr), "sem internet, o predev avisa e segue")
conferir(!fs.existsSync(semInternet), "uma falha de download não cria dados substitutos")
process.env.RAIZ_DADOS = semInternet
const semDados = await createServer({ root: GLOBO, configFile: path.join(GLOBO, "vite.config.ts"), server: { port: 0 }, logLevel: "error" })
try {
  await semDados.listen()
  const manifest = await (await fetch(new URL("amostra/estados.json", semDados.resolvedUrls.local[0]))).json()
  conferir(manifest.pasta === "RAIZ_DADOS" && manifest.estados.length === 27 && manifest.estados.every(e => e.situacao === "sem_dados" && e.municipios === 0 && e.com_lista.length === 0), "uma origem ausente mantém os estados sem dados e não publica a amostra silenciosamente")
} finally {
  await semDados.close()
}
// A navegação usa a amostra do repositório por seleção explícita: os valores permanecem verificáveis.
process.env.RAIZ_DADOS = "dados/amostra"
process.env.VITE_RAIZ_PROCESSAMENTO_URL = "./amostra/processamento.json"

const servidor = await createServer({ root: GLOBO, configFile: path.join(GLOBO, "vite.config.ts"), server: { port: 0 }, logLevel: "error" })
await servidor.listen()
const URL_BASE = servidor.resolvedUrls.local[0]
const navegador = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, args: ARGS })

async function pagina(opcoes) {
  const ctx = await navegador.newContext(opcoes)
  const p = await ctx.newPage()
  const pedidos = []
  const erros = []
  p.on("request", (r) => pedidos.push(r.url()))
  p.on("pageerror", (e) => erros.push(e.message))
  return { p, pedidos, erros }
}

async function buscar(p, texto, opcao) {
  const dados = p.locator(".dados-mapa-v2[open]")
  if (await dados.count()) await p.getByRole("button", { name: "Fechar dados" }).click()
  const abrir = p.getByRole("button", { name: "Buscar CAR, município ou estado" })
  if (await abrir.isVisible()) await abrir.click()
  const caixa = p.locator(".topo .busca input")
  await caixa.fill(texto)
  const item = opcao ? p.locator(".busca li[role=option]", { hasText: opcao }).first() : p.locator(".busca li[role=option]").first()
  await item.waitFor({ timeout: 20000 })
  await caixa.press("Enter")
}

try {
  {
    const { p, pedidos, erros } = await pagina({ viewport: { width: 1440, height: 900 } })
    await p.goto(URL_BASE)
    await p.waitForFunction(() => document.querySelector(".mapa-brasil .mapa")?.__mapa?.loaded(), null, { timeout: 30000 })
    await p.locator("#territorio-v2-titulo").waitFor()
    conferir(!pedidos.some((u) => /(?:^|\/)cobe(?:[./?]|$)/i.test(new URL(u).pathname)), "a entrada não baixa o cobe")
    conferir((await p.getByText("Pular abertura").count()) === 0, "não há abertura nem botão de pular")
    conferir(new URL(p.url()).hash === "", "a entrada abre sem nada no endereço")
    conferir(await p.locator(".topo .busca input").isVisible(), "a busca está no topo")
    conferir(await p.locator(".painel-lateral").count() === 0, "o mapa não divide espaço com uma coluna lateral")
    const mapa = await p.locator(".mapa-brasil").boundingBox()
    conferir(mapa.x === 0 && mapa.y === 0 && mapa.width === 1440 && mapa.height === 900, "o mapa ocupa a tela inteira")
    const estados = await (await p.request.get(URL_BASE + "amostra/estados.json")).json()
    conferir(estados.pasta === "amostra", "a navegação usa a amostra selecionada explicitamente")
    const rotulos = await p.evaluate(() => Object.fromEntries(document.querySelector(".mapa-brasil .mapa").__mapa.getSource("estados-rotulos").serialize().data.features.map((f) => [f.properties.uf, f.properties.linha])))
    conferir(/144.*municípios/.test(rotulos.PA), "o Pará preserva a cobertura publicada nos rótulos")
    conferir(/ainda não processado/.test(rotulos.GO) && Object.keys(rotulos).length === 27, "todos os estados preservam o aviso de cobertura")
    conferir(!pedidos.some((u) => /pontos_|brasil_municipios\.geojson/.test(u)), "a escala nacional não carrega milhares de pontos ou limites municipais")
    const camadas = await p.evaluate(() => document.querySelector(".mapa-brasil .mapa").__mapa.getStyle().layers)
    conferir(camadas.some((l) => l.id === "hexagonos" && l.type === "fill"), "o agregado usa uma camada de hexágonos")
    conferir(!camadas.some((l) => l.source === "hexagonos" && l.type === "circle"), "o agregado não usa bolas verdes")

    await buscar(p, "Pará", "Pará (PA)")
    await p.waitForURL(/#\/estado\/PA$/)
    await p.getByRole("button", { name: "Sobre os dados" }).click()
    await p.locator(".estado-situacao").waitFor()
    conferir(/Completo/.test((await p.locator(".estado-situacao").textContent()) ?? ""), "a busca estadual abre a cobertura do Pará")

    await buscar(p, "são félix", "São Félix do Xingu")
    await p.waitForURL(new RegExp(`#/municipio/${SFX}$`), { timeout: 20000 })
    await p.waitForFunction(() => document.querySelector("#territorio-v2-titulo")?.textContent.includes("São Félix do Xingu"))
    conferir((await p.locator("#territorio-v2-titulo").textContent()).includes("São Félix do Xingu"), "a busca municipal atualiza o cartão")
    await p.getByRole("button", { name: "Sobre os dados" }).click()
    await p.locator(".funil-barras").waitFor({ timeout: 60000 })
    conferir((await p.locator(".fb-dentro").count()) === 4, "o detalhe mantém as quatro etapas do funil")
    await p.locator(".fb-dentro").nth(2).click()
    conferir(await p.locator(".fb-dentro").nth(2).getAttribute("aria-pressed") === "true", "o funil mantém o filtro de imóveis")
    conferir((await p.locator(".migalhas a", { hasText: "Pará" }).getAttribute("href")) === "#/estado/PA", "a trilha municipal leva ao estado")

    await buscar(p, "Goiás", "Goiás (GO)")
    await p.waitForURL(/#\/estado\/GO$/)
    await p.getByRole("button", { name: "Sobre os dados" }).click()
    await p.getByText("O estado de Goiás ainda não foi processado pela Raíz.").waitFor({ timeout: 20000 })
    conferir(await p.getByText("Os 246 municípios aparecem aqui").isVisible(), "um estado sem dados avisa sua cobertura real")

    await buscar(p, "sinop", "Ainda não processado")
    await p.waitForURL(/#\/municipio\/5107909$/, { timeout: 20000 })
    await p.getByRole("button", { name: "Sobre os dados" }).click()
    await p.getByText("ainda não foi processado").first().waitFor({ timeout: 20000 })
    conferir(!pedidos.some((u) => /\/busca(?:\?|$)/.test(u)), "a busca continua no navegador, sem rota inexistente no Pages")
    conferir(erros.length === 0, `sem erro de JavaScript${erros.length ? ": " + erros[0] : ""}`)
    await p.context().close()
  }

  {
    // A amostra legada só publica agregados. O CAR usa uma fixture explícita do contrato básico atual,
    // compartilhada com os testes Pages; nenhum dado pago é necessário para buscar e abrir a rota da ficha.
    const { p, pedidos, erros } = await pagina({ viewport: { width: 1440, height: 900 } })
    await p.route("**/amostra/estados.json", async rota => {
      const resposta = await rota.fetch()
      const manifesto = await resposta.json()
      manifesto.acesso = "publico_basico"
      manifesto.estados = manifesto.estados.map(e => ({ ...e, com_lista: e.uf === "PA" ? [MUNICIPIO] : [] }))
      await rota.fulfill({ response: resposta, json: manifesto })
    })
    await p.route("**/amostra/indice_PA.json", async rota => {
      const resposta = await rota.fetch()
      const indice = await resposta.json()
      await rota.fulfill({ response: resposta, json: { ...indice, arquivos: [...indice.arquivos, `imoveis_basicos_${MUNICIPIO}.csv`] } })
    })
    await p.route(`**/amostra/imoveis_basicos_${MUNICIPIO}.csv.gz`, rota => rota.fulfill({
      contentType: "application/gzip",
      body: gzipSync(`cod_imovel,cod_ibge,municipio,uf,situacao_basica\n${CAR},${MUNICIPIO},Parauapebas,PA,apto\n`),
    }))
    await p.goto(URL_BASE)
    await buscar(p, CAR)
    await p.waitForURL(/#\/fazenda\//, { timeout: 20000 })
    conferir(decodeURIComponent(p.url()).endsWith(`#/fazenda/${CAR}`), "buscar um CAR público abre a ficha correspondente")
    await p.locator(".ficha h1, main h1").first().waitFor({ timeout: 30000 })
    conferir(!pedidos.some(u => /\/amostra\/imoveis_\d{7}\.csv|\/amostra\/fichas\//.test(u)), "a busca por CAR não solicita a lista privada nem a ficha completa em arquivos públicos")
    conferir(!pedidos.some(u => /\/busca(?:\?|$)/.test(u)), "a busca por CAR público continua no navegador")
    conferir(erros.length === 0, `CAR público: sem erro de JavaScript${erros.length ? ": " + erros[0] : ""}`)
    await p.context().close()
  }

  for (const largura of [360, 390]) {
    const { p, erros } = await pagina({ viewport: { width: largura, height: 844 }, isMobile: true, hasTouch: true })
    await p.goto(URL_BASE)
    await p.locator("#territorio-v2-titulo").waitFor()
    await conferirAtribuicaoCompacta(p)
    conferir(true, `${largura}px: os créditos começam compactos e abrem/recolhem por teclado sem perder fontes`)
    const botaoBusca = p.getByRole("button", { name: "Buscar CAR, município ou estado" })
    const busca = await botaoBusca.boundingBox()
    conferir(busca.y < 76 && busca.width >= 48 && busca.height >= 48, `${largura}px: a busca tem alvo de toque de 48 px`)
    const mapa = await p.locator(".mapa-brasil").boundingBox()
    conferir(mapa.x === 0 && mapa.y === 0 && mapa.width === largura && mapa.height === 844, `${largura}px: o mapa ocupa a tela inteira`)
    conferir(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${largura}px: sem rolagem horizontal`)
    const marca = p.getByLabel("Raíz, abrir menu e conta")
    await marca.focus(); await p.keyboard.press("Enter")
    conferir(await p.getByRole("navigation", { name: "Principal", exact: true }).getByRole("link", { name: "Pedidos", exact: true }).isVisible(), `${largura}px: o menu da marca mantém o acesso aos pedidos`)
    await p.keyboard.press("Escape")
    await p.keyboard.press("/")
    conferir(await p.locator(".topo-dialogo-busca[open]").count() === 1, `${largura}px: o atalho abre a busca acessível`)
    await p.keyboard.press("Escape")
    conferir(await p.locator(".topo-dialogo-busca[open]").count() === 0, `${largura}px: Escape fecha a busca vazia`)
    await buscar(p, "nova esperança", "Nova Esperança do Piriá")
    await p.waitForURL(/#\/municipio\/1504950$/, { timeout: 20000 })
    conferir(await p.locator(".topo-dialogo-busca[open]").count() === 0, `${largura}px: escolher resultado fecha a busca`)
    await p.getByRole("button", { name: "Sobre os dados" }).click()
    await p.locator(".funil-barras").waitFor({ timeout: 60000 })
    await p.getByRole("button", { name: "Fechar dados" }).click()
    await p.getByRole("button", { name: "Expandir resumo" }).focus()
    await p.keyboard.press("Enter")
    conferir(await p.locator(".cartao-ampliado").count() === 1, `${largura}px: o resumo expande pelo teclado`)
    conferir(erros.length === 0, `${largura}px: sem erro de JavaScript${erros.length ? ": " + erros[0] : ""}`)
    await p.context().close()
  }
} catch (e) {
  falhas++
  console.error("FALHOU", e.message.split("\n")[0])
} finally {
  await navegador.close()
  await servidor.close()
}
console.log(falhas ? `\n${falhas} conferência(s) falharam.` : "\nTudo certo.")
process.exit(falhas ? 1 : 0)
