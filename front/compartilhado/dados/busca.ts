/**
 * Busca por código do CAR ou por município: GET /busca?q=
 *
 * A mesma função responde no plugin do Vite (amostra), no build estático (sem servidor) e serve de especificação
 * para o back-end. Ela entende o código do CAR como o SICAR mostra (PA-1507300-F293.CD17.B5FE...), com ou sem os
 * pontos, inteiro ou só o começo, e diz por que não achou: estado ainda não processado, município sem imóveis
 * processados ou código que não existe nos dados.
 */

import type { ImovelBasico } from "./basico"
import { normalizar, UFS } from "../formato"
import type { Categoria, FunilMunicipio, Imovel } from "./tipos"

export type SituacaoBusca =
  | "ok"
  | "curta"
  | "formato_invalido"
  | "estado_nao_processado"
  | "municipio_sem_imoveis"
  | "nao_encontrado"

export interface ImovelAchado {
  cod_imovel: string
  municipio: string
  cod_ibge: string
  uf: string
  ha: number
  carbono_ha: number
  apta: boolean
  categoria: Categoria
}

export interface MunicipioAchado {
  cod_ibge: string
  municipio: string
  uf: string
  imoveis: number | null
  /** a lista por fazenda já foi processada */
  tem_imoveis: boolean
}

export interface RespostaBusca {
  q: string
  tipo: "car" | "texto"
  situacao: SituacaoBusca
  /** frase pronta para a tela quando a situação não é "ok" */
  mensagem: string | null
  imoveis: (ImovelAchado | ImovelBasico)[]
  municipios: MunicipioAchado[]
}

export interface BaseBusca {
  municipios: FunilMunicipio[]
  /** imóveis de todos os municípios com lista por fazenda */
  imoveis: Imovel[]
  basicos?: ImovelBasico[]
  /** municípios com lista por fazenda */
  comImoveis: Set<string>
}

const MAX_IMOVEIS = 8
const MAX_MUNICIPIOS = 8

/** "pa 1507300 f293.cd17" → "PA-1507300-F293CD17": tira pontos e espaços e põe os hífens no lugar. */
export function normalizarCar(q: string): string | null {
  const s = q.toUpperCase().replace(/[\s.]/g, "")
  const m = /^([A-Z]{2})-?(\d{0,7})(?:-?([0-9A-F]{0,32}))?$/.exec(s)
  if (!m) return null
  const [, uf, mun, hash = ""] = m
  if (!mun) return uf + "-"
  if (mun.length < 7) return `${uf}-${mun}`
  return `${uf}-${mun}-${hash}`
}

/** Parece código do CAR? Duas letras e um número logo depois (com ou sem hífen). */
export const pareceCar = (q: string) => /^[A-Za-z]{2}\s*-?\s*\d/.test(q.trim())

const achado = (i: Imovel): ImovelAchado => ({
  cod_imovel: i.cod_imovel,
  municipio: i.municipio,
  cod_ibge: i.cod_ibge,
  uf: i.uf,
  ha: i.ha,
  carbono_ha: i.carbono_ha,
  apta: i.apta,
  categoria: i.categoria,
})

const munAchado = (m: FunilMunicipio, base: BaseBusca): MunicipioAchado => ({
  cod_ibge: m.cod_ibge,
  municipio: m.municipio,
  uf: m.uf,
  imoveis: m.imoveis,
  tem_imoveis: base.comImoveis.has(m.cod_ibge),
})

export function buscar(qBruta: string, base: BaseBusca): RespostaBusca {
  const q = qBruta.trim()
  const vazia = (tipo: RespostaBusca["tipo"], situacao: SituacaoBusca, mensagem: string): RespostaBusca => ({
    q,
    tipo,
    situacao,
    mensagem,
    imoveis: [],
    municipios: [],
  })
  const ufsProcessadas = [...new Set(base.municipios.map((m) => m.uf))].sort()
  const nomesUfs = ufsProcessadas.map((u) => UFS[u] ?? u).join(", ") || "nenhum"

  if (pareceCar(q)) {
    const cod = normalizarCar(q)
    const uf = q.trim().slice(0, 2).toUpperCase()
    if (!UFS[uf])
      return vazia("car", "formato_invalido", `"${uf}" não é sigla de estado. O código do CAR começa assim: PA-1507300-…`)
    if (!cod)
      return vazia(
        "car",
        "formato_invalido",
        "Código do CAR fora do formato. Ele tem a sigla do estado, os 7 números do município e 32 letras e números, por exemplo PA-1507300-F293CD17…",
      )
    const naoProcessado = () => vazia("car", "estado_nao_processado", `${UFS[uf]} ainda não foi processado pela Raíz. Por enquanto: ${nomesUfs}.`)
    if (cod.length < 10) return ufsProcessadas.includes(uf) ? vazia("car", "curta", "Continue digitando: depois da sigla vêm os 7 números do município.") : naoProcessado()
    const completo = cod.length === 43
    // Um CAR pode atravessar mais de um recorte. A busca abre a ficha pelo CAR, uma única vez.
    const unicos = new Map<string, ImovelBasico>()
    for (const i of base.basicos ?? []) {
      if ((completo ? i.cod_imovel === cod : i.cod_imovel.startsWith(cod)) && !unicos.has(i.cod_imovel)) unicos.set(i.cod_imovel, i)
    }
    const basicos = [...unicos.values()]
    if (basicos.length) return { q, tipo: "car", situacao: "ok", mensagem: null, imoveis: basicos.sort((a, b) => a.cod_imovel.localeCompare(b.cod_imovel)).slice(0, MAX_IMOVEIS), municipios: [] }
    const lista = completo
      ? base.imoveis.filter((i) => i.cod_imovel === cod)
      : base.imoveis.filter((i) => i.cod_imovel.startsWith(cod))
    if (lista.length) {
      lista.sort((a, b) => b.carbono_ha - a.carbono_ha)
      return { q, tipo: "car", situacao: "ok", mensagem: null, imoveis: lista.slice(0, MAX_IMOVEIS).map(achado), municipios: [] }
    }
    if (!ufsProcessadas.includes(uf)) return naoProcessado()
    // não achou: diz o porquê pelo município do código
    const codMun = cod.slice(3, 10)
    const mun = base.municipios.find((m) => m.cod_ibge === codMun)
    if (mun && !base.comImoveis.has(codMun))
      return {
        ...vazia(
          "car",
          "municipio_sem_imoveis",
          `${mun.municipio} (${mun.uf}) já tem o funil do município, mas os imóveis por fazenda ainda não foram processados. Este código aparece quando forem.`,
        ),
        municipios: [munAchado(mun, base)],
      }
    if (!mun)
      return vazia(
        "car",
        "nao_encontrado",
        `Nenhum município de ${UFS[uf]} com o código ${codMun} nos dados da Raíz. Confira os 7 números depois da sigla.`,
      )
    return vazia(
      "car",
      "nao_encontrado",
      completo
        ? `Nenhum imóvel com este código em ${mun.municipio}. Pode ser CAR cancelado, de assentamento coletivo ou terra indígena (a Raíz só analisa imóvel rural), ou um erro de digitação.`
        : `Nenhum código de ${mun.municipio} começa assim. Confira as letras e números depois do município.`,
    )
  }

  const t = normalizar(q)
  if (t.length < 3) return vazia("texto", "curta", "Digite pelo menos 3 letras do município ou o começo do código do CAR.")
  const porCodigo = /^\d{7}$/.test(t) ? base.municipios.filter((m) => m.cod_ibge === t) : []
  const porNome = base.municipios
    .filter((m) => normalizar(m.municipio).includes(t))
    .sort(
      (a, b) =>
        Number(!normalizar(a.municipio).startsWith(t)) - Number(!normalizar(b.municipio).startsWith(t)) ||
        b.imoveis - a.imoveis,
    )
  const municipios = [...porCodigo, ...porNome].slice(0, MAX_MUNICIPIOS).map((m) => munAchado(m, base))
  if (!municipios.length)
    return vazia(
      "texto",
      "nao_encontrado",
      `Nenhum município com "${q}" nos estados processados (${nomesUfs}). Para um imóvel, digite o código do CAR.`,
    )
  return { q, tipo: "texto", situacao: "ok", mensagem: null, imoveis: [], municipios }
}
