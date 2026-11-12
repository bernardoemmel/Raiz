/**
 * Fonte da amostra: lê os CSV do motor em dados/amostra/ e as geometrias geradas por front/scripts/geo.py em
 * front/geo/. O plugin do Vite (compartilhado/vite-dados.ts) serve as duas pastas em /amostra/ e /geo/ e lista os
 * arquivos em /amostra/indice.json, então um arquivo novo do motor (imoveis_1507300.csv, extras_..., uma coluna
 * nova) aparece na tela sem mudar código.
 */

import { n0, texto } from "./colunas"
import { lerCsv, type Linha } from "./csv"
import { buscarJson, buscarTexto, memo, type Certidao, type FonteDeDados } from "./fonte"
import { lerFicha, type FichaJson } from "./ficha"
import { funilDosImoveis, lerFunil, lerImovel } from "./funil"
import type { CamadaGeo, FunilMunicipio, Geo, Imovel } from "./tipos"

/** arquivos por município que completam imoveis_<mun>.csv, todos pela coluna cod_imovel */
const COMPLEMENTOS = ["filtros", "extras", "direto", "mapbiomas"]

interface IndiceGeo {
  municipios: Record<string, Partial<Record<CamadaGeo | "base", { arquivo: string; bytes: number }>>>
}

export function fonteAmostra(base = "/"): FonteDeDados {
  const raiz = base.endsWith("/") ? base : base + "/"
  const urlAmostra = (arq: string) => `${raiz}amostra/${arq}`
  const urlGeo = (arq: string) => `${raiz}geo/${arq}`

  const indice = memo(async () => (await buscarJson<{ arquivos: string[] }>(urlAmostra("indice.json")))?.arquivos ?? [])
  const indiceGeo = memo(async () => (await buscarJson<IndiceGeo>(urlGeo("indice.json")))?.municipios ?? {})

  const csv = memo(async (arq: string) => {
    const t = await buscarTexto(urlAmostra(arq))
    return t === null ? null : lerCsv(t).linhas
  })

  const arquivosDe = async (prefixo: string) =>
    (await indice("")).filter((a) => a.startsWith(prefixo + "_") && a.endsWith(".csv"))

  const municipios = memo(async () => {
    const todos: FunilMunicipio[] = []
    for (const arq of await arquivosDe("resumo")) {
      const uf = arq.slice(7, -4)
      for (const l of (await csv(arq)) ?? []) todos.push(lerFunil(l, uf))
    }
    return todos
  })

  const imoveis = memo(async (cod: string): Promise<Imovel[] | null> => {
    const arqs = await indice("")
    if (!arqs.includes(`imoveis_${cod}.csv`)) return null
    const principais = (await csv(`imoveis_${cod}.csv`)) ?? []
    const porImovel = new Map<string, Linha[]>()
    for (const tipo of COMPLEMENTOS) {
      if (!arqs.includes(`${tipo}_${cod}.csv`)) continue
      for (const l of (await csv(`${tipo}_${cod}.csv`)) ?? []) {
        if (!l.cod_imovel) continue
        const lista = porImovel.get(l.cod_imovel) ?? []
        lista.push(l)
        porImovel.set(l.cod_imovel, lista)
      }
    }
    return principais.filter((l) => l.cod_imovel).map((l) => lerImovel(l, porImovel.get(l.cod_imovel)))
  })

  const municipiosComImoveis = async () =>
    (await arquivosDe("imoveis")).map((a) => a.slice(8, -4)).filter((c) => /^\d{7}$/.test(c))

  return {
    nome: "amostra",
    municipios: () => municipios(""),
    async municipio(cod) {
      const resumo = (await municipios("")).find((m) => m.cod_ibge === cod)
      if (resumo) return resumo
      const lista = await imoveis(cod)
      if (!lista?.length) return null
      return funilDosImoveis(lista, cod, lista[0].municipio, lista[0].uf)
    },
    imoveis,
    async imovel(cod_imovel) {
      for (const cod of await municipiosComImoveis()) {
        const achado = (await imoveis(cod))?.find((i) => i.cod_imovel === cod_imovel)
        if (achado) return achado
      }
      return null
    },
    async ficha(cod_imovel) {
      // o plugin do Vite monta a ficha de uma fazenda só (em produção, arquivos gerados no build)
      const json = await buscarJson<FichaJson>(urlAmostra(`fichas/${encodeURIComponent(cod_imovel)}.json`))
      return json ? lerFicha(json) : null
    },
    async certidoes(cod_imovel) {
      const saida: Certidao[] = []
      for (const arq of await arquivosDe("certidoes")) {
        for (const l of (await csv(arq)) ?? []) {
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
    municipiosComImoveis,
    geo: {
      async camada(cod, camada) {
        const item = (await indiceGeo(""))[cod]?.[camada]
        return item ? buscarJson<Geo>(urlGeo(item.arquivo)) : null
      },
      async base(cod) {
        const item = (await indiceGeo(""))[cod]?.base
        return item ? new URL(urlGeo(item.arquivo), location.href).href : null
      },
    },
  }
}
