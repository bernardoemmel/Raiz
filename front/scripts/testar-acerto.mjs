#!/usr/bin/env node
/** Fixture só no teste: versões, erros, ausência, celular e nenhuma rota inexistente. */
import assert from "node:assert/strict"
import fs from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import os from "node:os"
import { fileURLToPath, pathToFileURL } from "node:url"
import { conferirPaginaAcessivel } from "./conferir-acessibilidade.mjs"

const globo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../globo")
const require = createRequire(path.join(globo, "package.json"))
const { default: AxeBuilder } = await import(pathToFileURL(require.resolve("@axe-core/playwright")).href)
const { createServer } = await import(pathToFileURL(require.resolve("vite")).href)
const { chromium } = require("playwright")
const evidencias = path.resolve(globo, "../.cache/teste-site/resultado/acerto")
fs.mkdirSync(evidencias, { recursive: true })
const pasta = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-acerto-teste-"))
process.env.RAIZ_ACERTO_DADOS = path.join(pasta, "placar.json")
fs.writeFileSync(process.env.RAIZ_ACERTO_DADOS, JSON.stringify({ schema: "raiz.acerto.publico.v1", gerado_em: null, fonte: "Banco de aprendizado da Raíz", minimo_imoveis: 5, versoes: [] }))
const servidor = await createServer({ root: globo, configFile: path.join(globo, "vite.config.ts"), server: { port: 0 }, logLevel: "error" })
await servidor.listen()
const navegador = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || (fs.existsSync("/usr/bin/chromium") ? "/usr/bin/chromium" : undefined), args: ["--no-sandbox"] })
const base = servidor.resolvedUrls.local[0]
const ausencia = { schema: "raiz.acerto.publico.v1", gerado_em: null, fonte: "Banco de aprendizado da Raíz", minimo_imoveis: 5, versoes: [] }
const versao = (versao, ae) => ({ modelo: "motor_teste", versao, alvo: "area_ha", horizonte_dias: 365, tipo: "numero", avaliacao: versao === "v1" ? "ao_vivo" : "backtest", criterio_temporal: "observacao_na_data_alvo", cronologia: versao === "v1" ? "congelada_antes_da_observacao" : "backtest_declarado", comparacoes: 12, imoveis_observados: 8, primeiro_corte: "2025-01-01", ultimo_corte: "2025-06-01", ultima_observacao: "2026-06-01", metricas: { ae, eq: ae * ae } })
try {
  for (const largura of [1440, 360]) {
    const contexto = await navegador.newContext({ viewport: { width: largura, height: 900 } })
    const pagina = await contexto.newPage()
    const erros = []
    pagina.on("pageerror", (e) => erros.push(e.message))
    pagina.on("response", (r) => { if (r.status() >= 400) erros.push(`${r.status()} ${r.url()}`) })
    await pagina.route("**/acerto/placar.json", (rota) => rota.fulfill({ json: { ...ausencia, gerado_em: "2026-11-12T12:00:00Z", versoes: [versao("v1", 0), versao("v2", 2)] } }))
    await pagina.goto(`${base}#/acerto`)
    await pagina.getByRole("heading", { name: "Acerto do modelo", exact: true }).waitFor()
    await pagina.getByText("2 grupos de comparação.", { exact: true }).waitFor()
    assert.equal(await pagina.locator(".acerto-grupo").count(), 2)
    assert((await pagina.locator(".acerto-grupo").first().innerText()).includes("Erro absoluto médio\n0"))
    await pagina.getByText("Avaliação retrospectiva", { exact: true }).waitFor()
    await pagina.getByLabel("Versão", { exact: true }).selectOption("v2")
    await pagina.getByText("1 grupo de comparação.", { exact: true }).waitFor()
    assert((await pagina.locator(".acerto-grupo").innerText()).includes("versão v2"))
    await pagina.getByRole("link", { name: "Pular para o conteúdo" }).focus()
    await pagina.keyboard.press("Enter")
    assert.equal(await pagina.locator(":focus").getAttribute("id"), "conteudo")
    await conferirPaginaAcessivel(pagina, AxeBuilder, `acerto-${largura}`, evidencias)
    assert(await pagina.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Sem rolagem horizontal")
    await pagina.screenshot({ path: path.join(evidencias, `acerto-${largura}.png`), fullPage: true })
    assert.deepEqual(erros, [])
    await pagina.unroute("**/acerto/placar.json")
    await pagina.route("**/acerto/placar.json", (rota) => rota.fulfill({ json: ausencia }))
    await pagina.reload()
    await pagina.getByText("Ainda não há comparações reais publicáveis.", { exact: true }).waitFor()
    assert.equal(await pagina.locator(".acerto-grupo").count(), 0)
    await conferirPaginaAcessivel(pagina, AxeBuilder, `acerto-ausente-${largura}`, evidencias)
    assert.deepEqual(erros, [])
    await contexto.close()
    console.log(`ok acerto por versão, zero observado, ausência, teclado, axe, ${largura}px e zero 404`)
  }
  const resposta = await fetch(new URL("acerto/placar.json", base))
  assert.equal(resposta.status, 200, "O plugin publica a ausência como JSON, sem 404")
  assert.deepEqual(await resposta.json(), ausencia)
} finally { await navegador.close(); await servidor.close(); fs.rmSync(pasta, { recursive: true, force: true }) }
