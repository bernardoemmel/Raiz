/**
 * Plugin do Vite que serve os dados da amostra para as telas, como se fosse a API:
 *
 *   /amostra/indice.json             lista dos arquivos de dados/amostra/ (um arquivo novo do motor aparece sozinho)
 *   /amostra/<arquivo>.csv           os CSV do motor, como estão
 *   /amostra/fichas/<cod>.json       a ficha leve de uma fazenda (dados/ficha.ts), montada aqui
 *   /geo/<arquivo>                   o que front/scripts/geo.py gerou (GeoJSON e PMTiles, com Range)
 *   /geo/fontes/<fonte>/<faixa>.pbf  letras dos rótulos do mapa
 *
 * No `vite build`, copia tudo para dist/ e grava uma ficha por fazenda. Sem dependência de pacote: os tipos do Vite
 * ficam de fora para este arquivo poder morar fora dos projetos.
 */

import fs from "node:fs"
import path from "node:path"
import { complementosDe, juntarComplementos } from "./dados/complementos"
import { lerCsv } from "./dados/csv"
import { baseDoMunicipio, montarFicha, type BaseMunicipio } from "./dados/ficha"
import { lerImovel } from "./dados/funil"
import type { Geo, Imovel } from "./dados/tipos"

interface Requisicao {
  url?: string
  headers: Record<string, string | string[] | undefined>
}
interface Resposta {
  statusCode: number
  setHeader(nome: string, valor: string | number): void
  end(dado?: string | Buffer): void
}
type Proximo = () => void
interface Servidor {
  middlewares: { use(fn: (req: Requisicao, res: Resposta, next: Proximo) => void): void }
}

const TIPOS: Record<string, string> = {
  ".csv": "text/csv; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".geojson": "application/geo+json; charset=utf-8",
  ".pmtiles": "application/octet-stream",
  ".pbf": "application/x-protobuf",
}

export function dadosRaiz(opcoes: { repo: string }) {
  const amostra = path.join(opcoes.repo, "dados", "amostra")
  const geo = path.join(opcoes.repo, "front", "geo")
  let saida = "dist"
  // o Vite chama closeBundle também ao fechar o servidor (e o Vitest fecha um no fim): só grava no vite build
  let construindo = false

  const listar = (dir: string) =>
    fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => fs.statSync(path.join(dir, f)).isFile()) : []

  // imóveis por município, lidos uma vez e relidos se o arquivo mudar
  const cache = new Map<
    string,
    { mtime: number; imoveis: Imovel[]; base: BaseMunicipio; geo: Map<string, Geo["features"][number]> }
  >()

  function municipio(cod: string) {
    const arq = path.join(amostra, `imoveis_${cod}.csv`)
    if (!fs.existsSync(arq)) return null
    const mtime = fs.statSync(arq).mtimeMs
    const ja = cache.get(cod)
    if (ja && ja.mtime === mtime) return ja
    const nomes = complementosDe(listar(amostra), cod)
    const { porImovel, avisos } = juntarComplementos(
      nomes.map((arquivo) => ({ arquivo, linhas: lerCsv(fs.readFileSync(path.join(amostra, arquivo), "utf8")).linhas })),
    )
    if (avisos.length) console.warn("raiz-dados: arquivos que não entraram:", avisos.join("; "))
    const imoveis = lerCsv(fs.readFileSync(arq, "utf8"))
      .linhas.filter((l) => l.cod_imovel)
      .map((l) => lerImovel(l, porImovel.get(l.cod_imovel)))
    const feicoes = new Map<string, Geo["features"][number]>()
    const g = path.join(geo, `imoveis_${cod}.geojson`)
    if (fs.existsSync(g)) {
      for (const f of (JSON.parse(fs.readFileSync(g, "utf8")) as Geo).features)
        feicoes.set(String(f.properties.cod_imovel), f)
    }
    const item = { mtime, imoveis, base: baseDoMunicipio(imoveis), geo: feicoes }
    cache.set(cod, item)
    return item
  }

  const comImoveis = () =>
    listar(amostra)
      .filter((f) => /^imoveis_\d{7}\.csv$/.test(f))
      .map((f) => f.slice(8, -4))

  function ficha(cod_imovel: string) {
    for (const cod of comImoveis()) {
      const m = municipio(cod)
      const alvo = m?.imoveis.find((i) => i.cod_imovel === cod_imovel)
      if (m && alvo) return montarFicha(alvo, m.imoveis, m.geo.get(cod_imovel), m.base)
    }
    return null
  }

  function enviarArquivo(req: Requisicao, res: Resposta, arq: string) {
    const tamanho = fs.statSync(arq).size
    res.setHeader("Content-Type", TIPOS[path.extname(arq)] ?? "application/octet-stream")
    res.setHeader("Accept-Ranges", "bytes")
    res.setHeader("Cache-Control", "no-cache")
    const faixa = /bytes=(\d*)-(\d*)/.exec(String(req.headers.range ?? ""))
    if (faixa) {
      const ini = faixa[1] ? Number(faixa[1]) : tamanho - Number(faixa[2])
      const fim = faixa[1] && faixa[2] ? Math.min(Number(faixa[2]), tamanho - 1) : tamanho - 1
      res.statusCode = 206
      res.setHeader("Content-Range", `bytes ${ini}-${fim}/${tamanho}`)
      res.setHeader("Content-Length", fim - ini + 1)
      const buf = Buffer.alloc(fim - ini + 1)
      const fd = fs.openSync(arq, "r")
      fs.readSync(fd, buf, 0, buf.length, ini)
      fs.closeSync(fd)
      res.end(buf)
      return
    }
    res.setHeader("Content-Length", tamanho)
    res.end(fs.readFileSync(arq))
  }

  function json(res: Resposta, dado: unknown) {
    res.setHeader("Content-Type", "application/json; charset=utf-8")
    res.setHeader("Cache-Control", "no-cache")
    res.end(JSON.stringify(dado))
  }

  function naoAchou(res: Resposta) {
    res.statusCode = 404
    res.setHeader("Content-Type", "application/json; charset=utf-8")
    res.end('{"erro":"não encontrado"}')
  }

  // só nomes simples de arquivo: nada de ../
  const seguro = (nome: string) => /^[\w.-]+$/.test(nome) && !nome.startsWith(".")

  return {
    name: "raiz-dados",
    configResolved(config: { root: string; command: string; build: { outDir: string } }) {
      saida = path.resolve(config.root, config.build.outDir)
      construindo = config.command === "build"
    },
    configureServer(server: Servidor) {
      server.middlewares.use((req, res, next) => {
        const url = decodeURIComponent((req.url ?? "").split("?")[0])
        let m: RegExpExecArray | null
        if (url === "/amostra/indice.json") return json(res, { arquivos: listar(amostra).filter((f) => f.endsWith(".csv")) })
        if ((m = /^\/amostra\/fichas\/([\w-]+)\.json$/.exec(url))) {
          const f = ficha(m[1])
          return f ? json(res, f) : naoAchou(res)
        }
        if ((m = /^\/amostra\/([^/]+)$/.exec(url))) {
          const arq = path.join(amostra, m[1])
          return seguro(m[1]) && fs.existsSync(arq) ? enviarArquivo(req, res, arq) : naoAchou(res)
        }
        if ((m = /^\/geo\/fontes\/([\w ]+)\/(\d+-\d+)\.pbf$/.exec(url))) {
          const arq = path.join(geo, "fontes", m[1], `${m[2]}.pbf`)
          return fs.existsSync(arq) ? enviarArquivo(req, res, arq) : naoAchou(res)
        }
        if ((m = /^\/geo\/([^/]+)$/.exec(url))) {
          const arq = path.join(geo, m[1])
          return seguro(m[1]) && fs.existsSync(arq) ? enviarArquivo(req, res, arq) : naoAchou(res)
        }
        next()
      })
    },
    closeBundle() {
      if (!construindo || !fs.existsSync(saida)) return
      const dAmostra = path.join(saida, "amostra")
      const dFichas = path.join(dAmostra, "fichas")
      fs.mkdirSync(dFichas, { recursive: true })
      const csvs = listar(amostra).filter((f) => f.endsWith(".csv"))
      for (const f of csvs) fs.copyFileSync(path.join(amostra, f), path.join(dAmostra, f))
      fs.writeFileSync(path.join(dAmostra, "indice.json"), JSON.stringify({ arquivos: csvs }))
      let n = 0
      for (const cod of comImoveis()) {
        const m = municipio(cod)
        if (!m) continue
        for (const i of m.imoveis) {
          fs.writeFileSync(
            path.join(dFichas, `${i.cod_imovel}.json`),
            JSON.stringify(montarFicha(i, m.imoveis, m.geo.get(i.cod_imovel), m.base)),
          )
          n++
        }
      }
      const dGeo = path.join(saida, "geo")
      fs.mkdirSync(dGeo, { recursive: true })
      for (const f of listar(geo)) fs.copyFileSync(path.join(geo, f), path.join(dGeo, f))
      if (fs.existsSync(path.join(geo, "fontes")))
        fs.cpSync(path.join(geo, "fontes"), path.join(dGeo, "fontes"), { recursive: true })
      console.log(`raiz-dados: ${csvs.length} CSV, ${n} fichas e ${listar(geo).length} arquivos de geometria em ${saida}`)
    },
  }
}
