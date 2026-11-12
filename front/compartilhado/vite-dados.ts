/**
 * Plugin do Vite que serve os dados do motor para as telas, como se fosse a API:
 *
 *   /amostra/estados.json            os 27 estados: quantos municípios o motor já processou, de quantos (lista do
 *                                    IBGE), se está completo e quais municípios têm lista por fazenda
 *   /amostra/indice_<UF>.json        os CSV de um estado (um arquivo novo do motor aparece sozinho)
 *   /amostra/<arquivo>.csv           um CSV do motor, limpo (sem coluna pessoal, CPF e CNPJ mascarados)
 *   /amostra/<arquivo>.csv.gz        o mesmo, comprimido (é como o site estático guarda; o navegador descomprime)
 *   /amostra/pontos_<UF>.json        fazendas aptas do estado como pontos (agrupamentos no mapa), com cache em disco
 *   /amostra/car_<UF>.json           códigos do CAR que estão no arquivo de outro município (código → município)
 *   /amostra/fichas/<cod>.json       a ficha leve de uma fazenda (dados/ficha.ts), montada aqui
 *   /busca?q=                        busca por código do CAR ou município (dados/busca.ts), como o back-end vai fazer
 *   /geo/<arquivo>                   o que front/scripts/geo.py gerou (GeoJSON e PMTiles, com Range)
 *   /geo/fontes/<fonte>/<faixa>.pbf  letras dos rótulos do mapa
 *
 * De onde vêm os CSV: a pasta da variável RAIZ_DADOS (no ambiente ou no .env da raiz do repositório), separada por
 * estado como o motor grava (<pasta>/<UF>/imoveis_<cod>.csv...); sem ela, dados/estados/ (o que o predev baixou do
 * Release "dados"); sem nenhuma, dados/amostra/ (ver pasta-dados.ts). As rotas são as mesmas nos três casos: o nome do
 * arquivo já diz de que estado ele é. /amostra/estados.json usa o estados.json baixado quando há.
 *
 * No `vite build`, grava os dados em dist/: CSV limpos e comprimidos (.csv.gz), estados, pontos, códigos fora do
 * município e as fichas prontas dos municípios com contorno (as outras o navegador monta dos CSV). Assim o Brasil cabe
 * num site estático (GitHub Pages: até 1 GB). RAIZ_BUILD_DADOS=0 não grava dado nenhum (a ficha do produtor no site lê
 * os do painel). Sem dependência de pacote: os tipos do Vite ficam de fora para este arquivo poder morar fora dos
 * projetos.
 */

import fs from "node:fs"
import path from "node:path"
import zlib from "node:zlib"
import { buscar } from "./dados/busca"
import { montarFicha } from "./dados/ficha"
import { funilDosImoveis } from "./dados/funil"
import { UFS } from "./formato"
import { abrirPasta, nomeSeguro, pastaPadrao } from "./pasta-dados"
import { paginasAgentes } from "./paginas-agentes"

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

/** repo: raiz do repositório; raizDados e cache só para teste (o normal é ler RAIZ_DADOS do ambiente ou do .env) */
export function dadosRaiz(opcoes: { repo: string; raizDados?: string | null; cache?: string }) {
  const pasta = abrirPasta({
    repo: opcoes.repo,
    raizDados: opcoes.raizDados !== undefined ? opcoes.raizDados : pastaPadrao(opcoes.repo),
    cache: opcoes.cache,
  })
  const geo = path.join(opcoes.repo, "front", "geo")
  let saida = "dist"
  let base = "/"
  let produtor = false
  // o Vite chama closeBundle também ao fechar o servidor (e o Vitest fecha um no fim): só grava no vite build
  let construindo = false

  /** CSV limpo e comprimido, guardado enquanto o arquivo não muda (os mais recentes) */
  const gz = new Map<string, { mtime: number; dado: Buffer }>()
  function csvComprimido(nome: string): Buffer | null {
    const arq = pasta.caminho(nome)
    if (!arq) return null
    const mtime = fs.statSync(arq).mtimeMs
    const ja = gz.get(nome)
    if (ja && ja.mtime === mtime) return ja.dado
    const dado = zlib.gzipSync(pasta.csvLimpo(nome) ?? "", { level: 6 })
    gz.set(nome, { mtime, dado })
    while (gz.size > 40) gz.delete(gz.keys().next().value!)
    return dado
  }

  const listar = (dir: string) =>
    fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => fs.statSync(path.join(dir, f)).isFile()) : []

  // GeoJSON e JSON grandes vão comprimidos (o contorno dos municípios do Brasil cai de 3,8 MB para perto de 1 MB)
  const comprimidos = new Map<string, { mtime: number; dado: Buffer }>()
  function enviarComprimido(req: Requisicao, res: Resposta, arq: string): boolean {
    const aceita = String(req.headers["accept-encoding"] ?? "")
    if (!/\bgzip\b/.test(aceita) || !/\.(geo)?json$/.test(arq) || req.headers.range) return false
    const mtime = fs.statSync(arq).mtimeMs
    let item = comprimidos.get(arq)
    if (!item || item.mtime !== mtime) {
      item = { mtime, dado: zlib.gzipSync(fs.readFileSync(arq), { level: 6 }) }
      comprimidos.set(arq, item)
    }
    res.setHeader("Content-Type", TIPOS[path.extname(arq)] ?? "application/octet-stream")
    res.setHeader("Content-Encoding", "gzip")
    res.setHeader("Vary", "Accept-Encoding")
    res.setHeader("Cache-Control", "no-cache")
    res.setHeader("Content-Length", item.dado.length)
    res.end(item.dado)
    return true
  }

  function enviarArquivo(req: Requisicao, res: Resposta, arq: string) {
    if (enviarComprimido(req, res, arq)) return
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

  function texto(req: Requisicao, res: Resposta, conteudo: string, tipo: string) {
    res.setHeader("Content-Type", tipo)
    res.setHeader("Cache-Control", "no-cache")
    if (conteudo.length > 20_000 && /\bgzip\b/.test(String(req.headers["accept-encoding"] ?? ""))) {
      const dado = zlib.gzipSync(conteudo, { level: 6 })
      res.setHeader("Content-Encoding", "gzip")
      res.setHeader("Vary", "Accept-Encoding")
      res.setHeader("Content-Length", dado.length)
      return res.end(dado)
    }
    res.end(conteudo)
  }

  const json = (req: Requisicao, res: Resposta, dado: unknown) =>
    texto(req, res, typeof dado === "string" ? dado : JSON.stringify(dado), "application/json; charset=utf-8")

  function naoAchou(res: Resposta) {
    res.statusCode = 404
    res.setHeader("Content-Type", "application/json; charset=utf-8")
    res.end('{"erro":"não encontrado"}')
  }

  return {
    name: "raiz-dados",
    configResolved(config: { root: string; command: string; base?: string; build: { outDir: string } }) {
      saida = path.resolve(config.root, config.build.outDir)
      construindo = config.command === "build"
      produtor = path.basename(config.root) === "produtor"
      base = produtor ? (process.env.RAIZ_BASE || "/Raiz/") : (config.base || "/")
    },
    configureServer(server: Servidor) {
      const ufs = pasta.ufs()
      console.log(
        pasta.modo === "amostra"
          ? `raiz-dados: dados/amostra (${ufs.join(", ") || "vazia"}). Sem dados publicados em dados/estados (o predev baixa sozinho quando há internet)`
          : `raiz-dados: ${path.relative(opcoes.repo, pasta.dir) || pasta.dir} (${ufs.length} estado(s): ${ufs.join(", ") || "nenhum"})`,
      )
      // os pontos de cada estado ficam prontos em segundo plano: o primeiro toque num estado já acha o cache
      const aquecer = setTimeout(
        () =>
          pasta
            .aquecer((uf, seg) => console.log(`raiz-dados: pontos ${UFS[uf] ?? uf} prontos (${seg.toFixed(1).replace(".", ",")} s)`))
            .catch((e: Error) => console.warn("raiz-dados: pontos não montaram: " + e.message)),
        1500,
      )
      aquecer.unref?.()
      server.middlewares.use((req, res, next) => {
        const url = decodeURIComponent((req.url ?? "").split("?")[0])
        let m: RegExpExecArray | null
        const falhou = (e: Error) => {
          res.statusCode = 500
          res.end(JSON.stringify({ erro: e.message }))
        }
        if (url === "/busca") {
          const q = new URLSearchParams((req.url ?? "").split("?")[1] ?? "").get("q") ?? ""
          pasta.baseBusca(q).then((base) => json(req, res, buscar(q, base)), falhou)
          return
        }
        if (url === "/amostra/estados.json") return json(req, res, pasta.estados())
        if ((m = /^\/amostra\/indice_([A-Z]{2})\.json$/.exec(url))) return json(req, res, { uf: m[1], arquivos: pasta.arquivos(m[1]) })
        if ((m = /^\/amostra\/pontos_([A-Z]{2})\.json$/.exec(url))) {
          pasta.pontosTexto(m[1]).then((t) => (t ? json(req, res, t) : naoAchou(res)), falhou)
          return
        }
        if ((m = /^\/amostra\/car_([A-Z]{2})\.json$/.exec(url))) {
          pasta.foraDoMunicipio(m[1]).then((t) => json(req, res, t), falhou)
          return
        }
        if ((m = /^\/amostra\/fichas\/([\w-]+)\.json$/.exec(url))) {
          pasta.ficha(m[1]).then((f) => (f ? json(req, res, f) : naoAchou(res)), falhou)
          return
        }
        if ((m = /^\/amostra\/([^/]+\.csv)\.gz$/.exec(url))) {
          const dado = csvComprimido(m[1])
          if (!dado) return naoAchou(res)
          res.setHeader("Content-Type", "application/gzip")
          res.setHeader("Cache-Control", "no-cache")
          res.setHeader("Content-Length", dado.length)
          return res.end(dado)
        }
        if ((m = /^\/amostra\/([^/]+\.csv)$/.exec(url))) {
          const t = pasta.csvLimpo(m[1])
          return t !== null ? texto(req, res, t, TIPOS[".csv"]) : naoAchou(res)
        }
        if ((m = /^\/geo\/fontes\/([\w ]+)\/(\d+-\d+)\.pbf$/.exec(url))) {
          const arq = path.join(geo, "fontes", m[1], `${m[2]}.pbf`)
          return fs.existsSync(arq) ? enviarArquivo(req, res, arq) : naoAchou(res)
        }
        if ((m = /^\/geo\/([^/]+)$/.exec(url))) {
          const arq = path.join(geo, m[1])
          return nomeSeguro(m[1]) && fs.existsSync(arq) ? enviarArquivo(req, res, arq) : naoAchou(res)
        }
        next()
      })
    },
    async closeBundle() {
      if (!construindo || !fs.existsSync(saida)) return
      const comDados = !produtor && process.env.RAIZ_BUILD_DADOS !== "0"
      const municipios = comDados ? pasta.municipios() : []
      if (comDados) {
        const conhecidos = new Set(municipios.map((m) => m.cod_ibge))
        for (const uf of pasta.ufs()) {
          for (const cod of pasta.comImoveis(uf)) {
            if (conhecidos.has(cod)) continue
            const m = pasta.municipio(cod)
            if (m) municipios.push(funilDosImoveis(m.imoveis, cod, m.imoveis[0]?.municipio || cod, uf))
          }
        }
      }
      paginasAgentes({
        saida, base, produtor, siteUrl: process.env.RAIZ_SITE_URL,
        ...(comDados ? { catalogo: { estados: pasta.estados(), municipios, arquivos: Object.fromEntries(pasta.ufs().map((uf) => [uf, pasta.arquivos(uf)])) } } : {}),
      })
      if (!comDados) return
      const dAmostra = path.join(saida, "amostra")
      const dFichas = path.join(dAmostra, "fichas")
      fs.mkdirSync(dFichas, { recursive: true })
      let csvs = 0
      let n = 0
      for (const uf of pasta.ufs()) {
        const arquivos = pasta.arquivos(uf)
        for (const f of arquivos) {
          fs.writeFileSync(path.join(dAmostra, `${f}.gz`), zlib.gzipSync(pasta.csvLimpo(f) ?? "", { level: 9 }))
          csvs++
        }
        fs.writeFileSync(path.join(dAmostra, `indice_${uf}.json`), JSON.stringify({ uf, arquivos }))
        fs.writeFileSync(path.join(dAmostra, `pontos_${uf}.json`), (await pasta.pontosTexto(uf)) ?? "")
        fs.writeFileSync(path.join(dAmostra, `car_${uf}.json`), JSON.stringify(await pasta.foraDoMunicipio(uf)))
        // ficha pronta só onde há o contorno das fazendas (as outras o navegador monta dos CSV do município)
        for (const cod of pasta.comImoveis(uf)) {
          if (!fs.existsSync(path.join(geo, `imoveis_${cod}.geojson`))) continue
          const m = pasta.municipio(cod)
          if (!m) continue
          for (const i of m.imoveis) {
            fs.writeFileSync(
              path.join(dFichas, `${i.cod_imovel}.json`),
              JSON.stringify(montarFicha(i, m.imoveis, m.geo.get(i.cod_imovel), m.base)),
            )
            n++
          }
        }
      }
      fs.writeFileSync(path.join(dAmostra, "estados.json"), JSON.stringify(pasta.estados()))
      const dGeo = path.join(saida, "geo")
      fs.mkdirSync(dGeo, { recursive: true })
      for (const f of listar(geo)) fs.copyFileSync(path.join(geo, f), path.join(dGeo, f))
      if (fs.existsSync(path.join(geo, "fontes")))
        fs.cpSync(path.join(geo, "fontes"), path.join(dGeo, "fontes"), { recursive: true })
      const de = path.relative(opcoes.repo, pasta.dir) || pasta.dir
      console.log(`raiz-dados: ${csvs} CSV de ${de}, ${n} fichas e ${listar(geo).length} arquivos de geometria em ${saida}`)
    },
  }
}
