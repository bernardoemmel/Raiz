/** Ponto único de entrada da camada de dados: as telas importam daqui e não sabem de onde vêm os números. */

import type { FonteDeDados } from "./fonte"
import { fonteAmostra } from "./fonte-amostra"
import { fonteApi } from "./fonte-api"

export type { FonteDeDados, Certidao } from "./fonte"
export type { Ficha, ContextoMunicipio } from "./ficha"
export type { RespostaBusca, ImovelAchado, MunicipioAchado, SituacaoBusca } from "./busca"
export type { Categoria, FunilMunicipio, Geo, Imovel, CamadaGeo } from "./tipos"
export { CATEGORIAS } from "./funil"

interface Ambiente {
  VITE_RAIZ_API?: string
  VITE_RAIZ_API_TOKEN?: string
  BASE_URL?: string
}

/** Com VITE_RAIZ_API definida, usa a API do back-end; sem ela, a amostra do motor. */
export function escolherFonte(env: Ambiente): FonteDeDados {
  if (env.VITE_RAIZ_API) return fonteApi(env.VITE_RAIZ_API, env.VITE_RAIZ_API_TOKEN)
  return fonteAmostra(env.BASE_URL ?? "/")
}
