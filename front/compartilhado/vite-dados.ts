/**
 * Publicação aberta do mapa: somente resumos por município, pontos agregados e mapa base.
 * Fichas, CAR, CSV por imóvel e geometrias das fazendas ficam na API autenticada de prospecção.
 * A mesma regra vale no servidor de desenvolvimento e no build estático.
 */

import fs from "node:fs"
import path from "node:path"
import zlib from "node:zlib"
import { buscar } from "./dados/busca"
import { escreverCsv, lerCsv } from "./dados/csv"
import { lerFunil } from "./dados/funil"
import { UFS } from "./formato"
import { abrirPasta, nomeSeguro, pastaPadrao } from "./pasta-dados"
import { paginasAgentes } from "./paginas-agentes"
import { projetarPublicacaoLote } from "./pedidos/release"

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
  ".gz": "application/gzip",
}

/** repo: raiz do repositório; raizDados e cache só para teste (o normal é ler RAIZ_DADOS do ambiente ou do .env) */
export function dadosRaiz(opcoes: { repo: string; raizDados?: string | null; cache?: string }) {
  const geo = path.resolve(opcoes.repo, process.env.RAIZ_GEO || "front/geo")
  const lotes = path.resolve(opcoes.repo, process.env.RAIZ_LOTES || "dados/lotes")
  function lotePublicado() {
    const arquivo = path.join(lotes, "lote_PA_central_r11.json")
    return projetarPublicacaoLote(fs.existsSync(arquivo) ? JSON.parse(fs.readFileSync(arquivo, "utf8")) : null)
  }
  const pasta = abrirPasta({
    repo: opcoes.repo,
    raizDados: opcoes.raizDados !== undefined ? opcoes.raizDados : pastaPadrao(opcoes.repo),
    cache: opcoes.cache,
    geo,
  })
  const resumoPermitido = (nome: string) => /^resumo_[A-Z]{2}\.csv$/.test(nome)
  const arquivosPublicos = (uf: string) => pasta.arquivos(uf).filter(resumoPermitido)
  const estadosPublicos = () => {
    const estados = pasta.estados()
    return { ...estados, acesso: "agregado" as const, estados: estados.estados.map((e) => ({ ...e, com_lista: [] })) }
  }
  const colunasResumo = new Set([
    "cod_ibge", "municipio", "imoveis", "sem_problema", "def_RL", "aptas_carbono", "ha_carbono",
    "tco2_ano_aptas", "aptas_com_matricula", "ha_carbono_matricula", "cota_reserva", "redd_imoveis", "redd_ha",
    "app_imoveis", "app_ha", "frigorifico_imoveis", "frigorifico_ha", "compensacao_ha", "eudr_ok",
    "credito_rural_ok", "compra_arrendamento", "alerta_pos2020_imoveis", "frente_regularizar_antes", "frente_carbono",
    "frente_silvipastoril", "frente_desbloqueio", "frente_carbono_revisar_desm10anos", "frente_assentamento_agrupado",
    "frente_carbono_so_plantio", "frente_fora_TI", "frente_ja_tem_projeto",
  ])
  function resumoPublico(nome: string): string | null {
    if (!resumoPermitido(nome)) return null
    const t = pasta.csvLimpo(nome)
    if (t === null) return null
    const { colunas, linhas } = lerCsv(t)
    const permitidas = colunas.filter((c) => colunasResumo.has(c))
    return escreverCsv([...permitidas, "dados_suprimidos"], linhas.map((linha) => {
      const n = Number(linha.imoveis)
      const suprimir = !Number.isFinite(n) || n < 5
      return Object.fromEntries([
        ...permitidas.map((c) => [c, suprimir && c !== "cod_ibge" && c !== "municipio" ? "" : linha[c]]),
        ["dados_suprimidos", String(suprimir)],
      ])
    }))
  }
  const geoPermitido = (nome: string) => /^(brasil_(municipios|estados)\.geojson|municipio_\d{7}\.geojson(?:\.gz)?|base_(brasil|[A-Z]{2}|\d{7})\.pmtiles)$/.test(nome)
  function indiceGeoPublico() {
    const municipios: Record<string, Record<string, { arquivo: string; bytes: number }>> = {}
    const brasil: Record<string, { arquivo: string; bytes: number }> = {}
    const indice = path.join(geo, "indice.json")
    // Preserva bases compartilhadas por UF e os caminhos gzip do manifesto do mapa, retirando camadas privadas.
    if (fs.existsSync(indice)) {
      const origem = JSON.parse(fs.readFileSync(indice, "utf8"))
      const item = (valor: { arquivo?: unknown } | undefined) => {
        const arquivo = valor?.arquivo
        return typeof arquivo === "string" && nomeSeguro(arquivo) && geoPermitido(arquivo) && fs.existsSync(path.join(geo, arquivo))
          ? { arquivo, bytes: fs.statSync(path.join(geo, arquivo)).size } : null
      }
      for (const chave of ["municipios", "estados", "base"]) {
        const dado = item(origem.brasil?.[chave])
        if (dado) brasil[chave] = dado
      }
      for (const [cod, camadas] of Object.entries(origem.municipios ?? {})) {
        if (!/^\d{7}$/.test(cod)) continue
        for (const chave of ["municipio", "base"]) {
          const dado = item((camadas as Record<string, { arquivo?: unknown }>)[chave])
          if (dado) (municipios[cod] ??= {})[chave] = dado
        }
      }
      return { brasil, municipios }
    }
    // Compatibilidade com pastas antigas, antes do manifesto: só limites e bases com nome conhecido.
    for (const arquivo of listar(geo).filter(geoPermitido)) {
      const item = { arquivo, bytes: fs.statSync(path.join(geo, arquivo)).size }
      const m = /^(municipio|base)_(\d{7})\./.exec(arquivo)
      if (m) (municipios[m[2]] ??= {})[m[1]] = item
      else if (arquivo.startsWith("brasil_") || arquivo === "base_brasil.pmtiles")
        brasil[arquivo === "base_brasil.pmtiles" ? "base" : arquivo.includes("municipios") ? "municipios" : "estados"] = item
    }
    return { brasil, municipios }
  }
  function arquivosGeo() {
    const indice = indiceGeoPublico()
    return [...new Set([...Object.values(indice.brasil), ...Object.values(indice.municipios).flatMap(Object.values)].map((item) => item.arquivo))]
  }
  let saida = "dist"
  let base = "/"
  let produtor = false
  // o Vite chama closeBundle também ao fechar o servidor (e o Vitest fecha um no fim): só grava no vite build
  let construindo = false

  /** CSV limpo e comprimido, guardado enquanto o arquivo não muda (os mais recentes) */
  const gz = new Map<string, { mtime: number; dado: Buffer }>()
  function csvComprimido(nome: string): Buffer | null {
    const arq = resumoPermitido(nome) ? pasta.caminho(nome) : null
    if (!arq) return null
    const mtime = fs.statSync(arq).mtimeMs
    const ja = gz.get(nome)
    if (ja && ja.mtime === mtime) return ja.dado
    const dado = zlib.gzipSync(resumoPublico(nome) ?? "", { level: 6 })
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
    configResolved(config: { root: string; command: string; base?: string; build: { outDir: string }; env?: Record<string, unknown> }) {
      if (config.command === "build" && ["VITE_RAIZ_TOKEN", "VITE_RAIZ_API_TOKEN"].some((chave) => config.env?.[chave] || process.env[chave])) {
        throw new Error("VITE_RAIZ_TOKEN e VITE_RAIZ_API_TOKEN não podem entrar no site. Use a sessão de cliente na API de prospecção.")
      }
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
        // O Vite também pode servir arquivos por /@fs: os dados de origem nunca passam por esse caminho.
        const arquivoDireto = url.startsWith("/@fs/") ? path.resolve(url.slice(4)) : path.resolve(opcoes.repo, `.${url}`)
        const emPasta = (dir: string) => arquivoDireto === dir || arquivoDireto.startsWith(dir + path.sep)
        if (emPasta(pasta.dir) || emPasta(path.join(opcoes.repo, "dados")) || emPasta(path.join(opcoes.repo, "motor", "saida"))) return naoAchou(res)
        if (emPasta(geo) || emPasta(lotes)) return naoAchou(res)
        if (url === "/busca") {
          const q = new URLSearchParams((req.url ?? "").split("?")[1] ?? "").get("q") ?? ""
          const resultado = buscar(q, { municipios: pasta.municipios(), imoveis: [], comImoveis: new Set() })
          return json(req, res, { ...resultado, municipios: resultado.municipios.map((m) => ({ ...m, imoveis: m.imoveis === null || m.imoveis < 5 ? null : m.imoveis })) })
        }
        if (url === "/amostra/estados.json") return json(req, res, estadosPublicos())
        if (url === "/amostra/lote_PA_central_r11.json") return json(req, res, lotePublicado())
        if ((m = /^\/amostra\/indice_([A-Z]{2})\.json$/.exec(url))) return json(req, res, { uf: m[1], arquivos: arquivosPublicos(m[1]) })
        if ((m = /^\/amostra\/pontos_([A-Z]{2})\.json$/.exec(url))) {
          pasta.pontosPublicos(m[1]).then((t) => (t ? json(req, res, t) : naoAchou(res)), falhou)
          return
        }
        if (/^\/amostra\/(car_|fichas\/)/.test(url)) return naoAchou(res)
        if ((m = /^\/amostra\/([^/]+\.csv)\.gz$/.exec(url))) {
          const dado = csvComprimido(m[1])
          if (!dado) return naoAchou(res)
          res.setHeader("Content-Type", "application/gzip")
          res.setHeader("Cache-Control", "no-cache")
          res.setHeader("Content-Length", dado.length)
          return res.end(dado)
        }
        if ((m = /^\/amostra\/([^/]+\.csv)$/.exec(url))) {
          const t = resumoPublico(m[1])
          return t !== null ? texto(req, res, t, TIPOS[".csv"]) : naoAchou(res)
        }
        if ((m = /^\/geo\/fontes\/([\w ]+)\/(\d+-\d+)\.pbf$/.exec(url))) {
          const arq = path.join(geo, "fontes", m[1], `${m[2]}.pbf`)
          return fs.existsSync(arq) ? enviarArquivo(req, res, arq) : naoAchou(res)
        }
        if (url === "/geo/indice.json") return json(req, res, indiceGeoPublico())
        if ((m = /^\/geo\/([^/]+)$/.exec(url))) {
          const arq = path.join(geo, m[1])
          return nomeSeguro(m[1]) && arquivosGeo().includes(m[1]) && fs.existsSync(arq) ? enviarArquivo(req, res, arq) : naoAchou(res)
        }
        next()
      })
    },
    async closeBundle() {
      if (!construindo || !fs.existsSync(saida)) return
      const comDados = !produtor && process.env.RAIZ_BUILD_DADOS !== "0"
      // Markdown e JSON-LD recebem exatamente o mesmo recorte público, com as mesmas supressões dos CSV.
      const municipios = comDados ? pasta.ufs().flatMap((uf) =>
        arquivosPublicos(uf).flatMap((nome) => lerCsv(resumoPublico(nome) ?? "").linhas.map((linha) => lerFunil(linha, uf)))) : []
      paginasAgentes({
        saida, base, produtor, siteUrl: process.env.RAIZ_SITE_URL,
        ...(comDados ? { catalogo: { estados: estadosPublicos(), municipios, arquivos: Object.fromEntries(pasta.ufs().map((uf) => [uf, arquivosPublicos(uf)])) } } : {}),
      })
      if (!comDados) return
      const dAmostra = path.join(saida, "amostra")
      const dGeo = path.join(saida, "geo")
      // Remove a publicação anterior para nenhum arquivo individual sobreviver a um rebuild.
      fs.rmSync(dAmostra, { recursive: true, force: true })
      fs.rmSync(dGeo, { recursive: true, force: true })
      fs.mkdirSync(dAmostra, { recursive: true })
      fs.mkdirSync(dGeo, { recursive: true })
      let csvs = 0
      for (const uf of pasta.ufs()) {
        const arquivos = arquivosPublicos(uf)
        for (const f of arquivos) {
          fs.writeFileSync(path.join(dAmostra, `${f}.gz`), zlib.gzipSync(resumoPublico(f) ?? "", { level: 9 }))
          csvs++
        }
        fs.writeFileSync(path.join(dAmostra, `indice_${uf}.json`), JSON.stringify({ uf, arquivos }))
        fs.writeFileSync(path.join(dAmostra, `pontos_${uf}.json`), JSON.stringify(await pasta.pontosPublicos(uf)))
      }
      fs.writeFileSync(path.join(dAmostra, "estados.json"), JSON.stringify(estadosPublicos()))
      fs.writeFileSync(path.join(dAmostra, "lote_PA_central_r11.json"), JSON.stringify(lotePublicado()))
      fs.writeFileSync(path.join(dGeo, "indice.json"), JSON.stringify(indiceGeoPublico()))
      for (const f of arquivosGeo()) fs.copyFileSync(path.join(geo, f), path.join(dGeo, f))
      if (fs.existsSync(path.join(geo, "fontes")))
        fs.cpSync(path.join(geo, "fontes"), path.join(dGeo, "fontes"), { recursive: true })
      console.log(`raiz-dados: ${csvs} resumos municipais e mapa agregado em ${saida}; fichas completas somente na API`)

    },
  }
}
