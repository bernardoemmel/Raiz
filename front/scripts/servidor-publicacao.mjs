/** Servidor de teste do artefato: sem fallback SPA, com gzip de texto e HTTP Range como na publicação. */
import fs from "node:fs"
import http from "node:http"
import path from "node:path"
import { gzipSync } from "node:zlib"

const tipos = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".geojson": "application/geo+json", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".txt": "text/plain", ".md": "text/markdown", ".png": "image/png", ".webp": "image/webp" }
export async function servirPublicacao(site, base) {
  const cache = new Map()
  const servidor = http.createServer((req, res) => {
    const caminho = decodeURIComponent(new URL(req.url, "http://localhost").pathname)
    if (!caminho.startsWith(base)) return res.writeHead(404).end()
    const relativo = caminho.slice(base.length)
    const arquivo = path.resolve(site, relativo.endsWith("/") || !relativo ? relativo + "index.html" : relativo)
    if (!arquivo.startsWith(site + path.sep) || !fs.existsSync(arquivo) || !fs.statSync(arquivo).isFile()) return res.writeHead(404).end()
    let item = cache.get(arquivo)
    if (!item) {
      const bytes = fs.readFileSync(arquivo), tipo = tipos[path.extname(arquivo)] || "application/octet-stream"
      item = { bytes, tipo, gzip: /^(text\/|application\/(json|geo\+json))|^image\/svg/.test(tipo) ? gzipSync(bytes) : null }
      cache.set(arquivo, item)
    }
    const { bytes, tipo, gzip } = item
    const headers = { "Content-Type": tipo, "Accept-Ranges": "bytes", "Cache-Control": "public, max-age=600", "Vary": "Accept-Encoding" }
    const faixa = /^bytes=(\d+)-(\d*)$/.exec(req.headers.range || "")
    if (faixa) {
      const inicio = Number(faixa[1]), fim = Math.min(Number(faixa[2] || bytes.length - 1), bytes.length - 1)
      if (inicio > fim) return res.writeHead(416, { "Content-Range": `bytes */${bytes.length}` }).end()
      res.writeHead(206, { ...headers, "Content-Range": `bytes ${inicio}-${fim}/${bytes.length}`, "Content-Length": fim - inicio + 1 })
      return res.end(bytes.subarray(inicio, fim + 1))
    }
    const comprimir = gzip && /\bgzip\b/.test(req.headers["accept-encoding"] || "")
    const corpo = comprimir ? gzip : bytes
    res.writeHead(200, { ...headers, ...(comprimir ? { "Content-Encoding": "gzip" } : {}), "Content-Length": corpo.length })
    res.end(req.method === "HEAD" ? undefined : corpo)
  })
  await new Promise((resolve) => servidor.listen(0, "127.0.0.1", resolve))
  return { url: `http://127.0.0.1:${servidor.address().port}${base}`, fechar: () => new Promise((resolve) => servidor.close(resolve)) }
}
