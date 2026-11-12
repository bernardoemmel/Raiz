/**
 * Arquivos por município que completam imoveis_<mun>.csv: todo <tipo>_<mun>.csv com a coluna cod_imovel e uma linha
 * por imóvel (hoje filtros_, extras_, extras_direto_, direto_ e mapbiomas_; amanhã o que o motor criar). Ficam de
 * fora imoveis_ (a base), certidoes_ (várias linhas por imóvel) e resumo_.
 *
 * Arquivo com cod_imovel repetido não é complemento (juntaria linhas erradas): fica de fora e aparece no aviso.
 */

import type { Linha } from "./csv"

const NAO_COMPLEMENTO = new Set(["imoveis", "certidoes", "resumo", "geo"])

export function complementosDe(arquivos: string[], cod: string): string[] {
  const rx = new RegExp(`^([a-z][a-z0-9_]*)_${cod}\\.csv$`)
  return arquivos
    .filter((a) => {
      const m = rx.exec(a)
      return !!m && !NAO_COMPLEMENTO.has(m[1])
    })
    .sort()
}

export interface Juncao {
  porImovel: Map<string, Linha[]>
  /** arquivos ignorados e por quê */
  avisos: string[]
}

export function juntarComplementos(tabelas: { arquivo: string; linhas: Linha[] }[]): Juncao {
  const porImovel = new Map<string, Linha[]>()
  const avisos: string[] = []
  for (const { arquivo, linhas } of tabelas) {
    if (!linhas.length) continue
    if (!("cod_imovel" in linhas[0])) {
      avisos.push(`${arquivo}: sem a coluna cod_imovel`)
      continue
    }
    const vistos = new Set<string>()
    let repetido = false
    for (const l of linhas) {
      if (vistos.has(l.cod_imovel)) {
        repetido = true
        break
      }
      vistos.add(l.cod_imovel)
    }
    if (repetido) {
      avisos.push(`${arquivo}: cod_imovel repetido, não é uma linha por imóvel`)
      continue
    }
    for (const l of linhas) {
      if (!l.cod_imovel) continue
      const lista = porImovel.get(l.cod_imovel)
      if (lista) lista.push(l)
      else porImovel.set(l.cod_imovel, [l])
    }
  }
  return { porImovel, avisos }
}
