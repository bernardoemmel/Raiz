#!/usr/bin/env node
/** Alcance nacional com manifesto controlado e contrato real da API. Nenhum número de fixture vai para o site. */
import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"
import { createRequire } from "node:module"
import { pathToFileURL } from "node:url"
import { REPO, FIXTURE, preparar } from "./preparar-teste-site.mjs"
import { conferirPaginaAcessivel } from "./conferir-acessibilidade.mjs"

const globo = path.join(REPO, "front/globo")
const require = createRequire(path.join(globo, "package.json"))
const { chromium } = require("playwright")
const { default: AxeBuilder } = await import(pathToFileURL(require.resolve("@axe-core/playwright")).href)
const { createServer } = await import(pathToFileURL(require.resolve("vite")).href)
const resultado = path.join(REPO, "front/.cache/teste-site/resultado/pedido-nacional")
fs.mkdirSync(resultado, { recursive: true })
preparar()
process.env.RAIZ_DADOS = path.join(FIXTURE, "dados")
process.env.RAIZ_GEO = path.join(FIXTURE, "geo")
process.env.RAIZ_BASE = "/"
process.env.VITE_CONFIG_NATIVE_IGNORE_WARNING = "true"
const ufs = "AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split(" ")
let novoEstado = false
function manifesto() {
  return { pasta: "publicada", lista_ibge: "Fixture do manifesto", gerado_em: "2026-11-12T21:00:00Z", estados: ufs.map((uf) => ({
    uf, nome: uf, cod: "", municipios: uf === "PA" ? 144 : uf === "GO" ? 10 : uf === "RS" && novoEstado ? 4 : 0,
    municipios_ibge: uf === "PA" ? 144 : uf === "GO" ? 246 : 10, com_lista: [], fora_da_lista: [], completo: uf === "PA", situacao: uf === "PA" ? "completo" : uf === "GO" || uf === "RS" && novoEstado ? "incompleto" : "sem_dados",
  })) }
}
const servidor = await createServer({ root: globo, configFile: path.join(globo, "vite.config.ts"), define: { "import.meta.env.VITE_RAIZ_API": JSON.stringify("/api/") }, server: { host: "127.0.0.1", port: 0 }, logLevel: "error" })
await servidor.listen()
const navegador = await chromium.launch({ ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}), args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] })
const erros = [], enviados = []
try {
  const contexto = await navegador.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" })
  const pagina = await contexto.newPage()
  pagina.setDefaultTimeout(15_000)
  pagina.on("pageerror", (e) => erros.push(e.message))
  pagina.on("response", (r) => { if (r.status() >= 400) erros.push(`${r.status()} ${r.url()}`) })
  await pagina.addInitScript(() => localStorage.setItem("raiz.sessao", JSON.stringify({ token: "sessao-teste-nacional", email: "cliente@example.test" })))
  await pagina.route("**/amostra/estados.json", (rota) => rota.fulfill({ json: manifesto() }))
  let pedido
  await pagina.route("**/api/pedidos", (rota) => {
    assert.equal(rota.request().method(), "POST")
    assert.equal(rota.request().headers().authorization, "Bearer sessao-teste-nacional")
    const campos = rota.request().postDataJSON()
    enviados.push(campos.onde)
    pedido = { id: "alcance", criado_em: "2026-11-12T21:00:00Z", campos, status: "faltou", versao_modelo: "fixture-nacional", opcoes: [], opcao_escolhida: null, reservado_ate: null, alertas: [], base: { fazendas: 0, hectares: 0, creditos: { p10: 0, p50: 0, p90: 0 }, por_caminho: [], por_interesse: [], alcanca_meta: false, falta: campos.meta.valor, afrouxar: [] } }
    return rota.fulfill({ json: pedido })
  })
  await pagina.route("**/api/pedidos/alcance", (rota) => rota.fulfill({ json: pedido }))
  const novo = async () => {
    await pagina.goto(`${servidor.resolvedUrls.local[0]}#/pedidos/novo`)
    await pagina.getByRole("heading", { name: "Novo pedido", exact: true }).waitFor()
    await pagina.locator(".cobertura-pedido time").waitFor()
  }
  const enviar = async () => {
    await pagina.getByRole("button", { name: "Ver o que existe e montar o lote", exact: true }).click()
    await pagina.getByRole("heading", { name: "Quanto existe na nossa base", exact: true }).waitFor()
  }
  await novo()
  await pagina.getByLabel("Num raio de uma planta ou fábrica", { exact: true }).check()
  await pagina.getByLabel("Latitude", { exact: true }).fill("-10")
  await pagina.getByLabel("Longitude", { exact: true }).fill("-50")
  await pagina.getByLabel("Raio (km)", { exact: true }).fill("25")
  await pagina.getByLabel("Brasil inteiro", { exact: true }).check()
  assert.equal(await pagina.getByLabel("Num raio de uma planta ou fábrica", { exact: true }).isChecked(), false)
  await pagina.getByText("Dados publicados em 2 estados.", { exact: true }).waitFor()
  assert.match(await pagina.locator(".cobertura-pedido").innerText(), /Cobertura parcial: Goiás/)
  for (const width of [1440, 360]) {
    await pagina.setViewportSize({ width, height: 960 })
    await conferirPaginaAcessivel(pagina, AxeBuilder, `brasil-${width}`, resultado)
  }
  await enviar()
  assert.deepEqual(enviados.at(-1), { biomas: [], ufs: [], municipios: [], raio: null, poligono: null, so_fornecedores_cadeia: false })
  await novo()
  await pagina.getByLabel("Um ou mais estados", { exact: true }).focus()
  await pagina.keyboard.press("ArrowDown")
  assert(await pagina.getByLabel("Um ou mais biomas", { exact: true }).isChecked())
  await pagina.getByLabel("Cerrado", { exact: true }).check()
  await pagina.getByText(/estes totais não medem a oferta do bioma/).waitFor()
  await conferirPaginaAcessivel(pagina, AxeBuilder, "biomas-360", resultado)
  await enviar()
  assert.deepEqual(enviados.at(-1).ufs, [])
  assert.deepEqual(enviados.at(-1).biomas, ["Amazônia", "Cerrado"])
  await novo()
  await pagina.getByRole("button", { name: "Tirar Pará", exact: true }).click()
  await pagina.getByLabel("Adicionar estado", { exact: true }).selectOption("RS")
  await pagina.getByText("Nenhum estado com dados publicados neste alcance.", { exact: true }).waitFor()
  assert.match(await pagina.locator(".cobertura-pedido").innerText(), /Ainda sem dados publicados: Rio Grande do Sul/)
  await enviar()
  assert.deepEqual(enviados.at(-1).ufs, ["RS"])
  novoEstado = true
  await pagina.reload()
  await novo()
  await pagina.getByLabel("Brasil inteiro", { exact: true }).check()
  await pagina.getByText("Dados publicados em 3 estados.", { exact: true }).waitFor()
  assert.match(await pagina.locator(".cobertura-pedido").innerText(), /Entram na consulta: Goiás, Pará, Rio Grande do Sul/)
  assert.deepEqual(erros, [])
  fs.writeFileSync(path.join(resultado, "resultado.json"), JSON.stringify({ erros, pedidos: enviados, verificacoes: ["27 UFs e 6 biomas", "Brasil limpa o recorte anterior", "estados ausentes e parciais", "estado novo automático", "contrato autenticado", "teclado", "axe", "360 px", "zero 404"] }, null, 2))
  console.log("ok pedido por estado, bioma e Brasil; cobertura atualizada, API, teclado, axe, 360 px e zero 404")
} finally {
  await navegador.close()
  await servidor.close()
}
