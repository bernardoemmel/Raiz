#!/usr/bin/env node
/** Confere a publicação para agentes e roda a categoria experimental oficial do Lighthouse.
 * O caminho RAIZ_BASE é testado sem fallback. O Lighthouse busca /llms.txt na raiz da origem:
 * sua auditoria roda em outra origem local com o site montado na raiz. Isso não comprova que
 * /robots.txt ou /llms.txt existem na raiz pública de bernardoemmel.github.io.
 * WebMCP e ARD são relatados, sem exigir recursos que o produto ainda não implementou.
 */
import assert from "node:assert/strict"
import fs from "node:fs"
import http from "node:http"
import { createRequire } from "node:module"
import path from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import { conferirAuditoriaAgentes, conferirCaminhoPublico, conferirConteudoPublico } from "./conferir-auditoria-agentes.mjs"
import { configurarPublicacao } from "./configurar-publicacao.mjs"

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const require = createRequire(path.join(repo, "front/globo/package.json"))
const { default: lighthouse } = await import(pathToFileURL(require.resolve("lighthouse")).href)
const { launch } = await import(pathToFileURL(require.resolve("chrome-launcher")).href)
const site = path.join(repo, "site")
const saida = path.join(repo, "front/.cache/teste-agentes")
const prefixo = process.env.RAIZ_BASE || "/Raiz/"
assert(prefixo.startsWith("/") && prefixo.endsWith("/"), "RAIZ_BASE precisa começar e terminar em /.")
fs.mkdirSync(saida, { recursive: true })
const tipos = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".geojson": "application/geo+json", ".svg": "image/svg+xml", ".woff2": "font/woff2",
  ".gz": "application/gzip", ".txt": "text/plain", ".md": "text/markdown; charset=utf-8" }

async function servir(naRaiz) {
  const servidor = http.createServer((req, res) => {
    const u = new URL(req.url, "http://localhost")
    const pathname = decodeURIComponent(u.pathname)
    // Na origem da auditoria, conserva também o caminho dos assets compilados para o Pages.
    const relativo = pathname.startsWith(prefixo) ? pathname.slice(prefixo.length) : naRaiz ? pathname.slice(1) : null
    if (relativo === null) return res.writeHead(404).end()
    const arquivo = path.resolve(site, relativo.endsWith("/") || !relativo ? relativo + "index.html" : relativo)
    if (!arquivo.startsWith(site + path.sep) || !fs.existsSync(arquivo) || !fs.statSync(arquivo).isFile())
      return res.writeHead(404).end()
    const bytes = fs.readFileSync(arquivo)
    const headers = { "Content-Type": tipos[path.extname(arquivo)] || "application/octet-stream", "Accept-Ranges": "bytes" }
    const faixa = /^bytes=(\d+)-(\d*)$/.exec(req.headers.range || "")
    if (faixa) {
      const inicio = Number(faixa[1]), fim = Math.min(Number(faixa[2] || bytes.length - 1), bytes.length - 1)
      if (inicio > fim) return res.writeHead(416, { "Content-Range": `bytes */${bytes.length}` }).end()
      res.writeHead(206, { ...headers, "Content-Range": `bytes ${inicio}-${fim}/${bytes.length}`, "Content-Length": fim - inicio + 1 })
      return res.end(bytes.subarray(inicio, fim + 1))
    }
    res.writeHead(200, { ...headers, "Content-Length": bytes.length })
    res.end(req.method === "HEAD" ? undefined : bytes)
  })
  await new Promise((resolve) => servidor.listen(0, "127.0.0.1", resolve))
  return { servidor, origem: `http://127.0.0.1:${servidor.address().port}` }
}

const pages = await servir(false)
const auditoria = await servir(true)
let chrome
try {
  const lidos = new Map()
  async function ler(caminho) {
    const url = new URL(caminho, pages.origem + prefixo)
    assert.equal(url.origin, pages.origem, "A checagem não deve buscar páginas externas.")
    conferirCaminhoPublico(url.pathname, caminho)
    if (lidos.has(url.href)) return lidos.get(url.href)
    const r = await fetch(url)
    assert.equal(r.status, 200, `${url.pathname} precisa responder HTTP 200.`)
    const texto = await r.text()
    if (url.pathname.endsWith(".md")) {
      assert.match(r.headers.get("content-type") || "", /text\/markdown/, `${url.pathname}: tipo incorreto.`)
      assert.match(texto, /^# .+/m, `${url.pathname} precisa conter Markdown, sem fallback HTML.`)
      assert(!/<html\b/i.test(texto), `${url.pathname} retornou HTML.`)
    }
    if (/\.(md|txt)$/.test(url.pathname)) conferirConteudoPublico(texto, url.pathname)
    lidos.set(url.href, texto)
    return texto
  }
  const llms = await ler("llms.txt")
  assert(Buffer.byteLength(llms) <= 8192, "llms.txt precisa ter no máximo 8 KB.")
  assert.match(llms, /^# .+/m)
  assert.match(llms, /\[.+?\]\(.+?\)/)
  assert.match(llms, /cr[eé]ditos?\s+pagos?/i, "llms.txt precisa explicar que fichas completas exigem créditos pagos.")
  const robots = await ler("robots.txt")
  assert.match(robots, /User-agent:\s*\*[\s\S]*?Allow:\s*\//i)
  assert(!/^Disallow:\s*\/\s*$/mi.test(robots), "robots.txt não pode bloquear toda a publicação.")
  for (const nome of ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-User", "PerplexityBot", "Google-Extended", "Applebot-Extended", "CCBot"])
    assert.match(robots, new RegExp(`User-agent:\\s*${nome}\\s*$`, "mi"), `Falta ${nome} no robots.txt.`)

  for (const pagina of ["index.html", "produtor/index.html"]) {
    const html = await ler(pagina)
    if (process.env.RAIZ_DOMINIO) {
      const { siteUrl, dominio } = configurarPublicacao(process.env)
      assert.equal((await ler("CNAME")).trim(), dominio)
      const canonico = new URL(pagina === "index.html" ? "" : "produtor/", siteUrl).href
      assert(html.includes(`<link rel="canonical" href="${canonico}"`), `${pagina}: URL canônica fora do domínio configurado.`)
    }
    const link = [...html.matchAll(/<link\b[^>]*>/gi)].map((m) => m[0]).find((l) => /rel=["']alternate["']/i.test(l) && /type=["']text\/markdown["']/i.test(l))
    assert(link, `${pagina} precisa anunciar sua versão Markdown.`)
    const href = /href=["']([^"']+)["']/i.exec(link)?.[1]
    assert(href, `${pagina}: link alternate sem endereço.`)
    await ler(new URL(href, pages.origem + prefixo + pagina).href)
  }
  for (const arquivo of ["index.md", "produtor/index.md", "servico.md", "privacidade.md", "fontes.md", "dados/index.md"])
    await ler(arquivo)
  const fichaGeral = await ler("produtor/index.md")
  assert.match(fichaGeral, /cr[eé]ditos?\s+pagos?/i, "A página geral da ficha deve explicar o acesso com créditos pagos.")
  assert.match(fichaGeral, /autentica|sess[aã]o|conta|[aá]rea de clientes/i,
    "A página geral da ficha deve explicar que a consulta depende de autenticação.")

  // Percorre todos os links Markdown locais anunciados pelo llms e pelo catálogo, incluindo municípios.
  const fila = [new URL("llms.txt", pages.origem + prefixo).href, ...lidos.keys()].filter((u) => u.endsWith(".md") || u.endsWith("llms.txt"))
  const visitados = new Set()
  while (fila.length) {
    const url = fila.shift()
    if (visitados.has(url)) continue
    visitados.add(url)
    const conteudo = await ler(url)
    for (const [, destino] of conteudo.matchAll(/\[[^\]]*\]\(([^\s)]+)\)/g)) {
      const alvo = new URL(destino, url)
      if (alvo.origin === pages.origem && alvo.pathname.endsWith(".md")) fila.push(alvo.href)
    }
  }

  const html = await ler("index.html")
  const scripts = [...html.matchAll(/<script\b[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi)]
  assert(scripts.length, "O HTML precisa entregar JSON-LD sem executar JavaScript.")
  const objetos = []
  function percorrer(valor) {
    if (!valor || typeof valor !== "object") return
    if (!Array.isArray(valor)) objetos.push(valor)
    for (const filho of Object.values(valor)) percorrer(filho)
  }
  for (const [, json] of scripts) {
    const schema = JSON.parse(json)
    conferirConteudoPublico(json, "JSON-LD")
    assert.equal(schema["@context"], "https://schema.org", "JSON-LD precisa declarar o contexto schema.org.")
    percorrer(schema)
  }
  const comTipo = (tipo) => objetos.filter((o) => (Array.isArray(o["@type"]) ? o["@type"] : [o["@type"]]).includes(tipo))
  for (const tipo of ["Dataset", "Service", "Offer"]) assert(comTipo(tipo).length, `Falta schema.org/${tipo}. Use o build com dados de teste no CI.`)
  for (const dataset of comTipo("Dataset")) {
    assert(dataset.name && dataset.description && dataset.url, "Dataset sem identificação e contexto.")
    for (const arquivo of dataset.distribution || []) {
      const caminho = new URL(arquivo.contentUrl).pathname
      conferirCaminhoPublico(caminho, "Dataset.distribution")
      assert.match(path.basename(caminho), /^resumo_[A-Z]{2}\.csv\.gz$/,
        "O Dataset público deve anunciar somente resumos agregados por estado.")
      const r = await fetch(pages.origem + caminho, { method: "HEAD" })
      assert.equal(r.status, 200, `Download anunciado no Dataset não existe: ${caminho}`)
    }
  }
  console.log(`ok: HTTP 200 em llms.txt, robots.txt e ${visitados.size - 1} documentos Markdown; alternates e Dataset/Service/Offer válidos.`)

  let chromePath = process.env.CHROME_PATH || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
  if (!chromePath) {
    try { chromePath = require("playwright").chromium.executablePath() } catch { /* chrome-launcher encontra o Chrome instalado */ }
  }
  chrome = await launch({ chromePath, chromeFlags: ["--headless", "--no-sandbox", "--disable-dev-shm-usage", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] })
  const resultado = await lighthouse(auditoria.origem + "/", {
    port: chrome.port, onlyCategories: ["agentic-browsing"], output: ["json", "html"], logLevel: "error",
    formFactor: "desktop", screenEmulation: { mobile: false, width: 1440, height: 900, deviceScaleFactor: 1, disabled: false },
    throttlingMethod: "provided", locale: "pt-BR",
  })
  assert(resultado, "O Lighthouse não entregou um resultado.")
  const { lhr, report } = resultado
  fs.writeFileSync(path.join(saida, "lighthouse.json"), report[0])
  fs.writeFileSync(path.join(saida, "lighthouse.html"), report[1])
  const categoria = conferirAuditoriaAgentes(lhr)
  const resumo = {
    lighthouse: lhr.lighthouseVersion, navegador: lhr.environment.hostUserAgent,
    categoria: categoria.id, score: categoria.score,
    portao: { acessibilidade: 1, llms_txt: 1, cls_maximo: 0.1, nota_cls_minima: 0.9 },
    auditorias: categoria.auditRefs.map(({ id }) => ({ id, score: lhr.audits[id].score, modo: lhr.audits[id].scoreDisplayMode })),
    escopo: `Arquivos e links conferidos sob ${prefixo}. Lighthouse executado em origem local com site na raiz; não comprova DNS ou a descoberta na origem pública. WebMCP e ARD apenas relatados.`,
  }
  fs.writeFileSync(path.join(saida, "resumo.json"), JSON.stringify(resumo, null, 2) + "\n")
  console.log(`ok: Lighthouse ${lhr.lighthouseVersion}, categoria experimental agentic-browsing, acessibilidade e llms-txt aprovados, CLS até 0,1 e nenhum erro de execução.`)
  console.log(resumo.escopo)
} finally {
  await chrome?.kill()
  await Promise.all([pages, auditoria].map(({ servidor }) => new Promise((resolve) => servidor.close(resolve))))
}
