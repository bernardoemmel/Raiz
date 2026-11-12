/**
 * Ficha de uma fazenda em JSON (passo 1 do E9: "a ficha de cada fazenda em JSON, com os campos que o vídeo, o cartão
 * e o texto vão usar"). É o que a ficha leve do produtor baixa: uma fazenda só, sem o CSV do município inteiro.
 *
 * Quem monta: o plugin do Vite (amostra) ou o back-end (GET {api}/imoveis/{cod}/ficha), com a mesma função abaixo.
 */

import { mediana } from "../comparacoes"
import { codificar, decodificar } from "../polyline"
import { comoLinha } from "./colunas"
import type { Linha } from "./csv"
import { lerImovel } from "./funil"
import type { Geo, Imovel } from "./tipos"

export interface ContextoMunicipio {
  cod_ibge: string
  municipio: string
  uf: string
  n_imoveis: number
  /** fração dos imóveis do município com MENOS área apta que esta fazenda (0 a 1) */
  posicao_carbono: number
  mediana_carbono_ha_aptas: number
  mediana_ha: number
}

export interface FichaJson {
  versao: 1
  imovel: Linha
  contexto: ContextoMunicipio
  /** anéis externos do polígono do CAR, em polyline de 6 casas ([lon, lat]) */
  perimetro: string[] | null
  caixa: [number, number, number, number] | null
}

export interface Ficha {
  imovel: Imovel
  contexto: ContextoMunicipio
  aneis: [number, number][][]
  caixa: [number, number, number, number] | null
}

type Feicao = Geo["features"][number]

/** Anéis externos de um Polygon ou MultiPolygon do GeoJSON. */
export function aneisExternos(f: Feicao | undefined): [number, number][][] {
  if (!f) return []
  const g = f.geometry
  if (g.type === "Polygon") return [(g.coordinates as [number, number][][])[0]]
  if (g.type === "MultiPolygon") return (g.coordinates as [number, number][][][]).map((p) => p[0])
  return []
}

export function caixaDe(aneis: [number, number][][]): [number, number, number, number] | null {
  let x0 = Infinity
  let y0 = Infinity
  let x1 = -Infinity
  let y1 = -Infinity
  for (const a of aneis)
    for (const [x, y] of a) {
      x0 = Math.min(x0, x)
      y0 = Math.min(y0, y)
      x1 = Math.max(x1, x)
      y1 = Math.max(y1, y)
    }
  return Number.isFinite(x0) ? [x0, y0, x1, y1] : null
}

export function montarFicha(alvo: Imovel, todos: Imovel[], feicao?: Feicao): FichaJson {
  const aneis = aneisExternos(feicao)
  const carbonos = todos.map((i) => (i.apta ? i.carbono_ha : 0))
  const meu = alvo.apta ? alvo.carbono_ha : 0
  return {
    versao: 1,
    imovel: alvo.linha,
    contexto: {
      cod_ibge: alvo.cod_ibge,
      municipio: alvo.municipio,
      uf: alvo.uf,
      n_imoveis: todos.length,
      posicao_carbono: todos.length ? carbonos.filter((c) => c < meu).length / todos.length : 0,
      mediana_carbono_ha_aptas: mediana(todos.filter((i) => i.apta).map((i) => i.carbono_ha)),
      mediana_ha: mediana(todos.map((i) => i.ha)),
    },
    perimetro: aneis.length ? aneis.map((a) => codificar(a)) : null,
    caixa: caixaDe(aneis),
  }
}

export function lerFicha(json: FichaJson): Ficha {
  return {
    imovel: lerImovel(comoLinha(json.imovel)),
    contexto: json.contexto,
    aneis: (json.perimetro ?? []).map((p) => decodificar(p)),
    caixa: json.caixa,
  }
}
