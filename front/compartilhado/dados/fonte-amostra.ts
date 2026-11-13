/**
 * Fonte estática: agregados e situação básica do pacote público mínimo. Acesso completo nunca é reconstruído
 * de arquivos abertos. As listas e os contornos são lidos por município; camadas pagas usam a API de prospecção.
 */

import { lerPotencialMapa } from "./potencial"
import { lerAgregadosMapa, lerAgregadosMapaUrl } from "./agregados"
import { lerBasico } from "./basico"
import { n0, texto } from "./colunas"
import { buscar, normalizarCar, pareceCar } from "./busca"
import { complementosDe, juntarComplementos } from "./complementos"
import { lerCsv } from "./csv"
import { buscarJson, buscarTexto, buscarTextoGz, lerPontos, memo, type Certidao, type FonteDeDados } from "./fonte"
import { baseDoMunicipio, lerFicha, montarFicha, type FichaJson } from "./ficha"
import { funilDosImoveis, lerFunil, lerImovel } from "./funil"
import { ufDoCodigo } from "../formato"
import type { CamadaGeo, Estados, FunilMunicipio, Geo, Imovel } from "./tipos"
import type { CoberturaMapa } from "./cobertura-mapa"

interface IndiceGeo {
  cobertura?: CoberturaMapa
  potencial?: Record<string, { arquivo: string; bytes: number }>
  agregados?: { arquivo: string; bytes: number; sha256?: string; bytes_total?: number; metadados?: unknown; normal?: { arquivo: string; bytes: number; sha256: string } } | null
  brasil?: Partial<Record<"municipios" | "estados" | "base", { arquivo: string; bytes: number }>>
  municipios: Record<string, Partial<Record<CamadaGeo | "base", { arquivo: string; bytes: number }>>>
}


export function fonteAmostra(base = "/"): FonteDeDados {
  const raiz = base.endsWith("/") ? base : base + "/"
  const urlAmostra = (arq: string) => `${raiz}amostra/${arq}`
  const urlGeo = (arq: string) => `${raiz}geo/${arq}`

  const estados = memo(async (): Promise<Estados> => (await buscarJson<Estados>(urlAmostra("estados.json"))) ?? { pasta: "amostra", lista_ibge: "", estados: [] })
  const indice = memo(async (uf: string) => (await buscarJson<{ arquivos: string[] }>(urlAmostra(`indice_${uf}.json`)))?.arquivos ?? [])
  const indiceCompleto = memo(async () => (await buscarJson<IndiceGeo>(urlGeo("indice.json"))) ?? { municipios: {} })
  const indiceFichas = memo(async () => new Set((await buscarJson<{ codigos: string[] }>(urlAmostra("fichas/indice.json")))?.codigos ?? []))
  const indiceGeo = async (_: string) => (await indiceCompleto("")).municipios
  const pontos = memo(async (uf: string) => {
    const estado = (await estados("")).estados.find((e) => e.uf === uf)
    if (!estado || estado.situacao === "sem_dados") return []
    return lerPontos(await buscarJson(urlAmostra(`pontos_${uf}.json`)))
  })

  // o site estático guarda os CSV comprimidos (.csv.gz); o servidor de desenvolvimento serve os dois
  const csv = memo(async (arq: string) => {
    const t = (await buscarTextoGz(urlAmostra(`${arq}.gz`))) ?? (await buscarTexto(urlAmostra(arq)))
    return t === null ? null : lerCsv(t).linhas
  })

  /** só os estados com algum município processado; o resumo de cada um num pedido */
  const municipios = memo(async () => {
    const comDado = (await estados("")).estados.filter((e) => e.situacao !== "sem_dados")
    const listas = await Promise.all(
      comDado.map(async (e) => ((await indice(e.uf)).includes(`resumo_${e.uf}.csv`) ? ((await csv(`resumo_${e.uf}.csv`)) ?? []) : [])),
    )
    const todos: FunilMunicipio[] = []
    comDado.forEach((e, k) => {
      for (const l of listas[k]) if (l.cod_ibge) todos.push(lerFunil(l, e.uf))
    })
    return todos
  })

  const basicos = memo(async (cod: string) => {
    if ((await estados("")).acesso !== "publico_basico") return null
    const uf = ufDoCodigo(cod)
    const estado = (await estados("")).estados.find((e) => e.uf === uf)
    if (!uf || !estado?.com_lista.includes(cod) || !(await indice(uf)).includes(`imoveis_basicos_${cod}.csv`)) return null
    return ((await csv(`imoveis_basicos_${cod}.csv`)) ?? []).flatMap((linha) => {
      const basico = lerBasico(linha)
      return basico && basico.cod_ibge === cod && basico.uf === uf ? [basico] : []
    })
  })

  const imoveis = memo(async (cod: string): Promise<Imovel[] | null> => {
    if ((await estados("")).acesso) return null
    const uf = ufDoCodigo(cod)
    if (!uf) return null
    const arqs = await indice(uf)
    if (!arqs.includes(`imoveis_${cod}.csv`)) return null
    const nomes = complementosDe(arqs, cod)
    const [principais, ...tabelas] = await Promise.all([csv(`imoveis_${cod}.csv`), ...nomes.map((a) => csv(a))])
    const { porImovel, avisos } = juntarComplementos(nomes.map((arquivo, n) => ({ arquivo, linhas: tabelas[n] ?? [] })))
    if (avisos.length) console.warn("Raíz, arquivos que não entraram:", avisos.join("; "))
    return (principais ?? []).filter((l) => l.cod_imovel).map((l) => lerImovel(l, porImovel.get(l.cod_imovel)))
  })

  async function camadaGeo(cod: string, camada: CamadaGeo): Promise<Geo | null> {
    const item = (await indiceGeo(""))[cod]?.[camada]
    if (!item) return null
    if (item.arquivo.endsWith(".gz")) {
      const texto = await buscarTextoGz(urlGeo(item.arquivo))
      return texto ? JSON.parse(texto) as Geo : null
    }
    return buscarJson<Geo>(urlGeo(item.arquivo))
  }

  const geoNacional = memo(async (arquivo: string) => buscarJson<Geo>(urlGeo(arquivo)))
  const agregadosNacionais = memo(async () => {
    const item = (await indiceCompleto("")).agregados
    if (!item || item.arquivo !== "agregados_brasil.geojson.gz") return null
    const direto = typeof location === "undefined" ? null : lerAgregadosMapaUrl(item, raiz, location.origin,
      typeof document === "undefined" ? location.href ?? location.origin : document.baseURI)
    if (direto) return direto
    const texto = await buscarTextoGz(urlGeo(item.arquivo))
    return texto ? lerAgregadosMapa(JSON.parse(texto)) : null
  })

  const municipiosComImoveis = async () => (await estados("")).estados.flatMap((e) => e.com_lista)

  // códigos do CAR que o motor pôs no arquivo de outro município (o plugin monta junto com os pontos do estado)
  const fora = memo(async (uf: string) => (await buscarJson<Record<string, string>>(urlAmostra(`car_${uf}.json`))) ?? {})

  /** onde procurar um código do CAR (inteiro ou o começo com os 7 números): o município do código e as exceções */
  async function municipiosDoCar(car: string): Promise<string[]> {
    if ((await estados("")).acesso === "agregado") return []
    const m = /^([A-Z]{2})-(\d{7})/.exec(car)
    const uf = m ? ufDoCodigo(m[2]) : null
    if (!m || !uf) return []
    const comLista = new Set((await estados("")).estados.find((e) => e.uf === uf)?.com_lista ?? [])
    // Estados sem dados não têm car_<UF>.json publicado; não tente uma URL que o Pages devolveria como 404.
    if (!comLista.size) return []
    const cods = new Set([m[2]])
    for (const [c, mun] of Object.entries(await fora(uf))) if (c.startsWith(car)) cods.add(mun)
    return [...cods].filter((c) => comLista.has(c))
  }

  return {
    nome: "amostra",
    // a amostra não tem foto de satélite (ela sai do back-end)
    imagem: async () => null,
    municipios: () => municipios(""),
    async municipio(cod) {
      const resumo = (await municipios("")).find((m) => m.cod_ibge === cod)
      if (resumo) return resumo
      const lista = await imoveis(cod)
      if (!lista?.length) return null
      return funilDosImoveis(lista, cod, lista[0].municipio, lista[0].uf)
    },
    imoveis,
    basicos,
    async imovel(cod_imovel) {
      for (const cod of await municipiosDoCar(cod_imovel)) {
        const achado = (await imoveis(cod))?.find((i) => i.cod_imovel === cod_imovel)
        if (achado) return achado
      }
      return null
    },
    async ficha(cod_imovel) {
      if ((await estados("")).acesso) return null
      // o plugin do Vite monta a ficha de uma fazenda só; no site estático, o build grava as fichas dos municípios com
      // contorno e as outras saem aqui, dos CSV do município (mesma função do plugin e do back-end)
      const prontas = await indiceFichas("")
      if (prontas.has(cod_imovel)) {
        const json = await buscarJson<FichaJson>(urlAmostra(`fichas/${encodeURIComponent(cod_imovel)}.json`))
        if (json) return lerFicha(json)
      }
      for (const cod of await municipiosDoCar(cod_imovel)) {
        const todos = await imoveis(cod)
        const alvo = todos?.find((i) => i.cod_imovel === cod_imovel)
        if (!todos || !alvo) continue
        const geo = await camadaGeo(cod, "imoveis").catch(() => null)
        const feicao = geo?.features.find((f) => String(f.properties.cod_imovel) === cod_imovel)
        return lerFicha(montarFicha(alvo, todos, feicao, baseDoMunicipio(todos)))
      }
      return null
    },
    async certidoes(cod_imovel) {
      if ((await estados("")).acesso) return []
      const saida: Certidao[] = []
      for (const cod of await municipiosDoCar(cod_imovel)) {
        const uf = ufDoCodigo(cod)
        if (!uf || !(await indice(uf)).includes(`certidoes_${cod}.csv`)) continue
        for (const l of (await csv(`certidoes_${cod}.csv`)) ?? []) {
          if (l.cod_imovel !== cod_imovel) continue
          saida.push({
            cod_imovel,
            registro_cns: texto(l, "registro_cns") ?? "",
            registro_matricula: texto(l, "registro_matricula") ?? "",
            ha_sobre_car: n0(l, "ha_sobre_car") || null,
            parcelas: n0(l, "parcelas") || null,
          })
        }
      }
      return saida
    },
    async buscar(q, sinal) {
      // A fonte estática sempre busca no navegador: Pages não tem a rota /busca.
      // As leituras ficam em cache e podem servir outra consulta; o cancelamento descarta só esta resposta.
      sinal?.throwIfAborted()
      const comImoveis = new Set(await municipiosComImoveis())
      const car = pareceCar(q) ? normalizarCar(q) : null
      const cods = car ? await municipiosDoCar(car) : []
      const lista = (await Promise.all(cods.map((c) => imoveis(c)))).flatMap((l) => l ?? [])
      const cidades = await municipios("")
      sinal?.throwIfAborted()
      const basicosDoCar = (await estados("")).acesso === "publico_basico" ? (await Promise.all(cods.map((c) => basicos(c)))).flatMap((l) => l ?? []) : []
      sinal?.throwIfAborted()
      const resultado = buscar(q, { municipios: cidades, imoveis: lista, basicos: basicosDoCar, comImoveis })
      const suprimidos = new Set(cidades.filter((m) => m.linha.dados_suprimidos === "true").map((m) => m.cod_ibge))
      return { ...resultado, municipios: resultado.municipios.map((m) => ({ ...m, imoveis: suprimidos.has(m.cod_ibge) ? null : m.imoveis })) }
    },
    estados: () => estados(""),
    pontos: (uf) => pontos(uf),
    municipiosComImoveis,
    geo: {
      cobertura: async () => (await indiceCompleto("")).cobertura,
      agregados: () => agregadosNacionais(""),
      potencial: memo(async (uf: string) => {
        if (!/^[A-Z]{2}$/.test(uf)) return null
        const item = (await indiceCompleto("")).potencial?.[uf]
        if (!item || !/^potencial_[A-Z]{2}\.geojson(?:\.gz)?$/.test(item.arquivo)) return null
        const texto = await buscarTextoGz(urlGeo(item.arquivo))
        return texto ? lerPotencialMapa(JSON.parse(texto)) : null
      }),
      async brasil(opcoes) {
        const indice = await indiceCompleto("")
        const b = indice.brasil ?? {}
        const [municipios, estados] = await Promise.all([
          opcoes?.municipios !== false && b.municipios ? geoNacional(b.municipios.arquivo) : null,
          b.estados ? geoNacional(b.estados.arquivo) : null,
        ])
        return { municipios, estados, base: b.base ? new URL(urlGeo(b.base.arquivo), location.href).href : null, cobertura: indice.cobertura }
      },
      async comContorno() {
        return Object.entries(await indiceGeo(""))
          .filter(([, c]) => c.imoveis)
          .map(([cod]) => cod)
      },
      camada: camadaGeo,
      async base(cod) {
        const item = (await indiceGeo(""))[cod]?.base
        return item ? new URL(urlGeo(item.arquivo), location.href).href : null
      },
    },
  }
}
