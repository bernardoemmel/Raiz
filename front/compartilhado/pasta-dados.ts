/**
 * A pasta com os CSV do motor, lida por estado. Só roda no Node (plugin do Vite e testes); o navegador nunca importa.
 *
 *   RAIZ_DADOS=<pasta>  os arquivos vêm separados por estado, como o motor grava em motor/saida/:
 *                       <pasta>/<UF>/imoveis_<cod>.csv, direto_<cod>.csv, filtros_<cod>.csv, extras_<cod>.csv,
 *                       mapbiomas_<cod>.csv, certidoes_<cod>.csv e resumo_<UF>.csv. Caminho relativo vale a partir
 *                       da raiz do repositório.
 *   sem a variável      dados/publicos/, se existir: é onde front/scripts/baixar-dados.mjs (predev) põe sozinho o que
 *                       o motor publicou no Release "dados" do GitHub (docs/dados-publicados.md), com o estados.json
 *                       que diz o que há em cada estado.
 *   sem nenhuma das duas  dados/amostra/, tudo numa pasta só, como sempre foi (sem internet, o front abre assim).
 *
 * Com milhares de municípios nada é lido de uma vez: o resumo de cada estado é lido quando pedido (e relido só se o
 * arquivo mudar), os imóveis de um município ficam num cache pequeno, e os pontos do mapa de cada estado são montados
 * uma vez e guardados em disco (front/.cache/), refeitos só quando um CSV ou contorno daquele estado muda.
 *
 * Os CSV saem daqui já limpos (sem coluna pessoal, CPF e CNPJ mascarados), a mesma regra do resto do front.
 */

import crypto from "node:crypto"
import fs from "node:fs"
import path from "node:path"
import { gunzipSync } from "node:zlib"
import type { BaseBusca } from "./dados/busca"
import { normalizarCar, pareceCar } from "./dados/busca"
import { limpar } from "./dados/colunas"
import { complementosDe, juntarComplementos } from "./dados/complementos"
import { escreverCsv, lerCsv, type Linha } from "./dados/csv"
import { baseDoMunicipio, montarFicha, type BaseMunicipio, type FichaJson } from "./dados/ficha"
import { aptidao, COLUNAS_APTIDAO, lerFunil, lerImovel } from "./dados/funil"
import { lerProcessamentoEstados, situacaoProcessamento, type ProcessamentoEstado, type ProcessamentoEstados } from "./dados/processamento-estados"
import { lerProcessamentoPublicado } from "./dados/processamento-publicado"
import type { EstadoDados, Estados, FunilMunicipio, Geo, Imovel } from "./dados/tipos"
import { UFS, ufDoCodigo } from "./formato"
import { LISTA_IBGE, municipiosDoEstado } from "./ibge-municipios"
import { colunaPessoal } from "./privacidade"
import { pontoDentro } from "./rotulos-mapa"

type Feicao = Geo["features"][number]

/** o estados.json publicado com os dados (motor/publicar_dados.py): só o que o front usa */
interface Manifesto {
  versao_publicacao?: number
  escopo?: string
  gerado_em?: string
  estados?: Record<
    string,
    {
      versao_publicacao?: number
      escopo?: string
      municipios?: number
      total_ibge?: number | null
      completo?: boolean
      tabelas?: Record<string, number>
      versao?: string
      atualizado_em?: string
      processamento?: unknown
    }
  >
}

/** Muda quando a montagem dos pontos mudar: o cache antigo deixa de valer sozinho. */
const VERSAO_PONTOS = 3
/** municípios com imóveis guardados na memória ao mesmo tempo (os mais recentes) */
const MUNICIPIOS_NA_MEMORIA = 12

export const CAMPOS_PONTOS = ["lon", "lat", "situacao", "ha", "cod_ibge", "n"] as const
export type LinhaPonto = [number, number, "apta" | "pendencia", number, string, number]
export interface PontosDoEstado {
  uf: string
  campos: typeof CAMPOS_PONTOS
  /** n = quantas fazendas o ponto representa: 1 é a fazenda no lugar dela; mais de 1 é a soma do município, no meio dele */
  pontos: LinhaPonto[]
  /** fazendas aptas no total do estado (soma de n) */
  fazendas: number
  /** aptas que ficaram sem lugar no mapa (falta o contorno do município em front/geo) */
  sem_lugar: number
}

export interface OpcoesPasta {
  /** raiz do repositório */
  repo: string
  /** valor de RAIZ_DADOS (null ou vazio: a amostra) */
  raizDados?: string | null
  /** pasta das geometrias geradas por front/scripts/geo.py (padrão: front/geo) */
  geo?: string
  /** pasta do cache em disco (padrão: front/.cache/raiz-dados) */
  cache?: string
  avisar?: (mensagem: string) => void
}

/** onde o baixar-dados.mjs grava, relativo à raiz do repositório */
export const PASTA_BAIXADA = "dados/publicos"

/**
 * A pasta de dados que o front usa: RAIZ_DADOS (ambiente ou .env); sem ela, dados/publicos/ se já tiver algum estado
 * baixado; sem nada, null (a amostra).
 */
export function pastaPadrao(repo: string, env: Record<string, string | undefined> = process.env): string | null {
  const pedida = lerRaizDados(repo, env)
  if (pedida) return pedida
  const baixada = path.join(repo, PASTA_BAIXADA)
  if (!fs.existsSync(baixada)) return null
  return PASTA_BAIXADA
}

/**
 * RAIZ_DADOS do ambiente ou, se não estiver lá, do .env da raiz do repositório (o mesmo do motor) ou de front/.env.
 * Só esta variável é lida dos arquivos: o resto do .env fica onde está.
 */
export function lerRaizDados(repo: string, env: Record<string, string | undefined> = process.env): string | null {
  if (env.RAIZ_DADOS !== undefined) return env.RAIZ_DADOS.trim() || null
  for (const arq of [path.join(repo, ".env"), path.join(repo, "front", ".env")]) {
    if (!fs.existsSync(arq)) continue
    for (const linha of fs.readFileSync(arq, "utf8").split(/\r?\n/)) {
      const m = /^\s*(?:export\s+)?RAIZ_DADOS\s*=\s*(.*?)\s*$/.exec(linha)
      if (m) return m[1].replace(/^(['"])(.*)\1$/, "$2").trim() || null
    }
  }
  return null
}

const ehUf = (s: string) => /^[A-Z]{2}$/.test(s) && s in UFS

/** De que estado é o arquivo: resumo_PA.csv é do Pará; imoveis_1507300.csv também (15 é o código do Pará). */
export function ufDoArquivo(nome: string): string | null {
  const r = /^resumo_([A-Z]{2})\.csv$/.exec(nome)
  if (r) return ehUf(r[1]) ? r[1] : null
  const m = /_(\d{7})\.csv$/.exec(nome)
  return m ? ufDoCodigo(m[1]) : null
}

/** só nomes simples de arquivo: nada de ../ */
export const nomeSeguro = (nome: string) => /^[\w.-]+$/.test(nome) && !nome.startsWith(".")

export type PastaDados = ReturnType<typeof abrirPasta>

export function abrirPasta(opcoes: OpcoesPasta) {
  const avisar = opcoes.avisar ?? ((m: string) => console.warn("raiz-dados: " + m))
  const amostra = path.join(opcoes.repo, "dados", "amostra")
  const pedida = opcoes.raizDados?.trim() ? path.resolve(opcoes.repo, opcoes.raizDados.trim()) : null
  let modo: "amostra" | "estados" = "amostra"
  let dir = amostra
  // RAIZ_DADOS=dados/amostra força a amostra (os testes de tela usam assim, para os números não mudarem)
  if (pedida && pedida !== amostra) {
    if (fs.existsSync(pedida) && fs.statSync(pedida).isDirectory()) {
      modo = "estados"
      dir = pedida
    } else {
      modo = "estados"
      dir = pedida
      avisar(`RAIZ_DADOS aponta para uma pasta que não existe (${opcoes.raizDados}); nenhum dado será servido`)
    }
  }
  const geo = opcoes.geo ?? path.join(opcoes.repo, "front", "geo")
  const raizCache = opcoes.cache ?? path.join(opcoes.repo, "front", ".cache", "raiz-dados")
  // um cache por pasta de dados: trocar de RAIZ_DADOS não apaga o da outra
  const cache = path.join(raizCache, modo === "amostra" ? "amostra" : "dados-" + hash(dir).slice(0, 10))

  // ---- arquivos -------------------------------------------------------------------------------------------------

  /** lista de uma pasta, relida só quando a pasta muda (arquivo novo ou apagado) */
  const listagens = new Map<string, { mtime: number; nomes: string[] }>()
  function listar(d: string): string[] {
    if (!fs.existsSync(d)) return []
    const mtime = fs.statSync(d).mtimeMs
    const ja = listagens.get(d)
    if (ja && ja.mtime === mtime) return ja.nomes
    const nomes = fs
      .readdirSync(d, { withFileTypes: true })
      .filter((e) => e.isFile() && e.name.endsWith(".csv"))
      .map((e) => e.name)
      .sort()
    listagens.set(d, { mtime, nomes })
    return nomes
  }

  const pastaDoEstado = (uf: string) => (modo === "amostra" ? amostra : path.join(dir, uf))

  /** os estados que têm algum CSV */
  function ufs(): string[] {
    if (modo === "amostra")
      return [...new Set(listar(amostra).map(ufDoArquivo).filter((u): u is string => !!u))].sort()
    if (!fs.existsSync(dir)) return []
    return fs
      .readdirSync(dir, { withFileTypes: true })
      .filter((e) => e.isDirectory() && ehUf(e.name) && listar(path.join(dir, e.name)).length > 0)
      .map((e) => e.name)
      .sort()
  }

  const publicoBasico = (uf: string) => lerManifesto()?.estados?.[uf]?.escopo === "publico_basico"
  const arquivoBasico = (nome: string) => /^(imoveis_basicos_\d{7}|resumo_[A-Z]{2})\.csv$/.test(nome)

  /** os CSV de um estado (na amostra, os da pasta única que são daquele estado) */
  function arquivos(uf: string): string[] {
    if (!ehUf(uf)) return []
    return listar(pastaDoEstado(uf)).filter((f) => ufDoArquivo(f) === uf && (!publicoBasico(uf) || arquivoBasico(f)))
  }

  /** caminho de um CSV pelo nome (o estado sai do próprio nome), ou null */
  function caminho(nome: string): string | null {
    if (!nomeSeguro(nome)) return null
    const uf = ufDoArquivo(nome)
    if (!uf || (publicoBasico(uf) && !arquivoBasico(nome))) return null
    const arq = path.join(pastaDoEstado(uf), nome)
    return fs.existsSync(arq) ? arq : null
  }

  /** CSV lido e guardado enquanto o arquivo não muda (para os pequenos: resumo e índice) */
  const lidos = new Map<string, { mtime: number; linhas: Linha[] }>()
  function lerArquivo(nome: string, guardar = true, colunas?: string[]): Linha[] | null {
    const arq = caminho(nome)
    if (!arq) return null
    const mtime = fs.statSync(arq).mtimeMs
    const ja = lidos.get(arq)
    if (ja && ja.mtime === mtime) return ja.linhas
    const linhas = lerCsv(fs.readFileSync(arq, "utf8"), { colunas }).linhas
    if (guardar) lidos.set(arq, { mtime, linhas })
    return linhas
  }

  /** o CSV como vai para o navegador: sem coluna pessoal e com CPF e CNPJ mascarados */
  function csvLimpo(nome: string): string | null {
    const arq = caminho(nome)
    if (!arq) return null
    const { colunas, linhas } = lerCsv(fs.readFileSync(arq, "utf8"))
    return escreverCsv(
      colunas.filter((c) => !colunaPessoal(c)),
      linhas.map((l) => limpar(l).linha),
    )
  }

  // ---- municípios -----------------------------------------------------------------------------------------------

  const resumo = (uf: string): FunilMunicipio[] =>
    (lerArquivo(`resumo_${uf}.csv`) ?? []).filter((l) => l.cod_ibge).map((l) => lerFunil(l, uf))

  function comImoveis(uf: string): string[] {
    return [...new Set(arquivos(uf)
      .map((f) => /^imoveis_(?:basicos_)?(\d{7})\.csv$/.exec(f)?.[1])
      .filter((c): c is string => !!c))].sort()
  }

  /** A publicação básica prevalece sobre uma cópia antiga com dados detalhados. */
  function nomeImoveis(cod: string): string | null {
    const basico = `imoveis_basicos_${cod}.csv`
    const completo = `imoveis_${cod}.csv`
    return caminho(basico) ? basico : caminho(completo) ? completo : null
  }

  const municipios = (): FunilMunicipio[] => ufs().flatMap(resumo)

  function arquivoGeo(cod: string): string {
    const comprimido = path.join(geo, `imoveis_${cod}.geojson.gz`)
    return fs.existsSync(comprimido) ? comprimido : path.join(geo, `imoveis_${cod}.geojson`)
  }

  function lerGeo(cod: string): Geo | null {
    const arq = arquivoGeo(cod)
    if (!fs.existsSync(arq)) return null
    const bytes = fs.readFileSync(arq)
    return JSON.parse((arq.endsWith(".gz") ? gunzipSync(bytes) : bytes).toString("utf8")) as Geo
  }

  /** A publicação por CAR exige o manifesto novo; nunca é inferida dos CSV privados legados. */
  function publicacaoBasica(uf?: string): boolean {
    const m = lerManifesto()
    if (m?.escopo !== "publico_basico" || m.versao_publicacao !== 1) return false
    return uf ? m.estados?.[uf]?.escopo === "publico_basico" && m.estados[uf].versao_publicacao === 1 : true
  }
  const COLUNAS_BASICAS = ["cod_imovel", "cod_ibge", "municipio", "uf", "situacao_basica"]
  function comBasicos(uf: string): string[] {
    return publicacaoBasica(uf) ? arquivos(uf).flatMap((f) => /^imoveis_basicos_(\d{7})\.csv$/.exec(f)?.[1] ?? []) : []
  }
  const memoriaBasicos = new Map<string, { mtime: number; linhas: Linha[] }>()
  function basicos(cod: string): Linha[] {
    const uf = ufDoCodigo(cod)
    if (!uf || !publicacaoBasica(uf)) return []
    const arq = caminho(`imoveis_basicos_${cod}.csv`)
    if (!arq) return []
    const mtime = fs.statSync(arq).mtimeMs
    const ja = memoriaBasicos.get(cod)
    if (ja?.mtime === mtime) return ja.linhas
    const { colunas, linhas } = lerCsv(fs.readFileSync(arq, "utf8"))
    if (colunas.join() !== COLUNAS_BASICAS.join()) throw new Error(`imoveis_basicos_${cod}: colunas fora do contrato público`)
    const vistos = new Set<string>()
    for (const l of linhas) {
      if (!/^[A-Z]{2}-\d{7}-[A-F0-9]{32}$/.test(l.cod_imovel) || l.cod_ibge !== cod || l.uf !== uf ||
          !["apto", "com_pendencia", "nao_apto"].includes(l.situacao_basica) || vistos.has(l.cod_imovel))
        throw new Error(`imoveis_basicos_${cod}: identificação ou situação fora do contrato público`)
      vistos.add(l.cod_imovel)
    }
    const projetadas = linhas.map((l) => Object.fromEntries(COLUNAS_BASICAS.map((c) => [c, l[c]])))
    memoriaBasicos.set(cod, { mtime, linhas: projetadas })
    while (memoriaBasicos.size > MUNICIPIOS_NA_MEMORIA) memoriaBasicos.delete(memoriaBasicos.keys().next().value!)
    return projetadas
  }
  function csvBasico(nome: string): string | null {
    const m = /^imoveis_basicos_(\d{7})\.csv$/.exec(nome)
    if (!m || !caminho(nome) || !publicacaoBasica(ufDoCodigo(m[1]) ?? "")) return null
    return escreverCsv(COLUNAS_BASICAS, basicos(m[1]))
  }
  const indicesBasicos = new Map<string, { assinatura: string; dado: Record<string, string> }>()
  function foraBasicos(uf: string): Record<string, string> {
    const cods = comBasicos(uf)
    const marca = cods.map((cod) => { const st = fs.statSync(caminho(`imoveis_basicos_${cod}.csv`)!); return `${cod}:${st.size}:${st.mtimeMs}` }).join(";")
    const ja = indicesBasicos.get(uf)
    if (ja?.assinatura === marca) return ja.dado
    const dado = Object.fromEntries(cods.flatMap((cod) => basicos(cod).filter((l) => l.cod_imovel.slice(3, 10) !== cod).map((l) => [l.cod_imovel, cod])))
    indicesBasicos.set(uf, { assinatura: marca, dado })
    return dado
  }
  function geoBasico(cod: string): Geo | null {
    const uf = ufDoCodigo(cod)
    if (!uf || !comBasicos(uf).includes(cod)) return null
    const original = lerGeo(cod)
    if (!original) return null
    const permitidos = new Set(basicos(cod).map((l) => l.cod_imovel))
    const coordenadasValidas = (x: unknown): boolean => Array.isArray(x) && x.length > 0 && x.every((v) => typeof v === "number" ? Number.isFinite(v) : coordenadasValidas(v))
    return {
      type: "FeatureCollection",
      features: original.features.flatMap((f) => {
        const car = String(f.properties?.cod_imovel ?? "")
        const g = f.geometry
        if (!permitidos.has(car) || !g || !["Polygon", "MultiPolygon"].includes(g.type) || !coordenadasValidas(g.coordinates)) return []
        return [{ type: "Feature" as const, properties: { cod_imovel: car, ...(typeof f.properties.sobreposto === "boolean" ? { sobreposto: f.properties.sobreposto } : {}) }, geometry: { type: g.type, coordinates: g.coordinates } }]
      }),
    }
  }

  /** imóveis de um município, com os arquivos que o completam; os mais recentes ficam na memória */
  const memoria = new Map<string, { mtime: number; imoveis: Imovel[]; base: BaseMunicipio; geo: Map<string, Feicao> }>()
  function quantidadeImoveis(cod: string): number {
    const nome = nomeImoveis(cod)
    return nome ? (lerArquivo(nome, false, ["cod_imovel"]) ?? []).filter((l) => l.cod_imovel).length : 0
  }

  function municipio(cod: string) {
    const nome = nomeImoveis(cod)
    // O pacote básico não permite reconstruir hectares, matrícula, créditos ou uma ficha individual.
    if (!nome || nome.startsWith("imoveis_basicos_")) return null
    const arq = caminho(nome)
    if (!arq) return null
    const mtime = fs.statSync(arq).mtimeMs
    const ja = memoria.get(cod)
    if (ja && ja.mtime === mtime) {
      memoria.delete(cod)
      memoria.set(cod, ja)
      return ja
    }
    const uf = ufDoCodigo(cod)!
    const nomes = complementosDe(arquivos(uf), cod)
    const { porImovel, avisos } = juntarComplementos(nomes.map((arquivo) => ({ arquivo, linhas: lerArquivo(arquivo, false) ?? [] })))
    if (avisos.length) avisar("arquivos que não entraram: " + avisos.join("; "))
    const imoveis = (lerArquivo(`imoveis_${cod}.csv`, false) ?? [])
      .filter((l) => l.cod_imovel)
      .map((l) => lerImovel(l, porImovel.get(l.cod_imovel)))
    const feicoes = new Map<string, Feicao>()
    for (const f of lerGeo(cod)?.features ?? []) feicoes.set(String(f.properties.cod_imovel), f)
    const item = { mtime, imoveis, base: baseDoMunicipio(imoveis), geo: feicoes }
    memoria.set(cod, item)
    while (memoria.size > MUNICIPIOS_NA_MEMORIA) memoria.delete(memoria.keys().next().value!)
    return item
  }

  /**
   * Em que arquivos de município procurar um código do CAR (inteiro ou o começo, com os 7 números do município): o
   * do próprio código e, para a fazenda que o motor pôs em outro município (0,6% no Pará: o código do CAR traz um
   * município e o polígono cai no vizinho), o que o índice do estado diz.
   */
  async function municipiosDoCar(car: string): Promise<string[]> {
    const m = /^([A-Z]{2})-(\d{7})/.exec(car)
    if (!m) return []
    const uf = ufDoCodigo(m[2]) ?? m[1]
    const cods = new Set([m[2]])
    for (const [c, mun] of Object.entries(await foraDoMunicipio(uf))) if (c.startsWith(car)) cods.add(mun)
    const comLista = new Set(comImoveis(uf))
    return [...cods].filter((c) => comLista.has(c))
  }

  /** a ficha de uma fazenda, procurada pelo código do CAR */
  async function ficha(cod_imovel: string): Promise<FichaJson | null> {
    for (const cod of await municipiosDoCar(cod_imovel)) {
      const m = municipio(cod)
      const alvo = m?.imoveis.find((i) => i.cod_imovel === cod_imovel)
      if (m && alvo) return montarFicha(alvo, m.imoveis, m.geo.get(cod_imovel), m.base)
    }
    return null
  }

  /** o que a busca precisa: todos os municípios, e imóveis só de onde o código do CAR digitado pode estar */
  async function baseBusca(q: string): Promise<BaseBusca> {
    const lista = municipios()
    const comLista = new Set(ufs().flatMap(comImoveis))
    const car = pareceCar(q) ? normalizarCar(q) : null
    const cods = car ? await municipiosDoCar(car) : []
    const imoveis = cods.flatMap((c) => municipio(c)?.imoveis ?? [])
    return { municipios: lista, imoveis, comImoveis: comLista }
  }

  // ---- estados --------------------------------------------------------------------------------------------------

  /** o estados.json que veio com os dados (o baixar-dados.mjs grava; o motor monta em publicar_dados.py) */
  let manifesto: { mtime: number; dado: Manifesto | null } | null = null
  function lerManifesto(): Manifesto | null {
    const arq = path.join(dir, "estados.json")
    if (!fs.existsSync(arq)) return null
    const mtime = fs.statSync(arq).mtimeMs
    if (manifesto?.mtime === mtime) return manifesto.dado
    let dado: Manifesto | null = null
    try {
      dado = JSON.parse(fs.readFileSync(arq, "utf8")) as Manifesto
    } catch {
      avisar("estados.json da pasta de dados não abriu; contando os arquivos")
    }
    manifesto = { mtime, dado }
    return dado
  }

  /** Telemetria agregada publicada; cobertura de CSV e jobs não substituem uma observação válida. */
  function processamento(agora = Date.now()): ProcessamentoEstados {
    const publicado = lerManifesto()
    const publico = publicado?.versao_publicacao === 1 && publicado.escopo === "publico_basico"
    const estados = Object.keys(UFS).sort().map((uf): ProcessamentoEstado => {
      const entrada = publico ? publicado.estados?.[uf] : undefined
      const estado = entrada?.versao_publicacao === 1 && entrada.escopo === "publico_basico"
        ? lerProcessamentoPublicado(entrada.processamento, uf) : null
      if (estado) return { ...estado, situacao: situacaoProcessamento(estado, agora) }
      return {
        uf, escopo: "indisponivel", unidade: null, municipios_total: null,
        municipios: { prontos: null, em_execucao: null, com_erro: null, pendentes: null, desconhecidos: null },
        observado_em: null, ultima_mudanca_em: null, valido_ate: null, situacao: "sem_telemetria",
      }
    })
    return lerProcessamentoEstados({ versao: 1, gerado_em: new Date(agora).toISOString(), estados })
  }

  /**
   * Quais estados têm dado, quantos municípios cada um tem e se está completo. Com o estados.json baixado, os números
   * vêm dele (não reconta); sem ele, ou para estado que não está nele, conta os arquivos e compara com a lista do IBGE.
   */
  function estados(): Estados {
    const comDado = new Set(ufs())
    const publicado = lerManifesto()
    const lista: EstadoDados[] = Object.keys(UFS)
      .sort((a, b) => UFS[a].localeCompare(UFS[b], "pt-BR"))
      .map((uf): EstadoDados => {
        const ibge = municipiosDoEstado(uf)
        const doIbge = new Set(ibge)
        const comLista = comDado.has(uf) ? comImoveis(uf) : []
        const base = { uf, cod: ibge[0]?.slice(0, 2) ?? "", nome: UFS[uf], com_lista: comLista.filter((c) => doIbge.has(c)) }
        const m = comDado.has(uf) ? publicado?.estados?.[uf] : undefined
        if (m && typeof m.municipios === "number") {
          const total = m.total_ibge ?? ibge.length
          const situacao = m.completo ? "completo" : m.municipios > 0 ? "incompleto" : "sem_dados"
          return {
            ...base,
            municipios_ibge: total,
            municipios: m.municipios,
            situacao,
            completo: situacao === "completo",
            fora_da_lista: comLista.filter((c) => !doIbge.has(c)),
            tabelas: m.tabelas,
            versao: m.versao,
            atualizado_em: m.atualizado_em,
          }
        }
        const lidos = new Set(comDado.has(uf) ? [...resumo(uf).map((x) => x.cod_ibge), ...comLista] : [])
        const dentro = ibge.filter((c) => lidos.has(c)).length
        const situacao = !lidos.size ? "sem_dados" : dentro === ibge.length ? "completo" : "incompleto"
        return {
          ...base,
          municipios_ibge: ibge.length,
          municipios: dentro,
          situacao,
          completo: situacao === "completo",
          fora_da_lista: [...lidos].filter((c) => !doIbge.has(c)).sort(),
        }
      })
    for (const e of lista)
      if (e.fora_da_lista.length)
        avisar(`${e.nome}: ${e.fora_da_lista.length} código(s) de município fora da lista do IBGE (${e.fora_da_lista.slice(0, 5).join(", ")})`)
    return {
      pasta: modo === "amostra" ? "amostra" : publicado ? "publicada" : "RAIZ_DADOS",
      lista_ibge: LISTA_IBGE,
      ...(publicado?.gerado_em ? { gerado_em: publicado.gerado_em } : {}),
      estados: lista,
    }
  }

  // ---- pontos do mapa, por estado, com cache em disco -------------------------------------------------------------

  /** o meio de cada município (dentro dele), do contorno do Brasil gerado por geo.py; relido se o arquivo mudar */
  let centros: { mtime: number; porCod: Map<string, [number, number]> } | null = null
  function centroDosMunicipios(): Map<string, [number, number]> {
    const arq = path.join(geo, "brasil_municipios.geojson")
    if (!fs.existsSync(arq)) return new Map()
    const mtime = fs.statSync(arq).mtimeMs
    if (centros?.mtime === mtime) return centros.porCod
    const porCod = new Map<string, [number, number]>()
    for (const f of (JSON.parse(fs.readFileSync(arq, "utf8")) as Geo).features) {
      const p = pontoDentro(f.geometry)
      if (p) porCod.set(String(f.properties.cod_ibge), [arredondar(p[0]), arredondar(p[1])])
    }
    centros = { mtime, porCod }
    return porCod
  }

  /** o que entra na conta dos pontos de um estado: se qualquer um mudar (nome, tamanho ou data), refaz */
  function fontesDosPontos(uf: string): string[] {
    const lista = [path.join(dir, "estados.json"), path.join(pastaDoEstado(uf), `resumo_${uf}.csv`), path.join(geo, "brasil_municipios.geojson")]
    for (const cod of comImoveis(uf)) {
      const nome = nomeImoveis(cod)
      if (nome) lista.push(path.join(pastaDoEstado(uf), nome), arquivoGeo(cod))
    }
    return lista
  }

  function assinatura(uf: string): string {
    const partes = [`versao ${VERSAO_PONTOS}`, `uf ${uf}`]
    for (const arq of fontesDosPontos(uf)) {
      const st = fs.existsSync(arq) ? fs.statSync(arq) : null
      partes.push(`${path.basename(arq)} ${st ? `${st.size} ${Math.round(st.mtimeMs)}` : "-"}`)
    }
    return hash(partes.join("\n")).slice(0, 16)
  }

  /** quantas vezes os pontos foram montados de verdade (o teste confere que o cache segura) */
  let montagens = 0

  /** deixa o servidor responder outros pedidos entre um município e outro (o Pará tem 345 mil imóveis) */
  const respirar = () => new Promise<void>((r) => setImmediate(r))

  async function montarPontos(uf: string): Promise<{ pontos: PontosDoEstado; fora: Record<string, string> }> {
    montagens++
    const centro = centroDosMunicipios()
    const pontos: LinhaPonto[] = []
    // fazenda cujo código do CAR diz um município e que está no arquivo de outro: código → município do arquivo
    const fora: Record<string, string> = {}
    let semLugar = 0
    const somar = (cod: string, situacao: "apta" | "pendencia", n: number, ha: number) => {
      if (n <= 0) return
      const c = centro.get(cod)
      if (c) pontos.push([c[0], c[1], situacao, Math.round(ha), cod, n])
      else semLugar += n
    }
    const lista = comImoveis(uf)
    const completos = new Set<string>()
    for (const cod of lista) {
      const nome = nomeImoveis(cod)!
      if (nome.startsWith("imoveis_basicos_")) {
        // Guarda somente o índice interno; as métricas vêm do resumo, sem inferir valores ausentes.
        for (const l of lerArquivo(nome, false, ["cod_imovel"]) ?? [])
          if (l.cod_imovel && l.cod_imovel.slice(3, 10) !== cod) fora[l.cod_imovel] = cod
        await respirar()
        continue
      }
      completos.add(cod)
      // só imoveis_<cod>.csv: apta e matrícula saem das colunas dele, como no resumo do motor
      const feicoes = new Map<string, [number, number]>()
      for (const f of lerGeo(cod)?.features ?? []) {
        const c = centroDoCar(f)
        if (c) feicoes.set(String(f.properties.cod_imovel), c)
      }
      const soma = { apta: [0, 0], pendencia: [0, 0] }
      // só as colunas que decidem a aptidão, pela mesma conta do funil (aptidao, em dados/funil.ts)
      for (const l of lerArquivo(`imoveis_${cod}.csv`, false, COLUNAS_APTIDAO) ?? []) {
        if (!l.cod_imovel) continue
        if (l.cod_imovel.slice(3, 10) !== cod) fora[l.cod_imovel] = cod
        const i = aptidao(l)
        if (!i.apta) continue
        const s = i.com_matricula ? "apta" : "pendencia"
        const c = feicoes.get(l.cod_imovel)
        if (c) pontos.push([c[0], c[1], s, Math.round(i.carbono_ha), cod, 1])
        else {
          soma[s][0]++
          soma[s][1] += i.carbono_ha
        }
      }
      await respirar()
      // fazenda sem contorno em front/geo: conta no meio do município, para o número do estado continuar certo
      somar(cod, "apta", soma.apta[0], soma.apta[1])
      somar(cod, "pendencia", soma.pendencia[0], soma.pendencia[1])
    }
    // Sem tabela detalhada, inclusive no Release básico: preserva os agregados publicados do município.
    for (const m of resumo(uf)) {
      if (completos.has(m.cod_ibge)) continue
      somar(m.cod_ibge, "apta", m.aptas_com_matricula, m.ha_carbono_matricula)
      somar(m.cod_ibge, "pendencia", m.aptas_carbono - m.aptas_com_matricula, m.ha_carbono - m.ha_carbono_matricula)
    }
    return {
      pontos: {
        uf,
        campos: CAMPOS_PONTOS,
        pontos,
        fazendas: pontos.reduce((s, p) => s + p[5], 0) + semLugar,
        sem_lugar: semLugar,
      },
      fora,
    }
  }

  /** montagens em andamento: dois pedidos do mesmo estado esperam a mesma */
  const emAndamento = new Map<string, Promise<string>>()

  /** os pontos do estado como texto JSON, do cache em disco quando nada mudou */
  async function pontosTexto(uf: string): Promise<string | null> {
    if (!ehUf(uf) || !arquivos(uf).length) return null
    const marca = assinatura(uf)
    const arq = path.join(cache, `pontos_${uf}.${marca}.json`)
    if (fs.existsSync(arq)) return fs.readFileSync(arq, "utf8")
    let pedido = emAndamento.get(arq)
    if (!pedido) {
      pedido = montarPontos(uf)
        .then(({ pontos: p, fora }) => {
          const texto = JSON.stringify(p)
          fs.mkdirSync(cache, { recursive: true })
          // o índice dos códigos fora do município vai antes: quem acha os pontos acha o índice
          gravar(path.join(cache, `car_${uf}.${marca}.json`), JSON.stringify(fora))
          gravar(arq, texto)
          // a versão antiga do mesmo estado sai
          for (const f of fs.readdirSync(cache))
            if ((f.startsWith(`pontos_${uf}.`) || f.startsWith(`car_${uf}.`)) && !f.includes(`.${marca}.`))
              fs.rmSync(path.join(cache, f), { force: true })
          return texto
        })
        .finally(() => emAndamento.delete(arq))
      emAndamento.set(arq, pedido)
    }
    return pedido
  }

  /** códigos do CAR do estado que estão no arquivo de outro município (montado junto com os pontos) */
  const indicesFora = new Map<string, Record<string, string>>()
  async function foraDoMunicipio(uf: string): Promise<Record<string, string>> {
    if (!ehUf(uf) || !arquivos(uf).length) return {}
    await pontosTexto(uf)
    const arq = path.join(cache, `car_${uf}.${assinatura(uf)}.json`)
    let indice = indicesFora.get(arq)
    if (!indice) {
      indice = fs.existsSync(arq) ? (JSON.parse(fs.readFileSync(arq, "utf8")) as Record<string, string>) : {}
      indicesFora.clear()
      indicesFora.set(arq, indice)
    }
    return indice
  }

  const pontos = async (uf: string): Promise<PontosDoEstado | null> => {
    const t = await pontosTexto(uf)
    return t ? (JSON.parse(t) as PontosDoEstado) : null
  }

  /** A publicação aberta soma por município e situação; nunca devolve a coordenada da fazenda. */
  async function pontosPublicos(uf: string): Promise<(Omit<PontosDoEstado, "fazendas" | "sem_lugar"> & {
    fazendas: number | null; sem_lugar: number | null; suprimidos: boolean
  }) | null> {
    const centro = centroDosMunicipios()
    let originais: PontosDoEstado | null
    if (publicacaoBasica(uf)) {
      const agregados: LinhaPonto[] = []
      let semLugar = 0, total = 0
      for (const m of resumo(uf)) {
        const c = centro.get(m.cod_ibge)
        for (const [situacao, n, ha] of [["apta", m.aptas_com_matricula, m.ha_carbono_matricula], ["pendencia", m.aptas_carbono - m.aptas_com_matricula, m.ha_carbono - m.ha_carbono_matricula]] as const) {
          if (n <= 0) continue
          total += n
          if (c) agregados.push([c[0], c[1], situacao, Math.max(0, ha), m.cod_ibge, n])
          else semLugar += n
        }
      }
      originais = { uf, campos: CAMPOS_PONTOS, pontos: agregados, fazendas: total, sem_lugar: semLugar }
    } else originais = await pontos(uf)
    if (!originais) return null
    const grupos = new Map<string, LinhaPonto>()
    let semLugar = originais.sem_lugar
    for (const [, , situacao, ha, cod, n] of originais.pontos) {
      const c = centro.get(cod)
      if (!c) {
        semLugar += n
        continue
      }
      const chave = `${cod}:${situacao}`
      const grupo = grupos.get(chave) ?? [c[0], c[1], situacao, 0, cod, 0]
      grupo[3] += ha
      grupo[5] += n
      grupos.set(chave, grupo)
    }
    const publicos = [...grupos.values()].filter((p) => p[5] >= 5)
    const suprimidos = publicos.length < grupos.size || (originais.fazendas > 0 && originais.fazendas < 5) || (semLugar > 0 && semLugar < 5)
    return {
      ...originais, pontos: publicos, suprimidos,
      // Sem totais auxiliares quando permitiriam recuperar a contagem protegida por subtração.
      fazendas: suprimidos ? null : originais.fazendas,
      sem_lugar: suprimidos ? null : semLugar,
    }
  }

  /** monta, em segundo plano, os pontos de todo estado que ainda não está no cache; diz quais montou e em quanto tempo */
  async function aquecer(aviso: (uf: string, segundos: number) => void = () => {}) {
    for (const uf of ufs()) {
      const antes = montagens
      const t0 = Date.now()
      await pontosTexto(uf)
      if (montagens > antes) aviso(uf, (Date.now() - t0) / 1000)
    }
  }

  return {
    modo,
    /** a pasta lida (para mensagens no terminal; não vai para o navegador) */
    dir,
    cache,
    ufs,
    arquivos,
    caminho,
    csvLimpo,
    resumo,
    municipios,
    comImoveis,
    quantidadeImoveis,
    municipio,
    ficha,
    baseBusca,
    estados,
    processamento,
    pontos,
    pontosTexto,
    pontosPublicos,
    publicacaoBasica,
    comBasicos,
    basicos,
    csvBasico,
    foraBasicos,
    geoBasico,
    foraDoMunicipio,
    aquecer,
    montagens: () => montagens,
  }
}

function gravar(arq: string, texto: string) {
  const temp = `${arq}.${process.pid}.tmp`
  fs.writeFileSync(temp, texto)
  fs.renameSync(temp, arq)
}

function hash(s: string): string {
  return crypto.createHash("sha1").update(s).digest("hex")
}

const arredondar = (v: number) => Math.round(v * 1e4) / 1e4

/** o meio do maior anel do polígono do CAR (bom o bastante para agrupar no mapa) */
function centroDoCar(f: Feicao): [number, number] | null {
  // Polygon, MultiPolygon ou GeometryCollection (sobra do conserto de polígono): os anéis externos que houver
  const aneisDe = (g: { type: string; coordinates?: unknown; geometries?: unknown[] }): number[][][] =>
    g.type === "Polygon"
      ? [(g.coordinates as number[][][])[0]]
      : g.type === "MultiPolygon"
        ? (g.coordinates as number[][][][]).map((p) => p[0])
        : g.type === "GeometryCollection"
          ? ((g.geometries ?? []) as { type: string; coordinates?: unknown }[]).flatMap(aneisDe)
          : []
  const anel = aneisDe(f.geometry as never).sort((a, b) => b.length - a.length)[0]
  if (!anel?.length) return null
  let x = 0
  let y = 0
  for (const [a, b] of anel) {
    x += a
    y += b
  }
  return [arredondar(x / anel.length), arredondar(y / anel.length)]
}
